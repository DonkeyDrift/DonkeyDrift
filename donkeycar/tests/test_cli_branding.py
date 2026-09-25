import subprocess
import sys
from configparser import ConfigParser
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_console_script_remains_donkey():
    parser = ConfigParser()
    parser.read(PROJECT_ROOT / "setup.cfg", encoding="utf-8")

    entry_points = parser["options.entry_points"]["console_scripts"]
    assert "donkey = donkeycar.management.base:execute_from_command_line" in entry_points
    assert "donkeydrifter =" not in entry_points
    assert "drifter =" not in entry_points


def test_cli_usage_mentions_donkeydrifter_for_unknown_command():
    result = subprocess.run(
        [sys.executable, "-m", "donkeycar.management.base", "unknown-command"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        check=False,
        text=True,
    )

    combined_output = result.stdout + result.stderr
    # CLI banner 已随仓库改名同步为 DonkeyDrift。
    assert "DonkeyDrift" in combined_output
    assert "available commands" in combined_output
