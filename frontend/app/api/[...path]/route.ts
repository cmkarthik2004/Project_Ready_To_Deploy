// Runtime reverse proxy: browser -> Next.js (/api/*) -> FastAPI (BACKEND_URL/api/*).
// BACKEND_URL is read on every request (Next.js rewrites are fixed at build time,
// which would break container deployments). Keeps the auth cookie same-origin.
import type { NextRequest } from "next/server";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

const HOP = new Set(["connection", "keep-alive", "transfer-encoding", "upgrade", "host", "content-length", "accept-encoding"]);

async function proxy(req: NextRequest, ctx: { params: Promise<{ path: string[] }> }) {
  const { path } = await ctx.params;
  const backend = (process.env.BACKEND_URL || "http://127.0.0.1:8000").replace(/\/$/, "");
  const url = `${backend}/api/${path.map(encodeURIComponent).join("/")}${req.nextUrl.search}`;
  const headers = new Headers();
  req.headers.forEach((v, k) => { if (!HOP.has(k.toLowerCase())) headers.set(k, v); });
  const fwd = req.headers.get("x-forwarded-for");
  headers.set("x-forwarded-for", fwd || "unknown");
  const init: RequestInit & { duplex?: "half" } = { method: req.method, headers, redirect: "manual" };
  if (!["GET", "HEAD"].includes(req.method)) { init.body = req.body; init.duplex = "half"; }
  let res: Response;
  try {
    res = await fetch(url, init);
  } catch {
    return Response.json({ detail: "The FinRAG API is not reachable from the web server." }, { status: 502 });
  }
  const out = new Headers();
  res.headers.forEach((v, k) => { if (!HOP.has(k.toLowerCase()) && k.toLowerCase() !== "set-cookie" && k.toLowerCase() !== "content-encoding") out.set(k, v); });
  for (const c of res.headers.getSetCookie()) out.append("set-cookie", c);
  return new Response(res.body, { status: res.status, headers: out });
}

export { proxy as GET, proxy as POST, proxy as PUT, proxy as PATCH, proxy as DELETE };
