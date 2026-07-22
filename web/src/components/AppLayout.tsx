import { NavLink, Outlet, useLocation } from "react-router-dom";
import {
  FileText,
  FolderOpen,
  LayoutDashboard,
  Loader2,
  Scale,
  Search,
  ShieldCheck,
} from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "../api/client";
import { useReviewSession } from "../lib/reviewSession";

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
  const review = useReviewSession();
  const location = useLocation();
  const reviewBusy = review.loading;
  const reviewReady =
    review.justFinished && !review.loading && Boolean(review.review || review.materialReport);
  const showAwayBanner = (reviewBusy || reviewReady) && !location.pathname.startsWith("/review");

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
                <span className="flex-1 text-left">{label}</span>
                {to === "/review" && reviewBusy ? (
                  <span
                    className="inline-flex items-center gap-1 rounded-md bg-sky-500/20 px-1.5 py-0.5 text-[10px] font-semibold text-sky-200"
                    aria-label="审查进行中"
                  >
                    <Loader2 className="h-3 w-3 animate-spin" aria-hidden />
                    分析中
                  </span>
                ) : null}
                {to === "/review" && reviewReady ? (
                  <span
                    className="rounded-md bg-emerald-500/25 px-1.5 py-0.5 text-[10px] font-semibold text-emerald-200"
                    aria-label="审查已完成"
                  >
                    已完成
                  </span>
                ) : null}
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

      <aside className="sticky top-0 z-40 hidden h-screen w-64 shrink-0 flex-col bg-primary-deep lg:flex">
        {sidebar}
      </aside>

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
        {showAwayBanner ? (
          <div
            className={[
              "border-b px-4 py-2.5 text-sm sm:px-6",
              reviewBusy
                ? "border-sky-200 bg-sky-50 text-sky-950"
                : "border-emerald-200 bg-emerald-50 text-emerald-950",
            ].join(" ")}
            role="status"
            aria-live="polite"
          >
            <div className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-2">
              <span className="inline-flex items-center gap-2">
                {reviewBusy ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : null}
                {reviewBusy
                  ? "智能审查仍在后台分析，返回后可继续查看进度与结果。"
                  : "智能审查已完成，点击返回查看报告。"}
              </span>
              <NavLink
                to="/review"
                className="inline-flex min-h-9 items-center rounded-lg bg-white/80 px-3 text-xs font-semibold text-primary no-underline ring-1 ring-border hover:bg-white"
              >
                返回智能审查
              </NavLink>
            </div>
          </div>
        ) : null}
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
