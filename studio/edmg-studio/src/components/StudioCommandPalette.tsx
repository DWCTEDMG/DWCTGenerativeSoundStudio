import React, { useEffect, useMemo, useRef, useState } from "react";
import { ArrowRight, Search, X } from "lucide-react";
import {
  getStudioNavigationGroups,
  preloadNavigationIntent,
  type Page,
  type StudioNavigationItem,
} from "../pageRouting";

type PaletteItem = StudioNavigationItem & { groupLabel: string };

function normalizeSearch(value: string) {
  return value.trim().toLocaleLowerCase();
}

function scoreItem(item: PaletteItem, query: string) {
  if (!query) return 1;
  const label = item.label.toLocaleLowerCase();
  const haystack = [item.label, item.hint, item.groupLabel, ...item.keywords]
    .join(" ")
    .toLocaleLowerCase();
  if (label === query) return 100;
  if (label.startsWith(query)) return 70;
  if (label.includes(query)) return 50;
  if (haystack.includes(query)) return 20;
  const terms = query.split(/\s+/).filter(Boolean);
  return terms.every((term) => haystack.includes(term)) ? 10 : 0;
}

export function StudioCommandPalette({
  open,
  activePage,
  onClose,
  onNavigate,
}: {
  open: boolean;
  activePage: Page;
  onClose: () => void;
  onNavigate: (page: Page) => void;
}) {
  const [query, setQuery] = useState("");
  const [activeIndex, setActiveIndex] = useState(0);
  const inputRef = useRef<HTMLInputElement | null>(null);
  const dialogRef = useRef<HTMLDivElement | null>(null);
  const previouslyFocusedRef = useRef<HTMLElement | null>(null);
  const shouldRestoreFocusRef = useRef(true);

  const items = useMemo<PaletteItem[]>(
    () =>
      getStudioNavigationGroups().flatMap((group) =>
        group.items.map((item) => ({ ...item, groupLabel: group.label })),
      ),
    [],
  );
  const results = useMemo(() => {
    const normalized = normalizeSearch(query);
    return items
      .map((item) => ({ item, score: scoreItem(item, normalized) }))
      .filter((entry) => entry.score > 0)
      .sort((left, right) => right.score - left.score || left.item.label.localeCompare(right.item.label))
      .map((entry) => entry.item);
  }, [items, query]);

  useEffect(() => {
    if (!open) return;
    previouslyFocusedRef.current =
      document.activeElement instanceof HTMLElement ? document.activeElement : null;
    shouldRestoreFocusRef.current = true;
    setQuery("");
    setActiveIndex(0);
    const timer = window.setTimeout(() => inputRef.current?.focus(), 0);
    return () => {
      window.clearTimeout(timer);
      if (shouldRestoreFocusRef.current) previouslyFocusedRef.current?.focus();
      previouslyFocusedRef.current = null;
    };
  }, [open]);

  useEffect(() => {
    setActiveIndex((current) => Math.min(current, Math.max(0, results.length - 1)));
  }, [results.length]);

  if (!open) return null;

  const choose = (page: Page) => {
    shouldRestoreFocusRef.current = false;
    onNavigate(page);
    onClose();
  };

  const keepFocusInDialog = (event: React.KeyboardEvent<HTMLDivElement>) => {
    if (event.key !== "Tab") return;
    const focusable = Array.from(
      dialogRef.current?.querySelectorAll<HTMLElement>(
        'input:not([disabled]), button:not([disabled]), [href], [tabindex]:not([tabindex="-1"])',
      ) ?? [],
    ).filter((element) => element.getAttribute("aria-hidden") !== "true");
    if (!focusable.length) {
      event.preventDefault();
      return;
    }
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    const active = document.activeElement;
    if (event.shiftKey && (active === first || !dialogRef.current?.contains(active))) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && active === last) {
      event.preventDefault();
      first.focus();
    }
  };

  return (
    <div className="studio-commandBackdrop" role="presentation" onMouseDown={onClose}>
      <div
        ref={dialogRef}
        className="studio-commandPalette"
        role="dialog"
        aria-modal="true"
        aria-label="Search Studio screens and tools"
        onMouseDown={(event) => event.stopPropagation()}
        onKeyDown={(event) => {
          keepFocusInDialog(event);
          if (event.defaultPrevented) return;
          if (event.key === "Escape") {
            event.preventDefault();
            onClose();
          } else if (event.key === "ArrowDown") {
            event.preventDefault();
            setActiveIndex((current) => Math.min(results.length - 1, current + 1));
          } else if (event.key === "ArrowUp") {
            event.preventDefault();
            setActiveIndex((current) => Math.max(0, current - 1));
          } else if (event.key === "Enter" && results[activeIndex]) {
            event.preventDefault();
            choose(results[activeIndex].page);
          }
        }}
      >
        <div className="studio-commandSearchRow">
          <Search size={19} aria-hidden="true" />
          <input
            ref={inputRef}
            value={query}
            onChange={(event) => {
              setQuery(event.target.value);
              setActiveIndex(0);
            }}
            aria-label="Search Studio screens and tools"
            placeholder="Find timeline editing, render settings, models, outputs..."
          />
          <button className="secondary studio-commandClose" type="button" onClick={onClose} aria-label="Close Studio search">
            <X size={16} aria-hidden="true" />
          </button>
        </div>
        <div className="studio-commandHint">
          Search by what you want to do. Use ↑ ↓ to choose and Enter to open.
        </div>
        <div className="studio-commandResults" aria-label="Studio screens and tools">
          {results.length ? (
            results.map((item, index) => (
              <button
                key={item.page}
                type="button"
                aria-current={item.page === activePage ? "page" : undefined}
                className={`studio-commandResult${index === activeIndex ? " is-active" : ""}`}
                onMouseEnter={() => {
                  setActiveIndex(index);
                  preloadNavigationIntent(item.page);
                }}
                onFocus={() => setActiveIndex(index)}
                onClick={() => choose(item.page)}
              >
                <span className="studio-commandResultCopy">
                  <span className="studio-commandResultTopline">
                    <strong>{item.label}</strong>
                    {item.page === activePage ? <span className="badge">Current</span> : null}
                  </span>
                  <span>{item.hint}</span>
                  <small>{item.groupLabel}</small>
                </span>
                <ArrowRight size={16} aria-hidden="true" />
              </button>
            ))
          ) : (
            <div className="studio-commandEmpty">
              No matching Studio screen. Try “video edit”, “model”, “render”, or “audio”.
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
