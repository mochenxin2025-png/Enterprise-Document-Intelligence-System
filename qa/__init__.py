"""QA module — re-exports QAEngine from qa.engine.

QASystem (deprecated) removed in v1.1. Use QAEngine directly:
    from qa.engine import QAEngine
"""

from qa.engine import QAEngine

# Backward-compat alias for any remaining callers
QASystem = QAEngine

__all__ = ["QAEngine", "QASystem"]
