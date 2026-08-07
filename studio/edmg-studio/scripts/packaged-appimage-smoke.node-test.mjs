import assert from "node:assert/strict";
import path from "node:path";
import test from "node:test";

import { resolveCurrentAppImage } from "./packaged-appimage-smoke.mjs";

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
