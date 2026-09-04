---
name: bruno-converser
description: Interactive multi-persona chat execution, unified conversation history, persona switching, and Bruno API converse collection integration. Always use this skill for ANY work, changes, refactoring, or additions within the `bruno_converser` module or `start_converse.py`.
---

# Bruno Converser Skill

Use this skill when developing, refactoring, or extending the `bruno_converser` interactive chat module (`src/bruno_converser/`) and `start_converse.py`.

---

## Single Source of Truth for Workspace Paths (`src/paths.py`)

All top-level workspace paths are centralized in [paths.py](src/paths.py):

```python
from paths import BRUNO_DIR, CONTEXT_STATE_FILENAME, PROJECT_ROOT, SRC_DIR
```

Use `BRUNO_DIR`, `CONTEXT_STATE_FILENAME`, `SRC_DIR`, and `PROJECT_ROOT` instead of hardcoding relative paths.

---

## Core Architecture & Responsibilities

The converser module consists of 3 distinct components:

1. **Session Management (`src/bruno_converser/session.py`)**:
   - `ConversationSession` loads `PipelineContext` metadata from `data/<ProjectName>/context_state.json`.
   - Maintains the active persona target (`active_persona_key`).
   - Maintains a single **unified multi-persona conversation history**.
   - Formats previous assistant responses with persona prefixes (e.g. `[Persona: Boomer-Bürger] <Response>`) so switched personas understand prior context while retaining their own system prompt persona identity.

2. **Bruno Request Execution (`src/bruno_converser/runner.py`)**:
   - `ConverserRunner` injects `chat_id`, `session_id`, and formatted `messages` payload into `bruno/RAGFlowApiClient/collections/RAGFlow converse/Converse.yml` using `yml_injector.py`.
   - Executes `run_bruno_collection()` on `RAGFlow converse`.
   - Validates response payload via `verify_bruno_collection_results()` and extracts assistant answer string.

3. **Interactive CLI Interface (`src/bruno_converser/cli.py`)**:
   - `run_cli_chat()` runs an interactive terminal loop with user input and formatted persona prompts (`[User -> Persona: Pflegekraft]>`).
   - Supports commands: `/personas`, `/switch <persona>`, `/history`, `/clear`, `/exit`.

---

## Core Engineering Principles

1. **Structured Logging (INFO & DEBUG with F-Strings)**:
   - Do NOT use bare `print()` statements for module logic or runner errors.
   - Always instantiate and use project loggers via `get_logger("bruno_converser.module_name")`.
   - Use f-strings for all parameters in log messages.

2. **YAML & Payload Injection (`yml_injector.py`)**:
   - Use `update_yml_payload_key(yml_path, key_path, value)` from `bruno_populator.yml_injector` to update `chat_id`, `session_id`, and `messages` in `Converse.yml`.

3. **Strict Hard Failures (Zero Silent Failures)**:
   - If `context_state.json` is missing, `created_chats` is empty, or Bruno API execution fails, raise explicit exceptions (`BrunoPopulatorError`, `FileNotFoundError`).

4. **Zero Lint Errors & Ruff Formatting**:
   - Code written or modified must achieve **0 linting errors** (`ruff check .`).
   - All code must be formatted using `ruff format .`.

5. **Automated Unit Testing Requirement**:
   - All session logic, persona switching, history prefixing, payload generation, and runner mocks MUST be verified with automated unit tests in `tests/test_converser.py`.
   - Run `pytest` to verify 100% test suite pass rate.

6. **No Inline Terminal Scripts (`python -c`)**:
   - **never execute inline Python commands via terminal** (e.g. `python -c "..."` or `python.exe -c "..."`).
   - Instead, write the code as a clean Python script inside the `dummy_scripts/` directory (which is gitignored) and run it from there.