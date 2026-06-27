"""Tool Registry — 统一 Agent 工具抽象

所有 Agent 操作（搜索 / 问答 / 导入 / 评估）通过 Tool 接口暴露。
任何 Agent（Hermes / Claude / Codex / GPT）调用 Tool 而非直接调 Python 模块。

设计:
  - @tool 装饰器注册 Tool
  - ToolRegistry.run(name, **kwargs) 执行
  - 每个 Tool 有 name / description / input_schema / output_schema
"""
from typing import Any, Callable
from dataclasses import dataclass, field


@dataclass
class ToolDef:
    name: str
    description: str
    fn: Callable
    input_schema: dict = field(default_factory=dict)
    output_schema: dict = field(default_factory=dict)


class ToolRegistry:
    """全局工具注册表"""

    _tools: dict[str, ToolDef] = {}

    @classmethod
    def register(cls, name: str, description: str,
                 input_schema: dict = None, output_schema: dict = None):
        """装饰器：注册 Tool"""
        def decorator(fn):
            cls._tools[name] = ToolDef(
                name=name, description=description, fn=fn,
                input_schema=input_schema or {},
                output_schema=output_schema or {},
            )
            return fn
        return decorator

    @classmethod
    def run(cls, name: str, **kwargs) -> Any:
        """执行 Tool"""
        tool = cls._tools.get(name)
        if tool is None:
            raise ValueError(f"Tool not found: {name}. Available: {list(cls._tools.keys())}")
        return tool.fn(**kwargs)

    @classmethod
    def list_all(cls) -> list[dict]:
        return [{"name": t.name, "description": t.description,
                 "input_schema": t.input_schema} for t in cls._tools.values()]

    @classmethod
    def get_schema(cls, name: str) -> dict | None:
        t = cls._tools.get(name)
        return t.input_schema if t else None


# ── 注册核心 Tools ──────────────────────────────

@ToolRegistry.register("search", "语义搜索工程文档",
    {"query": "string", "top_k": "int=5"})
def tool_search(query: str, top_k: int = 5) -> list[dict]:
    from plugins import get_embedder
    from retrieval import VectorStore
    from config import config
    embedder = get_embedder()
    store = VectorStore(config.get("storage", "db_path"))
    hits = store.search(embedder.encode_query(query), top_k=top_k)
    store.close()
    return [{"page": h.page, "score": round(h.score, 4), "text": h.text[:500]} for h in hits]


@ToolRegistry.register("ask", "向知识库提问，返回答案+引用+置信度",
    {"question": "string"})
def tool_ask(question: str) -> dict:
    from qa.engine import QAEngine
    engine = QAEngine()
    return engine.ask_v2(question)


@ToolRegistry.register("ingest", "导入 PDF 到知识库",
    {"filepath": "string", "tenant_id": "string=default"})
def tool_ingest(filepath: str, tenant_id: str = "default") -> dict:
    import os
    if not os.path.exists(filepath):
        return {"error": f"File not found: {filepath}"}
    from main import ingest_pdf
    try:
        doc_id = ingest_pdf(filepath, tenant_id)
        return {"status": "ok", "document_id": doc_id}
    except Exception as e:
        return {"error": str(e)}


@ToolRegistry.register("status", "获取系统状态",
    {})
def tool_status() -> dict:
    from retrieval import VectorStore
    store = VectorStore()
    r = {
        "documents": store.conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0],
        "chunks": store.conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0],
        "qa_pairs": store.conn.execute("SELECT COUNT(*) FROM qa_pairs").fetchone()[0],
        "pending": store.conn.execute("SELECT COUNT(*) FROM unanswered_queue WHERE status='pending'").fetchone()[0],
    }
    store.close()
    return r


@ToolRegistry.register("compare", "比较两个实体或参数",
    {"entity_a": "string", "entity_b": "string"})
def tool_compare(entity_a: str, entity_b: str) -> dict:
    from qa.engine import QAEngine
    engine = QAEngine()
    question = f"比较 {entity_a} 和 {entity_b} 的区别和联系"
    return engine.ask_v2(question)


@ToolRegistry.register("citations", "查找指定话题的引用来源",
    {"topic": "string", "top_k": "int=5"})
def tool_citations(topic: str, top_k: int = 5) -> list[dict]:
    return tool_search(topic, top_k)


@ToolRegistry.register("evaluate", "运行评估",
    {"dataset_path": "string", "sample_size": "int=0"})
def tool_evaluate(dataset_path: str, sample_size: int = 0) -> dict:
    from evaluate import evaluate
    return evaluate(dataset_path, sample_size or None)


@ToolRegistry.register("category", "检测文档类别",
    {"text": "string"})
def tool_category(text: str) -> dict:
    from config.categorizer import detect_category
    cat = detect_category(text)
    return {"category": cat.category, "confidence": cat.confidence,
            "keywords": cat.matched_keywords}
