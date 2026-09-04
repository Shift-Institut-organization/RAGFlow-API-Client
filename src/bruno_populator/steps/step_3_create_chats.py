"""Collection step for creating RAGFlow Chat assistants and sessions."""

from pathlib import Path
from typing import Any

from bruno_populator.exceptions import BrunoPopulatorError
from bruno_populator.logger import get_logger
from bruno_populator.pipeline.base_step import BaseCollectionStep
from bruno_populator.pipeline.context import PipelineContext
from bruno_populator.yml_injector import update_chat_yml_request

logger = get_logger("bruno_populator.steps.create_chats")
STEP_DIR = Path(__file__).resolve().parent


class CreateChatsStep(BaseCollectionStep):
    """Collection step for creating RAGFlow Chats and Sessions for each persona prompt."""

    @property
    def name(self) -> str:
        return "RAGFlow Create Chats"

    def get_item_key(self, item: tuple[str, str]) -> str:
        """Return persona key for output JSON report naming."""
        persona_key, _ = item
        return persona_key

    def get_items(self, context: PipelineContext) -> list[tuple[str, str]] | None:
        """
        Retrieve list of (persona_key, prompt_text) tuples from context.

        Hard fails if dataset_id or generated_persona_prompts is missing/empty.
        """
        dataset_id = context.get_data("dataset_id")
        if not dataset_id:
            raise BrunoPopulatorError(f"Missing required 'dataset_id' in PipelineContext for step '{self.name}'.")

        prompts_dict = context.get_data("generated_persona_prompts")
        if not prompts_dict or not isinstance(prompts_dict, dict):
            raise BrunoPopulatorError(
                f"Missing or empty 'generated_persona_prompts' in PipelineContext for step '{self.name}'."
            )

        items = [(key, str(prompt_text)) for key, prompt_text in prompts_dict.items()]
        logger.info(f"Loaded {len(items)} persona prompts for chat creation in step '{self.name}'.")
        return items

    def preprocess(self, context: PipelineContext, item: Any | None = None) -> None:
        """Inject chat_name, dataset_id, and persona system prompt into Create Chat.yml for this item."""
        if item is None:
            raise BrunoPopulatorError(
                f"Step '{self.name}' must be executed with item iteration via get_items(). Normal single-execution preprocess() is not supported."
            )

        persona_key, prompt_text = item
        dataset_id = str(context.get_data("dataset_id"))
        chat_name = f"Persona: {persona_key.replace('persona_', '')}"

        chat_yml = self.collection_dir / "Create Chat.yml"
        if not chat_yml.exists():
            raise FileNotFoundError(f"Bruno request file not found: {chat_yml}")

        update_chat_yml_request(
            yml_path=chat_yml,
            chat_name=chat_name,
            dataset_id=dataset_id,
            system_prompt=str(prompt_text),
        )
        logger.info(f"Preprocessed Create Chat.yml for persona '{persona_key}' with dataset_id '{dataset_id}'.")

    def _extract_results_list(self, result_data: dict[str, Any] | list[Any] | None) -> list[dict[str, Any]]:
        """Helper to collect all request result dicts across list/dict report structures."""
        results_list: list[dict[str, Any]] = []
        if isinstance(result_data, dict) and "results" in result_data:
            results_list = result_data["results"]
        elif isinstance(result_data, list):
            for entry in result_data:
                if isinstance(entry, dict) and "results" in entry:
                    results_list.extend(entry["results"])
                elif isinstance(entry, dict):
                    results_list.append(entry)
        return results_list

    def verify_result(
        self,
        context: PipelineContext,
        result_data: dict[str, Any] | list[Any] | None,
        item: Any | None = None,
    ) -> None:
        """Verify created chat ID, chat metadata, and session ID in Bruno response data for this persona item."""
        if item is None:
            raise BrunoPopulatorError(
                f"Step '{self.name}' must be executed with item iteration via get_items(). Normal single-execution verify_result() is not supported."
            )

        persona_key, _ = item
        results_list = self.verify_bruno_collection_results(result_data, expected_request_count=2)

        # 1. Validate Request #1 (Create Chat)
        chat_data = self.extract_value_by_key_path(results_list[0], "response.data.data")
        if not isinstance(chat_data, dict) or not chat_data.get("id"):
            raise BrunoPopulatorError(
                f"Failed to extract created Chat ID from response for persona '{persona_key}' in step '{self.name}'."
            )

        chat_id = str(chat_data["id"])
        chat_name = str(chat_data.get("name", ""))
        if not chat_name.startswith("Persona:"):
            raise BrunoPopulatorError(
                f"Unexpected chat name '{chat_name}' for persona '{persona_key}'. Expected name starting with 'Persona:'."
            )

        dataset_ids = chat_data.get("dataset_ids")
        if not isinstance(dataset_ids, list) or not dataset_ids:
            raise BrunoPopulatorError(
                f"Missing or empty 'dataset_ids' in created chat for persona '{persona_key}' in '{self.name}'."
            )

        system_prompt = self.extract_value_by_key_path(chat_data, "prompt_config.system")
        if not system_prompt or "{knowledge}" not in str(system_prompt):
            raise BrunoPopulatorError(
                f"System prompt in created chat for persona '{persona_key}' is missing mandatory RAG placeholder '{{knowledge}}'."
            )

        # 2. Validate Request #2 (Create Session)
        session_data = self.extract_value_by_key_path(results_list[1], "response.data.data")
        if not isinstance(session_data, dict) or not session_data.get("id"):
            raise BrunoPopulatorError(
                f"Failed to extract created Session ID from response for persona '{persona_key}' in step '{self.name}'."
            )

        session_chat_id = session_data.get("chat_id")
        if session_chat_id and str(session_chat_id) != chat_id:
            raise BrunoPopulatorError(
                f"Session chat_id mismatch: session specifies '{session_chat_id}' but parent chat is '{chat_id}' for persona '{persona_key}'."
            )

    def set_context(
        self,
        context: PipelineContext,
        result_data: dict[str, Any] | list[Any] | None,
        item: Any | None = None,
    ) -> None:
        """Extract created chat ID and session ID for this persona item and store in context."""
        if item is None:
            raise BrunoPopulatorError(
                f"Step '{self.name}' must be executed with item iteration via get_items(). Normal single-execution set_context() is not supported."
            )

        persona_key, _ = item
        results_list = self._extract_results_list(result_data)

        chat_id = str(self.extract_value_by_key_path(results_list[0], "response.data.data.id"))
        session_id = str(self.extract_value_by_key_path(results_list[1], "response.data.data.id"))

        logger.info(f"Created Chat ID: '{chat_id}', Session ID: '{session_id}' for persona '{persona_key}'.")

        created_chats = context.get_data("created_chats") or {}
        if not isinstance(created_chats, dict):
            created_chats = {}

        created_chats[persona_key] = {
            "chat_id": chat_id,
            "session_id": session_id,
        }
        context.set_data("created_chats", created_chats)
