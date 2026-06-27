"""Unanswered Queue — 检索+LLM 都答不了的问题入池，运营手动填写后入 QA Pair"""
import hashlib
import json
import sqlite3
import time
from dataclasses import dataclass
from typing import Optional


@dataclass
class UnansweredItem:
    id: str
    question: str
    retrieval_context: str     # 最近 Chunk 文本
    top_chunks: list[dict]     # [{page, score, text[:100]}]
    status: str = "pending"
    created_at: float = 0.0


class UnansweredQueue:
    """SQLite 待解决问题池"""

    def __init__(self, db_path: str = "./data/edis.db"):
        self.conn = sqlite3.connect(db_path)
        self._init_tables()

    def _init_tables(self):
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS unanswered_queue (
                id TEXT, tenant_id TEXT DEFAULT 'default',
                question TEXT,
                retrieval_context TEXT,
                top_chunks TEXT DEFAULT '[]',
                status TEXT DEFAULT 'pending',
                created_at REAL,
                resolved_at REAL,
                resolved_answer TEXT,
                PRIMARY KEY (id, tenant_id)
            )
        """)
        self.conn.commit()

    def enqueue(self, question: str, retrieval_context: str = "",
                top_chunks: list[dict] = None, tenant_id: str = "default") -> str:
        qid = hashlib.sha256(question.encode()).hexdigest()[:12]
        now = time.time()
        existing = self.conn.execute(
            "SELECT id FROM unanswered_queue WHERE id = ? AND tenant_id = ? AND status = 'pending'",
            (qid, tenant_id)
        ).fetchone()
        if existing:
            return qid

        self.conn.execute(
            "INSERT OR REPLACE INTO unanswered_queue (id, tenant_id, question, retrieval_context, top_chunks, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (qid, tenant_id, question, retrieval_context, json.dumps(top_chunks or []), now),
        )
        self.conn.commit()
        return qid

    def list_pending(self, limit: int = 50, tenant_id: str = "default") -> list[dict]:
        """列出待处理问题"""
        rows = self.conn.execute(
            "SELECT id, question, retrieval_context, top_chunks, created_at "
            "FROM unanswered_queue WHERE status = 'pending' AND tenant_id = ? ORDER BY created_at ASC LIMIT ?",
            (tenant_id, limit),
        ).fetchall()
        return [
            {"id": r[0], "question": r[1], "context_preview": (r[2] or "")[:200],
             "top_chunks": json.loads(r[3]), "created_at": r[4]}
            for r in rows
        ]

    def resolve(self, qid: str, answer: str):
        """运营填写答案后标记已解决"""
        self.conn.execute(
            "UPDATE unanswered_queue SET status='answered', resolved_at=?, resolved_answer=? WHERE id=?",
            (time.time(), answer, qid),
        )
        self.conn.commit()

    def ignore(self, qid: str):
        """标记忽略"""
        self.conn.execute(
            "UPDATE unanswered_queue SET status='ignored', resolved_at=? WHERE id=?",
            (time.time(), qid),
        )
        self.conn.commit()

    def stats(self) -> dict:
        """队列统计"""
        total = self.conn.execute("SELECT COUNT(*) FROM unanswered_queue").fetchone()[0]
        pending = self.conn.execute(
            "SELECT COUNT(*) FROM unanswered_queue WHERE status='pending'"
        ).fetchone()[0]
        return {"total": total, "pending": pending}

    def close(self):
        self.conn.close()
