"""Bounded observation waits and truthful simulator recovery state."""

import base64
import threading
import time
from types import SimpleNamespace
from unittest.mock import patch

import cv2
import numpy as np
import pytest

from donkeycar.parts.dgym import DonkeyGymEnv
from gym_donkeycar.core.client import SDClient
from gym_donkeycar.envs.donkey_sim import (
    DonkeyUnitySimContoller,
    DonkeyUnitySimHandler,
)


def make_handler(timeout=0.1):
    handler = DonkeyUnitySimHandler({
        "level": "generated_track",
        "max_cte": 8.0,
        "cam_resolution": (24, 32, 3),
        "observe_timeout": timeout,
    })
    handler.client = SimpleNamespace(
        is_connected=lambda: True, send_now=lambda message: None,
        queue_message=lambda message: None)
    return handler


def telemetry():
    ok, image = cv2.imencode(".jpg", np.zeros((24, 32, 3), dtype=np.uint8))
    assert ok
    return {"msg_type": "telemetry",
            "image": base64.b64encode(image).decode("ascii")}


def bounded_observe(handler):
    errors = []

    def observe():
        try:
            handler.observe()
        except Exception as exc:
            errors.append(exc)

    worker = threading.Thread(target=observe, daemon=True)
    worker.start()
    worker.join(timeout=0.5)
    stopped = not worker.is_alive()
    if not stopped:
        # Release the original infinite wait on a failing pre-fix implementation.
        handler.time_received += 1
        worker.join(timeout=0.5)
    return stopped, errors


def test_observe_exits_after_disconnect():
    handler = make_handler()
    handler.on_disconnect()
    stopped, errors = bounded_observe(handler)
    assert stopped, "observe remained stuck after disconnect"
    assert len(errors) == 1 and isinstance(errors[0], ConnectionError)


def test_observe_exits_after_explicit_close():
    handler = make_handler()
    handler.on_close()
    stopped, errors = bounded_observe(handler)
    assert stopped, "observe remained stuck after close"
    assert len(errors) == 1 and isinstance(errors[0], ConnectionError)


def test_observe_times_out_on_connected_silent_server():
    handler = make_handler(timeout=0.05)
    stopped, errors = bounded_observe(handler)
    assert stopped, "silent connection must not wait forever"
    assert len(errors) == 1 and isinstance(errors[0], TimeoutError)


def test_observe_returns_real_new_frame():
    handler = make_handler()
    with patch("gym_donkeycar.envs.donkey_sim.time.time",
               return_value=handler.time_received + 0.01):
        handler.on_telemetry(telemetry())
    image, _, _, _ = handler.observe()
    assert image.shape == (24, 32, 3)
    assert handler.last_telemetry_ts > 0
    assert handler.last_received == handler.time_received


def test_reset_does_not_fabricate_telemetry_timestamp():
    handler = make_handler()
    assert handler.last_telemetry_ts == 0
    handler.on_telemetry(telemetry())
    received = handler.last_telemetry_ts
    with patch("gym_donkeycar.envs.donkey_sim.time.sleep"):
        handler.reset()
    assert handler.last_telemetry_ts == received


def test_scene_wait_has_timeout_and_closes_client():
    controller = DonkeyUnitySimContoller.__new__(DonkeyUnitySimContoller)
    controller.handler = make_handler(timeout=0.01)
    stopped = []
    controller.client = SimpleNamespace(
        is_connected=lambda: True, stop=lambda: stopped.append(True))
    with pytest.raises(TimeoutError):
        controller.wait_until_loaded()
    assert stopped == [True]


def test_health_uses_real_telemetry_not_reset_clock():
    with patch.object(DonkeyGymEnv, "_try_connect"):
        env = DonkeyGymEnv("remote", conf={"watchdog_sec": 0.1})
    handler = make_handler()
    env.env = SimpleNamespace(viewer=SimpleNamespace(
        handler=handler, client=handler.client), close=lambda: None)
    env._last_frame_ts = time.time()
    try:
        assert env._telemetry_ts() == 0
        assert not env._telemetry_is_fresh()
        with patch.object(env, "_post_rebuild"):
            env.run_threaded(0, 0)
        assert not env.connected
    finally:
        env.shutdown()


def test_failed_reset_closes_unpublished_environment():
    closed = []
    candidate = SimpleNamespace(
        reset=lambda: (_ for _ in ()).throw(TimeoutError("no telemetry")),
        close=lambda: closed.append(True))
    with patch.object(DonkeyGymEnv, "_try_connect"):
        env = DonkeyGymEnv("remote")
    env.env = None
    env.connected = False
    try:
        with patch("donkeycar.parts.dgym.gym.make", return_value=candidate):
            env._try_connect()
        assert env.env is None and not env.connected
        assert closed == [True]
    finally:
        env.shutdown()


def test_candidate_not_published_until_reset_returns():
    entered = threading.Event()
    release = threading.Event()
    candidate = SimpleNamespace(close=lambda: None)

    def reset():
        entered.set()
        assert release.wait(1)
        return np.zeros((120, 160, 3), dtype=np.uint8), {}

    candidate.reset = reset
    with patch.object(DonkeyGymEnv, "_try_connect"):
        env = DonkeyGymEnv("remote")
    env.env = None
    env.connected = False
    try:
        with patch("donkeycar.parts.dgym.gym.make", return_value=candidate):
            worker = threading.Thread(target=env._try_connect)
            worker.start()
            assert entered.wait(1)
            assert env.env is None and not env.connected
            release.set()
            worker.join(1)
            assert env.env is candidate
    finally:
        release.set()
        env.shutdown()


@pytest.mark.parametrize("fails", [False, True])
def test_old_step_cannot_overwrite_or_close_replacement(fails):
    entered = threading.Event()
    release = threading.Event()
    replacement_closed = []
    with patch.object(DonkeyGymEnv, "_try_connect"):
        env = DonkeyGymEnv("remote", conf={"img_w": 32, "img_h": 24})

    def old_step(action):
        entered.set()
        assert release.wait(1)
        if fails:
            raise ConnectionError("old session ended")
        return np.full((24, 32, 3), 255, dtype=np.uint8), 0, False, False, {}

    def new_step(action):
        env.running = False
        return np.full((24, 32, 3), 42, dtype=np.uint8), 0, False, False, {"speed": 7}

    old = SimpleNamespace(step=old_step, close=lambda: None)
    replacement = SimpleNamespace(
        step=new_step, close=lambda: replacement_closed.append(True))
    env.env = old
    pushed = []
    env.set_frame_sink(lambda frame: pushed.append(int(frame[0, 0, 0])))
    worker = threading.Thread(target=env.update, daemon=True)
    worker.start()
    try:
        assert entered.wait(1)
        with env._reconnect_lock:
            env.env = replacement
        release.set()
        worker.join(2)
        assert not worker.is_alive()
        assert env.env is replacement
        assert not replacement_closed
        assert pushed == [42]
        assert env.info["speed"] == 7
    finally:
        release.set()
        env.shutdown()


def test_connect_timeout_closes_socket():
    with patch("gym_donkeycar.core.client.socket.socket") as factory:
        sock = factory.return_value
        sock.connect.side_effect = TimeoutError("connect timed out")
        with pytest.raises(TimeoutError):
            SDClient("127.0.0.1", 1)
        sock.close.assert_called_once()


@pytest.mark.parametrize("timeout", [0, -1, float("inf"), float("nan")])
def test_observe_timeout_must_be_positive_and_finite(timeout):
    with pytest.raises(ValueError, match="observe_timeout"):
        make_handler(timeout)
