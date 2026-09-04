"""Extractor for separating INFERRED and EXPLICIT user features from summary JSON."""

import json
import re
from pathlib import Path
from typing import Any

from bruno_populator.logger import get_logger
from paths import SUMMARY_JSON_FILENAME, USER_FEATURES_FILENAME
from user_features.models import ExtractedUserFeatures

logger = get_logger("user_features.extractor")


def _clean_json_trailing_commas(raw_text: str) -> str:
    """Remove trailing commas before closing brackets or braces in JSON string."""
    return re.sub(r",\s*([\]}])", r"\1", raw_text)


def load_json_data(file_path: Path | str) -> dict[str, Any]:
    """Load JSON from file path, handling encoding and optional trailing commas."""
    path = Path(file_path).resolve()
    if not path.exists():
        raise FileNotFoundError(f"JSON summary file not found: {path}")

    raw_text = path.read_text(encoding="utf-8").strip()
    try:
        return json.loads(raw_text)
    except json.JSONDecodeError:
        cleaned_text = _clean_json_trailing_commas(raw_text)
        return json.loads(cleaned_text)


def _clean_feature_string(val: str, prefix: str) -> str:
    """Clean prefix and surrounding quotes or trailing brackets from feature string."""
    cleaned = val
    if cleaned.startswith(prefix):
        cleaned = cleaned[len(prefix) :].strip()
    return cleaned.strip()


def _extract_embedded_inferred(text: str) -> str | None:
    """Extract embedded [INFERRED] text from a malformed value string."""
    marker = "[INFERRED]"
    if marker not in text:
        return None

    idx = text.find(marker)
    content = text[idx + len(marker) :].strip()
    # Strip leading/trailing quote fragments, brackets, or commas
    content = content.strip("\", ']").strip()
    return content if content else None


def extract_user_features(
    data_or_path: dict[str, Any] | Path | str,
) -> ExtractedUserFeatures:
    """
    Extract and separate INFERRED and EXPLICIT user features into two lists.

    Emits warnings if non-user summary entries do not start with '[INFERRED]'.
    """
    if isinstance(data_or_path, (str, Path)):
        data = load_json_data(data_or_path)
    else:
        data = data_or_path

    # Handle nested summary structure {"data": {"summary": ...}} or {"summary": ...}
    summary: dict[str, Any] = {}
    if isinstance(data, dict):
        if "data" in data and isinstance(data["data"], dict) and "summary" in data["data"]:
            summary = data["data"]["summary"]
        elif "summary" in data and isinstance(data["summary"], dict):
            summary = data["summary"]
        else:
            summary = data

    explicit_features: list[str] = []
    inferred_features: list[str] = []

    for key, val_obj in summary.items():
        if key == "user":
            # Process explicit/inferred user entries inside "user" category
            values = val_obj.get("values", []) if isinstance(val_obj, dict) else val_obj
            if isinstance(values, list):
                for item in values:
                    feature_raw = item[0] if isinstance(item, (list, tuple)) and item else item
                    if not isinstance(feature_raw, str):
                        continue

                    feature_str = feature_raw.strip()
                    if feature_str.startswith("[EXPLICIT]"):
                        explicit_features.append(_clean_feature_string(feature_str, "[EXPLICIT]"))
                    elif feature_str.startswith("[INFERRED]"):
                        inferred_features.append(_clean_feature_string(feature_str, "[INFERRED]"))
                    else:
                        explicit_features.append(feature_str)
        else:
            # Non-user entry/category in summary
            if key.startswith("[INFERRED]"):
                inferred_features.append(_clean_feature_string(key, "[INFERRED]"))
            else:
                logger.warning(f"Summary entry '{key}' does not start with '[INFERRED]' in the beginning.")

                # Check if an embedded [INFERRED] feature exists inside values
                extracted_from_values = False
                values = val_obj.get("values", []) if isinstance(val_obj, dict) else val_obj
                if isinstance(values, list):
                    for item in values:
                        val_raw = item[0] if isinstance(item, (list, tuple)) and item else item
                        if isinstance(val_raw, str):
                            embedded = _extract_embedded_inferred(val_raw)
                            if embedded:
                                inferred_features.append(embedded)
                                extracted_from_values = True

                if not extracted_from_values and key.strip():
                    inferred_features.append(key.strip())

    result = ExtractedUserFeatures(
        explicit=explicit_features,
        inferred=inferred_features,
    )
    logger.info(f"Extracted {len(result.explicit)} explicit features and {len(result.inferred)} inferred features.")
    return result


def process_project_summary(
    data_dir: Path | str,
    input_filename: str = SUMMARY_JSON_FILENAME,
    output_filename: str = USER_FEATURES_FILENAME,
) -> Path:
    """
    Load summary JSON from data_dir/<input_filename>, separate features, and save to data_dir/<output_filename>.

    Returns the path to the written output file.
    """
    dir_path = Path(data_dir).resolve()
    if not dir_path.exists() or not dir_path.is_dir():
        raise FileNotFoundError(f"Project data directory not found: {dir_path}")

    input_path = dir_path / input_filename
    if not input_path.exists():
        raise FileNotFoundError(f"Summary JSON input file not found: {input_path}")

    features = extract_user_features(input_path)

    output_path = dir_path / output_filename
    output_payload = features.model_dump()

    output_json_text = json.dumps(output_payload, indent=2, ensure_ascii=False)
    output_path.write_text(output_json_text, encoding="utf-8")

    logger.info(f"Saved separated user features JSON to: {output_path}")
    return output_path
