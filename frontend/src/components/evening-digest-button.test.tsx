import React from "react";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { DigestBody, looksLikeMarkdownDigest } from "./evening-digest-button";
import type { EveningDigest } from "@/lib/digest-types";

const baseDigest: EveningDigest = {
  digest_date: "2026-06-01",
  generated_at: "2026-06-01T22:00:00Z",
  locale: "zh",
  timezone: "Asia/Shanghai",
  read_at: null,
  llm_summary: null,
  llm_error: null,
  unread: true,
  stats: {
    digest_date: "2026-06-01",
    published_total: 3,
    marked_read: 1,
    notes_saved: 1,
    unread_total: 9,
    by_platform: [],
    by_theme: [],
    highlights: [],
  },
};

describe("looksLikeMarkdownDigest", () => {
  it("detects markdown-style digest text", () => {
    const md = "# 今日晚报 | 2026-06-01\n**一句话总览**\n## 今日Crux\n- **[经济]** 关键变化";
    expect(looksLikeMarkdownDigest(md)).toBe(true);
    expect(looksLikeMarkdownDigest("今天新增 3 条，已读 1 条。")).toBe(false);
  });
});

describe("DigestBody summary rendering", () => {
  const ui = (_key: string): string => "summary";

  it("renders markdown summary with strong text", () => {
    render(
      <DigestBody
        digest={{
          ...baseDigest,
          llm_summary: "# 今日晚报 | 2026-06-01\n**一句话总览**\n- **[时政]** 关键变化",
        }}
        ui={ui as never}
      />
    );
    expect(screen.getByRole("heading", { name: /今日晚报/ })).toBeTruthy();
    expect(screen.getByText("一句话总览").tagName.toLowerCase()).toBe("strong");
  });

  it("keeps plain-text fallback for legacy summaries", () => {
    const { container } = render(
      <DigestBody
        digest={{ ...baseDigest, llm_summary: "旧版纯文本晚报\n第二行内容" }}
        ui={ui as never}
      />
    );
    expect(container.querySelector(".whitespace-pre-wrap")).toBeTruthy();
  });
});
