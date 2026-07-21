import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import UnderstandPanel from "../components/UnderstandPanel";
import type { MusicGraphV1 } from "../shared/api/contracts";

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
});
