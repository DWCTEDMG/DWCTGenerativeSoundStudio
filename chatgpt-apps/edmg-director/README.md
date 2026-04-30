# EDMG Director

A first-pass ChatGPT app scaffold for EDMG Studio.

This package wraps the existing EDMG backend so ChatGPT can:

- find EDMG Studio projects
- inspect project analysis and plan state
- trigger audio analysis
- generate storyboard variants with the existing `/plan` backend flow
- review those variants in a ChatGPT widget
- apply a chosen variant to the EDMG timeline

## Archetype

Primary archetype: `interactive-decoupled`

Reasoning:

- read-only project tools (`search`, `fetch`) stay reusable and chainable
- the plan-review tool owns the widget and presentation flow
- the widget can call a mutating tool (`apply_plan_variant`) without remounting the whole app flow

## Tool surface

- `search`
  - Use this when you need to find an EDMG Studio project by name before inspecting or changing it.
- `fetch`
  - Use this when you already know the project id and need its latest analysis, plan, and handoff status.
- `analyze_project_audio`
  - Use this when a project has audio uploaded but no current analysis, or when the user wants fresh beat/transcript features before planning.
- `generate_plan_preview`
  - Use this when the user wants EDMG Studio to generate or refresh storyboard variants and review them in ChatGPT before applying one to the timeline.
- `apply_plan_variant`
  - Use this when the user has already reviewed plan variants and wants one applied to the EDMG Studio timeline.

## Stack

- Node + TypeScript MCP server
- `@modelcontextprotocol/sdk`
- `@modelcontextprotocol/ext-apps`
- one embedded vanilla HTML widget resource
- direct HTTP calls to the EDMG backend via `EDMG_BACKEND_URL`

## Why this shape

This scaffold follows the current Apps SDK guidance to keep:

- the MCP server as the required integration surface
- the UI optional but present for the review/apply step
- reusable data tools separate from the render tool
- the widget lightweight so it can be tested without adding a second frontend build system

## Files

- `src/server.ts`
  - MCP server, EDMG backend client helpers, tool registrations, and embedded review widget.
- `package.json`
  - standalone app package manifest.
- `tsconfig.json`
  - minimal NodeNext TypeScript config.

## Environment

Required:

- `EDMG_BACKEND_URL`
  - defaults to `http://127.0.0.1:7863`

Optional:

- `PORT`
  - defaults to `8788`

## Local run

```bash
cd chatgpt-apps/edmg-director
pnpm install
pnpm start
```

PowerShell example:

```powershell
$env:EDMG_BACKEND_URL = "http://127.0.0.1:7863"
$env:PORT = "8788"
pnpm start
```

The server exposes:

- health check: `GET /`
- MCP endpoint: `http://localhost:8788/mcp`

## MCP and ChatGPT loop

1. Start EDMG Studio backend.
2. Start this MCP server.
3. Expose it publicly during development, for example:

```bash
ngrok http 8788
```

4. In ChatGPT, enable Developer Mode under `Settings -> Apps & Connectors -> Advanced settings`.
5. Create a new app using the public HTTPS tunnel URL plus `/mcp`.
6. Refresh the app in ChatGPT after tool or metadata changes.

## Suggested prompts

- `Use EDMG Director to find my project named neon freeway and summarize its current plan state.`
- `Use EDMG Director to analyze project <project-id> and then generate three storyboard variants.`
- `Use EDMG Director to generate a new plan preview for project <project-id> with 4 variants and up to 10 scenes.`
- `Use EDMG Director to apply variant 2 from the latest preview to the EDMG timeline.`

## Known limits

- This first pass focuses on the existing backend planning flow, not the separate Planner Lab import payloads.
- Reactive Lab handoff is not implemented yet.
- The widget reviews and applies plan variants, but does not preview local media files directly.
- There is no auth layer yet; the app assumes the MCP server can already reach a trusted EDMG backend.
- No persistence is needed for the current flow because the generated plan is stored by the EDMG backend itself.

## Next useful upgrades

- add `fetch_outputs` for render result summaries
- add `planner_lab/import` support for conversation-built handoff payloads
- add `reactive_lab/apply` support for motion schedules
- add backend auth and per-user project scoping
- split widget HTML into versioned static assets if the UI grows beyond a single file

## References

- Apps SDK home: https://developers.openai.com/apps-sdk
- Quickstart: https://developers.openai.com/apps-sdk/quickstart
- Build your MCP server: https://developers.openai.com/apps-sdk/build/mcp-server
- Build your ChatGPT UI: https://developers.openai.com/apps-sdk/build/chatgpt-ui
- Define tools: https://developers.openai.com/apps-sdk/plan/tools
- Official examples repo: https://github.com/openai/openai-apps-sdk-examples
