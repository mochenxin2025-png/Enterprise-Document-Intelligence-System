"""Incremental Indexing — Page/Chunk SHA256 指纹 + 增量重建

文档更新时：
  1. 比较旧版和新版的 Page Hash → 找出变更页
  2. 比较 Chunk Hash → 只重建变更 Chunk 的 Embedding
  3. 未变更的 Chunk 直接复用向量的 rowid 映射
  4. Graph Patch: INSERT 新增节点，MARK DEPRECATED 删除节点
"""
import hashlib
import sqlite3
from dataclasses import dataclass
from typing import Optional


@dataclass
class PageFingerprint:
    page_num: int
    hash: str
    changed: bool = False


@dataclass
class ChunkFingerprint:
    chunk_index: int
    page: int
    hash: str
    text: str = ""
    changed: bool = False


class IncrementalIndexer:
    """增量索引器 — 指纹比对 + 增量更新"""

    def __init__(self, db_path: str = "./data/edis.db"):
        self.conn = sqlite3.connect(db_path)
        self._init_tables()

    def _init_tables(self):
        # 页面指纹表
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS page_fingerprints (
                doc_id TEXT,
                page_num INTEGER,
                hash TEXT,
                created_at REAL,
                PRIMARY KEY (doc_id, page_num)
            )
        """)
        # Chunk 指纹表
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS chunk_fingerprints (
                doc_id TEXT,
                chunk_index INTEGER,
                page INTEGER,
                hash TEXT,
                chunk_rowid INTEGER,  -- 对应 chunks 表的 rowid
                created_at REAL,
                PRIMARY KEY (doc_id, chunk_index)
            )
        """)
        self.conn.commit()

    def fingerprint_pages(self, doc_id: str, pages: list) -> list[PageFingerprint]:
        """为每个页面生成 SHA256 指纹，并与旧版比较"""
        old_hashes = self._get_page_hashes(doc_id)
        fingerprints = []

        for page in pages:
            text = getattr(page, 'text', '') or str(page)
            page_hash = hashlib.sha256(text.encode()).hexdigest()[:16]
            changed = old_hashes.get(page.page_num if hasattr(page, 'page_num') else 0) != page_hash
            fingerprints.append(PageFingerprint(
                page_num=page.page_num if hasattr(page, 'page_num') else 0,
                hash=page_hash, changed=changed,
            ))

        return fingerprints

    def fingerprint_chunks(self, doc_id: str, chunks: list) -> list[ChunkFingerprint]:
        """为每个 Chunk 生成 SHA256 指纹"""
        import time
        old_hashes = self._get_chunk_hashes(doc_id)
        fingerprints = []

        for chunk in chunks:
            ch_hash = hashlib.sha256(chunk.text.encode()).hexdigest()[:16]
            changed = old_hashes.get(chunk.chunk_index) != ch_hash
            fingerprints.append(ChunkFingerprint(
                chunk_index=chunk.chunk_index, page=chunk.page,
                hash=ch_hash, text=chunk.text, changed=changed,
            ))

        return fingerprints

    def store_fingerprints(self, doc_id: str, fingerprints: list[ChunkFingerprint],
                           chunk_rowids: dict[int, int]):
        """存储指纹 + chunk_rowid 映射"""
        import time
        now = time.time()
        for fp in fingerprints:
            rowid = chunk_rowids.get(fp.chunk_index, 0)
            self.conn.execute(
                "INSERT OR REPLACE INTO chunk_fingerprints (doc_id, chunk_index, page, hash, chunk_rowid, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (doc_id, fp.chunk_index, fp.page, fp.hash, rowid, now),
            )
        self.conn.commit()

    def get_changed_chunks(self, doc_id: str, chunks: list) -> tuple[list, list]:
        """返回 (changed_chunks, unchanged_chunks)"""
        fps = self.fingerprint_chunks(doc_id, chunks)
        changed = [c for c, fp in zip(chunks, fps) if fp.changed]
        unchanged = [c for c, fp in zip(chunks, fps) if not fp.changed]
        return changed, unchanged

    def get_unchanged_rowids(self, doc_id: str) -> dict[int, int]:
        """获取未变更 Chunk 的 rowid 映射 {chunk_index: chunk_rowid}"""
        rows = self.conn.execute(
            "SELECT chunk_index, chunk_rowid FROM chunk_fingerprints WHERE doc_id = ?",
            (doc_id,)
        ).fetchall()
        return {r[0]: r[1] for r in rows if r[1] > 0}

    def _get_page_hashes(self, doc_id: str) -> dict[int, str]:
        rows = self.conn.execute(
            "SELECT page_num, hash FROM page_fingerprints WHERE doc_id = ?", (doc_id,)
        ).fetchall()
        return {r[0]: r[1] for r in rows}

    def _get_chunk_hashes(self, doc_id: str) -> dict[int, str]:
        rows = self.conn.execute(
            "SELECT chunk_index, hash FROM chunk_fingerprints WHERE doc_id = ?", (doc_id,)
        ).fetchall()
        return {r[0]: r[1] for r in rows}

    def close(self):
        self.conn.close()
