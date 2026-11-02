import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
HOOKS_DIR = REPO_ROOT / ".githooks"

VALIDATOR = '''import json
import os
import sys

args = sys.argv[1:]
with open(os.environ["VALIDATION_LOG"], "a", encoding="utf-8") as log:
    log.write(json.dumps(args) + "\\n")

failed = os.environ.get("VALIDATION_FAIL_ALL") == "1"
failed = failed or (
    os.environ.get("VALIDATION_FAIL_STAGED") == "1"
    and args == ["check", "--staged"]
)
failed = failed or (
    len(args) == 3
    and args[:2] == ["check", "--commit"]
    and args[2] == os.environ.get("VALIDATION_FAIL_SHA")
)
if failed:
    print("credential missing or stale", file=sys.stderr)
    raise SystemExit(1)
'''


def git(repo, *args, env=None, cwd=None):
    process_env = os.environ.copy()
    process_env.update(
        {
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
            "VALIDATION_LOG": str(repo / ".git" / "validation-test.log"),
        }
    )
    if env:
        process_env.update(env)
    return subprocess.run(
        ["git", *args],
        cwd=cwd or repo,
        env=process_env,
        text=True,
        capture_output=True,
        check=False,
    )


def git_ok(repo, *args, env=None, cwd=None):
    result = git(repo, *args, env=env, cwd=cwd)
    assert result.returncode == 0, result.stdout + result.stderr
    return result


def make_repo(tmp_path, *hook_names):
    remote = tmp_path / "remote.git"
    repo = tmp_path / "work"
    init_env = os.environ.copy()
    init_env.update({"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"})
    subprocess.run(
        ["git", "init", "--bare", str(remote)],
        env=init_env,
        text=True,
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "init", "-b", "main", str(repo)],
        env=init_env,
        text=True,
        capture_output=True,
        check=True,
    )
    git_ok(repo, "config", "user.name", "Hook Test")
    git_ok(repo, "config", "user.email", "hook-test@example.com")
    git_ok(repo, "remote", "add", "origin", str(remote))

    scripts = repo / "scripts"
    scripts.mkdir()
    (scripts / "linux_validation.py").write_text(VALIDATOR, encoding="utf-8")

    for hook_name in hook_names:
        source = HOOKS_DIR / hook_name
        assert source.is_file(), f"{hook_name} hook is missing"
        shutil.copy2(source, repo / ".git" / "hooks" / hook_name)
    return repo, remote


def make_commit(repo, subject, env=None, cwd=None, check=True):
    with (repo / "tracked.txt").open("a", encoding="utf-8") as tracked:
        tracked.write(subject + "\n")
    git_ok(repo, "add", "--", str(repo / "tracked.txt"), cwd=cwd)
    result = git(repo, "commit", "-m", subject, env=env, cwd=cwd)
    if not check:
        return result
    assert result.returncode == 0, result.stdout + result.stderr
    return git_ok(repo, "rev-parse", "HEAD").stdout.strip()


def validation_calls(repo):
    log = repo / ".git" / "validation-test.log"
    if not log.exists():
        return []
    return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]


def clear_validation_calls(repo):
    log = repo / ".git" / "validation-test.log"
    if log.exists():
        log.unlink()


def seed_remote_main(repo):
    base = make_commit(repo, "chore: base")
    git_ok(repo, "push", "origin", "main")
    clear_validation_calls(repo)
    return base


@pytest.mark.parametrize(
    "subject",
    ["feat: add mode", "feat(ui): add mode", "feat!: change mode", "feat(ui)!: change mode"],
)
def test_commit_msg_checks_staged_credential_for_feature_subjects(tmp_path, subject):
    repo, _ = make_repo(tmp_path, "commit-msg")
    subdirectory = repo / "nested"
    subdirectory.mkdir()

    make_commit(repo, subject, cwd=subdirectory)

    assert validation_calls(repo) == [["check", "--staged"]]


@pytest.mark.parametrize("subject", ["fix: repair mode", "feature: document mode"])
def test_commit_msg_allows_non_feature_commits_without_validation(tmp_path, subject):
    repo, _ = make_repo(tmp_path, "commit-msg")

    make_commit(repo, subject, env={"VALIDATION_FAIL_STAGED": "1"})

    assert validation_calls(repo) == []


def test_commit_msg_rejects_feature_commit_without_current_credential(tmp_path):
    repo, _ = make_repo(tmp_path, "commit-msg")
    base = make_commit(repo, "chore: base")

    result = make_commit(
        repo,
        "feat: unverified mode",
        env={"VALIDATION_FAIL_STAGED": "1"},
        check=False,
    )

    assert result.returncode != 0
    assert "run --staged" in result.stdout + result.stderr
    assert git_ok(repo, "rev-parse", "HEAD").stdout.strip() == base
    assert validation_calls(repo) == [["check", "--staged"]]


def test_pre_push_checks_every_feature_commit_in_update_range(tmp_path):
    repo, _ = make_repo(tmp_path, "pre-push")
    seed_remote_main(repo)
    first = make_commit(repo, "feat: first")
    make_commit(repo, "fix: intermediate")
    second = make_commit(repo, "feat(api)!: second")

    git_ok(repo, "push", "origin", "main")

    calls = validation_calls(repo)
    assert len(calls) == 2
    assert {tuple(call) for call in calls} == {
        ("check", "--commit", first),
        ("check", "--commit", second),
    }


def test_pre_push_new_branch_excludes_commits_already_on_remote(tmp_path):
    repo, _ = make_repo(tmp_path, "pre-push")
    seed_remote_main(repo)
    git_ok(repo, "checkout", "-b", "topic")
    feature = make_commit(repo, "feat(topic): branch mode")
    tip = make_commit(repo, "docs: describe branch mode")
    subdirectory = repo / "nested"
    subdirectory.mkdir()

    git_ok(repo, "push", "origin", "topic", cwd=subdirectory)

    assert validation_calls(repo) == [
        ["check", "--commit", feature],
        ["check", "--commit", tip],
    ]


def test_pre_push_allows_non_feature_push_without_validation(tmp_path):
    repo, _ = make_repo(tmp_path, "pre-push")
    make_commit(repo, "fix: repair mode")

    git_ok(repo, "push", "origin", "main", env={"VALIDATION_FAIL_ALL": "1"})

    assert validation_calls(repo) == []


def test_pre_push_allows_branch_deletion_without_validation(tmp_path):
    repo, _ = make_repo(tmp_path, "pre-push")
    seed_remote_main(repo)
    git_ok(repo, "branch", "topic")
    git_ok(repo, "push", "origin", "topic")
    clear_validation_calls(repo)

    git_ok(repo, "push", "origin", ":topic", env={"VALIDATION_FAIL_ALL": "1"})

    assert validation_calls(repo) == []


def test_pre_push_checks_shared_commit_only_once_across_refs(tmp_path):
    repo, _ = make_repo(tmp_path, "pre-push")
    feature = make_commit(repo, "feat: shared mode")

    git_ok(repo, "push", "origin", "main:one", "main:two")

    assert validation_calls(repo) == [["check", "--commit", feature]]


def test_pre_push_rejects_feature_commit_without_credential(tmp_path):
    repo, remote = make_repo(tmp_path, "pre-push")
    base = seed_remote_main(repo)
    feature = make_commit(repo, "feat: unverified mode")

    result = git(repo, "push", "origin", "main", env={"VALIDATION_FAIL_SHA": feature})

    assert result.returncode != 0
    assert f"run --commit {feature}" in result.stdout + result.stderr
    assert validation_calls(repo) == [["check", "--commit", feature]]
    remote_head = git_ok(repo, "--git-dir", str(remote), "rev-parse", "refs/heads/main")
    assert remote_head.stdout.strip() == base


def test_pre_push_new_branch_only_excludes_current_remote_history(tmp_path):
    repo, remote = make_repo(tmp_path, "pre-push")
    seed_remote_main(repo)
    git_ok(repo, "remote", "add", "gitee", str(remote))
    feature = make_commit(repo, "feat: cross remote mode")
    git_ok(repo, "push", "gitee", "main")
    clear_validation_calls(repo)
    tip = make_commit(repo, "docs: describe cross remote mode")

    git_ok(repo, "push", "origin", "main:topic")

    assert validation_calls(repo) == [
        ["check", "--commit", feature],
        ["check", "--commit", tip],
    ]


def test_pre_push_duplicate_feature_still_requires_tip_for_each_ref(tmp_path):
    repo, remote = make_repo(tmp_path, "pre-push")
    seed_remote_main(repo)
    feature = make_commit(repo, "feat: shared feature")
    git_ok(repo, "checkout", "-b", "topic")
    tip = make_commit(repo, "docs: shared feature docs")

    result = git(
        repo,
        "push",
        "origin",
        f"{feature}:refs/heads/one",
        "topic:refs/heads/two",
        env={"VALIDATION_FAIL_SHA": tip},
    )

    assert result.returncode != 0
    assert f"run --commit {tip}" in result.stdout + result.stderr
    assert validation_calls(repo) == [
        ["check", "--commit", feature],
        ["check", "--commit", tip],
    ]


def test_pre_push_requires_validated_tip_after_feature_commit(tmp_path):
    repo, remote = make_repo(tmp_path, "pre-push")
    base = seed_remote_main(repo)
    feature = make_commit(repo, "feat: mode")
    tip = make_commit(repo, "fix: adjust mode")

    result = git(repo, "push", "origin", "main", env={"VALIDATION_FAIL_SHA": tip})

    assert result.returncode != 0
    assert f"run --commit {tip}" in result.stdout + result.stderr
    assert validation_calls(repo) == [
        ["check", "--commit", feature],
        ["check", "--commit", tip],
    ]
    remote_head = git_ok(repo, "--git-dir", str(remote), "rev-parse", "refs/heads/main")
    assert remote_head.stdout.strip() == base
