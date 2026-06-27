"""配置加载器 — 读取 config.yaml + 注入 Hermes 环境变量"""
import os
import yaml
from pathlib import Path

# 确保 Hermes 环境变量已加载
try:
    from config.env_loader import load_hermes_env
    load_hermes_env()
except ImportError:
    pass


class Config:
    """单例配置，首次访问时从 config.yaml 加载。"""
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._loaded = False
        return cls._instance

    def _load(self):
        if self._loaded:
            return
        config_path = Path(__file__).parent.parent / "config.yaml"
        with open(config_path, "r", encoding="utf-8") as f:
            self._data = yaml.safe_load(f)
        self._loaded = True

    def __getattr__(self, name):
        self._load()
        if name.startswith("_"):
            raise AttributeError(name)
        return self._data.get(name)

    def get(self, *keys):
        """深层取值: config.get('cleaning', 'ocr', 'engine')"""
        self._load()
        node = self._data
        for k in keys:
            node = node[k]
        return node

    def api_key(self, provider: str) -> str:
        """获取 API Key，从环境变量读取"""
        env_map = {
            "deepseek": "DEEPSEEK_API_KEY",
            "minimax": "MINIMAX_API_KEY",
        }
        env_var = env_map.get(provider, "")
        if not env_var:
            raise ValueError(f"Unknown API provider: '{provider}'. Known: {list(env_map.keys())}")
        key = os.environ.get(env_var, "")
        if not key:
            raise ValueError(f"API key for '{provider}' not found. Set {env_var}")
        return key


config = Config()
