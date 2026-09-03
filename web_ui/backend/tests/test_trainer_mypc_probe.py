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


def _echo_executable(command):
    """Pretend the invoked interpreter resolves sys.executable to itself."""
    return (0, command.split(" -c ", 1)[0] + "\n", "")


def _donkeycar_only_under(path_fragment):
    """find_spec('donkeycar') succeeds only for interpreters under a path."""
    def _run(command):
        return (0, "", "") if path_fragment in command else (1, "", "")
    return _run


def _make_dispatcher(commands, calls=None):
    """Return a fake _run_remote that dispatches on the command string.

    ``commands`` maps a substring to a ``(code, stdout, stderr)`` tuple, or
    to a callable taking the full command and returning such a tuple. When
    ``calls`` is a list, every remote command is appended to it.
    """
    def _run(ssh, command, timeout=20):
        if calls is not None:
            calls.append(command)
        for key, result in commands.items():
            if key in command:
                return result(command) if callable(result) else result
        return (0, "", "")
    return _run


def _patchers(commands, ssh_ok=True, calls=None):
    """Create patchers for _open_ssh and _run_remote for one probe call."""
    ssh = FakeSsh()

    def _open(host, user, password, port=22, timeout=10, key_path=""):
        if not ssh_ok:
            raise ConnectionError("connection refused")
        return ssh

    return (
        patch.object(mypc_probe, "_open_ssh", side_effect=_open),
        patch.object(mypc_probe, "_run_remote", side_effect=_make_dispatcher(commands, calls)),
    )


def _probe(commands, ssh_ok=True, calls=None, **kwargs):
    open_patch, run_patch = _patchers(commands, ssh_ok=ssh_ok, calls=calls)
    with open_patch, run_patch:
        return mypc_probe.probe_mypc_environment("192.168.1.10", "u", "p", **kwargs)


def test_probe_ready_linux():
    calls = []
    cmds = {
        "uname -s": (0, "Linux\n", ""),
        # Layer 1: conda lists its envs itself. Comment lines and rc-file
        # junk in the output must be ignored.
        "conda env list": (
            0,
            "# conda environments:\n"
            "#\n"
            "Welcome to my custom shell!\n"
            "base                  *  /home/u/miniconda3\n"
            "donkey                   /home/u/miniconda3/envs/donkey\n",
            "",
        ),
        "import sys; print(sys.executable)": _echo_executable,
        "find_spec('donkeycar')": _donkeycar_only_under("envs/donkey"),
        "--help": (0, "usage: donkey", ""),
    }
    result = _probe(cmds, calls=calls)

    assert result.ok is True
    assert result.platform == "linux"
    # the first discovered interpreter that carries donkeycar wins
    assert result.python_path == "/home/u/miniconda3/envs/donkey/bin/python3"
    names = {c.name: c.status for c in result.checks}
    assert names["ssh"] == "ok"
    assert names["platform"] == "ok"
    assert names["python"] == "ok"
    assert names["donkeycar"] == "ok"
    assert names["donkey_cli"] == "ok"
    platform_check = next(c for c in result.checks if c.name == "platform")
    assert platform_check.message == "检测到远程系统: Linux"
    # conda was asked through zsh first and answered, so bash never ran
    conda_calls = [c for c in calls if "conda env list" in c]
    assert conda_calls == [
        "zsh -c 'source ~/.zshrc >/dev/null 2>&1; conda env list 2>/dev/null'"
    ]
    # the old GNU-find based discovery is gone for good
    assert not any('find "$HOME"' in c for c in calls)


def test_probe_discovers_via_glob_when_conda_silent():
    calls = []
    cmds = {
        "uname -s": (0, "Linux\n", ""),
        # conda is on neither shell's PATH -> layer 1 yields nothing
        "conda env list": (0, "", ""),
        # Layer 2: an env under a known-but-nondefault root (~/opt/...)
        "for b in": (
            0,
            "/home/u/opt/miniconda3/envs/donkey/bin/python3\n"
            "/home/u/opt/miniconda3/envs/donkey/bin/python\n",
            "",
        ),
        "import sys; print(sys.executable)": _echo_executable,
        "find_spec('donkeycar')": _donkeycar_only_under("envs/donkey"),
        "--help": (0, "usage: donkey", ""),
    }
    result = _probe(cmds, calls=calls)

    assert result.ok is True
    assert result.python_path == "/home/u/opt/miniconda3/envs/donkey/bin/python3"
    # all three shells were asked for `conda env list` before falling through
    conda_calls = [c for c in calls if "conda env list" in c]
    assert len(conda_calls) == 3
    assert conda_calls[0].startswith("zsh -c")
    assert conda_calls[1].startswith("bash -lc")
    assert conda_calls[2].startswith("zsh -lc")
    # the glob always runs inside sh so zsh nomatch cannot abort it
    assert any(c.startswith("sh -c 'for b in") for c in calls)


def test_probe_discovers_via_conda_binary_glob():
    calls = []
    cmds = {
        "uname -s": (0, "Linux\n", ""),
        # Layer 1b: the conda binary is found at a system-wide install root
        # (more specific keys first: the dispatcher returns the first
        # substring match, and the binary's env-list command also contains
        # the plain "conda env list" substring)
        'ls -d "$HOME"/*/condabin/conda': (0, "/opt/miniconda3/condabin/conda\n", ""),
        "/opt/miniconda3/condabin/conda env list": (
            0,
            "# conda environments:\n"
            "#\n"
            "base                  *  /opt/miniconda3\n"
            "donkey                   /opt/miniconda3/envs/donkey\n",
            "",
        ),
        # Layer 1: no rc file puts conda on PATH -> all three shells empty
        "conda env list": (0, "", ""),
        "import sys; print(sys.executable)": _echo_executable,
        "find_spec('donkeycar')": _donkeycar_only_under("envs/donkey"),
        "--help": (0, "usage: donkey", ""),
    }
    result = _probe(cmds, calls=calls)

    assert result.ok is True
    assert result.python_path == "/opt/miniconda3/envs/donkey/bin/python3"
    # the three rc-based attempts ran first, then the located binary was asked
    env_list_calls = [c for c in calls if "conda env list" in c]
    assert env_list_calls == [
        "zsh -c 'source ~/.zshrc >/dev/null 2>&1; conda env list 2>/dev/null'",
        "bash -lc 'conda env list 2>/dev/null'",
        "zsh -lc 'conda env list 2>/dev/null'",
        "/opt/miniconda3/condabin/conda env list 2>/dev/null",
    ]
    locate_calls = [c for c in calls if 'ls -d "$HOME"/*/condabin/conda' in c]
    assert len(locate_calls) == 1
    assert calls.index(locate_calls[0]) < calls.index(env_list_calls[3])


def test_probe_discovers_via_system_root_glob():
    calls = []
    cmds = {
        "uname -s": (0, "Linux\n", ""),
        # conda is entirely unavailable: rc shells list nothing and no
        # conda binary is globbed either
        "conda env list": (0, "", ""),
        # Layer 2: an env under a system-wide root (/usr/local/...)
        "for b in": (
            0,
            "/usr/local/anaconda3/envs/donkey/bin/python3\n"
            "/usr/local/anaconda3/envs/donkey/bin/python\n",
            "",
        ),
        "import sys; print(sys.executable)": _echo_executable,
        "find_spec('donkeycar')": _donkeycar_only_under("envs/donkey"),
        "--help": (0, "usage: donkey", ""),
    }
    result = _probe(cmds, calls=calls)

    assert result.ok is True
    assert result.python_path == "/usr/local/anaconda3/envs/donkey/bin/python3"
    # the glob command really covers the system-wide roots now
    glob_calls = [c for c in calls if c.startswith("sh -c 'for b in")]
    assert len(glob_calls) == 1
    assert '"/opt/conda"' in glob_calls[0]
    assert '"/usr/local/anaconda3"' in glob_calls[0]


def test_probe_discovers_via_donkey_command():
    calls = []
    cmds = {
        "uname -s": (0, "Darwin\n", ""),
        "sw_vers -productVersion": (0, "26.5\n", ""),
        # layers 1 and 2 come up empty (env lives in a custom location)
        "conda env list": (0, "", ""),
        "for b in": (0, "", ""),
        # Layer 3: the donkey console script gives the env away
        "command -v donkey": (0, "/Users/u/myenv/bin/donkey\n", ""),
        "import sys; print(sys.executable)": _echo_executable,
        "find_spec('donkeycar')": _donkeycar_only_under("/Users/u/myenv"),
        "--help": (0, "usage: donkey", ""),
    }
    result = _probe(cmds, calls=calls)

    assert result.ok is True
    assert result.platform == "macos"
    assert result.python_path == "/Users/u/myenv/bin/python3"
    assert any("command -v donkey" in c for c in calls)


def test_probe_ssh_failure():
    result = _probe({}, ssh_ok=False)

    assert result.ok is False
    assert result.checks[0].name == "ssh"
    assert result.checks[0].status == "fail"
    assert result.suggestions


def test_probe_macos_autodetect_python():
    cmds = {
        "uname -s": (0, "Darwin\n", ""),
        "sw_vers -productVersion": (0, "26.5\n", ""),
        # no env interpreters discovered remotely -> static list is used
        "/opt/homebrew/bin/python3 -c \"import sys; print(sys.executable)\"": (
            0, "/opt/homebrew/bin/python3\n", ""),
        "find_spec('donkeycar')": (0, "", ""),
        "--help": (0, "usage: donkey", ""),
    }
    result = _probe(cmds, python_path="")

    assert result.ok is True
    assert result.platform == "macos"
    assert result.python_path == "/opt/homebrew/bin/python3"
    platform_check = next(c for c in result.checks if c.name == "platform")
    assert platform_check.status == "ok"
    assert platform_check.message == "检测到远程系统: macOS 26.5"


def test_probe_macos_without_version():
    cmds = {
        "uname -s": (0, "Darwin\n", ""),
        # sw_vers unavailable -> plain "macOS" without a version number
        "sw_vers -productVersion": (1, "", ""),
        "import sys; print(sys.executable)": (0, "/usr/bin/python3\n", ""),
        "find_spec('donkeycar')": (0, "", ""),
        "--help": (0, "usage: donkey", ""),
    }
    result = _probe(cmds, python_path="")

    assert result.ok is True
    assert result.platform == "macos"
    platform_check = next(c for c in result.checks if c.name == "platform")
    assert platform_check.message == "检测到远程系统: macOS"


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
        # every candidate interpreter is usable but none carries donkeycar
        "import sys; print(sys.executable)": (0, "/usr/bin/python3\n", ""),
        "find_spec('donkeycar')": (1, "", "ModuleNotFoundError: No module named 'donkeycar'"),
        "--help": (1, "", ""),
    }
    result = _probe(cmds)

    assert result.ok is False
    # falls back to the first usable interpreter
    assert result.python_path == "/usr/bin/python3"
    names = {c.name: c.status for c in result.checks}
    assert names["python"] == "ok"
    assert names["donkeycar"] == "fail"
    donkeycar_check = next(c for c in result.checks if c.name == "donkeycar")
    assert "pip install" not in donkeycar_check.hint
    assert "手动填写" in donkeycar_check.hint
    assert any("donkeycar" in s for s in result.suggestions)


def test_probe_uses_configured_python_first():
    cmds = {
        "uname -s": (0, "Linux\n", ""),
        # configured path is probed before any discovered/static candidate
        "/custom/python -c \"import sys; print(sys.executable)\"": (0, "/custom/python\n", ""),
        "find_spec('donkeycar')": (0, "", ""),
        "--help": (0, "usage: donkey", ""),
    }
    result = _probe(cmds, python_path="/custom/python")

    assert result.ok is True
    assert result.python_path == "/custom/python"
