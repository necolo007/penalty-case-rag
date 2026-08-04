import { useEffect, useMemo, useRef, useState, type DragEvent, type FormEvent, type ReactNode } from "react";
import { FileUp, Loader2, Scale, X } from "lucide-react";
import { Link, useSearchParams } from "react-router-dom";
import { ErrorAlert, TagChip } from "../components/ui";
import { ThinkingPanel } from "../components/ThinkingPanel";
import { reviewSession, useReviewSession } from "../lib/reviewSession";

function riskTone(level?: string): string {
  const lv = (level || "").toLowerCase();
  if (lv === "high" || lv === "高") return "bg-red-50 text-red-700 ring-red-200";
  if (lv === "medium" || lv === "中") return "bg-amber-50 text-amber-800 ring-amber-200";
  if (lv === "low" || lv === "低") return "bg-emerald-50 text-emerald-800 ring-emerald-200";
  return "bg-slate-50 text-slate-700 ring-slate-200";
}

function riskLabel(level?: string): string {
  const lv = (level || "").toLowerCase();
  if (lv === "high") return "高";
  if (lv === "medium") return "中";
  if (lv === "low") return "低";
  if (lv === "none") return "未发现";
  return level || "—";
}

function HighlightedText({
  text,
  ranges,
  activeStart,
}: {
  text: string;
  ranges: Array<{ start: number; end: number; level?: string }>;
  activeStart?: number | null;
}) {
  if (!text) return <p className="text-sm text-muted-fg">暂无原文</p>;
  const sorted = [...ranges].sort((a, b) => a.start - b.start);
  const nodes: ReactNode[] = [];
  let cursor = 0;
  sorted.forEach((r, i) => {
    const start = Math.max(0, Math.min(text.length, r.start));
    const end = Math.max(start, Math.min(text.length, r.end));
    if (start > cursor) {
      nodes.push(<span key={`t-${i}`}>{text.slice(cursor, start)}</span>);
    }
    const active = activeStart != null && activeStart === r.start;
    nodes.push(
      <mark
        key={`m-${i}`}
        id={`risk-span-${r.start}`}
        className={[
          "rounded px-0.5",
          r.level === "high" || r.level === "高"
            ? "bg-red-200/90 text-red-950"
            : r.level === "medium" || r.level === "中"
              ? "bg-amber-200/80 text-amber-950"
              : "bg-emerald-100 text-emerald-950",
          active ? "ring-2 ring-primary" : "",
        ].join(" ")}
      >
        {text.slice(start, end)}
      </mark>,
    );
    cursor = end;
  });
  if (cursor < text.length) nodes.push(<span key="tail">{text.slice(cursor)}</span>);
  return (
    <pre className="whitespace-pre-wrap break-words font-sans text-sm leading-relaxed text-slate-800">
      {nodes}
    </pre>
  );
}

export function ReviewPage() {
  const s = useReviewSession();
  const [dragOver, setDragOver] = useState(false);
  const [activeSpan, setActiveSpan] = useState<number | null>(null);
  const [humanNote, setHumanNote] = useState("");
  const [humanSaved, setHumanSaved] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const [searchParams] = useSearchParams();

  useEffect(() => {
    const prefill = searchParams.get("prefill");
    if (prefill) {
      reviewSession.setTab("sentence");
      reviewSession.setQuery(prefill);
    }
  }, [searchParams]);

  const materialText = useMemo(() => {
    const report = s.materialReport;
    if (!report) return s.material;
    return String(report.raw_text || s.material || "");
  }, [s.materialReport, s.material]);

  const highlightRanges = useMemo(() => {
    const sentences = s.materialReport?.risk_sentences || [];
    return sentences
      .filter((x) => typeof x.position_start === "number" && typeof x.position_end === "number")
      .map((x) => ({
        start: Number(x.position_start),
        end: Number(x.position_end),
        level: x.risk_level,
      }));
  }, [s.materialReport]);

  const blocks = useMemo(() => {
    const report = s.materialReport;
    if (report?.case_blocks?.length) return report.case_blocks;
    if (report?.risk_sentences?.length) {
      return [
        {
          block_id: "block-1",
          paragraph_idx: 0,
          label: "风险识别结果",
          risk_sentences: report.risk_sentences,
        },
      ];
    }
    return [];
  }, [s.materialReport]);

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

  async function onHumanReviewComplete() {
    const ok = await reviewSession.saveMaterialHumanReview(humanNote);
    if (ok) setHumanSaved(true);
  }

  function focusSpan(start?: number) {
    if (start == null) return;
    setActiveSpan(start);
    const el = document.getElementById(`risk-span-${start}`);
    el?.scrollIntoView({ behavior: "smooth", block: "center" });
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
            材料原文右侧展开、风险句高亮定位；报告展示风险类型、命中案例、文号与匹配理由，并支持人工复核。
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

      {s.error ? <ErrorAlert message={s.error} /> : null}

      {s.tab === "sentence" ? (
        <form onSubmit={onSentenceReview} className="surface space-y-4 rounded-3xl p-6">
          <label className="block text-sm font-semibold" htmlFor="sentence-query">
            待审查语句
          </label>
          <textarea
            id="sentence-query"
            value={s.query}
            onChange={(e) => reviewSession.setQuery(e.target.value)}
            rows={5}
            className="w-full rounded-xl border border-border bg-white px-4 py-3 text-sm"
            placeholder="粘贴营销话术或风险表述…"
          />
          <button
            type="submit"
            disabled={s.loading}
            className="inline-flex min-h-11 items-center gap-2 rounded-xl bg-primary px-5 text-sm font-semibold text-white disabled:opacity-60"
          >
            {s.loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Scale className="h-4 w-4" />}
            生成审查意见
          </button>
        </form>
      ) : (
        <form onSubmit={onMaterialReview} className="surface space-y-4 rounded-3xl p-6">
          <label className="block text-sm font-semibold" htmlFor="material-text">
            材料文本
          </label>
          <textarea
            id="material-text"
            value={s.material}
            onChange={(e) => reviewSession.setMaterial(e.target.value)}
            rows={8}
            className="w-full rounded-xl border border-border bg-white px-4 py-3 text-sm"
            placeholder="粘贴整篇营销材料或处罚文书文本…"
          />
          <div
            onDragOver={(e) => {
              e.preventDefault();
              setDragOver(true);
            }}
            onDragLeave={() => setDragOver(false)}
            onDrop={onDrop}
            className={[
              "flex flex-col items-center justify-center gap-2 rounded-2xl border border-dashed px-4 py-8 text-sm",
              dragOver ? "border-primary bg-primary/5" : "border-border bg-slate-50/60",
            ].join(" ")}
          >
            <FileUp className="h-5 w-5 text-primary" />
            <p className="text-muted-fg">拖拽上传 txt / docx / pdf / pptx，或点击选择文件</p>
            <button
              type="button"
              className="text-sm font-semibold text-primary"
              onClick={() => fileRef.current?.click()}
            >
              选择文件
            </button>
            <input
              ref={fileRef}
              type="file"
              accept=".txt,.docx,.pdf,.pptx"
              className="hidden"
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) void reviewSession.startMaterialFile(f);
              }}
            />
          </div>
          <button
            type="submit"
            disabled={s.loading}
            className="inline-flex min-h-11 items-center gap-2 rounded-xl bg-primary px-5 text-sm font-semibold text-white disabled:opacity-60"
          >
            {s.loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Scale className="h-4 w-4" />}
            开始材料审查
          </button>
        </form>
      )}

      {(s.loading || s.thinkFinished) && s.thinkHint ? (
        <ThinkingPanel
          active={s.loading}
          queryHint={s.thinkHint}
          finished={s.thinkFinished}
          elapsedMs={s.thinkElapsedMs}
          startedAt={s.thinkStartedAt}
        />
      ) : null}

      {s.review ? (
        <section className="surface rise-in space-y-4 rounded-3xl bg-white p-6">
          <h2 className="font-display text-2xl font-semibold">单句审查结果</h2>
          {Array.isArray(s.review.risk_types) && s.review.risk_types.length > 0 ? (
            <div className="flex flex-wrap gap-2">
              {s.review.risk_types.map((t) => (
                <TagChip key={t}>{t}</TagChip>
              ))}
            </div>
          ) : null}
          {s.review.suggestion ? (
            <p className="whitespace-pre-wrap text-sm leading-relaxed text-slate-700">
              {s.review.suggestion}
            </p>
          ) : null}
          {Array.isArray(s.review.case_analysis) && s.review.case_analysis.length > 0 ? (
            <ul className="space-y-2">
              {s.review.case_analysis.map((c, i) => (
                <li key={i} className="rounded-xl border border-border/80 bg-slate-50 px-4 py-3 text-sm">
                  <Link
                    to={`/cases/${encodeURIComponent(String(c.case_id || ""))}`}
                    className="font-semibold text-primary no-underline hover:underline"
                  >
                    {String(c.case_id || `案例 ${i + 1}`)}
                  </Link>
                  {c.similarity_reason ? (
                    <p className="mt-1 text-xs text-muted-fg">{String(c.similarity_reason)}</p>
                  ) : null}
                </li>
              ))}
            </ul>
          ) : null}
        </section>
      ) : null}

      {s.materialReport ? (
        <section className="space-y-4">
          <div className="surface rounded-3xl p-5 sm:p-6">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <h2 className="font-display text-2xl font-semibold">材料审查报告</h2>
                <p className="mt-1 text-xs text-muted-fg">
                  来源文件：{s.materialReport.file_name || s.materialReport.source_file || "粘贴文本"}
                </p>
              </div>
              {s.materialReport.overall_risk ? (
                <span
                  className={`rounded-full px-3 py-1 text-xs font-semibold ring-1 ${riskTone(s.materialReport.overall_risk)}`}
                >
                  整体风险：{riskLabel(s.materialReport.overall_risk)}
                </span>
              ) : null}
            </div>
          </div>

          <div className="grid gap-4 lg:grid-cols-12">
            <div className="space-y-4 lg:col-span-7">
              {blocks.map((block) => (
                <div key={block.block_id} className="surface rounded-2xl p-5">
                  <h3 className="font-display text-lg font-semibold">{block.label}</h3>
                  <ul className="mt-4 space-y-4">
                    {(block.risk_sentences || []).map((raw, i) => {
                      const item = raw as NonNullable<
                        NonNullable<typeof s.materialReport>["risk_sentences"]
                      >[number];
                      return (
                        <li
                          key={`${block.block_id}-${i}`}
                          className="rounded-xl border border-border/80 bg-white px-4 py-3"
                        >
                          <div className="mb-2 flex flex-wrap items-center gap-2">
                            <span
                              className={`rounded-md px-2 py-0.5 text-xs font-semibold ring-1 ${riskTone(item.risk_level)}`}
                            >
                              风险等级：{riskLabel(item.risk_level)}
                            </span>
                            {typeof item.confidence === "number" ? (
                              <span className="text-xs text-muted-fg">
                                置信度 {(item.confidence * 100).toFixed(0)}%
                              </span>
                            ) : null}
                          </div>
                          <button
                            type="button"
                            className="text-left text-sm font-medium text-foreground hover:text-primary"
                            onClick={() => focusSpan(item.position_start)}
                          >
                            风险语句原文：「{item.text}」
                          </button>
                          <dl className="mt-3 grid gap-2 text-xs sm:grid-cols-2">
                            <div>
                              <dt className="text-muted-fg">风险类型</dt>
                              <dd className="mt-0.5 font-medium">
                                {(item.risk_types || []).join("；") || "—"}
                              </dd>
                            </div>
                            <div>
                              <dt className="text-muted-fg">命中案例</dt>
                              <dd className="mt-0.5 font-medium">
                                {item.hit_case_id ? (
                                  <Link
                                    to={`/cases/${encodeURIComponent(item.hit_case_id)}`}
                                    className="text-primary no-underline hover:underline"
                                  >
                                    {item.hit_case_id}
                                    {item.hit_party_name ? ` · ${item.hit_party_name}` : ""}
                                  </Link>
                                ) : (
                                  "—"
                                )}
                              </dd>
                            </div>
                            <div>
                              <dt className="text-muted-fg">处罚文号</dt>
                              <dd className="mt-0.5 font-medium">{item.hit_penalty_doc_no || "—"}</dd>
                            </div>
                            <div>
                              <dt className="text-muted-fg">案例关键字段</dt>
                              <dd className="mt-0.5 font-medium">{item.case_key_field || "—"}</dd>
                            </div>
                            <div className="sm:col-span-2">
                              <dt className="text-muted-fg">匹配理由</dt>
                              <dd className="mt-0.5 leading-relaxed text-slate-700">
                                {item.match_reason || item.compliance_reason || "—"}
                              </dd>
                            </div>
                            <div className="sm:col-span-2">
                              <dt className="text-muted-fg">整改建议</dt>
                              <dd className="mt-0.5 leading-relaxed text-slate-700">
                                {item.suggestion || "—"}
                              </dd>
                            </div>
                          </dl>
                        </li>
                      );
                    })}
                  </ul>
                </div>
              ))}

              <div className="surface rounded-2xl p-5">
                <h3 className="font-display text-lg font-semibold">人工复核</h3>
                <p className="mt-1 text-xs text-muted-fg">
                  供工作人员填写复核意见；点击完成后写入材料审查记录。
                </p>
                <textarea
                  value={humanNote}
                  onChange={(e) => {
                    setHumanNote(e.target.value);
                    setHumanSaved(false);
                  }}
                  rows={4}
                  className="mt-3 w-full rounded-xl border border-border bg-white px-4 py-3 text-sm"
                  placeholder="复核建议（可留空）…"
                />
                <button
                  type="button"
                  disabled={Boolean(s.feedbackSaving.human)}
                  onClick={() => void onHumanReviewComplete()}
                  className="mt-3 inline-flex min-h-11 items-center rounded-xl bg-primary px-5 text-sm font-semibold text-white disabled:opacity-60"
                >
                  {s.feedbackSaving.human ? "保存中…" : humanSaved ? "已完成复核" : "复核完成"}
                </button>
              </div>
            </div>

            <aside className="surface sticky top-4 h-fit max-h-[80vh] overflow-auto rounded-2xl p-5 lg:col-span-5">
              <h3 className="font-display text-lg font-semibold">材料原文</h3>
              <p className="mt-1 text-xs text-muted-fg">高风险语句已高亮；点击左侧风险句可定位。</p>
              <div className="mt-4 rounded-xl border border-border/70 bg-slate-50/80 p-3">
                <HighlightedText
                  text={materialText}
                  ranges={highlightRanges}
                  activeStart={activeSpan}
                />
              </div>
            </aside>
          </div>
        </section>
      ) : null}
    </div>
  );
}
