.PHONY: install backend frontend test lint migrate migration dev images

install:
	cd backend && python3 -m venv .venv && .venv/bin/pip install -q -e ".[dev]"
	cd frontend && npm install

backend:
	cd backend && .venv/bin/uvicorn app.main:app --reload --port 8000

frontend:
	cd frontend && npm start

test:
	cd backend && .venv/bin/python -m pytest tests -q
	cd frontend && npx ng build

lint:
	cd backend && .venv/bin/ruff check app tests migrations

# Apply migrations to SHIFTLEFT_DATABASE_URL. Every deployed environment runs this before start.
migrate:
	cd backend && .venv/bin/alembic upgrade head

# After changing a model: make migration m="add widget owner"
migration:
	cd backend && .venv/bin/alembic revision --autogenerate -m "$(m)"

# Postgres + Redis. Optional — the service runs on SQLite without them.
dev:
	docker compose up -d

images:
	docker build -t shiftleft-backend backend
	docker build -t shiftleft-frontend frontend
