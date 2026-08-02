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

# Exige la stack demarree ; sans elle les tests sont ignores, pas en echec.
test-integration:
	API_URL=http://localhost:8011 pytest tests/integration/ -v -m integration

audit:
	pip-audit -r requirements.txt

up:
	docker compose up -d

down:
	docker compose down

logs:
	docker compose logs -f

# Les LLM viennent du projet llm-service : c'est lui qu'on interroge.
models:
	docker exec ollama-central ollama list

health:
	curl -s http://localhost:8011/health

# Campagne d'evaluation : rappel du retrieval, completude des citations,
# abstention et latence. Deterministe, sans juge LLM.
eval:
	uv run python scripts/evaluate.py --golden tests/fixtures/golden_qa_generated.json \
		--out runs/$(shell date +%Y%m%d-%H%M).json --compare runs/reference.json
