import re
from pathlib import Path
from typing import Any

from bruno_populator.exceptions import BrunoPopulatorError
from bruno_populator.logger import get_logger
from bruno_populator.pipeline.base_step import BaseCollectionStep
from bruno_populator.pipeline.context import PipelineContext
from bruno_populator.yml_injector import (
    inject_prompt_into_bruno_yml,
    update_multipart_files_in_yml,
    update_yml_payload_key,
)
from paths import GENERATED_PROMPTS_DIR, PROMPTS_DIR

logger = get_logger("bruno_populator.steps.create_system_prompts")
STEP_DIR = Path(__file__).resolve().parent

# Target key path in output.json for extracting the generated persona prompt answer string
ANSWER_KEY_PATH = "[0].results[2].response.data.data.answer"


def parse_persona_prompts(text: str) -> list[tuple[str, str]]:
    """
    Extract individual persona prompt sections using the mandatory '{knowledge}' keyword as block terminator.

    Hard fails with BrunoPopulatorError if '{knowledge}' is missing.
    Warns if header doesn't strictly match '# System-Prompt für Persona: <NAME>', but falls back to loose header match.
    Auto-increments persona names if duplicate names are encountered.
    """
    if "{knowledge}" not in text:
        raise BrunoPopulatorError(
            "No '{knowledge}' placeholder found in LLM output text. "
            "Generated persona system-prompts must contain the '{knowledge}' placeholder."
        )

    raw_blocks = text.split("{knowledge}")
    if raw_blocks and not raw_blocks[-1].strip():
        raw_blocks.pop()

    parsed: list[tuple[str, str]] = []
    seen_names: dict[str, int] = {}

    strict_header_pattern = r"# System-Prompt f[üu]r Persona:\s*([^\r\n]+)"
    loose_header_pattern = (
        r"#+\s*(?:\*\*)?System-Prompt\s*(?:f[üu]r\s*)?(?:die\s*)?(?:Persona)?:?\s*([^\r\n*]+)(?:\*\*)?"
    )

    for block in raw_blocks:
        strict_match = re.search(strict_header_pattern, block)

        if strict_match:
            raw_name = strict_match.group(1).strip().strip('"').strip("'")
            header_start = strict_match.start()
        else:
            loose_match = re.search(loose_header_pattern, block, re.IGNORECASE)
            if not loose_match:
                continue

            header_line = loose_match.group(0).strip()
            raw_name = loose_match.group(1).strip().strip('"').strip("'")
            header_start = loose_match.start()

            logger.warning(
                f"Persona prompt header '{header_line}' does not strictly match "
                f"recommended format '# System-Prompt für Persona: <NAME>'. Falling back to name '{raw_name}'."
            )

        clean_key = raw_name.lower()
        if clean_key in seen_names:
            seen_names[clean_key] += 1
            final_name = f"{raw_name} {seen_names[clean_key]}"
            logger.warning(f"Duplicate persona name detected ('{raw_name}'). Renamed to '{final_name}'.")
        else:
            seen_names[clean_key] = 1
            final_name = raw_name

        prompt_body = block[header_start:].strip()
        full_prompt = f"{prompt_body}\n\nder context: {{knowledge}}\n"

        parsed.append((final_name, full_prompt))

    if not parsed:
        raise BrunoPopulatorError("Failed to extract any valid persona system-prompts from LLM output text.")

    return parsed


def sanitize_persona_filename(persona_name: str) -> str:
    """Sanitize persona name into a clean markdown filename (e.g. 'Günther' -> 'persona_guenther.md')."""
    cleaned = persona_name.strip().lower()
    cleaned = cleaned.replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")
    cleaned = re.sub(r"[^\w\-]", "_", cleaned)
    cleaned = re.sub(r"_+", "_", cleaned).strip("_")
    return f"persona_{cleaned}.md" if not cleaned.startswith("persona_") else f"{cleaned}.md"


class CreateSystemPromptsStep(BaseCollectionStep):
    """Collection step for creating System Prompt chats."""

    def __init__(
        self,
        collection_dir: Path | str | None = None,
        prompt_path: Path | str | None = None,
        skip_preprocess: bool = False,
        skip_run: bool = False,
        skip_postprocess: bool = False,
    ):
        p_path = Path(prompt_path).resolve() if prompt_path else (PROMPTS_DIR / "create_persona_prompt.md").resolve()
        if not p_path.exists():
            raise FileNotFoundError(f"System prompt file not found: {p_path}")
        self._prompt_path = p_path

        super().__init__(
            collection_dir=collection_dir,
            skip_preprocess=skip_preprocess,
            skip_run=skip_run,
            skip_postprocess=skip_postprocess,
        )

    @property
    def name(self) -> str:
        return "RAGFlow create System prompts"

    @property
    def prompt_path(self) -> Path:
        return self._prompt_path

    def preprocess(self, context: PipelineContext, item: Any | None = None) -> None:
        """Inject Markdown prompt and file attachment into Bruno YML files before execution."""
        logger.info(f"Preprocessing Bruno request files for '{self.name}'...")

        # 1. Inject prompt and project chat name into Create Chat System Prompt.yml
        create_prompt_yml = self.collection_dir / "Create Chat System Prompt.yml"
        if not create_prompt_yml.exists():
            raise FileNotFoundError(f"Bruno request file not found: {create_prompt_yml}")

        inject_prompt_into_bruno_yml(
            yml_path=create_prompt_yml,
            prompt_path=self.prompt_path,
            key_path="prompt_config.system",
        )

        chat_name = f"Create System Prompt Chats Auto - {context.project_name}"
        update_yml_payload_key(create_prompt_yml, "name", chat_name)
        logger.info(f"Configured System Prompt chat name to '{chat_name}'.")

        # 2. Attach requirements.md file to Upload Document.yml
        upload_doc_yml = self.collection_dir / "Upload Document.yml"
        if not upload_doc_yml.exists():
            raise FileNotFoundError(f"Bruno request file not found: {upload_doc_yml}")

        requirements_path = context.requirements_path
        update_multipart_files_in_yml(upload_doc_yml, [requirements_path])

    def verify_result(
        self,
        context: PipelineContext,
        result_data: dict[str, Any] | list[Any] | None,
        item: Any | None = None,
    ) -> None:
        """Verify generated persona prompts answer string in Bruno JSON output report."""
        request_entries = self.verify_bruno_collection_results(result_data, expected_request_count=3)

        # 1. Validate Request #1 (Create Chat System Prompt)
        code = self.extract_value_by_key_path(request_entries[0], "response.data.code")
        if code is not None and code != 0:
            msg = self.extract_value_by_key_path(request_entries[0], "response.data.message") or "Unknown error"
            raise BrunoPopulatorError(
                f"RAGFlow API error in Request #1 (Create Chat System Prompt): code={code}, message='{msg}'. "
                f"Note: RAGFlow rejects duplicate chat names. Ensure chat 'Create System Prompt Chats Auto - {context.project_name}' does not already exist."
            )

        chat_id = self.extract_value_by_key_path(request_entries[0], "response.data.data.id")
        if not chat_id:
            raise BrunoPopulatorError(
                f"Failed to extract created System Prompt chat ID from Request #1 in '{self.name}'."
            )

        # 2. Validate Request #2 (Upload Document)
        doc_id = self.extract_value_by_key_path(request_entries[1], "response.data.data.id")
        if not doc_id:
            raise BrunoPopulatorError(f"Failed to extract uploaded document ID from Request #2 in '{self.name}'.")

        # 3. Validate Request #3 (Create Persona Prompts LLM answer)
        answer_text = self.extract_value_by_key_path(result_data, ANSWER_KEY_PATH)
        if not isinstance(answer_text, str) or not answer_text.strip():
            raise BrunoPopulatorError(
                f"Failed to find generated prompt answer string at key path '{ANSWER_KEY_PATH}' for '{self.name}'."
            )

        parsed_prompts = parse_persona_prompts(answer_text)
        if not parsed_prompts:
            logger.error(f"Raw answer text:\n{answer_text}")
            raise BrunoPopulatorError(
                f"Failed to parse any persona prompts matching boundary pattern from answer text in '{self.name}'."
            )

        # Validate blueprint sections and RAG placeholder for each persona prompt
        required_headers = [
            "DEINE IDENTITÄT:",
            "NAME:",
            "ALTER:",
            "CHARAKTER & SPRACHSTIL:",
            "PROJEKT-ROLLE:",
            "HAUPTBEDÜRFNIS:",
        ]
        for persona_name, prompt_text in parsed_prompts:
            if "{knowledge}" not in prompt_text:
                raise BrunoPopulatorError(
                    f"Generated prompt for persona '{persona_name}' is missing mandatory RAG placeholder '{{knowledge}}'."
                )
            for header in required_headers:
                if header not in prompt_text:
                    raise BrunoPopulatorError(
                        f"Generated prompt for persona '{persona_name}' is missing required blueprint section '{header}'."
                    )

    def set_context(
        self,
        context: PipelineContext,
        result_data: dict[str, Any] | list[Any] | None,
        item: Any | None = None,
    ) -> None:
        """Extract generated persona prompts from Bruno JSON output report and save to src/prompts/generated."""
        logger.info(f"Setting context and saving generated files for '{self.name}'...")
        answer_text = self.extract_value_by_key_path(result_data, ANSWER_KEY_PATH)
        parsed_prompts = parse_persona_prompts(str(answer_text))

        GENERATED_PROMPTS_DIR.mkdir(parents=True, exist_ok=True)
        prompt_map: dict[str, str] = {}
        saved_files: list[str] = []

        for persona_name, prompt_text in parsed_prompts:
            filename = sanitize_persona_filename(persona_name)
            key_name = Path(filename).stem
            prompt_map[key_name] = prompt_text

            file_path = GENERATED_PROMPTS_DIR / filename
            file_path.write_text(prompt_text, encoding="utf-8")
            saved_files.append(str(file_path))
            logger.info(f"Saved generated prompt for persona '{persona_name}' to {file_path}")

        context.set_data("generated_persona_prompts", prompt_map)
        context.set_data("generated_prompt_files", saved_files)
        logger.info(
            f"Successfully postprocessed '{self.name}': extracted {len(prompt_map)} persona prompts and saved files."
        )
