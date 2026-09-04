"""Main entrypoint script for running the interactive RAGFlow Multi-Persona Converser."""

import sys
from pathlib import Path

# Ensure src/ is in sys.path
sys.path.insert(0, str((Path(__file__).parent / "src").resolve()))

from bruno_converser.cli import run_cli_chat  # noqa: E402
from bruno_populator.exceptions import BrunoPopulatorError  # noqa: E402
from bruno_populator.logger import LogLevelMode, get_logger, set_log_level_mode  # noqa: E402

logger = get_logger("start_converse")


def main() -> None:
    set_log_level_mode(LogLevelMode.CONVERSE)
    logger.info("Starting interactive RAGFlow Multi-Persona Converser...")
    try:
        run_cli_chat()
    except BrunoPopulatorError as exc:
        logger.error(f"Converser execution error: {exc}")
        print(f"\n[Fatal Error] {exc}")
        sys.exit(1)
    except Exception as exc:
        logger.error(f"Unexpected error: {exc}", exc_info=True)
        print(f"\n[Fatal Error] Unexpected failure: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
