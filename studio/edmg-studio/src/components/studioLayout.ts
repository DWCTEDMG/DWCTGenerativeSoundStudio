import { useEffect, useMemo, useState } from "react";

export type StudioPageLayoutState<PanelId extends string> = {
  order: PanelId[];
  hidden: PanelId[];
};

export type StudioLayoutControlItem<PanelId extends string> = {
  id: PanelId;
  label: string;
  description: string;
  hidden: boolean;
  canMoveUp: boolean;
  canMoveDown: boolean;
};

function layoutStorageKey(pageKey: string) {
  return `edmg_layout_${pageKey}_v1`;
}

function dedupe<PanelId extends string>(items: PanelId[]) {
  return [...new Set(items)];
}

function normalizeLayoutState<PanelId extends string>(
  panelIds: PanelId[],
  value: Partial<StudioPageLayoutState<PanelId>> | null | undefined,
): StudioPageLayoutState<PanelId> {
  const validPanelIds = new Set(panelIds);
  const order = dedupe(
    Array.isArray(value?.order)
      ? value.order.filter((item): item is PanelId => validPanelIds.has(item as PanelId))
      : [],
  );
  panelIds.forEach((panelId) => {
    if (!order.includes(panelId)) order.push(panelId);
  });

  const hidden = dedupe(
    Array.isArray(value?.hidden)
      ? value.hidden.filter((item): item is PanelId => validPanelIds.has(item as PanelId))
      : [],
  );

  return { order, hidden };
}

function readLayoutState<PanelId extends string>(pageKey: string, panelIds: PanelId[]) {
  try {
    const raw = localStorage.getItem(layoutStorageKey(pageKey));
    if (!raw) return normalizeLayoutState(panelIds, null);
    return normalizeLayoutState(panelIds, JSON.parse(raw));
  } catch {
    return normalizeLayoutState(panelIds, null);
  }
}

function writeLayoutState<PanelId extends string>(pageKey: string, value: StudioPageLayoutState<PanelId>) {
  localStorage.setItem(layoutStorageKey(pageKey), JSON.stringify(value));
}

function movePanelInOrder<PanelId extends string>(order: PanelId[], panelId: PanelId, offset: -1 | 1) {
  const index = order.indexOf(panelId);
  const nextIndex = index + offset;
  if (index < 0 || nextIndex < 0 || nextIndex >= order.length) return order;
  const nextOrder = [...order];
  [nextOrder[index], nextOrder[nextIndex]] = [nextOrder[nextIndex], nextOrder[index]];
  return nextOrder;
}

export function resetStudioPageLayout(pageKey: string) {
  localStorage.removeItem(layoutStorageKey(pageKey));
}

export function useStudioPageLayout<PanelId extends string>(pageKey: string, panelIds: PanelId[]) {
  const panelIdKey = panelIds.join("|");
  const [layoutState, setLayoutState] = useState<StudioPageLayoutState<PanelId>>(() =>
    readLayoutState(pageKey, panelIds),
  );

  useEffect(() => {
    setLayoutState((current) => normalizeLayoutState(panelIds, current));
  }, [pageKey, panelIdKey]);

  useEffect(() => {
    writeLayoutState(pageKey, layoutState);
  }, [layoutState, pageKey]);

  useEffect(() => {
    const onStorage = (event: StorageEvent) => {
      if (event.key === layoutStorageKey(pageKey)) {
        setLayoutState(readLayoutState(pageKey, panelIds));
      }
    };
    window.addEventListener("storage", onStorage);
    return () => window.removeEventListener("storage", onStorage);
  }, [pageKey, panelIdKey]);

  const hiddenSet = useMemo(() => new Set(layoutState.hidden), [layoutState.hidden]);
  const visibleOrder = useMemo(
    () => layoutState.order.filter((panelId) => !hiddenSet.has(panelId)),
    [hiddenSet, layoutState.order],
  );

  const controlItems = useMemo<StudioLayoutControlItem<PanelId>[]>(
    () =>
      layoutState.order.map((panelId, index) => ({
        id: panelId,
        label: panelId,
        description: "",
        hidden: hiddenSet.has(panelId),
        canMoveUp: index > 0,
        canMoveDown: index < layoutState.order.length - 1,
      })),
    [hiddenSet, layoutState.order],
  );

  const updateHidden = (panelId: PanelId, hidden: boolean) => {
    setLayoutState((current) => {
      const nextHidden = new Set(current.hidden);
      if (hidden) nextHidden.add(panelId);
      else nextHidden.delete(panelId);
      return normalizeLayoutState(panelIds, {
        order: current.order,
        hidden: [...nextHidden],
      });
    });
  };

  const movePanel = (panelId: PanelId, offset: -1 | 1) => {
    setLayoutState((current) =>
      normalizeLayoutState(panelIds, {
        order: movePanelInOrder(current.order, panelId, offset),
        hidden: current.hidden,
      }),
    );
  };

  const resetLayout = () => {
    const nextState = normalizeLayoutState(panelIds, null);
    setLayoutState(nextState);
    resetStudioPageLayout(pageKey);
  };

  return {
    layoutState,
    visibleOrder,
    hiddenSet,
    controlItems,
    movePanel,
    updateHidden,
    resetLayout,
  };
}
