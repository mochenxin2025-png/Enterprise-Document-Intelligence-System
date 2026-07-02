"""Knowledge Objects — 统一知识对象层

从"所有内容都是文本 chunk"升级为"不同类型走不同处理链"。

五大对象类型:
  TextBlock    — 纯文本段落
  TableBlock   — 表格数据
  FigureBlock  — 图片/截图
  DiagramBlock — 流程图/结构图
  OCRRegion    — OCR 识别的区域
"""
from dataclasses import dataclass, field
from typing import Optional


# ── Base ─────────────────────────────────────────

@dataclass
class KnowledgeObject:
    """知识对象基类"""
    obj_type: str = "unknown"
    page: int = 0
    section: str = ""
    source: str = ""
    confidence: float = 1.0
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "type": self.obj_type,
            "page": self.page,
            "section": self.section,
            "source": self.source,
            "confidence": self.confidence,
        }

    def to_searchable_text(self) -> str:
        """转为可检索文本（用于 embedding）"""
        return ""


# ── TextBlock ────────────────────────────────────

@dataclass
class TextBlock(KnowledgeObject):
    """纯文本段落"""
    text: str = ""
    chunk_id: int = 0
    chapter: str = ""

    def __post_init__(self):
        self.obj_type = "text"

    def to_searchable_text(self) -> str:
        return self.text

    def to_dict(self) -> dict:
        d = super().to_dict()
        d.update({"text": self.text[:500], "chapter": self.chapter})
        return d


# ── TableBlock ───────────────────────────────────

@dataclass
class TableBlock(KnowledgeObject):
    """表格数据"""
    caption: str = ""
    headers: list[str] = field(default_factory=list)
    rows: list[list[str]] = field(default_factory=list)
    raw_text: str = ""

    def __post_init__(self):
        self.obj_type = "table"

    @property
    def row_count(self) -> int:
        return len(self.rows)

    def to_markdown(self) -> str:
        """转为 Markdown 表格"""
        if not self.headers and not self.rows:
            return ""
        lines = []
        h = self.headers or [f"Col{i}" for i in range(len(self.rows[0]) if self.rows else 1)]
        lines.append("| " + " | ".join(h) + " |")
        lines.append("| " + " | ".join(["---"] * len(h)) + " |")
        for row in self.rows[:50]:
            padded = row + [""] * (len(h) - len(row))
            lines.append("| " + " | ".join(padded[:len(h)]) + " |")
        return "\n".join(lines)

    def to_searchable_text(self) -> str:
        return f"{self.caption}\n{self.to_markdown()}"

    def to_dict(self) -> dict:
        d = super().to_dict()
        d.update({
            "caption": self.caption,
            "headers": self.headers,
            "row_count": self.row_count,
        })
        return d


# ── FigureBlock ──────────────────────────────────

@dataclass
class FigureBlock(KnowledgeObject):
    """图片/截图"""
    image_path: str = ""
    caption: str = ""
    bbox: tuple = ()           # (x0, y0, x1, y1)
    vision_summary: str = ""   # 视觉模型生成的描述

    def __post_init__(self):
        self.obj_type = "figure"

    def to_searchable_text(self) -> str:
        return f"{self.caption} {self.vision_summary}"

    def to_dict(self) -> dict:
        d = super().to_dict()
        d.update({
            "caption": self.caption,
            "has_vision_summary": bool(self.vision_summary),
        })
        return d


# ── DiagramBlock ─────────────────────────────────

@dataclass
class DiagramBlock(KnowledgeObject):
    """流程图/结构图/工程示意图"""
    image_path: str = ""
    ocr_labels: list[str] = field(default_factory=list)
    detected_relations: list[dict] = field(default_factory=list)  # [{from, to, type}]
    diagram_explanation: str = ""

    def __post_init__(self):
        self.obj_type = "diagram"

    def to_searchable_text(self) -> str:
        labels = ", ".join(self.ocr_labels)
        return f"Diagram: {labels}\n{self.diagram_explanation}"

    def to_dict(self) -> dict:
        d = super().to_dict()
        d.update({
            "labels": self.ocr_labels[:10],
            "relations_count": len(self.detected_relations),
        })
        return d


# ── OCRRegion ────────────────────────────────────

@dataclass
class OCRRegion(KnowledgeObject):
    """OCR 识别的文字区域"""
    bbox: tuple = ()            # (x0, y0, x1, y1)
    ocr_text: str = ""
    ocr_confidence: float = 0.0

    def __post_init__(self):
        self.obj_type = "ocr"
        self.confidence = self.ocr_confidence

    def to_searchable_text(self) -> str:
        return self.ocr_text

    def to_dict(self) -> dict:
        d = super().to_dict()
        d.update({"text": self.ocr_text[:200]})
        return d


# ── Parsed Document (upgraded) ───────────────────

@dataclass
class RichDocument:
    """增强版文档 — 包含多种知识对象"""
    doc_id: str = ""
    filename: str = ""
    page_count: int = 0
    objects: list[KnowledgeObject] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)

    @property
    def text_blocks(self) -> list[TextBlock]:
        return [o for o in self.objects if isinstance(o, TextBlock)]

    @property
    def table_blocks(self) -> list[TableBlock]:
        return [o for o in self.objects if isinstance(o, TableBlock)]

    @property
    def figure_blocks(self) -> list[FigureBlock]:
        return [o for o in self.objects if isinstance(o, FigureBlock)]

    @property
    def diagram_blocks(self) -> list[DiagramBlock]:
        return [o for o in self.objects if isinstance(o, DiagramBlock)]

    def stats(self) -> dict:
        return {
            "doc_id": self.doc_id,
            "filename": self.filename,
            "pages": self.page_count,
            "text_blocks": len(self.text_blocks),
            "tables": len(self.table_blocks),
            "figures": len(self.figure_blocks),
            "diagrams": len(self.diagram_blocks),
        }
