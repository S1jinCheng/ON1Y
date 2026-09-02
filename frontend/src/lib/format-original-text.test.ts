import { describe, expect, it } from "vitest";

import { formatMarkdownForReading, formatOriginalText } from "@/lib/format-original-text";

describe("subtitle readability formatting", () => {
  it("removes spaces between Chinese subtitle chunks and restores sentence punctuation", () => {
    const raw = [
      "## 字幕",
      "大家 好",
      "你们 好吗"
    ].join("\n");

    expect(formatOriginalText(raw, { locale: "zh" })).toContain("大家好，你们好吗？");
  });

  it("uses the cleaned subtitle text in Markdown mode", () => {
    const raw = [
      "# 示例视频",
      "",
      "## 字幕",
      "这是 一段 没有 标点 的字幕"
    ].join("\n");

    expect(formatMarkdownForReading(raw, { locale: "zh" })).toBe(
      "# 示例视频\n\n## 字幕\n\n这是一段没有标点的字幕。"
    );
  });
});
