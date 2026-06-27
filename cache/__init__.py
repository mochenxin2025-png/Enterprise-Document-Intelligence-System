"""Query Cache — LRU 缓存减少重复 LLM/Embedding 调用

两层缓存:
  1. Answer Cache: 问题→答案 映射 (TTL 30min, LRU 淘汰)
  2. Embedding Cache: 文本→向量 映射 (TTL 1h)

统计: hit_rate, miss_count
"""
import hashlib
import time
import json
import threading
from collections import OrderedDict
from typing import Any, Optional


class LRUCache:
    """线程安全的 LRU 缓存"""

    def __init__(self, max_size: int = 1000, ttl_seconds: int = 1800):
        self.max_size = max_size
        self.ttl = ttl_seconds
        self._cache: OrderedDict[str, tuple[float, Any]] = OrderedDict()
        self._lock = threading.Lock()
        self.hits = 0
        self.misses = 0

    def _key(self, raw: str) -> str:
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    def get(self, key_raw: str) -> Optional[Any]:
        k = self._key(key_raw)
        with self._lock:
            if k not in self._cache:
                self.misses += 1
                return None
            ts, val = self._cache[k]
            if time.time() - ts > self.ttl:
                del self._cache[k]
                self.misses += 1
                return None
            self._cache.move_to_end(k)
            self.hits += 1
            return val

    def set(self, key_raw: str, value: Any):
        k = self._key(key_raw)
        with self._lock:
            if k in self._cache:
                del self._cache[k]
            self._cache[k] = (time.time(), value)
            if len(self._cache) > self.max_size:
                self._cache.popitem(last=False)

    @property
    def hit_rate(self) -> float:
        total = self.hits + self.misses
        return self.hits / total if total > 0 else 0.0

    @property
    def stats(self) -> dict:
        return {"size": len(self._cache), "hits": self.hits,
                "misses": self.misses, "hit_rate": round(self.hit_rate, 3)}


# 全局缓存实例
answer_cache = LRUCache(max_size=500, ttl_seconds=1800)      # 答案 30min
embedding_cache = LRUCache(max_size=2000, ttl_seconds=3600)  # 向量 1h


def cached_ask(question: str, engine, top_k: int = 10) -> dict:
    """带缓存的问答"""
    cached = answer_cache.get(question)
    if cached:
        cached["cached"] = True
        return cached
    result = engine.ask_v2(question, top_k)
    answer_cache.set(question, result)
    return result


def cached_embed(text: str, embedder) -> list[float]:
    """带缓存的 embedding"""
    cached = embedding_cache.get(text)
    if cached:
        return cached
    vec = embedder.encode_query(text)
    embedding_cache.set(text, vec)
    return vec
