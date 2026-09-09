const AUTH_TOKEN_KEY = "on1y_auth_token";
const SESSION_AUTH_TOKEN_KEY = "on1y_session_auth_token";
const RECENT_USERNAMES_KEY = "on1y_recent_usernames";
const RECENT_USERNAMES_MAX = 8;

export type AuthUser = {
  id: number;
  username: string;
  email: string | null;
  display_name: string;
  created_at: string | null;
};

export function getAuthToken(): string | null {
  if (typeof window === "undefined") {
    return null;
  }
  return sessionStorage.getItem(SESSION_AUTH_TOKEN_KEY) ?? localStorage.getItem(AUTH_TOKEN_KEY);
}

export function setAuthToken(token: string | null, persist = true): void {
  if (typeof window === "undefined") {
    return;
  }
  localStorage.removeItem(AUTH_TOKEN_KEY);
  sessionStorage.removeItem(SESSION_AUTH_TOKEN_KEY);
  if (!token) {
    return;
  }
  if (persist) {
    localStorage.setItem(AUTH_TOKEN_KEY, token);
  } else {
    sessionStorage.setItem(SESSION_AUTH_TOKEN_KEY, token);
  }
}

export function clearAuth(): void {
  setAuthToken(null);
}

export function rememberAuthUsername(username: string): void {
  if (typeof window === "undefined") {
    return;
  }
  const name = username.trim();
  if (!name) {
    return;
  }
  const prev = getRecentAuthUsernames().filter((u) => u.toLowerCase() !== name.toLowerCase());
  const next = [name, ...prev].slice(0, RECENT_USERNAMES_MAX);
  localStorage.setItem(RECENT_USERNAMES_KEY, JSON.stringify(next));
}

export function getRecentAuthUsernames(): string[] {
  if (typeof window === "undefined") {
    return [];
  }
  try {
    const raw = localStorage.getItem(RECENT_USERNAMES_KEY);
    if (!raw) {
      return [];
    }
    const parsed = JSON.parse(raw) as unknown;
    if (!Array.isArray(parsed)) {
      return [];
    }
    return parsed.map((value) => String(value).trim()).filter(Boolean);
  } catch {
    return [];
  }
}