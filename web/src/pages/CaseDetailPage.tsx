import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ArrowLeft, Check, Loader2, Pencil } from "lucide-react";
import { api, ApiError } from "../api/client";
import type { CaseDetail } from "../api/types";
import { RiskTypeChip } from "../components/RiskTypeChip";
import { formatDate } from "../lib/format";
import { ErrorAlert, LoadingBlock } from "../components/ui";
import { CN_TAG_NAMES } from "../lib/cnRiskTags";

export function CaseDetailPage() {
  const { caseId = "" } = useParams();
  const [data, setData] = useState<CaseDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [toast, setToast] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const [partyName, setPartyName] = useState("");
  const [riskTags, setRiskTags] = useState<string[]>([]);

  async function reload() {
    const d = await api.getCase(caseId);
    setData(d);
    setPartyName(d.party_name || "");
    setRiskTags([...(d.risk_tags || [])]);
  }

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    api
      .getCase(caseId)
      .then((d) => {
        if (!cancelled) {
          setData(d);
          setPartyName(d.party_name || "");
          setRiskTags([...(d.risk_tags || [])]);
        }
      })
      .catch((e: Error) => {
        if (!cancelled) setError(e instanceof ApiError ? e.message : "加载失败");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [caseId]);

  useEffect(() => {
    if (!toast) return;
    const t = window.setTimeout(() => setToast(null), 2800);
    return () => window.clearTimeout(t);
  }, [toast]);

  if (loading) return <LoadingBlock label="加载案例详情…" />;
  if (error) return <ErrorAlert message={error} />;
  if (!data) return null;

  const pending =
    Boolean(data.is_insurance_candidate) && !data.is_insurance_related;
  const reasons = (data.candidate_reasons as string[] | null) || [];
  const tags = (data.risk_tags || []) as string[];
  const typeIds = (data.risk_type_ids || []) as string[];

  async function onConfirm() {
    setBusy(true);
    setError(null);
    try {
      await api.confirmCase(caseId);
      await reload();
      setToast("已确认保险相关，统计将更新");
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "确认失败");
    } finally {
      setBusy(false);
    }
  }

  async function onExclude() {
    setBusy(true);
    setError(null);
    try {
      await api.excludeCase(caseId);
      await reload();
      setToast("已排除该案例");
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "排除失败");
    } finally {
      setBusy(false);
    }
  }

  async function onSaveEdits() {
    setBusy(true);
    setError(null);
    try {
      await api.patchCase(caseId, {
        party_name: partyName.trim() || undefined,
        risk_tags: riskTags,
      });
      await reload();
      setEditing(false);
      setToast("已保存主体与标签修订");
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "保存失败");
    } finally {
      setBusy(false);
    }
  }

  function toggleTag(tag: string) {
    setRiskTags((prev) =>
      prev.includes(tag) ? prev.filter((t) => t !== tag) : [...prev, tag],
    );
  }

  return (
    <div className="space-y-6">
      <Link
        to="/knowledge?view=queue"
        className="inline-flex min-h-11 items-center gap-2 text-sm font-medium text-muted-fg no-underline hover:text-primary"
      >
        <ArrowLeft className="h-4 w-4" />
        返回案例知识库
      </Link>

      {toast ? (
        <p className="rounded-xl bg-emerald-50 px-4 py-3 text-sm text-emerald-800" role="status">
          {toast}
        </p>
      ) : null}
      {error ? <ErrorAlert message={error} /> : null}

      <article className="surface rise-in rounded-3xl p-6 sm:p-8">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <p className="font-mono text-xs text-muted-fg">{data.case_id}</p>
            <h1 className="mt-2 font-display text-3xl font-bold sm:text-4xl">
              {data.party_name || "未命名当事人"}
            </h1>
            <p className="mt-2 text-sm text-muted-fg">
              {data.penalty_doc_no || "无文号"} · {formatDate(data.publish_date)} ·{" "}
              {data.source_file || "未知来源"}
            </p>
          </div>
          <div>
            {data.is_insurance_related ? (
              <span className="rounded-full bg-emerald-50 px-3 py-1 text-xs font-semibold text-emerald-800 ring-1 ring-emerald-200">
                已确认保险 / 已入库
              </span>
            ) : pending ? (
              <span className="rounded-full bg-amber-50 px-3 py-1 text-xs font-semibold text-amber-900 ring-1 ring-amber-200">
                待复核候选
              </span>
            ) : (
              <span className="rounded-full bg-slate-100 px-3 py-1 text-xs font-semibold text-slate-700 ring-1 ring-slate-200">
                已排除
              </span>
            )}
          </div>
        </div>

        <section className="mt-8 rounded-2xl border border-primary/15 bg-primary/[0.03] p-5">
          <h2 className="font-display text-xl font-semibold">风险标签</h2>
          <div className="mt-3 flex flex-wrap gap-2">
            {tags.length
              ? tags.map((t) => <RiskTypeChip key={t} idOrTag={t} />)
              : (
                <span className="text-sm text-muted-fg">暂无标签</span>
              )}
            {typeIds.map((t) => (
              <span
                key={t}
                className="rounded-md bg-white px-2 py-1 font-mono text-xs text-muted-fg ring-1 ring-border"
              >
                {t}
              </span>
            ))}
          </div>

          <div className="mt-5">
            <h3 className="text-sm font-semibold text-foreground">系统判断依据</h3>
            <p className="mt-1 text-xs text-muted-fg">命中关键词 / 候选原因</p>
            <ul className="mt-2 space-y-1.5 text-sm text-slate-700">
              {reasons.length ? (
                reasons.map((r) => (
                  <li key={r} className="flex gap-2">
                    <Check className="mt-0.5 h-3.5 w-3.5 shrink-0 text-emerald-600" />
                    {r}
                  </li>
                ))
              ) : (
                <li className="text-muted-fg">暂无命中记录（可能为金标导入或人工修订）</li>
              )}
            </ul>
          </div>
        </section>

        <section className="mt-6 flex flex-wrap gap-2">
          {pending ? (
            <>
              <button
                type="button"
                disabled={busy}
                onClick={() => void onConfirm()}
                className="inline-flex min-h-11 items-center gap-2 rounded-xl bg-primary px-4 text-sm font-semibold text-white disabled:opacity-50"
              >
                {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
                确认保险
              </button>
              <button
                type="button"
                disabled={busy}
                onClick={() => void onExclude()}
                className="min-h-11 rounded-xl border border-border bg-white px-4 text-sm font-medium disabled:opacity-50"
              >
                排除
              </button>
            </>
          ) : null}
          {!data.is_insurance_related && !pending ? (
            <button
              type="button"
              disabled={busy}
              onClick={() => void onConfirm()}
              className="inline-flex min-h-11 items-center gap-2 rounded-xl bg-primary px-4 text-sm font-semibold text-white disabled:opacity-50"
            >
              重新确认为保险
            </button>
          ) : null}
          <button
            type="button"
            onClick={() => setEditing((v) => !v)}
            className="inline-flex min-h-11 items-center gap-2 rounded-xl border border-border bg-white px-4 text-sm font-medium"
          >
            <Pencil className="h-4 w-4" />
            {editing ? "取消修订" : "修改标签 / 主体"}
          </button>
        </section>

        {editing ? (
          <section className="mt-4 space-y-4 rounded-2xl border border-border bg-slate-50/80 p-4">
            <div>
              <label htmlFor="party" className="mb-1 block text-xs font-semibold text-muted-fg">
                保险主体 / 当事人
              </label>
              <input
                id="party"
                value={partyName}
                onChange={(e) => setPartyName(e.target.value)}
                className="min-h-11 w-full rounded-xl border border-border bg-white px-3 text-sm outline-none focus:border-primary focus:ring-4 focus:ring-primary/10"
              />
            </div>
            <div>
              <p className="mb-2 text-xs font-semibold text-muted-fg">风险标签（可多选）</p>
              <div className="flex max-h-48 flex-wrap gap-2 overflow-y-auto">
                {CN_TAG_NAMES.map((tag) => {
                  const on = riskTags.includes(tag);
                  return (
                    <button
                      key={tag}
                      type="button"
                      onClick={() => toggleTag(tag)}
                      className={[
                        "min-h-11 rounded-full px-3 text-xs font-semibold ring-1 transition",
                        on
                          ? "bg-primary text-white ring-primary"
                          : "bg-white text-muted-fg ring-border hover:text-foreground",
                      ].join(" ")}
                    >
                      {tag}
                    </button>
                  );
                })}
              </div>
            </div>
            <button
              type="button"
              disabled={busy}
              onClick={() => void onSaveEdits()}
              className="min-h-11 rounded-xl bg-slate-900 px-4 text-sm font-semibold text-white disabled:opacity-50"
            >
              保存修订
            </button>
          </section>
        ) : null}

        <dl className="mt-8 grid gap-4 sm:grid-cols-2">
          {(
            [
              ["监管机构", data.regulator],
              ["机构类型", data.institution_type],
              ["法律依据", data.legal_basis],
              ["处罚金额", data.fine_amount],
            ] as const
          ).map(([label, value]) => (
            <div key={label} className="rounded-xl bg-muted/50 px-4 py-3">
              <dt className="text-xs text-muted-fg">{label}</dt>
              <dd className="mt-1 text-sm leading-relaxed text-foreground">{value || "—"}</dd>
            </div>
          ))}
        </dl>

        <section className="mt-8 space-y-4">
          <div>
            <h2 className="font-display text-xl font-semibold">违规行为</h2>
            <p className="mt-2 whitespace-pre-wrap text-sm leading-relaxed text-slate-700">
              {data.violation_behavior || "—"}
            </p>
          </div>
          <div>
            <h2 className="font-display text-xl font-semibold">处罚内容</h2>
            <p className="mt-2 whitespace-pre-wrap text-sm leading-relaxed text-slate-700">
              {data.penalty_content || "—"}
            </p>
          </div>
        </section>
      </article>
    </div>
  );
}
