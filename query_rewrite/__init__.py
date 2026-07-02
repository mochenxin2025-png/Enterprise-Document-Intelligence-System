"""Query Rewrite — 多轮对话指代消解

问题: "Nginx过滤规则怎么配置？" → "它怎么修改？"
这里的"它"需要改写为"Nginx过滤规则"才能正确检索。

两种实现:
  - RuleRewrite: 正则替换常见代词（零成本）
  - LLMRewrite: DeepSeek 上下文改写（高质量）
"""
import re
from typing import Optional


class RuleRewrite:
    """基于规则的多轮指代消解"""

    CHINESE_PRONOUNS = [
        "它", "他", "她", "它们", "他们", "她们",
        "这个", "那个", "这些", "那些",
        "这里", "那里", "这样", "那样",
        "其", "该", "此",
    ]
    ENGLISH_PRONOUNS = [
        "it", "they", "them", "this", "that", "these", "those",
    ]

    @classmethod
    def rewrite(cls, current_question: str,
                history: list[str] = None) -> str:
        """简单规则改写：如果当前问题是指代性问题，拼接上一次提问"""
        if not history:
            return current_question

        q = current_question.strip()

        # 检测是否是纯指代问题
        is_reference_only = cls._is_pure_reference(q)

        if is_reference_only and history:
            # 直接返回上一次提问
            return history[-1]

        # 检测是否包含指代词
        has_pronoun = any(p in q for p in cls.CHINESE_PRONOUNS)
        has_pronoun = has_pronoun or any(p.lower() in q.lower() for p in cls.ENGLISH_PRONOUNS)

        if has_pronoun and history:
            # 把上一轮主题拼到前面
            last = history[-1][:100]
            return f"{last} {q}"

        return current_question

    @classmethod
    def _is_pure_reference(cls, q: str) -> bool:
        """是否完全是代词问题（无实质内容）"""
        # 去掉疑问词后的纯代词
        stripped = re.sub(r'[怎么|如何|什么|多少|哪里|什么时候|为什么|吗|呢|啊|吧]$', '', q)
        stripped = re.sub(r'[的得地]$', '', stripped)
        return len(stripped) <= 2


class LLMRewrite:
    """LLM 上下文改写 — 高质量但消耗 token"""

    def __init__(self, llm=None):
        if llm is None:
            from adapters import DeepSeekAdapter
            self.llm = DeepSeekAdapter()
        else:
            self.llm = llm

    def rewrite(self, current_question: str,
                history: list[str] = None) -> str:
        """用 LLM 改写带指代的问题"""
        if not history:
            return current_question

        context = "\n".join(f"Q: {h}" for h in history[-3:])
        prompt = (
            "你是一个查询改写助手。根据对话历史，将用户当前问题中的代词"
            "（如'它'、'这个'）替换为具体的指代对象。只输出改写后的问题，不要解释。\n\n"
            f"对话历史:\n{context}\n\n"
            f"当前问题: {current_question}\n\n"
            "改写后:"
        )

        try:
            resp = self.llm.chat([
                {"role": "user", "content": prompt},
            ], max_tokens=200, temperature=0)
            rewritten = resp.content.strip()
            return rewritten if rewritten else current_question
        except Exception:
            return current_question


# ── Service ──────────────────────────────────────

class QueryRewriteService:
    """查询改写服务 — 默认用规则，可选 LLM"""

    def __init__(self, use_llm: bool = False):
        self.rule = RuleRewrite()
        self.llm = LLMRewrite() if use_llm else None
        self.history: list[str] = []

    def rewrite(self, question: str) -> str:
        """改写查询"""
        rewritten = self.rule.rewrite(question, self.history)
        if self.llm and rewritten != question:
            rewritten = self.llm.rewrite(question, self.history)
        return rewritten

    def add_to_history(self, question: str):
        """添加到对话历史（每次提问后调用）"""
        self.history.append(question)
        if len(self.history) > 10:
            self.history = self.history[-10:]

    def clear_history(self):
        self.history = []
