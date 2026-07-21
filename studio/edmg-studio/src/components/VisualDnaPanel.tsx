import React, { useEffect, useState } from "react";
import { apiGet, apiPost } from "./api";

type VisualDnaPanelProps = {
  projectId: string;
  compact?: boolean;
};

type VisualDnaTrait = {
  id: string;
  scope: string;
  value: string;
  state: string;
  weight: number;
  evidence_count?: number;
};

export function VisualDnaPanel(props: VisualDnaPanelProps) {
  const { projectId, compact = false } = props;
  const [dna, setDna] = useState<any>(null);
  const [traits, setTraits] = useState<VisualDnaTrait[]>([]);
  const [hints, setHints] = useState<any>(null);
  const [status, setStatus] = useState<string>("");
  const [loading, setLoading] = useState(false);
  const [notes, setNotes] = useState("");

  const refresh = async () => {
    if (!projectId) {
      setDna(null);
      setTraits([]);
      setHints(null);
      setStatus("Select a project to inspect Visual DNA.");
      return;
    }
    setLoading(true);
    setStatus("Loading Visual DNA...");
    try {
      const result = await apiGet(`/v1/projects/${projectId}/visual_dna`);
      setDna(result?.visual_dna || null);
      setTraits(Array.isArray(result?.traits) ? result.traits : []);
      setHints(result?.prompt_hints || null);
      setStatus("");
    } catch (error: any) {
      setDna(null);
      setTraits([]);
      setHints(null);
      setStatus(`Visual DNA unavailable: ${String(error)}`);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    refresh().catch(() => {});
  }, [projectId]);

  const mutateTraits = async (payload: { approve_trait_ids?: string[]; deprecate_trait_ids?: string[]; notes?: string }) => {
    if (!projectId) return;
    setStatus("");
    try {
      const result = await apiPost(`/v1/projects/${projectId}/visual_dna/update`, payload);
      setDna(result?.visual_dna || null);
      setTraits(Array.isArray(result?.traits) ? result.traits : []);
      setHints(result?.prompt_hints || null);
      setStatus("Visual DNA updated.");
      if (payload.notes) setNotes("");
    } catch (error: any) {
      setStatus(`Update failed: ${String(error)}`);
    }
  };

  const identity = dna?.identity || {};
  const continuity = dna?.continuity || {};
  const confidence = typeof hints?.confidence === "number" ? hints.confidence : dna?.learning_state?.confidence;

  return (
    <div className="visual-dna-panel">
      <div className="row" style={{ justifyContent: "space-between", alignItems: "center", flexWrap: "wrap" }}>
        <div>
          <div style={{ fontWeight: 900, fontSize: compact ? 18 : 20 }}>Visual DNA</div>
          <div className="small">Inspect project identity, continuity anchors, and approve or deprecate learned traits.</div>
        </div>
        <button className="secondary" onClick={() => refresh()} disabled={!projectId || loading}>
          Refresh
        </button>
      </div>

      {status ? <div className="small" style={{ marginTop: 8 }}>{status}</div> : null}

      {!projectId ? (
        <div className="small" style={{ marginTop: 10 }}>Select a project to load Visual DNA.</div>
      ) : loading && !dna ? (
        <div className="small" style={{ marginTop: 10 }}>Loading…</div>
      ) : (
        <>
          <div className="row" style={{ gap: 8, flexWrap: "wrap", marginTop: 10 }}>
            {typeof confidence === "number" ? (
              <div className="badge">Confidence {Math.round(Number(confidence) * 100)}%</div>
            ) : null}
            <div className="badge">{(identity.core_themes || []).length} themes</div>
            <div className="badge">{(identity.motifs || []).length} motifs</div>
            <div className="badge">{traits.length} traits</div>
          </div>

          <div style={{ marginTop: 12 }}>
            <div style={{ fontWeight: 800, marginBottom: 6 }}>Identity</div>
            <div className="small">
              Themes: {(identity.core_themes || []).slice(0, 6).join(" • ") || "—"}
            </div>
            <div className="small" style={{ marginTop: 4 }}>
              Motifs: {(identity.motifs || []).slice(0, 6).join(" • ") || "—"}
            </div>
            <div className="small" style={{ marginTop: 4 }}>
              Palette: {(identity.palette?.dominant || []).slice(0, 5).join(", ") || "—"}
            </div>
            <div className="small" style={{ marginTop: 4 }}>
              Camera: {(identity.camera_language || []).slice(0, 4).join(" • ") || "—"}
            </div>
          </div>

          <div style={{ marginTop: 12 }}>
            <div style={{ fontWeight: 800, marginBottom: 6 }}>Continuity</div>
            <div className="small">
              Subject: {(continuity.subject_anchors || []).slice(0, 4).join(" • ") || "—"}
            </div>
            <div className="small" style={{ marginTop: 4 }}>
              Environment: {(continuity.environment_anchors || []).slice(0, 4).join(" • ") || "—"}
            </div>
          </div>

          <div style={{ marginTop: 12 }}>
            <div style={{ fontWeight: 800, marginBottom: 6 }}>Trait memory</div>
            {!traits.length ? (
              <div className="small">No traits yet. Plan, render, or approve feedback to seed Visual DNA.</div>
            ) : (
              <div style={{ display: "grid", gap: 8 }}>
                {traits.slice(0, compact ? 6 : 12).map((trait) => (
                  <div key={trait.id} className="row" style={{ justifyContent: "space-between", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
                    <div className="small" style={{ flex: 1, minWidth: 180 }}>
                      <b>{trait.scope}</b> · {trait.value}
                      <div style={{ opacity: 0.75 }}>
                        {trait.state} · weight {Number(trait.weight || 0).toFixed(2)}
                        {typeof trait.evidence_count === "number" ? ` · evidence ${trait.evidence_count}` : ""}
                      </div>
                    </div>
                    <div className="row" style={{ gap: 6 }}>
                      <button
                        className="secondary"
                        disabled={trait.state === "declared"}
                        onClick={() => mutateTraits({ approve_trait_ids: [trait.id] })}
                      >
                        Approve
                      </button>
                      <button
                        className="secondary"
                        disabled={trait.state === "deprecated"}
                        onClick={() => mutateTraits({ deprecate_trait_ids: [trait.id] })}
                      >
                        Deprecate
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>

          {!compact ? (
            <div style={{ marginTop: 12 }}>
              <div style={{ fontWeight: 800, marginBottom: 6 }}>Curator note</div>
              <textarea
                value={notes}
                onChange={(event) => setNotes(event.target.value)}
                rows={2}
                placeholder="Optional note to reinforce as a declared theme"
                style={{ width: "100%" }}
              />
              <button
                className="secondary"
                style={{ marginTop: 8 }}
                disabled={!notes.trim()}
                onClick={() => mutateTraits({ notes: notes.trim() })}
              >
                Save note to DNA
              </button>
            </div>
          ) : null}
        </>
      )}
    </div>
  );
}
