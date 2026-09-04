"""Unit tests for Bruno opencollection.yml token injection and cleanup."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from bruno_populator.config import AppConfig, BrunoRunConfig
from bruno_populator.pipeline.base_step import BaseCollectionStep
from bruno_populator.pipeline.context import PipelineContext
from bruno_populator.runner import run_bruno_collection, run_bruno_request
from bruno_populator.yml_injector import (
    clear_all_collection_tokens,
    clear_collection_token,
    inject_collection_token,
    sync_all_collection_tokens,
    temporary_collection_token,
)

SAMPLE_OPENCOLLECTION = """opencollection: 1.0.0

info:
  name: Test Collection
config:
  proxy:
    inherit: true

request:
  auth:
    type: bearer
    token: ""
bundled: false
"""


@pytest.fixture
def collection_with_opencol(tmp_path: Path) -> tuple[Path, Path]:
    """Create a temporary collection directory with a clean opencollection.yml."""
    col_dir = tmp_path / "test_collection"
    col_dir.mkdir()
    opencol_file = col_dir / "opencollection.yml"
    opencol_file.write_text(SAMPLE_OPENCOLLECTION, encoding="utf-8")
    return col_dir, opencol_file


def test_inject_and_clear_collection_token(collection_with_opencol: tuple[Path, Path]):
    """Verify injecting a token and clearing it resets the opencollection file."""
    col_dir, opencol_file = collection_with_opencol

    inject_collection_token(col_dir, "test-secret-token-123")
    content = opencol_file.read_text(encoding="utf-8")
    assert 'token: "test-secret-token-123"' in content

    clear_collection_token(col_dir)
    cleared_content = opencol_file.read_text(encoding="utf-8")
    assert 'token: ""' in cleared_content


def test_temporary_collection_token_success(collection_with_opencol: tuple[Path, Path]):
    """Verify temporary_collection_token restores original content on normal exit."""
    col_dir, opencol_file = collection_with_opencol
    original = opencol_file.read_text(encoding="utf-8")

    with temporary_collection_token(col_dir, token="temp-token-xyz"):
        in_block_content = opencol_file.read_text(encoding="utf-8")
        assert 'token: "temp-token-xyz"' in in_block_content

    restored = opencol_file.read_text(encoding="utf-8")
    assert restored == original


def test_temporary_collection_token_restores_on_exception(collection_with_opencol: tuple[Path, Path]):
    """Verify temporary_collection_token restores original content even when an exception occurs."""
    col_dir, opencol_file = collection_with_opencol
    original = opencol_file.read_text(encoding="utf-8")

    with pytest.raises(RuntimeError, match="Simulated crash"):
        with temporary_collection_token(col_dir, token="crash-token-999"):
            assert 'token: "crash-token-999"' in opencol_file.read_text(encoding="utf-8")
            raise RuntimeError("Simulated crash")

    restored = opencol_file.read_text(encoding="utf-8")
    assert restored == original


def test_temporary_collection_token_no_token(collection_with_opencol: tuple[Path, Path], monkeypatch):
    """Verify temporary_collection_token leaves file unchanged if no token is available."""
    col_dir, opencol_file = collection_with_opencol
    monkeypatch.delenv("RAGFLOW_API_KEY", raising=False)
    monkeypatch.delenv("API_KEY", raising=False)

    original = opencol_file.read_text(encoding="utf-8")
    with temporary_collection_token(col_dir, token=None):
        pass

    assert opencol_file.read_text(encoding="utf-8") == original


def test_temporary_collection_token_missing_opencollection(tmp_path: Path):
    """Verify temporary_collection_token yields without error if opencollection.yml is absent."""
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()

    with temporary_collection_token(empty_dir, token="some-token"):
        pass  # Should not raise


def test_sync_and_clear_all_collection_tokens(tmp_path: Path):
    """Verify syncing and clearing across multiple collection folders."""
    col1 = tmp_path / "col1"
    col2 = tmp_path / "col2"
    col1.mkdir()
    col2.mkdir()
    (col1 / "opencollection.yml").write_text(SAMPLE_OPENCOLLECTION, encoding="utf-8")
    (col2 / "opencollection.yml").write_text(SAMPLE_OPENCOLLECTION, encoding="utf-8")

    updated = sync_all_collection_tokens(token="sync-token-456", bruno_dir=tmp_path)
    assert len(updated) == 2
    for p in updated:
        assert 'token: "sync-token-456"' in p.read_text(encoding="utf-8")

    cleared = clear_all_collection_tokens(bruno_dir=tmp_path)
    assert len(cleared) == 2
    for p in cleared:
        assert 'token: ""' in p.read_text(encoding="utf-8")


@patch("subprocess.run")
def test_run_bruno_collection_injects_token_temporarily(mock_subproc, collection_with_opencol: tuple[Path, Path]):
    """Verify run_bruno_collection injects token during execution and cleans it up."""
    col_dir, opencol_file = collection_with_opencol
    token_during_run = None

    def capture_during_run(*args, **kwargs):
        nonlocal token_during_run
        token_during_run = opencol_file.read_text(encoding="utf-8")
        return MagicMock(returncode=0, stdout="", stderr="")

    mock_subproc.side_effect = capture_during_run

    config = BrunoRunConfig(collection_dir=col_dir, api_key="run-token-777")
    run_bruno_collection(config)

    assert token_during_run is not None
    assert 'token: "run-token-777"' in token_during_run
    # Reverted after execution
    assert 'token: ""' in opencol_file.read_text(encoding="utf-8")


@patch("subprocess.run")
def test_run_bruno_request_injects_token_temporarily(
    mock_subproc, collection_with_opencol: tuple[Path, Path], monkeypatch
):
    """Verify run_bruno_request injects token from env during execution and cleans it up."""
    col_dir, opencol_file = collection_with_opencol
    monkeypatch.setenv("RAGFLOW_API_KEY", "env-token-888")

    req_file = col_dir / "Single Request.yml"
    req_file.write_text("info:\n  name: Single", encoding="utf-8")

    token_during_run = None

    def capture_during_run(*args, **kwargs):
        nonlocal token_during_run
        token_during_run = opencol_file.read_text(encoding="utf-8")
        return MagicMock(returncode=0, stdout="", stderr="")

    mock_subproc.side_effect = capture_during_run

    run_bruno_request(req_file)

    assert token_during_run is not None
    assert 'token: "env-token-888"' in token_during_run
    # Reverted after execution
    assert 'token: ""' in opencol_file.read_text(encoding="utf-8")


class _DummyStep(BaseCollectionStep):
    @property
    def name(self) -> str:
        return "Dummy Step"

    def preprocess(self, context, item=None):
        pass

    def postprocess(self, context, result_data, item=None):
        pass

    def verify_result(self, context, result_data, item=None):
        pass

    def set_context(self, context, result_data, item=None):
        pass


def test_base_step_token_helpers(tmp_path: Path):
    """Verify BaseCollectionStep inject_collection_token and clear_collection_token methods."""
    step = _DummyStep(collection_dir=tmp_path)
    opencol = tmp_path / "opencollection.yml"
    opencol.write_text(SAMPLE_OPENCOLLECTION, encoding="utf-8")

    step.inject_collection_token("step-token-111")
    assert 'token: "step-token-111"' in opencol.read_text(encoding="utf-8")

    step.clear_collection_token()
    assert 'token: ""' in opencol.read_text(encoding="utf-8")


def test_app_config_and_pipeline_context_api_key(monkeypatch):
    """Verify AppConfig and PipelineContext expose api_key."""
    monkeypatch.setenv("RAGFLOW_API_KEY", "cfg-test-key")
    cfg = AppConfig(api_key="cfg-test-key")
    ctx = PipelineContext(config=cfg)
    assert ctx.api_key == "cfg-test-key"
