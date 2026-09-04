import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from bruno_converser.runner import ConverserRunner
from bruno_converser.session import ConversationSession, clean_persona_name
from bruno_populator.exceptions import BrunoPopulatorError
from bruno_populator.logger import get_logger

logger = get_logger("bruno_converser.report_generator")


def extract_page_numbers(chunk: dict[str, Any]) -> list[int]:
    """
    Extract all unique page numbers from a chunk's 'positions' attribute.

    Each entry in 'positions' is expected to be a list/tuple starting with page_number (e.g. [10, 0, 595, 0, 794]).
    Returns sorted list of unique integer page numbers.
    """
    positions = chunk.get("positions")
    if not isinstance(positions, list) or not positions:
        return []

    pages: set[int] = set()
    for pos in positions:
        if isinstance(pos, list | tuple) and pos and isinstance(pos[0], int | float):
            pages.add(int(pos[0]))

    return sorted(list(pages))


def format_page_numbers_str(pages: list[int]) -> str:
    """Format list of page numbers into human readable string (e.g. [7] -> 'Page 7', [7, 8] -> 'Pages 7, 8')."""
    if not pages:
        return ""
    if len(pages) == 1:
        return f"Page {pages[0]}"
    return f"Pages {', '.join(str(p) for p in pages)}"


def extract_cited_indices(content: str) -> list[int]:
    """Extract unique integer chunk indices from '[ID:x]' citations in text."""
    matches = re.findall(r"\[ID:(\d+)\]", content)
    if not matches:
        return []
    return sorted(list(set(int(m) for m in matches)))


def extract_chunks_from_turn_file(history_file: Path) -> list[dict[str, Any]]:
    """Load turn history JSON file and extract reference chunks array."""
    if not history_file.exists():
        logger.warning(f"Turn history file '{history_file}' does not exist.")
        return []

    try:
        with open(history_file, encoding="utf-8") as f:
            raw_data = json.load(f)
    except Exception as exc:
        logger.warning(f"Failed loading turn history JSON from '{history_file}': {exc}")
        return []

    # Path 1: Bruno wrapper [0].results[0].response.data.data
    target_data = None
    if isinstance(raw_data, list) and raw_data:
        res_list = raw_data[0].get("results", [])
        if res_list and isinstance(res_list, list):
            target_data = res_list[0].get("response", {}).get("data", {}).get("data")
    elif isinstance(raw_data, dict):
        target_data = raw_data.get("response", {}).get("data", {}).get("data", raw_data)

    if not isinstance(target_data, dict):
        return []

    ref = target_data.get("reference")
    if isinstance(ref, dict):
        return ref.get("chunks", [])
    elif isinstance(ref, list) and ref and isinstance(ref[0], dict):
        return ref[0].get("chunks", [])

    return []


class ConversationReportGenerator:
    """Generates structured Markdown conversation report with quoted document references."""

    def __init__(self, session: ConversationSession, runner: ConverserRunner | None = None):
        self.session = session
        self.runner = runner or ConverserRunner()

    def generate_report(self, filename: str = "conversation_report.md") -> Path:
        """
        Export formatted Markdown report reading reference chunks from per-turn history JSONs.

        Saves report to session.context.data_dir / filename.
        Returns absolute Path of generated report file.
        """
        if not self.session.history:
            raise BrunoPopulatorError("Cannot generate conversation report: conversation transcript is empty.")

        target_personas = set(
            msg.get("persona") for msg in self.session.history if msg.get("role") == "assistant" and msg.get("persona")
        )
        if not target_personas:
            target_personas = set(self.session.persona_keys)

        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        data_dir = self.session.context.data_dir.resolve()

        lines: list[str] = [
            "# Conversation Transcript & RAG Reference Report",
            "",
            f"- **Generated At**: {now_str}",
            f"- **Active Data Directory**: `{data_dir}`",
            f"- **Participating Personas**: {', '.join(clean_persona_name(p) for p in target_personas)}",
            f"- **Total Turns**: {len(self.session.history)}",
            "",
            "---",
            "",
            "## Sequential Conversation History",
            "",
        ]

        persona_turn_counter: dict[str, int] = {p: 0 for p in target_personas}

        for idx, msg in enumerate(self.session.history, start=1):
            role = msg.get("role", "user")
            content = msg.get("content", "").strip()

            if role == "user":
                lines.append(f"### Turn {idx}: User")
                lines.append(content)
                lines.append("")
            elif role == "assistant":
                persona_key = msg.get("persona", self.session.active_persona_key)
                clean_name = clean_persona_name(persona_key)

                lines.append(f"### Turn {idx}: Persona: {clean_name}")
                lines.append(content)
                lines.append("")

                turn_idx = persona_turn_counter.get(persona_key, 0) + 1
                persona_turn_counter[persona_key] = turn_idx

                history_file = self.session.history_dir / f"{persona_key}_message_{turn_idx:02d}.json"
                chunks = extract_chunks_from_turn_file(history_file)
                cited_ids = extract_cited_indices(content)

                # If specific [ID:x] citations exist, filter to cited chunks; otherwise output available chunks
                target_chunk_indices = cited_ids if cited_ids else list(range(len(chunks)))

                if chunks and target_chunk_indices:
                    lines.append("#### Quoted Documents & References:")
                    for c_id in target_chunk_indices:
                        if c_id < len(chunks):
                            chunk = chunks[c_id]
                            doc_name = chunk.get("document_name", "Unknown Document")
                            chunk_content = chunk.get("content", "").strip()
                            similarity = chunk.get("vector_similarity") or chunk.get("similarity")

                            pages = extract_page_numbers(chunk)
                            page_str = f" ({format_page_numbers_str(pages)})" if pages else ""
                            score_str = (
                                f" | Similarity: {similarity:.4f}" if isinstance(similarity, float | int) else ""
                            )

                            lines.append(f"> **[ID:{c_id}] {doc_name}**{page_str}{score_str}")
                            if chunk_content:
                                quoted_snippet = "\n> ".join(chunk_content.splitlines())
                                lines.append(f"> {quoted_snippet}")
                            lines.append(">")
                    lines.append("")
                else:
                    lines.append("*[No external document references cited for this response]*")
                    lines.append("")

        lines.append("---")
        lines.append("*Report generated automatically by RAGFlow Converser CLI.*")

        report_md_text = "\n".join(lines)

        output_file_path = (
            (data_dir / filename).resolve() if not Path(filename).is_absolute() else Path(filename).resolve()
        )
        output_file_path.parent.mkdir(parents=True, exist_ok=True)
        output_file_path.write_text(report_md_text, encoding="utf-8")

        logger.info(f"Successfully generated conversation report at '{output_file_path}'.")
        return output_file_path


def generate_conversation_report(
    session: ConversationSession,
    runner: ConverserRunner | None = None,
    filename: str = "conversation_report.md",
) -> Path:
    """Convenience function to generate and save conversation report in active data directory."""
    generator = ConversationReportGenerator(session, runner)
    return generator.generate_report(filename)
