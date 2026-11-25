"use client";

import { useState } from "react";
import { Badge, Card, ErrorBox, PageHeader, useApi } from "@/components/ui";
import { api, fmtDate } from "@/lib/api";

type Cfg = { id: string; name: string; provider: string; base_url: string; model_name: string; api_key_env: string | null; api_key_present: boolean; is_active: boolean };
type Me = { email: string; role: string };

export default function SettingsPage() {
  const me = useApi<Me>("/auth/me");
  const limits = useApi<Record<string, unknown>>("/settings/limits");
  const models = useApi<{ configurations: Cfg[]; environment_default: Record<string, unknown> }>("/settings/models");
  const isAdmin = me.data?.role === "admin";
  const users = useApi<{ id: string; email: string; role: string; is_active: boolean; created_at: string }[]>(isAdmin ? "/admin/users" : null, [isAdmin]);
  const audit = useApi<{ id: string; created_at: string; user: string | null; action: string; resource_type: string | null; ip: string | null }[]>(isAdmin ? "/admin/audit-logs?limit=50" : null, [isAdmin]);
  const [f, setF] = useState({ name: "", provider: "NVIDIA NIM", base_url: "https://integrate.api.nvidia.com/v1", model_name: "", api_key_env: "NVIDIA_API_KEY" });
  const [error, setError] = useState<string | null>(null);
  const [test, setTest] = useState<Record<string, unknown> | null>(null);
  const act = async (fn: () => Promise<unknown>) => { setError(null); try { await fn(); models.reload(); users.reload(); } catch (e) { setError((e as Error).message); } };

  return (
    <>
      <PageHeader title="Settings" subtitle="Upload limits, language-model endpoints and (for administrators) users and the audit log. API keys are never stored in the database — only the name of the environment variable that holds them." />
      <ErrorBox error={error} />
      <div className="grid gap-6 lg:grid-cols-2">
        <Card title="Account"><p className="text-sm">{me.data?.email} — role <Badge status={me.data?.role} /></p></Card>
        <Card title="Processing limits">
          <ul className="space-y-1 text-sm">{limits.data && Object.entries(limits.data).map(([k, v]) => <li key={k} className="flex justify-between"><span className="text-slate-500">{k}</span><span>{Array.isArray(v) ? v.join(", ") : String(v)}</span></li>)}</ul>
        </Card>
        <Card title="Language model endpoints" className="lg:col-span-2">
          <p className="mb-3 text-sm text-slate-500">Default (from environment): {String(models.data?.environment_default.provider)} — {String(models.data?.environment_default.model)} at {String(models.data?.environment_default.base_url)}. Any OpenAI-compatible endpoint works (llama.cpp, NVIDIA NIM, vLLM, TensorRT-LLM).</p>
          <table className="table"><thead><tr><th>Name</th><th>Provider</th><th>Model</th><th>Endpoint</th><th>API key env</th><th>Active</th>{isAdmin && <th />}</tr></thead>
            <tbody>{models.data?.configurations.map((c) => (
              <tr key={c.id}><td>{c.name}</td><td>{c.provider}</td><td>{c.model_name}</td><td className="text-xs">{c.base_url}</td>
                <td className="text-xs">{c.api_key_env || "—"} {c.api_key_env && <Badge status={c.api_key_present ? "ok" : "error"} />}</td><td>{c.is_active ? <Badge status="ok" /> : "—"}</td>
                {isAdmin && <td className="whitespace-nowrap text-xs">
                  <button className="text-brand-600 hover:underline" onClick={() => act(() => api(`/settings/models/${c.id}/activate`, { method: "POST" }))}>activate</button>{" · "}
                  <button className="text-brand-600 hover:underline" onClick={async () => { setTest(null); try { setTest(await api(`/settings/models/${c.id}/test`, { method: "POST" })); } catch (e) { setError((e as Error).message); } }}>test</button>{" · "}
                  <button className="text-red-600 hover:underline" onClick={() => act(() => api(`/settings/models/${c.id}`, { method: "DELETE" }))}>delete</button></td>}
              </tr>))}
              {!models.data?.configurations.length && <tr><td colSpan={7} className="text-sm text-slate-500">No additional endpoints configured; the environment default is used.</td></tr>}
            </tbody></table>
          {test && <pre className="mt-3 overflow-auto rounded bg-slate-50 p-2 text-xs dark:bg-slate-800">{JSON.stringify(test, null, 2)}</pre>}
          {isAdmin && (
            <div className="mt-4 grid gap-2 sm:grid-cols-5">
              {(["name", "provider", "base_url", "model_name", "api_key_env"] as const).map((k) => <input key={k} className="input" placeholder={k} value={f[k]} onChange={(e) => setF({ ...f, [k]: e.target.value })} />)}
              <div className="flex gap-2 sm:col-span-5">
                <button className="btn-primary" onClick={() => act(() => api("/settings/models", { method: "POST", json: { ...f, api_key_env: f.api_key_env || null } }))}>Add endpoint</button>
                <button className="btn-ghost" onClick={() => act(() => api("/settings/models/deactivate", { method: "POST" }))}>Use environment default</button>
              </div>
            </div>)}
        </Card>
        {isAdmin && (
          <Card title="Users" className="lg:col-span-2">
            <table className="table"><thead><tr><th>Email</th><th>Role</th><th>Active</th><th>Created</th><th>Change role</th></tr></thead>
              <tbody>{users.data?.map((u) => (
                <tr key={u.id}><td>{u.email}</td><td><Badge status={u.role} /></td><td>{String(u.is_active)}</td><td>{fmtDate(u.created_at)}</td>
                  <td><select className="input !w-auto !py-1 text-xs" value={u.role} onChange={(e) => act(() => api(`/admin/users/${u.id}`, { method: "PATCH", json: { role: e.target.value, is_active: u.is_active } }))}>
                    {["admin", "analyst", "viewer"].map((r) => <option key={r}>{r}</option>)}</select></td></tr>))}</tbody></table>
          </Card>)}
        {isAdmin && (
          <Card title="Audit log (latest 50)" className="lg:col-span-2">
            <div className="max-h-80 overflow-auto"><table className="table"><thead><tr><th>Time</th><th>User</th><th>Action</th><th>Resource</th><th>IP</th></tr></thead>
              <tbody>{audit.data?.map((a) => <tr key={a.id}><td className="whitespace-nowrap text-xs">{fmtDate(a.created_at)}</td><td className="text-xs">{a.user || "—"}</td><td className="text-xs">{a.action}</td><td className="text-xs">{a.resource_type || "—"}</td><td className="text-xs">{a.ip || "—"}</td></tr>)}</tbody></table></div>
          </Card>)}
      </div>
    </>
  );
}
