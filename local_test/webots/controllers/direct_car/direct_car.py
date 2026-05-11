"""
Simple direct car controller — minimal behavior for local testing.
It drives forward at a constant speed and performs gentle oscillating steering
so the car moves around the track. Keeps dependencies minimal (uses numpy if
available, but it's optional).
"""
from controller import Robot
import math
import time

robot = Robot()
timestep = int(robot.getBasicTimeStep())

left_motor = robot.getDevice('left_motor')
right_motor = robot.getDevice('right_motor')
left_motor.setPosition(float('inf'))
right_motor.setPosition(float('inf'))
left_motor.setVelocity(0.0)
right_motor.setVelocity(0.0)

# Optional cameras (not used for control here, but kept enabled so supervisor
# can capture images if needed).
try:
    left_cam = robot.getDevice('left_camera')
    right_cam = robot.getDevice('right_camera')
    left_cam.enable(timestep)
    right_cam.enable(timestep)
except Exception:
    left_cam = right_cam = None

start = time.time()
while robot.step(timestep) != -1:
    # gentle oscillation steering based on elapsed time
    t = time.time() - start
    steer = 0.3 * math.sin(t * 0.5)
    base_speed = 4.0
    # differential for simple skid-steer
    v_l = max(-10.0, min(10.0, base_speed + steer))
    v_r = max(-10.0, min(10.0, base_speed - steer))
    left_motor.setVelocity(v_l)
    right_motor.setVelocity(v_r)

