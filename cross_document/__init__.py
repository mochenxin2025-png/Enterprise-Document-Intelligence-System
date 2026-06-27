"""Cross-Document Layer — 跨文档去重 + 冲突解决 + 引用追踪

Document Registry: 记录所有导入文档的版本、来源、时间戳
Conflict Resolver: 同一参数跨文档出现不同值时，按策略裁决
Reference Tracker: 文档间的引用关系
"""
import hashlib
import json
import sqlite3
import time
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class DocumentRecord:
    doc_id: str
    filename: str
    path: str
    version: str = "1.0"
    source_type: str = "upload"  # upload / reference / derived
    page_count: int = 0
    checksum: str = ""
    imported_at: float = 0.0


@dataclass
class ParameterConflict:
    param_name: str
    values: list[tuple[float, str, str, str]]  # (value, unit, doc_id, page)
    resolution: str = "unresolved"
    resolved_value: Optional[tuple[float, str]] = None


class DocumentRegistry:
    """文档注册表 — 版本管理 + 去重"""

    def __init__(self, db_path: str = "./data/edis.db"):
        self.conn = sqlite3.connect(db_path)
        self._init_tables()

    def _init_tables(self):
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS document_registry (
                doc_id TEXT PRIMARY KEY,
                filename TEXT,
                path TEXT,
                version TEXT DEFAULT '1.0',
                source_type TEXT DEFAULT 'upload',
                page_count INTEGER DEFAULT 0,
                checksum TEXT,
                metadata TEXT,
                imported_at REAL,
                updated_at REAL
            )
        """)
        # 跨文档引用关系
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS document_references (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_doc_id TEXT,
                target_doc_id TEXT,
                reference_type TEXT,   -- cites / replaces / derived_from / conflicts_with
                description TEXT,
                created_at REAL,
                FOREIGN KEY (source_doc_id) REFERENCES document_registry(doc_id),
                FOREIGN KEY (target_doc_id) REFERENCES document_registry(doc_id)
            )
        """)
        self.conn.commit()

    def register(self, doc_id: str, filename: str, path: str,
                 version: str = "1.0", page_count: int = 0,
                 checksum: str = "", metadata: dict = None) -> bool:
        """注册文档。如果已存在且 checksum 相同，跳过。"""
        existing = self.conn.execute(
            "SELECT checksum FROM document_registry WHERE doc_id = ?", (doc_id,)
        ).fetchone()

        now = time.time()
        if existing:
            if existing[0] == checksum:
                return False  # 相同文档，跳过
            # 版本更新
            self.conn.execute(
                "UPDATE document_registry SET checksum=?, page_count=?, metadata=?, updated_at=? WHERE doc_id=?",
                (checksum, page_count, json.dumps(metadata or {}), now, doc_id),
            )
        else:
            self.conn.execute(
                "INSERT INTO document_registry (doc_id, filename, path, version, source_type, page_count, checksum, metadata, imported_at) "
                "VALUES (?, ?, ?, ?, 'upload', ?, ?, ?, ?)",
                (doc_id, filename, path, version, page_count, checksum, json.dumps(metadata or {}), now),
            )
        self.conn.commit()
        return True

    def get(self, doc_id: str) -> Optional[DocumentRecord]:
        row = self.conn.execute(
            "SELECT doc_id, filename, path, version, source_type, page_count, checksum, imported_at "
            "FROM document_registry WHERE doc_id = ?", (doc_id,)
        ).fetchone()
        if row:
            return DocumentRecord(
                doc_id=row[0], filename=row[1], path=row[2], version=row[3],
                source_type=row[4], page_count=row[5], checksum=row[6], imported_at=row[7],
            )
        return None

    def list_all(self) -> list[DocumentRecord]:
        rows = self.conn.execute(
            "SELECT doc_id, filename, path, version, source_type, page_count, checksum, imported_at "
            "FROM document_registry ORDER BY imported_at DESC"
        ).fetchall()
        return [
            DocumentRecord(doc_id=r[0], filename=r[1], path=r[2], version=r[3],
                          source_type=r[4], page_count=r[5], checksum=r[6], imported_at=r[7])
            for r in rows
        ]

    def add_reference(self, source_id: str, target_id: str,
                      ref_type: str = "cites", description: str = ""):
        self.conn.execute(
            "INSERT INTO document_references (source_doc_id, target_doc_id, reference_type, description, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (source_id, target_id, ref_type, description, time.time()),
        )
        self.conn.commit()

    def find_duplicates(self, checksum: str) -> list[str]:
        """查找相同 checksum 的文档（跨版本重复）"""
        rows = self.conn.execute(
            "SELECT doc_id FROM document_registry WHERE checksum = ?", (checksum,)
        ).fetchall()
        return [r[0] for r in rows]

    def close(self):
        self.conn.close()


class ConflictResolver:
    """跨文档参数冲突解决

    策略:
      latest_first    — 取最新文档的值
      source_priority — 按来源优先级
      majority_vote   — 取多数值
    """

    def __init__(self, registry: DocumentRegistry, strategy: str = "latest_first"):
        self.registry = registry
        self.strategy = strategy

    def resolve(self, conflicts: list[ParameterConflict]) -> list[ParameterConflict]:
        """解决冲突"""
        for conflict in conflicts:
            if self.strategy == "latest_first":
                conflict = self._resolve_by_latest(conflict)
            elif self.strategy == "majority_vote":
                conflict = self._resolve_by_majority(conflict)
            # source_priority: 保持 unresolved，等待人工裁决
        return conflicts

    def _resolve_by_latest(self, conflict: ParameterConflict) -> ParameterConflict:
        """取最新文档的值"""
        latest_time = 0
        latest_value = None
        for value, unit, doc_id, page in conflict.values:
            doc = self.registry.get(doc_id)
            if doc and doc.imported_at > latest_time:
                latest_time = doc.imported_at
                latest_value = (value, unit)

        if latest_value:
            conflict.resolution = "resolved_latest"
            conflict.resolved_value = latest_value
        return conflict

    def _resolve_by_majority(self, conflict: ParameterConflict) -> ParameterConflict:
        """取多数值"""
        from collections import Counter
        value_counts = Counter((v, u) for v, u, d, p in conflict.values)
        most_common = value_counts.most_common(1)
        if most_common:
            (val, unit), count = most_common[0]
            if count >= len(conflict.values) / 2:
                conflict.resolution = "resolved_majority"
                conflict.resolved_value = (val, unit)
        return conflict


class ReferenceTracker:
    """文档间引用关系追踪"""

    def __init__(self, registry: DocumentRegistry):
        self.registry = registry

    def track_citation(self, source_doc: str, cited_text: str) -> list[str]:
        """从引用文本中提取可能的目标文档"""
        # 检测标准引用：ITU-T G.984, IEEE 802.3, ISO 11801 等
        import re
        std_pattern = re.compile(
            r'\b(ITU-T?\s+[A-Z]\.\d+\.?\d*|IEEE\s+\d+\.\d+[a-z]?|'
            r'ISO\s+\d+|IEC\s+\d+|GB/T?\s+\d+|ANSI\s+\w+\.\d+)',
            re.IGNORECASE
        )
        matches = std_pattern.findall(cited_text)
        return matches

    def link_documents(self, source_id: str, target_id: str, reason: str = ""):
        self.registry.add_reference(source_id, target_id, "related", reason)

    def get_references(self, doc_id: str) -> list[dict]:
        """获取文档的所有引用关系"""
        rows = self.registry.conn.execute(
            """SELECT r.reference_type, r.description, d.filename, d.doc_id
               FROM document_references r
               JOIN document_registry d ON r.target_doc_id = d.doc_id
               WHERE r.source_doc_id = ?
            """, (doc_id,)
        ).fetchall()
        return [{"type": r[0], "description": r[1], "target_file": r[2], "target_id": r[3]} for r in rows]
