const WEB_PROTOCOLS = new Set(["http:", "https:"]);

function parseUrl(rawUrl) {
  const candidate = String(rawUrl || "").trim();
  if (!candidate) return null;
  try {
    return new URL(candidate);
  } catch {
    return null;
  }
}

export function normalizeExternalUrl(rawUrl) {
  const parsed = parseUrl(rawUrl);
  if (!parsed || !WEB_PROTOCOLS.has(parsed.protocol)) {
    return "";
  }

  const normalizedPath =
    parsed.pathname && parsed.pathname !== "/" ? parsed.pathname.replace(/\/+$/, "") : "";
  return `${parsed.origin}${normalizedPath}${parsed.search}${parsed.hash}`;
}

export function canNavigateWithinApp(targetUrl, currentUrl, { testMode = false } = {}) {
  const target = parseUrl(targetUrl);
  if (!target) return false;

  if (target.protocol === "file:") {
    return true;
  }

  if (testMode && (target.protocol === "data:" || target.protocol === "about:")) {
    return true;
  }

  if (!WEB_PROTOCOLS.has(target.protocol)) {
    return false;
  }

  const current = parseUrl(currentUrl);
  if (!current || !WEB_PROTOCOLS.has(current.protocol)) {
    return false;
  }

  return current.origin === target.origin;
}

export function assertTrustedRendererIpc(event, channel, { devServerUrl = "", testMode = false } = {}) {
  const senderUrl = String(event?.senderFrame?.url || event?.sender?.getURL?.() || "").trim();
  const parsedSender = parseUrl(senderUrl);
  if (!parsedSender) {
    throw new Error(`Blocked ${channel}: missing renderer URL`);
  }

  if (parsedSender.protocol === "file:") {
    return senderUrl;
  }

  if (testMode && (parsedSender.protocol === "data:" || parsedSender.protocol === "about:")) {
    return senderUrl;
  }

  if (WEB_PROTOCOLS.has(parsedSender.protocol)) {
    const parsedDevServer = parseUrl(devServerUrl);
    if (parsedDevServer && WEB_PROTOCOLS.has(parsedDevServer.protocol)) {
      if (parsedDevServer.origin === parsedSender.origin) {
        return senderUrl;
      }
    }
  }

  throw new Error(`Blocked ${channel} from untrusted renderer: ${senderUrl}`);
}
