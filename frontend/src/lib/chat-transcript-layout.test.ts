import { describe, expect, it } from "vitest";

import { layoutChatTranscript } from "@/lib/chat-transcript-layout";

describe("layoutChatTranscript", () => {
  it("groups consecutive messages from the same sender", () => {
    const blocks = layoutChatTranscript(
      [
        { sender: "Alice", time: "07-01 14:30", text: "hi", isSelf: false },
        { sender: "Alice", time: "07-01 14:31", text: "there", isSelf: false }
      ],
      "en",
      { isGroupChat: true }
    );
    const groups = blocks.filter((b) => b.type === "group");
    expect(groups).toHaveLength(1);
    expect(groups[0].type === "group" && groups[0].messages).toHaveLength(2);
  });

  it("inserts date dividers when the day changes", () => {
    const blocks = layoutChatTranscript(
      [
        { sender: "Alice", time: "07-01 23:59", text: "a", isSelf: false, timestamp: 1719859140 },
        { sender: "Alice", time: "07-02 00:01", text: "b", isSelf: false, timestamp: 1719864060 }
      ],
      "zh",
      { isGroupChat: false }
    );
    expect(blocks.some((b) => b.type === "date")).toBe(true);
  });
});
