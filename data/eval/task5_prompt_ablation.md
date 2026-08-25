# 任务五：提示词规范消融实验

## 设定

- 金标：`gold_task2_822_cleaned.jsonl`
- **关闭 few-shot**，只对比 SYSTEM 提示词
- **bare**：只给 27 类标签名，不解释判定标准
- **full**：当前规范提示词（总则 + 每类正例/排除边界）

## 结果

| 指标 | bare（无标准） | full（规范提示词） | Δ (full−bare) |
|---|---:|---:|---:|
| Exact Match | 0.4802 | 0.6778 | 0.1976 |
| Mean Jaccard | 0.7538 | 0.8507 | 0.0969 |
| Macro F1 | 0.7589 | 0.8322 | 0.0733 |
| R00x Macro F1 | 0.8677 | 0.9163 | 0.0486 |

## 结论

在相同模型与金标下，仅补充「风险类别判定标准」即可显著提升多标签分类效果；说明任务五中「规范提示词 / 标签标准沉淀」是有效的样本与知识增强手段（与 few-shot 示例库互补）。

## 产物

- `data/eval/label_eval_task5_prompt_bare.json`
- `data/eval/label_eval_task5_prompt_full.json`
- `data/eval/task5_prompt_ablation.json`
- `data/eval/predicted_task5_prompt_bare.jsonl`
- `data/eval/predicted_task5_prompt_full.jsonl`
