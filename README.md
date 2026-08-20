# 保险监管处罚案例知识库与合规审查系统

基于知识增强检索的保险监管处罚案例知识库构建与合规审查智能匹配

完整部署说明（本地模型/权重、词典、环境变量、依赖与启动步骤）见仓库文档：  
[docs/deployment-guide.md](../docs/deployment-guide.md)

## 核心能力

| 任务块 | 模块 | 说明 |
|--------|------|------|
| 任务1 文档解析与结构化抽取 | `pipeline/parser` + `pipeline/extraction` | PDF 分流；决定书/OCR：LLM 主抽长字段 + 文号/机关正则回填（`hybrid`）；公示表映射；`EXTRACTION_MODE=regex_first` 可回退 |
| 任务2 保险筛选与标签归类 | `engine/classification` | 三维词典加权打分 + 三级风险标签（内外双轨 R001–R008） |
| 任务3 相似案例检索（核心） | `engine/retrieval` | LLM 改写 + HyDE → BGE-M3（dense_raw/dense/dense_hyde + sparse）→ 余弦合并 → bge-reranker；`legacy_four_way` 可回滚 |
| 任务4 合规审查与归因 | `engine/review` | 风险句定位（规则/词典/LLM 三重）+ 逐句检索 + 可追溯审查意见 |
| 任务5 样本增强与金标导入 | `scripts/data_augmentation.py` 等 | 竞赛配套数据接入、金标入库、样本增强 |

## 技术栈

- **API**：FastAPI + asyncpg + ARQ(Redis)
- **存储**：PostgreSQL + pgvector（HNSW）+ sparse JSONB 倒排；zhparser 保留供 legacy BM25
- **LLM**：DeepSeek-V4-Flash（改写/抽取/分类/审查，统一客户端）
- **Embedding / 召回**：FlagEmbedding `BAAI/bge-m3`（dense+sparse，默认）；云端 Qwen / bge-large 仅 legacy
- **Reranker**：`bge-reranker-v2-m3` 本地 Cross-Encoder（可 CPU / 可关闭）
- **OCR**：仅 Docker Worker（RapidOCR ONNX），不支持本机安装

## 快速启动

```bash
# 1. 配置环境变量
cp .env.example .env   # 填入 LLM_API_KEY；任务3默认本地 BGE-M3，需 install-local-models
# LLM查看ds token官网：https://platform.deepseek.com/

# 2. 启动基础设施 + 依赖
docker compose up -d postgres redis
pip install -e ".[dev]"
pip install -e ".[local-models]"   # BGE-M3 + Reranker（任务3必需）

# 3. 启动 API（首次连接 DB 时自动建表/种子，含 sparse 列迁移）
make api        # uvicorn api.main:app --port 8000

# 4. 文档入库 Worker
#    文字版 PDF：本机轻量 Worker
make worker
#    含扫描件：必须用 Docker OCR Worker（勿本机 pip 装 OCR）
docker compose build worker && docker compose up -d worker

# 5. 批量入库 / 重建 BGE-M3 双表征索引
python scripts/batch_ingest.py --dir data/raw
make reindex-embed   # 写入 dense + sparse_weights
```

### Docker OCR Worker（扫描件）

Windows / 本机不安装 OCR 依赖。扫描件解析统一走 Docker：

```bash
# 构建 OCR Worker
docker compose build worker

# 启动基础设施 + OCR worker（本机可只跑 API）
docker compose up -d postgres redis worker

# 冒烟测试（必须在容器内）
docker compose run --rm worker python scripts/test_ocr.py

# 扫描件实测（文件放到 uploads/）
docker compose run --rm worker python scripts/test_ocr.py /app/uploads/your_scan.pdf
```

> **说明**：默认 `worker` → `Dockerfile.worker.ocr`（RapidOCR + pdfplumber）。  
> 无 OCR 轻量版：`docker compose --profile lite up -d worker-lite`  
> GPU profile：`docker compose --profile gpu up -d worker-gpu`（仍为 RapidOCR 镜像）

> **注意**：默认 Postgres 使用 `Dockerfile.postgres`（pgvector + zhparser）。  
> 构建：`docker compose build postgres`；`.env` 建议 `REQUIRE_ZHPARSER=true` 禁止降级。

### Postgres 启用 zhparser（中文 BM25，不降级）

`pgvector/pgvector:pg16` 官方镜像不含 zhparser。项目已提供 `Dockerfile.postgres` 在 pgvector 基础上编译 SCWS + zhparser：

```powershell
# 1. .env 中强制要求 zhparser（可选但推荐）
# REQUIRE_ZHPARSER=true

# 2. 构建镜像（首次约 3–5 分钟）
docker compose build postgres

# 3. 若之前用过 simple 降级，需清空旧数据卷后重建
docker compose down -v
docker compose up -d postgres redis

# 4. 验证扩展
docker exec penalty-case-rag-postgres-1 psql -U kb_admin -d penalty_kb -c `
  "CREATE EXTENSION IF NOT EXISTS zhparser; SELECT extname FROM pg_extension WHERE extname IN ('vector','zhparser');"

# 5. 启动本地 API（AutoMigrate 会自动创建 zhparser_config）
uv run --no-sync uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload
```

验证中文分词：

```sql
SELECT * FROM ts_parse('zhparser', '销售误导 给予合同外利益');
```

日志中应出现：`Text search config: zhparser_config (zhparser)`，而不是 simple fallback。

完整路由见 `http://localhost:8000/docs`（Swagger UI）。  
Web 前端（React）：`http://localhost:8000/`（总览 / 检索 / 案例库 / 文档入库 / 合规审查）。

```bash
# 开发模式（Vite 热更新，代理 /api → :8000）
make web-dev          # 或 cd web && npm run dev

# 生产构建（产物 web/dist，由 FastAPI 托管）
make web-build        # 或 cd web && npm run build
```

## 开发说明

- **数据库 AutoMigrate**：`AUTO_MIGRATE=true`（默认）时，API/Worker 启动自动执行 `db/migrations/` 建表与种子；关闭后需手动 `python scripts/setup_db.py`
- 无 LLM Key 时系统可降级运行：查询改写退化为同义词词典扩展，审查生成接口返回 503
- 任务3 默认 `RETRIEVAL_BACKEND=bge_m3` + `EMBEDDING_PROVIDER=local_bge_m3`，需 `pip install -e ".[local-models]"`；Hub 权重经 `HF_ENDPOINT`（默认 hf-mirror）拉取
- 回滚四路：`RETRIEVAL_BACKEND=legacy_four_way`（并视情况切回 cloud embedding + reindex）
- 无本地模型时：`RERANKER_ENABLED=false` 关闭精排（按 RRF 顺序输出）
- 启用精排：`pip/uv install -e ".[local-models]"`，并设 `RERANKER_DEVICE=cpu`（无 GPU）或 `cuda`
- 向量重建（BGE-M3 dense+sparse）：`make reindex-embed`（文档侧为 `违规行为`+`案件总结`，不含 raw_text）
- 任务3 查询改写：规范化行为描述 JSON（`normalized_violation`）；原文走 dense_raw，改写走 dense
- 离线便宜评测（不对齐生产最优）：`make eval-cheap LIMIT=50`
- 对齐生产一键评测：`make eval`（hybrid+LLM 标签 + 检索 rewrite/rerank/listwise）
- 任务1 长字段默认 BERTScore：`pip install -e ".[eval]"` 后跑 `scripts/eval_extraction.py`（`--no-bert-score` 可回退字符重叠；默认 `HF_ENDPOINT=https://hf-mirror.com`）
- 含精排+改写+listwise：`make eval-rerank`（默认 bge_m3，与生产对齐）
- 检索合理性（LLM-as-Judge，辅助）：`python scripts/eval_retrieval_judge.py --submission data/eval/submission_test_vb_summary_n30_listwise.jsonl --top-k 5`
- 双后端 A/B：`make eval-ab`（legacy_four_way vs bge_m3，需已 reindex）
- 竞赛数据接入：`make link-data` → `make import-gold` → `make reindex-embed`
  - `test_gold_labels.jsonl` 默认隔离到 `data/eval/quarantine/`，不进评测主目录
  - 评测目录约定见 `data/eval/README.md`（当前结果在根目录，历史实验在 `data/eval/archive/`）
- 批量提交：`POST /api/v1/retrieve/batch-submission` → `data/eval/retrieval_submission.jsonl`
  （失败写入 `submission_errors.jsonl`，不含 `error` 字段进提交文件）
- 切换 Embedding 模型后必须全量重建 `case_embeddings`（向量空间不一致）
- 上传按 `content_sha256` 去重；解析失败可用 `POST /api/v1/documents/{file_id}/retry` 重试
- API + Redis + Worker 需同时运行，否则文档会停在 `pending`
- 扫描件 OCR：**仅** Docker Worker，禁止本机安装 RapidOCR / PaddleOCR
