[![中文](https://img.shields.io/badge/中文-README__CN-blue)](README_CN.md)

# Enterprise Document Intelligence System (EDIS)

> **Agent-First Enterprise Document Intelligence Framework**  
> Turn large-scale engineering documents into a searchable, citable, evaluable knowledge base.  
> EDIS = **E**nterprise **D**ocument **I**ntelligence **S**ystem.

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-MIT-green)](LICENSE)
[![Tests](https://img.shields.io/badge/tests-26%20passed-brightgreen)](tests/)
[![MCP](https://img.shields.io/badge/MCP-Ready-purple)](mcp_server.py)

---

## What is EDIS?

EDIS is a **local-first, agent-first** engineering document intelligence framework. It ingests PDFs, DOCX, Markdown, and HTML files, parses and cleans them, indexes them with local embeddings (BGE), and exposes knowledge retrieval via MCP / Python SDK / CLI — so any AI agent can query your documents.

EDIS is **not a chatbot**. It's knowledge infrastructure that multiple agents and LLMs share.

---

## Quick Start

```bash
git clone https://github.com/mochenxin2025-png/edis.git
cd edis
pip install -e .

# Ingest a document
python main.py ingest your-doc.pdf

# Ask a question
python main.py --v2 ask "What is the control valve assembly?"

# Run evaluation
python evaluate.py your-answers.md
```

---

## Architecture

```
┌──────────────────────────────────────────────────────┐
│  Agent Layer (Hermes / Claude / Cursor / GPT / ...)  │
├──────────────────────────────────────────────────────┤
│  MCP Server         Python SDK            CLI         │
├──────────────────────────────────────────────────────┤
│          Tool Registry (10 unified tools)             │
├──────────────────────────────────────────────────────┤
│  QA Engine  │  Search  │  Fusion  │  Cache  │  Cost  │
├──────────────────────────────────────────────────────┤
│  Plugin Registry  (6 parsers · 3 LLM · 1 embedding)  │
├──────────────────────────────────────────────────────┤
│     SQLite + sqlite-vec  (vectors + metadata + mem)   │
└──────────────────────────────────────────────────────┘
```

**Knowledge Pipeline:**  
`Upload → FileValidator → MetadataExtractor → Parser → Cleaner → Chunker → Embedding → VectorStore → Retrieval`

**Query Pipeline:**  
`Question → QA Pair Registry → Intent Classifier → Semantic Search → Evidence Fusion → Context Builder → LLM → Answer + Citations [N, Page X]`

---

## Supported File Types

| Format | Parser | Status |
|---|---|---|
| PDF | pymupdf | ✅ Built-in |
| DOCX | python-docx | ✅ Plugin |
| Markdown | stdlib | ✅ Plugin |
| HTML | bs4 (optional) | ✅ Plugin |
| TXT / CSV / JSON / XML | stdlib | ✅ Plugin |
| Images (OCR) | PaddleOCR | ✅ Plugin |

---

## LLM Providers

| Provider | Model | Config |
|---|---|---|
| DeepSeek | deepseek-chat | `$DEEPSEEK_API_KEY` |
| OpenAI | gpt-4o-mini | `$OPENAI_API_KEY` |
| MiniMax | abab6.5s-chat | `$MINIMAX_API_KEY` |

Switch via code: `get_llm("openai")` or MCP config.

---

## Key Features

- ✅ **Full Retrieval Pipeline** — parse → clean → chunk → embed → search → fusion → answer
- ✅ **MCP Native** — works with Claude Desktop / Cursor / Codex / Gemini CLI
- ✅ **Multi-Tenant** — tenant-level isolation for documents, QA pairs, memory
- ✅ **QA Pair Registry** — human-filled knowledge patches bypass LLM entirely
- ✅ **Unanswered Queue** — questions the system can't answer go into a review queue
- ✅ **10 Unified Tools** — search, ask, ingest, compare, citations, evaluate, category...
- ✅ **Plugin System** — swap LLM, embedding, parser without touching core code
- ✅ **Prompt Registry** — versioned, intent-adaptive prompts (7 templates / 8 versions)
- ✅ **Context Builder** — deduplication + truncation + token budgeting
- ✅ **Extension System** — pip-installable extensions via entry_points
- ✅ **Cost Manager** — per-model token/cost tracking
- ✅ **LRU Cache** — answer cache (30min) + embedding cache (1h)
- ✅ **Evaluation** — Recall@K + Faithfulness scoring with LLM judge

---

## Requirements

| Resource | Minimum | Recommended |
|---|---|---|
| CPU | 4 cores | 8+ cores |
| RAM | 8 GB | 16 GB |
| Disk | 5 GB | 20 GB |
| GPU | **Not needed** | Not needed |
| Python | 3.10+ | 3.11 |

**Zero external services required.** SQLite + local CPU embedding is all you need for Phases 1-3.

---

## Evaluation Baseline (PC200-6 Manual, 341 pages, 200 questions)

| Metric | Phase 1 | Phase 2 |
|---|---|---|
| Recall@5 | 100% | 100% |
| Faithfulness | 21% | 63.5% |

---

## Agent Integration

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
result = engine.ask_v2("What is the Rx Sensitivity?")
print(result["answer"], result["citations"])
```

See [AGENTS.md](AGENTS.md) for full integration guide.

---

## Project Structure

```
edis/
├── interfaces/       # 9 ABC interfaces
├── adapters/         # 6 concrete implementations
├── plugins/          # Plugin registry
├── tools/            # 10 unified tools
├── qa/               # QA Engine v3
├── mcp_server.py     # MCP entry point
├── main.py           # CLI entry point
├── metadata/         # Metadata extraction
├── validator/        # File validation
├── parsers/          # Multi-format parsers
├── cache/            # LRU cache
├── operations/       # Cost tracking + versioning
├── config/           # Config + tenants + prompts
├── context_builder/  # Context assembly
├── extensions/       # Extension system
├── tests/            # 26 pytest tests
└── setup.py          # pip install edis
```

---

## License

MIT — see [LICENSE](LICENSE).
