"""Bad Case Database — 结构化反馈闭环

记录每次问答失败案例，用于系统持续优化。
与 AuditLogger 互补: AuditLogger 记录全量，BadCaseDB 聚焦失败案例。
"""
import sqlite3
import time
import json
import hashlib
from dataclasses import dataclass, field


@dataclass
class BadCase:
    """失败案例"""
    id: str = ""
    question: str = ""
    rewritten: str = ""
    answer: str = ""
    expected_answer: str = ""       # 人工反馈的正确答案
    failure_type: str = ""          # "no_answer" | "wrong_answer" | "hallucination" | "citation_error"
    confidence: float = 0.0
    tenant_id: str = "default"
    user_id: str = ""
    resolved: bool = False
    created_at: float = 0.0


class BadCaseDB:
    """失败案例数据库"""

    def __init__(self, db_path: str = "./data/edis.db"):
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self._init_table()

    def _init_table(self):
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS bad_cases (
                id TEXT PRIMARY KEY,
                tenant_id TEXT DEFAULT 'default',
                question TEXT,
                rewritten TEXT DEFAULT '',
                answer TEXT DEFAULT '',
                expected_answer TEXT DEFAULT '',
                failure_type TEXT DEFAULT '',
                confidence REAL DEFAULT 0.0,
                user_id TEXT DEFAULT '',
                resolved INTEGER DEFAULT 0,
                created_at REAL
            )
        """)
        self.conn.commit()

    def record(self, question: str, answer: str = "",
               failure_type: str = "no_answer",
               confidence: float = 0.0,
               tenant_id: str = "default",
               user_id: str = "") -> str:
        """记录一个失败案例"""
        cid = hashlib.sha256(f"{tenant_id}:{question}:{time.time()}".encode()).hexdigest()[:12]
        self.conn.execute(
            "INSERT INTO bad_cases (id, tenant_id, question, answer, "
            "failure_type, confidence, user_id, created_at) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (cid, tenant_id, question, answer, failure_type,
             confidence, user_id, time.time()),
        )
        self.conn.commit()
        return cid

    def resolve(self, case_id: str, expected_answer: str):
        """标记已解决并记录正确答案"""
        self.conn.execute(
            "UPDATE bad_cases SET resolved=1, expected_answer=? WHERE id=?",
            (expected_answer, case_id),
        )
        self.conn.commit()

    def stats(self, tenant_id: str = "default") -> dict:
        """统计失败分布"""
        by_type = {}
        rows = self.conn.execute(
            "SELECT failure_type, COUNT(*) FROM bad_cases "
            "WHERE tenant_id=? AND resolved=0 GROUP BY failure_type",
            (tenant_id,),
        ).fetchall()
        for ft, cnt in rows:
            by_type[ft] = cnt

        total = self.conn.execute(
            "SELECT COUNT(*) FROM bad_cases WHERE tenant_id=? AND resolved=0",
            (tenant_id,),
        ).fetchone()[0]

        return {"total_unresolved": total, "by_type": by_type}

    def close(self):
        self.conn.close()
