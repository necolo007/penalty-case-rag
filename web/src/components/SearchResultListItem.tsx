import { AlertTriangle } from "lucide-react";
import type { CaseResult } from "../api/types";
import {
  caseHeadline,
  findMissedKeywords,
  penaltyHighlight,
  relevancePercent,
  relevanceTier,
  riskLabel,
} from "../lib/searchInsights";
import { truncate } from "../lib/format";
import { TagChip } from "./ui";

type Props = {
  item: CaseResult;
  userQuery: string;
  predictedCnTags?: string[];
  predictedRiskIds?: string[];
  selected: boolean;
  onSelect: () => void;
};

export function SearchResultListItem({
  item,
  userQuery,
  predictedCnTags = [],
  predictedRiskIds = [],
  selected,
  onSelect,
}: Props) {
  const pct = relevancePercent(item.score);
  const tier = relevanceTier(item.score);
  const missed = findMissedKeywords(userQuery, item);
  const tags = [
    ...new Set([
      ...(predictedCnTags.length ? predictedCnTags : predictedRiskIds.map(riskLabel)),
      ...item.risk_tags.slice(0, 2),
    ]),
  ].slice(0, 3);

  return (
    <button
      type="button"
      onClick={onSelect}
      aria-pressed={selected}
      className={[
        "w-full rounded-xl border bg-white p-3 text-left transition duration-200",
        "hover:shadow-[var(--shadow-soft)] focus-visible:ring-2 focus-visible:ring-primary/30",
        selected
          ? "border-accent shadow-[var(--shadow-soft)] ring-1 ring-accent/30"
          : "border-border/80 hover:border-primary/30",
      ].join(" ")}
    >
      <div className="flex items-start gap-2.5">
        <div className="w-12 shrink-0 text-center">
          <p className="font-display text-xl font-bold tabular-nums leading-none text-primary">{pct.toFixed(0)}</p>
          <p className={`mt-0.5 text-[10px] font-semibold ${tier.tone}`}>{tier.label}</p>
        </div>
        <div className="min-w-0 flex-1">
          <div className="mb-0.5 flex flex-wrap items-center gap-1.5">
            <span className="rounded bg-primary/10 px-1 py-px text-[10px] font-bold text-primary">
              #{item.rank}
            </span>
            <span className="font-mono text-[10px] text-muted-fg">{item.case_id}</span>
          </div>
          <h3 className="font-display text-sm font-semibold leading-snug text-foreground">
            {caseHeadline(item, 44)}
          </h3>
          <p className="mt-0.5 truncate text-[11px] text-muted-fg">
            {item.party_name || "未知当事人"}
            {item.regulator ? ` · ${item.regulator}` : ""}
          </p>
          <p className="mt-1.5 line-clamp-1 text-[11px] leading-relaxed text-slate-600">
            处罚：{truncate(penaltyHighlight(item), 56)}
          </p>
          <div className="mt-1.5 flex flex-wrap items-center gap-1">
            {tags.map((t) => (
              <TagChip key={t}>{t}</TagChip>
            ))}
            {missed[0] ? (
              <span className="inline-flex items-center gap-1 rounded-md bg-amber-50 px-1.5 py-0.5 text-[10px] font-medium text-amber-800 ring-1 ring-amber-200/80">
                <AlertTriangle className="h-3 w-3" aria-hidden />
                未直接命中「{missed[0]}」
              </span>
            ) : null}
          </div>
        </div>
      </div>
    </button>
  );
}
