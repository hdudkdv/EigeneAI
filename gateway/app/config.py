from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path


def _env(key: str, default: str = "") -> str:
    return os.environ.get(key, default)


def _env_bool(key: str, default: bool = False) -> bool:
    raw = os.environ.get(key)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


class Settings:
    def __init__(self) -> None:
        self.host: str = _env("EIGENEAI_HOST", "0.0.0.0")
        self.port: int = int(_env("EIGENEAI_PORT", "8080"))
        self.data_dir: Path = Path(_env("EIGENEAI_DATA_DIR", "./data"))
        self.admin_secret: str = _env("EIGENEAI_ADMIN_SECRET", "change-me-admin-secret")
        self.public_url: str = _env("EIGENEAI_PUBLIC_URL", "https://eigeneai.local")

        self.llama_cpp_url: str = _env("LLAMA_CPP_URL", "http://127.0.0.1:8081")
        self.mock_inference: bool = _env_bool("MOCK_INFERENCE", False)

        self.default_model: str = _env("DEFAULT_MODEL", "Qwen2.5-14B-Instruct-Q5_K_M")
        self.models_dir: Path = Path(_env("MODELS_DIR", "/var/lib/ai/models"))

        self.gpu_count: int = int(_env("GPU_COUNT", "1"))
        self.gpu_queue_size: int = int(_env("GPU_QUEUE_SIZE", "32"))

        web = _env("WEB_DIST", "")
        self.web_dist: Path | None = Path(web) if web else None

    @property
    def db_path(self) -> Path:
        return self.data_dir / "eigeneai.db"

    @property
    def accounts_dir(self) -> Path:
        return self.data_dir / "accounts"

    @property
    def use_mock(self) -> bool:
        if self.mock_inference:
            return True
        return not str(self.llama_cpp_url or "").strip()


@lru_cache
def get_settings() -> Settings:
    return Settings()


def refresh_settings() -> Settings:
    get_settings.cache_clear()
    return get_settings()
