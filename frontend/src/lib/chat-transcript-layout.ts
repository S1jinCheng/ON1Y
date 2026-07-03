import type { Locale } from "@/lib/i18n";

export type ChatTranscriptMessage = {
  sender: string;
  time: string;
  text: string;
  isSelf?: boolean;
  timestamp?: number;
  kind?: string;
};

export type ChatDateDivider = {
  type: "date";
  key: string;
  label: string;
};

export type ChatMessageGroup = {
  type: "group";
  key: string;
  sender: string;
  isSelf: boolean;
  showSender: boolean;
  messages: ChatTranscriptMessage[];
};

export type ChatTranscriptBlock = ChatDateDivider | ChatMessageGroup;

const MEDIA_LABELS: Record<string, { zh: string; en: string; icon: string }> = {
  photo: { zh: "图片", en: "Photo", icon: "🖼" },
  video_file: { zh: "视频", en: "Video", icon: "🎬" },
  video_message: { zh: "视频消息", en: "Video message", icon: "📹" },
  voice_message: { zh: "语音", en: "Voice", icon: "🎤" },
  sticker: { zh: "贴纸", en: "Sticker", icon: "🎭" },
  animation: { zh: "动图", en: "GIF", icon: "✨" },
  file: { zh: "文件", en: "File", icon: "📎" },
  poll: { zh: "投票", en: "Poll", icon: "📊" },
  contact: { zh: "联系人", en: "Contact", icon: "👤" },
  location: { zh: "位置", en: "Location", icon: "📍" }
};

function inferKind(text: string): string {
  const trimmed = text.trim();
  const bracket = trimmed.match(/^\[(.+)\]$/u);
  if (!bracket) {
    return "text";
  }
  const label = bracket[1];
  for (const [kind, meta] of Object.entries(MEDIA_LABELS)) {
    if (label === meta.zh || label === meta.en) {
      return kind;
    }
  }
  return "media";
}

export function normalizeChatMessage(row: ChatTranscriptMessage): ChatTranscriptMessage {
  const kind = row.kind && row.kind !== "text" ? row.kind : inferKind(row.text);
  return { ...row, kind };
}

function dayKey(msg: ChatTranscriptMessage): string {
  if (typeof msg.timestamp === "number" && msg.timestamp > 0) {
    const d = new Date(msg.timestamp * 1000);
    return `${d.getFullYear()}-${d.getMonth()}-${d.getDate()}`;
  }
  const match = msg.time.match(/^(\d{2}-\d{2})/u);
  return match ? match[1] : msg.time.slice(0, 10);
}

function formatDateDivider(msg: ChatTranscriptMessage, locale: Locale): string {
  if (typeof msg.timestamp === "number" && msg.timestamp > 0) {
    return new Date(msg.timestamp * 1000).toLocaleDateString(
      locale === "zh" ? "zh-CN" : "en-US",
      { year: "numeric", month: "long", day: "numeric", weekday: "short" }
    );
  }
  const match = msg.time.match(/^(\d{2})-(\d{2})/u);
  if (match) {
    const year = new Date().getFullYear();
    const month = Number(match[1]);
    const day = Number(match[2]);
    return new Date(year, month - 1, day).toLocaleDateString(
      locale === "zh" ? "zh-CN" : "en-US",
      { month: "long", day: "numeric", weekday: "short" }
    );
  }
  return msg.time;
}

function sameGroup(a: ChatTranscriptMessage, b: ChatTranscriptMessage): boolean {
  return Boolean(a.isSelf) === Boolean(b.isSelf) && a.sender === b.sender;
}

export function layoutChatTranscript(
  messages: ChatTranscriptMessage[],
  locale: Locale,
  options?: { isGroupChat?: boolean }
): ChatTranscriptBlock[] {
  const isGroupChat = options?.isGroupChat ?? false;
  if (messages.length === 0) {
    return [];
  }

  const normalized = messages.map(normalizeChatMessage);
  const blocks: ChatTranscriptBlock[] = [];
  let lastDay = "";
  let group: ChatMessageGroup | null = null;

  function flushGroup(): void {
    if (group) {
      blocks.push(group);
      group = null;
    }
  }

  for (const msg of normalized) {
    const day = dayKey(msg);
    if (day !== lastDay) {
      flushGroup();
      blocks.push({
        type: "date",
        key: `date-${day}`,
        label: formatDateDivider(msg, locale)
      });
      lastDay = day;
    }

    if (group && sameGroup(group.messages[group.messages.length - 1], msg)) {
      group.messages.push(msg);
      continue;
    }

    flushGroup();
    group = {
      type: "group",
      key: `group-${blocks.length}-${msg.time}-${msg.sender}`,
      sender: msg.sender,
      isSelf: Boolean(msg.isSelf),
      showSender: isGroupChat && !msg.isSelf,
      messages: [msg]
    };
  }
  flushGroup();
  return blocks;
}

export function mediaBubbleLabel(
  kind: string | undefined,
  text: string,
  locale: Locale
): { icon: string; label: string; isMedia: boolean } {
  const resolved = kind && kind !== "text" ? kind : inferKind(text);
  if (resolved === "text") {
    return { icon: "", label: text, isMedia: false };
  }
  const meta = MEDIA_LABELS[resolved];
  if (meta) {
    return {
      icon: meta.icon,
      label: locale === "zh" ? meta.zh : meta.en,
      isMedia: true
    };
  }
  return { icon: "📎", label: text, isMedia: true };
}

export function formatBubbleTime(time: string): string {
  const match = time.match(/\d{2}:\d{2}/u);
  return match ? match[0] : time;
}
