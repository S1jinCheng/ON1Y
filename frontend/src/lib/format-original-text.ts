/** Strip VTT noise and format original text for comfortable reading. */

import type { Locale } from "@/lib/types";

const VTT_INLINE_TAG = /<\/?(?:c|\d{2}:\d{2}:\d{2}[.,]\d{3})>/g;
const CUE_TIMESTAMP =
  /(?:\d{1,2}:)?\d{2}:\d{2}[.,]\d{3}\s*-->\s*(?:\d{1,2}:)?\d{2}:\d{2}[.,]\d{3}\s*/g;
const VTT_CUE_LINE =
  /^(?:\d{1,2}:)?\d{2}:\d{2}[.,]\d{3}\s*-->\s*(?:\d{1,2}:)?\d{2}:\d{2}[.,]\d{3}\s*$/;
const META_LINE = /^(WEBVTT|Kind:|Language:|NOTE|STYLE)/i;
const HEADING_LINE = /^#{1,6}\s+/;

export type TranscriptSectionKind = "zh" | "en" | "description" | "other";

type ParsedSection = {
  kind: TranscriptSectionKind;
  heading: string;
  body: string;
};

function decodeHtmlEntities(value: string): string {
  if (typeof document !== "undefined") {
    const el = document.createElement("textarea");
    el.innerHTML = value;
    return el.value;
  }
  return value
    .replace(/&gt;/g, ">")
    .replace(/&lt;/g, "<")
    .replace(/&amp;/g, "&")
    .replace(/&quot;/g, '"');
}

function classifySectionHeading(heading: string): TranscriptSectionKind {
  const value = heading.trim();
  if (value.includes("字幕")) {
    return "zh";
  }
  if (/subtitle|transcript|english/i.test(value)) {
    return "en";
  }
  if (/description/i.test(value)) {
    return "description";
  }
  return "other";
}

export function normalizeSectionBoundaries(text: string): string {
  return text
    .replace(/\s*(## Subtitle \(English\))/gi, "\n\n$1\n\n")
    .replace(/\s*(## 字幕[^\n]*)/g, "\n\n$1\n\n")
    .replace(/\s+(## Subtitle)(?!\s*\(English\))/gi, "\n\n$1\n\n")
    .replace(/\s+(## Transcript\b)/gi, "\n\n$1\n\n")
    .replace(/\s+(## Description\b)/gi, "\n\n$1\n\n")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

export function parseBodySections(raw: string): { title: string; sections: ParsedSection[] } {
  const text = normalizeSectionBoundaries(raw ?? "");
  if (!text) {
    return { title: "", sections: [] };
  }

  let title = "";
  const sections: ParsedSection[] = [];
  let currentHeading = "";
  let currentLines: string[] = [];

  function flush(): void {
    const body = currentLines.join("\n").trim();
    if (!currentHeading && !body) {
      currentLines = [];
      return;
    }
    sections.push({
      kind: currentHeading ? classifySectionHeading(currentHeading) : "other",
      heading: currentHeading,
      body
    });
    currentHeading = "";
    currentLines = [];
  }

  for (const line of text.split(/\r?\n/)) {
    if (/^#\s+/.test(line) && !/^##\s+/.test(line)) {
      flush();
      title = line.replace(/^#\s+/, "").trim();
      continue;
    }
    if (/^##\s+/.test(line)) {
      flush();
      currentHeading = line.replace(/^##\s+/, "").trim();
      continue;
    }
    currentLines.push(line);
  }
  flush();

  if (sections.length === 0 && text) {
    sections.push({ kind: "other", heading: "", body: text });
  }

  return { title, sections };
}

function findSection(sections: ParsedSection[], kind: TranscriptSectionKind): ParsedSection | undefined {
  return sections.find((section) => section.kind === kind);
}

function assembleSection(title: string, section: ParsedSection): string {
  const parts: string[] = [];
  if (title) {
    parts.push(`# ${title}`);
  }
  if (section.heading) {
    parts.push(`## ${section.heading}`);
  }
  if (section.body) {
    parts.push(section.body);
  }
  return parts.join("\n\n").trim();
}

/** Pick one transcript version for the active UI locale. */
export function pickLocaleTranscript(
  raw: string,
  locale: Locale,
  translatedBodyText?: string | null
): { text: string; kind: TranscriptSectionKind | "none" } {
  const { title, sections } = parseBodySections(raw);
  const zh = findSection(sections, "zh");
  const en = findSection(sections, "en");
  const description = findSection(sections, "description");
  const translated = (translatedBodyText ?? "").trim();

  if (locale === "zh") {
    if (zh?.body) {
      return { text: assembleSection(title, zh), kind: "zh" };
    }
    if (translated) {
      return { text: translated, kind: "zh" };
    }
    if (en?.body) {
      return { text: assembleSection(title, en), kind: "en" };
    }
    if (description?.body) {
      return { text: assembleSection(title, description), kind: "none" };
    }
  } else {
    if (en?.body) {
      return { text: assembleSection(title, en), kind: "en" };
    }
    if (zh?.body) {
      return { text: assembleSection(title, zh), kind: "zh" };
    }
    if (description?.body) {
      return { text: assembleSection(title, description), kind: "none" };
    }
  }

  const fallback = sections.find((section) => section.body.trim());
  if (fallback) {
    return { text: assembleSection(title, fallback), kind: fallback.kind };
  }
  return { text: raw.trim(), kind: "other" };
}

function isSubtitleDump(text: string): boolean {
  return (
    text.includes("WEBVTT") ||
    /<\d{2}:\d{2}:\d{2}[.,]\d{3}>/.test(text) ||
    /\d{2}:\d{2}:\d{2}[.,]\d{3}\s*-->\s*\d{2}:\d{2}:\d{2}[.,]\d{3}/.test(text) ||
    text.includes("## 字幕") ||
    text.includes("## Subtitle") ||
    text.includes("## Transcript") ||
    /^Kind:\s*captions/m.test(text)
  );
}

function stripVttNoise(line: string): string {
  return decodeHtmlEntities(
    line.replace(VTT_INLINE_TAG, "").replace(CUE_TIMESTAMP, "").replace(/\s+/g, " ").trim()
  );
}

function dedupeLines(lines: string[]): string[] {
  const out: string[] = [];
  for (const line of lines) {
    if (out.length === 0 || out[out.length - 1] !== line) {
      out.push(line);
    }
  }
  return out;
}

function cleanSubtitleLines(raw: string): string[] {
  const cleaned: string[] = [];
  for (const rawLine of raw.split(/\r?\n/)) {
    const line = stripVttNoise(rawLine);
    if (!line || META_LINE.test(line) || VTT_CUE_LINE.test(line)) {
      continue;
    }
    cleaned.push(line);
  }
  return dedupeLines(cleaned);
}

function restoreSubtitlePunctuation(line: string, nextLine?: string): string {
  const value = line.trim();
  if (!value || /[。！？.!?…；;：:]$/.test(value)) {
    return value;
  }
  if (/[吗呢]$/.test(value) || /^(?:为什么|怎么|如何|是否|是不是|难道)/.test(value)) {
    return value + "？";
  }
  if (/[啊呀哇]$/.test(value)) {
    return value + "！";
  }
  if (/(?:因为|如果|虽然|但是|不过|所以|因此|然后|而且|以及|当|让|把|被|对|从|在|和|与)$/.test(value)) {
    return value + "，";
  }
  const next = (nextLine || "").trim();
  if (next && /^(?:所以|因此|但是|不过|然后|而且|以及|这|那|它|我们|你们|他们|如果|虽然)/.test(next)) {
    return value + "，";
  }
  if (/[\u4e00-\u9fff]/.test(value)) {
    return value + "。";
  }
  return value;
}

function normalizeSubtitleSpacing(line: string): string {
  return line
    .replace(/([\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])/g, "$1")
    .replace(/\s+([，。！？；：、）】》」』])/g, "$1")
    .replace(/([（【《「『])\s+/g, "$1")
    .replace(/\s{2,}/g, " ")
    .trim();
}

function groupLinesIntoParagraphs(lines: string[]): string[] {
  const paragraphs: string[] = [];
  let buffer = "";

  function flush(): void {
    const value = restoreSubtitlePunctuation(
      normalizeSubtitleSpacing(buffer).replace(
        /([，。！？；：、])\s+(?=[\u4e00-\u9fff])/g,
        "$1"
      )
    );
    if (value) {
      paragraphs.push(value);
    }
    buffer = "";
  }

  for (let index = 0; index < lines.length; index += 1) {
    const line = restoreSubtitlePunctuation(
      normalizeSubtitleSpacing(lines[index]),
      normalizeSubtitleSpacing(lines[index + 1] || "")
    );
    if (HEADING_LINE.test(line)) {
      flush();
      paragraphs.push(line);
      continue;
    }
    buffer += buffer ? ` ${line}` : line;
    if (/[。！？.!?…]$/.test(line) || buffer.length >= 160) {
      flush();
    }
  }
  flush();
  return paragraphs;
}

/** Return readable Markdown while preserving headings and normal Markdown blocks. */
export function formatMarkdownForReading(
  raw: string | null | undefined,
  options?: { locale?: Locale; translatedBodyText?: string | null }
): string {
  const locale = options?.locale ?? "zh";
  const picked = pickLocaleTranscript(raw ?? "", locale, options?.translatedBodyText);
  return picked.text.trim() ? proseFromSection(picked.text) : "";
}

function proseFromSection(text: string): string {
  const { title, sections } = parseBodySections(text);
  const proseParts: string[] = [];
  if (title) {
    proseParts.push(`# ${title}`);
  }
  for (const section of sections) {
    if (section.heading) {
      proseParts.push(`## ${section.heading}`);
    }
    const body = section.body.trim();
    if (!body) {
      continue;
    }
    if (isSubtitleDump(body) || section.kind === "zh" || section.kind === "en") {
      proseParts.push(groupLinesIntoParagraphs(cleanSubtitleLines(body)).join("\n\n"));
    } else {
      proseParts.push(body.replace(/\n{3,}/g, "\n\n").trim());
    }
  }
  if (proseParts.length === 0) {
    return text.replace(/\r\n/g, "\n").replace(/\n{3,}/g, "\n\n").trim();
  }
  return proseParts.join("\n\n").trim();
}

export function formatOriginalText(
  raw: string | null | undefined,
  options?: { locale?: Locale; translatedBodyText?: string | null }
): string {
  const locale = options?.locale ?? "zh";
  const picked = pickLocaleTranscript(raw ?? "", locale, options?.translatedBodyText);
  if (!picked.text.trim()) {
    return "";
  }
  return proseFromSection(picked.text);
}

export function originalTextToHtml(text: string): string {
  const blocks = text.split(/\n{2,}/).filter(Boolean);
  if (blocks.length === 0) {
    return "";
  }
  return blocks
    .map((block) => {
      if (HEADING_LINE.test(block)) {
        const level = block.match(/^#+/)?.[0].length ?? 2;
        const content = block.replace(/^#+\s*/, "");
        const tag = level <= 1 ? "h2" : level === 2 ? "h3" : "h4";
        return `<${tag} class="original-heading">${escapeHtml(content)}</${tag}>`;
      }
      return `<p class="original-paragraph">${escapeHtml(block).replace(/\n/g, "<br/>")}</p>`;
    })
    .join("");
}

function escapeHtml(value: string): string {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}
