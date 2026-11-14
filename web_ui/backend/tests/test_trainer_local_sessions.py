# -*- coding: utf-8 -*-
"""本地训练按录制会话筛选：LocalTrainRequest.session_ids/session_filter →
run_local 的 --session-filter 临时 JSON 文件（job 结束后 finally 清理）。

覆盖：
(a) 不带 session_ids 时训练命令无 --session-filter；
(b) 带 session_ids 时命令行带该参数、JSON 内容为平坦字符串列表；
(c) 临时文件在 job 结束后被清理（含子进程启动失败路径）；
(d) 路由层把 session_ids 原样传给 run_local，缺省为 None；
(e) session_filter（grouped dict {tub: [sid,...]}）原样写入 JSON，且优先于
    平坦 session_ids；
(f) 路由层训练前对 tub 做家族展开（_discover_family_tubs）：data/ 自身是
    tub 且含子 tub 时展开为逗号分隔绝对路径；发现异常/为空回退原样透传；
(g) 路由层把 session_filter 原样传给 run_local。
"""
import asyncio
import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def _build_client():
    from routers import trainer as trainer_router

    app = FastAPI()
    app.include_router(trainer_router.router, prefix="/api/trainer")
    return TestClient(app)


class _FakeStream:
    async def readline(self):
        return b''


class _FakeProc:
    def __init__(self, returncode=0):
        self.stdout = _FakeStream()
        self.stderr = _FakeStream()
        self.returncode = None
        self._returncode = returncode

    async def wait(self):
        self.returncode = self._returncode

    def terminate(self):
        pass


def _run_local(monkeypatch, tmp_path, job_id='job-sess', **kwargs):
    """以假子进程执行 run_local 到结束，返回 (job, captured)。"""
    from trainer_engine import TrainingJob, job_manager

    captured = {}

    async def fake_exec(*cmd, **kw):
        captured['cmd'] = list(cmd)
        captured['cwd'] = kw.get('cwd')
        return _FakeProc()

    monkeypatch.setattr(asyncio, 'create_subprocess_exec', fake_exec)

    job = TrainingJob(id=job_id, mode='local')
    asyncio.run(job_manager.run_local(
        job, tub='./data', model='./models/m', model_type='linear',
        working_dir=str(tmp_path), **kwargs))
    return job, captured


def test_run_local_without_session_ids_has_no_filter_flag(tmp_path, monkeypatch):
    job, captured = _run_local(monkeypatch, tmp_path)
    assert '--session-filter' not in captured['cmd']
    assert job.status == 'completed'


def test_run_local_with_session_ids_passes_filter_file(tmp_path, monkeypatch):
    job, captured = _run_local(
        monkeypatch, tmp_path, job_id='job-f1',
        session_ids=['26-10-20_0', '26-10-21_0'])

    assert job.status == 'completed'
    assert '--session-filter' in captured['cmd']
    filter_path = Path(captured['cmd'][captured['cmd'].index('--session-filter') + 1])
    assert filter_path.parent == tmp_path
    assert filter_path.name == '.train_session_filter_job-f1.json'
    # 临时文件在 job 结束（finally 路径）已被清理
    assert not filter_path.exists()


def test_run_local_session_filter_file_content_and_str_conversion(tmp_path, monkeypatch):
    seen = {}

    async def fake_exec(*cmd, **kw):
        # 子进程拉起瞬间读取 JSON 内容（run_local 结束后文件即被清理）
        filter_path = Path(cmd[cmd.index('--session-filter') + 1])
        seen['content'] = json.loads(filter_path.read_text(encoding='utf-8'))
        return _FakeProc()

    monkeypatch.setattr(asyncio, 'create_subprocess_exec', fake_exec)

    from trainer_engine import TrainingJob, job_manager

    job = TrainingJob(id='job-f2', mode='local')
    asyncio.run(job_manager.run_local(
        job, tub='./data', model='./models/m', model_type='linear',
        working_dir=str(tmp_path), session_ids=['26-10-20_0', 123]))

    assert job.status == 'completed'
    assert seen['content'] == ['26-10-20_0', '123']


def test_run_local_empty_session_ids_means_no_filter(tmp_path, monkeypatch):
    job, captured = _run_local(monkeypatch, tmp_path, session_ids=[])
    assert '--session-filter' not in captured['cmd']
    assert list(tmp_path.iterdir()) == []


def test_run_local_cleans_filter_file_when_subprocess_start_fails(tmp_path, monkeypatch):
    """子进程启动抛异常（except 路径）时，临时文件同样在 finally 被清理。"""

    async def fake_exec(*cmd, **kw):
        raise OSError('spawn failed')

    monkeypatch.setattr(asyncio, 'create_subprocess_exec', fake_exec)

    from trainer_engine import TrainingJob, job_manager

    job = TrainingJob(id='job-f3', mode='local')
    asyncio.run(job_manager.run_local(
        job, tub='./data', model='./models/m', model_type='linear',
        working_dir=str(tmp_path), session_ids=['26-10-20_0']))

    assert job.status == 'failed'
    assert 'spawn failed' in (job.error_message or '')
    assert list(tmp_path.iterdir()) == []


def test_local_route_passes_session_ids_to_run_local():
    from trainer_engine import TrainingJob

    captured = {}

    def fake_run_local(job, tub, model, model_type, transfer=None,
                       working_dir=None, session_ids=None, session_filter=None):
        captured['job'] = job
        captured['session_ids'] = session_ids
        captured['working_dir'] = working_dir

    with _build_client() as client, \
         patch('trainer_engine.job_manager.run_local',
               side_effect=fake_run_local):
        resp = client.post("/api/trainer/train/local", json={
            "tub": "./data",
            "model": "./models/m",
            "session_ids": ["26-10-20_0", "26-10-21_0"],
        })

    assert resp.status_code == 200
    job: TrainingJob = captured['job']
    assert job.id == resp.json()["job_id"]
    assert job.mode == "local"
    assert captured['session_ids'] == ["26-10-20_0", "26-10-21_0"]


def test_local_route_defaults_session_ids_to_none():
    captured = {}

    def fake_run_local(job, tub, model, model_type, transfer=None,
                       working_dir=None, session_ids=None, session_filter=None):
        captured['session_ids'] = session_ids
        captured['session_filter'] = session_filter

    with _build_client() as client, \
         patch('trainer_engine.job_manager.run_local',
               side_effect=fake_run_local):
        resp = client.post("/api/trainer/train/local", json={
            "tub": "./data",
            "model": "./models/m",
        })

    assert resp.status_code == 200
    assert captured['session_ids'] is None
    assert captured['session_filter'] is None


def test_run_local_grouped_session_filter_writes_dict(tmp_path, monkeypatch):
    """grouped session_filter（{tub绝对路径: [sid,...]}）原样写入临时 JSON。"""
    seen = {}

    async def fake_exec(*cmd, **kw):
        filter_path = Path(cmd[cmd.index('--session-filter') + 1])
        seen['content'] = json.loads(filter_path.read_text(encoding='utf-8'))
        return _FakeProc()

    monkeypatch.setattr(asyncio, 'create_subprocess_exec', fake_exec)

    from trainer_engine import TrainingJob, job_manager

    grouped = {'/abs/data': ['26-10-23_0'], '/abs/data/tub_1_26-10-23': ['26-10-23_0', 'a']}
    job = TrainingJob(id='job-g1', mode='local')
    asyncio.run(job_manager.run_local(
        job, tub='/abs/data,/abs/data/tub_1_26-10-23', model='./models/m',
        model_type='linear', working_dir=str(tmp_path), session_filter=grouped))

    assert job.status == 'completed'
    assert seen['content'] == grouped
    # 临时文件在 job 结束（finally 路径）已被清理
    assert list(tmp_path.iterdir()) == []


def test_run_local_grouped_filter_takes_priority_over_flat_ids(tmp_path, monkeypatch):
    """session_filter 与 session_ids 同时给时以 grouped dict 为准。"""
    seen = {}

    async def fake_exec(*cmd, **kw):
        filter_path = Path(cmd[cmd.index('--session-filter') + 1])
        seen['content'] = json.loads(filter_path.read_text(encoding='utf-8'))
        return _FakeProc()

    monkeypatch.setattr(asyncio, 'create_subprocess_exec', fake_exec)

    from trainer_engine import TrainingJob, job_manager

    job = TrainingJob(id='job-g2', mode='local')
    asyncio.run(job_manager.run_local(
        job, tub='./data', model='./models/m', model_type='linear',
        working_dir=str(tmp_path),
        session_ids=['flat_0'],
        session_filter={'/abs/data': ['26-10-23_0']}))

    assert job.status == 'completed'
    assert seen['content'] == {'/abs/data': ['26-10-23_0']}


def _make_fake_tub(path: Path) -> None:
    """家族展开只校验 manifest.json 存在性，无需真实 catalog。"""
    path.mkdir(parents=True, exist_ok=True)
    (path / 'manifest.json').write_text('{}', encoding='utf-8')


def test_local_route_expands_tub_family_to_absolute_members(tmp_path, monkeypatch):
    """tub=./data（相对路径）训练前展开为家族成员 tub 逗号分隔绝对路径。

    家族布局回归：data/ 自身是 tub 且含 tub_序号_日期 子目录时，不展开则
    CLI 只加载根 tub，子 tub 数据完全不参与训练。
    """
    _make_fake_tub(tmp_path / 'data')
    _make_fake_tub(tmp_path / 'data' / 'tub_1_26-10-23')
    _make_fake_tub(tmp_path / 'data' / 'tub_2_26-10-23')

    captured = {}

    def fake_run_local(job, tub, model, model_type, transfer=None,
                       working_dir=None, session_ids=None, session_filter=None):
        captured['tub'] = tub

    with _build_client() as client, \
         patch('trainer_engine.job_manager.run_local',
               side_effect=fake_run_local):
        resp = client.post("/api/trainer/train/local", json={
            "tub": "./data",
            "model": "./models/m",
            "working_dir": str(tmp_path),
        })

    assert resp.status_code == 200
    members = captured['tub'].split(',')
    assert set(members) == {
        os.path.abspath(tmp_path / 'data'),
        os.path.abspath(tmp_path / 'data' / 'tub_1_26-10-23'),
        os.path.abspath(tmp_path / 'data' / 'tub_2_26-10-23'),
    }
    # 展开结果全部是绝对路径
    assert all(os.path.isabs(m) for m in members)


def test_local_route_family_expansion_failure_falls_back_passthrough(tmp_path, monkeypatch):
    """家族发现抛异常时回退原样透传，训练不被展开逻辑拖垮。"""
    def boom(path):
        raise RuntimeError('disk gone')

    monkeypatch.setattr('routers.tub._discover_family_tubs', boom)

    captured = {}

    def fake_run_local(job, tub, model, model_type, transfer=None,
                       working_dir=None, session_ids=None, session_filter=None):
        captured['tub'] = tub

    with _build_client() as client, \
         patch('trainer_engine.job_manager.run_local',
               side_effect=fake_run_local):
        resp = client.post("/api/trainer/train/local", json={
            "tub": "./data",
            "model": "./models/m",
            "working_dir": str(tmp_path),
        })

    assert resp.status_code == 200
    assert captured['tub'] == './data'


def test_local_route_family_expansion_empty_falls_back_passthrough(tmp_path, monkeypatch):
    """tub 路径不存在（成员为空）时回退原样透传。"""

    captured = {}

    def fake_run_local(job, tub, model, model_type, transfer=None,
                       working_dir=None, session_ids=None, session_filter=None):
        captured['tub'] = tub

    with _build_client() as client, \
         patch('trainer_engine.job_manager.run_local',
               side_effect=fake_run_local):
        resp = client.post("/api/trainer/train/local", json={
            "tub": "./no_such_dir",
            "model": "./models/m",
            "working_dir": str(tmp_path),
        })

    assert resp.status_code == 200
    assert captured['tub'] == './no_such_dir'


def test_local_route_passes_grouped_session_filter_to_run_local():
    captured = {}

    def fake_run_local(job, tub, model, model_type, transfer=None,
                       working_dir=None, session_ids=None, session_filter=None):
        captured['session_filter'] = session_filter

    grouped = {'/abs/data': ['26-10-23_0'], '/abs/data/tub_1_26-10-23': ['26-10-23_0']}
    with _build_client() as client, \
         patch('trainer_engine.job_manager.run_local',
               side_effect=fake_run_local):
        resp = client.post("/api/trainer/train/local", json={
            "tub": "./data",
            "model": "./models/m",
            "session_filter": grouped,
        })

    assert resp.status_code == 200
    assert captured['session_filter'] == grouped
