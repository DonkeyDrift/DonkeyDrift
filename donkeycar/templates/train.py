#!/usr/bin/env python3
"""
Scripts to train a keras model using tensorflow.
Basic usage should feel familiar: train.py --tubs data/ --model models/mypilot.h5

Usage:
    train.py [--tubs=tubs] (--model=<model>)
    [--type=(linear|inferred|tensorrt_linear|tflite_linear)]
    [--comment=<comment>]

Options:
    -h --help              Show this screen.
"""

import os

# Set TensorFlow log level to reduce noise
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '2'

# CRITICAL: Configure GPU memory BEFORE importing ANY libraries that might initialize TF.
# This must be the very first thing that happens.
import tensorflow as tf

def configure_gpu_memory():
    """
    Configure GPU memory limits strictly before any other TF operations.
    This function is self-contained to avoid external dependencies.
    """
    try:
        gpus = tf.config.list_physical_devices('GPU')
        if gpus:
            for gpu in gpus:
                try:
                    tf.config.set_logical_device_configuration(
                        gpu,
                        [tf.config.LogicalDeviceConfiguration(memory_limit=7168)])
                except RuntimeError as e:
                    print(f"ERROR: Failed to set memory limit: {e}")
                    print("Hint: This usually means TensorFlow was already initialized.")
                    return
            print("SUCCESS: GPU memory limit set to 8192MB (8GB)")
        else:
            print("No GPU devices found.")
    except Exception as e:
        print(f"Critical error configuring GPU: {e}")

# Execute configuration immediately
configure_gpu_memory()

# Now import other libraries
from docopt import docopt
from tensorflow.keras import mixed_precision

# 3. Enable mixed precision training
try:
    policy = mixed_precision.Policy('mixed_float16')
    mixed_precision.set_global_policy(policy)
    print('Mixed precision policy set to mixed_float16')
except Exception as e:
    print(f"Error setting mixed precision: {e}")

import donkeycar as dk
from donkeycar.pipeline.training import train


def main():
    args = docopt(__doc__)
    cfg = dk.load_config()
    tubs = args['--tubs']
    model = args['--model']
    model_type = args['--type']
    comment = args['--comment']
    train(cfg, tubs, model, model_type, comment)


if __name__ == "__main__":
    main()
