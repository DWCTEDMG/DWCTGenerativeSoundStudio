import React from "react";

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
  onMove: (panelId: PanelId, offset: -1 | 1) => void;
  onToggleHidden: (panelId: PanelId, hidden: boolean) => void;
  onReset: () => void;
}) {
  const { title, description, items, onMove, onToggleHidden, onReset } = props;

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
          <button className="secondary" onClick={onReset}>
            Reset layout
          </button>
          <div className="small">
            Frontend-only customization. Reordering and visibility do not change project, setup, render, or model data.
          </div>
        </div>
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
