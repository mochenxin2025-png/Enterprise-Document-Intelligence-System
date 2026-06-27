"""QA Pair Registry — 运营填写的知识补丁库

优先级最高：每次问答先查 QA Pair，命中直接返回，不调 LLM。
"""
import hashlib
import sqlite3
import time
import re
from dataclasses import dataclass
from typing import Optional


@dataclass
class QAPair:
    id: str
    question: str
    answer: str
    tags: list[str]
    source: str = "manual"
    hit_count: int = 0


class QARegistry:
    """SQLite QA 对存储 + 精确/模糊匹配"""

    def __init__(self, db_path: str = "./data/edis.db"):
        self.conn = sqlite3.connect(db_path)
        self._init_tables()

    def _init_tables(self):
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS qa_pairs (
                id TEXT, tenant_id TEXT DEFAULT 'default',
                question TEXT, answer TEXT,
                tags TEXT DEFAULT '[]',
                source TEXT DEFAULT 'manual',
                created_by TEXT DEFAULT '',
                hit_count INTEGER DEFAULT 0,
                created_at REAL, updated_at REAL,
                PRIMARY KEY (id, tenant_id)
            )
        """)
        self.conn.commit()

    def add(self, question: str, answer: str, tags: list[str] = None,
            source: str = "manual", created_by: str = "", tenant_id: str = "default") -> str:
        import json
        qid = hashlib.sha256(question.encode()).hexdigest()[:12]
        now = time.time()
        self.conn.execute(
            "INSERT OR REPLACE INTO qa_pairs (id, tenant_id, question, answer, tags, source, created_by, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (qid, tenant_id, question, answer, json.dumps(tags or []), source, created_by, now),
        )
        self.conn.commit()
        return qid

    def search(self, query: str, threshold: float = 0.65, tenant_id: str = "default") -> Optional[QAPair]:
        """精确 + 模糊匹配。命中则更新 hit_count。"""
        import json

        # 1. 精确匹配
        row = self.conn.execute(
            "SELECT id, question, answer, tags, source, hit_count FROM qa_pairs "
            "WHERE question = ? AND tenant_id = ?",
            (query.strip(), tenant_id)
        ).fetchone()
        if row:
            self._hit(row[0])
            return QAPair(id=row[0], question=row[1], answer=row[2],
                         tags=json.loads(row[3]), source=row[4], hit_count=row[5])

        # 2. 模糊匹配：遍历该租户所有 QA Pair
        all_rows = self.conn.execute(
            "SELECT id, question, answer, tags, source, hit_count FROM qa_pairs WHERE tenant_id=?",
            (tenant_id,)
        ).fetchall()
        best_score = 0.0
        best_row = None
        for row in all_rows:
            sim = self._similarity(query, row[1])
            if sim > best_score and sim >= threshold:
                best_score = sim
                best_row = row

        if best_row:
            self._hit(best_row[0])
            return QAPair(id=best_row[0], question=best_row[1], answer=best_row[2],
                         tags=json.loads(best_row[3]), source=best_row[4], hit_count=best_row[5])

        return None

    def list_all(self) -> list[dict]:
        import json
        rows = self.conn.execute(
            "SELECT id, question, answer, tags, source, hit_count FROM qa_pairs ORDER BY hit_count DESC"
        ).fetchall()
        return [{"id": r[0], "question": r[1], "answer": r[2][:80],
                "tags": json.loads(r[3]), "hit_count": r[5]} for r in rows]

    def _hit(self, qid: str):
        self.conn.execute("UPDATE qa_pairs SET hit_count = hit_count + 1, updated_at = ? WHERE id = ?",
                         (time.time(), qid))
        self.conn.commit()

    @staticmethod
    def _fts_query(query: str) -> str:
        """将用户问题转为 FTS5 查询 — 中文按字切分"""
        tokens = []
        for ch in query:
            if '\u4e00' <= ch <= '\u9fff':
                tokens.append(ch)
        for word in re.findall(r'[a-zA-Z0-9]+', query.lower()):
            tokens.append(word)
        return " OR ".join(f'"{t}"' for t in tokens[:20])

    @staticmethod
    def _similarity(a: str, b: str) -> float:
        """token overlap — 中文按字，英文按词，过滤停用字"""
        STOP_CHARS = set('的是不在了有这和个为可以就也都要会对与及或能把被让从到什么吗呢啊')
        def _tokens(s):
            t = set()
            for ch in s.lower():
                if '\u4e00' <= ch <= '\u9fff' and ch not in STOP_CHARS:
                    t.add(ch)
            for w in re.findall(r'[a-zA-Z0-9]+', s.lower()):
                if len(w) >= 2:
                    t.add(w)
            return t
        ta = _tokens(a)
        tb = _tokens(b)
        if not ta or not tb:
            return 0.0
        return len(ta & tb) / min(len(ta), len(tb))

    def close(self):
        self.conn.close()
