import { useEffect, useMemo, useState } from "react";

export type StudioPageLayoutState<PanelId extends string> = {
  order: PanelId[];
  hidden: PanelId[];
};

export type StudioLayoutProfileId = "personal" | "focus" | "technical" | "presentation";

export type StudioLayoutProfileOption<ProfileId extends string = StudioLayoutProfileId> = {
  id: ProfileId;
  label: string;
  description: string;
};

export type StudioLayoutControlItem<PanelId extends string> = {
  id: PanelId;
  label: string;
  description: string;
  hidden: boolean;
  canMoveUp: boolean;
  canMoveDown: boolean;
};

export const STUDIO_LAYOUT_PROFILE_OPTIONS: StudioLayoutProfileOption[] = [
  {
    id: "personal",
    label: "Personal",
    description: "Your main saved layout. Existing page customizations stay here.",
  },
  {
    id: "focus",
    label: "Focus",
    description: "A cleaner secondary view for reduced panel clutter.",
  },
  {
    id: "technical",
    label: "Technical",
    description: "A separate slot for denser inspection and operational layouts.",
  },
  {
    id: "presentation",
    label: "Presentation",
    description: "A simplified slot for showing work or reviewing status.",
  },
];

function layoutStorageKey(pageKey: string) {
  return `edmg_layout_${pageKey}_v1`;
}

function layoutProfileStorageKey(pageKey: string, profileId: string) {
  if (profileId === "personal") return layoutStorageKey(pageKey);
  return `edmg_layout_${pageKey}_${profileId}_v1`;
}

function activeProfileStorageKey(pageKey: string) {
  return `edmg_layout_${pageKey}_active_profile_v1`;
}

function layoutStorageKeyPrefix(pageKey: string) {
  return `edmg_layout_${pageKey}_`;
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

function readLayoutState<PanelId extends string>(
  pageKey: string,
  panelIds: PanelId[],
  profileId: string,
) {
  try {
    const raw = localStorage.getItem(layoutProfileStorageKey(pageKey, profileId));
    if (!raw) return normalizeLayoutState(panelIds, null);
    return normalizeLayoutState(panelIds, JSON.parse(raw));
  } catch {
    return normalizeLayoutState(panelIds, null);
  }
}

function writeLayoutState<PanelId extends string>(
  pageKey: string,
  profileId: string,
  value: StudioPageLayoutState<PanelId>,
) {
  localStorage.setItem(layoutProfileStorageKey(pageKey, profileId), JSON.stringify(value));
}

function readActiveProfile<ProfileId extends string>(
  pageKey: string,
  profileOptions: StudioLayoutProfileOption<ProfileId>[],
): ProfileId {
  const fallback = profileOptions[0]?.id;
  if (!fallback) {
    throw new Error("Studio layout profiles require at least one profile option.");
  }
  try {
    const raw = localStorage.getItem(activeProfileStorageKey(pageKey));
    if (!raw) return fallback;
    return profileOptions.some((option) => option.id === raw) ? (raw as ProfileId) : fallback;
  } catch {
    return fallback;
  }
}

function writeActiveProfile(pageKey: string, profileId: string) {
  localStorage.setItem(activeProfileStorageKey(pageKey), profileId);
}

function movePanelInOrder<PanelId extends string>(order: PanelId[], panelId: PanelId, offset: -1 | 1) {
  const index = order.indexOf(panelId);
  const nextIndex = index + offset;
  if (index < 0 || nextIndex < 0 || nextIndex >= order.length) return order;
  const nextOrder = [...order];
  [nextOrder[index], nextOrder[nextIndex]] = [nextOrder[nextIndex], nextOrder[index]];
  return nextOrder;
}

export function resetStudioPageLayout(pageKey: string, profileId: string = "personal") {
  localStorage.removeItem(layoutProfileStorageKey(pageKey, profileId));
}

export function useStudioPageLayout<PanelId extends string, ProfileId extends string = StudioLayoutProfileId>(
  pageKey: string,
  panelIds: PanelId[],
  profileOptions: StudioLayoutProfileOption<ProfileId>[] = STUDIO_LAYOUT_PROFILE_OPTIONS as StudioLayoutProfileOption<ProfileId>[],
) {
  const panelIdKey = panelIds.join("|");
  const profileIdKey = profileOptions.map((option) => option.id).join("|");
  const [activeProfile, setActiveProfile] = useState<ProfileId>(() =>
    readActiveProfile(pageKey, profileOptions),
  );
  const [layoutState, setLayoutState] = useState<StudioPageLayoutState<PanelId>>(() =>
    readLayoutState(pageKey, panelIds, readActiveProfile(pageKey, profileOptions)),
  );

  useEffect(() => {
    setLayoutState((current) => normalizeLayoutState(panelIds, current));
  }, [pageKey, panelIdKey]);

  useEffect(() => {
    setActiveProfile((current) => {
      if (profileOptions.some((option) => option.id === current)) return current;
      return readActiveProfile(pageKey, profileOptions);
    });
  }, [pageKey, profileIdKey, profileOptions]);

  useEffect(() => {
    setLayoutState(readLayoutState(pageKey, panelIds, activeProfile));
  }, [activeProfile, pageKey, panelIdKey]);

  useEffect(() => {
    writeLayoutState(pageKey, activeProfile, layoutState);
  }, [activeProfile, layoutState, pageKey]);

  useEffect(() => {
    writeActiveProfile(pageKey, activeProfile);
  }, [activeProfile, pageKey]);

  useEffect(() => {
    const onStorage = (event: StorageEvent) => {
      if (!event.key) return;
      if (
        event.key === activeProfileStorageKey(pageKey) ||
        event.key === layoutStorageKey(pageKey) ||
        event.key.startsWith(layoutStorageKeyPrefix(pageKey))
      ) {
        const nextProfile = readActiveProfile(pageKey, profileOptions);
        setActiveProfile(nextProfile);
        setLayoutState(readLayoutState(pageKey, panelIds, nextProfile));
      }
    };
    window.addEventListener("storage", onStorage);
    return () => window.removeEventListener("storage", onStorage);
  }, [pageKey, panelIdKey, profileIdKey, profileOptions]);

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
    resetStudioPageLayout(pageKey, activeProfile);
  };

  return {
    profileOptions,
    activeProfile,
    setActiveProfile,
    layoutState,
    visibleOrder,
    hiddenSet,
    controlItems,
    movePanel,
    updateHidden,
    resetLayout,
  };
}
