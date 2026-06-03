"use client";

import { FileText, Tv } from "lucide-react";

import { t, type UiKey } from "@/lib/i18n";
import type { Locale } from "@/lib/types";

export type ContentKind = "video" | "text";

export function resolveContentKind(
  contentType?: string | null,
  platform?: string | null
): ContentKind | null {
  const kind = (contentType || "").trim().toLowerCase();
  if (kind === "video") {
    return "video";
  }
  if (kind === "article") {
    return "text";
  }
  const platformKey = (platform || "").trim().toLowerCase();
  if (platformKey === "youtube" || platformKey === "bilibili") {
    return "video";
  }
  if (platformKey === "zhihu" || platformKey === "economist" || platformKey === "manual") {
    return "text";
  }
  return null;
}

export function ContentTypeIndicator(props: {
  contentType?: string | null;
  platform?: string | null;
  locale: Locale;
  className?: string;
}): JSX.Element | null {
  const kind = resolveContentKind(props.contentType, props.platform);
  if (!kind) {
    return null;
  }
  const labelKey: UiKey = kind === "video" ? "contentTypeVideo" : "contentTypeText";
  const label = t(props.locale, labelKey);
  const Icon = kind === "video" ? Tv : FileText;
  return (
    <span
      className={`inline-flex shrink-0 items-center text-neutral-400 ${props.className ?? ""}`}
      title={label}
      aria-label={label}
    >
      <Icon className="h-3.5 w-3.5" strokeWidth={2} />
    </span>
  );
}
