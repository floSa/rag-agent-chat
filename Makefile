.PHONY: lint format typecheck test audit up down logs

lint:
	ruff check src/ tests/

format:
	ruff format src/ tests/
	ruff check --fix src/ tests/

typecheck:
	mypy src/

test:
	pytest tests/unit/ -v

test-integration:
	pytest tests/integration/ -v -m integration

audit:
	pip-audit -r requirements.txt

up:
	docker compose up -d

down:
	docker compose down

logs:
	docker compose logs -f

ollama-shell:
	docker compose exec ollama ollama list
