"""EDIS Extension System — pip-installable 扩展机制

任何第三方可通过 entry_points 注册扩展:
  pip install edis-diagram-extension
  → 自动发现并注册到 PluginRegistry

setup.py:
  entry_points={
      "edis.extensions": [
          "diagram = edis_diagram:DiagramExtension",
      ],
  }

Extension 基类定义三个钩子:
  - on_load(): 加载时调用，注册插件/工具/prompt
  - on_unload(): 卸载时调用
  - metadata(): 返回扩展元信息
"""
import sys
import importlib.metadata
from typing import ClassVar

from plugins import PluginRegistry
from tools import ToolRegistry


class Extension:
    """扩展基类 — 继承并实现 on_load"""

    name: str = ""
    version: str = "0.1.0"
    description: str = ""

    @classmethod
    def metadata(cls) -> dict:
        return {"name": cls.name, "version": cls.version, "description": cls.description}

    @classmethod
    def on_load(cls):
        """加载时调用 — 注册 plugins / tools / prompts"""
        pass

    @classmethod
    def on_unload(cls):
        """卸载时调用"""
        pass


class ExtensionManager:
    """管理所有已安装扩展"""

    _extensions: ClassVar[dict[str, type[Extension]]] = {}
    _loaded: ClassVar[bool] = False

    @classmethod
    def discover(cls):
        """从 entry_points 发现已安装的扩展"""
        if cls._loaded:
            return

        try:
            eps = importlib.metadata.entry_points(group="edis.extensions")
        except TypeError:
            # Python < 3.12 fallback
            try:
                eps = importlib.metadata.entry_points().get("edis.extensions", [])
            except Exception:
                eps = []

        for ep in eps:
            try:
                ext_cls = ep.load()
                if issubclass(ext_cls, Extension):
                    cls._extensions[ep.name] = ext_cls
                    print(f"[ext] Discovered: {ep.name} ({ext_cls.name} v{ext_cls.version})")
            except Exception as e:
                print(f"[ext] Failed to load {ep.name}: {e}")

        cls._loaded = True

    @classmethod
    def load_all(cls):
        """加载所有发现的扩展"""
        cls.discover()
        for name, ext_cls in cls._extensions.items():
            try:
                ext_cls.on_load()
                print(f"[ext] Loaded: {name}")
            except Exception as e:
                print(f"[ext] Error loading {name}: {e}")

    @classmethod
    def list_all(cls) -> list[dict]:
        cls.discover()
        return [ext_cls.metadata() for ext_cls in cls._extensions.values()]


# ── 内置扩展示例 ────────────────────────────────

class DiagramExtension(Extension):
    """图理解扩展 — Phase 6 预留"""
    name = "Diagram Agent"
    version = "0.1.0"
    description = "工程图纸理解（流程图/拓扑图/架构图）"

    @classmethod
    def on_load(cls):
        from tools import ToolRegistry
        @ToolRegistry.register("diagram_analyze", "分析工程图纸",
            {"image_path": "string", "question": "string=描述这张图"})
        def tool_diagram(image_path: str, question: str = "描述这张图") -> dict:
            return {"status": "not_implemented", "message": "Phase 6"}


class WorkflowExtension(Extension):
    """工作流扩展 — 多步推理链"""
    name = "Workflow Engine"
    version = "0.1.0"
    description = "多步问答工作流（分解→检索→融合→推理）"

    @classmethod
    def on_load(cls):
        from tools import ToolRegistry
        @ToolRegistry.register("workflow", "执行多步推理工作流",
            {"question": "string", "steps": "int=3"})
        def tool_workflow(question: str, steps: int = 3) -> dict:
            return {"status": "not_implemented", "steps": steps}


# ── 启动时自动发现 ──────────────────────────────

def init_extensions():
    """在 QAEngine 初始化时调用"""
    # 加载内置扩展
    DiagramExtension.on_load()
    WorkflowExtension.on_load()
    # 加载第三方扩展
    ExtensionManager.load_all()
