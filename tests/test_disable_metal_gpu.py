"""disable_metal_gpu_on_macos 助手与本地训练入口守卫的回归测试。

背景（2026-10-23 实测，pilot_1792739150191）：Web UI 本地训练走
donkeycar.management train → pipeline/training.py，该路径此前没有任何
Metal GPU 防护（防护只存在于 createcar 模板 train.py 与远程 sed 补丁），
在本机（TF 2.15.1 + tensorflow-metal 1.2.0）训练塌缩成恒定输出——
train/val loss 钉在预测均值水平、模型对任意输入输出同一值
（上游 keras-team/tf-keras#140）。修复：守卫下沉为
donkeycar.utils.disable_metal_gpu_on_macos，并由 pipeline/training.py
模块级调用，覆盖所有本地 TF 训练入口。
"""

import os
import sys
import types
import unittest
from unittest import mock


def _fake_tf(gpus=('/physical_device:GPU:0',), raise_on_set=False):
    """构造最小可用的假 tensorflow 模块，记录 set_visible_devices 调用。"""
    tf = types.ModuleType('tensorflow')
    calls = []

    class _Config:
        @staticmethod
        def list_physical_devices(kind):
            assert kind == 'GPU'
            return list(gpus)

        @staticmethod
        def set_visible_devices(devices, kind):
            if raise_on_set:
                raise RuntimeError('Visible devices cannot be modified')
            calls.append((devices, kind))

    tf.config = _Config
    tf._calls = calls
    return tf


class TestDisableMetalGpuOnMacos(unittest.TestCase):
    def _run(self, platform, fake_tf):
        from donkeycar.utils import disable_metal_gpu_on_macos
        with mock.patch.object(sys, 'platform', platform), \
                mock.patch.dict(sys.modules, {'tensorflow': fake_tf}):
            return disable_metal_gpu_on_macos()

    def test_non_darwin_is_noop(self):
        fake = _fake_tf()
        self.assertFalse(self._run('linux', fake))
        self.assertEqual(fake._calls, [])

    def test_darwin_with_gpu_hides_metal(self):
        fake = _fake_tf()
        self.assertTrue(self._run('darwin', fake))
        self.assertEqual(fake._calls, [([], 'GPU')])

    def test_darwin_without_gpu_is_noop(self):
        fake = _fake_tf(gpus=[])
        self.assertFalse(self._run('darwin', fake))
        self.assertEqual(fake._calls, [])

    def test_runtime_already_initialized_returns_false(self):
        # TF 运行时初始化后 set_visible_devices 抛 RuntimeError：
        # 不得炸掉训练入口，按未禁用处理并告警
        fake = _fake_tf(raise_on_set=True)
        self.assertFalse(self._run('darwin', fake))

    def test_missing_tensorflow_returns_false(self):
        # sys.modules['tensorflow'] = None 会让 import 抛 ImportError
        self.assertFalse(self._run('darwin', None))


class TestLocalTrainingEntryGuard(unittest.TestCase):
    """pipeline/training.py 必须在模块级调用守卫（management train、TUI、
    模板 train.py 等所有本地 TF 训练入口都经此模块）。"""

    def test_pipeline_training_calls_guard_at_module_level(self):
        root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
        path = os.path.join(root, 'donkeycar', 'pipeline', 'training.py')
        with open(path, encoding='utf-8') as f:
            src = f.read()
        self.assertIn('disable_metal_gpu_on_macos()', src)


if __name__ == '__main__':
    unittest.main()
