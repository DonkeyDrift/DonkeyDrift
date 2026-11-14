"""myconfig 覆盖 config.py 时 dict 型配置必须键级深合并。

旧行为是属性级整体覆盖：myconfig 里重定义 GYM_CONF 会替换掉整个 dict，
config.py 后续新增的键（或用户忘记抄的键）被静默丢失——myconfig 注释里
"必须整体重定义 GYM_CONF" 的坑即源于此。现在 dict 与已有 dict 逐键合并，
非 dict 值（标量/list/tuple）保持整体覆盖语义。
"""
import types

import pytest

from donkeycar.config import Config, _deep_merge_dicts, load_config


def _obj(**attrs):
    d = types.ModuleType('cfg')
    for k, v in attrs.items():
        setattr(d, k.upper(), v)
    return d


def test_deep_merge_dicts_nested_override():
    base = {"a": 1, "nested": {"x": 1, "y": 2}, "keep": "base"}
    override = {"nested": {"y": 3, "z": 4}, "new": "added"}
    merged = _deep_merge_dicts(base, override)
    assert merged == {"a": 1, "nested": {"x": 1, "y": 3, "z": 4},
                      "keep": "base", "new": "added"}


def test_deep_merge_dicts_replaces_non_dict_values():
    base = {"body_rgb": (128, 128, 128), "flags": [1, 2], "n": 1}
    override = {"body_rgb": (0, 0, 0), "flags": [3], "n": 2}
    assert _deep_merge_dicts(base, override) == {
        "body_rgb": (0, 0, 0), "flags": [3], "n": 2}


def test_deep_merge_dicts_does_not_mutate_inputs():
    base = {"nested": {"x": 1}}
    override = {"nested": {"y": 2}}
    merged = _deep_merge_dicts(base, override)
    assert base == {"nested": {"x": 1}}
    assert override == {"nested": {"y": 2}}
    assert merged["nested"] is not base["nested"]


def test_from_object_merges_dict_over_existing():
    cfg = Config()
    cfg.from_object(_obj(gym_conf={"fps": 20, "body_style": "donkey"}))
    cfg.from_object(_obj(gym_conf={"fps": 60}))
    assert cfg.GYM_CONF == {"fps": 60, "body_style": "donkey"}


def test_from_object_replaces_scalar_and_dict_replaces_when_absent():
    cfg = Config()
    cfg.from_object(_obj(drive_loop_hz=20))
    cfg.from_object(_obj(drive_loop_hz=60))
    assert cfg.DRIVE_LOOP_HZ == 60

    fresh = Config()
    fresh.from_object(_obj(gym_conf={"fps": 60}))
    assert fresh.GYM_CONF == {"fps": 60}


def test_load_config_end_to_end_deep_merges_myconfig(tmp_path):
    (tmp_path / "config.py").write_text(
        "GYM_CONF = {'body_style': 'donkey', 'font_size': 100}\n"
        "DRIVE_LOOP_HZ = 20\n", encoding="utf-8")
    (tmp_path / "myconfig.py").write_text(
        "GYM_CONF = {'fps': 60}\nDRIVE_LOOP_HZ = 60\n", encoding="utf-8")

    cfg = load_config(config_path=str(tmp_path / "config.py"),
                      myconfig="myconfig.py")
    # myconfig 只声明差异键，config.py 的其余键保留；标量整体覆盖
    assert cfg.GYM_CONF == {"body_style": "donkey", "font_size": 100, "fps": 60}
    assert cfg.DRIVE_LOOP_HZ == 60
