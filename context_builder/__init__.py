"""Context Builder — 独立上下文组装层

从检索结果 → 去重 → 排序 → 压缩 → 格式化 → 最终 Prompt 上下文。

可复用于 QA / 评估 / Rerank / Memory Consolidation 等场景。

Token Budget:
  问题:     5%
  指令:     10%
  上下文:   50%
  推理空间: 35%
"""
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ContextConfig:
    max_tokens: int = 3000        # 上下文 token 上限
    max_chunks: int = 10          # 最大 chunk 数
    max_chunk_chars: int = 600    # 单个 chunk 最大字符数
    dedup_threshold: float = 0.85 # Jaccard 去重阈值
    include_page_ref: bool = True # 是否带页码引用
    source_format: str = "[{i}] {source}, Page {page}{section}"


class ContextBuilder:
    """从检索结果构建 LLM 上下文"""

    def __init__(self, config: ContextConfig = None):
        self.cfg = config or ContextConfig()

    def build(self, results: list, conflicts: list = None,
              token_budget: int = None) -> str:
        """主入口：检索结果 → Prompt 上下文"""
        if not results:
            return "No relevant context found."

        max_tokens = token_budget or self.cfg.max_tokens

        # 1. 去重
        deduped = self._deduplicate(results)

        # 2. 排序（按 score 降序）
        deduped.sort(key=lambda r: getattr(r, 'score', 0), reverse=True)

        # 3. 截断到 chunk 数上限
        deduped = deduped[:self.cfg.max_chunks]

        # 4. 格式化
        parts = []
        for i, r in enumerate(deduped):
            text = getattr(r, 'text', '')
            if len(text) > self.cfg.max_chunk_chars:
                text = text[:self.cfg.max_chunk_chars] + "..."

            if self.cfg.include_page_ref:
                source = getattr(r, 'source', '')
                page = getattr(r, 'page', 0)
                section = getattr(r, 'section', '')
                sec = f", {section}" if section else ""
                header = self.cfg.source_format.format(
                    i=i+1, source=source, page=page, section=sec)
                parts.append(f"{header}\n{text}")
            else:
                parts.append(text)

        context = "\n\n---\n\n".join(parts)

        # 5. 冲突标注
        if conflicts:
            context += "\n\n---\n[DETECTED CONFLICTS]"
            for c in conflicts:
                vals = ", ".join(f"{v}{u}" for v, u, _ in c.values)
                context += f"\n  {c.param}: {vals}"

        # 6. Token 预算裁剪
        est_tokens = len(context) // 2
        if est_tokens > max_tokens:
            ratio = max_tokens / est_tokens
            for i in range(len(parts)):
                parts[i] = parts[i][:int(len(parts[i]) * ratio)]
            context = "\n\n---\n\n".join(parts)

        return context

    def _deduplicate(self, results: list) -> list:
        """基于 Jaccard trigram 去重"""
        if len(results) <= 1:
            return list(results)

        kept = []
        for r in results:
            is_dup = False
            r_text = getattr(r, 'text', '')
            for existing in kept:
                e_text = getattr(existing, 'text', '')
                if self._jaccard(r_text, e_text) >= self.cfg.dedup_threshold:
                    is_dup = True
                    break
            if not is_dup:
                kept.append(r)
        return kept

    @staticmethod
    def _jaccard(a: str, b: str) -> float:
        def trigrams(s):
            return set(s[i:i+3] for i in range(len(s) - 2))
        sa, sb = trigrams(a.lower()), trigrams(b.lower())
        if not sa or not sb:
            return 0.0
        return len(sa & sb) / len(sa | sb)


# 快捷函数
default_builder = ContextBuilder()


def build_context(results, conflicts=None, max_tokens=None) -> str:
    return default_builder.build(results, conflicts, max_tokens)
