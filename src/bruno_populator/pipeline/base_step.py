"""Abstract Base Class interface for Bruno collection steps with payload helper static methods."""

import json
import shutil
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from bruno_populator.exceptions import BrunoPopulatorError
from bruno_populator.pipeline.context import PipelineContext
from paths import BRUNO_DIR


class BaseCollectionStep(ABC):
    """
    Abstract interface for individual Bruno collection steps.

    Lifecycle: preprocess -> execute (run_bruno_collection) -> postprocess
    """

    def __init__(
        self,
        collection_dir: Path | str | None = None,
        skip_preprocess: bool = False,
        skip_run: bool = False,
        skip_postprocess: bool = False,
    ):
        """
        Initialize base collection step.

        1. Resolves collection_dir (defaults to BRUNO_DIR / self.name).
        2. Automatically creates collection_dir folder if it doesn't exist.
        3. Copies reference `opencollection.yml` into collection_dir if present in BRUNO_DIR / self.name.
        """
        col_path = Path(collection_dir).resolve() if collection_dir else (BRUNO_DIR / self.name).resolve()
        col_path.mkdir(parents=True, exist_ok=True)
        if not col_path.is_dir():
            raise NotADirectoryError(f"Bruno collection path is not a directory: {col_path}")

        self._collection_dir = col_path
        self._skip_preprocess = skip_preprocess
        self._skip_run = skip_run
        self._skip_postprocess = skip_postprocess

        # Auto-copy reference opencollection.yml if available
        self.ensure_opencollection_yml()

    def ensure_opencollection_yml(self) -> None:
        """Copy reference opencollection.yml into collection_dir if present in reference folder."""
        ref_opencol = (BRUNO_DIR / self.name / "opencollection.yml").resolve()
        target_opencol = self._collection_dir / "opencollection.yml"
        if ref_opencol.exists() and not target_opencol.exists():
            shutil.copy2(ref_opencol, target_opencol)

    def inject_collection_token(self, token: str) -> None:
        """Inject API Bearer token into this step's collection opencollection.yml."""
        from bruno_populator.yml_injector import inject_collection_token

        inject_collection_token(self.collection_dir, token)

    def clear_collection_token(self) -> None:
        """Reset API Bearer token in this step's collection opencollection.yml to empty string."""
        from bruno_populator.yml_injector import clear_collection_token

        clear_collection_token(self.collection_dir)

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable step name."""
        pass

    @property
    def collection_dir(self) -> Path:
        """Directory containing the Bruno collection to execute."""
        return self._collection_dir

    @property
    def exclude_tags(self) -> list[str]:
        """Tags to exclude during Bruno collection execution."""
        return ["delete"]

    @property
    def env(self) -> str | None:
        """Environment name for Bruno CLI execution."""
        return None

    @property
    def skip_preprocess(self) -> bool:
        """Flag to skip preprocessing phase for this step."""
        return getattr(self, "_skip_preprocess", False)

    @property
    def skip_run(self) -> bool:
        """Flag to skip Bruno CLI execution phase (`bru run`) for this step."""
        return getattr(self, "_skip_run", False)

    @property
    def skip_postprocess(self) -> bool:
        """Flag to skip postprocessing phase for this step."""
        return getattr(self, "_skip_postprocess", False)

    def get_item_key(self, item: Any) -> str:
        """
        Return a unique string identifier key for an item used in item-based step iteration.

        Must be overridden by step subclasses that utilize item iteration.
        """
        raise NotImplementedError(
            f"Step '{self.name}' utilizes item iteration but has not overridden get_item_key(item)."
        )

    def get_items(self, context: PipelineContext) -> list[Any] | None:
        """
        Optional hook: Retrieve list of items to iterate over during step execution.

        Returns None by default for single-execution steps.
        """
        return None

    @abstractmethod
    def preprocess(self, context: PipelineContext, item: Any | None = None) -> None:
        """
        Preprocessing hook: Update/generate Bruno collection YML request files
        before collection execution (optionally for a specific item).
        """
        pass

    def postprocess(
        self,
        context: PipelineContext,
        result_data: dict[str, Any] | list[Any] | None,
        item: Any | None = None,
    ) -> None:
        """
        Postprocessing lifecycle: Verifies Bruno output JSON report then sets context.
        """
        self.verify_result(context, result_data, item=item)
        self.set_context(context, result_data, item=item)

    @abstractmethod
    def verify_result(
        self,
        context: PipelineContext,
        result_data: dict[str, Any] | list[Any] | None,
        item: Any | None = None,
    ) -> None:
        """Verify Bruno execution report payload. Must be overridden by step subclass."""
        raise NotImplementedError(f"Step '{self.name}' must implement verify_result(context, result_data, item).")

    @abstractmethod
    def set_context(
        self,
        context: PipelineContext,
        result_data: dict[str, Any] | list[Any] | None,
        item: Any | None = None,
    ) -> None:
        """Extract output IDs/data and update PipelineContext. Must be overridden by step subclass."""
        raise NotImplementedError(f"Step '{self.name}' must implement set_context(context, result_data, item).")

    def verify_bruno_collection_results(
        self,
        result_data: dict[str, Any] | list[Any] | None,
        expected_request_count: int | None = None,
    ) -> list[dict[str, Any]]:
        """
        Generic verification helper for Bruno execution report payloads.

        Verifies:
        1. Non-empty result_data payload.
        2. Expected request count (if provided).
        3. For every request entry:
           - Bruno execution status is 'pass' and 'error' is None.
           - HTTP response status is 200 (OK).
           - RAGFlow API envelope code == 0 (if JSON response).
           - RAGFlow API response data field is non-null.

        Returns flattened list of request execution dictionaries.
        """
        if not result_data:
            raise BrunoPopulatorError(f"No result data report found for step '{self.name}'.")

        # Flatten request results list across dictionary or iteration list structures
        request_entries: list[dict[str, Any]] = []
        if isinstance(result_data, dict) and "results" in result_data:
            request_entries = result_data["results"]
        elif isinstance(result_data, list):
            for entry in result_data:
                if isinstance(entry, dict) and "results" in entry:
                    request_entries.extend(entry["results"])
                elif isinstance(entry, dict):
                    request_entries.append(entry)

        if not request_entries:
            raise BrunoPopulatorError(f"No request execution entries found in Bruno report for step '{self.name}'.")

        if expected_request_count is not None and len(request_entries) != expected_request_count:
            raise BrunoPopulatorError(
                f"Expected {expected_request_count} request execution(s) in Bruno report for step '{self.name}', "
                f"but found {len(request_entries)}."
            )

        for idx, req_entry in enumerate(request_entries, start=1):
            req_name = req_entry.get("test", {}).get("filename") or req_entry.get("name") or f"Request #{idx}"

            # 1. Bruno execution status check
            bruno_status = str(req_entry.get("status", "")).lower()
            bruno_error = req_entry.get("error")
            if (bruno_status and bruno_status != "pass") or bruno_error:
                err_msg = bruno_error or f"Bruno execution status: '{bruno_status}'"
                raise BrunoPopulatorError(f"Bruno request '{req_name}' failed in step '{self.name}': {err_msg}")

            # 2. Response object checks
            response = req_entry.get("response")
            if isinstance(response, dict):
                http_status = response.get("status")
                if http_status is not None and http_status != 200:
                    status_text = response.get("statusText", "Unknown Error")
                    raise BrunoPopulatorError(
                        f"HTTP request '{req_name}' failed with status {http_status} ({status_text}) in step '{self.name}'."
                    )

                # 3. RAGFlow API JSON envelope check
                resp_data = response.get("data")
                if isinstance(resp_data, dict) and "code" in resp_data:
                    api_code = resp_data.get("code")
                    api_msg = resp_data.get("message", "")
                    if api_code != 0:
                        raise BrunoPopulatorError(
                            f"RAGFlow API error in request '{req_name}' for step '{self.name}': code={api_code}, message='{api_msg}'."
                        )

        return request_entries

    @staticmethod
    def load_script_file(script_path: Path) -> str:
        """
        Read JavaScript script file (e.g. before-request or after-response) as a string.

        Raises FileNotFoundError if the script file does not exist.
        """
        resolved_path = script_path.resolve()
        if not resolved_path.exists():
            raise FileNotFoundError(f"Script JS file not found: {resolved_path}")
        return resolved_path.read_text(encoding="utf-8").replace("\r\n", "\n").strip()

    @classmethod
    def attach_script_if_exists(
        cls,
        builder: Any,
        script_path: Path,
        type_: Any,
    ) -> Any:
        """Attach JS script file to builder if script_path exists."""
        if script_path.exists():
            script_code = cls.load_script_file(script_path)
            builder.set_script(type_, script_code)
        return builder

    @classmethod
    def auto_attach_step_scripts(
        cls,
        builder: Any,
        step_dir: Path,
        prefix: str | None = None,
    ) -> Any:
        """
        Automatically discover and attach after-response and before-request scripts
        from step_dir. Checks `<prefix>_after.js`, `<step_dir.name>_after.js`, `after.js`, `after-response.js`.
        """
        prefixes = [prefix] if prefix else []
        prefixes.extend([step_dir.name, ""])

        # Check after-response scripts
        for p in prefixes:
            p_str = f"{p}_" if p else ""
            for name in (f"{p_str}after.js", f"{p_str}after-response.js"):
                candidate = step_dir / name
                if candidate.exists():
                    cls.attach_script_if_exists(builder, candidate, "after-response")
                    break

        # Check before-request scripts
        for p in prefixes:
            p_str = f"{p}_" if p else ""
            for name in (f"{p_str}before.js", f"{p_str}before-request.js"):
                candidate = step_dir / name
                if candidate.exists():
                    cls.attach_script_if_exists(builder, candidate, "before-request")
                    break

        return builder

    @staticmethod
    def load_markdown_prompt(prompt_path: Path) -> str:
        """
        Read markdown system prompt file as a string.

        Raises FileNotFoundError if the prompt file does not exist.
        """
        resolved_path = prompt_path.resolve()
        if not resolved_path.exists():
            raise FileNotFoundError(f"System prompt markdown file not found: {resolved_path}")
        return resolved_path.read_text(encoding="utf-8").replace("\r\n", "\n").strip()

    @staticmethod
    def inject_prompt_into_payload(
        payload: dict[str, Any],
        key_path: str,
        prompt_text: str,
    ) -> dict[str, Any]:
        """
        Inject markdown prompt text into a dictionary payload at a dot-separated key path.

        Raises KeyError if any key along key_path is missing.
        """
        keys = key_path.split(".")
        current = payload
        for k in keys[:-1]:
            if not isinstance(current, dict) or k not in current:
                raise KeyError(f"Key '{k}' in path '{key_path}' not found in payload dictionary.")
            current = current[k]

        last_key = keys[-1]
        if not isinstance(current, dict) or last_key not in current:
            raise KeyError(f"Target key '{last_key}' in path '{key_path}' not found in payload dictionary.")

        current[last_key] = prompt_text
        return payload

    @staticmethod
    def extract_value_by_key_path(data: Any, key_path: str) -> Any:
        """
        Navigate nested dictionary/list structures using a string key path.

        Supports notation like:
        - `"[0].results[2].response.data.data.answer"`
        - `"results.2.response.data.data.answer"`
        - `"results[2].response.data.id"`

        Returns None if key_path does not exist or structure mismatch occurs.
        """
        if data is None or not key_path:
            return None

        import re

        normalized = re.sub(r"\[(\d+)\]", r".\1", key_path)
        tokens = [t for t in normalized.split(".") if t]

        curr = data
        for token in tokens:
            if isinstance(curr, list):
                try:
                    idx = int(token)
                    curr = curr[idx]
                except (ValueError, IndexError):
                    return None
            elif isinstance(curr, dict):
                if token in curr:
                    curr = curr[token]
                else:
                    return None
            else:
                return None

        return curr

    @classmethod
    def load_payload_with_prompt(
        cls,
        json_path: Path,
        prompt_path: Path,
        key_path: str,
    ) -> dict[str, Any]:
        """
        Load payload.json and inject markdown prompt file content at target key_path.

        Fails fast with explicit FileNotFoundError or KeyError if files/keys are missing.
        """
        resolved_json = json_path.resolve()
        if not resolved_json.exists():
            raise FileNotFoundError(f"JSON payload file not found: {resolved_json}")

        with open(resolved_json, encoding="utf-8") as f:
            payload = json.load(f)

        prompt_text = cls.load_markdown_prompt(prompt_path)
        return cls.inject_prompt_into_payload(payload, key_path, prompt_text)

    def create_request(
        self,
        name: str,
        seq: int,
        method: Any = "POST",
        url: str = "",
        step_dir: Path | None = None,
        context: PipelineContext | None = None,
        prompt_path: Path | None = None,
        prompt_key_path: str | None = None,
        headers: list[dict[str, str]] | None = None,
        multipart_files: list[str | Path] | None = None,
    ) -> Any:
        """
        Build and save a Bruno request YML file automatically discovering assets matching `name`.

        Workflow:
        1. Initialize BrunoRequestBuilder with request metadata (name, method, url, seq, base_url).
        2. Set custom headers if explicitly provided.
        3. Load and bind body payload from `<name>.json` (with optional prompt injection or multipart upload).
        4. Auto-attach `<name>_after.js` and `<name>_before.js` scripts if present in `step_dir`.
        5. Save generated request YML file to `self.collection_dir / f"{name}.yml"`.
        """
        from bruno_populator.request_builder import BrunoRequestBuilder

        base_url = context.base_url if context else "http://localhost:9222"
        builder = BrunoRequestBuilder(
            name=name,
            method=method,
            url=url,
            seq=seq,
            base_url=base_url,
        )

        # Step 1: Set custom headers if explicitly provided
        if headers:
            for h in headers:
                builder.add_header(h["name"], h["value"])

        # Step 2: Configure request payload from <name>.json asset file
        if multipart_files:
            builder.set_multipart_files(multipart_files)
        elif step_dir:
            json_path = (step_dir / f"{name}.json").resolve()
            if json_path.exists():
                if prompt_path and prompt_key_path:
                    payload = self.load_payload_with_prompt(
                        json_path=json_path,
                        prompt_path=prompt_path,
                        key_path=prompt_key_path,
                    )
                    builder.set_json_body(payload)
                else:
                    raw_text = json_path.read_text(encoding="utf-8").replace("\r\n", "\n").strip()
                    payload = json.loads(raw_text)

                    if isinstance(payload, dict) and "files" in payload and isinstance(payload["files"], list):
                        builder.set_multipart_files(payload["files"])
                    else:
                        builder.set_json_body(raw_text)

        # Step 3: Auto-attach JavaScript scripts matching request name
        if step_dir:
            after_script = (step_dir / f"{name}_after.js").resolve()
            self.attach_script_if_exists(builder, after_script, "after-response")

            before_script = (step_dir / f"{name}_before.js").resolve()
            self.attach_script_if_exists(builder, before_script, "before-request")

        # Step 4: Save generated request YML file
        yml_path = self.collection_dir / f"{name}.yml"
        builder.save(yml_path)
        return builder
