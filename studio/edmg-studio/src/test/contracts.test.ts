import { describe, expect, it } from "vitest";
import {
  CONTRACT_SCHEMA_VERSION,
  CONTRACT_TYPES,
  isV1Contract,
  type ProjectContract,
} from "../contracts/v1";

describe("v1 Studio contracts", () => {
  it("freezes all eight cross-domain contract names", () => {
    expect(CONTRACT_SCHEMA_VERSION).toBe("1.0");
    expect(CONTRACT_TYPES).toEqual([
      "edmg.project",
      "edmg.music_graph",
      "edmg.creative_intent",
      "edmg.render_plan",
      "edmg.artifact",
      "edmg.capability",
      "edmg.job",
      "edmg.cue",
    ]);
  });

  it("recognizes versioned payloads and rejects drifted versions", () => {
    const project = {
      schema_version: "1.0",
      contract_type: "edmg.project",
      id: "project-1",
      created_at: "2026-07-14T00:00:00Z",
      updated_at: "2026-07-14T00:00:00Z",
      name: "Contract Fixture",
      revision: 1,
      timeline: {},
      render_plan_refs: [],
      artifact_refs: [],
      metadata: {},
      extensions: {},
    } satisfies ProjectContract;

    expect(isV1Contract(project)).toBe(true);
    expect(isV1Contract({ ...project, schema_version: "2.0" })).toBe(false);
    expect(isV1Contract({ ...project, contract_type: "edmg.unknown" })).toBe(false);
  });
});
