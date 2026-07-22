import { useRef, useState, type DragEvent, type FormEvent } from "react";
import { FileUp, Loader2, Scale, X } from "lucide-react";
import { Link } from "react-router-dom";
import { ErrorAlert, TagChip } from "../components/ui";
import { ThinkingPanel } from "../components/ThinkingPanel";
import { reviewSession, useReviewSession } from "../lib/reviewSession";

export function ReviewPage() {
  const s = useReviewSession();
  const [dragOver, setDragOver] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  function onSentenceReview(e: FormEvent) {
    e.preventDefault();
    void reviewSession.startSentenceReview();
  }

  function onMaterialReview(e: FormEvent) {
    e.preventDefault();
    void reviewSession.startMaterialReview();
  }

  function onDrop(e: DragEvent) {
    e.preventDefault();
    setDragOver(false);
    const file = e.dataTransfer.files?.[0];
    if (file) void reviewSession.startMaterialFile(file);
  }

  return (
    <div className="space-y-8">
      <header className="rise-in relative overflow-hidden rounded-3xl border border-border/50 bg-primary-deep px-6 py-8 text-white sm:px-8">
        <img
          src="/hero-ai-hub.png"
          alt=""
          className="pointer-events-none absolute inset-0 h-full w-full object-cover opacity-45"
          aria-hidden
        />
        <div className="absolute inset-0 bg-gradient-to-r from-primary-deep via-primary-deep/85 to-primary/40" aria-hidden />
        <div className="relative max-w-2xl">
          <h1 className="font-display text-4xl font-bold">智能审查</h1>
          <p className="mt-2 text-sm text-white/85 sm:text-base">
            核心能力：审查整篇材料或单句表述，生成可追溯合规意见；思考过程可折叠回看。
            切换其他页面时任务会在后台继续，结果自动保留。
          </p>
        </div>
      </header>

      {s.loading ? (
        <div
          className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-sky-200 bg-sky-50 px-4 py-3 text-sm text-sky-900"
          role="status"
          aria-live="polite"
        >
          <span>审查正在后台进行中，切换页面不会中断；完成后结果会自动出现在此处。</span>
          <Loader2 className="h-4 w-4 shrink-0 animate-spin" aria-hidden />
        </div>
      ) : null}

      {s.justFinished && (s.review || s.materialReport) ? (
        <div
          className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-900"
          role="status"
        >
          <span>审查已完成，结果已恢复。</span>
          <button
            type="button"
            className="inline-flex min-h-9 min-w-9 items-center justify-center rounded-lg hover:bg-emerald-100"
            aria-label="关闭提示"
            onClick={() => reviewSession.dismissJustFinished()}
          >
            <X className="h-4 w-4" />
          </button>
        </div>
      ) : null}

      <div className="inline-flex rounded-xl border border-border bg-white p-1" role="tablist">
        {(
          [
            ["material", "材料审查"],
            ["sentence", "单句审查"],
          ] as const
        ).map(([id, label]) => (
          <button
            key={id}
            type="button"
            role="tab"
            aria-selected={s.tab === id}
            onClick={() => reviewSession.setTab(id)}
            className={[
              "min-h-11 rounded-lg px-4 text-sm font-semibold transition",
              s.tab === id ? "bg-primary text-white" : "text-muted-fg hover:text-foreground",
            ].join(" ")}
          >
            {label}
          </button>
        ))}
      </div>

      {s.tab === "sentence" ? (
        <form onSubmit={onSentenceReview} className="surface rounded-3xl p-6">
          <label htmlFor="review-q" className="mb-2 block text-sm font-semibold">
            待审查表述
          </label>
          <textarea
            id="review-q"
            rows={4}
            value={s.query}
            onChange={(e) => reviewSession.setQuery(e.target.value)}
            className="w-full rounded-2xl border border-border bg-white p-4 text-sm leading-relaxed outline-none focus:border-primary focus:ring-4 focus:ring-primary/10"
            placeholder="（示例）购买本产品即可领取价值1000元体检卡。"
          />
          <p className="mt-2 text-xs text-muted-fg">
            也可粘贴业务话术、宣传文案或可疑表述进行风险研判。
          </p>
          <div className="mt-4 flex flex-wrap items-end gap-4">
            <div>
              <label htmlFor="topk" className="mb-1 block text-xs font-semibold text-muted-fg">
                参考案例数
              </label>
              <input
                id="topk"
                type="number"
                min={1}
                max={20}
                value={s.topK}
                onChange={(e) => reviewSession.setTopK(Number(e.target.value) || 5)}
                className="min-h-11 w-28 rounded-xl border border-border bg-white px-3 text-sm"
              />
            </div>
            <button
              type="submit"
              disabled={s.loading}
              className="inline-flex min-h-11 items-center gap-2 rounded-xl bg-primary px-5 text-sm font-semibold text-white hover:bg-primary-deep disabled:opacity-60"
            >
              {s.loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Scale className="h-4 w-4" />}
              生成审查意见
            </button>
          </div>
        </form>
      ) : (
        <form onSubmit={onMaterialReview} className="surface space-y-4 rounded-3xl p-6">
          <div>
            <label htmlFor="scene" className="mb-1.5 block text-xs font-semibold text-muted-fg">
              业务场景（可选）
            </label>
            <input
              id="scene"
              value={s.scene}
              onChange={(e) => reviewSession.setScene(e.target.value)}
              className="min-h-11 w-full max-w-md rounded-xl border border-border bg-white px-3 text-sm outline-none focus:border-primary focus:ring-4 focus:ring-primary/10"
              placeholder="如：产品宣传 / 代理人话术"
            />
          </div>

          <div
            onDragOver={(e) => {
              e.preventDefault();
              setDragOver(true);
            }}
            onDragLeave={() => setDragOver(false)}
            onDrop={onDrop}
            className={[
              "rounded-2xl border-2 border-dashed px-6 py-10 text-center transition duration-200",
              dragOver ? "border-primary bg-primary/5" : "border-border bg-slate-50/80",
            ].join(" ")}
          >
            <FileUp className="mx-auto h-8 w-8 text-primary" aria-hidden />
            <p className="mt-3 text-sm font-semibold text-foreground">拖拽 PDF / Word 到此处上传</p>
            <p className="mt-1 text-xs text-muted-fg">支持 .pdf / .docx / .txt / .pptx</p>
            <label className="mt-4 inline-flex min-h-11 cursor-pointer items-center gap-2 rounded-xl border border-border bg-white px-4 text-sm font-medium hover:bg-muted">
              选择文件
              <input
                ref={fileRef}
                type="file"
                accept=".txt,.docx,.pdf,.pptx"
                className="sr-only"
                onChange={(e) => {
                  const f = e.target.files?.[0];
                  if (f) void reviewSession.startMaterialFile(f);
                  e.target.value = "";
                }}
              />
            </label>
          </div>

          <div>
            <label htmlFor="mat" className="mb-1.5 block text-sm font-semibold">
              或粘贴材料文本
            </label>
            <textarea
              id="mat"
              rows={8}
              value={s.material}
              onChange={(e) => reviewSession.setMaterial(e.target.value)}
              className="w-full rounded-2xl border border-border bg-white p-4 text-sm leading-relaxed outline-none focus:border-primary focus:ring-4 focus:ring-primary/10"
              placeholder="（示例）购买本产品即可领取价值1000元体检卡。"
            />
          </div>
          <button
            type="submit"
            disabled={s.loading}
            className="inline-flex min-h-11 items-center gap-2 rounded-xl bg-primary px-5 text-sm font-semibold text-white hover:bg-primary-deep disabled:opacity-60"
          >
            {s.loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Scale className="h-4 w-4" />}
            开始智能分析
          </button>
        </form>
      )}

      <ThinkingPanel
        active={s.loading}
        finished={s.thinkFinished}
        queryHint={s.thinkHint}
        elapsedMs={s.thinkElapsedMs}
        startedAt={s.thinkStartedAt}
      />

      {s.error ? <ErrorAlert message={s.error} /> : null}

      {s.review ? (
        <section className="surface rise-in space-y-5 rounded-3xl border border-border bg-white p-6 shadow-[var(--shadow-soft)]">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h2 className="font-display text-2xl font-semibold">审查报告</h2>
            <span className="font-mono text-xs text-muted-fg">{s.review.review_id}</span>
          </div>

          <div>
            <h3 className="text-sm font-semibold text-muted-fg">风险类型判定</h3>
            <div className="mt-2 flex flex-wrap gap-1.5">
              {(s.review.risk_types ?? []).length ? (
                (s.review.risk_types ?? []).map((t) => <TagChip key={t}>{t}</TagChip>)
              ) : (
                <span className="text-sm text-muted-fg">未返回风险类型</span>
              )}
            </div>
          </div>

          <div>
            <h3 className="text-sm font-semibold text-muted-fg">合规整改建议</h3>
            <p className="mt-2 whitespace-pre-wrap rounded-xl bg-slate-50 px-4 py-3 text-sm leading-relaxed text-slate-700">
              {s.review.suggestion || "（未返回建议，请确认 LLM 已配置）"}
            </p>
          </div>

          {s.review.case_analysis && s.review.case_analysis.length > 0 ? (
            <div>
              <h3 className="text-sm font-semibold text-muted-fg">相似案例 Top5</h3>
              <ul className="mt-2 space-y-3">
                {s.review.case_analysis.slice(0, 5).map((a, i) => {
                  const id = String(a.case_id ?? i);
                  const fb = s.feedback[id];
                  return (
                    <li key={id} className="rounded-xl border border-border/80 bg-slate-50/80 px-4 py-3">
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <Link
                          to={`/cases/${encodeURIComponent(String(a.case_id ?? ""))}`}
                          className="font-mono text-xs font-semibold text-primary no-underline hover:underline"
                        >
                          {a.case_id || "未知案例"}
                        </Link>
                        <div className="flex gap-2">
                          <button
                            type="button"
                            onClick={() =>
                              reviewSession.setFeedback({ ...s.feedback, [id]: "pass" })
                            }
                            className={[
                              "min-h-9 rounded-lg px-2.5 text-xs font-medium",
                              fb === "pass" ? "bg-accent text-white" : "border border-border bg-white",
                            ].join(" ")}
                          >
                            复核通过
                          </button>
                          <button
                            type="button"
                            onClick={() =>
                              reviewSession.setFeedback({ ...s.feedback, [id]: "wrong" })
                            }
                            className={[
                              "min-h-9 rounded-lg px-2.5 text-xs font-medium",
                              fb === "wrong" ? "bg-destructive text-white" : "border border-border bg-white",
                            ].join(" ")}
                          >
                            标记误判
                          </button>
                        </div>
                      </div>
                      <p className="mt-2 text-sm text-slate-700">{a.similarity_reason || "—"}</p>
                    </li>
                  );
                })}
              </ul>
            </div>
          ) : null}
          <p className="text-xs text-muted-fg">耗时 {s.review.took_ms} ms</p>
        </section>
      ) : null}

      {s.materialReport ? (
        <section className="surface rise-in space-y-4 rounded-3xl bg-white p-6">
          <h2 className="font-display text-2xl font-semibold">材料审查报告</h2>
          {s.materialReport.overall_risk ? (
            <p className="text-sm">
              <span className="text-muted-fg">整体风险：</span>
              <strong className="text-primary">{String(s.materialReport.overall_risk)}</strong>
            </p>
          ) : null}
          {s.materialReport.summary ? (
            <p className="whitespace-pre-wrap text-sm leading-relaxed text-slate-700">
              {String(s.materialReport.summary)}
            </p>
          ) : null}
          {Array.isArray(s.materialReport.risk_sentences) && s.materialReport.risk_sentences.length > 0 ? (
            <ul className="space-y-3">
              {s.materialReport.risk_sentences.map((item, i) => (
                <li key={i} className="rounded-xl border border-border/80 bg-slate-50 px-4 py-3">
                  {item.risk_level ? (
                    <span className="mb-2 inline-block rounded-md bg-red-50 px-2 py-0.5 text-xs font-semibold text-destructive">
                      {String(item.risk_level)}
                    </span>
                  ) : null}
                  <p className="text-sm text-foreground">{item.text || JSON.stringify(item)}</p>
                  {item.suggestion ? (
                    <p className="mt-2 text-xs text-muted-fg">{String(item.suggestion)}</p>
                  ) : null}
                </li>
              ))}
            </ul>
          ) : (
            <pre className="overflow-x-auto rounded-xl bg-muted/70 p-4 text-xs text-slate-700">
              {JSON.stringify(s.materialReport, null, 2)}
            </pre>
          )}
        </section>
      ) : null}
    </div>
  );
}
