.PHONY: up down down-v migrate api test-contracts test-db test-backend openapi openapi-check lint

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

TEST_DB ?= checkmate_test_w3b
TEST_DATABASE_URL ?= postgresql://checkmate:checkmate@127.0.0.1:5432/$(TEST_DB)

test-db:       ## create and migrate the throwaway test database on the running compose db (never touches checkmate)
	docker compose exec -T db psql -U checkmate -d checkmate -tAc "SELECT 1 FROM pg_database WHERE datname='$(TEST_DB)'" | grep -q 1 || \
	  docker compose exec -T db psql -U checkmate -d checkmate -c "CREATE DATABASE $(TEST_DB)"
	DATABASE_URL=$(TEST_DATABASE_URL) uv run python -m contracts.migrations.apply

test-backend:  ## backend tests against the test database (make test-db first)
	TEST_DATABASE_URL=$(TEST_DATABASE_URL) uv run pytest backend/tests -q
