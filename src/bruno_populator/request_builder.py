"""Bruno YML request file builder with sensible defaults for HTTP/JSON payloads."""

import json
from pathlib import Path
from typing import Any, Literal

import yaml

from bruno_populator.exceptions import YamlGenerationError
from bruno_populator.logger import get_logger

logger = get_logger("bruno_populator.request_builder")

HttpMethod = Literal["GET", "POST", "PUT", "DELETE", "PATCH"]
BodyType = Literal["json", "multipart-form", "none"]


class LiteralStr(str):
    """String subclass to force PyYAML literal block scalar representation (data: |-)."""

    pass


class BrunoYamlDumper(yaml.SafeDumper):
    """Custom PyYAML SafeDumper for Bruno YAML generation."""

    def increase_indent(self, flow=False, indentless=False):
        return super().increase_indent(flow=flow, indentless=False)


def _literal_str_representer(dumper: yaml.SafeDumper, data: str) -> yaml.Node:
    return dumper.represent_scalar("tag:yaml.org,2002:str", data, style="|")


BrunoYamlDumper.add_representer(LiteralStr, _literal_str_representer)


class BrunoRequestBuilder:
    """Builder for constructing Bruno HTTP request YAML files."""

    def __init__(
        self,
        name: str,
        method: HttpMethod = "POST",
        url: str = "",
        seq: int = 1,
        base_url: str = "http://localhost:9222",
    ):
        self.name = name
        self.method = method
        self.url = url if url.startswith("http") else f"{base_url.rstrip('/')}{url}"
        self.seq = seq
        self.headers: list[dict[str, str]] = []
        self.body_type: BodyType = "none"
        self.body_data: Any = None
        self.auth: str = "inherit"
        self.scripts: list[dict[str, Any]] = []
        self.settings: dict[str, Any] = {
            "encodeUrl": True,
            "timeout": 0,
            "followRedirects": True,
            "maxRedirects": 5,
        }

    def set_json_body(self, payload: dict[str, Any] | str) -> "BrunoRequestBuilder":
        """Configure request to send a JSON body payload as a block scalar."""
        self.body_type = "json"
        if isinstance(payload, str):
            self.body_data = LiteralStr(payload)
        else:
            raw_json = json.dumps(payload, indent=2, ensure_ascii=False)
            self.body_data = LiteralStr(raw_json)
        return self

    def set_multipart_files(self, file_paths: list[str | Path]) -> "BrunoRequestBuilder":
        """Configure request to send multipart-form file uploads."""
        self.body_type = "multipart-form"
        self.body_data = [{"name": "file", "type": "file", "value": [str(Path(p).resolve())]} for p in file_paths]
        self.add_header("Content-Type", "multipart/form-data")
        return self

    def add_header(self, name: str, value: str) -> "BrunoRequestBuilder":
        """Add or update an HTTP header."""
        for h in self.headers:
            if h["name"].lower() == name.lower():
                h["value"] = value
                return self
        self.headers.append({"name": name, "value": value})
        return self

    def set_script(self, type_: Literal["before-request", "after-response"], code: str) -> "BrunoRequestBuilder":
        """Add a before-request or after-response JavaScript script block."""
        raw_code = code.replace("\r\n", "\n").strip()
        clean_code = LiteralStr(raw_code) if "\n" in raw_code else raw_code
        for s in self.scripts:
            if s["type"] == type_:
                s["code"] = clean_code
                return self
        self.scripts.append({"type": type_, "code": clean_code})
        return self

    def build_dict(self) -> dict[str, Any]:
        """Construct dictionary matching Bruno's HTTP YAML schema."""
        http_block: dict[str, Any] = {
            "method": self.method,
            "url": self.url,
        }

        if self.headers:
            http_block["headers"] = self.headers

        if self.body_type != "none":
            http_block["body"] = {
                "type": self.body_type,
                "data": self.body_data,
            }

        http_block["auth"] = self.auth

        result_dict: dict[str, Any] = {
            "info": {
                "name": self.name,
                "type": "http",
                "seq": self.seq,
            },
            "http": http_block,
        }

        if self.scripts:
            result_dict["runtime"] = {"scripts": self.scripts}

        result_dict["settings"] = self.settings
        return result_dict

    def save(self, output_path: Path) -> Path:
        """Write Bruno request YAML file to output_path."""
        out_file = output_path.resolve()
        out_file.parent.mkdir(parents=True, exist_ok=True)
        data = self.build_dict()

        logger.debug(f"Building Bruno YAML request '{self.name}' -> {out_file}")
        try:
            raw_yaml = yaml.dump(
                data,
                Dumper=BrunoYamlDumper,
                sort_keys=False,
                default_flow_style=False,
                allow_unicode=True,
                width=10000,
            )
            # Add blank lines between top-level sections (info, http, settings) to match Bruno format
            if "\nhttp:\n" in raw_yaml:
                raw_yaml = raw_yaml.replace("\nhttp:\n", "\n\nhttp:\n")
            if "\nruntime:\n" in raw_yaml:
                raw_yaml = raw_yaml.replace("\nruntime:\n", "\n\nruntime:\n")
            if "\nsettings:\n" in raw_yaml:
                raw_yaml = raw_yaml.replace("\nsettings:\n", "\n\nsettings:\n")

            with open(out_file, "w", encoding="utf-8") as f:
                f.write(raw_yaml)
        except Exception as exc:
            logger.error(f"Failed writing Bruno YAML request file {out_file}: {exc}")
            raise YamlGenerationError(f"Failed writing Bruno request file {out_file}: {exc}") from exc

        logger.info(f"Saved Bruno request '{self.name}' at {out_file}")
        return out_file
