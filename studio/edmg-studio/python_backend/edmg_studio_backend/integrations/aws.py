from __future__ import annotations

import os
import re
import shutil
import tarfile
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Any
from urllib.parse import urlparse
import zipfile

def _require_boto3():
    try:
        import boto3  # type: ignore
        return boto3
    except Exception as e:
        raise RuntimeError("AWS integration requires optional deps: pip install -e '.[aws]'") from e


def _require_client_error():
    try:
        from botocore.exceptions import ClientError  # type: ignore
        return ClientError
    except Exception as e:
        raise RuntimeError("AWS integration requires optional deps: pip install -e '.[aws]'") from e


def _truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _clean_part(value: str, fallback: str) -> str:
    raw = str(value or "").strip().strip("/\\") or fallback
    return re.sub(r"[^A-Za-z0-9._=-]+", "-", raw).strip(".-") or fallback


def _first_string(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _parse_s3_uri(value: str) -> tuple[str, str] | None:
    raw = str(value or "").strip()
    if not raw.lower().startswith("s3://"):
        return None
    parsed = urlparse(raw)
    bucket = str(parsed.netloc or "").strip()
    key = str(parsed.path or "").lstrip("/")
    if not bucket or not key:
        return None
    return bucket, key


def _aws_region() -> str:
    return (
        os.getenv("AWS_REGION", "").strip()
        or os.getenv("AWS_DEFAULT_REGION", "").strip()
        or "us-east-1"
    )


@dataclass
class AwsTestResult:
    ok: bool
    account: str | None = None
    region: str | None = None


@dataclass(frozen=True)
class S3ModelCacheSettings:
    bucket: str
    prefix: str = "models"
    region: str = "us-east-1"
    endpoint_url: str = ""
    storage_class: str = "STANDARD"


def settings_from_env(*, bucket: str | None = None, prefix: str | None = None) -> S3ModelCacheSettings:
    resolved_bucket = (
        str(bucket or "").strip()
        or os.getenv("EDMG_AWS_MODEL_CACHE_BUCKET", "").strip()
        or os.getenv("EDMG_AWS_MODEL_BUCKET", "").strip()
        or os.getenv("EDMG_S3_MODEL_CACHE_BUCKET", "").strip()
    )
    if not resolved_bucket:
        raise RuntimeError("Set EDMG_AWS_MODEL_CACHE_BUCKET to the S3 bucket for model cache files.")

    return S3ModelCacheSettings(
        bucket=resolved_bucket,
        prefix=(
            str(prefix or "").strip()
            or os.getenv("EDMG_AWS_MODEL_CACHE_PREFIX", "").strip()
            or os.getenv("EDMG_S3_MODEL_CACHE_PREFIX", "").strip()
            or "models"
        ).strip("/"),
        region=_aws_region(),
        endpoint_url=(
            os.getenv("EDMG_S3_ENDPOINT_URL", "").strip()
            or os.getenv("AWS_ENDPOINT_URL", "").strip()
        ),
        storage_class=(
            os.getenv("EDMG_AWS_MODEL_CACHE_STORAGE_CLASS", "").strip()
            or os.getenv("EDMG_S3_MODEL_CACHE_STORAGE_CLASS", "").strip()
            or "STANDARD"
        ).strip().upper(),
    )


def _s3_client(settings: S3ModelCacheSettings | None = None):
    boto3 = _require_boto3()
    settings = settings or S3ModelCacheSettings(bucket="")
    kwargs: dict[str, Any] = {"region_name": settings.region or _aws_region()}
    if settings.endpoint_url:
        kwargs["endpoint_url"] = settings.endpoint_url
    return boto3.client("s3", **kwargs)


def test_credentials(bucket: Optional[str] = None, prefix: Optional[str] = None) -> AwsTestResult:
    boto3 = _require_boto3()
    sts = boto3.client("sts")
    ident = sts.get_caller_identity()
    account = ident.get("Account")
    region = boto3.session.Session().region_name
    if bucket:
        settings = S3ModelCacheSettings(
            bucket=bucket,
            prefix=(str(prefix or "").strip() or "models").strip("/"),
            region=region or _aws_region(),
            endpoint_url=os.getenv("EDMG_S3_ENDPOINT_URL", "").strip() or os.getenv("AWS_ENDPOINT_URL", "").strip(),
        )
        s3 = _s3_client(settings)
        s3.head_bucket(Bucket=bucket)
    return AwsTestResult(ok=True, account=account, region=region)


def upload_file_s3(bucket: str, key: str, path: str) -> dict[str, Any]:
    boto3 = _require_boto3()
    s3 = boto3.client("s3")
    s3.upload_file(path, bucket, key)
    return {"bucket": bucket, "key": key}


def _safe_extract_zip(zip_path: Path, target_dir: Path) -> None:
    root = target_dir.resolve()
    with zipfile.ZipFile(zip_path) as archive:
        for member in archive.infolist():
            dest = (target_dir / member.filename).resolve()
            if root != dest and root not in dest.parents:
                raise RuntimeError(f"Unsafe path in model archive: {member.filename}")
        archive.extractall(target_dir)


def _safe_extract_tar(tar_path: Path, target_dir: Path) -> None:
    root = target_dir.resolve()
    with tarfile.open(tar_path) as archive:
        for member in archive.getmembers():
            if not (member.isdir() or member.isfile()):
                raise RuntimeError(f"Unsupported entry in model archive: {member.name}")
            dest = (target_dir / member.name).resolve()
            if root != dest and root not in dest.parents:
                raise RuntimeError(f"Unsafe path in model archive: {member.name}")
        archive.extractall(target_dir)


def _move_extracted_snapshot(extract_root: Path, dest: Path) -> None:
    source = extract_root
    if not (extract_root / "model_index.json").exists():
        children = [child for child in extract_root.iterdir() if child.is_dir()]
        files = [child for child in extract_root.iterdir() if child.is_file()]
        if len(children) == 1 and not files and (children[0] / "model_index.json").exists():
            source = children[0]

    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        if dest.is_dir():
            shutil.rmtree(dest)
        else:
            dest.unlink()
    shutil.move(str(source), str(dest))


class S3ModelCache:
    label = "AWS S3 model cache"

    def __init__(self, settings: S3ModelCacheSettings):
        self.settings = settings
        self._client = _s3_client(settings)

    @classmethod
    def from_env(cls) -> "S3ModelCache | None":
        if not _truthy(os.getenv("EDMG_AWS_MODEL_CACHE")) and not _truthy(os.getenv("EDMG_S3_MODEL_CACHE")):
            return None
        return cls(settings_from_env())

    def _explicit_object_location(self, entry: dict[str, Any]) -> tuple[str, str] | None:
        target = entry.get("target") if isinstance(entry.get("target"), dict) else {}
        uri = _first_string(
            entry.get("s3_uri"),
            entry.get("aws_s3_uri"),
            entry.get("s3_url"),
            target.get("s3_uri"),
            target.get("aws_s3_uri"),
            target.get("s3_url"),
        )
        if uri:
            parsed = _parse_s3_uri(uri)
            if parsed is not None:
                return parsed

        key = _first_string(
            entry.get("s3_key"),
            entry.get("aws_s3_key"),
            entry.get("object_key"),
            entry.get("key"),
            target.get("s3_key"),
            target.get("aws_s3_key"),
            target.get("object_key"),
            target.get("key"),
        )
        if not key:
            return None

        parsed = _parse_s3_uri(key)
        if parsed is not None:
            return parsed

        bucket = _first_string(
            entry.get("s3_bucket"),
            entry.get("aws_s3_bucket"),
            target.get("s3_bucket"),
            target.get("aws_s3_bucket"),
            self.settings.bucket,
        )
        return bucket, key.strip("/")

    def _default_object_key_for(self, entry: dict[str, Any], path: Path, *, archive: bool = False) -> str:
        target = entry.get("target") if isinstance(entry.get("target"), dict) else {}
        folder = _clean_part(str(target.get("folder") or "models"), "models")
        model_id = _clean_part(str(entry.get("id") or path.stem), path.stem)
        filename = _clean_part(path.name, "model")
        if archive and not filename.lower().endswith((".zip", ".tar", ".tar.gz", ".tgz")):
            filename = f"{filename}.zip"
        prefix = self.settings.prefix.strip("/")
        return "/".join(part for part in (prefix, folder, model_id, filename) if part)

    def object_location_for(self, entry: dict[str, Any], path: Path, *, archive: bool = False) -> tuple[str, str]:
        explicit = self._explicit_object_location(entry)
        if explicit is not None:
            return explicit
        return self.settings.bucket, self._default_object_key_for(entry, path, archive=archive)

    def object_key_for(self, entry: dict[str, Any], path: Path, *, archive: bool = False) -> str:
        return self.object_location_for(entry, path, archive=archive)[1]

    def _is_missing_object(self, exc: Exception) -> bool:
        response = getattr(exc, "response", {})
        error = response.get("Error", {}) if isinstance(response, dict) else {}
        code = str(error.get("Code") or "")
        return code in {"404", "NoSuchKey", "NotFound"}

    def _head(self, bucket: str, key: str) -> bool:
        ClientError = _require_client_error()
        try:
            self._client.head_object(Bucket=bucket, Key=key)
        except ClientError as exc:
            if self._is_missing_object(exc):
                return False
            raise
        return True

    def download_model(self, entry: dict[str, Any], dest: Path) -> bool:
        bucket, key = self.object_location_for(entry, dest)
        if not self._head(bucket, key):
            return False
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(dest.suffix + ".s3.tmp")
        self._client.download_file(bucket, key, str(tmp))
        tmp.replace(dest)
        return True

    def model_exists(self, entry: dict[str, Any], path: Path) -> str | None:
        bucket, key = self.object_location_for(entry, path)
        return key if self._head(bucket, key) else None

    def upload_model(self, entry: dict[str, Any], path: Path) -> str:
        if not path.exists() or not path.is_file():
            raise RuntimeError(f"Model cache upload source is not a file: {path}")
        bucket, key = self.object_location_for(entry, path)
        metadata = {
            "model_id": _clean_part(str(entry.get("id") or path.stem), path.stem)[:128],
            "source": _clean_part(str(entry.get("source") or "unknown"), "unknown")[:128],
            "kind": _clean_part(str(entry.get("kind") or "model"), "model")[:128],
        }
        extra_args: dict[str, Any] = {"Metadata": metadata}
        if self.settings.storage_class:
            extra_args["StorageClass"] = self.settings.storage_class
        self._client.upload_file(str(path), bucket, key, ExtraArgs=extra_args)
        return key

    def model_directory_exists(self, entry: dict[str, Any], path: Path) -> str | None:
        bucket, key = self.object_location_for(entry, path, archive=True)
        return key if self._head(bucket, key) else None

    def download_model_directory(self, entry: dict[str, Any], dest: Path) -> bool:
        bucket, key = self.object_location_for(entry, dest, archive=True)
        if not self._head(bucket, key):
            return False

        transfer_dir = dest.parent / f".{dest.name}.s3-{uuid.uuid4().hex}"
        archive_path = transfer_dir / Path(key).name
        extract_root = transfer_dir / "extract"
        transfer_dir.mkdir(parents=True, exist_ok=True)
        extract_root.mkdir(parents=True, exist_ok=True)
        try:
            self._client.download_file(bucket, key, str(archive_path))
            lower_key = key.lower()
            if lower_key.endswith(".zip"):
                _safe_extract_zip(archive_path, extract_root)
            elif lower_key.endswith((".tar", ".tar.gz", ".tgz")):
                _safe_extract_tar(archive_path, extract_root)
            else:
                raise RuntimeError("Internal model S3 objects must be .zip, .tar, .tar.gz, or .tgz archives.")
            _move_extracted_snapshot(extract_root, dest)
        finally:
            shutil.rmtree(transfer_dir, ignore_errors=True)
        return True

    def upload_model_directory(self, entry: dict[str, Any], path: Path) -> str:
        if not path.exists() or not path.is_dir():
            raise RuntimeError(f"Model cache upload source is not a directory: {path}")
        bucket, key = self.object_location_for(entry, path, archive=True)
        if not key.lower().endswith(".zip"):
            key = f"{key.rstrip('/')}.zip"
        transfer_dir = path.parent / f".{path.name}.s3-upload-{uuid.uuid4().hex}"
        archive_path = transfer_dir / "snapshot.zip"
        transfer_dir.mkdir(parents=True, exist_ok=True)
        try:
            with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_STORED) as archive:
                for candidate in sorted(path.rglob("*")):
                    if candidate.is_file():
                        archive.write(candidate, candidate.relative_to(path).as_posix())
            metadata = {
                "model_id": _clean_part(str(entry.get("id") or path.name), path.name)[:128],
                "source": _clean_part(str(entry.get("source") or "unknown"), "unknown")[:128],
                "kind": _clean_part(str(entry.get("kind") or "snapshot"), "snapshot")[:128],
                "archive": "zip",
            }
            extra_args: dict[str, Any] = {"Metadata": metadata}
            if self.settings.storage_class:
                extra_args["StorageClass"] = self.settings.storage_class
            self._client.upload_file(str(archive_path), bucket, key, ExtraArgs=extra_args)
        finally:
            shutil.rmtree(transfer_dir, ignore_errors=True)
        return key
