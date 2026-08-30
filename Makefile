.PHONY: up down migrate seed fixtures api worker web test test-unit test-api test-web

up:
	docker compose up -d

down:
	docker compose down

migrate:
	cd backend && uv run alembic upgrade head

seed:
	cd backend && uv run python -m sbda.db.seed

fixtures:
	cd backend && uv run python ../fixtures/generate.py

api:
	cd backend && uv run uvicorn sbda.api.main:app --reload --port 8000

worker:
	cd backend && uv run python -m sbda.temporal.worker

web:
	cd frontend && npm run dev

test: test-unit test-api test-web

test-unit:
	cd backend && uv run pytest ../tests/unit -q

test-api:
	cd backend && uv run pytest ../tests/api -q

test-web:
	cd frontend && npm test
