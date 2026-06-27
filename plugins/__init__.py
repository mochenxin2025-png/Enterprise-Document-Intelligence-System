"""Plugin Registry — 声明式插件注册

任何模块通过 @register 装饰器注册，通过 PluginRegistry.get() 获取。
换模型只需改 config.yaml，无需改源码。
"""
from typing import Any, Callable


class PluginRegistry:
    """全局插件注册表"""

    _plugins: dict[str, dict[str, Any]] = {}

    @classmethod
    def register(cls, category: str, name: str):
        """装饰器：将类/函数注册到指定类别下"""
        def decorator(impl: Any):
            if category not in cls._plugins:
                cls._plugins[category] = {}
            cls._plugins[category][name] = impl
            return impl
        return decorator

    @classmethod
    def get(cls, category: str, name: str, default: Any = None) -> Any:
        """获取已注册的插件类/函数"""
        return cls._plugins.get(category, {}).get(name, default)

    @classmethod
    def list(cls, category: str = None) -> dict:
        """列出所有已注册插件"""
        if category:
            return dict(cls._plugins.get(category, {}))
        return {k: dict(v) for k, v in cls._plugins.items()}

    @classmethod
    def create(cls, category: str, name: str, **kwargs) -> Any:
        """获取插件类并实例化"""
        impl = cls.get(category, name)
        if impl is None:
            raise ValueError(f"Plugin not found: {category}/{name}. Available: {list(cls._plugins.get(category, {}).keys())}")
        return impl(**kwargs)


# ── 注册所有内置插件 ───────────────────────────

from interfaces import LLMInterface, EmbeddingInterface, ParserInterface, VectorStoreInterface


@PluginRegistry.register("llm", "deepseek")
class DeepSeekPlugin(LLMInterface):
    def __init__(self, api_key: str = None, model: str = "deepseek-chat",
                 base_url: str = "https://api.deepseek.com", temperature: float = 0.3, **kwargs):
        import os
        if api_key is None:
            from config.env_loader import load_hermes_env; load_hermes_env()
            api_key = os.environ.get("DEEPSEEK_API_KEY", "")
        self._key = api_key
        self.model = model
        self.base_url = base_url
        self.temperature = temperature

    @property
    def model_name(self) -> str: return self.model

    def chat(self, messages, **kwargs):
        import httpx
        resp = httpx.post(f"{self.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self._key}", "Content-Type": "application/json"},
            json={"model": self.model, "messages": messages,
                  "temperature": kwargs.get("temperature", self.temperature),
                  "max_tokens": kwargs.get("max_tokens", 2048)},
            timeout=kwargs.get("timeout", 60))
        resp.raise_for_status()
        d = resp.json()
        from interfaces import LLMResponse
        return LLMResponse(content=d["choices"][0]["message"]["content"], model=self.model, usage=d.get("usage", {}), raw=d)


@PluginRegistry.register("llm", "openai")
class OpenAIPlugin(LLMInterface):
    def __init__(self, api_key: str = None, model: str = "gpt-4o-mini",
                 base_url: str = "https://api.openai.com/v1", temperature: float = 0.3, **kwargs):
        import os
        self._key = api_key or os.environ.get("OPENAI_API_KEY", "")
        self.model = model; self.base_url = base_url; self.temperature = temperature

    @property
    def model_name(self) -> str: return self.model

    def chat(self, messages, **kwargs):
        import httpx
        resp = httpx.post(f"{self.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self._key}", "Content-Type": "application/json"},
            json={"model": self.model, "messages": messages,
                  "temperature": kwargs.get("temperature", self.temperature),
                  "max_tokens": kwargs.get("max_tokens", 2048)},
            timeout=kwargs.get("timeout", 60))
        resp.raise_for_status()
        d = resp.json()
        from interfaces import LLMResponse
        return LLMResponse(content=d["choices"][0]["message"]["content"], model=self.model, usage=d.get("usage", {}), raw=d)


@PluginRegistry.register("llm", "minimax")
class MiniMaxPlugin(LLMInterface):
    def __init__(self, api_key: str = None, model: str = "abab6.5s-chat",
                 base_url: str = "https://api.minimax.chat/v1/text/chatcompletion_v2", temperature: float = 0.3, **kwargs):
        import os
        if api_key is None:
            from config.env_loader import load_hermes_env; load_hermes_env()
            api_key = os.environ.get("MINIMAX_API_KEY", os.environ.get("MINIMAX_CN_API_KEY", ""))
        self._key = api_key; self.model = model; self.base_url = base_url; self.temperature = temperature

    @property
    def model_name(self) -> str: return self.model

    def chat(self, messages, **kwargs):
        import httpx
        resp = httpx.post(self.base_url,
            headers={"Authorization": f"Bearer {self._key}", "Content-Type": "application/json"},
            json={"model": self.model, "messages": messages,
                  "temperature": kwargs.get("temperature", self.temperature),
                  "max_tokens": kwargs.get("max_tokens", 2048)},
            timeout=kwargs.get("timeout", 60))
        resp.raise_for_status()
        d = resp.json()
        from interfaces import LLMResponse
        return LLMResponse(content=d["choices"][0]["message"]["content"], model=self.model, usage=d.get("usage", {}), raw=d)


@PluginRegistry.register("embedding", "bge-large-zh")
class BGEPlugin(EmbeddingInterface):
    def __init__(self, model_path: str = "./data/models/BAAI/bge-large-zh-v1___5", device: str = "cpu", **kwargs):
        import os, torch
        from transformers import AutoTokenizer, AutoModel
        path = model_path if os.path.exists(model_path) else "BAAI/bge-large-zh-v1.5"
        self._tokenizer = AutoTokenizer.from_pretrained(path, local_files_only=(path == model_path))
        self._model = AutoModel.from_pretrained(path, local_files_only=(path == model_path))
        self._model.eval()

    @property
    def dimension(self) -> int: return 1024

    def encode(self, texts, batch_size=32, **kwargs):
        import torch, numpy as np
        all_embs = []
        for i in range(0, len(texts), batch_size):
            batch = texts[i:i+batch_size]
            enc = self._tokenizer(batch, padding=True, truncation=True, max_length=512, return_tensors="pt")
            with torch.no_grad():
                out = self._model(**enc)
                tok = out.last_hidden_state
                mask = enc["attention_mask"].unsqueeze(-1).expand(tok.size()).float()
                emb = torch.sum(tok * mask, 1) / torch.clamp(mask.sum(1), min=1e-9)
                emb = torch.nn.functional.normalize(emb, p=2, dim=1)
            all_embs.append(emb.cpu().numpy())
        return np.concatenate(all_embs, axis=0).tolist()

    def encode_query(self, query):
        return self.encode([f"为这个句子生成表示以用于检索相关文章：{query}"])[0]


@PluginRegistry.register("parser", "pymupdf")
class PyMuPDFPlugin(ParserInterface):
    def parse(self, filepath):
        import fitz, hashlib
        from pathlib import Path
        doc = fitz.open(filepath)
        from interfaces import ParsedDoc
        parsed = ParsedDoc(
            doc_id=hashlib.sha256(Path(filepath).read_bytes()).hexdigest()[:16],
            filename=Path(filepath).name,
            metadata={"format": "PDF"})
        for i in range(len(doc)):
            page = doc[i]; blocks = page.get_text("dict")["blocks"]
            text = "\n".join("".join(s["text"] for s in line["spans"]) for block in blocks if block["type"]==0 for line in block.get("lines",[]))
            parsed.pages.append({"num": i+1, "text": text, "hash": hashlib.sha256(text.encode()).hexdigest()[:16]})
        parsed.page_count = len(parsed.pages); parsed.total_chars = sum(len(p["text"]) for p in parsed.pages)
        doc.close(); return parsed

    @classmethod
    def supports(cls, filepath): return filepath.lower().endswith(".pdf")


def get_llm(provider: str = "deepseek", **kwargs) -> LLMInterface:
    """从 config 或参数创建 LLM 实例"""
    return PluginRegistry.create("llm", provider, **kwargs)


def get_embedder(provider: str = "bge-large-zh", **kwargs) -> EmbeddingInterface:
    return PluginRegistry.create("embedding", provider, **kwargs)


def get_parser(provider: str = "pymupdf", **kwargs) -> ParserInterface:
    return PluginRegistry.create("parser", provider, **kwargs)
