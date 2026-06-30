"""Reranker Adapters — 实现 RerankerInterface

两种实现:
  - HeuristicReranker: 关键词重叠 + 多样性 + 位置加权（零成本，默认）
  - LLMReranker: 用 LLM 精排（高质量，有 token 成本）

设计:
  - 实现 interfaces.RerankerInterface
  - 可替换 — QAEngine 依赖接口而非具体实现
"""

import re
from typing import Optional
from interfaces import RerankerInterface


class HeuristicReranker(RerankerInterface):
    """启发式精排 — 关键词重叠 + 多样性 + 位置加权

    零外部依赖，零 API 成本。
    """

    def __init__(self, keyword_weight: float = 0.4,
                 position_weight: float = 0.2,
                 diversity_weight: float = 0.2,
                 vector_weight: float = 0.2):
        self.kw_w = keyword_weight
        self.pos_w = position_weight
        self.div_w = diversity_weight
        self.vec_w = vector_weight

    def rerank(self, query: str, candidates: list[str],
               vector_scores: list[float] = None,
               pages: list[int] = None) -> list[int]:
        """返回按综合得分降序排列的索引。

        candidates: chunk 文本列表
        vector_scores: 原始向量检索得分（可选）
        pages: 每个 chunk 的页码（用于位置加权）
        """
        n = len(candidates)
        if n <= 1:
            return list(range(n))

        # 1. 关键词重叠得分（query 词在 chunk 中的覆盖度）
        query_tokens = self._tokenize(query)
        keyword_scores = []
        for text in candidates:
            text_lower = text.lower()
            hits = sum(1 for t in query_tokens if t in text_lower)
            keyword_scores.append(hits / max(len(query_tokens), 1))

        # 2. 位置得分（靠前的页码权重大 — 工程文档前几页通常更重要）
        position_scores = []
        if pages:
            max_page = max(pages) if pages else 1
            for p in pages:
                position_scores.append(1.0 - (p / (max_page + 1)) * 0.5)
        else:
            position_scores = [0.5] * n

        # 3. 向量得分归一化
        if vector_scores:
            max_vs = max(vector_scores) if vector_scores else 1.0
            norm_vs = [s / max(max_vs, 0.001) for s in vector_scores]
        else:
            norm_vs = [0.5] * n

        # 4. 多样性惩罚（相似文本降权）
        diversity_penalty = self._diversity_penalty(candidates)

        # 综合得分
        scores = []
        for i in range(n):
            s = (
                self.kw_w * keyword_scores[i] +
                self.pos_w * position_scores[i] +
                self.div_w * diversity_penalty[i] +
                self.vec_w * norm_vs[i]
            )
            scores.append((i, s))

        # 按得分降序
        scores.sort(key=lambda x: x[1], reverse=True)
        return [idx for idx, _ in scores]

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        """中英文混合分词"""
        tokens = []
        # 中文单字
        for ch in text:
            if '\u4e00' <= ch <= '\u9fff':
                tokens.append(ch)
        # 英文词
        for w in re.findall(r'[a-zA-Z0-9]+', text.lower()):
            if len(w) >= 2:
                tokens.append(w)
        return tokens

    @staticmethod
    def _diversity_penalty(candidates: list[str]) -> list[float]:
        """Jaccard 去重：与前面已选文本越相似，得分越低"""
        n = len(candidates)
        if n <= 1:
            return [1.0] * n

        penalties = [1.0] * n
        for i in range(1, n):
            max_sim = 0.0
            for j in range(i):
                sim = HeuristicReranker._jaccard(candidates[i], candidates[j])
                max_sim = max(max_sim, sim)
            penalties[i] = 1.0 - max_sim * 0.5  # 最多降权 50%
        return penalties

    @staticmethod
    def _jaccard(a: str, b: str) -> float:
        def trigrams(s):
            return set(s[i:i+3] for i in range(len(s) - 2))
        sa, sb = trigrams(a.lower()), trigrams(b.lower())
        if not sa or not sb:
            return 0.0
        return len(sa & sb) / len(sa | sb)


class LLMReranker(RerankerInterface):
    """LLM 精排 — 用 DeepSeek 对候选 chunk 打分

    适合需要语义理解的场景。有 token 成本。
    """

    def __init__(self, llm=None, max_chunks: int = 20):
        """
        llm: LLMInterface 实例（默认 DeepSeekAdapter）
        max_chunks: 最多送多少个 chunk 给 LLM
        """
        self.max_chunks = max_chunks
        if llm is None:
            from adapters import DeepSeekAdapter
            self.llm = DeepSeekAdapter()
        else:
            self.llm = llm

    def rerank(self, query: str, candidates: list[str],
               vector_scores: list[float] = None,
               pages: list[int] = None) -> list[int]:
        """LLM 精排 — 让模型选出最相关的 chunk"""
        n = len(candidates)
        if n <= 1:
            return list(range(n))

        # 限制数量
        if n > self.max_chunks:
            n = self.max_chunks
            candidates = candidates[:n]

        # 构建 prompt
        chunks_text = ""
        for i, text in enumerate(candidates):
            preview = text[:300].replace("\n", " ")
            chunks_text += f"[{i}] {preview}\n"

        prompt = (
            "你是一个检索质量评估器。给定用户问题和候选文档片段，"
            "请选出最相关的 5 个片段，按相关性从高到低排列。\n\n"
            f"问题: {query}\n\n"
            f"候选片段:\n{chunks_text}\n"
            "请只输出数字索引，用逗号分隔，例如: 3,0,7,1,5"
        )

        try:
            resp = self.llm.chat([
                {"role": "user", "content": prompt},
            ], max_tokens=50, temperature=0)
            # 解析返回的索引
            indices = []
            for part in resp.content.split(","):
                part = part.strip()
                if part.isdigit():
                    idx = int(part)
                    if 0 <= idx < n:
                        indices.append(idx)

            # 补全未排到的索引
            seen = set(indices)
            for i in range(n):
                if i not in seen:
                    indices.append(i)

            return indices[:n]
        except Exception:
            # LLM 失败 → 返回原始顺序
            return list(range(n))
