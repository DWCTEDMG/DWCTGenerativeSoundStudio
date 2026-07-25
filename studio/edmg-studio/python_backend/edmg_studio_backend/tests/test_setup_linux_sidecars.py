from __future__ import annotations

from pathlib import Path

from edmg_studio_backend.services import setup_wizard


def _linux(monkeypatch):
    monkeypatch.setattr(setup_wizard.platform, "system", lambda: "Linux")
    monkeypatch.setattr(setup_wizard.shutil, "which", lambda name: "/bin/bash" if name == "bash" else None)


def test_linux_ollama_setup_routes_through_bundled_sidecar_script(tmp_path, monkeypatch) -> None:
    _linux(monkeypatch)
    captured: dict[str, object] = {}

    def fake_run(task, args, *, cwd=None, env=None, creationflags=0):
        captured["args"] = args
        captured["cwd"] = cwd
        captured["env"] = env

    monkeypatch.setattr(setup_wizard, "_run_subprocess", fake_run)

    task = setup_wizard.SetupTask(id="task", name="ollama")
    studio_home = tmp_path / "EDMG-Studio"
    setup_wizard.download_and_install_ollama(
        task,
        studio_home / "external" / "_installers",
        studio_home / "external",
        studio_home / "models",
        "http://127.0.0.1:12345",
    )

    args = captured["args"]
    env = captured["env"]
    assert isinstance(args, list)
    assert isinstance(env, dict)
    assert args[0] == "/bin/bash"
    assert Path(args[1]).name == "setup_linux_ollama.sh"
    assert env["EDMG_STUDIO_HOME"] == str(studio_home)
    assert env["OLLAMA_MODELS"] == str(studio_home / "models" / "ollama")
    assert env["EDMG_AI_OLLAMA_URL"] == "http://127.0.0.1:12345"
    assert env["OLLAMA_PORT"] == "12345"
    assert env["OLLAMA_PULL_MODEL"] == "0"


def test_linux_comfyui_install_routes_through_bundled_sidecar_script(tmp_path, monkeypatch) -> None:
    _linux(monkeypatch)
    captured: dict[str, object] = {}

    def fake_run(task, args, *, cwd=None, env=None, creationflags=0):
        captured["args"] = args
        captured["cwd"] = cwd
        captured["env"] = env

    monkeypatch.setattr(setup_wizard, "_run_subprocess", fake_run)

    task = setup_wizard.SetupTask(id="task", name="comfy")
    studio_home = tmp_path / "EDMG-Studio"
    root = setup_wizard.download_and_extract_portable(
        task,
        studio_home / "external",
        "nvidia",
        studio_home / "data",
        studio_home / "models",
    )

    args = captured["args"]
    env = captured["env"]
    assert root == studio_home / "external" / "ComfyUI"
    assert isinstance(args, list)
    assert isinstance(env, dict)
    assert args[0] == "/bin/bash"
    assert Path(args[1]).name == "setup_linux_comfyui.sh"
    assert env["EDMG_STUDIO_HOME"] == str(studio_home)
    assert env["COMFY_ROOT"] == str(studio_home / "external" / "ComfyUI")
    assert env["COMFY_PYTHON_BIN"]
    assert env["COMFY_START"] == "0"
    assert env["COMFY_INSTALL_MODELS"] == "0"


def test_linux_comfyui_installed_detection_uses_sidecar_layout(tmp_path, monkeypatch) -> None:
    _linux(monkeypatch)
    external_dir = tmp_path / "EDMG-Studio" / "external"

    assert setup_wizard.comfy_portable_installed(external_dir) is False

    root = external_dir / "ComfyUI"
    root.mkdir(parents=True)
    (root / "main.py").write_text("print('comfy')\n", encoding="utf-8")

    assert setup_wizard.comfy_portable_root(external_dir) == root
    assert setup_wizard.comfy_portable_installed(external_dir) is True
