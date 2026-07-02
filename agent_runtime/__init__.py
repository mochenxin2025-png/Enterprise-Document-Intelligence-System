"""Job Manager — 每次任务生成唯一 run_id，管理生命周期

解决多 Agent 同时写同一个 output/result.json 的低级事故。
"""

import uuid
import time
import json
import sqlite3
from dataclasses import dataclass, field
from typing import Optional
from pathlib import Path


@dataclass
class JobInfo:
    """任务元信息"""
    run_id: str
    agent_id: str = ""
    agent_type: str = ""
    status: str = "pending"      # pending | running | done | failed | timeout
    created_at: float = 0.0
    started_at: float = 0.0
    finished_at: float = 0.0
    error: str = ""
    metadata: dict = field(default_factory=dict)


class JobManager:
    """任务生命周期管理"""

    def __init__(self, db_path: str = "./data/edis.db"):
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self._init_table()

    def _init_table(self):
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS jobs (
                run_id TEXT PRIMARY KEY,
                agent_id TEXT DEFAULT '',
                agent_type TEXT DEFAULT '',
                status TEXT DEFAULT 'pending',
                created_at REAL,
                started_at REAL,
                finished_at REAL,
                error TEXT DEFAULT '',
                metadata TEXT DEFAULT '{}'
            )
        """)
        self.conn.commit()

    def create(self, agent_id: str = "", agent_type: str = "",
               metadata: dict = None) -> JobInfo:
        """创建新任务，返回 run_id"""
        run_id = uuid.uuid4().hex[:12]
        now = time.time()

        job = JobInfo(
            run_id=run_id,
            agent_id=agent_id,
            agent_type=agent_type,
            status="pending",
            created_at=now,
            metadata=metadata or {},
        )

        self.conn.execute(
            "INSERT INTO jobs (run_id, agent_id, agent_type, status, "
            "created_at, metadata) VALUES (?,?,?,?,?,?)",
            (run_id, agent_id, agent_type, "pending", now,
             json.dumps(metadata or {})),
        )
        self.conn.commit()
        return job

    def start(self, run_id: str):
        """标记任务开始"""
        self.conn.execute(
            "UPDATE jobs SET status='running', started_at=? WHERE run_id=?",
            (time.time(), run_id),
        )
        self.conn.commit()

    def finish(self, run_id: str, success: bool = True, error: str = ""):
        """标记任务结束"""
        status = "done" if success else "failed"
        self.conn.execute(
            "UPDATE jobs SET status=?, finished_at=?, error=? WHERE run_id=?",
            (status, time.time(), error, run_id),
        )
        self.conn.commit()

    def timeout(self, run_id: str):
        """标记任务超时"""
        self.finish(run_id, success=False, error="timeout")

    def get(self, run_id: str) -> Optional[JobInfo]:
        """查询任务状态"""
        row = self.conn.execute(
            "SELECT run_id, agent_id, agent_type, status, created_at, "
            "started_at, finished_at, error, metadata FROM jobs WHERE run_id=?",
            (run_id,),
        ).fetchone()
        if not row:
            return None
        return JobInfo(
            run_id=row[0], agent_id=row[1], agent_type=row[2],
            status=row[3], created_at=row[4], started_at=row[5] or 0,
            finished_at=row[6] or 0, error=row[7],
            metadata=json.loads(row[8]) if row[8] else {},
        )

    def list_active(self) -> list[JobInfo]:
        """列出活跃任务"""
        rows = self.conn.execute(
            "SELECT run_id, agent_id, agent_type, status FROM jobs "
            "WHERE status IN ('pending','running')"
        ).fetchall()
        return [JobInfo(run_id=r[0], agent_id=r[1], agent_type=r[2],
                        status=r[3]) for r in rows]

    def close(self):
        self.conn.close()
