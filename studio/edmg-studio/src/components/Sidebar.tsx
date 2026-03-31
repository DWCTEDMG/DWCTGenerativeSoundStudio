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
      <div className="sidebar-brandBlock">
        <div className="sidebar-logoShell">
          <img
            src="studio-logo.png"
            alt="EDMG Studio logo"
            className="sidebar-logo"
          />
        </div>
        <div className="sidebar-brandText">
          <div className="sidebar-eyebrow">Studio Control</div>
          <div className="sidebar-brand">EDMG Studio</div>
        </div>
      </div>
      <div className="small sidebar-tagline">
        Desktop UI + local backend + ComfyUI + AI + EDMG Core
      </div>

      <div className="sidebar-nav">
        {items.map(([k, label]) => (
          <button
            key={k}
            onClick={() => onNavigate(k)}
            className={`sidebar-navButton${page === k ? " is-active" : ""}`}
          >
            {label}
          </button>
        ))}
      </div>

      <div className="sidebar-footer">
        <span className="badge">backend 7863</span>
        <span className="badge">Ollama 11434</span>
        <span className="badge">ComfyUI 8188</span>
      </div>
    </div>
  );
}
