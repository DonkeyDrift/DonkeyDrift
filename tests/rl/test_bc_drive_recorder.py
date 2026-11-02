"""M3 D0 补丁单测:DriveBcRecorder(网页驾驶 BC 录制 part)。

覆盖:
- (obs_k, u_k) 配对序列:state_vec 的 prev_action 分量 = u_{k-1},标签 = u_k;
- 与 env.build_state_vector 口径逐位一致(三方同源的直接断言);
- 重复 frame_id tick 跳过并计数;
- 帧数自动切段(多文件);
- shutdown 落 data_card + 蒙太奇;零数据 shutdown 不炸;
- 相机未就绪(frame=None)不记录。
"""

import json
import os

import numpy as np
import pytest

from donkeydrifter.rl.bc_data import load_dataset
from donkeydrifter.rl.bc_drive_recorder import DriveBcRecorder
from donkeydrifter.rl.env import build_state_vector


class FakeCam:
    def __init__(self):
        self.info = {}
        self.frame = None


def _info(fid, cte=0.1, speed=2.0):
    return {"cte": cte, "speed": speed, "forward_vel": speed,
            "vel": (speed, 0.0, 0.0), "gyro": (0.0, 0.0, 0.0),
            "accel": (0.0, 0.0, 0.0), "pos": (1.0, 0.0, 2.0), "frame_id": fid}


def _img(seed=0):
    rng = np.random.default_rng(seed)
    return rng.integers(0, 255, (120, 160, 3), dtype=np.uint8)


def test_pairing_sequence_and_prev_action(tmp_path):
    cam = FakeCam()
    rec = DriveBcRecorder(cam, out_dir=str(tmp_path), auto_episode_frames=0)
    cam.frame = _img(1)
    cam.info = _info(101)
    rec.run(0.1, 0.5)                       # 记录 (obs_1, u_1),prev=(0,0)
    cam.frame = _img(2)
    cam.info = _info(102, cte=0.3)
    rec.run(-0.2, 0.6)                      # 记录 (obs_2, u_2),prev=u_1
    rec.shutdown()
    ds = load_dataset(str(tmp_path))
    assert ds["steer"].tolist() == pytest.approx([0.1, -0.2])
    assert ds["throttle"].tolist() == pytest.approx([0.5, 0.6])
    # state_vec 口径:与 build_state_vector(同 info, prev=u_{k-1}) 逐位一致
    s0, _ = build_state_vector(_info(101), (0.0, 0.0))
    s1, _ = build_state_vector(_info(102, cte=0.3), (0.1, 0.5))
    assert np.allclose(ds["state"][0], s0)
    assert np.allclose(ds["state"][1], s1)
    # prev_action 分量落位(下标 14/15)
    assert ds["state"][0][14] == pytest.approx(0.0) and ds["state"][0][15] == pytest.approx(0.0)
    assert ds["state"][1][14] == pytest.approx(0.1) and ds["state"][1][15] == pytest.approx(0.5)


def test_duplicate_fid_tick_skipped(tmp_path):
    cam = FakeCam()
    rec = DriveBcRecorder(cam, out_dir=str(tmp_path), auto_episode_frames=0)
    cam.frame = _img(1)
    cam.info = _info(201)
    rec.run(0.0, 0.4)
    rec.run(0.3, 0.4)                       # 同 fid:跳过
    cam.frame = _img(2)
    cam.info = _info(202)
    rec.run(0.2, 0.4)                       # 新 fid:记录,prev=0.3(跳过 tick 也推进动作链)
    rec.shutdown()
    ds = load_dataset(str(tmp_path))
    assert len(ds["steer"]) == 2
    assert ds["steer"].tolist() == pytest.approx([0.0, 0.2])
    assert ds["state"][1][14] == pytest.approx(0.3)        # prev = 被跳过 tick 的最新动作
    card = json.load(open(os.path.join(tmp_path, "data_card.json")))
    assert card["dropped_frames"] == 1


def test_auto_episode_split(tmp_path):
    cam = FakeCam()
    rec = DriveBcRecorder(cam, out_dir=str(tmp_path), auto_episode_frames=2)
    cam.frame = _img(1)
    for i, fid in enumerate((301, 302, 303, 304)):
        cam.info = _info(fid)
        rec.run(0.0, 0.4)
    rec.shutdown()
    files = sorted(f for f in os.listdir(tmp_path) if f.startswith("bc_"))
    assert files == ["bc_00000.npz", "bc_00001.npz"]
    ds = load_dataset(str(tmp_path))
    assert len(ds["steer"]) == 4
    assert set(np.asarray(ds["meta"][:, 0], dtype=int).tolist()) == {0, 1}


def test_shutdown_writes_card_and_montage(tmp_path):
    cam = FakeCam()
    rec = DriveBcRecorder(cam, out_dir=str(tmp_path), auto_episode_frames=0)
    cam.frame = _img(1)
    cam.info = _info(401)
    rec.run(0.5, 0.8)
    rec.shutdown()
    card_path = os.path.join(tmp_path, "data_card.json")
    assert os.path.exists(card_path)
    card = json.load(open(card_path))
    assert card["pairs_total"] == 1
    assert "gates" in card and "gates_pass_all_hard" in card
    assert card["extra_source"] if "extra_source" in card else True
    assert os.path.exists(os.path.join(tmp_path, "montage.jpg"))


def test_empty_shutdown_no_crash(tmp_path):
    cam = FakeCam()
    rec = DriveBcRecorder(cam, out_dir=str(tmp_path))
    rec.shutdown()
    rec.shutdown()  # 幂等
    assert not os.path.exists(os.path.join(tmp_path, "data_card.json"))


def test_frame_not_ready_skips(tmp_path):
    cam = FakeCam()
    rec = DriveBcRecorder(cam, out_dir=str(tmp_path), auto_episode_frames=0)
    cam.info = _info(501)
    rec.run(0.1, 0.5)                       # frame=None:不记录
    cam.frame = _img(1)
    cam.info = _info(502)
    rec.run(0.2, 0.5)
    rec.shutdown()
    ds = load_dataset(str(tmp_path))
    assert len(ds["steer"]) == 1
    assert ds["steer"][0] == pytest.approx(0.2)
    assert ds["state"][0][14] == pytest.approx(0.1)        # 未记录 tick 的动作仍进 prev 链
