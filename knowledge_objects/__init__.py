"""Knowledge Objects — 多模态统一知识对象

从"所有内容都是文本 chunk"升级为"文本/表格/图示/OCR区域各有专门对象"。
"""

from dataclasses import dataclass, field
from typing import Optional


# ── Base ────────────────────────────────────────

@dataclass
class KnowledgeObject:
    """所有知识对象的基类"""
    object_id: str = ""
    page: int = 0
    bbox: tuple = ()          # (x0, y0, x1, y1) on page
    confidence: float = 0.0
    metadata: dict = field(default_factory=dict)

    def object_type(self) -> str:
        return "unknown"


# ── Text Block ──────────────────────────────────

@dataclass
class TextBlock(KnowledgeObject):
    """纯文本块 — 替代传统 chunk"""
    text: str = ""
    section: str = ""
    chapter: str = ""
    chunk_index: int = 0

    def object_type(self) -> str:
        return "text"


# ── Table Block ─────────────────────────────────

@dataclass
class TableBlock(KnowledgeObject):
    """表格块 — 结构化数据"""
    raw_cells: list[list[str]] = field(default_factory=list)
    rows: int = 0
    cols: int = 0
    caption: str = ""
    title: str = ""
    normalized_rows: list[list[str]] = field(default_factory=list)

    def object_type(self) -> str:
        return "table"

    def to_markdown(self) -> str:
        """输出为 Markdown 表格"""
        if not self.normalized_rows:
            return ""
        lines = []
        headers = self.normalized_rows[0] if self.normalized_rows else []
        if headers:
            lines.append("| " + " | ".join(str(c) for c in headers) + " |")
            lines.append("| " + " | ".join("---" for _ in headers) + " |")
        for row in self.normalized_rows[1:]:
            lines.append("| " + " | ".join(str(c) for c in row) + " |")
        return "\n".join(lines)


# ── Figure Block ────────────────────────────────

@dataclass
class FigureBlock(KnowledgeObject):
    """图片/插图块"""
    image_path: str = ""
    caption: str = ""
    vision_summary: str = ""       # 视觉模型描述

    def object_type(self) -> str:
        return "figure"


# ── Diagram Block ───────────────────────────────

@dataclass
class DiagramBlock(KnowledgeObject):
    """图示块 — 流程图/结构图/工程图"""
    image_path: str = ""
    ocr_labels: list[str] = field(default_factory=list)
    detected_relations: list[dict] = field(default_factory=list)
    diagram_type: str = ""          # flowchart / architecture / schematic
    explanation: str = ""            # 图示文字解释

    def object_type(self) -> str:
        return "diagram"


# ── OCR Region ──────────────────────────────────

@dataclass
class OCRRegion(KnowledgeObject):
    """OCR 识别区域"""
    text: str = ""
    ocr_confidence: float = 0.0

    def object_type(self) -> str:
        return "ocr_region"


# ── Factory ─────────────────────────────────────

def create_knowledge_object(obj_type: str, **kwargs) -> KnowledgeObject:
    """工厂方法：按类型创建知识对象"""
    mapping = {
        "text": TextBlock,
        "table": TableBlock,
        "figure": FigureBlock,
        "diagram": DiagramBlock,
        "ocr_region": OCRRegion,
    }
    cls = mapping.get(obj_type, TextBlock)
    return cls(**kwargs)
