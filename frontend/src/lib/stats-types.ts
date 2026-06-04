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
