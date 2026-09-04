"""Unit tests for conversation report generator and slash command integration."""

import json
from pathlib import Path

import pytest

from bruno_converser.cli import handle_slash_command
from bruno_converser.report_generator import (
    extract_page_numbers,
    format_page_numbers_str,
    generate_conversation_report,
)
from bruno_converser.session import ConversationSession
from bruno_populator.exceptions import BrunoPopulatorError
from bruno_populator.pipeline.context import PipelineContext


def test_extract_page_numbers():
    chunk1 = {"positions": [[7, 0, 595, 0, 794]]}
    assert extract_page_numbers(chunk1) == [7]

    chunk2 = {"positions": [[7, 0, 595, 0, 794], [8, 0, 595, 0, 794], [7, 10, 20, 30, 40]]}
    assert extract_page_numbers(chunk2) == [7, 8]

    chunk3 = {"positions": []}
    assert extract_page_numbers(chunk3) == []

    chunk4 = {}
    assert extract_page_numbers(chunk4) == []


def test_format_page_numbers_str():
    assert format_page_numbers_str([]) == ""
    assert format_page_numbers_str([7]) == "Page 7"
    assert format_page_numbers_str([7, 8]) == "Pages 7, 8"


def test_generate_report_empty_history_raises(tmp_path: Path):
    ctx = PipelineContext(data_dir=tmp_path)
    ctx.set_data("created_chats", {"persona_test": {"chat_id": "c1", "session_id": "s1"}})

    session = ConversationSession(context=ctx)
    with pytest.raises(BrunoPopulatorError, match="conversation transcript is empty"):
        generate_conversation_report(session)


def test_generate_report_successful_creation(tmp_path: Path):
    ctx = PipelineContext(data_dir=tmp_path)
    ctx.set_data("created_chats", {"persona_pfleger": {"chat_id": "c1", "session_id": "s1"}})

    session = ConversationSession(context=ctx)
    session.add_user_message("was ist dir wichtig als Pflegekraft?")
    session.add_persona_response(
        "persona_pfleger",
        "Mir ist vor allem wichtig, dass die Stimmung im Team stimmt [ID:0].",
    )

    # Save turn history JSON
    turn_file = session.history_dir / "persona_pfleger_message_01.json"
    turn_data = {
        "response": {
            "data": {
                "data": {
                    "reference": {
                        "chunks": [
                            {
                                "content": "The team is simply a second family.",
                                "document_name": "qualitative_interview_study.pdf",
                                "positions": [[7, 0, 595, 0, 794], [8, 0, 595, 0, 794]],
                                "vector_similarity": 0.739,
                            }
                        ]
                    }
                }
            }
        }
    }
    turn_file.write_text(json.dumps(turn_data), encoding="utf-8")

    out_file = generate_conversation_report(session, filename="test_report.md")

    assert out_file.exists()
    assert out_file.parent == tmp_path.resolve()

    content = out_file.read_text(encoding="utf-8")
    assert "# Conversation Transcript & RAG Reference Report" in content
    assert "### Turn 1: User" in content
    assert "### Turn 2: Persona: pfleger" in content
    assert "qualitative_interview_study.pdf" in content
    assert "(Pages 7, 8)" in content
    assert "The team is simply a second family." in content
    assert "Similarity: 0.7390" in content


def test_handle_slash_command_report(tmp_path: Path):
    ctx = PipelineContext(data_dir=tmp_path)
    ctx.set_data("created_chats", {"persona_pfleger": {"chat_id": "c1", "session_id": "s1"}})

    session = ConversationSession(context=ctx)
    session.add_user_message("Hallo")
    session.add_persona_response("persona_pfleger", "Hallo!")

    handled = handle_slash_command("/report my_report.md", session)
    assert handled is True

    expected_path = tmp_path.resolve() / "my_report.md"
    assert expected_path.exists()


def test_inspect_real_report_output_json():
    json_path = Path("bruno/RAGFlowApiClient/collections/RAGFlow Report/output.json")
    if not json_path.exists():
        pytest.skip(f"File '{json_path}' does not exist.")

    with open(json_path, encoding="utf-8") as f:
        raw_report = json.load(f)

    data = raw_report[0]["results"][0]["response"]["data"]["data"]
    messages = data.get("messages", [])
    reference = data.get("reference", [])

    print(f"\n--- Inspection of '{json_path}' ---")
    print(f"Total messages: {len(messages)}")
    for m_idx, msg in enumerate(messages):
        role = msg.get("role")
        content_snippet = msg.get("content", "")[:60].replace("\n", " ")
        msg_id = msg.get("id", "N/A")
        print(f"  msg[{m_idx}] ({role}, id={msg_id}): {content_snippet}")

    print(f"\nTotal reference entries: {len(reference)}")
    for r_idx, ref in enumerate(reference):
        if isinstance(ref, dict):
            chunks = ref.get("chunks", [])
            print(f"  reference[{r_idx}] chunks count: {len(chunks)}")
            for c_idx, chunk in enumerate(chunks):
                doc_name = chunk.get("document_name")
                c_id = chunk.get("id")
                print(f"    chunk[{c_idx}] id={c_id}, doc={doc_name}")
        else:
            print(f"  reference[{r_idx}]: {type(ref)} -> {ref}")
