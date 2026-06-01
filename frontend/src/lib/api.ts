import {
  type ClassificationInput,
  type KnowledgeItemsResponse,
  type Locale,
  type ReaderContent,
  type TaxonomyResponse,
  type ThemeCreateInput,
  type ThemeSplitInput
} from "@/lib/types";

const API_BASE =
  process.env.NEXT_PUBLIC_ON1Y_API_BASE?.replace(/\/$/, "") ?? "http://127.0.0.1:8765";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {})
    },
    cache: "no-store"
  });
  if (!response.ok) {
    const fallback = `request failed: ${response.status}`;
    try {
      const payload = (await response.json()) as { detail?: string };
      throw new Error(payload.detail ?? fallback);
    } catch {
      throw new Error(fallback);
    }
  }
  return (await response.json()) as T;
}

export function getTaxonomy(locale: Locale): Promise<TaxonomyResponse> {
  return request<TaxonomyResponse>(`/api/knowledge/taxonomy?locale=${locale}`);
}

export function getKnowledgeItems(params: {
  locale?: Locale;
  themeId?: number;
  tagId?: number;
  q?: string;
  platform?: string;
  source?: string;
  limit?: number;
}): Promise<KnowledgeItemsResponse> {
  const query = new URLSearchParams();
  query.set("limit", String(params.limit ?? 60));
  if (params.themeId !== undefined) {
    query.set("theme_id", String(params.themeId));
  }
  if (params.tagId !== undefined) {
    query.set("tag_id", String(params.tagId));
  }
  if (params.q) {
    query.set("query", params.q);
  }
  if (params.platform) {
    query.set("platform", params.platform);
  }
  if (params.source) {
    query.set("source", params.source);
  }
  return request<KnowledgeItemsResponse>(`/api/knowledge/items?${query.toString()}`);
}

export function getReaderContent(rawId: number): Promise<ReaderContent> {
  return request<ReaderContent>(`/api/knowledge/items/${rawId}/reader`);
}

export function translateItemTranscript(rawId: number): Promise<{
  raw_id: number;
  translated_body_text: string;
  cached: boolean;
}> {
  return request(`/api/knowledge/items/${rawId}/translate`, { method: "POST" });
}

export function saveItemNote(rawId: number, html: string): Promise<{ raw_id: number; user_note_html: string }> {
  return request(`/api/knowledge/items/${rawId}/note`, {
    method: "PATCH",
    body: JSON.stringify({ html })
  });
}

export function saveItemAnnotation(
  rawId: number,
  html: string
): Promise<{ raw_id: number; annotated_body_html: string }> {
  return request(`/api/knowledge/items/${rawId}/annotation`, {
    method: "PATCH",
    body: JSON.stringify({ html })
  });
}

export function toggleItemFavorite(
  rawId: number,
  starred: boolean
): Promise<{ raw_id: number; starred: boolean }> {
  return request(`/api/knowledge/items/${rawId}/favorite`, {
    method: "PATCH",
    body: JSON.stringify({ starred })
  });
}

export function deleteKnowledgeItem(rawId: number): Promise<{ raw_id: number; deleted: boolean }> {
  return request(`/api/knowledge/items/${rawId}`, { method: "DELETE" });
}

export function moveItemTheme(
  rawId: number,
  themeId: number
): Promise<{ raw_id: number; theme: { slug: string } }> {
  return request(`/api/knowledge/items/${rawId}/theme`, {
    method: "PATCH",
    body: JSON.stringify({ theme_id: themeId })
  });
}

export function patchItemClassification(
  rawId: number,
  payload: ClassificationInput
): Promise<{ raw_id: number; theme: string | null; tags: number }> {
  return request(`/api/knowledge/items/${rawId}/classification`, {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export function createTheme(payload: ThemeCreateInput): Promise<{ theme: { id: number } }> {
  return request("/api/knowledge/themes", {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export function splitTheme(payload: ThemeSplitInput): Promise<{
  remapped: number;
  failed: number;
}> {
  return request("/api/knowledge/themes/split", {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export function createManualItem(payload: {
  title: string;
  body_text: string;
  url?: string;
  platform?: string;
  author?: string;
  theme_slug?: string;
  tags: string[];
  auto_distill: boolean;
}): Promise<{ raw_id: number; distilled_id: number | null }> {
  return request("/api/knowledge/items/manual", {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export async function uploadDocument(file: File, autoDistill: boolean): Promise<{
  raw_id: number;
  distilled_id: number | null;
}> {
  const form = new FormData();
  form.append("file", file);
  const response = await fetch(
    `${API_BASE}/api/knowledge/upload?auto_distill=${autoDistill ? "true" : "false"}`,
    {
      method: "POST",
      body: form
    }
  );
  if (!response.ok) {
    throw new Error(`upload failed: ${response.status}`);
  }
  return (await response.json()) as { raw_id: number; distilled_id: number | null };
}

export type SubscriptionSettings = {
  bilibili_sync_since: string | null;
  youtube_sync_since: string | null;
  zhihu_sync_since: string | null;
  platforms?: string[];
  bilibili_up_sync_enabled?: boolean;
};

export function getSubscriptionSettings(): Promise<SubscriptionSettings> {
  return request<SubscriptionSettings>("/api/subscriptions/settings");
}

export function saveSubscriptionSettings(payload: {
  bilibili_sync_since?: string | null;
  youtube_sync_since?: string | null;
  zhihu_sync_since?: string | null;
}): Promise<SubscriptionSettings & { saved: boolean }> {
  return request("/api/subscriptions/settings", {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export function runHotlistSync(payload?: {
  sources?: string[];
  auto_distill?: boolean;
}): Promise<{
  results?: {
    zhihu?: { created?: number; updated?: number; fetched?: number };
  };
}> {
  return request("/api/hotlist/sync", {
    method: "POST",
    body: JSON.stringify(payload ?? { sources: ["zhihu"] })
  });
}

export function runDistillBackfill(payload?: {
  platform?: string | null;
  batch_size?: number;
  max_items?: number;
}): Promise<{
  started: boolean;
  running?: boolean;
  message?: string;
}> {
  return request("/api/distill/backfill", {
    method: "POST",
    body: JSON.stringify(payload ?? { platform: "bilibili" })
  });
}

export type DistillBackfillStatus = {
  running: boolean;
  started_at?: string | null;
  finished_at?: string | null;
  platform?: string | null;
  distilled?: number;
  failed?: number;
  remaining?: number | null;
  error?: string | null;
};

export function getDistillBackfillStatus(): Promise<DistillBackfillStatus> {
  return request<DistillBackfillStatus>("/api/distill/backfill/status");
}

export function runSubscriptionSync(payload?: {
  platform?: string;
  backfill?: boolean;
  ingest?: boolean;
  ingest_limit?: number;
  subtitle_limit?: number;
  distill_limit?: number;
  refresh_feeds?: boolean;
  sync_hotlist?: boolean;
}): Promise<{
  started: boolean;
  running?: boolean;
  message?: string;
}> {
  return request("/api/subscriptions/sync", {
    method: "POST",
    body: JSON.stringify(payload ?? {})
  });
}

export type SubscriptionSyncStatus = {
  running: boolean;
  started_at?: string | null;
  finished_at?: string | null;
  error?: string | null;
  last_report?: {
    bilibili?: {
      poll?: {
        enqueued?: number;
        ups_deferred?: number;
        rate_limited?: number;
      };
    };
    youtube?: { poll?: { enqueued?: number; skipped_before_since?: number } };
    zhihu?: { poll?: { enqueued?: number; skipped_before_since?: number } };
    enrich?: {
      distill?: {
        distilled?: number;
        failed?: number;
      };
    };
  } | null;
};

export function getSubscriptionSyncStatus(): Promise<SubscriptionSyncStatus> {
  return request<SubscriptionSyncStatus>("/api/subscriptions/sync/status");
}
