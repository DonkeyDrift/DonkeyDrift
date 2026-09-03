import sys
from pathlib import Path
from unittest.mock import patch

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import mypc_probe


class FakeSsh:
    def close(self):
        pass


def _make_dispatcher(commands):
    """Return a fake _run_remote that dispatches on the command string.

    ``commands`` maps a substring to a ``(code, stdout, stderr)`` tuple.
    """
    def _run(ssh, command, timeout=20):
        for key, result in commands.items():
            if key in command:
                return result
        return (0, "", "")
    return _run


def _patchers(commands, ssh_ok=True):
    """Create patchers for _open_ssh and _run_remote for one probe call."""
    ssh = FakeSsh()

    def _open(host, user, password, port=22, timeout=10, key_path=""):
        if not ssh_ok:
            raise ConnectionError("connection refused")
        return ssh

    return (
        patch.object(mypc_probe, "_open_ssh", side_effect=_open),
        patch.object(mypc_probe, "_run_remote", side_effect=_make_dispatcher(commands)),
    )


def _probe(commands, ssh_ok=True, **kwargs):
    open_patch, run_patch = _patchers(commands, ssh_ok=ssh_ok)
    with open_patch, run_patch:
        return mypc_probe.probe_mypc_environment("192.168.1.10", "u", "p", **kwargs)


def test_probe_ready_linux():
    cmds = {
        "uname -s": (0, "Linux\n", ""),
        "import sys; print(sys.executable)": (0, "/home/u/miniconda3/envs/donkey/bin/python\n", ""),
        "import donkeycar": (0, "", ""),
        "--help": (0, "usage: donkey", ""),
    }
    result = _probe(cmds)

    assert result.ok is True
    assert result.platform == "linux"
    assert result.python_path == "/home/u/miniconda3/envs/donkey/bin/python"
    names = {c.name: c.status for c in result.checks}
    assert names["ssh"] == "ok"
    assert names["python"] == "ok"
    assert names["donkeycar"] == "ok"
    assert names["donkey_cli"] == "ok"


def test_probe_ssh_failure():
    result = _probe({}, ssh_ok=False)

    assert result.ok is False
    assert result.checks[0].name == "ssh"
    assert result.checks[0].status == "fail"
    assert result.suggestions


def test_probe_macos_autodetect_python():
    cmds = {
        "uname -s": (0, "Darwin\n", ""),
        # configured python empty -> first candidate 'python3' works
        "python3 -c \"import sys; print(sys.executable)\"": (0, "/opt/homebrew/bin/python3\n", ""),
        "import donkeycar": (0, "", ""),
        "--help": (0, "usage: donkey", ""),
    }
    result = _probe(cmds, python_path="")

    assert result.ok is True
    assert result.platform == "macos"
    assert result.python_path == "/opt/homebrew/bin/python3"


def test_probe_windows_without_wsl():
    cmds = {
        "uname -s": (1, "", "'uname' is not recognized"),
        "wsl.exe -e uname -s": (1, "", ""),
    }
    result = _probe(cmds)

    assert result.platform == "windows"
    assert result.shell == "windows"
    assert result.ok is False
    names = {c.name: c.status for c in result.checks}
    assert names.get("wsl") == "warn"
    # python detection still attempts, but all candidates fail
    assert names["python"] == "fail"


def test_probe_missing_donkeycar():
    cmds = {
        "uname -s": (0, "Linux\n", ""),
        "import sys; print(sys.executable)": (0, "/usr/bin/python3\n", ""),
        "import donkeycar": (1, "", "ModuleNotFoundError: No module named 'donkeycar'"),
        "--help": (1, "", ""),
    }
    result = _probe(cmds)

    assert result.ok is False
    names = {c.name: c.status for c in result.checks}
    assert names["donkeycar"] == "fail"
    assert any("donkeycar" in s for s in result.suggestions)


def test_probe_uses_configured_python_first():
    cmds = {
        "uname -s": (0, "Linux\n", ""),
        # configured path succeeds, so auto-detection never runs
        "/custom/python -c \"import sys; print(sys.executable)\"": (0, "/custom/python\n", ""),
        "import donkeycar": (0, "", ""),
        "--help": (0, "usage: donkey", ""),
    }
    result = _probe(cmds, python_path="/custom/python")

    assert result.ok is True
    assert result.python_path == "/custom/python"
