import dill
import types
import queue
import PySpin
import numpy as np
import multiprocessing as mp
from .dummy import DummyCameraPointer
from loguru import logger
# Method for identifying camera devices
GETBY_DUMMY_CAMERA  = 0
GETBY_SERIAL_NUMBER = 1
GETBY_DEVICE_INDEX  = 2

# Shared frame counter (to keep primary and secondary cameras grossly in sync)
SHARED_FRAME_COUNTER = mp.Value('i', 0)

class CameraError(Exception):
    """"""
    def __init__(self, message: str) -> None:
        super().__init__(message)

def queued(f):
    """
    This decorator sends functions through the input queue and retrieves the
    result of the function call from the output queue
    """

    def wrapped(main, **kwargs):
        """
        Keywords
        --------
        main : MainProcess
            An instance of the MainProcess class
        """

        item = (dill.dumps(f), kwargs)
        main._child.iq.put(item)
        result, output, message = main._child.oq.get()
        if result is False:
            raise CameraError(message)
        else:
            return result, output, message

    return wrapped

class ChildProcess(mp.Process):
    """
    """

    def __init__(self, value=0, getby=GETBY_DEVICE_INDEX):
        """
        """

        super().__init__()

        self.value = value
        self.getby = getby

        # IO queues
        self.iq = mp.Queue()
        self.oq = mp.Queue()

        # Shared memory flags
        self.started   = mp.Value('i', 0)
        self.acquiring = mp.Value('i', 0)

        #
        global SHARED_FRAME_COUNTER
        self.shared_frame_counter = SHARED_FRAME_COUNTER

        return

    def start(self) -> None:
        """
        Override the start method
        """

        self.started.value = 1

        super().start()

        return

    def run(self) -> None:
        """
        """

        try:

            # create instances of the system and cameras list
            system = PySpin.System.GetInstance()
            cameras = system.GetCameras()
            pointer = None

            # instantiate the camera
            if self.getby == GETBY_DUMMY_CAMERA:
                pointer = DummyCameraPointer()
            elif self.getby == GETBY_DEVICE_INDEX:
                pointer = cameras.GetByIndex(int(self.value))
            elif self.getby == GETBY_SERIAL_NUMBER:
                pointer = cameras.GetBySerial(str(self.value))

            # emit the result
            self.oq.put(True)

        except PySpin.SpinnakerException:

            # cleanup
            if pointer is not None:
                del pointer

            cameras.Clear()
            system.ReleaseInstance()

            # reset the started flag
            self.started.value = 0

            # emit the result
            self.oq.put(False)

            return

        # main loop
        while self.started.value:

            try:
                # call the function
                dilled, kwargs = self.iq.get(block=False)
                f = dill.loads(dilled)
                result, output, message = f(child=self, pointer=pointer, **kwargs)

                # output
                self.oq.put((result, output, message))

            except queue.Empty:
                continue

        # cleanup and emit signal
        try:
            if pointer.IsInitialized():
                pointer.DeInit()
            del pointer
            cameras.Clear()
            system.ReleaseInstance()
            self.oq.put(True)

        except PySpin.SpinnakerException:
            self.oq.put(False)

        return

class MainProcess():
    """
    """

    def __init__(
        self,
        serial_number : int=None,
        device_index  : int=None,
        nickname      : str=None,
        dummy         : bool=False,
        color         : bool=False
        ):
        """
        """

        # Identify the getby method
        if serial_number is None and device_index is None and dummy is False:
            raise CameraError(f'No identifier provided to constructor')

        elif dummy is True and serial_number is None and device_index is None:
            self._getby = GETBY_DUMMY_CAMERA
            self._device = None

        elif serial_number is not None and device_index is None and dummy is False:
            self._getby = GETBY_SERIAL_NUMBER
            self._device = serial_number

        elif device_index is not None and serial_number is None and dummy is False:
            self._getby = GETBY_DEVICE_INDEX
            self._device = device_index

        else:
            raise CameraError(f'Invalid kwargs combo: serial number={serial_number}, device index={device_index}, dummy={dummy}')

        # parameters (determined during initialization)
        self._framerate = None
        self._exposure  = None
        self._binsize   = None
        self._format    = None
        self._roi       = None
        self._stream_buffer_count = None

        # acquisition lock state
        self._locked = False

        # default class for the child process
        self._child = None

        #
        if nickname is None:
            self._nickname = f'camera[{self.device}]'
        else:
            self._nickname = nickname

        #
        self._color = color

        return

    def _spawn_child_process(self, cls : ChildProcess, **kwargs) -> None:
        """
        Create an instance of the child process and initialize the camera

        keywords
        --------
        cls : ChildProcess
            a child process class or subclass
        """

        # kill the child process if it already exists
        if self._child is not None:
            self._join_child_process()

        # create and start the child process
        self._child = cls(self.device, self.getby)
        self._child.start()
        result = self._child.oq.get()
        if not result:
            self._child.join()
            self._child = None
            raise CameraError('Failed to spawn child process')

        @queued
        def f(child, pointer, **kwargs):
            """
            Initialize the camera pointer object

            Keywords
            --------
            child: MainProcess
                Instance of a MainProcess object
            pointer:
                Instance of a camera pointer object
            color: bool`
                color flag
            """

            try:

                #
                pointer.Init()

                if kwargs['color'] == 'RGB8':
                    col = PySpin.PixelFormat_RGB8
                elif kwargs['color'] == 'BGR8':
                    col = PySpin.PixelFormat_BGR8
                else:
                    col = PySpin.PixelFormat_Mono8

                # target property values
                values = [
                    #PySpin.PixelFormat_RGB8 if kwargs['color'] else PySpin.PixelFormat_Mono8,
                    col,
                    PySpin.AcquisitionMode_Continuous,
                    PySpin.StreamBufferHandlingMode_NewestOnly,
                    PySpin.StreamBufferCountMode_Manual,
                    PySpin.ExposureAuto_Off,
                    False,
                    3000,
                    True,
                    30,
                    2,
                    2
                ]

                # property objects
                properties = [
                    pointer.PixelFormat,
                    pointer.AcquisitionMode,
                    pointer.TLStream.StreamBufferHandlingMode,
                    pointer.TLStream.StreamBufferCountMode,
                    pointer.ExposureAuto,
                    pointer.AcquisitionFrameRateEnable,
                    pointer.ExposureTime,
                    pointer.AcquisitionFrameRateEnable,
                    pointer.AcquisitionFrameRate,
                    pointer.BinningHorizontal,
                    pointer.BinningVertical
                ]

                # property object names
                names = [
                    'PixelFormat',
                    'AcquisitionMode',
                    'StreamBufferHandlingMode',
                    'StreamBufferCountMode',
                    'ExposureAuto',
                    'AcquisitionFrameRateEnable',
                    'ExposureTime',
                    'AcqusitionFrameRateEnable',
                    'AcquisitionFrameRate',
                    'BinningHorizontal',
                    'BinningVertical'
                ]

                #
                for p, v, n in zip(properties, values, names):
                    if p.GetAccessMode() != PySpin.RW:
                        message = f'Property is not readable and/or writeable: {n}'
                        return False, None, message
                    try:
                        p.SetValue(v)
                    except PySpin.SpinnakerException:
                        message = f'Failed to set {n} to {v}'
                        return False, None, message

                #
                roi = (
                    pointer.OffsetX.GetValue(),
                    pointer.OffsetY.GetValue(),
                    pointer.Width.GetValue(),
                    pointer.Height.GetValue(),
                )
                framerate = int(np.ceil(pointer.AcquisitionFrameRate.GetValue()))
                exposure  = int(np.ceil(pointer.ExposureTime.GetValue()))
                binsize   = (
                    pointer.BinningHorizontal.GetValue(),
                    pointer.BinningVertical.GetValue()
                )
                stream_buffer_count = pointer.TLStream.StreamBufferCountManual.GetValue()

                #
                output = {
                    'framerate' : framerate,
                    'exposure'  : exposure,
                    'binsize'   : binsize,
                    'roi'       : roi,
                    'stream_buffer_count': stream_buffer_count
                }

                return True, output, None

            except PySpin.SpinnakerException as e:
                print(e)
                return False, None, 'Failed to initialize camera pointer object'

        # NOTE: It's very important to reference the "_color" attribute and not
        #       invoke the "color" property's getter (see line below)
        logger.debug(f'_colour {self._color}')
        result, output, message = f(main=self, color=self._color)

        self._framerate = output['framerate']
        self._exposure  = output['exposure']
        self._binsize   = output['binsize']
        self._height    = output['roi'][3]
        self._width     = output['roi'][2]
        self._roi       = output['roi']
        self._stream_buffer_count = output['stream_buffer_count']

        return

    def _join_child_process(self, timeout: int=3) -> None:
        """
        """

        if self._child is None:
            raise CameraError('No active child process')

        if self._child.started.value != 1:
            raise CameraError('Child process is inactive')

        @queued
        def f(child, pointer, **kwargs):
            try:
                if pointer.IsStreaming():
                    pointer.EndAcquisition()
                if pointer.IsInitialized():
                    pointer.DeInit()
                return True, None, None
            except PySpin.SpinnakerException:
                return False, None, 'Failed to deinitialize camera pointer object'

        # Send the function through the queue
        result, output, message = f(main=self)

        # Break out of the main loop in the child process
        self._child.started.value = 0
        result = self._child.oq.get()

        # Flush the IO queues
        for q in [self._child.iq, self._child.oq]:
            while q.qsize() != 0:
                discard = q.get()
            q.close()
            q.join_thread()

        # Attempt to join the child process
        self._child.join(timeout)

        # Raise an error if it hangs
        if self._child.is_alive():
            self._child.terminate()
            self._child = None
            raise CameraError('Child process dead-locked during cleanup')

        else:
            self._child = None

        return

    # framerate
    @property
    def framerate(self):
        """
        Camera framerate in frames per second
        """

        if self.locked:
            return self._framerate

        @queued
        def f(child, pointer, **kwargs):
            try:
                output = pointer.AcquisitionFrameRate.GetValue()
                return True, output, None
            except PySpin.SpinnakerException:
                return False, None, 'Failed to query framerate property'

        result, output, message = f(main=self)

        return output

    @framerate.setter
    def framerate(self, value):

        if self.locked:
            raise CameraError(f'Camera is locked during acquisition')

        @queued
        def f(child, pointer, **kwargs):

            # Get the range of possible values for framerate
            value = kwargs['value']
            try:
                if pointer.AcquisitionFrameRateEnable.GetValue() is False:
                    pointer.AcquisitionFrameRateEnable.SetValue(True)
                min = pointer.AcquisitionFrameRate.GetMin()
                max = pointer.AcquisitionFrameRate.GetMax()
            except PySpin.SpinnakerException:
                return False, None, f'Failed to determine the range of possible framerate values'

            # Set framerate to maximum value
            if value == 'max':
                try:
                    max = pointer.AcquisitionFrameRate.GetMax()
                    pointer.AcquisitionFrameRate.SetValue(max)
                    return True, None, None

                except PySpin.SpinnakerException:
                    return False, None, f'Failed to query exposure property'

            # Target framerate is outside the range of possible values
            if not min <= value <= max:
                message = f'Target framerate ({value} fps) falls outside the range of possible values: {min}, {max} fps'
                return False, None, message

            # Target framerate is within th range of possible values
            else:
                try:
                    pointer.AcquisitionFrameRate.SetValue(value)
                    check = int(np.around(pointer.AcquisitionFrameRate.GetValue()))

                    if check != value:
                        message = f'Target framerate ({value:.1f} fps) does not equal new framerate ({check:.1f} fps)'
                        return False, None, message

                    else:
                        return True, None, None

                except PySpin.SpinnakerException:
                    message = f'Failed to set framerate to {value:.1f} fps'
                    return False, None, message

        # call
        result, output, message = f(main=self, value=value)

        # update data
        if result:
            self._framerate = value

        return

    # exposure
    @property
    def exposure(self):
        """
        Camera exposure time in micro seconds
        """

        if self.locked:
            return self._exposure

        @queued
        def f(child, pointer, **kwargs):
            try:
                output = pointer.ExposureTime.GetValue()
                return True, output, None
            except PySpin.SpinnakerException:
                return False, None, f'Failed to query exposure property'

        result, output, message = f(main=self)

        return output

    @exposure.setter
    def exposure(self, value):

        if self.locked:
            raise CameraError(f'Camera is locked during acquisition')

        @queued
        def f(child, pointer, **kwargs):
            value = kwargs['value']
            try:
                min = pointer.ExposureTime.GetMin()
                max = pointer.ExposureTime.GetMax()

                if not min <= value <= max:
                    message = f'Target exposure ({value} us) falls outside the range of possible values: {min:.1f}, {max:.1f} us'
                    return False, None, message

                else:
                    pointer.ExposureTime.SetValue(value)
                    return True, None, None

            except PySpin.SpinnakerException:
                return False, None,  f'Failed to set exposure to {value} us'

        result, output, message = f(self, value=value)
        if result:
            self._exposure = value

        return

    # binsize
    @property
    def binsize(self):

        if self.locked:
            return self._binsize

        @queued
        def f(child, pointer, **kwargs):
            try:
                x = pointer.BinningHorizontal.GetValue()
                y = pointer.BinningVertical.GetValue()
                return True, (x, y), None
            except PySpin.SpinnakerException:
                return False, None, f'Failed to query binsize property'

        result, output, message = f(main=self)

        return output

    @binsize.setter
    def binsize(self, value):

        # check the value of the target binsize

        # it can be a single integer
        if isinstance(value, int):
            if value not in [1, 2, 4]:
                raise CameraError('Binsize must be 1, 2, or 4 pixels')
            value = (value, value)

        # it can be a list or tuple of two integers
        elif (type(value) == list or type(value) == tuple) and len(value) == 2:
            for item in value:
                if item not in [1, 2, 4]:
                    raise CameraError('Binsize must be 1, 2, or 4 pixels')

        # it can't be anything else
        else:
            raise CameraError(f'{value} is not a valid value for binsize')

        @queued
        def f(child, pointer, **kwargs):
            xbin, ybin = kwargs['value']
            try:
                xmin = pointer.BinningHorizontal.GetMin()
                xmax = pointer.BinningHorizontal.GetMax()
                ymin = pointer.BinningVertical.GetMin()
                ymax = pointer.BinningVertical.GetMax()

                if xmin >= xbin >= xmax or ymin >= ybin >= ymax:
                    message = f'Target binsize ({xbin}, {ybin} pixels) falls outside the range of possible values: ({xmin}, {xmax}), ({ymin}, {ymax}) pixels'
                    return False, None, message

                else:
                    pointer.BinningHorizontal.SetValue(xbin)
                    pointer.BinningVertical.SetValue(ybin)

                    # reset offset, height, and width
                    try:
                        pointer.OffsetX.SetValue(0)
                        pointer.OffsetY.SetValue(0)
                        pointer.Height.SetValue(pointer.Height.GetMax())
                        pointer.Width.SetValue(pointer.Width.GetMax())

                    except PySpin.SpinnakerException:
                        return False, None, f'Failed to reset offset, height, and width properties'

                    return True, None, None

            except PySpin.SpinnakerException:
                return False, None, f'Failed to set binsize to {xbin}, {ybin} pixels'

        result, output, message = f(main=self, value=value)
        if result:
            self._binsize = value

        return

    # Number of buffered images
    @property
    def stream_buffer_count(self):

        if self.locked:
            return self._stream_buffer_count

        @queued
        def f(child, pointer, **kwargs):
            try:
                buffer_count_mode = pointer.TLStream.StreamBufferCountMode.GetValue()
                if buffer_count_mode != PySpin.StreamBufferCountMode_Manual:
                    return False, None, 'Stream buffer mode is not set to manual count'
                else:
                    output = pointer.TLStream.StreamBufferCountManual.GetValue()
                    return True, output, None
            except PySpin.SpinnakerException:
                return False, None, 'Failed to query the stream buffer count property'

        result, output, message = f(main=self)

        return output

    @stream_buffer_count.setter
    def stream_buffer_count(self, value):
        if self.locked:
            raise CameraError('Camera is locked during acquisition')

        @queued
        def f(child, pointer, **kwargs):
            value = kwargs['value']
            try:
                max = pointer.TLStream.StreamBufferCountManual.GetMax()
                if value > max:
                    return False, None, f'Stream buffer count of {value} exceed maximum count of {max}'
                else:
                    pointer.TLStream.StreamBufferCountManual.SetValue(value)
                    return True, None, None
            except PySpin.SpinnakerException:
                return False, None, f'Failed to set stream buffer count to {value}'

        result, output, message = f(main=self, value=value)
        self._stream_buffer_count = value

        return

    # roi
    @property
    def roi(self):

        if self.locked:
            return self._roi

        @queued
        def f(child, pointer, **kwargs):
            try:
                output = (
                    pointer.OffsetX.GetValue(),
                    pointer.OffsetY.GetValue(),
                    pointer.Width.GetValue(),
                    pointer.Height.GetValue(),
                )
                return True, output, None
            except PySpin.SpinnakerException:
                return False, None, 'Failed to query the roi property'

        result, output, message = f(main=self)

        return output

    @roi.setter
    def roi(self, value):

        if self.locked:
            raise CameraError('Camera is locked during acquisition')

        if (type(value) != list and type(value) != tuple) or len(value) != 4:
            raise CameraError(f'{value} is not a valid value for the ROI')

        @queued
        def f(child, pointer, **kwargs):
            x, y, w, h = kwargs['value']
            try:
                if (pointer.Width.GetMax() - (x + w) < 0) or (pointer.Height.GetMax() - (y + h) < 0):
                    message = f'ROI ({x}, {y}, {w}, {h} pixels) exceeds boundaries of the image frame'
                    return False, None, message
                else:
                    pointer.OffsetX.SetValue(x)
                    pointer.OffsetY.SetValue(y)
                    pointer.Height.SetValue(h)
                    pointer.Width.SetValue(w)
                    return True, None, None

            except PySpin.SpinnakerException:
                message = f'Failed to set roi to {x}, {y}, {w}, {h} pixels'
                return False, None, message

        result, output, message = f(main=self, value=value)
        if result:
            self._roi = value

        return output

    # color flag
    @property
    def color(self):

        if self.locked:
            return self._color

        @queued
        def f(child, pointer, **kwargs):
            format = pointer.PixelFormat.GetValue()
            if format == PySpin.PixelFormat_RGB8:
                result, output, message = True, 'RGB8', ''
            if format == PySpin.PixelFormat_BGR8:
                result, output, message = True, 'BGR8', ''
            elif format == PySpin.PixelFormat_Mono8:
                result, output, message = True, False, ''
            else:
                result, output, message = False, None, f'Unrecognized pixel format code: {format}'
            return result, output, message

        result, output, message = f(main=self)
        if result:
            return output

    @color.setter
    def color(self, value):
        if self.locked:
            raise CameraError(f'Acquisition lock is engaged')

        if value=='RGB8':
            format = PySpin.PixelFormat_RGB8
        elif value=='BGR8':
            format = PySpin.PixelFormat_BGR8
        else:
            format = PySpin.PixelFormat_Mono8

        @queued
        def f(child, pointer, **kwargs):
            value = kwargs['value']
            try:
                pointer.PixelFormat.SetValue(format)
                result, output, message = (True, None, '')

            except PySpin.SpinnakerException:
                result, output, message = (
                    False,
                    None,
                    f'Failed to set pixel format property'
                )

            return result, output, message

        result, output, message = f(main=self, value=value)
        if result:
            logger.debug(f'Returned colour val {value}')
            self._color = value

    # width (read-only)
    @property
    def width(self):

        if self.locked:
            return self._width

        @queued
        def f(child, pointer, **kwargs):
            try:
                value = pointer.Width.GetValue()
                return True, value, None
            except PySpin.SpinnakerException:
                return False, None, f'Failed to query width property'

        result, output, message = f(main=self)

        return output

    # height (read-only)
    @property
    def height(self):

        if self.locked:
            return self._height

        @queued
        def f(child, pointer, **kwargs):
            try:
                value = pointer.Height.GetValue()
                return True, value, None
            except PySpin.SpinnakerException:
                return False, None, f'Failed to query height property'

        result, output, message = f(main=self)

        return output

    # acquisition lock state
    @property
    def locked(self):
        return self._locked

    # device index or serial number
    @property
    def device(self):
        return self._device

    #
    @property
    def getby(self):
        return self._getby

    # camera nickname
    @property
    def nickname(self):
        return self._nickname

    @nickname.setter
    def nickname(self, value):
        self._nickname = str(value)

    @property
    def opened(self):
        """
        Returns the state of the child process (active or inactive)
        """

        if self._child is not None and self._child.started.value:
            return True
        else:
            return False
