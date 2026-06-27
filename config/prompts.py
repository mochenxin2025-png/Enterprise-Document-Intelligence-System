"""Prompt Registry — 版本化 Prompt 模板

不要: prompt = "You are an engineering assistant..." 写死在代码里
改为: prompt = PromptRegistry.render("qa_v2", intent="definition")

支持:
  - 多版本 (v1/v2/v3)
  - 变量替换 ({question} / {context})
  - 意图自适应 (parameter / definition / relationship 各有不同模板)
  - A/B 测试 (同问题用不同版本 prompt 对比)
"""
from typing import Optional


class PromptRegistry:
    """全局 Prompt 模板库"""

    _templates: dict[str, dict] = {}

    @classmethod
    def register(cls, name: str, version: str = "v1", **kwargs):
        """注册一个 Prompt 模板"""
        if name not in cls._templates:
            cls._templates[name] = {}
        cls._templates[name][version] = kwargs
        return cls

    @classmethod
    def render(cls, name: str, version: str = "v1", **variables) -> tuple[str, str]:
        """渲染 Prompt → (system_prompt, user_prompt)"""
        entry = cls._templates.get(name, {}).get(version)
        if entry is None:
            raise ValueError(f"Prompt not found: {name}/{version}. Available: {list(cls._templates.get(name, {}).keys())}")

        system = entry.get("system", "").format(**variables)
        user = entry.get("user", "").format(**variables)
        return system, user

    @classmethod
    def list_versions(cls, name: str) -> list[str]:
        return list(cls._templates.get(name, {}).keys())

    @classmethod
    def list_all(cls) -> dict:
        return {k: list(v.keys()) for k, v in cls._templates.items()}


# ── 注册所有内置 Prompts ────────────────────────

# QA — Phase 1 (基础)
PromptRegistry.register("qa", "v1",
    system="You are an engineering document assistant. Answer based ONLY on the provided context. "
           "If the context doesn't contain enough information, say so. Be precise.",
    user="Context:\n{context}\n\nQuestion: {question}\n\nAnswer:")

# QA — Phase 2 (分类增强)
PromptRegistry.register("qa", "v2",
    system="You are an engineering document assistant. Answer based ONLY on the provided context. "
           "If the context doesn't contain enough information, say so. "
           "If multiple sources conflict, note the discrepancy. "
           "Cite with [N, Page X]. Be precise — include parameter values, units, and page references.",
    user="Context:\n{context}\n\nQuestion: {question}\n\n"
         "Answer (cite with [N, Page X] format). If not found, say so without guessing:")

# QA — 按 Intent 细分
_intent_systems = {
    "parameter": "You are a precise engineering parameter lookup assistant. "
                 "Answer ONLY from the context. Include values, units, and [N, Page X] references. "
                 "If multiple values exist for the same parameter, note the discrepancy.",
    "definition": "You are a technical documentation assistant. Answer based ONLY on the provided context. "
                  "Provide clear, concise definitions with [N, Page X] citations. "
                  "If the context doesn't define the term, say so.",
    "relationship": "You are an engineering systems analyst. Answer based ONLY on the provided context. "
                    "Describe relationships between components with [N, Page X] citations. "
                    "If the context doesn't describe the relationship, say so.",
}

for intent, system in _intent_systems.items():
    PromptRegistry.register(f"qa_{intent}", "v1",
        system=system,
        user="Context:\n{context}\n\nQuestion: {question}\n\n"
             "Answer with [N, Page X] citations. If not found, say so:")

# Evaluation Judge
PromptRegistry.register("eval_judge", "v1",
    system="You are evaluating an RAG system's answer quality. Judge whether the answer is FACTUALLY "
           "SUPPORTED by the provided context chunks. Return ONLY a JSON object.",
    user="Question: {question}\n\nAnswer: {answer}\n\nContext chunks:\n{context}\n\n"
         'Return JSON: {{"supported": true/false, "relevant_chunks": [1,2,...], '
         '"confidence": 0.0-1.0, "reason": "one sentence"}}')

# Rerank Judge
PromptRegistry.register("rerank_judge", "v1",
    system="You are a search relevance judge. Given a query and candidate passages, "
           "return the indices of the MOST relevant passages, sorted by relevance.",
    user="Query: {query}\n\nCandidates:\n{candidates}\n\nReturn ONLY a JSON array of integers, e.g. [3, 0, 7].")

# Memory Consolidation
PromptRegistry.register("memory_consolidation", "v1",
    system="Extract important facts and user preferences from this conversation. "
           "Return ONLY a JSON array of strings. Skip trivial/small-talk content.",
    user="Conversation:\n{conversation}\n\nImportant facts (JSON array):")
