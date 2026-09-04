"""Subprocess wrapper for Bruno CLI execution with strict error checking."""

import json
import subprocess
from pathlib import Path
from typing import Any

from bruno_populator.config import BrunoRunConfig
from bruno_populator.exceptions import BrunoCliError, ConfigurationError
from bruno_populator.logger import get_logger
from bruno_populator.yml_injector import temporary_collection_token

logger = get_logger("bruno_populator.runner")


def build_bru_command(config: BrunoRunConfig) -> list[str]:
    """Construct command line argument list for Bruno CLI."""
    cmd = ["bru", "run"]

    if config.request_file:
        cmd.append(str(config.request_file))

    if config.env:
        cmd.extend(["--env", config.env])

    if config.exclude_tags:
        tags_str = ",".join(config.exclude_tags)
        cmd.append(f"--exclude-tags={tags_str}")

    if config.output_json_path:
        cmd.extend(["--output", str(config.output_json_path)])

    logger.debug(f"Constructed Bruno CLI command: {' '.join(cmd)}")
    return cmd


def run_bruno_collection(config: BrunoRunConfig) -> dict[str, Any] | None:
    """
    Execute Bruno collection via CLI and return parsed JSON output if configured.

    Raises:
        ConfigurationError: If collection directory is missing.
        BrunoCliError: If `bru` CLI fails, returns non-zero code, or produces corrupt output.
    """
    col_dir = config.collection_dir.resolve()
    if not col_dir.exists():
        logger.error(f"Bruno collection directory does not exist: {col_dir}")
        raise ConfigurationError(f"Collection directory does not exist: {col_dir}")

    cmd = build_bru_command(config)
    logger.info(f"Executing Bruno CLI collection in {col_dir}")
    logger.debug(f"exact bru command {cmd}")

    try:
        with temporary_collection_token(col_dir, token=config.api_key):
            result = subprocess.run(
                cmd,
                cwd=str(col_dir),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                shell=True,
            )

    except FileNotFoundError as exc:
        logger.error(f"Bruno CLI ('bru') executable not found: {exc}")
        raise BrunoCliError(f"Bruno CLI (`bru`) executable not found: {exc}") from exc
    except Exception as exc:
        logger.error(f"Unexpected error starting subprocess: {exc}")
        raise BrunoCliError(f"Subprocess execution failed unexpectedly: {exc}") from exc

    if result.returncode != 0:
        stdout_msg = f"\nStdout:\n{result.stdout.strip()}" if result.stdout and result.stdout.strip() else ""
        stderr_msg = f"\nStderr:\n{result.stderr.strip()}" if result.stderr and result.stderr.strip() else ""
        err_details = f"{stdout_msg}{stderr_msg}".strip()
        logger.error(f"Bruno CLI failed with exit code {result.returncode}.\n{err_details}")
        raise BrunoCliError(
            message=f"Bruno CLI execution failed with code {result.returncode}.\n{err_details}",
            exit_code=result.returncode,
            stderr=result.stderr,
        )

    logger.info("Bruno CLI collection executed successfully (exit code 0)")

    if not config.output_json_path:
        return None

    out_file = config.output_json_path
    if not out_file.is_absolute():
        out_file = col_dir / out_file

    if not out_file.exists():
        logger.warning(f"Output JSON file requested but not found at {out_file}")
        return None

    try:
        with open(out_file, encoding="utf-8") as f:
            data = json.load(f)
            logger.debug(f"Loaded output JSON results from {out_file}")
            return data
    except Exception as exc:
        logger.error(f"Failed parsing output JSON file {out_file}: {exc}")
        raise BrunoCliError(f"Failed to parse Bruno output JSON at {out_file}: {exc}") from exc


def run_bruno_request(
    request_file_path: Path,
    env: str | None = None,
    output_json_path: Path | None = None,
) -> dict[str, Any] | None:
    """
    Execute a single Bruno request file (.yml) via Bruno CLI (`bru run <request.yml>`).

    Raises:
        FileNotFoundError: If request_file_path does not exist.
        BrunoCliError: If `bru` CLI fails, returns non-zero code, or produces corrupt output.
    """
    resolved_file = request_file_path.resolve()
    if not resolved_file.exists():
        logger.error(f"Bruno request file does not exist: {resolved_file}")
        raise FileNotFoundError(f"Bruno request file does not exist: {resolved_file}")

    col_dir = resolved_file.parent
    from paths import OUTPUT_JSON_FILENAME

    output_path = output_json_path or (col_dir / OUTPUT_JSON_FILENAME)

    cmd = ["bru", "run", resolved_file.name]
    if env:
        cmd.extend(["--env", env])
    if output_path:
        cmd.extend(["--output", str(output_path)])

    logger.info(f"Executing single Bruno request '{resolved_file.name}' in {col_dir}")
    logger.debug(f"Exact bru command: {' '.join(cmd)}")

    try:
        with temporary_collection_token(col_dir):
            result = subprocess.run(
                cmd,
                cwd=str(col_dir),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                shell=True,
            )
    except FileNotFoundError as exc:
        logger.error(f"Bruno CLI ('bru') executable not found: {exc}")
        raise BrunoCliError(f"Bruno CLI (`bru`) executable not found: {exc}") from exc
    except Exception as exc:
        logger.error(f"Unexpected error starting subprocess: {exc}")
        raise BrunoCliError(f"Subprocess execution failed unexpectedly: {exc}") from exc

    if result.returncode != 0:
        stdout_msg = f"\nStdout:\n{result.stdout.strip()}" if result.stdout and result.stdout.strip() else ""
        stderr_msg = f"\nStderr:\n{result.stderr.strip()}" if result.stderr and result.stderr.strip() else ""
        err_details = f"{stdout_msg}{stderr_msg}".strip()
        logger.error(f"Bruno CLI failed with exit code {result.returncode}.\n{err_details}")
        raise BrunoCliError(
            message=f"Bruno CLI execution for '{resolved_file.name}' failed with code {result.returncode}.\n{err_details}",
            exit_code=result.returncode,
            stderr=result.stderr,
        )

    logger.info(f"Bruno request '{resolved_file.name}' executed successfully (exit code 0)")

    if not output_path.exists():
        logger.warning(f"Output JSON file requested but not found at {output_path}")
        return None

    try:
        with open(output_path, encoding="utf-8") as f:
            data = json.load(f)
            logger.debug(f"Loaded output JSON results from {output_path}")
            return data
    except Exception as exc:
        logger.error(f"Failed parsing output JSON file {output_path}: {exc}")
        raise BrunoCliError(f"Failed to parse Bruno output JSON at {output_path}: {exc}") from exc
