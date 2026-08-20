# -*- coding: utf-8 -*-
"""Launcher 菜单动作（issue #126：接线 1-5、8-10 号菜单项）的单元测试。

覆盖 donkeycar.launcher.server 新增后端：
- _create_car：项目名白名单、目录已存在、成功后切换当前项目
- _open_project：只允许 ~/projects 下有效项目
- 数据三件套：_backup_data / _clear_data / _restore_data 往返
  （tmp_path 假项目：造 data → backup → clear → restore → 文件回来），
  备份文件名白名单（防路径穿越）、data 不存在/为空的 skip 分支
- _next_train_model：models/ 下 pilot_N 自动递增
- HTTP 端点：GET /api/projects、/api/data/backups、/api/train/next-model；
  POST /api/launch/web（issue #181 随 Web 菜单下线，应 404）、
  /api/createcar（非法项目名 400）、/api/data/*
- 前端静态断言：MENU_HTML 各菜单动作接线（7/11/12 号已并入
  DonkeyDrifter 顶栏、改为占位行，序号保留不递补）、terminal.html ?cmd= 自动执行

不启动真实 donkey / 子进程，全部替身。
"""

import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

import pytest

from donkeycar.launcher import server as launcher_server
from donkeycar.launcher.server import (
    _backup_data,
    _clear_data,
    _create_car,
    _list_backups,
    _next_train_model,
    _open_project,
    _restore_data,
    LauncherHandler,
    MENU_HTML,
)


@pytest.fixture(autouse=True)
def _reset_processes(monkeypatch, tmp_path):
    """每个测试前后复位全局进程表，避免跨测试污染。

    同时把 last_project_path 持久化打桩掉，防止测试写真实 ~/.donkeyrc
    （需要断言该调用的测试自行 monkeypatch 覆盖）。
    """
    monkeypatch.setattr(launcher_server,
                        "_save_last_project_path_local",
                        lambda p: None)
    saved = dict(launcher_server._processes)
    yield
    launcher_server._processes.clear()
    launcher_server._processes.update(saved)


@pytest.fixture()
def fake_project(tmp_path, monkeypatch):
    """tmp_path 下的假 mycar 项目（含 data/ 若干文件），并设为当前项目。"""
    project = tmp_path / "mycar"
    (project / "data" / "tub1").mkdir(parents=True)
    (project / "manage.py").write_text("# manage")
    (project / "myconfig.py").write_text("# config")
    for i in range(3):
        (project / "data" / "tub1" / f"record_{i}.json").write_text(
            f'{{"i": {i}}}')
    launcher_server._processes["project"] = str(project)
    return project


def _fake_completed(returncode=0, stderr="", stdout=""):
    return SimpleNamespace(returncode=returncode, stderr=stderr,
                           stdout=stdout)


# ===========================================================================
# _create_car（菜单 1）/ _open_project（菜单 2）
# ===========================================================================
class TestCreateCar:
    def test_rejects_bad_folder_names(self, tmp_path, monkeypatch):
        monkeypatch.setattr(launcher_server, "_PROJECTS_ROOT", tmp_path)
        for bad in ("../evil", "a/b", "..", "", "a b", None, 123):
            result, code = _create_car(bad)
            assert code == 400, bad
            assert result["status"] == "error"

    def test_rejects_existing_dir_without_overwrite(self, tmp_path,
                                                    monkeypatch):
        monkeypatch.setattr(launcher_server, "_PROJECTS_ROOT", tmp_path)
        (tmp_path / "mycar").mkdir()
        result, code = _create_car("mycar")
        assert code == 409
        assert "已存在" in result["error"]

    def test_success_sets_current_project(self, tmp_path, monkeypatch):
        monkeypatch.setattr(launcher_server, "_PROJECTS_ROOT", tmp_path)
        monkeypatch.setattr(
            launcher_server.subprocess, "run",
            lambda cmd, **k: _fake_completed())
        saved = []
        monkeypatch.setattr(launcher_server,
                            "_save_last_project_path_local",
                            saved.append)
        result, code = _create_car("newcar", template="basic",
                                   overwrite=True)
        assert code == 200
        assert result["status"] == "ok"
        assert result["path"] == str(tmp_path / "newcar")
        assert launcher_server._processes["project"] == \
            str(tmp_path / "newcar")
        assert saved == [tmp_path / "newcar"]

    def test_command_line_matches_tui(self, tmp_path, monkeypatch):
        monkeypatch.setattr(launcher_server, "_PROJECTS_ROOT", tmp_path)
        seen = {}

        def _run(cmd, **kwargs):
            seen["cmd"] = cmd
            return _fake_completed()

        monkeypatch.setattr(launcher_server.subprocess, "run", _run)
        _create_car("car1")
        assert seen["cmd"] == ["donkey", "createcar",
                               "--path", str(tmp_path / "car1")]

    def test_createcar_failure_reports_stderr(self, tmp_path, monkeypatch):
        monkeypatch.setattr(launcher_server, "_PROJECTS_ROOT", tmp_path)
        monkeypatch.setattr(
            launcher_server.subprocess, "run",
            lambda cmd, **k: _fake_completed(returncode=2,
                                             stderr="boom"))
        result, code = _create_car("car1")
        assert code == 500
        assert "boom" in result["error"]


class TestOpenProject:
    def test_rejects_path_outside_projects_root(self, tmp_path,
                                                monkeypatch):
        monkeypatch.setattr(launcher_server, "_PROJECTS_ROOT", tmp_path)
        result, code = _open_project("/etc")
        assert code == 400

    def test_rejects_invalid_project(self, tmp_path, monkeypatch):
        monkeypatch.setattr(launcher_server, "_PROJECTS_ROOT", tmp_path)
        (tmp_path / "notcar").mkdir()
        result, code = _open_project(str(tmp_path / "notcar"))
        assert code == 400

    def test_opens_valid_project(self, tmp_path, monkeypatch):
        monkeypatch.setattr(launcher_server, "_PROJECTS_ROOT", tmp_path)
        project = tmp_path / "mycar"
        project.mkdir()
        (project / "manage.py").write_text("x")
        (project / "myconfig.py").write_text("x")
        saved = []
        monkeypatch.setattr(launcher_server,
                            "_save_last_project_path_local",
                            saved.append)
        result, code = _open_project(str(project))
        assert code == 200
        assert launcher_server._processes["project"] == str(project)
        assert saved == [project]


# ===========================================================================
# 数据三件套（菜单 3/4/5）：backup → clear → restore 往返
# ===========================================================================
class TestDataOps:
    def test_backup_creates_numbered_archive(self, fake_project):
        result = _backup_data()
        assert isinstance(result, tuple) is False  # ok 时不是 tuple
        assert result["status"] == "ok"
        name = result["file"]
        assert name.startswith("data-") and name.endswith(".tar.gz")
        archive = fake_project / "data_cache" / name
        assert archive.is_file()
        assert result["size"] == archive.stat().st_size > 0
        # 第二次备份序号递增
        result2 = _backup_data()
        assert result2["file"] != name

    def test_backup_without_data_dir(self, tmp_path):
        launcher_server._processes["project"] = str(tmp_path)
        result, code = _backup_data()
        assert code == 400

    def test_clear_removes_data(self, fake_project):
        result = _clear_data(backup=False)
        assert result["status"] == "ok"
        assert list((fake_project / "data").iterdir()) == []
        # trash 目录不留残余
        leftovers = [p for p in fake_project.iterdir()
                     if p.name.startswith(".data_")]
        assert leftovers == []

    def test_clear_with_backup_creates_zip(self, fake_project):
        result = _clear_data(backup=True)
        assert result["status"] == "ok"
        assert result["backup_path"]
        assert Path(result["backup_path"]).is_file()

    def test_clear_skips_missing_or_empty(self, tmp_path):
        launcher_server._processes["project"] = str(tmp_path)
        assert _clear_data()["status"] == "skipped"
        (tmp_path / "data").mkdir()
        assert _clear_data()["status"] == "skipped"

    def test_list_backups(self, fake_project):
        assert _list_backups()["backups"] == []
        first = _backup_data()
        items = _list_backups()["backups"]
        assert len(items) == 1
        assert items[0]["name"] == first["file"]
        assert items[0]["size"] == first["size"]

    def test_restore_roundtrip(self, fake_project):
        _backup_data()
        assert _clear_data()["status"] == "ok"
        assert not any((fake_project / "data").iterdir())
        backups = _list_backups()["backups"]
        result, code = _restore_data(backups[0]["name"])
        assert code == 200
        assert result["status"] == "ok"
        restored = sorted(
            p.name for p in (fake_project / "data" / "tub1").iterdir())
        assert restored == ["record_0.json", "record_1.json",
                            "record_2.json"]

    def test_restore_rejects_traversal_names(self, fake_project):
        for evil in ("../evil.tar.gz", "data-260801-001.tar.gz/../../x",
                     "evil", "/abs/path", ".."):
            result, code = _restore_data(evil)
            assert code == 400, evil

    def test_restore_missing_archive(self, fake_project):
        result, code = _restore_data("data-260801-999.tar.gz")
        assert code == 404

    def test_restore_corrupt_archive(self, fake_project):
        cache = fake_project / "data_cache"
        cache.mkdir()
        (cache / "data-260801-001.tar.gz").write_bytes(b"not a tar")
        result, code = _restore_data("data-260801-001.tar.gz")
        assert code == 500
        assert "损坏" in result["error"]

    def test_restore_handles_data_prefixed_archive(self, fake_project):
        # 兼容 tar czf backup.tar.gz data/ 形式的归档
        import tarfile
        cache = fake_project / "data_cache"
        cache.mkdir()
        archive = cache / "data-260801-005.tar.gz"
        with tarfile.open(archive, "w:gz") as tar:
            tar.add(fake_project / "data", arcname="data")
        assert _clear_data()["status"] == "ok"
        result, code = _restore_data(archive.name)
        assert code == 200
        assert result["status"] == "ok"
        assert (fake_project / "data" / "tub1" /
                "record_0.json").is_file()


# ===========================================================================
# _next_train_model（菜单 9）
# ===========================================================================
class TestNextTrainModel:
    def test_increments_pilot_number(self, fake_project):
        models = fake_project / "models"
        models.mkdir()
        (models / "pilot_1").write_text("m")
        (models / "pilot_3").write_text("m")
        (models / "pilot_linear").write_text("m")  # 非纯数字不算
        result = _next_train_model()
        assert result == {"status": "ok", "model": "./models/pilot_4"}

    def test_starts_at_1(self, fake_project):
        assert _next_train_model()["model"] == "./models/pilot_1"


# ===========================================================================
# HTTP 端点（内存 HTTP 服务器）
# ===========================================================================
@pytest.fixture()
def http_server():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), LauncherHandler)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()
    thread.join(timeout=2)


def _get(url):
    try:
        with urllib.request.urlopen(url, timeout=5) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def _post(url, body):
    req = urllib.request.Request(
        url, data=json.dumps(body).encode(), method="POST",
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


class TestEndpoints:
    def test_get_projects(self, http_server, tmp_path, monkeypatch):
        monkeypatch.setattr(launcher_server, "_PROJECTS_ROOT", tmp_path)
        code, data = _get(http_server + "/api/projects")
        assert code == 200
        assert data["projects"] == []

    def test_get_backups(self, http_server, fake_project):
        _backup_data()
        code, data = _get(http_server + "/api/data/backups")
        assert code == 200
        assert len(data["backups"]) == 1

    def test_get_next_model(self, http_server, fake_project):
        code, data = _get(http_server + "/api/train/next-model")
        assert code == 200
        assert data["model"] == "./models/pilot_1"

    def test_post_launch_web_removed(self, http_server):
        # issue #181：原 7 号 Web 菜单并入 6 号「Donkey Drifter」，
        # /api/launch/web 端点随之下线，应返回 404
        code, _ = _post(http_server + "/api/launch/web", {})
        assert code == 404

    def test_post_createcar_rejects_bad_folder(self, http_server):
        code, data = _post(http_server + "/api/createcar",
                           {"folder": "../evil"})
        assert code == 400

    def test_post_createcar_rejects_bad_json(self, http_server):
        req = urllib.request.Request(
            http_server + "/api/createcar", data=b"not-json",
            method="POST")
        try:
            urllib.request.urlopen(req, timeout=5)
            raise AssertionError("应返回 400")
        except urllib.error.HTTPError as e:
            assert e.code == 400

    def test_post_projects_open(self, http_server, fake_project,
                                 monkeypatch):
        monkeypatch.setattr(launcher_server, "_PROJECTS_ROOT",
                            fake_project.parent)
        # 不打桩会写真实 ~/.donkeyrc
        monkeypatch.setattr(launcher_server,
                            "_save_last_project_path_local",
                            lambda p: None)
        code, data = _post(http_server + "/api/projects/open",
                           {"path": str(fake_project)})
        assert code == 200
        assert data["path"] == str(fake_project)

    def test_post_data_backup_and_restore(self, http_server, fake_project):
        code, data = _post(http_server + "/api/data/backup", {})
        assert code == 200
        name = data["file"]
        code, data = _post(http_server + "/api/data/clear",
                           {"backup": False})
        assert code == 200 and data["status"] == "ok"
        code, data = _post(http_server + "/api/data/restore",
                           {"name": name})
        assert code == 200 and data["status"] == "ok"
        assert (fake_project / "data" / "tub1" /
                "record_0.json").is_file()

    def test_post_data_restore_rejects_traversal(self, http_server,
                                                 fake_project):
        code, _ = _post(http_server + "/api/data/restore",
                        {"name": "../evil.tar.gz"})
        assert code == 400


# ===========================================================================
# 前端静态断言（MENU_HTML / terminal.html）
# ===========================================================================
class TestFrontendWiring:
    def test_all_menu_actions_wired(self):
        for fn in ("createCar()", "openProject()", "clearData()",
                   "backupData()", "restoreData()",
                   "launchDonkeyUI()", "launchTrainLocal()",
                   "launchTrainOnline()"):
            assert fn in MENU_HTML, fn
        # 所有菜单项接线后不再有 notImplemented 分支
        assert "showError(t('overlay.notImplemented'))" not in MENU_HTML

    def test_menu_7_11_12_merged_into_dd_topbar(self):
        # 用户指示：7 号 Drifter Console、11 号 Kimi Code Web、12 号
        # DeepSeek Harness 已并入 DonkeyDrifter 顶栏（标签页栏），Donkey
        # 菜单对应项改为占位行、序号保留不递补。
        assert 'name: "DonkeyDrifter"' in MENU_HTML
        assert 'descZh: "打开 DonkeyDrifter"' in MENU_HTML
        assert 'descEn: "Open DonkeyDrifter"' in MENU_HTML
        # 6 号仍走 launchDrive 启动 DD
        assert "launchDrive()" in MENU_HTML
        # 7/11/12 号占位行：placeholder 标记 + 「已并入 DonkeyDrifter 顶栏」双语描述
        assert "placeholder: true" in MENU_HTML
        assert "已并入 DonkeyDrifter 顶栏" in MENU_HTML
        assert "Merged into DonkeyDrifter top bar" in MENU_HTML
        assert "'menuItem placeholder'" in MENU_HTML
        # 序号保留、不递补：8 号 Donkey UI 与 12 号占位行仍在原位
        assert "no: 8" in MENU_HTML
        assert "no: 12" in MENU_HTML
        # 原 DC/Kimi/DSH 菜单动作不再接入 selectItem（占位行点击只提示）
        assert "no === 7" not in MENU_HTML
        assert "no === 11" not in MENU_HTML
        assert "no === 12" not in MENU_HTML
        # 原 7 号 Web 链路仍不存在
        assert "launchWebUI" not in MENU_HTML
        assert "/api/launch/web" not in MENU_HTML
        assert "overlay.startingWeb" not in MENU_HTML

    def test_new_i18n_keys_bilingual(self):
        for key in ("overlay.working", "overlay.done",
                    "menu.createcar.prompt", "menu.clear.confirm",
                    "menu.train.openTerminal",
                    "menu.donkeyui.openTerminal"):
            assert ("'" + key + "'") in MENU_HTML, key
        # zh 与 en 两个语言块都含新键：统计出现次数 ≥ 2
        assert MENU_HTML.count("'menu.createcar.prompt'") >= 2

    def test_menu_reads_dd_lang_url_param(self):
        # DD 内嵌 Donkey 时经 iframe src 的 `?lang=` 传入语言；launcher
        # 需优先读取该参数，跨源 localStorage（:8000 vs :8090）各自独立
        # 时仍能与 DD 语言一致，避免“DD 已英文、Donkey 菜单仍中文”。
        assert "function readUrlLanguage" in MENU_HTML
        assert "window.location.search" in MENU_HTML
        assert "[?&]lang=(zh|en)" in MENU_HTML
        assert "const fromUrl = readUrlLanguage()" in MENU_HTML

    def test_terminal_html_supports_cmd_param(self):
        page = (Path(launcher_server.__file__).parent /
                "terminal_static" / "terminal.html").read_text("utf-8")
        assert "cmd=" in page or "autoCmd" in page
        assert "autoCmd" in page
        # hello 之后发送自动命令
        assert "sendCtrl({type:'hello'" in page
        assert "autoCmd=null" in page
