"""Agent Adapters — 不同 Agent 类型的调用适配

Chat / Coding / Batch / Workflow 四种 Agent 通过不同工具集和调度方式接入。
"""

from dataclasses import dataclass, field
from typing import Optional
from agent import AgentToolRegistry, ToolResult


@dataclass
class AgentContext:
    """Agent 调用上下文"""
    agent_id: str
    agent_type: str          # "chat" | "coding" | "batch" | "workflow"
    user_id: str = ""
    tenant_id: str = "default"
    run_id: str = ""


# ── Chat Agent Adapter ──────────────────────────

class ChatAgentAdapter:
    """Chat Agent: 文档问答、检索式对话、总结解释

    适合 ChatGPT / Claude / Gemini 等对话型 Agent。
    """

    AVAILABLE_TOOLS = [
        "answer_question", "search_knowledge",
        "compare_evidence", "get_document_metadata", "system_status",
    ]

    @staticmethod
    def run(tool_name: str, ctx: AgentContext, **params) -> ToolResult:
        if tool_name not in ChatAgentAdapter.AVAILABLE_TOOLS:
            return ToolResult.fail("FORBIDDEN",
                f"Tool '{tool_name}' not available for chat agent")
        return AgentToolRegistry.run(tool_name, **params)

    @staticmethod
    def list_tools() -> list[str]:
        return ChatAgentAdapter.AVAILABLE_TOOLS


# ── Coding Agent Adapter ────────────────────────

class CodingAgentAdapter:
    """Coding Agent: 批量处理文件、修改配置、自动生成

    适合 Cursor / Codex / OpenHands 等编码型 Agent。
    """

    AVAILABLE_TOOLS = [
        "ingest_document", "search_knowledge",
        "get_document_metadata", "system_status",
    ]

    @staticmethod
    def run(tool_name: str, ctx: AgentContext, **params) -> ToolResult:
        if tool_name not in CodingAgentAdapter.AVAILABLE_TOOLS:
            return ToolResult.fail("FORBIDDEN",
                f"Tool '{tool_name}' not available for coding agent")
        return AgentToolRegistry.run(tool_name, **params)

    @staticmethod
    def list_tools() -> list[str]:
        return CodingAgentAdapter.AVAILABLE_TOOLS


# ── Batch QA Agent Adapter ──────────────────────

class BatchAgentAdapter:
    """Batch Agent: 批量问答、质检、审阅

    适合需要批量处理大量问题的场景。
    """

    AVAILABLE_TOOLS = [
        "answer_question", "search_knowledge",
        "compare_evidence", "get_document_metadata",
    ]

    @staticmethod
    def run(tool_name: str, ctx: AgentContext, **params) -> ToolResult:
        if tool_name not in BatchAgentAdapter.AVAILABLE_TOOLS:
            return ToolResult.fail("FORBIDDEN",
                f"Tool '{tool_name}' not available for batch agent")
        return AgentToolRegistry.run(tool_name, **params)

    @staticmethod
    def list_tools() -> list[str]:
        return BatchAgentAdapter.AVAILABLE_TOOLS


# ── Workflow Agent Adapter ──────────────────────

class WorkflowAgentAdapter:
    """Workflow Agent: 审批流程、企业知识工单

    适合需要多步骤审批场景。
    """

    AVAILABLE_TOOLS = [
        "answer_question", "search_knowledge",
        "compare_evidence", "get_document_metadata",
        "ingest_document", "system_status",
    ]

    @staticmethod
    def run(tool_name: str, ctx: AgentContext, **params) -> ToolResult:
        if tool_name not in WorkflowAgentAdapter.AVAILABLE_TOOLS:
            return ToolResult.fail("FORBIDDEN",
                f"Tool '{tool_name}' not available for workflow agent")
        return AgentToolRegistry.run(tool_name, **params)

    @staticmethod
    def list_tools() -> list[str]:
        return WorkflowAgentAdapter.AVAILABLE_TOOLS


# ── Adapter Registry ────────────────────────────

def get_adapter(agent_type: str):
    """根据 Agent 类型获取对应适配器"""
    adapters = {
        "chat": ChatAgentAdapter,
        "coding": CodingAgentAdapter,
        "batch": BatchAgentAdapter,
        "workflow": WorkflowAgentAdapter,
    }
    return adapters.get(agent_type)
