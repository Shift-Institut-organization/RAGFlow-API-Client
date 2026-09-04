"""Configuration models powered by Pydantic for API dataset seeding and Bruno CLI runs."""

import os
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, field_validator

from bruno_populator.exceptions import ConfigurationError
from paths import (
    DEFAULT_DATA_DIR,
    PROJECT_ROOT,
    REQUIREMENTS_FILENAME,
    SOURCES_DIR_NAME,
)


class AppConfig(BaseModel):
    """Main application configuration loaded from environment or .env file."""

    base_url: str = "http://localhost:9222"
    api_key: str = ""
    debug: bool = False
    data_dir: Path = Field(default_factory=lambda: DEFAULT_DATA_DIR)

    @field_validator("data_dir", mode="before")
    @classmethod
    def resolve_data_dir(cls, v: Any) -> Path:
        if isinstance(v, str):
            p = Path(v)
            return p if p.is_absolute() else (PROJECT_ROOT / p).resolve()
        elif isinstance(v, Path):
            return v if v.is_absolute() else (PROJECT_ROOT / v).resolve()
        return DEFAULT_DATA_DIR.resolve()

    def validate_data_dir_assets(self) -> tuple[Path, Path]:
        """
        Validate that data_dir exists and contains 'requirements.md' and 'sources' folder.

        Returns (requirements_path, sources_dir).
        Raises ConfigurationError with informative guidance if any file/folder is missing.
        """
        resolved = self.data_dir.resolve()
        if not resolved.exists() or not resolved.is_dir():
            raise ConfigurationError(
                f"[Config Error] Configured project data directory '{resolved}' does not exist or is not a directory. "
                f"Please verify your DATA_DIR setting in .env."
            )

        req_path = resolved / REQUIREMENTS_FILENAME
        if not req_path.exists():
            raise ConfigurationError(
                f"[Config Error] Project data directory '{resolved}' is missing the required requirements file.\n"
                f"Expected file: '{req_path}'\n"
                f"Please ensure the folder contains a file named '{REQUIREMENTS_FILENAME}'."
            )

        sources_path = resolved / SOURCES_DIR_NAME
        if not sources_path.exists() or not sources_path.is_dir():
            raise ConfigurationError(
                f"[Config Error] Project data directory '{resolved}' is missing the required sources directory.\n"
                f"Expected directory: '{sources_path}'\n"
                f"Please ensure the folder contains a directory named '{SOURCES_DIR_NAME}'."
            )

        return req_path, sources_path

    @property
    def requirements_path(self) -> Path:
        req_path, _ = self.validate_data_dir_assets()
        return req_path

    @property
    def sources_dir(self) -> Path:
        _, sources_path = self.validate_data_dir_assets()
        return sources_path


_env_loaded = False


def load_dotenv(env_file_path: Path | None = None, override: bool = False) -> None:
    """Load environment variables from .env into os.environ (runs once unless override=True)."""
    global _env_loaded
    if _env_loaded and env_file_path is None and not override:
        return

    target_env = (env_file_path or (PROJECT_ROOT / ".env")).resolve()
    should_override = override or (env_file_path is not None)
    if target_env.exists() and target_env.is_file():
        try:
            with open(target_env, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        key, value = line.split("=", 1)
                        key = key.strip()
                        value = value.strip().strip('"').strip("'")
                        if key:
                            if should_override or key not in os.environ:
                                os.environ[key] = value
        except Exception:
            pass
    if env_file_path is None:
        _env_loaded = True


# Auto-load default .env on module import
load_dotenv()


def load_app_config(env_file_path: Path | None = None) -> AppConfig:
    """
    Load AppConfig from environment variables or .env file at env_file_path / PROJECT_ROOT / '.env'.
    """
    load_dotenv(env_file_path)

    base_url = os.environ.get("BASE_URL", "http://localhost:9222")
    api_key = os.environ.get("RAGFLOW_API_KEY") or os.environ.get("API_KEY") or ""
    debug_str = os.environ.get("DEBUG", "false")
    debug = str(debug_str).lower() in ("true", "1", "yes")
    data_dir_val = os.environ.get("DATA_DIR", "data/Bicycle")

    config = AppConfig(
        base_url=base_url,
        api_key=api_key,
        debug=debug,
        data_dir=data_dir_val,
    )
    return config


class DatasetDocumentConfig(BaseModel):
    """Configuration for populating dataset documents."""

    dataset_id: str
    base_url: str = "http://localhost:9222"
    request_name: str = "Upload Documents"
    source_dir: Path
    output_yaml_path: Path

    @field_validator("source_dir")
    @classmethod
    def validate_source_dir(cls, v: Path) -> Path:
        resolved = v.resolve()
        if not resolved.exists():
            raise ConfigurationError(f"Source directory does not exist: {resolved}")
        if not resolved.is_dir():
            raise ConfigurationError(f"Source path is not a directory: {resolved}")
        return resolved

    @property
    def api_url(self) -> str:
        return f"{self.base_url.rstrip('/')}/api/v1/datasets/{self.dataset_id}/documents"


class BrunoRunConfig(BaseModel):
    """Configuration for executing Bruno CLI (`bru run`)."""

    collection_dir: Path
    request_file: Path | str | None = None
    env: str | None = None
    output_json_path: Path | None = None
    exclude_tags: list[str] = Field(default_factory=lambda: ["delete"])
    api_key: str | None = None

    @field_validator("collection_dir")
    @classmethod
    def validate_collection_dir(cls, v: Path) -> Path:
        resolved = v.resolve()
        if not resolved.exists():
            raise ConfigurationError(f"Bruno collection directory does not exist: {resolved}")
        return resolved

    @field_validator("request_file")
    @classmethod
    def validate_request_file(cls, v: Path | str | None, info: Any) -> Path | str | None:
        if v is None:
            return None
        col_dir = info.data.get("collection_dir")
        if col_dir and isinstance(col_dir, Path):
            req_path = Path(v)
            full_path = req_path if req_path.is_absolute() else col_dir.resolve() / req_path
            if not full_path.exists():
                raise ConfigurationError(f"Bruno request file does not exist: {full_path}")
        return v
