# 保险监管处罚案例知识库与合规审查系统

基于知识增强检索的保险监管处罚案例知识库构建与合规审查智能匹配

## 核心能力

| 任务块 | 模块 | 说明 |
|--------|------|------|
| 任务1 文档解析与结构化抽取 | `pipeline/parser` + `pipeline/extraction` | PDF 分流（公示表→pdfplumber / 决定书→MinerU / 扫描件→OCR）+ 正则抽取 + LLM 纠错 |
| 任务2 保险筛选与标签归类 | `engine/classification` | 三维词典加权打分 + 三级风险标签（内外双轨 R001–R008） |
| 任务3 相似案例检索（核心） | `engine/retrieval` | LLM 改写 → instruct embed → 四路召回（BM25/向量/标签/规则）→ RRF → Reranker |
| 任务4 合规审查与归因 | `engine/review` | 风险句定位（规则/词典/LLM 三重）+ 逐句检索 + 可追溯审查意见 |
| 任务5 标注与评测 | `scripts/` + `api/routes/eval.py` | Recall@K / MRR / NDCG / 字段 F1 + 样本增强 |

## 技术栈

- **API**：FastAPI + asyncpg + ARQ(Redis)
- **存储**：PostgreSQL + pgvector（HNSW）+ zhparser（中文全文检索）
- **LLM**：DeepSeek-V4-Flash（改写/抽取/分类/审查，统一客户端）
- **Embedding**：Qwen text-embedding-v4 云端 API（主）/ bge-large-zh 本地（兜底）
- **Reranker**：bge-reranker-v2-m3 本地 Cross-Encoder（可 CPU / 可关闭）

## 快速启动

```bash
# 1. 配置环境变量（API Key 禁止入库）
cp .env.example .env   # 填入 LLM_API_KEY / EMBEDDING_API_KEY

# 2. 启动基础设施 + 依赖
docker compose up -d postgres redis
pip install -e ".[dev]"

# 3. 启动 API 与 Worker（首次连接 DB 时自动建表/种子，无需手动跑 SQL）
make api        # uvicorn api.main:app --port 8000
make worker     # arq 文档解析 worker

# 4. 批量入库原始处罚文件
python scripts/batch_ingest.py --dir data/raw
```

### WSL / Docker（含 OCR）

Windows 本机 PaddleOCR 不稳定，且 Paddle 与 Torch/OpenCV 混装易 SIGSEGV。  
Docker OCR Worker 使用 **RapidOCR（ONNX）**：扫描件走 OCR，文字 PDF 走 pdfplumber。

```bash
# 构建 OCR Worker
docker compose build worker

# 启动基础设施 + OCR worker（本机可只跑 API）
docker compose up -d postgres redis worker

# 冒烟测试
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

## 竞赛数据与本地评测

（500 金标 + 300 训练查询 + 200 测试题）。**不要把万级 PDF 拷进本项目**。

```bash
# 1. 将评测文件复制到 data/eval/（也可设置 COMP_DATA_DIR）
make link-data

# 2. 导入官方金标 C001–C500（保留官方 ID，写入向量；需 Embedding Key）
#    自动关联赛题包 raw_text/{file_id}.txt
make import-gold

# 3. API 启动后生成 submission 并评测
make api          # 另开终端
make eval-local   # = submission + eval → data/eval/eval_report.json
```

相关脚本：

| 命令 | 作用 |
|------|------|
| `scripts/link_comp_data.py` | 接入配套评测文件 |
| `scripts/import_gold_cases.py` | 导入金标 + embedding |
| `scripts/run_batch_submission.py` | 生成 `submission.jsonl` |
| `scripts/eval_retrieval.py` | Recall@K / MRR / NDCG |

标签：库内 `risk_type_ids` 存 R001–R008；提交 `risk_type` 默认输出配套中文标签（`SUBMISSION_RISK_STYLE=cn`）。

## 开发说明

- **数据库 AutoMigrate**：`AUTO_MIGRATE=true`（默认）时，API/Worker 启动自动执行 `db/migrations/` 建表与种子；关闭后需手动 `python scripts/setup_db.py`
- 无 LLM Key 时系统可降级运行：查询改写退化为同义词词典扩展，审查生成接口返回 503
- 无本地模型时：`RERANKER_ENABLED=false` 关闭精排（按 RRF 顺序输出）
- 切换 Embedding 模型后必须全量重建 `case_embeddings`（向量空间不一致）
- 上传按 `content_sha256` 去重；解析失败可用 `POST /api/v1/documents/{file_id}/retry` 重试
- API + Redis + Worker 需同时运行，否则文档会停在 `pending`
