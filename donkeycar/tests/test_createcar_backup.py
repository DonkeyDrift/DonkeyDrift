"""createcar/update 的 overwrite 分支必须先备份将被覆盖的用户文件。

manage.py/config.py 常被深度定制，`donkey update`（create_car overwrite=True）
曾是一次性无备份覆盖，一次就能抹掉全部本地改动。备份落在 <car>/backups/。
"""
from pathlib import Path

from donkeycar.management.base import CreateCar


def _seed(path: Path, name: str, content: str) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / name).write_text(content, encoding="utf-8")


def test_overwrite_backs_up_existing_user_files(tmp_path):
    car = tmp_path / "mycar"
    _seed(car, "manage.py", "# my heavily customized manage.py\n")
    _seed(car, "config.py", "DRIVE_LOOP_HZ = 60  # my tweak\n")

    CreateCar().create_car(path=str(car), template="complete", overwrite=True)

    backups = sorted((car / "backups").glob("manage.py.*"))
    assert len(backups) == 1, "manage.py 覆盖前未备份"
    assert backups[0].read_text(encoding="utf-8") == "# my heavily customized manage.py\n"

    config_backups = sorted((car / "backups").glob("config.py.*"))
    assert len(config_backups) == 1
    assert "DRIVE_LOOP_HZ = 60" in config_backups[0].read_text(encoding="utf-8")

    # 覆盖后与模板归一
    from donkeycar.management import base
    assert (car / "manage.py").read_text(encoding="utf-8") == \
        (Path(base.__file__).parent.parent / "templates" / "complete.py").read_text(encoding="utf-8")


def test_fresh_createcar_writes_no_backup(tmp_path):
    car = tmp_path / "mycar"
    CreateCar().create_car(path=str(car), template="complete", overwrite=False)
    assert not (car / "backups").exists() or not any((car / "backups").iterdir())
    assert (car / "manage.py").exists()
