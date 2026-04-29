/**
 * Resolve a backend-relative path (e.g. "/static/foo.png" returned by the API)
 * into a URL the browser can fetch. Works in both dev and prod:
 *
 *   dev:  VITE_API_BASE_URL = "http://localhost:8000/api/v1"
 *         → strip "/api/v1" → "http://localhost:8000" + "/static/foo.png"
 *
 *   prod: VITE_API_BASE_URL = "/api/v1"
 *         → strip "/api/v1" → "" + "/static/foo.png" (nginx proxies it)
 */
export function staticUrl(path: string | null | undefined): string {
  if (!path) return "";
  const base = import.meta.env.VITE_API_BASE_URL ?? "";
  const root = base.replace(/\/api\/v1\/?$/, "");
  return `${root}${path}`;
}
