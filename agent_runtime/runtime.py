"""Agent Runtime — artifact store, timeout guard, scheduler, result merger"""

import os
import time
import json
import signal
import threading
from pathlib import Path
from typing import Callable, Optional
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout


# ── Artifact Store ──────────────────────────────

class ArtifactStore:
    """按 run_id 隔离输入/输出/缓存/日志

    jobs/{run_id}/
    ├── input/
    ├── output/
    ├── cache/
    └── logs/
    """

    def __init__(self, base_dir: str = "./jobs"):
        self._base = Path(base_dir)

    def init_run(self, run_id: str) -> dict[str, Path]:
        """为任务创建隔离目录"""
        dirs = {}
        for sub in ["input", "output", "cache", "logs"]:
            d = self._base / run_id / sub
            d.mkdir(parents=True, exist_ok=True)
            dirs[sub] = d
        return dirs

    def write_output(self, run_id: str, filename: str, data):
        """写入输出文件"""
        out = self._base / run_id / "output" / filename
        out.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(data, (dict, list)):
            out.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                           encoding="utf-8")
        else:
            out.write_text(str(data), encoding="utf-8")

    def read_output(self, run_id: str, filename: str) -> Optional[str]:
        """读取输出文件"""
        p = self._base / run_id / "output" / filename
        return p.read_text(encoding="utf-8") if p.exists() else None

    def write_log(self, run_id: str, message: str):
        """追加日志"""
        log = self._base / run_id / "logs" / "run.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        with open(log, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] {message}\n")

    def cleanup(self, run_id: str):
        """清理任务目录"""
        import shutil
        d = self._base / run_id
        if d.exists():
            shutil.rmtree(d)


# ── Timeout Guard ───────────────────────────────

class TimeoutGuard:
    """子任务超时保护 + 重试"""

    def __init__(self, default_timeout: float = 60, max_retries: int = 2):
        self.default_timeout = default_timeout
        self.max_retries = max_retries

    def run(self, fn: Callable, args: tuple = (),
            kwargs: dict = None, timeout: float = None,
            run_id: str = "") -> tuple[bool, any, str]:
        """执行函数，带超时保护。

        Returns: (success, result, error_message)
        """
        timeout = timeout or self.default_timeout
        kwargs = kwargs or {}

        for attempt in range(1 + self.max_retries):
            try:
                with ThreadPoolExecutor(max_workers=1) as ex:
                    future = ex.submit(fn, *args, **kwargs)
                    result = future.result(timeout=timeout)
                return True, result, ""

            except FutureTimeout:
                if attempt < self.max_retries:
                    time.sleep(1)
                    continue
                return False, None, f"timeout after {timeout}s ({1+self.max_retries} attempts)"

            except Exception as e:
                if attempt < self.max_retries:
                    time.sleep(1)
                    continue
                return False, None, str(e)

        return False, None, "max retries exceeded"


# ── Scheduler ───────────────────────────────────

class Scheduler:
    """并发任务调度器"""

    def __init__(self, max_workers: int = 4):
        self.max_workers = max_workers
        self._results: dict[str, tuple[bool, any]] = {}
        self._lock = threading.Lock()

    def run_parallel(self, tasks: list[dict]) -> dict[str, tuple[bool, any]]:
        """并行执行多个任务

        tasks: [{"id": "t1", "fn": callable, "args": (), "kwargs": {}, "timeout": 60}, ...]
        Returns: {"t1": (True, result), "t2": (False, error), ...}
        """
        guard = TimeoutGuard()
        results = {}

        def _worker(task):
            tid = task["id"]
            ok, result, err = guard.run(
                task["fn"],
                args=task.get("args", ()),
                kwargs=task.get("kwargs", {}),
                timeout=task.get("timeout"),
                run_id=tid,
            )
            with self._lock:
                results[tid] = (ok, result if ok else err)

        with ThreadPoolExecutor(max_workers=self.max_workers) as ex:
            futures = [ex.submit(_worker, t) for t in tasks]
            for f in futures:
                try:
                    f.result(timeout=3600)  # overall cap
                except FutureTimeout:
                    pass

        return results


# ── Result Merger ───────────────────────────────

class ResultMerger:
    """多 Agent 结果合并与追踪"""

    @staticmethod
    def merge_dicts(results: dict[str, dict]) -> dict:
        """合并多个 Agent 的字典结果"""
        merged = {}
        for agent_id, data in results.items():
            merged[agent_id] = data
        merged["_agent_count"] = len(results)
        return merged

    @staticmethod
    def merge_lists(results: dict[str, list]) -> list:
        """合并多个 Agent 的列表结果（去重）"""
        seen = set()
        merged = []
        for agent_id, items in results.items():
            for item in items:
                key = json.dumps(item, sort_keys=True, ensure_ascii=False) if isinstance(item, dict) else str(item)
                if key not in seen:
                    seen.add(key)
                    merged.append(item)
        return merged

    @staticmethod
    def summary(results: dict[str, tuple[bool, any]]) -> dict:
        """生成多 Agent 执行摘要"""
        total = len(results)
        ok_count = sum(1 for ok, _ in results.values() if ok)
        return {
            "total": total,
            "success": ok_count,
            "failed": total - ok_count,
            "by_agent": {
                aid: {"ok": ok, "result_preview": str(r)[:100]}
                for aid, (ok, r) in results.items()
            },
        }
