import subprocess
import sys
from configparser import ConfigParser
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def run_python_snippet(snippet):
    return subprocess.run(
        [sys.executable, "-c", snippet],
        cwd=PROJECT_ROOT,
        capture_output=True,
        check=False,
        text=True,
    )


def test_import_donkeycar_does_not_write_stdout():
    result = run_python_snippet("import donkeycar")

    assert result.returncode == 0
    assert result.stdout == ""


def test_version_is_available_from_side_effect_free_module():
    result = run_python_snippet(
        "from donkeycar._version import __version__; print(__version__)"
    )

    assert result.returncode == 0
    assert result.stdout.strip()


def test_package_version_matches_side_effect_free_version_module():
    result = run_python_snippet(
        "import donkeycar; from donkeycar._version import __version__; "
        "print(donkeycar.__version__ == __version__)"
    )

    assert result.returncode == 0
    assert result.stdout.strip() == "True"


def test_setup_cfg_reads_version_from_side_effect_free_module():
    parser = ConfigParser()
    parser.read(PROJECT_ROOT / "setup.cfg", encoding="utf-8")

    assert parser["metadata"]["version"] == "attr: donkeycar._version.__version__"
