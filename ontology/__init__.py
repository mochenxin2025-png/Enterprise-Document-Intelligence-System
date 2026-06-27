"""Ontology System — 参数别名自动发现 + 单位归一化

Phase 3: 基于 embedding 相似度 + 共现分析的别名发现
Human-in-the-Loop: 自动发现的候选别名需人工审核后入 Registry
"""
import re
import json
import sqlite3
from typing import Optional
from dataclasses import dataclass, field

import numpy as np


# ── Unit Normalization ─────────────────────────

# 单位换算表：所有单位统一转为基准单位
_UNIT_CONVERSIONS = {
    # 功率
    "dBm": {"base": "dBm", "scale": 1.0, "offset": 0.0},
    "mW":  {"base": "dBm", "fn": "mw_to_dbm"},
    "W":   {"base": "dBm", "fn": "w_to_dbm"},
    # 长度
    "nm":  {"base": "m", "scale": 1e-9},
    "km":  {"base": "m", "scale": 1e3},
    "m":   {"base": "m", "scale": 1.0},
    "mile": {"base": "m", "scale": 1609.344},
    "ft":  {"base": "m", "scale": 0.3048},
    # 频率
    "Hz":  {"base": "Hz", "scale": 1.0},
    "kHz": {"base": "Hz", "scale": 1e3},
    "MHz": {"base": "Hz", "scale": 1e6},
    "GHz": {"base": "Hz", "scale": 1e9},
    # 温度
    "°C": {"base": "°C", "scale": 1.0},
    "°F": {"base": "°C", "fn": "f_to_c"},
    "℃":  {"base": "°C", "scale": 1.0},
    # 电压
    "V":  {"base": "V", "scale": 1.0},
    "mV": {"base": "V", "scale": 1e-3},
    "kV": {"base": "V", "scale": 1e3},
    # 电流
    "A":  {"base": "A", "scale": 1.0},
    "mA": {"base": "A", "scale": 1e-3},
    # 衰减
    "dB": {"base": "dB", "scale": 1.0},
    # 电阻
    "Ω":  {"base": "Ω", "scale": 1.0},
    "Ohm":{"base": "Ω", "scale": 1.0},
}

_UNIT_ALIASES = {"ohm": "Ω", "ohms": "Ω", "°c": "°C", "°f": "°F", "celsius": "°C", "fahrenheit": "°F"}


def _mw_to_dbm(value: float) -> float:
    import math
    return 10 * math.log10(value) if value > 0 else float('-inf')


def _w_to_dbm(value: float) -> float:
    import math
    return 10 * math.log10(value * 1000) if value > 0 else float('-inf')


def _f_to_c(value: float) -> float:
    return (value - 32) * 5 / 9


class UnitNormalizer:
    """单位归一化：参数值 + 单位 → 基准单位值"""

    def normalize(self, value: float, unit: str) -> tuple[float, str]:
        unit_key = _UNIT_ALIASES.get(unit.lower().strip(), unit.strip())
        conv = _UNIT_CONVERSIONS.get(unit_key)
        if conv is None:
            return value, unit_key  # 未知单位，原样返回

        if "fn" in conv:
            fn_name = conv["fn"]
            fn_map = {"mw_to_dbm": _mw_to_dbm, "w_to_dbm": _w_to_dbm, "f_to_c": _f_to_c}
            fn = fn_map.get(fn_name)
            if fn:
                return fn(value), conv["base"]
        if "scale" in conv:
            return value * conv["scale"], conv["base"]

        return value, unit_key

    def convert(self, value: float, from_unit: str, to_unit: str) -> float:
        """从 from_unit 转换到 to_unit"""
        base_val, _ = self.normalize(value, from_unit)
        # 反向转换
        to_key = _UNIT_ALIASES.get(to_unit.lower().strip(), to_unit.strip())
        conv = _UNIT_CONVERSIONS.get(to_key, {})
        scale = conv.get("scale", 1.0)
        return base_val / scale if scale else base_val


# ── Alias Discovery ────────────────────────────

@dataclass
class AliasCandidate:
    canonical: str
    alias: str
    similarity: float
    context_overlap: float = 0.0
    source: str = ""
    status: str = "candidate"  # candidate | approved | rejected


class OntologyRegistry:
    """本体注册表 — SQLite 存储 Canonical Name + Aliases"""

    def __init__(self, db_path: str = "./data/edis.db"):
        self.conn = sqlite3.connect(db_path)
        self._init_tables()

    def _init_tables(self):
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS ontology_canonical (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                canonical_name TEXT UNIQUE,
                category TEXT,           -- device / protocol / parameter / standard
                base_unit TEXT,
                description TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS ontology_aliases (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                canonical_id INTEGER,
                alias TEXT,
                language TEXT DEFAULT 'en',  -- en / zh
                source TEXT,                 -- auto-discovered / manual
                status TEXT DEFAULT 'approved',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (canonical_id) REFERENCES ontology_canonical(id)
            )
        """)
        self.conn.commit()

    def register(self, canonical: str, category: str = "parameter",
                 base_unit: str = "", aliases: list[str] = None, description: str = ""):
        """注册一个新的 Canonical Name"""
        self.conn.execute(
            "INSERT OR IGNORE INTO ontology_canonical (canonical_name, category, base_unit, description) VALUES (?, ?, ?, ?)",
            (canonical, category, base_unit, description),
        )
        self.conn.commit()

        row = self.conn.execute(
            "SELECT id FROM ontology_canonical WHERE canonical_name = ?", (canonical,)
        ).fetchone()
        if row is None:
            return

        canonical_id = row[0]
        all_aliases = [canonical] + (aliases or [])
        for alias in set(all_aliases):
            self.conn.execute(
                "INSERT OR IGNORE INTO ontology_aliases (canonical_id, alias, source) VALUES (?, ?, 'manual')",
                (canonical_id, alias),
            )
        self.conn.commit()

    def lookup(self, term: str) -> Optional[str]:
        """查找术语的 Canonical Name"""
        row = self.conn.execute(
            """SELECT c.canonical_name FROM ontology_canonical c
               JOIN ontology_aliases a ON c.id = a.canonical_id
               WHERE LOWER(a.alias) = LOWER(?) AND a.status = 'approved'
            """, (term.strip(),)
        ).fetchone()
        return row[0] if row else None

    def list_all(self) -> list[dict]:
        rows = self.conn.execute(
            """SELECT c.canonical_name, c.category, c.base_unit,
                      GROUP_CONCAT(a.alias, '||') as aliases
               FROM ontology_canonical c
               LEFT JOIN ontology_aliases a ON c.id = a.canonical_id AND a.status='approved'
               GROUP BY c.id
            """
        ).fetchall()
        return [
            {"canonical": r[0], "category": r[1], "base_unit": r[2],
             "aliases": r[3].split("||") if r[3] else []}
            for r in rows
        ]

    def close(self):
        self.conn.close()


class AliasDiscoverer:
    """参数别名自动发现 — embedding 相似度 + 上下文共现"""

    def __init__(self, registry: OntologyRegistry, embedder=None):
        self.registry = registry
        self.embedder = embedder  # lazy import to avoid circular

    def discover_from_chunks(self, chunks_text: list[str]) -> list[AliasCandidate]:
        """从文本块中自动发现参数别名候选"""
        # 提取疑似参数名
        params = self._extract_parameters(chunks_text)
        candidates = []

        if self.embedder and len(params) >= 2:
            # Embedding 相似度分组
            embeddings = self.embedder.encode(params)
            for i in range(len(params)):
                for j in range(i + 1, len(params)):
                    sim = self._cosine_sim(embeddings[i], embeddings[j])
                    if sim > 0.75:
                        candidates.append(AliasCandidate(
                            canonical=params[i], alias=params[j],
                            similarity=round(sim, 3),
                            source="embedding_similarity"
                        ))

        # Context co-occurrence: same page, similar surrounding text
        co_occur = self._find_co_occurring(params, chunks_text)
        candidates.extend(co_occur)

        return candidates

    def _extract_parameters(self, texts: list[str]) -> list[str]:
        """提取疑似工程参数名"""
        param_pattern = re.compile(
            r'\b((?:rx|tx|receiver|transmitter|input|output|max|min|typical|nominal|peak)\s+)?'
            r'(sensitivity|power|wavelength|ratio|frequency|bandwidth|voltage|current|'
            r'temperature|loss|gain|attenuation|impedance|resistance|capacitance|'
            r'extinction\s+ratio|overload|saturation)\b',
            re.IGNORECASE
        )
        found = set()
        for text in texts:
            for match in param_pattern.finditer(text):
                param = match.group(0).strip()
                if param:
                    found.add(param.lower())
        return sorted(found)

    def _cosine_sim(self, a, b) -> float:
        a = np.array(a)
        b = np.array(b)
        return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))

    def _find_co_occurring(self, params: list[str], texts: list[str]) -> list[AliasCandidate]:
        """同一 chunk 内共同出现的参数 → 可能相关"""
        candidates = []
        for text in texts:
            text_lower = text.lower()
            present = [p for p in params if p in text_lower]
            if len(present) >= 2:
                for i in range(len(present)):
                    for j in range(i + 1, len(present)):
                        # 可能是别名对（如 "rx sensitivity" 和 "receiver sensitivity"）
                        if self._is_likely_alias(present[i], present[j]):
                            candidates.append(AliasCandidate(
                                canonical=present[i], alias=present[j],
                                similarity=0.6, context_overlap=0.8,
                                source="co_occurrence"
                            ))
        return candidates

    def _is_likely_alias(self, a: str, b: str) -> bool:
        """启发式：判断两个参数名是否可能是别名"""
        words_a = set(a.split())
        words_b = set(b.split())
        if not words_a or not words_b:
            return False
        overlap = len(words_a & words_b) / len(words_a | words_b)
        return overlap >= 0.5  # 两种写法共享一半以上的词


def seed_engineering_ontology(registry: OntologyRegistry):
    """预置常见工程参数本体"""
    presets = [
        ("receiver_sensitivity", "parameter", "dBm",
         ["rx sensitivity", "rx_sensitivity", "rx sens", "receiver sensitivity", "接收灵敏度"]),
        ("transmitter_power", "parameter", "dBm",
         ["tx power", "tx_power", "transmitter power", "output power", "发射功率"]),
        ("wavelength", "parameter", "nm",
         ["rx wavelength", "tx wavelength", "operating wavelength", "波长"]),
        ("extinction_ratio", "parameter", "dB",
         ["tx extinction ratio", "er", "消光比"]),
        ("optical_network_unit", "device", "",
         ["onu", "optical network unit", "光网络单元"]),
        ("optical_line_terminal", "device", "",
         ["olt", "optical line terminal", "光线路终端"]),
        ("gpon", "protocol", "",
         ["gigabit passive optical network", "g.984", "吉比特无源光网络"]),
        ("epon", "protocol", "",
         ["ethernet passive optical network", "以太网无源光网络"]),
    ]
    for canonical, cat, unit, aliases in presets:
        registry.register(canonical, cat, unit, aliases)
