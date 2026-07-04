from __future__ import annotations

from edmg_studio_backend.services import hf_auth


class _FakeSecrets:
    def __init__(self, token: str = "") -> None:
        self._token = token

    def get(self, name: str) -> str:
        if name == "hf_token":
            return self._token
        return ""


def _clear_env_tokens(monkeypatch) -> None:
    for name in ("EDMG_HF_TOKEN", "HF_TOKEN", "HUGGINGFACE_TOKEN"):
        monkeypatch.delenv(name, raising=False)


def test_env_token_wins_over_cached_and_settings_tokens(monkeypatch) -> None:
    _clear_env_tokens(monkeypatch)
    monkeypatch.setenv("HF_TOKEN", "hf_env_token_1234567890")
    monkeypatch.setattr(hf_auth, "_hf_hub_cache_token", lambda: "hf_cache_token_1234567890")
    monkeypatch.setattr(hf_auth, "_hf_cli_token", lambda: "hf_cli_token_1234567890")

    token, source = hf_auth.resolve_hf_token(secrets_store=_FakeSecrets("hf_settings_token_1234567890"))

    assert token == "hf_env_token_1234567890"
    assert source == "env:HF_TOKEN"


def test_modern_hub_cache_token_wins_over_settings_token(monkeypatch) -> None:
    _clear_env_tokens(monkeypatch)
    monkeypatch.setattr(hf_auth, "_hf_hub_cache_token", lambda: "hf_cache_token_1234567890")
    monkeypatch.setattr(hf_auth, "_hf_cli_token", lambda: "")

    token, source = hf_auth.resolve_hf_token(secrets_store=_FakeSecrets("hf_settings_token_1234567890"))

    assert token == "hf_cache_token_1234567890"
    assert source == "hf_cache"


def test_hf_cli_oauth_token_shape_is_accepted(monkeypatch) -> None:
    _clear_env_tokens(monkeypatch)
    oauth_token = "oauth-" + ("x" * 128)
    monkeypatch.setattr(hf_auth, "_hf_hub_cache_token", lambda: "")
    monkeypatch.setattr(hf_auth, "_hf_cli_token", lambda: oauth_token)

    token, source = hf_auth.resolve_hf_token(secrets_store=_FakeSecrets("hf_settings_token_1234567890"))

    assert token == oauth_token
    assert source == "hf_cli"


def test_describe_hf_auth_reports_commands_without_token(monkeypatch) -> None:
    _clear_env_tokens(monkeypatch)
    monkeypatch.setattr(hf_auth, "_hf_hub_cache_token", lambda: "")
    monkeypatch.setattr(hf_auth, "_hf_cli_token", lambda: "hf_cli_token_1234567890")
    monkeypatch.setattr(hf_auth, "_hf_cli_path", lambda: "hf")

    status = hf_auth.describe_hf_auth(secrets_store=_FakeSecrets(""))

    assert status == {
        "available": True,
        "token_source": "hf_cli",
        "modern_cli": "hf",
        "cli_available": True,
        "login_command": "hf auth login",
        "whoami_command": "hf auth whoami",
        "token_command": "hf auth token",
    }
    assert "hf_cli_token_1234567890" not in str(status)
