import {
  confidenceTier,
  confidenceTone,
  formatConfidencePct,
  normalizeConfidence,
} from "../lib/confidence";

export function ConfidenceBar({
  value,
  showLabel = true,
  className = "",
}: {
  value: number | string | null | undefined;
  showLabel?: boolean;
  className?: string;
}) {
  const n = normalizeConfidence(value);
  const tier = confidenceTier(n);
  const tone = confidenceTone(tier);
  const pct = n == null ? 0 : Math.round(n * 100);

  return (
    <div className={`flex min-w-[7.5rem] items-center gap-2 ${className}`}>
      <div
        className="h-2 flex-1 overflow-hidden rounded-full bg-slate-200"
        role="progressbar"
        aria-valuenow={pct}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label={`置信度 ${formatConfidencePct(value)}`}
      >
        <div
          className={`h-full rounded-full transition-[width] duration-300 ${tone.bar}`}
          style={{ width: `${pct}%` }}
        />
      </div>
      {showLabel ? (
        <span className={`shrink-0 text-xs font-semibold tabular-nums ${tone.text}`}>
          {formatConfidencePct(value)}
        </span>
      ) : null}
    </div>
  );
}
