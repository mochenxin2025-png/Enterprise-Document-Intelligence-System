"""Agent Tool Layer — 统一工具接口，标准化输入输出

让 EDIS 从"内部模块堆叠"升级为"可被外部 Agent 调用的工具系统"。

设计:
  - ToolSchema: 统一 {ok, data, error} 输出格式
  - ToolRegistry (已有): 装饰器注册 + 动态调用
  - 与现有 tools/__init__.py 兼容 — 旧工具通过 wrap 适配
"""

import traceback
import time
from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class ToolResult:
    """统一工具返回格式"""
    ok: bool
    data: Any = None
    error: dict = field(default_factory=dict)
    latency_ms: float = 0.0

    @staticmethod
    def success(data: Any, latency_ms: float = 0) -> "ToolResult":
        return ToolResult(ok=True, data=data, latency_ms=latency_ms)

    @staticmethod
    def fail(code: str, message: str) -> "ToolResult":
        return ToolResult(ok=False, error={"code": code, "message": message})

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "data": self.data,
            "error": self.error if not self.ok else None,
            "latency_ms": self.latency_ms,
        }


# ── Tool Schema Wrapper ─────────────────────────

def wrap_tool_result(fn: Callable) -> Callable:
    """将现有工具函数包装为统一 ToolResult 格式"""
    def wrapper(*args, **kwargs):
        t0 = time.time()
        try:
            result = fn(*args, **kwargs)
            return ToolResult.success(
                result, latency_ms=(time.time() - t0) * 1000
            )
        except Exception as e:
            return ToolResult.fail(
                code=type(e).__name__.upper(),
                message=str(e),
            )
    wrapper.__name__ = fn.__name__
    wrapper.__doc__ = fn.__doc__
    return wrapper


# ── Agent Tool Registry ─────────────────────────

class AgentToolRegistry:
    """面向 Agent 的工具注册表 — 统一输出格式"""

    _tools: dict[str, dict] = {}

    @classmethod
    def register(cls, name: str, description: str,
                 input_schema: dict = None):
        def decorator(fn):
            cls._tools[name] = {
                "name": name,
                "description": description,
                "input_schema": input_schema or {},
                "fn": wrap_tool_result(fn),
            }
            return fn
        return decorator

    @classmethod
    def run(cls, name: str, **kwargs) -> ToolResult:
        tool = cls._tools.get(name)
        if not tool:
            return ToolResult.fail("NOT_FOUND",
                f"Tool '{name}' not found. Available: {list(cls._tools.keys())}")
        return tool["fn"](**kwargs)

    @classmethod
    def list_all(cls) -> list[dict]:
        return [
            {"name": t["name"], "description": t["description"],
             "input_schema": t["input_schema"]}
            for t in cls._tools.values()
        ]


# ── Register Core Agent Tools ────────────────────

@AgentToolRegistry.register(
    "ingest_document", "导入文档到知识库",
    {"filepath": "string", "tenant_id": "string=default"})
def agent_ingest(filepath: str, tenant_id: str = "default") -> dict:
    from main import ingest_pdf
    doc_id = ingest_pdf(filepath, tenant_id)
    return {"document_id": doc_id, "status": "ingested"}


@AgentToolRegistry.register(
    "search_knowledge", "语义搜索知识库",
    {"query": "string", "top_k": "int=5"})
def agent_search(query: str, top_k: int = 5) -> dict:
    from tools import tool_search
    results = tool_search(query, top_k)
    return {"results": results, "count": len(results)}


@AgentToolRegistry.register(
    "answer_question", "基于知识库回答问题",
    {"question": "string"})
def agent_answer(question: str) -> dict:
    from qa.engine import QAEngine
    engine = QAEngine()
    result = engine.ask_v2(question)
    return result


@AgentToolRegistry.register(
    "get_document_metadata", "获取文档元数据",
    {"doc_id": "string"})
def agent_metadata(doc_id: str) -> dict:
    from retrieval import VectorStore
    store = VectorStore()
    row = store.conn.execute(
        "SELECT filename, page_count, total_chars, metadata, created_at "
        "FROM documents WHERE id=?", (doc_id,)).fetchone()
    store.close()
    if not row:
        return {}
    return {"filename": row[0], "page_count": row[1],
            "total_chars": row[2], "created_at": row[4]}


@AgentToolRegistry.register(
    "compare_evidence", "比较两个实体的证据",
    {"entity_a": "string", "entity_b": "string"})
def agent_compare(entity_a: str, entity_b: str) -> dict:
    from tools import tool_compare
    return tool_compare(entity_a, entity_b)


@AgentToolRegistry.register(
    "system_status", "获取系统状态",
    {})
def agent_status() -> dict:
    from tools import tool_status
    return tool_status()
