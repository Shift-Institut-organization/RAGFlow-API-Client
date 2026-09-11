"""Unit tests for PipelineContext, BaseCollectionStep, and PipelineRunner."""

import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from bruno_populator.exceptions import BrunoPopulatorError
from bruno_populator.pipeline.base_step import BaseCollectionStep
from bruno_populator.pipeline.context import PipelineContext
from bruno_populator.pipeline.orchestrator import PipelineRunner
from bruno_populator.steps.step_1_create_system_prompts import (
    CreateSystemPromptsStep,
    parse_persona_prompts,
    sanitize_persona_filename,
)


class MockStep(BaseCollectionStep):
    def __init__(self, step_name: str, target_dir: Path):
        self._name = step_name
        self._target_dir = target_dir
        self.preprocessed = False
        self.postprocessed = False
        self.verified = False
        self.context_set = False

    @property
    def name(self) -> str:
        return self._name

    @property
    def collection_dir(self) -> Path:
        return self._target_dir

    def get_item_key(self, item: Any) -> str:
        return str(item[0]) if isinstance(item, tuple | list) and item else str(item)

    def preprocess(self, context: PipelineContext, item: Any | None = None) -> None:
        self.preprocessed = True
        context.set_data(f"{self.name}_pre", True)

    def verify_result(
        self,
        context: PipelineContext,
        result_data: dict[str, Any] | list[Any] | None,
        item: Any | None = None,
    ) -> None:
        self.verified = True

    def set_context(
        self,
        context: PipelineContext,
        result_data: dict[str, Any] | list[Any] | None,
        item: Any | None = None,
    ) -> None:
        self.postprocessed = True
        self.context_set = True
        context.set_data(f"{self.name}_post", True)


def test_pipeline_context_embeds_app_config(tmp_path: Path):
    from bruno_populator.config import AppConfig

    data_dir = tmp_path / "test_data"
    data_dir.mkdir()
    (data_dir / "requirements.md").write_text("# Req", encoding="utf-8")
    (data_dir / "sources").mkdir()

    cfg = AppConfig(base_url="http://localhost:8080", data_dir=data_dir)
    context = PipelineContext(config=cfg)

    assert context.config == cfg
    assert context.base_url == "http://localhost:8080"
    assert context.requirements_path == (data_dir / "requirements.md").resolve()
    assert context.sources_dir == (data_dir / "sources").resolve()


def test_pipeline_context_serialization(tmp_path: Path):
    ctx = PipelineContext(base_url="http://localhost:9222")
    ctx.set_data("key1", "val1")

    saved = ctx.save_state(tmp_path / "state.json")
    loaded = PipelineContext.load_state(saved)

    assert loaded.base_url == "http://localhost:9222"
    assert loaded.get_data("key1") == "val1"


def test_pipeline_context_save_and_load_existing_state(tmp_path: Path):
    from bruno_populator.config import AppConfig

    data_dir = tmp_path / "test_data"
    data_dir.mkdir()
    (data_dir / "requirements.md").write_text("# Req", encoding="utf-8")
    (data_dir / "sources").mkdir()

    cfg = AppConfig(data_dir=data_dir)
    ctx1 = PipelineContext(config=cfg)
    ctx1.set_data("dataset_id", "ds-999")
    ctx1.set_data("test_key", "test_val")

    # Save state to data_dir/context_state.json
    saved_path = ctx1.save_to_data_dir()
    assert saved_path.exists()
    assert saved_path.name == "context_state.json"

    # Create new context pointing to same data_dir and load existing state
    ctx2 = PipelineContext(config=cfg)
    assert ctx2.get_data("dataset_id") is None
    loaded_ok = ctx2.load_existing_state()
    assert loaded_ok is True
    assert ctx2.get_data("dataset_id") == "ds-999"
    assert ctx2.get_data("test_key") == "test_val"


def test_parse_persona_prompts_unfenced_and_fenced():
    sample_text = """Hier sind die maßgeschneiderten System-Prompts:

---

# System-Prompt für Persona: Hannelore (Boomer-Generation)

Du bist ein KI-Simulator.
der context: {knowledge}

---

# System-Prompt für Persona: Marc (Entscheidungsträger)

Du bist ein KI-Simulator.
der context: {knowledge}
```

---

# System-Prompt: Sarah (Pflegekraft)

Du bist ein KI-Simulator.
der context: {knowledge}
"""

    parsed = parse_persona_prompts(sample_text)
    assert len(parsed) == 3

    name1, prompt1 = parsed[0]
    assert name1 == "Hannelore (Boomer-Generation)"
    assert "{knowledge}" in prompt1
    assert sanitize_persona_filename(name1) == "persona_hannelore_boomer-generation.md"

    name2, prompt2 = parsed[1]
    assert name2 == "Marc (Entscheidungsträger)"
    assert "{knowledge}" in prompt2

    name3, prompt3 = parsed[2]
    assert name3 == "Sarah (Pflegekraft)"
    assert "{knowledge}" in prompt3


def test_parse_persona_prompts_missing_knowledge_hard_fails():
    sample_text = """# System-Prompt für Persona: Hannelore
Du bist ein KI-Simulator ohne knowledge.
"""
    with pytest.raises(BrunoPopulatorError, match="No '{knowledge}' placeholder found in LLM output text"):
        parse_persona_prompts(sample_text)


def test_parse_persona_prompts_duplicate_names_increment():
    sample_text = """# System-Prompt für Persona: Hannelore
Du bist Hannelore 1.
der context: {knowledge}

# System-Prompt für Persona: Hannelore
Du bist Hannelore 2.
der context: {knowledge}
"""
    parsed = parse_persona_prompts(sample_text)
    assert len(parsed) == 2
    assert parsed[0][0] == "Hannelore"
    assert parsed[1][0] == "Hannelore 2"


@patch("bruno_populator.pipeline.orchestrator.run_bruno_collection")
def test_pipeline_runner_sequential_execution(mock_run_bruno, tmp_path: Path):
    col1 = tmp_path / "col1"
    col2 = tmp_path / "col2"
    col1.mkdir()
    col2.mkdir()

    mock_run_bruno.return_value = {"results": [{"name": "req", "status": "pass"}]}

    step1 = MockStep("Step1", col1)
    step2 = MockStep("Step2", col2)

    runner = PipelineRunner(steps=[step1, step2])
    ctx = runner.run()

    assert step1.preprocessed and step1.postprocessed
    assert step2.preprocessed and step2.postprocessed
    assert ctx.get_data("Step1_pre") is True
    assert ctx.get_data("Step2_post") is True
    assert mock_run_bruno.call_count == 2


@patch("bruno_populator.pipeline.orchestrator.run_bruno_collection")
def test_pipeline_runner_halts_on_preprocess_error(mock_run_bruno, tmp_path: Path):
    col1 = tmp_path / "col1"
    col1.mkdir()

    class FailingStep(MockStep):
        def preprocess(self, context: PipelineContext, item: Any | None = None) -> None:
            raise ValueError("Preprocessing error")

    step = FailingStep("FailingStep", col1)
    runner = PipelineRunner(steps=[step])

    with pytest.raises(BrunoPopulatorError, match="Preprocessing error"):
        runner.run()

    assert mock_run_bruno.call_count == 0


def test_base_step_load_markdown_prompt(tmp_path: Path):
    prompt_file = tmp_path / "test_prompt.md"
    prompt_file.write_text("Hello Prompt World\n", encoding="utf-8")

    loaded = BaseCollectionStep.load_markdown_prompt(prompt_file)
    assert loaded == "Hello Prompt World"


def test_base_step_load_markdown_prompt_missing_raises(tmp_path: Path):
    missing_file = tmp_path / "missing.md"
    with pytest.raises(FileNotFoundError, match="System prompt markdown file not found"):
        BaseCollectionStep.load_markdown_prompt(missing_file)


def test_base_step_inject_prompt_into_payload_valid():
    payload = {"name": "Test", "prompt_config": {"system": ""}}
    updated = BaseCollectionStep.inject_prompt_into_payload(payload, "prompt_config.system", "New System Prompt")
    assert updated["prompt_config"]["system"] == "New System Prompt"


def test_base_step_inject_prompt_into_payload_invalid_key_raises():
    payload = {"name": "Test", "prompt_config": {}}
    with pytest.raises(KeyError, match="Target key 'missing_key'"):
        BaseCollectionStep.inject_prompt_into_payload(payload, "prompt_config.missing_key", "New Prompt")


def test_base_step_load_payload_with_prompt_full_flow(tmp_path: Path):
    json_path = tmp_path / "payload.json"
    json_path.write_text(json.dumps({"name": "Chat", "prompt_config": {"system": ""}}), encoding="utf-8")

    md_path = tmp_path / "prompt.md"
    md_path.write_text("# Persona Prompt\nDu bist ein KI-Assistent.", encoding="utf-8")

    result = BaseCollectionStep.load_payload_with_prompt(
        json_path=json_path,
        prompt_path=md_path,
        key_path="prompt_config.system",
    )

    assert result["name"] == "Chat"
    assert "Du bist ein KI-Assistent." in result["prompt_config"]["system"]


def test_create_system_prompts_step_auto_creates_collection_dir(tmp_path: Path):
    prompt_file = tmp_path / "prompt.md"
    prompt_file.write_text("prompt", encoding="utf-8")
    missing_col = tmp_path / "missing_bruno_col"

    step = CreateSystemPromptsStep(collection_dir=missing_col, prompt_path=prompt_file)
    assert step.collection_dir.exists()
    assert step.collection_dir.is_dir()


def test_create_system_prompts_step_missing_prompt_raises(tmp_path: Path):
    valid_col = tmp_path / "col"
    valid_col.mkdir()
    missing_prompt = tmp_path / "missing_prompt.md"

    with pytest.raises(FileNotFoundError, match="System prompt file not found"):
        CreateSystemPromptsStep(collection_dir=valid_col, prompt_path=missing_prompt)


def test_base_step_load_script_file(tmp_path: Path):
    js_file = tmp_path / "test_after.js"
    js_file.write_text("const x = 1;\nbru.setVar('x', x);", encoding="utf-8")

    loaded = BaseCollectionStep.load_script_file(js_file)
    assert loaded == "const x = 1;\nbru.setVar('x', x);"


def test_pipeline_runner_skip_flags(tmp_path: Path, monkeypatch):
    from unittest.mock import MagicMock

    step = MagicMock(spec=BaseCollectionStep)
    step.name = "Test Step"
    step.collection_dir = tmp_path
    step.env = None
    step.exclude_tags = ["delete"]
    step.skip_preprocess = True
    step.skip_run = False
    step.skip_postprocess = True

    # Mock runner execution
    monkeypatch.setattr("bruno_populator.pipeline.orchestrator.run_bruno_collection", lambda cfg: {})

    context = PipelineContext()
    runner = PipelineRunner(steps=[step], context=context)
    runner.run()

    step.preprocess.assert_not_called()
    step.postprocess.assert_not_called()


def test_extract_value_by_key_path():
    data = [
        {
            "results": [
                {},
                {},
                {"response": {"data": {"data": {"answer": "extracted answer text"}}}},
            ]
        }
    ]

    val = BaseCollectionStep.extract_value_by_key_path(data, "[0].results[2].response.data.data.answer")
    assert val == "extracted answer text"

    # Test non-existent key path
    assert BaseCollectionStep.extract_value_by_key_path(data, "[0].results[5].response") is None
    assert BaseCollectionStep.extract_value_by_key_path(None, "[0]") is None


def test_create_system_prompts_postprocess(tmp_path: Path, monkeypatch):
    from bruno_populator.steps.step_1_create_system_prompts import (
        CreateSystemPromptsStep,
        parse_persona_prompts,
    )

    sample_answer = (
        "Hier sind die System-Prompts:\n\n"
        "# System-Prompt für Persona: Günther\n"
        "```text\n"
        "Du bist Günther.\n"
        "DEINE IDENTITÄT:\n"
        "- NAME: Günther\n"
        "- ALTER: 60\n"
        "- CHARAKTER & SPRACHSTIL: Ruhig\n"
        "- PROJEKT-ROLLE: Bürger\n"
        "- HAUPTBEDÜRFNIS: Sicherheit\n"
        "der context: {knowledge}\n"
        "```\n\n"
        "# System-Prompt für Persona: Sabine\n"
        "```text\n"
        "Du bist Sabine.\n"
        "DEINE IDENTITÄT:\n"
        "- NAME: Sabine\n"
        "- ALTER: 45\n"
        "- CHARAKTER & SPRACHSTIL: Analytisch\n"
        "- PROJEKT-ROLLE: Leitung\n"
        "- HAUPTBEDÜRFNIS: Planung\n"
        "der context: {knowledge}\n"
        "```\n"
    )

    parsed = parse_persona_prompts(sample_answer)
    assert len(parsed) == 2
    assert parsed[0][0] == "Günther"
    assert "Du bist Günther." in parsed[0][1]
    assert parsed[1][0] == "Sabine"

    # Test step postprocess execution
    prompt_file = tmp_path / "prompt.md"
    prompt_file.write_text("prompt", encoding="utf-8")
    col_dir = tmp_path / "col"
    col_dir.mkdir()

    # Monkeypatch GENERATED_PROMPTS_DIR to isolated test temp path
    gen_dir = tmp_path / "generated"
    monkeypatch.setattr("bruno_populator.steps.step_1_create_system_prompts.GENERATED_PROMPTS_DIR", gen_dir)

    step = CreateSystemPromptsStep(collection_dir=col_dir, prompt_path=prompt_file)
    context = PipelineContext()

    mock_result = [
        {
            "results": [
                {"response": {"data": {"data": {"id": "chat-gen-123"}}}},
                {"response": {"data": {"data": {"id": "doc-req-456"}}}},
                {"response": {"data": {"data": {"answer": sample_answer}}}},
            ]
        }
    ]

    step.postprocess(context, mock_result)

    persona_prompts = context.get_data("generated_persona_prompts")
    assert isinstance(persona_prompts, dict)
    assert len(persona_prompts) == 2
    assert "persona_guenther" in persona_prompts
    assert "persona_sabine" in persona_prompts
    assert "Du bist Günther." in persona_prompts["persona_guenther"]
    assert (gen_dir / "persona_guenther.md").exists()
    assert (gen_dir / "persona_sabine.md").exists()
    assert "Du bist Günther." in (gen_dir / "persona_guenther.md").read_text(encoding="utf-8")

    # Verify hard failure when answer is missing
    bad_result = [
        {
            "results": [
                {"response": {"data": {"data": {"id": "chat-gen-123"}}}},
                {"response": {"data": {"data": {"id": "doc-req-456"}}}},
                {"response": {"data": {"data": {}}}},
            ]
        }
    ]
    with pytest.raises(BrunoPopulatorError, match="Failed to find generated prompt answer string"):
        step.postprocess(context, bad_result)


def test_create_dataset_postprocess_extracts_id(tmp_path: Path, monkeypatch):
    from bruno_populator.steps.step_2_create_dataset import CreateDatasetStep

    col_dir = tmp_path / "col"
    col_dir.mkdir()

    step = CreateDatasetStep(collection_dir=col_dir)
    context = PipelineContext()

    mock_result = [
        {
            "results": [
                {"response": {"data": {"data": {"id": "dataset-123-abc"}}}},
            ]
        }
    ]

    parsed_calls = []
    monkeypatch.setattr(
        "bruno_populator.steps.step_2_create_dataset.parse_documents_sequentially",
        lambda *args, **kwargs: parsed_calls.append(kwargs.get("dataset_id") or (args[1] if len(args) > 1 else None)),
    )

    step.postprocess(context, mock_result)

    assert context.get_data("dataset_id") == "dataset-123-abc"
    assert parsed_calls == ["dataset-123-abc"]

    # Verify hard failure when dataset ID is missing
    with pytest.raises(BrunoPopulatorError, match="Failed to extract created dataset ID"):
        step.postprocess(context, [{"results": [{}]}])


def test_sequential_document_parsing_all_succeed_first_try(monkeypatch):
    from bruno_populator.steps.step_2_create_dataset import parse_documents_sequentially

    context = PipelineContext()
    triggered_docs = []

    mock_docs = [
        {"id": "doc1", "name": "doc1.pdf", "run": "UNSTART", "progress_msg": ""},
        {"id": "doc2", "name": "doc2.pdf", "run": "UNSTART", "progress_msg": ""},
    ]

    def mock_fetch(ctx, ds_id):
        current_docs = []
        for d in mock_docs:
            d_copy = dict(d)
            if d["id"] in triggered_docs:
                d_copy["run"] = "DONE"
            current_docs.append(d_copy)
        return current_docs

    def mock_trigger(ctx, ds_id, doc_id):
        triggered_docs.append(doc_id)

    monkeypatch.setattr("bruno_populator.steps.step_2_create_dataset.fetch_documents_status", mock_fetch)
    monkeypatch.setattr("bruno_populator.steps.step_2_create_dataset.trigger_document_parse", mock_trigger)

    parse_documents_sequentially(context, "dataset-test", poll_interval=0.001)

    assert triggered_docs == ["doc1", "doc2"]


def test_sequential_document_parsing_retry_success(monkeypatch):
    from bruno_populator.steps.step_2_create_dataset import parse_documents_sequentially

    context = PipelineContext()
    trigger_counts: dict[str, int] = {}

    def mock_trigger(ctx, ds_id, doc_id):
        trigger_counts[doc_id] = trigger_counts.get(doc_id, 0) + 1

    def mock_fetch(ctx, ds_id):
        docs = []
        doc1_status = "DONE" if trigger_counts.get("doc1", 0) >= 1 else "UNSTART"
        docs.append({"id": "doc1", "name": "doc1.pdf", "run": doc1_status, "progress_msg": ""})

        doc2_count = trigger_counts.get("doc2", 0)
        if doc2_count == 0:
            doc2_status = "UNSTART"
            doc2_msg = ""
        elif doc2_count == 1:
            doc2_status = "FAIL"
            doc2_msg = "Temporary failure"
        else:
            doc2_status = "DONE"
            doc2_msg = ""
        docs.append({"id": "doc2", "name": "doc2.pdf", "run": doc2_status, "progress_msg": doc2_msg})

        return docs

    monkeypatch.setattr("bruno_populator.steps.step_2_create_dataset.fetch_documents_status", mock_fetch)
    monkeypatch.setattr("bruno_populator.steps.step_2_create_dataset.trigger_document_parse", mock_trigger)

    parse_documents_sequentially(context, "dataset-test", poll_interval=0.001)

    assert trigger_counts["doc1"] == 1
    assert trigger_counts["doc2"] == 2


def test_sequential_document_parsing_retry_hard_failure(monkeypatch):
    from bruno_populator.steps.step_2_create_dataset import parse_documents_sequentially

    context = PipelineContext()
    trigger_counts: dict[str, int] = {}

    def mock_trigger(ctx, ds_id, doc_id):
        trigger_counts[doc_id] = trigger_counts.get(doc_id, 0) + 1

    def mock_fetch(ctx, ds_id):
        doc1_status = "DONE" if trigger_counts.get("doc1", 0) >= 1 else "UNSTART"
        doc2_count = trigger_counts.get("doc2", 0)
        doc2_status = "FAIL" if doc2_count >= 1 else "UNSTART"

        return [
            {"id": "doc1", "name": "doc1.pdf", "run": doc1_status, "progress_msg": ""},
            {"id": "doc2", "name": "doc2.pdf", "run": doc2_status, "progress_msg": "Corrupt document"},
        ]

    monkeypatch.setattr("bruno_populator.steps.step_2_create_dataset.fetch_documents_status", mock_fetch)
    monkeypatch.setattr("bruno_populator.steps.step_2_create_dataset.trigger_document_parse", mock_trigger)

    with pytest.raises(BrunoPopulatorError, match="Document parsing failed on second attempt"):
        parse_documents_sequentially(context, "dataset-test", poll_interval=0.001)

    assert trigger_counts["doc1"] == 1
    assert trigger_counts["doc2"] == 2


def test_sequential_document_parsing_trigger_error_retry(monkeypatch):
    from bruno_populator.steps.step_2_create_dataset import parse_documents_sequentially

    context = PipelineContext()
    trigger_counts: dict[str, int] = {}

    def mock_trigger(ctx, ds_id, doc_id):
        trigger_counts[doc_id] = trigger_counts.get(doc_id, 0) + 1
        if trigger_counts[doc_id] == 1:
            raise BrunoPopulatorError("CLI execution error on attempt 1")

    def mock_fetch(ctx, ds_id):
        doc1_count = trigger_counts.get("doc1", 0)
        status = "DONE" if doc1_count >= 2 else "UNSTART"
        return [{"id": "doc1", "name": "doc1.pdf", "run": status, "progress_msg": ""}]

    monkeypatch.setattr("bruno_populator.steps.step_2_create_dataset.fetch_documents_status", mock_fetch)
    monkeypatch.setattr("bruno_populator.steps.step_2_create_dataset.trigger_document_parse", mock_trigger)

    parse_documents_sequentially(context, "dataset-test", poll_interval=0.001)
    assert trigger_counts["doc1"] == 2


def test_trigger_document_parse_api_error(monkeypatch):
    from bruno_populator.steps.step_2_create_dataset import trigger_document_parse

    context = PipelineContext(base_url="http://localhost:9222")

    mock_error_report = [
        {
            "results": [
                {
                    "response": {
                        "status": 200,
                        "data": {
                            "code": 102,
                            "message": "Document parsing service unavailable",
                        },
                    }
                }
            ]
        }
    ]

    monkeypatch.setattr(
        "bruno_populator.steps.step_2_create_dataset.run_bruno_request", lambda req_file: mock_error_report
    )

    with pytest.raises(BrunoPopulatorError, match="RAGFlow API error starting document parsing"):
        trigger_document_parse(context, "ds-1", "doc-1")


def test_sequential_document_parsing_progress_resets_timeout(monkeypatch):
    import time

    from bruno_populator.steps.step_2_create_dataset import parse_documents_sequentially

    context = PipelineContext()
    call_count = 0

    def mock_fetch(ctx, ds_id):
        nonlocal call_count
        call_count += 1
        time.sleep(0.01)
        if call_count == 1:
            return [
                {
                    "id": "doc1",
                    "name": "doc1.pdf",
                    "run": "RUNNING",
                    "progress": 0.1,
                    "chunk_count": 1,
                    "progress_msg": "Started",
                }
            ]
        elif call_count == 2:
            return [
                {
                    "id": "doc1",
                    "name": "doc1.pdf",
                    "run": "RUNNING",
                    "progress": 0.5,
                    "chunk_count": 5,
                    "progress_msg": "Parsing",
                }
            ]
        return [
            {
                "id": "doc1",
                "name": "doc1.pdf",
                "run": "DONE",
                "progress": 1.0,
                "chunk_count": 10,
                "progress_msg": "Completed",
            }
        ]

    monkeypatch.setattr("bruno_populator.steps.step_2_create_dataset.fetch_documents_status", mock_fetch)
    monkeypatch.setattr(
        "bruno_populator.steps.step_2_create_dataset.trigger_document_parse", lambda ctx, ds, doc_id: None
    )

    parse_documents_sequentially(context, "dataset-test", poll_interval=0.001, doc_timeout=0.015)
    assert call_count >= 3


def test_sequential_document_parsing_timeout_when_no_progress(monkeypatch):
    import time

    from bruno_populator.steps.step_2_create_dataset import parse_documents_sequentially

    context = PipelineContext()
    trigger_counts: dict[str, int] = {}

    def mock_trigger(ctx, ds_id, doc_id):
        trigger_counts[doc_id] = trigger_counts.get(doc_id, 0) + 1

    def mock_fetch(ctx, ds_id):
        time.sleep(0.005)
        count = trigger_counts.get("doc1", 0)
        if count == 0:
            return [
                {
                    "id": "doc1",
                    "name": "doc1.pdf",
                    "run": "UNSTART",
                    "progress": 0.0,
                    "chunk_count": 0,
                    "progress_msg": "",
                }
            ]
        elif count == 1:
            return [
                {
                    "id": "doc1",
                    "name": "doc1.pdf",
                    "run": "RUNNING",
                    "progress": 0.1,
                    "chunk_count": 1,
                    "progress_msg": "Frozen",
                }
            ]
        return [
            {
                "id": "doc1",
                "name": "doc1.pdf",
                "run": "DONE",
                "progress": 1.0,
                "chunk_count": 10,
                "progress_msg": "Done",
            }
        ]

    monkeypatch.setattr("bruno_populator.steps.step_2_create_dataset.fetch_documents_status", mock_fetch)
    monkeypatch.setattr("bruno_populator.steps.step_2_create_dataset.trigger_document_parse", mock_trigger)

    parse_documents_sequentially(context, "dataset-test", poll_interval=0.002, doc_timeout=0.01)
    assert trigger_counts["doc1"] == 2


def test_sequential_document_parsing_recheck_completes_in_background(monkeypatch):
    import time

    from bruno_populator.steps.step_2_create_dataset import parse_documents_sequentially

    context = PipelineContext()
    trigger_counts: dict[str, int] = {}

    def mock_trigger(ctx, ds_id, doc_id):
        trigger_counts[doc_id] = trigger_counts.get(doc_id, 0) + 1

    def mock_fetch(ctx, ds_id):
        time.sleep(0.002)
        if trigger_counts.get("doc2", 0) >= 1:
            doc1_run = "DONE"
            doc1_prog = 1.0
        else:
            doc1_run = "RUNNING"
            doc1_prog = 0.1

        doc2_run = "DONE" if trigger_counts.get("doc2", 0) >= 1 else "UNSTART"

        return [
            {
                "id": "doc1",
                "name": "doc1.pdf",
                "run": doc1_run,
                "progress": doc1_prog,
                "chunk_count": 1,
                "progress_msg": "",
            },
            {
                "id": "doc2",
                "name": "doc2.pdf",
                "run": doc2_run,
                "progress": 0.0,
                "chunk_count": 0,
                "progress_msg": "",
            },
        ]

    monkeypatch.setattr("bruno_populator.steps.step_2_create_dataset.fetch_documents_status", mock_fetch)
    monkeypatch.setattr("bruno_populator.steps.step_2_create_dataset.trigger_document_parse", mock_trigger)

    parse_documents_sequentially(context, "dataset-test", poll_interval=0.001, doc_timeout=0.005)

    assert trigger_counts["doc1"] == 1
    assert trigger_counts["doc2"] == 1


def test_sequential_document_parsing_recheck_running_with_progress_finishes(monkeypatch):
    import time

    from bruno_populator.steps.step_2_create_dataset import parse_documents_sequentially

    context = PipelineContext()
    trigger_counts: dict[str, int] = {}
    phase2_polls = 0

    def mock_trigger(ctx, ds_id, doc_id):
        trigger_counts[doc_id] = trigger_counts.get(doc_id, 0) + 1

    def mock_fetch(ctx, ds_id):
        nonlocal phase2_polls
        time.sleep(0.002)
        if trigger_counts.get("doc2", 0) == 0:
            return [
                {
                    "id": "doc1",
                    "name": "doc1.pdf",
                    "run": "RUNNING",
                    "progress": 0.1,
                    "chunk_count": 1,
                    "progress_msg": "OCR",
                },
                {
                    "id": "doc2",
                    "name": "doc2.pdf",
                    "run": "UNSTART",
                    "progress": 0.0,
                    "chunk_count": 0,
                    "progress_msg": "",
                },
            ]

        doc2_run = "DONE"
        if phase2_polls == 0:
            doc1_run = "RUNNING"
            doc1_prog = 0.8
            phase2_polls += 1
        else:
            doc1_run = "DONE"
            doc1_prog = 1.0

        return [
            {
                "id": "doc1",
                "name": "doc1.pdf",
                "run": doc1_run,
                "progress": doc1_prog,
                "chunk_count": 5,
                "progress_msg": "Chunking",
            },
            {
                "id": "doc2",
                "name": "doc2.pdf",
                "run": doc2_run,
                "progress": 1.0,
                "chunk_count": 2,
                "progress_msg": "",
            },
        ]

    monkeypatch.setattr("bruno_populator.steps.step_2_create_dataset.fetch_documents_status", mock_fetch)
    monkeypatch.setattr("bruno_populator.steps.step_2_create_dataset.trigger_document_parse", mock_trigger)

    parse_documents_sequentially(context, "dataset-test", poll_interval=0.001, doc_timeout=0.005)

    assert trigger_counts["doc1"] == 1
    assert trigger_counts["doc2"] == 1


def test_sequential_document_parsing_all_documents_get_second_attempt_before_hard_fail(monkeypatch):
    from bruno_populator.steps.step_2_create_dataset import parse_documents_sequentially

    context = PipelineContext()
    trigger_counts: dict[str, int] = {}

    def mock_trigger(ctx, ds_id, doc_id):
        trigger_counts[doc_id] = trigger_counts.get(doc_id, 0) + 1

    def mock_fetch(ctx, ds_id):
        return [
            {"id": "doc1", "name": "doc1.pdf", "run": "FAIL", "progress_msg": "Doc 1 Error"},
            {"id": "doc2", "name": "doc2.pdf", "run": "FAIL", "progress_msg": "Doc 2 Error"},
        ]

    monkeypatch.setattr("bruno_populator.steps.step_2_create_dataset.fetch_documents_status", mock_fetch)
    monkeypatch.setattr("bruno_populator.steps.step_2_create_dataset.trigger_document_parse", mock_trigger)

    with pytest.raises(BrunoPopulatorError, match="Document parsing failed on second attempt for 2 document"):
        parse_documents_sequentially(context, "dataset-test", poll_interval=0.001, doc_timeout=0.01)

    assert trigger_counts["doc1"] == 2
    assert trigger_counts["doc2"] == 2


@patch("bruno_populator.pipeline.orchestrator.run_bruno_collection")
def test_pipeline_runner_skip_run_success(mock_run_bruno, tmp_path: Path):
    col = tmp_path / "col"
    col.mkdir()
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    context = PipelineContext(data_dir=data_dir)

    class SkipRunStep(MockStep):
        def __init__(self, target_dir: Path):
            super().__init__("SkipRunStep", target_dir)
            self._skip_run = True

    step = SkipRunStep(col)
    output_json = context.get_output_json_path(step.name)
    output_json.write_text(json.dumps([{"results": [{"response": "ok"}]}]), encoding="utf-8")

    runner = PipelineRunner(steps=[step], context=context)
    ctx = runner.run()

    assert step.preprocessed and step.postprocessed
    assert mock_run_bruno.call_count == 0
    assert ctx.get_data("SkipRunStep_post") is True


@patch("bruno_populator.pipeline.orchestrator.run_bruno_collection")
def test_pipeline_runner_skip_run_hard_fails_if_output_json_missing(mock_run_bruno, tmp_path: Path):
    col = tmp_path / "col"
    col.mkdir()
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    context = PipelineContext(data_dir=data_dir)

    class SkipRunStep(MockStep):
        def __init__(self, target_dir: Path):
            super().__init__("SkipRunStep", target_dir)
            self._skip_run = True

    step = SkipRunStep(col)
    runner = PipelineRunner(steps=[step], context=context)

    with pytest.raises(FileNotFoundError, match="required output JSON report not found"):
        runner.run()

    assert mock_run_bruno.call_count == 0


def test_context_get_output_json_path(tmp_path: Path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    context = PipelineContext(data_dir=data_dir)

    assert context.get_output_json_path("Step One") == data_dir / "steps" / "Step One.json"
    assert context.get_output_json_path("Step One", "persona_a") == data_dir / "steps" / "Step One_persona_a.json"


def test_get_item_key_not_implemented_error(tmp_path: Path):
    class UnimplementedItemStep(BaseCollectionStep):
        @property
        def name(self) -> str:
            return "UnimplementedItemStep"

        def preprocess(self, context: PipelineContext, item: Any | None = None) -> None:
            pass

        def verify_result(
            self,
            context: PipelineContext,
            result_data: dict[str, Any] | list[Any] | None,
            item: Any | None = None,
        ) -> None:
            pass

        def set_context(
            self,
            context: PipelineContext,
            result_data: dict[str, Any] | list[Any] | None,
            item: Any | None = None,
        ) -> None:
            pass

    step = UnimplementedItemStep(collection_dir=tmp_path)
    with pytest.raises(NotImplementedError, match="utilizes item iteration but has not overridden get_item_key"):
        step.get_item_key("some_item")


def test_verify_result_and_set_context_not_implemented_error(tmp_path: Path):
    class UnimplementedHooksStep(BaseCollectionStep):
        @property
        def name(self) -> str:
            return "UnimplementedHooksStep"

        def preprocess(self, context: PipelineContext, item: Any | None = None) -> None:
            pass

        def verify_result(
            self,
            context: PipelineContext,
            result_data: dict[str, Any] | list[Any] | None,
            item: Any | None = None,
        ) -> None:
            return super().verify_result(context, result_data, item=item)

        def set_context(
            self,
            context: PipelineContext,
            result_data: dict[str, Any] | list[Any] | None,
            item: Any | None = None,
        ) -> None:
            return super().set_context(context, result_data, item=item)

    step = UnimplementedHooksStep(collection_dir=tmp_path)
    ctx = PipelineContext()
    with pytest.raises(NotImplementedError, match="must implement verify_result"):
        step.postprocess(ctx, {})


def test_verify_bruno_collection_results_valid_and_failures(tmp_path: Path):
    step = MockStep("TestStep", tmp_path)

    # 1. Valid report
    valid_report = [
        {
            "results": [
                {
                    "status": "pass",
                    "response": {"status": 200, "data": {"code": 0, "message": "success", "data": {"id": "123"}}},
                }
            ]
        }
    ]
    entries = step.verify_bruno_collection_results(valid_report, expected_request_count=1)
    assert len(entries) == 1

    # 2. None / Empty report
    with pytest.raises(BrunoPopulatorError, match="No result data report found"):
        step.verify_bruno_collection_results(None)

    # 3. Expected request count mismatch
    with pytest.raises(BrunoPopulatorError, match="Expected 2 request execution"):
        step.verify_bruno_collection_results(valid_report, expected_request_count=2)

    # 4. Bruno status fail
    failed_bruno = [{"results": [{"status": "fail", "error": "Connection refused", "response": {"status": 200}}]}]
    with pytest.raises(BrunoPopulatorError, match="Connection refused"):
        step.verify_bruno_collection_results(failed_bruno)

    # 5. HTTP status code failure
    failed_http = [
        {"results": [{"status": "pass", "response": {"status": 500, "statusText": "Internal Server Error"}}]}
    ]
    with pytest.raises(BrunoPopulatorError, match="status 500"):
        step.verify_bruno_collection_results(failed_http)

    # 6. RAGFlow API code != 0
    failed_api = [
        {
            "results": [
                {
                    "status": "pass",
                    "response": {
                        "status": 200,
                        "data": {"code": 102, "message": "Authentication failed", "data": None},
                    },
                }
            ]
        }
    ]
    with pytest.raises(BrunoPopulatorError, match="code=102, message='Authentication failed'"):
        step.verify_bruno_collection_results(failed_api)


def test_pipeline_runner_item_iteration(tmp_path: Path):
    col = tmp_path / "col"
    col.mkdir()
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    context = PipelineContext(data_dir=data_dir)

    class IterativeStep(MockStep):
        def __init__(self, target_dir: Path, items: list | None = None):
            super().__init__("IterativeStep", target_dir)
            self._items = items

        def get_items(self, context: PipelineContext) -> list[Any] | None:
            return self._items

    valid_step = IterativeStep(col, items=["item1", "item2"])
    valid_step._skip_run = True

    # Item-specific output reports inside context.steps_dir
    report1 = context.get_output_json_path(valid_step.name, item_key="item1")
    report2 = context.get_output_json_path(valid_step.name, item_key="item2")
    report1.write_text(json.dumps([]), encoding="utf-8")
    report2.write_text(json.dumps([]), encoding="utf-8")

    runner = PipelineRunner(steps=[valid_step], context=context)
    ctx = runner.run()
    assert valid_step.preprocessed and valid_step.postprocessed
    assert ctx.get_data("IterativeStep_post") is True


def test_create_chats_step_lifecycle(tmp_path: Path):
    from bruno_populator.steps.step_3_create_chats import CreateChatsStep

    col = tmp_path / "col"
    col.mkdir()
    (col / "Create Chat.yml").write_text(
        """info:
  name: Create Chat
http:
  method: POST
  url: http://localhost:9222/api/v1/chats
  body:
    type: json
    data: |-
      {
        "name": "old",
        "dataset_ids": []
      }
""",
        encoding="utf-8",
    )

    step = CreateChatsStep(collection_dir=col)
    ctx = PipelineContext()

    # Verify single-execution preprocess/postprocess raises hard failure
    with pytest.raises(BrunoPopulatorError, match="must be executed with item iteration"):
        step.preprocess(ctx)
    with pytest.raises(BrunoPopulatorError, match="must be executed with item iteration"):
        step.postprocess(ctx, {})

    # Verify hard failure when dataset_id is missing
    with pytest.raises(BrunoPopulatorError, match="Missing required 'dataset_id'"):
        step.get_items(ctx)

    ctx.set_data("dataset_id", "dataset-xyz-789")

    # Verify hard failure when persona prompts missing
    with pytest.raises(BrunoPopulatorError, match="Missing or empty 'generated_persona_prompts'"):
        step.get_items(ctx)

    ctx.set_data("generated_persona_prompts", {"persona_test": "Du bist ein Test Bot."})

    items = step.get_items(ctx)
    assert items == [("persona_test", "Du bist ein Test Bot.")]

    # Test preprocess with item
    step.preprocess(ctx, item=items[0])
    yml_content = (col / "Create Chat.yml").read_text(encoding="utf-8")
    assert "dataset-xyz-789" in yml_content
    assert "Du bist ein Test Bot." in yml_content

    # Test postprocess with item (verify_result + set_context)
    mock_result = [
        {
            "results": [
                {
                    "response": {
                        "data": {
                            "data": {
                                "id": "chat-111",
                                "name": "Persona: test",
                                "dataset_ids": ["ds1"],
                                "prompt_config": {"system": "System {knowledge}"},
                            }
                        }
                    }
                }
            ]
        },
        {
            "results": [
                {
                    "response": {
                        "data": {
                            "data": {
                                "id": "session-222",
                                "chat_id": "chat-111",
                            }
                        }
                    }
                }
            ]
        },
    ]
    step.postprocess(ctx, mock_result, item=items[0])

    chats = ctx.get_data("created_chats")
    assert isinstance(chats, dict)
    assert chats["persona_test"] == {"chat_id": "chat-111", "session_id": "session-222"}
