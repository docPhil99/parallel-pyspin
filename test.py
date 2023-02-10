from llpyspin import primary
from time import sleep
from loguru import logger

# disable logging in the llpyspin if you want
#logger.disable('llpyspin')

nums = [ #21377661,
    21293195,
    21293202,
        21293198,
         21293196,
        #21377663,
          ]
cams =  []


# set up cameras
for ind,num in enumerate(nums):
    print(f'{ind} : {num}')
    try:
        color = 'BGR8'
        if num in [21377663,]:
            color='RGB8'
        cam1 = primary.PrimaryCamera(serial_number=num, color=color)
        cam1.framerate = 15
        #cam1.prime(f'/home/phil/tmp/prime{ind}.mp4', backend='spinnaker')
        cams.append(cam1)
    except:
        logger.exception(f'Cannot start {ind}: {num}')

# set file names
for loop in range(5):
    for ind, cam in enumerate(cams):
        fname = f'/home/phil/tmp/prime{loop}_{ind}.mp4'
        logger.debug(f'New filename: {fname}')
        cam.prime(fname, backend='spinnaker')


    logger.debug('Start tigger')
    for cam in cams:
        cam.trigger()

    logger.debug('Sleeping')
    sleep(5)

    logger.debug('Stopping')
    for cam in cams:
        try:
            cam.stop()
        except:
            logger.exception(f'Failed to stop {ind}')



logger.debug('Release')
for ind, cam in enumerate(cams):
    try:
        cam.release()
    except:
        logger.exception(f'Failed to release {ind}')

logger.debug('stopped')
cams = []
logger.debug('done')


