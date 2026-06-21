"""Hugging Face bucket model cache.

Implements the same model-cache contract used by :class:`S3ModelCache`
(``edmg_studio_backend.integrations.aws``) so the existing
:class:`ModelManager` can store/restore weights in a Hugging Face *bucket*
(``hf://buckets/<namespace>/<name>``) without any other code changes.

Storage layout
---------------
The bucket is treated as a 1:1 *mirror* of the Studio models directory.
A local file at ``<models_dir>/checkpoints/foo.safetensors`` maps to the
bucket path ``checkpoints/foo.safetensors`` (optionally under a configured
prefix). This matches the layout produced by ``hf sync <models_dir>
hf://buckets/<id>`` so weights uploaded that way are picked up directly.

Enable with environment variables (see ``from_env``)::

    EDMG_HF_BUCKET_MODEL_CACHE=1
    EDMG_HF_BUCKET_ID=namespace/bucket-name
    # optional:
    EDMG_HF_BUCKET_PREFIX=
    EDMG_STUDIO_MODELS_DIR=...   # already set by the launcher
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


def _truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _first_string(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _normalize_remote(path: str) -> str:
    return str(path or "").strip().strip("/").replace("\\", "/")


def _require_hf_api():
    try:
        from huggingface_hub import HfApi  # type: ignore

        return HfApi
    except Exception as exc:  # pragma: no cover - import guard
        raise RuntimeError(
            "Hugging Face bucket cache requires 'huggingface_hub' with bucket support "
            "(huggingface_hub>=0.34). Reinstall the Studio backend dependencies."
        ) from exc


@dataclass(frozen=True)
class HFBucketCacheSettings:
    bucket: str  # bucket id: "namespace/name"
    models_dir: Path
    prefix: str = ""
    token: str = ""


def _hf_bucket_enabled() -> bool:
    return _truthy(os.getenv("EDMG_HF_BUCKET_MODEL_CACHE")) or _truthy(
        os.getenv("EDMG_HF_MODEL_CACHE")
    )


def _configured_bucket_id(*, bucket: str | None = None) -> str:
    resolved = (
        str(bucket or "").strip()
        or os.getenv("EDMG_HF_BUCKET_ID", "").strip()
        or os.getenv("EDMG_HF_MODEL_BUCKET", "").strip()
        or os.getenv("EDMG_HF_BUCKET", "").strip()
    )
    if "buckets/" in resolved:
        resolved = resolved.split("buckets/", 1)[1]
    return resolved.strip().strip("/")


def resolve_models_dir(*, models_dir: Path | None = None) -> Path:
    """Resolve the Studio models directory (mirrors ``Settings.models_dir`` fallback)."""
    if models_dir is not None:
        return Path(models_dir).expanduser().resolve()

    raw = (
        os.getenv("EDMG_STUDIO_MODELS_DIR", "").strip()
        or os.getenv("EDMG_HF_BUCKET_MODELS_DIR", "").strip()
    )
    if raw:
        return Path(raw).expanduser().resolve()

    data_dir = Path(os.getenv("EDMG_STUDIO_DATA_DIR", "./data")).expanduser().resolve()
    studio_home_raw = os.getenv("EDMG_STUDIO_HOME", "").strip()
    if studio_home_raw:
        studio_home = Path(studio_home_raw).expanduser().resolve()
    else:
        studio_home = data_dir.parent.resolve()
    return (studio_home / "models").resolve()


def resolve_hf_token(*, secrets_store: Any | None = None) -> tuple[str, str]:
    env_token = (
        os.getenv("EDMG_HF_TOKEN", "").strip()
        or os.getenv("HF_TOKEN", "").strip()
        or os.getenv("HUGGINGFACE_TOKEN", "").strip()
    )
    if env_token:
        return env_token, "env"
    if secrets_store is not None:
        settings_token = str(secrets_store.get("hf_token") or "").strip()
        if settings_token:
            return settings_token, "settings"
    return "", ""


def settings_from_env(
    *,
    bucket: str | None = None,
    prefix: str | None = None,
    token: str | None = None,
    models_dir: Path | None = None,
) -> HFBucketCacheSettings:
    resolved_bucket = (
        str(bucket or "").strip()
        or os.getenv("EDMG_HF_BUCKET_ID", "").strip()
        or os.getenv("EDMG_HF_MODEL_BUCKET", "").strip()
        or os.getenv("EDMG_HF_BUCKET", "").strip()
    )
    if not resolved_bucket:
        raise RuntimeError(
            "Set EDMG_HF_BUCKET_ID to the Hugging Face bucket id (namespace/name) for the model cache."
        )
    # Tolerate a full hf:// URI being pasted in.
    if "buckets/" in resolved_bucket:
        resolved_bucket = resolved_bucket.split("buckets/", 1)[1]
    resolved_bucket = resolved_bucket.strip().strip("/")

    resolved_models_dir = resolve_models_dir(models_dir=models_dir)

    resolved_token = str(token or "").strip()
    if not resolved_token:
        resolved_token, _ = resolve_hf_token()

    return HFBucketCacheSettings(
        bucket=resolved_bucket,
        models_dir=resolved_models_dir,
        prefix=_normalize_remote(
            str(prefix or "").strip() or os.getenv("EDMG_HF_BUCKET_PREFIX", "").strip()
        ),
        token=resolved_token,
    )


class HFBucketModelCache:
    """Model cache backed by a Hugging Face bucket (Xet-backed storage)."""

    label = "Hugging Face bucket"

    def __init__(self, settings: HFBucketCacheSettings):
        self.settings = settings
        HfApi = _require_hf_api()
        self._api = HfApi(token=settings.token or None)
        self._token = settings.token or None

    @classmethod
    def from_env(cls) -> "HFBucketModelCache | None":
        return cls.from_runtime()

    @classmethod
    def from_runtime(
        cls,
        *,
        models_dir: Path | None = None,
        secrets_store: Any | None = None,
    ) -> "HFBucketModelCache | None":
        if not _hf_bucket_enabled():
            return None
        token, _ = resolve_hf_token(secrets_store=secrets_store)
        return cls(
            settings_from_env(
                models_dir=models_dir,
                token=token or None,
            )
        )

    # ------------------------------------------------------------------
    # remote-path resolution (mirror of models_dir, with explicit overrides)
    # ------------------------------------------------------------------
    def _explicit_remote(self, entry: dict[str, Any]) -> str | None:
        target = entry.get("target") if isinstance(entry.get("target"), dict) else {}
        explicit = _first_string(
            entry.get("hf_bucket_path"),
            entry.get("hf_key"),
            entry.get("bucket_path"),
            entry.get("s3_key"),  # set by ModelManager from a recorded cloud object
            entry.get("key"),
            target.get("hf_bucket_path"),
            target.get("hf_key"),
            target.get("bucket_path"),
            target.get("s3_key"),
            target.get("key"),
        )
        return _normalize_remote(explicit) if explicit else None

    def _relative_to_models(self, path: Path) -> str | None:
        try:
            rel = Path(path).resolve().relative_to(self.settings.models_dir)
        except (ValueError, OSError):
            return None
        return rel.as_posix()

    def _fallback_remote(self, entry: dict[str, Any], path: Path) -> str:
        """Mirror path used when ``path`` is not under models_dir (e.g. a temp staging dir).

        Mirrors ``ModelManager._models_dest`` so uploads from cloud-only temp dirs
        still land at the canonical bucket location:
          - internal engine -> ``internal/<folder>/<id>`` (snapshot directory)
          - otherwise        -> ``<folder>/<filename>`` (single ComfyUI file)
        """
        target = entry.get("target") if isinstance(entry.get("target"), dict) else {}
        engine = str(target.get("engine") or entry.get("engine") or "comfyui").strip().lower()
        folder = _normalize_remote(str(target.get("folder") or "checkpoints")) or "checkpoints"
        if engine == "internal":
            model_id = _first_string(entry.get("id"), path.name) or "model"
            return _normalize_remote(f"internal/{folder}/{model_id}")
        filename = _first_string(entry.get("filename"), path.name) or "model.safetensors"
        return _normalize_remote(f"{folder}/{filename}")

    def _with_prefix(self, remote: str) -> str:
        remote = _normalize_remote(remote)
        if self.settings.prefix:
            return _normalize_remote(f"{self.settings.prefix}/{remote}")
        return remote

    def remote_path_for(self, entry: dict[str, Any], path: Path) -> str:
        explicit = self._explicit_remote(entry)
        if explicit:
            return explicit
        rel = self._relative_to_models(Path(path))
        if rel is None:
            rel = self._fallback_remote(entry, Path(path))
        return self._with_prefix(rel)

    # ------------------------------------------------------------------
    # single-file model operations
    # ------------------------------------------------------------------
    def _file_exists(self, remote: str) -> bool:
        remote = _normalize_remote(remote)
        try:
            infos = list(self._api.get_bucket_paths_info(self.settings.bucket, [remote], token=self._token))
        except Exception:
            from huggingface_hub.errors import EntryNotFoundError  # type: ignore

            try:
                self._api.get_bucket_file_metadata(self.settings.bucket, remote, token=self._token)
                return True
            except EntryNotFoundError:
                return False
        for info in infos:
            if _normalize_remote(getattr(info, "path", "")) == remote:
                return True
        return False

    def model_exists(self, entry: dict[str, Any], path: Path) -> str | None:
        remote = self.remote_path_for(entry, Path(path))
        return remote if self._file_exists(remote) else None

    def download_model(self, entry: dict[str, Any], dest: Path) -> bool:
        remote = self.remote_path_for(entry, Path(dest))
        if not self._file_exists(remote):
            return False
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(dest.suffix + ".hf.tmp")
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass
        self._api.download_bucket_files(
            self.settings.bucket,
            [(remote, str(tmp))],
            raise_on_missing_files=True,
            token=self._token,
        )
        os.replace(tmp, dest)
        return True

    def upload_model(self, entry: dict[str, Any], path: Path) -> str:
        path = Path(path)
        if not path.exists() or not path.is_file():
            raise RuntimeError(f"Model cache upload source is not a file: {path}")
        remote = self.remote_path_for(entry, path)
        self._api.batch_bucket_files(
            self.settings.bucket,
            add=[(str(path), remote)],
            token=self._token,
        )
        return remote

    # ------------------------------------------------------------------
    # directory (snapshot) operations
    # ------------------------------------------------------------------
    def _bucket_uri(self, remote_dir: str) -> str:
        remote_dir = _normalize_remote(remote_dir)
        base = f"hf://buckets/{self.settings.bucket}"
        return f"{base}/{remote_dir}" if remote_dir else base

    def _iter_remote_files(self, remote_dir: str) -> list[str]:
        remote_dir = _normalize_remote(remote_dir)
        out: list[str] = []
        try:
            items = self._api.list_bucket_tree(
                self.settings.bucket,
                prefix=remote_dir or None,
                recursive=True,
                token=self._token,
            )
        except Exception:
            return out
        for item in items:
            if type(item).__name__ != "BucketFile":
                continue
            rel = _normalize_remote(getattr(item, "path", ""))
            if not rel:
                continue
            if remote_dir and not (rel == remote_dir or rel.startswith(remote_dir + "/")):
                continue
            out.append(rel)
        return out

    def model_directory_exists(self, entry: dict[str, Any], path: Path) -> str | None:
        remote_dir = self.remote_path_for(entry, Path(path))
        return remote_dir if self._iter_remote_files(remote_dir) else None

    def download_model_directory(self, entry: dict[str, Any], dest: Path) -> bool:
        remote_dir = self.remote_path_for(entry, Path(dest))
        if not self._iter_remote_files(remote_dir):
            return False
        dest = Path(dest)
        dest.mkdir(parents=True, exist_ok=True)
        self._api.sync_bucket(
            source=self._bucket_uri(remote_dir),
            dest=str(dest),
            quiet=True,
            token=self._token,
        )
        return any(dest.rglob("*"))

    def upload_model_directory(self, entry: dict[str, Any], path: Path) -> str:
        path = Path(path)
        if not path.exists() or not path.is_dir():
            raise RuntimeError(f"Model cache upload source is not a directory: {path}")
        remote_dir = self.remote_path_for(entry, path)
        self._api.sync_bucket(
            source=str(path),
            dest=self._bucket_uri(remote_dir),
            quiet=True,
            token=self._token,
        )
        return remote_dir


def describe_status(
    *, models_dir: Path | None = None, secrets_store: Any | None = None
) -> dict[str, Any]:
    bucket = _configured_bucket_id()
    prefix = _normalize_remote(os.getenv("EDMG_HF_BUCKET_PREFIX", "").strip())
    token, token_source = resolve_hf_token(secrets_store=secrets_store)

    resolved_models_dir = resolve_models_dir(models_dir=models_dir)

    active = False
    active_error: str | None = None
    if _hf_bucket_enabled():
        try:
            active = HFBucketModelCache.from_runtime(
                models_dir=resolved_models_dir,
                secrets_store=secrets_store,
            ) is not None
        except Exception as exc:
            active_error = str(exc)

    return {
        "ok": True,
        "provider": "huggingface_bucket",
        "enabled": _hf_bucket_enabled(),
        "active": active,
        "active_error": active_error,
        "bucket": bucket or None,
        "prefix": prefix or None,
        "models_dir": str(resolved_models_dir),
        "has_token": bool(token),
        "token_source": token_source or None,
        "token_note": (
            "Runtime model cache uses HF_TOKEN/EDMG_HF_TOKEN env vars, falling back to "
            "Settings → Tokens when env vars are unset."
        ),
    }


def test_credentials(
    *,
    bucket: str | None = None,
    prefix: str | None = None,
    models_dir: Path | None = None,
    secrets_store: Any | None = None,
) -> dict[str, Any]:
    token, token_source = resolve_hf_token(secrets_store=secrets_store)
    if not token:
        raise RuntimeError(
            "No Hugging Face token found. Set HF_TOKEN (or EDMG_HF_TOKEN) in the backend "
            "environment or save a token in Settings → Tokens."
        )

    settings = settings_from_env(
        bucket=bucket,
        prefix=prefix,
        token=token,
        models_dir=models_dir,
    )
    cache = HFBucketModelCache(settings)
    prefix_filter = settings.prefix or None
    items = cache._api.list_bucket_tree(
        settings.bucket,
        prefix=prefix_filter,
        recursive=False,
        token=cache._token,
    )
    sample_paths: list[str] = []
    for item in items:
        rel = _normalize_remote(getattr(item, "path", ""))
        if rel:
            sample_paths.append(rel)
        if len(sample_paths) >= 5:
            break

    return {
        "ok": True,
        "provider": "huggingface_bucket",
        "bucket": settings.bucket,
        "prefix": settings.prefix or None,
        "models_dir": str(settings.models_dir),
        "token_source": token_source,
        "sample_paths": sample_paths,
        "bucket_uri": cache._bucket_uri(""),
    }
