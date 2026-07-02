"""Agent Runtime — 多 Agent 并发任务管理

核心原则:
  - 每次任务生成唯一 run_id
  - 每个 Agent 有独立工作目录
  - 子任务支持 timeout / retry
  - 多 Agent 结果支持合并与追踪
"""
import os
import uuid
import time
import threading
import traceback
from pathlib import Path
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Callable


class JobStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


@dataclass
class Job:
    """一次 Agent 任务"""
    run_id: str
    name: str = ""
    agent_type: str = ""
    status: JobStatus = JobStatus.PENDING
    created_at: float = 0.0
    started_at: float = 0.0
    finished_at: float = 0.0
    error: str = ""
    result: dict = field(default_factory=dict)
    retries: int = 0

    @property
    def latency_ms(self) -> float:
        if self.finished_at and self.started_at:
            return (self.finished_at - self.started_at) * 1000
        return 0.0


class JobManager:
    """任务管理器 — run_id 生成 + 生命周期"""

    def __init__(self):
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def create(self, name: str = "", agent_type: str = "") -> Job:
        """创建新任务"""
        run_id = f"{int(time.time())}_{uuid.uuid4().hex[:8]}"
        job = Job(
            run_id=run_id,
            name=name,
            agent_type=agent_type,
            created_at=time.time(),
            status=JobStatus.PENDING,
        )
        with self._lock:
            self._jobs[run_id] = job
        return job

    def start(self, run_id: str):
        with self._lock:
            job = self._jobs.get(run_id)
            if job:
                job.status = JobStatus.RUNNING
                job.started_at = time.time()

    def complete(self, run_id: str, result: dict = None):
        with self._lock:
            job = self._jobs.get(run_id)
            if job:
                job.status = JobStatus.DONE
                job.finished_at = time.time()
                if result:
                    job.result = result

    def fail(self, run_id: str, error: str):
        with self._lock:
            job = self._jobs.get(run_id)
            if job:
                job.status = JobStatus.FAILED
                job.finished_at = time.time()
                job.error = error

    def timeout(self, run_id: str):
        with self._lock:
            job = self._jobs.get(run_id)
            if job:
                job.status = JobStatus.TIMEOUT
                job.finished_at = time.time()
                job.error = "Task exceeded time limit"

    def cancel(self, run_id: str):
        with self._lock:
            job = self._jobs.get(run_id)
            if job:
                job.status = JobStatus.CANCELLED
                job.finished_at = time.time()

    def get(self, run_id: str) -> Optional[Job]:
        return self._jobs.get(run_id)

    def list_active(self) -> list[Job]:
        return [
            j for j in self._jobs.values()
            if j.status in (JobStatus.PENDING, JobStatus.RUNNING)
        ]

    def stats(self) -> dict:
        with self._lock:
            total = len(self._jobs)
            by_status = {}
            for j in self._jobs.values():
                by_status[j.status.value] = by_status.get(j.status.value, 0) + 1
            return {"total": total, "by_status": by_status}


# ── Timeout Guard ────────────────────────────────

class TimeoutGuard:
    """超时保护 — 在独立线程中运行任务，超时则终止"""

    DEFAULT_TIMEOUT = 300  # 5 分钟

    def __init__(self, job_manager: JobManager = None):
        self.jm = job_manager or JobManager()

    def run(self, run_id: str, fn: Callable, timeout: int = None) -> Optional[dict]:
        """运行任务，超时则标记 TIMEOUT"""
        timeout = timeout or self.DEFAULT_TIMEOUT
        result_container = {}
        error_container = {}

        def _worker():
            try:
                result_container["data"] = fn()
            except Exception as e:
                error_container["error"] = str(e)
                error_container["traceback"] = traceback.format_exc()

        thread = threading.Thread(target=_worker, daemon=True)
        self.jm.start(run_id)
        thread.start()
        thread.join(timeout=timeout)

        if thread.is_alive():
            self.jm.timeout(run_id)
            return None

        if error_container:
            self.jm.fail(run_id, error_container.get("error", ""))
            return None

        result = result_container.get("data")
        self.jm.complete(run_id, result if isinstance(result, dict) else {"value": str(result)})
        return result if isinstance(result, dict) else {"value": str(result)}


# ── Scheduler ────────────────────────────────────

class Scheduler:
    """简易并发调度器 — 限制同时运行的任务数"""

    def __init__(self, max_concurrent: int = 4):
        self.max_concurrent = max_concurrent
        self._semaphore = threading.BoundedSemaphore(max_concurrent)
        self.jm = JobManager()
        self.guard = TimeoutGuard(self.jm)

    def run_tasks(self, tasks: list[dict], timeout_per_task: int = 300) -> list[dict]:
        """并发运行多个任务

        tasks: [{"name": str, "fn": callable, "agent_type": str}, ...]
        """
        results = []
        threads = []

        def _run_one(task):
            self._semaphore.acquire()
            try:
                job = self.jm.create(
                    name=task.get("name", ""),
                    agent_type=task.get("agent_type", ""),
                )
                result = self.guard.run(
                    job.run_id, task["fn"], timeout=timeout_per_task,
                )
                results.append({
                    "run_id": job.run_id,
                    "name": job.name,
                    "ok": job.status == JobStatus.DONE,
                    "result": result,
                    "error": job.error,
                    "latency_ms": job.latency_ms,
                })
            finally:
                self._semaphore.release()

        for task in tasks:
            t = threading.Thread(target=_run_one, args=(task,))
            t.start()
            threads.append(t)

        for t in threads:
            t.join()

        return results
