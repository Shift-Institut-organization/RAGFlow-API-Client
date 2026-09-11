"""Master orchestrator for running sequential Bruno collection steps."""

import json
from typing import Any

from bruno_populator.config import BrunoRunConfig
from bruno_populator.exceptions import BrunoPopulatorError
from bruno_populator.logger import get_logger
from bruno_populator.pipeline.base_step import BaseCollectionStep
from bruno_populator.pipeline.context import PipelineContext
from bruno_populator.runner import run_bruno_collection

logger = get_logger("bruno_populator.pipeline.orchestrator")


class PipelineRunner:
    """Orchestrates sequential execution of Bruno collection pipeline steps."""

    def __init__(self, steps: list[BaseCollectionStep] | None = None, context: PipelineContext | None = None):
        self.steps: list[BaseCollectionStep] = steps or []
        self.context: PipelineContext = context or PipelineContext()

    def add_step(self, step: BaseCollectionStep) -> "PipelineRunner":
        """Register a new collection step to the pipeline."""
        self.steps.append(step)
        return self

    def run(self) -> PipelineContext:
        """
        Execute all registered steps sequentially.

        Halts immediately on step failure with explicit error logging.
        """
        total_steps = len(self.steps)
        logger.info(f"Starting Bruno Pipeline with {total_steps} registered steps.")

        for idx, step in enumerate(self.steps, start=1):
            logger.info(f"========== Step [{idx}/{total_steps}]: {step.name} ==========")

            items = step.get_items(self.context)

            if items is not None and len(items) > 0:
                total_items = len(items)
                logger.info(f"Iterating over {total_items} items for step '{step.name}'...")
                for item_idx, item in enumerate(items, start=1):
                    item_desc = str(item[0]) if isinstance(item, tuple | list) and item else str(item)
                    logger.info(
                        f"--- Step [{idx}/{total_steps}] '{step.name}' Item [{item_idx}/{total_items}]: {item_desc} ---"
                    )
                    self._run_single_step(step, item=item)
                    self.context.save_to_data_dir()
            else:
                self._run_single_step(step, item=None)
                self.context.save_to_data_dir()

            logger.info(f"Successfully completed Step [{idx}/{total_steps}]: {step.name}\n")

        logger.info("All collection pipeline steps completed successfully!")
        return self.context

    def _run_single_step(self, step: BaseCollectionStep, item: Any | None = None) -> None:
        """Execute Phase 1 -> Phase 2 -> Phase 3 lifecycle for a step (or single item)."""
        # Phase 1: Preprocessing
        if step.skip_preprocess:
            logger.info(f"--> [Phase 1/3] Preprocessing for '{step.name}' skipped (skip_preprocess=True).")
        else:
            logger.info(f"--> [Phase 1/3] Preprocessing for '{step.name}'...")
            try:
                step.preprocess(self.context, item=item)
            except Exception as exc:
                logger.error(f"Preprocessing failed for step '{step.name}': {exc}", exc_info=True)
                raise BrunoPopulatorError(f"Step '{step.name}' preprocessing error: {exc}") from exc

        # Phase 2: Execution via Bruno CLI
        item_key = step.get_item_key(item) if item is not None else None
        output_json_path = self.context.get_output_json_path(step.name, item_key=item_key)
        if step.skip_run:
            item_info = f" (item '{item[0] if isinstance(item, tuple | list) and item else item}')" if item else ""
            logger.info(f"--> [Phase 2/3] Executing Bruno collection '{step.name}' skipped (skip_run=True).")
            if not output_json_path.exists():
                msg = f"Cannot skip execution for step '{step.name}'{item_info}: required output JSON report not found at '{output_json_path}'."
                logger.error(msg)
                raise FileNotFoundError(msg)

            try:
                with open(output_json_path, encoding="utf-8") as f:
                    result_data = json.load(f)
                logger.info(f"Loaded existing output JSON report from '{output_json_path}'.")
            except Exception as exc:
                logger.error(
                    f"Failed to parse existing output JSON report at '{output_json_path}': {exc}",
                    exc_info=True,
                )
                raise BrunoPopulatorError(
                    f"Failed to parse existing output JSON report for step '{step.name}': {exc}"
                ) from exc
        else:
            logger.info(f"--> [Phase 2/3] Executing Bruno collection '{step.name}'...")
            run_config = BrunoRunConfig(
                collection_dir=step.collection_dir,
                env=step.env,
                output_json_path=output_json_path,
                exclude_tags=step.exclude_tags,
            )
            result_data = run_bruno_collection(run_config)

        # Phase 3: Postprocessing
        if step.skip_postprocess:
            logger.info(f"--> [Phase 3/3] Postprocessing for '{step.name}' skipped (skip_postprocess=True).")
        else:
            logger.info(f"--> [Phase 3/3] Postprocessing for '{step.name}'...")
            try:
                step.postprocess(self.context, result_data, item=item)
            except Exception as exc:
                logger.error(f"Postprocessing failed for step '{step.name}': {exc}", exc_info=True)
                raise BrunoPopulatorError(f"Step '{step.name}' postprocessing error: {exc}") from exc
