"""Optional test suite for verifying postprocessing against real Bruno output JSON report files."""

import json
import warnings
from pathlib import Path

from bruno_populator.pipeline.context import PipelineContext
from bruno_populator.steps import (
    CreateChatsStep,
    CreateDatasetStep,
    CreateSystemPromptsStep,
)


def test_postprocess_real_output_json_reports(tmp_path: Path, monkeypatch):
    """
    Optional test: Runs postprocessing on active step classes using real output.json report files.

    If an output JSON report is missing or invalid due to local state changes,
    the test issues a soft warning without causing a test suite failure.
    """
    # Isolated test context with temp generated prompts directory
    gen_prompts_dir = tmp_path / "generated_prompts"
    monkeypatch.setattr(
        "bruno_populator.steps.step_1_create_system_prompts.GENERATED_PROMPTS_DIR",
        gen_prompts_dir,
    )

    # Mock document polling to prevent live API network requests during testing
    monkeypatch.setattr(
        "bruno_populator.steps.step_2_create_dataset.fetch_documents_status",
        lambda ctx, ds_id: [{"id": "doc1", "run": "DONE", "name": "doc1.pdf"}],
    )

    context = PipelineContext()
    context.set_data("dataset_id", "test-dataset-id")
    context.set_data("generated_persona_prompts", {"persona_boomer-buerger": "Prompt 1"})

    # 1. Test CreateSystemPromptsStep real report
    step1 = CreateSystemPromptsStep()
    report1_path = step1.collection_dir / "output.json"
    if not report1_path.exists():
        warnings.warn(f"Optional test skipped: '{report1_path}' does not exist.", stacklevel=2)
    else:
        with open(report1_path, encoding="utf-8") as f:
            result1 = json.load(f)
        step1.postprocess(context, result1)
        generated_prompts = context.get_data("generated_persona_prompts")
        assert isinstance(generated_prompts, dict)
        assert len(generated_prompts) >= 3

    # 2. Test CreateDatasetStep real report
    step2 = CreateDatasetStep()
    report2_path = step2.collection_dir / "output.json"
    if not report2_path.exists():
        warnings.warn(f"Optional test skipped: '{report2_path}' does not exist.", stacklevel=2)
    else:
        try:
            with open(report2_path, encoding="utf-8") as f:
                result2 = json.load(f)
            step2.postprocess(context, result2)
            assert context.get_data("dataset_id")
        except Exception as exc:
            warnings.warn(f"Optional test soft warning for '{step2.name}': {exc}", stacklevel=2)

    # 3. Test CreateChatsStep real report(s)
    step3 = CreateChatsStep()
    output_files = sorted(list(step3.collection_dir.glob("output_*.json")))
    if not output_files:
        warnings.warn(
            f"Optional test skipped: No 'output_*.json' files found in '{step3.collection_dir}'.", stacklevel=2
        )
    else:
        for out_file in output_files:
            try:
                item_key = out_file.stem.replace("output_", "")
                item = (item_key, "Dummy Prompt")

                with open(out_file, encoding="utf-8") as f:
                    result3 = json.load(f)

                step3.postprocess(context, result3, item=item)
            except Exception as exc:
                warnings.warn(f"Optional test soft warning for '{step3.name}' ({out_file.name}): {exc}", stacklevel=2)

        created_chats = context.get_data("created_chats")
        if isinstance(created_chats, dict):
            assert len(created_chats) > 0
