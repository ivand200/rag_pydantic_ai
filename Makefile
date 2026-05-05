SHELL := /bin/sh

.DEFAULT_GOAL := help

BACKEND_DIR := backend
FRONTEND_DIR := frontend
COMPOSE := docker compose

.PHONY: help setup infra-up infra-down infra-reset migrate backend-check backend-test evals frontend-format frontend-unit frontend-check e2e e2e-clerk e2e-schema-capture test

help: ## Show available targets.
	@awk 'BEGIN {FS = ":.*##"; printf "\nTargets:\n"} /^[a-zA-Z0-9_.-]+:.*##/ {printf "  %-14s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

.env:
	cp .env.example .env

setup: .env ## Install dependencies and create .env if it is missing.
	cd $(BACKEND_DIR) && uv sync
	cd $(FRONTEND_DIR) && npm install

infra-up: ## Start local infrastructure.
	docker compose up -d

infra-down: ## Stop local infrastructure and keep data.
	$(COMPOSE) down

infra-reset: ## Stop local infrastructure and remove persisted local data.
	$(COMPOSE) down -v

migrate: ## Apply backend database migrations.
	cd $(BACKEND_DIR) && uv run alembic upgrade head

backend-check: ## Run backend lint and formatting checks.
	cd $(BACKEND_DIR) && uv run ruff check .
	cd $(BACKEND_DIR) && uv run ruff format --check .

backend-test: ## Run backend unit/API tests.
	cd $(BACKEND_DIR) && uv run python -m tests.ensure_test_database
	cd $(BACKEND_DIR) && uv run pytest

evals: ## Run deterministic backend RAG evals against the test database.
	cd $(BACKEND_DIR) && uv run python -m tests.ensure_test_database
	cd $(BACKEND_DIR) && DATABASE_URL="$${TEST_DATABASE_URL:-postgresql+psycopg://rag_service:rag_service@localhost:5432/rag_service_test}" uv run alembic upgrade head
	cd $(BACKEND_DIR) && uv run python -m evals.runner

frontend-check: ## Run frontend type check and production build.
	cd $(FRONTEND_DIR) && npm run format:check
	cd $(FRONTEND_DIR) && npm run type-check
	cd $(FRONTEND_DIR) && npm run test:unit
	cd $(FRONTEND_DIR) && npm run build:only

frontend-format: ## Run frontend formatting checks.
	cd $(FRONTEND_DIR) && npm run format:check

frontend-unit: ## Run frontend unit tests.
	cd $(FRONTEND_DIR) && npm run test:unit

e2e: ## Run deterministic mocked frontend e2e smoke and schema-baseline tests.
	cd $(FRONTEND_DIR) && E2E_FRONTEND_PORT=5174 npm run e2e -- e2e/document-pool-smoke.spec.ts e2e/chat-session-smoke.spec.ts e2e/chat-stream-smoke.spec.ts e2e/schema-files.spec.ts

e2e-clerk: ## Run real Clerk auth/schema e2e checks when credentials are configured.
	cd $(FRONTEND_DIR) && E2E_FRONTEND_PORT=5174 npm run e2e:clerk

e2e-schema-capture: ## Capture/validate real document/chat API schemas when bearer tokens are configured.
	cd $(FRONTEND_DIR) && E2E_FRONTEND_PORT=5174 E2E_WRITE_SCHEMAS=1 npm run e2e -- e2e/document-real-schema-capture.spec.ts e2e/chat-real-schema-capture.spec.ts

test: ## Run the main local test suite.
	$(MAKE) infra-up
	$(MAKE) migrate
	$(MAKE) backend-check
	$(MAKE) backend-test
	$(MAKE) evals
	$(MAKE) frontend-check
	$(MAKE) e2e
