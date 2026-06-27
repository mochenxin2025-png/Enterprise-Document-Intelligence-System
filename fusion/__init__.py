"""Evidence Fusion Layer — 多源结果去重 + 冲突检测 + 跨源排序"""
import re
from dataclasses import dataclass, field
from typing import Union
from retrieval import SearchResult


@dataclass
class FusedEvidence:
    """融合后的证据"""
    text: str
    score: float
    page: int
    chapter: str = ""
    section: str = ""
    source: str = ""
    path: str = ""              # 来源检索路径
    conflicts: list[str] = field(default_factory=list)


# ── Deduplication ─────────────────────────────

def deduplicate(results: list[SearchResult], threshold: float = 0.9) -> list[SearchResult]:
    """基于文本重叠率去重。超过 threshold 相似度的结果只保留最高分。"""
    if len(results) <= 1:
        return results

    kept = []
    for i, r in enumerate(results):
        is_dup = False
        for existing in kept:
            overlap = _jaccard_similarity(r.text, existing.text)
            if overlap >= threshold:
                is_dup = True
                # 保留分数更高的来源
                if r.score > existing.score:
                    kept.remove(existing)
                    kept.append(r)
                break
        if not is_dup:
            kept.append(r)
    return kept


def _jaccard_similarity(a: str, b: str) -> float:
    """Jaccard 相似度（基于 trigram）"""
    def trigrams(s):
        return set(s[i:i+3] for i in range(len(s) - 2))

    set_a = trigrams(a.lower())
    set_b = trigrams(b.lower())
    if not set_a or not set_b:
        return 0.0
    return len(set_a & set_b) / len(set_a | set_b)


# ── Conflict Detection ─────────────────────────

@dataclass
class Conflict:
    """检测到的冲突"""
    param: str
    values: list[tuple[float, str, str]]  # [(value, unit, source)]
    confidence: float


def detect_conflicts(results: list[SearchResult]) -> list[Conflict]:
    """检测同一参数在不同来源中的数值冲突。

    识别模式: "Parameter ... Value Unit" (如 "Rx Sensitivity -28 dBm")
    如果同一参数出现两个不同数值 → 标记为冲突。
    """
    param_pattern = re.compile(
        r'(rx|tx|receiver|transmitter|input|output|max|min|typical|nominal|peak)?\s*'
        r'(sensitivity|power|wavelength|ratio|frequency|bandwidth|voltage|current|temperature|loss|gain|attenuation|impedance)'
        r'.*?([+-]?\d+\.?\d*)\s*(dBm|mW|W|nm|km|m|s|Hz|V|A|dB|°C|°F|%)?',
        re.IGNORECASE
    )

    found: dict[str, list[tuple[float, str, SearchResult]]] = {}
    for r in results:
        for match in param_pattern.finditer(r.text):
            prefix = (match.group(1) or "").lower().strip()
            param = (match.group(2) or "").lower().strip()
            value = float(match.group(3))
            unit = (match.group(4) or "").lower().strip()

            key = f"{prefix} {param}".strip() if prefix else param
            if key not in found:
                found[key] = []
            found[key].append((value, unit, r))

    conflicts = []
    for param, entries in found.items():
        unique_values = set((v, u) for v, u, _ in entries)
        if len(unique_values) > 1:
            conflict = Conflict(
                param=param,
                values=[(v, u, r.source) for v, u, r in entries],
                confidence=0.6 + min(0.3, len(entries) * 0.1),
            )
            conflicts.append(conflict)

    return conflicts


# ── Cross-Source Ranking ───────────────────────

def rank_results(results: list[SearchResult], path_info: dict[str, float] | None = None) -> list[FusedEvidence]:
    """跨源排序：组合语义分数 + 来源多样性 + 路径权重"""
    if not results:
        return []

    # 1. 去重
    deduped = deduplicate(results)

    # 2. 构建 FusedEvidence
    fused = []
    for r in deduped:
        # 从 source 推断路径（简化：根据来源名判断）
        path = _infer_path(r.text)
        fused.append(FusedEvidence(
            text=r.text, score=r.score, page=r.page,
            chapter=r.chapter, section=r.section, source=r.source, path=path,
        ))

    # 3. 重排序：相关性 + 来源多样性
    # 对同一 source+page 的结果进行降权（避免同页垄断）
    source_counts: dict[tuple[str, int], int] = {}
    for fe in fused:
        key = (fe.source, fe.page)
        source_counts[key] = source_counts.get(key, 0) + 1

    for fe in fused:
        key = (fe.source, fe.page)
        # 同源同页超过2条 → 降权
        if source_counts[key] > 2:
            fe.score *= 0.8

    # 按最终分数排序
    fused.sort(key=lambda x: x.score, reverse=True)
    return fused


def _infer_path(text: str) -> str:
    """从文本特征推断检索路径"""
    lower = text.lower()
    if re.search(r'(parameter|value|unit|dbm|nm|mhz|ghz|spec|rating)', lower):
        return "structured"
    elif re.search(r'(protocol|connect|interface|topology|between|relationship)', lower):
        return "graph"
    elif re.search(r'(standard|compliance|spec|itu|ieee|regulation)', lower):
        return "metadata"
    return "semantic"
