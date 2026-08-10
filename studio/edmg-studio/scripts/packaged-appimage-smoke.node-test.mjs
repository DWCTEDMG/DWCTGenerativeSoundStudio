import assert from "node:assert/strict";
import path from "node:path";
import test from "node:test";

import {
  APPIMAGE_RENDERER_TIMEOUT_ENV,
  APPIMAGE_RENDERER_TIMEOUT_LIMITS,
  resolveCurrentAppImage,
  resolveRendererReportTimeoutMs,
} from "./packaged-appimage-smoke.mjs";

test("final AppImage selection is version-specific and ignores unrelated dist files", () => {
  assert.equal(
    resolveCurrentAppImage("/release/dist", "1.2.0", [
      "builder-effective-config.yaml",
      "EDMG-Studio-1.1.0-linux-x64-cuda.AppImage",
      "EDMG-Studio-1.2.0-linux-x64-cuda.AppImage",
    ]),
    path.join("/release/dist", "EDMG-Studio-1.2.0-linux-x64-cuda.AppImage"),
  );
});

test("final AppImage selection fails closed for missing or colliding candidates", () => {
  assert.throws(
    () => resolveCurrentAppImage("/release/dist", "1.2.0", ["EDMG-Studio-1.1.0.AppImage"]),
    /found 0/,
  );
  assert.throws(
    () =>
      resolveCurrentAppImage("/release/dist", "1.2.0", [
        "EDMG-Studio-1.2.0-linux-x64-cpu.AppImage",
        "EDMG-Studio-1.2.0-linux-x64-cuda.AppImage",
      ]),
    /found 2/,
  );
});

test("renderer report timeout uses profile-aware defaults", () => {
  assert.equal(resolveRendererReportTimeoutMs({ profile: "cpu", env: {} }), 210_000);
  assert.equal(resolveRendererReportTimeoutMs({ profile: "cuda", env: {} }), 900_000);
});

test("renderer report timeout accepts a bounded integer override", () => {
  assert.equal(
    resolveRendererReportTimeoutMs({
      profile: "cuda",
      env: { [APPIMAGE_RENDERER_TIMEOUT_ENV]: "600000" },
    }),
    600_000,
  );
  assert.equal(
    resolveRendererReportTimeoutMs({
      profile: "cpu",
      env: { [APPIMAGE_RENDERER_TIMEOUT_ENV]: String(APPIMAGE_RENDERER_TIMEOUT_LIMITS.min) },
    }),
    APPIMAGE_RENDERER_TIMEOUT_LIMITS.min,
  );
  assert.equal(
    resolveRendererReportTimeoutMs({
      profile: "cpu",
      env: { [APPIMAGE_RENDERER_TIMEOUT_ENV]: String(APPIMAGE_RENDERER_TIMEOUT_LIMITS.max) },
    }),
    APPIMAGE_RENDERER_TIMEOUT_LIMITS.max,
  );
});

test("renderer report timeout rejects malformed and out-of-range overrides", () => {
  for (const value of [
    "",
    " ",
    "0",
    "-1",
    "29999",
    "210000.5",
    "1e6",
    "+900000",
    "30s",
    "NaN",
    "Infinity",
    " 600000 ",
    String(APPIMAGE_RENDERER_TIMEOUT_LIMITS.max + 1),
    "9007199254740993",
    undefined,
  ]) {
    assert.throws(
      () =>
        resolveRendererReportTimeoutMs({
          profile: "cuda",
          env: { [APPIMAGE_RENDERER_TIMEOUT_ENV]: value },
        }),
      new RegExp(APPIMAGE_RENDERER_TIMEOUT_ENV),
    );
  }
  assert.throws(() => resolveRendererReportTimeoutMs({ profile: "directml", env: {} }), /cpu or cuda profile/);
});
