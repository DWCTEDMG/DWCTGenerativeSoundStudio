import React from "react";
import type { MusicGraphSection, MusicGraphV1 } from "../shared/api/contracts";

type UnderstandPanelProps = {
  musicGraph: MusicGraphV1 | null;
  analysisTags?: string[];
  analysisSections?: MusicGraphSection[];
  compact?: boolean;
};

function fallbackTags(tags: string[]): Array<{ tag: string; confidence: number }> {
  return tags.slice(0, 12).map((tag) => ({ tag, confidence: 0.55 }));
}

export default function UnderstandPanel({
  musicGraph,
  analysisTags = [],
  analysisSections = [],
  compact = false,
}: UnderstandPanelProps) {
  if (!musicGraph) {
    return (
      <div className="card" style={{ marginTop: 12, padding: 12 }}>
        <div style={{ fontWeight: 800, marginBottom: 6 }}>Understand</div>
        <div className="small" style={{ opacity: 0.85 }}>
          Run Analyze on a project track to populate Music Graph v1 — beats, sections, stems, semantic tags, and ASR lyrics.
        </div>
      </div>
    );
  }

  const sections = Array.isArray(musicGraph.sections) && musicGraph.sections.length
    ? musicGraph.sections
    : analysisSections;
  const stems = Array.isArray(musicGraph.stems) ? musicGraph.stems : [];
  const semanticTags = Array.isArray(musicGraph.semantics?.tags) && musicGraph.semantics?.tags.length
    ? musicGraph.semantics.tags
    : fallbackTags(analysisTags);
  const beatCount = Array.isArray(musicGraph.beats) ? musicGraph.beats.length : 0;
  const lyricLines = Array.isArray(musicGraph.lyrics?.lines) ? musicGraph.lyrics.lines : [];
  const lyricWords = Array.isArray(musicGraph.lyrics?.words) ? musicGraph.lyrics.words : [];
  const confidenceNotes = Array.isArray(musicGraph.confidenceNotes) ? musicGraph.confidenceNotes : [];
  const bpm = musicGraph.tempo?.bpm ? Math.round(Number(musicGraph.tempo.bpm)) : null;
  const durationS = musicGraph.timebase?.durationSeconds;
  const lyricsStatus = musicGraph.lyrics?.error
    ? "failed"
    : lyricLines.length || lyricWords.length
      ? "ready"
      : "optional";

  return (
    <div className="card" style={{ marginTop: 12, padding: 12 }}>
      <div style={{ fontWeight: 800, marginBottom: 6 }}>Understand — Music Graph v1</div>
      <div className="small" style={{ opacity: 0.85, marginBottom: 8 }}>
        Canonical analysis consumed by Director, Conductor, live cues, and timeline markers.
        {musicGraph.source?.filename ? <> Source: <code>{musicGraph.source.filename}</code>.</> : null}
      </div>
      <div className="workspace-analysisGrid">
        <div className="workspace-handoffCard">
          <div className="workspace-handoffLabel">Tempo</div>
          <strong>{bpm ? `${bpm} BPM` : "pending"}</strong>
        </div>
        <div className="workspace-handoffCard">
          <div className="workspace-handoffLabel">Beats</div>
          <strong>{beatCount}</strong>
        </div>
        <div className="workspace-handoffCard">
          <div className="workspace-handoffLabel">Sections</div>
          <strong>{sections.length}</strong>
        </div>
        <div className="workspace-handoffCard">
          <div className="workspace-handoffLabel">Stems</div>
          <strong>{stems.length}</strong>
        </div>
        <div className="workspace-handoffCard">
          <div className="workspace-handoffLabel">Semantic tags</div>
          <strong>{semanticTags.length}</strong>
        </div>
        <div className="workspace-handoffCard">
          <div className="workspace-handoffLabel">ASR / lyrics</div>
          <strong>{lyricsStatus}</strong>
        </div>
        {!compact && typeof durationS === "number" ? (
          <div className="workspace-handoffCard">
            <div className="workspace-handoffLabel">Duration</div>
            <strong>{durationS.toFixed(1)}s</strong>
          </div>
        ) : null}
        {!compact && musicGraph.meter?.numerator ? (
          <div className="workspace-handoffCard">
            <div className="workspace-handoffLabel">Meter</div>
            <strong>
              {musicGraph.meter.numerator}/{musicGraph.meter.denominator || 4}
            </strong>
          </div>
        ) : null}
      </div>

      {sections.length ? (
        <div className="workspace-sceneList" style={{ marginTop: 10 }}>
          <div className="workspace-sectionTitle">Sections & energy</div>
          {sections.slice(0, compact ? 6 : 12).map((section, index) => (
            <div key={`${section.label}-${index}`} className="workspace-sceneRow">
              <div className="row" style={{ justifyContent: "space-between", gap: 8, flexWrap: "wrap" }}>
                <div style={{ fontWeight: 700 }}>{section.label || "section"}</div>
                <div className="small">
                  {Number(section.start || 0).toFixed(1)}s → {Number(section.end || 0).toFixed(1)}s
                  {typeof section.energy === "number" ? (
                    <> • energy {(section.energy * 100).toFixed(0)}%</>
                  ) : null}
                  {typeof section.confidence === "number" ? (
                    <> • conf {(section.confidence * 100).toFixed(0)}%</>
                  ) : null}
                </div>
              </div>
            </div>
          ))}
        </div>
      ) : null}

      {stems.length ? (
        <div className="workspace-chipRow" style={{ marginTop: 10 }}>
          {stems.slice(0, compact ? 6 : 12).map((stem) => (
            <span key={stem.kind} className="badge">{stem.kind}</span>
          ))}
        </div>
      ) : null}

      {semanticTags.length ? (
        <div className="workspace-chipRow" style={{ marginTop: 10 }}>
          {semanticTags.slice(0, compact ? 8 : 16).map((item) => (
            <span key={item.tag} className="badge">
              {item.tag}
              {item.confidence ? ` (${Math.round(Number(item.confidence) * 100)}%)` : ""}
            </span>
          ))}
        </div>
      ) : null}

      {lyricLines.length ? (
        <details className="workspace-inlineDetails" style={{ marginTop: 10 }} open={!compact}>
          <summary>ASR transcript ({lyricLines.length} lines)</summary>
          <div className="workspace-scrollPanel">
            {lyricLines.slice(0, compact ? 12 : 48).map((line, index) => (
              <div key={`${line.start}-${index}`} className="small" style={{ marginBottom: 6 }}>
                <span style={{ opacity: 0.7 }}>
                  {Number(line.start || 0).toFixed(1)}s–{Number(line.end || 0).toFixed(1)}s
                </span>
                {" — "}
                {line.text}
              </div>
            ))}
            {musicGraph.lyrics?.language ? (
              <div className="small" style={{ marginTop: 8, opacity: 0.75 }}>
                Language: {musicGraph.lyrics.language}
                {musicGraph.lyrics.source ? ` • source ${musicGraph.lyrics.source}` : null}
              </div>
            ) : null}
          </div>
        </details>
      ) : musicGraph.lyrics?.error ? (
        <div className="small" style={{ marginTop: 10, color: "#c90" }}>
          ASR failed: {musicGraph.lyrics.error}
          {musicGraph.lyrics.note ? ` — ${musicGraph.lyrics.note}` : null}
        </div>
      ) : null}

      {confidenceNotes.length ? (
        <details className="workspace-inlineDetails" style={{ marginTop: 10 }}>
          <summary>Confidence notes</summary>
          <div className="workspace-scrollPanel">
            {confidenceNotes.map((note) => (
              <div key={note} className="small" style={{ marginBottom: 4 }}>{note}</div>
            ))}
          </div>
        </details>
      ) : null}
    </div>
  );
}
