"""Restricted host-side GPU lease broker for EDMG A100 deployments."""
from __future__ import annotations

import concurrent.futures
import json
import logging
from pathlib import Path
import socket
import os
import subprocess
import threading
import time
import urllib.request

SOCKET = "/srv/edmg/data/.gpu-coordinator.sock"
RESIDENT = "nemotron-vllm"
LOCK = threading.Lock()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")


def docker(*args: str) -> str:
    return subprocess.run(["docker", *args], check=True, capture_output=True, text=True, timeout=120).stdout.strip()


def resident_exists() -> bool:
    return subprocess.run(["docker", "container", "inspect", RESIDENT], capture_output=True, timeout=15).returncode == 0


def restore() -> None:
    if not resident_exists():
        return
    docker("start", RESIDENT)
    address = docker("inspect", "--format", "{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}", RESIDENT)
    deadline = time.monotonic() + 1200
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(f"http://{address}:8000/health", timeout=3) as response:
                if response.status == 200:
                    return
        except Exception:
            time.sleep(2)
    raise RuntimeError("Resident Director did not become ready within 20 minutes")


def serve(client: socket.socket) -> None:
    suspended = False
    with client:
        try:
            request = json.loads(client.makefile("rb").readline(1024))
            mode = request.get("mode")
            if mode not in {"render", "director"}:
                raise ValueError("Invalid lease mode")
            with LOCK:
                if mode == "render" and resident_exists():
                    suspended = True
                    logging.info("Render lease: stopping resident Director")
                    docker("stop", "--time", "30", RESIDENT)
                    free = subprocess.run(["nvidia-smi", "--query-gpu=memory.free", "--format=csv,noheader,nounits"], check=True, capture_output=True, text=True, timeout=15).stdout.splitlines()
                    if not free or int(free[0].strip()) < 60000:
                        raise RuntimeError("Less than 60000 MiB free after releasing resident Director")
                elif mode == "director":
                    restore()
                client.sendall(b'{"ready":true}\n')
                while client.recv(1024):
                    pass
        except Exception:
            logging.exception("GPU handoff error")
            try:
                client.sendall(b'{"ready":false,"error":"See gpu-coordinator service log"}\n')
            except OSError as exc:
                logging.debug("Client disconnected before error response: %s", exc)
        finally:
            if suspended:
                try:
                    logging.info("Render lease released: restoring resident Director")
                    restore()
                except Exception:
                    logging.exception("Could not restore resident Director")


def main() -> None:
    path = Path(SOCKET)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.unlink(missing_ok=True)
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
        server.bind(SOCKET)
        os.chown(SOCKET, 10001, 10001)
        os.chmod(SOCKET, 0o600)
        server.listen(16)
        with concurrent.futures.ThreadPoolExecutor(max_workers=16) as pool:
            while True:
                client, _ = server.accept()
                pool.submit(serve, client)


if __name__ == "__main__":
    main()
