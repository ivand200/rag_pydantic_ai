SHELL := /bin/sh

.DEFAULT_GOAL := help

BACKEND_DIR := backend
FRONTEND_DIR := frontend
COMPOSE := docker compose

.PHONY: help setup infra-up infra-down migrate test-unit test

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

infra-down-v:
	$(COMPOSE) down -v

migrate: ## Apply backend database migrations.
	cd $(BACKEND_DIR) && uv run alembic upgrade head

test-unit: ## Run backend unit/API tests.
	cd $(BACKEND_DIR) && uv run pytest

test: ## Run the main local test suite.
	$(MAKE) infra-up
	$(MAKE) migrate
	cd $(BACKEND_DIR) && uv run ruff check .
	cd $(BACKEND_DIR) && uv run ruff format --check .
	cd $(BACKEND_DIR) && uv run pytest
	cd $(FRONTEND_DIR) && npm run type-check
	cd $(FRONTEND_DIR) && npm run build
	$(COMPOSE) config
