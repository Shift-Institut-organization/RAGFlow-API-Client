"""Unit tests for Bruno CLI runner."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from bruno_populator.config import BrunoRunConfig
from bruno_populator.exceptions import BrunoCliError
from bruno_populator.runner import build_bru_command, run_bruno_collection


def test_build_bru_command():
    config = BrunoRunConfig(
        collection_dir=Path("."),
        env="production",
        exclude_tags=["delete", "draft"],
        output_json_path=Path("out.json"),
    )
    cmd = build_bru_command(config)
    assert cmd == ["bru", "run", "--env", "production", "--exclude-tags=delete,draft", "--output", "out.json"]


def test_build_bru_command_with_single_request_file(tmp_path: Path):
    req_file = tmp_path / "Parse Document.yml"
    req_file.write_text("info:\n  name: Parse", encoding="utf-8")

    config = BrunoRunConfig(
        collection_dir=tmp_path,
        request_file="Parse Document.yml",
        env="local",
        output_json_path=Path("output.json"),
    )
    cmd = build_bru_command(config)
    assert cmd == [
        "bru",
        "run",
        "Parse Document.yml",
        "--env",
        "local",
        "--exclude-tags=delete",
        "--output",
        "output.json",
    ]


@patch("subprocess.run")
def test_run_bruno_collection_success(mock_subproc, tmp_path: Path):
    col_dir = tmp_path / "collection"
    col_dir.mkdir()
    out_json = col_dir / "output.json"
    out_json.write_text(json.dumps({"results": [{"name": "req1", "status": "pass"}]}))

    mock_subproc.return_value = MagicMock(returncode=0, stdout="", stderr="")

    config = BrunoRunConfig(
        collection_dir=col_dir,
        output_json_path=Path("output.json"),
    )

    data = run_bruno_collection(config)
    assert data is not None
    assert len(data["results"]) == 1
    assert data["results"][0]["status"] == "pass"


@patch("subprocess.run")
def test_run_bruno_collection_failure_raises(mock_subproc, tmp_path: Path):
    col_dir = tmp_path / "collection"
    col_dir.mkdir()

    mock_subproc.return_value = MagicMock(returncode=1, stdout="", stderr="Error: Tag not found")

    config = BrunoRunConfig(collection_dir=col_dir)

    with pytest.raises(BrunoCliError) as exc_info:
        run_bruno_collection(config)

    assert exc_info.value.exit_code == 1
    assert "Tag not found" in exc_info.value.stderr


@patch("subprocess.run")
def test_run_bruno_request_success(mock_subproc, tmp_path: Path):
    from bruno_populator.runner import run_bruno_request

    col_dir = tmp_path / "collection"
    col_dir.mkdir()
    req_file = col_dir / "Get Documents.yml"
    req_file.write_text("info:\n  name: Get Documents\n", encoding="utf-8")

    out_json = col_dir / "output.json"
    out_json.write_text(json.dumps({"results": [{"name": "Get Documents", "status": "pass"}]}))

    mock_subproc.return_value = MagicMock(returncode=0, stdout="", stderr="")

    data = run_bruno_request(req_file)
    assert data is not None
    assert len(data["results"]) == 1

    # Verify command line arguments passed to subprocess
    called_cmd = mock_subproc.call_args[0][0]
    assert called_cmd == ["bru", "run", "Get Documents.yml", "--output", str(out_json)]


def test_run_bruno_request_missing_file_raises(tmp_path: Path):
    from bruno_populator.runner import run_bruno_request

    missing_file = tmp_path / "Missing.yml"
    with pytest.raises(FileNotFoundError, match="Bruno request file does not exist"):
        run_bruno_request(missing_file)
