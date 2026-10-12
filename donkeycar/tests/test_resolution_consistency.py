"""锁 320x240 全链路分辨率契约（2026-10-12「模拟器画面仍 160x120」修复）。

问题：`cfg_*.py` 默认 `IMAGE_W/H = 160/120`，且除 cfg_simulator 外的模板
`GYM_CONF` 不带 `img_w/img_h`——dgym 缺省回退 160x120，模拟器模式下
`cam/image_array` 恒为 160x120（真机链路已升 320x240），Drive 页只能由
`DriveVideoFrameBuffer` 把 160x120 上采样成 320x240 的糊画。

契约：
1) 模板配置默认原生 320x240；
2) 模拟器接线把 GYM_CONF 的 `img_w/img_h` 强制对齐 `IMAGE_W/H`（缺失或
   停留在旧值都不允许——cam/image_array 与相机路径、TubWriter、模型输入同一契约）；
3) cfg_simulator 的 GYM_CONF img 键引用 `IMAGE_W/H`，不写死分辨率。
"""
from pathlib import Path

_TEMPLATES_DIR = Path(__file__).resolve().parents[2] / "donkeycar" / "templates"

# 会创建 config 的模板（cfg_cv_control 本就是 320x240，无需断言）
_CFG_TEMPLATES = (
    "cfg_basic.py",
    "cfg_complete.py",
    "cfg_path_follow.py",
    "cfg_simulator.py",
    "cfg_square.py",
)

# 支持 DONKEY_GYM 的 drive 脚本模板，须做 img_w/img_h 对齐
_SIM_DRIVE_TEMPLATES = ("basic.py", "complete.py", "simulator.py")


def _read(name: str) -> str:
    return (_TEMPLATES_DIR / name).read_text(encoding="utf-8")


def test_cfg_templates_default_to_native_320x240():
    for name in _CFG_TEMPLATES:
        src = _read(name)
        assert "IMAGE_W = 320" in src, f"{name} 默认分辨率未升到 320x240"
        assert "IMAGE_H = 240" in src, f"{name} 默认分辨率未升到 320x240"
        assert "IMAGE_W = 160" not in src and "IMAGE_H = 120" not in src, \
            f"{name} 仍残留 160x120 分辨率"


def test_sim_drive_templates_force_gym_img_to_image_wh():
    for name in _SIM_DRIVE_TEMPLATES:
        src = _read(name)
        assert 'sim_conf["img_w"] = cfg.IMAGE_W' in src, \
            f"{name} 未把 GYM_CONF img_w 对齐 IMAGE_W"
        assert 'sim_conf["img_h"] = cfg.IMAGE_H' in src, \
            f"{name} 未把 GYM_CONF img_h 对齐 IMAGE_H"
        # DonkeyGymEnv 必须消费对齐后的 sim_conf，而不是原始 GYM_CONF
        assert "conf=sim_conf" in src, f"{name} 仍把原始 GYM_CONF 传给 DonkeyGymEnv"
        assert "conf=cfg.GYM_CONF" not in src, f"{name} 仍把原始 GYM_CONF 传给 DonkeyGymEnv"


def test_cfg_simulator_gym_conf_img_follows_image_wh():
    # cfg_simulator 的 GYM_CONF 显式带 img 键：必须引用 IMAGE_W/H，
    # 写死分辨率会让 myconfig 覆盖 IMAGE_W 后模拟器出图与模型输入错位
    src = _read("cfg_simulator.py")
    assert '"img_h" : IMAGE_H' in src
    assert '"img_w" : IMAGE_W' in src
    # 渲染分辨率（预览画质）与 NN 输入解耦，默认与预览编码上限（640×480）对齐：
    # 实测模拟器遥测节拍固定 20fps 与渲染分辨率无关，更高渲染不涨帧率/画质，
    # 只多烧模拟器 CPU 与编解码时延
    assert 'GYM_CONF["render_img_w"] = 640' in src
    assert 'GYM_CONF["render_img_h"] = 480' in src
