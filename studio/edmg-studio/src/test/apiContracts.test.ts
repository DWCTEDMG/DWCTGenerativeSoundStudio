import { describe, expect, it } from "vitest";
import type {
  AutosaveResponse,
  LiveAssetsResponse,
  MusicGraphResponse,
  PerformerWorkflowPlanResponse,
  ProjectHealthReport,
  ProjectRecoveryStatus,
  RenderConductorPlanResponse,
  SystemReadinessReport,
  TemplatePackageExportResponse,
  VariantReviewResponse,
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

  it("accepts baseline metrics payloads", () => {
    const baseline: import("../shared/api/contracts").BaselineMetricsReport = {
      ok: true,
      schema_version: 1,
      stub: true,
      samples: {
        launch: { count: 1, last_ms: 1200, budget_ms: 8000, within_budget: true },
      },
    };
    expect(baseline.samples?.launch?.within_budget).toBe(true);
  });

  it("accepts music graph, render plan, review, live assets, template, and performer payloads", () => {
    const musicGraph: MusicGraphResponse = {
      ok: true,
      music_graph: {
        schemaVersion: "1.0",
        sections: [{ start: 0, end: 4, label: "intro" }],
        stems: [{ kind: "mixed" }],
      },
    };
    const renderPlan: RenderConductorPlanResponse = {
      ok: true,
      plan: { plan_id: "plan-1", sections: [{ scene_id: "scene-1", engine: "proxy" }] },
    };
    const review: VariantReviewResponse = {
      ok: true,
      variant_review: { approved_count: 1, pending_count: 0, artifacts: [] },
    };
    const liveAssets: LiveAssetsResponse = {
      ok: true,
      live_assets: { pack_count: 1, channel_count: 2, packs: [] },
    };
    const template: TemplatePackageExportResponse = {
      ok: true,
      package: { schema_version: 1, package_id: "tpl-1", models: [], assets: [] },
    };
    const performer: PerformerWorkflowPlanResponse = {
      ok: true,
      performer_plan: {
        plan_id: "performer-1",
        tasks: [{ scene_id: "scene-1", engine: "hosted_video" }],
      },
    };
    expect(musicGraph.music_graph.schemaVersion).toBe("1.0");
    expect(renderPlan.plan?.sections?.[0]?.engine).toBe("proxy");
    expect(review.variant_review.approved_count).toBe(1);
    expect(liveAssets.live_assets.pack_count).toBe(1);
    expect(template.package.package_id).toBe("tpl-1");
    expect(performer.performer_plan?.tasks?.[0]?.scene_id).toBe("scene-1");
  });
});
