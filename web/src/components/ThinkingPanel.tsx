import { useEffect, useRef, useState } from "react";
import { ChevronDown, Sparkles } from "lucide-react";

export const THINK_STEPS = [
  "文档切分",
  "风险语句识别",
  "风险类型判断",
  "查询改写 / HyDE",
  "BGE-M3 多通道召回",
  "融合精排",
  "审查意见生成",
] as const;

/** 末步流式「内心独白」文案（模拟大模型 thinking） */
function buildThinkingScript(queryHint?: string): string {
  const hint = queryHint?.trim().slice(0, 80) || "待审查表述";
  return [
    `先确认审查目标：「${hint}」。`,
    "按段落切分材料，定位可能触达监管红线的语句。",
    "对照风险词典与历史标签，初步判断风险类型候选集。",
    "对口语话术做监管表述改写，并可选生成 HyDE 假想违法事实。",
    "并行召回：dense_raw（原文）、dense（改写）、dense_hyde 与 sparse，收集相似处罚案例。",
    "dense 族按分数 max_merge 融合，再经 Cross-Encoder 精排与 LLM listwise 减枝，保留 Top 证据。",
    "综合案例归因与法条语境，输出可解释、可追溯的审查意见与整改建议，并为人工复核预留标记位。",
  ].join("\n");
}

type Props = {
  active: boolean;
  queryHint?: string;
  /** 请求结束后保留「已思考」面板 */
  finished?: boolean;
  elapsedMs?: number | null;
  /** 跨路由恢复时沿用会话开始时间，避免计时归零 */
  startedAt?: number | null;
};

export function ThinkingPanel({
  active,
  queryHint,
  finished = false,
  elapsedMs,
  startedAt,
}: Props) {
  const [step, setStep] = useState(-1);
  const [streamText, setStreamText] = useState("");
  const [expanded, setExpanded] = useState(true);
  const [elapsedSec, setElapsedSec] = useState(0);
  const scriptRef = useRef("");
  const startRef = useRef<number>(0);

  useEffect(() => {
    if (!active) return;

    setStep(0);
    setStreamText("");
    setExpanded(true);
    startRef.current = startedAt && startedAt > 0 ? startedAt : Date.now();
    setElapsedSec(Math.max(1, Math.round((Date.now() - startRef.current) / 1000)));
    scriptRef.current = buildThinkingScript(queryHint);

    const stepTimer = window.setInterval(() => {
      setStep((s) => {
        if (s >= THINK_STEPS.length - 1) {
          window.clearInterval(stepTimer);
          return THINK_STEPS.length - 1;
        }
        return s + 1;
      });
    }, 650);

    const clock = window.setInterval(() => {
      setElapsedSec(Math.max(1, Math.round((Date.now() - startRef.current) / 1000)));
    }, 250);

    return () => {
      window.clearInterval(stepTimer);
      window.clearInterval(clock);
    };
  }, [active, queryHint, startedAt]);

  // 到达最后一步后开始打字流式
  useEffect(() => {
    if (!active || step < THINK_STEPS.length - 1) return;

    const full = scriptRef.current;
    let i = 0;
    setStreamText("");
    const preferReduced =
      typeof window !== "undefined" &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    if (preferReduced) {
      setStreamText(full);
      return;
    }

    const id = window.setInterval(() => {
      i += 2;
      setStreamText(full.slice(0, i));
      if (i >= full.length) window.clearInterval(id);
    }, 28);

    return () => window.clearInterval(id);
  }, [active, step]);

  // 结束后若未写完，一次性补全
  useEffect(() => {
    if (active || !finished) return;
    const full = scriptRef.current || buildThinkingScript(queryHint);
    setStreamText(full);
    setStep(THINK_STEPS.length - 1);
  }, [active, finished, queryHint]);

  if (!active && !finished) return null;

  const displaySec =
    finished && elapsedMs != null ? Math.max(1, Math.round(elapsedMs / 1000)) : elapsedSec;
  const headerLabel = active ? "思考中" : "已思考";

  return (
    <section className="surface rounded-2xl p-5 sm:p-6" aria-live="polite">
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className="flex w-full min-h-11 items-center gap-2 text-left"
        aria-expanded={expanded}
      >
        <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-primary/10 text-primary">
          <Sparkles className="h-4 w-4" aria-hidden />
        </span>
        <span className="text-sm font-semibold text-foreground">
          {headerLabel}
          <span className="ml-1 font-normal text-muted-fg">（用时 {displaySec} 秒）</span>
        </span>
        <ChevronDown
          className={[
            "ml-auto h-4 w-4 text-muted-fg transition duration-200",
            expanded ? "rotate-0" : "-rotate-90",
          ].join(" ")}
          aria-hidden
        />
      </button>

      {expanded ? (
        <div className="mt-4 space-y-4">
          <ol className="flex flex-wrap gap-2">
            {THINK_STEPS.map((label, i) => {
              const done = i < step || (!active && finished);
              const current = active && i === step;
              return (
                <li
                  key={label}
                  className={[
                    "rounded-full px-3 py-1 text-xs font-medium transition",
                    current
                      ? "bg-primary text-white"
                      : done
                        ? "bg-accent-soft text-accent"
                        : "bg-muted text-muted-fg",
                  ].join(" ")}
                >
                  {i + 1}. {label}
                </li>
              );
            })}
          </ol>

          {/* DeepSeek 风格：左侧竖线 + 灰色流式正文 */}
          {(step >= THINK_STEPS.length - 1 || finished) && (
            <div className="border-l-2 border-slate-200 pl-4">
              <p className="mb-2 text-xs font-medium text-muted-fg">模型思考过程</p>
              <pre className="whitespace-pre-wrap font-sans text-sm leading-relaxed text-slate-500">
                {streamText}
                {active && streamText.length < (scriptRef.current?.length || 0) ? (
                  <span className="ml-0.5 inline-block h-4 w-1.5 animate-pulse bg-slate-400 align-middle" />
                ) : null}
              </pre>
            </div>
          )}
        </div>
      ) : null}
    </section>
  );
}
