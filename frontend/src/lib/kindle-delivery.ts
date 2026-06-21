import type { KindleSendFeedback } from "@/components/book-acquire-notice";

export type KindleDeliveryLight = "none" | "local" | "kindle";

const KINDLE_STATUS_RE = /^kindle_status:\s*(\S+)/im;
const KINDLE_DETAIL_RE = /^kindle_detail:\s*(.+)$/im;

export function parseKindleStatusFromNotes(notes?: string | null): string | null {
  if (!notes) return null;
  const match = notes.match(KINDLE_STATUS_RE);
  return match?.[1]?.trim().toLowerCase() ?? null;
}

export function parseKindleDetailFromNotes(notes?: string | null): string | null {
  if (!notes) return null;
  const match = notes.match(KINDLE_DETAIL_RE);
  return match?.[1]?.trim() ?? null;
}

function isKindleSent(status: string | null | undefined, feedback?: KindleSendFeedback | null): boolean {
  if (feedback?.kindle_status === "sent" || feedback?.kindle_sent) return true;
  return status === "sent";
}

/** Red = nothing local; yellow = cached locally; green = delivered to Kindle. */
export function resolveKindleDeliveryLight(props: {
  hasLocalFile: boolean;
  notes?: string | null;
  session?: KindleSendFeedback | null;
}): KindleDeliveryLight {
  const { hasLocalFile, notes, session } = props;
  const storedStatus = parseKindleStatusFromNotes(notes);
  const status = session?.kindle_status ?? storedStatus;

  if (isKindleSent(status, session)) {
    return "kindle";
  }
  if (hasLocalFile) {
    return "local";
  }
  return "none";
}

export function kindleDeliveryTooltip(
  locale: "zh" | "en",
  light: KindleDeliveryLight,
  detail?: string | null
): string {
  if (light === "kindle") {
    return locale === "zh" ? "已推送到 Kindle" : "Delivered to Kindle";
  }
  if (light === "local") {
    if (detail?.trim()) {
      return locale === "zh" ? `已保存本地；${detail}` : `Saved locally; ${detail}`;
    }
    return locale === "zh" ? "已保存本地，尚未推送到 Kindle" : "Saved locally, not on Kindle yet";
  }
  return locale === "zh" ? "尚无本地文件" : "No local file yet";
}
