.PHONY: help install dev format lint typecheck test build docker-up docker-down clean

help: ## Display available commands
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-18s\033[0m %s\n", $$1, $$2}'

install: ## Install all dependencies (Node via pnpm, Python via uv)
	pnpm install
	uv sync

dev: ## Start local development services
	pnpm dev

format: ## Format codebase (ruff format + import sort, no black/isort - see pyproject.toml)
	uv run ruff format .
	uv run ruff check --select I --fix .

lint: ## Run linters across codebase (ruff & pnpm lint)
	uv run ruff check .
	pnpm lint

typecheck: ## Run type checking (mypy; strict, with a known non-blocking backlog)
	uv run mypy .

test: ## Run test suites (pytest with pytest-asyncio and pytest-cov, pnpm test)
	uv run pytest --cov
	pnpm test

build: ## Build all apps and packages
	pnpm build

docker-up: ## Start docker-compose stack
	docker compose up -d

docker-down: ## Stop docker-compose stack
	docker compose down

clean: ## Clean node_modules, build artifacts, and caches
	find . -name "node_modules" -type d -prune -exec rm -rf {} +
	find . -name "__pycache__" -type d -prune -exec rm -rf {} +
	find . -name ".dist" -type d -prune -exec rm -rf {} +
	find . -name "dist" -type d -prune -exec rm -rf {} +
