import React from "react";

export type Page =
  | "dashboard"
  | "projects"
  | "workspace"
  | "timeline"
  | "render"
  | "queue"
  | "outputs"
  | "cloud"
  | "settings"
  | "setup"
  | "models";

export default function Sidebar({
  page,
  onNavigate
}: {
  page: Page;
  onNavigate: (p: Page) => void;
}) {
  const items: Array<[Page, string]> = [
    ["dashboard", "Dashboard"],
    ["projects", "Projects"],
    ["workspace", "Workspace"],
    ["timeline", "Timeline"],
    ["render", "Render"],
    ["queue", "Render Queue"],
    ["outputs", "Outputs"],
    ["cloud", "Cloud"],
    ["models", "Models"],
    ["settings", "Settings"],
    ["setup", "Setup"],
  ];

  return (
    <div className="sidebar">
      <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 10, marginBottom: 6 }}>
        <img
          src="/studio-logo.png"
          alt="EDMG Studio logo"
          style={{
            width: "100%",
            maxWidth: 220,
            aspectRatio: "1 / 1",
            objectFit: "contain",
            borderRadius: 24,
            border: "1px solid rgba(70,214,224,0.28)",
            background:
              "radial-gradient(circle at top center, rgba(255,132,52,0.14), transparent 34%), rgba(5,17,19,0.94)",
            boxShadow: "0 18px 40px rgba(0,0,0,0.32), 0 0 0 1px rgba(70,214,224,0.08)",
          }}
        />
        <div style={{ fontSize: 18, fontWeight: 800, textAlign: "center" }}>EDMG Studio</div>
      </div>
      <div className="small" style={{ marginTop: 6, textAlign: "center" }}>
        Desktop UI + local backend + ComfyUI + AI + EDMG Core
      </div>

      <div style={{ marginTop: 14, display: "flex", flexDirection: "column", gap: 8 }}>
        {items.map(([k, label]) => (
          <button
            key={k}
            onClick={() => onNavigate(k)}
            style={{
              textAlign: "left",
              background: page === k ? "#1b1d2b" : "#141623"
            }}
          >
            {label}
          </button>
        ))}
      </div>

      <div className="small" style={{ marginTop: 14 }}>
        backend: 7863 • Ollama: 11434 • ComfyUI: 8188
      </div>
    </div>
  );
}
