"""项目运行时配置。

当前版本只保留最小闭环所需的本地目录和基础参数，避免过早引入
环境变量框架或更复杂的配置层。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class Settings:
    """承载应用启动时需要的最小配置集合。"""

    project_root: Path
    uploads_dir: Path
    local_index_dir: Path
    temp_dir: Path
    chunk_size: int = 500
    chunk_overlap: int = 50
    embedding_dimensions: int = 256
    max_top_k: int = 10
    app_name: str = "ragflow-lite"
    api_prefix: str = "/api/v0"

    @classmethod
    def default(cls, project_root: Path | None = None) -> "Settings":
        """生成默认配置。

        默认目录全部落在仓库内的 `data/` 下，便于本地直接运行和调试。
        """
        root = project_root or Path(__file__).resolve().parents[3]
        return cls(
            project_root=root,
            uploads_dir=root / "data" / "uploads",
            local_index_dir=root / "data" / "local_index",
            temp_dir=root / "data" / "tmp",
        )

    def ensure_directories(self) -> None:
        """确保运行期依赖的本地目录存在。"""
        for directory in (self.uploads_dir, self.local_index_dir, self.temp_dir):
            directory.mkdir(parents=True, exist_ok=True)
