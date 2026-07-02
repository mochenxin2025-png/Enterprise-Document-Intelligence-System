"""QA Engine v3 — 基于 Interface Layer，所有依赖可替换

v3.2: 集成 Parent Document Retrieval + Reranker
"""

import time
from typing import Optional

from interfaces import LLMInterface, EmbeddingInterface, RerankerInterface
from retrieval import VectorStore
from adapters import DeepSeekAdapter, BGEEmbedder
from adapters.reranker import HeuristicReranker
from planner import IntentClassifier, plan_retrieval
from fusion import deduplicate, detect_conflicts, rank_results
from qa_pairs import QARegistry
from unanswered import UnansweredQueue
from context_builder import ContextBuilder
from config.tenant import get_current_tenant
from audit import AuditLogger, AuditEntry
from verifier import PermissionVerifier


class QAEngine:
    """基于接口的问答引擎 — 完整企业级 RAG"""

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
        self.audit = AuditLogger(db_path)
        self.reranker: RerankerInterface = HeuristicReranker()
        self.tenant_id = tenant_id or get_current_tenant()

    def ask(self, question: str, top_k: int = 10) -> dict:
        """Phase 1: 单路检索 -> LLM"""
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
        """v3.2: QA Pair -> Intent -> ParentDoc -> Rerank -> L4 Verify -> L5 Audit"""
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

        # Intent + Parent Document Retrieval + Rerank
        plan = plan_retrieval(question, self.planner)
        embedding = self.embedder.encode_query(question)

        # Parent Document Retrieval: 解决 Chunk 孤岛
        results = self.store.search_with_parent_retrieval(
            embedding, top_k=top_k, user_context=user_ctx, parent_top_n=3)
        if not results:
            results = self._retrieve(question, top_k * 2, user_ctx)

        sufficiency = self._check_sufficiency(results)
        if not sufficiency["sufficient"]:
            results.extend(self._retrieve(question, top_k, user_ctx))

        # Reranker: 精排候选
        if len(results) > 5:
            texts = [r.text for r in results]
            scores = [r.score for r in results]
            pages = [r.page for r in results]
            try:
                new_order = self.reranker.rerank(question, texts, scores, pages)
                results = [results[i] for i in new_order if i < len(results)]
            except Exception:
                pass

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

        ctx = self._build_context(fused, conflicts)
        answer = self._generate(question, ctx, plan.primary_intent).content
        answer = self._sanitize_output(answer)

        confidence = self._estimate_confidence(fused, conflicts)
        if confidence < 0.3:
            self.unanswered.enqueue(question, ctx[:500], tenant_id=self.tenant_id)

        result = {"answer": answer, "confidence": confidence,
                  "citations": self._extract_citations(fused),
                  "evidence_count": len(fused), "sufficiency": sufficiency,
                  "intent": plan.primary_intent,
                  "security_alerts": security_alerts if security_alerts else []}

        self._audit_log(question, result, user_ctx, t_start, security_alerts,
                        len(security_alerts) == 0)
        return result

    def ask_v3(self, question: str, top_k: int = 10,
               user_context: dict = None) -> dict:
        """v3.3: 模态感知 — 判断问题偏向文本/表格/图示，加权检索

        Modality Affinity: 先判断用户问题更偏向哪种证据类型，
        然后调整检索权重和证据融合策略。
        """
        t_start = time.time()
        user_ctx = user_context or {}
        security_alerts = []

        qa_match = self.qa_registry.search(question, tenant_id=self.tenant_id)
        if qa_match:
            result = {"answer": qa_match.answer, "confidence": 0.99,
                      "citations": [{"document": "QA Pair", "page": 0, "relevance": 1.0}],
                      "evidence_count": 1, "intent": "qa_pair_match",
                      "modality": "text"}
            self._audit_log(question, result, user_ctx, t_start, security_alerts, True)
            return result

        # Modality Affinity — 判断问题偏向哪种证据
        modality = self._classify_modality(question)
        plan = plan_retrieval(question, self.planner)
        embedding = self.embedder.encode_query(question)

        # 根据模态调整检索策略
        results = self.store.search_with_parent_retrieval(
            embedding, top_k=top_k, user_context=user_ctx, parent_top_n=3)
        if not results:
            results = self._retrieve(question, top_k * 2, user_ctx)

        sufficiency = self._check_sufficiency(results)
        if not sufficiency["sufficient"]:
            results.extend(self._retrieve(question, top_k, user_ctx))

        if len(results) > 5:
            texts = [r.text for r in results]
            scores = [r.score for r in results]
            pages = [r.page for r in results]
            try:
                new_order = self.reranker.rerank(question, texts, scores, pages)
                results = [results[i] for i in new_order if i < len(results)]
            except Exception:
                pass

        fused = rank_results(results)
        conflicts = detect_conflicts(results)
        if not fused:
            self.unanswered.enqueue(question, results[0].text if results else "",
                                    tenant_id=self.tenant_id)
            result = self._no_answer()
            result["modality"] = modality
            self._audit_log(question, result, user_ctx, t_start, security_alerts, False)
            return result

        if user_ctx:
            verifier = PermissionVerifier()
            vresult, fused = verifier.verify_batch(fused, user_ctx, self.tenant_id,
                                                    db_conn=self.store.conn)
            if not vresult.passed:
                security_alerts.extend(vresult.alerts)

        # 根据模态调整 prompt
        intent = f"{plan.primary_intent}_{modality}" if modality != "text" else plan.primary_intent
        ctx = self._build_context(fused, conflicts)
        answer = self._generate(question, ctx, intent).content
        answer = self._sanitize_output(answer)

        confidence = self._estimate_confidence(fused, conflicts)
        if confidence < 0.3:
            self.unanswered.enqueue(question, ctx[:500], tenant_id=self.tenant_id)

        result = {"answer": answer, "confidence": confidence,
                  "citations": self._extract_citations(fused),
                  "evidence_count": len(fused), "sufficiency": sufficiency,
                  "intent": plan.primary_intent, "modality": modality,
                  "security_alerts": security_alerts if security_alerts else []}

        self._audit_log(question, result, user_ctx, t_start, security_alerts,
                        len(security_alerts) == 0)
        return result

    @staticmethod
    def _classify_modality(question: str) -> str:
        """判断问题偏向哪种证据类型"""
        q = question.lower()

        table_keywords = ['表格', '对照表', '列表', '费用标准', '价格',
                         '尺寸表', '参数表', '规格表', '汇总表']
        diagram_keywords = ['流程图', '架构图', '拓扑图', '示意图', '结构图',
                           '框图', '关系图', '怎么连接', '如何连接']
        figure_keywords = ['图片', '照片', '截图', '图示', '如图所示']

        if any(kw in q for kw in table_keywords):
            return "table"
        if any(kw in q for kw in diagram_keywords):
            return "diagram"
        if any(kw in q for kw in figure_keywords):
            return "figure"
        return "text"

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
            pass

    @staticmethod
    def _sanitize_output(text: str) -> str:
        import re
        text = re.sub(r'(?<!\d)\d{15}(?:\d{2}[0-9Xx])?(?!\d)', '[ID_REDACTED]', text)
        text = re.sub(r'(?<!\d)1[3-9]\d{9}(?!\d)', '[PHONE_REDACTED]', text)
        text = re.sub(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}',
                      '[EMAIL_REDACTED]', text)
        text = re.sub(r'(?<!\d)(?:\d{1,3}\.){3}\d{1,3}(?!\d)', '[IP_REDACTED]', text)
        return text

    # ── v3: Modality-Aware ────────────────────────

    def ask_v3(self, question: str, top_k: int = 10,
               user_context: dict = None) -> dict:
        """v3: 模态感知问答 — 根据问题类型选择证据来源

        与 v2 的区别: 增加 ModalityAffinity，引导检索偏好。
        文本问题 → 文本检索
        表格问题 → 优先 TableBlock
        图示问题 → 优先 DiagramBlock + Vision
        """
        from multimodal import ModalityAffinity
        t_start = time.time()
        user_ctx = user_context or {}
        security_alerts = []

        # QA Pair 优先
        qa_match = self.qa_registry.search(question, tenant_id=self.tenant_id)
        if qa_match:
            return {"answer": qa_match.answer, "confidence": 0.99,
                    "citations": [{"document": "QA Pair", "page": 0, "relevance": 1.0}],
                    "evidence_count": 1, "intent": "qa_pair_match",
                    "modality_affinity": "qa_pair"}

        # 模态亲和度
        affinity = ModalityAffinity.detect(question)
        print(f"[v3] Modality affinity: {affinity}")

        # 根据亲和度调整检索策略
        if affinity == "table":
            # 表格类问题: 加大 top_k，优先匹配含表格关键词的 chunk
            results = self._retrieve(
                f"表格 数据 {question}", top_k * 2, user_ctx)
        elif affinity in ("diagram", "figure"):
            results = self._retrieve(
                f"图示 结构 {question}", top_k * 2, user_ctx)
        else:
            # 默认: Parent Document Retrieval
            embedding = self.embedder.encode_query(question)
            results = self.store.search_with_parent_retrieval(
                embedding, top_k=top_k, user_context=user_ctx, parent_top_n=3)

        if not results:
            results = self._retrieve(question, top_k * 2, user_ctx)

        # Reranker
        if len(results) > 5:
            texts = [r.text for r in results]
            scores = [r.score for r in results]
            pages = [r.page for r in results]
            try:
                new_order = self.reranker.rerank(question, texts, scores, pages)
                results = [results[i] for i in new_order if i < len(results)]
            except Exception:
                pass

        fused = rank_results(results)
        conflicts = detect_conflicts(results)
        if not fused:
            return self._no_answer()

        # L4 + L5 + 生成
        if user_ctx:
            verifier = PermissionVerifier()
            vresult, fused = verifier.verify_batch(
                fused, user_ctx, self.tenant_id, db_conn=self.store.conn)
            if not vresult.passed:
                security_alerts.extend(vresult.alerts)

        ctx = self._build_context(fused, conflicts)
        answer = self._generate(question, ctx,
            affinity if affinity in ("table", "diagram") else "basic").content
        answer = self._sanitize_output(answer)

        confidence = self._estimate_confidence(fused, conflicts)
        result = {"answer": answer, "confidence": confidence,
                  "citations": self._extract_citations(fused),
                  "evidence_count": len(fused),
                  "intent": "v3_multimodal",
                  "modality_affinity": affinity,
                  "security_alerts": security_alerts if security_alerts else []}

        self._audit_log(question, result, user_ctx, t_start, security_alerts,
                        len(security_alerts) == 0)
        return result
