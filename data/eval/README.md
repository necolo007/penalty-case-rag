# `data/eval` 目录说明

评测相关数据与产物。根目录只保留**输入/金标**与**当前有效结果**；`archive/` 仅作占位说明。

## 根目录（当前有效）

| 类别 | 文件 |
|------|------|
| 竞赛输入 | `test_questions.jsonl`、`test_queries.jsonl`、`retrieval_train_queries.jsonl`、`risk_type_dictionary.csv` |
| 竞赛抽取金标 | `gold_extraction_cases.jsonl`、`gold_extraction_cases.cleaned.jsonl` |
| 任务1（521） | `gold_extraction_521_cleaned.jsonl`、`extracted_cases_hybrid_521.jsonl`、`extraction_eval_hybrid_521_cleaned_bert.json` |
| 任务2（822/481） | `gold_task2_822_cleaned.jsonl`、`label_eval_report_822_llm.json`、`predicted_risk_tags_822_llm.jsonl` |
| 任务2 few-shot A/B | `label_eval_task2_full_nofs.json`、`*_excel_fs*`、`*_multilabel_fs3*`（及对应 `predicted_task2_full_*.jsonl`） |
| 任务五 提示词消融 | `task5_prompt_ablation.md` / `.json`；`label_eval_task5_prompt_{bare,full}.json` |
| 任务3 提交 | `submission.jsonl`（全量）；`submission_test_vb_summary_n30*_listwise*`（n30 评测） |
| 任务3 对照 | `submission_test_vb_summary_n30.jsonl`、`submission_test_rerank_llm_bge_m3.jsonl` |
| 改写样例 | `query_rewrites_test_n30.jsonl` |
| LLM-as-Judge | `judge_test_vb_summary_n30*_top5.*`、`judge_compare_top5.json` |
| 报告 | `效果总结.md`、`评测报告_BGE-M3.md`、`README_竞赛数据说明.md` |
| 隔离答案 | `quarantine/test_gold_labels.jsonl`（勿用于调参） |

## 已清理（勿再引用）

- 任务2 中间金标：`gold_task2_820/821_*` 及对应 predicted / label_eval_report
- 任务2 实验：`*_fixed_*`、`*_gated_*`、`*_gate_compare*`
- 临时：`submission_smoke*`、`label_eval_*_run.log`
- 任务3 改写动态 few-shot 库与脚本（已移除）

## 评测 ↔ 生产对齐

| 任务 | 评测默认 | 生产默认 |
|------|----------|----------|
| 1 | `reextract --mode llm_first` + `gold_extraction_521_cleaned` | `EXTRACTION_MODE=llm_first` |
| 2 | `eval_labels --with-llm` + `gold_task2_822_cleaned`；few-shot 用评测集外 Excel/多标签库 | `RiskTagger` + 动态 few-shot |
| 3 | `make eval-rerank`：rewrite/rerank/listwise；效果以 Judge 为准 | `RETRIEVAL_LLM_LISTWISE=true` |
| 4 | 无自动金标 | `/review` 复用任务3 |

一键：`make eval` / `make eval-cheap` / `make eval-task2-ab` / `make eval-task2-multilabel`。
