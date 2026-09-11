"""Single point of truth for project paths."""

from pathlib import Path

# Core directory hierarchy
SRC_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SRC_DIR.parent

# Main workspace subfolders
BRUNO_DIR = PROJECT_ROOT / "bruno" / "RAGFlowApiClient" / "collections"
PROMPTS_DIR = SRC_DIR / "prompts"
GENERATED_PROMPTS_DIR = PROMPTS_DIR / "generated"
STEPS_DIR = SRC_DIR / "bruno_populator" / "steps"

# Common output filenames & dataset asset structure names
OUTPUT_JSON_FILENAME = "output.json"
CONTEXT_STATE_FILENAME = "context_state.json"
REQUIREMENTS_FILENAME = "requirements.md"
SUMMARY_JSON_FILENAME = "summary.json"
USER_FEATURES_FILENAME = "user_features.json"
SOURCES_DIR_NAME = "sources"
STEPS_DATA_DIR_NAME = "steps"