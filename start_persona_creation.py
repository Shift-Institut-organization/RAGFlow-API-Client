"""Main entrypoint script for executing sequential Bruno API populator collections."""

import sys
from pathlib import Path

# Ensure src is on python path
sys.path.insert(0, str(Path(__file__).parent / "src"))

import logging

from bruno_populator.exceptions import BrunoPopulatorError  # noqa: E402
from bruno_populator.logger import LogLevelMode, get_logger, set_log_level_mode  # noqa: E402
from bruno_populator.pipeline.context import PipelineContext  # noqa: E402
from bruno_populator.pipeline.orchestrator import PipelineRunner  # noqa: E402
from bruno_populator.steps import (  # noqa: E402, F401
    CreateChatsStep,
    CreateDatasetStep,
    CreateSystemPromptsStep,
)

context = PipelineContext()
logger = get_logger("start_bruno")


def main() -> None:
    set_log_level_mode(LogLevelMode.POPULATOR)
    level_name = logging.getLevelName(logger.getEffectiveLevel())
    logger.info("Initializing Master Bruno API Population Pipeline")
    logger.info(f"LOG_LEVEL: {level_name}")

    runner = PipelineRunner(context=context)
    runner.add_step(CreateSystemPromptsStep(skip_run=True))
    runner.add_step(CreateDatasetStep(skip_run=False))
    # runner.add_step(CreateChatsStep(skip_run=False))

    final_context = runner.run()
    logger.info("Master Pipeline Execution finished successfully!")
    logger.info(f"Final Context: {final_context}")


if __name__ == "__main__":
    try:
        main()
    except BrunoPopulatorError as err:
        logger.error(f"Pipeline Execution Failed: {err}", exc_info=True)
        sys.exit(1)
    except Exception as err:
        logger.error(f"Unexpected Pipeline Error: {err}", exc_info=True)
        sys.exit(1)
