"""
Training Job Engine - manages local and online training jobs with SSE streaming.
"""
import asyncio
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
    mode: Literal['local', 'online']
    status: Literal['pending', 'running', 'completed', 'failed', 'stopped'] = 'pending'
    log_queue: asyncio.Queue = field(default_factory=lambda: asyncio.Queue())
    progress: TrainingProgress = field(default_factory=TrainingProgress)
    logs: list = field(default_factory=list)
    started_at: str = field(default_factory=lambda: datetime.now().isoformat())
    finished_at: Optional[str] = None
    process: Optional[asyncio.subprocess.Process] = None
    trainer_thread: Optional[threading.Thread] = None
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

    def create_job(self, mode: Literal['local', 'online']) -> TrainingJob:
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
        elif job.mode == 'online' and job.stop_event:
            job.stop_event.set()

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
            await job.log_queue.put({"type": "status", "status": job.status})

    # ------------------------------------------------------------------
    # Online training
    # ------------------------------------------------------------------
    async def run_online(self, job: TrainingJob, config_file: str = "train_online.conf",
                         working_dir: Optional[str] = None):
        job.status = 'running'
        cwd = working_dir or os.getcwd()

        thread_queue: queue.Queue = queue.Queue()
        job.stop_event = threading.Event()

        def run_trainer():
            try:
                trainer = WebOnlineTrainer(
                    config_file=config_file,
                    log_queue=thread_queue,
                    working_dir=cwd
                )
                trainer.run(no_interactive=True)
            except Exception as e:
                thread_queue.put({"type": "error", "message": str(e)})

        job.trainer_thread = threading.Thread(target=run_trainer, daemon=True)
        job.trainer_thread.start()

        # Bridge thread_queue -> async job.log_queue
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
        await job.log_queue.put({"type": "status", "status": job.status})

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

            step_match = re.match(r"^\s*(\d+)/(\d+)\s+\[", line)
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
