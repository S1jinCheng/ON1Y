export type PaperStatus = "to_read" | "reading" | "read";

export type PaperAuthor = {
  name: string;
  scholar_id?: string | null;
  scholar_url?: string | null;
  google_scholar_url: string;
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
  citation_count?: number | null;
  google_scholar_url: string;
  user_note_html?: string | null;
  importance?: number | null;
  theme_slug?: string | null;
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
