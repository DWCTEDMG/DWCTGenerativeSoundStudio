import React, { useCallback, useEffect, useState } from "react";
import { apiPatch } from "./api";
import type { MusicGraphSection, MusicGraphV1, WeightedTag } from "../shared/api/contracts";

type UnderstandPanelProps = {
  musicGraph: MusicGraphV1 | null;
  projectId?: string;
  analysisTags?: string[];
  analysisSections?: MusicGraphSection[];
  compact?: boolean;
  onSaved?: (graph: MusicGraphV1, invalidation: { changed: string[]; invalidated: string[] }) => void;
};

function fallbackTags(tags: string[]): Array<{ tag: string; confidence: number }> {
  return tags.slice(0, 12).map((tag) => ({ tag, confidence: 0.55 }));
}

type SectionDraft = {
  label: string;
  start: string;
  end: string;
  energy: string;
};

type LyricDraft = {
  start: string;
  end: string;
  text: string;
};

export default function UnderstandPanel({
  musicGraph,
  projectId = "",
  analysisTags = [],
  analysisSections = [],
  compact = false,
  onSaved,
}: UnderstandPanelProps) {
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [tempoDraft, setTempoDraft] = useState("");
  const [sectionDrafts, setSectionDrafts] = useState<SectionDraft[]>([]);
  const [lyricDrafts, setLyricDrafts] = useState<LyricDraft[]>([]);
  const [tagDraft, setTagDraft] = useState("");

  const sections = musicGraph && Array.isArray(musicGraph.sections) && musicGraph.sections.length
    ? musicGraph.sections
    : analysisSections;
  const semanticTags = musicGraph && Array.isArray(musicGraph.semantics?.tags) && musicGraph.semantics?.tags.length
    ? musicGraph.semantics.tags
    : fallbackTags(analysisTags);
  const lyricLines = musicGraph && Array.isArray(musicGraph.lyrics?.lines) ? musicGraph.lyrics.lines : [];
  const bpm = musicGraph?.tempo?.bpm ? Math.round(Number(musicGraph.tempo.bpm)) : null;

  const resetDrafts = useCallback(() => {
    setTempoDraft(bpm ? String(bpm) : "");
    setSectionDrafts(
      sections.slice(0, compact ? 6 : 12).map((section) => ({
        label: section.label || "section",
        start: String(section.start ?? 0),
        end: String(section.end ?? 0),
        energy: section.energy != null ? String(section.energy) : "",
      })),
    );
    setLyricDrafts(
      lyricLines.slice(0, compact ? 12 : 48).map((line) => ({
        start: String(line.start ?? 0),
        end: String(line.end ?? 0),
        text: line.text || "",
      })),
    );
    setTagDraft(semanticTags.map((item) => item.tag).join(", "));
  }, [bpm, compact, lyricLines, sections, semanticTags]);

  useEffect(() => {
    if (editing && musicGraph) resetDrafts();
  }, [editing, musicGraph, resetDrafts]);

  const saveCorrections = async () => {
    if (!projectId) {
      setError("Select a project before saving corrections.");
      return;
    }
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const payload = {
        sections: sectionDrafts.map((section) => ({
          label: section.label.trim() || "section",
          start: Number(section.start) || 0,
          end: Number(section.end) || 0,
          ...(section.energy.trim() ? { energy: Number(section.energy) } : {}),
        })),
        lyrics_lines: lyricDrafts
          .filter((line) => line.text.trim())
          .map((line) => ({
            start: Number(line.start) || 0,
            end: Number(line.end) || 0,
            text: line.text.trim(),
          })),
        semantic_tags: tagDraft
          .split(",")
          .map((tag) => tag.trim())
          .filter(Boolean)
          .map((tag) => ({ tag, confidence: 0.85, source: "manual" })),
        ...(tempoDraft.trim() ? { tempo_bpm: Number(tempoDraft) } : {}),
        reason: "workspace_understand_edit",
      };
      const response = await apiPatch(`/v1/projects/${projectId}/music_graph/corrections`, payload);
      const invalidation = response?.invalidation || { changed: [], invalidated: [] };
      onSaved?.(response.music_graph, invalidation);
      setEditing(false);
      const invalidated = Array.isArray(invalidation.invalidated) ? invalidation.invalidated : [];
      setNotice(
        invalidated.length
          ? `Saved corrections. Cleared stale derived data: ${invalidated.join(", ")}.`
          : "Saved corrections.",
      );
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

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

  const stems = Array.isArray(musicGraph.stems) ? musicGraph.stems : [];
  const beatCount = Array.isArray(musicGraph.beats) ? musicGraph.beats.length : 0;
  const lyricWords = Array.isArray(musicGraph.lyrics?.words) ? musicGraph.lyrics.words : [];
  const confidenceNotes = Array.isArray(musicGraph.confidenceNotes) ? musicGraph.confidenceNotes : [];
  const durationS = musicGraph.timebase?.durationSeconds;
  const lyricsStatus = musicGraph.lyrics?.error
    ? "failed"
    : lyricLines.length || lyricWords.length
      ? "ready"
      : "optional";

  return (
    <div className="card" style={{ marginTop: 12, padding: 12 }}>
      <div className="row" style={{ justifyContent: "space-between", gap: 8, flexWrap: "wrap", marginBottom: 6 }}>
        <div style={{ fontWeight: 800 }}>Understand — Music Graph v1</div>
        {!compact && projectId ? (
          <div className="row" style={{ gap: 8 }}>
            {editing ? (
              <>
                <button className="secondary" disabled={busy} onClick={() => { setEditing(false); setError(null); }}>
                  Cancel
                </button>
                <button disabled={busy} onClick={() => void saveCorrections()}>
                  {busy ? "Saving…" : "Save corrections"}
                </button>
              </>
            ) : (
              <button className="secondary" onClick={() => setEditing(true)}>
                Edit corrections
              </button>
            )}
          </div>
        ) : null}
      </div>
      <div className="small" style={{ opacity: 0.85, marginBottom: 8 }}>
        Canonical analysis consumed by Director, Conductor, live cues, and timeline markers.
        {musicGraph.source?.filename ? <> Source: <code>{musicGraph.source.filename}</code>.</> : null}
      </div>
      {notice ? <div className="small" style={{ marginBottom: 8, color: "#6a6" }}>{notice}</div> : null}
      {error ? <div className="small" style={{ marginBottom: 8, color: "#c44" }}>{error}</div> : null}
      <div className="workspace-analysisGrid">
        <div className="workspace-handoffCard">
          <div className="workspace-handoffLabel">Tempo</div>
          {editing ? (
            <input
              value={tempoDraft}
              onChange={(e) => setTempoDraft(e.target.value)}
              aria-label="Tempo BPM"
              style={{ width: "100%" }}
            />
          ) : (
            <strong>{bpm ? `${bpm} BPM` : "pending"}</strong>
          )}
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

      {editing ? (
        <div className="small" style={{ marginTop: 10, opacity: 0.85 }}>
          Edit section labels/times, lyric lines, semantic tags, and tempo. Saving invalidates stored Conductor plans so the next plan reflects your corrections.
        </div>
      ) : null}

      {sections.length ? (
        <div className="workspace-sceneList" style={{ marginTop: 10 }}>
          <div className="workspace-sectionTitle">Sections & energy</div>
          {(editing ? sectionDrafts : sections.slice(0, compact ? 6 : 12)).map((section, index) => (
            <div key={`${section.label}-${index}`} className="workspace-sceneRow">
              {editing ? (
                <div className="row" style={{ gap: 8, flexWrap: "wrap" }}>
                  <input
                    value={(section as SectionDraft).label}
                    onChange={(e) => {
                      const next = [...sectionDrafts];
                      next[index] = { ...next[index], label: e.target.value };
                      setSectionDrafts(next);
                    }}
                    aria-label={`Section ${index + 1} label`}
                  />
                  <input
                    value={(section as SectionDraft).start}
                    onChange={(e) => {
                      const next = [...sectionDrafts];
                      next[index] = { ...next[index], start: e.target.value };
                      setSectionDrafts(next);
                    }}
                    aria-label={`Section ${index + 1} start`}
                    style={{ width: 72 }}
                  />
                  <input
                    value={(section as SectionDraft).end}
                    onChange={(e) => {
                      const next = [...sectionDrafts];
                      next[index] = { ...next[index], end: e.target.value };
                      setSectionDrafts(next);
                    }}
                    aria-label={`Section ${index + 1} end`}
                    style={{ width: 72 }}
                  />
                  <input
                    value={(section as SectionDraft).energy}
                    onChange={(e) => {
                      const next = [...sectionDrafts];
                      next[index] = { ...next[index], energy: e.target.value };
                      setSectionDrafts(next);
                    }}
                    aria-label={`Section ${index + 1} energy`}
                    placeholder="energy"
                    style={{ width: 72 }}
                  />
                </div>
              ) : (
                <div className="row" style={{ justifyContent: "space-between", gap: 8, flexWrap: "wrap" }}>
                  <div style={{ fontWeight: 700 }}>{(section as MusicGraphSection).label || "section"}</div>
                  <div className="small">
                    {Number((section as MusicGraphSection).start || 0).toFixed(1)}s → {Number((section as MusicGraphSection).end || 0).toFixed(1)}s
                    {typeof (section as MusicGraphSection).energy === "number" ? (
                      <> • energy {(((section as MusicGraphSection).energy || 0) * 100).toFixed(0)}%</>
                    ) : null}
                    {typeof (section as MusicGraphSection).confidence === "number" ? (
                      <> • conf {(((section as MusicGraphSection).confidence || 0) * 100).toFixed(0)}%</>
                    ) : null}
                  </div>
                </div>
              )}
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

      {editing ? (
        <div style={{ marginTop: 10 }}>
          <div className="workspace-sectionTitle">Semantic tags</div>
          <input
            value={tagDraft}
            onChange={(e) => setTagDraft(e.target.value)}
            aria-label="Semantic tags"
            placeholder="comma,separated,tags"
            style={{ width: "100%" }}
          />
        </div>
      ) : semanticTags.length ? (
        <div className="workspace-chipRow" style={{ marginTop: 10 }}>
          {semanticTags.slice(0, compact ? 8 : 16).map((item: WeightedTag) => (
            <span key={item.tag} className="badge">
              {item.tag}
              {item.confidence ? ` (${Math.round(Number(item.confidence) * 100)}%)` : ""}
            </span>
          ))}
        </div>
      ) : null}

      {editing && lyricDrafts.length ? (
        <details className="workspace-inlineDetails" style={{ marginTop: 10 }} open>
          <summary>Edit ASR transcript ({lyricDrafts.length} lines)</summary>
          <div className="workspace-scrollPanel">
            {lyricDrafts.map((line, index) => (
              <div key={`${line.start}-${index}`} className="row" style={{ gap: 8, marginBottom: 8, flexWrap: "wrap" }}>
                <input
                  value={line.start}
                  onChange={(e) => {
                    const next = [...lyricDrafts];
                    next[index] = { ...next[index], start: e.target.value };
                    setLyricDrafts(next);
                  }}
                  aria-label={`Lyric ${index + 1} start`}
                  style={{ width: 72 }}
                />
                <input
                  value={line.end}
                  onChange={(e) => {
                    const next = [...lyricDrafts];
                    next[index] = { ...next[index], end: e.target.value };
                    setLyricDrafts(next);
                  }}
                  aria-label={`Lyric ${index + 1} end`}
                  style={{ width: 72 }}
                />
                <input
                  value={line.text}
                  onChange={(e) => {
                    const next = [...lyricDrafts];
                    next[index] = { ...next[index], text: e.target.value };
                    setLyricDrafts(next);
                  }}
                  aria-label={`Lyric ${index + 1} text`}
                  style={{ flex: 1, minWidth: 180 }}
                />
              </div>
            ))}
          </div>
        </details>
      ) : lyricLines.length ? (
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
