from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient

from edmg_studio_backend.security import (
    BackendSecurityMiddleware,
    BackendSecuritySettings,
    _DEFAULT_CORS_ORIGINS,
    _LOCAL_DEV_CORS_ORIGIN_REGEX,
    validate_remote_bind_security,
)


def _settings(**overrides):
    values = {
        "auth_mode": "required",
        "auth_token": "test-backend-token",
        "configured_host": "0.0.0.0",
        "allow_insecure_remote": False,
        "cors_origins": ("http://127.0.0.1:5173",),
        "cors_origin_regex": _LOCAL_DEV_CORS_ORIGIN_REGEX,
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


def test_cors_defaults_survive_env_origin_override(monkeypatch):
    monkeypatch.setenv("EDMG_BACKEND_CORS_ORIGINS", "https://app.example.com")
    monkeypatch.delenv("EDMG_BACKEND_CORS_ORIGIN_REGEX", raising=False)
    settings = BackendSecuritySettings.from_env()
    assert "null" in settings.cors_origins
    assert "https://app.example.com" in settings.cors_origins
    # Loopback Studio UI is regex-covered (any port), not a pinned origin list.
    assert "http://127.0.0.1:5173" not in settings.cors_origins
    assert settings.cors_origin_regex == _LOCAL_DEV_CORS_ORIGIN_REGEX


def test_cors_origin_regex_keeps_local_dev_when_cloud_regex_set(monkeypatch):
    monkeypatch.delenv("EDMG_BACKEND_CORS_ORIGINS", raising=False)
    monkeypatch.setenv(
        "EDMG_BACKEND_CORS_ORIGIN_REGEX",
        r"^https://[A-Za-z0-9.-]+\.example\.com$",
    )
    settings = BackendSecuritySettings.from_env()
    assert _LOCAL_DEV_CORS_ORIGIN_REGEX in (settings.cors_origin_regex or "")
    assert r"example\.com" in (settings.cors_origin_regex or "")
    for origin in _DEFAULT_CORS_ORIGINS:
        assert origin in settings.cors_origins


def test_cors_middleware_allows_any_loopback_studio_origin():
    settings = _settings(
        auth_mode="disabled",
        auth_token="",
        configured_host="127.0.0.1",
        cors_origins=_DEFAULT_CORS_ORIGINS,
        cors_origin_regex=_LOCAL_DEV_CORS_ORIGIN_REGEX,
    )
    app = FastAPI()
    app.add_middleware(BackendSecurityMiddleware, settings=settings)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_origin_regex=settings.cors_origin_regex,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/v1/models/catalog")
    def catalog():
        return {"ok": True}

    with TestClient(app) as client:
        for origin in ("http://127.0.0.1:5173", "http://localhost:5199", "http://127.0.0.1:4173"):
            get_res = client.get("/v1/models/catalog", headers={"Origin": origin})
            assert get_res.status_code == 200
            assert get_res.headers.get("access-control-allow-origin") == origin

        options_res = client.options(
            "/v1/models/catalog",
            headers={
                "Origin": "http://127.0.0.1:5173",
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "content-type",
            },
        )
        assert options_res.status_code == 200
        assert options_res.headers.get("access-control-allow-origin") == "http://127.0.0.1:5173"
