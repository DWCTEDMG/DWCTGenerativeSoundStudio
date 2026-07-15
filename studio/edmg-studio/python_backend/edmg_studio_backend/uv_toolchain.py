from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import platform
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
import zipfile
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

UV_REQUIRED_VERSION = "0.11.28"
PYTHON_REQUIRED_MINOR = (3, 12)
ACCELERATOR_PROFILES = ("cpu", "directml", "cuda")
RUNTIME_CAPABILITY_EXTRAS = ("core", "audio", "asr", "internal-video", "aws")
TORCH_INDEXES = {
    "cpu": "https://download.pytorch.org/whl/cpu",
    "directml": "https://download.pytorch.org/whl/cpu",
    "cuda": "https://download.pytorch.org/whl/cu130",
}

_UV_ARCHIVES: dict[tuple[str, str], tuple[str, str]] = {
    ("Windows", "x86_64"): (
        "uv-x86_64-pc-windows-msvc.zip",
        "0a23463216d09c6a72ff80ef5dc5a795f07dc1575cb84d24596c2f124a441b7b",
    ),
    ("Windows", "aarch64"): (
        "uv-aarch64-pc-windows-msvc.zip",
        "3248109afad3ec59baad299d324ff53de17e2d9a3b3e21580ffd26744b11e036",
    ),
    ("Linux", "x86_64"): (
        "uv-x86_64-unknown-linux-gnu.tar.gz",
        "e490a6464492183c5d4534a5527fb4440f7f2bb2f228162ad7e4afe076dc0224",
    ),
    ("Linux", "aarch64"): (
        "uv-aarch64-unknown-linux-gnu.tar.gz",
        "03e9fe0a81b0718d0bc84625de3885df6cc3f89a8b6af6121d6b9f6113fb6533",
    ),
    ("Darwin", "x86_64"): (
        "uv-x86_64-apple-darwin.tar.gz",
        "2ad79983127ffca7d77b77ce6a24278d7e4f7b817a1acf72fea5f8124b4aac5e",
    ),
    ("Darwin", "aarch64"): (
        "uv-aarch64-apple-darwin.tar.gz",
        "33540eb7c883ab857eff79bd5ac2aa31fe27b595abecb4a9c003a2c998447232",
    ),
}

_LEGACY_BUNDLE_PROFILES = {
    "": None,
    "studio_bundle": None,
    "full": None,
    "studio_bundle_directml": "directml",
    "directml": "directml",
    "studio_bundle_cuda": "cuda",
    "cuda": "cuda",
    "cpu": "cpu",
}


class ToolchainError(RuntimeError):
    """A deterministic Studio toolchain requirement was not met."""


def backend_root() -> Path:
    return Path(__file__).resolve().parents[1]


def repository_root() -> Path:
    return backend_root().parents[2]


def is_packaged_backend() -> bool:
    return bool(getattr(sys, "frozen", False))


def normalize_accelerator_profile(value: str | None) -> str:
    profile = str(value or "").strip().lower()
    aliases = {"nvidia": "cuda", "amd": "directml"}
    profile = aliases.get(profile, profile)
    if profile not in ACCELERATOR_PROFILES:
        allowed = ", ".join(ACCELERATOR_PROFILES)
        raise ToolchainError(
            f"Unsupported accelerator profile {value!r}. Choose exactly one of: {allowed}."
        )
    if profile == "directml" and platform.system() != "Windows":
        raise ToolchainError("The directml profile is supported only on Windows.")
    return profile


def profile_from_legacy_inputs(
    *,
    profile: str | None = None,
    bundle: str | None = None,
    flavor: str | None = None,
) -> str:
    if str(profile or "").strip():
        return normalize_accelerator_profile(profile)

    normalized_bundle = str(bundle or "").strip().lower().replace("-", "_")
    if normalized_bundle not in _LEGACY_BUNDLE_PROFILES:
        raise ToolchainError(
            f"Unsupported legacy backend bundle {bundle!r}. Use accelerator_profile=cpu, directml, or cuda."
        )
    bundle_profile = _LEGACY_BUNDLE_PROFILES[normalized_bundle]
    normalized_flavor = str(flavor or "cpu").strip().lower()
    flavor_profile = {
        "nvidia": "cuda",
        "cuda": "cuda",
        "amd": "directml",
        "directml": "directml",
    }.get(
        normalized_flavor,
        "cpu" if normalized_flavor == "cpu" else None,
    )
    if flavor_profile is None:
        raise ToolchainError(f"Unsupported backend flavor {flavor!r}. Use cpu, directml, or cuda.")
    resolved = bundle_profile or flavor_profile
    if bundle_profile and flavor_profile != "cpu" and bundle_profile != flavor_profile:
        raise ToolchainError(
            f"Conflicting backend selections: bundle {bundle!r} maps to {bundle_profile}, "
            f"while flavor {flavor!r} maps to {flavor_profile}."
        )
    return normalize_accelerator_profile(resolved)


def active_accelerator_profile(default: str = "cpu") -> str:
    raw = os.getenv("EDMG_BACKEND_ACCELERATOR_PROFILE", default)
    return normalize_accelerator_profile(raw)


def lock_sha256(path: Path | None = None) -> str:
    lock_path = path or (backend_root() / "uv.lock")
    if not lock_path.is_file():
        return ""
    return hashlib.sha256(lock_path.read_bytes()).hexdigest()


def _normalized_machine() -> str:
    machine = platform.machine().strip().lower()
    if machine in {"amd64", "x64", "x86_64"}:
        return "x86_64"
    if machine in {"arm64", "aarch64"}:
        return "aarch64"
    return machine


def _managed_uv_root() -> Path:
    override = os.getenv("EDMG_UV_INSTALL_ROOT", "").strip()
    if override:
        return Path(override).expanduser().resolve() / UV_REQUIRED_VERSION
    if os.name == "nt":
        base = Path(os.getenv("LOCALAPPDATA") or (Path.home() / "AppData" / "Local"))
    else:
        base = Path(os.getenv("XDG_CACHE_HOME") or (Path.home() / ".cache"))
    return base / "EDMG Studio" / "toolchain" / "uv" / UV_REQUIRED_VERSION


def managed_uv_path() -> Path:
    return _managed_uv_root() / ("uv.exe" if os.name == "nt" else "uv")


def uv_version(command: str | Path) -> str:
    try:
        result = subprocess.run(
            [str(command), "--version"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except OSError:
        return ""
    if result.returncode != 0:
        return ""
    raw = str(result.stdout or result.stderr or "").strip()
    prefix = "uv "
    return raw[len(prefix) :].split()[0] if raw.startswith(prefix) else ""


def _candidate_uv_commands() -> list[Path]:
    candidates: list[Path] = []
    explicit = os.getenv("EDMG_UV_BIN", "").strip()
    if explicit:
        candidates.append(Path(explicit).expanduser())
    candidates.append(managed_uv_path())
    discovered = shutil.which("uv")
    if discovered:
        candidates.append(Path(discovered))
    unique: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = os.path.normcase(str(candidate.resolve(strict=False)))
        if key not in seen:
            seen.add(key)
            unique.append(candidate)
    return unique


def _validated_archive_target(root: Path, member_name: str) -> Path:
    target = (root / member_name).resolve()
    try:
        target.relative_to(root.resolve())
    except ValueError as exc:
        raise ToolchainError(
            f"Pinned uv archive contains an unsafe path: {member_name!r}."
        ) from exc
    return target


def _extract_uv_archive(archive_path: Path, destination: Path) -> None:
    """Extract the checksum-pinned uv archive without path traversal or links."""
    if archive_path.name.endswith(".zip"):
        with zipfile.ZipFile(archive_path) as archive:
            for member in archive.infolist():
                _validated_archive_target(destination, member.filename)
                # Unix symlinks can be represented in a zip's external mode.
                if ((member.external_attr >> 16) & 0o170000) == 0o120000:
                    raise ToolchainError(
                        f"Pinned uv archive contains a symbolic link: {member.filename!r}."
                    )
            archive.extractall(destination)
        return

    with tarfile.open(archive_path, "r:gz") as archive:
        for member in archive.getmembers():
            _validated_archive_target(destination, member.name)
            if member.issym() or member.islnk():
                raise ToolchainError(f"Pinned uv archive contains a link: {member.name!r}.")
        # Members were validated above. Avoid the Python 3.12-only `filter=`
        # argument because the stdlib bootstrap launcher also supports older
        # host interpreters while uv acquires the pinned Python 3.12 runtime.
        archive.extractall(destination)


def resolve_uv(*, install: bool = False) -> Path:
    wrong_versions: list[str] = []
    for candidate in _candidate_uv_commands():
        version = uv_version(candidate)
        if version == UV_REQUIRED_VERSION:
            return candidate.resolve()
        if version:
            wrong_versions.append(f"{candidate} ({version})")

    if install:
        installed = install_pinned_uv()
        version = uv_version(installed)
        if version == UV_REQUIRED_VERSION:
            return installed.resolve()
        raise ToolchainError(
            f"Installed uv at {installed}, but it reported version {version or 'unknown'}."
        )

    detail = f" Found incompatible versions: {', '.join(wrong_versions)}." if wrong_versions else ""
    raise ToolchainError(
        f"EDMG Studio requires uv {UV_REQUIRED_VERSION}, but that exact version was not found.{detail} "
        "Run the source launcher to install the pinned toolchain or set EDMG_UV_BIN."
    )


def install_pinned_uv() -> Path:
    key = (platform.system(), _normalized_machine())
    archive_info = _UV_ARCHIVES.get(key)
    if archive_info is None:
        raise ToolchainError(
            f"No pinned uv bootstrap artifact is configured for {key[0]} {key[1]}. "
            f"Install uv {UV_REQUIRED_VERSION} manually and set EDMG_UV_BIN."
        )
    archive_name, expected_sha256 = archive_info
    destination = managed_uv_path()
    if destination.is_file() and uv_version(destination) == UV_REQUIRED_VERSION:
        return destination

    destination.parent.mkdir(parents=True, exist_ok=True)
    url = f"https://github.com/astral-sh/uv/releases/download/{UV_REQUIRED_VERSION}/{archive_name}"
    with tempfile.TemporaryDirectory(prefix="edmg-uv-bootstrap-") as raw_tmp:
        temp_root = Path(raw_tmp)
        archive_path = temp_root / archive_name
        try:
            with (
                urllib.request.urlopen(url, timeout=120) as response,
                archive_path.open("wb") as output,
            ):
                shutil.copyfileobj(response, output)
        except Exception as exc:  # pragma: no cover - network failures are environment-specific
            raise ToolchainError(
                f"Could not download pinned uv {UV_REQUIRED_VERSION} from {url}: {exc}"
            ) from exc

        actual_sha256 = hashlib.sha256(archive_path.read_bytes()).hexdigest()
        if actual_sha256 != expected_sha256:
            raise ToolchainError(
                f"Pinned uv archive checksum mismatch for {archive_name}: "
                f"expected {expected_sha256}, got {actual_sha256}."
            )

        extract_root = temp_root / "extract"
        extract_root.mkdir()
        _extract_uv_archive(archive_path, extract_root)

        executable_name = "uv.exe" if os.name == "nt" else "uv"
        matches = [path for path in extract_root.rglob(executable_name) if path.is_file()]
        if len(matches) != 1:
            raise ToolchainError(
                f"Pinned uv archive {archive_name} contained {len(matches)} matching executables; expected one."
            )
        temporary_destination = destination.with_suffix(destination.suffix + ".tmp")
        shutil.copy2(matches[0], temporary_destination)
        if os.name != "nt":
            temporary_destination.chmod(temporary_destination.stat().st_mode | stat.S_IXUSR)
        temporary_destination.replace(destination)
    return destination


def _selected_extras(profile: str, capability_extras: Iterable[str]) -> list[str]:
    selected = [normalize_accelerator_profile(profile)]
    for extra in capability_extras:
        normalized = str(extra).strip().lower().replace("_", "-")
        if normalized and normalized not in selected:
            selected.append(normalized)
    return selected


def frozen_project_args(
    action: str,
    profile: str,
    *,
    capability_extras: Iterable[str] = RUNTIME_CAPABILITY_EXTRAS,
    groups: Iterable[str] = (),
) -> list[str]:
    if action not in {"sync", "run"}:
        raise ValueError(f"Unsupported uv project action: {action}")
    args = [action, "--frozen", "--no-default-groups"]
    for extra in _selected_extras(profile, capability_extras):
        args.extend(["--extra", extra])
    for group in groups:
        args.extend(["--group", str(group)])
    return args


def toolchain_environment(base: Mapping[str, str] | None = None, *, profile: str) -> dict[str, str]:
    env = dict(base or os.environ)
    env["EDMG_BACKEND_ACCELERATOR_PROFILE"] = normalize_accelerator_profile(profile)
    env["NVIDIA_TENSORRT_DISABLE_INTERNAL_PIP"] = "1"
    return env


def run_checked(
    command: Sequence[str | Path],
    *,
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
    capture_output: bool = False,
    timeout: float | None = None,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        [str(part) for part in command],
        cwd=str(cwd or backend_root()),
        env=dict(env) if env is not None else None,
        text=True,
        capture_output=capture_output,
        timeout=timeout,
        check=False,
    )
    if result.returncode != 0:
        output = "\n".join(
            part.strip() for part in (result.stdout or "", result.stderr or "") if part.strip()
        )
        suffix = f"\n{output}" if output else ""
        raise ToolchainError(
            f"Command failed ({result.returncode}): {' '.join(map(str, command))}{suffix}"
        )
    return result


def sync_frozen_project(
    profile: str,
    *,
    capability_extras: Iterable[str] = RUNTIME_CAPABILITY_EXTRAS,
    groups: Iterable[str] = (),
    install_uv: bool = True,
) -> Path:
    if is_packaged_backend():
        raise ToolchainError(
            "This installed EDMG Studio backend is self-contained and cannot mutate Python dependencies. "
            "Install an application build created for the required accelerator profile."
        )
    resolved_profile = normalize_accelerator_profile(profile)
    uv = resolve_uv(install=install_uv)
    env = toolchain_environment(profile=resolved_profile)
    run_checked([uv, "lock", "--check"], cwd=backend_root(), env=env)
    run_checked(
        [
            uv,
            *frozen_project_args(
                "sync", resolved_profile, capability_extras=capability_extras, groups=groups
            ),
        ],
        cwd=backend_root(),
        env=env,
    )
    return uv


def frozen_run_command(
    profile: str,
    command: Sequence[str],
    *,
    capability_extras: Iterable[str] = RUNTIME_CAPABILITY_EXTRAS,
    groups: Iterable[str] = (),
    install_uv: bool = False,
) -> tuple[list[str], dict[str, str]]:
    resolved_profile = normalize_accelerator_profile(profile)
    uv = resolve_uv(install=install_uv)
    args = [
        str(uv),
        *frozen_project_args(
            "run", resolved_profile, capability_extras=capability_extras, groups=groups
        ),
        *map(str, command),
    ]
    return args, toolchain_environment(profile=resolved_profile)


def _installed_version(name: str) -> str:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return ""


def _packaged_manifest() -> dict[str, Any] | None:
    if not is_packaged_backend():
        return None
    candidates = [
        Path(sys.executable).resolve().parent / "backend-bundle-manifest.json",
        Path(sys.executable).resolve().parent.parent / "backend-bundle-manifest.json",
    ]
    for candidate in candidates:
        try:
            payload = json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            continue
        if isinstance(payload, dict):
            return payload
    return None


def toolchain_status(*, profile: str | None = None, check_sync: bool = True) -> dict[str, Any]:
    packaged = is_packaged_backend()
    if packaged:
        manifest = _packaged_manifest() or {}
        return {
            "ok": bool(manifest),
            "packaged": True,
            "immutable": True,
            "python_version": str(manifest.get("pythonVersion") or platform.python_version()),
            "uv_version": str(manifest.get("uvVersion") or "build-time only"),
            "lock_sha256": str(manifest.get("lockSha256") or ""),
            "accelerator_profile": str(manifest.get("acceleratorProfile") or "unknown"),
            "capability_extras": list(manifest.get("capabilityExtras") or []),
            "torch_packages": list(manifest.get("torchPackages") or []),
            "torch_index": str(manifest.get("torchIndex") or ""),
            "pyinstaller_version": str(manifest.get("pyinstallerVersion") or ""),
            "lock_check": "embedded-manifest" if manifest else "missing-manifest",
            "sync_health": "bundled" if manifest else "unknown",
            "hint": (
                "Backend dependencies are bundled into this application; uv and Python are not required at runtime."
                if manifest
                else "The packaged backend provenance manifest is missing. Reinstall EDMG Studio."
            ),
        }

    resolved_profile = normalize_accelerator_profile(
        profile or os.getenv("EDMG_BACKEND_ACCELERATOR_PROFILE", "cpu")
    )
    status: dict[str, Any] = {
        "ok": False,
        "packaged": False,
        "immutable": False,
        "python_version": platform.python_version(),
        "python_supported": sys.version_info[:2] == PYTHON_REQUIRED_MINOR,
        "uv_version": "",
        "uv_required_version": UV_REQUIRED_VERSION,
        "lock_sha256": lock_sha256(),
        "accelerator_profile": resolved_profile,
        "capability_extras": list(RUNTIME_CAPABILITY_EXTRAS),
        "torch_packages": [
            {
                "name": name,
                "version": _installed_version(name),
                "index": TORCH_INDEXES[resolved_profile],
            }
            for name in ("torch", "torchvision", "torchaudio")
        ],
        "torch_index": TORCH_INDEXES[resolved_profile],
        "pyinstaller_version": _installed_version("pyinstaller"),
        "lock_check": "failed",
        "sync_health": "unchecked" if not check_sync else "failed",
    }
    try:
        uv = resolve_uv(install=False)
        status["uv_version"] = uv_version(uv)
        env = toolchain_environment(profile=resolved_profile)
        run_checked(
            [uv, "lock", "--check"], cwd=backend_root(), env=env, capture_output=True, timeout=60
        )
        status["lock_check"] = "ok"
        if check_sync:
            sync_args = frozen_project_args("sync", resolved_profile)
            run_checked(
                [uv, *sync_args, "--check"],
                cwd=backend_root(),
                env=env,
                capture_output=True,
                timeout=60,
            )
            status["sync_health"] = "ok"
        status["ok"] = bool(
            status["python_supported"]
            and status["lock_sha256"]
            and status["lock_check"] == "ok"
            and (not check_sync or status["sync_health"] == "ok")
        )
    except ToolchainError as exc:
        status["error"] = str(exc)
        status["hint"] = (
            f"Run the source launcher or `uv sync --frozen --extra {resolved_profile}` from python_backend."
        )
    return status
