import assert from "node:assert/strict";
import fsp from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";

import {
  assertOwnedPackagedDesktopSmokePath,
  resolveOwnedPackagedDesktopSmokePaths,
  runWithOwnedPackagedDesktopSmokeCleanup,
} from "./packaged-desktop-smoke.mjs";

async function createFixtureRoot() {
  const baseRoot = await fsp.mkdtemp(path.join(os.tmpdir(), "edmg-desktop-smoke-cleanup-test-"));
  const canonicalStageSentinel = path.join(baseRoot, "release", "staged-app", "sentinel.txt");
  const canonicalDistSentinel = path.join(baseRoot, "dist", "sentinel.txt");
  await Promise.all([
    fsp.mkdir(path.dirname(canonicalStageSentinel), { recursive: true }),
    fsp.mkdir(path.dirname(canonicalDistSentinel), { recursive: true }),
  ]);
  await Promise.all([
    fsp.writeFile(canonicalStageSentinel, "canonical staged app\n", "utf8"),
    fsp.writeFile(canonicalDistSentinel, "canonical dist\n", "utf8"),
  ]);
  return { baseRoot, canonicalStageSentinel, canonicalDistSentinel };
}

async function assertCanonicalSentinels(fixture) {
  assert.equal(await fsp.readFile(fixture.canonicalStageSentinel, "utf8"), "canonical staged app\n");
  assert.equal(await fsp.readFile(fixture.canonicalDistSentinel, "utf8"), "canonical dist\n");
}

async function pathExists(targetPath) {
  try {
    await fsp.lstat(targetPath);
    return true;
  } catch (error) {
    if (error.code === "ENOENT") return false;
    throw error;
  }
}

test("owned desktop smoke lifecycle pre-cleans and post-cleans without touching canonical artifacts", async () => {
  const fixture = await createFixtureRoot();
  const paths = resolveOwnedPackagedDesktopSmokePaths(fixture.baseRoot);
  try {
    await Promise.all([
      fsp.mkdir(paths.smokeStageDir, { recursive: true }),
      fsp.mkdir(paths.smokeOutputDir, { recursive: true }),
    ]);
    await Promise.all([
      fsp.writeFile(path.join(paths.smokeStageDir, "stale.txt"), "stale", "utf8"),
      fsp.writeFile(path.join(paths.smokeOutputDir, "stale.txt"), "stale", "utf8"),
    ]);

    const result = await runWithOwnedPackagedDesktopSmokeCleanup(
      async (ownedPaths) => {
        assert.equal(await pathExists(ownedPaths.smokeStageDir), false);
        assert.equal(await pathExists(ownedPaths.smokeOutputDir), false);
        await Promise.all([
          fsp.mkdir(ownedPaths.smokeStageDir, { recursive: true }),
          fsp.mkdir(ownedPaths.smokeOutputDir, { recursive: true }),
        ]);
        return { skipped: true };
      },
      { baseRoot: fixture.baseRoot },
    );

    assert.deepEqual(result, { skipped: true });
    assert.equal(await pathExists(paths.smokeStageDir), false);
    assert.equal(await pathExists(paths.smokeOutputDir), false);
    await assertCanonicalSentinels(fixture);
  } finally {
    await fsp.rm(fixture.baseRoot, { recursive: true, force: true });
  }
});

test("owned desktop smoke lifecycle cleans both paths after an operation failure", async () => {
  const fixture = await createFixtureRoot();
  const paths = resolveOwnedPackagedDesktopSmokePaths(fixture.baseRoot);
  const primaryError = new Error("injected packaged probe failure");
  try {
    await assert.rejects(
      runWithOwnedPackagedDesktopSmokeCleanup(
        async (ownedPaths) => {
          await Promise.all([
            fsp.mkdir(ownedPaths.smokeStageDir, { recursive: true }),
            fsp.mkdir(ownedPaths.smokeOutputDir, { recursive: true }),
          ]);
          throw primaryError;
        },
        { baseRoot: fixture.baseRoot },
      ),
      (error) => error === primaryError,
    );
    assert.equal(await pathExists(paths.smokeStageDir), false);
    assert.equal(await pathExists(paths.smokeOutputDir), false);
    await assertCanonicalSentinels(fixture);
  } finally {
    await fsp.rm(fixture.baseRoot, { recursive: true, force: true });
  }
});

test("owned desktop smoke lifecycle preserves primary and post-cleanup failures", async () => {
  const fixture = await createFixtureRoot();
  const primaryError = new Error("primary smoke failure");
  let removalCalls = 0;
  const removePath = async (targetPath) => {
    removalCalls += 1;
    if (removalCalls > 2) throw new Error(`injected cleanup failure for ${path.basename(targetPath)}`);
    await fsp.rm(targetPath, { recursive: true, force: true });
  };
  try {
    await assert.rejects(
      runWithOwnedPackagedDesktopSmokeCleanup(
        async () => {
          throw primaryError;
        },
        { baseRoot: fixture.baseRoot, removePath },
      ),
      (error) => {
        assert.ok(error instanceof AggregateError);
        assert.equal(error.errors[0], primaryError);
        assert.equal(error.errors.length, 3);
        assert.match(error.errors[1].message, /injected cleanup failure/);
        assert.match(error.errors[2].message, /injected cleanup failure/);
        return true;
      },
    );
  } finally {
    await fsp.rm(fixture.baseRoot, { recursive: true, force: true });
  }
});

test("owned desktop smoke lifecycle fails closed when post-cleanup fails", async () => {
  const fixture = await createFixtureRoot();
  let removalCalls = 0;
  const removePath = async (targetPath) => {
    removalCalls += 1;
    if (removalCalls > 2) throw new Error("injected cleanup-only failure");
    await fsp.rm(targetPath, { recursive: true, force: true });
  };
  try {
    await assert.rejects(
      runWithOwnedPackagedDesktopSmokeCleanup(async () => "ok", { baseRoot: fixture.baseRoot, removePath }),
      (error) => {
        assert.ok(error instanceof AggregateError);
        assert.equal(error.errors.length, 2);
        assert.ok(error.errors.every((cleanupError) => /injected cleanup-only failure/.test(cleanupError.message)));
        return true;
      },
    );
  } finally {
    await fsp.rm(fixture.baseRoot, { recursive: true, force: true });
  }
});

test("desktop smoke cleanup ownership guard accepts only the two exact scratch paths", async () => {
  const fixture = await createFixtureRoot();
  try {
    const paths = resolveOwnedPackagedDesktopSmokePaths(fixture.baseRoot);
    assert.equal(assertOwnedPackagedDesktopSmokePath(paths.smokeStageDir, fixture.baseRoot), paths.smokeStageDir);
    assert.equal(assertOwnedPackagedDesktopSmokePath(paths.smokeOutputDir, fixture.baseRoot), paths.smokeOutputDir);

    for (const rejectedPath of [
      fixture.baseRoot,
      path.join(fixture.baseRoot, "release"),
      path.join(fixture.baseRoot, "release", "staged-app"),
      path.join(fixture.baseRoot, "dist"),
      path.join(fixture.baseRoot, "release", "staged-app-smoke-child"),
      path.join(paths.smokeStageDir, "nested"),
      path.join(paths.smokeStageDir, "..", "staged-app"),
      path.join(os.tmpdir(), "unrelated-desktop-smoke-path"),
    ]) {
      assert.throws(
        () => assertOwnedPackagedDesktopSmokePath(rejectedPath, fixture.baseRoot),
        /Refusing to remove non-owned/,
      );
    }
  } finally {
    await fsp.rm(fixture.baseRoot, { recursive: true, force: true });
  }
});

test("owned desktop smoke cleanup unlinks a symlink or junction without following it", async (t) => {
  const fixture = await createFixtureRoot();
  const paths = resolveOwnedPackagedDesktopSmokePaths(fixture.baseRoot);
  const linkTarget = path.join(fixture.baseRoot, "canonical-link-target");
  const targetSentinel = path.join(linkTarget, "sentinel.txt");
  try {
    await fsp.mkdir(linkTarget, { recursive: true });
    await fsp.writeFile(targetSentinel, "preserve target\n", "utf8");
    try {
      await fsp.symlink(linkTarget, paths.smokeStageDir, process.platform === "win32" ? "junction" : "dir");
    } catch (error) {
      if (["EPERM", "EACCES", "ENOSYS"].includes(error.code)) {
        t.skip(`host does not permit the cleanup link fixture: ${error.code}`);
        return;
      }
      throw error;
    }

    await runWithOwnedPackagedDesktopSmokeCleanup(async () => ({ skipped: true }), {
      baseRoot: fixture.baseRoot,
    });
    assert.equal(await pathExists(paths.smokeStageDir), false);
    assert.equal(await fsp.readFile(targetSentinel, "utf8"), "preserve target\n");
    await assertCanonicalSentinels(fixture);
  } finally {
    await fsp.rm(fixture.baseRoot, { recursive: true, force: true });
  }
});
