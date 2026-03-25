import React, { useEffect, useMemo, useState } from "react";

type CreativeMode = "music-video" | "lyric-film" | "performance-hybrid";
type ProviderMode = "local-heuristic" | "ollama-contract" | "openai-contract";
type Preview = "prompt-pack" | "bundle" | "contract" | "timeline";
type Emotion = { emotion: string; score: number };
type Motif = { term: string; category: string; score: number };
type Scene = {
  title: string;
  startS: number;
  endS: number;
  emotion: string;
  energy: number;
  motifs: string[];
  lyricCue: string;
  prompt: string;
  negative: string;
  camera: string;
  motion: string;
  overlay: string;
};

const styles = {
  root: {
    minHeight: "100vh",
    padding: 28,
    color: "#f4f7ff",
    background:
      "radial-gradient(circle at top left, rgba(227, 138, 48, 0.18), transparent 30%), radial-gradient(circle at top right, rgba(57, 113, 255, 0.22), transparent 30%), linear-gradient(150deg, #10131c 0%, #161221 46%, #0d1d29 100%)",
    fontFamily: 'Inter, "Segoe UI", sans-serif',
  } as React.CSSProperties,
  shell: { maxWidth: 1460, margin: "0 auto", display: "grid", gap: 18 } as React.CSSProperties,
  panel: {
    background: "rgba(13, 19, 31, 0.78)",
    border: "1px solid rgba(167, 190, 255, 0.16)",
    borderRadius: 22,
    padding: 18,
    backdropFilter: "blur(14px)",
    boxShadow: "0 20px 48px rgba(0, 0, 0, 0.26)",
  } as React.CSSProperties,
  subtle: { color: "rgba(229, 235, 255, 0.72)", fontSize: 13, lineHeight: 1.45 } as React.CSSProperties,
  input: {
    width: "100%",
    borderRadius: 12,
    border: "1px solid rgba(174, 194, 255, 0.22)",
    background: "rgba(8, 13, 24, 0.92)",
    color: "#f4f7ff",
    padding: "11px 12px",
    boxSizing: "border-box",
  } as React.CSSProperties,
  button: {
    border: "1px solid rgba(174, 194, 255, 0.22)",
    borderRadius: 12,
    padding: "10px 14px",
    color: "#f4f7ff",
    cursor: "pointer",
    fontWeight: 700,
    background: "rgba(14, 24, 41, 0.88)",
  } as React.CSSProperties,
};

const STOP_WORDS = new Set(["the", "and", "with", "that", "this", "into", "from", "your", "have", "been", "when", "over", "under", "through", "there", "then", "they", "them", "just", "like", "feel", "will", "your", "you", "for", "are", "not", "but", "out", "our", "too", "all", "can", "was", "were", "its", "it's", "their"]);

const EMOTION_WORDS: Record<string, string[]> = {
  euphoria: ["light", "higher", "rise", "alive", "open", "glow", "gold", "electric", "dance", "rush"],
  longing: ["echo", "late", "ghost", "after", "distance", "remember", "missing", "fade", "lost", "again"],
  tension: ["edge", "fall", "smoke", "storm", "shadow", "break", "pressure", "night", "wire", "warning"],
  intimacy: ["skin", "breath", "close", "touch", "hand", "heart", "whisper", "inside"],
  defiance: ["burn", "riot", "wild", "fight", "loud", "rough", "fire", "run"],
  wonder: ["sky", "stars", "ocean", "dream", "horizon", "infinite", "blue", "sun"],
};

const MOTIF_TAGS: Record<string, string> = {
  city: "urban",
  neon: "light",
  sky: "nature",
  ocean: "nature",
  smoke: "atmosphere",
  mirror: "symbol",
  street: "urban",
  fire: "element",
  skin: "body",
  heart: "body",
  stars: "cosmos",
  signal: "technology",
  shadow: "atmosphere",
  rain: "weather",
  gold: "light",
  dance: "movement",
  run: "movement",
};

function clamp(value: number, min: number, max: number) {
  return Math.max(min, Math.min(max, value));
}

function average(values: number[]) {
  return values.length ? values.reduce((sum, value) => sum + value, 0) / values.length : 0;
}

function fmt(value: number) {
  const minutes = Math.floor(Math.max(0, value) / 60);
  const seconds = Math.max(0, value) % 60;
  return `${minutes}:${seconds.toFixed(1).padStart(4, "0")}`;
}

function tokenize(text: string) {
  return text
    .toLowerCase()
    .replace(/[^a-z0-9\s'-]/g, " ")
    .split(/\s+/)
    .map((token) => token.trim())
    .filter((token) => token && !STOP_WORDS.has(token));
}

function parseLines(text: string, durationS: number) {
  const lines = text.split(/\r?\n/).map((line) => line.trim()).filter(Boolean);
  if (!lines.length) return [];
  const slice = durationS / lines.length;
  return lines.map((line, index) => ({
    text: line,
    startS: index * slice,
    endS: index === lines.length - 1 ? durationS : (index + 1) * slice,
  }));
}

function emotionScores(tokens: string[]) {
  const scores = Object.entries(EMOTION_WORDS).map(([emotion, words]) => ({
    emotion,
    score: tokens.reduce((sum, token) => sum + (words.includes(token) ? 1 : 0), 0),
  }));
  const peak = Math.max(...scores.map((score) => score.score), 1);
  return scores.map((score) => ({ emotion: score.emotion, score: score.score / peak })).sort((left, right) => right.score - left.score);
}

function extractMotifs(tokens: string[], anchors: string[]) {
  const counts = new Map<string, number>();
  for (const token of [...tokens, ...anchors.map((anchor) => anchor.toLowerCase())]) {
    counts.set(token, (counts.get(token) || 0) + 1);
  }
  return [...counts.entries()]
    .map(([term, count]) => ({ term, category: MOTIF_TAGS[term] || (anchors.includes(term) ? "anchor" : "freeform"), score: count }))
    .sort((left, right) => right.score - left.score)
    .slice(0, 10);
}

function sceneCamera(mode: CreativeMode, emotion: string, energy: number) {
  if (mode === "lyric-film") return energy > 0.72 ? "Slow dolly through lyric space with animated text layers." : "Static or gently floating frame with lyric emphasis.";
  if (mode === "performance-hybrid") return energy > 0.72 ? "Stage-front kinetic camera with crowd-scale reveal." : "Mid-shot performance cutaway with controlled drift.";
  return emotion === "longing" ? "Wide anamorphic drift with horizon parallax." : energy > 0.72 ? "Forward glide into a stronger reveal." : "Steadicam move with layered foreground depth.";
}

function sceneMotion(mode: CreativeMode, energy: number) {
  if (mode === "lyric-film") return energy > 0.7 ? "Animate typography on beat accents and let the background pulse." : "Favor gentle subtitle motion and slow environment drift.";
  return energy > 0.74 ? "Push edits, camera roll restraint, and visible momentum through the cut." : "Longer tails, softer transitions, and restrained parallax.";
}

function buildBundle(params: {
  title: string;
  transcript: string;
  durationS: number;
  bpm: number;
  sceneCount: number;
  mode: CreativeMode;
  provider: ProviderMode;
  visualTone: string;
  anchorText: string;
  negative: string;
}) {
  const anchors = params.anchorText.split(/[,|\n]/).map((value) => value.trim()).filter(Boolean);
  const tokens = tokenize(`${params.transcript} ${params.anchorText}`);
  const emotions = emotionScores(tokens).slice(0, 4);
  const motifs = extractMotifs(tokens, anchors);
  const lines = parseLines(params.transcript, params.durationS);
  const groups = Array.from({ length: Math.max(1, params.sceneCount) }, (_, index) =>
    lines.filter((_, lineIndex) => Math.floor((lineIndex / Math.max(1, lines.length)) * params.sceneCount) === index),
  ).filter((group) => group.length);

  const roleNames = ["Opening Frame", "Ignition", "Lift", "Impact", "Release", "Afterglow", "Echo"];
  const scenes: Scene[] = groups.map((group, index) => {
    const lyricCue = group.map((line) => line.text).join(" / ");
    const localTokens = tokenize(lyricCue);
    const localEmotion = emotionScores(localTokens)[0]?.emotion || emotions[0]?.emotion || "wonder";
    const localMotifs = extractMotifs(localTokens, anchors).slice(0, 4).map((motif) => motif.term);
    const energy = clamp(0.3 + params.bpm / 260 + (index / Math.max(1, groups.length - 1)) * 0.18 + (lyricCue.includes("!") ? 0.08 : 0), 0, 1);
    const title = `${roleNames[Math.min(index, roleNames.length - 1)]} / ${(localMotifs[0] || motifs[0]?.term || "signal").replace(/^\w/, (value) => value.toUpperCase())}`;
    return {
      title,
      startS: group[0]?.startS ?? 0,
      endS: group[group.length - 1]?.endS ?? params.durationS,
      emotion: localEmotion,
      energy,
      motifs: localMotifs.length ? localMotifs : motifs.slice(0, 3).map((motif) => motif.term),
      lyricCue,
      prompt: `${params.visualTone}, ${params.mode}, ${title.toLowerCase()}, motifs: ${(localMotifs.length ? localMotifs : motifs.slice(0, 3).map((motif) => motif.term)).join(", ")}, emotion: ${localEmotion}, camera: ${sceneCamera(params.mode, localEmotion, energy)}`,
      negative: params.negative,
      camera: sceneCamera(params.mode, localEmotion, energy),
      motion: sceneMotion(params.mode, energy),
      overlay: group[0]?.text || title,
    };
  });

  const promptPack = scenes
    .map((scene, index) => [
      `${index + 1}. ${scene.title} (${fmt(scene.startS)} - ${fmt(scene.endS)})`,
      `Prompt: ${scene.prompt}`,
      `Camera: ${scene.camera}`,
      `Motion: ${scene.motion}`,
      `Overlay: ${scene.overlay}`,
      `Negative: ${scene.negative}`,
    ].join("\n"))
    .join("\n\n");

  return {
    analysis: {
      ok: true,
      title: params.title,
      duration_s: params.durationS,
      bpm: params.bpm,
      emotions,
      motifs,
      hooks: lines.slice(0, 2).concat(lines.slice(-1)).map((line) => line.text).slice(0, 3),
    },
    creative_direction: {
      ok: true,
      status: "Local-first narrative direction pack ready for backend integration.",
      mode: params.mode,
      provider_mode: params.provider,
      scenes: scenes.map((scene, index) => ({
        index,
        name: scene.title,
        start_s: scene.startS,
        end_s: scene.endS,
        prompt: scene.prompt,
        camera_hint: scene.camera,
        motion_hint: scene.motion,
        lyric_cue: scene.lyricCue,
      })),
      export_text: promptPack,
    },
    timeline_patch: {
      ok: true,
      timeline: {
        tracks: [
          {
            id: "track_prompt",
            name: "Prompt Track",
            type: "prompt",
            clips: scenes.map((scene, index) => ({ id: `prompt_${index}`, start_s: scene.startS, end_s: scene.endS, data: { prompt: scene.prompt, negative_prompt: scene.negative } })),
          },
          {
            id: "track_overlay",
            name: "Overlay Track",
            type: "overlay",
            clips: scenes.map((scene, index) => ({ id: `overlay_${index}`, start_s: scene.startS, end_s: scene.endS, data: { text: scene.overlay } })),
          },
        ],
      },
    },
    llm_contract: {
      ok: true,
      endpoint: "/v1/projects/:project_id/narrative_direction",
      provider_mode: params.provider,
      request: {
        title: params.title,
        transcript: params.transcript,
        duration_s: params.durationS,
        bpm: params.bpm,
        scene_count: params.sceneCount,
        mode: params.mode,
        visual_tone: params.visualTone,
        anchors,
      },
      expected_response_shape: {
        ok: true,
        creative_direction: {
          scenes: [{ name: "string", start_s: 0, end_s: 0, prompt: "string", camera_hint: "string", motion_hint: "string" }],
        },
      },
    },
    promptPack,
    scenes,
  };
}

function downloadText(name: string, content: string, type: string) {
  const blob = new Blob([content], { type });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = name;
  anchor.click();
  URL.revokeObjectURL(url);
}

export default function AIEnhancedMusicGenerator() {
  const [audioUrl, setAudioUrl] = useState("");
  const [title, setTitle] = useState("Untitled direction study");
  const [durationS, setDurationS] = useState(120);
  const [bpm, setBpm] = useState(128);
  const [sceneCount, setSceneCount] = useState(6);
  const [mode, setMode] = useState<CreativeMode>("music-video");
  const [provider, setProvider] = useState<ProviderMode>("local-heuristic");
  const [visualTone, setVisualTone] = useState("nocturnal cinematic realism with glass reflections and sodium haze");
  const [anchorText, setAnchorText] = useState("neon rain, skyline glass, human silhouette");
  const [negative, setNegative] = useState("muddy framing, generic club crowd, broken anatomy, unreadable text");
  const [transcript, setTranscript] = useState("");
  const [preview, setPreview] = useState<Preview>("prompt-pack");
  const [selectedScene, setSelectedScene] = useState(0);
  const [result, setResult] = useState<ReturnType<typeof buildBundle> | null>(null);
  const [log, setLog] = useState<string[]>([]);

  const note = (message: string) => setLog((current) => [...current, `${new Date().toLocaleTimeString()}: ${message}`].slice(-12));

  useEffect(() => () => {
    if (audioUrl) URL.revokeObjectURL(audioUrl);
  }, [audioUrl]);

  const previewText = !result
    ? "Generate a direction pack to see prompt, contract, and timeline payload previews."
    : preview === "prompt-pack"
      ? result.promptPack
      : preview === "bundle"
        ? JSON.stringify(result, null, 2)
        : preview === "contract"
          ? JSON.stringify(result.llm_contract, null, 2)
          : JSON.stringify(result.timeline_patch, null, 2);

  const activeScene = result?.scenes[selectedScene] ?? null;

  return (
    <div style={styles.root}>
      <div style={styles.shell}>
        <section style={{ ...styles.panel, padding: 22 }}>
          <div style={{ display: "flex", justifyContent: "space-between", gap: 18, flexWrap: "wrap" }}>
            <div style={{ maxWidth: 860 }}>
              <div style={{ display: "inline-flex", gap: 8, alignItems: "center", padding: "8px 10px", borderRadius: 999, background: "rgba(90,132,255,0.12)", border: "1px solid rgba(120,153,255,0.2)", fontSize: 12, letterSpacing: "0.12em", textTransform: "uppercase", color: "#bcd0ff" }}>
                Archive Prototype / Narrative Direction
              </div>
              <h1 style={{ margin: "14px 0 10px", fontSize: 40, lineHeight: 1.04 }}>AI Narrative Planning Lab</h1>
              <p style={{ ...styles.subtle, fontSize: 15 }}>
                This replaces the old hardcoded API call demo with a local-first planning surface: transcript analysis, motif extraction, scene blueprinting, prompt packs, timeline patches, and provider contract previews.
              </p>
            </div>
            <div style={{ minWidth: 240, display: "grid", gap: 8, alignContent: "start" }}>
              <div style={{ fontWeight: 800 }}>Mode</div>
              <div style={styles.subtle}>{mode}</div>
              <div style={{ fontWeight: 800 }}>Provider contract</div>
              <div style={styles.subtle}>{provider}</div>
            </div>
          </div>
        </section>

        <section style={{ display: "grid", gridTemplateColumns: "minmax(360px,1.15fr) minmax(340px,0.95fr) minmax(320px,0.9fr)", gap: 18 }}>
          <div style={styles.panel}>
            <div style={{ display: "grid", gap: 12 }}>
              <div style={{ fontWeight: 800, fontSize: 18 }}>Source material</div>
              <input value={title} onChange={(event) => setTitle(event.target.value)} style={styles.input} />
              <textarea value={transcript} onChange={(event) => setTranscript(event.target.value)} placeholder="Paste lyrics, transcript fragments, or a creative monologue here." style={{ ...styles.input, minHeight: 220, resize: "vertical" }} />
              <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
                <button type="button" onClick={() => {
                  setTranscript([
                    "We ran through the neon rain until the skyline started breathing.",
                    "Your name was a signal bouncing off the glass and back into my chest.",
                    "Now the streets are gold and every brake light feels like a sunrise.",
                    "Hold the frame wide while the city opens and the crowd lifts with it.",
                    "When the drop lands, let the smoke roll and keep the silhouette human.",
                    "After the impact, leave one quiet echo in the mirror before fadeout.",
                  ].join("\n"));
                  note("Loaded demo transcript.");
                }} style={{ ...styles.button, background: "rgba(46,80,160,0.88)" }}>
                  Load demo lyrics
                </button>
                <input
                  type="file"
                  accept="audio/*"
                  onChange={(event) => {
                    const file = event.target.files?.[0];
                    if (!file) return;
                    if (audioUrl) URL.revokeObjectURL(audioUrl);
                    const nextUrl = URL.createObjectURL(file);
                    setAudioUrl(nextUrl);
                    setTitle(file.name.replace(/\.[^/.]+$/, ""));
                    note(`Attached ${file.name} for metadata and playback reference.`);
                  }}
                  style={{ ...styles.input, padding: 10 }}
                />
              </div>
              {audioUrl ? <audio src={audioUrl} controls style={{ width: "100%" }} onLoadedMetadata={(event) => setDurationS(event.currentTarget.duration)} /> : null}
            </div>
          </div>

          <div style={styles.panel}>
            <div style={{ display: "grid", gap: 12 }}>
              <div style={{ fontWeight: 800, fontSize: 18 }}>Creative controls</div>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
                <select value={mode} onChange={(event) => setMode(event.target.value as CreativeMode)} style={styles.input}>
                  <option value="music-video">Music video</option>
                  <option value="lyric-film">Lyric film</option>
                  <option value="performance-hybrid">Performance hybrid</option>
                </select>
                <select value={provider} onChange={(event) => setProvider(event.target.value as ProviderMode)} style={styles.input}>
                  <option value="local-heuristic">Local heuristic</option>
                  <option value="ollama-contract">Ollama contract</option>
                  <option value="openai-contract">OpenAI contract</option>
                </select>
                <input type="number" min={30} max={900} value={durationS} onChange={(event) => setDurationS(clamp(Number(event.target.value) || 120, 30, 900))} style={styles.input} />
                <input type="number" min={60} max={200} value={bpm} onChange={(event) => setBpm(clamp(Number(event.target.value) || 128, 60, 200))} style={styles.input} />
                <input type="number" min={3} max={10} value={sceneCount} onChange={(event) => setSceneCount(clamp(Number(event.target.value) || 6, 3, 10))} style={styles.input} />
                <input value={negative} onChange={(event) => setNegative(event.target.value)} style={styles.input} />
              </div>
              <textarea value={visualTone} onChange={(event) => setVisualTone(event.target.value)} style={{ ...styles.input, minHeight: 92, resize: "vertical" }} />
              <textarea value={anchorText} onChange={(event) => setAnchorText(event.target.value)} style={{ ...styles.input, minHeight: 92, resize: "vertical" }} />
              <button
                type="button"
                onClick={() => {
                  const next = buildBundle({ title, transcript, durationS, bpm, sceneCount, mode, provider, visualTone, anchorText, negative });
                  setResult(next);
                  setSelectedScene(0);
                  note(`Generated ${next.scenes.length} scene blueprints with ${next.analysis.motifs.length} motifs.`);
                }}
                style={{ ...styles.button, background: "linear-gradient(120deg, #2a7fff, #7b5cff)" }}
              >
                Generate direction pack
              </button>
            </div>
          </div>

          <div style={styles.panel}>
            <div style={{ display: "grid", gap: 12 }}>
              <div style={{ fontWeight: 800, fontSize: 18 }}>Analysis summary</div>
              {result ? (
                <>
                  <div style={styles.subtle}>Top emotions</div>
                  {result.analysis.emotions.map((emotion) => (
                    <div key={emotion.emotion} style={{ display: "grid", gap: 8 }}>
                      <div style={{ display: "flex", justifyContent: "space-between" }}><span style={styles.subtle}>{emotion.emotion}</span><span style={styles.subtle}>{Math.round(emotion.score * 100)}%</span></div>
                      <div style={{ height: 10, borderRadius: 999, background: "rgba(255,255,255,0.08)", overflow: "hidden" }}>
                        <div style={{ width: `${Math.round(emotion.score * 100)}%`, height: "100%", borderRadius: 999, background: "linear-gradient(90deg, #ffb157, #7b8eff)" }} />
                      </div>
                    </div>
                  ))}
                  <div style={{ ...styles.subtle, marginTop: 8 }}>Motifs: {result.analysis.motifs.map((motif) => motif.term).join(", ")}</div>
                  <div style={styles.subtle}>Hooks: {result.analysis.hooks.join(" / ")}</div>
                </>
              ) : <div style={styles.subtle}>Generate a direction pack to see emotion mix, motifs, and hook lines.</div>}
            </div>
          </div>
        </section>

        <section style={{ display: "grid", gridTemplateColumns: "minmax(420px,1.1fr) minmax(420px,1.1fr)", gap: 18 }}>
          <div style={styles.panel}>
            <div style={{ display: "flex", justifyContent: "space-between", gap: 12, flexWrap: "wrap", marginBottom: 12 }}>
              <div>
                <div style={{ fontWeight: 800, fontSize: 18 }}>Scene ladder</div>
                <div style={styles.subtle}>Each scene already carries a prompt, negative prompt, overlay cue, camera, and motion language.</div>
              </div>
              <div style={styles.subtle}>{result ? `${result.scenes.length} scenes` : "No scenes yet"}</div>
            </div>
            <div style={{ display: "grid", gap: 10, maxHeight: 420, overflowY: "auto", paddingRight: 4 }}>
              {result?.scenes.length ? result.scenes.map((scene, index) => (
                <button key={`${scene.title}-${index}`} type="button" onClick={() => setSelectedScene(index)} style={{ ...styles.button, textAlign: "left", background: index === selectedScene ? "rgba(69,97,170,0.35)" : "rgba(8,13,26,0.76)" }}>
                  <div style={{ display: "flex", justifyContent: "space-between", gap: 12 }}>
                    <strong>{index + 1}. {scene.title}</strong>
                    <span style={styles.subtle}>{Math.round(scene.energy * 100)}%</span>
                  </div>
                  <div style={{ ...styles.subtle, marginTop: 6 }}>{fmt(scene.startS)} - {fmt(scene.endS)} | {scene.emotion}</div>
                </button>
              )) : <div style={styles.subtle}>Generate a pack to populate the scene ladder.</div>}
            </div>
            {activeScene ? (
              <div style={{ borderRadius: 16, padding: 14, background: "rgba(8,13,26,0.8)", border: "1px solid rgba(174,194,255,0.14)", display: "grid", gap: 8, marginTop: 12 }}>
                <div style={{ fontWeight: 800 }}>{activeScene.title}</div>
                <div style={styles.subtle}><strong>Prompt:</strong> {activeScene.prompt}</div>
                <div style={styles.subtle}><strong>Camera:</strong> {activeScene.camera}</div>
                <div style={styles.subtle}><strong>Motion:</strong> {activeScene.motion}</div>
                <div style={styles.subtle}><strong>Overlay:</strong> {activeScene.overlay}</div>
              </div>
            ) : null}
          </div>

          <div style={styles.panel}>
            <div style={{ display: "flex", justifyContent: "space-between", gap: 12, flexWrap: "wrap", marginBottom: 12 }}>
              <div>
                <div style={{ fontWeight: 800, fontSize: 18 }}>Export preview</div>
                <div style={styles.subtle}>Prompt pack, Studio bundle, provider contract, and timeline patch previews all come from the same local analysis pass.</div>
              </div>
              <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                {(["prompt-pack", "bundle", "contract", "timeline"] as Preview[]).map((mode) => (
                  <button key={mode} type="button" onClick={() => setPreview(mode)} style={{ ...styles.button, padding: "8px 12px", background: preview === mode ? "rgba(123,156,255,0.28)" : "rgba(8,13,26,0.76)" }}>
                    {mode}
                  </button>
                ))}
              </div>
            </div>
            <textarea readOnly value={previewText} style={{ ...styles.input, minHeight: 420, resize: "vertical", fontFamily: "Consolas, monospace" }} />
            <div style={{ display: "flex", gap: 10, flexWrap: "wrap", marginTop: 12 }}>
              <button type="button" disabled={!result} onClick={() => navigator.clipboard?.writeText(previewText)} style={{ ...styles.button, opacity: result ? 1 : 0.6 }}>
                Copy current preview
              </button>
              <button type="button" disabled={!result} onClick={() => downloadText(`narrative-direction-${preview}-${Date.now()}.${preview === "prompt-pack" ? "md" : "json"}`, previewText, preview === "prompt-pack" ? "text/markdown" : "application/json")} style={{ ...styles.button, opacity: result ? 1 : 0.6, background: "linear-gradient(120deg, #2a7fff, #7b5cff)" }}>
                Download current preview
              </button>
            </div>
          </div>
        </section>

        <section style={{ display: "grid", gridTemplateColumns: "minmax(420px,1fr) minmax(340px,0.9fr)", gap: 18 }}>
          <div style={styles.panel}>
            <div style={{ fontWeight: 800, fontSize: 18, marginBottom: 12 }}>Integration notes</div>
            <div style={{ display: "grid", gap: 8 }}>
              <div style={styles.subtle}>The prototype now emits a real scene ladder, a prompt pack, and a provider contract preview instead of making an unconfigured external request.</div>
              <div style={styles.subtle}>`creative_direction`, `timeline_patch`, and `llm_contract` are already serialized as stable objects, so the Studio backend can replace the heuristics later without changing the frontend contract.</div>
            </div>
          </div>
          <div style={styles.panel}>
            <div style={{ fontWeight: 800, fontSize: 18, marginBottom: 12 }}>Activity log</div>
            <div style={{ borderRadius: 16, padding: 14, background: "rgba(8,13,26,0.8)", border: "1px solid rgba(174,194,255,0.14)", minHeight: 180, display: "grid", gap: 8, alignContent: "start" }}>
              {log.length ? log.map((entry) => <div key={entry} style={{ ...styles.subtle, color: "#d9e4ff" }}>{entry}</div>) : <div style={styles.subtle}>Actions will appear here as you load demo material or generate direction packs.</div>}
            </div>
          </div>
        </section>
      </div>
    </div>
  );
}
