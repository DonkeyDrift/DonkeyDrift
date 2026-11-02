#!/usr/bin/env python3

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import tempfile


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_HOST = "dkc@192.168.3.62"
DEFAULT_PYTHON = "/home/dkc/miniconda3/envs/donkey/bin/python"
REMOTE_TEMP_TEMPLATE = "/tmp/donkeydrift-linux-validation.XXXXXXXXXX"
REMOTE_TEMP_PATTERN = re.compile(
    r"^/tmp/donkeydrift-linux-validation\.[A-Za-z0-9]{10}$"
)
TREE_PATTERN = re.compile(r"^(?:[0-9a-fA-F]{40}|[0-9a-fA-F]{64})$")


class ValidationError(Exception):
    pass


def _error_text(value):
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace").strip()
    return (value or "").strip()


def _run(command, **kwargs):
    try:
        return subprocess.run(command, check=True, **kwargs)
    except subprocess.CalledProcessError as exc:
        details = []
        for output in (exc.output, exc.stderr):
            detail = _error_text(output)
            if detail and detail not in details:
                details.append(detail)
        message = (
            f"command failed with exit code {exc.returncode}: "
            f"{shlex.join(str(part) for part in command)}"
        )
        if details:
            message = f"{message}\n" + "\n".join(details)
        raise ValidationError(message) from exc
    except OSError as exc:
        raise ValidationError(
            f"could not execute {shlex.join(str(part) for part in command)}: {exc}"
        ) from exc


def _git(arguments):
    return _run(
        ["git", *arguments],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )


def _git_dir():
    value = _git(["rev-parse", "--git-dir"]).stdout.strip()
    if not value:
        raise ValidationError("git rev-parse --git-dir returned an empty path")
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = REPO_ROOT / path
    return path.resolve()


def _selected_tree(arguments):
    if arguments.staged:
        result = _git(["write-tree"])
    else:
        result = _git(["rev-parse", f"{arguments.commit}^{{tree}}"])
    tree = result.stdout.strip()
    if not TREE_PATTERN.fullmatch(tree):
        raise ValidationError(f"git returned an invalid tree ID: {tree!r}")
    return tree.lower()


def _ssh(host, remote_command, **kwargs):
    return _run(["ssh", "--", host, remote_command], **kwargs)


def _ssh_text(host, remote_command):
    return _ssh(host, remote_command, capture_output=True, text=True)


def _create_remote_directory(host):
    result = _ssh_text(host, f"mktemp -d {REMOTE_TEMP_TEMPLATE}")
    remote_dir = result.stdout.strip()
    if not REMOTE_TEMP_PATTERN.fullmatch(remote_dir):
        raise ValidationError(
            f"unsafe remote temporary directory returned by mktemp: {remote_dir!r}"
        )
    return remote_dir


def _upload_tree(tree, host, remote_dir):
    with tempfile.TemporaryFile(prefix="linux-validation-", suffix=".tar") as archive:
        _run(
            ["git", "archive", "--format=tar", tree],
            cwd=REPO_ROOT,
            stdout=archive,
            stderr=subprocess.PIPE,
        )
        archive.seek(0)
        _ssh(
            host,
            f"tar -x -C {shlex.quote(remote_dir)}",
            stdin=archive,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )


def _test_commands(remote_dir, python):
    directory = shlex.quote(remote_dir)
    interpreter = shlex.quote(python)
    python_bin = shlex.quote(str(Path(python).parent))
    home = shlex.quote(str(Path(remote_dir) / ".home"))
    environment = (
        f"PATH={python_bin}:\"$PATH\" PYTHONPATH={directory} HOME={home}"
    )
    root_command = (
        f"cd {directory} && mkdir -p {home} && "
        f"{environment} {interpreter} -m pytest"
    )
    return [root_command, f"{root_command} web_ui/backend/tests"]


def _remove_remote_directory(host, remote_dir):
    _ssh_text(host, f"rm -rf -- {shlex.quote(remote_dir)}")


def _write_attestation(path, attestation):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
            json.dump(attestation, temporary, indent=2, sort_keys=True)
            temporary.write("\n")
        os.replace(temporary_path, path)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


def _run_validation(arguments):
    host = os.environ.get("DONKEYDRIFT_LINUX_SSH") or DEFAULT_HOST
    python = os.environ.get("DONKEYDRIFT_LINUX_PYTHON") or DEFAULT_PYTHON
    git_dir = _git_dir()
    tree = _selected_tree(arguments)
    remote_dir = _create_remote_directory(host)
    commands = _test_commands(remote_dir, python)

    try:
        _upload_tree(tree, host, remote_dir)
        for command in commands:
            _ssh_text(host, command)
    except BaseException:
        try:
            _remove_remote_directory(host, remote_dir)
        except ValidationError as cleanup_error:
            print(
                f"warning: remote cleanup also failed: {cleanup_error}",
                file=sys.stderr,
            )
        raise
    else:
        _remove_remote_directory(host, remote_dir)

    attestation_path = git_dir / "linux-validation" / f"{tree}.json"
    _write_attestation(
        attestation_path,
        {
            "tree": tree,
            "host": host,
            "time": datetime.now(timezone.utc).isoformat(),
            "commands": commands,
            "status": "passed",
        },
    )
    print(f"Linux validation passed for {tree}: {attestation_path}")
    return 0


def _read_attestation(path, tree):
    if not path.is_file():
        raise ValidationError(f"attestation missing for tree {tree}: {path}")
    try:
        attestation = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValidationError(f"invalid attestation {path}: {exc}") from exc
    if not isinstance(attestation, dict):
        raise ValidationError(f"invalid attestation {path}: expected a JSON object")
    if attestation.get("tree") != tree:
        raise ValidationError(
            f"attestation tree mismatch: expected {tree}, "
            f"found {attestation.get('tree')!r}"
        )
    if attestation.get("status") != "passed":
        raise ValidationError(
            f"Linux validation did not pass for tree {tree}: "
            f"status is {attestation.get('status')!r}"
        )
    if not isinstance(attestation.get("host"), str) or not attestation["host"]:
        raise ValidationError(f"invalid attestation {path}: missing host")
    if not isinstance(attestation.get("time"), str) or not attestation["time"]:
        raise ValidationError(f"invalid attestation {path}: missing time")
    commands = attestation.get("commands")
    if (
        not isinstance(commands, list)
        or not commands
        or not all(isinstance(command, str) and command for command in commands)
    ):
        raise ValidationError(f"invalid attestation {path}: missing commands")
    return attestation


def _check_validation(arguments):
    git_dir = _git_dir()
    tree = _selected_tree(arguments)
    attestation_path = git_dir / "linux-validation" / f"{tree}.json"
    _read_attestation(attestation_path, tree)
    print(f"Linux validation attestation is valid for {tree}: {attestation_path}")
    return 0


def _rerun_hint(arguments):
    selection = ["--staged"] if arguments.staged else ["--commit", arguments.commit]
    return shlex.join(
        ["python", "scripts/linux_validation.py", "run", *selection]
    )


def _parser():
    parser = argparse.ArgumentParser(
        description="Validate an exact Git tree on the DonkeyDrift Linux host."
    )
    subparsers = parser.add_subparsers(dest="action", required=True)
    for action in ("run", "check"):
        subparser = subparsers.add_parser(action)
        selection = subparser.add_mutually_exclusive_group(required=True)
        selection.add_argument("--staged", action="store_true")
        selection.add_argument("--commit", metavar="COMMIT")
    return parser


def main(argv=None):
    arguments = _parser().parse_args(argv)
    try:
        if arguments.action == "run":
            return _run_validation(arguments)
        return _check_validation(arguments)
    except ValidationError as exc:
        print(f"Linux validation error: {exc}", file=sys.stderr)
        print(f"Fix the failure, then run: {_rerun_hint(arguments)}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
