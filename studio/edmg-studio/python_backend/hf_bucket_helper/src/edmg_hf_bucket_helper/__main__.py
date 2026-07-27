from __future__ import annotations

import dataclasses
import importlib.metadata
import json
import os
import sys
from collections.abc import Mapping
from datetime import date, datetime
from pathlib import Path
from typing import Any

from huggingface_hub import HfApi
from huggingface_hub import __version__ as huggingface_hub_version

from edmg_hf_bucket_helper import CONTRACT_VERSION, HELPER_VERSION

MAX_REQUEST_BYTES = 1024 * 1024
SUPPORTED_OPERATIONS = (
    "capabilities",
    "bucket_info",
    "list",
    "paths_info",
    "download",
    "upload",
    "sync",
)


class ContractError(ValueError):
    """Raised when a caller sends an invalid helper request."""


def _required_string(request: Mapping[str, Any], key: str) -> str:
    value = request.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ContractError(f"{key} must be a non-empty string")
    return value.strip()


def _optional_string(request: Mapping[str, Any], key: str) -> str:
    value = request.get(key, "")
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ContractError(f"{key} must be a string")
    return value.strip()


def _token_from_environment(environment: Mapping[str, str]) -> str:
    return str(environment.get("HF_TOKEN") or environment.get("EDMG_HF_TOKEN") or "").strip()


def _serialize(value: Any) -> Any:
    if dataclasses.is_dataclass(value):
        return {field.name: _serialize(getattr(value, field.name)) for field in dataclasses.fields(value)}
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): _serialize(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_serialize(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _bucket_uri(bucket: str, remote_path: str = "") -> str:
    normalized = remote_path.strip().strip("/").replace("\\", "/")
    base = f"hf://buckets/{bucket.strip().strip('/')}"
    return f"{base}/{normalized}" if normalized else base


def _capabilities() -> dict[str, Any]:
    try:
        hf_xet_version = importlib.metadata.version("hf-xet")
    except importlib.metadata.PackageNotFoundError:
        hf_xet_version = None
    return {
        "contract_version": CONTRACT_VERSION,
        "helper_version": HELPER_VERSION,
        "huggingface_hub_version": huggingface_hub_version,
        "hf_xet_version": hf_xet_version,
        "operations": list(SUPPORTED_OPERATIONS),
    }


def execute(
    request: Mapping[str, Any],
    *,
    api: HfApi | Any | None = None,
    environment: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Execute one JSON request.

    Authentication is intentionally accepted only through the process
    environment. This keeps access tokens out of argv, the JSON protocol, and
    normal error output.
    """

    if not isinstance(request, Mapping):
        raise ContractError("request must be a JSON object")
    if "token" in request:
        raise ContractError("token must be supplied through HF_TOKEN, never in the request")
    version = request.get("contract_version", CONTRACT_VERSION)
    if version != CONTRACT_VERSION:
        raise ContractError(
            f"unsupported contract_version {version!r}; expected {CONTRACT_VERSION}"
        )
    operation = _required_string(request, "operation")
    if operation not in SUPPORTED_OPERATIONS:
        raise ContractError(f"unsupported operation: {operation}")
    if operation == "capabilities":
        return _capabilities()

    env = os.environ if environment is None else environment
    token = _token_from_environment(env)
    auth_token: str | bool = token if token else False
    client = api if api is not None else HfApi(token=auth_token)

    bucket = _required_string(request, "bucket").strip().strip("/")
    if operation == "bucket_info":
        return {"bucket": _serialize(client.bucket_info(bucket, token=auth_token))}

    if operation == "list":
        prefix = _optional_string(request, "prefix").strip().strip("/").replace("\\", "/")
        recursive = request.get("recursive", False)
        if not isinstance(recursive, bool):
            raise ContractError("recursive must be a boolean")
        entries = client.list_bucket_tree(
            bucket,
            prefix=prefix or None,
            recursive=recursive,
            token=auth_token,
        )
        return {"entries": [_serialize(entry) for entry in entries]}

    if operation == "paths_info":
        paths = request.get("paths")
        if not isinstance(paths, list) or not paths or not all(
            isinstance(path, str) and path.strip() for path in paths
        ):
            raise ContractError("paths must be a non-empty array of strings")
        entries = client.get_bucket_paths_info(bucket, paths, token=auth_token)
        return {"entries": [_serialize(entry) for entry in entries]}

    if operation == "download":
        remote_path = _required_string(request, "remote_path").strip().strip("/").replace("\\", "/")
        local_path = Path(_required_string(request, "local_path")).expanduser()
        local_path.parent.mkdir(parents=True, exist_ok=True)
        client.download_bucket_files(
            bucket,
            [(remote_path, str(local_path))],
            raise_on_missing_files=True,
            token=auth_token,
        )
        return {"remote_path": remote_path, "local_path": str(local_path), "exists": local_path.is_file()}

    if operation == "upload":
        local_path = Path(_required_string(request, "local_path")).expanduser()
        if not local_path.is_file():
            raise ContractError(f"upload source is not a file: {local_path}")
        remote_path = _required_string(request, "remote_path").strip().strip("/").replace("\\", "/")
        client.batch_bucket_files(
            bucket,
            add=[(str(local_path), remote_path)],
            token=auth_token,
        )
        return {"remote_path": remote_path, "local_path": str(local_path)}

    source = _required_string(request, "source")
    dest = _required_string(request, "dest")
    source_is_bucket = source.startswith("hf://buckets/")
    dest_is_bucket = dest.startswith("hf://buckets/")
    if source_is_bucket == dest_is_bucket:
        raise ContractError("sync requires exactly one local path and one hf://buckets/ path")
    include = request.get("include", [])
    if not isinstance(include, list) or not all(
        isinstance(pattern, str) and pattern.strip() for pattern in include
    ):
        raise ContractError("include must be an array of non-empty glob strings")
    exclude = request.get("exclude", [])
    if not isinstance(exclude, list) or not all(
        isinstance(pattern, str) and pattern.strip() for pattern in exclude
    ):
        raise ContractError("exclude must be an array of non-empty glob strings")
    client.sync_bucket(
        source=source,
        dest=dest,
        delete=False,
        include=include or None,
        exclude=exclude or None,
        quiet=True,
        token=auth_token,
    )
    return {"source": source, "dest": dest, "include": include, "exclude": exclude}


def _redact(message: str, token: str) -> str:
    sanitized = str(message or "").strip()
    if token:
        sanitized = sanitized.replace(token, "[REDACTED]")
    return sanitized[:4000] or "Hugging Face bucket helper failed"


def _response(payload: dict[str, Any], *, ok: bool) -> str:
    return json.dumps(
        {
            "contract_version": CONTRACT_VERSION,
            "ok": ok,
            **payload,
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )


def main() -> int:
    token = _token_from_environment(os.environ)
    try:
        raw = sys.stdin.read(MAX_REQUEST_BYTES + 1)
        if len(raw.encode("utf-8")) > MAX_REQUEST_BYTES:
            raise ContractError("request exceeds 1 MiB")
        request = json.loads(raw)
        result = execute(request)
        sys.stdout.write(_response({"result": result}, ok=True) + "\n")
        return 0
    except Exception as exc:
        sys.stdout.write(
            _response(
                {
                    "error": {
                        "type": type(exc).__name__,
                        "message": _redact(str(exc), token),
                    }
                },
                ok=False,
            )
            + "\n"
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
