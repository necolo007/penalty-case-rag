import { useState, type FormEvent } from "react";
import { FileUp, Loader2, Scale } from "lucide-react";
import { api, ApiError } from "../api/client";
import type { MaterialReviewResponse, ReviewGenerateResponse } from "../api/types";
import { ErrorAlert, TagChip } from "../components/ui";

type Tab = "sentence" | "material";

export function ReviewPage() {
  const [tab, setTab] = useState<Tab>("sentence");
  const [query, setQuery] = useState("");
  const [material, setMaterial] = useState("");
  const [scene, setScene] = useState("");
  const [topK, setTopK] = useState(5);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [review, setReview] = useState<ReviewGenerateResponse | null>(null);
  const [materialReport, setMaterialReport] = useState<MaterialReviewResponse | null>(null);

  async function onSentenceReview(e: FormEvent) {
    e.preventDefault();
    if (!query.trim()) {
      setError("请输入待审查文本");
      return;
    }
    setLoading(true);
    setError(null);
    setMaterialReport(null);
    try {
      const res = await api.generateReview({
        query_text: query.trim(),
        top_k: topK,
        generate_suggestion: true,
      });
      setReview(res);
    } catch (err) {
      setReview(null);
      setError(err instanceof ApiError ? err.message : "审查生成失败");
    } finally {
      setLoading(false);
    }
  }

  async function onMaterialReview(e: FormEvent) {
    e.preventDefault();
    if (!material.trim()) {
      setError("请粘贴待审查材料文本");
      return;
    }
    setLoading(true);
    setError(null);
    setReview(null);
    try {
      const res = await api.reviewMaterialText(material.trim(), scene || undefined);
      setMaterialReport(res);
    } catch (err) {
      setMaterialReport(null);
      setError(err instanceof ApiError ? err.message : "材料审查失败");
    } finally {
      setLoading(false);
    }
  }

  async function onMaterialFile(file: File | undefined) {
    if (!file) return;
    setLoading(true);
    setError(null);
    setReview(null);
    try {
      const res = await api.reviewMaterialUpload(file, scene || undefined);
      setMaterialReport(res);
    } catch (err) {
      setMaterialReport(null);
      setError(err instanceof ApiError ? err.message : "材料文件审查失败");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="space-y-8">
      <header className="rise-in">
        <h1 className="font-display text-4xl font-bold">合规审查</h1>
        <p className="mt-2 text-muted-fg">
          基于相似案例生成可追溯审查意见，支持单句审查与整篇材料风险定位。
        </p>
      </header>

      <div className="inline-flex rounded-xl border border-border bg-white p-1" role="tablist">
        {(
          [
            ["sentence", "单句审查"],
            ["material", "材料审查"],
          ] as const
        ).map(([id, label]) => (
          <button
            key={id}
            type="button"
            role="tab"
            aria-selected={tab === id}
            onClick={() => setTab(id)}
            className={[
              "min-h-11 rounded-lg px-4 text-sm font-semibold transition",
              tab === id ? "bg-primary text-white" : "text-muted-fg hover:text-foreground",
            ].join(" ")}
          >
            {label}
          </button>
        ))}
      </div>

      {tab === "sentence" ? (
        <form onSubmit={onSentenceReview} className="surface rounded-3xl p-6">
          <label htmlFor="review-q" className="mb-2 block text-sm font-semibold">
            待审查表述
          </label>
          <textarea
            id="review-q"
            rows={4}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            className="w-full rounded-2xl border border-border bg-white p-4 text-sm leading-relaxed outline-none focus:border-primary focus:ring-4 focus:ring-primary/10"
            placeholder="粘贴业务话术、宣传文案或可疑表述…"
          />
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
                value={topK}
                onChange={(e) => setTopK(Number(e.target.value) || 5)}
                className="min-h-11 w-28 rounded-xl border border-border bg-white px-3 text-sm"
              />
            </div>
            <button
              type="submit"
              disabled={loading}
              className="inline-flex min-h-11 items-center gap-2 rounded-xl bg-primary px-5 text-sm font-semibold text-white hover:bg-primary-deep disabled:opacity-60"
            >
              {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Scale className="h-4 w-4" />}
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
              value={scene}
              onChange={(e) => setScene(e.target.value)}
              className="min-h-11 w-full max-w-md rounded-xl border border-border bg-white px-3 text-sm outline-none focus:border-primary focus:ring-4 focus:ring-primary/10"
              placeholder="如：产品宣传 / 代理人话术"
            />
          </div>
          <div>
            <label htmlFor="mat" className="mb-1.5 block text-sm font-semibold">
              材料文本
            </label>
            <textarea
              id="mat"
              rows={10}
              value={material}
              onChange={(e) => setMaterial(e.target.value)}
              className="w-full rounded-2xl border border-border bg-white p-4 text-sm leading-relaxed outline-none focus:border-primary focus:ring-4 focus:ring-primary/10"
              placeholder="粘贴整篇宣传材料、合同条文或培训讲稿…"
            />
          </div>
          <div className="flex flex-wrap gap-3">
            <button
              type="submit"
              disabled={loading}
              className="inline-flex min-h-11 items-center gap-2 rounded-xl bg-primary px-5 text-sm font-semibold text-white hover:bg-primary-deep disabled:opacity-60"
            >
              {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Scale className="h-4 w-4" />}
              审查粘贴文本
            </button>
            <label className="inline-flex min-h-11 cursor-pointer items-center gap-2 rounded-xl border border-border bg-white px-4 text-sm font-medium hover:bg-muted">
              <FileUp className="h-4 w-4" />
              上传文件审查
              <input
                type="file"
                accept=".txt,.docx,.pdf,.pptx"
                className="sr-only"
                onChange={(e) => void onMaterialFile(e.target.files?.[0])}
              />
            </label>
          </div>
        </form>
      )}

      {error ? <ErrorAlert message={error} /> : null}

      {review ? (
        <section className="surface rise-in space-y-4 rounded-3xl p-6">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h2 className="font-display text-2xl font-semibold">审查结果</h2>
            <span className="font-mono text-xs text-muted-fg">{review.review_id}</span>
          </div>
          <div className="flex flex-wrap gap-1.5">
            {(review.risk_types ?? []).map((t) => (
              <TagChip key={t}>{t}</TagChip>
            ))}
          </div>
          <div>
            <h3 className="text-sm font-semibold text-muted-fg">审查建议</h3>
            <p className="mt-2 whitespace-pre-wrap text-sm leading-relaxed text-slate-700">
              {review.suggestion || "（未返回建议，请确认 LLM 已配置）"}
            </p>
          </div>
          {review.case_analysis && review.case_analysis.length > 0 ? (
            <div>
              <h3 className="text-sm font-semibold text-muted-fg">案例归因</h3>
              <ul className="mt-2 space-y-2">
                {review.case_analysis.map((a, i) => (
                  <li
                    key={`${a.case_id ?? i}`}
                    className="rounded-xl bg-muted/60 px-4 py-3 text-sm"
                  >
                    <span className="font-mono text-xs text-primary">{a.case_id}</span>
                    <p className="mt-1 text-slate-700">{a.similarity_reason || "—"}</p>
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
          <p className="text-xs text-muted-fg">耗时 {review.took_ms} ms</p>
        </section>
      ) : null}

      {materialReport ? (
        <section className="surface rise-in space-y-4 rounded-3xl p-6">
          <h2 className="font-display text-2xl font-semibold">材料审查报告</h2>
          {materialReport.overall_risk ? (
            <p className="text-sm">
              <span className="text-muted-fg">整体风险：</span>
              <strong className="text-primary">{String(materialReport.overall_risk)}</strong>
            </p>
          ) : null}
          {materialReport.summary ? (
            <p className="whitespace-pre-wrap text-sm leading-relaxed text-slate-700">
              {String(materialReport.summary)}
            </p>
          ) : null}
          {Array.isArray(materialReport.risk_sentences) &&
          materialReport.risk_sentences.length > 0 ? (
            <ul className="space-y-3">
              {materialReport.risk_sentences.map((s, i) => (
                <li key={i} className="rounded-xl border border-border/80 bg-white px-4 py-3">
                  <div className="mb-1 flex flex-wrap gap-2 text-xs">
                    {s.risk_level ? (
                      <span className="rounded-md bg-red-50 px-2 py-0.5 font-semibold text-destructive">
                        {String(s.risk_level)}
                      </span>
                    ) : null}
                  </div>
                  <p className="text-sm text-foreground">{s.text || JSON.stringify(s)}</p>
                  {s.suggestion ? (
                    <p className="mt-2 text-xs text-muted-fg">{String(s.suggestion)}</p>
                  ) : null}
                </li>
              ))}
            </ul>
          ) : (
            <pre className="overflow-x-auto rounded-xl bg-muted/70 p-4 text-xs text-slate-700">
              {JSON.stringify(materialReport, null, 2)}
            </pre>
          )}
        </section>
      ) : null}
    </div>
  );
}
