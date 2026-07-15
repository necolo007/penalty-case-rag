import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ArrowLeft } from "lucide-react";
import { api, ApiError } from "../api/client";
import type { CaseDetail } from "../api/types";
import { formatDate } from "../lib/format";
import { ErrorAlert, LoadingBlock, TagChip } from "../components/ui";

export function CaseDetailPage() {
  const { caseId = "" } = useParams();
  const [data, setData] = useState<CaseDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    api
      .getCase(caseId)
      .then((d) => {
        if (!cancelled) setData(d);
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

  if (loading) return <LoadingBlock label="加载案例详情…" />;
  if (error) return <ErrorAlert message={error} />;
  if (!data) return null;

  const fields: Array<[string, string | null | undefined]> = [
    ["案例编号", data.case_id],
    ["当事人", data.party_name],
    ["文号", data.penalty_doc_no],
    ["监管机构", data.regulator],
    ["机构类型", data.institution_type],
    ["发布日期", formatDate(data.publish_date)],
    ["来源文件", data.source_file],
    ["法律依据", data.legal_basis],
  ];

  return (
    <div className="space-y-6">
      <Link
        to="/cases"
        className="inline-flex min-h-11 items-center gap-2 text-sm font-medium text-muted-fg no-underline hover:text-primary"
      >
        <ArrowLeft className="h-4 w-4" />
        返回案例库
      </Link>

      <article className="surface rise-in rounded-3xl p-6 sm:p-8">
        <p className="font-mono text-xs text-muted-fg">{data.case_id}</p>
        <h1 className="mt-2 font-display text-3xl font-bold sm:text-4xl">
          {data.party_name || "未命名当事人"}
        </h1>

        <div className="mt-4 flex flex-wrap gap-1.5">
          {(data.risk_tags ?? []).map((t) => (
            <TagChip key={t}>{t}</TagChip>
          ))}
          {(data.risk_type_ids ?? []).map((t) => (
            <span key={t} className="rounded-md bg-muted px-2 py-0.5 text-xs text-muted-fg">
              {t}
            </span>
          ))}
        </div>

        <dl className="mt-8 grid gap-4 sm:grid-cols-2">
          {fields.map(([label, value]) => (
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
