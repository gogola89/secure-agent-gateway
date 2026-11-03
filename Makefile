include .env
export

PYTHON := .venv/bin/python
PIP := .venv/bin/pip
CUSTOMER ?= amina

.PHONY: up down keys seed test lint format openapi login confirm run-api run-mcp

up:
	docker compose up -d postgres redis rabbitmq
	$(MAKE) keys
	$(PYTHON) -m alembic upgrade head

down:
	docker compose down

keys:
	mkdir -p keys var
	$(PYTHON) scripts/gen_keys.py

seed:
	$(PYTHON) scripts/seed.py

test:
	$(PYTHON) -m pytest --cov=banking_api --cov-report=term-missing

lint:
	$(PYTHON) -m ruff check .
	$(PYTHON) -m ruff format --check .

format:
	$(PYTHON) -m ruff format .
	$(PYTHON) -m ruff check --fix .

openapi:
	$(PYTHON) -c "import json; from banking_api.main import app; json.dump(app.openapi(), open('openapi.json', 'w'), indent=2, sort_keys=True)"

run-api:
	$(PYTHON) -m uvicorn banking_api.main:app --reload --port 8000

run-mcp:
	$(PYTHON) -m mcp_server.server

login:
	$(PYTHON) scripts/login.py $(CUSTOMER)

confirm:
	$(PYTHON) scripts/confirm_transfer.py $(CUSTOMER) $(TRANSFER) $(OTP)
