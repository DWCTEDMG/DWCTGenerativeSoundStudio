from __future__ import annotations

from typing import Any, Literal

ModelLane = Literal["stable", "recommended", "experimental", "research", "legacy"]

LANES: tuple[ModelLane, ...] = (
    "stable",
    "recommended",
    "experimental",
    "research",
    "legacy",
)

# Promotion gates: source lane may move into these targets.
PROMOTION_GATES: dict[ModelLane, tuple[ModelLane, ...]] = {
    "research": ("experimental", "legacy"),
    "experimental": ("recommended", "legacy"),
    "recommended": ("stable", "experimental", "legacy"),
    "stable": ("recommended", "legacy"),
    "legacy": ("experimental", "recommended"),
}

REQUIRED_EVIDENCE_FOR_STABLE = (
    "benchmark_json",
    "license_accepted",
    "install_smoke",
)


def normalize_lane(value: str | None, *, fallback: ModelLane = "experimental") -> ModelLane:
    raw = str(value or "").strip().lower()
    if raw in LANES:
        return raw  # type: ignore[return-value]
    if raw in {"default", "production", "prod"}:
        return "recommended"
    if raw in {"advanced", "optional"}:
        return "experimental"
    if raw in {"browser", "discovery"}:
        return "research"
    return fallback


def infer_lane(entry: dict[str, Any]) -> ModelLane:
    if entry.get("lane"):
        return normalize_lane(str(entry.get("lane")))
    tags = {str(tag).strip().lower() for tag in (entry.get("tags") or []) if str(tag).strip()}
    recommended = str(entry.get("recommended") or "").strip().lower()
    if "legacy" in tags or recommended == "legacy":
        return "legacy"
    if "research" in tags or recommended in {"research", "browser"}:
        return "research"
    if recommended == "default" or "default" in tags:
        return "recommended"
    if recommended in {"stable", "production"}:
        return "stable"
    if recommended in {"advanced", "optional", "experimental"} or "experimental" in tags:
        return "experimental"
    if entry.get("installable") is False:
        return "research"
    return "experimental"


def can_promote(from_lane: ModelLane, to_lane: ModelLane) -> bool:
    if from_lane == to_lane:
        return True
    return to_lane in PROMOTION_GATES.get(from_lane, ())


def promotion_blockers(
    entry: dict[str, Any],
    *,
    target_lane: ModelLane,
    has_benchmark: bool = False,
    license_accepted: bool = False,
) -> list[str]:
    blockers: list[str] = []
    current = infer_lane(entry)
    if not can_promote(current, target_lane):
        blockers.append(f"lane_gate:{current}->{target_lane}")
    if target_lane == "stable":
        if not has_benchmark:
            blockers.append("missing_benchmark_json")
        if not license_accepted and entry.get("license_id"):
            blockers.append("license_not_accepted")
        if entry.get("installable") is False:
            blockers.append("browser_only_not_promotable")
    return blockers


def annotate_entry(entry: dict[str, Any], *, lane_override: str | None = None) -> dict[str, Any]:
    item = dict(entry)
    lane = normalize_lane(lane_override) if lane_override else infer_lane(item)
    item["lane"] = lane
    item["lane_gates"] = {
        "promotable_to": list(PROMOTION_GATES.get(lane, ())),
        "stable_requires": list(REQUIRED_EVIDENCE_FOR_STABLE),
    }
    return item
