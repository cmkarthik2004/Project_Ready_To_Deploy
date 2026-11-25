"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { ErrorBox } from "@/components/ui";
import { api } from "@/lib/api";

export default function Register() {
  const r = useRouter();
  const [f, setF] = useState({ email: "", password: "", full_name: "" });
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const submit = async (e: React.FormEvent) => {
    e.preventDefault(); setBusy(true); setError(null);
    try { await api("/auth/register", { method: "POST", json: f }); r.push("/"); }
    catch (err) { setError((err as Error).message); } finally { setBusy(false); }
  };
  return (
    <div className="flex min-h-screen items-center justify-center px-4">
      <form onSubmit={submit} className="card w-full max-w-sm p-6">
        <h1 className="mb-1 text-lg font-semibold">Create your FinRAG account</h1>
        <p className="mb-4 text-xs text-slate-500">The first account on a new installation becomes the administrator.</p>
        <ErrorBox error={error} />
        <label className="label">Full name (optional)</label>
        <input className="input mb-3" value={f.full_name} onChange={(e) => setF({ ...f, full_name: e.target.value })} />
        <label className="label">Email</label>
        <input className="input mb-3" type="email" required value={f.email} onChange={(e) => setF({ ...f, email: e.target.value })} />
        <label className="label">Password</label>
        <input className="input mb-1" type="password" required minLength={10} autoComplete="new-password" value={f.password} onChange={(e) => setF({ ...f, password: e.target.value })} />
        <p className="mb-5 text-xs text-slate-500">At least 10 characters, with upper- and lower-case letters and a digit.</p>
        <button className="btn-primary w-full justify-center" disabled={busy}>{busy ? "Creating…" : "Create account"}</button>
        <p className="mt-4 text-center text-sm text-slate-500">Have an account? <Link className="text-brand-600 hover:underline" href="/login">Sign in</Link></p>
      </form>
    </div>
  );
}
