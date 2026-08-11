/**
 * Resolve an image reference from the API into a URL the browser can fetch.
 *
 * Two shapes arrive, depending on how the backend is storing files:
 *
 *   object storage → an absolute URL ("https://images.example.com/products/x.png").
 *                    Already complete; prefixing the API host would produce
 *                    "http://localhost:8000https://..." and every photo would
 *                    break the moment the shop moved off local disk.
 *   local disk     → a backend-relative path ("/static/x.png"), which needs the
 *                    API root in front of it.
 */
export function staticUrl(path: string | null | undefined): string {
  if (!path) return "";
  if (/^(https?:)?\/\//i.test(path) || path.startsWith("data:")) return path;
  const base = import.meta.env.VITE_API_BASE_URL ?? "";
  const root = base.replace(/\/api\/v1\/?$/, "");
  return `${root}${path}`;
}
