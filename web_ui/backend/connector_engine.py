import asyncio
import shutil
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Literal, Optional

from remote_car_client import (
    ConnectorConfig,
    build_pull_tub_command,
    build_push_pilots_command,
    build_remote_drive_start_command,
    build_remote_drive_stop_command,
    build_remote_rsync_check_command,
    parse_rsync_progress,
)


@dataclass
class ConnectorJob:
    id: str
    kind: Literal["pull_tub", "push_pilots", "drive_start", "drive_stop"]
    status: Literal["pending", "running", "completed", "failed", "stopped"] = "pending"
    progress: float = 0.0
    logs: list[str] = field(default_factory=list)
    log_queue: asyncio.Queue = field(default_factory=lambda: asyncio.Queue())
    started_at: str = field(default_factory=lambda: datetime.now().isoformat())
    finished_at: Optional[str] = None
    process: Optional[asyncio.subprocess.Process] = None
    error_message: Optional[str] = None


class ConnectorJobManager:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance.jobs: Dict[str, ConnectorJob] = {}
            cls._instance.drive_pid: Optional[int] = None
        return cls._instance

    def create_job(self, kind: Literal["pull_tub", "push_pilots", "drive_start", "drive_stop"]) -> ConnectorJob:
        job = ConnectorJob(id=str(uuid.uuid4())[:8], kind=kind)
        self.jobs[job.id] = job
        return job

    def get_job(self, job_id: str) -> Optional[ConnectorJob]:
        return self.jobs.get(job_id)

    async def stop_job(self, job_id: str):
        job = self.jobs.get(job_id)
        if not job or job.status != "running":
            return
        job.status = "stopped"
        if job.process and job.process.returncode is None:
            job.process.terminate()
        job.finished_at = datetime.now().isoformat()
        await job.log_queue.put({"type": "status", "status": job.status})

    async def run_pull_tub(self, job: ConnectorJob, config: ConnectorConfig, remote_tub: str, local_data_path: str, create_new_dir: bool):
        try:
            command = build_pull_tub_command(config, remote_tub, local_data_path, create_new_dir)
        except Exception as exc:
            await self._fail_job(job, exc)
            return
        if not await self._ensure_rsync_available(job, config):
            return
        await self._run_rsync(job, command)

    async def run_push_pilots(self, job: ConnectorJob, config: ConnectorConfig, local_models_path: str, formats: list[str]):
        try:
            command = build_push_pilots_command(config, local_models_path, formats)
        except Exception as exc:
            await self._fail_job(job, exc)
            return
        if not await self._ensure_rsync_available(job, config):
            return
        await self._run_rsync(job, command)

    async def run_drive_start(self, job: ConnectorJob, config: ConnectorConfig, model_type: str | None, pilot: str | None, bridge_server_url: str | None):
        try:
            command = build_remote_drive_start_command(config, model_type, pilot, bridge_server_url)
        except Exception as exc:
            await self._fail_job(job, exc)
            return
        await self._run_drive_command(job, command, capture_pid=True)

    async def run_drive_stop(self, job: ConnectorJob, config: ConnectorConfig, pid: int | None = None):
        target_pid = pid or self.drive_pid
        if not target_pid:
            job.status = "failed"
            job.error_message = "没有可停止的远端驾驶进程"
            job.finished_at = datetime.now().isoformat()
            await job.log_queue.put({"type": "status", "status": job.status, "error": job.error_message})
            return
        try:
            command = build_remote_drive_stop_command(config, target_pid)
        except Exception as exc:
            await self._fail_job(job, exc)
            return
        await self._run_drive_command(job, command, capture_pid=False)
        if job.status == "completed":
            self.drive_pid = None

    async def _fail_job(self, job: ConnectorJob, exc: Exception):
        job.status = "failed"
        job.error_message = str(exc)
        job.finished_at = datetime.now().isoformat()
        await job.log_queue.put({"type": "status", "status": job.status, "error": job.error_message})

    async def _ensure_rsync_available(self, job: ConnectorJob, config: ConnectorConfig) -> bool:
        if shutil.which("rsync") is None:
            await self._fail_job(job, RuntimeError("本机缺少 rsync，无法同步文件。请安装 rsync 后重试；Linux/WSL: sudo apt install rsync，macOS: brew install rsync。"))
            return False

        command = build_remote_rsync_check_command(config)
        output: list[str] = []
        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            while True:
                line = await process.stdout.readline()
                if not line:
                    break
                text = line.decode("utf-8", errors="ignore").strip()
                if text:
                    output.append(text)
                    job.logs.append(text)
                    await job.log_queue.put({"type": "log", "line": text, "timestamp": time.time()})
            await process.wait()
            if process.returncode == 0:
                return True
            message = output[-1] if output else f"车端 rsync 检测失败，退出码: {process.returncode}"
            await self._fail_job(job, RuntimeError(message))
            return False
        except FileNotFoundError:
            await self._fail_job(job, RuntimeError("ssh 命令不可用，请先安装 OpenSSH 客户端"))
            return False
        except Exception as exc:
            await self._fail_job(job, exc)
            return False

    async def _run_drive_command(self, job: ConnectorJob, command: list[str], capture_pid: bool):
        job.status = "running"
        try:
            job.process = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            output = []
            while True:
                line = await job.process.stdout.readline()
                if not line:
                    break
                text = line.decode("utf-8", errors="ignore").strip()
                if not text:
                    continue
                output.append(text)
                job.logs.append(text)
                await job.log_queue.put({"type": "log", "line": text, "timestamp": time.time()})
            await job.process.wait()
            if job.status == "stopped":
                return
            if job.process.returncode == 0:
                job.status = "completed"
                if capture_pid and output:
                    try:
                        self.drive_pid = int(output[-1])
                        await job.log_queue.put({"type": "drive_pid", "pid": self.drive_pid})
                    except ValueError:
                        job.status = "failed"
                        job.error_message = "未能解析远端驾驶进程 PID"
            else:
                job.status = "failed"
                detail = "；".join(output[-3:])
                job.error_message = f"远端命令退出码: {job.process.returncode}" + (f"，{detail}" if detail else "")
        except Exception as exc:
            job.status = "failed"
            job.error_message = str(exc)
        finally:
            job.finished_at = datetime.now().isoformat()
            await job.log_queue.put({"type": "status", "status": job.status, "error": job.error_message})

    async def _run_rsync(self, job: ConnectorJob, command: list[str]):
        job.status = "running"
        try:
            job.process = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            while True:
                line = await job.process.stdout.readline()
                if not line:
                    break
                text = line.decode("utf-8", errors="ignore").strip()
                if not text:
                    continue
                job.logs.append(text)
                await job.log_queue.put({"type": "log", "line": text, "timestamp": time.time()})
                progress = parse_rsync_progress(text)
                if progress is not None:
                    job.progress = progress
                    await job.log_queue.put({"type": "progress", "progress": progress})

            await job.process.wait()
            if job.status == "stopped":
                return
            if job.process.returncode == 0:
                job.status = "completed"
                job.progress = 100.0
            else:
                job.status = "failed"
                job.error_message = f"rsync 退出码: {job.process.returncode}"
        except Exception as exc:
            if job.status != "stopped":
                job.status = "failed"
                job.error_message = str(exc)
        finally:
            job.finished_at = datetime.now().isoformat()
            await job.log_queue.put({"type": "status", "status": job.status, "error": job.error_message})


connector_job_manager = ConnectorJobManager()
