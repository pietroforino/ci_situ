from rd03d import RD03D
import time

# Initialize radar with Pi 5 UART settings
radar = RD03D()  # Uses /dev/ttyAMA0 by default

radar.set_multi_mode(True)   # Switch to multi-target mode

while True:
    if radar.update():
        target1 = radar.get_target(1)
        target2 = radar.get_target(2)
        target3 = radar.get_target(3)
        
        print('1 dist:', target1.distance, 'mm Angle:', target1.angle, " deg Speed:", target1.speed, "cm/s X:", target1.x, "mm Y:", target1.y, "mm")
        print('2 dist:', target2.distance, 'mm Angle:', target2.angle, " deg Speed:", target2.speed, "cm/s X:", target2.x, "mm Y:", target2.y, "mm")
        print('3 dist:', target3.distance, 'mm Angle:', target3.angle, " deg Speed:", target3.speed, "cm/s X:", target3.x, "mm Y:", target3.y, "mm \n")
    
    else:
        print('No radar data received.')
    
    time.sleep(0.2)