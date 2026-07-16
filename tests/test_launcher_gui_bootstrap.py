import importlib.util
import json
import sys
from pathlib import Path

import pytest


pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows-specific bootstrap path handling")
pytest.importorskip("tkinter")


def _load_launcher_gui():
    root = Path(__file__).resolve().parents[1]
    module_path = root / "studio" / "edmg-studio" / "tools" / "launcher_gui.py"
    spec = importlib.util.spec_from_file_location("launcher_gui_test_module", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_saved_path_if_usable_rejects_missing_windows_drive(monkeypatch):
    launcher_gui = _load_launcher_gui()

    monkeypatch.setattr(
        launcher_gui,
        "_windows_drive_usable",
        lambda path: not str(path).replace("/", "\\").upper().startswith("H:"),
    )
    monkeypatch.setattr(launcher_gui, "_discover_missing_drive_remaps", lambda _path: [])

    assert launcher_gui._saved_path_if_usable(r"H:\Repositories\DWCTGenerativeSoundStudio") is None


def test_discover_missing_drive_remaps_scans_mounted_hosts(monkeypatch, tmp_path):
    launcher_gui = _load_launcher_gui()
    host_root = tmp_path / "host_G"
    remapped = host_root / "Users" / "lanak" / "edmg-studio-home"
    remapped.mkdir(parents=True)

    monkeypatch.setattr(launcher_gui, "_available_windows_drive_letters", lambda: ["Z"])

    original_exists = Path.exists

    def fake_exists(self):
        normalized = str(self).replace("/", "\\").upper()
        if normalized in {"G:", "G:\\"}:
            return False
        if normalized == "Z:\\G" or normalized.startswith("Z:\\G\\"):
            relative = str(self).replace("/", "\\")[len("Z:\\G") :].lstrip("\\")
            probe = host_root / relative if relative else host_root
            return original_exists(probe)
        return original_exists(self)

    monkeypatch.setattr(Path, "exists", fake_exists, raising=False)

    found = launcher_gui._discover_missing_drive_remaps(Path(r"G:\Users\lanak\edmg-studio-home"))
    assert found == [Path(r"Z:\G\Users\lanak\edmg-studio-home")]
    assert launcher_gui._discover_missing_drive_remaps(Path(r"C:\G\Users\lanak\edmg-studio-home")) == []


def test_saved_path_if_usable_uses_discovered_remount(monkeypatch, tmp_path):
    launcher_gui = _load_launcher_gui()
    remapped = tmp_path / "Users" / "lanak" / "edmg-studio-home"
    remapped.mkdir(parents=True)

    monkeypatch.setattr(
        launcher_gui,
        "_windows_drive_usable",
        lambda path: not str(path).replace("/", "\\").upper().startswith("G:"),
    )
    monkeypatch.setattr(
        launcher_gui,
        "_discover_missing_drive_remaps",
        lambda path: [remapped] if str(path).upper().startswith("G:") else [],
    )

    usable = launcher_gui._saved_path_if_usable(r"G:\Users\lanak\edmg-studio-home")
    assert usable == remapped.resolve()


def test_ensure_data_dir_env_ignores_unreachable_saved_home(monkeypatch, tmp_path):
    launcher_gui = _load_launcher_gui()
    original_exists = launcher_gui.Path.exists

    def fake_exists(self):
        normalized = str(self).replace("/", "\\").upper()
        if normalized.rstrip("\\") == "H:" or normalized == "H:\\":
            return False
        if normalized.rstrip("\\") == "C:\\H" or normalized.startswith("C:\\H\\"):
            return False
        if normalized.rstrip("\\") == "E:\\H" or normalized.startswith("E:\\H\\"):
            return False
        return original_exists(self)

    bootstrap_path = tmp_path / "bootstrap.json"
    launcher_env_path = tmp_path / "launcher_env.json"
    bootstrap_path.write_text(json.dumps({"studioHome": r"H:\Repositories\DWCTGenerativeSoundStudio\studio\edmg-studio"}), encoding="utf-8")

    monkeypatch.setattr(launcher_gui.Path, "exists", fake_exists, raising=False)
    monkeypatch.setattr(launcher_gui, "LAUNCHER_ENV_PATH", launcher_env_path)
    monkeypatch.setattr(launcher_gui, "_bootstrap_config_path", lambda: bootstrap_path)
    monkeypatch.setattr(launcher_gui, "_available_windows_drive_letters", lambda: ["C", "E"])
    monkeypatch.delenv("EDMG_STUDIO_HOME", raising=False)
    monkeypatch.delenv("EDMG_STUDIO_DATA_DIR", raising=False)

    data_dir = launcher_gui._ensure_data_dir_env()

    assert data_dir == (launcher_gui.STUDIO_DIR / "data").resolve()

    persisted = json.loads(bootstrap_path.read_text(encoding="utf-8"))
    assert persisted["studioHome"] == str(launcher_gui.STUDIO_DIR.resolve())


def test_ensure_data_dir_env_ignores_unreachable_env_home(monkeypatch, tmp_path):
    """Regression: backend __init__ loads launcher_env into os.environ before Launcher runs."""
    launcher_gui = _load_launcher_gui()
    original_exists = launcher_gui.Path.exists

    def fake_exists(self):
        normalized = str(self).replace("/", "\\").upper()
        if normalized.rstrip("\\") == "G:" or normalized == "G:\\":
            return False
        if normalized.rstrip("\\") == "C:\\G" or normalized.startswith("C:\\G\\"):
            return False
        if normalized.rstrip("\\") == "E:\\G" or normalized.startswith("E:\\G\\"):
            return False
        return original_exists(self)

    bootstrap_path = tmp_path / "bootstrap.json"
    launcher_env_path = tmp_path / "launcher_env.json"
    bootstrap_path.write_text("{}", encoding="utf-8")
    launcher_env_path.write_text("{}", encoding="utf-8")

    monkeypatch.setattr(launcher_gui.Path, "exists", fake_exists, raising=False)
    monkeypatch.setattr(launcher_gui, "LAUNCHER_ENV_PATH", launcher_env_path)
    monkeypatch.setattr(launcher_gui, "_bootstrap_config_path", lambda: bootstrap_path)
    monkeypatch.setattr(launcher_gui, "_available_windows_drive_letters", lambda: ["C", "E"])
    monkeypatch.setenv("EDMG_STUDIO_HOME", r"G:\Users\lanak\edmg-studio-home")
    monkeypatch.delenv("EDMG_STUDIO_DATA_DIR", raising=False)

    data_dir = launcher_gui._ensure_data_dir_env()

    assert data_dir == (launcher_gui.STUDIO_DIR / "data").resolve()
    persisted_env = json.loads(launcher_env_path.read_text(encoding="utf-8"))
    assert persisted_env["EDMG_STUDIO_HOME"] == str(launcher_gui.STUDIO_DIR.resolve())


def test_ensure_data_dir_env_persists_discovered_remount(monkeypatch, tmp_path):
    """Once a missing drive is discovered under another host, persist that path."""
    launcher_gui = _load_launcher_gui()
    remapped_home = tmp_path / "remount" / "Users" / "lanak" / "edmg-studio-home"
    remapped_home.mkdir(parents=True)

    bootstrap_path = tmp_path / "bootstrap.json"
    launcher_env_path = tmp_path / "launcher_env.json"
    bootstrap_path.write_text("{}", encoding="utf-8")
    launcher_env_path.write_text("{}", encoding="utf-8")

    monkeypatch.setattr(launcher_gui, "LAUNCHER_ENV_PATH", launcher_env_path)
    monkeypatch.setattr(launcher_gui, "_bootstrap_config_path", lambda: bootstrap_path)
    monkeypatch.setattr(
        launcher_gui,
        "_windows_drive_usable",
        lambda path: not str(path).replace("/", "\\").upper().startswith("G:"),
    )
    monkeypatch.setattr(
        launcher_gui,
        "_discover_missing_drive_remaps",
        lambda path: [remapped_home] if str(path).upper().startswith("G:") else [],
    )
    monkeypatch.setenv("EDMG_STUDIO_HOME", r"G:\Users\lanak\edmg-studio-home")
    monkeypatch.delenv("EDMG_STUDIO_DATA_DIR", raising=False)

    data_dir = launcher_gui._ensure_data_dir_env()

    assert data_dir == (remapped_home / "data").resolve()
    persisted_env = json.loads(launcher_env_path.read_text(encoding="utf-8"))
    assert persisted_env["EDMG_STUDIO_HOME"] == str(remapped_home.resolve())
    persisted_bootstrap = json.loads(bootstrap_path.read_text(encoding="utf-8"))
    assert persisted_bootstrap["studioHome"] == str(remapped_home.resolve())


def test_launcher_accepts_only_python_312_for_the_locked_backend():
    launcher_gui = _load_launcher_gui()

    assert launcher_gui._is_supported_python_version((3, 12, 0))
    assert launcher_gui._is_supported_python_version((3, 12, 99))
    assert not launcher_gui._is_supported_python_version((3, 11, 9))
    assert not launcher_gui._is_supported_python_version((3, 13, 0))


def test_sync_locked_backend_uses_one_fixed_profile_and_capability_set(monkeypatch):
    launcher_gui = _load_launcher_gui()
    calls = {}

    def fake_sync(profile, *, capability_extras, install_uv):
        calls["sync"] = (profile, tuple(capability_extras), install_uv)
        return Path(r"C:\toolchain\uv.exe")

    def fake_run(profile, command, *, capability_extras):
        calls["run"] = (profile, tuple(command), tuple(capability_extras))
        return ["uv", "run", "--frozen", "python", "-c", "verify"], {"PROFILE": profile}

    monkeypatch.setattr(launcher_gui, "sync_frozen_project", fake_sync)
    monkeypatch.setattr(launcher_gui, "frozen_run_command", fake_run)
    monkeypatch.setattr(launcher_gui, "uv_version", lambda _uv: "0.11.28")
    monkeypatch.setattr(launcher_gui, "lock_sha256", lambda: "a" * 64)
    monkeypatch.setattr(launcher_gui, "_run_cmd", lambda *args, **kwargs: 0)

    launcher_gui._sync_locked_backend("cuda", lambda _message: None)

    assert calls["sync"][0] == "cuda"
    assert "core" in calls["sync"][1]
    assert calls["run"][0] == "cuda"
