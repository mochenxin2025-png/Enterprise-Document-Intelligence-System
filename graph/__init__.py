"""Knowledge Graph Agent — 实体/关系提取 + SQLite 图存储 + Graph Patch

实体类型: Device / Protocol / Parameter / Standard / Interface / DiagramNode
关系类型: supports / connected_to / depends_on / configured_by / references / implements / derived_from

Phase 4: 规则驱动提取（后续可接 LLM 提取）
"""
import re
import sqlite3
import hashlib
import time
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Entity:
    id: str = ""               # SHA256-based stable ID
    name: str = ""
    entity_type: str = ""      # device / protocol / parameter / standard / interface / diagram_node
    doc_id: str = ""
    page: int = 0
    metadata: dict = field(default_factory=dict)
    status: str = "active"     # active / deprecated


@dataclass
class Relation:
    source_id: str
    target_id: str
    relation_type: str  # supports / connected_to / depends_on / configured_by / references / implements / derived_from
    doc_id: str = ""
    page: int = 0
    confidence: float = 0.8


class GraphStore:
    """SQLite 图存储 — 节点 + 边表"""

    def __init__(self, db_path: str = "./data/edis.db"):
        self.conn = sqlite3.connect(db_path)
        self._init_tables()

    def _init_tables(self):
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS graph_entities (
                id TEXT PRIMARY KEY,
                name TEXT,
                entity_type TEXT,
                doc_id TEXT,
                page INTEGER,
                metadata TEXT,
                status TEXT DEFAULT 'active',
                created_at REAL
            )
        """)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS graph_relations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_id TEXT,
                target_id TEXT,
                relation_type TEXT,
                doc_id TEXT,
                page INTEGER,
                confidence REAL DEFAULT 0.8,
                status TEXT DEFAULT 'active',
                created_at REAL,
                FOREIGN KEY (source_id) REFERENCES graph_entities(id),
                FOREIGN KEY (target_id) REFERENCES graph_entities(id)
            )
        """)
        self.conn.commit()

    def upsert_entity(self, entity: Entity):
        import json
        self.conn.execute(
            "INSERT OR REPLACE INTO graph_entities (id, name, entity_type, doc_id, page, metadata, status, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (entity.id, entity.name, entity.entity_type, entity.doc_id,
             entity.page, json.dumps(entity.metadata), entity.status, time.time()),
        )
        self.conn.commit()

    def add_relation(self, rel: Relation):
        # 防止重复边
        existing = self.conn.execute(
            "SELECT id FROM graph_relations WHERE source_id=? AND target_id=? AND relation_type=? AND status='active'",
            (rel.source_id, rel.target_id, rel.relation_type),
        ).fetchone()
        if existing:
            return
        self.conn.execute(
            "INSERT INTO graph_relations (source_id, target_id, relation_type, doc_id, page, confidence, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (rel.source_id, rel.target_id, rel.relation_type, rel.doc_id, rel.page, rel.confidence, time.time()),
        )
        self.conn.commit()

    def deprecate_entity(self, entity_id: str):
        """标记实体为废弃（Graph Patch 的一部分）"""
        self.conn.execute("UPDATE graph_entities SET status='deprecated' WHERE id=?", (entity_id,))
        self.conn.commit()

    def deprecate_relations(self, entity_id: str):
        """废弃与指定实体相关的所有关系"""
        self.conn.execute(
            "UPDATE graph_relations SET status='deprecated' WHERE (source_id=? OR target_id=?) AND status='active'",
            (entity_id, entity_id),
        )
        self.conn.commit()

    def query_neighbors(self, entity_id: str, relation_type: str | None = None) -> list[dict]:
        query = """
            SELECT r.relation_type, e.name, e.entity_type, e.id, r.confidence
            FROM graph_relations r
            JOIN graph_entities e ON (r.target_id = e.id)
            WHERE r.source_id = ? AND r.status = 'active' AND e.status = 'active'
        """
        params = [entity_id]
        if relation_type:
            query += " AND r.relation_type = ?"
            params.append(relation_type)
        rows = self.conn.execute(query, params).fetchall()
        return [{"relation": r[0], "entity": r[1], "type": r[2], "id": r[3], "confidence": r[4]} for r in rows]

    def find_entity(self, name: str, entity_type: str | None = None) -> Optional[Entity]:
        query = "SELECT id, name, entity_type, doc_id, page, metadata, status FROM graph_entities WHERE name = ? AND status = 'active'"
        params = [name]
        if entity_type:
            query += " AND entity_type = ?"
            params.append(entity_type)
        row = self.conn.execute(query, params).fetchone()
        if row:
            return Entity(id=row[0], name=row[1], entity_type=row[2], doc_id=row[3], page=row[4], status=row[6])
        return None

    def get_all_entities(self, entity_type: str | None = None) -> list[Entity]:
        query = "SELECT id, name, entity_type, doc_id, page, metadata, status FROM graph_entities WHERE status='active'"
        params = []
        if entity_type:
            query += " AND entity_type = ?"
            params.append(entity_type)
        rows = self.conn.execute(query, params).fetchall()
        return [Entity(id=r[0], name=r[1], entity_type=r[2], doc_id=r[3], page=r[4], status=r[6]) for r in rows]

    def close(self):
        self.conn.close()


# ── Entity Extractor ───────────────────────────

def _make_entity_id(name: str, entity_type: str) -> str:
    """SHA256 生成稳定实体 ID"""
    raw = f"{entity_type}:{name.lower()}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


class EntityExtractor:
    """从文本块中提取工程实体"""

    _DEVICE_PAT = re.compile(
        r'\b((?:Huawei|ZTE|Cisco|Nokia|Ericsson|Juniper|FiberHome|Alcatel)?\s*'
        r'(?:ONU|OLT|ONT|ODN|SFP|GPON|EPON|XG-PON|NG-PON2|MA\d+|ZX[A-Z]+\d+)[-A-Za-z0-9]*)\b',
        re.IGNORECASE
    )
    _PROTOCOL_PAT = re.compile(
        r'\b(GPON|EPON|XG-PON|XGS-PON|NG-PON2|10G-EPON|G\.984|G\.987|G\.988|G\.989|'
        r'IEEE\s+802\.3[a-z]*|ITU-T\s+G\.\d+\.?\d*|TCP/IP|Ethernet|MPLS|OSPF|BGP)\b',
        re.IGNORECASE
    )
    _STANDARD_PAT = re.compile(
        r'\b(ITU-T\s+G\.\d+\.?\d*|IEEE\s+\d+\.\d+[a-z]?|ISO\s+\d+|IEC\s+\d+|'
        r'GB/T?\s?\d+\.?\d*|ANSI\s+\w+\.\d+|ETSI\s+\w+\s+\d+)\b',
        re.IGNORECASE
    )
    _INTERFACE_PAT = re.compile(
        r'\b((?:SC|LC|FC|ST|MPO|RJ45|SFP\+?|QSFP\d*|XFP|CFP\d*|'
        r'GE|FE|10GE|25GE|40GE|100GE|400GE)\s*(?:port|interface|connector)?)\b',
        re.IGNORECASE
    )
    _RELATION_PATTERNS = [
        (r'(\w+(?:\s+\w+)?)\s+(?:connects?\s+to|is\s+connected\s+to|linked\s+to|attached\s+to)\s+(\w+(?:\s+\w+)?)',
         'connected_to'),
        (r'(\w+(?:\s+\w+)?)\s+(?:supports?|provides?|enables?)\s+(\w+(?:\s+\w+)?)',
         'supports'),
        (r'(\w+(?:\s+\w+)?)\s+(?:depends?\s+on|requires?|needs?)\s+(\w+(?:\s+\w+)?)',
         'depends_on'),
        (r'(\w+(?:\s+\w+)?)\s+(?:is\s+configured\s+by|configured\s+via|managed\s+by)\s+(\w+(?:\s+\w+)?)',
         'configured_by'),
        (r'(\w+(?:\s+\w+)?)\s+(?:references?|cites?|follows?|according\s+to)\s+(\w+(?:\s+\w+)?)',
         'references'),
    ]

    def extract(self, chunks: list, doc_id: str) -> tuple[list[Entity], list[Relation]]:
        entities = []
        relations = []
        seen = set()

        for chunk in chunks:
            text = chunk.text
            page = chunk.page

            # 提取设备
            for match in self._DEVICE_PAT.finditer(text):
                name = match.group(0).strip()
                eid = _make_entity_id(name, "device")
                if eid not in seen:
                    seen.add(eid)
                    entities.append(Entity(id=eid, name=name, entity_type="device",
                                          doc_id=doc_id, page=page))

            # 提取协议
            for match in self._PROTOCOL_PAT.finditer(text):
                name = match.group(0).strip()
                eid = _make_entity_id(name, "protocol")
                if eid not in seen:
                    seen.add(eid)
                    entities.append(Entity(id=eid, name=name, entity_type="protocol",
                                          doc_id=doc_id, page=page))

            # 提取标准
            for match in self._STANDARD_PAT.finditer(text):
                name = match.group(0).strip()
                eid = _make_entity_id(name, "standard")
                if eid not in seen:
                    seen.add(eid)
                    entities.append(Entity(id=eid, name=name, entity_type="standard",
                                          doc_id=doc_id, page=page))

            # 提取接口
            for match in self._INTERFACE_PAT.finditer(text):
                name = match.group(0).strip()
                eid = _make_entity_id(name, "interface")
                if eid not in seen:
                    seen.add(eid)
                    entities.append(Entity(id=eid, name=name, entity_type="interface",
                                          doc_id=doc_id, page=page))

            # 提取关系
            for pattern, rel_type in self._RELATION_PATTERNS:
                for match in re.finditer(pattern, text, re.IGNORECASE):
                    src_name = match.group(1).strip()
                    tgt_name = match.group(2).strip()
                    src_id = _make_entity_id(src_name, "device")
                    tgt_id = _make_entity_id(tgt_name, "device")
                    relations.append(Relation(
                        source_id=src_id, target_id=tgt_id,
                        relation_type=rel_type, doc_id=doc_id, page=page,
                    ))

        return entities, relations
