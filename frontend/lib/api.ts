// Thin fetch wrapper. All data shown in the UI comes from these calls; there is
// no mock data anywhere in the frontend.
export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message); }
}

function messageFrom(body: unknown, status: number): string {
  if (body && typeof body === "object" && "detail" in body) {
    const d = (body as { detail: unknown }).detail;
    if (typeof d === "string") return d;
    if (Array.isArray(d)) return d.map((x) => (x as { msg?: string }).msg ?? JSON.stringify(x)).join("; ");
    return JSON.stringify(d);
  }
  return `Request failed (HTTP ${status})`;
}

export async function api<T = unknown>(path: string, init: RequestInit & { json?: unknown } = {}): Promise<T> {
  const { json, headers, ...rest } = init;
  const res = await fetch(`/api${path}`, {
    credentials: "same-origin",
    ...rest,
    headers: { ...(json !== undefined ? { "Content-Type": "application/json" } : {}), ...(headers || {}) },
    body: json !== undefined ? JSON.stringify(json) : rest.body,
  });
  const ct = res.headers.get("content-type") || "";
  const body = ct.includes("application/json") ? await res.json().catch(() => null) : await res.text();
  if (res.status === 401 && typeof window !== "undefined" && !location.pathname.startsWith("/login") && !location.pathname.startsWith("/register")) {
    location.href = "/login";
  }
  if (!res.ok) throw new ApiError(res.status, messageFrom(body, res.status));
  return body as T;
}

export const fmtBytes = (n?: number | null) =>
  n == null ? "—" : n < 1024 ? `${n} B` : n < 1048576 ? `${(n / 1024).toFixed(1)} KB` : `${(n / 1048576).toFixed(1)} MB`;

export const fmtDate = (s?: string | null) => (s ? new Date(s).toLocaleString() : "—");

export const ND = "Not detected";

export function fmtResult(v: string | null, unit: string) {
  if (v == null) return "—";
  const n = Number(v);
  const s = Number.isFinite(n) ? n.toLocaleString(undefined, { maximumFractionDigits: 2 }) : v;
  return unit === "percent" ? `${s}%` : unit === "times" ? `${s}×` : s;
}
