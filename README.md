[![中文](https://img.shields.io/badge/中文-README__CN-blue)](README_CN.md)

# Enterprise Document Intelligence System (EDIS)

> **Agent-First Enterprise Document Intelligence Framework**  
> Turn large-scale engineering documents into a searchable, citable, evaluable knowledge base.  
> EDIS = **E**nterprise **D**ocument **I**ntelligence **S**ystem.

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-MIT-green)](LICENSE)
[![Tests](https://img.shields.io/badge/tests-59%20passed-brightgreen)](tests/)
[![MCP](https://img.shields.io/badge/MCP-Ready-purple)](mcp_server.py)
[![HTTP](https://img.shields.io/badge/HTTP_API-8765-orange)](agent/http_server.py)
[![Platform](https://img.shields.io/badge/platform-Win%20%7C%20Mac%20%7C%20Linux-lightgrey)](docs/platform-compatibility.md)

---

## What is EDIS?

EDIS is a **local-first, agent-first** enterprise document intelligence framework. Ingest PDFs, DOCX, Markdown, HTML — parse, clean, chunk, embed, and retrieve with local BGE embeddings. Exposed via MCP / HTTP API / Python SDK / CLI.

EDIS is **not a chatbot**. It's knowledge infrastructure shared by multiple agents and LLMs.

---

## Quick Start

```bash
# Cross-platform install
# Windows:  .\scripts\install_windows.ps1
# macOS:    bash scripts/install_macos.sh
# Linux:    bash scripts/install_linux.sh

# Or manual:
git clone https://github.com/mochenxin2025-png/Enterprise-Document-Intelligence-System.git
cd edis
pip install uv
uv pip install -r requirements-base.txt -r requirements-windows.txt

# Ingest a document
python main.py ingest your-doc.pdf

# Ask a question
python main.py --v2 ask "What is the control valve assembly?"

# HTTP API mode
python -m agent.http_server --port 8765
curl -X POST http://localhost:8765/tools/call \
  -d '{"name":"answer_question","params":{"question":"MQTT如何配置？"}}'
```

---

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│         Agent Layer (Hermes / Claude / Cursor / GPT)         │
├──────────────────────────────────────────────────────────────┤
│  MCP Server      HTTP API (8765)      CLI      Python SDK    │
├──────────────────────────────────────────────────────────────┤
│              Agent Tool Registry (5 tools, {ok,data,error})  │
├──────────────────────────────────────────────────────────────┤
│  Security L1-L5: Tenant → Permissions → FilterFirst → Verify → Audit │
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
│  Data Pipeline: Parser(6) → Cleaner → Chunker → Embedder     │
│  Hybrid Retrieval: Vector(sqlite-vec) + BM25                 │
├──────────────────────────────────────────────────────────────┤
│  SQLite + sqlite-vec  ·  Platform Adapter (Win/Mac/Linux)    │
└──────────────────────────────────────────────────────────────┘
```

**Query Pipeline (v4.0):**  
`Question → QueryRewrite → QA Pair → Intent → ParentDoc → Rerank → L4Verify → Context → LLM → L5Sanitize → Audit`

---

## Key Features

### Core RAG
- ✅ Full pipeline: parse → clean → chunk → embed → search → fusion → answer
- ✅ **Parent Document Retrieval** — solves chunk isolation (summary dominates TopK)
- ✅ **Heuristic + LLM Reranker** — keyword overlap, diversity, position weighting
- ✅ **Hybrid Retrieval** — vector (sqlite-vec) + keyword (BM25)
- ✅ **Query Rewrite** — multi-turn pronoun resolution ("它"→"Nginx")
- ✅ **QA Pair Registry** + **Unanswered Queue** + **Bad Case Database**

### Enterprise Security (L1-L5)
- ✅ **L1 Tenant Isolation** — per-tenant data separation at SQL level
- ✅ **L2 Doc/Chunk Permissions** — role, department, project, security_level, access_policy
- ✅ **L3 Filter First** — permission WHERE clause pushed before vector search
- ✅ **L4 Pre-Generation Verify** — chunk-level re-check before LLM sees data
- ✅ **L5 Audit Logging** — full trace: user→question→docs→chunks→answer→timestamp
- ✅ **Output Sanitization** — auto-redact ID cards, phone numbers, emails, IPs

### Authentication
- ✅ JWT (HS256) session tokens + Local (bcrypt/pbkdf2) + Firebase ID token verify
- ✅ User model with auto-create on first login + L2 permission integration

### Agent Platform
- ✅ **Unified Tool Schema** — `{ok, data, error, latency_ms}` for all tools
- ✅ **HTTP API** — start with `python -m agent.http_server --port 8765`
- ✅ **Agent Adapters** — Chat / Coding / Batch / Workflow adapters
- ✅ **Multi-Agent Runtime** — JobManager, Scheduler, TimeoutGuard, ResultMerger
- ✅ **Per-run Isolation** — `jobs/{run_id}/input/ output/ cache/ logs/`

### Multimodal
- ✅ **Knowledge Objects** — TextBlock, TableBlock, FigureBlock, DiagramBlock, OCRRegion
- ✅ **Modality Router** — auto-detect page type, route to correct processing chain
- ✅ **Modality Affinity** — question→evidence preference (table vs diagram vs text)
- ✅ **Vision Adapter** — unified MiniMax/GPT-4V/Claude Vision interface
- ✅ **ask_v3()** — modality-aware retrieval with mixed evidence fusion

### Platform
- ✅ **Cross-Platform** — Windows / macOS / Linux, CPU / CUDA / Apple Silicon MPS
- ✅ **Auto-Detection** — OS, arch, GPU, recommended device/workers
- ✅ **Runtime Profiles** — 6 presets (win/mac/linux × cpu/cuda)
- ✅ **Document Versioning** — SHA256 fingerprint, incremental re-index
- ✅ **Async Pipeline** — background document processing with callbacks

### Infrastructure
- ✅ **Prompt Registry** — 7 templates × 8 versions, intent-adaptive
- ✅ **Context Builder** — Jaccard dedup + token budget
- ✅ **Cost Manager** — per-model token/$ tracking
- ✅ **LRU Cache** — answer (30min) + embedding (1h)
- ✅ **Evaluation** — Recall@K + Faithfulness + Bad Case tracking
- ✅ **Metadata Enhancer** — LLM auto-generates Summary/Keywords/Questions

---

## Platform Support

| OS | CPU | CUDA | Apple Silicon |
|---|---|---|---|
| Windows 10/11 | ✅ | ✅ | — |
| macOS | ✅ | — | ✅ MPS |
| Linux | ✅ | ✅ | — |

See [docs/platform-compatibility.md](docs/platform-compatibility.md) for details.

---

## Quick API Reference

### HTTP API
```bash
GET  /tools/list                        # List all tools
POST /tools/call  {"name":"...","params":{...}}  # Call tool
GET  /health                            # Health check
```

### MCP Tools (9)
`edis_ask` · `edis_search` · `edis_ingest` · `edis_status` · `edis_compare` · `edis_citations` · `edis_evaluate` · `edis_category` · `edis_audit`

### Python SDK
```python
from qa.engine import QAEngine
engine = QAEngine()
result = engine.ask_v2("What is the Rx Sensitivity?", user_context={"user_id": "alice"})
result = engine.ask_v3("对照表里上海住宿标准？")  # modality-aware
```

### Agent Adapters
```python
from agent.adapters import ChatAgentAdapter
adapter = ChatAgentAdapter("http://localhost:8765")
result = adapter.ask("MQTT如何配置？", user_id="alice")
```

---

## Project Structure

```
edis/
├── agent/              # Agent Tool Registry + HTTP API + Adapters
├── agent_runtime/      # JobManager, Scheduler, TimeoutGuard, ResultMerger
├── multimodal/         # PageClassifier, ModalityRouter, VisionAdapter
├── knowledge_objects/  # TextBlock, TableBlock, FigureBlock, DiagramBlock
├── query_rewrite/      # Multi-turn pronoun resolution
├── permissions/        # L2: Doc/Chunk access control
├── verifier/           # L4: Pre-generation permission verify
├── audit/              # L5: Full audit logging
├── auth/               # JWT + Firebase + Local auth
├── edis_platform/      # Cross-platform detector + runtime profiles
├── interfaces/         # 6 ABC interfaces (LLM/Embedding/Parser/VectorStore/OCR/Reranker)
├── adapters/           # DeepSeek/OpenAI/MiniMax + BGE + Heuristic/LLM Reranker
├── plugins/            # Plugin registry (decorator-based)
├── parsers/            # DOCX, Markdown, HTML, Text parsers
├── tools/              # 11 unified tools
├── qa/                 # QA Engine v4.0 (ask/ask_v2/ask_v3)
├── retrieval/          # VectorStore + Embedder + ParentDocRetrieval + Hybrid(BM25)
├── ingestion/          # PDF parser, chunker, parallel, versioning
├── cleaning/           # 5-step cleaning pipeline + Quality Gate
├── metadata/           # Metadata extraction + LLM enhancer
├── evaluation/         # Recall@K + Faithfulness + Bad Case DB
├── config/             # config.yaml + runtime_profiles.yaml + prompts
├── context_builder/    # Jaccard dedup + token budgeting
├── fusion/             # Dedup + conflict detection + ranking
├── planner/            # Intent classifier + retrieval planning
├── cache/              # LRU cache
├── operations/         # Cost tracking + embedding version
├── validator/          # 5-step file validation
├── security.py         # File security + injection guard + rate limiting
├── mcp_server.py       # MCP JSON-RPC over stdio (9 tools)
├── main.py             # CLI (ingest / ask / auth)
├── batch_ingest.py     # Batch document ingestion
├── batch_qa.py         # Batch question answering
├── evaluate.py         # Evaluation runner
├── docs/               # Platform compatibility, agent integration
├── scripts/            # Cross-platform install scripts
├── config/             # YAML configs + runtime profiles
├── requirements-*.txt  # Per-platform dependencies
├── tests/              # 59 pytest tests
└── setup.py            # pip install edis
```

---

## Requirements

| Resource | Minimum | Recommended |
|---|---|---|
| CPU | 4 cores | 8+ cores |
| RAM | 8 GB | 16 GB |
| Disk | 5 GB | 20 GB |
| GPU | **Not needed** | Optional (CUDA/MPS) |
| Python | 3.10+ | 3.11 |

**Zero external services required.** SQLite + local CPU embedding.

---

## License

MIT — see [LICENSE](LICENSE).
