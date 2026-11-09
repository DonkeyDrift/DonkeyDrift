# -*- coding: utf-8 -*-
"""无 TF 车端 tflite 推理的输入形状回归测试。

main → RealCar-1 引入 TRAINING_IMAGE_SIZE 后，`get_model_by_type` 的无 TF
`tflite_linear` 分支拿它（旧配置缺键 → 默认 160x120）当模型输入形状，而车端
模型实际是 320x240，aidlite 的 set_model_properties 拿到错误形状，推理失效。
这里覆盖两层修复：
  1. read_tflite_input_shape 直接从 .tflite FlatBuffer 读模型声明的形状；
  2. AidLiteTflite.load() 用模型形状覆盖构造时给的配置回退值；
  3. 旧配置（无 TRAINING_IMAGE_SIZE）构造回退值回到相机分辨率 IMAGE_H/W。
"""
import sys
import types

import pytest

from donkeycar.parts.npu_pilot import AidLiteTflite, NpuLinearPilot, \
    read_tflite_input_shape


class _Cfg:
    IMAGE_W = 320
    IMAGE_H = 240
    IMAGE_DEPTH = 3
    DEFAULT_MODEL_TYPE = 'linear'


def _fake_aidlite(record):
    """AidLite[.tflite] 用到的最小门面；记录 set_model_properties 收到的形状。"""

    def set_props(in_shapes, in_dt, out_shapes, out_dt):
        record['in_shapes'] = [list(s) for s in in_shapes]
        record['out_shapes'] = [list(s) for s in out_shapes]

    interpreter = types.SimpleNamespace(
        init=lambda: 0, load_model=lambda: 0, destroy=lambda: None)

    return types.SimpleNamespace(
        Model=types.SimpleNamespace(
            create_instance=lambda _p: types.SimpleNamespace(
                set_model_properties=set_props)),
        Config=types.SimpleNamespace(create_instance=lambda: types.SimpleNamespace()),
        InterpreterBuilder=types.SimpleNamespace(
            build_interpreter_from_model_and_config=lambda _m, _c: interpreter),
        FrameworkType=types.SimpleNamespace(TYPE_TFLITE='tflite', TYPE_QNN240='qnn240'),
        AccelerateType=types.SimpleNamespace(TYPE_CPU='cpu', TYPE_DSP='dsp'),
        DataType=types.SimpleNamespace(TYPE_FLOAT32='f32'),
    )


@pytest.fixture(scope='module')
def tflite_320(tmp_path_factory):
    """320x240x3 的 KerasLinear → tflite（与车端真实模型尺寸一致）。"""
    pytest.importorskip('tensorflow')
    from donkeycar.parts.interpreter import keras_to_tflite
    from donkeycar.parts.keras import KerasInterpreter, KerasLinear

    path = tmp_path_factory.mktemp('tflite_shape') / 'm320.tflite'
    interpreter = KerasInterpreter()
    KerasLinear(interpreter=interpreter, input_shape=(240, 320, 3))
    keras_to_tflite(interpreter.model, str(path))
    return str(path)


def test_read_input_shape_matches_tf(tflite_320):
    import tensorflow as tf

    expected = tf.lite.Interpreter(model_path=tflite_320) \
        .get_input_details()[0]['shape'].tolist()
    assert read_tflite_input_shape(tflite_320) == expected == [1, 240, 320, 3]


def test_read_input_shape_invalid_file(tmp_path):
    junk = tmp_path / 'junk.tflite'
    junk.write_bytes(b'not a tflite model')
    assert read_tflite_input_shape(str(junk)) is None
    assert read_tflite_input_shape(str(tmp_path / 'missing.tflite')) is None


def test_tflite_load_overrides_configured_shape(monkeypatch, tflite_320):
    record = {}
    monkeypatch.setitem(sys.modules, 'aidlite', _fake_aidlite(record))
    interp = AidLiteTflite(in_shapes=[[1, 120, 160, 3]],
                           out_shapes=[[1, 1], [1, 1]])
    interp.load(tflite_320)

    assert record['in_shapes'] == [[1, 240, 320, 3]]
    assert interp.get_input_shape('img_in') == (240, 320, 3)


def test_no_tf_legacy_cfg_falls_back_to_camera_size(monkeypatch):
    """旧 mycar 配置没有 TRAINING_IMAGE_SIZE：回退 IMAGE_H/W（main 行为）。"""
    import donkeycar.utils as dk_utils

    monkeypatch.setattr(dk_utils, '_TF_AVAILABLE', False)
    pilot = dk_utils.get_model_by_type('tflite_linear', _Cfg())

    assert isinstance(pilot, NpuLinearPilot)
    assert pilot.interpreter.in_shapes == [[1, 240, 320, 3]]


def test_no_tf_configured_training_size_used_as_fallback(monkeypatch):
    """显式配置 TRAINING_IMAGE_SIZE 时仍按它构造（load() 会以模型形状覆盖）。"""
    import donkeycar.utils as dk_utils

    monkeypatch.setattr(dk_utils, '_TF_AVAILABLE', False)
    cfg = _Cfg()
    cfg.TRAINING_IMAGE_SIZE = '160x120'
    pilot = dk_utils.get_model_by_type('tflite_linear', cfg)

    assert pilot.interpreter.in_shapes == [[1, 120, 160, 3]]
