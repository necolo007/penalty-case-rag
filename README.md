# 保险监管处罚案例知识库与合规审查系统

基于知识增强检索的保险监管处罚案例知识库构建与合规审查智能匹配。

## 核心能力

| 任务 | 模块 | 说明 |
|------|------|------|
| 1 文档解析与抽取 | `pipeline/parser` + `pipeline/extraction` | PDF 分流；决定书/OCR：默认 `EXTRACTION_MODE=llm_first`（长字段 LLM 主抽，文号/机关正则回填）；`regex_first` 可回退 |
| 2 保险筛选与标签 | `engine/classification` | 28 类中文风险标签（规范 Prompt）+ 赛题粗类 **R001–R011** |
| 3 相似案例检索 | `engine/retrieval` | LLM 改写 + HyDE → BGE-M3（`dense_raw` / `dense` / `dense_hyde` + `sparse`）→ **max_merge** → CE 精排 → **LLM listwise**；`legacy_four_way` 可回滚 |
| 4 合规审查与归因 | `engine/review` | 风险句定位 + 逐句检索 + 可溯源审查意见 |
| 5 样本 / 知识增强 | `scripts/eval_task5_prompt_ab.py` + 检索合成 | **bare vs full** Prompt 消融（主指标 LLM-as-Judge）；标准融合任务二 |

## 技术栈

- **API**：FastAPI + asyncpg + ARQ（Redis）
- **存储**：PostgreSQL + pgvector（HNSW）+ sparse JSONB（官方 `pgvector/pgvector:pg16`）
- **LLM**：DeepSeek-V4-Flash（改写 / 抽取 / 分类 / 审查 / listwise）
- **召回**：`BAAI/bge-m3` dense + sparse（默认）；云端 embedding 仅 legacy
- **精排**：`bge-reranker-v2-m3` Cross-Encoder（可关）
- **OCR**：扫描件用 Docker OCR Worker（RapidOCR）；文字版可本机 `make worker`；勿本机装 OCR

## 快速启动

```bash
# 1. 环境
cp .env.example .env   # 填入 LLM_API_KEY
# DeepSeek：https://platform.deepseek.com/

# 2. 基础设施 + Python 依赖
docker compose up -d postgres redis
pip install -e ".[dev]"
pip install -e ".[local-models]"   # BGE-M3 + Reranker（任务3必需）

# 3. API（首次连库 AutoMigrate 建表 / 种子）
make api

# 4. 文档入库 Worker
make worker                                    # 文字版 PDF（本机轻量）
docker compose up -d --build worker            # 扫描件：OCR Worker

# 5. 批量入库 + 重建 dense/sparse 索引
python scripts/batch_ingest.py --dir data/raw
make reindex-embed
```

Swagger：`http://localhost:8000/docs`  
Web（React）：`http://localhost:8000/`（开发：`make web-dev` → Vite `:5173`）

### Docker 服务

| 服务 | 镜像 | 用途 |
|------|------|------|
| `postgres` | `pgvector/pgvector:pg16` | 案例库 + dense 向量 |
| `redis` | `redis:7-alpine` | ARQ 队列 |
| `worker` | `Dockerfile.worker.ocr` | 扫描件 OCR 入库 |
| `api` | `Dockerfile.api` | 可选整栈；日常用本机 `make api` |

```bash
docker compose up -d postgres redis          # 基础设施
docker compose up -d --build worker          # 需要扫扫描件时再启
docker compose run --rm worker python scripts/test_ocr.py
```

Postgres 宿主机端口默认 **15432**（`PG_HOST_PORT`），Redis 默认 **6534**。  
若曾用过自建 zhparser 镜像，切到官方 pgvector 时可重建卷：`docker compose down -v && docker compose up -d postgres redis`。

## 开发要点

- **任务3 默认**：`RETRIEVAL_BACKEND=bge_m3` + `EMBEDDING_PROVIDER=local_bge_m3`；融合为 dense 族 max_merge，不是 RRF
- **回滚四路**：`RETRIEVAL_BACKEND=legacy_four_way`（并视情况改 embedding + `make reindex-embed`）
- **精排关闭**：`RERANKER_ENABLED=false`（按召回融合顺序截断）
- **任务二**：规范 SYSTEM Prompt 打标（`RISK_CN_SYSTEM_PROMPT`）
- **任务五**：样本增强 = bare vs full Prompt 消融（`make eval-task5-ab`）+ 检索合成样本
- **评测产物不入库**：`data/eval/label_eval*`、`judge_*`、`label_judge_*`、`task5_prompt_ablation.*`、`task3_exp5_*` 等由 `.gitignore` 忽略，本地 `make eval` / `scripts/eval_*.py` 重跑即可；正式交付见仓库根目录 `deliver/`
- **对齐生产评测**：`make eval`；便宜模式 `make eval-cheap LIMIT=50`；检索 Judge：`scripts/eval_retrieval_judge.py`；任务五消融：`make eval-task5-ab`（含标签 LLM-as-Judge）
- **竞赛金标**：`make link-data` → `make import-gold` → `make reindex-embed`；隐藏答案放 `data/eval/quarantine/`
- API + Redis + Worker 需同时运行，否则文档停在 `pending`
- 切换 Embedding 模型后必须全量 `make reindex-embed`
