.PHONY: ingest dev deploy test lint

ingest:
	cd backend && python scripts/ingest_docs.py

dev:
	docker compose up --build

deploy:
	cd infra && cdk deploy --all

test:
	pytest tests/ -v

lint:
	ruff check backend/ frontend/