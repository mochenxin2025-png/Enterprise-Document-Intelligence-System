"""Batch Ingestor — 10000+ 文档队列调度 + 断点续传 + 容错

用法:
  python batch_ingest.py scan <directory> [--tenant <id>]   → 扫描目录入队
  python batch_ingest.py process [--tenant <id>] [--workers N] → 处理队列
  python batch_ingest.py status [--tenant <id>]             → 查看进度
"""
import os
import sys
import json
import time
import hashlib
import sqlite3
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, str(Path(__file__).parent))

from config import config
from ingestion import parse_pdf
from ingestion.chunker import HierarchicalChunker
from cleaning import clean_pipeline
from retrieval import VectorStore, Embedder

SUPPORTED_EXTENSIONS = {".pdf", ".txt", ".md"}
MAX_FILE_SIZE_MB = 200
MAX_RETRIES = 3


class ProcessingQueue:
    """SQLite 任务队列 — 断点续传 + 进度追踪"""

    def __init__(self, db_path: str = "./data/edis.db"):
        self.conn = sqlite3.connect(db_path)
        self._init_tables()

    def _init_tables(self):
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS processing_queue (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant_id TEXT DEFAULT 'default',
                filepath TEXT,
                file_size INTEGER,
                file_type TEXT,
                checksum TEXT,
                status TEXT DEFAULT 'pending',
                chunks_created INTEGER DEFAULT 0,
                error_log TEXT,
                retry_count INTEGER DEFAULT 0,
                created_at REAL,
                started_at REAL,
                completed_at REAL,
                UNIQUE(tenant_id, checksum)
            )
        """)
        self.conn.commit()

    def scan_directory(self, directory: str, tenant_id: str = "default") -> int:
        """扫描目录，去重后入队。返回新增数量。"""
        added = 0
        total = 0
        for root, dirs, files in os.walk(directory):
            for fname in files:
                total += 1
                fpath = os.path.join(root, fname)
                ext = Path(fname).suffix.lower()
                if ext not in SUPPORTED_EXTENSIONS:
                    continue
                try:
                    fsize = os.path.getsize(fpath)
                except OSError:
                    continue
                if fsize > MAX_FILE_SIZE_MB * 1024 * 1024:
                    continue

                checksum = hashlib.sha256(fpath.encode()).hexdigest()[:16]
                existing = self.conn.execute(
                    "SELECT id FROM processing_queue WHERE tenant_id=? AND checksum=?",
                    (tenant_id, checksum)
                ).fetchone()
                if existing:
                    continue

                self.conn.execute(
                    "INSERT INTO processing_queue (tenant_id, filepath, file_size, file_type, checksum, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (tenant_id, fpath, fsize, ext, checksum, time.time()),
                )
                added += 1

        self.conn.commit()
        print(f"[scan] {total} files found, {added} new queued (tenant={tenant_id})")
        return added

    def get_next_batch(self, tenant_id: str = "default", batch_size: int = 10) -> list[dict]:
        """取下一批待处理任务"""
        rows = self.conn.execute(
            "SELECT id, filepath, file_size, file_type, checksum, retry_count "
            "FROM processing_queue WHERE tenant_id=? AND status IN ('pending', 'failed') "
            "ORDER BY file_size ASC LIMIT ?",
            (tenant_id, batch_size),
        ).fetchall()
        return [
            {"id": r[0], "path": r[1], "size": r[2], "type": r[3],
             "checksum": r[4], "retries": r[5]}
            for r in rows
        ]

    def mark_started(self, task_id: int):
        self.conn.execute(
            "UPDATE processing_queue SET status='processing', started_at=? WHERE id=?",
            (time.time(), task_id),
        )
        self.conn.commit()

    def mark_done(self, task_id: int, chunks: int = 0):
        self.conn.execute(
            "UPDATE processing_queue SET status='done', chunks_created=?, completed_at=? WHERE id=?",
            (chunks, time.time(), task_id),
        )
        self.conn.commit()

    def mark_failed(self, task_id: int, error: str):
        self.conn.execute(
            "UPDATE processing_queue SET status='failed', error_log=?, retry_count=retry_count+1 WHERE id=?",
            (error[:500], task_id),
        )
        self.conn.commit()

    def stats(self, tenant_id: str = "default") -> dict:
        for status in ['pending', 'processing', 'done', 'failed']:
            count = self.conn.execute(
                "SELECT COUNT(*) FROM processing_queue WHERE tenant_id=? AND status=?",
                (tenant_id, status)
            ).fetchone()[0]
            print(f"  {status}: {count}")
        self.conn.commit()

    def close(self):
        self.conn.close()


def process_one(filepath: str, tenant_id: str) -> tuple[int, str]:
    """处理单个文件 → 返回 (chunks_created, error)"""
    try:
        doc = parse_pdf(filepath)
        chunker = HierarchicalChunker(
            chunk_size=config.get("ingestion", "chunk_size"),
            chunk_overlap=config.get("ingestion", "chunk_overlap"),
        )
        chunks = chunker.chunk(doc)

        store = VectorStore(config.get("storage", "db_path"))
        store.insert_document(doc.document_id, doc.filename, filepath,
                             doc.page_count, doc.total_chars, doc.metadata, tenant_id)
        texts = [ch.text for ch in chunks]
        embeddings = Embedder.encode(texts, batch_size=config.get("embedding", "batch_size"))
        for chunk, emb in zip(chunks, embeddings):
            rowid = store.insert_chunk(doc.document_id, chunk.chunk_index, chunk.text,
                                      chunk.page, chunk.chapter, chunk.section, chunk.metadata, tenant_id)
            store.insert_embedding(rowid, emb)
        store.close()
        return len(chunks), ""
    except Exception as e:
        return 0, str(e)[:200]


def process_batch(tenant_id: str = "default", workers: int = 2):
    """批量处理队列中的任务"""
    queue = ProcessingQueue()
    total_done = 0
    total_failed = 0

    while True:
        batch = queue.get_next_batch(tenant_id, batch_size=workers * 5)
        if not batch:
            print("[batch] Queue empty.")
            break

        print(f"[batch] Processing {len(batch)} files...")
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {}
            for task in batch:
                if task["retries"] >= MAX_RETRIES:
                    queue.mark_failed(task["id"], "Max retries exceeded")
                    continue
                queue.mark_started(task["id"])
                f = executor.submit(process_one, task["path"], tenant_id)
                futures[f] = task

            for future in as_completed(futures):
                task = futures[future]
                try:
                    chunks, error = future.result()
                    if error:
                        queue.mark_failed(task["id"], error)
                        total_failed += 1
                        print(f"  ✗ {Path(task['path']).name}: {error[:60]}")
                    else:
                        queue.mark_done(task["id"], chunks)
                        total_done += 1
                        print(f"  ✓ {Path(task['path']).name}: {chunks} chunks")
                except Exception as e:
                    queue.mark_failed(task["id"], str(e)[:200])
                    total_failed += 1

        print(f"[batch] Progress: {total_done} done, {total_failed} failed")

    queue.stats(tenant_id)
    queue.close()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python batch_ingest.py scan <directory> [--tenant <id>]")
        print("  python batch_ingest.py process [--tenant <id>] [--workers N]")
        print("  python batch_ingest.py status [--tenant <id>]")
        sys.exit(1)

    cmd = sys.argv[1]
    args = sys.argv[2:]
    tenant = "default"
    workers = 2

    i = 0
    while i < len(args):
        if args[i] == "--tenant" and i + 1 < len(args):
            tenant = args[i + 1]
            i += 2
        elif args[i] == "--workers" and i + 1 < len(args):
            workers = int(args[i + 1])
            i += 2
        else:
            i += 1

    if cmd == "scan":
        directory = args[0] if args else "."
        ProcessingQueue().scan_directory(directory, tenant)
    elif cmd == "process":
        process_batch(tenant, workers)
    elif cmd == "status":
        ProcessingQueue().stats(tenant)
