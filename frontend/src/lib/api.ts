import {
  type ClassificationInput,
  type CreatorRow,
  type KnowledgeItem,
  type KnowledgeItemsResponse,
  type Locale,
  type ReaderContent,
  type TaxonomyResponse,
  type ThemeCreateInput,
  type ThemeRow,
  type ThemeSplitInput
} from "@/lib/types";
import type { StatsDailyDigest, StatsOverview } from "@/lib/stats-types";
import {
  clearAuth,
  getAuthToken,
  rememberAuthUsername,
  setAuthToken,
  type AuthUser
} from "@/lib/auth";

/** Empty = same-origin when UI is served by `on1y serve` (static export). */
const API_BASE = process.env.NEXT_PUBLIC_ON1Y_API_BASE?.replace(/\/$/, "") ?? "";

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
  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      ...init,
      headers: authHeaders(init?.headers),
      cache: "no-store"
    });
  } catch (error) {
    if (error instanceof Error && error.name === "AbortError") {
      throw new Error("请求超时，请确认 on1y serve 已启动");
    }
    throw new Error("无法连接后端，请确认 on1y serve 已启动");
  }
  if (response.status === 401) {
    clearAuth();
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

export type AuthStatus = {
  auth_required: boolean;
  allow_registration: boolean;
  multi_user: boolean;
  user_count: number;
};

export function fetchAuthStatus(): Promise<AuthStatus> {
  return request<AuthStatus>("/api/auth/status");
}

export function login(username: string, password: string): Promise<{ token: string; user: AuthUser }> {
  return request<{ token: string; user: AuthUser }>("/api/auth/login", {
    method: "POST",
    body: JSON.stringify({ username, password })
  }).then((data) => {
    setAuthToken(data.token);
    rememberAuthUsername(data.user.username);
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
    rememberAuthUsername(data.user.username);
    return data;
  });
}

export function fetchAuthUsers(): Promise<{ users: AuthUser[]; multi_user: boolean }> {
  return request<{ users: AuthUser[]; multi_user: boolean }>("/api/auth/users");
}

export function switchAccount(username: string, password: string): Promise<{ user: AuthUser }> {
  return login(username, password).then((data) => data);
}

export function fetchCurrentUser(): Promise<{ user: AuthUser }> {
  const controller = new AbortController();
  const timer =
    typeof window !== "undefined"
      ? window.setTimeout(() => controller.abort(), 8000)
      : undefined;
  return request<{ user: AuthUser }>("/api/auth/me", { signal: controller.signal }).finally(
    () => {
      if (timer !== undefined) {
        window.clearTimeout(timer);
      }
    }
  );
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
  app?: {
    locale: string;
    appearance?: "light" | "dark" | "system";
    open_browser_on_start: boolean;
    autostart_enabled: boolean;
    autostart_supported: boolean;
  };
  kindle: { enabled: boolean; send_to: string };
  economist: {
    auto_ingest_enabled: boolean;
    auto_kindle_enabled: boolean;
    last_synced_edition: string | null;
    last_kindle_edition: string | null;
  };
  cold_start?: {
    onboarding_dismissed: boolean;
    last_completed_at: string | null;
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

export type DesktopAppStatus = {
  platform: string;
  autostart_supported: boolean;
  autostart_enabled: boolean;
  version: string;
  project_root: string;
  data_dir: string;
  data_dir_override?: string | null;
  close_window_action?: "hide" | "quit";
  is_desktop_shell?: boolean;
  web_url: string;
};

export function getDesktopAppStatus(): Promise<DesktopAppStatus> {
  return request<DesktopAppStatus>("/api/app/desktop");
}

export function patchDesktopPrefs(input: {
  close_window_action?: "hide" | "quit";
  data_dir_override?: string | null;
}): Promise<{
  close_window_action: "hide" | "quit";
  data_dir_override: string | null;
  restart_required?: boolean;
}> {
  return request("/api/app/desktop-prefs", {
    method: "PATCH",
    body: JSON.stringify(input)
  });
}

export function setAutostart(enabled: boolean): Promise<{ autostart_enabled: boolean }> {
  return request<{ autostart_enabled: boolean }>("/api/app/autostart", {
    method: "POST",
    body: JSON.stringify({ enabled })
  });
}

export function patchUserProfile(input: {
  kindle_enabled?: boolean;
  kindle_send_to?: string;
  economist_auto_ingest?: boolean;
  economist_auto_kindle?: boolean;
  locale?: "zh" | "en";
  appearance?: "light" | "dark" | "system";
  open_browser_on_start?: boolean;
  cold_start_onboarding_dismissed?: boolean;
}): Promise<UserProfile> {
  return request<UserProfile>("/api/user/profile", {
    method: "PATCH",
    body: JSON.stringify(input)
  });
}

export function getCookieStatuses(): Promise<{ platforms: CookieStatus[] }> {
  return request<{ platforms: CookieStatus[] }>("/api/user/cookies");
}

export function importCookieJson(
  platform: CookiePlatform,
  payload: unknown
): Promise<{ platform: string; count: number }> {
  return request<{ platform: string; count: number }>(`/api/user/cookies/${platform}/import`, {
    method: "POST",
    body: JSON.stringify({ payload })
  });
}

export async function importCookieFromClipboard(
  platform: CookiePlatform
): Promise<{ platform: string; count: number }> {
  if (typeof navigator === "undefined" || !navigator.clipboard?.readText) {
    throw new Error("当前浏览器不支持读取剪贴板");
  }
  const text = (await navigator.clipboard.readText()).trim();
  if (!text) {
    throw new Error("剪贴板为空");
  }
  let payload: unknown;
  try {
    payload = JSON.parse(text) as unknown;
  } catch {
    throw new Error("剪贴板内容不是有效的 Cookie JSON");
  }
  if (typeof payload !== "object" || payload === null) {
    throw new Error("Cookie JSON 必须是对象或数组");
  }
  return importCookieJson(platform, payload);
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

export type ArchiveImportResult = {
  manifest: Record<string, unknown>;
  imported: number;
  skipped: number;
  themes_created: number;
  cookies_restored: number;
  subscription_restored: number;
  errors: string[];
  error_count: number;
};

export type ArchiveExportOptions = {
  includeTrash?: boolean;
  includeSettings?: boolean;
};

export function buildUserArchiveExportUrl(options: ArchiveExportOptions = {}): string {
  const token = getAuthToken();
  const params = new URLSearchParams();
  if (options.includeTrash) {
    params.set("include_trash", "true");
  }
  if (options.includeSettings) {
    params.set("include_settings", "true");
  }
  if (token) {
    params.set("access_token", token);
  }
  const qs = params.toString() ? `?${params.toString()}` : "";
  return `${API_BASE}/api/user/archive/export${qs}`;
}

export async function exportUserArchive(options: ArchiveExportOptions = {}): Promise<Blob> {
  const url = buildUserArchiveExportUrl(options);
  const token = getAuthToken();
  let response: Response;
  try {
    response = await fetch(url, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
      cache: "no-store"
    });
  } catch {
    throw new Error("无法连接后端，请确认 on1y serve 已启动");
  }
  if (response.status === 401) {
    clearAuth();
    throw new Error("请先登录");
  }
  if (!response.ok) {
    throw new Error(`export failed: ${response.status}`);
  }
  return response.blob();
}

export async function importUserArchive(
  file: File,
  onConflict: "skip" | "overwrite" = "overwrite"
): Promise<ArchiveImportResult> {
  const form = new FormData();
  form.append("file", file);
  const token = getAuthToken();
  let response: Response;
  try {
    response = await fetch(
      `${API_BASE}/api/user/archive/import?on_conflict=${encodeURIComponent(onConflict)}`,
      {
        method: "POST",
        body: form,
        headers: token ? { Authorization: `Bearer ${token}` } : {},
        cache: "no-store"
      }
    );
  } catch {
    throw new Error("无法连接后端，请确认 on1y serve 已启动");
  }
  if (response.status === 401) {
    clearAuth();
    throw new Error("请先登录");
  }
  if (!response.ok) {
    const fallback = `import failed: ${response.status}`;
    let detail = fallback;
    try {
      const payload = (await response.json()) as { detail?: string };
      if (typeof payload.detail === "string") {
        detail = payload.detail;
      }
    } catch {
      /* non-JSON */
    }
    throw new Error(detail);
  }
  return (await response.json()) as ArchiveImportResult;
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

export type NetworkSettingsView = {
  proxy_mode: "auto" | "manual" | "off";
  manual_proxy: string;
  env_proxy: string | null;
  system_proxy: string | null;
  probed_proxy: string | null;
  effective_proxy: string | null;
};

export function getNetworkSettings(): Promise<NetworkSettingsView> {
  return request<NetworkSettingsView>("/api/network/settings");
}

export function saveNetworkSettings(input: {
  proxy_mode?: "auto" | "manual" | "off";
  manual_proxy?: string;
}): Promise<NetworkSettingsView & { saved: boolean }> {
  return request("/api/network/settings", {
    method: "POST",
    body: JSON.stringify(input)
  });
}

export function testNetworkProxy(proxy: string): Promise<{
  ok: boolean;
  proxy?: string;
  status_code?: number;
  error?: string;
}> {
  return request("/api/network/settings", {
    method: "POST",
    body: JSON.stringify({ test_proxy: proxy })
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

export function getStatsOverview(days = 90): Promise<StatsOverview> {
  const query = new URLSearchParams({ days: String(days) });
  return request<StatsOverview>(`/api/stats/overview?${query.toString()}`);
}

export function getStatsDaily(day: string): Promise<StatsDailyDigest> {
  const query = new URLSearchParams({ day });
  return request<StatsDailyDigest>(`/api/stats/daily?${query.toString()}`);
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

export function getCreators(options?: {
  enrichAvatars?: boolean;
}): Promise<{ creators: CreatorRow[]; count: number }> {
  const query = new URLSearchParams();
  if (options?.enrichAvatars) {
    query.set("enrich_avatars", "true");
  }
  const suffix = query.toString() ? `?${query.toString()}` : "";
  return request(`/api/knowledge/creators${suffix}`);
}

export function getKnowledgeItems(params: {
  locale?: Locale;
  themeId?: number;
  creatorKey?: string;
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
  if (params.creatorKey) {
    query.set("creator_key", params.creatorKey);
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

export function getRelatedItems(
  rawId: number,
  limit = 6
): Promise<{ items: KnowledgeItem[]; scope: string }> {
  const query = new URLSearchParams({ limit: String(limit) });
  return request(`/api/knowledge/items/${rawId}/related?${query.toString()}`);
}

export function postRelatedLessRelevant(
  fromRawId: number,
  toRawId: number
): Promise<{ ok: boolean }> {
  return request(`/api/knowledge/items/${fromRawId}/related/${toRawId}/feedback`, {
    method: "POST"
  });
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

export type FullSyncTiming = {
  user_id: number;
  started_at: string;
  finished_at: string;
  total_ms: number;
  total_human: string;
  phases_ms: Record<string, number>;
  phases_human: Record<string, string>;
  detail?: Record<string, unknown>;
  error?: string | null;
  recorded_at?: string;
};

export type ColdStartProgressView = {
  phase?: string | null;
  elapsed_ms?: number;
  counters?: Record<string, number>;
  events?: Array<{
    id: number;
    ts: string;
    kind: string;
    status: string;
    phase: string;
    title: string;
    platform?: string | null;
    detail?: string | null;
    url?: string | null;
  }>;
  event_total?: number;
};

export type PipelineBarMetrics = {
  done: number;
  total: number;
};

export type FullSyncStatus = {
  running: boolean;
  active?: boolean;
  distill_running?: boolean;
  started_at: string | null;
  finished_at: string | null;
  elapsed_ms?: number | null;
  last_report: Record<string, unknown> | null;
  last_timing: FullSyncTiming | null;
  current_phase: string | null;
  phases_ms: Record<string, number>;
  progress: ColdStartProgressView | null;
  pipeline_bars?: {
    ingest: PipelineBarMetrics;
    subtitles: PipelineBarMetrics;
    distill: PipelineBarMetrics;
  } | null;
  background_distill?: DistillBackfillStatus | null;
  error: string | null;
  user_id: number | null;
};

export type FullSyncTimingResponse = {
  last_timing: FullSyncTiming | null;
  current_phase: string | null;
  phases_ms: Record<string, number>;
  history: FullSyncTiming[];
};

export function runFullSync(): Promise<{ started: boolean; running: boolean; message: string }> {
  return request<{ started: boolean; running: boolean; message: string }>("/api/cold-start", {
    method: "POST"
  });
}

export function getFullSyncStatus(): Promise<FullSyncStatus> {
  return request<FullSyncStatus>("/api/cold-start/status");
}

export const runColdStart = runFullSync;
export const getColdStartStatus = getFullSyncStatus;

export function getFullSyncTiming(limit = 20): Promise<FullSyncTimingResponse> {
  return request<FullSyncTimingResponse>(`/api/sync/full/timing?limit=${limit}`);
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
