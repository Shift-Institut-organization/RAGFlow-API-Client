---
name: bruno-api-populator
description: Automate API content seeding, document uploads, pipeline steps, and request collections using Bruno CLI and PyYAML/Pydantic request generators. Always use this skill for ANY work, changes, refactoring, or additions within this repository (`RAGFlowAPIClient`).
---

# Bruno API Populator Skill

Use this skill to automate seeding API-based applications with initial content, document collections, or test datasets using Bruno API collections (`bru run`) and Python pipelines.

## Single Source of Truth for Paths (`src/paths.py`)

All top-level paths are centralized in [paths.py](src/paths.py):

```python
from paths import BRUNO_DIR, PROJECT_ROOT, PROMPTS_DIR, SRC_DIR, STEPS_DIR
```

Use `BRUNO_DIR`, `PROMPTS_DIR`, `STEPS_DIR`, and `PROJECT_ROOT` across all step implementations instead of hardcoding or computing relative parent paths.

---

## Architecture: Modular 3-Stage Pipeline with Folder-per-Step Layout

All Bruno collections follow a standardized 3-stage lifecycle executed sequentially via `PipelineRunner`:

1. **Preprocessing (`preprocess`)**: Dynamically update or generate Bruno request `.yml` files in the collection folder using `BrunoRequestBuilder`.
2. **Execution (`run`)**: Execute `bru run` on the collection folder, saving an `output.json` report.
3. **Postprocessing (`postprocess`)**: Analyze the `output.json` report, extracting created IDs/responses into `PipelineContext` for downstream steps.

### Step Directory Organization

Each collection step is placed in its own self-contained directory under `src/bruno_populator/steps/<step_name>/`:

```
RAGFlowAPIClient/
├── src/
│   ├── paths.py                                  # Single source of truth for directory paths
│   ├── prompts/
│   │   └── create_persona_prompt.md             # Readable Markdown system prompt file
│   └── bruno_populator/
│       └── steps/
│           └── create_system_prompts/            # Step directory
│               ├── __init__.py
│               ├── step.py                       # Step handler subclassing BaseCollectionStep
│               └── payload.json                  # Clean isolated JSON request body template
```

---

## Core Engineering Principles

1. **Centralized Paths & Hard Fail Validation**:
   - Always import workspace directory paths from `paths` (`BRUNO_DIR`, `PROMPTS_DIR`, `STEPS_DIR`).
   - Validate path existence with `.exists()` during step `__init__`, raising `FileNotFoundError` immediately if a path is invalid or missing.

2. **Dependency Minimization Rule**:
   - Use external libraries ONLY when they are common, well-established libraries (`pydantic`, `pyyaml`, `pytest`, `ruff`). Prefer standard library (`pathlib`, `subprocess`, `json`, `logging`, `abc`).

3. **Structured Logging (INFO & DEBUG with F-Strings)**:
   - Do NOT use bare `print()` statements in module code or scripts.
   - Always instantiate and use the project logger via `bruno_populator.logger.get_logger("module_name")`.
   - **Always use Python f-strings** when parameters are included in logger calls (e.g. `logger.info(f"Generated request at: {yaml_path}")`).

4. **Markdown Prompts & Dict Path Injection**:
   - Markdown system prompts are stored separately in `src/prompts/*.md` for optimal readability and editing.
   - Request body templates are stored in isolated `payload.json` files within the step directory.
   - Use static helper method `BaseCollectionStep.load_payload_with_prompt(json_path, prompt_path, key_path)` to load and inject system prompts.

5. **Linter & Formatter Verification (Zero Lint Errors)**:
   - Code written or modified must achieve **0 linting errors** when verified with `ruff check .`.
   - Code formatting must be clean and formatted using `ruff format .`.

6. **Slim Functions & Low Nesting**:
   - Keep functions focused on a single responsibility (ideally under 20-30 lines).
   - Use **guard clauses** and early returns to avoid deep nesting of `if/else` statements.

7. **Strict Hard Failures (Zero Silent Failures)**:
   - **NEVER allow silent failures** or swallow missing data with log warnings and silent early returns when expected resources, key paths, prompts, IDs (`datasetId`, `chatId`), or response payloads are missing.
   - If a prompt, key path, expected JSON field, dataset ID, or response output cannot be found, the step MUST **hard fail immediately** by raising a domain exception (e.g. `BrunoPopulatorError`, `FileNotFoundError`, `KeyError`, `ValueError`).
   - Hard failing halts pipeline execution immediately and prints the full Python stacktrace so developers can locate and fix the issue straight away. (Note: Optional document parsing status checks may log individual document parse errors without raising an exception if downstream steps can still proceed).

8. **No Inline Terminal Scripts (`python -c`)**:
   - **never execute inline Python commands via terminal** (e.g. `python -c "..."` or `python.exe -c "..."`).
   - Instead, write the code as a clean Python   script inside the `dummy_scripts/` directory (which is gitignored) and run it from there.

---

## Adding a New Bruno Collection Step

To add a new Bruno collection folder to the pipeline:

### Step 1: Create the Step Directory
Create `src/bruno_populator/steps/<my_step_name>/` containing:
- `payload.json`: JSON payload template with target keys.
- `step.py`: Class subclassing `BaseCollectionStep`.

```python
from pathlib import Path
from typing import Any
from bruno_populator.logger import get_logger
from bruno_populator.pipeline.base_step import BaseCollectionStep
from bruno_populator.pipeline.context import PipelineContext
from bruno_populator.request_builder import BrunoRequestBuilder
from paths import BRUNO_DIR, PROMPTS_DIR

logger = get_logger("bruno_populator.steps.my_collection")
STEP_DIR = Path(__file__).resolve().parent

class MyCollectionStep(BaseCollectionStep):

    def __init__(
        self,
        collection_dir: Path | str | None = None,
        prompt_path: Path | str | None = None,
    ):
        col_path = (
            Path(collection_dir).resolve()
            if collection_dir
            else (BRUNO_DIR / "My Collection Folder").resolve()
        )
        if not col_path.exists():
            raise FileNotFoundError(f"Bruno collection directory not found: {col_path}")
        self._collection_dir = col_path

        p_path = (
            Path(prompt_path).resolve()
            if prompt_path
            else (PROMPTS_DIR / "my_prompt.md").resolve()
        )
        if not p_path.exists():
            raise FileNotFoundError(f"Prompt file not found: {p_path}")
        self._prompt_path = p_path

    @property
    def name(self) -> str:
        return "My Collection Step"

    @property
    def collection_dir(self) -> Path:
        return self._collection_dir

    def preprocess(self, context: PipelineContext) -> None:
        """Construct Bruno request YML file from payload.json and src/prompts/."""
        json_path = (STEP_DIR / "payload.json").resolve()

        # Load payload.json and inject markdown prompt at dot path
        payload = self.load_payload_with_prompt(
            json_path=json_path,
            prompt_path=self._prompt_path,
            key_path="prompt_config.system",
        )

        builder = (
            BrunoRequestBuilder(
                name="Create Resource",
                method="POST",
                url="/api/v1/resources",
                seq=1,
                base_url=context.base_url,
            )
            .set_json_body(payload)
        )

        # Auto-attach available before/after JS scripts from step directory
        self.auto_attach_step_scripts(builder, STEP_DIR)

        yml_file = self.collection_dir / "Create Resource.yml"
        builder.save(yml_file)

    def postprocess(self, context: PipelineContext, result_data: dict[str, Any] | None) -> None:
        """Analyze Bruno output JSON and save outputs to context."""
        if not result_data:
            return

        for res in result_data.get("results", []):
            body = res.get("response", {}).get("body", {})
            if isinstance(body, dict) and "id" in body:
                resource_id = body["id"]
                context.set_data("created_resource_id", resource_id)
                logger.info(f"Extracted Resource ID: {resource_id}")
```

### Step 2: Register the Step Class in the Test Suite & Pipeline
1. In `tests/test_compare_bruno_yml.py`: Add `MyCollectionStep` to `REGISTERED_STEP_CLASSES` so generated `.yml` files are automatically compared line-by-line against reference collection files in `BRUNO_DIR`.
2. In `start_bruno.py`: Add `runner.add_step(MyCollectionStep())` to execute in pipeline order.

```python
from bruno_populator.pipeline.context import PipelineContext
from bruno_populator.pipeline.orchestrator import PipelineRunner
from bruno_populator.steps import CreateSystemPromptsStep, MyCollectionStep

context = PipelineContext(base_url="http://localhost:9222")
runner = PipelineRunner(context=context)

# Steps execute strictly in registration order
runner.add_step(CreateSystemPromptsStep())
runner.add_step(MyCollectionStep())

final_context = runner.run()
```

---

## Quality & Verification Checklist
Before completing work, always execute all verification steps sequentially in one go:

```powershell
# Option A: Run automated batch script
.\run_checks.bat

# Option B: Run sequential one-liner in PowerShell
.\.venv\Scripts\pytest ; .\.venv\Scripts\ruff check . ; .\.venv\Scripts\ruff format --check .
```

