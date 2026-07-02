"""Agent Adapter Layer — 不同 Agent 类型通过不同适配器接入 EDIS

Chat Agent:    文档问答、检索式对话（ChatGPT, Claude, Gemini）
Coding Agent:  批量处理、仓库改造（Cursor, Codex, OpenHands）
Batch Agent:   批量问答、自动质检
Workflow Agent:审批流程、工单系统
"""

from . import AgentToolRegistry
from .http_server import run_server


class AgentAdapter:
    """适配器基类"""

    def __init__(self, base_url: str = "http://127.0.0.1:8765"):
        self.base_url = base_url

    def call_tool(self, name: str, params: dict) -> dict:
        """调用工具（默认通过 HTTP，子类可 override）"""
        import urllib.request, json

        data = json.dumps({"name": name, "params": params}).encode()
        req = urllib.request.Request(
            f"{self.base_url}/tools/call",
            data=data,
            headers={"Content-Type": "application/json"},
        )
        resp = urllib.request.urlopen(req)
        return json.loads(resp.read())


class ChatAgentAdapter(AgentAdapter):
    """对话型 Agent 适配器 — 文档问答、检索式对话

    适用于: ChatGPT, Claude, Gemini
    """

    def ask(self, question: str, user_id: str = "") -> dict:
        return self.call_tool("answer_question", {
            "question": question, "user_id": user_id,
        })

    def search(self, query: str, top_k: int = 5) -> dict:
        return self.call_tool("search_knowledge", {
            "query": query, "top_k": top_k,
        })


class CodingAgentAdapter(AgentAdapter):
    """编程型 Agent 适配器 — 批量处理文件、修改配置

    适用于: Cursor, Codex, OpenHands
    """

    def ingest(self, filepath: str, tenant_id: str = "default") -> dict:
        return self.call_tool("ingest_document", {
            "filepath": filepath, "tenant_id": tenant_id,
        })

    def get_metadata(self, filename: str) -> dict:
        return self.call_tool("get_document_metadata", {
            "filename": filename,
        })


class BatchAgentAdapter(AgentAdapter):
    """批量 Agent 适配器 — 批量问答、自动质检"""

    def ask_batch(self, questions: list[str], user_id: str = "") -> list[dict]:
        results = []
        for q in questions:
            r = self.call_tool("answer_question", {
                "question": q, "user_id": user_id,
            })
            results.append(r)
        return results

    def search_batch(self, queries: list[str], top_k: int = 5) -> list[dict]:
        results = []
        for q in queries:
            r = self.call_tool("search_knowledge", {
                "query": q, "top_k": top_k,
            })
            results.append(r)
        return results


class WorkflowAgentAdapter(AgentAdapter):
    """工作流 Agent 适配器 — 审批流程、企业知识工作流"""

    def compare(self, entity_a: str, entity_b: str) -> dict:
        return self.call_tool("compare_evidence", {
            "entity_a": entity_a, "entity_b": entity_b,
        })
