"""QA Engine v3 — 基于 Interface Layer，所有依赖可替换

v3.1: 集成 L4 生成前校验 + L5 审计日志
"""

import time
from typing import Optional

from interfaces import LLMInterface, EmbeddingInterface
from retrieval import VectorStore
from adapters import DeepSeekAdapter, BGEEmbedder
from planner import IntentClassifier, plan_retrieval
from fusion import deduplicate, detect_conflicts, rank_results
from qa_pairs import QARegistry
from unanswered import UnansweredQueue
from context_builder import ContextBuilder
from config.tenant import get_current_tenant
from audit import AuditLogger, AuditEntry
from verifier import PermissionVerifier


class QAEngine:
    """基于接口的问答引擎 — 完整企业级 RAG 五层架构"""

    def __init__(self,
                 llm: LLMInterface = None,
                 embedder: EmbeddingInterface = None,
                 store = None,
                 db_path: str = "./data/edis.db",
                 tenant_id: str = None):
        self.llm = llm or DeepSeekAdapter()
        self.embedder = embedder or BGEEmbedder()
        self.store = store or VectorStore(db_path)
        self.ctx_builder = ContextBuilder()
        self.planner = IntentClassifier()
        self.qa_registry = QARegistry(db_path)
        self.unanswered = UnansweredQueue(db_path)
        self.audit = AuditLogger(db_path)           # L5: 审计日志
        self.tenant_id = tenant_id or get_current_tenant()

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

    def ask_v2(self, question: str, top_k: int = 10,
               user_context: dict = None) -> dict:
        """Phase 2+: QA Pair → Intent → Progressive → L4 Verify → L5 Audit

        user_context: {"user_id", "role", "department", "security_clearance"}
        """
        t_start = time.time()
        user_ctx = user_context or {}
        security_alerts = []

        # QA Pair 优先
        qa_match = self.qa_registry.search(question, tenant_id=self.tenant_id)
        if qa_match:
            print(f"[qa] QA Pair: {qa_match.id}")
            result = {"answer": qa_match.answer, "confidence": 0.99,
                      "citations": [{"document": "QA Pair", "page": 0, "relevance": 1.0}],
                      "evidence_count": 1, "intent": "qa_pair_match"}
            self._audit_log(question, result, user_ctx, t_start, security_alerts, True)
            return result

        # Intent + 渐进式检索 (with user_context for permission filtering)
        plan = plan_retrieval(question, self.planner)
        results = self._retrieve(question, top_k * 2, user_ctx)
        sufficiency = self._check_sufficiency(results)
        if not sufficiency["sufficient"]:
            results.extend(self._retrieve(question, top_k, user_ctx))

        fused = rank_results(results)
        conflicts = detect_conflicts(results)
        if not fused:
            self.unanswered.enqueue(question, results[0].text if results else "",
                                    tenant_id=self.tenant_id)
            result = self._no_answer()
            self._audit_log(question, result, user_ctx, t_start, security_alerts, False)
            return result

        # L4: 生成前二次校验
        if user_ctx:
            verifier = PermissionVerifier()
            vresult, fused = verifier.verify_batch(fused, user_ctx, self.tenant_id,
                                                    db_conn=self.store.conn)
            if not vresult.passed:
                security_alerts.extend(vresult.alerts)
                print(f"[L4] Permission verify: {vresult.rejected_chunks}/{vresult.total_chunks} rejected")

        ctx = self._build_context(fused, conflicts)
        answer = self._generate(question, ctx, plan.primary_intent).content

        # L5: 输出脱敏
        answer = self._sanitize_output(answer)

        confidence = self._estimate_confidence(fused, conflicts)
        if confidence < 0.3:
            self.unanswered.enqueue(question, ctx[:500], tenant_id=self.tenant_id)

        result = {"answer": answer, "confidence": confidence,
                  "citations": self._extract_citations(fused),
                  "evidence_count": len(fused), "sufficiency": sufficiency,
                  "intent": plan.primary_intent,
                  "security_alerts": security_alerts if security_alerts else []}

        # L5: 审计日志
        self._audit_log(question, result, user_ctx, t_start, security_alerts,
                        len(security_alerts) == 0)

        return result

    def _retrieve(self, question, top_k, user_context=None):
        embedding = self.embedder.encode_query(question)
        return self.store.search(embedding, top_k=top_k, user_context=user_context)

    def _build_context(self, results, conflicts=None):
        parts = []
        for i, r in enumerate(results):
            src = f"[{i+1}] Page {r.page}"
            parts.append(f"{src}\n{r.text}")
        return "\n\n---\n\n".join(parts)

    def _generate(self, question, context, intent="basic"):
        from config.prompts import PromptRegistry
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
                cits.append({"document": getattr(r, 'source', ''),
                            "page": r.page, "relevance": r.score})
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
        return {"answer": "Insufficient evidence.", "confidence": 0,
                "citations": [], "evidence_count": 0}

    def _audit_log(self, question, result, user_ctx, t_start,
                   security_alerts, verified):
        """L5: 写入审计日志"""
        try:
            entry = AuditEntry(
                user_id=user_ctx.get("user_id", ""),
                question=question,
                tenant_id=self.tenant_id,
                retrieved_doc_ids=list(set(
                    c.get("document", "") for c in result.get("citations", [])
                )),
                cited_chunks=result.get("citations", []),
                answer=result.get("answer", ""),
                confidence=result.get("confidence", 0),
                intent=result.get("intent", ""),
                model=self.llm.model_name,
                latency_ms=(time.time() - t_start) * 1000,
                timestamp=time.time(),
                security_alerts=security_alerts,
                verification_passed=verified,
            )
            self.audit.log(entry)
        except Exception:
            pass  # 审计失败不阻断主流程

    @staticmethod
    def _sanitize_output(text: str) -> str:
        """L5: 输出脱敏 — 移除可能泄露的敏感模式"""
        import re
        # 身份证号 (15 or 18 digits)
        text = re.sub(r'(?<!\d)\d{15}(?:\d{2}[0-9Xx])?(?!\d)', '[ID_REDACTED]', text)
        # 手机号 (11 digits, starts with 1)
        text = re.sub(r'(?<!\d)1[3-9]\d{9}(?!\d)', '[PHONE_REDACTED]', text)
        # 邮箱
        text = re.sub(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}',
                      '[EMAIL_REDACTED]', text)
        # IP 地址
        text = re.sub(r'(?<!\d)(?:\d{1,3}\.){3}\d{1,3}(?!\d)', '[IP_REDACTED]', text)
        return text
