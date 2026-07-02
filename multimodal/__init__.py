"""Multimodal Layer — page classifier, modality router, interpreters, vision adapter

从"所有内容尽量转文本"升级为"按内容类型选择最佳处理链"。
"""

import re
from dataclasses import dataclass
from typing import Optional
from knowledge_objects import (
    KnowledgeObject, TextBlock, TableBlock, FigureBlock,
    DiagramBlock, OCRRegion, create_knowledge_object,
)


# ── Page Classifier ─────────────────────────────

@dataclass
class PageClassification:
    """页面分类结果"""
    page_num: int
    modality: str           # "text" | "table" | "figure" | "diagram" | "ocr"
    confidence: float
    text_density: float     # 文字覆盖率 0-1
    table_ratio: float      # 表格结构占比 0-1
    figure_ratio: float     # 图片区域占比 0-1
    has_diagram_elements: bool  # 是否有箭头/框线/连接线


class PageClassifier:
    """页面模态分类器 — 判断页面属于哪种类型"""

    def classify(self, page_num: int, text: str,
                 blocks: list[dict] = None,
                 images: list[dict] = None) -> PageClassification:
        """根据页面内容判断模态类型"""
        blocks = blocks or []
        images = images or []

        # 文字密度
        total_chars = len(text)
        text_density = min(1.0, total_chars / 2000)  # 2000 chars = full text page

        # 表格占比（检测 | 分隔符，网格对齐的文本）
        table_lines = len(re.findall(r'\|.+\|', text))
        table_ratio = min(1.0, table_lines / max(1, len(text.split('\n'))))

        # 图片占比
        figure_ratio = min(1.0, len(images) / 3) if images else 0.0

        # 图示检测（箭头、框线关键词）
        diagram_keywords = ['流程图', '架构', '拓扑', '箭头', '→', '↓', '框图',
                           'flowchart', 'diagram', 'architecture']
        has_diagram = any(kw in text.lower() for kw in diagram_keywords)

        # 路由决策
        if table_ratio > 0.15:
            modality = "table"
            confidence = table_ratio
        elif figure_ratio > 0.3 and has_diagram:
            modality = "diagram"
            confidence = 0.7
        elif figure_ratio > 0.3:
            modality = "figure"
            confidence = figure_ratio
        elif text_density < 0.05:
            modality = "ocr"
            confidence = 0.5
        else:
            modality = "text"
            confidence = text_density

        return PageClassification(
            page_num=page_num, modality=modality,
            confidence=min(confidence, 1.0),
            text_density=text_density, table_ratio=table_ratio,
            figure_ratio=figure_ratio, has_diagram_elements=has_diagram,
        )


# ── Modality Router ─────────────────────────────

class ModalityRouter:
    """模态路由器 — 按页面类型走不同处理链

    输入: 页面内容
    输出: KnowledgeObject 列表（TextBlock/TableBlock/FigureBlock/...）
    """

    def __init__(self):
        self.classifier = PageClassifier()

    def route_page(self, page_num: int, text: str,
                   blocks: list[dict] = None,
                   images: list[dict] = None) -> list[KnowledgeObject]:
        """路由单个页面 → 返回该页面的知识对象列表"""
        classification = self.classifier.classify(
            page_num, text, blocks, images)

        objects = []

        if classification.modality == "text":
            objects.append(TextBlock(
                object_id=f"p{page_num}_text",
                page=page_num, text=text,
                confidence=classification.confidence,
            ))

        elif classification.modality == "table":
            # 尝试提取表格
            tables = self._extract_tables(text, page_num)
            objects.extend(tables)
            # 剩余文本也保留
            if text.strip():
                objects.append(TextBlock(
                    object_id=f"p{page_num}_text",
                    page=page_num, text=text,
                    confidence=0.5,
                ))

        elif classification.modality == "figure":
            for img in (images or []):
                objects.append(FigureBlock(
                    object_id=f"p{page_num}_fig",
                    page=page_num,
                    image_path=img.get("path", ""),
                    caption=img.get("caption", ""),
                    confidence=classification.confidence,
                ))

        elif classification.modality == "diagram":
            objects.append(DiagramBlock(
                object_id=f"p{page_num}_diag",
                page=page_num,
                image_path=(images[0].get("path", "") if images else ""),
                diagram_type="unknown",
                confidence=classification.confidence,
            ))

        elif classification.modality == "ocr":
            objects.append(OCRRegion(
                object_id=f"p{page_num}_ocr",
                page=page_num, text=text,
                ocr_confidence=classification.confidence,
            ))

        return objects

    @staticmethod
    def _extract_tables(text: str, page_num: int) -> list[TableBlock]:
        """从文本中提取表格结构"""
        tables = []
        lines = text.split('\n')
        table_lines = []
        in_table = False

        for line in lines:
            if '|' in line and line.count('|') >= 2:
                table_lines.append(line)
                in_table = True
            elif in_table and table_lines:
                # 表格结束
                cells = []
                for tl in table_lines:
                    row = [c.strip() for c in tl.split('|')[1:-1]]
                    if any(c for c in row):
                        cells.append(row)
                if cells:
                    tables.append(TableBlock(
                        object_id=f"p{page_num}_tbl{len(tables)}",
                        page=page_num,
                        raw_cells=cells,
                        rows=len(cells),
                        cols=len(cells[0]) if cells else 0,
                        normalized_rows=cells,
                    ))
                table_lines = []
                in_table = False

        if table_lines:
            cells = []
            for tl in table_lines:
                row = [c.strip() for c in tl.split('|')[1:-1]]
                if any(c for c in row):
                    cells.append(row)
            if cells:
                tables.append(TableBlock(
                    object_id=f"p{page_num}_tbl{len(tables)}",
                    page=page_num, raw_cells=cells,
                    rows=len(cells),
                    cols=len(cells[0]) if cells else 0,
                    normalized_rows=cells,
                ))

        return tables


# ── Interpreter stubs ───────────────────────────

class TableInterpreter:
    """表格解释器 — 结构恢复、无边框表格修复"""

    @staticmethod
    def normalize(table: TableBlock) -> TableBlock:
        """行列归一化"""
        if not table.raw_cells:
            return table
        max_cols = max(len(row) for row in table.raw_cells)
        normalized = []
        for row in table.raw_cells:
            normalized.append(row + [''] * (max_cols - len(row)))
        table.normalized_rows = normalized
        table.rows = len(normalized)
        table.cols = max_cols
        return table

    @staticmethod
    def to_text(table: TableBlock) -> str:
        """表格转为可检索文本"""
        parts = []
        if table.caption:
            parts.append(f"[表格] {table.caption}")
        parts.append(table.to_markdown())
        return "\n".join(parts)


class DiagramInterpreter:
    """图示解释器 — 视觉信息转结构化描述

    当前为 stub，后续可接入视觉模型进行深层理解。
    """

    @staticmethod
    def basic_analysis(diagram: DiagramBlock) -> str:
        """基于 OCR 标签的初步分析"""
        parts = [f"[图示] Page {diagram.page}"]
        if diagram.diagram_type:
            parts.append(f"类型: {diagram.diagram_type}")
        if diagram.ocr_labels:
            parts.append("标签: " + ", ".join(diagram.ocr_labels))
        if diagram.explanation:
            parts.append(diagram.explanation)
        return "\n".join(parts)


# ── Vision Adapter ──────────────────────────────

class VisionAdapter:
    """统一视觉模型调用接口

    对接 MiniMax / GPT-4V / Claude Vision 等视觉模型。
    """

    def __init__(self, provider: str = None):
        """
        provider: 视觉模型提供商。None=自动选择（优先 minimax）。
        """
        self.provider = provider or self._detect_provider()

    @staticmethod
    def _detect_provider() -> str:
        import os
        if os.environ.get("DEEPSEEK_API_KEY"):
            return "deepseek"    # DeepSeek supports vision via API
        if os.environ.get("MINIMAX_API_KEY"):
            return "minimax"
        return "none"

    def describe_image(self, image_path: str, prompt: str = "") -> Optional[str]:
        """让视觉模型描述图片内容"""
        if self.provider == "none":
            return None

        try:
            if self.provider == "minimax":
                return self._minimax_vision(image_path, prompt)
            if self.provider == "deepseek":
                return self._deepseek_vision(image_path, prompt)
        except Exception:
            return None

        return None

    def _minimax_vision(self, image_path: str, prompt: str) -> str:
        import os, httpx, base64
        with open(image_path, "rb") as f:
            img_b64 = base64.b64encode(f.read()).decode()

        resp = httpx.post(
            "https://api.minimax.chat/v1/text/chatcompletion_v2",
            headers={
                "Authorization": f"Bearer {os.environ.get('MINIMAX_API_KEY', '')}",
                "Content-Type": "application/json",
            },
            json={
                "model": "abab6.5s-chat",
                "messages": [{"role": "user", "content": [
                    {"type": "text", "text": prompt or "描述这张图片的内容"},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img_b64}"}},
                ]}],
            },
            timeout=60,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]

    def _deepseek_vision(self, image_path: str, prompt: str) -> str:
        import os, httpx, base64
        with open(image_path, "rb") as f:
            img_b64 = base64.b64encode(f.read()).decode()

        resp = httpx.post(
            "https://api.deepseek.com/chat/completions",
            headers={
                "Authorization": f"Bearer {os.environ.get('DEEPSEEK_API_KEY', '')}",
                "Content-Type": "application/json",
            },
            json={
                "model": "deepseek-chat",
                "messages": [{"role": "user", "content": [
                    {"type": "text", "text": prompt or "描述这张图片的内容"},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img_b64}"}},
                ]}],
            },
            timeout=60,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]
