import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  REACTIVE_SCHEDULE_FIELDS,
  buildReactiveDraft,
  parseScheduleString,
  type PlanPreviewOutput,
  type ReactiveDraft,
} from "../src/widget/reactiveScheduler.js";

function samplePreview(): PlanPreviewOutput {
  return {
    type: "plan-preview",
    projectId: "demo-project",
    projectName: "Demo Project",
    mode: "auto",
    planSource: "test-suite",
    selectedVariantIndex: 0,
    analysisSummary: {
      bpm: 128,
      durationS: 12,
      hookLine: "Lift the skyline",
      narrative: "intro -> rise -> drop",
    },
    variants: [
      {
        index: 0,
        label: "Neon Pulse",
        summary: "Aggressive club lighting with strong camera travel.",
        durationS: 12,
        scenes: [
          {
            index: 0,
            title: "Cold Open",
            prompt: "Neon tunnel tracking shot around the singer.",
            startS: 0,
            endS: 4,
            durationS: 4,
            shotType: "wide",
            rationale: "Introduce the performer before the hook.",
            transitionCue: "push through the chorus hit",
            continuityNote: "keep performer centered",
          },
          {
            index: 1,
            title: "Drop Bloom",
            prompt: "Orbit the vocalist while LED walls strobe on the beat.",
            startS: 4,
            endS: 8,
            durationS: 4,
            shotType: "orbit",
            rationale: "Peak-energy section with more rotation.",
            transitionCue: "orbit into the drop",
            continuityNote: null,
          },
          {
            index: 2,
            title: "Afterglow",
            prompt: "Slow pullback into atmospheric haze as the hook resolves.",
            startS: 8,
            endS: null,
            durationS: 2,
            shotType: "pullback",
            rationale: "Release pressure without losing continuity.",
            transitionCue: "soft cut into haze",
            continuityNote: "hold camera travel direction",
          },
        ],
      },
    ],
  };
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" ? (value as Record<string, unknown>) : {};
}

describe("reactiveScheduler", () => {
  it("builds dense schedules, keyframes, and handoff metadata from a preview", () => {
    const preview = samplePreview();
    const draft = buildReactiveDraft(preview, 0) as ReactiveDraft;
    const expectedUniquePoints =
      preview.variants[0]!.scenes.length * 3 - (preview.variants[0]!.scenes.length - 1);

    assert.equal(draft.metadata.projectId, "demo-project");
    assert.equal(draft.metadata.variantLabel, "Neon Pulse");
    assert.equal(draft.metadata.bpm, 128);
    assert.equal(draft.keyframes.length, 9);
    assert.equal(draft.cueEvents.length, 3);
    assert.equal(draft.sections.length, 3);
    assert.equal(draft.repairSuggestions.length >= 2, true);
    assert.equal(draft.handoffManifest.scheduleStride, 1);

    REACTIVE_SCHEDULE_FIELDS.forEach((field) => {
      const points = parseScheduleString(draft.schedules[field]);
      assert.equal(
        points.length,
        expectedUniquePoints,
        `${field} should preserve scene peaks while deduping shared boundary frames`,
      );
      assert.equal(points.every((point, index) => index === 0 || point.frame >= points[index - 1].frame), true);
    });
  });

  it("extends the last section to the total duration hint when the final scene undershoots", () => {
    const draft = buildReactiveDraft(samplePreview(), 0) as ReactiveDraft;
    const lastSection = asRecord(draft.sections.at(-1));
    const lastKeyframe = asRecord(draft.keyframes.at(-1));

    assert.equal(lastSection.endTime, 12);
    assert.equal(lastKeyframe.time, 12);
  });

  it("parses schedule strings into sorted, deduplicated points", () => {
    const points = parseScheduleString("48:(1.0200),0:(1.1000),48:(1.0400),oops,96:(0.9800)");

    assert.deepEqual(points, [
      { frame: 0, value: 1.1 },
      { frame: 48, value: 1.04 },
      { frame: 96, value: 0.98 },
    ]);
  });
});
