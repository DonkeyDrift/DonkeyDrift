from pathlib import Path

from donkeycar.management import tui


class FakeRcHandler:
    def __init__(self):
        self.data = {}
        self.write_count = 0

    def write_file(self):
        self.write_count += 1


def _make_project(path: Path):
    path.mkdir(parents=True)
    (path / "manage.py").write_text("", encoding="utf-8")
    (path / "myconfig.py").write_text("", encoding="utf-8")


def test_is_valid_project_dir_checks_required_files(tmp_path):
    valid_project = tmp_path / "valid"
    _make_project(valid_project)

    missing_manage = tmp_path / "missing_manage"
    missing_manage.mkdir()
    (missing_manage / "myconfig.py").write_text("", encoding="utf-8")

    missing_myconfig = tmp_path / "missing_myconfig"
    missing_myconfig.mkdir()
    (missing_myconfig / "manage.py").write_text("", encoding="utf-8")

    assert tui._is_valid_project_dir(valid_project)
    assert not tui._is_valid_project_dir(missing_manage)
    assert not tui._is_valid_project_dir(missing_myconfig)
    assert not tui._is_valid_project_dir(tmp_path / "missing")


def test_project_dir_valid_with_config_but_no_myconfig(tmp_path):
    """myconfig.py 缺失不再直接判整个目录无效——先认项目，再由 _ensure_myconfig 补齐。"""
    project = tmp_path / "mycar"
    project.mkdir()
    (project / "manage.py").write_text("", encoding="utf-8")
    (project / "config.py").write_text("import os\nDRIVE_LOOP_HZ = 20\n", encoding="utf-8")

    assert tui._is_valid_project_dir(project)
    assert not (project / "myconfig.py").exists()


def test_ensure_myconfig_generates_from_template(tmp_path):
    project = tmp_path / "mycar"
    project.mkdir()
    (project / "manage.py").write_text("", encoding="utf-8")
    (project / "config.py").write_text('"""cfg"""\nimport os\nDRIVE_LOOP_HZ = 20\n', encoding="utf-8")

    assert tui._ensure_myconfig(project) is True

    myconfig = (project / "myconfig.py").read_text(encoding="utf-8")
    # 模板正文 + config.py 内容以注释形式追加
    assert "# DRIVE_LOOP_HZ = 20" in myconfig


def test_ensure_myconfig_keeps_existing_file(tmp_path):
    project = tmp_path / "mycar"
    project.mkdir()
    (project / "manage.py").write_text("", encoding="utf-8")
    (project / "myconfig.py").write_text("DONKEY_GYM = True\n", encoding="utf-8")

    assert tui._ensure_myconfig(project) is True
    assert (project / "myconfig.py").read_text(encoding="utf-8") == "DONKEY_GYM = True\n"


def test_is_valid_mycar_folder_repairs_missing_myconfig(monkeypatch, tmp_path):
    project = tmp_path / "mycar"
    project.mkdir()
    (project / "manage.py").write_text("", encoding="utf-8")
    (project / "config.py").write_text("import os\n", encoding="utf-8")
    monkeypatch.chdir(project)

    assert tui.is_valid_mycar_folder() is True
    assert (project / "myconfig.py").exists()


def test_find_valid_projects_returns_sorted_projects(tmp_path):
    projects_dir = tmp_path / "projects"
    _make_project(projects_dir / "z_car")
    _make_project(projects_dir / "a_car")
    (projects_dir / "not_car").mkdir()

    projects = tui._find_valid_projects(projects_dir)

    assert [project.name for project in projects] == ["a_car", "z_car"]


def test_last_project_path_is_saved_and_loaded(monkeypatch, tmp_path):
    rc_handler = FakeRcHandler()
    monkeypatch.setattr(tui, "rc_handler", rc_handler)
    project = tmp_path / "mycar"
    _make_project(project)

    tui._save_last_project_path(project)

    assert rc_handler.data["last_project_path"] == str(project)
    assert rc_handler.write_count == 1
    assert tui._get_last_project_path() == project


def test_get_last_project_path_ignores_missing_or_invalid_project(monkeypatch, tmp_path):
    rc_handler = FakeRcHandler()
    monkeypatch.setattr(tui, "rc_handler", rc_handler)

    assert tui._get_last_project_path() is None

    rc_handler.data["last_project_path"] = str(tmp_path / "missing")
    assert tui._get_last_project_path() is None

    invalid_project = tmp_path / "invalid"
    invalid_project.mkdir()
    rc_handler.data["last_project_path"] = str(invalid_project)
    assert tui._get_last_project_path() is None


def test_auto_open_project_keeps_current_project(monkeypatch, tmp_path):
    rc_handler = FakeRcHandler()
    monkeypatch.setattr(tui, "rc_handler", rc_handler)
    current_project = tmp_path / "current"
    projects_dir = tmp_path / "projects"
    _make_project(current_project)
    projects_dir.mkdir()
    monkeypatch.chdir(current_project)

    assert tui._auto_open_project(projects_dir)

    assert Path.cwd() == current_project
    assert rc_handler.data["last_project_path"] == str(current_project)


def test_auto_open_project_uses_last_project(monkeypatch, tmp_path):
    rc_handler = FakeRcHandler()
    monkeypatch.setattr(tui, "rc_handler", rc_handler)
    start_dir = tmp_path / "start"
    last_project = tmp_path / "last"
    projects_dir = tmp_path / "projects"
    start_dir.mkdir()
    projects_dir.mkdir()
    _make_project(last_project)
    rc_handler.data["last_project_path"] = str(last_project)
    monkeypatch.chdir(start_dir)

    assert tui._auto_open_project(projects_dir)

    assert Path.cwd() == last_project


def test_auto_open_project_opens_single_project(monkeypatch, tmp_path):
    rc_handler = FakeRcHandler()
    monkeypatch.setattr(tui, "rc_handler", rc_handler)
    start_dir = tmp_path / "start"
    projects_dir = tmp_path / "projects"
    project = projects_dir / "mycar"
    start_dir.mkdir()
    _make_project(project)
    monkeypatch.chdir(start_dir)

    assert tui._auto_open_project(projects_dir)

    assert Path.cwd() == project
    assert rc_handler.data["last_project_path"] == str(project)


def test_auto_open_project_prompts_when_multiple_projects(monkeypatch, tmp_path):
    rc_handler = FakeRcHandler()
    monkeypatch.setattr(tui, "rc_handler", rc_handler)
    start_dir = tmp_path / "start"
    projects_dir = tmp_path / "projects"
    first_project = projects_dir / "a_car"
    second_project = projects_dir / "b_car"
    start_dir.mkdir()
    _make_project(first_project)
    _make_project(second_project)
    monkeypatch.chdir(start_dir)
    monkeypatch.setattr(tui.Prompt, "ask", lambda *args, **kwargs: "2")

    assert tui._auto_open_project(projects_dir)

    assert Path.cwd() == second_project
    assert rc_handler.data["last_project_path"] == str(second_project)


def test_auto_open_project_can_cancel_multiple_project_selection(monkeypatch, tmp_path):
    rc_handler = FakeRcHandler()
    monkeypatch.setattr(tui, "rc_handler", rc_handler)
    start_dir = tmp_path / "start"
    projects_dir = tmp_path / "projects"
    start_dir.mkdir()
    _make_project(projects_dir / "a_car")
    _make_project(projects_dir / "b_car")
    monkeypatch.chdir(start_dir)
    monkeypatch.setattr(tui.Prompt, "ask", lambda *args, **kwargs: "0")

    assert not tui._auto_open_project(projects_dir)

    assert Path.cwd() == start_dir
    assert "last_project_path" not in rc_handler.data


def _patch_projects_root(monkeypatch, projects_dir: Path):
    """让 OpenProjectCommand 扫描临时目录而不是真实的 ~/projects。"""
    monkeypatch.setattr(
        tui.os.path,
        "expanduser",
        lambda p: str(projects_dir) if p == "~/projects" else p,
    )


def test_open_project_command_auto_opens_single_project(monkeypatch, tmp_path):
    rc_handler = FakeRcHandler()
    monkeypatch.setattr(tui, "rc_handler", rc_handler)
    start_dir = tmp_path / "start"
    projects_dir = tmp_path / "projects"
    project = projects_dir / "mycar"
    start_dir.mkdir()
    _make_project(project)
    monkeypatch.chdir(start_dir)
    _patch_projects_root(monkeypatch, projects_dir)
    prompts = []
    monkeypatch.setattr(
        tui.Prompt,
        "ask",
        lambda message, **kwargs: prompts.append(message) or "",
    )

    tui.OpenProjectCommand().execute()

    assert Path.cwd() == project
    assert rc_handler.data["last_project_path"] == str(project)
    # 只出现“按回车键返回菜单”一次提示，未要求输入编号
    assert len(prompts) == 1
    assert "返回菜单" in prompts[0]


def test_open_project_command_prompts_when_multiple_projects(monkeypatch, tmp_path):
    rc_handler = FakeRcHandler()
    monkeypatch.setattr(tui, "rc_handler", rc_handler)
    start_dir = tmp_path / "start"
    projects_dir = tmp_path / "projects"
    first_project = projects_dir / "a_car"
    second_project = projects_dir / "b_car"
    start_dir.mkdir()
    _make_project(first_project)
    _make_project(second_project)
    monkeypatch.chdir(start_dir)
    _patch_projects_root(monkeypatch, projects_dir)
    answers = iter(["2", ""])
    prompts = []

    def fake_ask(message, **kwargs):
        prompts.append(message)
        return next(answers)

    monkeypatch.setattr(tui.Prompt, "ask", fake_ask)

    tui.OpenProjectCommand().execute()

    assert Path.cwd() == second_project
    assert rc_handler.data["last_project_path"] == str(second_project)
    # 提示文案已支持粘贴项目路径（"请输入编号或项目路径"），只要求仍是编号入口
    assert prompts[0].startswith("请输入编号")


def _patch_no_sleep(monkeypatch):
    monkeypatch.setattr(tui.time, "sleep", lambda *args, **kwargs: None)


def _patch_confirm_off(monkeypatch):
    """Confirm 询问一律答否：去读 pytest 捕获的 stdin 会抛
    OSError: reading from stdin while output is captured（同 test_tui_drive.py 的做法）。"""
    monkeypatch.setattr(tui.Confirm, "ask", lambda *args, **kwargs: False)


def _drive_ask(asks):
    """Drive 全流程的 Prompt 替身：记录提示文本；编号/路径类提问回「取消」，
    其余回「不执行」。编号/路径类若回无效值，产品侧会一直重新提示，
    叠加 _patch_no_sleep 把 sleep 置空就成了死循环。"""
    def fake_ask(message, **kwargs):
        asks.append(message)
        if "编号" in message or "项目路径" in message:
            return "0"
        return "n"
    return fake_ask


def test_drive_command_auto_enters_single_project(monkeypatch, tmp_path):
    rc_handler = FakeRcHandler()
    monkeypatch.setattr(tui, "rc_handler", rc_handler)
    start_dir = tmp_path / "start"
    projects_dir = tmp_path / "projects"
    project = projects_dir / "mycar"
    start_dir.mkdir()
    _make_project(project)
    monkeypatch.chdir(start_dir)
    _patch_projects_root(monkeypatch, projects_dir)
    _patch_no_sleep(monkeypatch)
    # 进入项目后 has_car_process 为真；默认模式一键启动会真的拉起进程，
    # 这里用 -v 模式让执行确认页（答 n 取消）作为流程终点，不触达 Popen
    _patch_confirm_off(monkeypatch)
    monkeypatch.setattr(tui.Prompt, "ask", lambda *args, **kwargs: "n")

    tui.DriveCommand(verbose=True).execute()

    assert Path.cwd() == project
    assert rc_handler.data["last_project_path"] == str(project)


def test_drive_command_opens_without_any_project(monkeypatch, tmp_path):
    rc_handler = FakeRcHandler()
    monkeypatch.setattr(tui, "rc_handler", rc_handler)
    start_dir = tmp_path / "start"
    projects_dir = tmp_path / "projects"
    start_dir.mkdir()
    projects_dir.mkdir()
    monkeypatch.chdir(start_dir)
    _patch_projects_root(monkeypatch, projects_dir)
    _patch_no_sleep(monkeypatch)
    _patch_confirm_off(monkeypatch)
    asks = []
    monkeypatch.setattr(tui.Prompt, "ask", _drive_ask(asks))

    tui.DriveCommand(verbose=True).execute()

    # 未被环境检查拦截：先走手动输入项目路径的兜底（答 0 取消），
    # 再到达执行确认提示（-v 模式，确认页为终点），且目录未切换
    assert asks == ["请输入项目路径", "请选择操作"]
    assert Path.cwd() == start_dir
    assert "last_project_path" not in rc_handler.data


def test_drive_command_does_not_auto_enter_when_multiple_projects(monkeypatch, tmp_path):
    rc_handler = FakeRcHandler()
    monkeypatch.setattr(tui, "rc_handler", rc_handler)
    start_dir = tmp_path / "start"
    projects_dir = tmp_path / "projects"
    start_dir.mkdir()
    _make_project(projects_dir / "a_car")
    _make_project(projects_dir / "b_car")
    monkeypatch.chdir(start_dir)
    _patch_projects_root(monkeypatch, projects_dir)
    _patch_no_sleep(monkeypatch)
    _patch_confirm_off(monkeypatch)
    asks = []
    monkeypatch.setattr(tui.Prompt, "ask", _drive_ask(asks))

    tui.DriveCommand(verbose=True).execute()

    # 多项目选择（答 0 取消）→ 手动输入路径兜底（答 0 取消）→ 执行确认
    assert asks == ["请输入编号或项目路径", "请输入项目路径", "请选择操作"]
    assert Path.cwd() == start_dir
