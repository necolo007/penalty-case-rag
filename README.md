# 保险监管处罚案例知识库与合规审查系统（后端 RAG）

基于知识增强检索的保险监管处罚案例知识库构建与合规审查智能匹配 — 后端实现。

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

### WSL / Docker 全栈（含 OCR）

在 WSL2 中推荐用 Docker 跑 MinerU + PaddleOCR（Windows 本机难以安装 parsing 栈）：

```bash
# 构建 OCR Worker 镜像（首次约 5–10 分钟，镜像 ~3GB）
make docker-ocr-build

# 启动 postgres + redis + api + OCR worker
make docker-up

# 冒烟测试：校验 paddle / paddleocr / magic_pdf 导入
make docker-ocr-test

# 对扫描件实测 OCR（将 PDF/图片放到 uploads/ 后）
docker compose run --rm worker python scripts/test_ocr.py /app/uploads/your_scan.pdf
```

> **说明**：默认 `worker` 使用 `Dockerfile.worker.ocr`（CPU 即可跑 OCR）。
> 无需 OCR 时用轻量 Worker：`docker compose --profile lite up -d worker-lite`
> 有 NVIDIA GPU 时：`docker compose --profile gpu up -d worker-gpu`

> **注意**：`pgvector/pgvector:pg16` 镜像不含 zhparser 扩展，生产部署请使用包含
> zhparser 的自建镜像，或在容器内编译安装（SCWS + zhparser）。

完整路由见 `http://localhost:8000/docs`（Swagger UI）。

## 比赛提交流水线

```bash
# 生成提交文件
make submission

# 本地评测（需 gold 标签）
make eval

# 一键导出全部交付物（manifest / candidates / gold / 标签字典 / 主体关联）
make export

# 样本增强：反向生成检索训练 query
python scripts/data_augmentation.py --limit 100
```

## 开发说明

- **数据库 AutoMigrate**：`AUTO_MIGRATE=true`（默认）时，API/Worker 启动自动执行 `db/migrations/` 建表与种子；关闭后需手动 `python scripts/setup_db.py`
- 无 LLM Key 时系统可降级运行：查询改写退化为同义词词典扩展，审查生成接口返回 503
- 无本地模型时：`RERANKER_ENABLED=false` 关闭精排（按 RRF 顺序输出）
- 切换 Embedding 模型后必须全量重建 `case_embeddings`（向量空间不一致）
