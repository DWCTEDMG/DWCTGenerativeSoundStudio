import React, { useEffect, useMemo, useRef, useState } from "react";

type Preset = "cinematic" | "pulse-grid" | "ambient-drift";
type Preview = "prompt-pack" | "timeline" | "deforum" | "bundle";
type Band = "bass" | "mid" | "treble";
type Frame = {
  timeS: number;
  energy: number;
  bass: number;
  mid: number;
  treble: number;
  flux: number;
  motion: number;
  tension: number;
};
type Analysis = { durationS: number; frames: Frame[] };
type Section = {
  id: string;
  label: string;
  startS: number;
  endS: number;
  avgEnergy: number;
  peakEnergy: number;
  band: Band;
  prompt: string;
  camera: string;
  motion: string;
};

const styles = {
  root: {
    minHeight: "100vh",
    padding: 28,
    color: "#f5f7ff",
    background:
      "radial-gradient(circle at top left, rgba(43,134,197,0.28), transparent 32%), radial-gradient(circle at top right, rgba(199,77,92,0.22), transparent 26%), linear-gradient(145deg, #09111d 0%, #0d1422 48%, #14132b 100%)",
    fontFamily: 'Inter, "Segoe UI", sans-serif',
  } as React.CSSProperties,
  shell: { maxWidth: 1440, margin: "0 auto", display: "grid", gap: 18 } as React.CSSProperties,
  panel: {
    background: "rgba(12,20,33,0.76)",
    border: "1px solid rgba(153,181,255,0.18)",
    borderRadius: 22,
    padding: 18,
    backdropFilter: "blur(14px)",
    boxShadow: "0 18px 48px rgba(0,0,0,0.24)",
  } as React.CSSProperties,
  subtle: { color: "rgba(230,236,255,0.72)", fontSize: 13, lineHeight: 1.45 } as React.CSSProperties,
  input: {
    width: "100%",
    borderRadius: 12,
    border: "1px solid rgba(174,194,255,0.24)",
    background: "rgba(8,13,26,0.9)",
    color: "#f5f7ff",
    padding: "11px 12px",
    boxSizing: "border-box",
  } as React.CSSProperties,
  button: {
    border: "1px solid rgba(174,194,255,0.24)",
    borderRadius: 12,
    padding: "10px 14px",
    color: "#f5f7ff",
    cursor: "pointer",
    fontWeight: 700,
    background: "rgba(14,24,41,0.88)",
  } as React.CSSProperties,
};

function clamp(value: number, min: number, max: number) {
  return Math.max(min, Math.min(max, value));
}

function clamp01(value: number) {
  return clamp(value, 0, 1);
}

function average(values: number[]) {
  return values.length ? values.reduce((sum, value) => sum + value, 0) / values.length : 0;
}

function fmt(value: number) {
  const minutes = Math.floor(Math.max(0, value) / 60);
  const seconds = Math.max(0, value) % 60;
  return `${minutes}:${seconds.toFixed(1).padStart(4, "0")}`;
}

function normalize(values: number[]) {
  const peak = Math.max(...values, 0);
  return peak > 0 ? values.map((value) => clamp01(value / peak)) : values.map(() => 0);
}

function smooth(values: number[], radius = 1) {
  return values.map((_, index) => {
    const start = Math.max(0, index - radius);
    const end = Math.min(values.length, index + radius + 1);
    return average(values.slice(start, end));
  });
}

function dominantBand(bass: number, mid: number, treble: number): Band {
  if (bass >= mid && bass >= treble) return "bass";
  if (mid >= bass && mid >= treble) return "mid";
  return "treble";
}

function mixToMono(buffer: AudioBuffer) {
  const mono = new Float32Array(buffer.length);
  for (let channelIndex = 0; channelIndex < buffer.numberOfChannels; channelIndex += 1) {
    const data = buffer.getChannelData(channelIndex);
    for (let index = 0; index < data.length; index += 1) mono[index] += data[index] / buffer.numberOfChannels;
  }
  return mono;
}

function spectralBands(slice: Float32Array, sampleRate: number) {
  const size = Math.min(192, slice.length);
  let bass = 0;
  let mid = 0;
  let treble = 0;
  for (let bin = 1; bin <= 24; bin += 1) {
    let real = 0;
    let imaginary = 0;
    for (let index = 0; index < size; index += 1) {
      const sample = slice[Math.floor((index / size) * slice.length)] ?? 0;
      const angle = (2 * Math.PI * bin * index) / size;
      real += sample * Math.cos(angle);
      imaginary -= sample * Math.sin(angle);
    }
    const magnitude = Math.sqrt(real * real + imaginary * imaginary);
    const frequency = (bin * sampleRate) / size;
    if (frequency < 220) bass += magnitude;
    else if (frequency < 2200) mid += magnitude;
    else treble += magnitude;
  }
  return { bass, mid, treble };
}

function analyzeBuffer(buffer: AudioBuffer): Analysis {
  const mono = mixToMono(buffer);
  const durationS = buffer.duration;
  const target = clamp(Math.round(durationS * 4), 48, 160);
  const windowSize = clamp(Math.floor(mono.length / Math.max(1, target)), 1024, 16384);
  const rawEnergy: number[] = [];
  const rawBass: number[] = [];
  const rawMid: number[] = [];
  const rawTreble: number[] = [];
  const rawMotion: number[] = [];
  const rawFlux: number[] = [];
  const times: number[] = [];
  let previousEnergy = 0;

  for (let index = 0; index < target; index += 1) {
    const start = index * windowSize;
    const end = Math.min(mono.length, start + windowSize);
    const slice = mono.subarray(start, end);
    if (!slice.length) break;

    let squared = 0;
    let motion = 0;
    for (let sampleIndex = 0; sampleIndex < slice.length; sampleIndex += 1) {
      const sample = slice[sampleIndex];
      squared += sample * sample;
      if (sampleIndex > 0) motion += Math.abs(sample - slice[sampleIndex - 1]);
    }

    const energy = Math.sqrt(squared / slice.length);
    const bands = spectralBands(slice, buffer.sampleRate);
    rawEnergy.push(energy);
    rawBass.push(bands.bass);
    rawMid.push(bands.mid);
    rawTreble.push(bands.treble);
    rawMotion.push(motion / Math.max(1, slice.length));
    rawFlux.push(Math.max(0, energy - previousEnergy));
    times.push(start / buffer.sampleRate);
    previousEnergy = energy;
  }

  const energy = smooth(normalize(rawEnergy), 2);
  const bass = smooth(normalize(rawBass), 2);
  const mid = smooth(normalize(rawMid), 2);
  const treble = smooth(normalize(rawTreble), 2);
  const motion = smooth(normalize(rawMotion), 1);
  const flux = smooth(normalize(rawFlux), 1);

  return {
    durationS,
    frames: energy.map((value, index) => ({
      timeS: times[index] ?? 0,
      energy: value,
      bass: bass[index] ?? 0,
      mid: mid[index] ?? 0,
      treble: treble[index] ?? 0,
      flux: flux[index] ?? 0,
      motion: motion[index] ?? 0,
      tension: clamp01(value * 0.46 + (flux[index] ?? 0) * 0.24 + (treble[index] ?? 0) * 0.15 + (motion[index] ?? 0) * 0.15),
    })),
  };
}

function labelFor(index: number, total: number, energy: number, band: Band) {
  if (index === 0) return energy < 0.42 ? "Arrival" : "Cold Open";
  if (index === total - 1) return energy > 0.68 ? "Resolve" : "Afterglow";
  if (energy > 0.82 && band === "bass") return "Drop";
  if (energy > 0.68 && band === "mid") return "Lift";
  if (energy < 0.34) return "Breath";
  return band === "treble" ? "Spark" : band === "bass" ? "Drive" : "Build";
}

function motionHints(label: string, band: Band) {
  if (label === "Drop") return { camera: "Fast dolly-in with handheld recovery.", motion: "Push zoom, negative Z travel, transient shake." };
  if (label === "Breath") return { camera: "Locked lens with slow focus drift.", motion: "Small XY drift with softened contrast." };
  if (band === "treble") return { camera: "Lateral glide with highlight streaks.", motion: "Particle flicker and short spin accents." };
  if (band === "bass") return { camera: "Low-angle orbit with grounded perspective.", motion: "Scale pulses and front-to-back travel." };
  return { camera: "Steadicam reveal with parallax depth.", motion: "Blend orbit, rise, and moderate contrast ramps." };
}

function deriveSections(frames: Frame[], durationS: number, count: number, brief: string) {
  if (!frames.length) return [] as Section[];
  const target = clamp(count, 3, 8);
  const minGap = Math.max(4, Math.floor(frames.length / Math.max(3, target + 1)));
  const candidates = frames
    .slice(1, frames.length - 1)
    .map((frame, index) => ({ index: index + 1, score: frame.flux * 0.5 + frame.motion * 0.2 + Math.abs(frame.energy - frames[index].energy) * 0.3 }))
    .sort((left, right) => right.score - left.score);
  const boundaries = [0];
  for (const candidate of candidates) {
    if (boundaries.length >= target) break;
    if (boundaries.every((value) => Math.abs(value - candidate.index) >= minGap)) boundaries.push(candidate.index);
  }
  while (boundaries.length < target) boundaries.push(Math.floor((boundaries.length / target) * frames.length));
  boundaries.push(frames.length - 1);
  const ordered = Array.from(new Set(boundaries)).sort((left, right) => left - right);
  return ordered.slice(0, -1).map((startIndex, index) => {
    const endIndex = ordered[index + 1];
    const group = frames.slice(startIndex, endIndex + 1);
    const avgEnergy = average(group.map((frame) => frame.energy));
    const peakEnergy = Math.max(...group.map((frame) => frame.energy), 0);
    const band = dominantBand(average(group.map((frame) => frame.bass)), average(group.map((frame) => frame.mid)), average(group.map((frame) => frame.treble)));
    const label = labelFor(index, ordered.length - 1, avgEnergy, band);
    const hints = motionHints(label, band);
    return {
      id: `section_${index}`,
      label,
      startS: frames[startIndex]?.timeS ?? 0,
      endS: index === ordered.length - 2 ? durationS : frames[endIndex]?.timeS ?? durationS,
      avgEnergy,
      peakEnergy,
      band,
      prompt: `${brief}, ${label.toLowerCase()} section, ${band}-led motion language, premium music-film framing`,
      camera: hints.camera,
      motion: hints.motion,
    };
  });
}

function paramsFor(frame: Frame, preset: Preset, sensitivity: number, timeS: number) {
  const sens = clamp(sensitivity, 0.2, 2.4);
  if (preset === "pulse-grid") {
    return {
      zoom: 1 + frame.bass * 0.24 * sens + frame.flux * 0.08,
      rotationY: (frame.mid - 0.5) * 20 * sens + Math.sin(timeS * 0.8) * 4,
      rotationZ: frame.treble * 16 * sens,
      translationZ: -frame.energy * 28 * sens,
      cfg: 6.2 + frame.mid * 2.2 * sens,
      strength: 0.42 + frame.treble * 0.22 * sens,
      contrast: 1 + frame.tension * 0.42,
    };
  }
  if (preset === "ambient-drift") {
    return {
      zoom: 0.98 + frame.energy * 0.1 * sens,
      rotationY: Math.cos(timeS * 0.18) * frame.bass * 8 * sens,
      rotationZ: frame.treble * 6 * sens,
      translationZ: -frame.energy * 12 * sens,
      cfg: 5.8 + frame.treble * 1.8 * sens,
      strength: 0.28 + frame.energy * 0.18 * sens,
      contrast: 0.92 + frame.tension * 0.22,
    };
  }
  return {
    zoom: 1 + frame.energy * 0.18 * sens + frame.bass * 0.05,
    rotationY: (frame.mid - 0.5) * 18 * sens + Math.sin(timeS * 0.55) * frame.bass * 5,
    rotationZ: frame.treble * 9 * sens,
    translationZ: -frame.energy * 20 * sens,
    cfg: 6.7 + frame.mid * 2.6 * sens,
    strength: 0.36 + frame.treble * 0.2 * sens,
    contrast: 1 + frame.tension * 0.32,
  };
}

function schedule(points: Array<{ frame: number; value: number }>, decimals: number, epsilon: number) {
  if (!points.length) return "";
  const compact = [points[0]];
  for (let index = 1; index < points.length - 1; index += 1) {
    const prev = compact[compact.length - 1];
    const current = points[index];
    const next = points[index + 1];
    if (Math.abs(current.value - prev.value) >= epsilon || Math.abs(next.value - current.value) >= epsilon) compact.push(current);
  }
  compact.push(points[points.length - 1]);
  return compact.map((point) => `${point.frame}:(${point.value.toFixed(decimals)})`).join(", ");
}

function buildBundle(analysis: Analysis, preset: Preset, sensitivity: number, brief: string, negative: string, fps: number, totalFrames: number, sectionCount: number) {
  const sections = deriveSections(analysis.frames, analysis.durationS, sectionCount, brief);
  const points = analysis.frames.map((frame) => ({
    frame: Math.round((frame.timeS / Math.max(0.001, analysis.durationS)) * Math.max(1, totalFrames - 1)),
    values: paramsFor(frame, preset, sensitivity, frame.timeS),
  }));
  const schedules = {
    zoom: schedule(points.map((point) => ({ frame: point.frame, value: point.values.zoom })), 4, 0.012),
    rotation_y: schedule(points.map((point) => ({ frame: point.frame, value: point.values.rotationY })), 4, 0.25),
    rotation_z: schedule(points.map((point) => ({ frame: point.frame, value: point.values.rotationZ })), 4, 0.25),
    translation_z: schedule(points.map((point) => ({ frame: point.frame, value: point.values.translationZ })), 4, 0.22),
    cfg_scale: schedule(points.map((point) => ({ frame: point.frame, value: point.values.cfg })), 4, 0.05),
    strength: schedule(points.map((point) => ({ frame: point.frame, value: point.values.strength })), 4, 0.02),
    contrast: schedule(points.map((point) => ({ frame: point.frame, value: point.values.contrast })), 4, 0.02),
  };
  const promptPack = sections
    .map((section, index) => [
      `${index + 1}. ${section.label} (${fmt(section.startS)} - ${fmt(section.endS)})`,
      `Prompt: ${section.prompt}`,
      `Camera: ${section.camera}`,
      `Motion: ${section.motion}`,
    ].join("\n"))
    .join("\n\n");
  return {
    sections,
    promptPack,
    creative_direction: {
      ok: true,
      status: "Archive prototype ready for Studio integration.",
      preset,
      sensitivity,
      metrics: {
        duration_s: analysis.durationS,
        frame_count: analysis.frames.length,
        energy: average(analysis.frames.map((frame) => frame.energy)),
        bass: average(analysis.frames.map((frame) => frame.bass)),
        mid: average(analysis.frames.map((frame) => frame.mid)),
        treble: average(analysis.frames.map((frame) => frame.treble)),
      },
      waveform: analysis.frames.map((frame) => Number(frame.energy.toFixed(4))),
      sections: sections.map((section, index) => ({
        index,
        name: section.label,
        start_s: section.startS,
        end_s: section.endS,
        prompt: section.prompt,
        camera_hint: section.camera,
        motion_hint: section.motion,
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
            clips: sections.map((section, index) => ({
              id: `prompt_${index}`,
              start_s: section.startS,
              end_s: section.endS,
              data: { prompt: section.prompt, negative_prompt: negative, band_focus: section.band },
            })),
          },
          {
            id: "track_motion",
            name: "Motion Track",
            type: "motion",
            clips: sections.map((section, index) => {
              const frame = analysis.frames.find((candidate) => candidate.timeS >= (section.startS + section.endS) / 2) || analysis.frames[analysis.frames.length - 1];
              const params = paramsFor(frame, preset, sensitivity, (section.startS + section.endS) / 2);
              return {
                id: `motion_${index}`,
                start_s: section.startS,
                end_s: section.endS,
                data: { zoom_start: params.zoom, zoom_end: params.zoom + section.avgEnergy * 0.02, rotation_end: params.rotationZ + section.peakEnergy * 4, strength: params.strength, cfg: params.cfg },
              };
            }),
          },
        ],
      },
    },
    deforum: {
      ok: true,
      settings: {
        animation_mode: "3D",
        fps,
        max_frames: totalFrames,
        negative_prompts: { 0: negative },
        prompt_schedule: Object.fromEntries(sections.map((section) => [Math.round((section.startS / Math.max(0.001, analysis.durationS)) * Math.max(1, totalFrames - 1)), section.prompt])),
        schedules,
      },
    },
    notes: [
      "creative_direction, timeline_patch, and deforum are already serialized in Studio-friendly shapes.",
      "Mic monitoring is preserved for auditioning, but file analysis drives deterministic exports.",
    ],
  };
}

function pathFromFrames(frames: Frame[], pick: (frame: Frame) => number, width: number, height: number, offset = 28) {
  if (!frames.length) return "";
  const lastIndex = Math.max(1, frames.length - 1);
  return frames.map((frame, index) => `${index === 0 ? "M" : "L"} ${((index / lastIndex) * width).toFixed(2)} ${(offset + (1 - clamp01(pick(frame))) * height).toFixed(2)}`).join(" ");
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

export default function AudioReactiveGenerator() {
  const [audioFile, setAudioFile] = useState<File | null>(null);
  const [audioUrl, setAudioUrl] = useState("");
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [durationS, setDurationS] = useState(0);
  const [currentS, setCurrentS] = useState(0);
  const [preset, setPreset] = useState<Preset>("cinematic");
  const [preview, setPreview] = useState<Preview>("prompt-pack");
  const [sensitivity, setSensitivity] = useState(1.1);
  const [brief, setBrief] = useState("neon pilgrimage that swells into communal release");
  const [negative, setNegative] = useState("muddy detail, flat motion, broken anatomy, dead eyes, washed highlights");
  const [fps, setFps] = useState(24);
  const [renderFrames, setRenderFrames] = useState(480);
  const [sectionCount, setSectionCount] = useState(6);
  const [selectedSection, setSelectedSection] = useState(0);
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [error, setError] = useState("");
  const [liveFrames, setLiveFrames] = useState<Frame[]>([]);
  const [liveFrame, setLiveFrame] = useState<Frame | null>(null);
  const [micActive, setMicActive] = useState(false);
  const [log, setLog] = useState<string[]>([]);

  const micContext = useRef<AudioContext | null>(null);
  const micAnalyser = useRef<AnalyserNode | null>(null);
  const micStream = useRef<MediaStream | null>(null);
  const micRaf = useRef<number | null>(null);
  const micStartedMs = useRef(0);
  const lastLiveSampleMs = useRef(0);
  const prevLiveEnergy = useRef(0);

  const note = (message: string) => setLog((current) => [...current, `${new Date().toLocaleTimeString()}: ${message}`].slice(-12));

  useEffect(() => {
    if (analysis?.durationS) setRenderFrames(Math.max(48, Math.round(analysis.durationS * fps)));
  }, [analysis?.durationS, fps]);

  useEffect(() => () => {
    if (audioUrl) URL.revokeObjectURL(audioUrl);
    if (micRaf.current) cancelAnimationFrame(micRaf.current);
    micStream.current?.getTracks().forEach((track) => track.stop());
    void micContext.current?.close();
  }, [audioUrl]);

  const bundle = useMemo(() => (analysis ? buildBundle(analysis, preset, sensitivity, brief, negative, fps, renderFrames, sectionCount) : null), [analysis, brief, fps, negative, preset, renderFrames, sectionCount, sensitivity]);
  const frames = analysis?.frames.length ? analysis.frames : liveFrames;
  const stageDuration = analysis?.durationS || (liveFrames[liveFrames.length - 1]?.timeS ?? durationS);
  const playhead = analysis ? currentS : liveFrame?.timeS ?? 0;
  const liveBand = liveFrame ? dominantBand(liveFrame.bass, liveFrame.mid, liveFrame.treble) : null;
  const meterRows: Array<[string, number, string]> = [
    ["Energy", analysis ? average(analysis.frames.map((frame) => frame.energy)) : liveFrame?.energy || 0, "linear-gradient(90deg, #35d8df, #88f1ff)"],
    ["Bass", analysis ? average(analysis.frames.map((frame) => frame.bass)) : liveFrame?.bass || 0, "linear-gradient(90deg, #ff7a66, #ffb46b)"],
    ["Mid", analysis ? average(analysis.frames.map((frame) => frame.mid)) : liveFrame?.mid || 0, "linear-gradient(90deg, #7b9cff, #9ad0ff)"],
    ["Treble", analysis ? average(analysis.frames.map((frame) => frame.treble)) : liveFrame?.treble || 0, "linear-gradient(90deg, #b47dff, #ff9fe9)"],
  ];
  const previewText = !bundle
    ? "Analyze an uploaded audio file to generate Studio-ready export payloads."
    : preview === "prompt-pack"
      ? bundle.promptPack
      : preview === "timeline"
        ? JSON.stringify(bundle.timeline_patch, null, 2)
        : preview === "deforum"
          ? JSON.stringify(bundle.deforum, null, 2)
          : JSON.stringify(bundle, null, 2);

  const startMic = async () => {
    try {
      setError("");
      const stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: false, noiseSuppression: false, autoGainControl: false } });
      const AudioContextCtor = window.AudioContext || (window as Window & { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
      if (!AudioContextCtor) throw new Error("AudioContext is unavailable.");
      const context = new AudioContextCtor();
      const analyser = context.createAnalyser();
      analyser.fftSize = 2048;
      analyser.smoothingTimeConstant = 0.52;
      context.createMediaStreamSource(stream).connect(analyser);
      micContext.current = context;
      micAnalyser.current = analyser;
      micStream.current = stream;
      micStartedMs.current = performance.now();
      lastLiveSampleMs.current = 0;
      prevLiveEnergy.current = 0;
      setLiveFrames([]);
      setMicActive(true);
      note("Microphone audition started.");
      const waveform = new Uint8Array(analyser.fftSize);
      const spectrum = new Uint8Array(analyser.frequencyBinCount);
      const tick = () => {
        analyser.getByteTimeDomainData(waveform);
        analyser.getByteFrequencyData(spectrum);
        const nowMs = performance.now();
        const nowS = (nowMs - micStartedMs.current) / 1000;
        let squared = 0;
        for (let index = 0; index < waveform.length; index += 1) {
          const centered = (waveform[index] - 128) / 128;
          squared += centered * centered;
        }
        const bassStop = Math.floor(spectrum.length * 0.12);
        const midStop = Math.floor(spectrum.length * 0.52);
        const bass = average(Array.from(spectrum.slice(0, bassStop)).map((value) => value / 255));
        const mid = average(Array.from(spectrum.slice(bassStop, midStop)).map((value) => value / 255));
        const treble = average(Array.from(spectrum.slice(midStop)).map((value) => value / 255));
        const energy = clamp01(Math.sqrt(squared / waveform.length) * 1.8);
        const flux = clamp01(Math.max(0, energy - prevLiveEnergy.current) * 2.4);
        const motion = clamp01(average(Array.from(spectrum).map((value) => value / 255)));
        const nextFrame: Frame = { timeS: nowS, energy, bass, mid, treble, flux, motion, tension: clamp01(energy * 0.45 + flux * 0.2 + treble * 0.18 + motion * 0.17) };
        prevLiveEnergy.current = energy;
        setLiveFrame(nextFrame);
        if (nowMs - lastLiveSampleMs.current >= 120) {
          lastLiveSampleMs.current = nowMs;
          setLiveFrames((current) => [...current, nextFrame].slice(-180));
        }
        micRaf.current = requestAnimationFrame(tick);
      };
      micRaf.current = requestAnimationFrame(tick);
    } catch (reason) {
      const message = reason instanceof Error ? reason.message : String(reason);
      setError(message);
      note(`Microphone start failed: ${message}`);
    }
  };

  const stopMic = async () => {
    if (micRaf.current) cancelAnimationFrame(micRaf.current);
    micStream.current?.getTracks().forEach((track) => track.stop());
    micStream.current = null;
    micAnalyser.current = null;
    prevLiveEnergy.current = 0;
    if (micContext.current) await micContext.current.close().catch(() => undefined);
    micContext.current = null;
    setMicActive(false);
    note("Microphone audition stopped.");
  };

  return (
    <div style={styles.root}>
      <div style={styles.shell}>
        <section style={{ ...styles.panel, padding: 22 }}>
          <div style={{ display: "flex", justifyContent: "space-between", gap: 18, flexWrap: "wrap" }}>
            <div style={{ maxWidth: 840 }}>
              <div style={{ display: "inline-flex", gap: 8, alignItems: "center", padding: "8px 10px", borderRadius: 999, background: "rgba(90,132,255,0.12)", border: "1px solid rgba(120,153,255,0.2)", fontSize: 12, letterSpacing: "0.12em", textTransform: "uppercase", color: "#bcd0ff" }}>
                Archive Prototype / Future Studio Handoff
              </div>
              <h1 style={{ margin: "14px 0 10px", fontSize: 40, lineHeight: 1.04 }}>Audio-Reactive Direction Lab</h1>
              <p style={{ ...styles.subtle, fontSize: 15 }}>
                The old demo only emitted a flat settings file. This version adds file analysis, section extraction, motion schedules, prompt packs, and Studio-shaped export payloads while preserving live mic auditioning.
              </p>
            </div>
            <div style={{ minWidth: 240, display: "grid", gap: 8, alignContent: "start" }}>
              <div style={{ fontWeight: 800 }}>Preset</div>
              <div style={styles.subtle}>{preset}</div>
              <div style={{ fontWeight: 800 }}>Export shape</div>
              <div style={styles.subtle}>creative_direction + timeline_patch + deforum</div>
            </div>
          </div>
        </section>

        <section style={{ display: "grid", gridTemplateColumns: "minmax(340px,1.2fr) minmax(340px,1fr) minmax(320px,0.9fr)", gap: 18 }}>
          <div style={styles.panel}>
            <div style={{ display: "grid", gap: 12 }}>
              <div style={{ fontWeight: 800, fontSize: 18 }}>Source + transport</div>
              <input
                type="file"
                accept="audio/*"
                onChange={(event) => {
                  const file = event.target.files?.[0];
                  if (!file) return;
                  if (audioUrl) URL.revokeObjectURL(audioUrl);
                  const nextUrl = URL.createObjectURL(file);
                  setAudioFile(file);
                  setAudioUrl(nextUrl);
                  setAnalysis(null);
                  setCurrentS(0);
                  setDurationS(0);
                  setError("");
                  note(`Loaded ${file.name}. Run arrangement analysis for structured export.`);
                }}
                style={{ ...styles.input, padding: 10 }}
              />
              {audioUrl ? (
                <audio
                  src={audioUrl}
                  controls
                  style={{ width: "100%" }}
                  onLoadedMetadata={(event) => setDurationS(event.currentTarget.duration)}
                  onTimeUpdate={(event) => setCurrentS(event.currentTarget.currentTime)}
                />
              ) : null}
              <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
                <button
                  type="button"
                  disabled={!audioFile || isAnalyzing}
                  onClick={async () => {
                    if (!audioFile) return;
                    try {
                      setIsAnalyzing(true);
                      setError("");
                      const AudioContextCtor = window.AudioContext || (window as Window & { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
                      if (!AudioContextCtor) throw new Error("AudioContext is unavailable.");
                      const context = new AudioContextCtor();
                      const decoded = await context.decodeAudioData((await audioFile.arrayBuffer()).slice(0));
                      const nextAnalysis = analyzeBuffer(decoded);
                      setAnalysis(nextAnalysis);
                      setDurationS(nextAnalysis.durationS);
                      note(`Analyzed ${audioFile.name}: ${nextAnalysis.frames.length} frames across ${nextAnalysis.durationS.toFixed(1)} seconds.`);
                      await context.close();
                    } catch (reason) {
                      const message = reason instanceof Error ? reason.message : String(reason);
                      setError(message);
                      note(`Analysis failed: ${message}`);
                    } finally {
                      setIsAnalyzing(false);
                    }
                  }}
                  style={{ ...styles.button, background: !audioFile || isAnalyzing ? "rgba(50,56,79,0.7)" : "linear-gradient(120deg, #2a7fff, #7b5cff)", opacity: !audioFile || isAnalyzing ? 0.7 : 1 }}
                >
                  {isAnalyzing ? "Analyzing..." : "Analyze arrangement"}
                </button>
                <button type="button" onClick={micActive ? () => void stopMic() : () => void startMic()} style={{ ...styles.button, background: micActive ? "rgba(191,75,98,0.82)" : "rgba(17,71,55,0.84)" }}>
                  {micActive ? "Stop mic audition" : "Start mic audition"}
                </button>
              </div>
              <div style={styles.subtle}>
                {audioFile ? `${audioFile.name} ready.` : "No file uploaded."}
                {durationS > 0 ? ` Duration: ${durationS.toFixed(1)}s.` : ""}
              </div>
              {error ? <div style={{ color: "#ffb6c6", fontSize: 13 }}>{error}</div> : null}
            </div>
          </div>

          <div style={styles.panel}>
            <div style={{ display: "grid", gap: 12 }}>
              <div style={{ fontWeight: 800, fontSize: 18 }}>Reactive controls</div>
              <textarea value={brief} onChange={(event) => setBrief(event.target.value)} style={{ ...styles.input, minHeight: 94, resize: "vertical" }} />
              <input value={negative} onChange={(event) => setNegative(event.target.value)} style={styles.input} />
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
                <select value={preset} onChange={(event) => setPreset(event.target.value as Preset)} style={styles.input}>
                  <option value="cinematic">Cinematic</option>
                  <option value="pulse-grid">Pulse grid</option>
                  <option value="ambient-drift">Ambient drift</option>
                </select>
                <input type="number" min={3} max={8} value={sectionCount} onChange={(event) => setSectionCount(clamp(Number(event.target.value) || 6, 3, 8))} style={styles.input} />
                <div>
                  <input type="range" min={0.2} max={2.4} step={0.1} value={sensitivity} onChange={(event) => setSensitivity(Number(event.target.value))} />
                  <div style={styles.subtle}>Sensitivity {sensitivity.toFixed(1)}</div>
                </div>
                <div style={{ display: "grid", gridTemplateColumns: "84px 1fr", gap: 10 }}>
                  <input type="number" min={12} max={60} value={fps} onChange={(event) => setFps(clamp(Number(event.target.value) || 24, 12, 60))} style={styles.input} />
                  <input type="number" min={48} max={18000} value={renderFrames} onChange={(event) => setRenderFrames(clamp(Number(event.target.value) || 480, 48, 18000))} style={styles.input} />
                </div>
              </div>
              <div style={styles.subtle}>Controls feed the local bundle now and later can map directly to real Studio endpoints or timeline tracks.</div>
            </div>
          </div>

          <div style={styles.panel}>
            <div style={{ display: "grid", gap: 12 }}>
              <div style={{ fontWeight: 800, fontSize: 18 }}>Current readout</div>
              <div style={{ ...styles.subtle, marginBottom: 6 }}>{analysis ? "File analysis is active." : micActive ? "Live mic audition is active." : "Waiting for audio."}</div>
              {meterRows.map(([label, value, tone]) => (
                <div key={label} style={{ display: "grid", gap: 8 }}>
                  <div style={{ display: "flex", justifyContent: "space-between" }}><span style={styles.subtle}>{label}</span><span style={styles.subtle}>{Math.round(value * 100)}%</span></div>
                  <div style={{ height: 10, borderRadius: 999, background: "rgba(255,255,255,0.08)", overflow: "hidden" }}>
                    <div style={{ width: `${Math.round(clamp01(value) * 100)}%`, height: "100%", borderRadius: 999, background: tone }} />
                  </div>
                </div>
              ))}
              <div style={styles.subtle}>Dominant band: {analysis ? dominantBand(average(analysis.frames.map((frame) => frame.bass)), average(analysis.frames.map((frame) => frame.mid)), average(analysis.frames.map((frame) => frame.treble))) : liveBand || "--"}</div>
            </div>
          </div>
        </section>

        <section style={{ display: "grid", gridTemplateColumns: "minmax(420px,1.45fr) minmax(340px,0.95fr)", gap: 18 }}>
          <div style={styles.panel}>
            <div style={{ display: "flex", justifyContent: "space-between", gap: 12, flexWrap: "wrap", marginBottom: 12 }}>
              <div>
                <div style={{ fontWeight: 800, fontSize: 18 }}>Reactive stage</div>
                <div style={styles.subtle}>Energy, bass, and treble curves with section overlays and transport tracking.</div>
              </div>
              <div style={styles.subtle}>{frames.length ? `${frames.length} analysis points` : "No analysis points yet"}</div>
            </div>
            <div style={{ borderRadius: 18, overflow: "hidden", background: "linear-gradient(180deg, rgba(255,255,255,0.03), rgba(255,255,255,0.01)), linear-gradient(180deg, rgba(7,10,19,0.92), rgba(13,18,31,0.88))", border: "1px solid rgba(174,194,255,0.12)" }}>
              <svg viewBox="0 0 1000 320" style={{ width: "100%", display: "block" }}>
                {[0, 1, 2, 3, 4].map((line) => <line key={line} x1={0} x2={1000} y1={50 + line * 45} y2={50 + line * 45} stroke="rgba(255,255,255,0.08)" strokeDasharray="6 10" />)}
                {bundle?.sections.map((section, index) => {
                  const startX = (section.startS / Math.max(0.001, stageDuration)) * 1000;
                  const endX = (section.endS / Math.max(0.001, stageDuration)) * 1000;
                  return (
                    <g key={section.id}>
                      <rect x={startX} y={260} width={Math.max(12, endX - startX)} height={36} fill={index === selectedSection ? "rgba(123,156,255,0.24)" : "rgba(255,255,255,0.05)"} stroke={index === selectedSection ? "rgba(154,203,255,0.65)" : "rgba(255,255,255,0.08)"} rx={10} style={{ cursor: "pointer" }} onClick={() => setSelectedSection(index)} />
                      <text x={startX + 10} y={282} fill="#f5f7ff" fontSize={12}>{section.label}</text>
                    </g>
                  );
                })}
                {frames.length ? (
                  <>
                    <path d={pathFromFrames(frames, (frame) => frame.energy, 1000, 180)} fill="none" stroke="#35d8df" strokeWidth={4} />
                    <path d={pathFromFrames(frames, (frame) => frame.bass, 1000, 180)} fill="none" stroke="#ff9d66" strokeWidth={2.5} opacity={0.85} />
                    <path d={pathFromFrames(frames, (frame) => frame.treble, 1000, 180)} fill="none" stroke="#c998ff" strokeWidth={2.5} opacity={0.82} />
                  </>
                ) : null}
                {stageDuration > 0 ? <line x1={(playhead / Math.max(0.001, stageDuration)) * 1000} x2={(playhead / Math.max(0.001, stageDuration)) * 1000} y1={22} y2={304} stroke="rgba(255,255,255,0.9)" strokeWidth={2} /> : null}
              </svg>
            </div>
            <div style={{ ...styles.subtle, marginTop: 10 }}>Transport: {fmt(playhead)} / {stageDuration ? fmt(stageDuration) : "--"}</div>
          </div>

          <div style={styles.panel}>
            <div style={{ display: "grid", gap: 12 }}>
              <div style={{ fontWeight: 800, fontSize: 18 }}>Cue sheet</div>
              <div style={styles.subtle}>Each section already contains a prompt seed plus motion and camera direction for later Studio integration.</div>
              <div style={{ display: "grid", gap: 10, maxHeight: 320, overflowY: "auto", paddingRight: 4 }}>
                {bundle?.sections.length ? bundle.sections.map((section, index) => (
                  <button key={section.id} type="button" onClick={() => setSelectedSection(index)} style={{ ...styles.button, textAlign: "left", background: index === selectedSection ? "rgba(69,97,170,0.35)" : "rgba(8,13,26,0.76)" }}>
                    <div style={{ display: "flex", justifyContent: "space-between", gap: 12 }}>
                      <strong>{index + 1}. {section.label}</strong>
                      <span style={styles.subtle}>{section.band}</span>
                    </div>
                    <div style={{ ...styles.subtle, marginTop: 6 }}>{fmt(section.startS)} - {fmt(section.endS)} | {Math.round(section.avgEnergy * 100)}% avg energy</div>
                  </button>
                )) : <div style={styles.subtle}>Run arrangement analysis to populate the cue sheet.</div>}
              </div>
              {bundle?.sections[selectedSection] ? (
                <div style={{ borderRadius: 16, padding: 14, background: "rgba(8,13,26,0.8)", border: "1px solid rgba(174,194,255,0.14)", display: "grid", gap: 8 }}>
                  <div style={{ fontWeight: 800 }}>{bundle.sections[selectedSection].label}</div>
                  <div style={styles.subtle}><strong>Prompt:</strong> {bundle.sections[selectedSection].prompt}</div>
                  <div style={styles.subtle}><strong>Camera:</strong> {bundle.sections[selectedSection].camera}</div>
                  <div style={styles.subtle}><strong>Motion:</strong> {bundle.sections[selectedSection].motion}</div>
                </div>
              ) : null}
            </div>
          </div>
        </section>

        <section style={{ display: "grid", gridTemplateColumns: "minmax(420px,1.05fr) minmax(340px,0.95fr)", gap: 18 }}>
          <div style={styles.panel}>
            <div style={{ display: "flex", justifyContent: "space-between", gap: 12, flexWrap: "wrap", marginBottom: 12 }}>
              <div>
                <div style={{ fontWeight: 800, fontSize: 18 }}>Export preview</div>
                <div style={styles.subtle}>Everything is local and deterministic, but the output shape is intentionally close to real Studio data.</div>
              </div>
              <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                {(["prompt-pack", "timeline", "deforum", "bundle"] as Preview[]).map((mode) => (
                  <button key={mode} type="button" onClick={() => setPreview(mode)} style={{ ...styles.button, padding: "8px 12px", background: preview === mode ? "rgba(123,156,255,0.28)" : "rgba(8,13,26,0.76)" }}>
                    {mode}
                  </button>
                ))}
              </div>
            </div>
            <textarea readOnly value={previewText} style={{ ...styles.input, minHeight: 420, resize: "vertical", fontFamily: "Consolas, monospace" }} />
            <div style={{ display: "flex", gap: 10, flexWrap: "wrap", marginTop: 12 }}>
              <button type="button" disabled={!bundle} onClick={() => navigator.clipboard?.writeText(previewText)} style={{ ...styles.button, opacity: bundle ? 1 : 0.6 }}>
                Copy current preview
              </button>
              <button type="button" disabled={!bundle} onClick={() => downloadText(`audio-reactive-${preview}-${Date.now()}.${preview === "prompt-pack" ? "md" : "json"}`, previewText, preview === "prompt-pack" ? "text/markdown" : "application/json")} style={{ ...styles.button, opacity: bundle ? 1 : 0.6, background: "linear-gradient(120deg, #2a7fff, #7b5cff)" }}>
                Download current preview
              </button>
            </div>
          </div>

          <div style={styles.panel}>
            <div style={{ display: "grid", gap: 12 }}>
              <div style={{ fontWeight: 800, fontSize: 18 }}>Activity log</div>
              <div style={{ borderRadius: 16, padding: 14, background: "rgba(8,13,26,0.8)", border: "1px solid rgba(174,194,255,0.14)", minHeight: 220, display: "grid", gap: 8, alignContent: "start" }}>
                {log.length ? log.map((entry) => <div key={entry} style={{ ...styles.subtle, color: "#d9e4ff" }}>{entry}</div>) : <div style={styles.subtle}>Actions will appear here as you load files, analyze arrangement, or audition presets.</div>}
              </div>
              <div style={{ borderRadius: 16, padding: 14, background: "rgba(8,13,26,0.8)", border: "1px solid rgba(174,194,255,0.14)", display: "grid", gap: 8 }}>
                <div style={{ fontWeight: 800 }}>What changed</div>
                <div style={styles.subtle}>The prototype now extracts sections, emits prompt and motion clips, and serializes schedule data instead of only writing a flat config object.</div>
                <div style={styles.subtle}>Mic monitoring is preserved, but file analysis drives deterministic exports for future Studio handoff.</div>
              </div>
            </div>
          </div>
        </section>
      </div>
    </div>
  );
}
