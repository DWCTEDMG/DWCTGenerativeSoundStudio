import { describe, expect, it } from "vitest";
import golden from "../../../contracts/fixtures/v1/shared-contract-golden.json";
import {
  CONTRACT_SCHEMA_VERSION,
  CONTRACT_TYPES,
  isExactSampleString,
  isV1Contract,
  type ProjectContract,
} from "../contracts/v1";

describe("v1 Studio contracts", () => {
  it("matches the authoritative cross-runtime fixture", () => {
    expect(CONTRACT_SCHEMA_VERSION).toBe(golden.contract_schema_version);
    expect(CONTRACT_TYPES).toEqual(golden.contract_types);
    expect(golden.exact_samples.valid.every(isExactSampleString)).toBe(true);
    expect(golden.exact_samples.invalid.some(isExactSampleString)).toBe(false);
    expect(golden.enums.job_status).toEqual(["queued", "running", "succeeded", "failed", "canceled", "paused", "blocked"]);
    expect(golden.director_scene.extensions["vendor.example"].nested).toEqual([1, "two", true]);
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
