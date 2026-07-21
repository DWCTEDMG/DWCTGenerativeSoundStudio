from __future__ import annotations

import socket
import threading
import time
from dataclasses import dataclass, field
from typing import Any

_sessions: dict[str, "LivePublishSession"] = {}
_lock = threading.Lock()


def _osc_encode_message(address: str, args: list[Any]) -> bytes:
    """Minimal OSC bundle payload for section/beat/energy cues."""
    addr = (address or "/edmg/cue").encode("utf-8") + b"\x00"
    pad_addr = addr + b"\x00" * ((4 - len(addr) % 4) % 4)
    type_tags = b"," + b"".join(b"f" if isinstance(arg, (int, float)) else b"s" for arg in args)
    type_tags += b"\x00" * ((4 - len(type_tags) % 4) % 4)
    payload = pad_addr + type_tags
    for arg in args:
        if isinstance(arg, (int, float)):
            import struct

            payload += struct.pack(">f", float(arg))
        else:
            raw = str(arg).encode("utf-8") + b"\x00"
            payload += raw + b"\x00" * ((4 - len(raw) % 4) % 4)
    return payload


@dataclass
class LivePublishSession:
    project_id: str
    started_at: float
    osc_host: str
    osc_port: int
    midi_enabled: bool
    websocket_enabled: bool
    events: list[dict[str, Any]] = field(default_factory=list)
    sent_count: int = 0
    midi_events: list[dict[str, Any]] = field(default_factory=list)
    websocket_events: list[dict[str, Any]] = field(default_factory=list)
    last_error: str | None = None
    stop_requested: bool = False
    thread: threading.Thread | None = None

    def publish_event(self, event: dict[str, Any]) -> None:
        osc = event.get("osc") if isinstance(event.get("osc"), dict) else {}
        address = str(osc.get("address") or "/edmg/cue")
        args = list(osc.get("args") or [])
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.sendto(_osc_encode_message(address, args), (self.osc_host, self.osc_port))
            sock.close()
        except OSError as exc:
            self.last_error = str(exc)
        self.sent_count += 1
        if self.midi_enabled:
            midi = event.get("midi") if isinstance(event.get("midi"), dict) else {}
            if midi:
                self.midi_events.append({"t": event.get("t"), **midi})
        if self.websocket_enabled:
            ws = event.get("ws") if isinstance(event.get("ws"), dict) else {}
            if ws:
                self.websocket_events.append({"t": event.get("t"), **ws})


def _playback_loop(session: LivePublishSession) -> None:
    cursor = 0.0
    start = time.monotonic()
    events = list(session.events)
    while not session.stop_requested and cursor <= max((float(item.get("t") or 0.0) for item in events), default=0.0) + 0.05:
        now = time.monotonic() - start
        while cursor <= now and events:
            event = events[0]
            event_time = float(event.get("t") or 0.0)
            if event_time > now:
                break
            session.publish_event(events.pop(0))
            cursor = event_time
        time.sleep(0.01)
    with _lock:
        _sessions.pop(session.project_id, None)


def start_live_publish(
    project_id: str,
    live_cues: dict[str, Any],
    *,
    osc_host: str = "127.0.0.1",
    osc_port: int = 9000,
    midi_enabled: bool = True,
    websocket_enabled: bool = True,
    playback_speed: float = 1.0,
) -> dict[str, Any]:
    events = [item for item in list(live_cues.get("events") or []) if isinstance(item, dict)]
    events = sorted(events, key=lambda item: float(item.get("t") or 0.0))
    if playback_speed <= 0:
        playback_speed = 1.0
    if playback_speed != 1.0:
        for event in events:
            event["t"] = float(event.get("t") or 0.0) / playback_speed
    with _lock:
        existing = _sessions.get(project_id)
        if existing and existing.thread and existing.thread.is_alive():
            existing.stop_requested = True
        session = LivePublishSession(
            project_id=project_id,
            started_at=time.time(),
            osc_host=str(osc_host or "127.0.0.1"),
            osc_port=int(osc_port or 9000),
            midi_enabled=bool(midi_enabled),
            websocket_enabled=bool(websocket_enabled),
            events=events,
        )
        thread = threading.Thread(target=_playback_loop, args=(session,), daemon=True)
        session.thread = thread
        _sessions[project_id] = session
        thread.start()
    return publish_status(project_id)


def stop_live_publish(project_id: str) -> dict[str, Any]:
    with _lock:
        session = _sessions.get(project_id)
        if session:
            session.stop_requested = True
    return publish_status(project_id)


def publish_status(project_id: str) -> dict[str, Any]:
    with _lock:
        session = _sessions.get(project_id)
    if not session:
        return {
            "ok": True,
            "running": False,
            "project_id": project_id,
            "sent_count": 0,
            "midi_events": [],
            "websocket_events": [],
        }
    running = bool(session.thread and session.thread.is_alive() and not session.stop_requested)
    return {
        "ok": True,
        "running": running,
        "project_id": project_id,
        "started_at": session.started_at,
        "osc_target": f"{session.osc_host}:{session.osc_port}",
        "midi_enabled": session.midi_enabled,
        "websocket_enabled": session.websocket_enabled,
        "sent_count": session.sent_count,
        "remaining_events": len(session.events),
        "last_error": session.last_error,
        "midi_events": session.midi_events[-32:],
        "websocket_events": session.websocket_events[-32:],
        "experimental": True,
    }
