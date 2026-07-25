import React from "react";
import type { StudioLayoutProfileOption } from "./studioLayout";

export type StudioLayoutCustomizerItem<PanelId extends string> = {
  id: PanelId;
  label: string;
  description: string;
  hidden: boolean;
  canMoveUp: boolean;
  canMoveDown: boolean;
};

export function StudioLayoutCustomizer<PanelId extends string>(props: {
  title: string;
  description: string;
  items: StudioLayoutCustomizerItem<PanelId>[];
  profileOptions?: StudioLayoutProfileOption[];
  activeProfile?: StudioLayoutProfileOption["id"];
  onSelectProfile?: (profileId: StudioLayoutProfileOption["id"]) => void;
  onMove: (panelId: PanelId, offset: -1 | 1) => void;
  onToggleHidden: (panelId: PanelId, hidden: boolean) => void;
  onReset: () => void;
}) {
  const {
    title,
    description,
    items,
    profileOptions,
    activeProfile,
    onSelectProfile,
    onMove,
    onToggleHidden,
    onReset,
  } = props;
  const activeProfileOption = profileOptions?.find((option) => option.id === activeProfile);

  return (
    <details className="card studio-layoutTools">
      <summary className="studio-layoutToolsSummary">
        <div>
          <div className="studio-layoutToolsTitle">{title}</div>
          <div className="small">{description}</div>
        </div>
      </summary>
      <div className="studio-layoutToolsBody">
        <div className="studio-layoutToolsActions">
          {profileOptions?.length && activeProfile && onSelectProfile ? (
            <label className="studio-layoutToolsProfilePicker">
              <span className="small">Layout profile</span>
              <select
                aria-label={`${title} profile`}
                value={activeProfile}
                onChange={(event) => onSelectProfile(event.target.value as StudioLayoutProfileOption["id"])}
              >
                {profileOptions.map((option) => (
                  <option key={option.id} value={option.id}>
                    {option.label}
                  </option>
                ))}
              </select>
            </label>
          ) : null}
          <button className="secondary" onClick={onReset}>
            Reset layout
          </button>
          <div className="small">
            Frontend-only customization. Reordering and visibility do not change project, setup, render, or model data.
          </div>
        </div>
        {activeProfileOption ? (
          <div className="small" style={{ marginTop: -4 }}>
            {activeProfileOption.description}
          </div>
        ) : null}
        <div className="studio-layoutToolsGrid">
          {items.map((item) => (
            <div key={item.id} className="studio-layoutToolsItem">
              <div className="studio-layoutToolsItemCopy">
                <div style={{ fontWeight: 800 }}>{item.label}</div>
                <div className="small">{item.description}</div>
              </div>
              <div className="studio-layoutToolsItemActions">
                <button
                  className="secondary"
                  disabled={!item.canMoveUp}
                  onClick={() => onMove(item.id, -1)}
                >
                  Move up
                </button>
                <button
                  className="secondary"
                  disabled={!item.canMoveDown}
                  onClick={() => onMove(item.id, 1)}
                >
                  Move down
                </button>
                <button
                  className="secondary"
                  onClick={() => onToggleHidden(item.id, !item.hidden)}
                >
                  {item.hidden ? "Show" : "Hide"}
                </button>
              </div>
            </div>
          ))}
        </div>
      </div>
    </details>
  );
}
