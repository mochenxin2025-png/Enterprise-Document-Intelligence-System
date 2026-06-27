"""Adapter Layer — 所有接口的具体实现

DeepSeekAdapter / OpenAIAdapter / MiniMaxAdapter → LLMInterface
BGEEmbedder → EmbeddingInterface
PyMuPDFParser → ParserInterface
SQLiteVecStore → VectorStoreInterface
"""
import os
import httpx
import numpy as np
from pathlib import Path
from typing import Optional

from interfaces import (
    LLMInterface, LLMResponse,
    EmbeddingInterface,
    ParserInterface, ParsedDoc,
    VectorStoreInterface, SearchHit,
)


# ── LLM Adapters ───────────────────────────────

class DeepSeekAdapter(LLMInterface):
    def __init__(self, api_key: str = None, model: str = "deepseek-chat",
                 base_url: str = "https://api.deepseek.com", temperature: float = 0.3):
        if api_key is None:
            from config.env_loader import load_hermes_env
            load_hermes_env()
            api_key = os.environ.get("DEEPSEEK_API_KEY", "")
        self._key = api_key
        self.model = model
        self.base_url = base_url
        self.temperature = temperature

    @property
    def model_name(self) -> str:
        return self.model

    def chat(self, messages: list[dict], **kwargs) -> LLMResponse:
        resp = httpx.post(
            f"{self.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self._key}", "Content-Type": "application/json"},
            json={
                "model": self.model,
                "messages": messages,
                "temperature": kwargs.get("temperature", self.temperature),
                "max_tokens": kwargs.get("max_tokens", 2048),
            },
            timeout=kwargs.get("timeout", 60),
        )
        resp.raise_for_status()
        data = resp.json()
        return LLMResponse(
            content=data["choices"][0]["message"]["content"],
            model=data.get("model", self.model),
            usage=data.get("usage", {}),
            raw=data,
        )


class OpenAIAdapter(LLMInterface):
    def __init__(self, api_key: str = None, model: str = "gpt-4o-mini",
                 base_url: str = "https://api.openai.com/v1", temperature: float = 0.3):
        self._key = api_key or os.environ.get("OPENAI_API_KEY", "")
        self.model = model
        self.base_url = base_url
        self.temperature = temperature

    @property
    def model_name(self) -> str:
        return self.model

    def chat(self, messages: list[dict], **kwargs) -> LLMResponse:
        resp = httpx.post(
            f"{self.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self._key}", "Content-Type": "application/json"},
            json={
                "model": self.model,
                "messages": messages,
                "temperature": kwargs.get("temperature", self.temperature),
                "max_tokens": kwargs.get("max_tokens", 2048),
            },
            timeout=kwargs.get("timeout", 60),
        )
        resp.raise_for_status()
        data = resp.json()
        return LLMResponse(
            content=data["choices"][0]["message"]["content"],
            model=data.get("model", self.model),
            usage=data.get("usage", {}),
            raw=data,
        )


class MiniMaxAdapter(LLMInterface):
    def __init__(self, api_key: str = None, model: str = "abab6.5s-chat",
                 base_url: str = "https://api.minimax.chat/v1/text/chatcompletion_v2",
                 temperature: float = 0.3):
        self._key = api_key or os.environ.get("MINIMAX_API_KEY", "")
        self.model = model
        self.base_url = base_url
        self.temperature = temperature

    @property
    def model_name(self) -> str:
        return self.model

    def chat(self, messages: list[dict], **kwargs) -> LLMResponse:
        resp = httpx.post(
            self.base_url,
            headers={"Authorization": f"Bearer {self._key}", "Content-Type": "application/json"},
            json={
                "model": self.model,
                "messages": messages,
                "temperature": kwargs.get("temperature", self.temperature),
                "max_tokens": kwargs.get("max_tokens", 2048),
            },
            timeout=kwargs.get("timeout", 60),
        )
        resp.raise_for_status()
        data = resp.json()
        return LLMResponse(
            content=data["choices"][0]["message"]["content"],
            model=self.model,
            usage=data.get("usage", {}),
            raw=data,
        )


# ── Embedding Adapter ──────────────────────────

class BGEEmbedder(EmbeddingInterface):
    """本地 BGE 模型 embedding"""
    _model = None
    _tokenizer = None

    def __init__(self, model_path: str = "./data/models/BAAI/bge-large-zh-v1___5",
                 device: str = "cpu"):
        self.model_path = model_path
        self.device = device
        self._ensure_loaded()

    def _ensure_loaded(self):
        if self._model is None:
            import torch
            from transformers import AutoTokenizer, AutoModel
            path = self.model_path if os.path.exists(self.model_path) else "BAAI/bge-large-zh-v1.5"
            self._tokenizer = AutoTokenizer.from_pretrained(path, local_files_only=(path == self.model_path))
            self._model = AutoModel.from_pretrained(path, local_files_only=(path == self.model_path))
            self._model.eval()

    @property
    def dimension(self) -> int:
        return 1024

    def encode(self, texts: list[str], batch_size: int = 32, **kwargs) -> list[list[float]]:
        import torch
        all_embeddings = []
        for i in range(0, len(texts), batch_size):
            batch = texts[i:i + batch_size]
            encoded = self._tokenizer(batch, padding=True, truncation=True, max_length=512, return_tensors="pt")
            with torch.no_grad():
                outputs = self._model(**encoded)
                token_embeddings = outputs.last_hidden_state
                attention_mask = encoded["attention_mask"]
                input_mask = attention_mask.unsqueeze(-1).expand(token_embeddings.size()).float()
                embeddings = torch.sum(token_embeddings * input_mask, 1) / torch.clamp(input_mask.sum(1), min=1e-9)
                embeddings = torch.nn.functional.normalize(embeddings, p=2, dim=1)
            all_embeddings.append(embeddings.cpu().numpy())
        return np.concatenate(all_embeddings, axis=0).tolist()

    def encode_query(self, query: str) -> list[float]:
        return self.encode([f"为这个句子生成表示以用于检索相关文章：{query}"])[0]


# ── Parser Adapter ─────────────────────────────

class PyMuPDFParser(ParserInterface):
    def parse(self, filepath: str) -> ParsedDoc:
        import fitz, hashlib
        doc = fitz.open(filepath)
        parsed = ParsedDoc(
            doc_id=hashlib.sha256(Path(filepath).read_bytes()).hexdigest()[:16],
            filename=Path(filepath).name,
            metadata={"format": "PDF", "title": doc.metadata.get("title", "")},
        )
        for i in range(len(doc)):
            page = doc[i]
            blocks = page.get_text("dict")["blocks"]
            text = "\n".join(
                "".join(s["text"] for s in line["spans"])
                for block in blocks if block["type"] == 0
                for line in block.get("lines", [])
            )
            parsed.pages.append({
                "num": i + 1,
                "text": text,
                "hash": hashlib.sha256(text.encode()).hexdigest()[:16],
            })
        parsed.page_count = len(parsed.pages)
        parsed.total_chars = sum(len(p["text"]) for p in parsed.pages)
        doc.close()
        return parsed

    @classmethod
    def supports(cls, filepath: str) -> bool:
        return Path(filepath).suffix.lower() in {".pdf"}


# ── VectorStore Adapter ────────────────────────

class SQLiteVecStore(VectorStoreInterface):
    def __init__(self, db_path: str = "./data/edis.db", dimension: int = 1024):
        import sqlite3, sqlite_vec
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self.conn = sqlite3.connect(db_path)
        self.conn.enable_load_extension(True)
        sqlite_vec.load(self.conn)
        self.conn.enable_load_extension(False)
        self._init(dimension)

    def _init(self, dim):
        self.conn.execute("CREATE TABLE IF NOT EXISTS vec_docs (id TEXT PRIMARY KEY, filename TEXT, metadata TEXT)")
        self.conn.execute("CREATE TABLE IF NOT EXISTS vec_chunks (id INTEGER PRIMARY KEY AUTOINCREMENT, doc_id TEXT, text TEXT, page INTEGER, metadata TEXT)")
        self.conn.execute(f"CREATE VIRTUAL TABLE IF NOT EXISTS vec_embeddings USING vec0(embedding float[{dim}])")
        self.conn.commit()

    def add(self, chunks: list[dict], embeddings: list[list[float]], doc_id: str):
        import json
        self.conn.execute("INSERT OR REPLACE INTO vec_docs (id, filename, metadata) VALUES (?, ?, ?)",
                         (doc_id, chunks[0].get("source", ""), "{}"))
        for chunk, emb in zip(chunks, embeddings):
            self.conn.execute(
                "INSERT INTO vec_chunks (doc_id, text, page, metadata) VALUES (?, ?, ?, ?)",
                (doc_id, chunk.get("text", ""), chunk.get("page", 0), json.dumps(chunk.get("metadata", {}))),
            )
            rowid = self.conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            self.conn.execute("INSERT INTO vec_embeddings (rowid, embedding) VALUES (?, ?)",
                             (rowid, np.array(emb, dtype=np.float32).tobytes()))
        self.conn.commit()

    def search(self, query_embedding: list[float], top_k: int = 10) -> list[SearchHit]:
        emb_bytes = np.array(query_embedding, dtype=np.float32).tobytes()
        rows = self.conn.execute(
            "SELECT c.id, c.text, c.page, vec_distance_L2(e.embedding, ?) AS dist FROM vec_embeddings e JOIN vec_chunks c ON e.rowid=c.id ORDER BY dist LIMIT ?",
            (emb_bytes, top_k)).fetchall()
        return [SearchHit(chunk_id=r[0], text=r[1], score=max(0, 1.0 - r[3] / 100.0), page=r[2]) for r in rows]

    def delete_document(self, doc_id: str):
        self.conn.execute("DELETE FROM vec_embeddings WHERE rowid IN (SELECT id FROM vec_chunks WHERE doc_id=?)", (doc_id,))
        self.conn.execute("DELETE FROM vec_chunks WHERE doc_id=?", (doc_id,))
        self.conn.execute("DELETE FROM vec_docs WHERE id=?", (doc_id,))
        self.conn.commit()

    def close(self):
        self.conn.close()
