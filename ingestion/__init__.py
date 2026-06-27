"""PDF 解析器 — 将工程 PDF 转为结构化页面列表"""
import hashlib
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional

import fitz  # pymupdf


@dataclass
class PageBlock:
    """页面中的一个文本块"""
    text: str
    bbox: tuple[float, float, float, float]  # (x0, y0, x1, y1)
    block_type: str = "text"  # text | image | table
    font_size: float = 0.0
    is_bold: bool = False


@dataclass
class ParsedPage:
    """单页解析结果"""
    page_num: int
    width: float
    height: float
    text: str                        # 全页纯文本
    blocks: list[PageBlock] = field(default_factory=list)
    images: list[bytes] = field(default_factory=list)
    tables: list[list[list[str]]] = field(default_factory=list)
    hash: str = ""


@dataclass
class ParsedDocument:
    """文档解析结果"""
    path: Path
    filename: str
    pages: list[ParsedPage] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)
    page_count: int = 0
    total_chars: int = 0

    @property
    def document_id(self) -> str:
        return hashlib.sha256(self.path.read_bytes()).hexdigest()[:16]


class PDFParser:
    """解析工程 PDF，提取文本、坐标、表格、图片。"""

    def __init__(self, ocr_enabled: bool = False):
        self.ocr_enabled = ocr_enabled

    def parse(self, filepath: str | Path) -> ParsedDocument:
        filepath = Path(filepath)
        if not filepath.exists():
            raise FileNotFoundError(f"PDF not found: {filepath}")

        doc = fitz.open(str(filepath))
        parsed = ParsedDocument(
            path=filepath,
            filename=filepath.name,
            metadata={
                "title": doc.metadata.get("title", ""),
                "author": doc.metadata.get("author", ""),
                "format": doc.metadata.get("format", "PDF"),
            },
        )

        for page_idx in range(len(doc)):
            page = doc[page_idx]
            parsed_page = self._parse_page(page, page_idx)
            parsed.pages.append(parsed_page)

        parsed.page_count = len(parsed.pages)
        parsed.total_chars = sum(len(p.text) for p in parsed.pages)
        doc.close()
        return parsed

    def _parse_page(self, page: fitz.Page, page_idx: int) -> ParsedPage:
        rect = page.rect
        parsed = ParsedPage(
            page_num=page_idx + 1,
            width=rect.width,
            height=rect.height,
            text="",
        )

        # 提取文本块（带坐标和字体信息）
        blocks = page.get_text("dict")["blocks"]
        text_lines = []
        all_blocks = []

        for block in blocks:
            if block["type"] == 0:  # 文本块
                block_text = ""
                block_fonts = []
                block_bbox = block["bbox"]

                for line in block.get("lines", []):
                    for span in line.get("spans", []):
                        block_text += span["text"]
                        block_fonts.append(span.get("size", 0))

                if block_text.strip():
                    avg_font = sum(block_fonts) / len(block_fonts) if block_fonts else 0
                    is_bold = any("Bold" in span.get("font", "") for line in block.get("lines", []) for span in line.get("spans", []))
                    all_blocks.append(PageBlock(
                        text=block_text.strip(),
                        bbox=tuple(block_bbox),
                        font_size=round(avg_font, 1),
                        is_bold=is_bold,
                    ))
                    text_lines.append(block_text.strip())

            elif block["type"] == 1:  # 图片块
                all_blocks.append(PageBlock(
                    text="[IMAGE]",
                    bbox=tuple(block["bbox"]),
                    block_type="image",
                ))
                # 提取图片字节
                try:
                    for img_info in block.get("images", []):
                        base_image = page.parent.extract_image(img_info[0])
                        parsed.images.append(base_image["image"])
                except Exception:
                    pass

        parsed.text = "\n".join(text_lines)
        parsed.blocks = all_blocks

        # 页面指纹
        parsed.hash = hashlib.sha256(parsed.text.encode()).hexdigest()[:16]

        # 提取表格
        parsed.tables = self._extract_tables(page)

        return parsed

    def _extract_tables(self, page: fitz.Page) -> list[list[list[str]]]:
        """使用 pymupdf 内置表格检测"""
        try:
            tabs = page.find_tables()
            if tabs and tabs.tables:
                return [tab.extract() for tab in tabs.tables]
        except Exception:
            pass
        return []


def parse_pdf(filepath: str | Path, ocr: bool = False) -> ParsedDocument:
    """快捷函数"""
    return PDFParser(ocr_enabled=ocr).parse(filepath)
