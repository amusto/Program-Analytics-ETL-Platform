"""Runtime configuration loaded from environment variables.

Keeping a single Settings object makes it easy to point the same code at
local Docker Postgres, a CI database, or a production RDS instance.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = (
        "postgresql+psycopg://analytics:analytics@localhost:5432/program_analytics"
    )
    data_dir: Path = Path(__file__).resolve().parents[2] / "data"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def raw_dir(self) -> Path:
        return self.data_dir / "raw"

    @property
    def failed_dir(self) -> Path:
        return self.data_dir / "failed"

    @property
    def processed_dir(self) -> Path:
        return self.data_dir / "processed"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
