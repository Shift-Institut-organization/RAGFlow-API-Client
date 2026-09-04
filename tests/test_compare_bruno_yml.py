"""Test suite for verifying preprocessing hooks on Bruno YAML collection steps."""

import shutil
from pathlib import Path

import pytest

from bruno_populator.pipeline.base_step import BaseCollectionStep
from bruno_populator.pipeline.context import PipelineContext
from bruno_populator.steps import CreateChatsStep, CreateDatasetStep, CreateSystemPromptsStep
from paths import BRUNO_DIR

# Registry of active collection step classes for automated testing
REGISTERED_STEP_CLASSES: list[type[BaseCollectionStep]] = [
    CreateSystemPromptsStep,
    CreateDatasetStep,
    CreateChatsStep,
]


@pytest.mark.parametrize(
    "step_cls",
    REGISTERED_STEP_CLASSES,
    ids=lambda cls: cls.__name__,
)
def test_step_preprocess_execution(step_cls: type[BaseCollectionStep], tmp_path: Path):
    """Verify that step.preprocess executes cleanly on a copy of the collection directory."""
    ref_folder = BRUNO_DIR / step_cls(collection_dir=tmp_path).name
    assert ref_folder.exists(), f"Reference Bruno collection folder missing at {ref_folder}"

    # Copy reference YML files to isolated temp path
    col_copy = tmp_path / "step_collection"
    shutil.copytree(ref_folder, col_copy)

    # Isolated dummy data directory for preprocessing
    dummy_data = tmp_path / "data"
    dummy_data.mkdir()
    (dummy_data / "requirements.md").write_text("# Requirements\n", encoding="utf-8")
    dummy_sources = dummy_data / "sources"
    dummy_sources.mkdir()
    (dummy_sources / "doc1.pdf").write_bytes(b"%PDF-1.4 dummy")

    step = step_cls(collection_dir=col_copy)
    context = PipelineContext(base_url="http://localhost:9222", data_dir=dummy_data)
    context.set_data("dataset_id", "test_ds_id")
    context.set_data("generated_persona_prompts", {"persona_test": "Test Prompt"})

    items = step.get_items(context)
    if items:
        step.preprocess(context, item=items[0])
    else:
        step.preprocess(context)

    assert col_copy.exists()
    assert list(col_copy.glob("*.yml"))
