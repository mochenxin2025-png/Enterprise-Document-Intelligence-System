"""额外 Parser — DOCX / Markdown / HTML

注册到 PluginRegistry，格式统一输出 ParsedDoc。
"""
import hashlib
from pathlib import Path
from plugins import PluginRegistry
from interfaces import ParserInterface, ParsedDoc


def _make_pages(text: str) -> list[dict]:
    """将纯文本转为 ParsedDoc pages 格式"""
    # 按双换行分段为粗略的"页"
    paragraphs = text.split("\n\n")
    pages = []
    current_text = ""
    page_num = 1
    for para in paragraphs:
        if len(current_text) + len(para) > 3000 and current_text:
            pages.append({"num": page_num, "text": current_text,
                         "hash": hashlib.sha256(current_text.encode()).hexdigest()[:16]})
            page_num += 1
            current_text = para
        else:
            current_text += ("\n\n" + para) if current_text else para
    if current_text:
        pages.append({"num": page_num, "text": current_text,
                     "hash": hashlib.sha256(current_text.encode()).hexdigest()[:16]})
    return pages


@PluginRegistry.register("parser", "docx")
class DOCXParser(ParserInterface):
    def parse(self, filepath: str) -> ParsedDoc:
        try:
            import docx
            doc = docx.Document(filepath)
            text = "\n\n".join(p.text for p in doc.paragraphs if p.text.strip())
        except ImportError:
            text = f"[DOCX parser requires python-docx: pip install python-docx] File: {filepath}"

        path = Path(filepath)
        return ParsedDoc(
            doc_id=hashlib.sha256(path.read_bytes()).hexdigest()[:16],
            filename=path.name,
            pages=_make_pages(text),
            metadata={"format": "DOCX"},
            page_count=len(_make_pages(text)),
            total_chars=len(text),
        )

    @classmethod
    def supports(cls, filepath: str) -> bool:
        return filepath.lower().endswith(".docx")


@PluginRegistry.register("parser", "markdown")
class MarkdownParser(ParserInterface):
    def parse(self, filepath: str) -> ParsedDoc:
        path = Path(filepath)
        with open(filepath, "r", encoding="utf-8") as f:
            text = f.read()

        pages = _make_pages(text)
        return ParsedDoc(
            doc_id=hashlib.sha256(path.read_bytes()).hexdigest()[:16],
            filename=path.name,
            pages=pages,
            metadata={"format": "Markdown"},
            page_count=len(pages),
            total_chars=len(text),
        )

    @classmethod
    def supports(cls, filepath: str) -> bool:
        return filepath.lower().endswith((".md", ".markdown"))


@PluginRegistry.register("parser", "html")
class HTMLParser(ParserInterface):
    def parse(self, filepath: str) -> ParsedDoc:
        path = Path(filepath)
        with open(filepath, "r", encoding="utf-8") as f:
            html = f.read()

        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(html, "html.parser")
            for tag in soup(["script", "style", "nav", "footer"]):
                tag.decompose()
            text = soup.get_text("\n")
            # 清理多余空行
            import re
            text = re.sub(r'\n{3,}', '\n\n', text)
        except ImportError:
            import re
            text = re.sub(r'<[^>]+>', ' ', html)
            text = re.sub(r'\s+', ' ', text)

        pages = _make_pages(text)
        return ParsedDoc(
            doc_id=hashlib.sha256(path.read_bytes()).hexdigest()[:16],
            filename=path.name,
            pages=pages,
            metadata={"format": "HTML"},
            page_count=len(pages),
            total_chars=len(text),
        )

    @classmethod
    def supports(cls, filepath: str) -> bool:
        return filepath.lower().endswith((".html", ".htm"))


@PluginRegistry.register("parser", "text")
class TextParser(ParserInterface):
    def parse(self, filepath: str) -> ParsedDoc:
        path = Path(filepath)
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            text = f.read()
        pages = _make_pages(text)
        return ParsedDoc(
            doc_id=hashlib.sha256(path.read_bytes()).hexdigest()[:16],
            filename=path.name,
            pages=pages,
            metadata={"format": "Text"},
            page_count=len(pages),
            total_chars=len(text),
        )

    @classmethod
    def supports(cls, filepath: str) -> bool:
        return filepath.lower().endswith((".txt", ".csv", ".json", ".xml", ".log"))
