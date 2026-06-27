"""Entity Resolution Agent — 跨文档实体消歧与合并

策略:
  1. 名称归一化（大小写、空格、缩写展开）
  2. 上下文相似度（同一实体的周边文本相似）
  3. 类型一致性（同类型实体更可能是同一实体）
"""
import re
from dataclasses import dataclass
from graph import Entity, GraphStore, _make_entity_id


@dataclass
class EntityGroup:
    canonical_name: str
    entity_type: str
    entity_ids: list[str]  # 同一实体的多个 ID
    aliases: list[str]     # 发现的所有别名
    confidence: float


class EntityResolver:
    """跨文档实体消歧"""

    def __init__(self, store: GraphStore):
        self.store = store

    def resolve(self, new_entities: list[Entity]) -> dict[str, str]:
        """将新实体与已存在实体匹配，返回 {new_id → canonical_id} 映射"""
        existing = self.store.get_all_entities()
        mapping = {}

        for new_ent in new_entities:
            matched = self._find_match(new_ent, existing)
            if matched:
                mapping[new_ent.id] = matched.id
            else:
                mapping[new_ent.id] = new_ent.id  # 新实体，保留自己的 ID

        return mapping

    def _find_match(self, new_ent: Entity, existing: list[Entity]) -> Entity | None:
        """查找最佳匹配"""
        best_score = 0.0
        best_match = None

        for ex in existing:
            if ex.entity_type != new_ent.entity_type:
                continue  # 类型不同，不可能是同一实体

            score = self._similarity(new_ent.name, ex.name)
            if score > best_score and score >= 0.7:
                best_score = score
                best_match = ex

        return best_match

    def _similarity(self, a: str, b: str) -> float:
        """名称相似度（归一化后比较）"""
        a_norm = self._normalize(a)
        b_norm = self._normalize(b)

        if a_norm == b_norm:
            return 1.0

        # Token overlap
        tokens_a = set(a_norm.split())
        tokens_b = set(b_norm.split())
        if not tokens_a or not tokens_b:
            return 0.0

        intersection = tokens_a & tokens_b
        union = tokens_a | tokens_b
        token_score = len(intersection) / len(union) if union else 0.0

        # 子串匹配
        if a_norm in b_norm or b_norm in a_norm:
            token_score = max(token_score, 0.85)

        return token_score

    @staticmethod
    def _normalize(name: str) -> str:
        """归一化实体名"""
        name = name.lower().strip()
        # 去掉型号后缀（如 MA5800-X7 → MA5800）
        name = re.sub(r'[-_][a-z0-9]+$', '', name)
        # 去掉常见前缀
        for prefix in ["huawei", "zte", "cisco", "nokia", "ericsson"]:
            if name.startswith(prefix + " "):
                name = name[len(prefix) + 1:]
        return name


def merge_entities(store: GraphStore, mapping: dict[str, str]):
    """根据映射表合并实体：将所有关系指向 canonical ID"""
    for new_id, canonical_id in mapping.items():
        if new_id == canonical_id:
            continue
        # 将指向 new_id 的关系重定向到 canonical_id
        store.conn.execute(
            "UPDATE graph_relations SET source_id = ? WHERE source_id = ?",
            (canonical_id, new_id),
        )
        store.conn.execute(
            "UPDATE graph_relations SET target_id = ? WHERE target_id = ?",
            (canonical_id, new_id),
        )
        # 废弃重复实体
        store.deprecate_entity(new_id)
    store.conn.commit()
