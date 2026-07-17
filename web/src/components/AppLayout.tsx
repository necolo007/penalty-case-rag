import { NavLink, Outlet } from "react-router-dom";
import {
  FileText,
  FolderOpen,
  LayoutDashboard,
  Scale,
  Search,
  ShieldCheck,
} from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "../api/client";

const mainLinks = [
  { to: "/", label: "智能驾驶舱", icon: LayoutDashboard, end: true },
  { to: "/review", label: "智能审查", icon: Scale },
  { to: "/search", label: "智能检索", icon: Search },
  { to: "/cases", label: "处罚案例库", icon: FolderOpen },
  { to: "/documents", label: "数据入库", icon: FileText },
];

export function AppLayout() {
  const [healthOk, setHealthOk] = useState<boolean | null>(null);
  const [mobileOpen, setMobileOpen] = useState(false);

  useEffect(() => {
    let cancelled = false;
    api
      .health()
      .then((h) => {
        if (!cancelled) setHealthOk(h.database);
      })
      .catch(() => {
        if (!cancelled) setHealthOk(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  function navClass({ isActive }: { isActive: boolean }) {
    return [
      "inline-flex min-h-11 w-full items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium transition-colors duration-200",
      isActive
        ? "bg-white text-primary shadow-sm"
        : "text-slate-300 hover:bg-white/10 hover:text-white",
    ].join(" ");
  }

  const sidebar = (
    <>
      <div className="px-5 pb-6 pt-7">
        <NavLink to="/" className="group flex items-center gap-3 no-underline" onClick={() => setMobileOpen(false)}>
          <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-accent text-white shadow-lg">
            <ShieldCheck className="h-5 w-5" aria-hidden />
          </span>
          <span>
            <span className="block font-display text-2xl font-bold leading-none text-white">案库</span>
            <span className="mt-1 block text-[11px] tracking-[0.16em] text-slate-400">PENALTY RAG</span>
          </span>
        </NavLink>
      </div>

      <nav className="flex flex-1 flex-col gap-6 overflow-y-auto px-3 pb-6" aria-label="主导航">
        <div>
          <p className="mb-2 px-3 text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-500">
            核心能力
          </p>
          <div className="space-y-1">
            {mainLinks.map(({ to, label, icon: Icon, end }) => (
              <NavLink key={to} to={to} end={end} className={navClass} onClick={() => setMobileOpen(false)}>
                <Icon className="h-4 w-4 shrink-0" aria-hidden />
                {label}
              </NavLink>
            ))}
          </div>
        </div>
      </nav>

      <div className="border-t border-white/10 px-5 py-4">
        <div className="flex items-center gap-2 text-xs text-slate-400">
          <span
            className={[
              "h-2 w-2 rounded-full",
              healthOk == null ? "bg-slate-500" : healthOk ? "bg-emerald-400" : "bg-red-400",
            ].join(" ")}
            aria-hidden
          />
          {healthOk == null ? "服务检测中" : healthOk ? "服务运行正常" : "服务异常"}
        </div>
      </div>
    </>
  );

  return (
    <div className="min-h-screen lg:flex">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-50 focus:rounded-lg focus:bg-white focus:px-3 focus:py-2"
      >
        跳到主内容
      </a>

      {/* Desktop sidebar */}
      <aside className="sticky top-0 z-40 hidden h-screen w-64 shrink-0 flex-col bg-primary-deep lg:flex">
        {sidebar}
      </aside>

      {/* Mobile top bar */}
      <div className="sticky top-0 z-40 flex items-center justify-between border-b border-border/80 bg-white/90 px-4 py-3 backdrop-blur-xl lg:hidden">
        <NavLink to="/" className="font-display text-xl font-bold text-primary no-underline">
          案库
        </NavLink>
        <button
          type="button"
          className="min-h-11 rounded-xl border border-border px-3 text-sm font-medium"
          aria-expanded={mobileOpen}
          onClick={() => setMobileOpen((v) => !v)}
        >
          {mobileOpen ? "关闭菜单" : "菜单"}
        </button>
      </div>

      {mobileOpen ? (
        <div className="fixed inset-0 z-50 lg:hidden">
          <button
            type="button"
            className="absolute inset-0 bg-black/40"
            aria-label="关闭菜单遮罩"
            onClick={() => setMobileOpen(false)}
          />
          <aside className="relative flex h-full w-72 flex-col bg-primary-deep shadow-2xl">{sidebar}</aside>
        </div>
      ) : null}

      <div className="min-w-0 flex-1">
        <main id="main" className="mx-auto max-w-7xl px-4 py-8 sm:px-6 sm:py-10">
          <Outlet />
        </main>
        <footer className="border-t border-border/60 py-6 text-center text-xs text-muted-fg">
          保险监管处罚案例知识库 · 四路混合召回 + RRF + 精排
        </footer>
      </div>
    </div>
  );
}
