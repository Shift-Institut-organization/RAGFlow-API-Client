"""Utilities for inspecting PDF page counts and splitting large PDF files into bounded parts."""

import math
import re
import shutil
from pathlib import Path

import pypdf

from bruno_populator.logger import get_logger

logger = get_logger("bruno_populator.pdf_splitter")
DEFAULT_MAX_PAGES = 40


def get_pdf_page_count(file_path: Path) -> int:
    """
    Extract page count from a local PDF file.
    Attempts pypdf extraction first, falling back to regex extraction if pypdf encounters an error.
    Returns 0 if count cannot be determined.
    """
    if not file_path.is_file():
        return 0

    # 1. Try pypdf
    try:
        reader = pypdf.PdfReader(str(file_path))
        return len(reader.pages)
    except Exception as exc:
        logger.debug(f"pypdf could not extract page count for '{file_path.name}': {exc}")

    # 2. Fallback to standard library regex
    try:
        content = file_path.read_bytes()
        counts = [int(m) for m in re.findall(rb"/Count\s+(\d+)", content)]
        if counts:
            return max(counts)
        pages = re.findall(rb"/Type\s*/Page\b", content)
        if pages:
            return len(pages)
    except Exception as exc:
        logger.debug(f"Regex page count fallback failed for '{file_path.name}': {exc}")

    return 0


def split_pdf_file(
    file_path: Path,
    output_dir: Path,
    max_pages: int = DEFAULT_MAX_PAGES,
) -> list[Path]:
    """
    Split a PDF file into parts of at most `max_pages` pages if it exceeds the limit.
    If the file has <= max_pages or is not a PDF, copies it directly to output_dir.

    Part naming convention:
        <stem>_p<start:03d>-<end:03d>.pdf
        e.g., sample_p001-040.pdf, sample_p041-080.pdf, sample_p081-116.pdf
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    if file_path.suffix.lower() != ".pdf":
        dest = output_dir / file_path.name
        if dest.resolve() != file_path.resolve():
            shutil.copy2(file_path, dest)
        return [dest]

    try:
        reader = pypdf.PdfReader(str(file_path))
        total_pages = len(reader.pages)
    except Exception as exc:
        logger.warning(f"Failed to read PDF '{file_path.name}' via pypdf ({exc}). Copying original without splitting.")
        dest = output_dir / file_path.name
        if dest.resolve() != file_path.resolve():
            shutil.copy2(file_path, dest)
        return [dest]

    if total_pages <= max_pages:
        dest = output_dir / file_path.name
        if dest.resolve() != file_path.resolve():
            shutil.copy2(file_path, dest)
        return [dest]

    # File exceeds max_pages: split into chunks of max_pages
    num_parts = math.ceil(total_pages / max_pages)
    logger.info(
        f"Splitting '{file_path.name}' ({total_pages} pages) into {num_parts} parts (max {max_pages} pages/part)..."
    )

    generated_parts: list[Path] = []
    for start_idx in range(0, total_pages, max_pages):
        end_idx = min(start_idx + max_pages, total_pages)
        pstart = start_idx + 1
        pend = end_idx
        part_name = f"{file_path.stem}_p{pstart:03d}-{pend:03d}{file_path.suffix}"
        part_path = output_dir / part_name

        writer = pypdf.PdfWriter()
        for page_idx in range(start_idx, end_idx):
            writer.add_page(reader.pages[page_idx])

        with open(part_path, "wb") as f_out:
            writer.write(f_out)

        logger.info(f"  Created part: '{part_path.name}' (pages {pstart}-{pend}, count: {pend - pstart + 1}).")
        generated_parts.append(part_path)

    return generated_parts


def prepare_staged_documents(
    source_files: list[Path],
    staged_dir: Path,
    max_pages: int = DEFAULT_MAX_PAGES,
) -> list[Path]:
    """
    Process source files into staged_dir, splitting any PDF exceeding max_pages into compliant parts.
    Returns a sorted list of all compliant staged file paths.
    """
    staged_dir.mkdir(parents=True, exist_ok=True)
    all_staged: list[Path] = []

    for src in source_files:
        if not src.is_file():
            continue
        parts = split_pdf_file(src, staged_dir, max_pages=max_pages)
        all_staged.extend(parts)

    return sorted(all_staged, key=lambda p: p.name)
