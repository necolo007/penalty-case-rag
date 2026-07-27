.PHONY: install install-local-models db worker api test lint export \
	docker-ocr-build docker-ocr-test docker-up docker-postgres-build docker-postgres-up \
	link-data import-gold web-install web-dev web-build reindex-embed sync-dict \
	eval eval-cheap eval-rerank eval-all

# Windows / uv 环境下保证顶层包可导入
export PYTHONPATH := .
LIMIT ?= 50

install:
	pip install -e ".[dev]"

install-local-models:
	uv pip install -e ".[local-models]"

web-install:
	cd web && npm install

web-dev:
	cd web && npm run dev

web-build:
	cd web && npm run build

db:
	python scripts/setup_db.py

api:
	uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload

# 本机轻量 Worker（pdfplumber，无 OCR）。扫描件请用 docker-ocr-build + docker compose up worker
worker:
	arq pipeline.tasks.ingest.WorkerSettings

test:
	pytest tests/ -v

lint:
	ruff check .

export:
	python scripts/export_all.py

link-data:
	python scripts/link_comp_data.py

import-gold: link-data
	python scripts/import_gold_cases.py

reindex-embed:
	python scripts/reindex_embeddings.py

sync-dict:
	python scripts/sync_dictionaries.py

# 离线评测：字段抽取 + 标签 + 检索（无精排，便宜）
# 用法：make eval-cheap LIMIT=50
eval-cheap:
	python scripts/run_eval.py --extract-limit $(LIMIT) --label-limit $(LIMIT) --retrieval-limit $(LIMIT)

eval:
	python scripts/run_eval.py --retrieval-limit 50

eval-rerank:
	python scripts/run_eval.py --retrieval-limit 30 --rerank

eval-all: eval-cheap eval-rerank

docker-up:
	docker compose up -d postgres redis api worker

docker-postgres-build:
	docker compose build postgres

docker-postgres-up:
	docker compose up -d postgres redis

docker-ocr-build:
	docker compose build worker

docker-ocr-test:
	docker compose run --rm worker python scripts/test_ocr.py
