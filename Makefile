.PHONY: up down migrate seed fixtures api worker web test test-unit test-api test-activities test-workflows test-web

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
	cd frontend && VITE_API_BASE_URL=http://localhost:8000 npm run dev

test: test-unit test-api test-activities test-workflows test-web

# -c pyproject.toml is required here: pytest derives its config-file search
# root from the common ancestor of the invocation dir and the test paths, and
# `../tests/...` lives outside `backend/`, so without an explicit -c the
# `asyncio_mode = "auto"` setting in backend/pyproject.toml is silently not
# picked up and every bare `async def test_...` fails to collect.
test-unit:
	cd backend && uv run pytest -c pyproject.toml ../tests/unit -q

test-api:
	cd backend && uv run pytest -c pyproject.toml ../tests/api -q

test-activities:
	cd backend && uv run pytest -c pyproject.toml ../tests/activities -q

test-workflows:
	cd backend && uv run pytest -c pyproject.toml ../tests/workflows -q

test-web:
	cd frontend && npm test
