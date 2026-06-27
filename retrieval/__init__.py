"""向量存储 + 语义检索 — sqlite-vec + BGE（绕过 sentence-transformers）"""
import os
import sqlite3
from pathlib import Path
from dataclasses import dataclass
from typing import Optional

import sqlite_vec
import numpy as np
import torch
from transformers import AutoTokenizer, AutoModel


@dataclass
class SearchResult:
    chunk_index: int
    text: str
    score: float
    page: int
    chapter: str = ""
    section: str = ""
    source: str = ""


class VectorStore:
    """sqlite-vec 向量存储。"""

    def __init__(self, db_path: str = "./data/edis.db"):
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.execute("PRAGMA journal_mode=WAL")       # 支持并发读
        self.conn.execute("PRAGMA busy_timeout=5000")       # 5s 等待锁
        self.conn.enable_load_extension(True)
        sqlite_vec.load(self.conn)
        self.conn.enable_load_extension(False)
        self._init_tables()
    def _init_tables(self):
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS documents (
                id TEXT, tenant_id TEXT DEFAULT 'default',
                filename TEXT, path TEXT,
                page_count INTEGER, total_chars INTEGER, metadata TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (id, tenant_id)
            )
        """)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS chunks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant_id TEXT DEFAULT 'default',
                document_id TEXT, chunk_index INTEGER, text TEXT,
                page INTEGER, chapter TEXT, section TEXT, metadata TEXT,
                FOREIGN KEY (document_id) REFERENCES documents(id)
            )
        """)
        self.conn.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS chunk_embeddings
            USING vec0(embedding float[1024])
        """)
        self.conn.commit()

    def insert_document(self, doc_id, filename, path, page_count, total_chars, metadata,
                        tenant_id: str = "default"):
        import json
        self.conn.execute(
            "INSERT OR REPLACE INTO documents (id, tenant_id, filename, path, page_count, total_chars, metadata) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (doc_id, tenant_id, filename, path, page_count, total_chars, json.dumps(metadata)),
        )
        self.conn.commit()
        return self.conn.execute("SELECT changes()").fetchone()[0]

    def insert_chunk(self, doc_id, chunk_index, text, page, chapter, section, metadata,
                     tenant_id: str = "default"):
        import json
        self.conn.execute(
            "INSERT INTO chunks (tenant_id, document_id, chunk_index, text, page, chapter, section, metadata) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (tenant_id, doc_id, chunk_index, text, page, chapter, section, json.dumps(metadata)),
        )
        self.conn.commit()
        return self.conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    def insert_embedding(self, chunk_rowid, embedding):
        self.conn.execute(
            "INSERT INTO chunk_embeddings (rowid, embedding) VALUES (?, ?)",
            (chunk_rowid, np.array(embedding, dtype=np.float32).tobytes()),
        )
        self.conn.commit()

    def search(self, query_embedding, top_k=10):
        emb_bytes = np.array(query_embedding, dtype=np.float32).tobytes()
        rows = self.conn.execute(
            """
            SELECT c.chunk_index, c.text, c.page, c.chapter, c.section, d.filename,
                   vec_distance_L2(ce.embedding, ?) AS distance
            FROM chunk_embeddings ce
            JOIN chunks c ON ce.rowid = c.id
            JOIN documents d ON c.document_id = d.id
            ORDER BY distance ASC LIMIT ?
            """,
            (emb_bytes, top_k),
        ).fetchall()

        results = []
        for row in rows:
            chunk_idx, text, page, chapter, section, filename, distance = row
            score = max(0, 1.0 - distance / 100.0)
            results.append(SearchResult(
                chunk_index=chunk_idx, text=text, score=round(score, 4),
                page=page, chapter=chapter or "", section=section or "", source=filename or "",
            ))
        return results

    def close(self):
        self.conn.close()


class Embedder:
    """BGE 本地 embedding — 直接使用 transformers（绕过 sentence-transformers 沙箱死锁）。

    使用 mean pooling + L2 normalize 产生 sentence embedding。
    """

    _tokenizer = None
    _model = None
    _model_paths = [
        "./data/models/BAAI/bge-large-zh-v1___5",   # modelscope cache
        "./data/models/BAAI/bge-large-zh-v1.5",      # HF cache
    ]

    @classmethod
    def _find_path(cls):
        for p in cls._model_paths:
            if os.path.exists(p):
                return p
        return cls._model_paths[0]

    @classmethod
    def _ensure_loaded(cls):
        if cls._model is None:
            path = cls._find_path()
            cls._tokenizer = AutoTokenizer.from_pretrained(path, local_files_only=True)
            cls._model = AutoModel.from_pretrained(path, local_files_only=True)
            cls._model.eval()

    @classmethod
    def _mean_pooling(cls, model_output, attention_mask):
        """Mean pooling — 对所有 token 的 hidden states 取平均（masked）"""
        token_embeddings = model_output.last_hidden_state
        input_mask_expanded = attention_mask.unsqueeze(-1).expand(token_embeddings.size()).float()
        return torch.sum(token_embeddings * input_mask_expanded, 1) / torch.clamp(input_mask_expanded.sum(1), min=1e-9)

    @classmethod
    def encode(cls, texts, batch_size=32, device="cpu"):
        cls._ensure_loaded()
        all_embeddings = []

        for i in range(0, len(texts), batch_size):
            batch = texts[i:i + batch_size]
            encoded = cls._tokenizer(batch, padding=True, truncation=True,
                                     max_length=512, return_tensors="pt")
            with torch.no_grad():
                outputs = cls._model(**encoded)
                embeddings = cls._mean_pooling(outputs, encoded["attention_mask"])
                # L2 normalize
                embeddings = torch.nn.functional.normalize(embeddings, p=2, dim=1)
            all_embeddings.append(embeddings.cpu().numpy())

        return np.concatenate(all_embeddings, axis=0).tolist()

    @classmethod
    def encode_query(cls, query, device="cpu"):
        """查询编码（BGE 系列需加 instruction prefix）"""
        return cls.encode([f"为这个句子生成表示以用于检索相关文章：{query}"])[0]
