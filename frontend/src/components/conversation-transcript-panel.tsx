"use client";

import { Maximize2, Minimize2 } from "lucide-react";
import { useMemo } from "react";

import {
  formatBubbleTime,
  layoutChatTranscript,
  mediaBubbleLabel
} from "@/lib/chat-transcript-layout";
import type { Locale } from "@/lib/i18n";
import { parseTelegramTranscript } from "@/lib/parse-telegram-transcript";

type Props = {
  locale: Locale;
  bodyText: string;
  structured?: Array<{
    sender?: string;
    time?: string;
    timestamp?: number;
    text?: string;
    is_self?: boolean;
    kind?: string;
  }> | null;
  emptyLabel: string;
  expandLabel: string;
  collapseLabel: string;
  expanded?: boolean;
  onExpand?: () => void;
  onCollapse?: () => void;
};

export function ConversationTranscriptPanel(props: Props): JSX.Element {
  const {
    locale,
    bodyText,
    structured,
    emptyLabel,
    expandLabel,
    collapseLabel,
    expanded = false,
    onExpand,
    onCollapse
  } = props;

  const messages = useMemo(
    () => parseTelegramTranscript(bodyText, structured),
    [bodyText, structured]
  );

  const isGroupChat = useMemo(() => {
    const senders = new Set(messages.filter((m) => !m.isSelf).map((m) => m.sender));
    return senders.size > 1;
  }, [messages]);

  const blocks = useMemo(
    () => layoutChatTranscript(messages, locale, { isGroupChat }),
    [messages, locale, isGroupChat]
  );

  if (messages.length === 0) {
    return <p className="text-sm text-muted">{emptyLabel}</p>;
  }

  const scrollClass = expanded
    ? "min-h-0 flex-1 overflow-y-auto shadow-inner scrollbar-thin"
    : "max-h-[min(50vh,28rem)] min-h-[10rem] overflow-y-auto scrollbar-thin";

  return (
    <div className={`flex flex-col ${expanded ? "h-full min-h-0 flex-1" : ""}`}>
      <div className="mb-2 flex shrink-0 justify-end">
        {expanded ? (
          <button
            type="button"
            onClick={onCollapse}
            className="inline-flex items-center gap-1 rounded border border-border px-2 py-1 text-xs hover:bg-soft"
            title={collapseLabel}
          >
            <Minimize2 className="h-3.5 w-3.5" />
            {collapseLabel}
          </button>
        ) : onExpand ? (
          <button
            type="button"
            onClick={onExpand}
            className="inline-flex items-center gap-1 rounded border border-border px-2 py-1 text-xs hover:bg-soft"
            title={expandLabel}
          >
            <Maximize2 className="h-3.5 w-3.5" />
            {expandLabel}
          </button>
        ) : null}
      </div>

      <div
        className={`rounded-md border border-border bg-[#efeae2]/40 px-3 py-4 dark:bg-panel/80 ${scrollClass}`}
      >
        <div className="space-y-3">
          {blocks.map((block) => {
            if (block.type === "date") {
              return (
                <div key={block.key} className="flex justify-center py-1">
                  <span className="rounded-full bg-black/5 px-3 py-0.5 text-[11px] text-muted dark:bg-white/10">
                    {block.label}
                  </span>
                </div>
              );
            }

            const tailTime = formatBubbleTime(
              block.messages[block.messages.length - 1]?.time ?? ""
            );

            return (
              <div
                key={block.key}
                className={`flex flex-col ${block.isSelf ? "items-end" : "items-start"}`}
              >
                {block.showSender ? (
                  <span className="mb-1 px-1 text-[11px] font-medium text-sky-700 dark:text-sky-400">
                    {block.sender}
                  </span>
                ) : null}
                <div
                  className={`flex max-w-[min(88%,28rem)] flex-col gap-0.5 ${
                    block.isSelf ? "items-end" : "items-start"
                  }`}
                >
                  {block.messages.map((msg, index) => {
                    const media = mediaBubbleLabel(msg.kind, msg.text, locale);
                    const isLast = index === block.messages.length - 1;
                    const isFirst = index === 0;
                    const isMiddle = !isFirst && !isLast;
                    const radiusSelf = isFirst
                      ? "rounded-2xl rounded-br-md"
                      : isLast
                        ? "rounded-2xl rounded-tr-md"
                        : "rounded-2xl rounded-r-md";
                    const radiusOther = isFirst
                      ? "rounded-2xl rounded-bl-md"
                      : isLast
                        ? "rounded-2xl rounded-tl-md"
                        : "rounded-2xl rounded-l-md";

                    return (
                      <div
                        key={`${msg.time}-${index}`}
                        className={`px-3 py-2 text-sm leading-relaxed shadow-sm ${
                          block.isSelf
                            ? `bg-[#d9fdd3] text-foreground dark:bg-emerald-900/40 ${radiusSelf}`
                            : `bg-white text-foreground dark:bg-surface ${radiusOther}`
                        } ${isMiddle ? "mt-px" : ""}`}
                      >
                        {media.isMedia ? (
                          <span className="inline-flex items-center gap-1.5 text-muted">
                            <span aria-hidden>{media.icon}</span>
                            <span className="text-sm">{media.label}</span>
                          </span>
                        ) : (
                          <span className="whitespace-pre-wrap break-words">{media.label}</span>
                        )}
                      </div>
                    );
                  })}
                  <span className="mt-0.5 px-1 text-[10px] text-muted">{tailTime}</span>
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
