"use client";

import { create } from "zustand";

import {
  DEFAULT_SORT_MODE,
  loadSortMode,
  persistSortMode,
  type SortMode
} from "@/lib/sort-knowledge-items";
import type { Locale } from "@/lib/types";

export const ALL_FILTER = "all";

export type KnowledgeCollection = "feed" | "favorites" | "trash" | "hotlist";

type FilterState = {
  locale: Locale;
  selectedThemeId?: number;
  selectedTagId?: number;
  query: string;
  platform: string;
  source: string;
  collection: KnowledgeCollection;
  sortMode: SortMode;
  setLocale: (locale: Locale) => void;
  setTheme: (id?: number) => void;
  setTag: (id?: number) => void;
  setQuery: (value: string) => void;
  setPlatform: (value: string) => void;
  setSource: (value: string) => void;
  setCollection: (collection: KnowledgeCollection) => void;
  setSortMode: (mode: SortMode) => void;
};

export const useKnowledgeFilterStore = create<FilterState>((set) => ({
  locale: "zh",
  selectedThemeId: undefined,
  selectedTagId: undefined,
  query: "",
  platform: ALL_FILTER,
  source: ALL_FILTER,
  collection: "feed",
  sortMode: DEFAULT_SORT_MODE,
  setLocale: (locale: Locale) => set({ locale }),
  setTheme: (id?: number) => set({ selectedThemeId: id }),
  setTag: (id?: number) => set({ selectedTagId: id }),
  setQuery: (value: string) => set({ query: value }),
  setPlatform: (value: string) => set({ platform: value }),
  setSource: (value: string) => set({ source: value }),
  setCollection: (collection: KnowledgeCollection) =>
    set({ collection, selectedThemeId: undefined, selectedTagId: undefined }),
  setSortMode: (sortMode: SortMode) => {
    persistSortMode(sortMode);
    set({ sortMode });
  }
}));

/** Hydrate sort mode from localStorage after client mount. */
export function hydrateKnowledgeSortMode(): void {
  useKnowledgeFilterStore.setState({ sortMode: loadSortMode() });
}
