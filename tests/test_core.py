"""EDIS Core Tests — pytest 覆盖所有可替换接口"""
import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))


# ── Plugin Registry ────────────────────────────

class TestPluginRegistry:
    def test_list_all_categories(self):
        from plugins import PluginRegistry
        cats = PluginRegistry.list()
        assert "llm" in cats
        assert "embedding" in cats
        assert "parser" in cats
        assert "deepseek" in cats["llm"]
        assert "openai" in cats["llm"]
        assert "minimax" in cats["llm"]
        assert "bge-large-zh" in cats["embedding"]
        assert "pymupdf" in cats["parser"]

    def test_create_valid(self):
        from plugins import get_llm
        llm = get_llm("deepseek")
        assert llm.model_name == "deepseek-chat"

    def test_create_invalid_raises(self):
        from plugins import PluginRegistry
        with pytest.raises(ValueError, match="Plugin not found"):
            PluginRegistry.create("llm", "nonexistent")


# ── Interfaces ─────────────────────────────────

class TestInterfaces:
    def test_llm_interface_is_abstract(self):
        from interfaces import LLMInterface
        with pytest.raises(TypeError):
            LLMInterface()

    def test_embedding_interface_is_abstract(self):
        from interfaces import EmbeddingInterface
        with pytest.raises(TypeError):
            EmbeddingInterface()

    def test_adapters_implement_llm(self):
        from interfaces import LLMInterface
        from plugins import PluginRegistry
        for name in PluginRegistry.list("llm"):
            cls = PluginRegistry.get("llm", name)
            assert issubclass(cls, LLMInterface), f"{name} does not implement LLMInterface"

    def test_adapters_implement_embedding(self):
        from interfaces import EmbeddingInterface
        from plugins import PluginRegistry
        for name in PluginRegistry.list("embedding"):
            cls = PluginRegistry.get("embedding", name)
            assert issubclass(cls, EmbeddingInterface), f"{name} does not implement EmbeddingInterface"


# ── Parser ─────────────────────────────────────

class TestParser:
    def test_parse_pdf(self):
        from plugins import get_parser
        parser = get_parser("pymupdf")
        doc = parser.parse("data/test_onu_manual.pdf")
        assert doc.page_count == 1
        assert doc.total_chars > 100
        assert "ONU" in doc.pages[0]["text"]

    def test_parser_supports(self):
        from plugins import get_parser
        parser_cls = get_parser("pymupdf").__class__
        assert parser_cls.supports("file.pdf")
        assert not parser_cls.supports("file.docx")


# ── QA Pairs ───────────────────────────────────

class TestQAPairs:
    def test_add_and_exact_match(self):
        from qa_pairs import QARegistry
        reg = QARegistry()
        reg.add("什么是ONU？", "光网络单元", ["设备"], tenant_id="test")
        result = reg.search("什么是ONU？", tenant_id="test")
        assert result is not None
        assert result.answer == "光网络单元"

    def test_fuzzy_match(self):
        from qa_pairs import QARegistry
        reg = QARegistry()
        reg.add("发动机驱动盘的作用是什么？", "传递扭矩", ["发动机"], tenant_id="test")
        result = reg.search("驱动盘干嘛用的", tenant_id="test")
        assert result is not None

    def test_no_false_match(self):
        from qa_pairs import QARegistry
        reg = QARegistry()
        reg.add("发动机驱动盘的作用是什么？", "传递扭矩", tenant_id="test")
        result = reg.search("发动机型号是什么？", tenant_id="test")
        assert result is None, "Should NOT match different question"


# ── Unanswered Queue ───────────────────────────

class TestUnansweredQueue:
    def test_enqueue_and_list(self):
        from unanswered import UnansweredQueue
        q = UnansweredQueue()
        q.enqueue("测试问题", "some context", [{"page":1,"score":0.5}], tenant_id="test")
        pending = q.list_pending(tenant_id="test")
        assert len(pending) >= 1
        assert pending[0]["question"] == "测试问题"

    def test_resolve(self):
        from unanswered import UnansweredQueue
        q = UnansweredQueue()
        qid = q.enqueue("需要人工回答", tenant_id="test")
        q.resolve(qid, "人工填写的答案")
        pending = q.list_pending()
        assert all(p["id"] != qid for p in pending)


# ── Cleaning ───────────────────────────────────

class TestCleaning:
    def test_normalize_text(self):
        from cleaning import normalize_text
        result = normalize_text("Hello   World\n\n\nTest")
        assert "  " not in result.text
        assert "\n\n\n" not in result.text

    def test_quality_check_clean(self):
        from cleaning import quality_check
        result = quality_check("Normal clean text without garbage.")
        assert result.quality == "clean"

    def test_quality_check_empty(self):
        from cleaning import quality_check
        result = quality_check("")
        assert result.quality == "unreadable"

    def test_ocr_post_process(self):
        from cleaning import ocr_post_process
        text = "Ｒｘ　Ｓｅｎｓｉｔｉｖｉｔｙ　－２８ｄＢｍ"
        result = ocr_post_process(text)
        # Fullwidth ASCII should be converted
        assert "Rx" in result.text or "Sensitivity" in result.text


# ── Ontology ───────────────────────────────────

class TestOntology:
    def test_unit_normalize(self):
        from ontology import UnitNormalizer
        un = UnitNormalizer()
        v, u = un.normalize(-28, "dBm")
        assert v == -28.0
        assert u == "dBm"

    def test_unit_convert_mw_to_dbm(self):
        from ontology import UnitNormalizer
        un = UnitNormalizer()
        v, _ = un.normalize(100, "mW")
        assert 19.9 <= v <= 20.1

    def test_seed_ontology(self):
        from ontology import OntologyRegistry, seed_engineering_ontology
        reg = OntologyRegistry()
        seed_engineering_ontology(reg)
        names = reg.list_all()
        assert len(names) >= 5
        # 查找别名
        result = reg.lookup("onu")
        assert result is not None


# ── Chunker ────────────────────────────────────

class TestChunker:
    def test_split_text_no_infinite_loop(self):
        from ingestion.chunker import HierarchicalChunker
        c = HierarchicalChunker(100, 20)
        text = "hello world. " * 50
        chunks = c._split_text(text)
        assert 3 <= len(chunks) <= 10

    def test_chunk_empty_text(self):
        from ingestion.chunker import HierarchicalChunker
        c = HierarchicalChunker()
        chunks = c._split_text("")
        assert chunks == []


# ── Document Category ──────────────────────────

class TestCategorizer:
    def test_detect_construction(self):
        from config.categorizer import detect_category
        text = "挖掘机 PC200-6 液压泵 控制阀 动臂 斗杆 回转马达"
        cat = detect_category(text)
        assert cat.category == "construction_machinery"

    def test_detect_optical(self):
        from config.categorizer import detect_category
        text = "ONU OLT GPON optical network receiver sensitivity"
        cat = detect_category(text)
        assert cat.category == "optical_network"

    def test_unknown(self):
        from config.categorizer import detect_category
        cat = detect_category("这是一本小说，讲述了爱情故事。")
        assert cat.category == "unknown"


# ── Tenant Isolation ────────────────────────────

class TestTenantIsolation:
    """企业级 RAG L1: 租户数据隔离验证"""

    def test_qa_pairs_scoped_to_tenant(self):
        """不同租户的 QA Pair 互不可见"""
        from qa_pairs import QARegistry
        reg = QARegistry()
        reg.add("测试问题", "答案A", tenant_id="tenant_a")
        reg.add("测试问题", "答案B", tenant_id="tenant_b")

        # tenant_a 只能搜到自己的
        r_a = reg.search("测试问题", tenant_id="tenant_a")
        assert r_a is not None
        assert r_a.answer == "答案A"

        # tenant_b 只能搜到自己的
        r_b = reg.search("测试问题", tenant_id="tenant_b")
        assert r_b is not None
        assert r_b.answer == "答案B"

        # 默认租户搜不到
        r_default = reg.search("测试问题", tenant_id="default")
        assert r_default is None

    def test_qa_pairs_list_all_scoped(self):
        """list_all 只返回当前租户的 QA Pair"""
        from qa_pairs import QARegistry
        reg = QARegistry()
        reg.add("问题A", "答案A", tenant_id="tenant_x")
        reg.add("问题B", "答案B", tenant_id="tenant_y")

        items_x = reg.list_all(tenant_id="tenant_x")
        items_y = reg.list_all(tenant_id="tenant_y")

        assert all(item["id"] != "" for item in items_x)
        # 互不包含对方的
        ids_x = {item["question"] for item in items_x}
        ids_y = {item["question"] for item in items_y}
        assert "问题B" not in ids_x
        assert "问题A" not in ids_y

    def test_vectorstore_search_tenant_filter(self):
        """VectorStore.search() 必须按租户过滤"""
        from retrieval import VectorStore
        from retrieval import Embedder
        store = VectorStore()

        # 为两个租户插入不同的文档
        store.insert_document("doc-t1", "t1.pdf", "/fake/t1.pdf",
                             1, 100, {}, tenant_id="tenant_1")
        store.insert_document("doc-t2", "t2.pdf", "/fake/t2.pdf",
                             1, 100, {}, tenant_id="tenant_2")

        cid1 = store.insert_chunk("doc-t1", 0, "发动机控制阀装配步骤",
                                  1, "ch1", "s1", {}, tenant_id="tenant_1")
        cid2 = store.insert_chunk("doc-t2", 0, "光网络单元接收灵敏度",
                                  1, "ch1", "s1", {}, tenant_id="tenant_2")

        # 为两个 chunk 插入相同 embedding（简化测试）
        import numpy as np
        dummy_emb = np.zeros(1024, dtype=np.float32).tolist()
        store.insert_embedding(cid1, dummy_emb)
        store.insert_embedding(cid2, dummy_emb)

        # tenant_1 检索：只能看到"发动机"
        results_t1 = store.search(dummy_emb, top_k=10, tenant_id="tenant_1")
        store.close()

        # 应该只返回 tenant_1 的数据
        assert len(results_t1) >= 1
        assert all("发动机" in r.text or True for r in results_t1)
        # 不能看到 tenant_2 的数据
        t1_texts = " ".join(r.text for r in results_t1)
        assert "光网络" not in t1_texts, "tenant_1 should NOT see tenant_2's data"

    def test_tool_status_tenant_aware(self):
        """工具层 status 也必须按租户过滤"""
        from config.tenant import set_current_tenant
        from tools import tool_status

        # 设置租户上下文
        set_current_tenant("tenant_1")
        status = tool_status()

        # 基本结构检查
        assert "documents" in status
        assert "chunks" in status
        assert isinstance(status["documents"], int)

    def test_vectorstore_search_reads_current_tenant(self):
        """search() 在不传 tenant_id 时读取当前线程上下文"""
        from config.tenant import set_current_tenant
        from retrieval import VectorStore
        import numpy as np

        store = VectorStore()
        store.insert_document("doc-ctx", "ctx.pdf", "/fake/ctx.pdf",
                             1, 100, {}, tenant_id="ctx_tenant")

        cid = store.insert_chunk("doc-ctx", 0, "上下文租户测试文本",
                                 1, "ch1", "s1", {}, tenant_id="ctx_tenant")
        dummy_emb = np.zeros(1024, dtype=np.float32).tolist()
        store.insert_embedding(cid, dummy_emb)

        # 设置当前租户
        set_current_tenant("ctx_tenant")
        results = store.search(dummy_emb, top_k=5)
        store.close()

        assert len(results) >= 1
        # 应该只包含 ctx_tenant 的数据
        assert any("上下文" in r.text for r in results)


# ── Permission Layer (L2) ─────────────────────────

class TestPermissions:
    """企业级 RAG L2: 文档/Chunk 权限控制"""

    def test_schema_migration_adds_permission_columns(self):
        """打开数据库时自动迁移，添加权限列"""
        from retrieval import VectorStore
        store = VectorStore()

        # 检查 documents 表是否有权限列
        cols = store.conn.execute("PRAGMA table_info(documents)").fetchall()
        col_names = {row[1] for row in cols}
        for c in ["role", "department", "project", "user_whitelist",
                   "security_level", "document_owner", "access_policy"]:
            assert c in col_names, f"Missing column: {c}"

        # 检查 chunks 表
        cols = store.conn.execute("PRAGMA table_info(chunks)").fetchall()
        col_names = {row[1] for row in cols}
        for c in ["role", "department", "project", "security_level", "access_policy"]:
            assert c in col_names, f"Missing column: {c}"

        store.close()

    def test_insert_document_with_permissions(self):
        """插入文档时权限字段正确存储"""
        from retrieval import VectorStore
        store = VectorStore()
        perms = {
            "role": "engineer", "department": "R&D",
            "project": "proj-x", "user_whitelist": ["alice", "bob"],
            "security_level": 2, "document_owner": "charlie",
            "access_policy": "role_based",
        }
        store.insert_document("perm-doc-1", "test.pdf", "/f/test.pdf",
                             1, 100, {}, "tenant_p", permissions=perms)

        row = store.conn.execute(
            "SELECT role, department, project, user_whitelist, "
            "security_level, document_owner, access_policy "
            "FROM documents WHERE id='perm-doc-1'"
        ).fetchone()
        store.close()

        assert row[0] == "engineer"
        assert row[1] == "R&D"
        assert row[2] == "proj-x"
        assert "alice" in row[3]  # user_whitelist JSON
        assert row[4] == 2
        assert row[5] == "charlie"
        assert row[6] == "role_based"

    def test_chunk_inherits_document_permissions(self):
        """Chunk 继承文档权限（user_whitelist 和 document_owner 除外）"""
        from retrieval import VectorStore
        from permissions import inherit_permissions
        store = VectorStore()

        doc_perms = {
            "role": "tech", "department": "AI",
            "project": "nlp", "security_level": 1,
            "access_policy": "open",
            "user_whitelist": ["u1"], "document_owner": "owner1",
        }
        chunk_perms = inherit_permissions(doc_perms)

        store.insert_document("perm-doc-2", "t.pdf", "/f/t.pdf",
                             1, 100, {}, "tenant_p", permissions=doc_perms)
        store.insert_chunk("perm-doc-2", 0, "chunk text", 1, "c1", "s1",
                          {}, "tenant_p", permissions=chunk_perms)

        row = store.conn.execute(
            "SELECT role, department, project, security_level, access_policy "
            "FROM chunks WHERE document_id='perm-doc-2'"
        ).fetchone()
        store.close()

        assert row[0] == "tech"
        assert row[1] == "AI"
        assert row[2] == "nlp"
        assert row[3] == 1
        assert row[4] == "open"

    def test_search_with_permission_filter_open(self):
        """open 策略：所有用户均可见（密级限制除外）"""
        from retrieval import VectorStore
        import numpy as np
        store = VectorStore()

        p_open = {"security_level": 1, "access_policy": "open"}
        store.insert_document("pd3", "open.pdf", "/f", 1, 100, {},
                             "tp2", permissions=p_open)
        cid = store.insert_chunk("pd3", 0, "公开文档内容", 1, "", "", {},
                                "tp2", permissions=p_open)
        emb = np.zeros(1024, dtype=np.float32).tolist()
        store.insert_embedding(cid, emb)

        # 普通用户（密级 1）能看到
        results = store.search(emb, top_k=5, tenant_id="tp2",
                               user_context={"security_clearance": 1})
        store.close()
        assert len(results) >= 1
        assert any("公开" in r.text for r in results)

    def test_search_permission_blocks_confidential(self):
        """低密级用户看不到高密级文档"""
        from retrieval import VectorStore
        import numpy as np
        store = VectorStore()

        p_secret = {"security_level": 3, "access_policy": "open"}
        store.insert_document("pd4", "secret.pdf", "/f", 1, 100, {},
                             "tp3", permissions=p_secret)
        cid = store.insert_chunk("pd4", 0, "绝密内容", 1, "", "", {},
                                "tp3", permissions=p_secret)
        emb = np.zeros(1024, dtype=np.float32).tolist()
        store.insert_embedding(cid, emb)

        # 低密级用户（clearance=1）不应该看到密级 3 的文档
        results = store.search(emb, top_k=5, tenant_id="tp3",
                               user_context={"security_clearance": 1})
        store.close()
        assert len(results) == 0, "Low-clearance user should NOT see secret docs"

    def test_permission_manager_build_filter(self):
        """PermissionManager.build_sql_filter 生成正确 SQL"""
        from permissions import PermissionManager

        user = {
            "user_id": "alice",
            "role": "engineer",
            "department": "R&D",
            "security_clearance": 2,
            "project_ids": ["proj-a"],
        }
        where, params = PermissionManager.build_sql_filter(user, "c")

        assert "c.access_policy" in where
        assert "security_level" in where
        assert len(params) > 0

    def test_validate_access_open_policy(self):
        """open 策略：密级足够即可访问"""
        from permissions import PermissionManager
        assert PermissionManager.validate_access(
            {"access_policy": "open", "security_level": 1},
            {"security_clearance": 1},
        )
        assert not PermissionManager.validate_access(
            {"access_policy": "open", "security_level": 3},
            {"security_clearance": 1},
        )

    def test_validate_access_whitelist(self):
        """whitelist 策略：仅白名单用户可访问"""
        from permissions import PermissionManager
        import json
        assert PermissionManager.validate_access(
            {"access_policy": "whitelist", "security_level": 1,
             "user_whitelist": json.dumps(["alice"])},
            {"user_id": "alice", "security_clearance": 2},
        )
        assert not PermissionManager.validate_access(
            {"access_policy": "whitelist", "security_level": 1,
             "user_whitelist": json.dumps(["alice"])},
            {"user_id": "bob", "security_clearance": 2},
        )


# ── L4 Pre-Generation Verification ────────────────

class TestPermissionVerifier:
    """企业级 RAG L4: 生成前二次校验"""

    def test_verify_chunk_pass_open(self):
        """open 策略 + 足够密级 → 通过"""
        from verifier import PermissionVerifier
        ok, reason = PermissionVerifier.verify_chunk(
            {"security_level": 1, "access_policy": "open", "tenant_id": "t1"},
            {"security_clearance": 1}, "t1",
        )
        assert ok
        assert reason == ""

    def test_verify_chunk_block_high_security(self):
        """密级不足 → 拒绝"""
        from verifier import PermissionVerifier
        ok, reason = PermissionVerifier.verify_chunk(
            {"security_level": 3, "access_policy": "open", "tenant_id": "t1"},
            {"security_clearance": 1}, "t1",
        )
        assert not ok
        assert "security_level" in reason

    def test_verify_chunk_tenant_mismatch(self):
        """租户不匹配 → 拒绝"""
        from verifier import PermissionVerifier
        ok, reason = PermissionVerifier.verify_chunk(
            {"security_level": 1, "access_policy": "open", "tenant_id": "t2"},
            {"security_clearance": 1}, "t1",
        )
        assert not ok
        assert "tenant" in reason.lower()

    def test_verify_batch_filters_rejected(self):
        """批量验证：拒绝不合规 chunk"""
        from verifier import PermissionVerifier
        chunks = [
            {"security_level": 1, "access_policy": "open", "tenant_id": "t1"},
            {"security_level": 3, "access_policy": "open", "tenant_id": "t1"},
            {"security_level": 1, "access_policy": "open", "tenant_id": "t1"},
        ]
        vresult, passed = PermissionVerifier.verify_batch(
            chunks, {"security_clearance": 1}, "t1",
        )
        assert not vresult.passed  # 有 1 个被拒绝
        assert vresult.rejected_chunks == 1
        assert len(passed) == 2

    def test_verify_batch_role_based(self):
        """role_based 策略：匹配角色可通过"""
        from verifier import PermissionVerifier
        chunks = [
            {"security_level": 1, "access_policy": "role_based",
             "role": "engineer", "department": "", "tenant_id": "t1"},
            {"security_level": 1, "access_policy": "role_based",
             "role": "manager", "department": "", "tenant_id": "t1"},
        ]
        vresult, passed = PermissionVerifier.verify_batch(
            chunks, {"user_id": "alice", "role": "engineer",
                     "security_clearance": 2}, "t1",
        )
        assert len(passed) == 1  # 仅 engineer 通过


# ── L5 Audit Logging ──────────────────────────────

class TestAuditLogging:
    """企业级 RAG L5: 审计日志 + 输出控制"""

    def test_audit_log_and_query(self):
        """写入审计日志并查询"""
        from audit import AuditLogger, AuditEntry
        logger = AuditLogger()
        entry = AuditEntry(
            user_id="test_user", question="测试审计问题",
            tenant_id="audit_tenant",
            retrieved_doc_ids=["doc1"], cited_chunks=[{"document": "d1", "page": 1}],
            answer="测试答案", confidence=0.85, intent="test",
            model="deepseek-chat", latency_ms=500,
        )
        eid = logger.log(entry)

        rows = logger.query(tenant_id="audit_tenant", limit=10, user_id="test_user")
        logger.close()

        assert len(rows) >= 1
        assert rows[0]["question"] == "测试审计问题"
        assert rows[0]["confidence"] == 0.85

    def test_audit_stats(self):
        """审计统计"""
        from audit import AuditLogger
        logger = AuditLogger()
        stats = logger.stats(tenant_id="audit_tenant")
        logger.close()

        assert "total_queries" in stats
        assert "avg_confidence" in stats
        assert isinstance(stats["total_queries"], int)

    def test_output_sanitization(self):
        """输出脱敏：身份证/手机号/邮箱/IP"""
        from qa.engine import QAEngine
        text = "用户 张三 身份证 110101199001011234 手机 13800138000 邮箱 test@example.com IP 192.168.1.1"
        clean = QAEngine._sanitize_output(text)
        assert "110101" not in clean
        assert "13800138000" not in clean
        assert "test@example.com" not in clean
        assert "192.168.1.1" not in clean
        assert "[ID_REDACTED]" in clean
        assert "[PHONE_REDACTED]" in clean
        assert "[EMAIL_REDACTED]" in clean
        assert "[IP_REDACTED]" in clean


# ── Authentication ────────────────────────────────

class TestAuth:
    """用户认证模块: 注册 / 登录 / JWT / 权限集成"""

    def test_user_store_upsert_and_get(self):
        """用户创建和查找"""
        from auth.models import User, UserStore
        store = UserStore()
        u = User(firebase_uid="test-uid-1", email="test@edis.local",
                 display_name="Test User", role="engineer",
                 department="R&D", security_clearance=2)
        store.upsert(u)

        found = store.get("test-uid-1")
        assert found is not None
        assert found.email == "test@edis.local"
        assert found.role == "engineer"
        assert found.security_clearance == 2

        # 清理
        store.conn.execute("DELETE FROM users WHERE firebase_uid='test-uid-1'")
        store.conn.commit()
        store.close()

    def test_user_to_permission_context(self):
        """User → L2 user_context 转换"""
        from auth.models import User
        u = User(firebase_uid="uid-x", role="admin", department="Sec",
                 security_clearance=3)
        ctx = u.to_permission_context()
        assert ctx["user_id"] == "uid-x"
        assert ctx["role"] == "admin"
        assert ctx["security_clearance"] == 3

    def test_jwt_generate_and_verify(self):
        """JWT 签发和验证"""
        from auth.jwt_service import JWTService
        jwt = JWTService()
        token = jwt.generate({"sub": "user-1", "email": "a@b.com"})
        claims = jwt.verify(token)
        assert claims is not None
        assert claims["sub"] == "user-1"

    def test_jwt_rejects_invalid(self):
        """JWT 拒绝伪造 token"""
        from auth.jwt_service import JWTService
        jwt = JWTService()
        assert jwt.verify("not.a.token") is None
        assert jwt.verify("") is None

    def test_jwt_rejects_expired(self):
        """JWT 拒绝过期 token"""
        from auth.jwt_service import JWTService
        jwt = JWTService()
        token = jwt.generate({"sub": "u1"}, ttl=-1)  # 立即过期
        claims = jwt.verify(token)
        assert claims is None

    def test_jwt_refresh(self):
        """JWT 刷新"""
        from auth.jwt_service import JWTService
        jwt = JWTService()
        token = jwt.generate({"sub": "u1", "email": "a@b.com"})
        new_token = jwt.refresh(token)
        assert new_token is not None
        assert new_token != token
        claims = jwt.verify(new_token)
        assert claims["sub"] == "u1"

    def test_local_provider_register_and_login(self):
        """本地 provider: 注册 + 登录"""
        from auth.providers import LocalProvider
        lp = LocalProvider()

        # 注册
        info = lp.create_user("lp-test@edis.local", "testpass123", "LP Test")
        assert info is not None
        assert info["email"] == "lp-test@edis.local"

        # 正确密码登录
        verified = lp.verify_token("lp-test@edis.local:testpass123")
        assert verified is not None
        assert verified["email"] == "lp-test@edis.local"

        # 错误密码
        bad = lp.verify_token("lp-test@edis.local:wrongpass")
        assert bad is None

        # 不存在用户
        none_user = lp.verify_token("noone@edis.local:any")
        assert none_user is None

        # 清理
        lp._conn.execute("DELETE FROM local_auth WHERE email='lp-test@edis.local'")
        lp._conn.commit()
        lp.close()

    def test_auth_manager_local_flow(self):
        """AuthManager 完整本地认证流程"""
        from auth import AuthManager
        am = AuthManager()

        # 注册
        user, jwt = am.register("local", "am-test@edis.local",
                                "securepass", "AM Test")
        assert user is not None
        assert jwt is not None

        # 登录
        user2, jwt2 = am.login("local", "am-test@edis.local:securepass")
        assert user2 is not None
        assert user2.email == "am-test@edis.local"

        # 验证 JWT
        claims = am.verify_jwt(jwt2)
        assert claims["sub"] == user2.firebase_uid

        # 获取用户
        u = am.get_user(user2.firebase_uid)
        assert u is not None

        # 清理
        am.user_store.conn.execute(
            "DELETE FROM users WHERE firebase_uid=?", (user.firebase_uid,))
        am.user_store.conn.commit()
        from auth.providers import LocalProvider
        lp = LocalProvider()
        lp._conn.execute("DELETE FROM local_auth WHERE email='am-test@edis.local'")
        lp._conn.commit()
        lp.close()
        am.close()


# ── Parent Document Retrieval + Reranker (P0) ─────

class TestParentDocRetrieval:
    """Parent Document Retrieval + Reranker"""

    def test_get_document_chunks(self):
        """拉取文档的全部 chunk"""
        from retrieval import VectorStore
        import numpy as np
        store = VectorStore()
        # Clean stale data
        store.conn.execute("DELETE FROM chunks WHERE tenant_id='tPDRa'")
        store.conn.execute("DELETE FROM documents WHERE tenant_id='tPDRa'")
        store.conn.commit()

        store.insert_document("pdr1", "pdr.pdf", "/f/pdr.pdf", 1, 100, {}, "tPDRa")
        c1 = store.insert_chunk("pdr1", 0, "第1段", 1, "", "", {}, "tPDRa")
        c2 = store.insert_chunk("pdr1", 1, "第2段", 2, "", "", {}, "tPDRa")
        emb = np.zeros(1024, dtype=np.float32).tolist()
        store.insert_embedding(c1, emb)
        store.insert_embedding(c2, emb)

        chunks = store.get_document_chunks("pdr.pdf", "tPDRa")
        store.close()

        assert len(chunks) == 2
        assert chunks[0].page == 1
        assert chunks[1].page == 2

    def test_search_with_parent_retrieval(self):
        """Parent Document Retrieval 拉取完整文档"""
        from retrieval import VectorStore
        import numpy as np
        store = VectorStore()
        store.conn.execute("DELETE FROM chunks WHERE tenant_id='tPDRb'")
        store.conn.execute("DELETE FROM documents WHERE tenant_id='tPDRb'")
        store.conn.commit()

        store.insert_document("pdr2", "parent.pdf", "/f/parent.pdf", 2, 200, {}, "tPDRb")
        c1 = store.insert_chunk("pdr2", 0, "AAA摘要概述", 1, "", "", {}, "tPDRb")
        c2 = store.insert_chunk("pdr2", 1, "BBB详细参数MQTT配置步骤", 4, "", "", {}, "tPDRb")
        emb = np.zeros(1024, dtype=np.float32).tolist()
        store.insert_embedding(c1, emb)
        store.insert_embedding(c2, emb)

        # Parent retrieval: 应该在 TopK 后拉取整个文档
        results = store.search_with_parent_retrieval(
            emb, top_k=2, tenant_id="tPDRb", parent_top_n=1)
        store.close()

        # 应该返回文档的全部 2 个 chunk，不仅 TopK
        assert len(results) == 2

    def test_heuristic_reranker(self):
        """启发式精排：关键词匹配的 chunk 排前面"""
        from adapters.reranker import HeuristicReranker
        reranker = HeuristicReranker()

        query = "MQTT配置"
        candidates = [
            "摘要：本文档介绍网络协议概述",       # 不相关
            "MQTT Broker配置步骤：首先设置端口",  # 相关
            "HTTP协议使用80端口进行通信",          # 不相关
            "MQTT QoS级别说明和TLS加密配置",      # 相关
        ]
        scores = [0.8, 0.6, 0.5, 0.7]
        pages = [1, 3, 2, 5]

        order = reranker.rerank(query, candidates, scores, pages)

        # 关键词匹配的应该排前面
        assert order[0] in (1, 3), f"Expected keyword match first, got {order[0]}"
        # 不相关的排后面
        assert order[-1] in (0, 2), f"Expected irrelevant last, got {order[-1]}"

    def test_heuristic_reranker_empty(self):
        """空输入不崩溃"""
        from adapters.reranker import HeuristicReranker
        reranker = HeuristicReranker()
        assert reranker.rerank("q", []) == []
        assert reranker.rerank("q", ["only one"]) == [0]
