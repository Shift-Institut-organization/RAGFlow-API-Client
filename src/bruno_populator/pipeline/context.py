"""Pipeline context state container shared across collection execution steps."""

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from bruno_populator.config import AppConfig, load_app_config
from bruno_populator.logger import get_logger
from paths import CONTEXT_STATE_FILENAME

logger = get_logger("bruno_populator.pipeline.context")


class PipelineContext(BaseModel):
    """Context state passed sequentially through Bruno collection steps."""

    config: AppConfig = Field(default_factory=load_app_config)
    metadata: dict[str, Any] = Field(default_factory=dict)

    def __init__(
        self,
        config: AppConfig | None = None,
        base_url: str | None = None,
        data_dir: Path | str | None = None,
        **data: Any,
    ):
        if config is None:
            if base_url is not None or data_dir is not None:
                default_cfg = load_app_config()
                cfg_base_url = base_url if base_url is not None else default_cfg.base_url
                cfg_data_dir = data_dir if data_dir is not None else default_cfg.data_dir
                config = AppConfig(base_url=cfg_base_url, data_dir=cfg_data_dir)
            else:
                config = load_app_config()
        data["config"] = config
        super().__init__(**data)

    @property
    def base_url(self) -> str:
        return self.config.base_url

    @property
    def api_key(self) -> str:
        return self.config.api_key

    @property
    def requirements_path(self) -> Path:
        return self.config.requirements_path

    @property
    def sources_dir(self) -> Path:
        return self.config.sources_dir

    @property
    def data_dir(self) -> Path:
        return self.config.data_dir

    @property
    def state_file_path(self) -> Path:
        return self.data_dir / CONTEXT_STATE_FILENAME

    def set_data(self, key: str, value: Any) -> None:
        """Store key-value data in pipeline context metadata."""
        logger.debug(f"Pipeline Context updated: {key} = {value}")
        self.metadata[key] = value

    def get_data(self, key: str, default: Any = None) -> Any:
        """Retrieve key-value data from pipeline context metadata."""
        return self.metadata.get(key, default)

    def save_state(self, file_path: Path) -> Path:
        """Persist context state to JSON file."""
        out_file = file_path.resolve()
        out_file.parent.mkdir(parents=True, exist_ok=True)
        with open(out_file, "w", encoding="utf-8") as f:
            json.dump(self.model_dump(mode="json"), f, indent=2)
        logger.info(f"Pipeline Context saved state to {out_file}")
        return out_file

    def save_to_data_dir(self) -> Path:
        """Persist current pipeline context state to context_state.json in data_dir."""
        return self.save_state(self.state_file_path)

    def load_existing_state(self) -> bool:
        """Load and merge existing context metadata from data_dir/context_state.json if present."""
        state_file = self.state_file_path
        if state_file.exists():
            try:
                with open(state_file, encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict) and "metadata" in data and isinstance(data["metadata"], dict):
                    for k, v in data["metadata"].items():
                        self.set_data(k, v)
                    logger.info(f"Loaded existing context state metadata from '{state_file}'.")
                    return True
            except Exception as exc:
                logger.warning(f"Failed to load existing context state from '{state_file}': {exc}")
        return False

    @classmethod
    def load_state(cls, file_path: Path) -> "PipelineContext":
        """Load context state from JSON file."""
        in_file = file_path.resolve()
        with open(in_file, encoding="utf-8") as f:
            data = json.load(f)
        logger.info(f"Pipeline Context loaded state from {in_file}")
        return cls(**data)
