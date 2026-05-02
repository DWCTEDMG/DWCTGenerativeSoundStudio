export type PlanScene = {
  index: number;
  title: string;
  prompt: string;
  startS: number | null;
  endS: number | null;
  durationS: number | null;
  shotType: string | null;
  rationale: string | null;
  transitionCue: string | null;
  continuityNote: string | null;
};

export type PlanVariant = {
  index: number;
  label: string;
  summary: string | null;
  durationS: number | null;
  scenes: PlanScene[];
};

export type AnalysisSummary = {
  bpm: number | null;
  durationS: number | null;
  hookLine: string | null;
  narrative: string | null;
};

export type PlanPreviewOutput = {
  type: "plan-preview";
  projectId: string;
  projectName: string;
  mode: string;
  planSource: string | null;
  selectedVariantIndex: number;
  analysisSummary: AnalysisSummary | null;
  variants: PlanVariant[];
};

export const REACTIVE_SCHEDULE_FIELDS = [
  "zoom",
  "rotation_y",
  "rotation_z",
  "translation_x",
  "translation_y",
  "translation_z",
  "strength",
  "cfg_scale",
  "brightness",
] as const;

export type ScheduleField = (typeof REACTIVE_SCHEDULE_FIELDS)[number];

export type SchedulePoint = {
  frame: number;
  value: number;
};

type SceneTiming = {
  start: number;
  end: number;
  duration: number;
};

type ReactiveProfile = {
  cueType: "cut" | "push" | "orbit" | "hold";
  energy: number;
  bass: number;
  mid: number;
  treble: number;
  zoom: number;
  rotationY: number;
  rotationZ: number;
  translationX: number;
  translationY: number;
  translationZ: number;
  strength: number;
  cfgScale: number;
  brightness: number;
};

export type ReactiveDraft = {
  metadata: {
    projectId: string;
    projectName: string;
    variantIndex: number;
    variantLabel: string;
    generatedBy: string;
    generatedAt: string;
    bpm: number;
    scheduleStride: number;
  };
  keyframes: Array<Record<string, unknown>>;
  beatMarkers: Array<Record<string, unknown>>;
  cueEvents: Array<Record<string, unknown>>;
  sections: Array<Record<string, unknown>>;
  repairSuggestions: Array<Record<string, unknown>>;
  schedules: Record<ScheduleField, string>;
  handoffManifest: {
    approvedSectionIds: number[];
    renderMode: string;
    scheduleStride: number;
    cueEvents: Array<Record<string, unknown>>;
    repairSuggestions: Array<Record<string, unknown>>;
    schedules: Record<ScheduleField, string>;
    modelHints: {
      executionPriority: string;
      continuityPriority: string;
      fallbackAction: string;
    };
  };
};

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

function round(value: number, precision = 3): number {
  const factor = 10 ** precision;
  return Math.round(value * factor) / factor;
}

export function getActiveVariant(
  preview: PlanPreviewOutput | null,
  selectedVariantIndex: number,
): PlanVariant | null {
  if (!preview) {
    return null;
  }
  return (
    preview.variants.find((variant) => variant.index === selectedVariantIndex) ??
    preview.variants[0] ??
    null
  );
}

function inferCueType(transitionCue: string | null): "cut" | "push" | "orbit" | "hold" {
  const cue = String(transitionCue ?? "").toLowerCase();
  if (cue.includes("cut") || cue.includes("smash") || cue.includes("flash")) {
    return "cut";
  }
  if (cue.includes("push") || cue.includes("crash") || cue.includes("zoom")) {
    return "push";
  }
  if (cue.includes("orbit") || cue.includes("pivot") || cue.includes("rotate")) {
    return "orbit";
  }
  return "hold";
}

function inferRenderMode(scene: PlanScene): "smooth" | "cut-heavy" | "performance-led" | "ambient" {
  const text = `${scene.prompt} ${scene.transitionCue ?? ""} ${scene.shotType ?? ""}`.toLowerCase();
  if (text.includes("cut") || text.includes("flash")) {
    return "cut-heavy";
  }
  if (text.includes("perform") || text.includes("tracking") || text.includes("push")) {
    return "performance-led";
  }
  if (text.includes("ambient") || text.includes("drift") || text.includes("haze")) {
    return "ambient";
  }
  return "smooth";
}

function sceneTiming(
  scene: PlanScene,
  sceneIndex: number,
  scenes: PlanScene[],
  totalDurationHint: number | null | undefined,
): SceneTiming {
  const previous = scenes[sceneIndex - 1];
  const previousEnd =
    previous && typeof previous.endS === "number"
      ? previous.endS
      : previous && typeof previous.startS === "number" && typeof previous.durationS === "number"
        ? previous.startS + previous.durationS
        : sceneIndex > 0
          ? sceneIndex * 5
          : 0;
  const fallbackStart = sceneIndex === 0 ? 0 : previousEnd;
  const start = scene.startS ?? fallbackStart;

  const next = scenes[sceneIndex + 1];
  const fallbackEndFromNext =
    next && typeof next.startS === "number" && next.startS > start ? next.startS : null;
  const fallbackDuration = Math.max(scene.durationS ?? 5, 1);
  let end = scene.endS ?? fallbackEndFromNext ?? start + fallbackDuration;
  if (totalDurationHint && sceneIndex === scenes.length - 1) {
    end = Math.max(end, totalDurationHint);
  }

  if (end <= start) {
    end = start + fallbackDuration;
  }

  return {
    start,
    end,
    duration: Math.max(end - start, 1),
  };
}

function keywordBoost(text: string, positive: string[], negative: string[] = []): number {
  const source = text.toLowerCase();
  let score = 0;
  positive.forEach((keyword) => {
    if (source.includes(keyword)) {
      score += 1;
    }
  });
  negative.forEach((keyword) => {
    if (source.includes(keyword)) {
      score -= 0.6;
    }
  });
  return score;
}

function buildReactiveProfile(
  scene: PlanScene,
  sceneIndex: number,
  sceneCount: number,
): ReactiveProfile {
  const cueType = inferCueType(scene.transitionCue);
  const sourceText = `${scene.prompt} ${scene.transitionCue ?? ""} ${scene.shotType ?? ""} ${
    scene.rationale ?? ""
  } ${scene.continuityNote ?? ""}`.toLowerCase();
  const direction = sceneIndex % 2 === 0 ? 1 : -1;
  const cueEnergy =
    cueType === "cut" ? 0.2 : cueType === "push" ? 0.16 : cueType === "orbit" ? 0.12 : 0.06;
  const motionBoost = keywordBoost(sourceText, [
    "tracking",
    "kinetic",
    "performance",
    "rush",
    "surge",
    "wide",
    "hero",
  ]);
  const ambientBoost = keywordBoost(sourceText, ["ambient", "dream", "mist", "glow", "haze"]);
  const brightBoost = keywordBoost(sourceText, ["neon", "flare", "sun", "bright", "glitter"]);
  const darkPenalty = keywordBoost(sourceText, [], ["dark", "shadow", "still", "static"]);
  const progression = sceneCount > 1 ? sceneIndex / (sceneCount - 1) : 0.5;

  const energy = clamp(
    0.38 +
      cueEnergy +
      progression * 0.08 +
      motionBoost * 0.03 +
      ambientBoost * 0.02 +
      darkPenalty * 0.02,
    0.28,
    0.96,
  );
  const bass = clamp(
    0.34 + (cueType === "push" ? 0.22 : cueType === "cut" ? 0.18 : 0.1) + motionBoost * 0.025,
    0.2,
    1,
  );
  const treble = clamp(
    0.32 + (cueType === "cut" ? 0.24 : cueType === "orbit" ? 0.18 : 0.08) + brightBoost * 0.03,
    0.2,
    1,
  );
  const mid = clamp((energy + bass + treble) / 3 + ambientBoost * 0.015, 0.2, 1);

  const zoom = round(
    clamp(
      1 + energy * 0.06 + (cueType === "push" ? 0.05 : cueType === "hold" ? 0.015 : 0.03),
      1.01,
      1.16,
    ),
    4,
  );
  const rotationY = round(
    direction * (cueType === "orbit" ? 10 : cueType === "push" ? 6 : 3.5) * (0.55 + energy),
    4,
  );
  const rotationZ = round(
    direction * -1 * (cueType === "cut" ? 3.2 : cueType === "orbit" ? 6.4 : 1.4) * (0.48 + treble),
    4,
  );
  const translationX = round(
    direction * (cueType === "push" ? 11 : cueType === "orbit" ? 7 : 4.5) * (0.5 + bass),
    4,
  );
  const translationY = round(
    (ambientBoost > 0 ? 1 : -1) * (1.5 + energy * 2.8 + ambientBoost * 0.4),
    4,
  );
  const translationZ = round(
    -(6 + energy * 12 + (cueType === "push" ? 5 : cueType === "cut" ? 2 : 0)),
    4,
  );
  const strength = round(clamp(0.54 + energy * 0.2 + ambientBoost * 0.01, 0.48, 0.9), 4);
  const cfgScale = round(clamp(6.1 + energy * 1.8 + brightBoost * 0.12, 5.8, 8.4), 4);
  const brightness = round(
    clamp(
      0.46 + energy * 0.24 + brightBoost * 0.03 + ambientBoost * 0.02,
      0.35,
      1.15,
    ),
    4,
  );

  return {
    cueType,
    energy: round(energy, 4),
    bass: round(bass, 4),
    mid: round(mid, 4),
    treble: round(treble, 4),
    zoom,
    rotationY,
    rotationZ,
    translationX,
    translationY,
    translationZ,
    strength,
    cfgScale,
    brightness,
  };
}

function buildScheduleEntries(current: SchedulePoint[], frame: number, value: number): SchedulePoint[] {
  return [...current, { frame, value }];
}

function dedupeSchedulePoints(points: SchedulePoint[]): SchedulePoint[] {
  const sorted = [...points].sort((left, right) => left.frame - right.frame);
  const deduped = new Map<number, number>();
  sorted.forEach((point) => {
    deduped.set(point.frame, point.value);
  });
  return [...deduped.entries()].map(([frame, value]) => ({ frame, value }));
}

export function scheduleToString(points: SchedulePoint[]): string {
  return dedupeSchedulePoints(points)
    .map((point) => `${point.frame}:(${round(point.value, 4).toFixed(4)})`)
    .join(",");
}

export function parseScheduleString(input: unknown): SchedulePoint[] {
  if (typeof input !== "string" || input.trim().length === 0) {
    return [];
  }

  const points: SchedulePoint[] = [];
  input.split(",").forEach((entry) => {
    const match = entry.trim().match(/^(-?\d+):\((-?\d+(?:\.\d+)?)\)$/);
    if (!match) {
      return;
    }
    const frame = Number.parseInt(match[1], 10);
    const value = Number.parseFloat(match[2]);
    if (Number.isFinite(frame) && Number.isFinite(value)) {
      points.push({ frame, value });
    }
  });
  return dedupeSchedulePoints(points);
}

export function buildReactiveDraft(
  preview: PlanPreviewOutput,
  selectedVariantIndex: number,
): ReactiveDraft | {} {
  const variant = getActiveVariant(preview, selectedVariantIndex);
  if (!variant) {
    return {};
  }

  const bpm = preview.analysisSummary?.bpm ?? 96;
  const framesPerSecond = 24;
  const beatIntervalSeconds = 60 / bpm;
  const scenes = variant.scenes;
  const totalDurationHint = preview.analysisSummary?.durationS ?? variant.durationS ?? null;

  const schedulePoints = Object.fromEntries(
    REACTIVE_SCHEDULE_FIELDS.map((field) => [field, [] as SchedulePoint[]]),
  ) as Record<ScheduleField, SchedulePoint[]>;

  const keyframes: Array<Record<string, unknown>> = [];
  const cueEvents: Array<Record<string, unknown>> = [];
  const beatMarkers: Array<Record<string, unknown>> = [];
  const sections: Array<Record<string, unknown>> = [];
  const repairSuggestions: Array<Record<string, unknown>> = [];

  scenes.forEach((scene, sceneIndex) => {
    const timing = sceneTiming(scene, sceneIndex, scenes, totalDurationHint);
    const profile = buildReactiveProfile(scene, sceneIndex, scenes.length);
    const startFrame = Math.max(0, Math.round(timing.start * framesPerSecond));
    const midFrame = Math.max(
      startFrame + 1,
      Math.round((timing.start + timing.duration / 2) * framesPerSecond),
    );
    const endFrame = Math.max(midFrame + 1, Math.round(timing.end * framesPerSecond));
    const startZoom = round(profile.zoom - 0.012, 4);
    const midZoom = profile.zoom;
    const endZoom = round(profile.zoom - 0.008, 4);
    const startStrength = round(profile.strength - 0.03, 4);
    const endStrength = round(profile.strength - 0.015, 4);
    const startBrightness = round(profile.brightness - 0.03, 4);
    const endBrightness = round(profile.brightness - 0.015, 4);

    schedulePoints.zoom = buildScheduleEntries(schedulePoints.zoom, startFrame, startZoom);
    schedulePoints.zoom = buildScheduleEntries(schedulePoints.zoom, midFrame, midZoom);
    schedulePoints.zoom = buildScheduleEntries(schedulePoints.zoom, endFrame, endZoom);

    schedulePoints.rotation_y = buildScheduleEntries(
      schedulePoints.rotation_y,
      startFrame,
      round(profile.rotationY * 0.65, 4),
    );
    schedulePoints.rotation_y = buildScheduleEntries(schedulePoints.rotation_y, midFrame, profile.rotationY);
    schedulePoints.rotation_y = buildScheduleEntries(
      schedulePoints.rotation_y,
      endFrame,
      round(profile.rotationY * 0.45, 4),
    );

    schedulePoints.rotation_z = buildScheduleEntries(
      schedulePoints.rotation_z,
      startFrame,
      round(profile.rotationZ * 0.55, 4),
    );
    schedulePoints.rotation_z = buildScheduleEntries(schedulePoints.rotation_z, midFrame, profile.rotationZ);
    schedulePoints.rotation_z = buildScheduleEntries(
      schedulePoints.rotation_z,
      endFrame,
      round(profile.rotationZ * 0.35, 4),
    );

    schedulePoints.translation_x = buildScheduleEntries(
      schedulePoints.translation_x,
      startFrame,
      round(profile.translationX * 0.6, 4),
    );
    schedulePoints.translation_x = buildScheduleEntries(
      schedulePoints.translation_x,
      midFrame,
      profile.translationX,
    );
    schedulePoints.translation_x = buildScheduleEntries(
      schedulePoints.translation_x,
      endFrame,
      round(profile.translationX * 0.4, 4),
    );

    schedulePoints.translation_y = buildScheduleEntries(
      schedulePoints.translation_y,
      startFrame,
      round(profile.translationY * 0.5, 4),
    );
    schedulePoints.translation_y = buildScheduleEntries(
      schedulePoints.translation_y,
      midFrame,
      profile.translationY,
    );
    schedulePoints.translation_y = buildScheduleEntries(
      schedulePoints.translation_y,
      endFrame,
      round(profile.translationY * 0.3, 4),
    );

    schedulePoints.translation_z = buildScheduleEntries(
      schedulePoints.translation_z,
      startFrame,
      round(profile.translationZ * 0.7, 4),
    );
    schedulePoints.translation_z = buildScheduleEntries(
      schedulePoints.translation_z,
      midFrame,
      profile.translationZ,
    );
    schedulePoints.translation_z = buildScheduleEntries(
      schedulePoints.translation_z,
      endFrame,
      round(profile.translationZ * 0.52, 4),
    );

    schedulePoints.strength = buildScheduleEntries(schedulePoints.strength, startFrame, startStrength);
    schedulePoints.strength = buildScheduleEntries(schedulePoints.strength, midFrame, profile.strength);
    schedulePoints.strength = buildScheduleEntries(schedulePoints.strength, endFrame, endStrength);

    schedulePoints.cfg_scale = buildScheduleEntries(
      schedulePoints.cfg_scale,
      startFrame,
      round(profile.cfgScale - 0.18, 4),
    );
    schedulePoints.cfg_scale = buildScheduleEntries(schedulePoints.cfg_scale, midFrame, profile.cfgScale);
    schedulePoints.cfg_scale = buildScheduleEntries(
      schedulePoints.cfg_scale,
      endFrame,
      round(profile.cfgScale - 0.1, 4),
    );

    schedulePoints.brightness = buildScheduleEntries(
      schedulePoints.brightness,
      startFrame,
      startBrightness,
    );
    schedulePoints.brightness = buildScheduleEntries(
      schedulePoints.brightness,
      midFrame,
      profile.brightness,
    );
    schedulePoints.brightness = buildScheduleEntries(schedulePoints.brightness, endFrame, endBrightness);

    keyframes.push(
      {
        frame: startFrame,
        time: round(timing.start, 4),
        metrics: {
          energy: round(profile.energy * 0.88, 4),
          bass: round(profile.bass * 0.9, 4),
          mid: round(profile.mid * 0.9, 4),
          treble: round(profile.treble * 0.86, 4),
        },
        params: {
          zoom: startZoom,
          rotation_y: round(profile.rotationY * 0.65, 4),
          rotation_z: round(profile.rotationZ * 0.55, 4),
          translation_x: round(profile.translationX * 0.6, 4),
          translation_y: round(profile.translationY * 0.5, 4),
          translation_z: round(profile.translationZ * 0.7, 4),
          strength: startStrength,
          cfg_scale: round(profile.cfgScale - 0.18, 4),
          brightness: startBrightness,
          shot_type: scene.shotType ?? undefined,
          continuity_hint: scene.continuityNote ?? undefined,
        },
        note: `${scene.title} entry`,
      },
      {
        frame: midFrame,
        time: round(timing.start + timing.duration / 2, 4),
        metrics: {
          energy: profile.energy,
          bass: profile.bass,
          mid: profile.mid,
          treble: profile.treble,
        },
        params: {
          zoom: profile.zoom,
          rotation_y: profile.rotationY,
          rotation_z: profile.rotationZ,
          translation_x: profile.translationX,
          translation_y: profile.translationY,
          translation_z: profile.translationZ,
          strength: profile.strength,
          cfg_scale: profile.cfgScale,
          brightness: profile.brightness,
          shot_type: scene.shotType ?? undefined,
          continuity_hint: scene.continuityNote ?? undefined,
        },
        note: `${scene.title} peak`,
      },
      {
        frame: endFrame,
        time: round(timing.end, 4),
        metrics: {
          energy: round(profile.energy * 0.84, 4),
          bass: round(profile.bass * 0.82, 4),
          mid: round(profile.mid * 0.84, 4),
          treble: round(profile.treble * 0.8, 4),
        },
        params: {
          zoom: endZoom,
          rotation_y: round(profile.rotationY * 0.45, 4),
          rotation_z: round(profile.rotationZ * 0.35, 4),
          translation_x: round(profile.translationX * 0.4, 4),
          translation_y: round(profile.translationY * 0.3, 4),
          translation_z: round(profile.translationZ * 0.52, 4),
          strength: endStrength,
          cfg_scale: round(profile.cfgScale - 0.1, 4),
          brightness: endBrightness,
          shot_type: scene.shotType ?? undefined,
          continuity_hint: scene.continuityNote ?? undefined,
        },
        note: `${scene.title} exit`,
      },
    );

    cueEvents.push({
      id: sceneIndex + 1,
      frame: startFrame,
      time: round(timing.start, 4),
      cueType: profile.cueType,
      instruction:
        scene.transitionCue ||
        `Enter ${scene.title.toLowerCase()} with a ${scene.shotType ?? "steady"} move and preserve ${
          scene.continuityNote ?? "shot continuity"
        }.`,
    });

    let beatTime = timing.start + beatIntervalSeconds;
    let beatMarkerId = 0;
    while (beatTime < timing.end) {
      beatMarkers.push({
        frame: Math.max(0, Math.round(beatTime * framesPerSecond)),
        time: round(beatTime, 4),
        intensity: round(clamp(profile.energy + beatMarkerId * 0.02, 0.45, 0.98), 4),
      });
      beatTime += beatIntervalSeconds * (profile.cueType === "cut" ? 1.5 : 2);
      beatMarkerId += 1;
      if (beatMarkerId > 6) {
        break;
      }
    }

    sections.push({
      id: sceneIndex + 1,
      startTime: round(timing.start, 4),
      endTime: round(timing.end, 4),
      label: scene.title,
      avgEnergy: profile.energy,
      approved: true,
      renderMode: inferRenderMode(scene),
    });

    if (scene.continuityNote) {
      repairSuggestions.push({
        id: repairSuggestions.length + 1,
        sectionId: sceneIndex + 1,
        issue: scene.continuityNote,
        action:
          `Preserve ${String(scene.continuityNote).toLowerCase()} while keeping camera direction stable across adjacent scenes.`,
      });
    } else if (profile.cueType === "cut" && timing.duration < 3.5) {
      repairSuggestions.push({
        id: repairSuggestions.length + 1,
        sectionId: sceneIndex + 1,
        issue: "Fast cut section may become visually abrupt.",
        action:
          "Reduce rotation and translation spikes at the section boundary, then keep the next scene on the same lateral travel direction.",
      });
    }
  });

  const schedules = Object.fromEntries(
    REACTIVE_SCHEDULE_FIELDS.map((field) => [field, scheduleToString(schedulePoints[field])]),
  ) as Record<ScheduleField, string>;

  const scheduleStride = keyframes.length > 24 ? 2 : 1;

  return {
    metadata: {
      projectId: preview.projectId,
      projectName: preview.projectName,
      variantIndex: variant.index,
      variantLabel: variant.label,
      generatedBy: "edmg-director-widget",
      generatedAt: new Date().toISOString(),
      bpm,
      scheduleStride,
    },
    keyframes,
    beatMarkers,
    cueEvents,
    sections,
    repairSuggestions,
    schedules,
    handoffManifest: {
      approvedSectionIds: sections.map((section) => Number(section.id)),
      renderMode: "smooth",
      scheduleStride,
      cueEvents,
      repairSuggestions,
      schedules,
      modelHints: {
        executionPriority:
          "Preview scene boundaries first, then commit the sections with the strongest continuity anchors.",
        continuityPriority:
          "Carry shot language, subject framing, and camera direction through adjacent scenes before increasing motion strength.",
        fallbackAction:
          "If a section breaks continuity, rerender only that section with lower rotation and keep neighboring cue timings unchanged.",
      },
    },
  };
}
