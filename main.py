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
from qa.engine import QAEngine

ALLOWED_EXTENSIONS = {".pdf"}
PARALLEL_THRESHOLD = 100


def _validate_filepath(filepath: str) -> Path:
    path = Path(filepath).resolve()
    if path.suffix.lower() not in ALLOWED_EXTENSIONS:
        raise ValueError(f"Unsupported file type: {path.suffix}")
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")
    return path


def ingest_pdf(filepath: str, tenant_id: str = "default",
               permissions: dict = None) -> str:
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

    # 权限：默认 open + internal
    from permissions import PermissionManager, inherit_permissions
    doc_perms = permissions or PermissionManager.default_permissions(
        owner=tenant_id,
        security_level=1,
        access_policy="open",
    )
    chunk_perms = inherit_permissions(doc_perms)

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
                             doc.page_count, doc.total_chars, doc.metadata,
                             tenant_id, permissions=doc_perms)
        print(f"[ingest] Embedding {len(chunks)} chunks...")
        texts = [ch.text for ch in chunks]
        embeddings = Embedder.encode(texts, batch_size=config.get("embedding", "batch_size"))
        for chunk, emb in zip(chunks, embeddings):
            rowid = store.insert_chunk(doc.document_id, chunk.chunk_index, chunk.text,
                                      chunk.page, chunk.chapter, chunk.section,
                                      chunk.metadata, tenant_id, permissions=chunk_perms)
            store.insert_embedding(rowid, emb)
    finally:
        store.close()

    print(f"[ingest] Done. {len(chunks)} chunks for '{doc.filename}' (tenant={tenant_id})")
    return doc.document_id


def ask_question(question: str, use_v2: bool = False,
                 user_context: dict = None) -> dict:
    engine = QAEngine()
    if use_v2:
        return engine.ask_v2(question, user_context=user_context)
    return engine.ask(question)


# ── Auth CLI ─────────────────────────────────────

def _cmd_auth(args: list[str]):
    """处理 auth 子命令"""
    if not args:
        print("Usage: python main.py auth <login|register|whoami> [options]")
        sys.exit(1)

    sub = args[0]
    from auth import AuthManager
    am = AuthManager()

    if sub == "login":
        provider = "local"
        email = password = ""
        i = 1
        while i < len(args):
            if args[i] == "--provider" and i + 1 < len(args):
                provider = args[i + 1]; i += 2
            elif args[i] == "--email" and i + 1 < len(args):
                email = args[i + 1]; i += 2
            elif args[i] == "--password" and i + 1 < len(args):
                password = args[i + 1]; i += 2
            else:
                i += 1

        credential = f"{email}:{password}" if provider == "local" else password
        user, jwt = am.login(provider, credential)
        if user:
            print(f"Login OK: {user.email} (uid={user.firebase_uid})")
            print(f"JWT: {jwt}")
        else:
            print("Login FAILED")
            sys.exit(1)

    elif sub == "register":
        provider = "local"
        email = password = name = ""
        i = 1
        while i < len(args):
            if args[i] == "--provider" and i + 1 < len(args):
                provider = args[i + 1]; i += 2
            elif args[i] == "--email" and i + 1 < len(args):
                email = args[i + 1]; i += 2
            elif args[i] == "--password" and i + 1 < len(args):
                password = args[i + 1]; i += 2
            elif args[i] == "--name" and i + 1 < len(args):
                name = args[i + 1]; i += 2
            else:
                i += 1

        user, jwt = am.register(provider, email, password, name)
        if user:
            print(f"Register OK: {user.email} (uid={user.firebase_uid})")
            print(f"JWT: {jwt}")
        else:
            print("Register FAILED")
            sys.exit(1)

    elif sub == "whoami":
        token = None
        i = 1
        while i < len(args):
            if args[i] == "--token" and i + 1 < len(args):
                token = args[i + 1]; i += 2
            else:
                i += 1
        if not token:
            print("Usage: python main.py auth whoami --token <jwt>")
            sys.exit(1)
        claims = am.verify_jwt(token)
        if claims:
            user = am.get_user(claims["sub"])
            if user:
                print(f"User: {user.email}")
                print(f"UID:  {user.firebase_uid}")
                print(f"Role: {user.role or '(none)'}")
                print(f"Dept: {user.department or '(none)'}")
                print(f"Clearance: {user.security_clearance}")
            else:
                print(f"Claims valid but user not found: {claims['sub']}")
        else:
            print("Invalid or expired token")
            sys.exit(1)

    else:
        print(f"Unknown auth command: {sub}")
        sys.exit(1)

    am.close()


def main():
    """CLI entry point for `edis` console script."""
    args = sys.argv[1:]
    tenant = "default"
    use_v2 = False

    # 解析 --tenant 和 --v2 和 --token 标志
    filtered = []
    token = None
    i = 0
    while i < len(args):
        if args[i] == "--tenant" and i + 1 < len(args):
            tenant = args[i + 1]
            i += 2
        elif args[i] == "--v2":
            use_v2 = True
            i += 1
        elif args[i] == "--token" and i + 1 < len(args):
            token = args[i + 1]
            i += 2
        else:
            filtered.append(args[i])
            i += 1

    if not filtered:
        print("Usage:")
        print("  python main.py [--tenant <id>] [--v2] [--token <jwt>] ingest <pdf_path>")
        print("  python main.py [--tenant <id>] [--v2] [--token <jwt>] ask <question>")
        print("  python main.py auth <login|register|whoami> [options]")
        sys.exit(1)

    cmd = filtered[0]
    set_current_tenant(tenant)

    if cmd == "auth":
        _cmd_auth(filtered[1:])

    elif cmd == "ingest":
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

        # 解析 JWT token 获取用户上下文
        user_context = None
        if token:
            from auth import AuthManager
            am = AuthManager()
            claims = am.verify_jwt(token)
            if claims:
                user = am.get_user(claims["sub"])
                if user:
                    user_context = user.to_permission_context()
                    set_current_tenant(user.tenant_id)
                    print(f"[auth] User: {user.email}, clearance: {user.security_clearance}")
                else:
                    print("[auth] Token valid but user not found")
            else:
                print("[auth] Invalid or expired token — running as anonymous")
            am.close()

        result = ask_question(question, use_v2=(cmd == "ask-v2" or use_v2),
                             user_context=user_context)
        print(f"\nAnswer: {result['answer']}")
        if result.get('intent'):
            print(f"Intent: {result['intent']}")
        print(f"Confidence: {result.get('confidence', 'N/A')}")
        for cit in result.get("citations", []):
            print(f"  - {cit.get('document','?')}, Page {cit.get('page','?')} ({cit.get('relevance','?')})")
        if result.get('security_alerts'):
            print(f"Security: {result['security_alerts']}")

    else:
        print(f"Unknown command: {cmd}")


if __name__ == "__main__":
    main()
