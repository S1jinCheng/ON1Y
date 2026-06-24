import type { Locale } from "@/lib/types";

const LABELS: Record<string, { zh: string; en: string }> = {
  youtube: { zh: "YouTube", en: "YouTube" },
  zhihu: { zh: "知乎", en: "Zhihu" },
  bilibili: { zh: "哔哩哔哩", en: "Bilibili" },
  twitter: { zh: "X", en: "X" },
  obsidian: { zh: "Obsidian", en: "Obsidian" },
  economist: { zh: "经济学人", en: "The Economist" },
  upload: { zh: "上传", en: "Upload" },
  manual: { zh: "手动录入", en: "Manual" }
};

export function platformLabel(platform: string, locale: Locale): string {
  const key = platform.trim().toLowerCase();
  const row = LABELS[key];
  if (row) {
    return locale === "zh" ? row.zh : row.en;
  }
  return platform || (locale === "zh" ? "未知平台" : "Unknown");
}
