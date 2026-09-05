"""createcar 模板 train.py 的 mixed_float16 门控回归测试（loss 发散修复）。

背景：2026-08-23 排查发现，同一批 12531 条数据在本机训练收敛、
在 Mac (Apple Metal) 上 3/3 发散——createcar 模板无条件启用
mixed_float16，在 Metal/CPU 上数值不稳定。
2026-09-05（issue #370）：禁用 fp16 后 Mac 上 float32 训练仍异常
（train loss 尖峰、val loss 卡在"预测均值"退化水平），确认为
tensorflow-metal 已知数值问题（keras-team/tf-keras#140），macOS
训练改为隐藏 Metal GPU、回退 CPU。
"""

import os
import unittest


class TestTrainTemplateFp16Gate(unittest.TestCase):
    """模板 train.py 只能在非 macOS 且有 GPU 时启用 mixed_float16。"""

    @classmethod
    def setUpClass(cls):
        root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
        template = os.path.join(root, 'donkeycar', 'templates', 'train.py')
        with open(template, encoding='utf-8') as f:
            cls.src = f.read()

    def test_mixed_float16_gated_on_platform(self):
        # macOS 上即使有 GPU(Metal) 也不得启用 mixed_float16
        self.assertIn("sys.platform != 'darwin'", self.src)

    def test_macos_metal_gpu_disabled(self):
        # tensorflow-metal 在 Apple Silicon 上 float32 下也有已知数值问题
        # （train loss 尖峰、val loss 卡在"预测均值"退化水平），
        # macOS 训练须隐藏 Metal GPU 回退 CPU
        self.assertIn("sys.platform == 'darwin'", self.src)
        self.assertIn("set_visible_devices([], 'GPU')", self.src)

    def test_mixed_float16_still_available_with_gpu(self):
        # 非 macOS 有 GPU 的机器仍应能启用 mixed_float16
        self.assertIn("set_global_policy(policy)", self.src)

    def test_comment_passed_as_keyword(self):
        # train() 签名为 (cfg, tub_paths, model, model_type, transfer, comment)，
        # 位置传参会把 comment 错落到 transfer
        self.assertIn("comment=comment", self.src)


if __name__ == '__main__':
    unittest.main()
