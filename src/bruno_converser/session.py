"""Session manager for multi-persona conversation history and persona state."""

from pathlib import Path
from typing import Any

from bruno_populator.exceptions import BrunoPopulatorError
from bruno_populator.logger import get_logger
from bruno_populator.pipeline.context import PipelineContext

logger = get_logger("bruno_converser.session")


def clean_persona_name(key: str) -> str:
    """Clean persona key into human-readable persona name (e.g. 'persona_boomer-buerger' -> 'boomer-buerger')."""
    return key.replace("persona_", "").replace("_", "-")


class ConversationSession:
    """Manages active persona selection and continuous multi-persona conversation history."""

    def __init__(self, context: PipelineContext | None = None):
        if context is None:
            context = PipelineContext()
            context.load_existing_state()

        self.context = context
        chats_data = self.context.get_data("created_chats")

        if not isinstance(chats_data, dict) or not chats_data:
            raise BrunoPopulatorError(
                f"No created chats found in context state at '{self.context.state_file_path}'. "
                f"Please run the Bruno Populator pipeline first."
            )

        self.created_chats: dict[str, dict[str, str]] = chats_data
        self.persona_keys: list[str] = sorted(list(self.created_chats.keys()))
        self.active_persona_key: str = self.persona_keys[0]
        self.history: list[dict[str, Any]] = []

        logger.info(
            f"Initialized ConversationSession with {len(self.persona_keys)} personas. Active: '{self.active_persona_key}'."
        )

    @property
    def history_dir(self) -> Path:
        """Return Path to history directory in active environment data path, creating it if needed."""

        dir_path = (self.context.data_dir / "history").resolve()
        dir_path.mkdir(parents=True, exist_ok=True)
        return dir_path

    def get_available_personas(self) -> list[str]:
        """Return list of available persona keys."""
        return self.persona_keys

    def get_persona_index_map(self) -> dict[int, str]:
        """Return 1-based index mapping of persona keys."""
        return {idx: key for idx, key in enumerate(self.persona_keys, start=1)}

    def get_persona_by_index(self, index: int) -> str | None:
        """Get persona key by 1-based index integer."""
        if 1 <= index <= len(self.persona_keys):
            return self.persona_keys[index - 1]
        return None

    def set_active_persona(self, persona_identifier: str | int) -> str:
        """Switch active persona by 1-based index, exact key, or clean persona name."""
        clean_target = str(persona_identifier).strip().lower()

        # Try 1-based numeric index match
        if clean_target.isdigit():
            idx = int(clean_target)
            key = self.get_persona_by_index(idx)
            if key:
                self.active_persona_key = key
                logger.info(f"Switched active persona to [{idx}] '{self.active_persona_key}'.")
                return self.active_persona_key
            raise BrunoPopulatorError(f"Invalid persona index [{idx}]. Valid range: 1 to {len(self.persona_keys)}.")

        # Try exact key match
        for key in self.persona_keys:
            if key.lower() == clean_target:
                self.active_persona_key = key
                logger.info(f"Switched active persona to '{self.active_persona_key}'.")
                return self.active_persona_key

        # Try clean persona name match
        for key in self.persona_keys:
            if clean_persona_name(key).lower() == clean_target:
                self.active_persona_key = key
                logger.info(f"Switched active persona to '{self.active_persona_key}'.")
                return self.active_persona_key

        raise BrunoPopulatorError(
            f"Unknown persona '{persona_identifier}'. Available personas: {', '.join(self.persona_keys)}"
        )

    def parse_prefixed_input(self, user_input: str) -> tuple[str | None, str]:
        """
        Parse input string for fast persona index prefixing (e.g. '2 Hallo' -> ('2', 'Hallo')).

        Returns (target_persona_index_or_name, remaining_message_text).
        """
        stripped = user_input.strip()
        if not stripped:
            return None, ""

        parts = stripped.split(maxsplit=1)
        first_token = parts[0]

        if first_token.isdigit():
            remaining = parts[1].strip() if len(parts) > 1 else ""
            return first_token, remaining

        return None, stripped

    def get_active_chat_credentials(self) -> tuple[str, str]:
        """Return (chat_id, session_id) for the active persona."""
        creds = self.created_chats.get(self.active_persona_key)
        if not creds or "chat_id" not in creds or "session_id" not in creds:
            raise BrunoPopulatorError(f"Missing chat credentials for active persona '{self.active_persona_key}'.")
        return creds["chat_id"], creds["session_id"]

    def add_user_message(self, content: str) -> None:
        """Append user message to conversation history."""
        self.history.append({"role": "user", "content": content.strip()})

    def add_persona_response(self, persona_key: str, content: str) -> None:
        """Append persona response to conversation history."""
        self.history.append({"role": "assistant", "persona": persona_key, "content": content.strip()})

    def build_payload_messages(self) -> list[dict[str, Any]]:
        """
        Build formatted messages list for RAGFlow API Converse request payload.

        Applies persona prefixing to assistant responses from other personas so target persona
        understands preceding context without losing character identity.
        """
        formatted_messages: list[dict[str, Any]] = []

        for msg in self.history:
            role = msg.get("role", "user")
            content = msg.get("content", "")

            if role == "user":
                formatted_messages.append({"role": "user", "content": content, "files": []})
            elif role == "assistant":
                origin_persona = msg.get("persona", "")
                if origin_persona and origin_persona != self.active_persona_key:
                    name_tag = clean_persona_name(origin_persona)
                    prefixed_content = f"[Persona: {name_tag}] {content}"
                    formatted_messages.append({"role": "assistant", "content": prefixed_content})
                else:
                    formatted_messages.append({"role": "assistant", "content": content})

        return formatted_messages

    def clear_history(self) -> None:
        """Reset local conversation history."""
        self.history.clear()
        logger.info("Cleared conversation history.")
