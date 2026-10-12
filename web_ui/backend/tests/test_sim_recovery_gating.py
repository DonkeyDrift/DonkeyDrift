"""模拟器自动恢复（sim recovery）门控回归测试。

背景缺陷：Web UI 页面加载即激活后端恢复 worker，worker 每 5s 无条件向
车端发 reconnect_simulator；车端收到后关掉健康连接，且 dgym 的 update()
线程可能卡死在 observe() 自旋里无法自愈——模拟器连接被周期性杀死、
车端永久掉线。

修复后 worker 必须依据车端遥测的 sim_connected 状态门控：确认在线且
状态新鲜时跳过；离线、未知或状态过期才发重连命令。
"""
import sys
import time
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from routers.drive import DriveState


@pytest.fixture
def state():
    return DriveState()


class TestSimStateTracking:
    def test_telemetry_updates_sim_state(self, state):
        state.note_telemetry_sim_state({"type": "telemetry", "sim_connected": True})
        assert state.car_sim_connected is True
        assert state.car_sim_seen_at > 0

    def test_telemetry_without_sim_field_keeps_state(self, state):
        state.note_telemetry_sim_state({"type": "telemetry", "sim_connected": True})
        seen_at = state.car_sim_seen_at
        # 真车模式（DONKEY_GYM 关）遥测不含 sim_connected，不应覆盖旧状态
        state.note_telemetry_sim_state({"type": "telemetry", "gz": 1.2})
        assert state.car_sim_connected is True
        assert state.car_sim_seen_at == seen_at

    def test_sim_disconnected_reported(self, state):
        state.note_telemetry_sim_state({"type": "telemetry", "sim_connected": False})
        assert state.car_sim_connected is False


class TestRecoveryGating:
    def test_skips_when_sim_connected_and_fresh(self, state):
        state.note_telemetry_sim_state({"type": "telemetry", "sim_connected": True})
        assert state.should_skip_sim_recovery() is True

    def test_sends_when_sim_disconnected(self, state):
        state.note_telemetry_sim_state({"type": "telemetry", "sim_connected": False})
        assert state.should_skip_sim_recovery() is False

    def test_sends_when_state_unknown(self, state):
        # 车端刚连上、遥测未到：状态未知，不跳过
        assert state.should_skip_sim_recovery() is False

    def test_sends_when_state_stale(self, state):
        state.note_telemetry_sim_state({"type": "telemetry", "sim_connected": True})
        # 遥测丢失超过 3 个恢复周期（5s * 3 = 15s）视为过期
        state.car_sim_seen_at = time.time() - 16.0
        assert state.should_skip_sim_recovery() is False

    def test_reset_on_car_disconnect(self, state):
        state.note_telemetry_sim_state({"type": "telemetry", "sim_connected": True})
        # 车端断开时处理器会将状态复位（模拟 handler 内联逻辑）
        state.car_sim_connected = None
        state.car_sim_seen_at = 0.0
        assert state.should_skip_sim_recovery() is False
