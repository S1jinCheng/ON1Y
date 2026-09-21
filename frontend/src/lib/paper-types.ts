export type PaperStatus = "to_read" | "reading" | "read" | "dismissed";

export type PaperCollection = {
  key: string;
  name: string;
  path: string;
  parent_key?: string | null;
  paper_count?: number;
};

export type PaperFolder = {
  key: string;
  name: string;
  path: string;
  parent_key?: string | null;
  paper_count?: number;
};

export type PaperAuthor = {
  name: string;
  scholar_id?: string | null;
  scholar_url?: string | null;
  google_scholar_url: string;
};

export type PaperFigure = {
  filename: string;
  page: number;
  caption: string;
  kind: "figure" | "table";
  width?: number | null;
  height?: number | null;
};

export type PaperItem = {
  id: number;
  raw_id?: number | null;
  title: string;
  authors: PaperAuthor[];
  abstract?: string | null;
  status: PaperStatus;
  year?: number | null;
  venue?: string | null;
  doi?: string | null;
  url?: string | null;
  pdf_path?: string | null;
  zotero_key?: string | null;
  zotero_library_id?: string | null;
  zotero_attachment_key?: string | null;
  zotero_library_type?: "users" | "groups" | null;
  zotero_reader_url?: string | null;
  zotero_version?: number | null;
  folders: PaperFolder[];
  literature_paper_id?: string | null;
  zotero_collections: PaperCollection[];
  citation_count?: number | null;
  google_scholar_url: string;
  user_note_html?: string | null;
  importance?: number | null;
  theme_slug?: string | null;
  figures: PaperFigure[];
  tags: string[];
  created_at: string;
  updated_at: string;
};

export type PaperSettings = {
  version: number;
  literature_vault_path: string;
  literature_vault?: { path: string; exists: boolean; drive_available: boolean; initialized: boolean };
  cache_dir?: string | null;
  resolved_cache_dir?: string;
  folder_sync_enabled: boolean;
  zotero_enabled: boolean;
  zotero_mode: "local" | "web";
  zotero_base_url: string;
  zotero_library_type: "users" | "groups";
  zotero_library_id: string;
  zotero_api_key?: string | null;
  zotero_collection_key?: string | null;
  zotero_download_pdfs: boolean;
  pdf_open_mode: "zotero" | "system" | "custom";
  pdf_application_path?: string | null;
  translation_enabled: boolean;
  translation_provider: "on1y_ai" | "deepl";
  translation_source_lang: string;
  translation_target_lang: string;
  translation_model_override?: string | null;
  translation_api_key?: string | null;
  translation_api_key_set?: boolean;
  translation_api_key_preview?: string | null;
  translation_deepl_plan: "free" | "pro";
  translation_babeldoc_executable?: string | null;
  translation_glossary_path?: string | null;
  translation_qps: number;
  translation_auto_enqueue: boolean;
  translation_ocr_workaround: boolean;
  translation_worker?: {
    available: boolean;
    executable?: string | null;
    engine: string;
    version: string;
    isolation: string;
    license: string;
    install_command: string;
  };
};

export type PaperSyncResult = {
  enabled: boolean;
  imported: number;
  updated?: number;
  downloaded?: number;
  skipped?: number;
  folder?: string;
  errors: string[];
};

export type LiteraturePaperInput = {
  title?: string;
  authors?: string[] | string;
  abstract?: string;
  year?: number;
  venue?: string;
  doi?: string;
  arxiv_id?: string;
  semantic_scholar_id?: string;
  source_url?: string;
  pdf_url?: string;
  local_pdf_path?: string;
  citation_count?: number;
  area?: string;
  age_category?: string;
  recommendation?: string;
};

export type LiteratureTranslationSummary = {
  state: "pending" | "translating" | "ready" | "ready_with_warnings" | "failed" | "unavailable";
  total: number;
  eligible: number;
  not_queued: number;
  queued: number;
  running: number;
  succeeded: number;
  failed: number;
  cancelled: number;
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
  character_count: number;
};

export type LiteratureTranslationJob = {
  id: string;
  batch_id: string;
  paper_id: string;
  title?: string;
  position?: number;
  status: "queued" | "running" | "succeeded" | "failed" | "cancelled";
  provider: "on1y_ai" | "deepl";
  model?: string | null;
  source_lang: string;
  target_lang: string;
  progress: number;
  stage?: string | null;
  attempt: number;
  error?: string | null;
  output_relpath?: string | null;
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
  character_count: number;
};

export type LiteratureReadingProgress = {
  total: number;
  read: number;
  dismissed: number;
  pending: number;
  carried: number;
};

export type LiteratureDailyPlan = {
  target_date: string;
  field: string;
  daily_target: number;
  carryover_count: number;
  new_slots: number;
  backlog_remaining: number;
  blocking_fields: string[];
  can_change_field: boolean;
  carryover: Array<{
    id: string;
    title: string;
    from_batch_id: string;
    from_position: number;
    from_date: string;
    from_field: string;
    status: PaperStatus;
  }>;
};

export type LiteratureBatch = {
  id: string;
  field: string;
  field_slug: string;
  field_code: string;
  batch_date: string;
  status: "draft" | "publishing" | "published" | "error";
  error?: string | null;
  paper_count?: number;
  papers?: Array<LiteraturePaperInput & {
    id: string;
    position: number;
    status: PaperStatus;
    note_relpath?: string | null;
    original_pdf_relpath?: string | null;
    bilingual_pdf_relpath?: string | null;
    carryover_from_batch_id?: string | null;
    carryover_from_position?: number | null;
    carryover_from_date?: string | null;
    carried_to_batch_id?: string | null;
    carried_to_date?: string | null;
  }>;
  progress?: LiteratureReadingProgress;
  translation?: LiteratureTranslationSummary;
  translation_jobs?: LiteratureTranslationJob[];
};
