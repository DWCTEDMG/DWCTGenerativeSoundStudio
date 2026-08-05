export function normalizeExternalUrl(rawUrl: string): string {
  const candidate = String(rawUrl || "").trim();
  if (!candidate) return "";

  try {
    const parsed = new URL(candidate);
    if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
      return "";
    }

    const normalizedPath =
      parsed.pathname && parsed.pathname !== "/" ? parsed.pathname.replace(/\/+$/, "") : "";

    return `${parsed.origin}${normalizedPath}${parsed.search}${parsed.hash}`;
  } catch {
    return "";
  }
}
