"""Main entrypoint script for extracting and separating INFERRED and EXPLICIT user features.

Reads summary.json from the active environment DATA_DIR project folder and outputs user_features.json
at the same level.
"""

import sys
from pathlib import Path

# Ensure src is on python path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from bruno_populator.config import load_app_config  # noqa: E402
from bruno_populator.logger import get_logger  # noqa: E402
from user_features import process_project_summary  # noqa: E402

logger = get_logger("start_feature_extraction")


def main() -> None:
    config = load_app_config()
    logger.info(f"Loaded project configuration. Active DATA_DIR: {config.data_dir}")

    output_file = process_project_summary(data_dir=config.data_dir)
    logger.info(f"Feature extraction completed successfully! Results written to: {output_file}")


if __name__ == "__main__":
    try:
        main()
    except Exception as err:
        logger.error(f"Feature extraction failed: {err}", exc_info=True)
        sys.exit(1)
