from llpyspin import primary
from time import sleep
from loguru import logger

# disable logging in the llpyspin if you want
#logger.disable('llpyspin')

nums = [ #21377661,
    21293195,
    # 21293202,
        #21377663,
       # 21293198,
         21293196,
          ]
cams =  []

for ind,num in enumerate(nums):
    print(f'{ind} : {num}')
    try:
        cam1 = primary.PrimaryCamera(serial_number=num, color='BGR8')
        cam1.framerate = 15
        cam1.prime(f'/home/phil/tmp/prime{ind}.mp4', backend='spinnaker')
        cams.append(cam1)
    except:
        logger.exception(f'Cannot start {ind}: {num}')

logger.debug('Start tigger')
for cam in cams:
    cam.trigger()

logger.debug('Sleeping')
sleep(5)

logger.debug('Stopping')

for ind, cam in enumerate(cams):
    logger.debug(f'Stopping {ind}')
    try:
        cam.stop()
    except:
        logger.exception(f'Failed to stop {ind}')
    try:
        cam.release()
    except:
        logger.exception(f'Failed to release {ind}')

logger.debug('stopped')
cams =[]
logger.debug('done')


