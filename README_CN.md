[![English](https://img.shields.io/badge/English-README-blue)](README.md)

# 企业文档智能系统 (EDIS)

> **面向 Agent 的企业文档智能框架**  
> 将大规模工程文档转化为可搜索、可引用、可评估的知识库。  
> EDIS = **E**nterprise **D**ocument **I**ntelligence **S**ystem（企业文档智能系统）。

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-MIT-green)](LICENSE)
[![Tests](https://img.shields.io/badge/tests-59%20passed-brightgreen)](tests/)
[![MCP](https://img.shields.io/badge/MCP-Ready-purple)](mcp_server.py)
[![HTTP](https://img.shields.io/badge/HTTP_API-8765-orange)](agent/http_server.py)
[![Platform](https://img.shields.io/badge/platform-Win%20%7C%20Mac%20%7C%20Linux-lightgrey)](docs/platform-compatibility.md)

---

## EDIS 是什么？

EDIS 是一个**本地优先、Agent 优先**的企业文档智能框架。导入 PDF、DOCX、Markdown、HTML 等格式文档，经过解析、清洗、分块、语义向量化后存入本地知识库，通过 MCP / HTTP API / Python SDK / CLI 对外暴露检索能力。

EDIS **不是聊天机器人**，而是多个 Agent 和 LLM 共享的知识基础设施。

---

## 快速开始

```bash
# 跨平台一键安装
# Windows:  .\scripts\install_windows.ps1
# macOS:    bash scripts/install_macos.sh
# Linux:    bash scripts/install_linux.sh

# 或手动安装:
git clone https://github.com/mochenxin2025-png/Enterprise-Document-Intelligence-System.git
cd edis
pip install uv
uv pip install -r requirements-base.txt -r requirements-windows.txt

# 导入文档
python main.py ingest your-doc.pdf

# 提问
python main.py --v2 ask "控制阀总成的分解步骤？"

# HTTP API 模式
python -m agent.http_server --port 8765
curl -X POST http://localhost:8765/tools/call \
  -d '{"name":"answer_question","params":{"question":"MQTT如何配置？"}}'
```

---

## 架构

```
┌──────────────────────────────────────────────────────────────┐
│         Agent 层 (Hermes / Claude / Cursor / GPT)            │
├──────────────────────────────────────────────────────────────┤
│  MCP Server      HTTP API (8765)      CLI      Python SDK    │
├──────────────────────────────────────────────────────────────┤
│          Agent Tool Registry (5 tools, {ok,data,error})      │
├──────────────────────────────────────────────────────────────┤
│  安全 L1-L5: 租户 → 权限 → 检索前过滤 → 二次校验 → 审计        │
├──────────────────────────────────────────────────────────────┤
│  QA Engine v4.0: QueryRewrite → Intent → ParentDoc → Rerank  │
│  ModalityRouter (text/table/figure/diagram)                  │
├──────────────────────────────────────────────────────────────┤
│  Agent Runtime: JobManager · Scheduler · TimeoutGuard · Merge│
├──────────────────────────────────────────────────────────────┤
│  Knowledge Objects: TextBlock · TableBlock · FigureBlock ... │
├──────────────────────────────────────────────────────────────┤
│  Auth: JWT · Firebase · Local (bcrypt/pbkdf2)               │
├──────────────────────────────────────────────────────────────┤
│  数据管线: Parser(6) → Cleaner → Chunker → Embedder           │
│  混合检索: Vector(sqlite-vec) + BM25                          │
├──────────────────────────────────────────────────────────────┤
│  SQLite + sqlite-vec  ·  平台适配 (Win/Mac/Linux)             │
└──────────────────────────────────────────────────────────────┘
```

**查询管线 (v4.0):**  
`问题 → QueryRewrite → QA Pair → 意图分类 → 父文档检索 → 精排 → L4校验 → 上下文组装 → LLM → L5脱敏 → 审计`

---

## 核心功能

### 基础 RAG
- ✅ 完整管线：解析 → 清洗 → 分块 → 向量化 → 检索 → 融合 → 回答
- ✅ **父文档检索** — 解决 Chunk 孤岛（摘要占 TopK，答案排不上）
- ✅ **启发式 + LLM 精排** — 关键词重叠、多样性、位置加权
- ✅ **混合检索** — 向量 (sqlite-vec) + 关键词 (BM25)
- ✅ **查询改写** — 多轮对话指代消解（"它"→"Nginx过滤规则"）
- ✅ **QA Pair 知识补丁** + **待答队列** + **Bad Case 数据库**

### 企业安全 (L1-L5)
- ✅ **L1 租户隔离** — SQL 级别按租户过滤
- ✅ **L2 文档/Chunk 权限** — 角色、部门、项目、密级、访问策略
- ✅ **L3 检索前过滤** — 权限条件先于向量检索下推
- ✅ **L4 生成前校验** — chunk 级二次验证，LLM 看不到无权数据
- ✅ **L5 审计日志** — 全链路追踪：用户→问题→文档→chunk→答案→时间戳
- ✅ **输出脱敏** — 自动遮挡身份证号、手机号、邮箱、IP 地址

### 身份认证
- ✅ JWT (HS256) 会话令牌 + 本地 (bcrypt/pbkdf2) + Firebase ID Token 验证
- ✅ 用户模型（首次登录自动创建）+ L2 权限集成

### Agent 平台
- ✅ **统一 Tool Schema** — 全部工具输出 `{ok, data, error, latency_ms}`
- ✅ **HTTP API** — `python -m agent.http_server --port 8765`
- ✅ **Agent 适配器** — Chat / Coding / Batch / Workflow
- ✅ **多 Agent 运行时** — JobManager、Scheduler、TimeoutGuard、ResultMerger
- ✅ **任务隔离** — `jobs/{run_id}/input/ output/ cache/ logs/`

### 多模态
- ✅ **知识对象** — TextBlock、TableBlock、FigureBlock、DiagramBlock、OCRRegion
- ✅ **模态路由** — 自动检测页面类型，分配最佳处理链
- ✅ **模态亲和度** — 问题→证据偏好（表格 vs 图示 vs 文本）
- ✅ **Vision Adapter** — 统一 MiniMax/GPT-4V/Claude Vision 接口
- ✅ **ask_v3()** — 模态感知检索 + 混合证据融合

### 平台
- ✅ **跨平台** — Windows / macOS / Linux，CPU / CUDA / Apple Silicon MPS
- ✅ **自动检测** — OS、架构、GPU、推荐设备和并发数
- ✅ **运行配置** — 6 种预设 (win/mac/linux × cpu/cuda)
- ✅ **文档版本管理** — SHA256 指纹，增量重索引
- ✅ **异步管线** — 后台文档处理 + 回调通知

### 基础设施
- ✅ **Prompt Registry** — 7 模板 × 8 版本，意图自适应
- ✅ **Context Builder** — Jaccard 去重 + token 预算裁剪
- ✅ **Cost Manager** — 按模型统计 token/费用
- ✅ **LRU 缓存** — 答案缓存 (30分钟) + 向量缓存 (1小时)
- ✅ **评估体系** — Recall@K + Faithfulness + Bad Case 追踪
- ✅ **元数据增强** — LLM 自动生成摘要/关键词/可答问题

---

## 平台支持

| 系统 | CPU | CUDA | Apple Silicon |
|---|---|---|---|
| Windows 10/11 | ✅ | ✅ | — |
| macOS | ✅ | — | ✅ MPS |
| Linux | ✅ | ✅ | — |

详见 [docs/platform-compatibility.md](docs/platform-compatibility.md)

---

## API 快速参考

### HTTP API
```bash
GET  /tools/list                        # 列出所有工具
POST /tools/call  {"name":"...","params":{...}}  # 调用工具
GET  /health                            # 健康检查
```

### MCP 工具 (9)
`edis_ask` · `edis_search` · `edis_ingest` · `edis_status` · `edis_compare` · `edis_citations` · `edis_evaluate` · `edis_category` · `edis_audit`

### Python SDK
```python
from qa.engine import QAEngine
engine = QAEngine()
result = engine.ask_v2("动臂油缸的规格参数？", user_context={"user_id": "alice"})
result = engine.ask_v3("对照表里上海住宿标准？")  # 模态感知
```

### Agent 适配器
```python
from agent.adapters import ChatAgentAdapter
adapter = ChatAgentAdapter("http://localhost:8765")
result = adapter.ask("MQTT如何配置？", user_id="alice")
```

---

## 项目结构

```
edis/
├── agent/              # Agent Tool Registry + HTTP API + 适配器
├── agent_runtime/      # JobManager, Scheduler, TimeoutGuard, ResultMerger
├── multimodal/         # PageClassifier, ModalityRouter, VisionAdapter
├── knowledge_objects/  # TextBlock, TableBlock, FigureBlock, DiagramBlock
├── query_rewrite/      # 多轮指代消解
├── permissions/        # L2: 文档/Chunk 权限控制
├── verifier/           # L4: 生成前权限校验
├── audit/              # L5: 全链路审计日志
├── auth/               # JWT + Firebase + 本地认证
├── edis_platform/      # 跨平台检测 + 运行配置
├── interfaces/         # 6 个 ABC 接口
├── adapters/           # DeepSeek/OpenAI/MiniMax + BGE + 精排器
├── plugins/            # 插件注册表（装饰器模式）
├── parsers/            # DOCX, Markdown, HTML, Text 解析器
├── tools/              # 11 个统一工具
├── qa/                 # QA Engine v4.0 (ask/ask_v2/ask_v3)
├── retrieval/          # VectorStore + Embedder + ParentDocRetrieval + Hybrid(BM25)
├── ingestion/          # PDF 解析, 分块, 并行, 版本管理
├── cleaning/           # 5 步清洗管线 + Quality Gate
├── metadata/           # 元数据提取 + LLM 增强
├── evaluation/         # Recall@K + Faithfulness + Bad Case DB
├── config/             # config.yaml + runtime_profiles.yaml + prompts
├── context_builder/    # Jaccard 去重 + token 预算
├── fusion/             # 去重 + 冲突检测 + 排序
├── planner/            # 意图分类 + 检索计划
├── cache/              # LRU 缓存
├── operations/         # 成本追踪 + 向量版本
├── validator/          # 5 步文件校验
├── security.py         # 文件安全 + 注入防护 + 限流
├── mcp_server.py       # MCP JSON-RPC stdio (9 tools)
├── main.py             # CLI (ingest / ask / auth)
├── batch_ingest.py     # 批量文档导入
├── batch_qa.py         # 批量问答
├── evaluate.py         # 评估运行器
├── docs/               # 平台兼容性, Agent 集成
├── scripts/            # 跨平台安装脚本
├── config/             # YAML 配置 + 运行配置
├── requirements-*.txt  # 分平台依赖
├── tests/              # 59 个 pytest 测试
└── setup.py            # pip install edis
```

---

## 系统要求

| 资源 | 最低 | 推荐 |
|---|---|---|
| CPU | 4 核 | 8 核以上 |
| RAM | 8 GB | 16 GB |
| 磁盘 | 5 GB | 20 GB |
| GPU | **不需要** | 可选 (CUDA/MPS) |
| Python | 3.10+ | 3.11 |

**无需任何外部服务。** SQLite + 本地 CPU embedding 即可运行。

---

## License

MIT — 详见 [LICENSE](LICENSE)
