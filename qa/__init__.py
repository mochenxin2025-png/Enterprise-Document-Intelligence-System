"""DEPRECATED — 请使用 qa.engine.QAEngine 代替。

此模块保留仅为向后兼容。新代码请导入:
    from qa.engine import QAEngine
"""
import warnings
warnings.warn("qa.QASystem is deprecated, use qa.engine.QAEngine instead", DeprecationWarning, stacklevel=2)

import httpx
from typing import Optional

from config import config
from retrieval import VectorStore, Embedder, SearchResult
from planner import IntentClassifier, plan_retrieval
from fusion import deduplicate, detect_conflicts, rank_results
from qa_pairs import QARegistry
from unanswered import UnansweredQueue


class QASystem:
    def __init__(self, vector_store=None):
        self.store = vector_store or VectorStore(config.get("storage", "db_path"))
        self.planner = IntentClassifier()
        self.qa_registry = QARegistry(config.get("storage", "db_path"))
        self.unanswered = UnansweredQueue(config.get("storage", "db_path"))

    def ask(self, question, top_k=10):
        results = self._retrieve(question, top_k)
        if not results:
            return self._no_answer()
        ctx = self._build_context(results)
        answer = self._generate(question, ctx)
        return {"answer": answer, "confidence": self._estimate_confidence(results),
                "citations": self._extract_citations(results),
                "evidence_count": len(results),
                "sufficiency": self._check_sufficiency(results)}

    def ask_v2(self, question, top_k=10):
        # QA Pair 优先
        qa_match = self.qa_registry.search(question)
        if qa_match:
            print(f"[qa-v2] QA Pair hit: {qa_match.id} (hits: {qa_match.hit_count})")
            return {"answer": qa_match.answer, "confidence": 0.99,
                    "citations": [{"document": "QA Pair", "page": 0, "relevance": 1.0}],
                    "evidence_count": 1, "intent": "qa_pair_match"}

        plan = plan_retrieval(question, self.planner)
        print(f"[qa-v2] Intent: {plan.primary_intent}, paths: {plan.paths}")
        results = self._retrieve(question, top_k * 2)
        sufficiency = self._check_sufficiency_v2(results)
        if not sufficiency["sufficient"]:
            results.extend(self._retrieve(question, top_k))

        fused = rank_results(results)
        conflicts = detect_conflicts(results)
        if not fused:
            self.unanswered.enqueue(question, results[0].text if results else "")
            return self._no_answer()

        ctx = self._build_context_fused(fused, conflicts)
        answer = self._generate_v2(question, ctx, plan.primary_intent)
        confidence = self._estimate_confidence_v2(fused, conflicts)
        if confidence < 0.3:
            self.unanswered.enqueue(question, ctx[:500])

        return {"answer": answer, "confidence": confidence,
                "citations": self._extract_citations_fused(fused),
                "evidence_count": len(fused), "sufficiency": sufficiency,
                "intent": plan.primary_intent,
                "conflicts": [{"param": c.param, "values": c.values} for c in conflicts] if conflicts else []}

    def _retrieve(self, question, top_k, offset=0):
        embedding = Embedder.encode_query(question)
        return self.store.search(embedding, top_k=top_k)

    def _build_context(self, results):
        parts = []
        for i, r in enumerate(results):
            src = f"[{i+1}] {r.source}, Page {r.page}"
            if r.section: src += f", {r.section}"
            parts.append(f"{src}\n{r.text}")
        return "\n\n---\n\n".join(parts)

    def _build_context_fused(self, fused, conflicts=None):
        parts = []
        for i, fe in enumerate(fused):
            src = f"[{i+1}] {fe.source}, Page {fe.page}"
            if fe.section: src += f", {fe.section}"
            parts.append(f"{src}\n{fe.text}")
        if conflicts:
            parts.append("\n---\n[DETECTED CONFLICTS]")
            for c in conflicts:
                parts.append(f"  {c.param}: " + ", ".join(f"{v}{u}" for v, u, _ in c.values))
        return "\n\n".join(parts)

    def _generate(self, question, context):
        return self._call_llm(question, context, "basic")

    def _generate_v2(self, question, context, intent):
        return self._call_llm(question, context, intent)

    def _call_llm(self, question, context, mode):
        key = config.api_key("deepseek")
        prompt = (
            "You are an engineering document assistant. Answer based ONLY on the provided context. "
            "If the context doesn't contain enough information, say so. "
            "When citing, use [N, Page X] format. Be precise."
        )
        user = f"Context:\n{context}\n\nQuestion: {question}\n\nAnswer (cite with [N, Page X]):"
        try:
            resp = httpx.post(
                f"{config.get('api', 'deepseek', 'base_url')}/chat/completions",
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                json={"model": config.get("llm", "model"),
                      "messages": [{"role": "system", "content": prompt}, {"role": "user", "content": user}],
                      "temperature": config.get("llm", "temperature"),
                      "max_tokens": config.get("llm", "max_tokens")},
                timeout=60)
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]
        except Exception as e:
            return f"[Error] {e}"

    def _extract_citations(self, results):
        seen = set()
        cits = []
        for r in results:
            k = (r.source, r.page)
            if k not in seen:
                seen.add(k)
                cits.append({"document": r.source, "page": r.page, "relevance": r.score})
        return cits[:5]

    def _extract_citations_fused(self, fused):
        seen = set()
        cits = []
        for fe in fused:
            k = (fe.source, fe.page)
            if k not in seen:
                seen.add(k)
                cits.append({"document": fe.source, "page": fe.page, "relevance": fe.score})
        return cits[:5]

    def _estimate_confidence(self, results):
        if not results: return 0.0
        top = results[0].score
        cnt = len([r for r in results if r.score > 0.3])
        div = len(set(r.page for r in results)) / max(len(results), 1)
        return round(min(0.4 * top + 0.3 * (cnt / len(results)) + 0.3 * div, 1.0), 3)

    def _estimate_confidence_v2(self, fused, conflicts=None):
        if not fused: return 0.0
        top = fused[0].score
        cnt = len([f for f in fused if f.score > 0.3])
        div = len(set(f.page for f in fused)) / max(len(fused), 1)
        w = 0.5 * top + 0.3 * div + 0.2 * (cnt / len(fused))
        if conflicts: w *= 0.7
        return round(min(w, 1.0), 3)

    def _check_sufficiency(self, results):
        try: cfg = config.get("retrieval", "sufficiency")
        except: cfg = {}
        th = cfg.get("relevance_threshold", 0.8) if isinstance(cfg, dict) else 0.8
        em = cfg.get("evidence_count_min", 3) if isinstance(cfg, dict) else 3
        q = [r for r in results if r.score >= th]
        up = len(set(r.page for r in q) - {0})
        return {"sufficient": len(q) >= em and up >= 2, "qualified_chunks": len(q),
                "unique_pages": up, "top_score": results[0].score if results else 0}

    def _check_sufficiency_v2(self, results):
        if not results: return {"sufficient": False, "score": 0, "qualified_chunks": 0, "unique_pages": 0}
        try: cfg = config.get("retrieval", "sufficiency")
        except: cfg = {}
        th = cfg.get("relevance_threshold", 0.8) if isinstance(cfg, dict) else 0.8
        q = [r for r in results if r.score >= th]
        up = len(set(r.page for r in q) - {0})
        rel = results[0].score
        div = up / max(len(results), 1)
        ev = len(q) / max(len(results), 1)
        score = 0.5 * rel + 0.3 * div + 0.2 * ev
        return {"sufficient": score >= 0.6 and up >= 2, "score": round(score, 3),
                "qualified_chunks": len(q), "unique_pages": up, "top_score": rel}

    def _no_answer(self):
        return {"answer": "Insufficient evidence.", "confidence": 0, "citations": [], "evidence_count": 0}
