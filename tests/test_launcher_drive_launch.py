# -*- coding: utf-8 -*-
"""launcher `_launch_drive` / `_wait_for_web_ready` 行为测试（issue #134）。

D 页面点 6 打开 Drive 后页面加载不出来，两个根因：

- `_launch_drive` 在 Popen 返回后立即报 launched，跳转页重定向到还没
  开始监听的 vite 端口 → `_wait_for_web_ready` 等实例登记出现且前端
  HTTP 探测通过才返回；
- launcher 预选的端口与 `donkey web` 内部二次改选后的实际端口不一致 →
  从实例登记（webui.json，donkey web 就绪后写入实际端口）回读。

覆盖：
- _wait_for_web_ready：新登记 + 探测通过返回实际端口；vite 二次改选时
  返回登记端口而非入参端口；web 提前退出带 warning；登记始终不出现
  超时带 warning；started_at 早于本次调用起点（并发链路代写）时不认
- _launch_drive：冷启动先 Popen web → 等就绪 → 再 Popen 车（env 用
  实际后端端口），url 用实际前端端口；复用存活实例时不起 web、不等待

DC 点击进入 DD 报"无法连接服务器"（2026-08-18）的补测：
- web 进程提前退出时 _launch_drive 不再报 launched + 死端口，改报
  error（跳转页显示原因而非重定向到从未监听的端口）；
- 就绪超时但进程仍在（生产模式 bundled web ui）时，兜底前端端口修正
  为后端端口（#135 生产模式前端由后端托管，5188 从不监听）；开发模式
  （--path 缺省）保持原入参端口。
"""

import time
from unittest import mock

import pytest

from donkeycar.launcher import server as launcher_server


class _FakeProc:
    """最小 Popen 替身：args 记录、poll 恒 None（存活）。"""

    def __init__(self, args=("fake",), returncode=None):
        self.args_seen = None
        self.kwargs_seen = None
        self.pid = 4242
        self._returncode = returncode

    def poll(self):
        return self._returncode


@pytest.fixture(autouse=True)
def _reset_processes():
    """每个测试后还原模块级进程跟踪表。"""
    yield
    launcher_server._processes.update({
        "web": None, "car": None, "backend_port": None,
        "frontend_port": None, "project": None,
    })


# ===========================================================================
# _wait_for_web_ready
# ===========================================================================
class TestWaitForWebReady:
    def test_returns_actual_ports_from_fresh_registry(self):
        """donkey web 就绪写入新登记：返回登记里的实际端口，探测通过。"""
        inst = {"pid": 100, "backend_port": 8000, "frontend_port": 5188,
                "started_at": time.time() + 1}
        web_proc = _FakeProc()
        with mock.patch.object(launcher_server, "read_instance",
                               return_value=inst), \
             mock.patch.object(launcher_server, "probe_http_ok",
                               return_value=True) as probe:
            frontend, backend, warning = launcher_server._wait_for_web_ready(
                web_proc, 5188, 8000,
            )
        assert (frontend, backend, warning) == (5188, 8000, None)
        probe.assert_called_once_with(5188, "/")

    def test_follows_port_reselection_by_vite(self):
        """vite/uvicorn 端口被占二次改选：以登记端口为准，不再用入参端口。"""
        inst = {"pid": 100, "backend_port": 8001, "frontend_port": 5189,
                "started_at": time.time() + 1}
        with mock.patch.object(launcher_server, "read_instance",
                               return_value=inst), \
             mock.patch.object(launcher_server, "probe_http_ok",
                               return_value=True):
            frontend, backend, warning = launcher_server._wait_for_web_ready(
                _FakeProc(), 5188, 8000,
            )
        assert (frontend, backend) == (5189, 8001)
        assert warning is None

    def test_web_proc_exited_early_returns_warning(self):
        """web 进程提前退出（依赖缺失等）：带 warning 返回，不抛错。"""
        web_proc = _FakeProc(returncode=1)
        with mock.patch.object(launcher_server, "read_instance",
                               return_value=None):
            frontend, backend, warning = launcher_server._wait_for_web_ready(
                web_proc, 5188, 8000, timeout=2.0,
            )
        assert (frontend, backend) == (5188, 8000)
        assert "提前退出" in warning

    def test_registry_never_appears_times_out_with_warning(self):
        """登记始终不出现（冷启动慢/卡死）：超时带 warning 返回入参端口。"""
        web_proc = _FakeProc()
        with mock.patch.object(launcher_server, "read_instance",
                               return_value=None), \
             mock.patch.object(launcher_server, "time") as fake_time:
            # 时间快进：跳过轮询间隔，直接跨过 deadline
            clock = iter([0.0, 0.0, 100.0, 100.0])
            fake_time.time.side_effect = lambda: next(clock, 100.0)
            fake_time.sleep = lambda *_: None
            frontend, backend, warning = launcher_server._wait_for_web_ready(
                web_proc, 5188, 8000, timeout=90.0,
            )
        assert (frontend, backend) == (5188, 8000)
        assert "未就绪" in warning

    def test_stale_registry_written_before_call_is_ignored(self):
        """started_at 早于本次调用起点的登记（他人在制实例）不算本次启动。"""
        # 假时钟起点 1000.0：stale 登记的 500.0 一定早于本次调用
        stale = {"pid": 100, "backend_port": 8000, "frontend_port": 5188,
                 "started_at": 500.0}
        web_proc = _FakeProc()
        with mock.patch.object(launcher_server, "read_instance",
                               return_value=stale), \
             mock.patch.object(launcher_server, "time") as fake_time:
            clock = iter([1000.0, 1000.0, 2000.0, 2000.0])
            fake_time.time.side_effect = lambda: next(clock, 2000.0)
            fake_time.sleep = lambda *_: None
            frontend, backend, warning = launcher_server._wait_for_web_ready(
                web_proc, 5188, 8000, timeout=90.0,
            )
        assert (frontend, backend) == (5188, 8000)
        assert "未就绪" in warning


# ===========================================================================
# _launch_drive
# ===========================================================================
class TestLaunchDrive:
    def _patch_common(self, inst=None, ready=(5189, 8001, None)):
        """公共桩：项目路径/杀车进程/实例探测/登记回读/就绪等待。
        read_drive_model 默认 None（隔离真实 ~/.donkeycar/drive_model.json），
        需要带模型启动的用例在 TestLaunchDriveWithModel 里自行覆写。"""
        return {
            "kill": mock.patch.object(launcher_server,
                                      "kill_previous_car_processes"),
            "project": mock.patch.object(
                launcher_server, "_find_mycar_project",
                return_value="/fake/mycar",
            ),
            "find": mock.patch.object(launcher_server, "find_live_instance",
                                      return_value=inst),
            "wait": mock.patch.object(launcher_server, "_wait_for_web_ready",
                                      return_value=ready),
            "pids": mock.patch.object(launcher_server, "write_drive_pids"),
            "model": mock.patch.object(launcher_server, "read_drive_model",
                                       return_value=None),
        }

    def test_cold_start_waits_ready_then_car_uses_actual_ports(self):
        """冷启动：先起 web → 等就绪回读实际端口 → 车进程连实际后端，
        返回 url 用实际前端端口（issue #134 两项验收）。"""
        web_proc, car_proc = _FakeProc(), _FakeProc()
        procs = [web_proc, car_proc]
        patches = self._patch_common(
            inst=None, ready=(5189, 8001, None),
        )
        with mock.patch.multiple(
            launcher_server,
            subprocess=mock.DEFAULT,
        ), mock.patch.object(
            launcher_server.subprocess, "Popen",
            side_effect=lambda *a, **k: procs.pop(0),
        ) as popen:
            with patches["kill"] as kill, patches["project"], \
                 patches["find"], patches["wait"] as wait, patches["pids"], \
                 patches["model"]:
                result = launcher_server._launch_drive()

        assert result["status"] == "launched"
        assert result["frontend_port"] == 5189
        assert result["backend_port"] == 8001
        assert result["url"] == "http://localhost:5189/#/drive"
        assert result["warning"] is None
        # 第一次 Popen 是 web，第二次是车
        assert popen.call_count == 2
        web_cmd = popen.call_args_list[0].args[0]
        car_cmd = popen.call_args_list[1].args[0]
        assert web_cmd[0] == "donkey" and "web" in web_cmd
        assert car_cmd[-2:] == ["drive"] or car_cmd[1:] == ["manage.py", "drive"]
        # 车进程 env 指向实际后端端口
        car_env = popen.call_args_list[1].kwargs["env"]
        assert car_env["DRIVE_API_SERVER_URL"] == \
            "ws://localhost:8001/api/drive/ws"
        # 就绪等待发生在 web Popen 之后（顺序由 wait 桩记录的先后保证）
        wait.assert_called_once()
        kill.assert_called_once()

    def test_cold_start_ready_timeout_still_launches_with_warning(self):
        """就绪等待超时：不报 error，照常 launched 并透出 warning。"""
        procs = [_FakeProc(), _FakeProc()]
        patches = self._patch_common(
            inst=None, ready=(5188, 8000, "Web UI 在 90s 内未就绪"),
        )
        with mock.patch.object(
            launcher_server.subprocess, "Popen",
            side_effect=lambda *a, **k: procs.pop(0),
        ):
            with patches["kill"], patches["project"], patches["find"], \
                 patches["wait"], patches["pids"], patches["model"]:
                result = launcher_server._launch_drive()
        assert result["status"] == "launched"
        assert "未就绪" in result["warning"]

    def test_web_proc_exited_early_returns_error(self):
        """web 进程提前退出（前端构建失败等）：报 error 而非 launched，
        不起车进程、不写 PID 文件——避免跳转页重定向到死端口。"""
        web_proc = _FakeProc(returncode=1)
        car_proc = _FakeProc()
        procs = [web_proc, car_proc]
        patches = self._patch_common(
            inst=None,
            ready=(5188, 8000, "donkey web 进程提前退出，页面可能加载失败"),
        )
        with mock.patch.object(
            launcher_server.subprocess, "Popen",
            side_effect=lambda *a, **k: procs.pop(0),
        ) as popen:
            with patches["kill"], patches["project"], patches["find"], \
                 patches["wait"], patches["pids"] as pids:
                result = launcher_server._launch_drive()
        assert result["status"] == "error"
        assert "提前退出" in result["error"]
        # 只起了 web（随后退出），车进程未起
        assert popen.call_count == 1
        assert popen.call_args_list[0].args[0][0] == "donkey"
        pids.assert_not_called()

    def test_timeout_production_mode_corrects_frontend_port(self):
        """生产模式（bundled web ui）就绪超时且登记未出现：兜底前端端口
        从入参 5188 修正为后端端口（#135 前端由后端托管，5188 从不监听）。"""
        procs = [_FakeProc(), _FakeProc()]
        patches = self._patch_common(
            inst=None, ready=(5188, 8000, "Web UI 在 90s 内未就绪"),
        )
        with mock.patch.object(
            launcher_server.subprocess, "Popen",
            side_effect=lambda *a, **k: procs.pop(0),
        ), mock.patch.object(
            launcher_server, "_get_bundled_web_ui_path",
            return_value="/fake/webui",
        ), mock.patch.object(
            launcher_server, "read_instance", return_value=None,
        ):
            with patches["kill"], patches["project"], patches["find"], \
                 patches["wait"], patches["pids"], patches["model"]:
                result = launcher_server._launch_drive()
        assert result["status"] == "launched"
        assert result["frontend_port"] == 8000
        assert result["url"] == "http://localhost:8000/#/drive"
        assert "未就绪" in result["warning"]

    def test_timeout_dev_mode_keeps_input_frontend_port(self):
        """开发模式（无 bundled --path）就绪超时：保持入参前端端口 5188
        （vite dev server 确实监听 5188，无需修正）。"""
        procs = [_FakeProc(), _FakeProc()]
        patches = self._patch_common(
            inst=None, ready=(5188, 8000, "Web UI 在 90s 内未就绪"),
        )
        with mock.patch.object(
            launcher_server.subprocess, "Popen",
            side_effect=lambda *a, **k: procs.pop(0),
        ), mock.patch.object(
            launcher_server, "_get_bundled_web_ui_path", return_value=None,
        ):
            with patches["kill"], patches["project"], patches["find"], \
                 patches["wait"], patches["pids"], patches["model"]:
                result = launcher_server._launch_drive()
        assert result["status"] == "launched"
        assert result["frontend_port"] == 5188
        assert result["url"] == "http://localhost:5188/#/drive"

    def test_reuse_instance_skips_web_popen_and_wait(self):
        """复用存活实例：不起 web、不等就绪，车进程直连登记端口。"""
        inst = {"pid": 999, "backend_port": 8000, "frontend_port": 5188,
                "started_at": time.time()}
        car_proc = _FakeProc()
        patches = self._patch_common(inst=inst)
        with mock.patch.object(
            launcher_server.subprocess, "Popen",
            return_value=car_proc,
        ) as popen:
            with patches["kill"], patches["project"], \
                 patches["find"], patches["wait"] as wait, patches["pids"], \
                 patches["model"]:
                result = launcher_server._launch_drive()
        assert result["status"] == "launched"
        assert result["url"] == "http://localhost:5188/#/drive"
        assert result["backend_port"] == 8000
        # 只起了车进程，没起 web，也没等就绪
        assert popen.call_count == 1
        car_cmd = popen.call_args_list[0].args[0]
        assert "manage.py" in car_cmd and "drive" in car_cmd
        car_env = popen.call_args_list[0].kwargs["env"]
        assert car_env["DRIVE_API_SERVER_URL"] == \
            "ws://localhost:8000/api/drive/ws"
        wait.assert_not_called()

    def test_no_project_returns_error(self):
        """找不到 mycar 项目：直接报错，不起任何进程。"""
        patches = self._patch_common()
        patches["project"] = mock.patch.object(
            launcher_server, "_find_mycar_project", return_value=None,
        )
        with mock.patch.object(launcher_server.subprocess, "Popen") as popen:
            with patches["kill"], patches["project"], patches["find"], \
                 patches["wait"], patches["pids"], patches["model"]:
                result = launcher_server._launch_drive()
        assert result["status"] == "error"
        assert "mycar" in result["error"]
        popen.assert_not_called()


# ===========================================================================
# _launch_drive 带模型启动（issue #003：web_ui 选定模型经
# ~/.donkeycar/drive_model.json 持久化，launcher 起车进程时附加 --model/--type）
# ===========================================================================
class TestLaunchDriveWithModel:
    def _reuse_inst(self):
        return {"pid": 999, "backend_port": 8000, "frontend_port": 5188,
                "started_at": time.time()}

    def _launch_reusing_instance(self, model_record=None):
        """复用实例路径跑一次 _launch_drive，返回 (result, popen mock)。
        持久化模型经 model_record 注入（None = 无持久化文件）：
        先由 _patch_common 的 model 桩（return_value=None）隔离真实
        ~/.donkeycar/drive_model.json，再在桩上覆写返回值。"""
        patches = TestLaunchDrive._patch_common(self, inst=self._reuse_inst())
        with mock.patch.object(
            launcher_server.subprocess, "Popen",
            side_effect=lambda *a, **k: _FakeProc(),
        ) as popen:
            with patches["kill"], patches["project"], patches["find"], \
                 patches["wait"], patches["pids"], \
                 patches["model"] as read_model:
                read_model.return_value = model_record
                result = launcher_server._launch_drive()
        return result, popen

    def test_persisted_model_appends_model_and_type_flags(self, tmp_path):
        """有持久化模型且文件存在：车命令带 --model/--type。"""
        model = tmp_path / "models" / "DKG-1.tflite"
        model.parent.mkdir(parents=True)
        model.write_bytes(b"tflite")
        record = {"model": str(model), "model_type": "tflite_linear"}
        result, popen = self._launch_reusing_instance(model_record=record)
        assert result["status"] == "launched"
        car_cmd = popen.call_args_list[0].args[0]
        assert "--model" in car_cmd
        assert car_cmd[car_cmd.index("--model") + 1] == str(model)
        assert car_cmd[car_cmd.index("--type") + 1] == "tflite_linear"

    def test_persisted_model_without_type_omits_type_flag(self, tmp_path):
        """持久化记录无 model_type：只带 --model，--type 交给 cfg 默认。"""
        model = tmp_path / "models" / "m.h5"
        model.parent.mkdir(parents=True)
        model.write_bytes(b"h5")
        record = {"model": str(model), "model_type": None}
        result, popen = self._launch_reusing_instance(model_record=record)
        assert result["status"] == "launched"
        car_cmd = popen.call_args_list[0].args[0]
        assert "--model" in car_cmd
        assert "--type" not in car_cmd

    def test_no_persisted_model_launches_without_model(self):
        """无持久化记录：保持旧行为，不带 --model。"""
        result, popen = self._launch_reusing_instance(model_record=None)
        assert result["status"] == "launched"
        car_cmd = popen.call_args_list[0].args[0]
        assert "--model" not in car_cmd

    def test_missing_model_file_falls_back_to_no_model(self):
        """持久化记录指向已删除的文件：不带 --model 启动并告警，
        避免 manage.py 因模型缺失直接退出导致车进程反复起不来。"""
        record = {"model": "/gone/models/deleted.tflite",
                  "model_type": "tflite_linear"}
        result, popen = self._launch_reusing_instance(model_record=record)
        assert result["status"] == "launched"
        car_cmd = popen.call_args_list[0].args[0]
        assert "--model" not in car_cmd
