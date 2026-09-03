export type BookStatus = "reading" | "read";

export type BookLink = {
  label: string;
  url: string;
};

export type BookSource = {
  id: string;
  name: string;
  type: "link" | "fetch";
  enabled: boolean;
  url_template: string;
  parser?: string | null;
  sort_order: number;
};

export type BookSourcesFile = {
  version: number;
  sources: BookSource[];
};

export type BookFormat = "epub" | "pdf" | "mobi";

export type BookAcquireStrategy = "match_first" | "format_first";

export type BookSettings = {
  version: number;
  cache_dir?: string | null;
  folder_sync_enabled?: boolean;
  zlib_base_url: string;
  acquire_strategy: BookAcquireStrategy;
  preferred_format: BookFormat;
  allowed_formats: BookFormat[];
  format_filter?: BookFormat | null;
  format_filters?: BookFormat[];
  /** @deprecated use preferred_format */
  default_format?: BookFormat;
  annas_secret_key?: string | null;
  resolved_cache_dir?: string;
};

export type BookAcquireCandidate = {
  source: "zlib" | "annas";
  format: BookFormat;
  title: string;
  author?: string | null;
  publisher?: string | null;
  year?: string | null;
  language?: string | null;
  filesize?: string | null;
  cover_url?: string | null;
  book_id?: string | number;
  book_hash?: string;
  md5?: string;
  label?: string;
};

export type BookAcquirePreview = {
  ok: boolean;
  source: "zlib" | "annas";
  search_query: string;
  format_filter: BookFormat | null;
  format_filters: BookFormat[];
  total_candidates: number;
  douban: {
    title: string;
    author?: string | null;
    translator?: string | null;
    publisher?: string | null;
    isbn?: string | null;
    cover_url?: string | null;
  };
  candidates: BookAcquireCandidate[];
};

export type BookAcquireResult = {
  ok: boolean;
  format: BookFormat;
  local_path: string;
  source?: string;
  kindle_sent: boolean;
  kindle_status?: "sent" | "skipped" | "failed";
  kindle_detail?: string | null;
  matched_title?: string | null;
  matched_author?: string | null;
  match_quality?: "high" | "medium" | "low";
  search_query?: string | null;
  file_size_bytes?: number;
  validation_ok?: boolean;
  validation_detail?: string | null;
  shelf_item?: BookShelfItem | null;
};

export type BookSearchHit = {
  source_id: string;
  source_name: string;
  query: string;
  url: string;
  kind: "link";
};

export type BookEditionHit = {
  edition_id: string;
  source_id: string;
  source_name: string;
  title: string;
  author?: string | null;
  translator?: string | null;
  publisher?: string | null;
  pub_meta?: string | null;
  rating?: number | null;
  rating_count?: number | null;
  cover_url?: string | null;
  url: string;
  kind: "edition";
};

export type BookShortReview = {
  author?: string | null;
  content: string;
  published_at?: string | null;
};

export type BookWorkDetail = {
  edition_id: string;
  title: string;
  author?: string | null;
  translator?: string | null;
  publisher?: string | null;
  pub_date?: string | null;
  isbn?: string | null;
  rating?: number | null;
  rating_count?: number | null;
  cover_url?: string | null;
  summary?: string | null;
  short_reviews?: BookShortReview[];
  url: string;
  acquisition_links: BookLink[];
  source_links?: BookLink[];
};

export type BookShelfItem = {
  id: number;
  raw_id?: number | null;
  title: string;
  author?: string | null;
  translator?: string | null;
  publisher?: string | null;
  cover_url?: string | null;
  summary?: string | null;
  status: BookStatus;
  links: BookLink[];
  notes?: string | null;
  user_note_html?: string | null;
  importance?: number | null;
  theme_slug?: string | null;
  tags?: string[];
  cached_format?: string | null;
  local_path?: string | null;
  created_at: string;
  updated_at: string;
};

export type BookShelfRelated = {
  id: number;
  title: string;
  author?: string | null;
  translator?: string | null;
  cover_url?: string | null;
  summary?: string | null;
  tags?: string[];
  status: BookStatus;
};
