"""Artifact Store — 按 run_id 隔离输入/输出/缓存/日志

每个 run_id 有独立目录: jobs/{run_id}/input/ output/ cache/ logs/
多 Agent 并发不会互相踩文件。
"""
import os
import json
from pathlib import Path
from datetime import datetime
from typing import Optional


class ArtifactStore:
    """文件隔离存储"""

    def __init__(self, base_dir: str = None):
        if base_dir:
            self._base = Path(base_dir)
        elif os.environ.get("EDIS_HOME"):
            self._base = Path(os.environ["EDIS_HOME"]) / "jobs"
        else:
            self._base = Path("jobs")

    def create_run_dir(self, run_id: str) -> Path:
        """创建任务隔离目录"""
        run_dir = self._base / run_id
        for sub in ["input", "output", "cache", "logs"]:
            (run_dir / sub).mkdir(parents=True, exist_ok=True)
        return run_dir

    def run_dir(self, run_id: str) -> Path:
        return self._base / run_id

    def write_input(self, run_id: str, filename: str, content: str | bytes):
        """写入输入文件"""
        p = self._base / run_id / "input" / filename
        p.parent.mkdir(parents=True, exist_ok=True)
        mode = "wb" if isinstance(content, bytes) else "w"
        with open(p, mode) as f:
            f.write(content)

    def read_input(self, run_id: str, filename: str) -> Optional[str]:
        p = self._base / run_id / "input" / filename
        if p.exists():
            return p.read_text(encoding="utf-8")
        return None

    def save_output(self, run_id: str, filename: str, content: str | bytes):
        p = self._base / run_id / "output" / filename
        p.parent.mkdir(parents=True, exist_ok=True)
        mode = "wb" if isinstance(content, bytes) else "w"
        with open(p, mode) as f:
            f.write(content)

    def save_json_output(self, run_id: str, filename: str, data: dict):
        p = self._base / run_id / "output" / filename
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def read_output(self, run_id: str, filename: str) -> Optional[str]:
        p = self._base / run_id / "output" / filename
        if p.exists():
            return p.read_text(encoding="utf-8")
        return None

    def write_log(self, run_id: str, message: str):
        p = self._base / run_id / "logs" / "run.log"
        p.parent.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().isoformat()
        with open(p, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] {message}\n")

    def cleanup(self, run_id: str):
        """清理任务目录"""
        import shutil
        run_dir = self._base / run_id
        if run_dir.exists():
            shutil.rmtree(run_dir)

    def list_runs(self) -> list[dict]:
        """列出所有任务"""
        if not self._base.exists():
            return []
        runs = []
        for d in sorted(self._base.iterdir(), reverse=True):
            if d.is_dir():
                runs.append({
                    "run_id": d.name,
                    "has_output": (d / "output").exists() and any((d / "output").iterdir()),
                    "has_logs": (d / "logs" / "run.log").exists(),
                })
        return runs[:50]  # 最多 50 条


# ── Result Merger ────────────────────────────────

class ResultMerger:
    """多 Agent 结果合并

    解决多个 sub-agent 并发运行后如何合并结果的问题。
    """

    @staticmethod
    def merge_dicts(results: list[dict], key_field: str = "run_id") -> dict:
        """合并多个 dict 结果"""
        merged = {}
        for r in results:
            if r.get("ok"):
                data = r.get("result", {})
                if isinstance(data, dict):
                    merged.update(data)
        merged["_sub_tasks"] = len(results)
        merged["_ok_count"] = sum(1 for r in results if r.get("ok"))
        merged["_fail_count"] = sum(1 for r in results if not r.get("ok"))
        return merged

    @staticmethod
    def merge_lists(results: list[dict]) -> list:
        """合并多个 list 结果"""
        merged = []
        for r in results:
            if r.get("ok"):
                data = r.get("result", {})
                items = data.get("value", data) if isinstance(data, dict) else data
                if isinstance(items, list):
                    merged.extend(items)
                else:
                    merged.append(items)
        return merged

    @staticmethod
    def merge_qa_results(results: list[dict]) -> list[dict]:
        """合并批量问答结果"""
        output = []
        for r in results:
            if r.get("ok"):
                data = r.get("result", {})
                output.append({
                    "name": r.get("name", ""),
                    "answer": data.get("answer", data.get("value", str(data))),
                    "confidence": data.get("confidence", 0),
                    "ok": True,
                })
            else:
                output.append({
                    "name": r.get("name", ""),
                    "error": r.get("error", "unknown"),
                    "ok": False,
                })
        return output
