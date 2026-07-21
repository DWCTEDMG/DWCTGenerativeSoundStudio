import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import UnderstandPanel from "../components/UnderstandPanel";
import type { MusicGraphV1 } from "../shared/api/contracts";

vi.mock("../components/api", () => ({
  apiPatch: vi.fn(),
}));

import { apiPatch } from "../components/api";

const sampleGraph: MusicGraphV1 = {
  schemaVersion: "1.0",
  tempo: { bpm: 128, confidence: 0.9 },
  sections: [{ start: 0, end: 8, label: "intro", energy: 0.42, confidence: 0.8 }],
  stems: [{ kind: "drums" }, { kind: "vocals" }],
  semantics: { tags: [{ tag: "uplifting", confidence: 0.71 }] },
  lyrics: {
    lines: [{ start: 1.2, end: 3.4, text: "hello world" }],
    language: "en",
  },
  beats: [{ t: 0.5 }, { t: 1.0 }],
};

describe("UnderstandPanel", () => {
  it("shows placeholder when music graph is missing", () => {
    render(<UnderstandPanel musicGraph={null} />);
    expect(screen.getByText(/Run Analyze on a project track/i)).toBeTruthy();
  });

  it("renders sections, tags, stems, and ASR lines", () => {
    render(
      <UnderstandPanel
        musicGraph={sampleGraph}
        analysisTags={["fallback-tag"]}
      />,
    );
    expect(screen.getByText(/Understand — Music Graph v1/i)).toBeTruthy();
    expect(screen.getByText("intro")).toBeTruthy();
    expect(screen.getByText(/uplifting \(71%\)/i)).toBeTruthy();
    expect(screen.getByText(/hello world/i)).toBeTruthy();
    expect(screen.getByText("drums")).toBeTruthy();
    expect(screen.getByText("128 BPM")).toBeTruthy();
  });

  it("saves editable corrections through the patch route", async () => {
    vi.mocked(apiPatch).mockResolvedValue({
      ok: true,
      music_graph: {
        ...sampleGraph,
        sections: [{ start: 0, end: 16, label: "verse", energy: 0.9 }],
      },
      invalidation: { changed: ["sections"], invalidated: ["last_conductor_plan"] },
    });
    const onSaved = vi.fn();

    render(
      <UnderstandPanel
        musicGraph={sampleGraph}
        projectId="proj-1"
        onSaved={onSaved}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /Edit corrections/i }));
    fireEvent.change(screen.getByLabelText(/Section 1 label/i), { target: { value: "verse" } });
    fireEvent.click(screen.getByRole("button", { name: /Save corrections/i }));

    await waitFor(() => {
      expect(apiPatch).toHaveBeenCalledWith(
        "/v1/projects/proj-1/music_graph/corrections",
        expect.objectContaining({
          sections: [expect.objectContaining({ label: "verse" })],
          reason: "workspace_understand_edit",
        }),
      );
    });
    expect(onSaved).toHaveBeenCalled();
    expect(screen.getByText(/Cleared stale derived data/i)).toBeTruthy();
  });
});
