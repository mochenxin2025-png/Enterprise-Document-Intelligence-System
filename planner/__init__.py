"""Query Planner — 意图分类 + 检索路径亲和度估算

Phase 2: 规则驱动（特征工程 + 关键词匹配）
Phase 5: 升级为 LightGBM / ML 模型
"""
import re
from dataclasses import dataclass, field
from enum import Enum


class Intent(str, Enum):
    PARAMETER = "parameter_query"
    DEFINITION = "definition_query"
    RELATIONSHIP = "relationship_query"
    DIAGRAM = "diagram_query"
    COMPLIANCE = "compliance_query"
    MULTI_HOP = "multi_hop_query"


# ── Intent Classification ──────────────────────

# 关键词/模式 → Intent 映射
_PATTERNS = {
    Intent.PARAMETER: [
        r'(what|how much|value of|specify|specification)\s+.*(is|of)\s+.*(the\s+)?(\w+\s+)?(sensitivity|power|wavelength|ratio|bandwidth|frequency|voltage|current|temperature|loss|gain|attenuation)',
        r'(?:\w+\s+)?(sensitivity|power|wavelength|ratio|bandwidth|frequency|voltage|current|temperature|loss|gain|attenuation)\s+(is|of|value|parameter|spec)',
        r'parameter.*(value|spec|rating)',
        r'(\d+\.?\d*)\s*(dBm|mW|W|nm|km|m|s|Hz|V|A|dB)',
        r'(maximum|minimum|typical|nominal|rated)\s+\w+',
    ],
    Intent.RELATIONSHIP: [
        r'(how|what).*(connect|relate|relationship|interface|between|link|attach|communicate)',
        r'(what|which).*(protocol|standard|interface|topology)',
        r'(how does|how do).*(work|function|operate|communicate|connect)',
        r'(relationship|connection|topology).*(between|of|among)',
        r'(upstream|downstream|peer|master|slave|client|server)',
    ],
    Intent.DEFINITION: [
        r'(what is|define|explain|meaning of|describe)\s+(a |an |the )?\w+',
        r'^(what|who)\s+(is|are)\s+',
        r'(overview|introduction|background|concept)\s+of',
    ],
    Intent.COMPLIANCE: [
        r'(comply|compliance|conform|standard|regulation|spec|requirement|mandate)',
        r'(must|shall|should|required|mandatory|obligatory)',
        r'(ITU|IEEE|ISO|IEC|GB|ANSI|ETSI)\s',
        r'(according to|per|as per|following)\s+(standard|spec)',
    ],
    Intent.MULTI_HOP: [
        r'(compare|difference|versus|vs\.?|better|worse|advantage|disadvantage)',
        r'(why|how come|reason|explain why)',
        r'(what if|scenario|case|condition|assume)',
        r'(calculate|compute|determine|estimate|derive)',
        r'how.*(affect|impact|influence|change|vary)',
    ],
    Intent.DIAGRAM: [
        r'(diagram|figure|chart|graph|drawing|illustration|schematic|picture|image)',
        r'(show|display|plot|visualize|depict)',
        r'(topology|layout|architecture)\s+(diagram|map|view)',
    ],
}


class IntentClassifier:
    """规则驱动的意图分类器。返回每个 Intent 的置信度。"""

    def classify(self, question: str) -> dict[str, float]:
        question_lower = question.lower()
        scores: dict[str, float] = {}

        for intent, patterns in _PATTERNS.items():
            score = 0.0
            for pat in patterns:
                try:
                    if re.search(pat, question_lower):
                        score += 1.0
                except re.error:
                    continue
            # 归一化：最多匹配几个模式
            if score > 0:
                scores[intent.value] = min(score / len(patterns) * 2, 1.0)

        # 特征工程增强
        features = _extract_features(question)
        scores = self._adjust_by_features(scores, features)

        # 兜底：如果没匹配到任何意图，默认 DEFINITION + SEMANTIC
        if not scores:
            scores[Intent.DEFINITION.value] = 0.6
            scores[Intent.PARAMETER.value] = 0.2

        return dict(sorted(scores.items(), key=lambda x: -x[1]))


    def _adjust_by_features(self, scores: dict, features: dict) -> dict:
        """特征工程微调"""
        # 含数字 + 单位 → 提高 parameter 权重
        if features.get("contains_numeric_unit"):
            scores[Intent.PARAMETER.value] = scores.get(Intent.PARAMETER.value, 0) + 0.15

        # 含关系词
        if features.get("contains_relation_word"):
            scores[Intent.RELATIONSHIP.value] = scores.get(Intent.RELATIONSHIP.value, 0) + 0.1

        # 实体数量多 → 可能 multi-hop
        if features.get("entity_count", 0) >= 3:
            scores[Intent.MULTI_HOP.value] = scores.get(Intent.MULTI_HOP.value, 0) + 0.1

        # 裁剪到 [0, 1]
        return {k: min(v, 1.0) for k, v in scores.items()}


# ── Feature Extraction ─────────────────────────

def _extract_features(question: str) -> dict:
    """从问题中提取特征"""
    features = {}

    # 数字+单位
    features["contains_numeric_unit"] = bool(re.search(
        r'\d+\.?\d*\s*(dBm|mW|W|nm|km|m|s|Hz|V|A|dB|°|℃|℉|%|Ω)', question
    ))

    # 关系词
    features["contains_relation_word"] = bool(re.search(
        r'\b(between|connect|interface|link|attach|relate|couple|topology|network|upstream|downstream)\b',
        question, re.IGNORECASE
    ))

    # 实体词数量（大写缩写 + 专业术语）
    entities = re.findall(r'\b[A-Z]{2,}(?:-[A-Z0-9]+)?\b', question)
    features["entity_count"] = len(entities)

    # 参数关键词
    features["contains_parameter_keyword"] = bool(re.search(
        r'\b(sensitivity|power|wavelength|ratio|frequency|voltage|current|bandwidth|attenuation|loss|gain|temperature|impedance|resistance|capacitance)\b',
        question, re.IGNORECASE
    ))

    return features


# ── Retrieval Affinity ─────────────────────────

@dataclass
class RetrievalPlan:
    """检索计划"""
    paths: dict[str, float]     # path_name → affinity_score (0-100)
    primary_intent: str


def plan_retrieval(question: str, classifier: IntentClassifier | None = None) -> RetrievalPlan:
    """根据意图分类生成检索亲和度。

    映射 Intent → 检索路径:
      PARAMETER    → structured (table) + semantic
      DEFINITION   → semantic + metadata
      RELATIONSHIP → graph + semantic
      DIAGRAM      → diagram
      COMPLIANCE   → metadata + semantic + cross_document
      MULTI_HOP    → graph + semantic + cross_document + structured
    """
    if classifier is None:
        classifier = IntentClassifier()

    intents = classifier.classify(question)

    # 意图 → 路径亲和度映射
    intent_to_paths = {
        Intent.PARAMETER.value:     {"structured": 90, "semantic": 60, "metadata": 20},
        Intent.DEFINITION.value:    {"semantic": 90, "metadata": 40},
        Intent.RELATIONSHIP.value:  {"semantic": 70, "graph": 80, "metadata": 30},
        Intent.DIAGRAM.value:       {"diagram": 90, "semantic": 30},
        Intent.COMPLIANCE.value:    {"metadata": 80, "semantic": 50, "cross_document": 60},
        Intent.MULTI_HOP.value:     {"semantic": 80, "graph": 70, "cross_document": 50, "structured": 40},
    }

    # 累加亲和度：各 intent 得分 × 该 intent 对各路径的亲和度
    affinity: dict[str, float] = {}
    for intent, score in intents.items():
        paths = intent_to_paths.get(intent, {})
        for path, base in paths.items():
            affinity[path] = affinity.get(path, 0) + score * base

    # 归一化到 0-100
    if affinity:
        max_val = max(affinity.values())
        affinity = {k: round(v / max_val * 100) for k, v in affinity.items()}

    primary = max(intents, key=intents.get) if intents else Intent.DEFINITION.value
    return RetrievalPlan(paths=affinity, primary_intent=primary)
