"""模拟器采集任务引擎：在后台跑 collect_sim_mac.sh，逐行解析进度。

把命令行采集管线（SSH 到 Mac 启动 DonkeySim + 跑 collect_sim_data.py）
包成一个可启动/查询/停止的异步任务，状态与日志通过 asyncio.Queue
以 SSE 形式推给前端。

设计参考 connector_engine.py（单例 JobManager + 子进程逐行解析）。
"""

import asyncio
import logging
import os
import re
import signal
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Optional

logger = logging.getLogger(__name__)

# 采集编排脚本路径（可被环境变量覆盖）
SIM_COLLECT_SCRIPT = os.environ.get(
    "SIM_COLLECT_SCRIPT", "/home/dkc/projects/mycar/collect_sim_mac.sh"
)

# 进度行：[collect] step 123: steer=-0.55 thr=0.18 ... cte=1.024 speed=1.566
_STEP_RE = re.compile(
    r"\[collect\] step\s+(\d+):.*?cte=(-?[\d.]+).*?speed=(-?[\d.]+)"
)
# 结果行：RESULT steps=1500 mean_cte=2.4094 max_cte=7.0614 crashed=0 out=/path
_RESULT_RE = re.compile(
    r"RESULT steps=(\d+)\s+mean_cte=([\d.]+)\s+max_cte=([\d.]+)\s+crashed=(\d)\s+out=(\S+)"
)
# 脚本自身的错误行
_ERROR_RE = re.compile(r"\[mac-collect\] 错误:\s*(.*)")


def parse_step_line(line: str) -> Optional[dict]:
    """解析单步遥测行，命中返回 {step, cte, speed}。"""
    m = _STEP_RE.search(line)
    if not m:
        return None
    return {
        "step": int(m.group(1)),
        "cte": float(m.group(2)),
        "speed": float(m.group(3)),
    }


def parse_result_line(line: str) -> Optional[dict]:
    """解析 RESULT 结尾行。"""
    m = _RESULT_RE.search(line)
    if not m:
        return None
    return {
        "steps": int(m.group(1)),
        "mean_cte": float(m.group(2)),
        "max_cte": float(m.group(3)),
        "crashed": bool(int(m.group(4))),
        "result_out": m.group(5),
    }


def parse_error_line(line: str) -> Optional[str]:
    """解析脚本错误行，命中返回错误文案。"""
    m = _ERROR_RE.search(line)
    return m.group(1) if m else None


@dataclass
class SimCollectJob:
    id: str
    status: str = "pending"  # pending | running | done | error | stopped
    step: int = 0
    steps_total: int = 0
    cte: Optional[float] = None
    speed: Optional[float] = None
    result: Optional[dict] = None
    error: Optional[str] = None
    logs: list = field(default_factory=list)
    log_queue: asyncio.Queue = field(default_factory=lambda: asyncio.Queue())
    started_at: str = field(default_factory=lambda: datetime.now().isoformat())
    finished_at: Optional[str] = None
    process: Optional[asyncio.subprocess.Process] = None
    keep_sim: bool = False


class SimCollectJobManager:
    """单例：同一时刻只允许一个采集任务运行。"""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance.jobs: Dict[str, SimCollectJob] = {}
            cls._instance.active_job_id: Optional[str] = None
        return cls._instance

    def get_running(self) -> Optional[SimCollectJob]:
        if self.active_job_id:
            job = self.jobs.get(self.active_job_id)
            if job and job.status in ("pending", "running"):
                return job
        return None

    def create_job(self, steps: int, kp: float, kd: float, throttle: float,
                   min_throttle: float, keep_sim: bool) -> SimCollectJob:
        if self.get_running() is not None:
            raise RuntimeError("已有采集任务在运行")
        job = SimCollectJob(id=str(uuid.uuid4())[:8], steps_total=steps, keep_sim=keep_sim)
        self.jobs[job.id] = job
        self.active_job_id = job.id
        return job

    def get_job(self, job_id: str) -> Optional[SimCollectJob]:
        return self.jobs.get(job_id)

    async def stop_job(self, job_id: str) -> bool:
        job = self.jobs.get(job_id)
        if not job or job.status not in ("pending", "running"):
            return False
        job.status = "stopped"
        # 脚本用 start_new_session 启动，整组一起终止；SIGTERM 会让 bash 的
        # EXIT trap 跑起来，完成 Mac 侧 sim/隧道的清理
        if job.process and job.process.returncode is None:
            try:
                pgid = os.getpgid(job.process.pid)
                os.killpg(pgid, signal.SIGTERM)
                try:
                    await asyncio.wait_for(job.process.wait(), timeout=3.0)
                except asyncio.TimeoutError:
                    os.killpg(pgid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        job.finished_at = datetime.now().isoformat()
        if self.active_job_id == job.id:
            self.active_job_id = None
        await job.log_queue.put({"type": "status", "status": "stopped"})
        return True

    async def run(self, job: SimCollectJob, steps: int, kp: float, kd: float,
                  throttle: float, min_throttle: float, keep_sim: bool):
        job.status = "running"
        env = os.environ.copy()
        env.update({
            "DONKEY_SIM_STEPS": str(steps),
            "DONKEY_SIM_KP": str(kp),
            "DONKEY_SIM_KD": str(kd),
            "DONKEY_SIM_THROTTLE": str(throttle),
            "DONKEY_SIM_MIN_THROTTLE": str(min_throttle),
            "KEEP_SIM": "1" if keep_sim else "0",
        })
        try:
            job.process = await asyncio.create_subprocess_exec(
                "bash", SIM_COLLECT_SCRIPT,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                env=env,
                start_new_session=True,
            )
            while True:
                line = await job.process.stdout.readline()
                if not line:
                    break
                text = line.decode("utf-8", errors="ignore").rstrip()
                if not text:
                    continue
                job.logs.append(text)
                await job.log_queue.put({"type": "log", "line": text, "timestamp": time.time()})

                err = parse_error_line(text)
                if err:
                    job.error = err

                step_info = parse_step_line(text)
                if step_info:
                    job.step = step_info["step"]
                    job.cte = step_info["cte"]
                    job.speed = step_info["speed"]
                    await job.log_queue.put({
                        "type": "progress",
                        "step": job.step,
                        "total": job.steps_total,
                        "cte": job.cte,
                        "speed": job.speed,
                    })
                    continue

                result = parse_result_line(text)
                if result:
                    job.result = result

            await job.process.wait()
            if job.status == "stopped":
                return
            if job.result is not None and job.process.returncode == 0:
                job.status = "done"
                await job.log_queue.put({"type": "status", "status": "done", "result": job.result})
            else:
                job.status = "error"
                if not job.error:
                    job.error = f"采集脚本退出码 {job.process.returncode}" + (
                        f"：{job.logs[-1]}" if job.logs else "")
                await job.log_queue.put({"type": "status", "status": "error", "error": job.error})
        except Exception as exc:  # noqa: BLE001
            if job.status != "stopped":
                job.status = "error"
                job.error = str(exc)
                await job.log_queue.put({"type": "status", "status": "error", "error": job.error})
        finally:
            job.finished_at = datetime.now().isoformat()
            if self.active_job_id == job.id:
                self.active_job_id = None


simcollect_job_manager = SimCollectJobManager()
