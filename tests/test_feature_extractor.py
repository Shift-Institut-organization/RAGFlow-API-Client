"""Unit tests for user feature extraction and separation."""

import json
from pathlib import Path

import pytest

from user_features.extractor import (
    _clean_json_trailing_commas,
    extract_user_features,
    load_json_data,
    process_project_summary,
)
from user_features.models import ExtractedUserFeatures


@pytest.fixture
def sample_summary_dict() -> dict:
    return {
        "code": 0,
        "data": {
            "summary": {
                "[INFERRED] Pendler nutzen Pendlerrelationen (Reason:": {
                    "type": "string",
                    "values": [["..", 1]],
                },
                "erfassen.": {
                    "type": "string",
                    "values": [
                        [
                            ', "[INFERRED] Nutzer nutzen Ridesharing-Apps (Reason: "...P+R-Standorte sollten... als Matching Points in Ridesharing-Apps aufgenommen werden.")]"',
                            1,
                        ]
                    ],
                },
                "user": {
                    "type": "list",
                    "values": [
                        ["[EXPLICIT] Pendler", 2],
                        ["[EXPLICIT] age", 2],
                        ["[EXPLICIT] gender", 2],
                        ["[EXPLICIT] Gender", 2],
                        ["[EXPLICIT] the number of kilometers driven during a year", 2],
                        ["[EXPLICIT] commuters", 2],
                        ["[EXPLICIT] Pendlerinnen und Pendler", 1],
                    ],
                },
            }
        },
    }


def test_extract_user_features_from_dict(sample_summary_dict: dict, caplog: pytest.LogCaptureFixture):
    with caplog.at_level("WARNING"):
        result = extract_user_features(sample_summary_dict)

    assert isinstance(result, ExtractedUserFeatures)

    # Check explicit list
    assert result.explicit == [
        "Pendler",
        "age",
        "gender",
        "Gender",
        "the number of kilometers driven during a year",
        "commuters",
        "Pendlerinnen und Pendler",
    ]

    # Check inferred list
    assert len(result.inferred) == 2
    assert "Pendler nutzen Pendlerrelationen (Reason:" in result.inferred[0]
    assert "Nutzer nutzen Ridesharing-Apps" in result.inferred[1]

    # Verify warning logged for 'erfassen.'
    assert any("erfassen." in record.message for record in caplog.records)


def test_clean_json_trailing_commas():
    raw = '{"list": [1, 2, ], "obj": {"a": 1, }}'
    cleaned = _clean_json_trailing_commas(raw)
    parsed = json.loads(cleaned)
    assert parsed == {"list": [1, 2], "obj": {"a": 1}}


def test_load_json_data_with_trailing_comma(tmp_path: Path):
    json_file = tmp_path / "test_trailing.json"
    json_file.write_text('{"data": {"summary": {"user": {"values": [["[EXPLICIT] test", 1], ]}}}}', encoding="utf-8")

    data = load_json_data(json_file)
    result = extract_user_features(data)
    assert result.explicit == ["test"]


def test_extract_user_features_from_file(tmp_path: Path, sample_summary_dict: dict):
    json_file = tmp_path / "summary.json"
    json_file.write_text(json.dumps(sample_summary_dict), encoding="utf-8")

    result = extract_user_features(json_file)
    assert len(result.explicit) == 7
    assert len(result.inferred) == 2


def test_process_project_summary_end_to_end(tmp_path: Path, sample_summary_dict: dict):
    json_file = tmp_path / "summary.json"
    json_file.write_text(json.dumps(sample_summary_dict), encoding="utf-8")

    output_path = process_project_summary(data_dir=tmp_path)
    assert output_path.exists()
    assert output_path.name == "user_features.json"

    saved_data = json.loads(output_path.read_text(encoding="utf-8"))
    assert "explicit" in saved_data
    assert "inferred" in saved_data
    assert len(saved_data["explicit"]) == 7
    assert len(saved_data["inferred"]) == 2


def test_process_project_summary_missing_dir():
    with pytest.raises(FileNotFoundError, match="Project data directory not found"):
        process_project_summary(data_dir=Path("non_existent_folder_xyz_123"))


def test_process_project_summary_missing_file(tmp_path: Path):
    with pytest.raises(FileNotFoundError, match="Summary JSON input file not found"):
        process_project_summary(data_dir=tmp_path)
