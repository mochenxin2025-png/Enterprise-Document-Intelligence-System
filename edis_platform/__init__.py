"""Platform Detector — 自动识别运行环境

启动时调用一次，返回 PlatformInfo。后续所有配置选择基于探测结果。
"""
import os
import sys
import platform as _stdlib_platform
from dataclasses import dataclass


@dataclass
class PlatformInfo:
    """平台运行环境信息"""
    os_name: str          # "windows" | "macos" | "linux"
    arch: str             # "x86_64" | "arm64"
    cpu_count: int        # 物理核心数
    has_cuda: bool
    has_mps: bool         # Apple Silicon
    python_version: str
    is_64bit: bool

    @property
    def recommended_device(self) -> str:
        """推荐 embedding/推理设备"""
        if self.has_cuda:
            return "cuda"
        if self.has_mps:
            return "mps"
        return "cpu"

    @property
    def recommended_workers(self) -> int:
        """推荐并发数"""
        return max(1, self.cpu_count // 2)

    def to_dict(self) -> dict:
        return {
            "os": self.os_name,
            "arch": self.arch,
            "cpu_count": self.cpu_count,
            "has_cuda": self.has_cuda,
            "has_mps": self.has_mps,
            "python": self.python_version,
            "recommended_device": self.recommended_device,
            "recommended_workers": self.recommended_workers,
        }


# ── Detection ───────────────────────────────────

def detect() -> PlatformInfo:
    """自动检测当前平台"""
    system = _stdlib_platform.system().lower()

    if system == "windows":
        os_name = "windows"
    elif system == "darwin":
        os_name = "macos"
    else:
        os_name = "linux"

    # Architecture
    machine = _stdlib_platform.machine().lower()
    arch = "arm64" if machine in ("arm64", "aarch64") else "x86_64"

    # CPU count
    cpu_count = os.cpu_count() or 4

    # CUDA detection
    has_cuda = False
    try:
        import torch
        has_cuda = torch.cuda.is_available()
    except ImportError:
        pass

    # Apple Silicon MPS detection
    has_mps = False
    if os_name == "macos":
        try:
            import torch
            has_mps = torch.backends.mps.is_available()
        except (ImportError, AttributeError):
            pass

    return PlatformInfo(
        os_name=os_name,
        arch=arch,
        cpu_count=cpu_count,
        has_cuda=has_cuda,
        has_mps=has_mps,
        python_version=_stdlib_platform.python_version(),
        is_64bit=sys.maxsize > 2**32,
    )


# ── Global singleton ─────────────────────────────

_platform_info: PlatformInfo = None


def get_platform() -> PlatformInfo:
    """获取平台信息（首次调用时自动检测）"""
    global _platform_info
    if _platform_info is None:
        _platform_info = detect()
    return _platform_info
