"""Agent Tool Registry — 统一输出格式 {ok, data, error}

所有外部 Agent 通过此层调用 EDIS 能力。
内部 tools/ToolRegistry 保持不变，此层做格式适配。
"""
import time
import traceback
from typing import Any, Callable
from dataclasses import dataclass, field


@dataclass
class ToolResult:
    """统一工具返回格式"""
    ok: bool
    data: Any = None
    error: dict = field(default_factory=dict)
    latency_ms: float = 0.0

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "data": self.data,
            "error": self.error if self.error else None,
            "latency_ms": self.latency_ms,
        }


class AgentToolRegistry:
    """对外 Agent 工具注册表 — 统一 {ok, data, error} 输出"""

    _tools: dict[str, Callable] = {}

    @classmethod
    def register(cls, name: str, description: str = ""):
        """装饰器：注册工具"""
        def decorator(fn):
            cls._tools[name] = fn
            fn._tool_name = name
            fn._tool_description = description
            return fn
        return decorator

    @classmethod
    def call(cls, name: str, params: dict = None) -> ToolResult:
        """调用工具，统一返回 ToolResult"""
        t_start = time.time()
        params = params or {}

        tool = cls._tools.get(name)
        if tool is None:
            return ToolResult(
                ok=False,
                error={"code": "TOOL_NOT_FOUND", "message": f"Tool '{name}' not found"},
                latency_ms=(time.time() - t_start) * 1000,
            )

        try:
            data = tool(**params)
            return ToolResult(
                ok=True,
                data=data,
                latency_ms=(time.time() - t_start) * 1000,
            )
        except Exception as e:
            return ToolResult(
                ok=False,
                error={
                    "code": type(e).__name__.upper(),
                    "message": str(e),
                    "traceback": traceback.format_exc()[-500:],
                },
                latency_ms=(time.time() - t_start) * 1000,
            )

    @classmethod
    def list_tools(cls) -> list[dict]:
        """列出所有已注册工具"""
        return [
            {
                "name": name,
                "description": getattr(fn, "_tool_description", ""),
            }
            for name, fn in cls._tools.items()
        ]


# ── 注册最小工具集 ──────────────────────────────

@AgentToolRegistry.register("ingest_document", "导入文档到知识库")
def tool_ingest_document(filepath: str, tenant_id: str = "default") -> dict:
    from main import ingest_pdf
    doc_id = ingest_pdf(filepath, tenant_id)
    return {"document_id": doc_id, "filepath": filepath}


@AgentToolRegistry.register("search_knowledge", "语义搜索知识库")
def tool_search_knowledge(query: str, top_k: int = 5) -> dict:
    from plugins import get_embedder
    from retrieval import VectorStore
    from config import config

    embedder = get_embedder()
    store = VectorStore(config.get("storage", "db_path"))
    embedding = embedder.encode_query(query)
    hits = store.search(embedding, top_k=top_k)
    store.close()

    return {
        "results": [
            {"page": h.page, "score": h.score, "text": h.text[:500]}
            for h in hits
        ]
    }


@AgentToolRegistry.register("answer_question", "向知识库提问，返回答案+引用")
def tool_answer_question(question: str, user_id: str = "") -> dict:
    from qa.engine import QAEngine
    engine = QAEngine()
    user_ctx = {"user_id": user_id, "security_clearance": 3} if user_id else None
    result = engine.ask_v2(question, user_context=user_ctx)
    return {
        "answer": result["answer"],
        "confidence": result.get("confidence", 0),
        "citations": result.get("citations", []),
        "intent": result.get("intent", ""),
    }


@AgentToolRegistry.register("get_document_metadata", "获取文档元数据")
def tool_get_document_metadata(filename: str, tenant_id: str = "default") -> dict:
    from retrieval import VectorStore
    store = VectorStore()
    rows = store.conn.execute(
        "SELECT id, filename, page_count, total_chars, metadata, created_at "
        "FROM documents WHERE filename = ? AND tenant_id = ?",
        (filename, tenant_id),
    ).fetchall()
    store.close()

    if not rows:
        return {"found": False, "filename": filename}

    return {
        "found": True,
        "documents": [
            {"id": r[0], "filename": r[1], "page_count": r[2],
             "total_chars": r[3], "metadata": r[4], "created_at": r[5]}
            for r in rows
        ],
    }


@AgentToolRegistry.register("compare_evidence", "比较多个证据来源")
def tool_compare_evidence(entity_a: str, entity_b: str) -> dict:
    from qa.engine import QAEngine
    engine = QAEngine()
    result = engine.ask_v2(f"比较 {entity_a} 和 {entity_b} 的区别和联系")
    return {
        "entity_a": entity_a,
        "entity_b": entity_b,
        "answer": result["answer"],
        "citations": result.get("citations", []),
    }
