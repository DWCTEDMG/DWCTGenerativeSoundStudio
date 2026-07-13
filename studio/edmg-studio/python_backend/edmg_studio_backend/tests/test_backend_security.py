from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from edmg_studio_backend.security import (
    BackendSecurityMiddleware,
    BackendSecuritySettings,
    validate_remote_bind_security,
)


def _settings(**overrides):
    values = {
        "auth_mode": "required",
        "auth_token": "test-backend-token",
        "configured_host": "0.0.0.0",
        "allow_insecure_remote": False,
        "cors_origins": ("http://127.0.0.1:5173",),
        "cors_origin_regex": None,
        "public_media_gets": True,
    }
    values.update(overrides)
    return BackendSecuritySettings(**values)


def _client(settings: BackendSecuritySettings) -> TestClient:
    app = FastAPI()
    app.add_middleware(BackendSecurityMiddleware, settings=settings)

    @app.get("/health")
    def health():
        return {"ok": True}

    @app.get("/v1/security/status")
    def status():
        return settings.public_status(request_scheme="https")

    @app.get("/v1/projects")
    def projects():
        return {"projects": []}

    @app.post("/v1/models/install")
    def install():
        return {"ok": True}

    @app.get("/v1/projects/0123456789abcdef0123456789abcdef/file")
    def media():
        return {"ok": True}

    return TestClient(app)


def test_required_auth_protects_control_and_metadata_routes():
    with _client(_settings()) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/v1/security/status").status_code == 200

        unauthorized = client.get("/v1/projects")
        assert unauthorized.status_code == 401
        assert unauthorized.json()["error"]["code"] == "BACKEND_AUTH_REQUIRED"

        headers = {"Authorization": "Bearer test-backend-token"}
        assert client.get("/v1/projects", headers=headers).status_code == 200
        assert client.post("/v1/models/install", headers=headers).status_code == 200


def test_public_media_compatibility_is_read_only_and_project_scoped():
    with _client(_settings()) as client:
        media_path = "/v1/projects/0123456789abcdef0123456789abcdef/file?path=outputs/demo.mp4"
        assert client.get(media_path).status_code == 200
        assert client.post(media_path).status_code == 401
        assert client.get("/v1/projects/not-a-project/file?path=demo.mp4").status_code == 401


def test_remote_bind_requires_auth_unless_explicitly_overridden():
    validate_remote_bind_security("127.0.0.1", settings=_settings(auth_mode="disabled", auth_token=""))
    validate_remote_bind_security("0.0.0.0", settings=_settings())
    validate_remote_bind_security(
        "0.0.0.0",
        settings=_settings(
            auth_mode="disabled",
            auth_token="",
            allow_insecure_remote=True,
        ),
    )

    try:
        validate_remote_bind_security(
            "0.0.0.0",
            settings=_settings(auth_mode="disabled", auth_token=""),
        )
    except RuntimeError as exc:
        assert "Refusing to bind" in str(exc)
    else:  # pragma: no cover - assertion guard
        raise AssertionError("expected insecure remote bind to be rejected")


def test_auto_mode_detects_direct_remote_server_socket_without_host_environment():
    settings = _settings(
        auth_mode="auto",
        auth_token="",
        configured_host="",
    )
    assert settings.remote_without_auth_for_server("192.168.1.20") is True
    assert settings.remote_without_auth_for_server("127.0.0.1") is False
    assert settings.remote_without_auth_for_server("testserver") is False

    explicit_test_mode = _settings(
        auth_mode="disabled",
        auth_token="",
        configured_host="",
    )
    assert explicit_test_mode.remote_without_auth_for_server("192.168.1.20") is False


def test_security_headers_are_added_to_success_and_error_responses():
    with _client(_settings()) as client:
        unauthorized = client.get("/v1/projects")
        assert unauthorized.headers["x-content-type-options"] == "nosniff"
        assert unauthorized.headers["x-frame-options"] == "DENY"

        ok = client.get(
            "/v1/projects",
            headers={"Authorization": "Bearer test-backend-token"},
        )
        assert ok.headers["referrer-policy"] == "no-referrer"
