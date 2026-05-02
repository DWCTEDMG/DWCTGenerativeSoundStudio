import assert from "node:assert/strict";
import { once } from "node:events";
import {
  createServer as createHttpServer,
  type IncomingMessage,
  type Server as HttpServer,
  type ServerResponse,
} from "node:http";
import type { AddressInfo } from "node:net";
import { after, before, describe, it } from "node:test";

import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StreamableHTTPClientTransport } from "@modelcontextprotocol/sdk/client/streamableHttp.js";

import {
  createStreamableHttpApp,
  resolveServerConfig,
  type ServerConfig,
} from "../src/server.js";

type CapturedRequests = {
  planBodies: Array<Record<string, unknown>>;
  applyPlanBodies: Array<Record<string, unknown>>;
  plannerImportBodies: Array<Record<string, unknown>>;
  reactiveApplyBodies: Array<Record<string, unknown>>;
};

const PROJECT_ID = "demo-project";
const PROJECT_NAME = "Demo Project";
const ANALYSIS = {
  hook_line: "Lift the skyline",
  narrative_structure: "intro -> rise -> drop",
  features: {
    bpm: 128,
    duration_s: 12,
  },
};
const PLAN_RESPONSE = {
  source: "test-harness",
  variants: [
    {
      label: "Neon Pulse",
      summary: "High-contrast club performance with aggressive camera pushes.",
      duration_s: 12,
      scenes: [
        {
          title: "Cold Open",
          prompt: "Neon tunnel tracking shot around the singer.",
          start_s: 0,
          end_s: 4,
          duration_s: 4,
          shot_type: "wide",
          rationale: "Introduce the performance space before the drop.",
          transition_cue: "push through the chorus hit",
          continuity_note: "keep performer centered",
        },
        {
          title: "Drop Bloom",
          prompt: "Orbit the vocalist while LED walls strobe on the beat.",
          start_s: 4,
          end_s: 8,
          duration_s: 4,
          shot_type: "orbit",
          rationale: "Peak-energy section with more rotation.",
          transition_cue: "orbit into the drop",
        },
        {
          title: "Afterglow",
          prompt: "Slow pullback into atmospheric haze as the hook resolves.",
          start_s: 8,
          end_s: 12,
          duration_s: 4,
          shot_type: "pullback",
          rationale: "Release pressure without losing continuity.",
          transition_cue: "soft cut into haze",
          continuity_note: "hold camera travel direction",
        },
      ],
    },
    {
      label: "City Echo",
      summary: "Exterior night skyline with slower transitions.",
      duration_s: 12,
      scenes: [
        {
          title: "Skyline Intro",
          prompt: "Aerial drift above the city before the beat lands.",
          start_s: 0,
          end_s: 6,
          duration_s: 6,
          shot_type: "drone",
          rationale: "Set the world before moving into performance shots.",
          transition_cue: "ambient rise",
        },
        {
          title: "Rooftop Hook",
          prompt: "Performance on a reflective rooftop with synchronized lights.",
          start_s: 6,
          end_s: 12,
          duration_s: 6,
          shot_type: "medium",
          rationale: "Ground the hook in a clear hero moment.",
          transition_cue: "smash cut on the snare",
        },
      ],
    },
  ],
};
const TIMELINE = {
  tracks: [{ id: "camera" }, { id: "motion" }],
  sections: [{ id: 1 }, { id: 2 }],
  camera: {
    mode: "cinematic",
  },
};

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" ? (value as Record<string, unknown>) : {};
}

function json(res: ServerResponse, status: number, payload: unknown): void {
  const body = JSON.stringify(payload);
  res.statusCode = status;
  res.setHeader("Content-Type", "application/json");
  res.end(body);
}

async function readJsonBody(req: IncomingMessage): Promise<Record<string, unknown>> {
  const chunks: Buffer[] = [];
  for await (const chunk of req) {
    chunks.push(Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk));
  }
  if (!chunks.length) {
    return {};
  }
  return asRecord(JSON.parse(Buffer.concat(chunks).toString("utf8")));
}

function projectPayload() {
  return {
    project: {
      id: PROJECT_ID,
      name: PROJECT_NAME,
      meta: {
        analysis: ANALYSIS,
        last_plan: PLAN_RESPONSE,
        timeline: TIMELINE,
      },
    },
  };
}

function createBackendServer(captured: CapturedRequests): HttpServer {
  return createHttpServer(async (req, res) => {
    const url = new URL(req.url ?? "/", `http://${req.headers.host ?? "127.0.0.1"}`);

    if (req.method === "GET" && url.pathname === "/health") {
      json(res, 200, { ok: true, version: "test-backend" });
      return;
    }

    if (req.method === "GET" && url.pathname === "/v1/projects") {
      json(res, 200, {
        projects: [
          {
            id: PROJECT_ID,
            name: PROJECT_NAME,
            created_at: 1710000000,
            updated_at: 1710003600,
          },
        ],
      });
      return;
    }

    if (req.method === "GET" && url.pathname === `/v1/projects/${PROJECT_ID}`) {
      json(res, 200, projectPayload());
      return;
    }

    if (req.method === "POST" && url.pathname === `/v1/projects/${PROJECT_ID}/analyze_audio`) {
      json(res, 200, { analysis: ANALYSIS });
      return;
    }

    if (req.method === "POST" && url.pathname === `/v1/projects/${PROJECT_ID}/plan`) {
      const body = await readJsonBody(req);
      captured.planBodies.push(body);
      json(res, 200, PLAN_RESPONSE);
      return;
    }

    if (req.method === "POST" && url.pathname === `/v1/projects/${PROJECT_ID}/timeline/apply_plan`) {
      const body = await readJsonBody(req);
      captured.applyPlanBodies.push(body);
      json(res, 200, { ok: true, timeline: TIMELINE });
      return;
    }

    if (req.method === "POST" && url.pathname === `/v1/projects/${PROJECT_ID}/planner_lab/import`) {
      const body = await readJsonBody(req);
      captured.plannerImportBodies.push(body);
      json(res, 200, {
        plan: body.plan ?? PLAN_RESPONSE,
        timeline: body.apply_timeline ? TIMELINE : null,
      });
      return;
    }

    if (req.method === "POST" && url.pathname === `/v1/projects/${PROJECT_ID}/reactive_lab/apply`) {
      const body = await readJsonBody(req);
      captured.reactiveApplyBodies.push(body);
      json(res, 200, {
        ok: true,
        timeline: TIMELINE,
      });
      return;
    }

    json(res, 404, {
      detail: `Unhandled ${req.method} ${url.pathname}`,
    });
  });
}

async function listen(server: HttpServer): Promise<string> {
  server.listen(0, "127.0.0.1");
  await once(server, "listening");
  const address = server.address() as AddressInfo;
  return `http://127.0.0.1:${address.port}`;
}

async function closeServer(server: HttpServer): Promise<void> {
  await new Promise<void>((resolve, reject) => {
    server.close((error) => {
      if (error) {
        reject(error);
        return;
      }
      resolve();
    });
  });
}

async function withClient(
  baseUrl: string,
  run: (client: Client, transport: StreamableHTTPClientTransport) => Promise<void>,
): Promise<void> {
  const transport = new StreamableHTTPClientTransport(new URL(`${baseUrl}/mcp`));
  const client = new Client({
    name: "edmg-director-tests",
    version: "0.0.0",
  });

  await client.connect(transport);
  try {
    await run(client, transport);
  } finally {
    await transport.close();
  }
}

function structured<T extends Record<string, unknown>>(value: unknown): T {
  return asRecord(asRecord(value).structuredContent) as T;
}

async function createHarness(edmgBaseUrl: string) {
  const config: ServerConfig = resolveServerConfig(process.env, {
    bindHost: "127.0.0.1",
    port: 0,
    publicBaseUrl: "http://127.0.0.1:0",
    edmgBaseUrl,
  });
  const app = createStreamableHttpApp(config);
  const server = app.listen(0, "127.0.0.1");
  await once(server, "listening");
  const address = server.address() as AddressInfo;
  config.publicBaseUrl = `http://127.0.0.1:${address.port}`;
  return {
    baseUrl: config.publicBaseUrl,
    server,
  };
}

describe("EDMG Director MCP server", () => {
  const captured: CapturedRequests = {
    planBodies: [],
    applyPlanBodies: [],
    plannerImportBodies: [],
    reactiveApplyBodies: [],
  };

  let backendServer: HttpServer;
  let backendBaseUrl = "";
  let appServer: HttpServer;
  let appBaseUrl = "";

  before(async () => {
    backendServer = createBackendServer(captured);
    backendBaseUrl = await listen(backendServer);

    const harness = await createHarness(backendBaseUrl);
    appServer = harness.server;
    appBaseUrl = harness.baseUrl;
  });

  after(async () => {
    await closeServer(appServer);
    await closeServer(backendServer);
  });

  it("serves the MCP metadata endpoint", async () => {
    const response = await fetch(appBaseUrl);
    assert.equal(response.ok, true);
    const payload = asRecord(await response.json());
    assert.equal(payload.mcpPath, "/mcp");
    assert.equal(payload.assetsPath, "/assets");
    assert.equal(payload.edmgBaseUrl, backendBaseUrl);
  });

  it("lists all EDMG tools", async () => {
    await withClient(appBaseUrl, async (client) => {
      const result = await client.listTools();
      const toolNames = result.tools.map((tool) => tool.name).sort();
      assert.deepEqual(toolNames, [
        "analyze_project_audio",
        "apply_plan_variant",
        "apply_reactive_handoff",
        "backend_status",
        "fetch",
        "generate_plan_preview",
        "import_planner_lab_payload",
        "search",
      ]);
    });
  });

  it("smoke-tests the EDMG tool flow through MCP", async () => {
    await withClient(appBaseUrl, async (client) => {
      const backendStatus = structured(await client.callTool({ name: "backend_status", arguments: {} }));
      assert.equal(backendStatus.type, "backend-status");
      assert.equal(backendStatus.available, true);
      assert.match(String(backendStatus.detail), /Connected to EDMG backend/i);

      const searchResult = structured<{ type: string; results: Array<Record<string, unknown>> }>(
        await client.callTool({
          name: "search",
          arguments: {
            query: "demo",
            limit: 5,
          },
        }),
      );
      assert.equal(searchResult.type, "project-search-results");
      assert.equal(searchResult.results.length, 1);
      assert.equal(searchResult.results[0]?.id, PROJECT_ID);

      const fetchResult = structured<{ type: string; projectName: string; variantCount: number }>(
        await client.callTool({
          name: "fetch",
          arguments: {
            projectId: PROJECT_ID,
          },
        }),
      );
      assert.equal(fetchResult.type, "project-detail");
      assert.equal(fetchResult.projectName, PROJECT_NAME);
      assert.equal(fetchResult.variantCount, PLAN_RESPONSE.variants.length);

      const analysisResult = structured<{ type: string; analysisSummary: Record<string, unknown> | null }>(
        await client.callTool({
          name: "analyze_project_audio",
          arguments: {
            projectId: PROJECT_ID,
          },
        }),
      );
      assert.equal(analysisResult.type, "audio-analysis");
      assert.equal(analysisResult.analysisSummary?.bpm, 128);

      const previewResult = structured<{
        type: string;
        projectId: string;
        selectedVariantIndex: number;
        variants: Array<Record<string, unknown>>;
      }>(
        await client.callTool({
          name: "generate_plan_preview",
          arguments: {
            projectId: PROJECT_ID,
            mode: "auto",
            title: "Festival Cut",
            userNotes: "Push the chorus harder.",
            stylePrefs: "Saturated neon with hard cuts.",
            numVariants: 2,
            maxScenes: 4,
          },
        }),
      );
      assert.equal(previewResult.type, "plan-preview");
      assert.equal(previewResult.projectId, PROJECT_ID);
      assert.equal(previewResult.selectedVariantIndex, 0);
      assert.equal(previewResult.variants.length, 2);
      assert.equal(captured.planBodies[0]?.num_variants, 2);
      assert.equal(captured.planBodies[0]?.max_scenes, 4);
      assert.equal(captured.planBodies[0]?.title, "Festival Cut");

      const applyVariantResult = structured<{
        type: string;
        applied: boolean;
        overwrite: boolean;
        variantIndex: number;
      }>(
        await client.callTool({
          name: "apply_plan_variant",
          arguments: {
            projectId: PROJECT_ID,
            variantIndex: 1,
            overwrite: false,
          },
        }),
      );
      assert.equal(applyVariantResult.type, "action-result");
      assert.equal(applyVariantResult.applied, true);
      assert.equal(applyVariantResult.overwrite, false);
      assert.equal(applyVariantResult.variantIndex, 1);
      assert.deepEqual(captured.applyPlanBodies[0], {
        variant_index: 1,
        overwrite: false,
      });

      const plannerImportResult = structured<{
        type: string;
        variantCount: number;
        appliedTimeline: boolean;
      }>(
        await client.callTool({
          name: "import_planner_lab_payload",
          arguments: {
            projectId: PROJECT_ID,
            analysis: {
              bpm: 128,
            },
            plan: PLAN_RESPONSE,
            settings: {
              selected_variant_index: 1,
            },
            applyTimeline: true,
            overwriteTimeline: false,
          },
        }),
      );
      assert.equal(plannerImportResult.type, "planner-import-result");
      assert.equal(plannerImportResult.variantCount, 2);
      assert.equal(plannerImportResult.appliedTimeline, true);
      assert.equal(captured.plannerImportBodies[0]?.apply_timeline, true);
      assert.equal(captured.plannerImportBodies[0]?.overwrite_timeline, false);

      const reactiveApplyResult = structured<{
        type: string;
        cueEventCount: number;
        keyframeCount: number;
        sectionCount: number;
      }>(
        await client.callTool({
          name: "apply_reactive_handoff",
          arguments: {
            projectId: PROJECT_ID,
            metadata: {
              generatedBy: "test-suite",
            },
            keyframes: [{ frame: 0, params: { zoom: 1.02 } }],
            beatMarkers: [{ frame: 12, time: 0.5, intensity: 0.72 }],
            cueEvents: [{ frame: 0, time: 0, cueType: "push" }],
            sections: [{ id: 1, startTime: 0, endTime: 4, label: "Cold Open" }],
            repairSuggestions: [{ id: 1, issue: "keep performer centered" }],
            schedules: {
              zoom: "0:(1.02)",
            },
            handoffManifest: {
              scheduleStride: 1,
            },
            overwriteMotionTrack: true,
            overwriteCamera: false,
          },
        }),
      );
      assert.equal(reactiveApplyResult.type, "reactive-apply-result");
      assert.equal(reactiveApplyResult.cueEventCount, 1);
      assert.equal(reactiveApplyResult.keyframeCount, 1);
      assert.equal(reactiveApplyResult.sectionCount, 1);
      assert.equal(captured.reactiveApplyBodies[0]?.overwrite_motion_track, true);
      assert.equal(captured.reactiveApplyBodies[0]?.overwrite_camera, false);
      assert.equal(Array.isArray(captured.reactiveApplyBodies[0]?.cue_events), true);
    });
  });

  it("reports backend_status as unavailable when the EDMG backend is offline", async () => {
    const offlineHarness = await createHarness("http://127.0.0.1:9");
    try {
      await withClient(offlineHarness.baseUrl, async (client) => {
        const backendStatus = structured(await client.callTool({ name: "backend_status", arguments: {} }));
        assert.equal(backendStatus.type, "backend-status");
        assert.equal(backendStatus.available, false);
        assert.match(String(backendStatus.detail), /Could not reach EDMG backend/i);
      });
    } finally {
      await closeServer(offlineHarness.server);
    }
  });
});
