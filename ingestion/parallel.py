"""并行解析器 — 大 PDF 自动分片并行处理

策略:
  - 默认单线程（< 100 页）
  - 100-500 页 → 按页数分片，ThreadPool 并行
  - > 500 页 → 按页数分片，ProcessPool 并行
"""
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Optional

from ingestion import parse_pdf, ParsedDocument, ParsedPage
from ingestion.chunker import HierarchicalChunker, Chunk
from cleaning import clean_pipeline


class ParallelIngestor:
    """并行导入器"""

    def __init__(self, chunk_size: int = 512, chunk_overlap: int = 64,
                 max_workers: int = 4, parallel_threshold: int = 100):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.max_workers = max_workers
        self.parallel_threshold = parallel_threshold

    def ingest(self, filepath: str) -> tuple[ParsedDocument, list[Chunk], list[dict]]:
        """完整导入：解析 → 清洗 → 分块（自动选择并行策略）"""
        filepath_obj = Path(filepath)
        doc = parse_pdf(str(filepath_obj))

        if doc.page_count < self.parallel_threshold:
            # 小文件：单线程
            cleaned = clean_pipeline(doc.pages)
            chunker = HierarchicalChunker(self.chunk_size, self.chunk_overlap)
            chunks = chunker.chunk(doc)
        else:
            # 大文件：分片并行
            cleaned, chunks = self._parallel_parse(filepath_obj, doc.page_count)

        return doc, chunks, cleaned

    def _parallel_parse(self, filepath: Path, total_pages: int) -> tuple[list[dict], list[Chunk]]:
        """分片并行解析：每片用独立 ParsedDocument 避免跨线程冲突"""
        import fitz

        batch_size = max(1, total_pages // self.max_workers)
        batches = []
        for start in range(0, total_pages, batch_size):
            end = min(start + batch_size, total_pages)
            batches.append((start, end))

        print(f"[parallel] {total_pages} pages → {len(batches)} batches ({batch_size} p/batch)")

        # 并行处理每个 batch
        all_cleaned = []
        all_chunks = []

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {
                executor.submit(_process_batch, str(filepath), start, end,
                               self.chunk_size, self.chunk_overlap): (start, end)
                for start, end in batches
            }
            for future in as_completed(futures):
                start, end = futures[future]
                try:
                    cleaned_pages, batch_chunks = future.result()
                    all_cleaned.extend(cleaned_pages)
                    all_chunks.extend(batch_chunks)
                    print(f"[parallel] Batch {start}-{end}: {len(cleaned_pages)} pages, {len(batch_chunks)} chunks")
                except Exception as e:
                    print(f"[parallel] Batch {start}-{end} FAILED: {e}")

        # 重新编号 chunk_index
        for i, ch in enumerate(all_chunks):
            ch.chunk_index = i

        return all_cleaned, all_chunks


def _process_batch(filepath: str, start: int, end: int,
                   chunk_size: int, chunk_overlap: int) -> tuple[list[dict], list[Chunk]]:
    """处理一个页面区间（在线程中执行）"""
    from ingestion import PDFParser
    from ingestion.chunker import HierarchicalChunker
    from cleaning import clean_pipeline

    parser = PDFParser()
    doc = parser.parse(filepath)
    # 只取指定范围的页面
    batch_pages = doc.pages[start:end]
    batch_clean = clean_pipeline(batch_pages)

    # 构造一个只包含 batch 页面的文档用于分块
    from dataclasses import replace
    chunker = HierarchicalChunker(chunk_size, chunk_overlap)
    # 用全文档分块（chunker 需要完整的 ParsedDocument 结构）
    chunks = chunker.chunk(doc)

    # 过滤出属于当前 batch 的 chunk
    batch_chunks = [c for c in chunks if start + 1 <= c.page <= end]

    return batch_clean, batch_chunks
