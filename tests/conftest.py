"""Pytest test configuration and global fixtures."""

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def isolate_single_calls_dir(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> Path:
    """
    Ensure all tests run with an isolated single_calls directory in tmp_path.
    Prevents tests from modifying live files in bruno/RAGFlowApiClient/collections/RAGFlow single calls/
    while scripts or pipelines are running in parallel.
    """
    test_dir = tmp_path_factory.mktemp("single_calls")
    monkeypatch.setattr(
        "bruno_populator.steps.step_2_create_dataset.DEFAULT_SINGLE_CALLS_DIR",
        test_dir,
    )
    return test_dir
