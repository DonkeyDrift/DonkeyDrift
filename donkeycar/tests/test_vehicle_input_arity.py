"""V.add 注册期校验 inputs 数量与部件执行函数签名匹配。

Vehicle 每轮按位置解包 run_threaded(*inputs)/run(*inputs)，inputs 数量
超出签名可接收位置参数时只能在运行期暴露（首拍 TypeError 或整体错位、
标志被静默丢弃）。注册期 fail fast 把这类错误提前到启动。
"""
import pytest

import donkeycar as dk


class FixedArityPart:
    def run(self, a, b, c=0):
        return a


class ThreadedShortPart:
    def update(self):
        pass

    def run_threaded(self, a):
        return a


class VarArgsPart:
    def run(self, *args):
        return args


class DefaultTailPart:
    def run(self, a, b=None):
        return a


def test_add_rejects_more_inputs_than_positional_params():
    v = dk.Vehicle()
    with pytest.raises(ValueError, match="FixedArityPart"):
        v.add(FixedArityPart(), inputs=['a', 'b', 'c', 'd'])


def test_add_threaded_checks_run_threaded_not_update():
    v = dk.Vehicle()
    with pytest.raises(ValueError, match="run_threaded"):
        v.add(ThreadedShortPart(), inputs=['a', 'b'], threaded=True)


def test_add_accepts_var_args_and_default_tails():
    v = dk.Vehicle()
    v.add(VarArgsPart(), inputs=['a', 'b', 'c'])
    v.add(DefaultTailPart(), inputs=['a'])
    v.add(FixedArityPart(), inputs=['a', 'b', 'c'])
    assert len(v.parts) == 3


def test_add_skips_check_without_inputs():
    v = dk.Vehicle()
    v.add(VarArgsPart())
    v.add(DefaultTailPart())
    assert len(v.parts) == 2
