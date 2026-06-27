"""QA Engine v3 — 基于 Interface Layer，所有依赖可替换"""
from typing import Optional

from interfaces import LLMInterface, EmbeddingInterface
from retrieval import VectorStore
from adapters import DeepSeekAdapter, BGEEmbedder
from planner import IntentClassifier, plan_retrieval
from fusion import deduplicate, detect_conflicts, rank_results
from qa_pairs import QARegistry
from unanswered import UnansweredQueue
from context_builder import ContextBuilder

class QAEngine:
    """基于接口的问答引擎 — LLM/Embedding/VectorStore/ContextBuilder 均可替换"""

    def __init__(self,
                 llm: LLMInterface = None,
                 embedder: EmbeddingInterface = None,
                 store = None,
                 db_path: str = "./data/edis.db"):
        self.llm = llm or DeepSeekAdapter()
        self.embedder = embedder or BGEEmbedder()
        self.store = store or VectorStore(db_path)
        self.ctx_builder = ContextBuilder()
        self.planner = IntentClassifier()
        self.qa_registry = QARegistry(db_path)
        self.unanswered = UnansweredQueue(db_path)

    def ask(self, question: str, top_k: int = 10) -> dict:
        """Phase 1: 单路检索 → LLM"""
        results = self._retrieve(question, top_k)
        if not results:
            return self._no_answer()
        ctx = self._build_context(results)
        answer = self._generate(question, ctx).content
        return {"answer": answer, "confidence": self._estimate_confidence(results),
                "citations": self._extract_citations(results),
                "evidence_count": len(results)}

    def ask_v2(self, question: str, top_k: int = 10) -> dict:
        """Phase 2+: QA Pair → Intent → Progressive → Queue"""
        qa_match = self.qa_registry.search(question)
        if qa_match:
            print(f"[qa] QA Pair: {qa_match.id}")
            return {"answer": qa_match.answer, "confidence": 0.99,
                    "citations": [{"document": "QA Pair", "page": 0, "relevance": 1.0}],
                    "evidence_count": 1, "intent": "qa_pair_match"}

        plan = plan_retrieval(question, self.planner)
        results = self._retrieve(question, top_k * 2)
        sufficiency = self._check_sufficiency(results)
        if not sufficiency["sufficient"]:
            results.extend(self._retrieve(question, top_k))

        fused = rank_results(results)
        conflicts = detect_conflicts(results)
        if not fused:
            self.unanswered.enqueue(question, results[0].text if results else "")
            return self._no_answer()

        ctx = self._build_context(fused, conflicts)
        answer = self._generate(question, ctx, plan.primary_intent).content
        confidence = self._estimate_confidence(fused, conflicts)
        if confidence < 0.3:
            self.unanswered.enqueue(question, ctx[:500])

        return {"answer": answer, "confidence": confidence,
                "citations": self._extract_citations(fused),
                "evidence_count": len(fused), "sufficiency": sufficiency,
                "intent": plan.primary_intent}

    def _retrieve(self, question, top_k, offset=0):
        embedding = self.embedder.encode_query(question)
        return self.store.search(embedding, top_k=top_k)

    def _build_context(self, results, conflicts=None):
        parts = []
        for i, r in enumerate(results):
            src = f"[{i+1}] Page {r.page}"
            parts.append(f"{src}\n{r.text}")
        return "\n\n---\n\n".join(parts)

    def _generate(self, question, context, intent="basic"):
        from config.prompts import PromptRegistry
        # Try intent-specific prompt, fall back to generic v2
        prompt_name = f"qa_{intent}"
        if prompt_name not in PromptRegistry._templates:
            system, user = PromptRegistry.render("qa", "v2",
                question=question, context=context)
        else:
            system, user = PromptRegistry.render(prompt_name, "v1",
                question=question, context=context)
        return self.llm.chat([
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ])

    def _extract_citations(self, results):
        seen = set()
        cits = []
        for r in results:
            k = (getattr(r, 'source', ''), r.page)
            if k not in seen:
                seen.add(k)
                cits.append({"document": getattr(r, 'source', ''), "page": r.page, "relevance": r.score})
        return cits[:5]

    def _estimate_confidence(self, results, conflicts=None):
        if not results: return 0.0
        top = results[0].score
        cnt = len([r for r in results if r.score > 0.3])
        div = len(set(r.page for r in results)) / max(len(results), 1)
        w = 0.5 * top + 0.3 * div + 0.2 * (cnt / len(results))
        if conflicts: w *= 0.7
        return round(min(w, 1.0), 3)

    def _check_sufficiency(self, results):
        if not results: return {"sufficient": False, "score": 0}
        q = [r for r in results if r.score >= 0.8]
        up = len(set(r.page for r in q) - {0})
        score = 0.5 * results[0].score + 0.3 * up / max(len(results), 1) + 0.2 * len(q) / max(len(results), 1)
        return {"sufficient": score >= 0.6 and up >= 2, "score": round(score, 3),
                "qualified_chunks": len(q), "unique_pages": up}

    def _no_answer(self):
        return {"answer": "Insufficient evidence.", "confidence": 0, "citations": [], "evidence_count": 0}
