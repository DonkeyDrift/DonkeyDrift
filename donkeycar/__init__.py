import os
import sys
import logging

from ._version import __version__

# TensorFlow >= 2.16 默认自带 Keras 3，但本仓库的训练/推理代码按 Keras 2 语义编写
# （ModelCheckpoint 落盘 SavedModel 目录、旧 .h5 反序列化等）。装了 tf-keras 时把
# tensorflow.keras 指回 Keras 2；必须在任何 tensorflow 导入之前设置才生效。
if 'TF_USE_LEGACY_KERAS' not in os.environ and 'tensorflow' not in sys.modules:
    from importlib.util import find_spec
    if find_spec('tf_keras') is not None:
        os.environ['TF_USE_LEGACY_KERAS'] = '1'

logging.basicConfig(level=os.environ.get('LOGLEVEL', 'INFO').upper())

if sys.version_info.major < 3 or sys.version_info.minor < 10:
    msg = f'Donkey Requires Python 3.10 or greater. You are using {sys.version}'
    raise ValueError(msg)

# The default recursion limits in CPython are too small.
sys.setrecursionlimit(10**5)

from .vehicle import Vehicle
from .memory import Memory
from . import utils
from . import config
from . import contrib
from .config import load_config
