"""Collection step for creating RAGFlow Datasets with sequential document parsing and retry policy."""

import time
from pathlib import Path
from typing import Any

from bruno_populator.exceptions import BrunoPopulatorError
from bruno_populator.logger import get_logger
from bruno_populator.pipeline.base_step import BaseCollectionStep
from bruno_populator.pipeline.context import PipelineContext
from bruno_populator.request_builder import BrunoRequestBuilder
from bruno_populator.runner import run_bruno_request
from bruno_populator.yml_injector import update_multipart_files_in_yml
from paths import BRUNO_DIR

logger = get_logger("bruno_populator.steps.create_dataset")
STEP_DIR = Path(__file__).resolve().parent
TERMINAL_STATUSES = {"DONE", "FAIL", "CANCEL"}
NON_TERMINAL_STATUSES = {"UNSTART", "RUNNING"}


def fetch_documents_status(context: PipelineContext, dataset_id: str) -> list[dict[str, Any]]:
    """Fetch document parsing status list for dataset_id using Bruno CLI single request."""
    single_calls_dir = (BRUNO_DIR / "RAGFlow single calls").resolve()
    single_calls_dir.mkdir(parents=True, exist_ok=True)

    request_file = single_calls_dir / "Get Documents.yml"
    builder = BrunoRequestBuilder(
        name="Get Documents",
        seq=1,
        method="GET",
        url=f"/api/v1/datasets/{dataset_id}/documents",
        base_url=context.base_url,
    )
    builder.save(request_file)

    open_col = single_calls_dir / "opencollection.yml"
    if not open_col.exists():
        open_col.write_text("bundled: []\n", encoding="utf-8")

    result_data = run_bruno_request(request_file)
    docs = BaseCollectionStep.extract_value_by_key_path(result_data, "[0].results[0].response.data.data.docs")
    if not isinstance(docs, list):
        raise BrunoPopulatorError(
            f"Failed to fetch document status list for dataset '{dataset_id}' via Bruno CLI request '{request_file.name}'."
        )

    return docs


def trigger_document_parse(context: PipelineContext, dataset_id: str, document_id: str) -> None:
    """Trigger chunking/parsing for a single document ID via Bruno CLI single request."""
    single_calls_dir = (BRUNO_DIR / "RAGFlow single calls").resolve()
    single_calls_dir.mkdir(parents=True, exist_ok=True)

    request_file = single_calls_dir / "Parse Document.yml"
    builder = BrunoRequestBuilder(
        name="Parse Document",
        seq=1,
        method="POST",
        url=f"/api/v1/datasets/{dataset_id}/chunks",
        base_url=context.base_url,
    ).set_json_body({"document_ids": [document_id]})
    builder.save(request_file)

    open_col = single_calls_dir / "opencollection.yml"
    if not open_col.exists():
        open_col.write_text("bundled: []\n", encoding="utf-8")

    result_data = run_bruno_request(request_file)
    code = BaseCollectionStep.extract_value_by_key_path(result_data, "[0].results[0].response.data.code")
    if code is not None and code != 0:
        msg = (
            BaseCollectionStep.extract_value_by_key_path(result_data, "[0].results[0].response.data.message")
            or "Unknown error"
        )
        raise BrunoPopulatorError(
            f"RAGFlow API error starting document parsing for '{document_id}': code={code}, message='{msg}'."
        )


def check_document_progress(
    curr_doc: dict[str, Any],
    last_doc: dict[str, Any],
) -> tuple[bool, str]:
    """Determine whether curr_doc has made forward progress compared to last_doc."""
    curr_prog = float(curr_doc.get("progress") or 0.0)
    last_prog = float(last_doc.get("progress") or 0.0)
    if curr_prog > last_prog:
        return True, f"progress increased ({last_prog:.1%} -> {curr_prog:.1%})"

    curr_chunks = int(curr_doc.get("chunk_count") or 0)
    last_chunks = int(last_doc.get("chunk_count") or 0)
    if curr_chunks > last_chunks:
        return True, f"chunk count increased ({last_chunks} -> {curr_chunks})"

    curr_tokens = int(curr_doc.get("token_count") or 0)
    last_tokens = int(last_doc.get("token_count") or 0)
    if curr_tokens > last_tokens:
        return True, f"token count increased ({last_tokens} -> {curr_tokens})"

    curr_msg = str(curr_doc.get("progress_msg") or "").strip()
    last_msg = str(last_doc.get("progress_msg") or "").strip()
    if curr_msg and curr_msg != last_msg:
        curr_lines = [ln.strip() for ln in curr_msg.splitlines() if ln.strip()]
        last_lines = set(ln.strip() for ln in last_msg.splitlines() if ln.strip())
        new_lines = [ln for ln in curr_lines if ln not in last_lines]
        detail = new_lines[-1] if new_lines else curr_msg[-40:]
        return True, f"new progress log ('{detail}')"

    curr_run = str(curr_doc.get("run", "")).upper()
    last_run = str(last_doc.get("run", "")).upper()
    if last_run == "UNSTART" and curr_run == "RUNNING":
        return True, "status changed from UNSTART to RUNNING"

    return False, ""


def poll_single_document_status(
    context: PipelineContext,
    dataset_id: str,
    doc_id: str,
    doc_name: str,
    poll_interval: float = 10.0,
    max_timeout: float = 600.0,
    initial_doc: dict[str, Any] | None = None,
) -> tuple[bool, str, str, dict[str, Any]]:
    """
    Poll status of a single document, resetting the timeout each time progress is observed.

    Returns:
        tuple[success, terminal_status, progress_message, latest_doc_snapshot]
    """
    start_time = time.time()
    last_progress_time = start_time
    last_doc_state = dict(initial_doc or {})
    latest_doc = last_doc_state

    while True:
        docs = fetch_documents_status(context, dataset_id)
        matching = [d for d in docs if str(d.get("id")) == str(doc_id)]
        if not matching:
            logger.debug(f"Document '{doc_name}' ({doc_id}) not found in dataset document list yet.")
        else:
            latest_doc = matching[0]
            status = str(latest_doc.get("run", "")).upper()
            msg = latest_doc.get("progress_msg", "") or ""

            if status == "DONE":
                elapsed = time.time() - start_time
                logger.info(f"Document '{doc_name}' parsed successfully (DONE) in {elapsed:.1f}s.")
                return True, status, msg, latest_doc

            if status in ("FAIL", "CANCEL"):
                return False, status, msg, latest_doc

            has_progressed, reason = check_document_progress(latest_doc, last_doc_state)
            if has_progressed:
                logger.info(
                    f"Document '{doc_name}' made progress: {reason}. Resetting {max_timeout:.0f}s timeout window."
                )
                last_progress_time = time.time()
                last_doc_state = dict(latest_doc)
            else:
                elapsed = time.time() - start_time
                logger.debug(
                    f"Document '{doc_name}' parsing in progress (Status: {status}, Elapsed: {elapsed:.0f}s)..."
                )

        if time.time() - last_progress_time > max_timeout:
            last_status = str(latest_doc.get("run", "TIMEOUT")).upper()
            logger.warning(
                f"Document '{doc_name}' made no progress for {max_timeout:.0f}s (Status: {last_status}). Continuing..."
            )
            return False, "TIMEOUT", f"Polling timed out after {max_timeout:.0f}s with no progress", latest_doc

        time.sleep(poll_interval)


def parse_single_doc_attempt(
    context: PipelineContext,
    dataset_id: str,
    doc: dict[str, Any],
    attempt_num: int,
    poll_interval: float = 10.0,
    doc_timeout: float = 600.0,
) -> tuple[bool, str, dict[str, Any]]:
    """Trigger and poll parsing for one document. Returns (success, failure_reason, latest_doc)."""
    doc_id = str(doc.get("id", ""))
    doc_name = str(doc.get("name", doc_id))

    try:
        trigger_document_parse(context, dataset_id, doc_id)
    except Exception as exc:
        err_msg = f"Failed to trigger parse request: {exc}"
        return False, err_msg, doc

    success, status, msg, latest_doc = poll_single_document_status(
        context=context,
        dataset_id=dataset_id,
        doc_id=doc_id,
        doc_name=doc_name,
        poll_interval=poll_interval,
        max_timeout=doc_timeout,
        initial_doc=doc,
    )
    if success:
        return True, "", latest_doc

    failure_reason = f"Status: {status}, Message: '{msg}'" if msg else f"Status: {status}"
    return False, failure_reason, latest_doc


def handle_doc_second_attempt(
    context: PipelineContext,
    dataset_id: str,
    doc_state: dict[str, Any],
    idx: int,
    retry_count: int,
    poll_interval: float = 10.0,
    doc_timeout: float = 600.0,
) -> tuple[bool, str, dict[str, Any]]:
    """
    Check document status before sending a new parsing request, resuming polling if
    active progress exists or triggering attempt 2 if stalled or failed.
    """
    doc_id = str(doc_state.get("id", ""))
    doc_name = str(doc_state.get("name", doc_id))

    # Pre-check status from server before issuing any new parsing request
    docs = fetch_documents_status(context, dataset_id)
    matching = [d for d in docs if str(d.get("id")) == doc_id]
    curr_doc = matching[0] if matching else doc_state
    curr_status = str(curr_doc.get("run", "")).upper()
    curr_prog = float(curr_doc.get("progress") or 0.0)
    curr_chunks = int(curr_doc.get("chunk_count") or 0)
    curr_msg = str(curr_doc.get("progress_msg") or "").strip()
    msg_summary = curr_msg.splitlines()[-1] if curr_msg else "None"

    logger.info(
        f"--> [Retry {idx}/{retry_count}] Pre-check status for document '{doc_name}' (ID: {doc_id}): "
        f"Status='{curr_status}', Progress={curr_prog:.1%}, Chunks={curr_chunks}, Message='{msg_summary}'."
    )

    if curr_status == "DONE":
        logger.info(f"Document '{doc_name}' (ID: {doc_id}) completed parsing in background (DONE).")
        return True, "", curr_doc

    if curr_status == "RUNNING":
        has_prog, reason = check_document_progress(curr_doc, doc_state)
        if has_prog:
            logger.info(f"Document '{doc_name}' is RUNNING and made background progress: {reason}. Resuming polling...")
            success, _status, _msg, latest_doc = poll_single_document_status(
                context=context,
                dataset_id=dataset_id,
                doc_id=doc_id,
                doc_name=doc_name,
                poll_interval=poll_interval,
                max_timeout=doc_timeout,
                initial_doc=curr_doc,
            )
            if success:
                return True, "", latest_doc
            curr_doc = latest_doc
            logger.warning(f"Document '{doc_name}' stalled while polling. Proceeding to trigger attempt 2...")

    logger.info(f"--> [Retry {idx}/{retry_count}] Triggering parse request for document '{doc_name}' (ID: {doc_id})...")
    return parse_single_doc_attempt(
        context=context,
        dataset_id=dataset_id,
        doc=curr_doc,
        attempt_num=2,
        poll_interval=poll_interval,
        doc_timeout=doc_timeout,
    )


def parse_documents_sequentially(
    context: PipelineContext,
    dataset_id: str,
    poll_interval: float = 10.0,
    doc_timeout: float = 600.0,
) -> None:
    """
    Parse documents sequentially one by one with progress-resetting timeout and Phase 2 retry.

    Phase 1 (Attempt 1):
        Parses all unparsed documents one by one. Resets timeout when progress is made.
        If no progress is made for doc_timeout seconds, logs error and continues to the next file.

    Phase 2 (Attempt 2 - Retry):
        Checks status of failed/timed-out files before sending new parsing requests.
        Attempts retry for all uncompleted files, then hard fails if any file still failed.
    """
    logger.info(f"Initiating sequential document parsing for dataset '{dataset_id}'...")
    all_docs = fetch_documents_status(context, dataset_id)
    if not all_docs:
        logger.info(f"No documents found for dataset '{dataset_id}'. Parsing complete.")
        return

    # Filter documents that need parsing (not yet DONE)
    docs_to_parse = [d for d in all_docs if str(d.get("run", "")).upper() != "DONE"]
    total = len(docs_to_parse)

    if total == 0:
        logger.info(f"All {len(all_docs)} document(s) in dataset '{dataset_id}' are already parsed (DONE).")
        return

    logger.info(f"Found {total} document(s) to parse sequentially (poll interval: {poll_interval}s)...")

    # ==================== Phase 1: First Attempt ====================
    failed_attempt_1: list[tuple[dict[str, Any], str]] = []
    for idx, doc in enumerate(docs_to_parse, start=1):
        doc_id = str(doc.get("id", ""))
        doc_name = str(doc.get("name", doc_id))
        logger.info(f"--> Parsing document [{idx}/{total}]: '{doc_name}' (ID: {doc_id})...")

        success, reason, latest_doc = parse_single_doc_attempt(
            context=context,
            dataset_id=dataset_id,
            doc=doc,
            attempt_num=1,
            poll_interval=poll_interval,
            doc_timeout=doc_timeout,
        )

        if not success:
            logger.error(
                f"Document '{doc_name}' (ID: {doc_id}) failed parsing on attempt 1: {reason}. "
                "Continuing with remaining files..."
            )
            failed_attempt_1.append((latest_doc, reason))

    # ==================== Phase 2: Retry Failed Documents ====================
    if not failed_attempt_1:
        logger.info(
            f"========== Document Parsing Report for Dataset '{dataset_id}' ==========\n"
            f"All {total} documents parsed successfully on first attempt (DONE)."
        )
        return

    retry_count = len(failed_attempt_1)
    logger.warning(
        f"Attempt 1 finished. {retry_count}/{total} document(s) failed or timed out. "
        "Checking status and starting second attempt for failed files..."
    )

    failed_attempt_2: list[tuple[dict[str, Any], str]] = []
    for idx, (doc_state, _prev_reason) in enumerate(failed_attempt_1, start=1):
        doc_id = str(doc_state.get("id", ""))
        doc_name = str(doc_state.get("name", doc_id))

        success, reason, latest_doc = handle_doc_second_attempt(
            context=context,
            dataset_id=dataset_id,
            doc_state=doc_state,
            idx=idx,
            retry_count=retry_count,
            poll_interval=poll_interval,
            doc_timeout=doc_timeout,
        )

        if not success:
            logger.error(
                f"[RETRY FAILED] Document '{doc_name}' (ID: {doc_id}) failed parsing on second attempt: {reason}."
            )
            failed_attempt_2.append((latest_doc, reason))

    # ==================== Hard Failure Check ====================
    if failed_attempt_2:
        err_lines = [
            f"  - Document '{d.get('name', d.get('id'))}' (ID: {d.get('id')}): {r}" for d, r in failed_attempt_2
        ]
        err_report = "\n".join(err_lines)
        logger.error(
            f"========== Document Parsing Hard Failure for Dataset '{dataset_id}' ==========\n"
            f"{len(failed_attempt_2)}/{total} document(s) failed parsing after 2 attempts:\n{err_report}"
        )
        raise BrunoPopulatorError(
            f"Document parsing failed on second attempt for {len(failed_attempt_2)} document(s) in dataset '{dataset_id}':\n{err_report}"
        )

    logger.info(
        f"========== Document Parsing Report for Dataset '{dataset_id}' ==========\n"
        f"All {total} documents parsed successfully ({retry_count} succeeded on retry)."
    )


class CreateDatasetStep(BaseCollectionStep):
    """Collection step for creating RAGFlow Datasets."""

    @property
    def name(self) -> str:
        return "RAGFlow Create Dataset"

    def preprocess(self, context: PipelineContext, item: Any | None = None) -> None:
        """Preprocessing hook for dataset creation: attaches source document files to Upload Documents.yml."""
        logger.info(f"Preprocessing Bruno request files for '{self.name}'...")

        sources_dir = context.sources_dir
        if not sources_dir.exists():
            raise FileNotFoundError(f"Source documents directory not found: {sources_dir}")

        source_files = sorted([p for p in sources_dir.iterdir() if p.is_file()])
        if not source_files:
            raise BrunoPopulatorError(
                f"No source files found in sources directory '{sources_dir}' for step '{self.name}'."
            )

        upload_yml = self.collection_dir / "Upload Documents.yml"
        if not upload_yml.exists():
            raise FileNotFoundError(f"Bruno request file not found: {upload_yml}")

        update_multipart_files_in_yml(upload_yml, source_files)

    def verify_result(
        self,
        context: PipelineContext,
        result_data: dict[str, Any] | list[Any] | None,
        item: Any | None = None,
    ) -> None:
        """Verify dataset ID, chunk_method, and document uploads in Bruno JSON output report."""
        request_entries = self.verify_bruno_collection_results(result_data)

        # 1. Validate Request #1 (Create Dataset)
        dataset_id = self.extract_value_by_key_path(request_entries[0], "response.data.data.id")
        if not dataset_id:
            raise BrunoPopulatorError(f"Failed to extract created dataset ID from Request #1 for '{self.name}'.")

        chunk_method = self.extract_value_by_key_path(request_entries[0], "response.data.data.chunk_method")
        if chunk_method and chunk_method != "naive":
            raise BrunoPopulatorError(
                f"Unexpected chunk_method '{chunk_method}' for dataset in '{self.name}'. Expected 'naive'."
            )

        # 2. Validate Upload Documents request
        upload_entry = None
        for entry in request_entries:
            filename = self.extract_value_by_key_path(entry, "test.filename") or entry.get("name")
            if filename and "Upload Documents" in str(filename):
                upload_entry = entry
                break

        if upload_entry:
            uploaded_docs = self.extract_value_by_key_path(upload_entry, "response.data.data")
            if isinstance(uploaded_docs, list) and uploaded_docs:
                for doc in uploaded_docs:
                    if isinstance(doc, dict):
                        if not doc.get("id"):
                            raise BrunoPopulatorError(
                                f"Uploaded document object missing 'id' in Upload Documents request for '{self.name}'."
                            )
                        if doc.get("size") is not None and doc.get("size", 0) <= 0:
                            raise BrunoPopulatorError(
                                f"Uploaded document '{doc.get('name')}' has invalid file size ({doc.get('size')}) in '{self.name}'."
                            )

    def set_context(
        self,
        context: PipelineContext,
        result_data: dict[str, Any] | list[Any] | None,
        item: Any | None = None,
    ) -> None:
        """Extract dataset ID, update PipelineContext, and run sequential document parsing."""
        dataset_id = self.extract_value_by_key_path(result_data, "[0].results[0].response.data.data.id")
        dataset_id_str = str(dataset_id)
        logger.info(f"Extracted Dataset ID: '{dataset_id_str}' for '{self.name}'.")

        context.set_data("dataset_id", dataset_id_str)
        self.parse_documents_sequentially(context, dataset_id_str)

    def parse_documents_sequentially(
        self,
        context: PipelineContext,
        dataset_id: str,
        poll_interval: float = 10.0,
        doc_timeout: float = 600.0,
    ) -> None:
        """Delegate sequential parsing to standalone function."""
        parse_documents_sequentially(
            context=context,
            dataset_id=dataset_id,
            poll_interval=poll_interval,
            doc_timeout=doc_timeout,
        )
