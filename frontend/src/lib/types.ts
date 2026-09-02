export type Locale = "zh" | "en";

export type ThemeRow = {
  id: number;
  slug: string;
  name_zh: string;
  name_en: string;
  label: string;
  description_zh?: string;
  description_en?: string;
  item_count: number;
  is_builtin?: boolean;
  archived_at?: string | null;
};

export type DynamicTagRow = {
  id: number;
  name: string;
  slug: string;
  item_count: number;
};

export type ItemTheme = {
  id: number;
  slug: string;
  name_zh: string;
  name_en: string;
};

export type CreatorRow = {
  key: string;
  name: string;
  platform: string;
  author_url?: string | null;
  author_avatar?: string | null;
  item_count: number;
  feed_labels: string[];
};

export type ItemTag = {
  id: number;
  name: string;
  slug: string;
};

export type ContentTypeValue = "video" | "article" | "unknown";

export type KnowledgeItem = {
  raw_id: number;
  url: string;
  title: string | null;
  platform: string;
  source: string;
  content_type?: ContentTypeValue | string | null;
  ingested_at: string | null;
  published_at?: string | null;
  duration_sec?: number | null;
  like_count?: number | null;
  comment_count?: number | null;
  feed_label?: string | null;
  hot_rank?: number | null;
  heat_text?: string | null;
  snapshot_date?: string | null;
  summary: string | null;
  topics: string[];
  prompt_version: string | null;
  distill_status: string | null;
  author: string;
  author_avatar: string;
  author_url: string;
  cover_image: string;
  theme_id: number | null;
  theme: ItemTheme | null;
  themes: ItemTheme[];
  tags: ItemTag[];
  starred?: boolean;
  read_at?: string | null;
  is_read?: boolean;
  has_note?: boolean;
  importance?: number | null;
  clip_source?: string | null;
  clip_count?: number | null;
  extract_strategy?: string | null;
  obsidian_uri?: string | null;
  obsidian_source_url?: string | null;
  obsidian_path?: string | null;
  obsidian_writeback_status?: string | null;
  deleted_at?: string | null;
  search_rank?: number;
  search_snippet?: string;
  search_title_html?: string;
  search_summary_html?: string;
};

export type TranscriptKind = "zh" | "en" | "none" | "other";

export type ReaderContent = {
  raw_id: number;
  url: string;
  title: string | null;
  platform: string;
  published_at?: string | null;
  duration_sec?: number | null;
  like_count?: number | null;
  comment_count?: number | null;
  body_text: string | null;
  raw_body_text?: string | null;
  summary: string | null;
  reader_text: string | null;
  author: string;
  author_avatar: string;
  author_url: string;
  cover_image: string;
  user_note_html: string;
  annotated_body_html: string;
  clip_source?: string | null;
  clip_title?: string | null;
  clip_count?: number | null;
  extract_strategy?: string | null;
  jina_markdown?: string | null;
  jina_markdown_length?: number | null;
  obsidian_uri?: string | null;
  obsidian_source_url?: string | null;
  obsidian_path?: string | null;
  obsidian_writeback_status?: string | null;
  transcript_kind: TranscriptKind;
  translated_body_text: string | null;
  can_translate: boolean;
  is_conversation?: boolean;
  telegram_messages?: Array<{
    sender?: string;
    time?: string;
    timestamp?: number;
    text?: string;
    is_self?: boolean;
    kind?: string;
  }> | null;
};

export type TaxonomyResponse = {
  themes: ThemeRow[];
  tags: DynamicTagRow[];
  locale: string;
};

export type KnowledgeItemsResponse = {
  items: KnowledgeItem[];
  count: number;
  total?: number;
  engine?: string;
};

export type ClassificationInput = {
  theme_slug?: string;
  theme_slugs?: string[];
  tags: string[];
};

export type ThemeCreateInput = {
  slug?: string;
  name_zh: string;
  name_en?: string;
  description_zh?: string;
  description_en?: string;
};

export type ThemeUpdateInput = {
  name_zh?: string;
  name_en?: string;
  description_zh?: string;
  description_en?: string;
  sort_order?: number;
};

export type ThemeSplitInput = {
  source_theme_id: number;
  new_themes: Array<{
    slug?: string;
    name_zh: string;
    name_en?: string;
    description_zh?: string;
    description_en?: string;
  }>;
  archive_source?: boolean;
};
