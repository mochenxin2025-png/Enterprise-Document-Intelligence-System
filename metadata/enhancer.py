"""Metadata Enhancer — LLM 自动生成语义元数据

当文件名无语义（如 "通信模块说明.docx"）时，LLM 自动生成:
  - Summary: 一句话摘要
  - Keywords: 3-5 个关键词
  - Questions: 3-5 个此文档能回答的问题

生成的元数据存入文档的 metadata JSON 字段，用于增强检索。
"""
from typing import Optional


class MetadataEnhancer:
    """LLM 驱动的元数据增强"""

    def __init__(self, llm=None):
        if llm is None:
            from adapters import DeepSeekAdapter
            self.llm = DeepSeekAdapter()
        else:
            self.llm = llm

    def enhance(self, filename: str, sample_text: str,
                max_chars: int = 2000) -> dict:
        """分析文档内容，生成增强元数据"""
        preview = sample_text[:max_chars]

        prompt = (
            "你是一个工程文档分析器。根据文档文件名和内容片段，"
            "生成以下元数据（JSON 格式）:\n\n"
            f"文件名: {filename}\n"
            f"内容预览:\n{preview}\n\n"
            '请输出 JSON:\n'
            '{\n'
            '  "summary": "一句话中文摘要",\n'
            '  "keywords": ["关键词1", "关键词2", "关键词3"],\n'
            '  "questions": ["此文档能回答的问题1", "问题2", "问题3"]\n'
            '}'
        )

        try:
            import json, re
            resp = self.llm.chat([
                {"role": "user", "content": prompt},
            ], max_tokens=300, temperature=0.3)

            # 提取 JSON
            text = resp.content
            match = re.search(r'\{.*\}', text, re.DOTALL)
            if match:
                return json.loads(match.group())

            return {
                "summary": filename,
                "keywords": [],
                "questions": [],
            }
        except Exception:
            return {"summary": filename, "keywords": [], "questions": []}

    def to_searchable_text(self, enhanced: dict) -> str:
        """将增强元数据转为可检索文本"""
        parts = [enhanced.get("summary", "")]
        parts.extend(enhanced.get("keywords", []))
        parts.extend(enhanced.get("questions", []))
        return " ".join(p for p in parts if p)
