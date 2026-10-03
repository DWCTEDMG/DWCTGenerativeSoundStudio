import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { test } from "node:test";

// Exercise the transitive Hono instance used by the MCP SDK, not a second copy.
const sdkRequire = createRequire(import.meta.resolve("@modelcontextprotocol/sdk/server/mcp.js"));
const { jsx, createContext, Suspense, ErrorBoundary } = sdkRequire("hono/jsx");
const { renderToString, renderToReadableStream } = sdkRequire("hono/jsx/dom/server");
const { renderToReadableStream: renderJsxStream } = sdkRequire("hono/jsx/streaming");

for (const input of ['<img src=x onerror="alert(1)">', '<script>alert("x")</script>', 'ordinary & readable']) {
  test(`Hono escapes untrusted strings across server rendering boundaries: ${input}`, async () => {
    const context = createContext("");
    const outputs = [
      await renderToString(input),
      await renderToString([input]),
      await jsx(context.Provider, { value: "" }, input).toString(),
      await jsx(Suspense, { fallback: "loading" }, input).toString(),
      await jsx(ErrorBoundary, { fallback: "error" }, input, Promise.resolve("")).toString(),
      await jsx(Suspense, { fallback: input }, jsx(async () => jsx("span", null, "ready"), null)).toString(),
      await jsx(ErrorBoundary, { fallback: input }, jsx(() => { throw new Error("test"); }, null)).toString(),
      await new Response(renderJsxStream(jsx(ErrorBoundary, { fallback: "error" }, jsx(async () => input, null)))).text(),
      await new Response(await renderToReadableStream(input)).text(),
    ];
    for (const output of outputs) {
      assert.ok(String(output).includes(input.startsWith("<") ? "&lt;" : "&amp;"));
      assert.ok(!String(output).includes(input));
    }
    assert.equal(await renderToString("ordinary text"), "ordinary text");
  });
}
