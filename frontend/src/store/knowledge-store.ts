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

export type SidebarMode = "theme" | "creator";

type FilterState = {
  locale: Locale;
  sidebarMode: SidebarMode;
  selectedThemeId?: number;
  selectedCreatorKey?: string;
  selectedTagId?: number;
  query: string;
  platform: string;
  source: string;
  collection: KnowledgeCollection;
  sortMode: SortMode;
  setLocale: (locale: Locale) => void;
  setSidebarMode: (mode: SidebarMode) => void;
  setTheme: (id?: number) => void;
  setCreator: (key?: string) => void;
  selectTheme: (id?: number) => void;
  selectCreator: (key?: string) => void;
  setTag: (id?: number) => void;
  setQuery: (value: string) => void;
  setPlatform: (value: string) => void;
  setSource: (value: string) => void;
  setCollection: (collection: KnowledgeCollection) => void;
  setSortMode: (mode: SortMode) => void;
};

export const useKnowledgeFilterStore = create<FilterState>((set) => ({
  locale: "zh",
  sidebarMode: "theme",
  selectedThemeId: undefined,
  selectedCreatorKey: undefined,
  selectedTagId: undefined,
  query: "",
  platform: ALL_FILTER,
  source: ALL_FILTER,
  collection: "feed",
  sortMode: DEFAULT_SORT_MODE,
  setLocale: (locale: Locale) => set({ locale }),
  setSidebarMode: (sidebarMode: SidebarMode) =>
    set((state) =>
      sidebarMode === "theme"
        ? { sidebarMode, selectedCreatorKey: undefined }
        : { sidebarMode, selectedThemeId: undefined }
    ),
  setTheme: (id?: number) =>
    set({ selectedThemeId: id, selectedCreatorKey: undefined }),
  setCreator: (key?: string) =>
    set({ selectedCreatorKey: key, selectedThemeId: undefined }),
  selectTheme: (id?: number) =>
    set({
      collection: "feed",
      selectedThemeId: id,
      selectedCreatorKey: undefined
    }),
  selectCreator: (key?: string) =>
    set((state) => ({
      collection: "feed",
      selectedCreatorKey: key,
      selectedThemeId: undefined,
      sortMode:
        state.sortMode === "hot_rank_asc" ? "published_desc" : state.sortMode
    })),
  setTag: (id?: number) => set({ selectedTagId: id }),
  setQuery: (value: string) => set({ query: value }),
  setPlatform: (value: string) => set({ platform: value }),
  setSource: (value: string) => set({ source: value }),
  setCollection: (collection: KnowledgeCollection) =>
    set({
      collection,
      selectedThemeId: undefined,
      selectedCreatorKey: undefined,
      selectedTagId: undefined
    }),
  setSortMode: (sortMode: SortMode) => {
    persistSortMode(sortMode);
    set({ sortMode });
  }
}));

/** Hydrate sort mode from localStorage after client mount. */
export function hydrateKnowledgeSortMode(): void {
  useKnowledgeFilterStore.setState({ sortMode: loadSortMode() });
}
