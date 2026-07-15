.PHONY: install dev db worker api test lint export submission eval \
	docker-ocr-build docker-ocr-test docker-up \
	link-data import-gold eval-local web-install web-dev web-build

# Windows / uv 环境下保证顶层包可导入
export PYTHONPATH := .

install:
	pip install -e ".[dev]"

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

submission:
	python scripts/run_batch_submission.py \
		--input data/eval/test_questions.jsonl \
		--output data/eval/submission.jsonl

eval:
	python scripts/eval_retrieval.py \
		--submission data/eval/submission.jsonl \
		--gold data/eval/test_gold_labels.jsonl \
		--k 5 10

eval-local: submission eval

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
