# -*- coding: utf-8 -*-
"""部署诊断（donkeycar/deployment.py，Tony 部署守护）的单元测试。

测试覆盖：
- get_source_head：本地 git 仓库返回 HEAD；非 Git 目录返回 None
- _behind_count：非 Git 目录返回 None（无法判断不告警）
- collect_deployment_warnings：
  * web_instance 登记 source_head 与当前源码不一致 → 提示端口 + 重启
  * web_instance 缺 source_head → 提示重启以确认版本
  * 本地源码落后 origin/Tony → 显示落后数量
  * 车辆 manage.py 与仓库模板 complete.py 不一致 → 提示 donkey update
  * 无 Git 元数据不报警；相等且模板一致返回空列表
"""

import re
import subprocess
from pathlib import Path
from unittest import mock

import pytest

from donkeycar.deployment import (
    _behind_count,
    collect_deployment_warnings,
    get_source_head,
)


# ===========================================================================
# get_source_head / _behind_count：仅本地 Git 元数据，失败静默返回 None
# ===========================================================================

def test_get_source_head_returns_local_head(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "-c", "user.email=t@t",
                    "-c", "user.name=t", "commit", "--allow-empty",
                    "-q", "-m", "init"], check=True)
    head = get_source_head(repo)
    assert head is not None
    assert re.fullmatch(r"[0-9a-f]{7,40}", head)


def test_get_source_head_non_git_dir_returns_none(tmp_path):
    assert get_source_head(tmp_path) is None


def test_get_source_head_missing_dir_returns_none(tmp_path):
    assert get_source_head(tmp_path / "nope") is None


def _git(*args, cwd=None):
    cmd = ["git"]
    if cwd is not None:
        cmd += ["-C", str(cwd)]
    cmd += list(args)
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return result.stdout.strip()


def _init_repo_with_commit(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git("init", "-q", str(repo))
    _git("-c", "user.email=t@t", "-c", "user.name=t",
         "commit", "--allow-empty", "-q", "-m", "init", cwd=repo)
    return repo


def test_get_source_head_matches_git_rev_parse_in_real_repo():
    """本仓库（链接 worktree，.git 为文件）：与 git rev-parse HEAD 一致。"""
    repo_root = Path(__file__).parent.parent
    if get_source_head(repo_root) is None:
        pytest.skip("Linux staged 验证使用不含 .git 的源码归档")
    expected = _git("rev-parse", "HEAD", cwd=repo_root)
    assert get_source_head() == expected


def test_get_source_head_matches_git_rev_parse_in_fresh_repo(tmp_path):
    repo = _init_repo_with_commit(tmp_path)
    assert get_source_head(repo) == _git("rev-parse", "HEAD", cwd=repo)


def test_get_source_head_resolves_packed_refs(tmp_path):
    """loose ref 被 pack-refs 收进 packed-refs 后仍能解析出同一提交。"""
    repo = _init_repo_with_commit(tmp_path)
    _git("pack-refs", "--all", "--prune", cwd=repo)
    assert get_source_head(repo) == _git("rev-parse", "HEAD", cwd=repo)


def test_get_source_head_detached_head(tmp_path):
    repo = _init_repo_with_commit(tmp_path)
    _git("checkout", "-q", "--detach", cwd=repo)
    assert get_source_head(repo) == _git("rev-parse", "HEAD", cwd=repo)


def test_get_source_head_linked_worktree(tmp_path):
    """链接 worktree（.git 文件 + commondir 间接）：与 rev-parse 一致。"""
    main = _init_repo_with_commit(tmp_path)
    linked = tmp_path / "linked"
    _git("worktree", "add", "-q", "-b", "wt-branch", str(linked), cwd=main)
    assert get_source_head(linked) == _git("rev-parse", "HEAD", cwd=linked)


def test_behind_count_non_git_dir_returns_none(tmp_path):
    assert _behind_count(tmp_path) is None


def test_behind_count_missing_base_branch_returns_none(tmp_path):
    """有 HEAD 但本地没有 origin/Tony 引用（未 fetch 过）：无法判断返回 None。"""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "-c", "user.email=t@t",
                    "-c", "user.name=t", "commit", "--allow-empty",
                    "-q", "-m", "init"], check=True)
    assert _behind_count(repo) is None


# ===========================================================================
# collect_deployment_warnings：Web 登记 / 落后分支 / 模板错配
# ===========================================================================

def test_warns_when_running_web_predates_current_source():
    with mock.patch("donkeycar.deployment.get_source_head", return_value="new"), \
         mock.patch("donkeycar.deployment._behind_count", return_value=0):
        warnings = collect_deployment_warnings(
            repo_root="/repo", web_instance={"source_head": "old"})
    assert any("8000" in item and "重启" in item for item in warnings)


def test_web_warning_uses_registered_backend_port():
    with mock.patch("donkeycar.deployment.get_source_head", return_value="new"), \
         mock.patch("donkeycar.deployment._behind_count", return_value=0):
        warnings = collect_deployment_warnings(
            repo_root="/repo",
            web_instance={"source_head": "old", "backend_port": 8001})
    assert any("8001" in item and "重启" in item for item in warnings)


def test_warns_when_web_instance_lacks_source_head():
    """登记存在但没有 source_head（旧代码启动）：提示重启以确认版本。"""
    with mock.patch("donkeycar.deployment.get_source_head", return_value=None):
        warnings = collect_deployment_warnings(
            repo_root="/repo",
            web_instance={"pid": 1, "backend_port": 8000,
                          "frontend_port": 5188})
    assert any("8000" in item and "重启" in item for item in warnings)


def test_behind_origin_tony_warning_shows_count():
    with mock.patch("donkeycar.deployment.get_source_head",
                    return_value="abc123"), \
         mock.patch("donkeycar.deployment._behind_count", return_value=3):
        warnings = collect_deployment_warnings(repo_root="/repo")
    assert any("3" in item and "origin/Tony" in item for item in warnings)


def test_warns_when_manage_differs_from_current_template(tmp_path):
    repo = tmp_path / "repo"
    car = tmp_path / "car"
    (repo / "donkeycar/templates").mkdir(parents=True)
    car.mkdir()
    (repo / "donkeycar/templates/complete.py").write_text("new")
    (car / "manage.py").write_text("old")
    with mock.patch("donkeycar.deployment.get_source_head", return_value=None):
        warnings = collect_deployment_warnings(car_path=car, repo_root=repo)
    assert any("manage.py" in item and "donkey update" in item for item in warnings)


def test_no_warning_when_manage_missing_or_template_missing(tmp_path):
    """任一文件缺失（车辆未初始化/包不完整）无法比较，不告警。"""
    repo = tmp_path / "repo"
    car = tmp_path / "car"
    (repo / "donkeycar/templates").mkdir(parents=True)
    car.mkdir()
    with mock.patch("donkeycar.deployment.get_source_head", return_value=None):
        assert collect_deployment_warnings(car_path=car, repo_root=repo) == []


def test_no_warnings_without_git_metadata(tmp_path):
    """无 Git 元数据（HEAD 取不到）：不落后告警；模板一致也不告警。"""
    repo = tmp_path / "repo"
    car = tmp_path / "car"
    (repo / "donkeycar/templates").mkdir(parents=True)
    car.mkdir()
    (repo / "donkeycar/templates/complete.py").write_text("same")
    (car / "manage.py").write_text("same")
    with mock.patch("donkeycar.deployment.get_source_head", return_value=None), \
         mock.patch("donkeycar.deployment._behind_count", return_value=None):
        assert collect_deployment_warnings(car_path=car, repo_root=repo) == []


def test_empty_list_when_up_to_date_and_template_matches(tmp_path):
    repo = tmp_path / "repo"
    car = tmp_path / "car"
    (repo / "donkeycar/templates").mkdir(parents=True)
    car.mkdir()
    (repo / "donkeycar/templates/complete.py").write_text("same")
    (car / "manage.py").write_text("same")
    with mock.patch("donkeycar.deployment.get_source_head",
                    return_value="same"), \
         mock.patch("donkeycar.deployment._behind_count", return_value=0):
        warnings = collect_deployment_warnings(
            car_path=car, repo_root=repo,
            web_instance={"source_head": "same", "backend_port": 8000})
    assert warnings == []
