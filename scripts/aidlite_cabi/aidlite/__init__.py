# -*- coding: utf-8 -*-
"""aidlite（ctypes 门面，用于没有官方 cp3xx 绑定的解释器，如本板 Python 3.12）。

底层是 /home/aidlux/tools/aidlite_cabi/libaidlite_cabi.so —— 官方 aidlite.hpp 的
C-ABI 外壳；本文件把它的 API 映射成与官方 pyaidlite 相同的形状：
  DataType / FrameworkType / AccelerateType / ImplementType / LogLevel
  Model / Config / InterpreterBuilder / Interpreter
仅覆盖 donkeycar 车端 NPU 推理所需的子集（官方绑定的其余成员未实现）。
"""
import ctypes
import os
import sys

import numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))
_LIBPATH = os.path.join(_HERE, "libaidlite_cabi.so")
if not os.path.exists(_LIBPATH):
    _LIBPATH = "/home/aidlux/tools/aidlite_cabi/libaidlite_cabi.so"
_lib = ctypes.CDLL(_LIBPATH, mode=ctypes.RTLD_GLOBAL)

__version__ = "aidlite-cabi-0.1 (ctypes, built from aidlite.hpp)"


# ── 枚举（数值与 aidlite.hpp 完全一致）──────────────────────────────
class DataType:
    TYPE_DEFAULT = 0
    TYPE_UINT8 = 1
    TYPE_INT8 = 2
    TYPE_UINT32 = 3
    TYPE_FLOAT32 = 4
    TYPE_INT32 = 5
    TYPE_INT64 = 6
    TYPE_UINT64 = 7
    TYPE_INT16 = 8
    TYPE_UINT16 = 9
    TYPE_FLOAT16 = 10
    TYPE_BOOL = 11


class FrameworkType:
    TYPE_DEFAULT = 0
    TYPE_SNPE = 1
    TYPE_TFLITE = 2
    TYPE_RKNN = 3
    TYPE_QNN = 4
    TYPE_SNPE2 = 5
    TYPE_NCNN = 6
    TYPE_MNN = 7
    TYPE_TNN = 8
    TYPE_PADDLE = 9
    TYPE_MS = 10
    TYPE_ONNX = 11
    TYPE_QNN216 = 101
    TYPE_SNPE216 = 102
    TYPE_QNN223 = 103
    TYPE_SNPE223 = 104
    TYPE_QNN229 = 105
    TYPE_SNPE229 = 106
    TYPE_QNN231 = 107
    TYPE_QNN236 = 108
    TYPE_QNN240 = 109
    TYPE_QNN248 = 110


class AccelerateType:
    TYPE_DEFAULT = 0
    TYPE_CPU = 1
    TYPE_GPU = 2
    TYPE_DSP = 3
    TYPE_NPU = 4


class ImplementType:
    TYPE_DEFAULT = 0
    TYPE_MMKV = 1
    TYPE_REMOTE = 2
    TYPE_LOCAL = 3


class LogLevel:
    INFO = 0
    WARNING = 1
    ERROR = 2
    FATAL = 3


# ── 原型 ────────────────────────────────────────────────────────────
_u32p = ctypes.POINTER(ctypes.c_uint32)
_lib.al_get_abi_version.restype = ctypes.c_uint64
_lib.al_get_library_version.restype = ctypes.c_char_p
_lib.al_set_log_level.argtypes = [ctypes.c_uint8]
_lib.al_set_log_level.restype = ctypes.c_int32
_lib.al_log_to_stderr.restype = ctypes.c_int32
_lib.al_log_to_file.argtypes = [ctypes.c_char_p, ctypes.c_int]
_lib.al_log_to_file.restype = ctypes.c_int32
_lib.al_last_log_msg.argtypes = [ctypes.c_uint8]
_lib.al_last_log_msg.restype = ctypes.c_char_p

_lib.al_model_create.argtypes = [ctypes.c_char_p]
_lib.al_model_create.restype = ctypes.c_void_p
_lib.al_model_set_properties.argtypes = [ctypes.c_void_p, _u32p, ctypes.c_int32, ctypes.c_int32,
                                         _u32p, ctypes.c_int32, ctypes.c_int32, ctypes.c_uint8]
_lib.al_model_set_properties.restype = ctypes.c_int32
_lib.al_model_delete.argtypes = [ctypes.c_void_p]

_lib.al_config_create.restype = ctypes.c_void_p
for _n in ("al_config_set_framework", "al_config_set_accelerate", "al_config_set_implement"):
    getattr(_lib, _n).argtypes = [ctypes.c_void_p, ctypes.c_uint8]
for _n in ("al_config_set_backend_extension", "al_config_set_performance_profile"):
    getattr(_lib, _n).argtypes = [ctypes.c_void_p, ctypes.c_char_p]
for _n in ("al_config_set_shared_buffer", "al_config_set_quantify_model", "al_config_set_threads"):
    getattr(_lib, _n).argtypes = [ctypes.c_void_p, ctypes.c_int32]
_lib.al_config_get_framework.argtypes = [ctypes.c_void_p]
_lib.al_config_get_framework.restype = ctypes.c_int32
_lib.al_config_get_accelerate.argtypes = [ctypes.c_void_p]
_lib.al_config_get_accelerate.restype = ctypes.c_int32
_lib.al_config_delete.argtypes = [ctypes.c_void_p]

_lib.al_build_interpreter.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
_lib.al_build_interpreter.restype = ctypes.c_void_p
_lib.al_build_interpreter_from_path.argtypes = [ctypes.c_char_p]
_lib.al_build_interpreter_from_path.restype = ctypes.c_void_p

_lib.al_interp_init.argtypes = [ctypes.c_void_p]
_lib.al_interp_init.restype = ctypes.c_int32
_lib.al_interp_load_model.argtypes = [ctypes.c_void_p]
_lib.al_interp_load_model.restype = ctypes.c_int32
_lib.al_interp_set_input.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p]
_lib.al_interp_set_input.restype = ctypes.c_int32
_lib.al_interp_invoke.argtypes = [ctypes.c_void_p]
_lib.al_interp_invoke.restype = ctypes.c_int32
_lib.al_interp_get_output.argtypes = [ctypes.c_void_p, ctypes.c_uint32,
                                      ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_uint32)]
_lib.al_interp_get_output.restype = ctypes.c_int32
_lib.al_interp_input_name_to_index.argtypes = [ctypes.c_void_p, ctypes.c_char_p, _u32p]
_lib.al_interp_input_name_to_index.restype = ctypes.c_int32
_lib.al_interp_output_name_to_index.argtypes = [ctypes.c_void_p, ctypes.c_char_p, _u32p]
_lib.al_interp_output_name_to_index.restype = ctypes.c_int32
_lib.al_interp_output_count.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_int32)]
_lib.al_interp_output_count.restype = ctypes.c_int32
_lib.al_interp_output_name.argtypes = [ctypes.c_void_p, ctypes.c_int32, ctypes.c_char_p, ctypes.c_int32]
_lib.al_interp_output_name.restype = ctypes.c_int32
_lib.al_interp_destroy.argtypes = [ctypes.c_void_p]
_lib.al_interp_destroy.restype = ctypes.c_int32
_lib.al_interp_delete.argtypes = [ctypes.c_void_p]


# ── 模块级函数 ──────────────────────────────────────────────────────
def get_abi_version():
    return int(_lib.al_get_abi_version())


def get_library_version():
    return _lib.al_get_library_version().decode()


def get_py_library_version():
    return __version__


def set_log_level(level):
    return int(_lib.al_set_log_level(int(level)))


def log_to_stderr():
    return int(_lib.al_log_to_stderr())


def log_to_file(path_and_prefix, also_to_stderr=False):
    return int(_lib.al_log_to_file(path_and_prefix.encode(), int(bool(also_to_stderr))))


def last_log_msg(level=LogLevel.INFO):
    p = _lib.al_last_log_msg(int(level))
    return p.decode() if p else ""


# ── 类 ──────────────────────────────────────────────────────────────
class Model(object):
    def __init__(self, ptr):
        self._p = ptr

    @staticmethod
    def create_instance(model_path):
        ptr = _lib.al_model_create(str(model_path).encode() if model_path else b"")
        return Model(ptr) if ptr else None

    def set_model_properties(self, input_shapes, input_data_type, output_shapes, output_data_type):
        ins = [list(s) for s in input_shapes]
        outs = [list(s) for s in output_shapes]
        in_rank = len(ins[0]) if ins else 0
        out_rank = len(outs[0]) if outs else 0
        in_flat = [int(v) for s in ins for v in s]
        out_flat = [int(v) for s in outs for v in s]
        in_arr = (ctypes.c_uint32 * max(1, len(in_flat)))(*in_flat) if in_flat else None
        out_arr = (ctypes.c_uint32 * max(1, len(out_flat)))(*out_flat) if out_flat else None
        rc = _lib.al_model_set_properties(self._p, in_arr, len(ins), in_rank,
                                          out_arr, len(outs), out_rank, int(input_data_type))
        del out_arr
        del in_arr
        return int(rc)

    def __del__(self):
        try:
            if getattr(self, "_p", None):
                _lib.al_model_delete(self._p)
                self._p = None
        except Exception:
            pass


class Config(object):
    def __init__(self):
        self._p = _lib.al_config_create()

    @staticmethod
    def create_instance():
        c = Config()
        return c if c._p else None

    @property
    def framework_type(self):
        return int(_lib.al_config_get_framework(self._p))

    @framework_type.setter
    def framework_type(self, v):
        _lib.al_config_set_framework(self._p, int(v))

    @property
    def accelerate_type(self):
        return int(_lib.al_config_get_accelerate(self._p))

    @accelerate_type.setter
    def accelerate_type(self, v):
        _lib.al_config_set_accelerate(self._p, int(v))

    @property
    def implement_type(self):
        return 0

    @implement_type.setter
    def implement_type(self, v):
        _lib.al_config_set_implement(self._p, int(v))

    @property
    def backend_extension_config(self):
        return ""

    @backend_extension_config.setter
    def backend_extension_config(self, v):
        _lib.al_config_set_backend_extension(self._p, str(v).encode())

    @property
    def qnn_shared_buffer(self):
        return 0

    @qnn_shared_buffer.setter
    def qnn_shared_buffer(self, v):
        _lib.al_config_set_shared_buffer(self._p, int(v))

    @property
    def is_quantify_model(self):
        return 0

    @is_quantify_model.setter
    def is_quantify_model(self, v):
        _lib.al_config_set_quantify_model(self._p, int(v))

    @property
    def number_of_threads(self):
        return 0

    @number_of_threads.setter
    def number_of_threads(self, v):
        _lib.al_config_set_threads(self._p, int(v))

    def __del__(self):
        try:
            if getattr(self, "_p", None):
                _lib.al_config_delete(self._p)
                self._p = None
        except Exception:
            pass


class Interpreter(object):
    def __init__(self, ptr):
        self._p = ptr
        self._last_input = None
        self._output_count = None

    # -- 生命周期 --
    def init(self, *args):
        return int(_lib.al_interp_init(self._p))

    def load_model(self, *args):
        return int(_lib.al_interp_load_model(self._p))

    def destroy(self):
        if getattr(self, "_p", None):
            return int(_lib.al_interp_destroy(self._p))
        return -1

    # -- 推理 --
    def set_input_tensor(self, idx, data, *args):
        arr = np.ascontiguousarray(data, dtype=np.float32)
        self._last_input = arr          # 保持存活，避免 aidlite 侧悬空指针
        return int(_lib.al_interp_set_input(self._p, int(idx), ctypes.c_void_p(arr.ctypes.data)))

    def invoke(self, *args):
        return int(_lib.al_interp_invoke(self._p))

    def get_output_tensor(self, idx, *args):
        data = ctypes.c_void_p()
        length = ctypes.c_uint32(0)
        rc = _lib.al_interp_get_output(self._p, int(idx), ctypes.byref(data), ctypes.byref(length))
        if rc != 0:
            raise RuntimeError("get_output_tensor(%d) 失败 rc=%d" % (int(idx), rc))
        n = int(length.value) // 4          # 输出按 float32 声明
        if n <= 0:
            return np.zeros((0,), dtype=np.float32)
        buf = ctypes.cast(data, ctypes.POINTER(ctypes.c_float))
        return np.copy(np.ctypeslib.as_array(buf, shape=(n,)))

    # -- 张量名 --
    def input_tensor_name_to_index(self, name):
        idx = ctypes.c_uint32(0)
        rc = _lib.al_interp_input_name_to_index(self._p, str(name).encode(), ctypes.byref(idx))
        if rc != 0:
            raise RuntimeError("input_tensor_name_to_index('%s') 失败 rc=%d" % (name, rc))
        return int(idx.value)

    def output_tensor_name_to_index(self, name):
        idx = ctypes.c_uint32(0)
        rc = _lib.al_interp_output_name_to_index(self._p, str(name).encode(), ctypes.byref(idx))
        if rc != 0:
            raise RuntimeError("output_tensor_name_to_index('%s') 失败 rc=%d" % (name, rc))
        return int(idx.value)

    def output_names(self):
        cnt = ctypes.c_int32(0)
        if _lib.al_interp_output_count(self._p, ctypes.byref(cnt)) != 0:
            return []
        out = []
        for i in range(int(cnt.value)):
            b = ctypes.create_string_buffer(256)
            if _lib.al_interp_output_name(self._p, i, b, 256) == 0:
                out.append(b.value.decode())
        return out

    def __del__(self):
        try:
            if getattr(self, "_p", None):
                _lib.al_interp_delete(self._p)
                self._p = None
        except Exception:
            pass


class InterpreterBuilder(object):
    @staticmethod
    def build_interpreter_from_model_and_config(model, config):
        ptr = _lib.al_build_interpreter(model._p if model else None,
                                        config._p if config else None)
        return Interpreter(ptr) if ptr else None

    @staticmethod
    def build_interpreter_from_model(model):
        return InterpreterBuilder.build_interpreter_from_model_and_config(model, None)

    @staticmethod
    def build_interpreter_from_path(model_path):
        ptr = _lib.al_build_interpreter_from_path(str(model_path).encode())
        return Interpreter(ptr) if ptr else None
