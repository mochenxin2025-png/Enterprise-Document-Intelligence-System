"""Metadata System — 结构化文档元数据层

元数据不进入 Embedding，用于 Filter / Permission / Ranking / Lifecycle / Version。

标准字段:
  - 基础: filename, file_type, file_size, checksum, upload_time
  - 文档: author, title, language, page_count, document_date
  - 质量: ocr_quality, parsing_quality, parsing_confidence
  - 版本: embedding_version, parser_version, index_version
  - 组织: department, owner, tags, confidentiality
  - 来源: source_path, source_type (upload/reference/api)
"""
import hashlib
import time
import os
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Optional


@dataclass
class DocumentMetadata:
    """标准文档元数据"""

    # 基础
    filename: str = ""
    file_type: str = ""
    file_size: int = 0
    checksum: str = ""
    upload_time: float = 0.0
    update_time: float = 0.0

    # 文档
    author: str = ""
    title: str = ""
    language: str = ""
    page_count: int = 0
    document_date: str = ""

    # 质量
    ocr_quality: float = 0.0       # 0-1
    parsing_quality: float = 0.0   # 0-1
    parsing_confidence: float = 0.0

    # 版本
    embedding_version: str = ""
    embedding_model: str = ""
    parser_version: str = "1.0"
    index_version: str = "1.0"

    # 组织
    department: str = ""
    owner: str = ""
    tags: list[str] = field(default_factory=list)
    confidentiality: str = "internal"  # public / internal / confidential / restricted

    # 来源
    source_path: str = ""
    source_type: str = "upload"

    # 分类
    category: str = "unknown"
    category_confidence: float = 0.0

    # 自定义扩展
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

    def to_db_json(self) -> str:
        import json
        return json.dumps(self.to_dict(), ensure_ascii=False)


class MetadataExtractor:
    """从文件和解析结果中提取元数据"""

    @classmethod
    def from_file(cls, filepath: str) -> DocumentMetadata:
        path = Path(filepath)
        meta = DocumentMetadata(
            filename=path.name,
            file_type=path.suffix.lower(),
            file_size=path.stat().st_size if path.exists() else 0,
            checksum=cls._checksum(filepath),
            upload_time=time.time(),
            source_path=str(path.resolve()),
            source_type="upload",
        )
        # 语言检测
        meta.language = cls._detect_language(filepath)
        return meta

    @classmethod
    def from_pdf_meta(cls, filepath: str, pdf_meta: dict) -> DocumentMetadata:
        meta = cls.from_file(filepath)
        meta.title = pdf_meta.get("title", "") or Path(filepath).stem
        meta.author = pdf_meta.get("author", "")
        if pdf_meta.get("creationDate"):
            meta.document_date = str(pdf_meta["creationDate"])[:10]
        return meta

    @classmethod
    def enrich(cls, meta: DocumentMetadata, doc) -> DocumentMetadata:
        """用解析结果丰富元数据"""
        meta.page_count = doc.page_count
        return meta

    @staticmethod
    def _checksum(filepath: str) -> str:
        try:
            with open(filepath, "rb") as f:
                return hashlib.sha256(f.read(65536)).hexdigest()[:16]
        except Exception:
            return ""

    @staticmethod
    def _detect_language(filepath: str) -> str:
        try:
            import chardet
            with open(filepath, "rb") as f:
                raw = f.read(10000)
            result = chardet.detect(raw)
            return result.get("language", "") or result.get("encoding", "")
        except Exception:
            return ""


# SQLite 存储扩展
METADATA_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS document_metadata (
    doc_id TEXT PRIMARY KEY,
    metadata_json TEXT,
    created_at REAL,
    updated_at REAL
)
"""
