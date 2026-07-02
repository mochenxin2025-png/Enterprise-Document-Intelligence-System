# EDIS Agent 集成指南

## 接入方式

### 方式 1: HTTP API（推荐）

```bash
# 启动 HTTP Server
python -m agent.http_server --port 8765

# 列出工具
curl http://localhost:8765/tools/list

# 调用工具
curl -X POST http://localhost:8765/tools/call \
  -H "Content-Type: application/json" \
  -d '{"name":"answer_question","params":{"question":"MQTT如何配置？"}}'
```

### 方式 2: Python SDK

```python
from agent import AgentToolRegistry

# 调用工具
result = AgentToolRegistry.call("answer_question", {
    "question": "MQTT如何配置？",
    "user_id": "alice",
})

print(result.ok)       # True/False
print(result.data)     # {"answer": "...", "citations": [...]}
print(result.error)    # None or {"code": "...", "message": "..."}
```

### 方式 3: Agent Adapter

```python
from agent.adapters import ChatAgentAdapter

adapter = ChatAgentAdapter("http://localhost:8765")
result = adapter.ask("MQTT如何配置？", user_id="alice")
```

## 工具列表

| 工具 | 参数 | 返回 |
|---|---|---|
| `ingest_document` | filepath, tenant_id | {document_id} |
| `search_knowledge` | query, top_k | {results: [{page, score, text}]} |
| `answer_question` | question, user_id | {answer, confidence, citations, intent} |
| `get_document_metadata` | filename, tenant_id | {found, documents: [...]} |
| `compare_evidence` | entity_a, entity_b | {answer, citations} |

## 统一返回格式

```json
{
  "ok": true,
  "data": { ... },
  "error": null,
  "latency_ms": 234.5
}
```

失败时:
```json
{
  "ok": false,
  "data": null,
  "error": {"code": "TIMEOUT", "message": "task exceeded 60 seconds"},
  "latency_ms": 60001.0
}
```

## Agent 类型适配

| Agent 类型 | 适配器 | 适用场景 |
|---|---|---|
| Chat | `ChatAgentAdapter` | ChatGPT, Claude, Gemini — 问答/搜索 |
| Coding | `CodingAgentAdapter` | Cursor, Codex — 批处理/导入 |
| Batch | `BatchAgentAdapter` | 批量问答/质检 |
| Workflow | `WorkflowAgentAdapter` | 审批/对比/工单 |
