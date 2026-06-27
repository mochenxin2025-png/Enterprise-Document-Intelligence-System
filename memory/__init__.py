"""Memory System — Session / Conversation / Long-term 三层记忆 + Consolidation

Storage View:
  Session Memory      → SQLite, TTL 30min-24h
  Conversation Memory → SQLite, 永久
  Long-term Memory    → SQLite, 永久 (Semantic + Procedural)

Semantic View:
  Episodic    → Session(临时) + Conversation(历史)
  Semantic    → Long-term(事实)
  Procedural  → Long-term(偏好)
"""
import json
import sqlite3
import time
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class MemoryEntry:
    user_id: str = "default"
    content: str = ""
    memory_type: str = "episodic"  # episodic | semantic | procedural
    importance: float = 0.5
    source: str = ""
    metadata: dict = field(default_factory=dict)
    timestamp: float = 0.0


class MemoryStore:
    """SQLite 三层记忆存储"""

    def __init__(self, db_path: str = "./data/edis.db"):
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self._init_tables()

    def _init_tables(self):
        # Session memory: 短期，带 TTL
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS session_memory (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT DEFAULT 'default',
                content TEXT,
                memory_type TEXT DEFAULT 'episodic',
                importance REAL DEFAULT 0.5,
                source TEXT,
                created_at REAL,
                expires_at REAL
            )
        """)
        # Conversation history: 完整对话
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS conversation_memory (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT DEFAULT 'default',
                role TEXT,              -- user / assistant / system
                content TEXT,
                conversation_id TEXT,
                created_at REAL
            )
        """)
        # Long-term memory: 提炼后的事实/偏好
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS long_term_memory (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT DEFAULT 'default',
                content TEXT,
                memory_type TEXT,       -- semantic / procedural
                importance REAL DEFAULT 0.5,
                source TEXT,
                created_at REAL,
                last_accessed REAL
            )
        """)
        self.conn.commit()

    # ── Session Memory ─────────────────────────

    def remember_session(self, content: str, user_id: str = "default",
                         importance: float = 0.5, ttl_minutes: int = 60):
        now = time.time()
        self.conn.execute(
            "INSERT INTO session_memory (user_id, content, importance, created_at, expires_at) VALUES (?, ?, ?, ?, ?)",
            (user_id, content, importance, now, now + ttl_minutes * 60),
        )
        self.conn.commit()

    def recall_session(self, user_id: str = "default", limit: int = 10) -> list[MemoryEntry]:
        """获取当前有效的会话记忆"""
        now = time.time()
        rows = self.conn.execute(
            "SELECT content, memory_type, importance, source, created_at FROM session_memory "
            "WHERE user_id = ? AND expires_at > ? ORDER BY importance DESC, created_at DESC LIMIT ?",
            (user_id, now, limit),
        ).fetchall()
        return [MemoryEntry(user_id=user_id, content=r[0], memory_type=r[1],
                           importance=r[2], source=r[3], timestamp=r[4]) for r in rows]

    def expire_sessions(self):
        """清理过期会话"""
        self.conn.execute("DELETE FROM session_memory WHERE expires_at < ?", (time.time(),))
        self.conn.commit()

    # ── Conversation Memory ────────────────────

    def log_conversation(self, role: str, content: str, user_id: str = "default",
                         conversation_id: str = ""):
        self.conn.execute(
            "INSERT INTO conversation_memory (user_id, role, content, conversation_id, created_at) VALUES (?, ?, ?, ?, ?)",
            (user_id, role, content, conversation_id, time.time()),
        )
        self.conn.commit()

    def get_conversation(self, user_id: str = "default", conversation_id: str = "",
                         limit: int = 50) -> list[dict]:
        rows = self.conn.execute(
            "SELECT role, content, created_at FROM conversation_memory "
            "WHERE user_id = ? AND conversation_id = ? ORDER BY created_at ASC LIMIT ?",
            (user_id, conversation_id, limit),
        ).fetchall()
        return [{"role": r[0], "content": r[1], "time": r[2]} for r in rows]

    # ── Long-term Memory ───────────────────────

    def remember_fact(self, content: str, memory_type: str = "semantic",
                      user_id: str = "default", importance: float = 0.5, source: str = ""):
        self.conn.execute(
            "INSERT INTO long_term_memory (user_id, content, memory_type, importance, source, created_at, last_accessed) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (user_id, content, memory_type, importance, source, time.time(), time.time()),
        )
        self.conn.commit()

    def recall_facts(self, user_id: str = "default", memory_type: str | None = None,
                     limit: int = 20) -> list[MemoryEntry]:
        query = "SELECT content, memory_type, importance, source, created_at FROM long_term_memory WHERE user_id = ?"
        params = [user_id]
        if memory_type:
            query += " AND memory_type = ?"
            params.append(memory_type)
        query += " ORDER BY importance DESC, last_accessed DESC LIMIT ?"
        params.append(limit)

        rows = self.conn.execute(query, params).fetchall()
        # 更新访问时间
        ids = self.conn.execute(
            "SELECT id FROM long_term_memory WHERE user_id = ? ORDER BY importance DESC LIMIT ?",
            (user_id, limit)
        ).fetchall()
        for (mid,) in ids:
            self.conn.execute("UPDATE long_term_memory SET last_accessed = ? WHERE id = ?",
                              (time.time(), mid))
        self.conn.commit()

        return [MemoryEntry(user_id=user_id, content=r[0], memory_type=r[1],
                           importance=r[2], source=r[3], timestamp=r[4]) for r in rows]

    def count_long_term(self, user_id: str = "default") -> int:
        row = self.conn.execute(
            "SELECT COUNT(*) FROM long_term_memory WHERE user_id = ?", (user_id,)
        ).fetchone()
        return row[0] if row else 0

    # ── Consolidation ───────────────────────────

    def consolidate(self, user_id: str = "default", max_facts: int = 500) -> int:
        """记忆整理：压缩历史对话 → 提炼长期事实，超过上限时合并低重要度记忆"""
        # 1. 清理过期 session
        self.expire_sessions()

        # 2. 如果长期记忆超限，合并相似项
        count = self.count_long_term(user_id)
        if count > max_facts:
            # 删除重要性最低的超出部分
            excess = count - max_facts + 50  # 多删一点留空间
            self.conn.execute(
                "DELETE FROM long_term_memory WHERE id IN ("
                "SELECT id FROM long_term_memory WHERE user_id = ? "
                "ORDER BY importance ASC, last_accessed ASC LIMIT ?)",
                (user_id, excess),
            )
            self.conn.commit()

        # 3. 从最近的对话中提取潜在长期事实
        recent = self.get_conversation(user_id, limit=100)
        new_facts = self._extract_facts(recent)

        added = 0
        for fact in new_facts:
            # 检查是否已存在相似的事实
            existing = self.conn.execute(
                "SELECT id FROM long_term_memory WHERE user_id = ? AND content LIKE ?",
                (user_id, f"%{fact[:30]}%"),
            ).fetchone()
            if not existing:
                self.remember_fact(fact, "semantic", user_id, 0.3, "consolidation")
                added += 1

        return added

    def _extract_facts(self, conversation: list[dict]) -> list[str]:
        """从对话中提取潜在事实（轻量启发式）"""
        facts = []
        import re
        patterns = [
            r'(?:I|i)\s+(?:am|prefer|like|use|work|study|learn)\s+(.+)',
            r'(?:my|the)\s+(\w+(?:\s+\w+){1,4})\s+(?:is|are|was|were)\s+(.+)',
            r'(?:use|using|prefer|prefers|like|likes)\s+(.+)',
        ]
        for msg in conversation:
            if msg["role"] != "user":
                continue
            text = msg["content"]
            for pat in patterns:
                match = re.search(pat, text, re.IGNORECASE)
                if match:
                    fact = match.group(0).strip().rstrip(".")
                    if len(fact) > 10:
                        facts.append(fact)
                    break
        return facts[:5]  # 每次最多提取 5 条

    def close(self):
        self.conn.close()
