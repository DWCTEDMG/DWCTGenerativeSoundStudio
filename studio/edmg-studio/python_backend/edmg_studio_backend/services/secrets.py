from __future__ import annotations

import base64
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SERVICE_NAME = "dwct-edmg-studio"
_TRUTHY = {"1", "true", "yes", "on"}
_DEV_ENVIRONMENTS = {"dev", "development", "test", "testing"}


def _restrict_permissions(path: Path, mode: int) -> None:
    try:
        if os.name != "nt":
            os.chmod(path, mode)
    except Exception:
        pass


def _config_dir(data_dir: Path) -> Path:
    path = (data_dir / "config").resolve()
    path.mkdir(parents=True, exist_ok=True)
    _restrict_permissions(path, 0o700)
    return path


def _read_json(path: Path, default: Any) -> Any:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default
    return default


def _write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    _restrict_permissions(path.parent, 0o700)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2, ensure_ascii=False), encoding="utf-8")
    _restrict_permissions(tmp, 0o600)
    tmp.replace(path)
    _restrict_permissions(path, 0o600)


def _b64e(value: str) -> str:
    return base64.b64encode(value.encode("utf-8")).decode("ascii")


def _b64d(value: str) -> str:
    return base64.b64decode(value.encode("ascii")).decode("utf-8")


@dataclass
class SecretsStatus:
    store: str
    available: bool
    has_hf_token: bool
    has_civitai_api_key: bool
    has_openai_compat_api_key: bool
    has_stability_api_key: bool
    has_nvidia_api_key: bool = False
    migration_status: str = "not_needed"
    legacy_file_present: bool = False
    note: str | None = None


class SecretStore:
    """Store credentials in the OS keyring, with an explicit dev-only file mode."""

    def __init__(self, data_dir: Path, *, keyring_backend: Any | None = None):
        self.data_dir = data_dir
        self._file_path = _config_dir(data_dir) / "secrets.json"
        self._forced = os.getenv("EDMG_SECRETS_STORE", "auto").strip().lower()
        self._environment = os.getenv("EDMG_ENVIRONMENT", "production").strip().lower()
        consent = os.getenv("EDMG_SECRETS_ALLOW_FILE", "").strip().lower() in _TRUTHY
        self._file_allowed = consent and self._environment in _DEV_ENVIRONMENTS
        self._keyring = None
        self._keyring_ok = False
        self._note: str | None = None
        self._migration_status = "pending" if self._file_path.exists() else "not_needed"

        if self._forced not in {"auto", "keyring", "file", "plaintext"}:
            self._note = f"Unsupported EDMG_SECRETS_STORE mode: {self._forced}"
            return
        if self._forced in {"file", "plaintext"}:
            if self._file_allowed:
                self._note = "Development-only file secret storage is explicitly enabled."
            else:
                self._note = (
                    "File secret storage is disabled. Set EDMG_ENVIRONMENT=development and "
                    "EDMG_SECRETS_ALLOW_FILE=1 only for local development."
                )
            return

        try:
            if keyring_backend is None:
                import keyring  # type: ignore

                keyring_backend = keyring
            keyring_backend.get_password(SERVICE_NAME, "__edmg_keyring_probe__")
            self._keyring = keyring_backend
            self._keyring_ok = True
        except Exception as exc:
            self._note = f"OS keyring unavailable; secret storage is disabled. ({exc})"
            return

        if self._file_path.exists():
            self._migrate_file_to_keyring()

    @property
    def _using_file(self) -> bool:
        return self._forced in {"file", "plaintext"} and self._file_allowed

    def _file_values(self) -> dict[str, str]:
        data = _read_json(self._file_path, default={})
        if not isinstance(data, dict):
            raise ValueError("Legacy secret file must contain an object")
        values: dict[str, str] = {}
        for name, entry in data.items():
            if not isinstance(name, str) or not name:
                raise ValueError("Legacy secret names must be non-empty strings")
            if not isinstance(entry, dict):
                raise ValueError(f"Legacy secret entry {name!r} must contain an object")
            encoded = entry.get("value_b64")
            if not isinstance(encoded, str) or not encoded:
                raise ValueError(f"Legacy secret entry {name!r} is missing value_b64")
            values[name] = _b64d(encoded)
        return values

    def _migrate_file_to_keyring(self) -> None:
        assert self._keyring is not None
        written: list[tuple[str, str | None]] = []
        try:
            values = self._file_values()
            for name, value in values.items():
                previous = self._keyring.get_password(SERVICE_NAME, name)
                self._keyring.set_password(SERVICE_NAME, name, value)
                written.append((name, previous))
                if self._keyring.get_password(SERVICE_NAME, name) != value:
                    raise RuntimeError(f"OS keyring did not verify migrated entry {name!r}")
            self._file_path.unlink()
            self._migration_status = "migrated" if values else "removed_empty"
            self._note = "Legacy file secrets migrated to the OS keyring."
        except Exception as exc:
            for name, previous in reversed(written):
                try:
                    if previous is None:
                        self._keyring.delete_password(SERVICE_NAME, name)
                    else:
                        self._keyring.set_password(SERVICE_NAME, name, previous)
                except Exception:
                    pass
            self._migration_status = "failed"
            self._keyring_ok = False
            self._note = f"Legacy secret migration failed; file retained and storage disabled. ({exc})"

    def status(self) -> SecretsStatus:
        names = (
            "hf_token",
            "civitai_api_key",
            "openai_compat_api_key",
            "stability_api_key",
            "nvidia_api_key",
        )
        configured = [bool(self.get(name)) for name in names]
        return SecretsStatus(
            store="keyring" if self._keyring_ok else ("file" if self._using_file else "unavailable"),
            available=self._keyring_ok or self._using_file,
            has_hf_token=configured[0],
            has_civitai_api_key=configured[1],
            has_openai_compat_api_key=configured[2],
            has_stability_api_key=configured[3],
            has_nvidia_api_key=configured[4],
            migration_status=self._migration_status,
            legacy_file_present=self._file_path.exists(),
            note=self._note,
        )

    def get(self, name: str) -> str | None:
        name = (name or "").strip().lower()
        if not name:
            return None
        if self._keyring_ok and self._keyring is not None:
            try:
                value = self._keyring.get_password(SERVICE_NAME, name)
                return str(value) if value else None
            except Exception as exc:
                self._keyring_ok = False
                self._note = f"OS keyring read failed; secret storage is disabled. ({exc})"
                return None
        if self._using_file:
            try:
                return self._file_values().get(name)
            except Exception as exc:
                self._note = f"File secret storage is unreadable. ({exc})"
        return None

    def set(self, name: str, value: str) -> None:
        name = (name or "").strip().lower()
        if not name:
            raise ValueError("Missing secret name")
        if self._keyring_ok and self._keyring is not None:
            try:
                self._keyring.set_password(SERVICE_NAME, name, value or "")
                return
            except Exception as exc:
                self._keyring_ok = False
                self._note = f"OS keyring write failed; secret storage is disabled. ({exc})"
                raise RuntimeError(self._note) from exc
        if not self._using_file:
            raise RuntimeError(self._note or "No permitted secret storage backend is available")
        data = _read_json(self._file_path, default={})
        if not isinstance(data, dict):
            data = {}
        data[name] = {"value_b64": _b64e(value or ""), "set_at": time.time()}
        _write_json(self._file_path, data)

    def delete(self, name: str) -> None:
        name = (name or "").strip().lower()
        if not name:
            return
        if self._keyring_ok and self._keyring is not None:
            try:
                self._keyring.delete_password(SERVICE_NAME, name)
            except Exception as exc:
                self._keyring_ok = False
                self._note = f"OS keyring delete failed; secret storage is disabled. ({exc})"
                raise RuntimeError(self._note) from exc
            return
        if not self._using_file:
            raise RuntimeError(self._note or "No permitted secret storage backend is available")
        data = _read_json(self._file_path, default={})
        if isinstance(data, dict) and name in data:
            del data[name]
            _write_json(self._file_path, data)
