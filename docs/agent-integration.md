# EDIS Agent 集成指南

## 接入方式

| 方式 | 适用场景 | 状态 |
|---|---|---|
| **Agent Tool API** | 所有 Agent 的统一入口 | ✅ v1.2 |
| HTTP Server | 外部 Agent 通过 HTTP 调用 | ✅ v1.3 |
| MCP Server | Claude Desktop / Cursor 等 | ✅ v1.0 |
| Python SDK | 直接 import 调用 | ✅ v1.0 |

---

## Agent Tool API

所有工具统一通过 `agent.AgentToolRegistry` 调用，返回格式统一为：

```json
// 成功
{"ok": true, "data": {...}, "error": null, "latency_ms": 123.4}

// 失败
{"ok": false, "data": null, "error": {"code": "TIMEOUT", "message": "..."}}
```

### 可用工具（6个）

| 工具 | 参数 | Agent 类型 |
|---|---|---|
| `ingest_document` | filepath, tenant_id | coding, workflow |
| `search_knowledge` | query, top_k | 全部 |
| `answer_question` | question | chat, batch, workflow |
| `get_document_metadata` | doc_id | 全部 |
| `compare_evidence` | entity_a, entity_b | chat, batch, workflow |
| `system_status` | — | 全部 |

---

## Agent 类型与工具权限

| Agent 类型 | 可用工具 | 典型场景 |
|---|---|---|
| **Chat** | answer, search, compare, metadata, status | 对话问答 |
| **Coding** | ingest, search, metadata, status | 批量处理 |
| **Batch** | answer, search, compare, metadata | 批量问答 |
| **Workflow** | 全部 6 个 | 企业工单 |

---

## HTTP API

```bash
# 启动
python agent/http_server.py

# 列出工具
curl http://127.0.0.1:8765/tools

# 调用工具
curl -X POST http://127.0.0.1:8765/tools/search_knowledge \
  -H "Content-Type: application/json" \
  -d '{"query": "MQTT配置", "top_k": 5}'

# 健康检查
curl http://127.0.0.1:8765/health
```

---

## Python SDK

```python
from agent import AgentToolRegistry

# 直接调用
result = AgentToolRegistry.run("search_knowledge", query="MQTT", top_k=3)
print(result.ok, result.data)

# 带 Agent 类型限制
from agent.adapters import ChatAgentAdapter, AgentContext

ctx = AgentContext(agent_id="agent-1", agent_type="chat")
result = ChatAgentAdapter.run("answer_question", ctx,
                               question="控制阀规格？")
```

---

## MCP Server

已有 `mcp_server.py`，9 个工具暴露为 MCP tools。配置方式见 `AGENTS.md`。

## 后续扩展

- [ ] HTTP Server 替换为 FastAPI（生产环境）
- [ ] JWT 认证中间件集成到 HTTP Server
- [ ] Tool 调用审计日志
- [ ] rate limiting per agent
