from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SERVICE_UNIT = (
    REPO_ROOT / "donkeycar" / "launcher" / "donkeydrifter-launcher.service"
)


def _unit_source() -> str:
    return SERVICE_UNIT.read_text(encoding="utf-8")


def test_launcher_unit_keeps_drive_processes_alive_on_restart():
    """launcher 停止/重启不得连坐杀死 drive 子进程（donkey web / manage.py
    drive）：KillMode=process 让 systemd 只向主进程发信号，DonkeyDrifter 驾驶
    界面（5188/8100）在服务重启后继续存活；下次 launch 仍由 launcher 按 PID
    文件先杀旧进程，不会累积孤儿。"""
    source = _unit_source()

    assert "KillMode=process" in source
    # 保持原有自愈能力：崩溃后自动拉起
    assert "Restart=always" in source
    # 不得退化为默认 control-group（cgroup 整体回收才会连坐杀子进程）
    assert "KillMode=control-group" not in source


def test_launcher_unit_still_runs_console_module():
    """unit 基本形态不变：conda 环境 python 启动 donkeycar.launcher，工作目录
    指向 mycar，保证改动只收窄 KillMode 一处。"""
    source = _unit_source()

    assert "python3 -m donkeycar.launcher" in source
    assert "WorkingDirectory=/home/dkc/projects/mycar" in source
