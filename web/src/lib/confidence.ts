/** 置信度展示：数值 0–1 / 百分比 / high|medium|low */

export type ConfidenceTier = "high" | "mid" | "low";

export function normalizeConfidence(value: number | string | null | undefined): number | null {
  if (value == null || value === "") return null;
  if (typeof value === "number") {
    if (Number.isNaN(value)) return null;
    return value > 1 ? Math.min(value / 100, 1) : Math.max(0, Math.min(value, 1));
  }
  const raw = String(value).trim().toLowerCase();
  if (raw === "high") return 0.95;
  if (raw === "medium" || raw === "mid") return 0.75;
  if (raw === "low") return 0.45;
  const n = Number(raw.replace("%", ""));
  if (Number.isNaN(n)) return null;
  return n > 1 ? Math.min(n / 100, 1) : Math.max(0, Math.min(n, 1));
}

export function confidenceTier(value: number | null): ConfidenceTier {
  if (value == null) return "low";
  if (value >= 0.85) return "high";
  if (value >= 0.6) return "mid";
  return "low";
}

export function confidenceTone(tier: ConfidenceTier): {
  bar: string;
  text: string;
  label: string;
} {
  switch (tier) {
    case "high":
      return { bar: "bg-emerald-500", text: "text-emerald-700", label: "高" };
    case "mid":
      return { bar: "bg-amber-500", text: "text-amber-700", label: "中" };
    default:
      return { bar: "bg-rose-500", text: "text-rose-700", label: "低" };
  }
}

export function formatConfidencePct(value: number | string | null | undefined): string {
  const n = normalizeConfidence(value);
  if (n == null) return "—";
  return `${Math.round(n * 100)}%`;
}
