"""
Training Job Engine - manages local and online training jobs with SSE streaming.
"""
import asyncio
import json
import os
import queue
import re
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Optional, Literal

from fastapi import HTTPException

from web_online_trainer import WebOnlineTrainer
from trainer_session import load_session


# Regex to strip ANSI escape codes (colour, cursor movement, etc.)
_ANSI_RE = re.compile(r'\x1b\[[0-9;]*m')


def _clean_training_line(raw: str) -> str:
    """Remove ANSI escape codes and handle \\r carriage returns.

    Keras verbose=1 progress bars emit \\r to overwrite the same line.
    When captured by readline() the line may contain multiple \\r-separated
    segments; only the final segment is the visible text.
    """
    cleaned = _ANSI_RE.sub('', raw)
    if '\r' in cleaned:
        cleaned = cleaned.split('\r')[-1]
    return cleaned.strip()


@dataclass
class TrainingProgress:
    current_epoch: int = 0
    total_epochs: int = 0
    current_step: int = 0
    total_steps: int = 0
    loss: Optional[float] = None
    global_percent: float = 0.0


@dataclass
class TrainingJob:
    id: str
    # 'local' = on the machine running this backend; 'mypc' = on the user's
    # own computer (SSH callback, config train_my_pc.conf); 'mypc_install' =
    # dependency install job on the user's computer (pip install
    # "donkeydrifter[pc]"); 'online' = on the configured cloud server
    # (config train_online.conf).
    mode: Literal['local', 'mypc', 'mypc_install', 'online']
    status: Literal['pending', 'running', 'completed', 'failed', 'stopped'] = 'pending'
    log_queue: asyncio.Queue = field(default_factory=lambda: asyncio.Queue())
    progress: TrainingProgress = field(default_factory=TrainingProgress)
    logs: list = field(default_factory=list)
    loss_history: list = field(default_factory=list)
    started_at: str = field(default_factory=lambda: datetime.now().isoformat())
    finished_at: Optional[str] = None
    process: Optional[asyncio.subprocess.Process] = None
    trainer_thread: Optional[threading.Thread] = None
    # mypc/online 模式的 WebOnlineTrainer 实例（训练线程启动后挂入），
    # stop_job 通过它杀远程训练进程（abort_remote）
    trainer: Optional[object] = None
    stop_event: Optional[threading.Event] = None
    error_message: Optional[str] = None


class TrainingJobManager:
    """Singleton managing active training jobs."""
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance.jobs: Dict[str, TrainingJob] = {}
        return cls._instance

    def create_job(self, mode: Literal['local', 'mypc', 'mypc_install', 'online']) -> TrainingJob:
        job_id = str(uuid.uuid4())[:8]
        job = TrainingJob(id=job_id, mode=mode)
        self.jobs[job_id] = job
        return job

    def get_job(self, job_id: str) -> Optional[TrainingJob]:
        return self.jobs.get(job_id)

    def stop_job(self, job_id: str):
        job = self.jobs.get(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")
        if job.status != 'running':
            return

        job.status = 'stopped'
        if job.mode == 'local' and job.process:
            try:
                job.process.terminate()
            except Exception:
                pass

            async def force_kill():
                await asyncio.sleep(3)
                if job.process and job.process.returncode is None:
                    try:
                        job.process.kill()
                    except Exception:
                        pass

            asyncio.create_task(force_kill())
        elif job.mode in ('mypc', 'mypc_install', 'online') and job.stop_event:
            job.stop_event.set()
            # 同时杀掉远程训练进程：否则「停止」只是断开监听，
            # 远程 train.py 变孤儿继续占算力（再点「继续」会双训练并发）
            if job.trainer is not None:
                try:
                    job.trainer.abort_remote()
                except Exception:
                    pass

        job.finished_at = datetime.now().isoformat()

    # ------------------------------------------------------------------
    # Local training
    # ------------------------------------------------------------------
    async def run_local(self, job: TrainingJob, tub: str, model: str,
                        model_type: str, transfer: Optional[str] = None,
                        working_dir: Optional[str] = None):
        job.status = 'running'
        cwd = working_dir or os.getcwd()
        cmd = ["donkey", "train", "--tub", tub, "--model", model, "--type", model_type]
        if transfer:
            cmd.extend(["--transfer", transfer])

        try:
            job.process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd
            )

            async def read_stream(stream, is_stderr=False):
                while True:
                    line = await stream.readline()
                    if not line:
                        break
                    text = line.decode('utf-8', errors='ignore').rstrip()
                    if text:
                        cleaned = _clean_training_line(text)
                        if not cleaned:
                            continue
                        payload = {
                            "type": "log",
                            "line": cleaned,
                            "is_stderr": is_stderr,
                            "timestamp": datetime.now().isoformat()
                        }
                        await job.log_queue.put(payload)
                        job.logs.append(cleaned)
                        # Try to parse progress from stdout
                        if not is_stderr:
                            old_progress = (
                                job.progress.current_epoch,
                                job.progress.total_epochs,
                                job.progress.current_step,
                                job.progress.total_steps,
                                job.progress.loss,
                                job.progress.global_percent,
                            )
                            self._parse_line(job, cleaned)
                            new_progress = (
                                job.progress.current_epoch,
                                job.progress.total_epochs,
                                job.progress.current_step,
                                job.progress.total_steps,
                                job.progress.loss,
                                job.progress.global_percent,
                            )
                            if new_progress != old_progress:
                                if job.progress.loss is not None:
                                    job.loss_history.append(job.progress.loss)
                                await job.log_queue.put({
                                    "type": "progress",
                                    "data": {
                                        "currentEpoch": job.progress.current_epoch,
                                        "totalEpochs": job.progress.total_epochs,
                                        "currentStep": job.progress.current_step,
                                        "totalSteps": job.progress.total_steps,
                                        "loss": job.progress.loss,
                                        "globalPercent": job.progress.global_percent,
                                    }
                                })

            await asyncio.gather(
                read_stream(job.process.stdout),
                read_stream(job.process.stderr, True)
            )

            await job.process.wait()

            if job.status == 'stopped':
                pass  # already set
            elif job.process.returncode == 0:
                job.status = 'completed'
            else:
                job.status = 'failed'
                job.error_message = f"Exit code: {job.process.returncode}"
        except Exception as e:
            if job.status != 'stopped':
                job.status = 'failed'
                job.error_message = str(e)
        finally:
            job.finished_at = datetime.now().isoformat()
            await job.log_queue.put({"type": "status", "status": job.status, "error": job.error_message})

    # ------------------------------------------------------------------
    # Online training
    # ------------------------------------------------------------------
    async def run_online(self, job: TrainingJob, config_file: str = "train_online.conf",
                         working_dir: Optional[str] = None,
                         ssh_credentials: Optional[dict] = None,
                         tub: Optional[str] = None):
        job.status = 'running'
        cwd = working_dir or os.getcwd()

        thread_queue: queue.Queue = queue.Queue()
        job.stop_event = threading.Event()

        def run_trainer():
            try:
                trainer = WebOnlineTrainer(
                    config_file=config_file,
                    log_queue=thread_queue,
                    working_dir=cwd,
                    ssh_credentials=ssh_credentials,
                    tub=tub,
                )
                job.trainer = trainer  # stop_job 据此杀远程进程
                trainer.run(no_interactive=True)
            except SystemExit as e:
                # SystemExit 不是 Exception 的子类：OnlineTrainer.run() 失败时会
                # sys.exit(1)，必须单独捕获，否则线程静默死掉、任务被误标 completed
                if e.code:
                    thread_queue.put({"type": "error", "message": f"Training flow exited abnormally (code {e.code}) — see the error line above for the reason"})
            except Exception as e:
                thread_queue.put({"type": "error", "message": str(e)})

        job.trainer_thread = threading.Thread(target=run_trainer, daemon=True)
        job.trainer_thread.start()

        await self._pump_thread_queue(job, thread_queue)

    async def _pump_thread_queue(self, job: TrainingJob, thread_queue: "queue.Queue"):
        """Bridge a worker-thread queue into the async job.log_queue.

        Shared by online/mypc training and mypc dependency install: relays
        log / progress / error events until the worker thread exits.
        """
        try:
            while job.trainer_thread.is_alive() or not thread_queue.empty():
                if job.stop_event.is_set():
                    break
                try:
                    msg = thread_queue.get(timeout=0.1)
                    msg_type = msg.get("type")
                    if msg_type == "error":
                        job.error_message = msg.get("message")
                    elif msg_type == "progress":
                        d = msg.get("data", {})
                        job.progress = TrainingProgress(
                            current_epoch=d.get("currentEpoch", 0),
                            total_epochs=d.get("totalEpochs", 0),
                            current_step=d.get("currentStep", 0),
                            total_steps=d.get("totalSteps", 0),
                            loss=d.get("loss"),
                            global_percent=d.get("globalPercent", 0.0),
                        )
                    elif msg_type == "log":
                        job.logs.append(msg.get("line", ""))

                    await job.log_queue.put(msg)
                except queue.Empty:
                    await asyncio.sleep(0.05)
        except Exception as e:
            if job.status != 'stopped':
                job.error_message = str(e)

        if job.status == 'running':
            if job.error_message:
                job.status = 'failed'
            else:
                job.status = 'completed'

        job.finished_at = datetime.now().isoformat()
        await job.log_queue.put({"type": "status", "status": job.status, "error": job.error_message})

    # ------------------------------------------------------------------
    # My-PC training (SSH callback to the user's own computer)
    # ------------------------------------------------------------------
    async def run_mypc(self, job: TrainingJob, config_file: str = "train_my_pc.conf",
                       working_dir: Optional[str] = None,
                       ssh_credentials: Optional[dict] = None,
                       tub: Optional[str] = None):
        """Train on the user's own computer (the machine running the browser).

        Same SSH pipeline as online training, but driven by a separate config
        file (train_my_pc.conf) pointing at the user's machine instead of a
        cloud server.
        """
        await self.run_online(job, config_file=config_file, working_dir=working_dir,
                              ssh_credentials=ssh_credentials, tub=tub)

    async def run_mypc_resume(self, job: TrainingJob, config_file: str = "train_my_pc.conf",
                              working_dir: Optional[str] = None,
                              ssh_credentials: Optional[dict] = None,
                              tub: Optional[str] = None):
        """mypc 断点续训：有历史会话则从上次最佳权重继续训练，否则回退全新训练。"""
        cwd = working_dir or os.getcwd()
        session = load_session(cwd, config_file)
        if not session or session.get("tub") != tub:
            fallback_log = "没有可续训的历史训练（或训练数据已变化），改为全新训练"
            job.logs.append(fallback_log)
            await job.log_queue.put({
                "type": "log",
                "line": fallback_log,
                "level": "info",
                "timestamp": datetime.now().isoformat(),
            })
            await self.run_online(job, config_file=config_file, working_dir=working_dir,
                                  ssh_credentials=ssh_credentials, tub=tub)
            return

        job.status = 'running'

        thread_queue: queue.Queue = queue.Queue()
        job.stop_event = threading.Event()

        def run_trainer():
            try:
                trainer = WebOnlineTrainer(
                    config_file=config_file,
                    log_queue=thread_queue,
                    working_dir=cwd,
                    ssh_credentials=ssh_credentials,
                    tub=tub,
                )
                job.trainer = trainer  # stop_job 据此杀远程进程
                trainer.run_resume(session)
            except SystemExit as e:
                # SystemExit 不是 Exception 的子类，必须单独捕获，
                # 否则线程静默死掉、任务被误标 completed
                if e.code:
                    thread_queue.put({"type": "error", "message": f"Training flow exited abnormally (code {e.code}) — see the error line above for the reason"})
            except Exception as e:
                thread_queue.put({"type": "error", "message": str(e)})

        job.trainer_thread = threading.Thread(target=run_trainer, daemon=True)
        job.trainer_thread.start()

        await self._pump_thread_queue(job, thread_queue)

    # ------------------------------------------------------------------
    # My-PC dependency install (pip install "donkeydrifter[pc]")
    # ------------------------------------------------------------------
    async def run_mypc_install(self, job: TrainingJob, host: str, user: str,
                               password: str, python_path: str, port: int = 22,
                               key_path: str = ""):
        """Install training dependencies on the user's own computer.

        Runs ``mypc_installer.install_mypc_environment`` in a worker thread
        (Paramiko is blocking) and streams its log events into the job queue,
        so the install job reuses the training job status / SSE endpoints.
        """
        job.status = 'running'

        thread_queue: queue.Queue = queue.Queue()
        job.stop_event = threading.Event()

        def run_installer():
            try:
                from mypc_installer import install_mypc_environment
                code = install_mypc_environment(
                    host=host,
                    user=user,
                    password=password,
                    python_path=python_path,
                    port=port,
                    log_queue=thread_queue,
                    stop_event=job.stop_event,
                    key_path=key_path,
                )
                if code != 0 and not job.stop_event.is_set():
                    thread_queue.put({
                        "type": "error",
                        "message": f"pip install 失败，退出码: {code}",
                    })
            except Exception as e:
                thread_queue.put({"type": "error", "message": str(e)})

        job.trainer_thread = threading.Thread(target=run_installer, daemon=True)
        job.trainer_thread.start()

        await self._pump_thread_queue(job, thread_queue)

    # ------------------------------------------------------------------
    # Shared parsing
    # ------------------------------------------------------------------
    def _parse_line(self, job: TrainingJob, line: str):
        """Parse Keras-style training output for local jobs."""
        try:
            line = _clean_training_line(line)
            if not line:
                return

            epoch_match = re.search(r"Epoch (\d+)/(\d+)", line)
            if epoch_match:
                job.progress.current_epoch = int(epoch_match.group(1))
                job.progress.total_epochs = int(epoch_match.group(2))
                return

            # 兼容 Keras 2 的 [====>...] 与 Keras 3 的 ━━━ Unicode 粗线进度条
            step_match = re.match(r"^\s*(\d+)/(\d+)\s+[\[━]", line)
            if step_match:
                job.progress.current_step = int(step_match.group(1))
                job.progress.total_steps = int(step_match.group(2))

            # Progress bars may contain multiple "loss:" keys;
            # the last one is the current value.
            loss_match = None
            for m in re.finditer(r"loss: ([\d.]+(?:e[+-]?\d+)?)", line):
                loss_match = m
            if loss_match:
                job.progress.loss = float(loss_match.group(1))

            if job.progress.total_epochs > 0 and job.progress.total_steps > 0:
                ce = job.progress.current_epoch
                te = job.progress.total_epochs
                cs = job.progress.current_step
                ts = job.progress.total_steps
                completed = (ce - 1) / te
                current = (cs / ts) / te
                job.progress.global_percent = (completed + current) * 100
        except Exception:
            pass


# Global singleton
job_manager = TrainingJobManager()
