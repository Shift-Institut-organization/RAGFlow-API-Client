"""Unit tests for top-level path configuration in src/paths.py."""

from paths import (
    BRUNO_DIR,
    CONTEXT_STATE_FILENAME,
    OUTPUT_JSON_FILENAME,
    PROJECT_ROOT,
    PROMPTS_DIR,
    REQUIREMENTS_FILENAME,
    SOURCES_DIR_NAME,
    SRC_DIR,
    STEPS_DATA_DIR_NAME,
    STEPS_DIR,
    SUMMARY_JSON_FILENAME,
    USER_FEATURES_FILENAME,
)


def test_project_paths_exist():
    assert PROJECT_ROOT.exists()
    assert SRC_DIR.exists()
    assert BRUNO_DIR.exists()
    assert PROMPTS_DIR.exists()
    assert STEPS_DIR.exists()


def test_project_paths_hierarchy():
    assert SRC_DIR.parent == PROJECT_ROOT
    assert BRUNO_DIR == PROJECT_ROOT / "bruno" / "RAGFlowApiClient" / "collections"
    assert PROMPTS_DIR == SRC_DIR / "prompts"
    assert STEPS_DIR == SRC_DIR / "bruno_populator" / "steps"
    assert OUTPUT_JSON_FILENAME == "output.json"
    assert CONTEXT_STATE_FILENAME == "context_state.json"
    assert REQUIREMENTS_FILENAME == "requirements.md"
    assert SUMMARY_JSON_FILENAME == "summary.json"
    assert USER_FEATURES_FILENAME == "user_features.json"
    assert SOURCES_DIR_NAME == "sources"
    assert STEPS_DATA_DIR_NAME == "steps"
