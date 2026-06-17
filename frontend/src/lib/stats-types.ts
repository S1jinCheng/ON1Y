export type StatsPlatformRow = {
  platform: string;
  count: number;
};

export type StatsContentKindRow = {
  content_kind: string;
  count: number;
};

export type StatsThemeRow = {
  theme_id: number | null;
  slug: string;
  name_zh: string;
  name_en: string;
  count: number;
};

export type StatsTimelineDay = {
  date: string;
  total: number;
  by_platform: Record<string, number>;
};

export type StatsHourRow = {
  hour: number;
  count: number;
};

export type StatsWeekdayRow = {
  weekday: number;
  label_zh: string;
  label_en: string;
  count: number;
};

export type StatsTimelinePeak = {
  date: string;
  total: number;
};

export type StatsHighlights = {
  peak_hour: number | null;
  peak_hour_count: number;
  peak_weekday: number | null;
  peak_weekday_count: number;
  busiest_day: string | null;
  busiest_day_count: number;
};

export type StatsOverview = {
  days: number;
  start_date: string;
  end_date: string;
  generated_at: string;
  date_basis: string;
  totals: {
    items: number;
    with_original_publish_time: number;
    in_range: number;
  };
  by_platform: StatsPlatformRow[];
  by_content_kind: StatsContentKindRow[];
  by_theme: StatsThemeRow[];
  timeline: StatsTimelineDay[];
  by_hour: StatsHourRow[];
  by_weekday: StatsWeekdayRow[];
  timeline_peaks: StatsTimelinePeak[];
  highlights: StatsHighlights;
  timezone?: string;
};

export type StatsDailyDigest = {
  date: string;
  total: number;
  by_platform: Record<string, number>;
  by_content_kind: Record<string, number>;
  date_basis: string;
};

export type WeeklyPlatformRow = {
  platform: string;
  count: number;
};

export type WeeklyThemeRow = {
  theme_id: number | null;
  slug: string;
  name_zh: string;
  name_en: string;
  count: number;
};

export type WeeklyDailyRow = {
  date: string;
  total: number;
};

export type WeeklyNoteItem = {
  raw_id: number;
  title: string;
  platform: string;
  note_preview: string;
  updated_at: string | null;
};

export type WeeklyReview = {
  week_offset: number;
  week_start: string;
  week_end: string;
  generated_at: string;
  timezone: string;
  date_basis: string;
  reading: {
    published_total: number;
    marked_read: number;
    by_platform: WeeklyPlatformRow[];
    by_theme: WeeklyThemeRow[];
    daily: WeeklyDailyRow[];
  };
  notes: {
    updated_count: number;
    items: WeeklyNoteItem[];
  };
  comparison: {
    published_prev_week: number;
    published_delta: number;
  };
};
