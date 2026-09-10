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
  type ThemeSplitInput,
  type ThemeUpdateInput
} from "@/lib/types";
import type {
  EveningDigest,
  EveningDigestArchive,
  EveningDigestResponse,
  EveningDigestStatus
} from "@/lib/digest-types";
import { isEveningDigestPending } from "@/lib/digest-types";
import type { StatsDailyDigest, StatsOverview, WeeklyReview } from "@/lib/stats-types";
import type {
  BookAcquireCandidate,
  BookAcquirePreview,
  BookAcquireResult,
  BookEditionHit,
  BookFormat,
  BookSearchHit,
  BookShelfItem,
  BookShelfRelated,
  BookSettings,
  BookSourcesFile,
  BookStatus,
  BookWorkDetail
} from "@/lib/book-types";
import type { PaperCollection, PaperItem, PaperSettings, PaperStatus, PaperSyncResult } from "@/lib/paper-types";
import {
  clearAuth,
  getAuthToken,
  rememberAuthUsername,
  setAuthToken,
  type AuthUser
} from "@/lib/auth";

/** Empty = same-origin when UI is served by `on1y serve` (static export). */
const API_BASE = process.env.NEXT_PUBLIC_ON1Y_API_BASE?.replace(/\/$/, "") ?? "";

/** Backend origin for dev (`npm run dev` on :3000) long requests — bypasses Next rewrite proxy timeouts. */
const DEV_BACKEND_ORIGIN =
  process.env.NEXT_PUBLIC_ON1Y_API_BASE?.replace(/\/$/, "") || "http://127.0.0.1:8765";

function isDevFrontendHost(): boolean {
  if (typeof window === "undefined") {
    return false;
  }
  const port = window.location.port;
  return port === "3000" || port === "3001" || port === "3045";
}

function resolveApiUrl(path: string, direct?: boolean): string {
  if (direct && isDevFrontendHost()) {
    return `${DEV_BACKEND_ORIGIN}${path}`;
  }
  return `${API_BASE}${path}`;
}

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

type RequestOptions = RequestInit & { direct?: boolean };

async function request<T>(path: string, init?: RequestOptions): Promise<T> {
  const { direct, ...fetchInit } = init ?? {};
  let response: Response;
  try {
    response = await fetch(resolveApiUrl(path, direct), {
      ...fetchInit,
      headers: authHeaders(fetchInit.headers),
      cache: "no-store"
    });
  } catch (error) {
    if (error instanceof Error && error.name === "AbortError") {
      throw new Error("请求超时，请确认 on1y serve 已启动");
    }
    if (direct && isDevFrontendHost()) {
      throw new Error(
        "无法连接 on1y serve（127.0.0.1:8765）。大文件下载需直连后端，请确认已运行 on1y serve"
      );
    }
    throw new Error("无法连接后端，请确认 on1y serve 已启动");
  }
  if (response.status === 401) {
    clearAuth();
    if (path !== "/api/auth/login") {
      throw new Error("请先登录");
    }
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
  single_user_mode: boolean;
  multi_user: boolean;
  user_count: number;
};

export function fetchAuthStatus(): Promise<AuthStatus> {
  return request<AuthStatus>("/api/auth/status");
}

export function login(
  username: string,
  password: string,
  persist = true
): Promise<{ token: string; user: AuthUser }> {
  return request<{ token: string; user: AuthUser }>("/api/auth/login", {
    method: "POST",
    body: JSON.stringify({ username, password })
  }).then((data) => {
    setAuthToken(data.token, persist ?? true);
    rememberAuthUsername(data.user.username);
    return data;
  });
}

export function register(input: {
  username: string;
  password: string;
  email?: string;
  display_name?: string;
  persist?: boolean;
}): Promise<{ token: string; user: AuthUser }> {
  const { persist, ...body } = input;
  return request<{ token: string; user: AuthUser }>("/api/auth/register", {
    method: "POST",
    body: JSON.stringify(body)
  }).then((data) => {
    setAuthToken(data.token, persist ?? true);
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

export type CookiePlatform = "youtube" | "bilibili" | "zhihu" | "xiaohongshu" | "twitter" | "zlibrary";

export type CookieAccountInfo = {
  valid: boolean | null;
  account_id: string | null;
  account_name: string | null;
  avatar_url: string | null;
  detail: string | null;
  verified_at: string | null;
};

export type CookieStatus = {
  platform: CookiePlatform;
  exists: boolean;
  count: number;
  updated_at: string | null;
  account?: CookieAccountInfo | null;
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
    smtp: {
      host: string;
      port: number;
      from: string;
      user: string;
      use_tls: boolean;
      configured: boolean;
      password_set: boolean;
    };
  };
};

export type SmtpSettingsView = {
  host: string;
  port: number;
  user: string;
  from: string;
  use_tls: boolean;
  password_set: boolean;
  configured: boolean;
  defaults: { host: string; port: number; use_tls: boolean };
  env_configured?: boolean;
};

export function getSmtpSettings(): Promise<SmtpSettingsView> {
  return request<SmtpSettingsView>("/api/smtp/settings");
}

export function saveSmtpSettings(input: {
  host?: string;
  port?: number;
  user?: string;
  from_addr?: string;
  password?: string;
  use_tls?: boolean;
  clear_password?: boolean;
}): Promise<SmtpSettingsView & { saved: boolean }> {
  return request("/api/smtp/settings", {
    method: "POST",
    body: JSON.stringify({
      host: input.host,
      port: input.port,
      user: input.user,
      from_addr: input.from_addr,
      password: input.password ?? "",
      use_tls: input.use_tls,
      clear_password: input.clear_password ?? false
    })
  });
}

export function testSmtpSettings(input?: {
  host?: string;
  port?: number;
  user?: string;
  from_addr?: string;
  password?: string;
  use_tls?: boolean;
}): Promise<{ ok: boolean; from?: string; host?: string; error?: string }> {
  return request("/api/smtp/test", {
    method: "POST",
    body: JSON.stringify(
      input
        ? {
            host: input.host,
            port: input.port,
            user: input.user,
            from_addr: input.from_addr,
            password: input.password ?? "",
            use_tls: input.use_tls
          }
        : {}
    )
  });
}

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
  is_bundled_release?: boolean;
  web_url: string;
};

export function getDesktopAppStatus(): Promise<DesktopAppStatus> {
  return request<DesktopAppStatus>("/api/app/desktop");
}

export type AppUpdateStatus = {
  check_enabled: boolean;
  current_version: string;
  latest_version?: string | null;
  has_update: boolean;
  release_url?: string | null;
  download_url?: string | null;
  release_notes?: string | null;
  published_at?: string | null;
  checked_at?: string | null;
  cached?: boolean;
  reason?: string | null;
  error?: string | null;
};

export function getAppUpdateStatus(force = false): Promise<AppUpdateStatus> {
  const query = force ? "?force=true" : "";
  return request<AppUpdateStatus>(`/api/app/update${query}`);
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

export function getCookieStatuses(
  verify = true,
  options?: { quick?: boolean }
): Promise<{ platforms: CookieStatus[] }> {
  const params = new URLSearchParams();
  if (!verify) {
    params.set("verify", "false");
  }
  if (options?.quick === false) {
    params.set("quick", "false");
  }
  const query = params.toString();
  return request<{ platforms: CookieStatus[] }>(
    `/api/user/cookies${query ? `?${query}` : ""}`
  );
}

export function verifyCookiePlatform(
  platform: CookiePlatform
): Promise<{ platform: string; account: CookieAccountInfo }> {
  return request<{ platform: string; account: CookieAccountInfo }>(
    `/api/user/cookies/${platform}/verify`,
    { method: "POST" }
  );
}

export type CookieImportResult = {
  platform: string;
  count: number;
  account?: CookieAccountInfo | null;
};

export type CookieQrLoginView = {
  session_id: string;
  platform: string;
  method: "app_scan" | "browser";
  status: string;
  qr_content: string | null;
  hint: string;
  message?: string | null;
  account?: CookieAccountInfo | null;
  import_result?: CookieImportResult | null;
};

export function startCookieQrLogin(platform: CookiePlatform): Promise<CookieQrLoginView> {
  return request<CookieQrLoginView>(`/api/user/cookies/${platform}/qr/start`, {
    method: "POST"
  });
}

export function pollCookieQrLogin(
  platform: CookiePlatform,
  sessionId: string
): Promise<CookieQrLoginView> {
  return request<CookieQrLoginView>(`/api/user/cookies/${platform}/qr/${sessionId}`);
}

export function cancelCookieQrLogin(
  platform: CookiePlatform,
  sessionId: string
): Promise<{ cancelled: boolean }> {
  return request<{ cancelled: boolean }>(`/api/user/cookies/${platform}/qr/${sessionId}`, {
    method: "DELETE"
  });
}

export function importCookieJson(
  platform: CookiePlatform,
  payload: unknown
): Promise<CookieImportResult> {
  return request<CookieImportResult>(`/api/user/cookies/${platform}/import`, {
    method: "POST",
    body: JSON.stringify({ payload })
  });
}

export async function importCookieFromClipboard(
  platform: CookiePlatform
): Promise<CookieImportResult> {
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
): Promise<CookieImportResult> {
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
  return (await response.json()) as CookieImportResult;
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
  unread: number;
  notes: number;
  papers: number;
  books: number;
  chats: number;
}> {
  const query = new URLSearchParams();
  if (params?.hotlistDate) {
    query.set("hotlist_date", params.hotlistDate);
  }
  if (params?.hotlistSource) {
    query.set("hotlist_source", params.hotlistSource);
  }
  const suffix = query.toString() ? `?${query.toString()}` : "";
  return request<{
    favorites: number;
    trash: number;
    hotlist: number;
    unread: number;
    notes: number;
    papers: number;
    books: number;
    chats: number;
  }>(`/api/knowledge/collections${suffix}`);
}

export function getStatsOverview(days = 90): Promise<StatsOverview> {
  const query = new URLSearchParams({ days: String(days) });
  return request<StatsOverview>(`/api/stats/overview?${query.toString()}`);
}

export function getWeeklyReview(weekOffset = 0): Promise<WeeklyReview> {
  const query = new URLSearchParams({ week_offset: String(weekOffset) });
  return request<WeeklyReview>(`/api/stats/weekly?${query.toString()}`);
}

export function getStatsDaily(day: string): Promise<StatsDailyDigest> {
  const query = new URLSearchParams({ day });
  return request<StatsDailyDigest>(`/api/stats/daily?${query.toString()}`);
}

export function getEveningDigestStatus(): Promise<EveningDigestStatus> {
  return request<EveningDigestStatus>("/api/digest/evening/status");
}

export function getEveningDigestArchive(): Promise<EveningDigestArchive> {
  return request<EveningDigestArchive>("/api/digest/evening/archive");
}

export function getEveningDigest(day?: string): Promise<EveningDigestResponse> {
  const query = day ? new URLSearchParams({ day }) : new URLSearchParams();
  const suffix = query.toString() ? `?${query.toString()}` : "";
  return request<EveningDigestResponse>(`/api/digest/evening${suffix}`);
}

export function markEveningDigestRead(day: string): Promise<EveningDigest> {
  return request<EveningDigest>("/api/digest/evening/read", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ day })
  });
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
  collection?: "feed" | "favorites" | "trash" | "hotlist" | "notes" | "chats" | "books";
  hotlistDate?: string;
  hotlistSource?: HotlistSource;
  feedDate?: string;
  unreadOnly?: boolean;
  minImportance?: number;
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
  if (params.feedDate) {
    query.set("feed_date", params.feedDate);
  }
  if (params.unreadOnly) {
    query.set("unread_only", "true");
  }
  if (params.minImportance !== undefined && params.minImportance >= 1) {
    query.set("min_importance", String(params.minImportance));
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

export function patchItemImportance(
  rawId: number,
  importance: number | null
): Promise<{ raw_id: number; importance: number | null }> {
  return request(`/api/knowledge/items/${rawId}/note`, {
    method: "PATCH",
    body: JSON.stringify({ importance })
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

export function markItemRead(
  rawId: number
): Promise<{ raw_id: number; read_at: string; is_read: boolean }> {
  return request(`/api/knowledge/items/${rawId}/read`, { method: "POST" });
}

export function patchItemRead(
  rawId: number,
  read: boolean
): Promise<{ raw_id: number; read_at: string | null; is_read: boolean }> {
  return request(`/api/knowledge/items/${rawId}/read`, {
    method: "PATCH",
    body: JSON.stringify({ read })
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

export function createTheme(
  payload: ThemeCreateInput,
  locale: Locale = "zh"
): Promise<{
  theme: { id: number };
  absorb?: { started?: boolean; reason?: string };
}> {
  return request(`/api/knowledge/themes?locale=${locale}`, {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export function updateTheme(
  themeId: number,
  payload: ThemeUpdateInput,
  locale: Locale = "zh"
): Promise<{
  theme: ThemeRow;
  absorb?: { started?: boolean; debounced?: boolean; reason?: string };
}> {
  return request(`/api/knowledge/themes/${themeId}?locale=${locale}`, {
    method: "PATCH",
    body: JSON.stringify(payload)
  });
}

export function absorbThemeFromOther(
  themeId: number,
  locale: Locale = "zh"
): Promise<{ started?: boolean; reason?: string; theme_id?: number }> {
  return request(`/api/knowledge/themes/${themeId}/absorb-from-other?locale=${locale}`, {
    method: "POST"
  });
}

export function absorbThemeFromTheme(
  targetThemeId: number,
  sourceThemeId: number,
  locale: Locale = "zh"
): Promise<{
  started?: boolean;
  reason?: string;
  target_theme_id?: number;
  source_theme_id?: number;
}> {
  return request(
    `/api/knowledge/themes/${targetThemeId}/absorb-from-theme?source_theme_id=${sourceThemeId}&locale=${locale}`,
    { method: "POST" }
  );
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

export function clipKnowledgeItem(payload: {
  url: string;
  title?: string;
  selected_text?: string;
  html_snapshot?: string;
  auto_distill?: boolean;
  clip_source?: "bookmarklet" | "extension" | "manual";
}): Promise<{
  raw_id: number;
  url: string;
  title?: string | null;
  platform: string;
  extract_status: string;
  distilled_id: number | null;
  auto_distill: boolean;
  existing: boolean;
  clip_source: string;
  clip_count: number;
  extract_strategy?: string;
}> {
  return request("/api/knowledge/clip", {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export function getClipStats(): Promise<{
  clipped_items: number;
  distilled_ok: number;
  distilled_fail_or_pending: number;
  clip_success_rate: number;
  distill_fail_rate: number;
  distill_latency_seconds_avg: number;
}> {
  return request("/api/knowledge/clip/stats");
}

export function retryExtract(rawId: number, autoDistill = true): Promise<{
  raw_id: number;
  url: string;
  extract_status: string;
  distilled_id: number | null;
}> {
  const query = autoDistill ? "true" : "false";
  return request(`/api/knowledge/items/${rawId}/retry-extract?auto_distill=${query}`, {
    method: "POST"
  });
}

export function retryDistill(rawId: number, force = true): Promise<{
  raw_id: number;
  distilled_id: number;
  elapsed_ms: number;
}> {
  const query = force ? "true" : "false";
  return request(`/api/knowledge/items/${rawId}/retry-distill?force=${query}`, {
    method: "POST"
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
  twitter_sync_since: string | null;
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
  twitter_sync_since?: string | null;
  enabled_platforms?: string[];
}): Promise<SubscriptionSettings & { saved: boolean }> {
  return request("/api/subscriptions/settings", {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export type SyncSettingsView = {
  zhihu_api_poll_max_followees: number;
  zhihu_api_poll_max_pages: number;
  zhihu_api_poll_backfill_pages: number;
  zhihu_follow_sync_mode: "api" | "rss";
  zhihu_rsshub_base: string;
  youtube_auto_refresh_channels: boolean;
  collections_sync_platforms: string;
  zhihu_auto_refresh_follows: boolean;
  auto_sync_enabled: boolean;
  auto_sync_interval_minutes: number;
  auto_sync_pipeline_batch_size: number;
  collections_sync_enabled: boolean;
  collections_sync_interval_seconds: number;
  bilibili_up_poll_mode: "dynamic" | "space";
  bilibili_up_poll_max_ups_per_run: number;
  bilibili_dynamic_poll_max_pages: number;
  bilibili_dynamic_poll_backfill_max_pages: number;
  bilibili_up_poll_rate_limit_backoff_seconds: number;
  bilibili_up_poll_rate_limit_cooldown_seconds: number;
  rss_backfill_max_items_per_feed: number;
  cold_start_bilibili_dynamic_days: number;
  cold_start_bilibili_dynamic_max_pages: number;
  economist_auto_sync_enabled: boolean;
  economist_auto_sync_interval_minutes: number;
  economist_github_raw_base: string;
  alert_enabled: boolean;
  alert_cooldown_seconds: number;
  alert_webhook_url: string;
  defaults: Record<string, string | number | boolean>;
  user_overrides: Record<string, string | number | boolean>;
};

export function getSyncSettings(): Promise<SyncSettingsView> {
  return request<SyncSettingsView>("/api/sync/settings");
}

export function saveSyncSettings(payload: Partial<SyncSettingsView>): Promise<SyncSettingsView & { saved: boolean }> {
  return request("/api/sync/settings", {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export type ObsidianSettingsView = {
  enabled: boolean;
  vault_path: string;
  inbox_relpath: string;
  archive_relpath: string;
  outbox_relpath: string;
  interval_seconds: number;
  import_mode: "move" | "keep" | "delete";
  auto_distill: boolean;
  writeback_enabled: boolean;
};

export function getObsidianSettings(): Promise<ObsidianSettingsView> {
  return request<ObsidianSettingsView>("/api/obsidian/settings");
}

export function saveObsidianSettings(payload: Partial<ObsidianSettingsView>): Promise<ObsidianSettingsView & { saved: boolean }> {
  return request("/api/obsidian/settings", {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export function runObsidianSync(payload?: {
  limit?: number;
  auto_distill?: boolean;
}): Promise<{
  enabled: boolean;
  reason: string;
  scanned: number;
  imported: number;
  failed: number;
  skipped: number;
  distilled?: number;
  error_count?: number;
  errors?: string[];
}> {
  return request("/api/obsidian/sync", {
    method: "POST",
    body: JSON.stringify(payload ?? {})
  });
}

export function getObsidianSyncStatus(): Promise<{
  running: boolean;
  started_at?: string | null;
  finished_at?: string | null;
  last_report?: Record<string, unknown> | null;
  last_error?: string | null;
  user_id?: number | null;
}> {
  return request("/api/obsidian/sync/status");
}

export type TelegramSettingsView = {
  enabled: boolean;
  sync_mode: "export" | "client";
  export_dir: string;
  api_id: number | null;
  api_hash: string;
  sync_chat_ids: string[];
  interval_seconds: number;
  auto_distill: boolean;
  auto_tag: boolean;
  session_gap_minutes: number;
  min_session_chars: number;
  min_msg_count: number;
  min_substantive_ratio: number;
  prefer_local_llm: boolean;
  session_authorized?: boolean;
  client_ready?: boolean;
  api_configured?: boolean;
};

export type TelegramAccountInfo = {
  valid: boolean | null;
  account_id: string | null;
  account_name: string | null;
  username: string | null;
  avatar_url: string | null;
  detail: string | null;
  verified_at: string | null;
};

export function getTelegramAccount(refresh = false): Promise<TelegramAccountInfo> {
  const query = refresh ? "?refresh=true" : "";
  return request<TelegramAccountInfo>(`/api/telegram/account${query}`);
}

export function logoutTelegram(): Promise<{ ok: boolean; logged_out: boolean }> {
  return request("/api/telegram/auth/logout", { method: "POST" });
}

export function getTelegramSettings(): Promise<TelegramSettingsView> {
  return request<TelegramSettingsView>("/api/telegram/settings");
}

export function saveTelegramSettings(
  payload: Partial<TelegramSettingsView>
): Promise<TelegramSettingsView & { saved: boolean }> {
  return request("/api/telegram/settings", {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export function runTelegramSync(payload?: {
  limit?: number;
  auto_distill?: boolean;
}): Promise<{
  started: boolean;
  running: boolean;
  message?: string;
}> {
  return request("/api/telegram/sync", {
    method: "POST",
    body: JSON.stringify(payload ?? {}),
    direct: true
  });
}

export function getTelegramSyncStatus(): Promise<{
  running: boolean;
  started_at?: string | null;
  finished_at?: string | null;
  last_report?: Record<string, unknown> | null;
  last_error?: string | null;
  user_id?: number | null;
}> {
  return request("/api/telegram/sync/status");
}

export type TelegramDialog = {
  chat_id: string;
  title: string;
  chat_type: string;
  unread_count: number;
};

export function sendTelegramAuthCode(phone: string): Promise<{ phone: string; sent: boolean }> {
  return request("/api/telegram/auth/send-code", {
    method: "POST",
    body: JSON.stringify({ phone })
  });
}

export function signInTelegramAuth(payload: {
  phone: string;
  code: string;
  password?: string;
}): Promise<{ ok: boolean; authorized?: boolean; needs_password?: boolean }> {
  return request("/api/telegram/auth/sign-in", {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export function getTelegramDialogs(limit = 100): Promise<{ dialogs: TelegramDialog[]; count: number }> {
  const query = new URLSearchParams({ limit: String(limit) });
  return request(`/api/telegram/dialogs?${query.toString()}`);
}

export type TelegramQrLoginView = {
  session_id: string;
  status: string;
  url: string | null;
  message?: string | null;
};

export function startTelegramQrLogin(force = false): Promise<TelegramQrLoginView> {
  const query = force ? "?force=true" : "";
  return request<TelegramQrLoginView>(`/api/telegram/auth/qr/start${query}`, { method: "POST" });
}

export function pollTelegramQrLogin(sessionId: string): Promise<TelegramQrLoginView> {
  return request<TelegramQrLoginView>(`/api/telegram/auth/qr/${encodeURIComponent(sessionId)}`);
}

export function cancelTelegramQrLogin(sessionId: string): Promise<TelegramQrLoginView> {
  return request(`/api/telegram/auth/qr/${encodeURIComponent(sessionId)}/cancel`, {
    method: "POST"
  });
}

export function completeTelegramQrPassword(
  sessionId: string,
  password: string
): Promise<{ ok: boolean; authorized?: boolean }> {
  return request(`/api/telegram/auth/qr/${encodeURIComponent(sessionId)}/password`, {
    method: "POST",
    body: JSON.stringify({ password })
  });
}

export type ItemRelation = {
  id: number;
  from_raw_id: number;
  to_raw_id: number;
  relation_type: string;
  confidence?: number | null;
  note?: string | null;
  source: string;
  from_title?: string | null;
  to_title?: string | null;
  from_url?: string | null;
  to_url?: string | null;
  from_platform?: string | null;
  to_platform?: string | null;
  other_item?: KnowledgeItem;
};

export function getItemRelations(rawId: number): Promise<{ items: ItemRelation[]; count: number }> {
  return request(`/api/knowledge/items/${rawId}/relations`);
}

export function createItemRelation(payload: {
  from_raw_id: number;
  to_raw_id: number;
  relation_type?: string;
  note?: string;
  confidence?: number;
}): Promise<{ ok: boolean }> {
  return request("/api/knowledge/relations", {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export function deleteItemRelation(relationId: number, rawId?: number): Promise<{ ok: boolean }> {
  const q = rawId ? `?raw_id=${rawId}` : "";
  return request(`/api/knowledge/relations/${relationId}${q}`, { method: "DELETE" });
}

export type RetrieveHit = {
  raw_id: number;
  score: number;
  score_parts: Record<string, number>;
  item: KnowledgeItem;
};

export function retrieveKnowledge(payload: {
  query?: string;
  from_raw_id?: number;
  mode?: "keyword" | "similar" | "hybrid" | "semantic";
  limit?: number;
  offset?: number;
  theme_id?: number;
  tag_ids?: number[];
  collection?: "feed" | "favorites" | "trash" | "hotlist" | "notes" | "chats" | "books";
  platform?: string;
  source?: string;
}): Promise<{ mode: string; engine: string; total: number; hits: RetrieveHit[] }> {
  return request("/api/knowledge/retrieve", {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export function getRetrieveContext(
  rawIds: number[],
  maxChars = 4000
): Promise<{ contexts: Array<Record<string, unknown>>; count: number }> {
  const query = new URLSearchParams({
    raw_ids: rawIds.join(","),
    max_chars: String(maxChars)
  });
  return request(`/api/knowledge/retrieve/context?${query.toString()}`);
}

export function getObsidianWritebackQueue(params?: {
  status?: "pending" | "processing" | "applied" | "failed" | "skipped";
  limit?: number;
}): Promise<{ items: Array<Record<string, unknown>>; count: number; status: string }> {
  const query = new URLSearchParams();
  if (params?.status) {
    query.set("status", params.status);
  }
  if (params?.limit) {
    query.set("limit", String(params.limit));
  }
  const suffix = query.toString() ? `?${query.toString()}` : "";
  return request(`/api/obsidian/writeback/queue${suffix}`);
}

export function enqueueObsidianWriteback(payload: {
  target_rel_path: string;
  content_md?: string;
  block_anchor?: string;
  link_raw_id?: number;
  relation_type?: string;
  summary?: string;
  context?: string;
  note?: string;
  on1y_url?: string;
  apply_now?: boolean;
}): Promise<Record<string, unknown>> {
  return request("/api/obsidian/writeback", {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export function applyObsidianWriteback(limit = 20): Promise<Record<string, unknown>> {
  return request(`/api/obsidian/writeback/apply?limit=${limit}`, {
    method: "POST"
  });
}

export type PipelineAlert = {
  id: string;
  kind: "rate_limit" | "antibot" | "cookie_expired" | string;
  kind_label: string;
  platform: string;
  worker: string;
  message: string;
  url?: string | null;
  created_at: string;
  acknowledged?: boolean;
};

export function getPipelineAlerts(active = true): Promise<PipelineAlert[]> {
  return request<PipelineAlert[]>(`/api/alerts?active=${active ? "true" : "false"}`);
}

export function acknowledgePipelineAlerts(clearAll = true): Promise<{ cleared: number }> {
  return request(`/api/alerts/ack?clear_all=${clearAll ? "true" : "false"}`, { method: "POST" });
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

export type SubscriptionSyncActivity = {
  running: boolean;
  started_at?: string | null;
  finished_at?: string | null;
  error?: string | null;
  user_id?: number | null;
  mode?: "auto" | "manual" | null;
  backfill?: boolean;
  progress?: ColdStartProgressView | null;
  last_report?: Record<string, unknown> | null;
};

export type AutoSyncSchedulerStatus = {
  enabled?: boolean;
  thread_alive?: boolean;
  next_subscription_tick_at?: string | null;
  startup_delay_seconds?: number;
};

export type FullSyncStatus = {
  running: boolean;
  active?: boolean;
  distill_running?: boolean;
  sync_kind?: "cold_start" | "subscription" | "auto" | null;
  auto_sync_enabled?: boolean;
  auto_sync_scheduler?: AutoSyncSchedulerStatus | null;
  resident_panel?: boolean;
  pending_work?: boolean;
  last_auto_sync_at?: string | null;
  subscription_sync?: SubscriptionSyncActivity | null;
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
  platforms?: Array<"bilibili" | "youtube" | "zhihu" | "twitter">;
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
    twitter?: PlatformSyncReport;
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

export function fetchBookSources(): Promise<BookSourcesFile> {
  return request<BookSourcesFile>("/api/books/sources");
}

export function saveBookSources(payload: BookSourcesFile): Promise<BookSourcesFile> {
  return request<BookSourcesFile>("/api/books/sources", {
    method: "PUT",
    body: JSON.stringify(payload)
  });
}

export function fetchBookSettings(): Promise<BookSettings> {
  return request<BookSettings>("/api/books/settings");
}

export function pickFolderPath(): Promise<{ path: string | null }> {
  return request<{ path: string | null }>("/api/system/pick-folder", { method: "POST" });
}

export function openLocalPath(path: string): Promise<{ ok: boolean }> {
  return request<{ ok: boolean }>("/api/system/open-path", {
    method: "POST",
    body: JSON.stringify({ path })
  });
}

export function fetchShelfCachedFiles(
  itemId: number
): Promise<{ files: { format: string; path: string }[] }> {
  return request<{ files: { format: string; path: string }[] }>(`/api/books/shelf/${itemId}/cached`);
}

export function saveBookSettings(payload: Partial<BookSettings>): Promise<BookSettings> {
  return request<BookSettings>("/api/books/settings", {
    method: "PUT",
    body: JSON.stringify(payload)
  });
}

export function previewAcquireBook(input: {
  title: string;
  author?: string | null;
  translator?: string | null;
  publisher?: string | null;
  isbn?: string | null;
  douban_url?: string | null;
  cover_url?: string | null;
  format?: BookFormat;
}): Promise<BookAcquirePreview> {
  return request<BookAcquirePreview>("/api/books/acquire/preview", {
    method: "POST",
    body: JSON.stringify(input)
  });
}

export function acquireBook(input: {
  title: string;
  author?: string | null;
  translator?: string | null;
  publisher?: string | null;
  isbn?: string | null;
  douban_url?: string | null;
  format?: BookFormat;
  add_to_shelf?: boolean;
  shelf_item_id?: number;
  candidate?: BookAcquireCandidate;
}): Promise<BookAcquireResult> {
  return request<BookAcquireResult>("/api/books/acquire", {
    method: "POST",
    body: JSON.stringify(input),
    direct: true
  });
}

export type BookKindleSendResult = {
  ok: boolean;
  kindle_sent: boolean;
  kindle_status?: "sent" | "skipped" | "failed";
  kindle_detail?: string | null;
  shelf_item?: BookShelfItem | null;
};

export function sendBookShelfToKindle(itemId: number): Promise<BookKindleSendResult> {
  return request<BookKindleSendResult>(`/api/books/shelf/${itemId}/kindle`, {
    method: "POST",
    direct: true
  });
}

export function searchBooks(input: {
  query: string;
  source_ids?: string[];
}): Promise<{ query: string; editions: BookEditionHit[]; links: BookSearchHit[] }> {
  return request<{ query: string; editions: BookEditionHit[]; links: BookSearchHit[] }>(
    "/api/books/search",
    {
      method: "POST",
      body: JSON.stringify(input)
    }
  );
}

export function fetchBookDetail(url: string): Promise<BookWorkDetail> {
  return request<BookWorkDetail>("/api/books/detail", {
    method: "POST",
    body: JSON.stringify({ url })
  });
}

export function fetchBookShelfItem(id: number): Promise<BookShelfItem> {
  return request<BookShelfItem>(`/api/books/shelf/${id}`);
}

export function fetchRelatedShelfBooks(
  id: number,
  limit = 6
): Promise<{ items: KnowledgeItem[]; scope: string; from_raw_id: number | null }> {
  return request<{ items: KnowledgeItem[]; scope: string; from_raw_id: number | null }>(
    `/api/books/shelf/${id}/related?limit=${limit}`
  );
}

export function listBookShelf(status?: BookStatus): Promise<{ items: BookShelfItem[]; total: number }> {
  const query = status ? `?status=${encodeURIComponent(status)}` : "";
  return request<{ items: BookShelfItem[]; total: number }>(`/api/books/shelf${query}`);
}

export function createBookShelfItem(input: {
  title: string;
  author?: string | null;
  status?: BookStatus;
  links: { label: string; url: string }[];
  notes?: string | null;
}): Promise<BookShelfItem> {
  return request<BookShelfItem>("/api/books/shelf", {
    method: "POST",
    body: JSON.stringify(input)
  });
}

export function updateBookShelfItem(
  id: number,
  input: {
    title?: string;
    author?: string | null;
    translator?: string | null;
    publisher?: string | null;
    cover_url?: string | null;
    summary?: string | null;
    status?: BookStatus;
    links?: { label: string; url: string }[];
    notes?: string | null;
    user_note_html?: string | null;
    importance?: number | null;
    theme_slug?: string | null;
    tags?: string[];
    cached_format?: string | null;
  }
): Promise<BookShelfItem> {
  return request<BookShelfItem>(`/api/books/shelf/${id}`, {
    method: "PATCH",
    body: JSON.stringify(input)
  });
}

export type BookUploadResult = {
  ok: boolean;
  format: BookFormat;
  local_path: string;
  original_filename?: string;
  kindle_sent: boolean;
  kindle_status?: "sent" | "skipped" | "failed";
  kindle_detail?: string | null;
  shelf_item?: BookShelfItem | null;
};

export async function uploadBookFile(
  file: File,
  input: { title?: string; author?: string; status?: BookStatus }
): Promise<BookUploadResult> {
  const token = getAuthToken();
  const form = new FormData();
  form.append("file", file);
  form.append("title", input.title ?? "");
  form.append("author", input.author ?? "");
  form.append("status", input.status ?? "reading");
  const response = await fetch(resolveApiUrl("/api/books/upload", true), {
    method: "POST",
    headers: token ? { Authorization: `Bearer ${token}` } : undefined,
    body: form,
    cache: "no-store"
  });
  if (!response.ok) {
    let detail = `upload failed: ${response.status}`;
    try {
      const payload = (await response.json()) as { detail?: string };
      if (payload.detail) detail = payload.detail;
    } catch {
      /* ignore */
    }
    throw new Error(detail);
  }
  return (await response.json()) as BookUploadResult;
}

export type BookFolderSyncResult = {
  enabled: boolean;
  folder?: string;
  imported: number;
  skipped: number;
  errors: string[];
};

export function scanBookFolder(): Promise<BookFolderSyncResult> {
  return request<BookFolderSyncResult>("/api/books/folder-sync/scan", { method: "POST" });
}
export function deleteBookShelfItem(id: number): Promise<{ ok: boolean }> {
  return request<{ ok: boolean }>(`/api/books/shelf/${id}`, { method: "DELETE" });
}

export function listPapers(params: { status?: PaperStatus; query?: string; collectionKey?: string } = {}): Promise<{ items: PaperItem[]; total: number; collections: PaperCollection[] }> {
  const query = new URLSearchParams();
  if (params.status) query.set("status", params.status);
  if (params.query) query.set("query", params.query);
  if (params.collectionKey) query.set("collection_key", params.collectionKey);
  const suffix = query.toString() ? `?${query.toString()}` : "";
  return request<{ items: PaperItem[]; total: number; collections: PaperCollection[] }>(`/api/papers${suffix}`);
}

export function fetchPaper(id: number): Promise<PaperItem> {
  return request<PaperItem>(`/api/papers/item/${id}`);
}

export function createPaper(input: {
  title: string;
  authors?: { name: string; scholar_id?: string; scholar_url?: string }[];
  abstract?: string;
  status?: PaperStatus;
  year?: number;
  venue?: string;
  doi?: string;
  url?: string;
  tags?: string[];
}): Promise<PaperItem> {
  return request<PaperItem>("/api/papers", { method: "POST", body: JSON.stringify(input) });
}

export function updatePaper(
  id: number,
  input: Partial<{
    title: string;
    authors: { name: string; scholar_id?: string; scholar_url?: string }[];
    abstract: string | null;
    status: PaperStatus;
    year: number | null;
    venue: string | null;
    doi: string | null;
    url: string | null;
    pdf_path: string | null;
    citation_count: number | null;
    user_note_html: string | null;
    importance: number | null;
    theme_slug: string | null;
    tags: string[];
  }>
): Promise<PaperItem> {
  return request<PaperItem>(`/api/papers/${id}`, { method: "PATCH", body: JSON.stringify(input) });
}

export function deletePaper(id: number): Promise<{ ok: boolean }> {
  return request<{ ok: boolean }>(`/api/papers/${id}`, { method: "DELETE" });
}

export function fetchRelatedPapers(id: number): Promise<{ items: KnowledgeItem[]; scope: string; from_raw_id: number | null }> {
  return request(`/api/papers/${id}/related`);
}

export function summarizePaper(id: number): Promise<PaperItem> {
  return request<PaperItem>(`/api/papers/${id}/summary`, { method: "POST", direct: true });
}

export function paperFigureUrl(id: number, filename: string): string {
  const token = getAuthToken();
  const suffix = token ? `?access_token=${encodeURIComponent(token)}` : "";
  return resolveApiUrl(`/api/papers/${id}/figures/${encodeURIComponent(filename)}${suffix}`, true);
}
export function fetchPaperSettings(): Promise<PaperSettings> {
  return request<PaperSettings>("/api/papers/settings");
}

export function savePaperSettings(input: Partial<PaperSettings>): Promise<PaperSettings> {
  return request<PaperSettings>("/api/papers/settings", { method: "PUT", body: JSON.stringify(input) });
}

export function scanPaperFolder(): Promise<PaperSyncResult> {
  return request<PaperSyncResult>("/api/papers/folder-sync", { method: "POST" });
}

export function syncZoteroPapers(): Promise<PaperSyncResult> {
  return request<PaperSyncResult>("/api/papers/zotero-sync", { method: "POST", direct: true });
}

export async function uploadPaperFile(
  file: File,
  input: { title?: string; authors?: string; status?: PaperStatus }
): Promise<{ ok: boolean; paper: PaperItem; local_path: string }> {
  const token = getAuthToken();
  const form = new FormData();
  form.append("file", file);
  form.append("title", input.title ?? "");
  form.append("authors", input.authors ?? "");
  form.append("status", input.status ?? "to_read");
  const response = await fetch(resolveApiUrl("/api/papers/upload", true), {
    method: "POST",
    headers: token ? { Authorization: `Bearer ${token}` } : undefined,
    body: form,
    cache: "no-store"
  });
  if (!response.ok) {
    let detail = `upload failed: ${response.status}`;
    try {
      const payload = (await response.json()) as { detail?: string };
      if (payload.detail) detail = payload.detail;
    } catch {
      /* ignore non-JSON errors */
    }
    throw new Error(detail);
  }
  return (await response.json()) as { ok: boolean; paper: PaperItem; local_path: string };
}
