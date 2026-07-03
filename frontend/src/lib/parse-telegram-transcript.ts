import type { ChatTranscriptMessage } from "@/lib/chat-transcript-layout";

export type { ChatTranscriptMessage };

const LINE_RE = /^\[([^\]]+)\]\s*(.+?)[：:]\s*(.*)$/u;

type RawTelegramMessage = {
  sender?: string;
  time?: string;
  timestamp?: number;
  text?: string;
  is_self?: boolean;
  kind?: string;
};

function formatTimestamp(ts: number): string {
  const date = new Date(ts * 1000);
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  const hours = String(date.getHours()).padStart(2, "0");
  const minutes = String(date.getMinutes()).padStart(2, "0");
  return `${month}-${day} ${hours}:${minutes}`;
}

export function parseTelegramTranscript(
  bodyText: string,
  structured?: RawTelegramMessage[] | null
): ChatTranscriptMessage[] {
  if (structured?.length) {
    const rows: ChatTranscriptMessage[] = [];
    for (const row of structured) {
      const text = (row.text ?? "").trim();
      if (!text) {
        continue;
      }
      const sender = (row.sender ?? "").trim() || "—";
      const timestamp = typeof row.timestamp === "number" ? row.timestamp : undefined;
      const time =
        (row.time ?? "").trim() ||
        (timestamp ? formatTimestamp(timestamp) : "");
      rows.push({
        sender,
        time,
        text,
        isSelf: Boolean(row.is_self),
        timestamp,
        kind: row.kind
      });
    }
    return rows;
  }

  const messages: ChatTranscriptMessage[] = [];
  for (const line of bodyText.split(/\r?\n/u)) {
    const trimmed = line.trim();
    if (!trimmed) {
      continue;
    }
    const match = LINE_RE.exec(trimmed);
    if (!match) {
      continue;
    }
    const [, time, sender, text] = match;
    if (!text.trim()) {
      continue;
    }
    messages.push({
      sender: sender.trim(),
      time: time.trim(),
      text: text.trim(),
      isSelf: sender.trim() === "我"
    });
  }
  return messages;
}
