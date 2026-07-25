from __future__ import annotations

from typing import Any

WORLD_ADAPTER_SCHEMA_VERSION = "1.0"


def export_touchdesigner_adapter(live_cues: dict[str, Any]) -> dict[str, Any]:
    events = [item for item in list(live_cues.get("events") or []) if isinstance(item, dict)]
    table_rows = []
    for event in events:
        osc = event.get("osc") if isinstance(event.get("osc"), dict) else {}
        table_rows.append(
            {
                "time": float(event.get("t") or 0.0),
                "address": str(osc.get("address") or "/edmg/cue"),
                "args": list(osc.get("args") or []),
                "kind": str(event.get("kind") or "cue"),
            }
        )
    return {
        "schemaVersion": WORLD_ADAPTER_SCHEMA_VERSION,
        "adapter": "touchdesigner",
        "status": "simulator_ready",
        "ingest": "osc_table",
        "osc_addresses": list((live_cues.get("transports") or {}).get("osc") or []),
        "table": table_rows,
        "notes": ["Import table rows into a Time CHOP or OSC In DAT for rehearsal."],
    }


def export_unreal_adapter(live_cues: dict[str, Any], *, bridge: dict[str, Any] | None = None) -> dict[str, Any]:
    bridge = dict(bridge or {})
    events = [item for item in list(live_cues.get("events") or []) if isinstance(item, dict)]
    cues = []
    for event in events:
        ws = event.get("ws") if isinstance(event.get("ws"), dict) else {}
        cues.append(
            {
                "time_s": float(event.get("t") or 0.0),
                "cue_name": str(ws.get("type") or event.get("kind") or "cue"),
                "payload": ws or {"label": event.get("label"), "confidence": event.get("confidence")},
            }
        )
    return {
        "schemaVersion": WORLD_ADAPTER_SCHEMA_VERSION,
        "adapter": "unreal",
        "status": "simulator_ready",
        "ingest": "live_control_bridge",
        "bridge": {
            "sequence_name": str(bridge.get("sequence_name") or "EDMG_LiveSet"),
            "variant_index": int(bridge.get("variant_index") or 0),
        },
        "cues": cues,
        "notes": ["Pair with Unreal live_control_bridge export for world handoff."],
    }


def run_adapter_simulator(adapter: str, payload: dict[str, Any]) -> dict[str, Any]:
    name = str(adapter or "").strip().lower()
    if name == "touchdesigner":
        required = {"adapter", "table", "osc_addresses"}
    elif name == "unreal":
        required = {"adapter", "cues", "bridge"}
    else:
        return {"ok": False, "adapter": adapter, "errors": [f"Unsupported adapter: {adapter}"]}
    missing = sorted(key for key in required if key not in payload)
    if missing:
        return {"ok": False, "adapter": adapter, "errors": [f"Missing fields: {', '.join(missing)}"]}
    return {
        "ok": True,
        "adapter": adapter,
        "contract_version": WORLD_ADAPTER_SCHEMA_VERSION,
        "simulated_events": len(payload.get("table") or payload.get("cues") or []),
        "latency_budget_ms": 33,
    }
