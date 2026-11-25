"use client";

import clsx from "clsx";
import {
  Activity, BarChart3, BookOpen, ClipboardCheck, Cpu, FileSearch, FileText, GitCompare, LayoutDashboard, LogOut, Menu,
  MessageSquareText, Moon, Percent, PieChart, Settings, Sun, Upload, X,
} from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";
import { api } from "@/lib/api";

export const NAV = [
  { href: "/dashboard", label: "Financial Dashboard", icon: PieChart },
  { href: "/", label: "Processing Overview", icon: LayoutDashboard },
  { href: "/upload", label: "Upload Documents", icon: Upload },
  { href: "/documents", label: "Document Library", icon: BookOpen },
  { href: "/chat", label: "AI Financial Chat", icon: MessageSquareText },
  { href: "/analysis", label: "Document Analysis", icon: FileSearch },
  { href: "/analytics", label: "Financial Analytics", icon: BarChart3 },
  { href: "/compare", label: "Compare Documents", icon: GitCompare },
  { href: "/ratios", label: "Financial Ratios", icon: Percent },
  { href: "/status", label: "AI Model & RAG Status", icon: Cpu },
  { href: "/evaluation", label: "Evaluation", icon: ClipboardCheck },
  { href: "/reports", label: "Reports", icon: FileText },
  { href: "/settings", label: "Settings", icon: Settings },
];

type Me = { email: string; role: string; full_name: string | null };

export default function AppShell({ children }: { children: ReactNode }) {
  const path = usePathname();
  const router = useRouter();
  const [me, setMe] = useState<Me | null>(null);
  const [open, setOpen] = useState(false);
  const [dark, setDark] = useState(false);
  const bare = path.startsWith("/login") || path.startsWith("/register");

  useEffect(() => {
    let d = false;
    try { d = localStorage.getItem("finrag-theme") === "dark" || (!localStorage.getItem("finrag-theme") && matchMedia("(prefers-color-scheme: dark)").matches); } catch {}
    setDark(d);
    document.documentElement.classList.toggle("dark", d);
  }, []);
  useEffect(() => { if (!bare) api<Me>("/auth/me").then(setMe).catch(() => {}); }, [bare, path]);
  useEffect(() => { setOpen(false); }, [path]);

  const toggle = () => {
    const d = !dark;
    setDark(d);
    document.documentElement.classList.toggle("dark", d);
    try { localStorage.setItem("finrag-theme", d ? "dark" : "light"); } catch {}
  };
  const logout = async () => { await api("/auth/logout", { method: "POST" }); router.push("/login"); };

  if (bare) return <>{children}</>;
  const nav = (
    <nav className="flex flex-col gap-0.5 p-3">
      {NAV.map(({ href, label, icon: Icon }) => {
        const active = href === "/" ? path === "/" : path.startsWith(href);
        return (
          <Link key={href} href={href} className={clsx("flex items-center gap-3 rounded-lg px-3 py-2 text-sm",
            active ? "bg-brand-50 font-semibold text-brand-700 dark:bg-brand-700/20 dark:text-brand-100" : "text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800")}>
            <Icon className="h-4 w-4" /> {label}
          </Link>
        );
      })}
    </nav>
  );
  return (
    <div className="min-h-screen lg:flex">
      <aside className="hidden w-64 shrink-0 border-r border-slate-200 bg-white lg:sticky lg:top-0 lg:block lg:h-screen lg:overflow-y-auto dark:border-slate-800 dark:bg-slate-900">
        <div className="flex items-center gap-2 px-5 py-5"><Activity className="h-6 w-6 text-brand-600" /><span className="text-lg font-semibold">FinRAG</span></div>
        {nav}
      </aside>
      {open && (
        <div className="fixed inset-0 z-40 lg:hidden">
          <div className="absolute inset-0 bg-black/40" onClick={() => setOpen(false)} />
          <aside className="absolute inset-y-0 left-0 w-72 overflow-y-auto bg-white dark:bg-slate-900">
            <div className="flex items-center justify-between px-5 py-4"><span className="text-lg font-semibold">FinRAG</span>
              <button aria-label="Close menu" onClick={() => setOpen(false)}><X className="h-5 w-5" /></button></div>
            {nav}
          </aside>
        </div>
      )}
      <div className="min-w-0 flex-1">
        <header className="sticky top-0 z-30 flex items-center justify-between border-b border-slate-200 bg-white/90 px-4 py-3 backdrop-blur dark:border-slate-800 dark:bg-slate-900/90">
          <button className="lg:hidden" aria-label="Open menu" onClick={() => setOpen(true)}><Menu className="h-5 w-5" /></button>
          <div className="hidden text-sm text-slate-500 lg:block">Financial Document Intelligence</div>
          <div className="flex items-center gap-3">
            <button onClick={toggle} aria-label="Toggle dark mode" className="rounded-lg p-2 hover:bg-slate-100 dark:hover:bg-slate-800">
              {dark ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
            </button>
            {me && <span className="hidden text-sm sm:inline">{me.email} <span className="rounded bg-slate-100 px-1.5 py-0.5 text-xs dark:bg-slate-800">{me.role}</span></span>}
            <button onClick={logout} className="btn-ghost !py-1.5"><LogOut className="h-4 w-4" /> <span className="hidden sm:inline">Sign out</span></button>
          </div>
        </header>
        <main className="mx-auto max-w-7xl px-4 py-6 sm:px-6">{children}</main>
      </div>
    </div>
  );
}
