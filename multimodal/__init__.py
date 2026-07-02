"""Multimodal Processing — 页面分类、模态路由、视觉理解

核心:
  - PageClassifier: 判断页面属于 text/table/figure/diagram/ocr
  - ModalityRouter: 根据分类结果选择处理链
  - VisionAdapter: 统一视觉模型调用接口
"""
import re
from dataclasses import dataclass
from typing import Optional


# ── Page Classifier ──────────────────────────────

class PageClassifier:
    """判断页面模态类型

    规则（无 LLM 依赖，纯启发式）:
      - 文字密度 > 50% → text
      - 表格行占比 > 20% → table
      - 图片占比 > 30%、文字少 → figure
      - OCR 置信度低 → ocr
    """

    TEXT_DENSITY_MIN = 0.3      # 文字占比下限（低于此可能是图片页）
    TABLE_ROW_RATIO = 0.2       # 表格行占比
    IMAGE_AREA_RATIO = 0.3      # 图片面积占比

    @classmethod
    def classify(cls, page_text: str, has_images: bool = False,
                  image_count: int = 0, ocr_confidence: float = 1.0,
                  table_rows: int = 0, total_lines: int = 0) -> str:
        """返回: text | table | figure | diagram | ocr"""
        lines = [l for l in page_text.split("\n") if l.strip()]
        total = max(len(lines), 1)

        # OCR 低置信度 → ocr route
        if ocr_confidence < 0.6:
            return "ocr"

        # 表格特征
        if table_rows > 0 and table_rows / max(total, 1) > cls.TABLE_ROW_RATIO:
            # 检测是否有图示特征（箭头、框线字符）
            if cls._has_diagram_chars(page_text):
                return "diagram"
            return "table"

        # 图片多、文字少 → figure
        if has_images and image_count > 0:
            text_chars = sum(1 for c in page_text if c.isalnum() or '\u4e00' <= c <= '\u9fff')
            text_len = max(len(page_text), 1)
            if text_len < 50 or text_chars / text_len < cls.TEXT_DENSITY_MIN:
                return "figure"

        # 默认 → text
        return "text"

    @staticmethod
    def _has_diagram_chars(text: str) -> bool:
        """检测流程图的字符特征: ─ │ ┌ ┐ └ ┘ ├ ┤ ┬ ┴ ┼ → ← ↑ ↓"""
        diagram_chars = set("─│┌┐└┘├┤┬┴┼→←↑↓▸▪◆○●□■△▲")
        count = sum(1 for c in text if c in diagram_chars)
        return count > 5


# ── Modality Router ──────────────────────────────

@dataclass
class ModalityRoute:
    """模态路由结果"""
    modality: str               # text | table | figure | diagram | ocr
    confidence: float
    reason: str = ""


class ModalityRouter:
    """模态路由器 — 决定页面走哪条处理链

    text route:     → 直接文本提取 → chunk → embed
    table route:    → 表格解析 → TableBlock → 结构化存储
    figure route:   → 保留原图 → 可选 vision 描述 → FigureBlock
    diagram route:  → OCR 标签 + 结构抽取 → DiagramBlock
    ocr route:      → OCR → 后处理 → OCRRegion
    """

    def __init__(self):
        self.classifier = PageClassifier()

    def route_page(self, page_text: str, page_num: int = 0,
                   has_images: bool = False, image_count: int = 0,
                   ocr_confidence: float = 1.0, table_rows: int = 0,
                   total_lines: int = 0) -> ModalityRoute:
        """路由单个页面"""
        modality = self.classifier.classify(
            page_text, has_images, image_count, ocr_confidence,
            table_rows, total_lines,
        )

        reasons = {
            "text": "High text density",
            "table": "Significant table content detected",
            "figure": "Image-heavy, low text density",
            "diagram": "Diagram characters detected",
            "ocr": "Low OCR confidence",
        }

        return ModalityRoute(
            modality=modality,
            confidence=0.9 if modality == "text" else 0.7,
            reason=reasons.get(modality, ""),
        )

    def route_document(self, pages: list[dict]) -> list[ModalityRoute]:
        """路由整个文档的所有页面"""
        routes = []
        for p in pages:
            text = p.get("text", "")
            route = self.route_page(
                page_text=text,
                page_num=p.get("num", 0),
                has_images=bool(p.get("images")),
                image_count=len(p.get("images", [])),
            )
            routes.append(route)
        return routes

    def stats(self, routes: list[ModalityRoute]) -> dict:
        """统计模态分布"""
        dist = {}
        for r in routes:
            dist[r.modality] = dist.get(r.modality, 0) + 1
        return {"total_pages": len(routes), "distribution": dist}


# ── Vision Adapter ───────────────────────────────

class VisionAdapter:
    """统一视觉模型调用接口

    对接 MiniMax / GPT-4V / Claude Vision 等视觉模型。
    当前实现: MiniMax API。
    """

    def __init__(self, provider: str = "minimax"):
        self.provider = provider

    def describe_image(self, image_path: str, prompt: str = "") -> str:
        """用视觉模型描述图片内容"""
        if self.provider == "minimax":
            return self._describe_minimax(image_path, prompt)
        return ""

    def explain_diagram(self, image_path: str,
                        ocr_labels: list[str] = None) -> str:
        """解释流程图/结构图"""
        labels_text = ", ".join(ocr_labels or [])
        prompt = (
            "你是一个工程图示解释器。请描述这张图的结构和含义。"
        )
        if labels_text:
            prompt += f" 图中识别到的文字标签: {labels_text}."
        return self.describe_image(image_path, prompt)

    def _describe_minimax(self, image_path: str, prompt: str) -> str:
        """MiniMax Vision API"""
        import os, base64, httpx
        from config.env_loader import load_hermes_env
        load_hermes_env()

        api_key = os.environ.get("MINIMAX_API_KEY", os.environ.get("MINIMAX_CN_API_KEY", ""))
        if not api_key:
            return ""

        # Read and encode image
        try:
            with open(image_path, "rb") as f:
                img_b64 = base64.b64encode(f.read()).decode()
        except Exception:
            return ""

        try:
            resp = httpx.post(
                "https://api.minimax.chat/v1/text/chatcompletion_v2",
                headers={"Authorization": f"Bearer {api_key}"},
                json={
                    "model": "abab6.5s-chat",
                    "messages": [{
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt or "Describe this image briefly."},
                            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img_b64}"}},
                        ],
                    }],
                    "temperature": 0.3,
                    "max_tokens": 500,
                },
                timeout=30,
            )
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]
        except Exception:
            return ""


# ── Modality Affinity ────────────────────────────

class ModalityAffinity:
    """判断用户问题更适合哪种证据类型"""

    TABLE_KEYWORDS = [
        "表格", "对照表", "费用表", "参数表", "规格表",
        "标准是多少", "上限是多少", "多少元", "多少米",
    ]
    DIAGRAM_KEYWORDS = [
        "流程图", "拓扑图", "结构图", "示意图", "框图",
        "什么关系", "怎么连接", "架构", "怎么走",
    ]
    FIGURE_KEYWORDS = [
        "截图", "图片", "照片", "图示", "界面",
        "长什么样", "什么样子",
    ]

    @classmethod
    def detect(cls, question: str) -> str:
        """返回: text | table | diagram | figure | mixed"""
        q = question.lower()
        scores = {"text": 0, "table": 0, "diagram": 0, "figure": 0}

        for kw in cls.TABLE_KEYWORDS:
            if kw in q:
                scores["table"] += 2      # 权重高于 text
        for kw in cls.DIAGRAM_KEYWORDS:
            if kw in q:
                scores["diagram"] += 2
        for kw in cls.FIGURE_KEYWORDS:
            if kw in q:
                scores["figure"] += 2

        # 多条命中 → mixed
        non_text = sum(1 for k in ("table", "diagram", "figure") if scores[k] > 0)
        if non_text > 1:
            return "mixed"

        best = max(scores, key=scores.get)
        return best if scores[best] > 0 else "text"
