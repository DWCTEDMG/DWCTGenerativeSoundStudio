from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import re
import subprocess
import sys
import uuid
from array import array
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import HTTPException, UploadFile

from .ffmpeg import ensure_ffmpeg, ensure_ffprobe

DEFAULT_MAX_UPLOAD_BYTES = 4 * 1024 * 1024 * 1024
_CHUNK_SIZE = 1024 * 1024
_AUDIO_EXTENSIONS = {".aac", ".aif", ".aiff", ".flac", ".m4a", ".mp3", ".ogg", ".opus", ".wav"}
_VIDEO_EXTENSIONS = {".avi", ".m4v", ".mkv", ".mov", ".mp4", ".mpeg", ".mpg", ".webm"}
_IMAGE_EXTENSIONS = {".bmp", ".gif", ".jpeg", ".jpg", ".png", ".tif", ".tiff", ".webp"}


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _safe_name(filename: str | None) -> str:
    name = Path(str(filename or "media").replace("\\", "/")).name
    stem = re.sub(r"[^A-Za-z0-9._ -]+", "_", Path(name).stem).strip(" ._") or "media"
    suffix = re.sub(r"[^A-Za-z0-9.]", "", Path(name).suffix.lower())
    return f"{stem[:100]}{suffix[:16]}"


def _media_kind(filename: str, content_type: str | None = None) -> str:
    suffix = Path(filename).suffix.lower()
    declared = str(content_type or "").lower()
    if suffix in _AUDIO_EXTENSIONS or declared.startswith("audio/"):
        return "audio"
    if suffix in _VIDEO_EXTENSIONS or declared.startswith("video/"):
        return "video"
    if suffix in _IMAGE_EXTENSIONS or declared.startswith("image/"):
        return "image"
    raise HTTPException(415, "Only audio, video, and image media files are supported")


def _relative(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _sha256(path: Path) -> tuple[int, str]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        while chunk := handle.read(_CHUNK_SIZE):
            size += len(chunk)
            digest.update(chunk)
    return size, digest.hexdigest()


def _waveform_peaks(path: Path, sample_count: int, requested_bins: int) -> list[list[float]]:
    target_bins = min(sample_count, requested_bins)
    peaks: list[list[float]] = []
    bin_min = 32767
    bin_max = -32768
    sample_index = 0
    next_boundary = (sample_count + target_bins - 1) // target_bins
    with path.open("rb") as handle:
        while chunk := handle.read(128 * 1024):
            samples = array("h")
            samples.frombytes(chunk)
            if sys.byteorder != "little":
                samples.byteswap()
            for sample in samples:
                bin_min = min(bin_min, sample)
                bin_max = max(bin_max, sample)
                sample_index += 1
                if sample_index >= next_boundary:
                    peaks.append([round(bin_min / 32768.0, 5), round(bin_max / 32767.0, 5)])
                    bin_min, bin_max = 32767, -32768
                    next_boundary = ((len(peaks) + 1) * sample_count + target_bins - 1) // target_bins
    return peaks


def _pool(meta: dict[str, Any], *, create: bool) -> list[dict[str, Any]]:
    timeline = meta.get("timeline")
    if not isinstance(timeline, dict):
        if not create:
            return []
        timeline = {}
        meta["timeline"] = timeline
    pool = timeline.get("media_pool")
    if not isinstance(pool, list):
        if not create:
            return []
        pool = []
        timeline["media_pool"] = pool
    return pool


class MediaPoolService:
    def __init__(self, store: Any, ffmpeg_path: str, max_upload_bytes: int | None = None):
        self.store = store
        self.ffmpeg_path = ffmpeg_path
        configured = os.getenv("EDMG_MEDIA_IMPORT_MAX_BYTES", "").strip()
        self.max_upload_bytes = int(configured or max_upload_bytes or DEFAULT_MAX_UPLOAD_BYTES)

    def _project(self, project_id: str):
        project = self.store.get(project_id)
        if project is None:
            raise HTTPException(404, "Project not found")
        return project

    @staticmethod
    def _find(meta: dict[str, Any], asset_id: str) -> dict[str, Any]:
        for asset in _pool(meta, create=False):
            if isinstance(asset, dict) and str(asset.get("id")) == asset_id:
                return asset
        raise HTTPException(404, "Media asset not found")

    def _safe_project_path(self, project_id: str, relative: str, *, require_file: bool = True) -> Path:
        root = self.store.project_dir(project_id).resolve()
        value = str(relative or "").replace("\\", "/")
        candidate = (root / value).resolve()
        if not value or candidate == root or root not in candidate.parents:
            raise HTTPException(400, "Media path must remain inside the project")
        if require_file and not candidate.is_file():
            raise HTTPException(404, "Media file does not exist")
        return candidate

    def _public_asset(self, project_id: str, asset: dict[str, Any]) -> dict[str, Any]:
        result = deepcopy(asset)
        try:
            missing = not self._safe_project_path(project_id, str(asset.get("path") or "")).is_file()
        except HTTPException:
            missing = True
        result["missing"] = missing
        result["status"] = "missing" if missing else "ready"
        return result

    def list(self, project_id: str) -> dict[str, Any]:
        project = self._project(project_id)
        assets = [item for item in _pool(project.meta, create=False) if isinstance(item, dict)]
        return {"ok": True, "schema_version": 1, "assets": [self._public_asset(project_id, item) for item in assets]}

    async def _stage_upload(self, upload: UploadFile, directory: Path) -> tuple[Path, int, str]:
        directory.mkdir(parents=True, exist_ok=True)
        temporary = directory / f".{uuid.uuid4().hex}.upload"
        size = 0
        digest = hashlib.sha256()
        try:
            with temporary.open("xb") as handle:
                while chunk := await upload.read(_CHUNK_SIZE):
                    size += len(chunk)
                    if size > self.max_upload_bytes:
                        raise HTTPException(413, f"Media file exceeds the {self.max_upload_bytes}-byte import limit")
                    digest.update(chunk)
                    handle.write(chunk)
                handle.flush()
                os.fsync(handle.fileno())
            if not size:
                raise HTTPException(400, "Media file is empty")
            return temporary, size, digest.hexdigest()
        except Exception:
            temporary.unlink(missing_ok=True)
            raise
        finally:
            await upload.close()

    def _probe(self, path: Path, *, required: bool) -> dict[str, Any]:
        try:
            executable = ensure_ffprobe(self.ffmpeg_path)
            process = subprocess.run(
                [executable, "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path)],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            if process.returncode:
                raise RuntimeError((process.stderr or "ffprobe failed").strip()[:1000])
            data = json.loads(process.stdout or "{}")
        except (OSError, RuntimeError, subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
            if required:
                raise HTTPException(503, f"Media probe failed: {exc}") from exc
            return {"status": "unavailable", "error": str(exc)}
        streams = data.get("streams") if isinstance(data.get("streams"), list) else []
        compact = [
            {key: stream[key] for key in (
                "index", "codec_name", "codec_type", "width", "height", "sample_rate", "channels",
                "channel_layout", "avg_frame_rate", "duration",
            ) if key in stream}
            for stream in streams if isinstance(stream, dict)
        ]
        media_format = data.get("format") if isinstance(data.get("format"), dict) else {}
        return {
            "status": "ready",
            "duration_seconds": _number(media_format.get("duration")),
            "format_name": media_format.get("format_name"),
            "bit_rate": _integer(media_format.get("bit_rate")),
            "streams": compact,
        }

    async def import_media(self, project_id: str, upload: UploadFile) -> dict[str, Any]:
        self._project(project_id)
        original_name = _safe_name(upload.filename)
        kind = _media_kind(original_name, upload.content_type)
        root = self.store.project_dir(project_id)
        staged, size, content_hash = await self._stage_upload(upload, root / "assets" / "media")
        existing: dict[str, Any] | None = None
        project = self._project(project_id)
        for item in _pool(project.meta, create=False):
            if isinstance(item, dict) and item.get("sha256") == content_hash:
                existing = item
                break
        if existing is not None:
            staged.unlink(missing_ok=True)
            return {"ok": True, "deduplicated": True, "asset": self._public_asset(project_id, existing)}

        asset_id = uuid.uuid4().hex
        destination = staged.with_name(f"{asset_id}-{uuid.uuid4().hex}-{original_name}")
        os.replace(staged, destination)
        now = _utc_now()
        asset = {
            "id": asset_id,
            "display_name": original_name,
            "original_filename": original_name,
            "path": _relative(destination, root),
            "kind": kind,
            "content_type": mimetypes.guess_type(original_name)[0] or upload.content_type or "application/octet-stream",
            "size_bytes": size,
            "sha256": content_hash,
            "probe": self._probe(destination, required=False),
            "derivatives": {},
            "created_at": now,
            "updated_at": now,
        }

        def register(value: Any) -> None:
            current_pool = _pool(value.meta, create=True)
            duplicate = next((item for item in current_pool if isinstance(item, dict) and item.get("sha256") == content_hash), None)
            if duplicate is not None:
                raise FileExistsError(str(duplicate.get("id") or "duplicate"))
            current_pool.append(deepcopy(asset))

        try:
            saved = self.store.mutate(project_id, register)
        except FileExistsError:
            destination.unlink(missing_ok=True)
            current = self._project(project_id)
            duplicate = next(item for item in _pool(current.meta, create=False) if item.get("sha256") == content_hash)
            return {"ok": True, "deduplicated": True, "asset": self._public_asset(project_id, duplicate)}
        except Exception:
            destination.unlink(missing_ok=True)
            raise
        stored = self._find(saved.meta, asset_id)
        return {"ok": True, "deduplicated": False, "asset": self._public_asset(project_id, stored)}

    async def relink_upload(self, project_id: str, asset_id: str, upload: UploadFile) -> dict[str, Any]:
        project = self._project(project_id)
        previous = self._find(project.meta, asset_id)
        original_name = _safe_name(upload.filename)
        kind = _media_kind(original_name, upload.content_type)
        if kind != previous.get("kind"):
            await upload.close()
            raise HTTPException(409, f"Replacement must be {previous.get('kind')} media")

        root = self.store.project_dir(project_id)
        staged, _, _ = await self._stage_upload(upload, root / "assets" / "media")
        destination = staged.with_name(f"{asset_id}-{uuid.uuid4().hex}-{original_name}")
        os.replace(staged, destination)
        try:
            result = self.relink(project_id, asset_id, _relative(destination, root))
        except Exception:
            destination.unlink(missing_ok=True)
            raise
        previous_path = self._safe_project_path(
            project_id, str(previous.get("path") or ""), require_file=False
        )
        managed_root = (root / "assets" / "media").resolve()
        current = self._project(project_id)
        referenced_paths = {
            str(item.get("path") or "")
            for item in _pool(current.meta, create=False)
            if isinstance(item, dict)
        }
        if (
            previous_path != destination
            and previous_path.resolve().is_relative_to(managed_root)
            and _relative(previous_path, root) not in referenced_paths
        ):
            previous_path.unlink(missing_ok=True)
        return result

    def probe(self, project_id: str, asset_id: str) -> dict[str, Any]:
        project = self._project(project_id)
        asset = self._find(project.meta, asset_id)
        result = self._probe(self._safe_project_path(project_id, str(asset.get("path") or "")), required=True)

        def update(value: Any) -> None:
            current = self._find(value.meta, asset_id)
            current["probe"] = deepcopy(result)
            current["updated_at"] = _utc_now()

        saved = self.store.mutate(project_id, update)
        return {"ok": True, "asset": self._public_asset(project_id, self._find(saved.meta, asset_id)), "probe": result}

    def relink(self, project_id: str, asset_id: str, candidate_path: str) -> dict[str, Any]:
        project = self._project(project_id)
        previous = self._find(project.meta, asset_id)
        source = self._safe_project_path(project_id, candidate_path)
        original_name = _safe_name(source.name)
        kind = _media_kind(original_name, mimetypes.guess_type(original_name)[0])
        if kind != previous.get("kind"):
            raise HTTPException(409, f"Replacement must be {previous.get('kind')} media")
        root = self.store.project_dir(project_id)
        size, content_hash = _sha256(source)
        probe = self._probe(source, required=False)

        def update(value: Any) -> None:
            asset = self._find(value.meta, asset_id)
            asset.update({
                "path": _relative(source, root),
                "display_name": original_name,
                "original_filename": original_name,
                "content_type": mimetypes.guess_type(original_name)[0] or "application/octet-stream",
                "size_bytes": size,
                "sha256": content_hash,
                "probe": deepcopy(probe),
                "derivatives": {},
                "updated_at": _utc_now(),
            })

        saved = self.store.mutate(project_id, update)
        return {"ok": True, "asset": self._public_asset(project_id, self._find(saved.meta, asset_id))}

    def _derivative_context(self, project_id: str, asset_id: str, name: str, options: str, suffix: str):
        project = self._project(project_id)
        asset = self._find(project.meta, asset_id)
        source = self._safe_project_path(project_id, str(asset.get("path") or ""))
        source_hash = str(asset.get("sha256") or _sha256(source)[1])
        cache_key = hashlib.sha256(f"{source_hash}:{name}:{options}:v1".encode()).hexdigest()
        output = self.store.project_dir(project_id) / "cache" / "media" / source_hash / f"{name}-{cache_key[:16]}{suffix}"
        existing = (asset.get("derivatives") or {}).get(name) or {}
        return project, asset, source, cache_key, output, existing

    def _record_derivative(self, project_id: str, asset_id: str, name: str, derivative: dict[str, Any]) -> dict[str, Any]:
        def update(value: Any) -> None:
            asset = self._find(value.meta, asset_id)
            asset.setdefault("derivatives", {})[name] = deepcopy(derivative)
            asset["updated_at"] = _utc_now()

        saved = self.store.mutate(project_id, update)
        asset = self._find(saved.meta, asset_id)
        return {"ok": True, "cached": False, "asset": self._public_asset(project_id, asset), "derivative": derivative}

    @staticmethod
    def _run(command: list[str], timeout: int) -> subprocess.CompletedProcess:
        try:
            process = subprocess.run(command, capture_output=True, timeout=timeout, check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise HTTPException(503, f"Media derivative generation failed: {exc}") from exc
        if process.returncode:
            detail = (process.stderr or b"ffmpeg failed").decode(errors="replace").strip()[:1000]
            raise HTTPException(422, f"Media derivative generation failed: {detail}")
        return process

    def waveform(self, project_id: str, asset_id: str, bins: int = 1024) -> dict[str, Any]:
        bins = min(4096, max(64, int(bins)))
        project, asset, source, key, output, existing = self._derivative_context(project_id, asset_id, "waveform", str(bins), ".json")
        if asset.get("kind") not in {"audio", "video"}:
            raise HTTPException(409, "Waveforms require audio-capable media")
        if existing.get("cache_key") == key and output.is_file():
            return {"ok": True, "cached": True, "asset": self._public_asset(project_id, asset), "derivative": existing}
        try:
            executable = ensure_ffmpeg(self.ffmpeg_path)
        except RuntimeError as exc:
            raise HTTPException(503, f"Media derivative generation failed: {exc}") from exc
        output.parent.mkdir(parents=True, exist_ok=True)
        pcm = output.with_name(f".{output.stem}.{uuid.uuid4().hex}.pcm")
        try:
            self._run([
                executable, "-y", "-v", "error", "-i", str(source), "-vn", "-ac", "1",
                "-ar", "8000", "-f", "s16le", str(pcm),
            ], 120)
            sample_count = pcm.stat().st_size // 2 if pcm.is_file() else 0
            if not sample_count:
                raise HTTPException(422, "No audio samples were decoded")
            peaks = _waveform_peaks(pcm, sample_count, bins)
        finally:
            pcm.unlink(missing_ok=True)
        payload = {"schema_version": 1, "asset_id": asset_id, "bins": len(peaks), "peaks": peaks}
        self._atomic_bytes(output, json.dumps(payload, separators=(",", ":")).encode())
        derivative = {"status": "ready", "cache_key": key, "path": _relative(output, self.store.project_dir(project_id)), "bins": len(peaks)}
        return self._record_derivative(project_id, asset_id, "waveform", derivative)

    def thumbnail(self, project_id: str, asset_id: str, width: int = 640) -> dict[str, Any]:
        return self._visual(project_id, asset_id, "thumbnail", min(1920, max(64, int(width))))

    def proxy(self, project_id: str, asset_id: str, width: int = 1280) -> dict[str, Any]:
        return self._visual(project_id, asset_id, "proxy", min(1920, max(320, int(width))))

    def _visual(self, project_id: str, asset_id: str, name: str, width: int) -> dict[str, Any]:
        project = self._project(project_id)
        asset = self._find(project.meta, asset_id)
        allowed = {"video", "image"} if name == "thumbnail" else {"video", "audio"}
        if asset.get("kind") not in allowed:
            raise HTTPException(409, f"{name.title()} is not supported for this media type")
        suffix = ".jpg" if name == "thumbnail" else (".m4a" if asset.get("kind") == "audio" else ".mp4")
        _, asset, source, key, output, existing = self._derivative_context(project_id, asset_id, name, str(width), suffix)
        if existing.get("cache_key") == key and output.is_file():
            return {"ok": True, "cached": True, "asset": self._public_asset(project_id, asset), "derivative": existing}
        try:
            executable = ensure_ffmpeg(self.ffmpeg_path)
        except RuntimeError as exc:
            raise HTTPException(503, f"Media derivative generation failed: {exc}") from exc
        output.parent.mkdir(parents=True, exist_ok=True)
        temporary = output.with_name(f".{output.stem}.{uuid.uuid4().hex}{output.suffix}")
        command = [executable, "-y", "-v", "error", "-i", str(source)]
        if name == "thumbnail":
            command.extend(["-frames:v", "1", "-vf", f"scale={width}:-2", str(temporary)])
        elif asset.get("kind") == "audio":
            command.extend(["-vn", "-c:a", "aac", "-b:a", "192k", str(temporary)])
        else:
            command.extend(["-vf", f"scale={width}:-2", "-c:v", "libx264", "-preset", "veryfast", "-crf", "28", "-c:a", "aac", "-movflags", "+faststart", str(temporary)])
        try:
            self._run(command, 600)
            if not temporary.is_file():
                raise HTTPException(422, "Media derivative generation did not produce an output file")
            os.replace(temporary, output)
        finally:
            temporary.unlink(missing_ok=True)
        derivative = {"status": "ready", "cache_key": key, "path": _relative(output, self.store.project_dir(project_id)), "width": width, "size_bytes": output.stat().st_size}
        return self._record_derivative(project_id, asset_id, name, derivative)

    @staticmethod
    def _atomic_bytes(output: Path, content: bytes) -> None:
        output.parent.mkdir(parents=True, exist_ok=True)
        temporary = output.with_name(f".{output.name}.{uuid.uuid4().hex}.tmp")
        try:
            with temporary.open("xb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, output)
        finally:
            temporary.unlink(missing_ok=True)


def _number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _integer(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
