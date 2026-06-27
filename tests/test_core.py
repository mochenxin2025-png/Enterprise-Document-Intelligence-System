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
