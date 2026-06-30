export type EveningDigestHighlight = {
  raw_id: number;
  title: string;
  url?: string;
  platform: string;
  summary: string;
  is_read: boolean;
  image_url?: string;
  theme_slug?: string;
  score?: number;
  timeliness_score?: number;
  impact_score?: number;
};

export type EveningDigestStats = {
  digest_date: string;
  published_total: number;
  marked_read: number;
  notes_saved: number;
  unread_total: number;
  by_platform: Array<{ platform: string; count: number }>;
  by_theme: Array<{ slug: string; name_zh: string; name_en: string; count: number }>;
  highlights: EveningDigestHighlight[];
  selection_meta?: {
    prompt_version?: string;
    focus_slugs?: string[];
    candidate_count?: number;
    focus_candidate_count?: number;
    selected_count?: number;
    focus_quota?: number;
    focus_selected_count?: number;
    focus_backfill?: boolean;
  };
};

export type EveningDigest = {
  digest_date: string;
  generated_at: string;
  prompt_version?: string | null;
  locale: string;
  timezone: string;
  read_at: string | null;
  llm_summary: string | null;
  llm_error: string | null;
  stats: EveningDigestStats;
  unread: boolean;
};

export type EveningDigestPending = {
  pending: true;
  digest_date: string;
  reason: "before_digest_hour" | "not_generated_yet";
  timezone: string;
};

export type EveningDigestResponse = EveningDigest | EveningDigestPending;

export function isEveningDigestPending(
  value: EveningDigestResponse
): value is EveningDigestPending {
  return "pending" in value && value.pending === true;
}

export type EveningDigestStatus = {
  today: string;
  digest_hour: number;
  timezone: string;
  hour_reached: boolean;
  today_available: boolean;
  today_unread: boolean;
  generated_at?: string | null;
  history_dates: string[];
  /** @deprecated use today_available */
  available?: boolean;
  /** @deprecated use today_unread */
  unread?: boolean;
  digest_date?: string | null;
};

export type EveningDigestArchive = {
  today: string;
  dates: string[];
};
