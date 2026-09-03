/** Proxy external book covers through the API (Douban / Z-Library hotlink blocks). */
export function bookCoverSrc(url: string | null | undefined): string | undefined {
  const trimmed = url?.trim();
  if (!trimmed) {
    return undefined;
  }
  const existingProxy = trimmed.match(/^\/api\/books\/cover\/?(?:\?(.*))?$/);
  if (existingProxy) {
    return existingProxy[1] ? `/api/books/cover?${existingProxy[1]}` : "/api/books/cover";
  }
  // Always same-origin relative URL so <img> works in Chrome:
  // - on1y serve (8765): hits FastAPI directly
  // - npm run dev (3000): Next.js rewrites /api/* to the backend
  // Avoids cross-origin img + missing Authorization on <img> requests.
  return `/api/books/cover?url=${encodeURIComponent(trimmed)}`;
}
