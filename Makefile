.PHONY: install dev db worker api test lint export submission docker-ocr-build docker-ocr-test docker-up

install:
	pip install -e ".[dev]"

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

submission:
	python scripts/run_batch_submission.py \
		--input data/eval/test_questions.jsonl \
		--output data/eval/submission.jsonl

eval:
	python scripts/eval_retrieval.py \
		--submission data/eval/submission.jsonl \
		--gold data/eval/test_gold_labels.jsonl \
		--k 5 10

docker-up:
	docker compose up -d postgres redis api worker

docker-ocr-build:
	docker compose build worker

docker-ocr-test:
	docker compose run --rm worker python scripts/test_ocr.py
