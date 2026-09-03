import asyncio
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


KERAS3_LINE = " 37/437 ━━━━━━━━━━━━━━━━━━━━ 2s 4ms/step - loss: 0.1234"
KERAS2_LINE = "37/437 [=====>........] - ETA: 2s - loss: 0.1234"

REMOTE_DIR = "/home/u/projects/mycar-260823-001-ABCD"
OLD_MODEL = "mycar-model-260823-ABCD"


def _build_client():
    from routers import trainer as trainer_router

    app = FastAPI()
    app.include_router(trainer_router.router, prefix="/api/trainer")
    return TestClient(app)


def _session_data(tub="./data"):
    return {
        "remote_work_dir": REMOTE_DIR,
        "model_name": OLD_MODEL,
        "tub": tub,
        "host": "192.168.1.10",
    }


# ------------------------------------------------------------------
# trainer_session save/load
# ------------------------------------------------------------------
def test_session_roundtrip(tmp_path):
    from trainer_session import load_session, save_session

    save_session(str(tmp_path), "train_my_pc.conf", _session_data())

    # session 文件按 config_file 主名命名
    assert (tmp_path / "train_my_pc.session.json").is_file()

    loaded = load_session(str(tmp_path), "train_my_pc.conf")
    assert loaded is not None
    assert loaded["remote_work_dir"] == REMOTE_DIR
    assert loaded["model_name"] == OLD_MODEL
    assert loaded["tub"] == "./data"
    assert loaded["host"] == "192.168.1.10"
    assert isinstance(loaded["updated_at"], float)


def test_session_load_missing_or_broken_returns_none(tmp_path):
    from trainer_session import load_session

    assert load_session(str(tmp_path), "train_my_pc.conf") is None
    (tmp_path / "train_my_pc.session.json").write_text("{not json", encoding="utf-8")
    assert load_session(str(tmp_path), "train_my_pc.conf") is None


# ------------------------------------------------------------------
# Keras 2/3 进度解析（改动 A）
# ------------------------------------------------------------------
def _make_trainer(tmp_path, monkeypatch):
    """构造带捕获队列的 WebOnlineTrainer（conf 在 tmp_path 下自动创建）。"""
    import queue as sync_queue

    from web_online_trainer import WebOnlineTrainer

    monkeypatch.chdir(tmp_path)
    q = sync_queue.Queue()
    trainer = WebOnlineTrainer(config_file="train_test.conf", log_queue=q)
    return trainer, q


def _drain(q):
    msgs = []
    while not q.empty():
        msgs.append(q.get())
    return msgs


@pytest.mark.parametrize("line", [KERAS3_LINE, KERAS2_LINE])
def test_parse_training_output_web_both_keras_formats(tmp_path, monkeypatch, line):
    trainer, q = _make_trainer(tmp_path, monkeypatch)

    trainer._parse_training_output_web("Epoch 2/100")
    trainer._parse_training_output_web(line)

    assert trainer.current_epoch == 2
    assert trainer.total_epochs == 100
    progress = [m for m in _drain(q) if m["type"] == "progress"]
    assert progress, "step 行必须产生进度事件（旧正则在 Keras 3 下恒为 0%）"
    last = progress[-1]["data"]
    assert last["currentStep"] == 37
    assert last["totalSteps"] == 437
    assert last["loss"] == pytest.approx(0.1234)
    assert last["globalPercent"] > 0


@pytest.mark.parametrize("line", [KERAS3_LINE, KERAS2_LINE])
def test_engine_parse_line_both_keras_formats(line):
    from trainer_engine import TrainingJob, TrainingJobManager

    job = TrainingJob(id="t1", mode="local")
    mgr = TrainingJobManager()
    mgr._parse_line(job, "Epoch 3/100")
    mgr._parse_line(job, line)

    assert job.progress.current_epoch == 3
    assert job.progress.total_epochs == 100
    assert job.progress.current_step == 37
    assert job.progress.total_steps == 437
    assert job.progress.loss == pytest.approx(0.1234)
    assert job.progress.global_percent > 0


def test_is_progress_bar_line():
    from web_online_trainer import _is_progress_bar_line

    assert _is_progress_bar_line(KERAS3_LINE) is True
    assert _is_progress_bar_line(KERAS2_LINE) is True
    assert _is_progress_bar_line("Epoch 1/100") is False
    assert _is_progress_bar_line("Model saved to ./models/x.tflite") is False


# ------------------------------------------------------------------
# run_resume（FakeSSH）
# ------------------------------------------------------------------
class FakeChannel:
    """脚本化 channel：stdout 数据未读完时不报 exit，读完后报结束。"""

    def __init__(self, stdout_chunks=(), exit_status=0):
        self._stdout_chunks = list(stdout_chunks)
        self._exit_status = exit_status

    def recv_ready(self):
        return bool(self._stdout_chunks)

    def recv(self, n):
        return self._stdout_chunks.pop(0)

    def exit_status_ready(self):
        return not self._stdout_chunks

    def recv_exit_status(self):
        return self._exit_status


class FakeStream:
    def __init__(self, data=b"", channel=None):
        self._data = data
        self.channel = channel or FakeChannel()

    def read(self):
        return self._data


class FakeSSH:
    def __init__(self, remote_files=(), dir_exists=True,
                 train_output=b"Finished training\n"):
        self.commands = []
        self._remote_files = list(remote_files)
        self._dir_exists = dir_exists
        self._train_output = train_output
        self.closed = False

    def exec_command(self, cmd, get_pty=False):
        self.commands.append(cmd)
        if cmd.startswith("ls -dt "):
            listing = "".join(f + "\n" for f in self._remote_files).encode()
            return None, FakeStream(listing), FakeStream()
        if "_dd_resume_train.py" in cmd or "train.py" in cmd:
            channel = FakeChannel(stdout_chunks=[self._train_output])
            return None, FakeStream(channel=channel), FakeStream()
        channel = FakeChannel(exit_status=0 if self._dir_exists else 1)
        return None, FakeStream(channel=channel), FakeStream(channel=channel)

    def close(self):
        self.closed = True


class FakeSFTP:
    def __init__(self):
        self.puts = []

    def put(self, local, remote, callback=None):
        self.puts.append((local, remote))


def _make_resume_trainer(tmp_path, monkeypatch, ssh, sftp):
    import queue as sync_queue

    from web_online_trainer import WebOnlineTrainer

    q = sync_queue.Queue()
    trainer = WebOnlineTrainer(
        config_file="train_my_pc.conf",
        log_queue=q,
        working_dir=str(tmp_path),
        ssh_credentials={"host": "192.168.1.10", "user": "u", "password": "p"},
        tub="./data",
    )

    def fake_connect(self):
        self.ssh_client = ssh
        self.sftp_client = sftp

    monkeypatch.setattr(WebOnlineTrainer, "connect_ssh", fake_connect)
    monkeypatch.setattr(WebOnlineTrainer, "download_model",
                        lambda self, model_name=None: None)
    return trainer, q


def test_run_resume_with_checkpoint_uses_transfer(tmp_path, monkeypatch):
    from trainer_session import load_session

    checkpoint = f"{REMOTE_DIR}/models/{OLD_MODEL}"
    ssh = FakeSSH(remote_files=[
        f"{checkpoint}.tflite",
        checkpoint,
        f"{checkpoint}.png",
        f"{checkpoint}_meta.json",
    ])
    sftp = FakeSFTP()
    trainer, q = _make_resume_trainer(tmp_path, monkeypatch, ssh, sftp)

    trainer.run_resume(_session_data())

    train_cmds = [c for c in ssh.commands if "_dd_resume_train.py" in c]
    assert len(train_cmds) == 1
    cmd = train_cmds[0]
    assert "--transfer" in cmd
    # --transfer 指向检查点本体（不是 .tflite/.png/_meta.json 产物）
    assert cmd.endswith(f"--transfer {checkpoint}")
    # 续训脚本已上传到远程工作目录
    assert sftp.puts and sftp.puts[0][1] == f"{REMOTE_DIR}/_dd_resume_train.py"
    # 有续训提示日志
    logs = [m["line"] for m in _drain(q) if m["type"] == "log"]
    assert any("继续训练" in line for line in logs)
    # 会话模型名已更新为新模型（链式续训），tub 不变
    updated = load_session(str(tmp_path), "train_my_pc.conf")
    assert updated is not None
    assert updated["model_name"] != OLD_MODEL
    assert updated["tub"] == "./data"
    assert updated["remote_work_dir"] == REMOTE_DIR
    # finally 里 cleanup 关闭了连接
    assert ssh.closed is True


def test_run_resume_without_checkpoint_raises(tmp_path, monkeypatch):
    ssh = FakeSSH(remote_files=[])
    trainer, _ = _make_resume_trainer(tmp_path, monkeypatch, ssh, FakeSFTP())

    with pytest.raises(RuntimeError, match="未找到上次训练留下的检查点"):
        trainer.run_resume(_session_data())
    assert ssh.closed is True


def test_run_resume_remote_dir_missing_raises(tmp_path, monkeypatch):
    ssh = FakeSSH(dir_exists=False)
    trainer, _ = _make_resume_trainer(tmp_path, monkeypatch, ssh, FakeSFTP())

    with pytest.raises(RuntimeError, match="远程训练目录已不存在"):
        trainer.run_resume(_session_data())
    assert ssh.closed is True


# ------------------------------------------------------------------
# run_mypc_resume（engine 层）
# ------------------------------------------------------------------
def test_run_mypc_resume_without_session_falls_back(tmp_path, monkeypatch):
    from trainer_engine import job_manager

    called = {}

    async def fake_run_online(job, config_file="train_online.conf", working_dir=None,
                              ssh_credentials=None, tub=None):
        called["tub"] = tub
        job.status = "completed"

    monkeypatch.setattr(job_manager, "run_online", fake_run_online)

    job = job_manager.create_job("mypc")
    asyncio.run(job_manager.run_mypc_resume(
        job, config_file="train_my_pc.conf", working_dir=str(tmp_path),
        ssh_credentials={"host": "h"}, tub="./data"))

    assert called["tub"] == "./data"
    assert any("改为全新训练" in line for line in job.logs)


def test_run_mypc_resume_tub_mismatch_falls_back(tmp_path, monkeypatch):
    from trainer_engine import job_manager
    from trainer_session import save_session

    save_session(str(tmp_path), "train_my_pc.conf", _session_data(tub="./data_old"))

    called = {}

    async def fake_run_online(job, config_file="train_online.conf", working_dir=None,
                              ssh_credentials=None, tub=None):
        called["tub"] = tub
        job.status = "completed"

    monkeypatch.setattr(job_manager, "run_online", fake_run_online)

    job = job_manager.create_job("mypc")
    asyncio.run(job_manager.run_mypc_resume(
        job, config_file="train_my_pc.conf", working_dir=str(tmp_path),
        ssh_credentials={"host": "h"}, tub="./data_new"))

    assert called["tub"] == "./data_new"
    assert any("改为全新训练" in line for line in job.logs)


def test_run_mypc_resume_with_session_runs_resume(tmp_path, monkeypatch):
    import trainer_engine
    from trainer_engine import job_manager
    from trainer_session import save_session

    save_session(str(tmp_path), "train_my_pc.conf", _session_data())

    captured = {}

    class FakeTrainer:
        def __init__(self, config_file="train_my_pc.conf", log_queue=None,
                     working_dir=None, ssh_credentials=None, tub=None):
            captured["working_dir"] = working_dir

        def run_resume(self, session):
            captured["session"] = session
            raise RuntimeError("远程爆炸")

    monkeypatch.setattr(trainer_engine, "WebOnlineTrainer", FakeTrainer)

    job = job_manager.create_job("mypc")
    asyncio.run(job_manager.run_mypc_resume(
        job, config_file="train_my_pc.conf", working_dir=str(tmp_path),
        ssh_credentials={"host": "h"}, tub="./data"))

    assert captured["session"]["model_name"] == OLD_MODEL
    assert job.status == "failed"
    assert "远程爆炸" in job.error_message


# ------------------------------------------------------------------
# resume 端点透传
# ------------------------------------------------------------------
def test_mypc_resume_route_passes_params():
    captured = {}

    def fake_run_mypc_resume(job, config_file="train_my_pc.conf", working_dir=None,
                             ssh_credentials=None, tub=None):
        captured["config_file"] = config_file
        captured["working_dir"] = working_dir
        captured["ssh_credentials"] = ssh_credentials
        captured["tub"] = tub

    with _build_client() as client, \
         patch("trainer_engine.job_manager.run_mypc_resume",
               side_effect=fake_run_mypc_resume):
        resp = client.post("/api/trainer/train/mypc/resume", json={
            "config_file": "train_my_pc.conf",
            "working_dir": "/tmp/mycar",
            "ssh": {"host": "192.168.1.10", "user": "me", "password": "secret"},
            "tub": "./data/tub_x",
        })

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "pending"
    assert "job_id" in body
    assert captured["config_file"] == "train_my_pc.conf"
    assert captured["working_dir"] == "/tmp/mycar"
    assert captured["ssh_credentials"]["host"] == "192.168.1.10"
    assert captured["tub"] == "./data/tub_x"


# ------------------------------------------------------------------
# 停止时杀远程进程（E2E 实测发现：停止只断开监听，远程 train.py 变孤儿）
# ------------------------------------------------------------------
def test_abort_remote_kills_remote_training_and_closes(tmp_path, monkeypatch):
    """abort_remote：置中止标志 + 远程 pkill 训练进程 + 关闭连接。"""
    trainer, _ = _make_trainer(tmp_path, monkeypatch)
    ssh = FakeSSH()
    trainer.ssh_client = ssh

    trainer.abort_remote()

    assert trainer._abort_requested is True
    assert any("pkill" in cmd for cmd in ssh.commands)
    assert ssh.closed is True


def test_abort_remote_without_connection_is_noop(tmp_path, monkeypatch):
    """还没连上 SSH（打包阶段）就点停止：不抛错，只置中止标志。"""
    trainer, _ = _make_trainer(tmp_path, monkeypatch)
    trainer.ssh_client = None

    trainer.abort_remote()

    assert trainer._abort_requested is True
