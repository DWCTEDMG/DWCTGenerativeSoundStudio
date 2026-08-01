import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import {
  normalizeSha1Thumbprint,
  parseBooleanSetting,
  resolveWindowsSigningPlan,
} from "./windows-signing-lib.mjs";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const studioRoot = path.resolve(__dirname, "..");

test("Windows signing settings normalize strict booleans and SHA1 thumbprints", () => {
  assert.equal(parseBooleanSetting("yes", "TEST"), true);
  assert.equal(parseBooleanSetting("off", "TEST"), false);
  assert.throws(() => parseBooleanSetting("sometimes", "TEST"), /TEST must be one of/);
  assert.equal(
    normalizeSha1Thumbprint("0123 4567 89ab cdef 0123 4567 89ab cdef 0123 4567"),
    "0123456789ABCDEF0123456789ABCDEF01234567",
  );
});

test("PFX configuration maps custom EDMG secrets into electron-builder without putting the password in arguments", () => {
  const tempRoot = fs.mkdtempSync(path.join(os.tmpdir(), "edmg-signing-plan-"));
  const certificatePath = path.join(tempRoot, "release-signing.pfx");
  fs.writeFileSync(certificatePath, "test fixture only");
  try {
    const plan = resolveWindowsSigningPlan({
      root: tempRoot,
      builderArgs: ["-w", "--x64"],
      platform: "win32",
      env: {
        EDMG_CODE_SIGN_CERT: certificatePath,
        EDMG_CODE_SIGN_PASSWORD: "do-not-log-this",
        EDMG_REQUIRE_CODE_SIGNING: "1",
        EDMG_CODE_SIGN_TIMESTAMP_URL: "https://timestamp.example.test",
      },
    });
    assert.equal(plan.windowsTarget, true);
    assert.equal(plan.required, true);
    assert.equal(plan.certificateKind, "pfx");
    assert.equal(plan.childEnv.CSC_LINK, certificatePath);
    assert.equal(plan.childEnv.CSC_KEY_PASSWORD, "do-not-log-this");
    assert.ok(plan.builderArgs.includes("-c.forceCodeSigning=true"));
    assert.ok(
      plan.builderArgs.includes(
        "-c.win.signtoolOptions.rfc3161TimeStampServer=https://timestamp.example.test",
      ),
    );
    assert.doesNotMatch(plan.builderArgs.join(" "), /do-not-log-this/);
  } finally {
    fs.rmSync(tempRoot, { recursive: true, force: true });
  }
});

test("certificate thumbprints map into native electron-builder SignTool options", () => {
  const thumbprint = "0123456789ABCDEF0123456789ABCDEF01234567";
  const plan = resolveWindowsSigningPlan({
    root: studioRoot,
    builderArgs: ["--dir", "--x64"],
    platform: "win32",
    env: { EDMG_CODE_SIGN_CERT: thumbprint, EDMG_REQUIRE_CODE_SIGNING: "true" },
  });
  assert.equal(plan.certificateKind, "thumbprint");
  assert.ok(plan.builderArgs.includes(`-c.win.signtoolOptions.certificateSha1=${thumbprint}`));
  assert.ok(plan.builderArgs.includes("-c.forceCodeSigning=true"));
});

test("required Windows signing fails closed without the custom certificate reference", () => {
  assert.throws(
    () =>
      resolveWindowsSigningPlan({
        root: studioRoot,
        builderArgs: ["-w"],
        platform: "win32",
        env: { EDMG_REQUIRE_CODE_SIGNING: "1" },
      }),
    /EDMG_CODE_SIGN_CERT is not configured/,
  );
});

test("Linux targets are not mutated by Windows signing configuration", () => {
  const args = ["-l", "AppImage", "--x64"];
  const plan = resolveWindowsSigningPlan({
    root: studioRoot,
    builderArgs: args,
    platform: "linux",
    env: {
      EDMG_CODE_SIGN_CERT: "C:\\certificate-that-exists-only-on-the-windows-signing-host.pfx",
      EDMG_REQUIRE_CODE_SIGNING: "1",
    },
  });
  assert.equal(plan.windowsTarget, false);
  assert.equal(plan.configured, false);
  assert.deepEqual(plan.builderArgs, args);
});

test("PowerShell signing lane performs real signing, dual verification, and evidence recording", () => {
  const signScript = fs.readFileSync(
    path.join(studioRoot, "packaging", "windows", "sign_release.ps1"),
    "utf8",
  );
  assert.match(signScript, /Join-Path \$PSHOME "Modules\\Microsoft\.PowerShell\.Security/);
  assert.match(signScript, /Import-Module -Name \$securityModule -Force/);
  assert.match(signScript, /Get-AuthenticodeSignature/);
  assert.match(signScript, /"sign", "\/fd", "SHA256"/);
  assert.match(signScript, /"verify", "\/pa", "\/all", "\/tw", "\/v"/);
  assert.match(signScript, /windows-signatures\.json/);
  assert.match(signScript, /Windows Kits\\10\\bin/);
  assert.match(signScript, /EDMG_REQUIRE_CODE_SIGNING/);
  assert.doesNotMatch(signScript, /Would sign|Stub only/);
});
