export type PaperStatus = "to_read" | "reading" | "read";

export type PaperCollection = {
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

export type PaperAiSummary = {
  overview: string;
  research_question: string;
  method: string;
  key_findings: string[];
  effects: string[];
  limitations: string[];
  keywords: string[];
};

export type PaperFigure = {
  filename: string;
  page: number;
  caption: string;
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
  zotero_collections: PaperCollection[];
  citation_count?: number | null;
  google_scholar_url: string;
  user_note_html?: string | null;
  importance?: number | null;
  theme_slug?: string | null;
  ai_summary?: PaperAiSummary | null;
  ai_summary_status: "idle" | "running" | "ok" | "error";
  ai_summary_error?: string | null;
  ai_summary_model?: string | null;
  ai_summary_updated_at?: string | null;
  figures: PaperFigure[];
  tags: string[];
  created_at: string;
  updated_at: string;
};

export type PaperSettings = {
  version: number;
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
  ai_summary_mode: "manual" | "auto";
  pdf_open_mode: "zotero" | "system" | "custom";
  pdf_application_path?: string | null;
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
