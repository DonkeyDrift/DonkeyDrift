import shutil
import tempfile
from pytest import approx
import pytest
import os

from donkeycar.parts.interpreter import keras_to_tflite, \
    saved_model_to_tensor_rt, TfLite, TensorRT, has_trt_support
from donkeycar.parts.keras import *
from donkeycar.utils import get_test_img

TOLERANCE = 1e-4


@pytest.fixture
def tmp_dir() -> str:
    tmp_dir = tempfile.mkdtemp()
    yield tmp_dir
    shutil.rmtree(tmp_dir)


test_data = [KerasLinear, KerasCategorical, KerasInferred, KerasLSTM,
             KerasLocalizer, KerasIMU, Keras3D_CNN, KerasMemory,
             KerasBehavioral]


def create_models(keras_pilot, dir):
    # build with keras interpreter
    interpreter = KerasInterpreter()
    km = keras_pilot(interpreter=interpreter)
    # build tflite model from TfLite interpreter
    tflite_model_path = os.path.join(dir, 'model.tflite')
    keras_to_tflite(interpreter.model, tflite_model_path)
    kl = keras_pilot(interpreter=TfLite())
    kl.load(tflite_model_path)
    # save model in savedmodel format
    savedmodel_path = os.path.join(dir, 'model.savedmodel')
    interpreter.model.save(savedmodel_path)
    krt = None
    # load tensorrt only if supported
    if has_trt_support():
        krt = keras_pilot(interpreter=TensorRT())
        krt.load(savedmodel_path)

    return km, kl, krt


def test_keras_interpreter_loads_legacy_json_and_weights(tmp_dir):
    source = KerasLinear()
    json_path = os.path.join(tmp_dir, 'model.json')
    with open(json_path, 'w', encoding='utf-8') as handle:
        handle.write(source.interpreter.model.to_json())
    h5_path = os.path.join(tmp_dir, 'model.weights.h5')
    source.interpreter.model.save_weights(h5_path)
    shutil.copyfile(h5_path, os.path.join(tmp_dir, 'model.weights'))

    loaded = KerasLinear()
    loaded.interpreter.load_json(json_path)
    img = get_test_img(source)

    assert loaded.run(img) == approx(source.run(img), rel=TOLERANCE, abs=TOLERANCE)


@pytest.mark.parametrize('keras_pilot', test_data)
def test_keras_vs_tflite_and_tensorrt(keras_pilot, tmp_dir):
    """ This test cannot run for the 3D CNN model in tflite and the LSTM
        model in """
    k_keras, k_tflite, k_trt = create_models(keras_pilot, tmp_dir)

    # prepare data
    img = get_test_img(k_keras)
    if keras_pilot is KerasIMU:
        # simulate 6 imu data in [0, 1]
        imu = np.random.rand(6).tolist()
        args = (img, imu)
    elif keras_pilot is KerasMemory:
        mem = np.random.rand(2).tolist()
        # steering should be in [-1, 1]
        mem[0] = mem[0] * 2 - 1
        args = (img, mem)
    elif keras_pilot is KerasBehavioral:
        one_hot = [1.0, 0.0] if np.random.rand() < 0.5 else [0.0, 1.0]
        args = (img, one_hot)
    else:
        args = (img, )

    # run all three interpreters and check results are numerically close
    out2 = out3 = None
    out1 = k_keras.run(*args)
    tolerance = 2e-4 if keras_pilot is Keras3D_CNN else TOLERANCE
    if k_tflite:
        out2 = k_tflite.run(*args)
        assert out2 == approx(out1, rel=tolerance, abs=tolerance)
    if k_trt:
        # lstm cells are not yet supported in tensor RT
        out3 = k_trt.run(*args)
        assert out3 == approx(out1, rel=tolerance, abs=tolerance)
    print('keras:', out1, 'tflite:', out2, 'trt:', out3)




