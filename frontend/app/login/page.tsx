"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { Activity } from "lucide-react";
import { ErrorBox } from "@/components/ui";
import { api } from "@/lib/api";

export default function Login() {
  const r = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const submit = async (e: React.FormEvent) => {
    e.preventDefault(); setBusy(true); setError(null);
    try { await api("/auth/login", { method: "POST", json: { email, password } }); r.push("/"); }
    catch (err) { setError((err as Error).message); } finally { setBusy(false); }
  };
  return (
    <div className="flex min-h-screen items-center justify-center px-4">
      <form onSubmit={submit} className="card w-full max-w-sm p-6">
        <div className="mb-6 flex items-center gap-2"><Activity className="h-6 w-6 text-brand-600" /><span className="text-xl font-semibold">FinRAG</span></div>
        <h1 className="mb-4 text-lg font-semibold">Sign in</h1>
        <ErrorBox error={error} />
        <label className="label" htmlFor="email">Email</label>
        <input id="email" className="input mb-3" type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
        <label className="label" htmlFor="pw">Password</label>
        <input id="pw" className="input mb-5" type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} />
        <button className="btn-primary w-full justify-center" disabled={busy}>{busy ? "Signing in…" : "Sign in"}</button>
        <p className="mt-4 text-center text-sm text-slate-500">No account? <Link className="text-brand-600 hover:underline" href="/register">Create one</Link></p>
      </form>
    </div>
  );
}
