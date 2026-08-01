import fs from "node:fs";
import path from "node:path";

const TRUE_VALUES = new Set(["1", "true", "yes", "on"]);
const FALSE_VALUES = new Set(["", "0", "false", "no", "off"]);

export function parseBooleanSetting(value, name = "value") {
  const normalized = String(value ?? "").trim().toLowerCase();
  if (TRUE_VALUES.has(normalized)) return true;
  if (FALSE_VALUES.has(normalized)) return false;
  throw new Error(`${name} must be one of 1/0, true/false, yes/no, or on/off.`);
}

export function normalizeSha1Thumbprint(value) {
  const normalized = String(value ?? "").replace(/\s+/g, "").toUpperCase();
  return /^[A-F0-9]{40}$/.test(normalized) ? normalized : "";
}

function resolveTimestampUrl(env) {
  const value = String(env.EDMG_CODE_SIGN_TIMESTAMP_URL || "http://timestamp.digicert.com").trim();
  let parsed;
  try {
    parsed = new URL(value);
  } catch {
    throw new Error("EDMG_CODE_SIGN_TIMESTAMP_URL must be an absolute HTTP or HTTPS URL.");
  }
  if (!new Set(["http:", "https:"]).has(parsed.protocol)) {
    throw new Error("EDMG_CODE_SIGN_TIMESTAMP_URL must use HTTP or HTTPS.");
  }
  return value;
}

export function isWindowsBuilderTarget(builderArgs, platform = process.platform) {
  const wantsWindows = builderArgs.some((arg) => /^-w(?:$|in)|^--win/i.test(arg));
  const wantsLinux = builderArgs.some((arg) => /^-l(?:$|inux)|^--linux/i.test(arg));
  if (wantsWindows && wantsLinux) {
    throw new Error("Release packaging must target Windows or Linux, not both in one invocation.");
  }
  return wantsWindows || (platform === "win32" && !wantsLinux);
}

export function resolveCertificateReference(root, value) {
  const reference = String(value ?? "").trim();
  if (!reference) return { kind: "none" };

  const thumbprint = normalizeSha1Thumbprint(reference);
  if (thumbprint) return { kind: "thumbprint", thumbprint };

  const certificatePath = path.isAbsolute(reference) ? path.normalize(reference) : path.resolve(root, reference);
  if (!fs.existsSync(certificatePath) || !fs.statSync(certificatePath).isFile()) {
    throw new Error("EDMG_CODE_SIGN_CERT must be an existing local PFX/P12 file or a SHA1 certificate thumbprint.");
  }
  if (!new Set([".pfx", ".p12"]).has(path.extname(certificatePath).toLowerCase())) {
    throw new Error("EDMG_CODE_SIGN_CERT file references must use the .pfx or .p12 extension.");
  }
  return { kind: "pfx", path: certificatePath };
}

export function resolveWindowsSigningPlan({
  root,
  builderArgs,
  env = process.env,
  platform = process.platform,
}) {
  const windowsTarget = isWindowsBuilderTarget(builderArgs, platform);
  const required = parseBooleanSetting(env.EDMG_REQUIRE_CODE_SIGNING, "EDMG_REQUIRE_CODE_SIGNING");

  if (!windowsTarget) {
    return {
      windowsTarget: false,
      required,
      configured: false,
      certificateKind: "none",
      builderArgs: [...builderArgs],
      childEnv: { ...env },
    };
  }

  const certificate = resolveCertificateReference(root, env.EDMG_CODE_SIGN_CERT);

  if (required && certificate.kind === "none") {
    throw new Error(
      "EDMG_REQUIRE_CODE_SIGNING is enabled, but EDMG_CODE_SIGN_CERT is not configured. " +
        "A PFX/P12 file or Windows certificate thumbprint is required so bundled executables can be signed before packing.",
    );
  }

  const configured = certificate.kind !== "none";
  const nextArgs = [...builderArgs];
  const childEnv = { ...env };

  if (certificate.kind === "pfx") {
    childEnv.EDMG_CODE_SIGN_CERT = certificate.path;
    childEnv.CSC_LINK = certificate.path;
    childEnv.WIN_CSC_LINK = certificate.path;
    const password = String(env.EDMG_CODE_SIGN_PASSWORD ?? "");
    if (password) {
      childEnv.CSC_KEY_PASSWORD = password;
      childEnv.WIN_CSC_KEY_PASSWORD = password;
    }
  } else if (certificate.kind === "thumbprint") {
    nextArgs.push(`-c.win.signtoolOptions.certificateSha1=${certificate.thumbprint}`);
  }

  if (configured || required) {
    const timestampUrl = resolveTimestampUrl(env);
    nextArgs.push(`-c.win.signtoolOptions.rfc3161TimeStampServer=${timestampUrl}`);
    nextArgs.push("-c.forceCodeSigning=true");
  }

  return {
    windowsTarget: true,
    required,
    configured,
    certificateKind: certificate.kind,
    builderArgs: nextArgs,
    childEnv,
  };
}
