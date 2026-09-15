from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest

from edmg_studio_backend.services.secrets import SERVICE_NAME, SecretStore


class FakeKeyring:
    def __init__(
        self,
        *,
        fail_on: str | None = None,
        corrupt_on: str | None = None,
    ) -> None:
        self.values: dict[tuple[str, str], str] = {}
        self.fail_on = fail_on
        self.corrupt_on = corrupt_on

    def get_password(self, service: str, name: str) -> str | None:
        return self.values.get((service, name))

    def set_password(self, service: str, name: str, value: str) -> None:
        if name == self.fail_on:
            raise RuntimeError("keyring write failed")
        if name == self.corrupt_on:
            self.corrupt_on = None
            value = "corrupt"
        self.values[(service, name)] = value

    def delete_password(self, service: str, name: str) -> None:
        self.values.pop((service, name), None)


def _legacy_file(data_dir: Path, values: dict[str, str]) -> Path:
    path = data_dir / "config" / "secrets.json"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                name: {"value_b64": base64.b64encode(value.encode()).decode()}
                for name, value in values.items()
            }
        ),
        encoding="utf-8",
    )
    return path


def test_production_file_store_requires_explicit_development_consent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("EDMG_ENVIRONMENT", "production")
    monkeypatch.setenv("EDMG_SECRETS_STORE", "file")
    monkeypatch.setenv("EDMG_SECRETS_ALLOW_FILE", "1")

    store = SecretStore(tmp_path)
    assert store.status().store == "unavailable"
    assert store.status().available is False
    with pytest.raises(RuntimeError, match="File secret storage is disabled"):
        store.set("hf_token", "secret")


def test_development_file_store_requires_both_mode_and_consent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("EDMG_ENVIRONMENT", "development")
    monkeypatch.setenv("EDMG_SECRETS_STORE", "file")
    monkeypatch.setenv("EDMG_SECRETS_ALLOW_FILE", "1")

    store = SecretStore(tmp_path)
    store.set("hf_token", "secret")
    assert store.get("hf_token") == "secret"
    assert store.status().store == "file"


def test_legacy_file_migrates_transactionally_to_keyring(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("EDMG_ENVIRONMENT", "production")
    monkeypatch.setenv("EDMG_SECRETS_STORE", "keyring")
    legacy = _legacy_file(tmp_path, {"hf_token": "hf-secret", "civitai_api_key": "cv-secret"})
    keyring = FakeKeyring()

    store = SecretStore(tmp_path, keyring_backend=keyring)

    assert not legacy.exists()
    assert keyring.values[(SERVICE_NAME, "hf_token")] == "hf-secret"
    status = store.status()
    assert status.migration_status == "migrated"
    assert status.legacy_file_present is False
    assert "hf-secret" not in str(status)


def test_malformed_legacy_entry_retains_entire_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("EDMG_ENVIRONMENT", "production")
    monkeypatch.setenv("EDMG_SECRETS_STORE", "keyring")
    legacy = _legacy_file(tmp_path, {"hf_token": "hf-secret"})
    legacy.write_text(
        json.dumps(
            {
                "hf_token": {"value_b64": base64.b64encode(b"hf-secret").decode()},
                "unsupported": {"value": "must-not-be-discarded"},
            }
        ),
        encoding="utf-8",
    )
    keyring = FakeKeyring()

    store = SecretStore(tmp_path, keyring_backend=keyring)

    assert legacy.exists()
    assert keyring.values == {}
    assert store.status().migration_status == "failed"


def test_failed_legacy_migration_rolls_back_and_retains_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("EDMG_ENVIRONMENT", "production")
    monkeypatch.setenv("EDMG_SECRETS_STORE", "keyring")
    legacy = _legacy_file(tmp_path, {"hf_token": "hf-secret", "civitai_api_key": "cv-secret"})
    keyring = FakeKeyring(fail_on="civitai_api_key")

    store = SecretStore(tmp_path, keyring_backend=keyring)

    assert legacy.exists()
    assert keyring.values == {}
    status = store.status()
    assert status.available is False
    assert status.migration_status == "failed"
    assert status.legacy_file_present is True
    assert store.get("hf_token") is None


def test_failed_keyring_verification_restores_previous_value(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("EDMG_ENVIRONMENT", "production")
    monkeypatch.setenv("EDMG_SECRETS_STORE", "keyring")
    legacy = _legacy_file(tmp_path, {"hf_token": "new-secret"})
    keyring = FakeKeyring(corrupt_on="hf_token")
    keyring.values[(SERVICE_NAME, "hf_token")] = "old-secret"

    store = SecretStore(tmp_path, keyring_backend=keyring)

    assert legacy.exists()
    assert keyring.values[(SERVICE_NAME, "hf_token")] == "old-secret"
    assert store.status().migration_status == "failed"
