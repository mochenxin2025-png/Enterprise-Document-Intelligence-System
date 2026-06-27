"""分层分块器 — Document → Chapter → Section → Chunk"""
import re
from dataclasses import dataclass, field

from ingestion import ParsedDocument, ParsedPage, PageBlock


@dataclass
class Chunk:
    """一个文本块，带层级元数据"""
    text: str
    page: int
    chapter: str = ""
    section: str = ""
    chunk_index: int = 0
    metadata: dict = field(default_factory=dict)


class HierarchicalChunker:
    """基于标题检测的层次化分块。"""

    def __init__(self, chunk_size: int = 512, chunk_overlap: int = 64):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

    def chunk(self, doc: ParsedDocument) -> list[Chunk]:
        chunks = []
        current_chapter = doc.filename
        current_section = ""
        chunk_idx = 0

        for page in doc.pages:
            # 在页面内检测标题
            headings = self._detect_headings(page)
            page_text = page.text
            if not page_text.strip():
                continue

            # 更新层级
            for heading, level in headings:
                if level == 1:
                    current_chapter = heading
                    current_section = ""
                elif level == 2:
                    current_section = heading

            # 分块
            page_chunks = self._split_text(page_text)
            for ch_text in page_chunks:
                chunks.append(Chunk(
                    text=ch_text,
                    page=page.page_num,
                    chapter=current_chapter,
                    section=current_section,
                    chunk_index=chunk_idx,
                    metadata={
                        "page": page.page_num,
                        "chapter": current_chapter,
                        "section": current_section,
                        "source": doc.filename,
                    },
                ))
                chunk_idx += 1

        return chunks

    def _detect_headings(self, page: ParsedPage) -> list[tuple[str, int]]:
        """通过字号和加粗检测标题。level 1 = 章, level 2 = 节。"""
        headings = []
        if not page.blocks:
            # 回退：正则匹配编号标题
            for line in page.text.split("\n"):
                line = line.strip()
                if re.match(r'^(第[一二三四五六七八九十\d]+章|Chapter\s+\d+)', line):
                    headings.append((line, 1))
                elif re.match(r'^(\d+\.\d+|\d+\.\d+\.\d+|\d{2,3}-\d{2,4})\s', line):
                    headings.append((line, 2))
            return headings

        # 基于字号的标题检测
        font_sizes = [b.font_size for b in page.blocks if b.font_size > 0]
        if not font_sizes:
            return headings

        # 正文字号 = 中位数，标题 = 显著大于正文
        body_size = sorted(font_sizes)[len(font_sizes) // 2]
        threshold = body_size * 1.3

        for block in page.blocks:
            if block.font_size >= threshold and block.text.strip():
                level = 1 if block.is_bold or block.font_size >= body_size * 1.6 else 2
                headings.append((block.text.strip(), level))

        return headings

    def _split_text(self, text: str) -> list[str]:
        """滑动窗口分块"""
        if len(text) <= self.chunk_size:
            return [text] if text.strip() else []

        chunks = []
        start = 0
        while start < len(text):
            end = min(start + self.chunk_size, len(text))
            # 尽量在句末或段末断开
            if end < len(text):
                for sep in ["\n\n", "\n", "。", ". ", " "]:
                    pos = text.rfind(sep, start, end)
                    if pos > start + self.chunk_size // 2:
                        end = pos + len(sep)
                        break
            chunks.append(text[start:end])
            # 到达末尾就停止，不再 overlap
            if end >= len(text):
                break
            start = end - self.chunk_overlap

        return chunks
