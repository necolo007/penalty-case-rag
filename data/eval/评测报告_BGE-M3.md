# 任务3 BGE-M3 评测与优化记录（2026-08-07）

## 结论摘要

BGE-M3（dense+sparse）已替换四路主路径并完成全量 reindex。  
**train 接近旧基线；test 仍受语域鸿沟限制。** 当前推荐配置见下文「已落地配置」。

| split | n | Top-1 | MRR | Recall@10 | 配置 |
|-------|---|-------|-----|-----------|------|
| **test（vb+summary）** | 30 | 0.033 | 0.051 | **0.150** | vb+summary 嵌入 + 规范化改写 + HyDE + 原文 CE |
| test（旧 v1） | 30 | 0.033 | **0.062** | 0.133 | raw_text 混嵌 + 旧追加改写 + 原文 CE |
| test（仅改写，消融） | 30 | 0.000 | 0.041 | **0.183** | `--rewrite-only`（不采纳为默认） |
| **train** | 30 | 0.333 | 0.478 | 0.494 | 旧配置（同义词改写，无 llm） |
| test legacy | 20 | 0.000 | 0.016 | 0.100 | 同 BGE-M3 向量上的四路回滚 |

当前推荐仍以 **vb+summary 嵌入** 为主（`submission_test_vb_summary_n30.jsonl`）；Judge 排序可用 **LLM listwise**（`submission_test_vb_summary_n30_listwise.jsonl`）。  
LLM 库内重抽 / 加权 RRF 扫参等实验已不采纳，产物已清理。  
对照基线：`submission_test_rerank_llm_bge_m3.jsonl`。

对照：旧四路 + Qwen 时代 test 精排约 Top-1/MRR/R@10≈0.10。  
本轮 test **Recall@10 略优于旧值**，Top-1/MRR 仍偏低。  
v3 同配置复现：MRR 0.048 / R@10 0.117（30 题中仅 4 题有分差，主因 LLM 改写非确定性，如 QT022）；生产仍以 v1 数字与配置为准。

## 诊断结论

1. 金标均在库内（test 相关 case 全有 `bge-m3` embedding）。
2. dense@200 池命中可达 **60–73%**（llm 改写更高），但 RRF 截到 Top-60/100 会把金标挤出精排窗口。
3. 改为 **dense_raw + dense 余弦 max 合并** 后池命中可保留；金标常排在 100–190 名 → **精排窗口需 ~200**。
4. 同向量下 legacy 四路更差 → 瓶颈是 **口语↔法言法语排序**，不是缺 BM25 四路。
5. 精排用 **原始口语 query** 优于改写句；过强 dense/CE 融合（如 0.65/0.35）会回退。

## 迭代对照

| 版本 | 要点 | test MRR | test R@10 | 结论 |
|------|------|----------|-----------|------|
| 首轮 | RRF dense/sparse + window60 | 0.033 | 0.033 | 差 |
| **v1（采用）** | 余弦合并 + 原文 CE + window200 + llm | **0.062** | **0.133** | **当前最优** |
| v2 | 改写 CE + 0.65/0.35 融合 + window120 | 0.037 | 0.067 | 弃用 |
| v3 | 同 v1 配置复现（~28min CPU） | 0.048 | 0.117 | LLM 改写方差，略逊；仍用 v1 |
| legacy | 四路 + 同 BGE-M3 向量 | 0.016 | 0.100 | 更差 |

## 已落地配置（生产默认）

- `EMBEDDING_PROVIDER=local_bge_m3`，`RETRIEVAL_BACKEND=bge_m3`
- `RECALL_DENSE=200`，`FUSION_SIZE=200`，`RERANK_CANDIDATES=200`
- **案例嵌入文本（2026-08-09）**：`违规行为：{violation_behavior}\n案件总结：{case_summary}`（`engine/embedding/case_text.py`）；**不再**拼 `raw_text` / risk_tags / penalty_content，避免文书套话稀释
- 召回：`dense_raw`（原文）+ `dense`（规范化改写 JSON）余弦 max；sparse 仅补位；可选 HyDE
- 改写：对齐 `docs/change/n8-4/任务三.md` → `normalized_violation`（不堆抽象风险标签）；原文由 dense_raw 单独编码
- 精排：`bge-reranker-v2-m3`，**原始口语 query**；文档字段优先违法行为
- 入库字段：建议 LLM 重抽 `violation_behavior`/`case_summary`，勿直接信任官方 `gold_extraction_cases.jsonl`

## 复跑命令

```bash
# 索引需为 bge-m3 且 sparse_weights 非空
python scripts/reindex_embeddings.py --batch-size 4

python scripts/eval_retrieval_local.py --split test --limit 30 --rerank --llm-rewrite --backend bge_m3 --rerank-candidates 200
python scripts/eval_retrieval_local.py --split train --limit 30 --rerank --backend bge_m3 --rerank-candidates 200
python scripts/diagnose_recall.py --split test --limit 50 --backend bge_m3 --llm-rewrite --fusion-top 200
```

## 已增强：HyDE 通道（2026-08-08）

在 dense_raw / dense（改写）之外新增 **dense_hyde**：

1. LLM 按决定书语体生成「假想违法事实」（保留话术中的数字/承诺）
2. 对该文本做 BGE-M3 dense 召回，与原文/改写结果做余弦 max 合并
3. 精排默认：口语 query CE；可选 **HyDE 双路 CE**（`RETRIEVAL_HYDE_RERANK=true`，与口语分取 max）

配置：`RETRIEVAL_HYDE_ENABLED=true`（默认开；无 `LLM_API_KEY` 时自动跳过）。

### 池命中探针（test n=20，无精排）

| 配置 | hit@50 | hit@100 | miss@200 |
|------|--------|---------|----------|
| 无 HyDE | 0.15 | 0.25 | 0.35 |
| +HyDE | **0.25** | **0.35** | **0.30** |

结论：HyDE 提升候选池命中，瓶颈仍在精排排序。

### 端到端 A/B（test 前 15 条，精排 200）

| 配置 | MRR | R@10 | Top-1 | 结论 |
|------|-----|------|-------|------|
| 无 HyDE（口语 CE） | 0.0150 | 0.100 | 0.0 | 基线 |
| +HyDE（口语 CE） | 0.0133 | 0.100 | 0.0 | 与基线持平（略低噪声） |
| +HyDE + 双路 CE | **0.0067** | **0.067** | 0.0 | **不采纳**（劣化） |

**默认策略**：保留 HyDE 召回通道（抬池命中）；精排只用口语 query（`RETRIEVAL_HYDE_RERANK=false`）。本切片 Top-10 极难，完整 test n=30 的 v1 基线约 MRR 0.062 / R@10 0.133，勿用前 15 条外推绝对水平。

```bash
# 推荐：HyDE 召回 + 口语 CE
python scripts/eval_retrieval_local.py --split test --limit 30 --rerank --llm-rewrite --hyde --backend bge_m3

# 对照：无 HyDE
python scripts/eval_retrieval_local.py --split test --limit 30 --rerank --llm-rewrite --no-hyde --backend bge_m3
```

## LLM-as-Judge 辅助评测（2026-08-10）

脚本：`scripts/eval_retrieval_judge.py`（prompt：`RETRIEVAL_JUDGE_PROMPT`）。  
对 Top-5 打 0/1/2「是否可作为合理相似判例」，**不替代** MRR/R@10。

同一切片 test n=30、Top-5：

| 提交 | mean_rel | hit≥2 | prec≥2 | mrr≥2 | 金标未中但 Judge≥2 |
|------|----------|-------|--------|-------|-------------------|
| vb+summary | **1.07** | **0.767** | 0.247 | 0.440 | **0.700** |
| 旧 v1（混嵌） | 0.89 | 0.667 | 0.227 | **0.446** | 0.600 |

vb+summary 在「至少一条强相关」与「金标未中仍合理」上最好。

### 排序优化（2026-08-11）：LLM 列表重排+减枝

目标：召回已够用时抬 **Judge 排序/精确率**（mrr≥2、prec≥2）。

加权 RRF / HyDE 双路 CE 等实验已不采纳，相关代码已移除；生产融合为 dense 族 **max_merge**。

**采用：CE Top-10 → LLM 列表重排+减枝**

- 代码：`RETRIEVAL_LLM_LISTWISE=true` 或 `scripts/llm_listwise_on_submission.py`
- 提交：`submission_test_vb_summary_n30_listwise.jsonl`（keep 3～8）
- 同轮 Judge 对照（Top-5，n=30）：

| 提交 | mean_rel | hit≥2 | prec≥2 | **mrr≥2** | 金标未中但 Judge≥2 |
|------|----------|-------|--------|-----------|-------------------|
| vb+summary 基线 | 1.00 | 0.700 | 0.213 | 0.416 | 0.633 |
| **+ LLM listwise** | **1.17** | **0.800** | **0.307** | **0.767** | **0.733** |

结论：listwise 显著抬高 **mrr≥2 / prec≥2**；默认关，可用开关打开。

```bash
python scripts/llm_listwise_on_submission.py \
  --submission data/eval/submission_test_vb_summary_n30.jsonl \
  --keep-min 3 --keep-max 8

python scripts/eval_retrieval_local.py --split test --limit 30 --rerank --llm-rewrite --llm-listwise

python scripts/eval_retrieval_judge.py --compare \
  data/eval/submission_test_vb_summary_n30.jsonl \
  data/eval/submission_test_vb_summary_n30_listwise.jsonl \
  --top-k 5
```

### 消融：仅改写 query（2026-08-10）

关闭 `dense_raw` 与 HyDE，只保留改写句的 dense + sparse，精排仍用口语原文。

| 配置 | MRR | R@10 |
|------|-----|------|
| vb+summary 全文（raw+改写+HyDE） | 0.051 | 0.150 |
| **仅改写** | 0.041 | **0.183** |

R@10 升、MRR 略降：改写更利于「进 Top10」，原文通道对靠前排序仍有帮助。改写样例见 `data/eval/query_rewrites_test_n30.jsonl`。

```bash
python scripts/dump_query_rewrites.py --split test --limit 30
python scripts/eval_retrieval_local.py --split test --limit 30 --rerank --llm-rewrite --rewrite-only --backend bge_m3
```

## 下一步（模型/语料级）

参数/管道侧已局部触顶：HyDE 抬池、双路 CE 伤精排。更高杠杆：

1. 口语↔案例平行语料微调 BGE-M3 / reranker（主推）
2. 改进 HyDE 提示或少样本示例（使假想事实更贴库内表述）
3. 扩库后前后 A/B（勿只拧融合权重）
4. 用 Judge 报告辅助人工重标 test 金标（见 `docs/change/n8-4/任务三.md`）
