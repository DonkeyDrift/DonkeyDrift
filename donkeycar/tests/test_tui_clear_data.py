import os
from pathlib import Path
import tempfile
import pytest

from donkeycar.management.tui import _scan_directory, _move_items_to_trash, _restore_from_trash, _delete_directory_contents


def _write_file(path: Path, size: int):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"a" * size)


def test_scan_directory_counts_and_size():
    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp) / "data"
        _write_file(data_dir / "a.txt", 3)
        _write_file(data_dir / "b.txt", 5)
        count, size = _scan_directory(data_dir)
        assert count == 2
        assert size == 8


def test_move_and_restore_items():
    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp) / "data"
        trash_dir = Path(tmp) / ".trash"
        _write_file(data_dir / "a.txt", 1)
        _write_file(data_dir / "sub" / "b.txt", 1)
        moved, errors = _move_items_to_trash(data_dir, trash_dir)
        assert errors == []
        assert data_dir.exists()
        assert list(data_dir.iterdir()) == []
        assert len(moved) == 2
        restore_errors = _restore_from_trash(trash_dir, data_dir)
        assert restore_errors == []
        assert (data_dir / "a.txt").exists()
        assert (data_dir / "sub" / "b.txt").exists()


def test_delete_directory_contents_success():
    with tempfile.TemporaryDirectory() as tmp:
        trash_dir = Path(tmp) / ".trash"
        _write_file(trash_dir / "a.txt", 1)
        _write_file(trash_dir / "sub" / "b.txt", 1)
        deleted = []
        errors = _delete_directory_contents(trash_dir, lambda n: deleted.append(n))
        assert errors == []
        assert sum(deleted) == 2
        assert list(trash_dir.rglob("*")) == []


@pytest.mark.skipif(os.name == "nt", reason="权限测试在 Windows 上不稳定")
def test_delete_directory_contents_permission_error():
    with tempfile.TemporaryDirectory() as tmp:
        trash_dir = Path(tmp) / ".trash"
        _write_file(trash_dir / "a.txt", 1)
        os.chmod(trash_dir, 0o500)
        try:
            errors = _delete_directory_contents(trash_dir, lambda n: None)
            assert errors
        finally:
            os.chmod(trash_dir, 0o700)
