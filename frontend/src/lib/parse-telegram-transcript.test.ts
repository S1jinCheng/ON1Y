import { describe, expect, it } from "vitest";

import { parseTelegramTranscript } from "@/lib/parse-telegram-transcript";

describe("parseTelegramTranscript", () => {
  it("parses line-oriented telegram body text", () => {
    const body = "[07-01 14:30] Alice：你好\n[07-01 14:31] 我：在的";
    const rows = parseTelegramTranscript(body);
    expect(rows).toHaveLength(2);
    expect(rows[0]).toMatchObject({
      sender: "Alice",
      time: "07-01 14:30",
      text: "你好",
      isSelf: false
    });
    expect(rows[1]).toMatchObject({
      sender: "我",
      time: "07-01 14:31",
      text: "在的",
      isSelf: true
    });
  });

  it("prefers structured messages when provided", () => {
    const rows = parseTelegramTranscript("", [
      { sender: "Bob", time: "07-02 09:00", text: "ping", is_self: false }
    ]);
    expect(rows).toEqual([
      { sender: "Bob", time: "07-02 09:00", text: "ping", isSelf: false }
    ]);
  });
});
