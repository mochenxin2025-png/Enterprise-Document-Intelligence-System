"""Runtime Profiles — 根据 PlatformInfo 自动选择运行参数"""
import os
import yaml
from pathlib import Path
from . import get_platform


# Default profiles as fallback if YAML not found
_DEFAULT_PROFILES = {
    "windows_cpu": {
        "embedding": {"device": "cpu", "batch_size": 16, "num_workers": 2},
        "ocr": {"threads": 2},
        "sqlite": {"pragmas": {"journal_mode": "WAL", "busy_timeout": 5000}},
        "ingestion": {"parallel_threshold": 100, "workers": 4},
    },
    "windows_cuda": {
        "embedding": {"device": "cuda", "batch_size": 64, "num_workers": 4},
        "ocr": {"threads": 4},
        "sqlite": {"pragmas": {"journal_mode": "WAL", "busy_timeout": 5000}},
        "ingestion": {"parallel_threshold": 50, "workers": 8},
    },
    "mac_apple_silicon": {
        "embedding": {"device": "mps", "batch_size": 32, "num_workers": 4},
        "ocr": {"threads": 4},
        "sqlite": {"pragmas": {"journal_mode": "WAL", "busy_timeout": 5000}},
        "ingestion": {"parallel_threshold": 100, "workers": 4},
    },
    "mac_intel": {
        "embedding": {"device": "cpu", "batch_size": 16, "num_workers": 2},
        "ocr": {"threads": 2},
        "sqlite": {"pragmas": {"journal_mode": "WAL", "busy_timeout": 5000}},
        "ingestion": {"parallel_threshold": 100, "workers": 4},
    },
    "linux_cpu": {
        "embedding": {"device": "cpu", "batch_size": 16, "num_workers": 2},
        "ocr": {"threads": 2},
        "sqlite": {"pragmas": {"journal_mode": "WAL", "busy_timeout": 5000}},
        "ingestion": {"parallel_threshold": 100, "workers": 4},
    },
    "linux_cuda": {
        "embedding": {"device": "cuda", "batch_size": 64, "num_workers": 4},
        "ocr": {"threads": 4},
        "sqlite": {"pragmas": {"journal_mode": "WAL", "busy_timeout": 5000}},
        "ingestion": {"parallel_threshold": 50, "workers": 8},
    },
}


def _load_profiles() -> dict:
    """从 YAML 加载 profiles，失败则用内置默认值"""
    yaml_paths = [
        Path("config/runtime_profiles.yaml"),
        Path(__file__).parent.parent / "config" / "runtime_profiles.yaml",
    ]
    for p in yaml_paths:
        if p.exists():
            try:
                with open(p) as f:
                    return yaml.safe_load(f) or _DEFAULT_PROFILES
            except Exception:
                pass
    return _DEFAULT_PROFILES


def get_profile() -> dict:
    """根据当前平台自动选择最佳 profile"""
    pi = get_platform()

    if pi.os_name == "windows":
        key = "windows_cuda" if pi.has_cuda else "windows_cpu"
    elif pi.os_name == "macos":
        key = "mac_apple_silicon" if pi.has_mps else "mac_intel"
    else:
        key = "linux_cuda" if pi.has_cuda else "linux_cpu"

    profiles = _load_profiles()
    return profiles.get(key, profiles.get("linux_cpu", {}))


def get_embedding_config() -> dict:
    """获取 embedding 推荐配置"""
    return get_profile().get("embedding", {"device": "cpu", "batch_size": 16})


def get_ocr_config() -> dict:
    return get_profile().get("ocr", {"threads": 2})


def get_ingestion_config() -> dict:
    return get_profile().get("ingestion", {"parallel_threshold": 100, "workers": 4})
