"use client";

import { useState } from "react";

import { platformLabel } from "@/lib/platform-label";
import type { CreatorRow, Locale } from "@/lib/types";

type CreatorSidebarProps = {
  locale: Locale;
  creators: CreatorRow[];
  selectedCreatorKey?: string;
  onSelectAll: () => void;
  onSelectCreator: (key: string) => void;
  labels: {
    creators: string;
    allCreators: string;
    empty: string;
  };
};

function CreatorAvatar(props: { name: string; avatar?: string | null }): JSX.Element {
  const name = props.name.trim() || "?";
  const [failed, setFailed] = useState(false);
  const avatar = props.avatar?.trim();
  if (avatar && !failed) {
    return (
      <img
        src={avatar}
        alt=""
        className="h-7 w-7 shrink-0 rounded-full object-cover bg-neutral-100"
        referrerPolicy="no-referrer"
        onError={() => setFailed(true)}
      />
    );
  }
  return (
    <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-neutral-200 text-xs font-medium text-neutral-600">
      {name.slice(0, 1).toUpperCase()}
    </div>
  );
}

export function CreatorSidebar(props: CreatorSidebarProps): JSX.Element {
  const { locale, creators, selectedCreatorKey, onSelectAll, onSelectCreator, labels } = props;

  return (
    <div>
      <h2 className="mb-2 text-xs font-medium uppercase tracking-wider text-muted">
        {labels.creators}
      </h2>
      <button
        type="button"
        onClick={onSelectAll}
        className={`mb-1 w-full rounded-md px-2 py-1.5 text-left text-sm transition-colors ${
          !selectedCreatorKey
            ? "bg-soft font-medium text-black"
            : "text-neutral-700 hover:bg-neutral-50"
        }`}
      >
        {labels.allCreators}
      </button>
      {creators.length === 0 ? (
        <p className="px-2 py-3 text-xs text-muted">{labels.empty}</p>
      ) : (
        <ul className="space-y-0.5">
          {creators.map((creator) => {
            const active = selectedCreatorKey === creator.key;
            return (
              <li key={creator.key}>
                <button
                  type="button"
                  onClick={() => onSelectCreator(creator.key)}
                  className={`flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left transition-colors ${
                    active
                      ? "bg-soft font-medium text-black"
                      : "text-neutral-700 hover:bg-neutral-50"
                  }`}
                >
                  <CreatorAvatar name={creator.name} avatar={creator.author_avatar} />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-sm leading-tight">{creator.name}</span>
                    <span className="block truncate text-[10px] text-muted">
                      {platformLabel(creator.platform, locale)}
                    </span>
                  </span>
                  <span className="shrink-0 text-xs tabular-nums text-muted">
                    {creator.item_count}
                  </span>
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
