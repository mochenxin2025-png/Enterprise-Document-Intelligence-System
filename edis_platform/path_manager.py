"""Path Manager — 统一管理所有目录路径

原则: 业务代码不再出现硬编码路径，统一从 PathManager 获取。
"""
import os
import tempfile
from pathlib import Path


class PathManager:
    """跨平台路径管理器"""

    def __init__(self, base_dir: str = None):
        """
        base_dir: EDIS 根目录。默认自动检测:
          1. EDIS_HOME 环境变量
          2. 当前工作目录
        """
        if base_dir:
            self._base = Path(base_dir)
        elif os.environ.get("EDIS_HOME"):
            self._base = Path(os.environ["EDIS_HOME"])
        else:
            self._base = Path.cwd()

        self._ensure_dirs()

    def _ensure_dirs(self):
        """确保核心目录存在"""
        for d in [self.data_dir, self.logs_dir, self.cache_dir,
                   self.jobs_dir, self.temp_dir]:
            d.mkdir(parents=True, exist_ok=True)

    @property
    def base_dir(self) -> Path:
        return self._base

    @property
    def data_dir(self) -> Path:
        """数据目录（数据库、模型）"""
        return self._base / "data"

    @property
    def db_path(self) -> str:
        """SQLite 数据库路径"""
        return str(self.data_dir / "edis.db")

    @property
    def models_dir(self) -> Path:
        """本地模型缓存"""
        return self.data_dir / "models"

    @property
    def logs_dir(self) -> Path:
        return self._base / "logs"

    @property
    def cache_dir(self) -> Path:
        return self._base / "cache"

    @property
    def jobs_dir(self) -> Path:
        """Agent 任务隔离目录"""
        return self._base / "jobs"

    @property
    def temp_dir(self) -> Path:
        """临时文件目录（优先用系统临时目录）"""
        return Path(tempfile.gettempdir()) / "edis"

    def job_dir(self, run_id: str) -> Path:
        """按 run_id 创建隔离目录"""
        d = self.jobs_dir / run_id
        for sub in ["input", "output", "cache", "logs"]:
            (d / sub).mkdir(parents=True, exist_ok=True)
        return d

    @property
    def config_path(self) -> str:
        return str(self._base / "config.yaml")


# ── Global singleton ─────────────────────────────

_path_manager: PathManager = None


def get_paths() -> PathManager:
    global _path_manager
    if _path_manager is None:
        _path_manager = PathManager()
    return _path_manager
