"""Audit Logger — 企业级 RAG L5: 全流程审计追踪

记录每次问答的完整链路：用户→问题→检索文档→引用Chunk→最终回答→时间戳。

设计原则:
  - 审计日志不可篡改（append-only via INSERT）
  - 记录原始数据而非摘要（完整追溯）
  - 按租户隔离
"""

import json
import sqlite3
import time
import hashlib
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class AuditEntry:
    """单条审计记录"""
    user_id: str
    question: str
    tenant_id: str = "default"
    retrieved_doc_ids: list[str] = field(default_factory=list)
    cited_chunks: list[dict] = field(default_factory=list)
    answer: str = ""
    answer_short: str = ""         # 前200字符用于快速浏览
    confidence: float = 0.0
    intent: str = ""
    model: str = ""
    latency_ms: float = 0.0
    timestamp: float = 0.0
    security_alerts: list[str] = field(default_factory=list)
    verification_passed: bool = True


class AuditLogger:
    """SQLite 审计日志存储 — append-only"""

    def __init__(self, db_path: str = "./data/edis.db"):
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self._init_table()

    def _init_table(self):
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS audit_log (
                id TEXT PRIMARY KEY,
                tenant_id TEXT DEFAULT 'default',
                user_id TEXT DEFAULT '',
                question TEXT,
                retrieved_doc_ids TEXT DEFAULT '[]',
                cited_chunks TEXT DEFAULT '[]',
                answer TEXT DEFAULT '',
                answer_short TEXT DEFAULT '',
                confidence REAL DEFAULT 0.0,
                intent TEXT DEFAULT '',
                model TEXT DEFAULT '',
                latency_ms REAL DEFAULT 0.0,
                security_alerts TEXT DEFAULT '[]',
                verification_passed INTEGER DEFAULT 1,
                created_at REAL
            )
        """)
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_audit_tenant ON audit_log(tenant_id)")
        self.conn.commit()

    def log(self, entry: AuditEntry) -> str:
        """写入一条审计记录，返回记录 ID"""
        eid = hashlib.sha256(
            f"{entry.tenant_id}:{entry.user_id}:{entry.question}:{time.time()}".encode()
        ).hexdigest()[:16]

        self.conn.execute(
            "INSERT INTO audit_log (id, tenant_id, user_id, question, "
            "retrieved_doc_ids, cited_chunks, answer, answer_short, "
            "confidence, intent, model, latency_ms, security_alerts, "
            "verification_passed, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                eid,
                entry.tenant_id,
                entry.user_id,
                entry.question,
                json.dumps(entry.retrieved_doc_ids, ensure_ascii=False),
                json.dumps(entry.cited_chunks, ensure_ascii=False),
                entry.answer,
                entry.answer[:200] if entry.answer else "",
                entry.confidence,
                entry.intent,
                entry.model,
                entry.latency_ms,
                json.dumps(entry.security_alerts, ensure_ascii=False),
                1 if entry.verification_passed else 0,
                entry.timestamp or time.time(),
            ),
        )
        self.conn.commit()
        return eid

    def query(
        self,
        tenant_id: str = None,
        user_id: str = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict]:
        """查询审计记录"""
        conditions = []
        params = []

        if tenant_id:
            conditions.append("tenant_id = ?")
            params.append(tenant_id)
        if user_id:
            conditions.append("user_id = ?")
            params.append(user_id)

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        rows = self.conn.execute(
            f"SELECT id, tenant_id, user_id, question, answer_short, "
            f"confidence, intent, model, latency_ms, created_at "
            f"FROM audit_log {where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
            params + [limit, offset],
        ).fetchall()

        return [
            {
                "id": r[0], "tenant_id": r[1], "user_id": r[2],
                "question": r[3], "answer_preview": r[4],
                "confidence": r[5], "intent": r[6], "model": r[7],
                "latency_ms": r[8], "timestamp": r[9],
            }
            for r in rows
        ]

    def stats(self, tenant_id: str = None) -> dict:
        """审计统计"""
        where = f"WHERE tenant_id = ?" if tenant_id else ""
        params = (tenant_id,) if tenant_id else ()

        total = self.conn.execute(
            f"SELECT COUNT(*) FROM audit_log {where}", params
        ).fetchone()[0]

        avg_conf = self.conn.execute(
            f"SELECT AVG(confidence) FROM audit_log {where}", params
        ).fetchone()[0] or 0.0

        avg_latency = self.conn.execute(
            f"SELECT AVG(latency_ms) FROM audit_log {where}", params
        ).fetchone()[0] or 0.0

        alerts = self.conn.execute(
            f"SELECT COUNT(*) FROM audit_log {where} "
            f"{'AND' if tenant_id else 'WHERE'} verification_passed = 0",
            params,
        ).fetchone()[0]

        return {
            "total_queries": total,
            "avg_confidence": round(avg_conf, 3),
            "avg_latency_ms": round(avg_latency, 1),
            "security_alerts": alerts,
        }

    def close(self):
        self.conn.close()
