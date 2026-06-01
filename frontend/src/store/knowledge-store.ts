"use client";

import { create } from "zustand";

import type { Locale } from "@/lib/types";

export const ALL_FILTER = "all";

type FilterState = {
  locale: Locale;
  selectedThemeId?: number;
  selectedTagId?: number;
  query: string;
  platform: string;
  source: string;
  setLocale: (locale: Locale) => void;
  setTheme: (id?: number) => void;
  setTag: (id?: number) => void;
  setQuery: (value: string) => void;
  setPlatform: (value: string) => void;
  setSource: (value: string) => void;
};

export const useKnowledgeFilterStore = create<FilterState>((set) => ({
  locale: "zh",
  selectedThemeId: undefined,
  selectedTagId: undefined,
  query: "",
  platform: ALL_FILTER,
  source: ALL_FILTER,
  setLocale: (locale: Locale) => set({ locale }),
  setTheme: (id?: number) => set({ selectedThemeId: id }),
  setTag: (id?: number) => set({ selectedTagId: id }),
  setQuery: (value: string) => set({ query: value }),
  setPlatform: (value: string) => set({ platform: value }),
  setSource: (value: string) => set({ source: value })
}));
