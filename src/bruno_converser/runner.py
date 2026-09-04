"""Runner module executing Bruno CLI RAGFlow converse collection requests."""

import json
from pathlib import Path
from typing import Any

from bruno_converser.session import ConversationSession
from bruno_populator.exceptions import BrunoPopulatorError
from bruno_populator.logger import get_logger
from bruno_populator.pipeline.base_step import BaseCollectionStep
from bruno_populator.pipeline.context import PipelineContext
from bruno_populator.runner import BrunoRunConfig, run_bruno_collection
from bruno_populator.yml_injector import update_yml_payload_key
from paths import BRUNO_DIR, OUTPUT_JSON_FILENAME

logger = get_logger("bruno_converser.runner")


class _ConverseStepHelper(BaseCollectionStep):
    """Internal concrete step helper for verifying converse execution reports."""

    @property
    def name(self) -> str:
        return "RAGFlow Converse"

    @property
    def collection_dir(self) -> Path:
        return Path(".")

    def preprocess(self, context: PipelineContext, item: Any | None = None) -> None:
        pass

    def verify_result(
        self,
        context: PipelineContext,
        result_data: dict[str, Any] | list[Any] | None,
        item: Any | None = None,
    ) -> None:
        pass

    def set_context(
        self,
        context: PipelineContext,
        result_data: dict[str, Any] | list[Any] | None,
        item: Any | None = None,
    ) -> None:
        pass


class ConverserRunner:
    """Injects conversation payload into Converse.yml and executes Bruno CLI request."""

    def __init__(self, collection_dir: Path | str | None = None, env: str | None = None):
        col_path = Path(collection_dir).resolve() if collection_dir else (BRUNO_DIR / "RAGFlow converse").resolve()
        if not col_path.exists():
            raise FileNotFoundError(f"Bruno converse collection directory not found: {col_path}")

        self.collection_dir = col_path
        self.env = env
        self.converse_yml = self.collection_dir / "Converse.yml"

        if not self.converse_yml.exists():
            raise FileNotFoundError(f"Bruno converse request file not found: {self.converse_yml}")
        self._helper = _ConverseStepHelper()

    def send_message(self, session: ConversationSession, user_input: str) -> str:
        """Send a user message to the active persona chat and return assistant answer."""
        if not user_input.strip():
            raise ValueError("User message content cannot be empty.")

        session.add_user_message(user_input)
        chat_id, session_id = session.get_active_chat_credentials()
        messages_payload = session.build_payload_messages()

        logger.info(
            f"Preparing Converse request for persona '{session.active_persona_key}' "
            f"(chat_id='{chat_id}', session_id='{session_id}', messages={len(messages_payload)})..."
        )

        # Inject updated variables into Converse.yml inline JSON payload
        update_yml_payload_key(self.converse_yml, "chat_id", chat_id)
        update_yml_payload_key(self.converse_yml, "session_id", session_id)
        update_yml_payload_key(self.converse_yml, "messages", messages_payload)

        # Execute Bruno collection
        out_json_path = self.collection_dir / OUTPUT_JSON_FILENAME
        run_config = BrunoRunConfig(
            collection_dir=self.collection_dir,
            env=self.env,
            output_json_path=out_json_path,
        )
        result_data = run_bruno_collection(run_config)

        # Verify response and extract answer
        self._helper.verify_bruno_collection_results(result_data, expected_request_count=1)

        answer_text = self._extract_answer_from_result(result_data)
        session.add_persona_response(session.active_persona_key, answer_text)

        # Save turn output JSON directly to history directory with persona prefix
        persona_key = session.active_persona_key
        assistant_turn_count = len(
            [m for m in session.history if m.get("role") == "assistant" and m.get("persona") == persona_key]
        )
        history_file = session.history_dir / f"{persona_key}_message_{assistant_turn_count:02d}.json"
        try:
            with open(history_file, "w", encoding="utf-8") as f:
                json.dump(result_data, f, indent=2, ensure_ascii=False)
            logger.info(f"Saved turn output JSON to '{history_file}'.")
        except Exception as exc:
            logger.warning(f"Failed to save turn history JSON at '{history_file}': {exc}")

        logger.info(f"Received response from persona '{session.active_persona_key}' ({len(answer_text)} chars).")
        return answer_text

    def _extract_answer_from_result(self, result_data: dict[str, Any] | list[Any] | None) -> str:
        """Extract assistant answer text from Bruno JSON output report."""
        # Try key paths: response.data.data.answer -> response.data.data.content -> response.data.data
        for key_path in [
            "response.data.data.answer",
            "response.data.data.content",
            "[0].results[0].response.data.data.answer",
            "[0].results[0].response.data.data.content",
        ]:
            val = self._helper.extract_value_by_key_path(result_data, key_path)
            if isinstance(val, str) and val.strip():
                return val.strip()

        raw_data = self._helper.extract_value_by_key_path(result_data, "[0].results[0].response.data.data")
        if isinstance(raw_data, str) and raw_data.strip():
            return raw_data.strip()

        raise BrunoPopulatorError("Failed to extract assistant answer text from Converse response report.")
