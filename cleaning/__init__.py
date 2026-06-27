"""数据清洗管线 — OCR 后处理 + 文本归一化 + 结构恢复 + 表格重建 + Quality Gate"""
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Optional

import chardet


# ── Quality labels ────────────────────────────

class Quality:
    CLEAN = "clean"
    NOISY = "noisy"
    STRUCTURAL_ISSUE = "structural_issue"
    UNREADABLE = "unreadable"
    REQUIRES_VISION = "requires_vision"


@dataclass
class CleanResult:
    text: str
    quality: str = Quality.CLEAN
    confidence: float = 1.0
    issues: list[str] = field(default_factory=list)


# ── OCR Post-Processing ──────────────────────

def ocr_post_process(text: str, llm_correct: Optional[callable] = None) -> CleanResult:
    """OCR 后处理：全角→半角，常见混淆修复，可选 LLM 纠错。"""
    issues = []
    confidence = 0.9

    # Unicode 归一化
    text = unicodedata.normalize("NFKC", text)

    # 全角 → 半角（保留中文全角标点）
    result = []
    for ch in text:
        code = ord(ch)
        if 0xFF01 <= code <= 0xFF5E:  # 全角英文/数字/标点
            result.append(chr(code - 0xFEE0))
        elif code == 0x3000:  # 全角空格
            result.append(" ")
        else:
            result.append(ch)
    text = "".join(result)

    # 数字/字母混淆修复（规则层）
    fixes = {
        "OΩΟ": "O",  # 不同语言的 O → 普通 O
    }
    # 在疑似数字上下文中修复
    text = re.sub(r'(?<=\d)\s*[lI]\s*(?=\d)', '1', text)  # 1和l混淆
    text = re.sub(r'(?<=\d)\s*[O]\s*(?=\d)', '0', text)   # 0和O混淆

    # LLM 层纠错（如果提供且文本需要）
    if llm_correct:
        try:
            text = llm_correct(text)
            issues.append("llm_corrected")
        except Exception:
            issues.append("llm_correction_failed")
    else:
        confidence = 0.85  # 未使用 LLM 纠错时降一点

    return CleanResult(text=text, quality=Quality.NOISY if issues else Quality.CLEAN,
                       confidence=confidence, issues=issues)


# ── Text Normalization ────────────────────────

def normalize_text(text: str) -> CleanResult:
    """编码修复 + 空白符清洗 + 特殊符号归一化。"""
    issues = []

    # 乱码检测（混合编码特征）
    garbage_ratio = sum(1 for ch in text if ord(ch) in _garbage_ranges()) / max(len(text), 1)
    if garbage_ratio > 0.3:
        issues.append("possible_encoding_garbage")

    # 空白符清洗
    text = re.sub(r'[ \t]{2,}', ' ', text)     # 多余空格
    text = re.sub(r'\n{3,}', '\n\n', text)      # 多余空行
    text = re.sub(r'[\r\v\f]', '', text)        # 控制字符

    # 特殊符号归一化
    replacements = {
        '℃': '°C', '℉': '°F', 'Ω': 'Ohm',
        'µ': 'u', '±': '+/-', '≤': '<=', '≥': '>=',
    }
    for old, new in replacements.items():
        text = text.replace(old, new)

    confidence = 0.7 if issues else 0.95
    quality = Quality.NOISY if garbage_ratio > 0.2 else Quality.CLEAN

    return CleanResult(text=text, quality=quality, confidence=confidence, issues=issues)


def _garbage_ranges():
    """疑似垃圾字符的 Unicode 范围"""
    return set(range(0x0000, 0x0020)) | {0x007F}  # 控制字符


# ── Structure Recovery ────────────────────────

def recover_structure(pages: list) -> list[dict]:
    """利用 PDF 坐标信息恢复多栏布局和段落边界。
    
    输入: ParsedPage 列表
    输出: [{page, sections: [{title, level, text}]}]
    """
    structured = []
    for page in pages:
        sections = []
        current_section = {"title": "", "level": 0, "text": []}

        # 按 y 坐标排序文本块
        sorted_blocks = sorted(page.blocks, key=lambda b: (b.bbox[1], b.bbox[0]))

        # 简单分栏检测：如果存在 x 坐标差异大的相邻块，可能是多栏
        x_centers = [b.bbox[0] + (b.bbox[2] - b.bbox[0]) / 2 for b in sorted_blocks if b.text.strip()]
        is_multi_column = _detect_columns(x_centers, page.width)

        col_texts = {0: [], 1: []} if is_multi_column else {0: []}
        for block in sorted_blocks:
            col = _assign_column(block, page.width) if is_multi_column else 0
            col_texts[col].append(block.text.strip())

        for col, lines in col_texts.items():
            sections.append({
                "column": col,
                "text": "\n".join(lines),
            })

        structured.append({
            "page": page.page_num,
            "sections": sections,
            "is_multi_column": is_multi_column,
        })

    return structured


def _detect_columns(x_centers: list[float], page_width: float) -> bool:
    """检测是否为多栏布局"""
    if len(x_centers) < 4:
        return False
    mid = page_width / 2
    left_count = sum(1 for x in x_centers if x < mid - 50)
    right_count = sum(1 for x in x_centers if x > mid + 50)
    return left_count > 2 and right_count > 2


def _assign_column(block, page_width: float) -> int:
    """根据 x 坐标分配栏位"""
    mid = page_width / 2
    center_x = block.bbox[0] + (block.bbox[2] - block.bbox[0]) / 2
    return 0 if center_x < mid else 1


# ── Table Reconstruction ──────────────────────

def reconstruct_tables(text: str, llm_extract: Optional[callable] = None) -> list[dict]:
    """从文本重建无边框表格。
    
    策略:
    1. pymupdf 已提取的结构化表格直接使用
    2. LLM 识别无边框参数表
    """
    # 无边框表格检测启发式
    lines = text.strip().split("\n")
    potential_table_lines = []

    for line in lines:
        # 多列特征：空格/制表符分隔、数字值、单位后缀
        parts = re.split(r'\s{2,}|\t', line)
        if len(parts) >= 2 and any(
            re.search(r'[\d.-]+\s*(dBm|mW|W|km|m|s|Hz|V|A)', p) for p in parts
        ):
            potential_table_lines.append(line)

    if not potential_table_lines:
        return []

    # 如果提供了 LLM 提取器，使用 LLM
    if llm_extract and len(potential_table_lines) >= 2:
        try:
            return llm_extract("\n".join(potential_table_lines))
        except Exception:
            pass

    # 回退：简单规则解析
    tables = []
    current_table = []
    for line in potential_table_lines:
        parts = re.split(r'\s{2,}|\t', line.strip())
        current_table.append(parts)
    if current_table:
        tables.append({"headers": current_table[0] if current_table else [], "rows": current_table[1:]})

    return tables


# ── Quality Gate ──────────────────────────────

def quality_check(text: str, min_confidence: float = 0.3, noisy_threshold: float = 0.6) -> CleanResult:
    """综合质量评估"""
    issues = []

    # 空内容
    if not text or not text.strip():
        return CleanResult(text=text, quality=Quality.UNREADABLE, confidence=0.0, issues=["empty"])

    # 垃圾字符比例
    garbage = sum(1 for ch in text if ord(ch) in _garbage_ranges())
    ratio = garbage / max(len(text), 1)

    if ratio > 0.5:
        return CleanResult(text=text, quality=Quality.UNREADABLE, confidence=0.1, issues=["excessive_garbage"])

    # 可读性评分
    printable = sum(1 for ch in text if ch.isprintable() or ch in '\n\t')
    readability = printable / max(len(text), 1)
    confidence = readability * (1 - ratio)

    if confidence < min_confidence:
        quality = Quality.UNREADABLE
    elif confidence < noisy_threshold:
        quality = Quality.NOISY
    elif ratio > 0.1:
        quality = Quality.NOISY
    else:
        quality = Quality.CLEAN

    return CleanResult(text=text, quality=quality, confidence=round(confidence, 3), issues=issues)


# ── Full Pipeline ─────────────────────────────

def clean_pipeline(pages: list, llm_correct=None, llm_extract=None) -> list[dict]:
    """完整清洗管线：页面列表 → 清洗后页面列表"""
    results = []
    for page in pages:
        text = page.text

        # 1. OCR 后处理
        ocr_result = ocr_post_process(text, llm_correct)

        # 2. 文本归一化
        norm_result = normalize_text(ocr_result.text)

        # 3. 质量关卡
        qc_result = quality_check(norm_result.text)
        qc_result.issues.extend(ocr_result.issues)
        qc_result.issues.extend(norm_result.issues)
        qc_result.confidence = min(ocr_result.confidence, norm_result.confidence, qc_result.confidence)

        results.append({
            "page": page.page_num if hasattr(page, 'page_num') else page.get("page", 0),
            "text": qc_result.text,
            "quality": qc_result.quality,
            "confidence": qc_result.confidence,
            "issues": qc_result.issues,
            "images": getattr(page, 'images', []),
            "tables": getattr(page, 'tables', []),
            "hash": getattr(page, 'hash', ''),
        })

    return results
