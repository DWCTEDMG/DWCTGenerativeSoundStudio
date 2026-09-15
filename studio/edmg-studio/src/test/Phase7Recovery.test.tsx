import React from "react";
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import DirectorWorkspacePanel from "../components/DirectorWorkspacePanel";
import AudioReactiveWorkbench from "../workbenches/AudioReactiveWorkbench";
import { installFetchMock, renderWithStudio } from "./testUtils";

const document = {
  version: 1,
  story_bible: { project_theme: "", visual_style: "" },
  analysis_revision: 1,
  scenes: [{ scene_id: "scene-1", start_sample: "0", end_sample: "48000", intent: "Open", subjects: [], actions: [], camera: {}, environment: {}, renderer_hints: {} }],
};

const reactivePoint = {
  id: "motion-1",
  camera_id: "camera-1",
  source_id: "scene-1",
  frame: 0,
  time: 0,
  t: 0,
  sample: "0",
  locked: false,
  motion_score: 0.5,
  strength: 0.7,
  anchor_strength: 0.5,
  cfg: 7,
  steps: 20,
  subject_motion: 0.5,
  environment_motion: 0.5,
  zoom: 1,
  pan_x: 0,
  pan_y: 0,
  rotation_deg: 0,
};

describe("Phase 7 recovery", () => {
  beforeEach(() => localStorage.clear());

  it("persists unsaved reactive edits by project and workflow draft identity", async () => {
    const { rerender } = renderWithStudio(
      <AudioReactiveWorkbench studioProjectId="project-a" studioProjectName="A" studioWorkflowDraftId="draft-a" studioReactiveDraft={{ metadata: { workflow_draft_id: "draft-a", fps: 24 }, keyframes: [reactivePoint] }} />,
    );
    await waitFor(() => expect(localStorage.getItem("edmg-reactive-draft-v1:project-a")).toContain('"draft_id":"draft-a"'));
    expect(localStorage.getItem("edmg-reactive-draft-v1:project-b")).toBeNull();

    rerender(
      <AudioReactiveWorkbench studioProjectId="project-b" studioProjectName="B" studioWorkflowDraftId="draft-b" studioReactiveDraft={{ metadata: { workflow_draft_id: "draft-b", fps: 24 }, keyframes: [reactivePoint] }} />,
    );
    await waitFor(() => expect(localStorage.getItem("edmg-reactive-draft-v1:project-b")).toContain('"draft_id":"draft-b"'));
    expect(localStorage.getItem("edmg-reactive-draft-v1:project-a")).toContain('"draft_id":"draft-a"');
  });

  it("recovers Director job, review, status, and captured context", async () => {
    installFetchMock({
      "GET /v1/projects/p1/director/readiness": { ready: true, director: {}, renderer: {} },
      "GET /v1/projects/p1/director/document": { revision: 4, document },
      "GET /v1/projects/p1/director/workflow": {
        revision: 4,
        context_revision: 12,
        director_job: { version: 1, job_id: "job-8", status: "reviewed", reviewed: true, reviewed_job_id: "job-8" },
        timeline_context: { version: 1, selected_range: { start_sample: "900", end_sample: "1900" } },
      },
    });
    renderWithStudio(<DirectorWorkspacePanel projectId="p1" project={{ id: "p1", name: "P1", revision: 4 }} analysis={{ revision: 1 }} plan={{ variants: [] }} selectedVariant={0} onRefreshProject={vi.fn()} />);

    expect(await screen.findByText("Queue job: job-8")).toBeTruthy();
    expect(screen.getByText(/Recovered Director job job-8: reviewed/)).toBeTruthy();
    expect((screen.getByLabelText("Director draft review") as HTMLTextAreaElement).value).toContain('"start_sample": "900"');
    expect((screen.getByRole("button", { name: "Apply reviewed draft" }) as HTMLButtonElement).disabled).toBe(false);
  });

  it("preserves the requested instruction when model generation is unavailable", async () => {
    installFetchMock({
      "GET /v1/projects/p1/director/readiness": { ready: false, blockers: ["Model unavailable"], director: {}, renderer: {} },
      "GET /v1/projects/p1/director/document": { revision: 4, document },
      "GET /v1/projects/p1/director/workflow": { revision: 4, status: "draft", draft: { draft_id: "draft-a" } },
      "POST /v1/projects/p1/director/generate": () => { throw new Error("Install the resolved Director model"); },
    });
    renderWithStudio(<DirectorWorkspacePanel projectId="p1" project={{ id: "p1", name: "P1", revision: 4 }} analysis={{ revision: 1 }} plan={{ variants: [] }} selectedVariant={0} onRefreshProject={vi.fn()} />);
    const input = await screen.findByLabelText("Direction instruction");
    fireEvent.change(screen.getByLabelText("Project theme"), { target: { value: "" } });
    fireEvent.change(input, { target: { value: "Keep the neon dancer centered" } });
    fireEvent.click(screen.getByRole("button", { name: "Generate draft" }));
    expect(await screen.findByText(/Direction preserved: “Keep the neon dancer centered”/)).toBeTruthy();
    expect((input as HTMLTextAreaElement).value).toBe("Keep the neon dancer centered");
  });
});
