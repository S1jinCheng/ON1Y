const AUTH_TOKEN_KEY = "on1y_auth_token";

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
  return localStorage.getItem(AUTH_TOKEN_KEY);
}

export function setAuthToken(token: string | null): void {
  if (typeof window === "undefined") {
    return;
  }
  if (!token) {
    localStorage.removeItem(AUTH_TOKEN_KEY);
    return;
  }
  localStorage.setItem(AUTH_TOKEN_KEY, token);
}

export function clearAuth(): void {
  setAuthToken(null);
}
