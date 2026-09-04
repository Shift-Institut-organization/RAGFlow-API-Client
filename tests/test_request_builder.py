"""Unit tests for BrunoRequestBuilder."""

from pathlib import Path

import yaml

from bruno_populator.request_builder import BrunoRequestBuilder


def test_bruno_request_builder_json_payload(tmp_path: Path):
    builder = (
        BrunoRequestBuilder(
            name="Test Create Chat",
            method="POST",
            url="/api/v1/chats",
            seq=1,
            base_url="http://localhost:9222",
        )
        .set_json_body({"name": "Chat Session", "llm_id": "qwen3.6-27b"})
        .add_header("X-Custom-Header", "Value123")
    )

    out_yaml = tmp_path / "test_request.yml"
    saved_path = builder.save(out_yaml)
    assert saved_path.exists()

    with open(saved_path, encoding="utf-8") as f:
        data = yaml.safe_load(f)

    assert data["info"]["name"] == "Test Create Chat"
    assert data["info"]["type"] == "http"
    assert data["info"]["seq"] == 1
    assert data["http"]["method"] == "POST"
    assert data["http"]["url"] == "http://localhost:9222/api/v1/chats"
    assert data["http"]["body"]["type"] == "json"
    assert "Chat Session" in data["http"]["body"]["data"]


def test_bruno_request_builder_multipart(tmp_path: Path):
    file1 = tmp_path / "doc.txt"
    file1.write_text("content")

    builder = BrunoRequestBuilder(
        name="Upload Doc",
        method="POST",
        url="http://localhost:9222/api/v1/datasets/123/documents",
    ).set_multipart_files([file1])

    out_yaml = tmp_path / "upload.yml"
    saved_path = builder.save(out_yaml)

    with open(saved_path, encoding="utf-8") as f:
        data = yaml.safe_load(f)

    assert data["http"]["body"]["type"] == "multipart-form"
    assert data["http"]["body"]["data"][0]["name"] == "file"
    assert str(file1.resolve()) in data["http"]["body"]["data"][0]["value"]


def test_bruno_request_builder_scripts(tmp_path: Path):
    builder = (
        BrunoRequestBuilder(
            name="Test Script Request",
            method="POST",
            url="/api/v1/chats",
        )
        .set_script("after-response", "bru.setVar('reqId', res.body.id);")
        .set_script("before-request", "console.log('starting');")
    )

    out_yaml = tmp_path / "script_request.yml"
    saved_path = builder.save(out_yaml)

    with open(saved_path, encoding="utf-8") as f:
        data = yaml.safe_load(f)

    assert "runtime" in data
    scripts = data["runtime"]["scripts"]
    assert len(scripts) == 2
    assert scripts[0]["type"] == "after-response"
    assert "bru.setVar" in scripts[0]["code"]
    assert scripts[1]["type"] == "before-request"
    assert "console.log" in scripts[1]["code"]
