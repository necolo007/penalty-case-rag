import { riskLabel, riskTone } from "../lib/riskColors";

export function RiskTypeChip({ idOrTag }: { idOrTag: string }) {
  const tone = riskTone(idOrTag);
  return (
    <span
      className={`inline-flex items-center rounded-md px-2 py-0.5 text-xs font-medium ring-1 ${tone.bg} ${tone.text} ${tone.ring}`}
    >
      {riskLabel(idOrTag)}
    </span>
  );
}
