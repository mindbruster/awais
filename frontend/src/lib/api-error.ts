import { AxiosError } from "axios";

export function apiError(err: unknown, fallback = "Request failed"): string {
  if (err instanceof AxiosError) {
    const detail = err.response?.data?.detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail) && detail.length) {
      const first = detail[0];
      if (first?.msg) return `${(first.loc ?? []).join(".")}: ${first.msg}`;
    }
  }
  return fallback;
}
