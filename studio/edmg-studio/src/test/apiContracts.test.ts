import { describe, expect, it } from "vitest";
import type {
  AutosaveResponse,
  ProjectHealthReport,
  ProjectRecoveryStatus,
  SystemReadinessReport,
} from "../shared/api/contracts";

describe("typed API contracts", () => {
  it("accepts system readiness payloads", () => {
    const report: SystemReadinessReport = {
      ok: true,
      status: "ready",
      checks: { ffmpeg: { ok: true } },
    };
    expect(report.ok).toBe(true);
  });

  it("accepts project health and recovery payloads", () => {
    const health: ProjectHealthReport = {
      ok: false,
      status: "error",
      issues: [{ code: "missing_asset", severity: "error", message: "Missing asset: a.wav" }],
      asset_index: {
        schema_version: 1,
        generated_at: "2026-07-15 00:00:00",
        asset_count: 0,
        missing_count: 1,
        total_bytes: 0,
        disk_estimate_gb: 0,
        missing: [{ path: "assets/audio/a.wav", reason: "missing" }],
        assets: [],
      },
      actions: ["relink_missing"],
    };
    const recovery: ProjectRecoveryStatus = {
      ok: true,
      needs_recovery: true,
      candidates: [{ kind: "journal", saved_at: "now", reason: "autosave", path: "autosave.journal.json" }],
    };
    const autosave: AutosaveResponse = {
      ok: true,
      autosave: { dirty: true, reason: "timeline_dirty" },
    };
    expect(health.status).toBe("error");
    expect(recovery.needs_recovery).toBe(true);
    expect(autosave.autosave.dirty).toBe(true);
  });
});
