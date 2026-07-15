import { NavLink, Outlet } from "react-router-dom";
import {
  FileText,
  FolderOpen,
  LayoutDashboard,
  Scale,
  Search,
} from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "../api/client";

const links = [
  { to: "/", label: "总览", icon: LayoutDashboard, end: true },
  { to: "/search", label: "案例检索", icon: Search },
  { to: "/cases", label: "案例库", icon: FolderOpen },
  { to: "/documents", label: "文档入库", icon: FileText },
  { to: "/review", label: "合规审查", icon: Scale },
];

export function AppLayout() {
  const [healthOk, setHealthOk] = useState<boolean | null>(null);

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

  return (
    <div className="min-h-screen">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-50 focus:rounded-lg focus:bg-white focus:px-3 focus:py-2"
      >
        跳到主内容
      </a>

      <header className="sticky top-0 z-40 border-b border-border/80 bg-white/75 backdrop-blur-xl">
        <div className="mx-auto flex max-w-7xl items-center gap-6 px-4 py-3 sm:px-6">
          <NavLink to="/" className="group flex shrink-0 items-baseline gap-2 no-underline">
            <span className="font-display text-2xl font-bold tracking-tight text-primary transition-colors group-hover:text-primary-deep">
              案库
            </span>
            <span className="hidden text-xs font-medium uppercase tracking-[0.18em] text-muted-fg sm:inline">
              Penalty RAG
            </span>
          </NavLink>

          <nav className="flex min-w-0 flex-1 items-center gap-1 overflow-x-auto" aria-label="主导航">
            {links.map(({ to, label, icon: Icon, end }) => (
              <NavLink
                key={to}
                to={to}
                end={end}
                className={({ isActive }) =>
                  [
                    "inline-flex min-h-11 shrink-0 items-center gap-2 rounded-lg px-3 py-2 text-sm font-medium transition-colors duration-200",
                    isActive
                      ? "bg-primary text-white shadow-sm"
                      : "text-muted-fg hover:bg-muted hover:text-foreground",
                  ].join(" ")
                }
              >
                <Icon className="h-4 w-4" aria-hidden />
                {label}
              </NavLink>
            ))}
          </nav>

          <div className="hidden items-center gap-2 sm:flex" title="API 健康状态">
            <span
              className={[
                "h-2 w-2 rounded-full",
                healthOk == null
                  ? "bg-slate-300"
                  : healthOk
                    ? "bg-accent"
                    : "bg-destructive",
              ].join(" ")}
              aria-hidden
            />
            <span className="text-xs text-muted-fg">
              {healthOk == null ? "检测中" : healthOk ? "服务正常" : "服务异常"}
            </span>
          </div>
        </div>
      </header>

      <main id="main" className="mx-auto max-w-7xl px-4 py-8 sm:px-6 sm:py-10">
        <Outlet />
      </main>

      <footer className="border-t border-border/60 py-8 text-center text-xs text-muted-fg">
        保险监管处罚案例知识库与合规审查系统 · 四路混合召回 + RRF + 精排
      </footer>
    </div>
  );
}
