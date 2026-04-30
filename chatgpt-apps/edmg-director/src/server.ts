import {
  registerAppResource,
  registerAppTool,
  RESOURCE_MIME_TYPE,
} from "@modelcontextprotocol/ext-apps/server";
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StreamableHTTPServerTransport } from "@modelcontextprotocol/sdk/server/streamableHttp.js";
import cors from "cors";
import express from "express";
import { z } from "zod";

const SERVER_VERSION = "0.1.0";
const DEFAULT_BACKEND_URL = "http://127.0.0.1:7863";
const REVIEW_WIDGET_URI = "ui://edmg-director/review-board-v1.html";
const PORT = Number.parseInt(process.env.PORT ?? "8788", 10);

function backendBaseUrl(): string {
  return (process.env.EDMG_BACKEND_URL ?? DEFAULT_BACKEND_URL).replace(/\/+$/, "");
}

function trimText(value: unknown, max = 220): string {
  const text = String(value ?? "").trim();
  if (!text) return "";
  return text.length > max ? `${text.slice(0, max - 1)}…` : text;
}

function asArray(value: unknown): any[] {
  return Array.isArray(value) ? value : [];
}

function asObject(value: unknown): Record<string, any> {
  return value && typeof value === "object" ? (value as Record<string, any>) : {};
}

function toNumber(value: unknown, fallback = 0): number {
  const number = Number(value);
  return Number.isFinite(number) ? number : fallback;
}

function analysisSummary(analysis: unknown): {
  summary: string;
  durationS: number;
  bpm: number;
  sectionCount: number;
  transcriptReady: boolean;
  tags: string[];
} {
  const source = asObject(analysis);
  const features = asObject(source.features);
  const transcript = source.transcript;
  const transcriptText =
    typeof transcript === "string"
      ? transcript.trim()
      : trimText(asObject(transcript).text, 400);
  const summary =
    trimText(source.summary, 260) ||
    trimText(transcriptText, 260) ||
    "No EDMG analysis summary available yet.";
  return {
    summary,
    durationS: Math.max(0, toNumber(features.duration_s ?? features.duration, 0)),
    bpm: Math.max(0, toNumber(features.bpm ?? features.tempo_bpm ?? features.tempo, 0)),
    sectionCount: asArray(source.sections).length,
    transcriptReady: Boolean(transcriptText),
    tags: asArray(source.tags)
      .map((tag) => String(tag ?? "").trim())
      .filter(Boolean)
      .slice(0, 10),
  };
}

function summarizeProjectRecord(project: unknown) {
  const source = asObject(project);
  const meta = asObject(source.meta);
  return {
    id: String(source.id ?? ""),
    name: trimText(source.name, 120) || "Untitled project",
    hasAudio: Boolean(meta.audio),
    hasAnalysis: Boolean(meta.analysis),
    variantCount: asArray(asObject(meta.last_plan).variants).length,
  };
}

function summarizeProjectSnapshot(project: unknown) {
  const source = asObject(project);
  const meta = asObject(source.meta);
  const audio = asObject(meta.audio);
  const plan = asObject(meta.last_plan);
  const timeline = asObject(meta.timeline);
  const render = asObject(timeline.render);
  const tracks = asArray(timeline.tracks);
  const plannerLab = asObject(meta.last_planner_lab);
  const reactiveLab = asObject(meta.last_reactive_lab);
  const analysis = analysisSummary(meta.analysis);

  return {
    kind: "projectSnapshot",
    project: {
      id: String(source.id ?? ""),
      name: trimText(source.name, 120) || "Untitled project",
      audio: audio.filename
        ? {
            filename: String(audio.filename),
            sizeBytes: toNumber(audio.size_bytes, 0),
          }
        : null,
      analysis,
      plan: {
        variantCount: asArray(plan.variants).length,
        title: trimText(plan.title, 160),
        durationS: Math.max(0, toNumber(plan.duration_s, 0)),
      },
      timeline: {
        trackCount: tracks.length,
        fpsOutput: toNumber(render.fps_output ?? timeline.fps_output, 0),
      },
      handoff: {
        plannerImportedAt: toNumber(plannerLab.imported_at, 0) || null,
        reactiveAppliedAt: toNumber(reactiveLab.applied_at, 0) || null,
      },
    },
  };
}

function summarizePlanVariants(plan: unknown) {
  const source = asObject(plan);
  const variants = asArray(source.variants);
  return variants.map((variant, index) => {
    const current = asObject(variant);
    const scenes = asArray(current.scenes).map((scene, sceneIndex) => {
      const item = asObject(scene);
      return {
        index: sceneIndex,
        id: item.id ?? sceneIndex + 1,
        name: trimText(item.name ?? item.title, 120) || `Scene ${sceneIndex + 1}`,
        startS: Math.max(0, toNumber(item.start_s, sceneIndex * 5)),
        endS: Math.max(0, toNumber(item.end_s, sceneIndex * 5 + 5)),
        promptSnippet: trimText(item.prompt ?? item.text, 240),
        transition: trimText(item.transition_cue ?? item.transition, 140),
      };
    });

    return {
      index,
      name: trimText(current.name, 120) || `Variant ${index + 1}`,
      sceneCount: scenes.length,
      durationS: Math.max(
        0,
        toNumber(
          current.duration_s,
          scenes.length ? scenes[scenes.length - 1].endS : toNumber(source.duration_s, 0)
        )
      ),
      scenes,
    };
  });
}

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);
  if (!headers.has("accept")) headers.set("accept", "application/json");
  const response = await fetch(`${backendBaseUrl()}${path}`, {
    ...init,
    headers,
  });

  const text = await response.text();
  const payload = text ? JSON.parse(text) : null;
  if (!response.ok) {
    const detail =
      trimText(asObject(payload).detail, 240) ||
      trimText(asObject(payload).error?.message, 240) ||
      trimText(text, 240) ||
      `${response.status} ${response.statusText}`;
    throw new Error(detail);
  }
  return payload as T;
}

async function postJson<T>(path: string, body: unknown): Promise<T> {
  return requestJson<T>(path, {
    method: "POST",
    headers: {
      "content-type": "application/json",
    },
    body: JSON.stringify(body),
  });
}

async function fetchProjects(query: string | undefined, limit: number): Promise<any[]> {
  const data = await requestJson<{ projects?: any[] }>("/v1/projects");
  const all = asArray(data.projects);
  const lowered = String(query ?? "").trim().toLowerCase();
  const filtered = lowered
    ? all.filter((project) => {
        const item = asObject(project);
        return String(item.name ?? "").toLowerCase().includes(lowered);
      })
    : all;
  return filtered.slice(0, limit);
}

async function fetchProject(projectId: string): Promise<any> {
  const data = await requestJson<{ project?: any }>(`/v1/projects/${encodeURIComponent(projectId)}`);
  if (!data.project) {
    throw new Error(`Project ${projectId} was not found by the EDMG backend.`);
  }
  return data.project;
}

function extractTextContent(content: unknown): string {
  return asArray(content)
    .map((item) => trimText(asObject(item).text, 260))
    .filter(Boolean)
    .join(" ");
}

const REVIEW_WIDGET_HTML = `<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>EDMG Director</title>
    <style>
      :root {
        color-scheme: light dark;
        --bg: #f6f0e7;
        --panel: rgba(255, 255, 255, 0.88);
        --panel-strong: rgba(255, 255, 255, 0.96);
        --text: #1e1b18;
        --muted: #645b54;
        --line: rgba(40, 31, 22, 0.12);
        --accent: #bf5a2a;
        --accent-soft: rgba(191, 90, 42, 0.14);
        --accent-strong: #8f3d16;
        --good: #1f7a4f;
        --warn: #9a4b1f;
        --shadow: 0 18px 44px rgba(50, 29, 14, 0.12);
        font-family: Georgia, "Iowan Old Style", "Palatino Linotype", serif;
      }

      :root[data-theme="dark"] {
        --bg: #16110d;
        --panel: rgba(33, 24, 18, 0.92);
        --panel-strong: rgba(28, 20, 15, 0.98);
        --text: #f7efe5;
        --muted: #c8b8a9;
        --line: rgba(255, 244, 232, 0.12);
        --accent: #ff8f57;
        --accent-soft: rgba(255, 143, 87, 0.12);
        --accent-strong: #ffb086;
        --good: #74d39c;
        --warn: #ffb278;
        --shadow: 0 20px 52px rgba(0, 0, 0, 0.32);
      }

      * { box-sizing: border-box; }
      html, body { margin: 0; padding: 0; min-height: 100%; background: radial-gradient(circle at top left, rgba(255,255,255,0.35), transparent 34%), var(--bg); color: var(--text); }
      body { padding: 18px; }
      button { font: inherit; }
      a { color: inherit; }
      .shell { display: grid; gap: 14px; }
      .hero {
        background: linear-gradient(145deg, var(--panel-strong), var(--panel));
        border: 1px solid var(--line);
        border-radius: 20px;
        padding: 18px 18px 16px;
        box-shadow: var(--shadow);
      }
      .eyebrow {
        font-size: 11px;
        letter-spacing: 0.18em;
        text-transform: uppercase;
        color: var(--muted);
        margin-bottom: 8px;
      }
      .title { font-size: 28px; line-height: 1; margin: 0 0 8px; }
      .summary { margin: 0; color: var(--muted); line-height: 1.45; }
      .metaRow, .buttonRow, .variantActions {
        display: flex;
        flex-wrap: wrap;
        gap: 10px;
        align-items: center;
      }
      .metaRow { margin-top: 14px; }
      .buttonRow { margin-top: 16px; }
      .badge {
        display: inline-flex;
        align-items: center;
        gap: 6px;
        border-radius: 999px;
        border: 1px solid var(--line);
        padding: 6px 10px;
        font-size: 12px;
        background: rgba(255,255,255,0.4);
      }
      .badgeAccent { background: var(--accent-soft); border-color: rgba(191, 90, 42, 0.2); color: var(--accent-strong); }
      .badgeGood { background: rgba(31,122,79,0.12); border-color: rgba(31,122,79,0.2); color: var(--good); }
      .button {
        appearance: none;
        border: 1px solid var(--line);
        background: var(--panel);
        color: var(--text);
        border-radius: 999px;
        padding: 10px 14px;
        cursor: pointer;
      }
      .button:hover { border-color: rgba(0,0,0,0.24); }
      .buttonPrimary {
        background: var(--accent);
        border-color: transparent;
        color: #fff6ef;
      }
      .buttonGhost { background: transparent; }
      .grid { display: grid; gap: 14px; }
      .variant {
        background: linear-gradient(165deg, var(--panel-strong), var(--panel));
        border: 1px solid var(--line);
        border-radius: 18px;
        padding: 16px;
        box-shadow: var(--shadow);
      }
      .variantHead {
        display: flex;
        justify-content: space-between;
        align-items: start;
        gap: 12px;
        margin-bottom: 12px;
      }
      .variantTitle {
        margin: 0;
        font-size: 21px;
        line-height: 1.15;
      }
      .variantSub { font-size: 13px; color: var(--muted); margin-top: 4px; }
      .sceneList { display: grid; gap: 10px; margin-top: 14px; }
      .scene {
        border: 1px solid var(--line);
        border-radius: 14px;
        padding: 12px;
        background: rgba(255,255,255,0.3);
      }
      .sceneHead {
        display: flex;
        justify-content: space-between;
        gap: 10px;
        align-items: center;
        margin-bottom: 8px;
      }
      .sceneName { font-size: 15px; margin: 0; }
      .sceneMeta { color: var(--muted); font-size: 12px; }
      .scenePrompt { margin: 0; font-size: 13px; line-height: 1.45; color: var(--text); }
      .sceneTransition { margin-top: 8px; color: var(--muted); font-size: 12px; }
      .status {
        border-radius: 16px;
        border: 1px dashed var(--line);
        padding: 12px 14px;
        background: rgba(255,255,255,0.24);
        color: var(--muted);
      }
      .error {
        color: #7b1f1f;
        border-color: rgba(123,31,31,0.2);
        background: rgba(123,31,31,0.08);
      }
      .finePrint { font-size: 12px; color: var(--muted); }
      @media (max-width: 720px) {
        body { padding: 12px; }
        .title { font-size: 24px; }
        .variantTitle { font-size: 19px; }
        .variantHead, .sceneHead { flex-direction: column; align-items: start; }
      }
    </style>
  </head>
  <body>
    <div id="app" class="shell"></div>
    <script>
      const root = document.getElementById("app");
      let lastOutput = null;
      let busyMessage = "";
      let errorMessage = "";

      function api() {
        return window.openai || {};
      }

      function setTheme() {
        document.documentElement.dataset.theme = api().theme || "light";
      }

      function escapeHtml(value) {
        const node = document.createElement("div");
        node.textContent = String(value ?? "");
        return node.innerHTML;
      }

      function fmtSeconds(value) {
        const total = Number(value || 0);
        if (!Number.isFinite(total) || total <= 0) return "0:00";
        const mins = Math.floor(total / 60);
        const secs = Math.round(total % 60).toString().padStart(2, "0");
        return mins + ":" + secs;
      }

      function extractText(content) {
        return Array.isArray(content)
          ? content.map(function (item) { return item && item.text ? String(item.text) : ""; }).filter(Boolean).join(" ")
          : "";
      }

      function renderScene(scene) {
        const transition = scene.transition
          ? '<div class="sceneTransition"><strong>Transition:</strong> ' + escapeHtml(scene.transition) + '</div>'
          : "";
        return [
          '<article class="scene">',
          '  <div class="sceneHead">',
          '    <div>',
          '      <h4 class="sceneName">' + escapeHtml(scene.name) + '</h4>',
          '      <div class="sceneMeta">Scene ' + escapeHtml(scene.index + 1) + ' · ' + escapeHtml(fmtSeconds(scene.startS)) + ' → ' + escapeHtml(fmtSeconds(scene.endS)) + '</div>',
          '    </div>',
          '  </div>',
          '  <p class="scenePrompt">' + escapeHtml(scene.promptSnippet || 'No prompt snippet available.') + '</p>',
          transition,
          '</article>'
        ].join("\n");
      }

      function renderVariant(projectId, variant) {
        const scenes = Array.isArray(variant.scenes) ? variant.scenes.map(renderScene).join("\n") : "";
        return [
          '<section class="variant">',
          '  <div class="variantHead">',
          '    <div>',
          '      <h3 class="variantTitle">' + escapeHtml(variant.name) + '</h3>',
          '      <div class="variantSub">' + escapeHtml(String(variant.sceneCount || 0)) + ' scenes · approx ' + escapeHtml(fmtSeconds(variant.durationS)) + '</div>',
          '    </div>',
          '    <div class="variantActions">',
          '      <button class="button buttonPrimary" data-action="apply" data-project-id="' + escapeHtml(projectId) + '" data-variant-index="' + escapeHtml(variant.index) + '" data-overwrite="false">Apply to timeline</button>',
          '      <button class="button" data-action="apply" data-project-id="' + escapeHtml(projectId) + '" data-variant-index="' + escapeHtml(variant.index) + '" data-overwrite="true">Apply with overwrite</button>',
          '      <button class="button buttonGhost" data-action="ask" data-project-id="' + escapeHtml(projectId) + '" data-variant-index="' + escapeHtml(variant.index) + '">Ask ChatGPT for notes</button>',
          '    </div>',
          '  </div>',
          '  <div class="sceneList">' + scenes + '</div>',
          '</section>'
        ].join("\n");
      }

      function renderPlanPreview(output) {
        const variants = Array.isArray(output.variants) ? output.variants : [];
        const body = variants.length
          ? variants.map(function (variant) { return renderVariant(output.projectId, variant); }).join("\n")
          : '<div class="status">No variants were returned by the EDMG backend.</div>';
        return [
          '<section class="hero">',
          '  <div class="eyebrow">EDMG Director</div>',
          '  <h1 class="title">' + escapeHtml(output.projectName || output.projectId || 'Project review') + '</h1>',
          '  <p class="summary">Review the generated EDMG storyboard variants below, then apply the best one to the timeline.</p>',
          '  <div class="metaRow">',
          '    <span class="badge badgeAccent">Plan mode: ' + escapeHtml(output.planMode || 'auto') + '</span>',
          '    <span class="badge">Generated: ' + escapeHtml(String(output.generatedAt || '')) + '</span>',
          '    <span class="badge badgeGood">Variants: ' + escapeHtml(String(variants.length)) + '</span>',
          '  </div>',
          '  <div class="buttonRow">',
          '    <button class="button" data-action="expand">Open larger</button>',
          '  </div>',
          '</section>',
          '<div class="grid">' + body + '</div>',
          '<div class="finePrint">This widget is intentionally thin. The EDMG backend remains the source of truth for analysis, plan storage, and timeline state.</div>'
        ].join("\n");
      }

      function renderActionResult(output) {
        return [
          '<section class="hero">',
          '  <div class="eyebrow">EDMG Director</div>',
          '  <h1 class="title">' + escapeHtml(output.title || 'Action complete') + '</h1>',
          '  <p class="summary">' + escapeHtml(output.message || 'The requested EDMG action completed.') + '</p>',
          '  <div class="metaRow">',
          '    <span class="badge badgeGood">Project: ' + escapeHtml(output.projectName || output.projectId || '') + '</span>',
          '    <span class="badge">Variant: ' + escapeHtml(String((output.variantIndex ?? 0) + 1)) + '</span>',
          output.overwrite ? '    <span class="badge badgeAccent">Overwrite applied</span>' : '',
          '  </div>',
          '  <div class="buttonRow">',
          '    <button class="button buttonPrimary" data-action="ask-next" data-project-id="' + escapeHtml(output.projectId || '') + '" data-variant-index="' + escapeHtml(output.variantIndex ?? 0) + '">Ask ChatGPT for next EDMG step</button>',
          '    <button class="button" data-action="expand">Open larger</button>',
          '  </div>',
          '</section>'
        ].join("\n");
      }

      function renderFallback(output) {
        return [
          '<section class="hero">',
          '  <div class="eyebrow">EDMG Director</div>',
          '  <h1 class="title">Tool output</h1>',
          '  <p class="summary">This view only has a custom layout for plan previews and apply confirmations.</p>',
          '</section>',
          '<pre class="status">' + escapeHtml(JSON.stringify(output || {}, null, 2)) + '</pre>'
        ].join("\n");
      }

      function render(output) {
        setTheme();
        lastOutput = output || {};
        let markup;
        if (lastOutput && lastOutput.kind === "planPreview") {
          markup = renderPlanPreview(lastOutput);
        } else if (lastOutput && lastOutput.kind === "actionResult") {
          markup = renderActionResult(lastOutput);
        } else {
          markup = renderFallback(lastOutput);
        }

        const status = busyMessage
          ? '<div class="status">' + escapeHtml(busyMessage) + '</div>'
          : errorMessage
            ? '<div class="status error">' + escapeHtml(errorMessage) + '</div>'
            : '';

        root.innerHTML = markup + status;
      }

      async function applyPlanVariant(projectId, variantIndex, overwrite) {
        errorMessage = "";
        busyMessage = "Applying the selected EDMG variant to the timeline…";
        render(lastOutput);
        try {
          if (!api().callTool) throw new Error("This host does not expose window.openai.callTool.");
          const result = await api().callTool("apply_plan_variant", {
            projectId: projectId,
            variantIndex: Number(variantIndex),
            overwrite: Boolean(overwrite),
          });
          if (result && result.isError) {
            throw new Error(extractText(result.content) || "The EDMG apply tool reported an error.");
          }
          busyMessage = "";
          errorMessage = "";
          render(result && result.structuredContent ? result.structuredContent : {
            kind: "actionResult",
            title: "Timeline updated",
            message: extractText(result && result.content) || "The EDMG timeline was updated.",
            projectId: projectId,
            variantIndex: Number(variantIndex),
            overwrite: Boolean(overwrite)
          });
        } catch (error) {
          busyMessage = "";
          errorMessage = error instanceof Error ? error.message : String(error);
          render(lastOutput);
        }
      }

      async function askForNotes(projectId, variantIndex) {
        if (!api().sendFollowUpMessage) return;
        await api().sendFollowUpMessage({
          role: "user",
          content: [{
            type: "text",
            text: "Summarize the EDMG storyboard differences for project " + projectId + " and focus on variant " + (Number(variantIndex) + 1) + "."
          }]
        });
      }

      async function askForNextStep(projectId, variantIndex) {
        if (!api().sendFollowUpMessage) return;
        await api().sendFollowUpMessage({
          role: "user",
          content: [{
            type: "text",
            text: "The EDMG timeline now has variant " + (Number(variantIndex) + 1) + " applied for project " + projectId + ". Tell me the best next step inside Studio."
          }]
        });
      }

      async function expandWidget() {
        if (!api().requestDisplayMode) return;
        await api().requestDisplayMode({ mode: "fullscreen" });
      }

      root.addEventListener("click", async function (event) {
        const target = event.target instanceof Element ? event.target.closest("button[data-action]") : null;
        if (!target) return;
        const action = target.getAttribute("data-action");
        if (action === "apply") {
          await applyPlanVariant(
            target.getAttribute("data-project-id") || "",
            Number(target.getAttribute("data-variant-index") || "0"),
            target.getAttribute("data-overwrite") === "true"
          );
          return;
        }
        if (action === "ask") {
          await askForNotes(
            target.getAttribute("data-project-id") || "",
            Number(target.getAttribute("data-variant-index") || "0")
          );
          return;
        }
        if (action === "ask-next") {
          await askForNextStep(
            target.getAttribute("data-project-id") || "",
            Number(target.getAttribute("data-variant-index") || "0")
          );
          return;
        }
        if (action === "expand") {
          await expandWidget();
        }
      });

      window.addEventListener(
        "openai:set_globals",
        function (event) {
          render(event && event.detail && event.detail.globals ? event.detail.globals.toolOutput : api().toolOutput);
        },
        { passive: true }
      );

      render(api().toolOutput || {});
    </script>
  </body>
</html>`;

function createServer(): McpServer {
  const server = new McpServer({
    name: "edmg-director",
    version: SERVER_VERSION,
  });

  registerAppResource(
    server,
    "edmg-director-review-board",
    REVIEW_WIDGET_URI,
    {
      mimeType: RESOURCE_MIME_TYPE,
      description: "Review EDMG storyboard variants and apply one to the timeline.",
    },
    async () => ({
      contents: [
        {
          uri: REVIEW_WIDGET_URI,
          mimeType: RESOURCE_MIME_TYPE,
          text: REVIEW_WIDGET_HTML,
          _meta: {
            ui: {
              prefersBorder: true,
              csp: {
                connectDomains: [],
                resourceDomains: [],
              },
            },
            "openai/widgetDescription": "Review EDMG storyboard variants and apply one to the timeline.",
          },
        },
      ],
    })
  );

  registerAppTool(
    server,
    "search",
    {
      title: "Search EDMG projects",
      description:
        "Use this when you need to find an EDMG Studio project by name before inspecting or changing it.",
      inputSchema: {
        query: z.string().optional().describe("Optional case-insensitive project name filter."),
        limit: z.number().int().min(1).max(20).optional().describe("Maximum number of projects to return."),
      },
      annotations: {
        readOnlyHint: true,
        destructiveHint: false,
        openWorldHint: false,
      },
      _meta: {
        "openai/toolInvocation/invoking": "Searching EDMG projects…",
        "openai/toolInvocation/invoked": "EDMG projects ready.",
      },
    },
    async ({ query, limit }) => {
      const projects = await fetchProjects(query, limit ?? 8);
      const summarized = projects.map(summarizeProjectRecord);
      return {
        structuredContent: {
          kind: "searchResults",
          backendUrl: backendBaseUrl(),
          query: String(query ?? ""),
          projects: summarized,
        },
        content: [
          {
            type: "text",
            text: summarized.length
              ? `Found ${summarized.length} EDMG Studio projects${query ? ` matching “${query}”` : ""}.`
              : `No EDMG Studio projects matched${query ? ` “${query}”` : " the current filter"}.`,
          },
        ],
      };
    }
  );

  registerAppTool(
    server,
    "fetch",
    {
      title: "Fetch EDMG project snapshot",
      description:
        "Use this when you already know the project id and need its latest analysis, plan, and handoff status.",
      inputSchema: {
        projectId: z.string().min(1).describe("Exact EDMG Studio project id."),
      },
      annotations: {
        readOnlyHint: true,
        destructiveHint: false,
        openWorldHint: false,
      },
      _meta: {
        "openai/toolInvocation/invoking": "Fetching EDMG project…",
        "openai/toolInvocation/invoked": "EDMG project snapshot ready.",
      },
    },
    async ({ projectId }) => {
      const project = await fetchProject(projectId);
      const snapshot = summarizeProjectSnapshot(project);
      return {
        structuredContent: snapshot,
        content: [
          {
            type: "text",
            text: `Fetched EDMG Studio snapshot for ${snapshot.project.name}.`,
          },
        ],
      };
    }
  );

  registerAppTool(
    server,
    "analyze_project_audio",
    {
      title: "Analyze EDMG project audio",
      description:
        "Use this when a project has audio uploaded but no current analysis, or when the user wants fresh beat/transcript features before planning.",
      inputSchema: {
        projectId: z.string().min(1).describe("Exact EDMG Studio project id."),
      },
      annotations: {
        readOnlyHint: false,
        destructiveHint: false,
        openWorldHint: false,
      },
      _meta: {
        "openai/toolInvocation/invoking": "Running EDMG audio analysis…",
        "openai/toolInvocation/invoked": "EDMG audio analysis complete.",
      },
    },
    async ({ projectId }) => {
      const result = await postJson<any>(`/v1/projects/${encodeURIComponent(projectId)}/analyze_audio`, {});
      const analysis = analysisSummary(result.analysis ?? asObject(result.project).meta?.analysis);
      return {
        structuredContent: {
          kind: "analysisResult",
          projectId,
          analysis,
        },
        content: [
          {
            type: "text",
            text: `EDMG audio analysis is ready. ${analysis.summary}`,
          },
        ],
      };
    }
  );

  registerAppTool(
    server,
    "generate_plan_preview",
    {
      title: "Generate EDMG plan preview",
      description:
        "Use this when the user wants EDMG Studio to generate or refresh storyboard variants and review them in ChatGPT before applying one to the timeline.",
      inputSchema: {
        projectId: z.string().min(1).describe("Exact EDMG Studio project id."),
        planMode: z
          .enum(["auto", "ai", "local"])
          .optional()
          .describe("Planner mode forwarded to the EDMG backend."),
        numVariants: z.number().int().min(1).max(6).optional().describe("How many plan variants EDMG should generate."),
        maxScenes: z.number().int().min(1).max(16).optional().describe("Maximum scene count per generated variant."),
        title: z.string().optional().describe("Optional plan title override."),
        stylePrefs: z.string().optional().describe("Optional EDMG style preference string."),
      },
      annotations: {
        readOnlyHint: false,
        destructiveHint: false,
        openWorldHint: false,
      },
      _meta: {
        ui: { resourceUri: REVIEW_WIDGET_URI },
        "openai/outputTemplate": REVIEW_WIDGET_URI,
        "openai/toolInvocation/invoking": "Generating EDMG storyboard variants…",
        "openai/toolInvocation/invoked": "EDMG storyboard variants ready.",
      },
    },
    async ({ projectId, planMode, numVariants, maxScenes, title, stylePrefs }) => {
      const project = await fetchProject(projectId);
      const requestBody = {
        title: trimText(title, 200) || trimText(project.name, 200) || "Untitled",
        style_prefs:
          trimText(stylePrefs, 260) ||
          "cinematic, coherent subject, high detail, consistent style",
        num_variants: numVariants ?? 3,
        max_scenes: maxScenes ?? 8,
      };
      const mode = planMode ?? "auto";
      const plan = await postJson<any>(
        `/v1/projects/${encodeURIComponent(projectId)}/plan?mode=${encodeURIComponent(mode)}`,
        requestBody
      );
      const variants = summarizePlanVariants(plan);
      const output = {
        kind: "planPreview",
        projectId,
        projectName: trimText(project.name, 120) || projectId,
        planMode: mode,
        generatedAt: new Date().toISOString(),
        variants,
      };
      return {
        structuredContent: output,
        content: [
          {
            type: "text",
            text: `Prepared ${variants.length} EDMG storyboard variants for ${output.projectName}. Review them in the widget and apply the best one to the timeline when ready.`,
          },
        ],
      };
    }
  );

  registerAppTool(
    server,
    "apply_plan_variant",
    {
      title: "Apply EDMG plan variant",
      description:
        "Use this when the user has already reviewed plan variants and wants one applied to the EDMG Studio timeline.",
      inputSchema: {
        projectId: z.string().min(1).describe("Exact EDMG Studio project id."),
        variantIndex: z.number().int().min(0).describe("Zero-based index of the EDMG plan variant to apply."),
        overwrite: z.boolean().optional().describe("Whether to overwrite the current timeline instead of merging into it."),
      },
      annotations: {
        readOnlyHint: false,
        destructiveHint: true,
        openWorldHint: false,
      },
      _meta: {
        ui: { resourceUri: REVIEW_WIDGET_URI },
        "openai/outputTemplate": REVIEW_WIDGET_URI,
        "openai/toolInvocation/invoking": "Applying EDMG plan to timeline…",
        "openai/toolInvocation/invoked": "EDMG timeline updated.",
      },
    },
    async ({ projectId, variantIndex, overwrite }) => {
      await postJson<any>(`/v1/projects/${encodeURIComponent(projectId)}/timeline/apply_plan`, {
        variant_index: variantIndex,
        overwrite: overwrite ?? false,
      });
      const project = await fetchProject(projectId);
      const variants = summarizePlanVariants(asObject(asObject(project).meta).last_plan);
      const chosenVariant = variants[variantIndex];
      const message = chosenVariant
        ? `Applied ${chosenVariant.name} to the EDMG timeline${overwrite ? " with overwrite enabled" : ""}.`
        : `Applied EDMG variant ${variantIndex + 1} to the timeline${overwrite ? " with overwrite enabled" : ""}.`;
      return {
        structuredContent: {
          kind: "actionResult",
          action: "applyPlanVariant",
          title: "Timeline updated",
          message,
          projectId,
          projectName: trimText(project.name, 120) || projectId,
          variantIndex,
          overwrite: overwrite ?? false,
        },
        content: [
          {
            type: "text",
            text: message,
          },
        ],
      };
    }
  );

  return server;
}

const app = express();
app.use(cors());
app.use(express.json({ limit: "1mb" }));

app.get("/", (_req, res) => {
  res.json({
    ok: true,
    name: "edmg-director",
    version: SERVER_VERSION,
    backendUrl: backendBaseUrl(),
    mcpPath: "/mcp",
  });
});

app.all("/mcp", async (req, res) => {
  const server = createServer();
  const transport = new StreamableHTTPServerTransport({
    sessionIdGenerator: undefined,
  });

  res.on("close", () => {
    transport.close().catch(() => {});
    server.close().catch(() => {});
  });

  try {
    await server.connect(transport);
    await transport.handleRequest(req, res, req.body);
  } catch (error) {
    console.error("EDMG Director MCP error:", error);
    if (!res.headersSent) {
      res.status(500).json({
        jsonrpc: "2.0",
        error: {
          code: -32603,
          message: error instanceof Error ? error.message : "Internal server error",
        },
        id: null,
      });
    }
  }
});

app.listen(PORT, () => {
  console.log(`EDMG Director listening on http://localhost:${PORT}/mcp`);
  console.log(`Using EDMG backend ${backendBaseUrl()}`);
});
