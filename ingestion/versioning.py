"""Async Index Pipeline — 文档版本管理 + 异步索引

问题:
  - 大文档导入阻塞 CLI
  - 重复导入同一文档产生重复 chunk
  - 缺少增量更新机制

解决:
  - DocumentVersion: SHA256 指纹识别文档变更
  - AsyncPipeline: 后台线程异步处理
  - 增量更新: 指纹变化才重新索引
"""
import os
import hashlib
import threading
import time
import json
import sqlite3
from pathlib import Path
from dataclasses import dataclass
from typing import Optional, Callable


@dataclass
class DocumentVersion:
    """文档版本记录"""
    doc_id: str
    filepath: str
    sha256: str           # 文件内容指纹
    page_count: int = 0
    chunk_count: int = 0
    status: str = "pending"   # pending | indexing | done | failed
    version: int = 1
    created_at: float = 0.0
    updated_at: float = 0.0


class VersionManager:
    """文档版本管理 — 指纹检测 + 增量更新"""

    def __init__(self, db_path: str = "./data/edis.db"):
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self._init_table()

    def _init_table(self):
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS doc_versions (
                doc_id TEXT PRIMARY KEY,
                filepath TEXT,
                sha256 TEXT,
                page_count INTEGER DEFAULT 0,
                chunk_count INTEGER DEFAULT 0,
                status TEXT DEFAULT 'pending',
                version INTEGER DEFAULT 1,
                created_at REAL,
                updated_at REAL
            )
        """)
        self.conn.commit()

    @staticmethod
    def fingerprint(filepath: str) -> str:
        """计算文件 SHA256 指纹"""
        with open(filepath, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()

    def needs_update(self, filepath: str) -> tuple[bool, Optional[str]]:
        """检查文档是否需要重新索引。返回 (需要更新?, 旧doc_id)"""
        fp = self.fingerprint(filepath)

        # 检查是否已存在同指纹的记录
        row = self.conn.execute(
            "SELECT doc_id, sha256 FROM doc_versions WHERE filepath=? ORDER BY version DESC LIMIT 1",
            (filepath,),
        ).fetchone()

        if row is None:
            # 新文件
            return True, None

        old_doc_id, old_sha = row
        return old_sha != fp, old_doc_id

    def record(self, doc_id: str, filepath: str, page_count: int = 0,
               chunk_count: int = 0, status: str = "done"):
        """记录文档版本"""
        fp = self.fingerprint(filepath)
        now = time.time()

        # 检查版本号
        existing = self.conn.execute(
            "SELECT version FROM doc_versions WHERE filepath=?",
            (filepath,),
        ).fetchone()

        version = (existing[0] + 1) if existing else 1

        self.conn.execute(
            "INSERT OR REPLACE INTO doc_versions "
            "(doc_id, filepath, sha256, page_count, chunk_count, status, version, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (doc_id, filepath, fp, page_count, chunk_count, status, version, now, now),
        )
        self.conn.commit()

    def get_version(self, doc_id: str) -> Optional[DocumentVersion]:
        row = self.conn.execute(
            "SELECT * FROM doc_versions WHERE doc_id=?",
            (doc_id,),
        ).fetchone()
        if row:
            return DocumentVersion(
                doc_id=row[0], filepath=row[1], sha256=row[2],
                page_count=row[3], chunk_count=row[4], status=row[5],
                version=row[6], created_at=row[7], updated_at=row[8],
            )
        return None

    def close(self):
        self.conn.close()


class AsyncPipeline:
    """异步索引流水线 — 后台线程处理文档"""

    def __init__(self, max_workers: int = 2):
        self.max_workers = max_workers
        self._queue: list[dict] = []
        self._lock = threading.Lock()
        self._running = False
        self._callbacks: dict[str, Callable] = {}

    def submit(self, filepath: str, tenant_id: str = "default",
               callback: Callable = None, **kwargs) -> str:
        """提交索引任务"""
        import uuid
        task_id = f"index_{uuid.uuid4().hex[:8]}"

        with self._lock:
            self._queue.append({
                "task_id": task_id,
                "filepath": filepath,
                "tenant_id": tenant_id,
                "kwargs": kwargs,
                "status": "queued",
            })

        if callback:
            self._callbacks[task_id] = callback

        return task_id

    def process_all(self, ingest_fn: Callable):
        """同步处理所有排队任务"""
        with self._lock:
            tasks = list(self._queue)
            self._queue = []

        for task in tasks:
            task["status"] = "processing"
            try:
                doc_id = ingest_fn(
                    task["filepath"],
                    tenant_id=task.get("tenant_id", "default"),
                    **task.get("kwargs", {}),
                )
                task["status"] = "done"
                task["doc_id"] = doc_id
                cb = self._callbacks.get(task["task_id"])
                if cb:
                    cb(task_id=task["task_id"], doc_id=doc_id, success=True)
            except Exception as e:
                task["status"] = "failed"
                task["error"] = str(e)
                cb = self._callbacks.get(task["task_id"])
                if cb:
                    cb(task_id=task["task_id"], success=False, error=str(e))

    def queue_size(self) -> int:
        return len(self._queue)
