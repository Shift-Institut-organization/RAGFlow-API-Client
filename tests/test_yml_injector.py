"""Unit tests for verifying YML payload variable injection and sync with Bruno YAML request files."""

from pathlib import Path

from bruno_populator.yml_injector import (
    extract_prompt_from_bruno_yml,
    inject_prompt_into_bruno_yml,
    update_chat_yml_request,
    update_multipart_files_in_yml,
    update_yml_payload_key,
)
from paths import BRUNO_DIR, PROMPTS_DIR


def test_prompt_injection_and_extraction(tmp_path: Path):
    sample_yml = tmp_path / "Test Request.yml"
    sample_yml.write_text(
        """info:
  name: Test Request
  type: http
  seq: 1

http:
  method: POST
  url: http://localhost:9222/api/v1/chats
  body:
    type: json
    data: |-
      {
        "name": "Test",
        "prompt_config": {
          "system": "Old Prompt"
        }
      }
""",
        encoding="utf-8",
    )

    new_prompt = "New Injected System Prompt Text"
    inject_prompt_into_bruno_yml(sample_yml, new_prompt)

    extracted = extract_prompt_from_bruno_yml(sample_yml)
    assert extracted == new_prompt


def test_update_multipart_files_in_yml(tmp_path: Path):
    sample_yml = tmp_path / "Upload Request.yml"
    sample_yml.write_text(
        """info:
  name: Upload Request
  type: http
  seq: 1

http:
  method: POST
  url: http://localhost:9222/api/v1/upload
  body:
    type: multipart
    multipart:
      - name: file
        type: file
        value: []
""",
        encoding="utf-8",
    )

    doc1 = tmp_path / "doc1.txt"
    doc1.write_text("content1", encoding="utf-8")
    doc2 = tmp_path / "doc2.txt"
    doc2.write_text("content2", encoding="utf-8")

    update_multipart_files_in_yml(sample_yml, [doc1, doc2])

    content = sample_yml.read_text(encoding="utf-8")
    assert str(doc1.resolve()) in content
    assert str(doc2.resolve()) in content


def test_update_chat_yml_request(tmp_path: Path):
    sample_yml = tmp_path / "Chat Request.yml"
    sample_yml.write_text(
        """info:
  name: Chat Request
  type: http
  seq: 1

http:
  method: POST
  url: http://localhost:9222/api/v1/chats
  body:
    type: json
    data: |-
      {
        "name": "Old Name",
        "dataset_ids": [],
        "prompt_config": {
          "system": "Old System"
        }
      }
""",
        encoding="utf-8",
    )

    update_chat_yml_request(
        sample_yml,
        prompt_text="Updated System",
        dataset_ids=["ds-123"],
        chat_name="Persona: Test",
    )

    content = sample_yml.read_text(encoding="utf-8")
    assert "Updated System" in content
    assert "ds-123" in content
    assert "Persona: Test" in content


def test_update_yml_payload_key(tmp_path: Path):
    sample_yml = tmp_path / "Converse Request.yml"
    sample_yml.write_text(
        """info:
  name: Converse Request
  type: http
  seq: 1

http:
  method: POST
  url: http://localhost:9222/api/v1/chat/completions
  body:
    type: json
    data: |-
      {
        "chat_id": "old_chat",
        "session_id": "old_session",
        "messages": []
      }
""",
        encoding="utf-8",
    )

    update_yml_payload_key(sample_yml, "chat_id", "new_chat_123")
    update_yml_payload_key(sample_yml, "session_id", "new_session_456")

    content = sample_yml.read_text(encoding="utf-8")
    assert "new_chat_123" in content
    assert "new_session_456" in content


def test_reference_prompt_injection_sync(tmp_path: Path):
    prompt_file = PROMPTS_DIR / "create_persona_prompt.md"
    assert prompt_file.exists()

    collection_file = BRUNO_DIR / "RAGFlow create System prompts" / "Create Chat System Prompt.yml"
    assert collection_file.exists()

    # Test prompt injection and extraction fidelity on temporary YML copy
    tmp_yml = tmp_path / "Create Chat System Prompt.yml"
    tmp_yml.write_text(collection_file.read_text(encoding="utf-8"), encoding="utf-8")

    inject_prompt_into_bruno_yml(tmp_yml, prompt_path=prompt_file)
    extracted = extract_prompt_from_bruno_yml(tmp_yml)
    assert extracted == prompt_file.read_text(encoding="utf-8")
