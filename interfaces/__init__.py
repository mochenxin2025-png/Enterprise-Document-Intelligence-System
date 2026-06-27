"""EDIS Interface Layer — 所有可替换组件的抽象基类

原则: 任何模块依赖接口而非具体实现。换模型/换存储/换解析器只需改 config + adapter。
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional


# ── LLM Interface ─────────────────────────────

@dataclass
class LLMResponse:
    content: str
    model: str = ""
    usage: dict = field(default_factory=dict)
    raw: dict = field(default_factory=dict)


class LLMInterface(ABC):
    """LLM 推理抽象"""

    @abstractmethod
    def chat(self, messages: list[dict], **kwargs) -> LLMResponse:
        """发送对话消息，返回 LLMResponse"""
        ...

    @property
    @abstractmethod
    def model_name(self) -> str:
        ...


# ── Embedding Interface ────────────────────────

class EmbeddingInterface(ABC):
    """文本向量化抽象"""

    @abstractmethod
    def encode(self, texts: list[str], **kwargs) -> list[list[float]]:
        """编码文本列表 → 向量列表"""
        ...

    @abstractmethod
    def encode_query(self, query: str) -> list[float]:
        """编码查询文本（可加前缀）"""
        ...

    @property
    @abstractmethod
    def dimension(self) -> int:
        ...


# ── Parser Interface ───────────────────────────

@dataclass
class ParsedDoc:
    """统一解析结果"""
    doc_id: str = ""
    filename: str = ""
    pages: list[dict] = field(default_factory=list)    # [{num, text, blocks, images, tables, hash}]
    metadata: dict = field(default_factory=dict)
    page_count: int = 0
    total_chars: int = 0


class ParserInterface(ABC):
    """文档解析抽象"""

    @abstractmethod
    def parse(self, filepath: str) -> ParsedDoc:
        """解析文件 → ParsedDoc"""
        ...

    @classmethod
    @abstractmethod
    def supports(cls, filepath: str) -> bool:
        """检查是否支持该文件格式"""
        ...


# ── VectorStore Interface ──────────────────────

@dataclass
class SearchHit:
    chunk_id: int
    text: str
    score: float
    page: int
    metadata: dict = field(default_factory=dict)


class VectorStoreInterface(ABC):
    """向量存储抽象"""

    @abstractmethod
    def add(self, chunks: list[dict], embeddings: list[list[float]], doc_id: str):
        """批量写入 chunk + embedding"""
        ...

    @abstractmethod
    def search(self, query_embedding: list[float], top_k: int = 10) -> list[SearchHit]:
        """语义检索"""
        ...

    @abstractmethod
    def delete_document(self, doc_id: str):
        """删除文档所有 chunk"""
        ...


# ── OCR Interface ──────────────────────────────

class OCRInterface(ABC):
    """OCR 抽象"""

    @abstractmethod
    def extract(self, image_bytes: bytes) -> str:
        """从图片字节提取文字"""
        ...


# ── Reranker Interface ─────────────────────────

class RerankerInterface(ABC):
    """精排抽象"""

    @abstractmethod
    def rerank(self, query: str, candidates: list[str]) -> list[int]:
        """返回最相关候选的索引列表（降序）"""
        ...
