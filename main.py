"""EDIS CLI — 支持多租户 + 批量导入"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from config import config
from config.tenant import tenant_context, set_current_tenant, get_current_tenant
from ingestion import parse_pdf
from ingestion.chunker import HierarchicalChunker
from ingestion.parallel import ParallelIngestor
from cleaning import clean_pipeline
from retrieval import VectorStore, Embedder
from qa import QASystem

ALLOWED_EXTENSIONS = {".pdf"}
PARALLEL_THRESHOLD = 100


def _validate_filepath(filepath: str) -> Path:
    path = Path(filepath).resolve()
    if path.suffix.lower() not in ALLOWED_EXTENSIONS:
        raise ValueError(f"Unsupported file type: {path.suffix}")
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")
    return path


def ingest_pdf(filepath: str, tenant_id: str = "default") -> str:
    path = _validate_filepath(filepath)
    print(f"[ingest] Tenant={tenant_id} Parsing: {path}")
    doc = parse_pdf(str(path))

    # 文档方向自动检测
    from config.categorizer import detect_category
    sample_text = " ".join(p.text[:500] for p in doc.pages[:5])
    category = detect_category(sample_text)
    doc.metadata["category"] = category.category
    doc.metadata["category_confidence"] = category.confidence
    print(f"[ingest] Category: {category.category} ({category.confidence:.0%})")

    if doc.page_count > PARALLEL_THRESHOLD:
        print(f"[ingest] {doc.page_count} pages → parallel mode")
        ingestor = ParallelIngestor(
            chunk_size=config.get("ingestion", "chunk_size"),
            chunk_overlap=config.get("ingestion", "chunk_overlap"),
            parallel_threshold=PARALLEL_THRESHOLD,
        )
        doc, chunks, cleaned = ingestor.ingest(str(path))
    else:
        print(f"[ingest] Cleaning {doc.page_count} pages...")
        cleaned = clean_pipeline(doc.pages)
        chunker = HierarchicalChunker(
            chunk_size=config.get("ingestion", "chunk_size"),
            chunk_overlap=config.get("ingestion", "chunk_overlap"),
        )
        chunks = chunker.chunk(doc)

    store = VectorStore(config.get("storage", "db_path"))
    try:
        store.insert_document(doc.document_id, doc.filename, str(doc.path),
                             doc.page_count, doc.total_chars, doc.metadata, tenant_id)
        print(f"[ingest] Embedding {len(chunks)} chunks...")
        texts = [ch.text for ch in chunks]
        embeddings = Embedder.encode(texts, batch_size=config.get("embedding", "batch_size"))
        for chunk, emb in zip(chunks, embeddings):
            rowid = store.insert_chunk(doc.document_id, chunk.chunk_index, chunk.text,
                                      chunk.page, chunk.chapter, chunk.section, chunk.metadata, tenant_id)
            store.insert_embedding(rowid, emb)
    finally:
        store.close()

    print(f"[ingest] Done. {len(chunks)} chunks for '{doc.filename}' (tenant={tenant_id})")
    return doc.document_id


def ask_question(question: str, use_v2: bool = False) -> dict:
    qa = QASystem()
    if use_v2:
        return qa.ask_v2(question)
    return qa.ask(question)


if __name__ == "__main__":
    args = sys.argv[1:]
    tenant = "default"
    use_v2 = False

    # 解析 --tenant 和 --v2 标志
    filtered = []
    i = 0
    while i < len(args):
        if args[i] == "--tenant" and i + 1 < len(args):
            tenant = args[i + 1]
            i += 2
        elif args[i] == "--v2":
            use_v2 = True
            i += 1
        else:
            filtered.append(args[i])
            i += 1

    if not filtered:
        print("Usage:")
        print("  python main.py [--tenant <id>] [--v2] ingest <pdf_path>")
        print("  python main.py [--tenant <id>] [--v2] ask <question>")
        sys.exit(1)

    cmd = filtered[0]
    set_current_tenant(tenant)

    if cmd == "ingest":
        if len(filtered) < 2:
            print("Error: missing PDF path")
            sys.exit(1)
        try:
            ingest_pdf(filtered[1], tenant)
        except (ValueError, FileNotFoundError) as e:
            print(f"Error: {e}")
            sys.exit(1)

    elif cmd in ("ask", "ask-v2"):
        if len(filtered) < 2:
            print("Error: missing question")
            sys.exit(1)
        question = " ".join(filtered[1:])
        result = ask_question(question, use_v2=(cmd == "ask-v2" or use_v2))
        print(f"\nAnswer: {result['answer']}")
        if result.get('intent'):
            print(f"Intent: {result['intent']}")
        print(f"Confidence: {result.get('confidence', 'N/A')}")
        for cit in result.get("citations", []):
            print(f"  - {cit.get('document','?')}, Page {cit.get('page','?')} ({cit.get('relevance','?')})")

    else:
        print(f"Unknown command: {cmd}")
