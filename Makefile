.PHONY: up down down-v migrate api test-contracts openapi openapi-check lint

up:            ## database + API
	docker compose up -d --build
	@echo "API: http://127.0.0.1:8000/api/v1/health"

down:
	docker compose down

down-v:        ## rebuild from the seed: drops the synthetic database
	docker compose down -v

db:            ## database only (for local uvicorn)
	docker compose up -d db

migrate:
	uv run python -m contracts.migrations.apply

api:           ## run the API locally against the compose database
	uv run uvicorn backend.app.main:app --host 127.0.0.1 --port 8000 --reload

test-contracts:
	uv run pytest contracts/tests -q

openapi:
	uv run python -m contracts.build_openapi

openapi-check:
	uv run python -m contracts.build_openapi --check

lint:
	uv run ruff check contracts backend
