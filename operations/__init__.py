"""Operations — Embedding Version 追踪 + Cost Manager

Embedding Version: 防止不同版本模型产生的向量混用
Cost Manager: Token/API 调用成本统计
"""
import time
import json
import sqlite3
from dataclasses import dataclass, field


# ── Embedding Version ──────────────────────────

EMBEDDING_VERSION = "bge-large-zh-v1.5:v1"
EMBEDDING_DIM = 1024


def get_embedding_version() -> str:
    return EMBEDDING_VERSION


def check_version_compatibility(db_path: str) -> bool:
    """检查 DB 中已有向量的版本是否与当前一致"""
    try:
        conn = sqlite3.connect(db_path)
        row = conn.execute(
            "SELECT value FROM kv_store WHERE key='embedding_version'"
        ).fetchone()
        conn.close()
        if row is None:
            # 首次使用，写入版本
            _set_version(db_path, EMBEDDING_VERSION)
            return True
        return row[0] == EMBEDDING_VERSION
    except Exception:
        return True


def _set_version(db_path: str, version: str):
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS kv_store (key TEXT PRIMARY KEY, value TEXT)"
    )
    conn.execute("INSERT OR REPLACE INTO kv_store VALUES ('embedding_version', ?)", (version,))
    conn.execute(
        "INSERT OR REPLACE INTO kv_store VALUES ('embedding_dim', ?)", (str(EMBEDDING_DIM),)
    )
    conn.commit()
    conn.close()


# ── Cost Manager ───────────────────────────────

@dataclass
class CostRecord:
    operation: str      # llm / embedding / ocr
    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    latency_ms: float = 0.0
    timestamp: float = 0.0
    tenant_id: str = "default"

# 参考价格 (USD / 1M tokens)
PRICE_MAP = {
    "deepseek-chat":       (0.14, 0.28),    # input, output
    "deepseek-reasoner":   (0.55, 2.19),
    "gpt-4o-mini":         (0.15, 0.60),
    "gpt-4o":              (2.50, 10.00),
    "abab6.5s-chat":       (0.10, 0.10),
}


class CostManager:
    """成本追踪器"""

    def __init__(self, db_path: str = "./data/edis.db"):
        self.conn = sqlite3.connect(db_path)
        self._init_table()

    def _init_table(self):
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS cost_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant_id TEXT DEFAULT 'default',
                operation TEXT,
                model TEXT,
                input_tokens INTEGER DEFAULT 0,
                output_tokens INTEGER DEFAULT 0,
                cost_usd REAL DEFAULT 0.0,
                latency_ms REAL DEFAULT 0.0,
                metadata TEXT DEFAULT '{}',
                created_at REAL
            )
        """)
        self.conn.commit()

    def record_llm(self, model: str, input_tokens: int, output_tokens: int,
                   latency_ms: float = 0, tenant_id: str = "default", metadata: dict = None):
        prices = PRICE_MAP.get(model, (0.0, 0.0))
        cost = (input_tokens / 1_000_000) * prices[0] + (output_tokens / 1_000_000) * prices[1]
        self.conn.execute(
            "INSERT INTO cost_log (tenant_id, operation, model, input_tokens, output_tokens, cost_usd, latency_ms, metadata, created_at) "
            "VALUES (?, 'llm', ?, ?, ?, ?, ?, ?, ?)",
            (tenant_id, model, input_tokens, output_tokens, round(cost, 6), latency_ms,
             json.dumps(metadata or {}), time.time()),
        )
        self.conn.commit()

    def stats(self, tenant_id: str = None) -> dict:
        """成本汇总"""
        where = f"WHERE tenant_id='{tenant_id}'" if tenant_id else ""
        row = self.conn.execute(
            f"SELECT COUNT(*), SUM(input_tokens), SUM(output_tokens), SUM(cost_usd), SUM(latency_ms) FROM cost_log {where}"
        ).fetchone()
        return {
            "total_calls": row[0] or 0,
            "total_input_tokens": row[1] or 0,
            "total_output_tokens": row[2] or 0,
            "total_cost_usd": round(row[3] or 0, 4),
            "total_latency_s": round((row[4] or 0) / 1000, 1),
        }

    def close(self):
        self.conn.close()
