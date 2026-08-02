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
    assert prompts[0] == "请输入编号"
