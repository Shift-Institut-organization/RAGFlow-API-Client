"""Utility for updating and injecting payload variables directly into Bruno YAML request files."""

import json
import os
import re
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import yaml

from bruno_populator.exceptions import BrunoPopulatorError, YamlGenerationError
from bruno_populator.logger import get_logger
from bruno_populator.request_builder import BrunoYamlDumper, LiteralStr
from paths import BRUNO_DIR

logger = get_logger("bruno_populator.yml_injector")

# Default key path constants for RAGFlow Chat request payloads
DEFAULT_SYSTEM_PROMPT_KEY_PATH = "prompt_config.system"
DEFAULT_CHAT_NAME_KEY_PATH = "name"
DEFAULT_DATASET_IDS_KEY_PATH = "dataset_ids"


def set_nested_value(data: dict[str, Any], key_path: str, value: Any) -> None:
    """Set a nested dictionary value using dot-notation key path."""
    keys = key_path.split(".")
    current = data
    for key in keys[:-1]:
        if key not in current or not isinstance(current[key], dict):
            current[key] = {}
        current = current[key]
    current[keys[-1]] = value


def get_nested_value(data: dict[str, Any], key_path: str) -> Any:
    """Get a nested dictionary value using dot-notation key path."""
    keys = key_path.split(".")
    current = data
    for key in keys:
        if not isinstance(current, dict) or key not in current:
            raise KeyError(f"Key path '{key_path}' not found at segment '{key}'")
        current = current[key]
    return current


def _load_bruno_yml(yml_path: Path | str) -> tuple[Path, dict[str, Any]]:
    """Resolve, check existence of, and parse a Bruno YAML request file."""
    resolved_yml = Path(yml_path).resolve()
    if not resolved_yml.exists():
        raise FileNotFoundError(f"Bruno YAML file does not exist: {resolved_yml}")

    try:
        raw_yml_text = resolved_yml.read_text(encoding="utf-8")
        parsed = yaml.safe_load(raw_yml_text)
    except Exception as exc:
        raise YamlGenerationError(f"Failed to parse YAML file at '{resolved_yml}': {exc}") from exc

    if not isinstance(parsed, dict):
        raise YamlGenerationError(f"YAML content at '{resolved_yml}' must be a dictionary.")

    return resolved_yml, parsed


def _extract_json_payload(yml_dict: dict[str, Any], yml_path: Path) -> dict[str, Any]:
    """Extract and parse the inline JSON body payload from a Bruno YAML dict."""
    try:
        body_data_str = yml_dict["http"]["body"]["data"]
    except KeyError as exc:
        raise YamlGenerationError(f"YAML file at '{yml_path}' missing expected structure 'http.body.data'.") from exc

    try:
        payload = json.loads(body_data_str)
    except json.JSONDecodeError as exc:
        raise YamlGenerationError(f"Failed to parse inline JSON body in YAML at '{yml_path}': {exc}") from exc

    if not isinstance(payload, dict):
        raise YamlGenerationError(f"Inline JSON body in '{yml_path}' must be a JSON object.")

    return payload


def _dump_and_save_bruno_yml(yml_path: Path, yml_dict: dict[str, Any], payload: dict[str, Any]) -> None:
    """Serialize modified JSON payload into YAML http.body.data and dump to file."""
    new_json_str = json.dumps(payload, indent=2, ensure_ascii=False)
    yml_dict["http"]["body"]["data"] = LiteralStr(new_json_str)

    try:
        formatted_yaml = yaml.dump(
            yml_dict,
            Dumper=BrunoYamlDumper,
            default_flow_style=False,
            allow_unicode=True,
            sort_keys=False,
        )
        yml_path.write_text(formatted_yaml, encoding="utf-8")
    except Exception as exc:
        raise YamlGenerationError(f"Failed to dump modified YAML to '{yml_path}': {exc}") from exc


def inject_prompt_into_bruno_yml(
    yml_path: Path | str,
    prompt_text: str | None = None,
    prompt_path: Path | str | None = None,
    key_path: str = DEFAULT_SYSTEM_PROMPT_KEY_PATH,
) -> None:
    """Inject a system prompt string or prompt file into a Bruno YAML request file's inline JSON body."""
    resolved_yml, yml_dict = _load_bruno_yml(yml_path)
    payload = _extract_json_payload(yml_dict, resolved_yml)

    if prompt_text is None and prompt_path is not None:
        p_file = Path(prompt_path).resolve()
        if not p_file.exists():
            raise FileNotFoundError(f"Prompt file not found: {p_file}")
        prompt_text = p_file.read_text(encoding="utf-8")

    if prompt_text is None:
        raise ValueError("Must provide either prompt_text or prompt_path to inject_prompt_into_bruno_yml.")

    set_nested_value(payload, key_path, prompt_text)
    _dump_and_save_bruno_yml(resolved_yml, yml_dict, payload)
    logger.info(f"Successfully injected system prompt into '{resolved_yml}' at key path '{key_path}'.")


def update_chat_yml_request(
    yml_path: Path | str,
    prompt_text: str | None = None,
    dataset_ids: list[str] | str | None = None,
    chat_name: str | None = None,
    system_prompt: str | None = None,
    dataset_id: str | None = None,
) -> None:
    """Update system prompt, dataset_ids list, and chat name in a Bruno YAML request file."""
    resolved_yml, yml_dict = _load_bruno_yml(yml_path)
    payload = _extract_json_payload(yml_dict, resolved_yml)

    effective_prompt = prompt_text if prompt_text is not None else system_prompt
    if effective_prompt is not None:
        set_nested_value(payload, DEFAULT_SYSTEM_PROMPT_KEY_PATH, effective_prompt)

    effective_ds = dataset_ids if dataset_ids is not None else dataset_id
    if effective_ds is not None:
        ds_list = [effective_ds] if isinstance(effective_ds, str) else effective_ds
        set_nested_value(payload, DEFAULT_DATASET_IDS_KEY_PATH, ds_list)

    if chat_name is not None:
        set_nested_value(payload, DEFAULT_CHAT_NAME_KEY_PATH, chat_name)

    _dump_and_save_bruno_yml(resolved_yml, yml_dict, payload)
    logger.info(f"Successfully updated chat YAML request file at '{resolved_yml}'.")


def update_yml_payload_key(
    yml_path: Path | str,
    key_path: str,
    value: Any,
) -> None:
    """Update an arbitrary key path in a Bruno YAML request file's inline JSON body."""
    resolved_yml, yml_dict = _load_bruno_yml(yml_path)
    payload = _extract_json_payload(yml_dict, resolved_yml)

    set_nested_value(payload, key_path, value)
    _dump_and_save_bruno_yml(resolved_yml, yml_dict, payload)
    logger.info(f"Successfully updated YAML request file at '{resolved_yml}' at key path '{key_path}'.")


def update_multipart_files_in_yml(
    yml_path: Path | str,
    file_paths: list[Path | str],
) -> None:
    """Update body.multipart or body.data file array entries in a Bruno YAML request file."""
    resolved_yml, yml_dict = _load_bruno_yml(yml_path)

    body = yml_dict.get("http", {}).get("body", {})
    multipart_list = body.get("data") if isinstance(body, dict) and "data" in body else body.get("multipart")

    if not isinstance(multipart_list, list):
        raise YamlGenerationError(
            f"YAML file at '{resolved_yml}' missing expected multipart array in 'http.body.data' or 'http.body.multipart'."
        )

    resolved_files = [str(Path(f).resolve()) for f in file_paths]
    for file_path_str in resolved_files:
        if not Path(file_path_str).exists():
            raise FileNotFoundError(f"Source file for multipart upload not found: {file_path_str}")

    updated = False
    for entry in multipart_list:
        if isinstance(entry, dict) and entry.get("type") == "file":
            entry["value"] = resolved_files
            updated = True
            break

    if not updated:
        raise YamlGenerationError(f"No file entry (type: 'file') found in multipart array for '{resolved_yml}'.")

    try:
        formatted_yaml = yaml.dump(
            yml_dict,
            Dumper=BrunoYamlDumper,
            default_flow_style=False,
            allow_unicode=True,
            sort_keys=False,
        )
        resolved_yml.write_text(formatted_yaml, encoding="utf-8")
    except Exception as exc:
        raise YamlGenerationError(f"Failed to dump modified multipart YAML to '{resolved_yml}': {exc}") from exc

    logger.info(f"Successfully updated multipart files in '{resolved_yml}' to {resolved_files}.")


def extract_prompt_from_bruno_yml(
    yml_path: Path | str,
    key_path: str = DEFAULT_SYSTEM_PROMPT_KEY_PATH,
) -> str:
    """Extract system prompt string from a Bruno YAML request file's inline JSON body."""
    resolved_yml, yml_dict = _load_bruno_yml(yml_path)
    payload = _extract_json_payload(yml_dict, resolved_yml)

    try:
        val = get_nested_value(payload, key_path)
    except KeyError as exc:
        raise BrunoPopulatorError(
            f"Failed to extract prompt from '{resolved_yml}': key path '{key_path}' not found."
        ) from exc

    if not isinstance(val, str):
        raise BrunoPopulatorError(f"Value at key path '{key_path}' in '{resolved_yml}' is not a string.")

    return val


def _replace_bearer_token(content: str, token: str) -> str:
    """Replace token value in opencollection.yml content while preserving structure."""
    pattern = re.compile(r"(\btoken:\s*)[^\r\n]*", re.MULTILINE)
    if pattern.search(content):
        token_str = json.dumps(token)
        return pattern.sub(rf"\g<1>{token_str}", content, count=1)

    data = yaml.safe_load(content)
    if not isinstance(data, dict):
        raise ValueError("opencollection content is not a valid YAML dictionary.")
    if "request" not in data or not isinstance(data["request"], dict):
        data["request"] = {}
    if "auth" not in data["request"] or not isinstance(data["request"]["auth"], dict):
        data["request"]["auth"] = {"type": "bearer"}
    data["request"]["auth"]["token"] = token
    return yaml.dump(data, sort_keys=False)


def inject_collection_token(collection_dir: Path | str, token: str) -> None:
    """Inject Bearer token into an opencollection.yml file."""
    col_path = Path(collection_dir).resolve()
    opencol_path = col_path / "opencollection.yml" if col_path.is_dir() else col_path
    if not opencol_path.exists():
        raise FileNotFoundError(f"opencollection.yml not found at: {opencol_path}")

    content = opencol_path.read_text(encoding="utf-8")
    updated_content = _replace_bearer_token(content, token)
    opencol_path.write_text(updated_content, encoding="utf-8")
    logger.debug(f"Injected Bearer token into '{opencol_path}'.")


def clear_collection_token(collection_dir: Path | str) -> None:
    """Reset Bearer token in an opencollection.yml file to empty string."""
    inject_collection_token(collection_dir, "")
    logger.debug(f"Cleared Bearer token in '{collection_dir}'.")


@contextmanager
def temporary_collection_token(collection_dir: Path | str, token: str | None = None):
    """
    Context manager temporarily injecting Bearer token into opencollection.yml.

    Restores original file content on exit (both normal and on exception).
    """
    col_path = Path(collection_dir).resolve()
    opencol_path = col_path / "opencollection.yml" if col_path.is_dir() else col_path

    if not opencol_path.exists():
        yield
        return

    effective_token = token if token else (os.environ.get("RAGFLOW_API_KEY") or os.environ.get("API_KEY") or "")
    if not effective_token:
        yield
        return

    original_content = opencol_path.read_text(encoding="utf-8")
    try:
        updated_content = _replace_bearer_token(original_content, effective_token)
        opencol_path.write_text(updated_content, encoding="utf-8")
        logger.debug(f"Temporarily injected token into '{opencol_path}'.")
        yield
    finally:
        opencol_path.write_text(original_content, encoding="utf-8")
        logger.debug(f"Restored original content in '{opencol_path}'.")


def sync_all_collection_tokens(token: str | None = None, bruno_dir: Path | None = None) -> list[Path]:
    """Inject Bearer token into all opencollection.yml files in BRUNO_DIR."""
    root_dir = bruno_dir or BRUNO_DIR
    effective_token = (
        token if token is not None else (os.environ.get("RAGFLOW_API_KEY") or os.environ.get("API_KEY") or "")
    )
    if not effective_token:
        raise ValueError("Cannot sync tokens: no token provided or found in RAGFLOW_API_KEY.")

    updated_files: list[Path] = []
    for opencol_path in root_dir.glob("**/opencollection.yml"):
        inject_collection_token(opencol_path, effective_token)
        updated_files.append(opencol_path)

    logger.info(f"Synced API token across {len(updated_files)} opencollection.yml files.")
    return updated_files


def clear_all_collection_tokens(bruno_dir: Path | None = None) -> list[Path]:
    """Clear Bearer tokens (reset to empty string) in all opencollection.yml files in BRUNO_DIR."""
    root_dir = bruno_dir or BRUNO_DIR
    cleared_files: list[Path] = []
    for opencol_path in root_dir.glob("**/opencollection.yml"):
        clear_collection_token(opencol_path)
        cleared_files.append(opencol_path)

    logger.info(f"Cleared API token in {len(cleared_files)} opencollection.yml files.")
    return cleared_files
