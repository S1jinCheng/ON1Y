import {
  type ClassificationInput,
  type KnowledgeItemsResponse,
  type Locale,
  type ReaderContent,
  type TaxonomyResponse,
  type ThemeCreateInput,
  type ThemeRow,
  type ThemeSplitInput
} from "@/lib/types";
import { clearAuth, getAuthToken, setAuthToken, type AuthUser } from "@/lib/auth";

const API_BASE =
  process.env.NEXT_PUBLIC_ON1Y_API_BASE?.replace(/\/$/, "") ?? "http://127.0.0.1:8765";

export function economistEpubDownloadUrl(rawId: number): string {
  const token = getAuthToken();
  const suffix = token ? `?access_token=${encodeURIComponent(token)}` : "";
  return `${API_BASE}/api/knowledge/items/${rawId}/economist-epub${suffix}`;
}

function authHeaders(extra?: HeadersInit): HeadersInit {
  const token = getAuthToken();
  return {
    "Content-Type": "application/json",
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    ...(extra ?? {})
  };
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: authHeaders(init?.headers),
    cache: "no-store"
  });
  if (response.status === 401) {
    clearAuth();
    if (typeof window !== "undefined" && !window.location.pathname.startsWith("/login")) {
      window.location.href = "/login";
    }
    throw new Error("请先登录");
  }
  if (!response.ok) {
    const fallback = `request failed: ${response.status}`;
    let detail = fallback;
    try {
      const payload = (await response.json()) as { detail?: string | string[] };
      if (typeof payload.detail === "string") {
        detail = payload.detail;
      } else if (Array.isArray(payload.detail)) {
        detail = payload.detail.map(String).join("; ");
      }
    } catch {
      /* non-JSON body */
    }
    throw new Error(detail);
  }
  return (await response.json()) as T;
}

export function login(username: string, password: string): Promise<{ token: string; user: AuthUser }> {
  return request<{ token: string; user: AuthUser }>("/api/auth/login", {
    method: "POST",
    body: JSON.stringify({ username, password })
  }).then((data) => {
    setAuthToken(data.token);
    return data;
  });
}

export function register(input: {
  username: string;
  password: string;
  email?: string;
  display_name?: string;
}): Promise<{ token: string; user: AuthUser }> {
  return request<{ token: string; user: AuthUser }>("/api/auth/register", {
    method: "POST",
    body: JSON.stringify(input)
  }).then((data) => {
    setAuthToken(data.token);
    return data;
  });
}

export function fetchCurrentUser(): Promise<{ user: AuthUser }> {
  return request<{ user: AuthUser }>("/api/auth/me");
}

export function logout(): void {
  clearAuth();
}

export type { AuthUser } from "@/lib/auth";

export function updateAuthProfile(input: {
  display_name?: string;
  email?: string | null;
}): Promise<{ user: AuthUser }> {
  return request<{ user: AuthUser }>("/api/auth/profile", {
    method: "PATCH",
    body: JSON.stringify(input)
  });
}

export function changePassword(input: {
  current_password: string;
  new_password: string;
}): Promise<{ status: string }> {
  return request<{ status: string }>("/api/auth/password", {
    method: "PATCH",
    body: JSON.stringify(input)
  });
}

export type CookiePlatform = "youtube" | "bilibili" | "zhihu" | "xiaohongshu" | "twitter";

export type CookieStatus = {
  platform: CookiePlatform;
  exists: boolean;
  count: number;
  updated_at: string | null;
};

export type UserProfile = {
  user_id: number;
  owner: string;
  kindle: { enabled: boolean; send_to: string };
  economist: {
    auto_ingest_enabled: boolean;
    auto_kindle_enabled: boolean;
    last_synced_edition: string | null;
    last_kindle_edition: string | null;
  };
  integrations: {
    cookies: Record<string, { path: string; exists: boolean }>;
    llm: { base_url: string; model: string; api_key_configured: boolean };
    smtp: { host: string; port: number; from: string; configured: boolean };
  };
};

export function getUserProfile(): Promise<UserProfile> {
  return request<UserProfile>("/api/user/profile");
}

export function patchUserProfile(input: {
  kindle_enabled?: boolean;
  kindle_send_to?: string;
  economist_auto_ingest?: boolean;
  economist_auto_kindle?: boolean;
}): Promise<UserProfile> {
  return request<UserProfile>("/api/user/profile", {
    method: "PATCH",
    body: JSON.stringify(input)
  });
}

export function getCookieStatuses(): Promise<{ platforms: CookieStatus[] }> {
  return request<{ platforms: CookieStatus[] }>("/api/user/cookies");
}

export async function uploadCookieFile(
  platform: CookiePlatform,
  file: File
): Promise<{ platform: string; count: number }> {
  const token = getAuthToken();
  const form = new FormData();
  form.append("file", file);
  const response = await fetch(`${API_BASE}/api/user/cookies/${platform}`, {
    method: "POST",
    headers: token ? { Authorization: `Bearer ${token}` } : undefined,
    body: form
  });
  if (!response.ok) {
    let detail = `upload failed: ${response.status}`;
    try {
      const payload = (await response.json()) as { detail?: string };
      if (payload.detail) {
        detail = payload.detail;
      }
    } catch {
      /* ignore */
    }
    throw new Error(detail);
  }
  return (await response.json()) as { platform: string; count: number };
}

export function deleteCookieFile(platform: CookiePlatform): Promise<{ removed: boolean }> {
  return request<{ removed: boolean }>(`/api/user/cookies/${platform}`, {
    method: "DELETE"
  });
}

export type LlmSettingsView = {
  base_url: string;
  model: string;
  api_key_set: boolean;
  api_key_preview: string;
  defaults: { base_url: string; model: string };
};

export function getLlmSettings(): Promise<LlmSettingsView> {
  return request<LlmSettingsView>("/api/llm/settings");
}

export function saveLlmSettings(input: {
  base_url: string;
  model: string;
  api_key?: string;
  clear_api_key?: boolean;
}): Promise<LlmSettingsView & { saved: boolean }> {
  return request("/api/llm/settings", {
    method: "POST",
    body: JSON.stringify({
      base_url: input.base_url,
      model: input.model,
      api_key: input.api_key ?? "",
      clear_api_key: input.clear_api_key ?? false
    })
  });
}

export function testLlmSettings(input?: {
  base_url: string;
  model: string;
  api_key?: string;
}): Promise<{ ok: boolean; endpoint: string; model: string; reply_preview?: string; error?: string }> {
  return request("/api/llm/test", {
    method: "POST",
    body: JSON.stringify(
      input
        ? { base_url: input.base_url, model: input.model, api_key: input.api_key ?? "", clear_api_key: false }
        : { base_url: "", model: "", api_key: "", clear_api_key: false }
    )
  });
}

export function getTaxonomy(locale: Locale): Promise<TaxonomyResponse> {
  return request<TaxonomyResponse>(`/api/knowledge/taxonomy?locale=${locale}`);
}

export type HotlistSource = "zhihu" | "economist";

export function getCollectionCounts(params?: {
  hotlistDate?: string;
  hotlistSource?: HotlistSource;
}): Promise<{
  favorites: number;
  trash: number;
  hotlist: number;
}> {
  const query = new URLSearchParams();
  if (params?.hotlistDate) {
    query.set("hotlist_date", params.hotlistDate);
  }
  if (params?.hotlistSource) {
    query.set("hotlist_source", params.hotlistSource);
  }
  const suffix = query.toString() ? `?${query.toString()}` : "";
  return request<{ favorites: number; trash: number; hotlist: number }>(
    `/api/knowledge/collections${suffix}`
  );
}

export function getHotlistDates(source: HotlistSource = "zhihu"): Promise<{
  dates: string[];
  today: string;
}> {
  const query = new URLSearchParams({ source });
  return request<{ dates: string[]; today: string }>(`/api/hotlist/dates?${query}`);
}

export type EconomistWeekOption = {
  edition_date: string;
  iso_year: number;
  iso_week: number;
  label: string;
  epub_url: string;
  title: string;
  synced?: boolean;
};

export function getEconomistWeeks(
  year?: number,
  locale?: Locale
): Promise<{
  year: number;
  weeks: EconomistWeekOption[];
  current_iso_year: number;
  current_iso_week: number;
}> {
  const query = new URLSearchParams();
  if (year !== undefined) {
    query.set("year", String(year));
  }
  if (locale) {
    query.set("locale", locale);
  }
  const suffix = query.toString() ? `?${query.toString()}` : "";
  return request(`/api/hotlist/economist/weeks${suffix}`);
}

export function getKnowledgeItems(params: {
  locale?: Locale;
  themeId?: number;
  tagId?: number;
  q?: string;
  platform?: string;
  source?: string;
  collection?: "feed" | "favorites" | "trash" | "hotlist";
  hotlistDate?: string;
  hotlistSource?: HotlistSource;
  limit?: number;
  offset?: number;
}): Promise<KnowledgeItemsResponse> {
  const query = new URLSearchParams();
  query.set("limit", String(params.limit ?? 60));
  if (params.offset !== undefined && params.offset > 0) {
    query.set("offset", String(params.offset));
  }
  if (params.collection && params.collection !== "feed") {
    query.set("collection", params.collection);
  }
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
  if (params.hotlistDate) {
    query.set("hotlist_date", params.hotlistDate);
  }
  if (params.hotlistSource) {
    query.set("hotlist_source", params.hotlistSource);
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

export function batchDeleteKnowledgeItems(
  rawIds: number[]
): Promise<{ raw_ids: number[]; deleted: number; not_found: number }> {
  return request("/api/knowledge/items/batch-delete", {
    method: "POST",
    body: JSON.stringify({ raw_ids: rawIds })
  });
}

export function restoreKnowledgeItem(rawId: number): Promise<{ raw_id: number; restored: boolean }> {
  return request(`/api/knowledge/items/${rawId}/restore`, { method: "POST" });
}

export function batchRestoreKnowledgeItems(
  rawIds: number[]
): Promise<{ raw_ids: number[]; restored: number; not_found: number }> {
  return request("/api/knowledge/items/batch-restore", {
    method: "POST",
    body: JSON.stringify({ raw_ids: rawIds })
  });
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

export function deleteTheme(
  themeId: number
): Promise<{ ok: boolean; theme_id: number; remapped: number }> {
  return request(`/api/knowledge/themes/${themeId}`, {
    method: "DELETE"
  });
}

export function reorderThemes(
  themeIds: number[],
  locale: Locale = "zh"
): Promise<{ ok: boolean; themes: ThemeRow[] }> {
  return request(`/api/knowledge/themes/reorder?locale=${locale}`, {
    method: "POST",
    body: JSON.stringify({ theme_ids: themeIds })
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
  enabled_platforms?: string[];
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
  enabled_platforms?: string[];
}): Promise<SubscriptionSettings & { saved: boolean }> {
  return request("/api/subscriptions/settings", {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export function runHotlistSync(payload?: {
  sources?: HotlistSource[];
  snapshot_date?: string;
  auto_distill?: boolean;
  auto_tag?: boolean;
}): Promise<{
  results?: Partial<
    Record<
      HotlistSource,
      {
        created?: number;
        updated?: number;
        fetched?: number;
        tagged?: number;
      }
    >
  >;
}> {
  return request("/api/hotlist/sync", {
    method: "POST",
    body: JSON.stringify(
      payload ?? { sources: ["zhihu"], auto_tag: true }
    )
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
  platforms?: Array<"bilibili" | "youtube" | "zhihu">;
  backfill?: boolean;
  ingest?: boolean;
  use_ai_summary?: boolean;
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
    bilibili?: PlatformSyncReport;
    youtube?: PlatformSyncReport;
    zhihu?: PlatformSyncReport;
    use_ai_summary?: boolean;
  } | null;
};

type PlatformSyncReport = {
  poll?: {
    enqueued?: number;
    ups_deferred?: number;
    rate_limited?: number;
    skipped_before_since?: number;
  };
  enrich?: {
    distill?: {
      distilled?: number;
      failed?: number;
    };
  };
  distill?: {
    distilled?: number;
    failed?: number;
  };
};

export function getSubscriptionSyncStatus(): Promise<SubscriptionSyncStatus> {
  return request<SubscriptionSyncStatus>("/api/subscriptions/sync/status");
}
