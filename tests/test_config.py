"""Unit tests for Pydantic configuration validation."""

from pathlib import Path

import pytest

from bruno_populator.config import BrunoRunConfig, DatasetDocumentConfig
from bruno_populator.exceptions import ConfigurationError


def test_dataset_document_config_valid(tmp_path: Path):
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    yaml_out = tmp_path / "out.yml"

    config = DatasetDocumentConfig(
        dataset_id="test-dataset-123",
        source_dir=source_dir,
        output_yaml_path=yaml_out,
    )

    assert config.dataset_id == "test-dataset-123"
    assert config.api_url == "http://localhost:9222/api/v1/datasets/test-dataset-123/documents"


def test_dataset_document_config_invalid_dir(tmp_path: Path):
    non_existent = tmp_path / "non_existent_folder"
    yaml_out = tmp_path / "out.yml"

    with pytest.raises(ConfigurationError, match="Source directory does not exist"):
        DatasetDocumentConfig(
            dataset_id="test",
            source_dir=non_existent,
            output_yaml_path=yaml_out,
        )


def test_bruno_run_config_valid(tmp_path: Path):
    col_dir = tmp_path / "collection"
    col_dir.mkdir()

    config = BrunoRunConfig(
        collection_dir=col_dir,
        exclude_tags=["delete", "draft"],
    )

    assert config.collection_dir == col_dir.resolve()
    assert config.exclude_tags == ["delete", "draft"]


def test_app_config_data_dir_validation(tmp_path: Path):
    from bruno_populator.config import AppConfig

    data_dir = tmp_path / "custom_data"
    data_dir.mkdir()

    # Should raise for missing requirements.md
    config = AppConfig(data_dir=data_dir)
    with pytest.raises(ConfigurationError, match="missing the required requirements file"):
        _ = config.requirements_path

    # Create requirements.md
    (data_dir / "requirements.md").write_text("# Requirements", encoding="utf-8")

    # Should raise for missing sources directory
    with pytest.raises(ConfigurationError, match="missing the required sources directory"):
        _ = config.sources_dir

    # Create sources directory
    (data_dir / "sources").mkdir()

    assert config.requirements_path == (data_dir / "requirements.md").resolve()
    assert config.sources_dir == (data_dir / "sources").resolve()


def test_load_app_config_from_env(tmp_path: Path):
    from bruno_populator.config import load_app_config

    env_file = tmp_path / ".env"
    env_file.write_text(
        'BASE_URL="http://localhost:9000"\nDEBUG=true\nDATA_DIR="data/Bicycle"\n',
        encoding="utf-8",
    )

    config = load_app_config(env_file)
    assert config.base_url == "http://localhost:9000"
    assert config.debug is True
