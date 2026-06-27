# EDIS Agent Integration Guide v1.0

> 本文档面向上游 Agent（Hermes / Claude / Cursor / Codex / GPT）对接开发者。  
> 读完本文档后，任何 Agent 都应能通过 MCP 或 Python SDK 调用 EDIS 的知识检索能力。

---

## 一、架构概览

```
┌─────────────────────────────────────────────┐
│  Agent Layer (Hermes / Claude / Cursor ...) │
├─────────────────────────────────────────────┤
│  MCP Server  │  Python SDK  │  CLI          │
├─────────────────────────────────────────────┤
│  Tool Registry (10 tools)                   │
├─────────────────────────────────────────────┤
│  QA Engine  │  Search  │  Cache  │  Cost    │
├─────────────────────────────────────────────┤
│  Plugin Registry (5 parsers, 3 LLM, 1 emb) │
├─────────────────────────────────────────────┤
│  SQLite + sqlite-vec (向量 + 元数据 + 记忆) │
└─────────────────────────────────────────────┘
```

---

## 二、三种接入方式

### 方式 1：MCP Server（推荐）

**支持平台：** Claude Desktop / Cursor / Codex / Gemini CLI

**配置：**
```json
{
  "mcpServers": {
    "edis": {
      "command": "D:\\GitHub\\self-media\\edis\\.venv\\Scripts\\python",
      "args": ["D:\\GitHub\\self-media\\edis\\mcp_server.py"]
    }
  }
}
```

**可用 Tools：**

| Tool | 参数 | 说明 |
|---|---|---|
| `edis_ask` | question: string | RAG 问答，返回答案+引用+置信度 |
| `edis_search` | query: string, top_k: int | 语义搜索，不调 LLM |
| `edis_ingest` | filepath: string | 导入文档到知识库 |
| `edis_status` | 无 | 系统状态：文档数/chunk数/QA对/队列 |
| `edis_compare` | entity_a: string, entity_b: string | 比较两个实体 |
| `edis_citations` | topic: string, top_k: int | 查找引用来源 |
| `edis_evaluate` | dataset_path: string | 运行评估 |
| `edis_category` | text: string | 检测文档类别 |

**示例调用（JSON-RPC）：**
```json
{"jsonrpc": "2.0", "method": "tools/call", "params": {
  "name": "edis_ask",
  "arguments": {"question": "控制阀总成的分解步骤？"}
}, "id": 1}
```

---

### 方式 2：Python SDK

```python
from qa.engine import QAEngine
from plugins import get_llm, get_embedder
from tools import ToolRegistry

# 初始化引擎
engine = QAEngine()

# 问答
result = engine.ask_v2("动臂油缸的规格参数？")
print(result["answer"])         # 答案
print(result["confidence"])     # 置信度 0-1
print(result["citations"])      # [{document, page, relevance}]
print(result["intent"])         # definition_query / parameter_query / ...

# 语义搜索
results = ToolRegistry.run("search", query="控制阀", top_k=5)
# → [{page, score, text}, ...]

# 换 LLM 提供商
llm = get_llm("openai", model="gpt-4o-mini")
engine = QAEngine(llm=llm)
```

---

### 方式 3：CLI

```bash
# 导入文档
python main.py --tenant client_a ingest "D:/docs/manual.pdf"

# 问答
python main.py --tenant client_a --v2 ask "什么是ONU?"

# 批量导入目录
python batch_ingest.py scan "D:/docs/pdfs/" --tenant client_a
python batch_ingest.py process --tenant client_a --workers 4
python batch_ingest.py status --tenant client_a
```

---

## 三、核心数据流

```
文件上传 → FileValidator (5关校验)
           ↓
     MetadataExtractor (提取元数据)
           ↓
     PluginRegistry.get("parser", "pymupdf").parse(filepath)
           ↓
     clean_pipeline → Chunker → Embedder.encode
           ↓
     VectorStore.insert (sqlite-vec)
           ↓
     用户问题 → QA Pair Registry 优先检索
           ↓ 未命中
     IntentClassifier → VectorStore.search → Evidence Fusion
           ↓
     LLM (DeepSeek/OpenAI/...) → 答案 + [Page X] 引用
```

---

## 四、已注册插件

### Parser（5 个）
| 名称 | 格式 | 依赖 |
|---|---|---|
| pymupdf | PDF | pymupdf (内置) |
| docx | DOCX | python-docx |
| markdown | MD | 无 |
| html | HTML | bs4 (可选) |
| text | TXT/CSV/JSON | 无 |

### LLM（3 个）
| 名称 | 模型默认值 | Base URL |
|---|---|---|
| deepseek | deepseek-chat | api.deepseek.com |
| openai | gpt-4o-mini | api.openai.com/v1 |
| minimax | abab6.5s-chat | api.minimax.chat/v1 |

### Embedding（1 个）
| 名称 | 维度 | 模型 |
|---|---|---|
| bge-large-zh | 1024 | BAAI/bge-large-zh-v1.5 |

---

## 五、多租户

所有操作通过 `tenant_id` 隔离：

```python
from config.tenant import set_current_tenant, tenant_context

# 方式1：全局设置
set_current_tenant("client_a")

# 方式2：上下文管理器
with tenant_context("client_b"):
    result = engine.ask_v2("问题")
```

CLI: `python main.py --tenant client_a ask "问题"`

---

## 六、成本追踪

```python
from operations import CostManager

cm = CostManager()
cm.record_llm("deepseek-chat", input_tokens=1500, output_tokens=300, latency_ms=1200)
print(cm.stats())  # → {total_calls, total_cost_usd, ...}
```

参考价格表：
| 模型 | Input \$/1M | Output \$/1M |
|---|---|---|
| deepseek-chat | \$0.14 | \$0.28 |
| gpt-4o-mini | \$0.15 | \$0.60 |
| gpt-4o | \$2.50 | \$10.00 |

---

## 七、扩展新功能

### 增加新 Parser
```python
from plugins import PluginRegistry
from interfaces import ParserInterface, ParsedDoc

@PluginRegistry.register("parser", "myformat")
class MyParser(ParserInterface):
    def parse(self, filepath): ...
    @classmethod
    def supports(cls, filepath): return filepath.endswith(".xyz")
```

### 增加新 LLM Provider
```python
@PluginRegistry.register("llm", "myllm")
class MyLLMPlugin(LLMInterface):
    def chat(self, messages, **kwargs): ...
    @property
    def model_name(self): return "my-model"
```

### 增加新 Tool
```python
from tools import ToolRegistry

@ToolRegistry.register("my_tool", "工具描述", {"param": "string"})
def my_tool(param: str) -> dict:
    ...
```

---

## 八、评估体系

```bash
python evaluate.py "path/to/answers.md"        # 全量评估
python evaluate.py "path/to/answers.md" 20     # 抽样20题
python -m pytest tests/ -v                      # 单元测试 (26 tests)
```

输出指标：
- **Recall@5/10**: 检索召回率
- **Faithfulness**: 答案真实基于 PDF 的比例

---

## 九、文件结构速查

```
edis/
├── interfaces/       # 9个ABC抽象
├── adapters/         # 6个具体实现
├── plugins/          # 插件注册表
├── tools/            # 10个统一Tool
├── qa/               # QAEngine v3
├── mcp_server.py     # MCP入口
├── main.py           # CLI入口
├── metadata/         # 元数据提取
├── validator/        # 文件校验
├── parsers/          # 多格式Parser
├── cache/            # LRU缓存
├── operations/       # 成本+版本追踪
├── config/           # 配置+租户+prompts
├── context_builder/  # 上下文组装
├── extensions/       # 扩展系统
├── tests/            # 26个pytest
└── setup.py          # pip install edis
```

---

## 十、MCP 配置示例

### Claude Desktop
编辑 `%APPDATA%\Claude\claude_desktop_config.json`:
```json
{"mcpServers": {"edis": {"command": "python", "args": ["mcp_server.py"]}}}
```

### Cursor
编辑 `.cursor/mcp.json`:
```json
{"mcpServers": {"edis": {"command": "python", "args": ["mcp_server.py"]}}}
```

### Codex
编辑 `~/.codex/config.toml`:
```toml
[mcp_servers.edis]
command = "python"
args = ["mcp_server.py"]
```

### Gemini CLI
编辑 `~/.gemini/settings.json`:
```json
{"mcpServers": {"edis": {"command": "python", "args": ["mcp_server.py"]}}}
```
