# """ 
# My CAR CONFIG 

# This file is read by your car application's manage.py script to change the car
# performance

# If desired, all config overrides can be specified here. 
# The update operation will not touch this file.
# """

#STEERING (aka servo)
STEERING_PWM_CHANNEL = 0  # the Arduino pin to which steering is connected
STEERING_LEFT_PWM = -100   # One end of steering 
STEERING_RIGHT_PWM = 100   # Other end of the steering

#THROTTLE (aka ESC)
THROTTLE_PWM_CHANNEL = 1  # the Arduino pin to which throttle is connected
THROTTLE_FORWARD_PWM = 100 # Max forward throttle config
THROTTLE_STOPPED_PWM = 0 # Stopped throttle config 
THROTTLE_REVERSE_PWM = -100 # Max reverse throttle config

# Arduino serial port configuration
ARDUINO_SERIAL_PORT = "/dev/ttyS6"  # Default serial port for Arduino
ARDUINO_BAUDRATE = 115200           # Baud rate for serial communication
ARDUINO_TIMEOUT = 1               # Serial read timeout in seconds
ARDUINO_WRITE_TIMEOUT = 1       # Serial write timeout in seconds

# Thread safety configuration
ARDUINO_LOCK_TIMEOUT = 1.0          # Maximum time to wait for lock in seconds
ARDUINO_MAX_RETRIES = 3             # Maximum number of retries for failed operations

# Debug settings
ARDUINO_DEBUG = False               # Enable debug logging
ARDUINO_VERBOSE = False             # Enable verbose logging

CAMERA_TYPE = "WEBCAM"   # pygame camera backend (SDL/v4l2)
CAMERA_INDEX = 0        # Select /dev/videoX index. Try 0,1 if needed
# BGR2RGB = True           # Convert OpenCV BGR frames to RGB for pipeline

DRIVE_TRAIN_TYPE = "ARDUINO_CONTROLLER"
# DRIVE_TRAIN_TYPE = "PIGPIO_PWM"

DRIVE_LOOP_HZ = 60      # the vehicle loop will pause if faster than this speed.

AI_THROTTLE_MULT = 1.1             # this multiplier will scale every throttle value for all output from NN models
