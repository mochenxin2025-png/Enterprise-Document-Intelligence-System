"""Hybrid Retrieval — Dense(BGE) + Sparse(BM25) + Reranker

Phase: P2 enhancement
依赖: rank_bm25 (pip install), BGE-Reranker (optional, 可降级为 LLM rerank)
"""
import re
import math
from collections import Counter
from typing import Optional

import numpy as np


class BM25Retriever:
    """BM25 稀疏检索 — 纯 Python 实现, 零外部依赖"""

    def __init__(self, k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self.corpus: list[list[str]] = []      # tokenized docs
        self.doc_lengths: list[int] = []
        self.avgdl: float = 0.0
        self.idf: dict[str, float] = {}
        self.N: int = 0

    def index(self, documents: list[str]):
        """构建 BM25 索引"""
        self.corpus = [self._tokenize(doc) for doc in documents]
        self.doc_lengths = [len(doc) for doc in self.corpus]
        self.N = len(self.corpus)
        self.avgdl = sum(self.doc_lengths) / max(self.N, 1)

        # IDF
        df = Counter()
        for doc in self.corpus:
            df.update(set(doc))
        self.idf = {
            term: math.log((self.N - freq + 0.5) / (freq + 0.5) + 1)
            for term, freq in df.items()
        }

    def search(self, query: str, top_k: int = 20) -> list[tuple[int, float]]:
        """返回 [(doc_idx, score), ...]"""
        query_tokens = self._tokenize(query)
        scores = np.zeros(self.N)

        for term in query_tokens:
            idf = self.idf.get(term, 0)
            if idf == 0:
                continue
            for i, doc in enumerate(self.corpus):
                tf = doc.count(term)
                if tf == 0:
                    continue
                doc_len = self.doc_lengths[i]
                score = idf * (tf * (self.k1 + 1)) / (tf + self.k1 * (1 - self.b + self.b * doc_len / self.avgdl))
                scores[i] += score

        # Top-K
        top_indices = np.argsort(scores)[::-1][:top_k]
        return [(int(i), float(scores[i])) for i in top_indices if scores[i] > 0]

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        """中文按字+词, 英文按词"""
        tokens = []
        # 中文按字切分
        for ch in text:
            if '\u4e00' <= ch <= '\u9fff':
                tokens.append(ch)
        # 英文/数字按词
        for word in re.findall(r'[a-zA-Z0-9]+', text.lower()):
            tokens.append(word)
        return tokens


class HybridRetriever:
    """Dense + Sparse 混合检索 + Reranker"""

    def __init__(self, dense_weight: float = 0.6):
        self.dense_weight = dense_weight
        self.bm25: Optional[BM25Retriever] = None
        self.chunk_texts: list[str] = []

    def build(self, chunk_texts: list[str]):
        """构建 BM25 索引 + 缓存文本"""
        self.chunk_texts = chunk_texts
        self.bm25 = BM25Retriever()
        self.bm25.index(chunk_texts)

    def search(self, query: str, dense_results: list,
               top_k: int = 20, rerank_top: int = 10) -> list:
        """
        dense_results: [(chunk_idx, score), ...]  # 来自 sqlite-vec
        返回融合 + Rerank 后的结果
        """
        if self.bm25 is None:
            return dense_results[:top_k]

        # 1. BM25 检索
        bm25_results = self.bm25.search(query, top_k=top_k)
        bm25_scores = {idx: score for idx, score in bm25_results}

        # 2. 分数归一化 + 融合
        dense_max = max(s for _, s in dense_results) if dense_results else 1.0
        bm25_max = max(bm25_scores.values()) if bm25_scores else 1.0

        combined = {}
        for idx, score in dense_results:
            combined[idx] = self.dense_weight * (score / dense_max)

        for idx, score in bm25_results:
            bm25_norm = score / max(bm25_max, 1.0)
            combined[idx] = combined.get(idx, 0) + (1 - self.dense_weight) * bm25_norm

        # 3. 排序
        sorted_results = sorted(combined.items(), key=lambda x: -x[1])[:rerank_top]
        return sorted_results

    @staticmethod
    def rerank_llm(query: str, candidates: list[str], llm_call) -> list[int]:
        """LLM Reranker — 让 LLM 选出最相关的 Chunk 序号"""
        prompt = (
            "You are a search relevance judge. Given a query and candidate passages, "
            "return the indices (0-based) of the MOST relevant passages, sorted by relevance. "
            "Return ONLY a JSON array of integers, e.g. [3, 0, 7].\n\n"
            f"Query: {query}\n\nCandidates:\n"
        )
        for i, text in enumerate(candidates):
            prompt += f"[{i}] {text[:300]}\n"
        prompt += "\nRelevant indices:"

        try:
            resp = llm_call(prompt)
            import json
            indices = json.loads(resp.strip())
            return indices[:5]
        except Exception:
            return list(range(min(5, len(candidates))))
