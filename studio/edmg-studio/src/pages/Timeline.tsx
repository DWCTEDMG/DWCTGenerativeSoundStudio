import React, { useEffect, useRef, useState } from "react";
import { Pause, Play, Repeat, SkipBack, SkipForward, StepBack, StepForward } from "lucide-react";
import { apiFetch, apiGet, apiPost, getBackendUrl } from "../components/api";
import { hasProjectId, resolveProjectId } from "../components/projectSelection";
import { ProgressBar } from "../components/ProgressBar";
import { useOperationProgress } from "../components/useOperationProgress";
import { useStudioSession } from "../components/studioSession";
import type { PageProps } from "../types/pageProps";

type AnyDict = Record<string, any>;

type Clip = { id: string; start_s: number; end_s: number; data: AnyDict };
type Track = { id: string; name: string; type: string; clips: Clip[] };

type Selected =
  | { kind: "track"; trackIdx: number; clipIdx: number }
  | { kind: "overlay"; layerIdx: number }
  | { kind: "camera"; kfIdx: number }
  | null;

type DockSection = "handoffs" | "inspector" | "proxy" | "diffusion" | "curves";
type TimelineDensity = "compact" | "comfortable";

const TIMELINE_MIN_ZOOM = 4;
const TIMELINE_MAX_ZOOM = 360;
const TIMELINE_MIN_RANGE_S = 0.1;

function clamp(n: number, a: number, b: number) {
  return Math.max(a, Math.min(b, n));
}

function fmtTime(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds < 0) return "0:00.0";
  const mins = Math.floor(seconds / 60);
  const secs = seconds - mins * 60;
  return `${mins}:${secs.toFixed(1).padStart(4, "0")}`;
}

function parseDeforumSchedule(s: string): Array<[number, number]> {
  const out: Array<[number, number]> = [];
  const parts = String(s || "").split(",");
  for (const p of parts) {
    const part = p.trim();
    if (!part) continue;
    const m = part.match(/^(\d+)\s*:\s*\(?\s*([-+]?\d*\.?\d+)\s*\)?$/);
    if (!m) continue;
    out.push([Number(m[1]), Number(m[2])]);
  }
  out.sort((a, b) => a[0] - b[0]);
  // de-dup (last wins)
  const dedup: Record<string, number> = {};
  for (const [f, v] of out) dedup[String(f)] = v;
  return Object.entries(dedup)
    .map(([k, v]) => [Number(k), Number(v)] as [number, number])
    .sort((a, b) => a[0] - b[0]);
}

function evalSchedule(pairs: Array<[number, number]>, frame: number): number | null {
  if (!pairs.length) return null;
  const f = Math.round(frame);
  if (f <= pairs[0][0]) return pairs[0][1];
  if (f >= pairs[pairs.length - 1][0]) return pairs[pairs.length - 1][1];
  for (let i = 0; i < pairs.length - 1; i++) {
    const [a, av] = pairs[i];
    const [b, bv] = pairs[i + 1];
    if (a <= f && f <= b) {
      const w = (f - a) / Math.max(1e-9, b - a);
      return av * (1 - w) + bv * w;
    }
  }
  return pairs[pairs.length - 1][1];
}

function upsertPoint(s: string, frame: number, value: number): string {
  const pairs = parseDeforumSchedule(s);
  const map: Record<string, number> = {};
  for (const [f, v] of pairs) map[String(f)] = v;
  map[String(Math.max(0, Math.round(frame)))] = Number(value);
  const next = Object.entries(map)
    .map(([k, v]) => [Number(k), Number(v)] as [number, number])
    .sort((a, b) => a[0] - b[0]);
  return next.map(([f, v]) => `${f}:(${Number(v).toFixed(4)})`).join(", ");
}

function sampleCurve(
  pairs: Array<[number, number]>,
  durationSOrOptions:
    | number
    | { durationS: number; fps: number; samples: number; fallback: number },
  fpsArg?: number,
  samplesArg?: number,
  fallbackArg?: number,
): Array<[number, number]> {
  const opts =
    typeof durationSOrOptions === "object"
      ? durationSOrOptions
      : {
          durationS: durationSOrOptions,
          fps: Number(fpsArg || 0),
          samples: Number(samplesArg || 0),
          fallback: Number(fallbackArg ?? 0),
        };
  const durationS = Number(opts.durationS || 0);
  const fps = Number(opts.fps || 0);
  const samples = Number(opts.samples || 0);
  const fallback = Number(opts.fallback ?? 0);

  const out: Array<[number, number]> = [];
  const n = Math.max(8, samples | 0);
  for (let i = 0; i < n; i++) {
    const u = i / Math.max(1, n - 1);
    const t = u * durationS;
    const f = t * fps;
    const v = evalSchedule(pairs, f);
    out.push([t, v == null ? fallback : v]);
  }
  return out;
}

function svgPath(
  points: Array<[number, number]>,
  xMax: number,
  yMin: number,
  yMax: number,
  w: number,
  h: number,
): string {
  if (!points.length) return "";
  const clampY = (v: number) => {
    const u = (v - yMin) / Math.max(1e-9, yMax - yMin);
    return h - clamp(u, 0, 1) * h;
  };
  const X = (t: number) => clamp(t / Math.max(1e-9, xMax), 0, 1) * w;
  let d = `M ${X(points[0][0]).toFixed(2)} ${clampY(points[0][1]).toFixed(2)}`;
  for (const [t, v] of points.slice(1)) d += ` L ${X(t).toFixed(2)} ${clampY(v).toFixed(2)}`;
  return d;
}

function ensureTimelineShape(timeline: AnyDict, planVariant: AnyDict | null): AnyDict {
  const tl = timeline && typeof timeline === "object" ? { ...timeline } : {};
  const scenes: AnyDict[] =
    planVariant?.scenes && Array.isArray(planVariant.scenes) ? planVariant.scenes : [];

  const ensureTrack = (id: string, name: string, type: string, clips: Clip[]) => {
    tl.tracks = Array.isArray(tl.tracks) ? [...tl.tracks] : [];
    const idx = tl.tracks.findIndex(
      (t: AnyDict) => String(t?.type || "").toLowerCase() === type.toLowerCase(),
    );
    if (idx >= 0) {
      const cur = tl.tracks[idx] || {};
      tl.tracks[idx] = {
        id: cur.id || id,
        name: cur.name || name,
        type,
        clips: Array.isArray(cur.clips) ? cur.clips : clips,
      };
    } else {
      tl.tracks.push({ id, name, type, clips });
    }
  };

  // Prompt track from plan scenes (if not present)
  const promptClips: Clip[] = scenes.map((s: AnyDict, i: number) => ({
    id: String(s.id || `scene_${i}`),
    start_s: Number(s.start_s || i * 5),
    end_s: Number(s.end_s || Number(s.start_s || i * 5) + 5),
    data: { prompt: String(s.prompt || "").trim() || "cinematic" },
  }));
  ensureTrack("track_prompt", "Prompts", "prompt", promptClips);

  // Motion track: basic camera automation (if not present)
  const motionClips: Clip[] = scenes.map((s: AnyDict, i: number) => ({
    id: String(`motion_${s.id || i}`),
    start_s: Number(s.start_s || i * 5),
    end_s: Number(s.end_s || Number(s.start_s || i * 5) + 5),
    data: {
      zoom_start: 1.0,
      zoom_end: 1.06,
      pan_x_start: 0.0,
      pan_x_end: 0.0,
      pan_y_start: 0.0,
      pan_y_end: 0.0,
      rotation_start: 0.0,
      rotation_end: 0.0,
      strength: 0.35,
      cfg: 7.0,
      steps: 12,
    },
  }));
  ensureTrack("track_motion", "Motion", "motion", motionClips);

  // Overlays/layers (kept as timeline.layers to match compositor)
  tl.layers = Array.isArray(tl.layers) ? tl.layers : [];

  // Camera keyframes (optional)
  tl.camera = tl.camera && typeof tl.camera === "object" ? { ...tl.camera } : {};
  tl.camera.keyframes = Array.isArray(tl.camera.keyframes) ? tl.camera.keyframes : [];

  return tl;
}

async function fetchAudioPeaks(audioUrl: string, targetPoints: number): Promise<number[]> {
  const res = await apiFetch(audioUrl);
  if (!res.ok) return [];
  const buf = await res.arrayBuffer();
  const AudioCtx = (window as any).AudioContext || (window as any).webkitAudioContext;
  const ctx = new AudioCtx();
  const audio = await ctx.decodeAudioData(buf.slice(0));
  const ch = audio.getChannelData(0);
  const step = Math.max(1, Math.floor(ch.length / targetPoints));
  const peaks: number[] = [];
  for (let i = 0; i < ch.length; i += step) {
    let m = 0;
    for (let j = 0; j < step && i + j < ch.length; j++) m = Math.max(m, Math.abs(ch[i + j]));
    peaks.push(m);
  }
  try {
    ctx.close();
  } catch {}
  return peaks;
}

function fmtLabel(trackType: string, clip: Clip): string {
  const t = String(trackType || "").toLowerCase();
  if (t === "prompt") return String(clip?.data?.prompt || "prompt").slice(0, 34);
  if (t === "motion") {
    const z0 = Number(clip?.data?.zoom_start ?? 1).toFixed(2);
    const z1 = Number(clip?.data?.zoom_end ?? z0).toFixed(2);
    return `zoom ${z0}→${z1}`;
  }
  return String(clip?.id || "clip");
}

export default function Timeline({ backendUrl: backendUrlProp, onNavigate }: PageProps) {
  const {
    projectId: sessionProjectId,
    setProjectId,
    selectedVariant,
    setSelectedVariant,
    lastHandoff,
    clearHandoff,
  } = useStudioSession();
  const backendUrl = backendUrlProp || getBackendUrl();

  const [projects, setProjects] = useState<any[]>([]);
  const [project, setProject] = useState<any>(null);
  const [projectsReady, setProjectsReady] = useState(false);

  const [plan, setPlan] = useState<any>(null);

  const [timeline, setTimeline] = useState<AnyDict>({});
  const [timelineDirty, setTimelineDirty] = useState(false);

  const [durationS, setDurationS] = useState<number>(60);
  const [pxPerSecond, setPxPerSecond] = useState<number>(80);
  const [playheadS, setPlayheadS] = useState<number>(0);

  const [quantizeBeats, setQuantizeBeats] = useState<number>(1);
  const [bpmOverride, setBpmOverride] = useState<number | null>(null);
  const [loopEnabled, setLoopEnabled] = useState<boolean>(false);
  const [locatorInS, setLocatorInS] = useState<number>(0);
  const [locatorOutS, setLocatorOutS] = useState<number>(5);

  const [selected, setSelected] = useState<Selected>(null);

  const [audioUrl, setAudioUrl] = useState<string>("");
  const [isPlaying, setIsPlaying] = useState(false);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const timelineScrollRef = useRef<HTMLDivElement | null>(null);

  const [peaks, setPeaks] = useState<number[]>([]);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);

  const [previewUrl, setPreviewUrl] = useState<string>("");
  const previewTimer = useRef<any>(null);
  const autoFitKeyRef = useRef<string>("");

  const [proxyUrl, setProxyUrl] = useState<string>("");
  const [proxyBusy, setProxyBusy] = useState(false);
  const [proxyStart, setProxyStart] = useState<number>(0);
  const [proxyEnd, setProxyEnd] = useState<number>(5);
  const [proxyFps, setProxyFps] = useState<number>(6);

  const [diffUrl, setDiffUrl] = useState<string>("");
  const [diffBusy, setDiffBusy] = useState(false);
  const [diffStart, setDiffStart] = useState<number>(0);
  const [diffEnd, setDiffEnd] = useState<number>(2);
  const [diffFps, setDiffFps] = useState<number>(2);
  const [diffSteps, setDiffSteps] = useState<number>(6);
  const [diffCfg, setDiffCfg] = useState<number>(7.0);
  const [diffStrength, setDiffStrength] = useState<number>(0.45);
  const [diffW, setDiffW] = useState<number>(512);
  const [diffH, setDiffH] = useState<number>(512);
  const [diffModel, setDiffModel] = useState<string>("auto");
  const [dockSection, setDockSection] = useState<DockSection>("handoffs");
  const [timelineDensity, setTimelineDensity] = useState<TimelineDensity>("compact");

  const [err, setErr] = useState<string | null>(null);
  const { progress, runOperation } = useOperationProgress();
  const projectId = projectsReady && hasProjectId(projects, sessionProjectId) ? sessionProjectId : "";

  const refreshProjects = async () => {
    const d = await apiGet("/v1/projects");
    const nextProjects = Array.isArray(d?.projects) ? d.projects : [];
    setProjects(nextProjects);
    setProjectsReady(true);
    const nextProjectId = resolveProjectId(nextProjects, sessionProjectId);
    if (nextProjectId !== sessionProjectId) setProjectId(nextProjectId);
    if (!nextProjectId) {
      setProject(null);
      setPlan(null);
      setTimeline(ensureTimelineShape({}, null));
      setTimelineDirty(false);
      setAudioUrl("");
    }
  };

  const refreshProject = async (pid: string) => {
    const d = await apiGet(`/v1/projects/${pid}`);
    setProject(d?.project || null);
    const p = d?.project || {};
    const tl = ensureTimelineShape(
      p?.meta?.timeline || {},
      (p?.meta?.last_plan?.variants || [])[selectedVariant] || null,
    );
    setTimeline(tl);
    setTimelineDirty(false);

    const dur = Number(
      p?.meta?.audio?.duration_s || p?.meta?.analysis?.features?.duration_s || p?.duration_s || 60,
    );
    setDurationS(Number.isFinite(dur) && dur > 0 ? dur : 60);

    const audioFn = p?.meta?.audio?.filename;
    if (audioFn) setAudioUrl(`${backendUrl}/v1/projects/${pid}/audio?v=${Date.now()}`);
    else setAudioUrl("");

    setPlan(p?.meta?.last_plan || null);
    const variantCount = Array.isArray(p?.meta?.last_plan?.variants) ? p.meta.last_plan.variants.length : 0;
    if (variantCount > 0 && selectedVariant > variantCount - 1) setSelectedVariant(0);
  };

  useEffect(() => {
    refreshProjects().catch(() => {});
  }, []);
  useEffect(() => {
    if (!projectsReady) return;
    if (projectId) refreshProject(projectId).catch(() => {});
    else {
      setProject(null);
      setPlan(null);
      setTimeline(ensureTimelineShape({}, null));
      setTimelineDirty(false);
      setAudioUrl("");
    }
  }, [projectId, projectsReady, selectedVariant]);

  useEffect(() => {
    if (!audioUrl) {
      setPeaks([]);
      return;
    }
    fetchAudioPeaks(audioUrl, 800)
      .then(setPeaks)
      .catch(() => setPeaks([]));
  }, [audioUrl]);

  useEffect(() => {
    setIsPlaying(false);
  }, [audioUrl]);

  useEffect(() => {
    const audioEl = audioRef.current;
    if (!audioEl) return;

    const handlePlay = () => setIsPlaying(true);
    const handlePause = () => setIsPlaying(false);
    const handleEnded = () => setIsPlaying(false);
    const handleTimeUpdate = () => {
      const currentTime = audioEl.currentTime || 0;
      if (loopEnabled && locatorOutS > locatorInS + TIMELINE_MIN_RANGE_S && currentTime >= locatorOutS) {
        audioEl.currentTime = locatorInS;
        setPlayheadS(locatorInS);
        if (!audioEl.paused) audioEl.play().catch(() => {});
        return;
      }
      setPlayheadS(currentTime);
    };

    audioEl.addEventListener("play", handlePlay);
    audioEl.addEventListener("pause", handlePause);
    audioEl.addEventListener("ended", handleEnded);
    audioEl.addEventListener("timeupdate", handleTimeUpdate);

    return () => {
      audioEl.removeEventListener("play", handlePlay);
      audioEl.removeEventListener("pause", handlePause);
      audioEl.removeEventListener("ended", handleEnded);
      audioEl.removeEventListener("timeupdate", handleTimeUpdate);
    };
  }, [audioUrl, loopEnabled, locatorInS, locatorOutS]);

  // draw waveform
  useEffect(() => {
    const c = canvasRef.current;
    if (!c || !peaks.length) return;
    const ctx = c.getContext("2d");
    if (!ctx) return;
    const w = c.width,
      h = c.height;
    ctx.clearRect(0, 0, w, h);
    ctx.fillStyle = "rgba(255,255,255,0.08)";
    const n = peaks.length;
    for (let i = 0; i < n; i++) {
      const x = Math.floor((i / n) * w);
      const ph = Math.max(1, Math.floor(peaks[i] * h));
      ctx.fillRect(x, Math.floor((h - ph) / 2), 1, ph);
    }
  }, [peaks, durationS, pxPerSecond]);

  // scrub preview frame
  useEffect(() => {
    if (!projectId) return;
    // During playback the playhead updates several times per second; refreshing
    // the cached program-monitor frame on every tick floods the backend and
    // causes jank. The monitor is most useful while paused/scrubbing, so skip
    // refreshes while audio is playing and update once playback stops.
    if (isPlaying) return;
    if (previewTimer.current) clearTimeout(previewTimer.current);
    previewTimer.current = setTimeout(() => {
      setPreviewUrl(
        `${backendUrl}/v1/projects/${projectId}/preview/frame?t=${encodeURIComponent(String(playheadS))}&w=768&h=432&v=${Date.now()}`,
      );
    }, 60);
    return () => {
      if (previewTimer.current) clearTimeout(previewTimer.current);
    };
  }, [projectId, playheadS, isPlaying]);

  const tracks: Track[] = Array.isArray(timeline?.tracks) ? timeline.tracks : [];
  const layers: AnyDict[] = Array.isArray(timeline?.layers) ? timeline.layers : [];
  const camKeyframes: AnyDict[] = Array.isArray(timeline?.camera?.keyframes)
    ? timeline.camera.keyframes
    : [];

  const onWaveformClick = (e: React.MouseEvent) => {
    const c = canvasRef.current;
    if (!c) return;
    const rect = c.getBoundingClientRect();
    const u = clamp((e.clientX - rect.left) / Math.max(1, rect.width), 0, 1);
    const t = u * durationS;
    seekTo(t);
  };

  const clipPx = (t: number) => Math.round(t * pxPerSecond);
  const seekTo = (seconds: number, syncAudio = true) => {
    const next = clamp(Number(seconds) || 0, 0, Math.max(0, durationS));
    setPlayheadS(next);
    if (syncAudio && audioRef.current) {
      audioRef.current.currentTime = next;
    }
  };

  const setTimelineZoomWithFocus = (nextZoom: number, focusSeconds?: number) => {
    const scroller = timelineScrollRef.current;
    const clamped = clamp(nextZoom, TIMELINE_MIN_ZOOM, TIMELINE_MAX_ZOOM);
    if (!scroller) {
      setPxPerSecond(clamped);
      return;
    }

    const currentZoom = Math.max(1, pxPerSecond);
    const focus =
      focusSeconds ??
      (scroller.scrollLeft + scroller.clientWidth / 2) / currentZoom;
    setPxPerSecond(clamped);
    requestAnimationFrame(() => {
      const nextLeft = Math.max(0, focus * clamped - scroller.clientWidth / 2);
      if (typeof scroller.scrollTo === "function") {
        scroller.scrollTo({
          left: nextLeft,
          behavior: "smooth",
        });
      } else {
        scroller.scrollLeft = nextLeft;
      }
    });
  };

  const fitTimelineZoom = () => {
    const scroller = timelineScrollRef.current;
    const viewport = scroller?.clientWidth ?? 1100;
    const nextZoom = (Math.max(320, viewport) - 96) / Math.max(durationS, 8);
    setTimelineZoomWithFocus(nextZoom, 0);
  };

  useEffect(() => {
    if (!projectId || durationS <= 0) return;
    const key = `${projectId}:${selectedVariant}:${durationS.toFixed(2)}`;
    if (autoFitKeyRef.current === key) return;
    autoFitKeyRef.current = key;
    const useRaf = typeof window.requestAnimationFrame === "function";
    const handle = useRaf
      ? window.requestAnimationFrame(() => fitTimelineZoom())
      : window.setTimeout(() => fitTimelineZoom(), 0);
    return () => {
      if (useRaf) window.cancelAnimationFrame(handle);
      else window.clearTimeout(handle);
    };
  }, [projectId, selectedVariant, durationS]);

  useEffect(() => {
    if (lastHandoff && lastHandoff.projectId === projectId) setDockSection("handoffs");
  }, [lastHandoff, projectId]);

  const onTimelineWheel = (event: React.WheelEvent<HTMLDivElement>) => {
    if (!(event.ctrlKey || event.metaKey)) return;
    const scroller = timelineScrollRef.current;
    if (!scroller) return;
    event.preventDefault();
    const rect = scroller.getBoundingClientRect();
    const focusSeconds =
      (scroller.scrollLeft + (event.clientX - rect.left)) / Math.max(1, pxPerSecond);
    const nextZoom = event.deltaY < 0 ? pxPerSecond * 1.1 : pxPerSecond / 1.1;
    setTimelineZoomWithFocus(nextZoom, focusSeconds);
  };

  const dragRef = useRef<any>(null);

  const onTrackClipPointerDown =
    (trackIdx: number, clipIdx: number, mode: "move" | "left" | "right") =>
    (e: React.PointerEvent) => {
      e.preventDefault();
      e.stopPropagation();
      const tr = tracks[trackIdx];
      const cl = tr?.clips?.[clipIdx];
      if (!cl) return;
      (e.currentTarget as any).setPointerCapture?.(e.pointerId);
      dragRef.current = {
        kind: "track",
        trackIdx,
        clipIdx,
        mode,
        x0: e.clientX,
        start0: cl.start_s,
        end0: cl.end_s,
      };
      setSelected({ kind: "track", trackIdx, clipIdx });
      setProxyStart(cl.start_s);
      setProxyEnd(cl.end_s);
    };

  const onOverlayPointerDown =
    (layerIdx: number, mode: "move" | "left" | "right") => (e: React.PointerEvent) => {
      e.preventDefault();
      e.stopPropagation();
      const l = layers[layerIdx];
      if (!l) return;
      (e.currentTarget as any).setPointerCapture?.(e.pointerId);
      const s0 = Number(l.start_s ?? 0);
      const e0 = Number(l.end_s ?? durationS);
      dragRef.current = { kind: "overlay", layerIdx, mode, x0: e.clientX, start0: s0, end0: e0 };
      setSelected({ kind: "overlay", layerIdx });
      setProxyStart(s0);
      setProxyEnd(e0);
    };

  const onCameraKfPointerDown = (kfIdx: number) => (e: React.PointerEvent) => {
    e.preventDefault();
    e.stopPropagation();
    const k = camKeyframes[kfIdx];
    if (!k) return;
    (e.currentTarget as any).setPointerCapture?.(e.pointerId);
    dragRef.current = { kind: "camera", kfIdx, x0: e.clientX, t0: Number(k.t || 0) };
    setSelected({ kind: "camera", kfIdx });
    setProxyStart(Math.max(0, Number(k.t || 0) - 1));
    setProxyEnd(Math.min(durationS, Number(k.t || 0) + 2));
  };

  const onTimelinePointerMove = (e: React.PointerEvent) => {
    const st = dragRef.current;
    if (!st) return;
    const dx = (e.clientX - st.x0) / pxPerSecond;

    if (st.kind === "track") {
      const tr = tracks[st.trackIdx];
      const cl = tr?.clips?.[st.clipIdx];
      if (!tr || !cl) return;
      let start = st.start0,
        end = st.end0;
      if (st.mode === "move") {
        start = st.start0 + dx;
        end = st.end0 + dx;
      }
      if (st.mode === "left") {
        start = st.start0 + dx;
      }
      if (st.mode === "right") {
        end = st.end0 + dx;
      }
      start = clamp(start, 0, durationS - 0.05);
      end = clamp(end, start + 0.05, durationS);

      const nextTracks = tracks.map((t, i) => {
        if (i !== st.trackIdx) return t;
        const nextClips = (t.clips || []).map((c, j) =>
          j === st.clipIdx ? { ...c, start_s: start, end_s: end } : c,
        );
        return { ...t, clips: nextClips };
      });

      setTimeline({ ...timeline, tracks: nextTracks });
      setTimelineDirty(true);
      return;
    }

    if (st.kind === "overlay") {
      const l = layers[st.layerIdx];
      if (!l) return;
      let start = st.start0,
        end = st.end0;
      if (st.mode === "move") {
        start = st.start0 + dx;
        end = st.end0 + dx;
      }
      if (st.mode === "left") {
        start = st.start0 + dx;
      }
      if (st.mode === "right") {
        end = st.end0 + dx;
      }
      start = clamp(start, 0, durationS - 0.05);
      end = clamp(end, start + 0.05, durationS);

      const nextLayers = layers.map((x, i) =>
        i === st.layerIdx ? { ...x, start_s: start, end_s: end } : x,
      );
      setTimeline({ ...timeline, layers: nextLayers });
      setTimelineDirty(true);
      return;
    }

    if (st.kind === "camera") {
      const k = camKeyframes[st.kfIdx];
      if (!k) return;
      let t = clamp(st.t0 + dx, 0, durationS);
      const next = camKeyframes.map((x, i) => (i === st.kfIdx ? { ...x, t } : x));
      next.sort((a, b) => Number(a.t || 0) - Number(b.t || 0));
      setTimeline({ ...timeline, camera: { ...(timeline.camera || {}), keyframes: next } });
      setTimelineDirty(true);
    }
  };

  const onTimelinePointerUp = () => {
    dragRef.current = null;
  };

  const saveTimeline = async () => {
    if (!projectId) return;
    setErr(null);
    try {
      const saved = await runOperation(
        {
          label: "Saving timeline",
          detail: "Persisting arrangement edits for the active session.",
          successDetail: "Timeline saved.",
        },
        () => apiPost(`/v1/projects/${projectId}/timeline`, { timeline }),
      );
      setTimeline(saved?.timeline || timeline);
      setTimelineDirty(false);
      // invalidate proxy preview on save
      setProxyUrl("");
      setProxyBusy(false);
    } catch (e: any) {
      setErr(String(e));
    }
  };

  const deleteSelection = () => {
    if (!selected) return;
    if (selected.kind === "track") {
      const tr = tracks[selected.trackIdx];
      if (!tr) return;
      const nextTracks = tracks.map((t, i) =>
        i === selected.trackIdx
          ? { ...t, clips: (t.clips || []).filter((_, j) => j !== selected.clipIdx) }
          : t,
      );
      setTimeline({ ...timeline, tracks: nextTracks });
      setTimelineDirty(true);
      setSelected(null);
      return;
    }
    if (selected.kind === "overlay") {
      const nextLayers = layers.filter((_, i) => i !== selected.layerIdx);
      setTimeline({ ...timeline, layers: nextLayers });
      setTimelineDirty(true);
      setSelected(null);
      return;
    }
    if (selected.kind === "camera") {
      const next = camKeyframes.filter((_, i) => i !== selected.kfIdx);
      setTimeline({ ...timeline, camera: { ...(timeline.camera || {}), keyframes: next } });
      setTimelineDirty(true);
      setSelected(null);
    }
  };

  const nudgeSelectionToPlayhead = () => {
    if (!selected) return;
    const target = clamp(playheadS, 0, durationS);
    if (selected.kind === "track") {
      const picked = selectedTrackClip(selected);
      if (!picked) return;
      const dur = Math.max(_minLen, Number(picked.cl.end_s) - Number(picked.cl.start_s));
      const s = clamp(target, 0, Math.max(0, durationS - dur));
      const e = clamp(s + dur, s + _minLen, durationS);
      const nextTracks = tracks.map((t, i) => {
        if (i !== selected.trackIdx) return t;
        const nextClips = (t.clips || []).map((c, j) =>
          j === selected.clipIdx ? { ...c, start_s: s, end_s: e } : c,
        );
        return { ...t, clips: nextClips };
      });
      setTimeline({ ...timeline, tracks: nextTracks });
      setTimelineDirty(true);
      return;
    }
    if (selected.kind === "overlay") {
      const l = layers[selected.layerIdx];
      if (!l) return;
      const dur = Math.max(_minLen, Number(l.end_s ?? durationS) - Number(l.start_s ?? 0));
      const s = clamp(target, 0, Math.max(0, durationS - dur));
      const e = clamp(s + dur, s + _minLen, durationS);
      updateSelectedOverlayTimes(s, e);
      return;
    }
    if (selected.kind === "camera") {
      updateSelectedCamera({ t: target });
    }
  };

  const syncToRenderer = async () => {
    if (!projectId) return;
    setErr(null);
    try {
      const saved = await runOperation(
        {
          label: "Syncing timeline to renderer",
          detail: "Saving arrangement edits and opening the internal renderer.",
          successDetail: "Timeline saved and sent to the internal renderer.",
        },
        () => apiPost(`/v1/projects/${projectId}/timeline`, { timeline }),
      );
      setTimeline(saved?.timeline || timeline);
      setTimelineDirty(false);
      setProxyUrl("");
      setProxyBusy(false);
      onNavigate?.("render");
    } catch (e: any) {
      setErr(String(e));
    }
  };

  const addClip = (type: "prompt" | "motion") => {
    const idx = tracks.findIndex((t) => String(t.type).toLowerCase() === type);
    if (idx < 0) return;
    const s = clamp(playheadS, 0, Math.max(0, durationS - 0.5));
    const e = clamp(s + 5, s + 0.2, durationS);
    const id = `${type}_${Date.now()}`;
    const data =
      type === "prompt"
        ? { prompt: "cinematic" }
        : {
            zoom_start: 1.0,
            zoom_end: 1.06,
            pan_x_start: 0,
            pan_x_end: 0,
            pan_y_start: 0,
            pan_y_end: 0,
            rotation_start: 0,
            rotation_end: 0,
            strength: 0.35,
            cfg: 7.0,
            steps: 12,
          };

    const nextTracks = tracks.map((t, i) =>
      i === idx ? { ...t, clips: [...(t.clips || []), { id, start_s: s, end_s: e, data }] } : t,
    );
    setTimeline({ ...timeline, tracks: nextTracks });
    setTimelineDirty(true);
  };

  const addCameraKeyframe = () => {
    const s = clamp(playheadS, 0, durationS);
    const k = { t: s, zoom: 1.0, pan_x: 0.0, pan_y: 0.0, rotation_deg: 0.0 };
    const next = [...camKeyframes, k].sort((a, b) => Number(a.t || 0) - Number(b.t || 0));
    setTimeline({ ...timeline, camera: { ...(timeline.camera || {}), keyframes: next } });
    setTimelineDirty(true);
  };

  const _bpm = () => {
    const b =
      bpmOverride ??
      Number(
        project?.meta?.analysis?.features?.bpm ??
          project?.meta?.analysis?.features?.tempo_bpm ??
          project?.meta?.analysis?.features?.tempo ??
          project?.meta?.last_plan?.bpm ??
          0,
      );
    return Number.isFinite(b) && b > 20 ? b : null;
  };

  const _beatTimes = (): number[] => {
    const feats = project?.meta?.analysis?.features || {};
    const raw =
      feats.beat_times_s ??
      feats.beat_times ??
      feats.beats_s ??
      feats.beats ??
      feats.beat_times_seconds ??
      null;

    const out: number[] = [];
    const push = (v: any) => {
      const n = Number(v);
      if (Number.isFinite(n) && n >= 0) out.push(n);
    };

    if (Array.isArray(raw)) {
      for (const it of raw) {
        if (typeof it === "number" || typeof it === "string") push(it);
        else if (it && typeof it === "object") push(it.t ?? it.time ?? it.sec ?? it.s);
      }
    }

    out.sort((a, b) => a - b);
    // Ensure 0 exists to make snapping predictable.
    if (!out.length || out[0] > 0.05) out.unshift(0);
    // De-dupe near-equals.
    const dedup: number[] = [];
    for (const t of out) {
      if (!dedup.length || Math.abs(dedup[dedup.length - 1] - t) > 1e-3) dedup.push(t);
    }
    return dedup;
  };

  const _quantStepS = () => {
    const bpm = _bpm();
    if (!bpm) return null;
    const beats = Number(quantizeBeats) || 1;
    return (60.0 / bpm) * beats;
  };

  const _beatGrid = (): number[] | null => {
    const beats = _beatTimes();
    if (beats.length < 2) return null;
    const n = Math.max(1, Math.floor(Number(quantizeBeats) || 1));
    if (n === 1) return beats;
    const grid: number[] = [];
    for (let i = 0; i < beats.length; i++) if (i % n === 0) grid.push(beats[i]);
    return grid.length >= 2 ? grid : beats;
  };

  const _nearestInSorted = (arr: number[], t: number) => {
    if (!arr.length) return t;
    let lo = 0;
    let hi = arr.length - 1;
    while (lo <= hi) {
      const mid = (lo + hi) >> 1;
      const v = arr[mid];
      if (v < t) lo = mid + 1;
      else if (v > t) hi = mid - 1;
      else return v;
    }
    const a = clamp(hi, 0, arr.length - 1);
    const b = clamp(lo, 0, arr.length - 1);
    return Math.abs(arr[a] - t) <= Math.abs(arr[b] - t) ? arr[a] : arr[b];
  };

  const _nextAfter = (arr: number[], t: number) => {
    if (!arr.length) return null;
    let lo = 0;
    let hi = arr.length - 1;
    while (lo <= hi) {
      const mid = (lo + hi) >> 1;
      if (arr[mid] < t) lo = mid + 1;
      else hi = mid - 1;
    }
    return lo >= 0 && lo < arr.length ? arr[lo] : null;
  };

  const _snap = (t: number) => {
    // Prefer true beat timestamps when available.
    const grid = _beatGrid();
    if (grid && grid.length >= 2) return Math.max(0, _nearestInSorted(grid, t));

    // Fallback: BPM grid.
    const step = _quantStepS();
    if (!step) return t;
    return Math.max(0, Math.round(t / step) * step);
  };

  const _minLen = TIMELINE_MIN_RANGE_S;

  const duplicateSelection = () => {
    if (!selected) return;
    if (selected.kind === "track") {
      const tr = tracks[selected.trackIdx];
      const cl = tr?.clips?.[selected.clipIdx];
      if (!tr || !cl) return;
      const dur = Math.max(_minLen, Number(cl.end_s) - Number(cl.start_s));
      const s = clamp(playheadS, 0, Math.max(0, durationS - dur));
      const e = clamp(s + dur, s + _minLen, durationS);
      const id = `${String(tr.type)}_${Date.now()}`;
      const nextTracks = tracks.map((t, i) => {
        if (i !== selected.trackIdx) return t;
        return { ...t, clips: [...(t.clips || []), { ...cl, id, start_s: s, end_s: e }] };
      });
      setTimeline({ ...timeline, tracks: nextTracks });
      setTimelineDirty(true);
      return;
    }
    if (selected.kind === "overlay") {
      const l = layers[selected.layerIdx];
      if (!l) return;
      const dur = Math.max(_minLen, Number(l.end_s ?? durationS) - Number(l.start_s ?? 0));
      const s = clamp(playheadS, 0, Math.max(0, durationS - dur));
      const e = clamp(s + dur, s + _minLen, durationS);
      const nextLayers = layers.map((x, i) => (i === selected.layerIdx ? x : x));
      nextLayers.push({ ...l, start_s: s, end_s: e });
      setTimeline({ ...timeline, layers: nextLayers });
      setTimelineDirty(true);
      return;
    }
    if (selected.kind === "camera") {
      const k = camKeyframes[selected.kfIdx];
      if (!k) return;
      const t = clamp(playheadS, 0, durationS);
      const next = [...camKeyframes, { ...k, t }].sort(
        (a, b) => Number(a.t || 0) - Number(b.t || 0),
      );
      setTimeline({ ...timeline, camera: { ...(timeline.camera || {}), keyframes: next } });
      setTimelineDirty(true);
    }
  };

  const splitSelection = () => {
    if (!selected) return;
    const tSplit = clamp(playheadS, 0, durationS);
    if (selected.kind === "track") {
      const tr = tracks[selected.trackIdx];
      const cl = tr?.clips?.[selected.clipIdx];
      if (!tr || !cl) return;
      if (!(cl.start_s + _minLen < tSplit && tSplit < cl.end_s - _minLen)) return;
      const left = { ...cl, end_s: tSplit };
      const right = { ...cl, id: `${String(tr.type)}_${Date.now()}`, start_s: tSplit };
      const nextTracks = tracks.map((t, i) => {
        if (i !== selected.trackIdx) return t;
        const nextClips = (t.clips || []).flatMap((c, j) =>
          j === selected.clipIdx ? [left, right] : [c],
        );
        return { ...t, clips: nextClips };
      });
      setTimeline({ ...timeline, tracks: nextTracks });
      setTimelineDirty(true);
      return;
    }
    if (selected.kind === "overlay") {
      const l = layers[selected.layerIdx];
      if (!l) return;
      const s0 = Number(l.start_s ?? 0),
        e0 = Number(l.end_s ?? durationS);
      if (!(s0 + _minLen < tSplit && tSplit < e0 - _minLen)) return;
      const left = { ...l, end_s: tSplit };
      const right = { ...l, start_s: tSplit };
      const nextLayers = layers.flatMap((x, i) => (i === selected.layerIdx ? [left, right] : [x]));
      setTimeline({ ...timeline, layers: nextLayers });
      setTimelineDirty(true);
    }
  };

  const quantizeSelection = () => {
    const grid = _beatGrid();
    const step = _quantStepS();
    if (!grid && !step) {
      setErr(
        "No beat grid available for quantize. Run Analyze (beat detection) or set BPM override.",
      );
      return;
    }
    if (!selected) return;

    const snapRange = (s: number, e: number) => {
      const ss = clamp(_snap(s), 0, durationS - _minLen);

      // If beat-grid snapping is active, prefer aligning end to a later beat boundary.
      const grid = _beatGrid();
      let ee0 = _snap(e);
      const minEnd = ss + _minLen;
      if (grid && grid.length >= 2 && ee0 < minEnd) {
        const next = _nextAfter(grid, minEnd);
        if (next != null) ee0 = next;
      }
      const ee = clamp(ee0, minEnd, durationS);
      return [ss, ee] as const;
    };

    if (selected.kind === "track") {
      const tr = tracks[selected.trackIdx];
      const cl = tr?.clips?.[selected.clipIdx];
      if (!tr || !cl) return;
      const [ss, ee] = snapRange(Number(cl.start_s), Number(cl.end_s));
      const nextTracks = tracks.map((t, i) => {
        if (i !== selected.trackIdx) return t;
        const nextClips = (t.clips || []).map((c, j) =>
          j === selected.clipIdx ? { ...c, start_s: ss, end_s: ee } : c,
        );
        return { ...t, clips: nextClips };
      });
      setTimeline({ ...timeline, tracks: nextTracks });
      setTimelineDirty(true);
      return;
    }

    if (selected.kind === "overlay") {
      const l = layers[selected.layerIdx];
      if (!l) return;
      const [ss, ee] = snapRange(Number(l.start_s ?? 0), Number(l.end_s ?? durationS));
      updateSelectedOverlayTimes(ss, ee);
      return;
    }

    if (selected.kind === "camera") {
      const k = camKeyframes[selected.kfIdx];
      if (!k) return;
      const tt = clamp(_snap(Number(k.t || 0)), 0, durationS);
      updateSelectedCamera({ t: tt });
    }
  };

  // Hotkeys (Timeline page)
  // S = split @ playhead, D = duplicate @ playhead, Q = quantize selection
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.ctrlKey || e.metaKey) return;
      // Allow Alt for other UI features; but prevent hotkey clashes when typing.
      const el = document.activeElement as any;
      const tag = String(el?.tagName || "").toUpperCase();
      if (tag === "INPUT" || tag === "TEXTAREA" || el?.isContentEditable) return;

      const k = e.key;
      if (k === "s" || k === "S") {
        e.preventDefault();
        splitSelection();
        return;
      }
      if (k === "d" || k === "D") {
        e.preventDefault();
        duplicateSelection();
        return;
      }
      if (k === "q" || k === "Q") {
        e.preventDefault();
        quantizeSelection();
        return;
      }
      if (k === "Delete" || k === "Backspace") {
        e.preventDefault();
        deleteSelection();
        return;
      }
    };

    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [
    selected,
    playheadS,
    durationS,
    quantizeBeats,
    bpmOverride,
    timeline,
    splitSelection,
    duplicateSelection,
    quantizeSelection,
    deleteSelection,
  ]);

  const setDiffRangeFromSelection = () => {
    if (!selected) return;
    if (selected.kind === "track") {
      const picked = selectedTrackClip(selected);
      if (!picked) return;
      setDiffStart(Number(picked.cl.start_s));
      setDiffEnd(Number(picked.cl.end_s));
      return;
    }
    if (selected.kind === "overlay") {
      const l = layers[selected.layerIdx];
      if (!l) return;
      setDiffStart(Number(l.start_s ?? 0));
      setDiffEnd(Number(l.end_s ?? durationS));
      return;
    }
    if (selected.kind === "camera") {
      const k = camKeyframes[selected.kfIdx];
      if (!k) return;
      const t = Number(k.t || 0);
      setDiffStart(clamp(t - 1.0, 0, durationS));
      setDiffEnd(clamp(t + 1.0, 0, durationS));
    }
  };

  const generateDiffusionPreview = () => {
    if (!projectId) return;
    const s = clamp(Number(diffStart), 0, durationS);
    const e = clamp(Number(diffEnd), s + 0.05, durationS);
    setDiffBusy(true);
    setDiffUrl(
      `${backendUrl}/v1/projects/${projectId}/preview/diffusion_segment?start_s=${encodeURIComponent(String(s))}&end_s=${encodeURIComponent(String(e))}` +
        `&w=${encodeURIComponent(String(diffW))}&h=${encodeURIComponent(String(diffH))}` +
        `&fps=${encodeURIComponent(String(diffFps))}&steps=${encodeURIComponent(String(diffSteps))}` +
        `&cfg=${encodeURIComponent(String(diffCfg))}&strength=${encodeURIComponent(String(diffStrength))}` +
        `&model_id=${encodeURIComponent(String(diffModel))}` +
        `&variant_index=${encodeURIComponent(String(selectedVariant || 0))}` +
        `&force=1&v=${Date.now()}`,
    );
  };

  const selectedTrackClip = (sel: Selected) => {
    if (!sel || sel.kind !== "track") return null;
    const tr = tracks[sel.trackIdx];
    const cl = tr?.clips?.[sel.clipIdx];
    if (!tr || !cl) return null;
    return { tr, cl };
  };

  const updateSelectedClipData = (patch: AnyDict) => {
    if (!selected || selected.kind !== "track") return;
    const tr = tracks[selected.trackIdx];
    const cl = tr?.clips?.[selected.clipIdx];
    if (!tr || !cl) return;
    const nextTracks = tracks.map((t, i) => {
      if (i !== selected.trackIdx) return t;
      const nextClips = (t.clips || []).map((c, j) =>
        j === selected.clipIdx ? { ...c, data: { ...(c.data || {}), ...patch } } : c,
      );
      return { ...t, clips: nextClips };
    });
    setTimeline({ ...timeline, tracks: nextTracks });
    setTimelineDirty(true);
  };

  const updateSelectedOverlayTimes = (start_s: number, end_s: number) => {
    if (!selected || selected.kind !== "overlay") return;
    const idx = selected.layerIdx;
    const nextLayers = layers.map((x, i) => (i === idx ? { ...x, start_s, end_s } : x));
    setTimeline({ ...timeline, layers: nextLayers });
    setTimelineDirty(true);
  };

  const updateSelectedCamera = (patch: AnyDict) => {
    if (!selected || selected.kind !== "camera") return;
    const idx = selected.kfIdx;
    const next = camKeyframes
      .map((x, i) => (i === idx ? { ...x, ...patch } : x))
      .sort((a, b) => Number(a.t || 0) - Number(b.t || 0));
    setTimeline({ ...timeline, camera: { ...(timeline.camera || {}), keyframes: next } });
    setTimelineDirty(true);
  };

  const selectedTimeRange = (): [number, number] | null => {
    if (!selected) return null;
    if (selected.kind === "track") {
      const picked = selectedTrackClip(selected);
      if (!picked) return null;
      return [Number(picked.cl.start_s), Number(picked.cl.end_s)];
    }
    if (selected.kind === "overlay") {
      const layer = layers[selected.layerIdx];
      if (!layer) return null;
      return [Number(layer.start_s ?? 0), Number(layer.end_s ?? durationS)];
    }
    if (selected.kind === "camera") {
      const keyframe = camKeyframes[selected.kfIdx];
      if (!keyframe) return null;
      const t = Number(keyframe.t || 0);
      return [clamp(t - 1, 0, durationS), clamp(t + 1, 0, durationS)];
    }
    return null;
  };

  const setLoopRange = (start: number, end: number) => {
    const s = clamp(Number(start) || 0, 0, Math.max(0, durationS - TIMELINE_MIN_RANGE_S));
    const e = clamp(Number(end) || durationS, s + TIMELINE_MIN_RANGE_S, durationS);
    setLocatorInS(s);
    setLocatorOutS(e);
  };

  const useSelectionAsLoopRange = () => {
    const range = selectedTimeRange();
    if (!range) return;
    setLoopRange(range[0], range[1]);
    setLoopEnabled(true);
  };

  const timelineGridMarkers = (() => {
    const detectedGrid = _beatGrid();
    const detected = detectedGrid && detectedGrid.length >= 2 ? detectedGrid : null;
    if (detected) return detected.filter((t) => t >= 0 && t <= durationS);

    const step = _quantStepS();
    if (!step || step <= 0) return [];
    const count = Math.floor(durationS / step);
    const stride = Math.max(1, Math.ceil(count / 700));
    const markers: number[] = [];
    for (let i = 0; i <= count; i += stride) markers.push(Number((i * step).toFixed(4)));
    if (!markers.includes(0)) markers.unshift(0);
    if (durationS > 0 && markers[markers.length - 1] < durationS - TIMELINE_MIN_RANGE_S) {
      markers.push(durationS);
    }
    return markers;
  })();

  const jumpToPreviousGrid = () => {
    const before = [...timelineGridMarkers].reverse().find((t) => t < playheadS - 0.03);
    seekTo(before ?? 0);
  };

  const jumpToNextGrid = () => {
    const after = timelineGridMarkers.find((t) => t > playheadS + 0.03);
    seekTo(after ?? durationS);
  };

  const generateProxy = () => {
    if (!projectId) return;
    const s = clamp(Number(proxyStart), 0, durationS);
    const e = clamp(Number(proxyEnd), s + 0.05, durationS);
    setProxyBusy(true);
    setProxyUrl(
      `${backendUrl}/v1/projects/${projectId}/preview/segment?start_s=${encodeURIComponent(String(s))}&end_s=${encodeURIComponent(String(e))}&w=768&h=432&fps=${encodeURIComponent(String(proxyFps))}&force=1&v=${Date.now()}`,
    );
  };

  const playPause = () => {
    const a = audioRef.current;
    if (!a) return;
    if (a.paused) {
      if (a.currentTime >= durationS - TIMELINE_MIN_RANGE_S) {
        a.currentTime = loopEnabled ? locatorInS : 0;
        setPlayheadS(a.currentTime);
      }
      a.play().catch(() => {});
    } else {
      a.pause();
    }
  };

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (
      e.key === " " &&
      (e.target as any)?.tagName !== "TEXTAREA" &&
      (e.target as any)?.tagName !== "INPUT"
    ) {
      e.preventDefault();
      playPause();
    }
  };

  const bpm = _bpm();
  const beatGrid = _beatGrid();
  const timelineViewportWidth = timelineScrollRef.current?.clientWidth ?? 0;
  const timelineCanvasWidth = Math.max(
    720,
    timelineViewportWidth,
    Math.ceil(durationS * pxPerSecond) + 120,
  );
  const rulerStepS = pxPerSecond >= 180 ? 1 : pxPerSecond >= 120 ? 2 : pxPerSecond >= 72 ? 4 : 8;
  const rulerEnd = Math.ceil(durationS / Math.max(1, rulerStepS)) * rulerStepS;
  const rulerTicks = Array.from(
    { length: Math.floor(rulerEnd / Math.max(1, rulerStepS)) + 1 },
    (_, i) => Number((i * rulerStepS).toFixed(3)),
  );
  const quantizeStatus =
    beatGrid && beatGrid.length >= 2
      ? `${beatGrid.length} detected beat markers`
      : bpm
        ? `BPM fallback ${bpm.toFixed(1)}`
        : "Run Analyze or set BPM to enable quantize";
  const plannerLabMeta = project?.meta?.last_planner_lab || null;
  const reactiveLabMeta = project?.meta?.last_reactive_lab || null;
  const plannerImportedAt = Number(plannerLabMeta?.imported_at || 0);
  const reactiveAppliedAt = Number(reactiveLabMeta?.applied_at || 0);
  const handoffReadyCount = [plannerImportedAt > 0, reactiveAppliedAt > 0].filter(Boolean).length;
  const plannerVariantCount = Array.isArray(plan?.variants) ? plan.variants.length : 0;
  const plannerSceneCount = Array.isArray(plan?.variants?.[selectedVariant]?.scenes)
    ? plan.variants[selectedVariant].scenes.length
    : 0;
  const reactiveCueCount = Array.isArray(reactiveLabMeta?.cue_events) ? reactiveLabMeta.cue_events.length : 0;
  const reactiveSectionCount = Array.isArray(reactiveLabMeta?.sections) ? reactiveLabMeta.sections.length : 0;
  const densityConfig =
    timelineDensity === "compact"
      ? { rail: 196, lane: 54, wave: 92, clipTop: 9, clipHeight: 34, keyframeTop: 19 }
      : { rail: 220, lane: 64, wave: 106, clipTop: 12, clipHeight: 40, keyframeTop: 24 };
  const pickedSelection =
    selected?.kind === "track" ? selectedTrackClip(selected) : null;
  const selectionStatus =
    selected?.kind === "track" && pickedSelection
      ? `${pickedSelection.tr.name} clip`
      : selected?.kind === "overlay"
        ? `Overlay ${selected.layerIdx + 1}`
        : selected?.kind === "camera"
          ? `Camera keyframe ${selected.kfIdx + 1}`
          : "No selection";
  const timelineSurfaceStyle = {
    width: timelineCanvasWidth,
    ["--timeline-rail-width" as any]: `${densityConfig.rail}px`,
    ["--timeline-lane-height" as any]: `${densityConfig.lane}px`,
    ["--timeline-wave-height" as any]: `${densityConfig.wave}px`,
    ["--timeline-clip-top" as any]: `${densityConfig.clipTop}px`,
    ["--timeline-clip-height" as any]: `${densityConfig.clipHeight}px`,
    ["--timeline-keyframe-top" as any]: `${densityConfig.keyframeTop}px`,
    ["--timeline-major-grid" as any]: `${Math.max(pxPerSecond, 24)}px`,
    ["--timeline-minor-grid" as any]: `${Math.max(pxPerSecond / 4, 12)}px`,
  } as React.CSSProperties;

  const pageHeader = (
    <div className="timeline-pageHeader">
      <div>
        <div className="timeline-kicker">Arrangement View</div>
        <div className="timeline-titleRow">
          <h1>Timeline</h1>
          <span className="badge">{timelineDirty ? "Unsaved edits" : "Saved"}</span>
        </div>
        <div className="small timeline-headerCopy">
          Console-style top bar, shared session state, fit-all overview zoom, and a utility dock
          that keeps planning and reactive handoffs visible without flooding the screen.
        </div>
      </div>
      <div className="timeline-statusStrip">
        <div className="timeline-stat">
          <span className="small">Duration</span>
          <strong>{fmtTime(durationS)}</strong>
        </div>
        <div className="timeline-stat">
          <span className="small">Playhead</span>
          <strong>{fmtTime(playheadS)}</strong>
        </div>
        <div className="timeline-stat">
          <span className="small">Loop</span>
          <strong>{loopEnabled ? "On" : "Off"} {fmtTime(locatorInS)} - {fmtTime(locatorOutS)}</strong>
        </div>
        <div className="timeline-stat">
          <span className="small">Selection</span>
          <strong>{selectionStatus}</strong>
        </div>
        <div className="timeline-stat">
          <span className="small">Handoffs</span>
          <strong>{handoffReadyCount}/2 ready</strong>
        </div>
      </div>
    </div>
  );

  const toolbarCard = (
    <div className="card timeline-toolbarCard">
      <div className="timeline-toolbarGrid">
        <div className="timeline-toolbarGroup">
          <div className="timeline-toolbarLabel">Session</div>
          <div className="timeline-toolbarFields">
            <div className="timeline-miniField">
              <span className="timeline-miniLabel">Project</span>
              <select value={projectId} onChange={(e) => setProjectId(e.target.value)}>
                {projects.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name || p.id}
                  </option>
                ))}
              </select>
            </div>
            <div className="timeline-miniField">
              <span className="timeline-miniLabel">Variant</span>
              <select
                value={selectedVariant}
                onChange={(e) => setSelectedVariant(Number(e.target.value))}
              >
                {Array.from({ length: Math.max(1, plan?.variants?.length || 1) }).map((_, i) => (
                  <option key={i} value={i}>
                    {plan?.variants?.[i]?.name
                      ? `${i + 1}. ${plan.variants[i].name}`
                      : `Variant ${i + 1}`}
                  </option>
                ))}
              </select>
            </div>
          </div>
        </div>

        <div className="timeline-toolbarGroup">
          <div className="timeline-toolbarLabel">Transport</div>
          <div className="timeline-toolbarFields">
            <div className="timeline-miniField">
              <span className="timeline-miniLabel">Playhead</span>
              <input
                aria-label="Playhead time"
                type="number"
                step={0.1}
                value={playheadS}
                onChange={(e) => seekTo(Number(e.target.value))}
              />
            </div>
            <div className="timeline-miniField timeline-miniField--transport">
              <span className="timeline-miniLabel">Controls</span>
              <div className="timeline-transportControls">
                <button className="secondary timeline-iconButton" type="button" aria-label="Go to start" title="Go to start" onClick={() => seekTo(0)}>
                  <SkipBack size={16} aria-hidden="true" />
                </button>
                <button className="secondary timeline-iconButton" type="button" aria-label="Previous grid" title="Previous grid" onClick={jumpToPreviousGrid}>
                  <StepBack size={16} aria-hidden="true" />
                </button>
                <button className="primary timeline-iconButton" type="button" aria-label={isPlaying ? "Pause" : "Play"} title={isPlaying ? "Pause" : "Play"} onClick={playPause}>
                  {isPlaying ? <Pause size={17} aria-hidden="true" /> : <Play size={17} aria-hidden="true" />}
                </button>
                <button className="secondary timeline-iconButton" type="button" aria-label="Next grid" title="Next grid" onClick={jumpToNextGrid}>
                  <StepForward size={16} aria-hidden="true" />
                </button>
                <button className="secondary timeline-iconButton" type="button" aria-label="Go to end" title="Go to end" onClick={() => seekTo(durationS)}>
                  <SkipForward size={16} aria-hidden="true" />
                </button>
                <button
                  className={`${loopEnabled ? "primary" : "secondary"} timeline-loopButton`}
                  type="button"
                  aria-label={loopEnabled ? "Disable loop" : "Enable loop"}
                  title={loopEnabled ? "Disable loop" : "Enable loop"}
                  onClick={() => setLoopEnabled((value) => !value)}
                >
                  <Repeat size={15} aria-hidden="true" />
                  <span>Loop</span>
                </button>
              </div>
            </div>
            <div className="timeline-miniField">
              <span className="timeline-miniLabel">Zoom</span>
              <div className="timeline-zoomControls">
                <button className="secondary" type="button" onClick={() => setTimelineZoomWithFocus(pxPerSecond / 1.18)}>
                  -
                </button>
                <input
                  type="range"
                  min={TIMELINE_MIN_ZOOM}
                  max={TIMELINE_MAX_ZOOM}
                  value={pxPerSecond}
                  onChange={(e) => setTimelineZoomWithFocus(Number(e.target.value))}
                />
                <button className="secondary" type="button" onClick={() => setTimelineZoomWithFocus(pxPerSecond * 1.18)}>
                  +
                </button>
                <button className="secondary" type="button" onClick={fitTimelineZoom}>
                  Fit all
                </button>
              </div>
              <div className="timeline-zoomMeta">
                <input
                  type="number"
                  step={5}
                  value={pxPerSecond}
                  onChange={(e) => setTimelineZoomWithFocus(Number(e.target.value))}
                />
                <span className="small">Ctrl/Cmd + wheel zoom</span>
              </div>
            </div>
            <div className="timeline-toolbarActions">
              <button
                className="primary"
                onClick={() => void syncToRenderer()}
                disabled={!projectId}
                title="Save the timeline and open it in the internal renderer"
              >
                Sync to renderer
              </button>
              <button className="secondary" onClick={() => setSelected(null)}>
                Clear selection
              </button>
            </div>
          </div>
        </div>

        <div className="timeline-toolbarGroup">
          <div className="timeline-toolbarLabel">Grid</div>
          <div className="timeline-toolbarFields">
            <div className="timeline-miniField">
              <span className="timeline-miniLabel">BPM</span>
              <input
                type="number"
                step={0.1}
                placeholder="auto"
                value={bpmOverride ?? ""}
                onChange={(e) => setBpmOverride(e.target.value ? Number(e.target.value) : null)}
              />
            </div>
            <div className="timeline-miniField">
              <span className="timeline-miniLabel">Quantize</span>
              <select
                value={String(quantizeBeats)}
                onChange={(e) => setQuantizeBeats(Number(e.target.value))}
              >
                <option value="1">1 beat</option>
                <option value="0.5">1/2 beat</option>
                <option value="0.25">1/4 beat</option>
              </select>
            </div>
            <div className="timeline-miniField">
              <span className="timeline-miniLabel">Density</span>
              <select value={timelineDensity} onChange={(e) => setTimelineDensity(e.target.value as TimelineDensity)}>
                <option value="compact">Compact</option>
                <option value="comfortable">Comfortable</option>
              </select>
            </div>
            <div className="timeline-miniField timeline-miniField--locator">
              <span className="timeline-miniLabel">Loop range</span>
              <div className="timeline-locatorInputs">
                <label className="small">
                  In
                  <input
                    aria-label="Loop in"
                    type="number"
                    step={0.1}
                    value={locatorInS}
                    onChange={(e) => setLoopRange(Number(e.target.value), locatorOutS)}
                  />
                </label>
                <label className="small">
                  Out
                  <input
                    aria-label="Loop out"
                    type="number"
                    step={0.1}
                    value={locatorOutS}
                    onChange={(e) => setLoopRange(locatorInS, Number(e.target.value))}
                  />
                </label>
              </div>
              <div className="timeline-locatorActions">
                <button className="secondary" type="button" onClick={() => setLoopRange(playheadS, locatorOutS)}>
                  Set in
                </button>
                <button className="secondary" type="button" onClick={() => setLoopRange(locatorInS, playheadS)}>
                  Set out
                </button>
                <button className="secondary" type="button" disabled={!selected} onClick={useSelectionAsLoopRange}>
                  Use selection
                </button>
                <button className="secondary" type="button" onClick={() => setLoopRange(0, durationS)}>
                  Full
                </button>
              </div>
            </div>
            <div className="timeline-toolbarActions timeline-toolbarActions--wide">
              <button className="secondary" disabled={!selected} onClick={quantizeSelection}>
                Quantize
              </button>
              <button className="secondary" disabled={!selected} onClick={splitSelection}>
                Split
              </button>
              <button className="secondary" disabled={!selected} onClick={duplicateSelection}>
                Duplicate
              </button>
              <button className="secondary" disabled={!selected} onClick={nudgeSelectionToPlayhead}>
                Nudge to playhead
              </button>
              <button className="secondary" disabled={!selected} onClick={deleteSelection}>
                Delete
              </button>
              <button className={timelineDirty ? "primary" : "secondary"} onClick={saveTimeline}>
                {timelineDirty ? "Save timeline *" : "Save timeline"}
              </button>
            </div>
          </div>
        </div>
      </div>

      <div className="timeline-toolbarFooter">
        <div className="small">
          Keyboard: `Space` play/pause, `S` split, `D` duplicate, `Q` quantize, `Delete` remove selection.
        </div>
        <div className="small">Grid source: {quantizeStatus}</div>
      </div>

      {audioUrl ? (
        <audio
          ref={audioRef}
          src={audioUrl}
          controls
          className="timeline-audioControl"
        />
      ) : (
        <div className="small timeline-audioEmpty">No audio uploaded for this project.</div>
      )}
    </div>
  );

  const arrangementCard = (
    <div
      className="card timeline-arrangementCard"
      onPointerMove={onTimelinePointerMove}
      onPointerUp={onTimelinePointerUp}
      onPointerCancel={onTimelinePointerUp}
    >
      <div className="timeline-panelHeader">
        <div>
          <div className="timeline-panelTitle">Arrangement</div>
          <div className="small">
            Tracks stay full-height and scroll horizontally instead of collapsing when the window
            gets tighter.
          </div>
        </div>
        <div className="timeline-panelMeta">
          <span className="badge">{tracks.length} tracks</span>
          <span className="badge">{layers.length} overlays</span>
          <span className="badge">{camKeyframes.length} camera keyframes</span>
        </div>
      </div>

      <div className="timeline-board">
        <div className="timeline-boardRail">
          <div className="timeline-railCell timeline-railCell--header">
            <div className="timeline-railTitle">Timeline ruler</div>
            <div className="timeline-railMeta">Seconds and grid divisions</div>
          </div>

          <div className="timeline-railCell timeline-railCell--wave">
            <div className="timeline-railTitle">Waveform</div>
            <div className="timeline-railMeta">Click to park the playhead</div>
          </div>

          {tracks.map((tr, trackIdx) => (
            <div key={tr.id || trackIdx} className="timeline-railCell">
              <div className="timeline-railTitle">{tr.name}</div>
              <div className="timeline-railMeta">
                {String(tr.type).toUpperCase()} • {(tr.clips || []).length} clips
              </div>
              <div className="timeline-railActions">
                {String(tr.type).toLowerCase() === "prompt" ? (
                  <button className="secondary" onClick={() => addClip("prompt")}>
                    Add prompt
                  </button>
                ) : null}
                {String(tr.type).toLowerCase() === "motion" ? (
                  <button className="secondary" onClick={() => addClip("motion")}>
                    Add motion
                  </button>
                ) : null}
                <button
                  className="secondary"
                  disabled={!(selected?.kind === "track" && selected.trackIdx === trackIdx)}
                  onClick={duplicateSelection}
                >
                  Dup
                </button>
                <button
                  className="secondary"
                  disabled={!(selected?.kind === "track" && selected.trackIdx === trackIdx)}
                  onClick={splitSelection}
                >
                  Split
                </button>
                <button
                  className="secondary"
                  disabled={!(selected?.kind === "track" && selected.trackIdx === trackIdx)}
                  onClick={quantizeSelection}
                >
                  Quant
                </button>
                <button
                  className="secondary"
                  disabled={!(selected?.kind === "track" && selected.trackIdx === trackIdx)}
                  onClick={deleteSelection}
                >
                  Del
                </button>
              </div>
            </div>
          ))}

          <div className="timeline-railCell">
            <div className="timeline-railTitle">Overlays</div>
            <div className="timeline-railMeta">timeline.layers</div>
            <div className="timeline-railHint">Edit visual placement in Render.</div>
            <div className="timeline-railActions">
              <button
                className="secondary"
                disabled={selected?.kind !== "overlay"}
                onClick={duplicateSelection}
              >
                Dup
              </button>
              <button
                className="secondary"
                disabled={selected?.kind !== "overlay"}
                onClick={splitSelection}
              >
                Split
              </button>
              <button
                className="secondary"
                disabled={selected?.kind !== "overlay"}
                onClick={quantizeSelection}
              >
                Quant
              </button>
              <button
                className="secondary"
                disabled={selected?.kind !== "overlay"}
                onClick={deleteSelection}
              >
                Del
              </button>
            </div>
          </div>

          <div className="timeline-railCell">
            <div className="timeline-railTitle">Camera</div>
            <div className="timeline-railMeta">Automation keyframes</div>
            <div className="timeline-railActions">
              <button className="secondary" onClick={addCameraKeyframe}>
                Add keyframe
              </button>
              <button
                className="secondary"
                disabled={selected?.kind !== "camera"}
                onClick={duplicateSelection}
              >
                Dup
              </button>
              <button
                className="secondary"
                disabled={selected?.kind !== "camera"}
                onClick={quantizeSelection}
              >
                Quant
              </button>
              <button
                className="secondary"
                disabled={selected?.kind !== "camera"}
                onClick={deleteSelection}
              >
                Del
              </button>
            </div>
          </div>
        </div>

        <div
          className="timeline-boardScroll"
          ref={timelineScrollRef}
          onWheel={onTimelineWheel}
        >
          <div className="timeline-boardCanvas" style={timelineSurfaceStyle}>
            <div
              className="timeline-locatorRange"
              style={{
                left: clipPx(locatorInS),
                width: Math.max(2, clipPx(locatorOutS) - clipPx(locatorInS)),
              }}
              aria-hidden="true"
            />
            {timelineGridMarkers.map((marker) => (
              <div
                key={marker}
                className="timeline-gridMarker"
                style={{ left: clipPx(marker) }}
                aria-hidden="true"
              />
            ))}
            <div className="timeline-rulerRow">
              {rulerTicks.map((tick) => (
                <div key={tick} className="timeline-rulerTick" style={{ left: clipPx(tick) }}>
                  <div className="timeline-rulerTickLine" />
                  <div className="timeline-rulerTickLabel">{fmtTime(tick)}</div>
                </div>
              ))}
              <div className="timeline-playhead" style={{ left: clipPx(playheadS) }} />
            </div>

            <div className="timeline-waveformRow" onClick={onWaveformClick}>
              <canvas
                ref={canvasRef}
                width={timelineCanvasWidth}
                height={92}
                className="timeline-waveformCanvas"
              />
              <div className="timeline-playhead" style={{ left: clipPx(playheadS) }} />
            </div>

            {tracks.map((tr, trackIdx) => (
              <div key={tr.id || trackIdx} className="timeline-laneRow">
                {(tr.clips || []).map((cl, i) => {
                  const left = clipPx(cl.start_s);
                  const width = Math.max(16, clipPx(cl.end_s) - clipPx(cl.start_s));
                  const isSel =
                    selected?.kind === "track" &&
                    selected.trackIdx === trackIdx &&
                    selected.clipIdx === i;
                  return (
                    <div
                      key={cl.id || i}
                      className={`timeline-laneClip timeline-laneClip--${String(tr.type).toLowerCase()}${isSel ? " is-selected" : ""}`}
                      onPointerDown={onTrackClipPointerDown(trackIdx, i, "move")}
                      style={{ left, width }}
                      title={fmtLabel(tr.type, cl)}
                    >
                      <div className="timeline-laneClipLabel">{fmtLabel(tr.type, cl)}</div>
                      <div
                        className="timeline-laneClipHandle timeline-laneClipHandle--left"
                        onPointerDown={onTrackClipPointerDown(trackIdx, i, "left")}
                      />
                      <div
                        className="timeline-laneClipHandle timeline-laneClipHandle--right"
                        onPointerDown={onTrackClipPointerDown(trackIdx, i, "right")}
                      />
                    </div>
                  );
                })}
                <div className="timeline-playhead" style={{ left: clipPx(playheadS) }} />
              </div>
            ))}

            <div className="timeline-laneRow timeline-laneRow--overlay">
              {layers.map((l, i) => {
                const s = Number(l.start_s ?? 0);
                const e = Number(l.end_s ?? durationS);
                const left = clipPx(s);
                const width = Math.max(16, clipPx(e) - clipPx(s));
                const label =
                  l.type === "image"
                    ? String(l.asset || "image")
                    : l.type === "text"
                      ? String(l.text || "text").slice(0, 32)
                      : String(l.type || "layer");
                const isSel = selected?.kind === "overlay" && selected.layerIdx === i;

                return (
                  <div
                    key={i}
                    className={`timeline-laneClip timeline-laneClip--overlay${isSel ? " is-selected" : ""}`}
                    onPointerDown={onOverlayPointerDown(i, "move")}
                    style={{ left, width }}
                    title={label}
                  >
                    <div className="timeline-laneClipLabel">{label}</div>
                    <div
                      className="timeline-laneClipHandle timeline-laneClipHandle--left"
                      onPointerDown={onOverlayPointerDown(i, "left")}
                    />
                    <div
                      className="timeline-laneClipHandle timeline-laneClipHandle--right"
                      onPointerDown={onOverlayPointerDown(i, "right")}
                    />
                  </div>
                );
              })}
              <div className="timeline-playhead" style={{ left: clipPx(playheadS) }} />
            </div>

            <div className="timeline-laneRow timeline-laneRow--camera">
              {camKeyframes.map((k, i) => {
                const x = clipPx(Number(k.t || 0));
                const isSel = selected?.kind === "camera" && selected.kfIdx === i;
                return (
                  <div
                    key={i}
                    className={`timeline-keyframe${isSel ? " is-selected" : ""}`}
                    onPointerDown={onCameraKfPointerDown(i)}
                    title={`t=${fmtTime(Number(k.t || 0))} • zoom=${Number(k.zoom || 1).toFixed(2)}`}
                    style={{ left: x - 7 }}
                  />
                );
              })}
              <div className="timeline-playhead" style={{ left: clipPx(playheadS) }} />
            </div>
          </div>
        </div>
      </div>
    </div>
  );

  const inspectorPanel = (
    <div className="timeline-dockPanel">
      <div className="timeline-panelHeader">
        <div>
          <div className="timeline-panelTitle">Inspector</div>
          <div className="small">
            Selection-aware controls stay docked instead of hiding below the timeline.
          </div>
        </div>
        <span className="badge">{selected ? selected.kind : "none"}</span>
      </div>

      <div className="timeline-inlineActions">
        <button className="secondary" disabled={!selected} onClick={nudgeSelectionToPlayhead}>
          Nudge to playhead
        </button>
        <button className="secondary" disabled={!selected} onClick={deleteSelection}>
          Delete selection
        </button>
      </div>

      {selected?.kind === "track" ? (
        (() => {
          const picked = selectedTrackClip(selected);
          if (!picked) return <div className="small timeline-emptyState">No selection.</div>;
          const { tr, cl } = picked;
          const tt = String(tr.type).toLowerCase();
          return (
            <>
              <div className="small timeline-inspectorMeta">
                {tr.name}: {fmtTime(cl.start_s)} → {fmtTime(cl.end_s)}
              </div>
              {tt === "prompt" ? (
                <>
                  <textarea
                    className="timeline-inspectorTextarea"
                    value={String(cl.data?.prompt || "")}
                    onChange={(e) => updateSelectedClipData({ prompt: e.target.value })}
                  />
                  <div className="small timeline-inspectorHint">
                    Internal render uses this prompt track whenever a prompt lane is present.
                  </div>
                </>
              ) : tt === "motion" ? (
                <>
                  <div className="small timeline-inspectorHint">
                    Motion clips can drive camera movement and diffusion parameters when they are
                    active.
                  </div>
                  <div className="timeline-fieldGrid timeline-fieldGrid--compact">
                    <label className="small">zoom start</label>
                    <input
                      type="number"
                      step={0.01}
                      value={Number(cl.data?.zoom_start ?? 1)}
                      onChange={(e) =>
                        updateSelectedClipData({ zoom_start: Number(e.target.value) })
                      }
                    />
                    <label className="small">zoom end</label>
                    <input
                      type="number"
                      step={0.01}
                      value={Number(cl.data?.zoom_end ?? 1)}
                      onChange={(e) => updateSelectedClipData({ zoom_end: Number(e.target.value) })}
                    />
                    <label className="small">strength</label>
                    <input
                      type="number"
                      step={0.01}
                      value={Number(cl.data?.strength ?? 0.35)}
                      onChange={(e) => updateSelectedClipData({ strength: Number(e.target.value) })}
                    />
                    <label className="small">cfg</label>
                    <input
                      type="number"
                      step={0.1}
                      value={Number(cl.data?.cfg ?? 7)}
                      onChange={(e) => updateSelectedClipData({ cfg: Number(e.target.value) })}
                    />
                    <label className="small">steps</label>
                    <input
                      type="number"
                      step={1}
                      value={Number(cl.data?.steps ?? 12)}
                      onChange={(e) => updateSelectedClipData({ steps: Number(e.target.value) })}
                    />
                    <label className="small">rot end</label>
                    <input
                      type="number"
                      step={0.1}
                      value={Number(cl.data?.rotation_end ?? 0)}
                      onChange={(e) =>
                        updateSelectedClipData({ rotation_end: Number(e.target.value) })
                      }
                    />
                  </div>
                </>
              ) : (
                <div className="small timeline-emptyState">Unsupported track type.</div>
              )}
            </>
          );
        })()
      ) : selected?.kind === "overlay" ? (
        (() => {
          const l = layers[selected.layerIdx];
          if (!l) return <div className="small timeline-emptyState">No selection.</div>;
          const s0 = Number(l.start_s ?? 0);
          const e0 = Number(l.end_s ?? durationS);
          const label =
            l.type === "image"
              ? String(l.asset || "image")
              : l.type === "text"
                ? String(l.text || "text").slice(0, 40)
                : String(l.type || "layer");
          return (
            <>
              <div className="small timeline-inspectorMeta">Overlay: {label}</div>
              <div className="timeline-fieldGrid timeline-fieldGrid--compact">
                <label className="small">start</label>
                <input
                  type="number"
                  step={0.1}
                  value={s0}
                  onChange={(e) => updateSelectedOverlayTimes(Number(e.target.value), e0)}
                />
                <label className="small">end</label>
                <input
                  type="number"
                  step={0.1}
                  value={e0}
                  onChange={(e) => updateSelectedOverlayTimes(s0, Number(e.target.value))}
                />
              </div>
              <div className="small timeline-inspectorHint">
                Edit overlay content and screen placement in Render → Visual editor.
              </div>
            </>
          );
        })()
      ) : selected?.kind === "camera" ? (
        (() => {
          const k = camKeyframes[selected.kfIdx];
          if (!k) return <div className="small timeline-emptyState">No selection.</div>;
          return (
            <>
              <div className="small timeline-inspectorMeta">Camera keyframe</div>
              <div className="timeline-fieldGrid timeline-fieldGrid--compact">
                <label className="small">t</label>
                <input
                  type="number"
                  step={0.1}
                  value={Number(k.t || 0)}
                  onChange={(e) => updateSelectedCamera({ t: Number(e.target.value) })}
                />
                <label className="small">zoom</label>
                <input
                  type="number"
                  step={0.01}
                  value={Number(k.zoom || 1)}
                  onChange={(e) => updateSelectedCamera({ zoom: Number(e.target.value) })}
                />
                <label className="small">pan_x</label>
                <input
                  type="number"
                  step={0.1}
                  value={Number(k.pan_x || 0)}
                  onChange={(e) => updateSelectedCamera({ pan_x: Number(e.target.value) })}
                />
                <label className="small">pan_y</label>
                <input
                  type="number"
                  step={0.1}
                  value={Number(k.pan_y || 0)}
                  onChange={(e) => updateSelectedCamera({ pan_y: Number(e.target.value) })}
                />
                <label className="small">rot</label>
                <input
                  type="number"
                  step={0.1}
                  value={Number(k.rotation_deg || 0)}
                  onChange={(e) => updateSelectedCamera({ rotation_deg: Number(e.target.value) })}
                />
              </div>
            </>
          );
        })()
      ) : (
        <div className="small timeline-emptyState">
          Click a clip, overlay, or keyframe to edit it here.
        </div>
      )}
    </div>
  );

  const monitorCard = (
    <div className="card timeline-dockCard">
      <div className="timeline-panelHeader">
        <div>
          <div className="timeline-panelTitle">Program Monitor</div>
          <div className="small">Cached frame preview for scrubbing and timing checks.</div>
        </div>
        <span className="badge">Frame</span>
      </div>
      <div className="timeline-monitor">
        {previewUrl ? (
          <img src={previewUrl} className="timeline-monitorImage" />
        ) : (
          <div className="small">No preview.</div>
        )}
      </div>
    </div>
  );

  const handoffsPanel = (
    <div className="timeline-dockPanel">
      <div className="timeline-panelHeader">
        <div>
          <div className="timeline-panelTitle">Session Handoffs</div>
          <div className="small">
            Planner and Reactive Lab sync status stays visible here while you arrange the track.
          </div>
        </div>
        <span className="badge">{handoffReadyCount}/2 ready</span>
      </div>
      <div className="timeline-handoffGrid">
        <div className="timeline-handoffCard">
          <div className="timeline-handoffLabel">Planner</div>
          <strong>{plannerImportedAt ? `${plannerVariantCount} variants available` : "Awaiting planner sync"}</strong>
          <div className="small">
            {plannerImportedAt
              ? `${plannerSceneCount} scenes in the active variant.`
              : "Open Workspace or AI Planner Lab to import storyboard and prompt tracks."}
          </div>
          <ProgressBar value={plannerImportedAt ? 100 : plannerVariantCount ? 72 : 0} compact />
        </div>
        <div className="timeline-handoffCard">
          <div className="timeline-handoffLabel">Reactive</div>
          <strong>{reactiveAppliedAt ? `${reactiveCueCount} cues wired` : "Awaiting reactive sync"}</strong>
          <div className="small">
            {reactiveAppliedAt
              ? `${reactiveSectionCount} reactive sections are merged into motion/camera tracks.`
              : "Open Workspace or Reactive Lab to apply motion schedules and camera data."}
          </div>
          <ProgressBar value={reactiveAppliedAt ? 100 : 0} compact />
        </div>
      </div>
      <div className="timeline-inlineActions">
        <button className="primary" onClick={() => void syncToRenderer()} disabled={!projectId}>
          Sync to renderer
        </button>
        <button className="secondary" onClick={() => setDockSection("inspector")}>
          Open inspector
        </button>
        <button className="secondary" onClick={() => clearHandoff()} disabled={!lastHandoff}>
          Clear notice
        </button>
      </div>
    </div>
  );

  const proxyPanel = (
    <div className="timeline-dockPanel">
      <div className="timeline-panelHeader">
        <div>
          <div className="timeline-panelTitle">Proxy Preview</div>
          <div className="small">Low-resolution timing clip for the selected range.</div>
        </div>
        <span className="badge">Cached MP4</span>
      </div>
      <div className="timeline-fieldGrid timeline-fieldGrid--compact">
        <label className="small">start</label>
        <input
          type="number"
          step={0.1}
          value={proxyStart}
          onChange={(e) => setProxyStart(Number(e.target.value))}
        />
        <label className="small">end</label>
        <input
          type="number"
          step={0.1}
          value={proxyEnd}
          onChange={(e) => setProxyEnd(Number(e.target.value))}
        />
        <label className="small">fps</label>
        <input
          type="number"
          step={1}
          value={proxyFps}
          onChange={(e) => setProxyFps(Number(e.target.value))}
        />
      </div>
      <div className="timeline-inlineActions">
        <button className="primary" onClick={generateProxy}>
          Generate
        </button>
        <button className="secondary" onClick={() => { setProxyUrl(""); setProxyBusy(false); }}>
          Clear
        </button>
      </div>
      {proxyBusy ? (
        <ProgressBar
          value={68}
          label="Generating proxy"
          detail="Waiting for the preview clip to finish writing."
          compact
        />
      ) : null}
      <div className="timeline-monitor timeline-monitor--video">
        {proxyUrl ? (
          <video
            src={proxyUrl}
            controls
            className="timeline-monitorVideo"
            onLoadedData={() => setProxyBusy(false)}
            onError={() => setProxyBusy(false)}
          />
        ) : (
          <div className="small">No proxy clip generated.</div>
        )}
      </div>
    </div>
  );

  const diffusionPanel = (
    <div className="timeline-dockPanel">
      <div className="timeline-panelHeader">
        <div>
          <div className="timeline-panelTitle">Diffusion Preview</div>
          <div className="small">
            Look-dev segment using the internal SD path without leaving the timeline.
          </div>
        </div>
        <span className="badge">Look Dev</span>
      </div>
      <div className="timeline-inlineActions">
        <button className="secondary" disabled={!selected} onClick={setDiffRangeFromSelection}>
          Use selection
        </button>
      </div>
      <div className="timeline-fieldGrid timeline-fieldGrid--compact">
        <label className="small">start</label>
        <input
          type="number"
          step={0.1}
          value={diffStart}
          onChange={(e) => setDiffStart(Number(e.target.value))}
        />
        <label className="small">end</label>
        <input
          type="number"
          step={0.1}
          value={diffEnd}
          onChange={(e) => setDiffEnd(Number(e.target.value))}
        />
        <label className="small">fps</label>
        <input
          type="number"
          step={1}
          value={diffFps}
          onChange={(e) => setDiffFps(Number(e.target.value))}
        />
        <label className="small">steps</label>
        <input
          type="number"
          step={1}
          value={diffSteps}
          onChange={(e) => setDiffSteps(Number(e.target.value))}
        />
        <label className="small">cfg</label>
        <input
          type="number"
          step={0.1}
          value={diffCfg}
          onChange={(e) => setDiffCfg(Number(e.target.value))}
        />
        <label className="small">strength</label>
        <input
          type="number"
          step={0.01}
          value={diffStrength}
          onChange={(e) => setDiffStrength(Number(e.target.value))}
        />
        <label className="small">width</label>
        <input
          type="number"
          step={64}
          value={diffW}
          onChange={(e) => setDiffW(Number(e.target.value))}
        />
        <label className="small">height</label>
        <input
          type="number"
          step={64}
          value={diffH}
          onChange={(e) => setDiffH(Number(e.target.value))}
        />
        <label className="small">model</label>
        <select value={diffModel} onChange={(e) => setDiffModel(e.target.value)}>
          <option value="auto">auto</option>
          <option value="hf_sd15_internal">sd15</option>
          <option value="hf_sdxl_internal">sdxl</option>
        </select>
      </div>
      <div className="timeline-inlineActions">
        <button className="primary" onClick={generateDiffusionPreview}>
          Generate
        </button>
        <button className="secondary" onClick={() => { setDiffUrl(""); setDiffBusy(false); }}>
          Clear
        </button>
      </div>
      {diffBusy ? (
        <ProgressBar
          value={68}
          label="Generating diffusion preview"
          detail="Waiting for the look-dev clip to finish writing."
          compact
        />
      ) : null}
      <div className="timeline-monitor timeline-monitor--video">
        {diffUrl ? (
          <video
            src={diffUrl}
            controls
            className="timeline-monitorVideo"
            onLoadedData={() => setDiffBusy(false)}
            onError={() => setDiffBusy(false)}
          />
        ) : (
          <div className="small">No diffusion preview generated.</div>
        )}
      </div>
    </div>
  );

  const motionCurvesPanel = (() => {
    const tr = (tracks || []).find((t: any) => String(t?.type || "").toLowerCase() === "motion");
    const clip = (tr?.clips || [])[0];
    if (!clip || !timeline) return null;
    const data: AnyDict = clip?.data && typeof clip.data === "object" ? clip.data : {};
    const fps = 24;
    const duration = Number(durationS || 0) || 60;

    const strengthSched = String(data.denoise_schedule || data.strength_schedule || "");
    const cfgSched = String(data.cfg_scale_schedule || "");
    const stepsSched = String(data.steps_schedule || "");
    const strengthPairs = parseDeforumSchedule(strengthSched);
    const cfgPairs = parseDeforumSchedule(cfgSched);
    const stepsPairs = parseDeforumSchedule(stepsSched);
    const strengthCurve = sampleCurve(strengthPairs, {
      durationS: duration,
      fps,
      samples: 220,
      fallback: 0.35,
    });
    const cfgCurve = sampleCurve(cfgPairs, {
      durationS: duration,
      fps,
      samples: 220,
      fallback: 7.0,
    });
    const stepsCurve = sampleCurve(stepsPairs, {
      durationS: duration,
      fps,
      samples: 220,
      fallback: 15,
    });

    const W = 720;
    const H = 160;

    const strengthPath = svgPath(strengthCurve, duration, 0, 1, W, H);
    const cfgPath = svgPath(cfgCurve, duration, 1, 30, W, H);
    const stepsPath = svgPath(stepsCurve, duration, 4, 60, W, H);

    const updateMotionField = (field: string, val: string) => {
      const next = { ...(timeline as any) };
      next.tracks = Array.isArray(next.tracks)
        ? next.tracks.map((t: any) => {
            if (String(t?.type || "").toLowerCase() !== "motion") return t;
            const clips = Array.isArray(t.clips) ? t.clips : [];
            if (!clips.length) return t;
            const c0 = clips[0] || {};
            const d0 = c0.data && typeof c0.data === "object" ? { ...c0.data } : {};
            d0[field] = val;
            return { ...t, clips: [{ ...c0, data: d0 }, ...clips.slice(1)] };
          })
        : next.tracks;
      setTimeline(next);
      setTimelineDirty(true);
    };

    const insertPointAtPlayhead = (
      field: "strength_schedule" | "cfg_scale_schedule" | "steps_schedule" | "denoise_schedule",
      value: number,
    ) => {
      const f = Math.round(Number(playheadS || 0) * fps);
      const cur = String((data as any)[field] || "");
      const next = upsertPoint(cur, f, value);
      updateMotionField(field, next);
    };

    const curStrength = evalSchedule(strengthPairs, Number(playheadS || 0) * fps) ?? 0.35;
    const curCfg = evalSchedule(cfgPairs, Number(playheadS || 0) * fps) ?? 7.0;
    const curSteps = evalSchedule(stepsPairs, Number(playheadS || 0) * fps) ?? 15;

    return (
      <div className="timeline-dockPanel">
        <div className="timeline-panelHeader">
          <div>
            <div className="timeline-panelTitle">Motion Curves</div>
            <div className="small">Deforum schedules for cfg, strength, steps, and denoise.</div>
          </div>
          <span className="badge">24 fps</span>
        </div>

        <div className="timeline-curveStage">
          <svg width={W} height={H} style={{ width: "100%", height: H }}>
            {Array.from({ length: 9 }).map((_, i) => (
              <line
                key={i}
                x1={(i / 8) * W}
                y1={0}
                x2={(i / 8) * W}
                y2={H}
                stroke="rgba(255,255,255,0.06)"
                strokeWidth={1}
              />
            ))}
            {Array.from({ length: 5 }).map((_, i) => (
              <line
                key={i}
                x1={0}
                y1={(i / 4) * H}
                x2={W}
                y2={(i / 4) * H}
                stroke="rgba(255,255,255,0.06)"
                strokeWidth={1}
              />
            ))}
            <path d={strengthPath} fill="none" stroke="rgba(120,200,255,0.85)" strokeWidth={2} />
            <path d={cfgPath} fill="none" stroke="rgba(255,210,120,0.85)" strokeWidth={2} />
            <path d={stepsPath} fill="none" stroke="rgba(180,255,180,0.85)" strokeWidth={2} />
            <line
              x1={(clamp(Number(playheadS || 0), 0, duration) / Math.max(1e-6, duration)) * W}
              y1={0}
              x2={(clamp(Number(playheadS || 0), 0, duration) / Math.max(1e-6, duration)) * W}
              y2={H}
              stroke="rgba(255,120,120,0.9)"
              strokeWidth={2}
            />
          </svg>
        </div>

        <div className="timeline-inlineActions">
          <span className="small">strength {curStrength.toFixed(3)}</span>
          <button
            className="secondary"
            onClick={() => insertPointAtPlayhead("strength_schedule", curStrength)}
          >
            Insert strength
          </button>
          <span className="small">cfg {curCfg.toFixed(2)}</span>
          <button
            className="secondary"
            onClick={() => insertPointAtPlayhead("cfg_scale_schedule", curCfg)}
          >
            Insert cfg
          </button>
          <span className="small">steps {Math.round(curSteps)}</span>
          <button
            className="secondary"
            onClick={() => insertPointAtPlayhead("steps_schedule", curSteps)}
          >
            Insert steps
          </button>
        </div>

        <div className="timeline-textareaStack">
          <div>
            <div className="small timeline-stackLabel">strength_schedule</div>
            <textarea
              value={String(data.strength_schedule || "")}
              onChange={(e) => updateMotionField("strength_schedule", e.target.value)}
            />
          </div>
          <div>
            <div className="small timeline-stackLabel">cfg_scale_schedule</div>
            <textarea
              value={String(data.cfg_scale_schedule || "")}
              onChange={(e) => updateMotionField("cfg_scale_schedule", e.target.value)}
            />
          </div>
          <div>
            <div className="small timeline-stackLabel">steps_schedule</div>
            <textarea
              value={String(data.steps_schedule || "")}
              onChange={(e) => updateMotionField("steps_schedule", e.target.value)}
            />
          </div>
          <div>
            <div className="small timeline-stackLabel">denoise_schedule</div>
            <textarea
              value={String(data.denoise_schedule || "")}
              onChange={(e) => updateMotionField("denoise_schedule", e.target.value)}
            />
          </div>
        </div>
      </div>
    );
  })();

  const dockTabs: Array<{ id: DockSection; label: string; meta: string }> = [
    {
      id: "handoffs",
      label: "Handoffs",
      meta: `${handoffReadyCount}/2`,
    },
    {
      id: "inspector",
      label: "Inspector",
      meta: selected ? selectionStatus : "idle",
    },
    {
      id: "proxy",
      label: "Proxy",
      meta: proxyUrl ? "ready" : "draft",
    },
    {
      id: "diffusion",
      label: "Look Dev",
      meta: diffUrl ? "ready" : "draft",
    },
    ...(motionCurvesPanel
      ? [
          {
            id: "curves" as DockSection,
            label: "Curves",
            meta: "motion",
          },
        ]
      : []),
  ];

  const activeDockPanel =
    dockSection === "handoffs"
      ? handoffsPanel
      : dockSection === "proxy"
      ? proxyPanel
      : dockSection === "diffusion"
        ? diffusionPanel
        : dockSection === "curves" && motionCurvesPanel
          ? motionCurvesPanel
          : inspectorPanel;

  return (
    <div className="timeline-page" onKeyDown={onKeyDown} tabIndex={0} style={{ outline: "none" }}>
      {pageHeader}
      <div className="timeline-sessionStrip">
        <div className="timeline-sessionCard">
          <div className="timeline-sessionLabel">Shared session</div>
          <div className="timeline-sessionValue">
            {project?.name || "No active project"} • {plan?.variants?.[selectedVariant]?.name || `Variant ${selectedVariant + 1}`}
          </div>
          <div className="small">
            Workspace, Timeline, and the standalone labs now follow the same active project and variant.
          </div>
        </div>
        {lastHandoff ? (
          <div className="timeline-sessionCard timeline-sessionCard--accent">
            <div className="timeline-sessionLabel">Last handoff</div>
            <div className="timeline-sessionValue">
              {lastHandoff.type === "planner" ? "Planner sync" : "Reactive sync"}
            </div>
            <div className="small">{lastHandoff.summary}</div>
          </div>
        ) : null}
      </div>
      {progress.label ? (
        <div className="card timeline-progressCard">
          <ProgressBar
            value={progress.value}
            label={progress.label}
            detail={progress.detail}
            tone={progress.tone}
          />
        </div>
      ) : null}
      {toolbarCard}
      <details className="card timeline-guideCard">
        <summary className="timeline-guideSummary">Quick guide and capabilities</summary>
        <div className="timeline-guideBody">
          <div className="guide-grid">
            <section className="guide-block">
              <div className="guide-kicker">What this view does</div>
              <p>Timeline is the full arrangement editor for the saved Studio plan. It combines prompt clips, motion clips, overlays, camera moves, and look-development tools in one horizontal workspace.</p>
            </section>
            <section className="guide-block">
              <div className="guide-kicker">Capabilities</div>
              <ul className="guide-list">
                <li>Play audio, move the playhead, switch variants, and review timing against the active soundtrack.</li>
                <li>Zoom with buttons, slider, numeric entry, Fit all, or Ctrl/Cmd plus mouse wheel.</li>
                <li>Switch density between compact and comfortable depending on how many tracks or keyframes you need to see.</li>
                <li>Use the dock for handoffs, inspector, proxy renders, look-dev, and motion-curve editing without removing advanced controls.</li>
              </ul>
            </section>
            <section className="guide-block">
              <div className="guide-kicker">Recommended flow</div>
              <ul className="guide-list">
                <li>Start in Fit all mode to see the whole arrangement, then zoom into dense sections for clip or keyframe edits.</li>
                <li>Check the Handoffs tab before editing so planner and reactive sync state is visible without leaving Timeline.</li>
                <li>Keep the inspector open for clip-level adjustments, and switch to proxy or look-dev when you need validation renders.</li>
                <li>Use Timeline after Workspace or Storyboard when the plan is ready for precise arrangement and finishing decisions.</li>
              </ul>
            </section>
          </div>
        </div>
      </details>
      {err ? (
        <div className="card timeline-errorBanner">
          <div className="small">{err}</div>
        </div>
      ) : null}
      <div className="timeline-workspace">
        <div className="timeline-mainColumn">{arrangementCard}</div>
        <div className="timeline-dock">
          {monitorCard}
          <div className="card timeline-dockCard timeline-dockHub">
            <div className="timeline-dockTabs" role="tablist" aria-label="Timeline utilities">
              {dockTabs.map((tab) => (
                <button
                  key={tab.id}
                  type="button"
                  role="tab"
                  aria-selected={dockSection === tab.id}
                  className={`timeline-dockTab${dockSection === tab.id ? " is-active" : ""}`}
                  onClick={() => setDockSection(tab.id)}
                >
                  <span>{tab.label}</span>
                  <span className="timeline-dockTabMeta">{tab.meta}</span>
                </button>
              ))}
            </div>
            <div className="timeline-dockStatusBar">
              <div className="small">Selection: <b>{selectionStatus}</b></div>
              <div className="small">
                Playhead {fmtTime(playheadS)} • Grid {quantizeStatus}
              </div>
            </div>
            <div className="timeline-dockBody">{activeDockPanel}</div>
          </div>
        </div>
      </div>
    </div>
  );
}
