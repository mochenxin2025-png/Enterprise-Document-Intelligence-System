[![English](https://img.shields.io/badge/English-README-blue)](README.md)

# 企业文档智能系统 (EDIS)

> **以 Agent 为核心的工程文档智能框架**  
> 将大型工程文档转化为可检索、可引用、可评估的知识库。

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-MIT-green)](LICENSE)
[![Tests](https://img.shields.io/badge/tests-26%20passed-brightgreen)](tests/)
[![MCP](https://img.shields.io/badge/MCP-Ready-purple)](mcp_server.py)

---

## EDIS 是什么？

EDIS（企业文档智能系统，**E**nterprise **D**ocument **I**ntelligence **S**ystem）是一个**本地优先、Agent 优先**的工程文档智能框架。它导入 PDF、DOCX、Markdown、HTML 等格式文件，经过解析、清洗、本地向量化（BGE），通过 MCP / Python SDK / CLI 三通道暴露知识检索能力，使任何 AI Agent 都能查询你的文档。

EDIS **不是聊天机器人**，而是多个 Agent 和 LLM 共享的知识基础设施。

---

## 快速开始

```bash
git clone https://github.com/mochenxin2025-png/edis.git
cd edis
pip install -e .

# 导入文档
python main.py ingest 你的文档.pdf

# 提问
python main.py --v2 ask "控制阀总成的分解步骤是什么？"

# 评估
python evaluate.py 答案文件.md
```

---

## 架构

```
┌──────────────────────────────────────────────────────┐
│  Agent 层 (Hermes / Claude / Cursor / GPT / ...)     │
├──────────────────────────────────────────────────────┤
│  MCP Server         Python SDK            CLI         │
├──────────────────────────────────────────────────────┤
│          工具注册中心 (10 个统一工具)                  │
├──────────────────────────────────────────────────────┤
│  QA引擎  │  检索  │  融合  │  缓存  │  成本统计       │
├──────────────────────────────────────────────────────┤
│  插件注册表  (6 解析器 · 3 LLM · 1 向量模型)         │
├──────────────────────────────────────────────────────┤
│     SQLite + sqlite-vec  (向量 + 元数据 + 记忆)       │
└──────────────────────────────────────────────────────┘
```

**知识管线：**  
`上传 → 文件校验 → 元数据提取 → 解析 → 清洗 → 分块 → 向量化 → 入库 → 检索`

**问答管线：**  
`问题 → QA对优先检索 → 意图分类 → 语义检索 → 证据融合 → 上下文构建 → LLM → 答案+引用 [N, Page X]`

---

## 支持的文件类型

| 格式 | 解析器 | 状态 |
|---|---|---|
| PDF | pymupdf | ✅ 内置 |
| DOCX | python-docx | ✅ 插件 |
| Markdown | stdlib | ✅ 插件 |
| HTML | bs4 (可选) | ✅ 插件 |
| TXT / CSV / JSON / XML | stdlib | ✅ 插件 |
| 图片 (OCR) | PaddleOCR | ✅ 插件 |

---

## LLM 提供商

| 提供商 | 模型 | 配置 |
|---|---|---|
| DeepSeek | deepseek-chat | `$DEEPSEEK_API_KEY` |
| OpenAI | gpt-4o-mini | `$OPENAI_API_KEY` |
| MiniMax | abab6.5s-chat | `$MINIMAX_API_KEY` |

切换方式：`get_llm("openai")` 或修改 MCP 配置。

---

## 核心功能

- ✅ **完整检索管线** — 解析→清洗→分块→向量化→检索→融合→回答
- ✅ **MCP 原生支持** — 适配 Claude Desktop / Cursor / Codex / Gemini CLI
- ✅ **多租户** — 文档、QA对、记忆均按租户隔离
- ✅ **QA Pair 知识补丁** — 人工录入的问答对优先匹配，零 API 消耗
- ✅ **待解决问题池** — 系统无法回答的问题自动入池等待运营处理
- ✅ **10 个统一工具** — search / ask / ingest / compare / citations / evaluate / category ...
- ✅ **插件系统** — 换 LLM、换向量模型、换解析器不改核心代码
- ✅ **Prompt 注册表** — 版本化、意图自适应的 Prompt 模板（7 模板 / 8 版本）
- ✅ **上下文构建器** — 去重 + 截断 + Token 预算控制
- ✅ **扩展系统** — 通过 entry_points 实现 pip-installable 扩展
- ✅ **成本管理器** — 按模型统计 Token 消耗和费用
- ✅ **LRU 缓存** — 答案缓存 30 分钟 + 向量缓存 1 小时
- ✅ **评估体系** — Recall@K + Faithfulness LLM 评分

---

## 环境要求

| 资源 | 最低 | 推荐 |
|---|---|---|
| CPU | 4 核 | 8+ 核 |
| 内存 | 8 GB | 16 GB |
| 磁盘 | 5 GB | 20 GB |
| GPU | **不需要** | 不需要 |
| Python | 3.10+ | 3.11 |

**零外部服务依赖。** SQLite + 本地 CPU 向量化即可跑通 Phase 1-3 全部功能。

---

## 评估基线 (PC200-6 装修手册, 341 页, 200 题)

| 指标 | Phase 1 | Phase 2 |
|---|---|---|
| Recall@5 | 100% | 100% |
| Faithfulness | 21% | 63.5% |

---

## Agent 接入

### MCP Server

```json
{
  "mcpServers": {
    "edis": {
      "command": "python", "args": ["mcp_server.py"]
    }
  }
}
```

### Python SDK

```python
from qa.engine import QAEngine
engine = QAEngine()
result = engine.ask_v2("动臂油缸的规格参数？")
print(result["answer"], result["citations"])
```

详见 [AGENTS.md](AGENTS.md) 完整对接文档。

---

## 项目结构

```
edis/
├── interfaces/       # 9 个 ABC 抽象接口
├── adapters/         # 6 个具体实现
├── plugins/          # 插件注册表
├── tools/            # 10 个统一工具
├── qa/               # QA 引擎 v3
├── mcp_server.py     # MCP 入口
├── main.py           # CLI 入口
├── metadata/         # 元数据提取与存储
├── validator/        # 文件五道关卡校验
├── parsers/          # 多格式解析器
├── cache/            # LRU 双层缓存
├── operations/       # 成本追踪 + 向量版本管理
├── config/           # 配置 + 租户 + Prompt 模板
├── context_builder/  # 上下文组装
├── extensions/       # 扩展系统
├── tests/            # 26 个 pytest 测试
└── setup.py          # pip install edis
```

---

## 开源协议

MIT — 详见 [LICENSE](LICENSE)。
