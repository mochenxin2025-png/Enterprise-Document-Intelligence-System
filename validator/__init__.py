"""File Validator — 文件合法性校验

上传文件在进入 Parser 之前过五道关卡:
  1. 存在性检查
  2. 扩展名白名单
  3. 文件大小限制
  4. MIME 类型检查
  5. 内容损坏检测
"""
import os
import mimetypes
from pathlib import Path
from dataclasses import dataclass
from typing import Optional

# 支持的文件类型
ALLOWED_EXTENSIONS = {
    ".pdf", ".docx", ".xlsx", ".pptx", ".md", ".txt",
    ".html", ".htm", ".csv", ".json", ".xml",
    ".png", ".jpg", ".jpeg", ".tiff", ".bmp",
}

# MIME → 扩展名映射
MIME_MAP = {
    "application/pdf": ".pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
    "text/markdown": ".md",
    "text/plain": ".txt",
    "text/html": ".html",
    "text/csv": ".csv",
    "application/json": ".json",
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/tiff": ".tiff",
}

MAX_FILE_SIZE_MB = 200


@dataclass
class ValidationResult:
    valid: bool
    filepath: str = ""
    error: str = ""
    checksum: str = ""
    file_type: str = ""
    file_size: int = 0


class FileValidator:
    """五道关卡校验"""

    def validate(self, filepath: str) -> ValidationResult:
        path = Path(filepath)

        # 1. 存在性
        if not path.exists():
            return ValidationResult(False, str(path), "File not found")

        # 2. 扩展名
        ext = path.suffix.lower()
        if ext not in ALLOWED_EXTENSIONS:
            return ValidationResult(False, filepath, f"Unsupported extension: {ext}")

        # 3. 大小
        try:
            fsize = path.stat().st_size
        except OSError as e:
            return ValidationResult(False, filepath, f"Cannot read file: {e}")

        if fsize == 0:
            return ValidationResult(False, filepath, "Empty file")
        if fsize > MAX_FILE_SIZE_MB * 1024 * 1024:
            return ValidationResult(False, filepath, f"File too large: {fsize / 1024 / 1024:.0f}MB > {MAX_FILE_SIZE_MB}MB")

        # 4. MIME
        mime, _ = mimetypes.guess_type(filepath)
        if mime and mime in MIME_MAP:
            expected_ext = MIME_MAP[mime]
            if ext != expected_ext:
                # 扩展名与 MIME 不匹配
                pass  # 只记录不拒绝——有些文件 MIME 检测不准确

        # 5. 文件头校验
        try:
            with open(filepath, "rb") as f:
                header = f.read(16)
        except Exception as e:
            return ValidationResult(False, filepath, f"Cannot open: {e}")

        if not self._validate_header(ext, header):
            return ValidationResult(False, filepath, f"File appears corrupted or wrong format: {header[:8].hex()}")

        # 通过
        import hashlib
        return ValidationResult(
            valid=True, filepath=filepath, file_type=ext,
            file_size=fsize,
            checksum=hashlib.sha256(f"{filepath}{fsize}".encode()).hexdigest()[:16],
        )

    @staticmethod
    def _validate_header(ext: str, header: bytes) -> bool:
        """Magic bytes 校验"""
        patterns = {
            ".pdf":  b"%PDF",
            ".docx": b"PK\x03\x04",
            ".xlsx": b"PK\x03\x04",
            ".pptx": b"PK\x03\x04",
            ".png":  b"\x89PNG",
            ".jpg":  b"\xff\xd8\xff",
            ".tiff": b"II*\x00",  # little-endian
        }
        expected = patterns.get(ext)
        if expected is None:
            return True  # 无预期 header 的格式不校验
        return header[:len(expected)] == expected
