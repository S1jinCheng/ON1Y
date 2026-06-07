import type { CookiePlatform, CookieStatus } from "@/lib/api";

/** Platforms that initial sync can use (collections + subscriptions). */
export const SYNC_COOKIE_PLATFORMS: CookiePlatform[] = ["bilibili", "youtube", "zhihu"];

export function hasSyncCookies(platforms: CookieStatus[]): boolean {
  return SYNC_COOKIE_PLATFORMS.some((key) => platforms.find((p) => p.platform === key)?.exists);
}

export function syncCookieSummary(platforms: CookieStatus[]): CookiePlatform[] {
  return SYNC_COOKIE_PLATFORMS.filter((key) => platforms.find((p) => p.platform === key)?.exists);
}
