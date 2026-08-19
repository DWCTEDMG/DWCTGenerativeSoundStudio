import React, { useState } from "react";
import { Search } from "lucide-react";
import {
  getStudioNavigationGroups,
  preloadNavigationIntent,
  type Page,
  type StudioNavigationGroupId,
} from "../pageRouting";

const DEFAULT_GROUP_STATE: Record<StudioNavigationGroupId, boolean> = {
  flow: true,
  delivery: true,
  labs: false,
  system: false,
};

export default function Sidebar({
  page,
  onNavigate,
  onOpenCommandPalette,
}: {
  page: Page;
  onNavigate: (p: Page) => void;
  onOpenCommandPalette?: () => void;
}) {
  const [openGroups, setOpenGroups] =
    useState<Record<StudioNavigationGroupId, boolean>>(DEFAULT_GROUP_STATE);
  const navGroups = getStudioNavigationGroups();

  const activeItem =
    navGroups.flatMap((group) => group.items).find((item) => item.page === page) || null;

  return (
    <nav className="sidebar" aria-label="Studio screens and tools">
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
        Desktop UI + managed or external backend + internal renderer + optional ComfyUI + AI + EDMG Core
      </div>

      <button
        type="button"
        className="secondary sidebar-commandButton"
        onClick={onOpenCommandPalette}
        aria-label="Search Studio screens and tools"
      >
        <Search size={15} aria-hidden="true" />
        <span>Search Studio</span>
        <kbd>Ctrl/⌘ K</kbd>
      </button>

      <div className="sidebar-focusCard">
        <div className="sidebar-focusLabel">Current focus</div>
        <div className="sidebar-focusValue">{activeItem?.label || "Studio home"}</div>
        <div className="small">{activeItem?.hint || "Use Workspace as the integrated hub."}</div>
      </div>

      <div className="sidebar-nav">
        {navGroups.map((group) => {
          const groupIsActive = group.items.some((item) => item.page === page);
          const isOpen = groupIsActive || openGroups[group.id];

          return (
            <details
              key={group.id}
              className={`sidebar-group${groupIsActive ? " is-active" : ""}`}
              open={isOpen}
              onToggle={(event) => {
                const nextOpen = (event.currentTarget as HTMLDetailsElement).open;
                setOpenGroups((current) => ({ ...current, [group.id]: nextOpen }));
              }}
            >
              <summary className="sidebar-groupSummary">
                <span className="sidebar-groupTitle">{group.label}</span>
                <span className="sidebar-groupMeta">{group.hint}</span>
              </summary>

              <div className="sidebar-groupBody">
                {group.items.map((item) => (
                  <button
                    key={item.page}
                    type="button"
                    onClick={() => onNavigate(item.page)}
                    onMouseEnter={() => preloadNavigationIntent(item.page)}
                    onFocus={() => preloadNavigationIntent(item.page)}
                    className={`sidebar-navButton${page === item.page ? " is-active" : ""}`}
                    aria-current={page === item.page ? "page" : undefined}
                  >
                    <span className="sidebar-navCopy">
                      <span className="sidebar-navText">{item.label}</span>
                      <span className="sidebar-navMeta">{item.hint}</span>
                    </span>
                  </button>
                ))}
              </div>
            </details>
          );
        })}
      </div>

      <div className="sidebar-footer">
        <span className="badge">backend configurable</span>
        <span className="badge">Ollama 11434</span>
        <span className="badge">ComfyUI 8188</span>
      </div>
    </nav>
  );
}
