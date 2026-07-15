export function truncate(text: string | null | undefined, max = 160): string {
  if (!text) return "—";
  const t = text.trim();
  if (t.length <= max) return t;
  return `${t.slice(0, max)}…`;
}

export function formatDate(value: string | null | undefined): string {
  if (!value) return "—";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return value.slice(0, 10);
  return d.toLocaleDateString("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  });
}

export function formatScore(score: number): string {
  return score.toFixed(3);
}

export function statusLabel(status: string): string {
  const map: Record<string, string> = {
    pending: "排队中",
    parsing: "解析中",
    extracting: "抽取中",
    done: "已完成",
    completed: "已完成",
    failed: "失败",
    error: "失败",
    duplicate: "重复",
  };
  return map[status] ?? status;
}
