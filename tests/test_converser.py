"""Unit tests for bruno_converser session management, payload formatting, and runner."""

from pathlib import Path
from unittest.mock import patch

import pytest

from bruno_converser.runner import ConverserRunner
from bruno_converser.session import ConversationSession, clean_persona_name
from bruno_populator.config import AppConfig
from bruno_populator.exceptions import BrunoPopulatorError
from bruno_populator.pipeline.context import PipelineContext


def test_clean_persona_name():
    assert clean_persona_name("persona_boomer-buerger") == "boomer-buerger"
    assert clean_persona_name("persona_pflegekraft") == "pflegekraft"
    assert clean_persona_name("general_bot") == "general-bot"


def test_converse_log_level_default_and_env_override(monkeypatch):
    import logging

    from bruno_populator.logger import LogLevelMode, get_logger, set_log_level_mode

    # Test LogLevelMode.CONVERSE reads CONVERSE_LOG_LEVEL (default WARNING)
    monkeypatch.delenv("CONVERSE_LOG_LEVEL", raising=False)
    set_log_level_mode(LogLevelMode.CONVERSE)
    logger1 = get_logger("bruno_converser.runner")
    assert logger1.level == logging.WARNING

    # Test setting CONVERSE_LOG_LEVEL env var actually takes effect in LogLevelMode.CONVERSE
    monkeypatch.setenv("CONVERSE_LOG_LEVEL", "ERROR")
    set_log_level_mode(LogLevelMode.CONVERSE)
    pop_logger = get_logger("bruno_populator.pipeline.context")
    assert pop_logger.level == logging.ERROR

    # Test LogLevelMode.POPULATOR reads LOG_LEVEL env var
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    set_log_level_mode(LogLevelMode.POPULATOR)
    assert get_logger("bruno_populator.runner").level == logging.DEBUG


def test_session_init_and_persona_switching(tmp_path: Path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "requirements.md").write_text("# Req", encoding="utf-8")
    (data_dir / "sources").mkdir()

    cfg = AppConfig(data_dir=data_dir)
    ctx = PipelineContext(config=cfg)
    ctx.set_data(
        "created_chats",
        {
            "persona_boomer-buerger": {"chat_id": "chat-1", "session_id": "sess-1"},
            "persona_pflegekraft": {"chat_id": "chat-2", "session_id": "sess-2"},
        },
    )

    session = ConversationSession(context=ctx)
    assert session.get_available_personas() == ["persona_boomer-buerger", "persona_pflegekraft"]
    assert session.active_persona_key == "persona_boomer-buerger"

    chat_id, sess_id = session.get_active_chat_credentials()
    assert chat_id == "chat-1"
    assert sess_id == "sess-1"

    # Switch by clean persona name
    switched = session.set_active_persona("pflegekraft")
    assert switched == "persona_pflegekraft"
    assert session.active_persona_key == "persona_pflegekraft"

    # Switch by 1-based index
    switched_idx = session.set_active_persona(1)
    assert switched_idx == "persona_boomer-buerger"
    assert session.active_persona_key == "persona_boomer-buerger"

    switched_idx_str = session.set_active_persona("2")
    assert switched_idx_str == "persona_pflegekraft"
    assert session.active_persona_key == "persona_pflegekraft"

    chat_id2, sess_id2 = session.get_active_chat_credentials()
    assert chat_id2 == "chat-2"
    assert sess_id2 == "sess-2"

    # Invalid persona switch raises BrunoPopulatorError
    with pytest.raises(BrunoPopulatorError, match="Unknown persona 'nonexistent'"):
        session.set_active_persona("nonexistent")

    with pytest.raises(BrunoPopulatorError, match="Invalid persona index \\[99\\]"):
        session.set_active_persona(99)


def test_session_parse_prefixed_input(tmp_path: Path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()

    cfg = AppConfig(data_dir=data_dir)
    ctx = PipelineContext(config=cfg)
    ctx.set_data(
        "created_chats",
        {
            "persona_a": {"chat_id": "c1", "session_id": "s1"},
            "persona_b": {"chat_id": "c2", "session_id": "s2"},
        },
    )
    session = ConversationSession(context=ctx)

    idx_token, text = session.parse_prefixed_input("2 Hallo wie geht es?")
    assert idx_token == "2"
    assert text == "Hallo wie geht es?"

    idx_token2, text2 = session.parse_prefixed_input("2")
    assert idx_token2 == "2"
    assert text2 == ""

    idx_token3, text3 = session.parse_prefixed_input("Hallo zusammen")
    assert idx_token3 is None
    assert text3 == "Hallo zusammen"


def test_handle_slash_command_typo_guard(tmp_path: Path):
    from bruno_converser.cli import handle_slash_command

    data_dir = tmp_path / "data"
    data_dir.mkdir()

    cfg = AppConfig(data_dir=data_dir)
    ctx = PipelineContext(config=cfg)
    ctx.set_data(
        "created_chats",
        {
            "persona_a": {"chat_id": "c1", "session_id": "s1"},
        },
    )
    session = ConversationSession(context=ctx)

    # Valid slash command
    assert handle_slash_command("/personas", session) is True
    assert handle_slash_command("/help", session) is True

    # Typo slash command must return True (handled/blocked) without sending to AI!
    assert handle_slash_command("/siwtch persona_a", session) is True
    assert handle_slash_command("/invalidcommand", session) is True

    # Normal non-slash input returns False (proceed to AI execution)
    assert handle_slash_command("Hallo wie gehts?", session) is False


def test_session_history_and_prefixing(tmp_path: Path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()

    cfg = AppConfig(data_dir=data_dir)
    ctx = PipelineContext(config=cfg)
    ctx.set_data(
        "created_chats",
        {
            "persona_boomer-buerger": {"chat_id": "c1", "session_id": "s1"},
            "persona_pflegekraft": {"chat_id": "c2", "session_id": "s2"},
        },
    )

    session = ConversationSession(context=ctx)

    # 1. User message to Boomer-Bürger
    session.add_user_message("Hallo Günther!")
    session.add_persona_response("persona_boomer-buerger", "Hallo! Ich bin Günther.")

    # Build payload while active persona is Boomer-Bürger
    msgs1 = session.build_payload_messages()
    assert len(msgs1) == 2
    assert msgs1[0] == {"role": "user", "content": "Hallo Günther!", "files": []}
    assert msgs1[1] == {"role": "assistant", "content": "Hallo! Ich bin Günther."}

    # 2. Switch to Pflegekraft and add another message
    session.set_active_persona("pflegekraft")
    session.add_user_message("Wie siehst du das, Pflegekraft?")

    # Build payload for Pflegekraft -> previous Boomer-Bürger response gets prefixed
    msgs2 = session.build_payload_messages()
    assert len(msgs2) == 3
    assert msgs2[0] == {"role": "user", "content": "Hallo Günther!", "files": []}
    assert msgs2[1] == {"role": "assistant", "content": "[Persona: boomer-buerger] Hallo! Ich bin Günther."}
    assert msgs2[2] == {"role": "user", "content": "Wie siehst du das, Pflegekraft?", "files": []}

    # Clear history
    session.clear_history()
    assert len(session.history) == 0


def test_session_init_raises_if_no_chats(tmp_path: Path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()

    cfg = AppConfig(data_dir=data_dir)
    ctx = PipelineContext(config=cfg)

    with pytest.raises(BrunoPopulatorError, match="No created chats found in context state"):
        ConversationSession(context=ctx)


@patch("bruno_converser.runner.run_bruno_collection")
@patch("bruno_converser.runner.update_yml_payload_key")
def test_converser_runner_send_message(mock_update_key, mock_run_bruno, tmp_path: Path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()

    cfg = AppConfig(data_dir=data_dir)
    ctx = PipelineContext(config=cfg)
    ctx.set_data(
        "created_chats",
        {
            "persona_test": {"chat_id": "chat-100", "session_id": "sess-200"},
        },
    )
    session = ConversationSession(context=ctx)

    col_dir = tmp_path / "converse_col"
    col_dir.mkdir()
    (col_dir / "Converse.yml").write_text("info:\n  name: Converse", encoding="utf-8")

    runner = ConverserRunner(collection_dir=col_dir)

    # Mock Bruno collection return report
    mock_run_bruno.return_value = [
        {
            "results": [
                {
                    "request": {"url": "http://localhost/chat"},
                    "response": {
                        "status": 200,
                        "data": {
                            "code": 0,
                            "data": {
                                "answer": "Persona response text from RAGFlow",
                            },
                        },
                    },
                    "status": "pass",
                }
            ]
        }
    ]

    answer = runner.send_message(session, "Hallo Test!")
    assert answer == "Persona response text from RAGFlow"
    assert len(session.history) == 2
    assert session.history[0]["content"] == "Hallo Test!"
    assert session.history[1]["content"] == "Persona response text from RAGFlow"
