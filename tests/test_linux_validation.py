import datetime as dt
import importlib.util
import json
from pathlib import Path
import subprocess

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = PROJECT_ROOT / "scripts" / "linux_validation.py"
SPEC = importlib.util.spec_from_file_location("linux_validation", MODULE_PATH)
linux_validation = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(linux_validation)

TREE = "a" * 40
OTHER_TREE = "b" * 40
REMOTE_DIR = "/tmp/donkeydrift-linux-validation.Abc123XYZ0"
DEFAULT_HOST = "dkc@192.168.3.62"
DEFAULT_PYTHON = "/home/dkc/miniconda3/envs/donkey/bin/python"


def expected_test_command(python=DEFAULT_PYTHON, backend=False):
    home = f"{REMOTE_DIR}/.home"
    python_bin = str(Path(python).parent)
    command = (
        f"cd {REMOTE_DIR} && mkdir -p {home} && "
        f"PATH={python_bin}:\"$PATH\" PYTHONPATH={REMOTE_DIR} HOME={home} "
        f"{python} -m pytest"
    )
    if backend:
        command += " web_ui/backend/tests"
    return command


ROOT_TEST_COMMAND = expected_test_command()
BACKEND_TEST_COMMAND = expected_test_command(backend=True)


class FakeExternalProcesses:
    def __init__(self, tmp_path):
        self.tmp_path = tmp_path
        self.git_dir = tmp_path / ".git"
        self.remote_dir = REMOTE_DIR
        self.fail_phase = None
        self.calls = []

    @property
    def attestation_path(self):
        return self.git_dir / "linux-validation" / f"{TREE}.json"

    @property
    def commands(self):
        return [call[0] for call in self.calls]

    @property
    def remote_commands(self):
        return [call[0][-1] for call in self.calls if call[0][0] == "ssh"]

    def __call__(self, args, **kwargs):
        args = list(args)
        self.calls.append((args, kwargs))
        assert not kwargs.get("shell", False)

        if args == ["git", "rev-parse", "--git-dir"]:
            return self._completed(args, stdout=f"{self.git_dir}\n")
        if args == ["git", "write-tree"]:
            return self._completed(args, stdout=f"{TREE}\n")
        if (
            len(args) == 3
            and args[:2] == ["git", "rev-parse"]
            and args[2].endswith("^{tree}")
        ):
            return self._completed(args, stdout=f"{TREE}\n")
        if args == ["git", "archive", "--format=tar", TREE]:
            kwargs["stdout"].write(b"exact tree archive")
            return self._completed(args)

        if args[0] != "ssh" or len(args) != 4:
            raise AssertionError(f"unexpected command: {args!r}")

        remote_command = args[-1]
        if remote_command == (
            "mktemp -d /tmp/donkeydrift-linux-validation.XXXXXXXXXX"
        ):
            return self._completed(args, stdout=f"{self.remote_dir}\n")
        if remote_command == f"tar -x -C {self.remote_dir}":
            assert kwargs["stdin"].read() == b"exact tree archive"
            if self.fail_phase == "upload":
                return self._fail(args, "archive upload failed", kwargs)
            return self._completed(args)
        if remote_command.endswith(" -m pytest web_ui/backend/tests"):
            if self.fail_phase == "backend":
                return self._fail(args, "backend pytest failed", kwargs)
            return self._completed(args)
        if remote_command.endswith(" -m pytest"):
            if self.fail_phase == "root":
                return self._fail(args, "root pytest failed", kwargs)
            return self._completed(args)
        if remote_command == f"rm -rf -- {self.remote_dir}":
            return self._completed(args)
        raise AssertionError(f"unexpected SSH command: {remote_command!r}")

    @staticmethod
    def _completed(args, stdout="", stderr=""):
        return subprocess.CompletedProcess(args, 0, stdout=stdout, stderr=stderr)

    @staticmethod
    def _fail(args, message, kwargs):
        if kwargs.get("check"):
            raise subprocess.CalledProcessError(
                1, args, output="", stderr=message
            )
        return subprocess.CompletedProcess(args, 1, stdout="", stderr=message)


def test_command_failure_reports_stdout_and_stderr(monkeypatch):
    def fail(command, **kwargs):
        raise subprocess.CalledProcessError(
            1,
            command,
            output="pytest failure summary",
            stderr="shutdown logging",
        )

    monkeypatch.setattr(linux_validation.subprocess, "run", fail)

    with pytest.raises(linux_validation.ValidationError) as caught:
        linux_validation._run(["dummy-command"])

    message = str(caught.value)
    assert "pytest failure summary" in message
    assert "shutdown logging" in message


@pytest.fixture
def external(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    processes = FakeExternalProcesses(tmp_path)
    monkeypatch.setattr(linux_validation.subprocess, "run", processes)
    return processes


def write_attestation(external, **overrides):
    attestation = {
        "tree": TREE,
        "host": DEFAULT_HOST,
        "time": "2026-10-30T12:00:00+00:00",
        "commands": [ROOT_TEST_COMMAND, BACKEND_TEST_COMMAND],
        "status": "passed",
    }
    attestation.update(overrides)
    external.attestation_path.parent.mkdir(parents=True, exist_ok=True)
    external.attestation_path.write_text(json.dumps(attestation), encoding="utf-8")


def test_run_staged_validates_exact_tree_and_writes_attestation(external, capsys):
    result = linux_validation.main(["run", "--staged"])

    assert result == 0
    assert ["git", "write-tree"] in external.commands
    assert ["git", "archive", "--format=tar", TREE] in external.commands
    assert external.remote_commands == [
        "mktemp -d /tmp/donkeydrift-linux-validation.XXXXXXXXXX",
        f"tar -x -C {REMOTE_DIR}",
        ROOT_TEST_COMMAND,
        BACKEND_TEST_COMMAND,
        f"rm -rf -- {REMOTE_DIR}",
    ]
    assert all(
        "/home/dkc/projects/DonkeyDrift" not in command
        for command in external.remote_commands
    )

    attestation = json.loads(external.attestation_path.read_text(encoding="utf-8"))
    assert attestation["tree"] == TREE
    assert attestation["host"] == DEFAULT_HOST
    assert attestation["status"] == "passed"
    assert attestation["commands"] == [ROOT_TEST_COMMAND, BACKEND_TEST_COMMAND]
    assert dt.datetime.fromisoformat(attestation["time"]).tzinfo is not None
    assert TREE in capsys.readouterr().out


def test_run_commit_uses_commit_tree_and_environment_overrides(
    external, monkeypatch
):
    monkeypatch.setenv("DONKEYDRIFT_LINUX_SSH", "builder@example.test")
    monkeypatch.setenv("DONKEYDRIFT_LINUX_PYTHON", "/opt/donkey/bin/python")

    result = linux_validation.main(["run", "--commit", "HEAD"])

    assert result == 0
    assert ["git", "rev-parse", "HEAD^{tree}"] in external.commands
    assert ["git", "write-tree"] not in external.commands
    assert ["git", "archive", "--format=tar", TREE] in external.commands
    assert all(
        command[2] == "builder@example.test"
        for command in external.commands
        if command[0] == "ssh"
    )
    attestation = json.loads(external.attestation_path.read_text(encoding="utf-8"))
    assert attestation["host"] == "builder@example.test"
    assert attestation["commands"] == [
        expected_test_command("/opt/donkey/bin/python"),
        expected_test_command("/opt/donkey/bin/python", backend=True),
    ]


def test_check_staged_accepts_matching_attestation_without_ssh(external):
    write_attestation(external)

    result = linux_validation.main(["check", "--staged"])

    assert result == 0
    assert all(command[0] == "git" for command in external.commands)
    assert not any(
        command[:2] == ["git", "archive"] for command in external.commands
    )


def test_check_commit_uses_commit_tree_for_attestation_lookup(external):
    write_attestation(external)

    result = linux_validation.main(["check", "--commit", "v1.2.3"])

    assert result == 0
    assert ["git", "rev-parse", "v1.2.3^{tree}"] in external.commands


def test_check_missing_attestation_is_actionable(external, capsys):
    result = linux_validation.main(["check", "--staged"])

    assert result != 0
    error = capsys.readouterr().err
    assert "missing" in error.lower()
    assert "run --staged" in error


def test_check_failed_attestation_is_rejected(external, capsys):
    write_attestation(external, status="failed")

    result = linux_validation.main(["check", "--staged"])

    assert result != 0
    error = capsys.readouterr().err
    assert "did not pass" in error
    assert "run --staged" in error


def test_check_tree_mismatch_is_rejected(external, capsys):
    write_attestation(external, tree=OTHER_TREE)

    result = linux_validation.main(["check", "--staged"])

    assert result != 0
    error = capsys.readouterr().err
    assert "tree mismatch" in error
    assert TREE in error
    assert OTHER_TREE in error
    assert "run --staged" in error


def test_check_malformed_attestation_is_actionable(external, capsys):
    external.attestation_path.parent.mkdir(parents=True, exist_ok=True)
    external.attestation_path.write_text("not json", encoding="utf-8")

    result = linux_validation.main(["check", "--staged"])

    assert result != 0
    error = capsys.readouterr().err
    assert "invalid" in error.lower()
    assert "run --staged" in error


@pytest.mark.parametrize("phase", ["root", "backend"])
def test_failed_remote_pytest_cleans_up_and_writes_no_attestation(
    external, phase, capsys
):
    external.fail_phase = phase

    result = linux_validation.main(["run", "--staged"])

    assert result != 0
    assert not external.attestation_path.exists()
    assert external.remote_commands[-1] == f"rm -rf -- {REMOTE_DIR}"
    error = capsys.readouterr().err
    assert f"{phase} pytest failed" in error
    assert "run --staged" in error


def test_failed_archive_upload_cleans_up_without_running_pytest(external):
    external.fail_phase = "upload"

    result = linux_validation.main(["run", "--staged"])

    assert result != 0
    assert not external.attestation_path.exists()
    assert external.remote_commands[-1] == f"rm -rf -- {REMOTE_DIR}"
    assert not any(" -m pytest" in command for command in external.remote_commands)


def test_remote_commands_expose_console_and_isolate_project_configuration():
    commands = linux_validation._test_commands(REMOTE_DIR, DEFAULT_PYTHON)

    for command in commands:
        assert 'PATH=/home/dkc/miniconda3/envs/donkey/bin:"$PATH"' in command
        assert f"PYTHONPATH={REMOTE_DIR}" in command
        assert f"HOME={REMOTE_DIR}/.home" in command
        assert f"mkdir -p {REMOTE_DIR}/.home" in command


def test_remote_python_is_shell_quoted(external, monkeypatch):
    monkeypatch.setenv("DONKEYDRIFT_LINUX_PYTHON", "/tmp/python;touch /tmp/pwned")

    result = linux_validation.main(["run", "--staged"])

    assert result == 0
    assert any(
        "'/tmp/python;touch /tmp/pwned' -m pytest" in command
        for command in external.remote_commands
    )


def test_unsafe_remote_temp_path_is_rejected_without_cleanup(external, capsys):
    external.remote_dir = "/tmp/unsafe;rm -rf /"

    result = linux_validation.main(["run", "--staged"])

    assert result != 0
    assert not external.attestation_path.exists()
    assert not any(command.startswith("rm ") for command in external.remote_commands)
    assert "unsafe remote temporary directory" in capsys.readouterr().err


def test_cli_rejects_ambiguous_tree_selection(external):
    with pytest.raises(SystemExit) as exc_info:
        linux_validation.main(["run", "--staged", "--commit", "HEAD"])

    assert exc_info.value.code == 2
    assert external.calls == []
