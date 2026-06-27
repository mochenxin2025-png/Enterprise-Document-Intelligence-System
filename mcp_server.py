"""MCP Server — Model Context Protocol over stdio

让 Cursor / Claude Desktop / Codex / Gemini CLI 直接调 EDIS 检索能力

启动:
  python mcp_server.py
  # 或通过 Claude Desktop / Cursor 配置自动启动

协议: JSON-RPC 2.0 over stdin/stdout
规范: https://modelcontextprotocol.io
"""
import sys
import json
import traceback
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent))


class MCPServer:
    """轻量 MCP 服务器 — JSON-RPC 2.0 over stdio"""

    def __init__(self, name: str = "edis", version: str = "1.0.0"):
        self.name = name
        self.version = version
        self._tools: dict[str, dict] = {}
        self._handlers: dict[str, callable] = {}
        self._initialized = False

        # 注册内置 tools/list 和 tools/call
        self._handlers["tools/list"] = self._handle_tools_list
        self._handlers["tools/call"] = self._handle_tools_call
        self._handlers["initialize"] = self._handle_initialize

    def tool(self, name: str, description: str, parameters: dict):
        """装饰器：注册 MCP Tool"""
        def decorator(fn):
            self._tools[name] = {
                "name": name,
                "description": description,
                "inputSchema": {
                    "type": "object",
                    "properties": parameters,
                    "required": list(parameters.keys()),
                },
            }
            self._handlers[name] = fn
            return fn
        return decorator

    def run(self):
        """启动 stdio 循环"""
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                request = json.loads(line)
                response = self._dispatch(request)
                if response is not None:
                    sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
                    sys.stdout.flush()
            except Exception as e:
                err = {
                    "jsonrpc": "2.0",
                    "id": request.get("id") if isinstance(request, dict) else None,
                    "error": {"code": -32603, "message": str(e)},
                }
                sys.stdout.write(json.dumps(err) + "\n")
                sys.stdout.flush()

    def _dispatch(self, request: dict) -> dict | None:
        method = request.get("method", "")
        params = request.get("params", {})
        req_id = request.get("id")

        # notifications (no id) don't get a response
        if method == "notifications/initialized":
            self._initialized = True
            return None

        handler = self._handlers.get(method)
        if handler is None:
            return {"jsonrpc": "2.0", "id": req_id,
                    "error": {"code": -32601, "message": f"Method not found: {method}"}}

        try:
            if method == "tools/call":
                result = handler(params)
            elif method == "initialize":
                result = handler(params)
            elif method == "tools/list":
                result = handler()
            else:
                result = handler(**params.get("arguments", {}))
            return {"jsonrpc": "2.0", "id": req_id, "result": result}
        except Exception as e:
            return {"jsonrpc": "2.0", "id": req_id,
                    "error": {"code": -32000, "message": str(e)}}

    def _handle_initialize(self, params: dict) -> dict:
        return {
            "protocolVersion": "2024-11-05",
            "serverInfo": {"name": self.name, "version": self.version},
            "capabilities": {"tools": {}},
        }

    def _handle_tools_list(self) -> dict:
        from tools import ToolRegistry
        return {"tools": [
            {"name": t["name"], "description": t["description"],
             "inputSchema": {"type": "object", "properties": {
                 k: {"type": "string" if "string" in str(v) else "integer", "description": str(v)}
                 for k, v in t["input_schema"].items()
             }, "required": list(t["input_schema"].keys())}}
            for t in ToolRegistry.list_all()
        ]}

    def _handle_tools_call(self, params: dict) -> dict:
        from tools import ToolRegistry
        tool_name = params.get("name", "")
        arguments = params.get("arguments", {})
        handler = self._handlers.get(tool_name)
        if handler:
            result = handler(**arguments)
        else:
            result = ToolRegistry.run(tool_name, **arguments)
        return {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False) if not isinstance(result, str) else result}]}


# ── 创建 MCP Server 实例 ────────────────────────

mcp = MCPServer("edis", "1.0.0")


# ── 注册 Tools ──────────────────────────────────

@mcp.tool("edis_ask", "向工程文档知识库提问，返回基于 PDF 上下文的答案",
          {"question": {"type": "string", "description": "要提问的问题"}})
def tool_ask(question: str) -> str:
    from qa.engine import QAEngine
    engine = QAEngine()
    result = engine.ask_v2(question)
    return json.dumps({
        "answer": result["answer"],
        "confidence": result.get("confidence", 0),
        "intent": result.get("intent", "unknown"),
        "citations": result.get("citations", []),
    }, ensure_ascii=False)


@mcp.tool("edis_search", "语义搜索工程文档，返回匹配的文本片段（不调 LLM）",
          {"query": {"type": "string", "description": "搜索关键词或问题"},
           "top_k": {"type": "integer", "description": "返回结果数，默认 5"}})
def tool_search(query: str, top_k: int = 5) -> str:
    from plugins import get_embedder
    from retrieval import VectorStore
    from config import config

    embedder = get_embedder()
    store = VectorStore(config.get("storage", "db_path"))
    embedding = embedder.encode_query(query)
    hits = store.search(embedding, top_k=top_k)
    store.close()

    results = [{"page": h.page, "score": round(h.score, 4), "text": h.text[:500]}
               for h in hits]
    return json.dumps(results, ensure_ascii=False)


@mcp.tool("edis_status", "获取系统状态：已索引文档数、Chunk 数、QA Pair 数、待处理队列",
          {})
def tool_status() -> str:
    from retrieval import VectorStore
    store = VectorStore()
    docs = store.conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
    chunks = store.conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
    emb = store.conn.execute("SELECT COUNT(*) FROM chunk_embeddings").fetchone()[0]
    qa = store.conn.execute("SELECT COUNT(*) FROM qa_pairs").fetchone()[0]
    queue = store.conn.execute("SELECT COUNT(*) FROM unanswered_queue WHERE status='pending'").fetchone()[0]
    store.close()

    return json.dumps({
        "documents": docs,
        "chunks": chunks,
        "embeddings": emb,
        "qa_pairs": qa,
        "pending_questions": queue,
    }, ensure_ascii=False)


@mcp.tool("edis_ingest", "导入 PDF 文档到知识库",
          {"filepath": {"type": "string", "description": "PDF 文件绝对路径"}})
def tool_ingest(filepath: str) -> str:
    import os
    if not os.path.exists(filepath):
        return json.dumps({"error": f"File not found: {filepath}"})

    # 复用主流程
    from main import ingest_pdf
    try:
        doc_id = ingest_pdf(filepath)
        return json.dumps({"status": "ok", "document_id": doc_id})
    except Exception as e:
        return json.dumps({"error": str(e)})


# ── 启动 ────────────────────────────────────────

if __name__ == "__main__":
    mcp.run()
