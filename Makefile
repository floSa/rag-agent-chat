.PHONY: install lint format typecheck test audit up down logs

# UN SEUL GESTE arme ce que ce depot sait garder de son historique, et c'est
# celui-ci. Il ne remplace PAS l'installation de l'environnement de
# developpement : la porte qualite (`make lint`, `make test`) appelle ses outils
# NUS, depuis `requirements-dev.txt`, comme la CI — le protocole est au §2.2 de
# documentation/pilotage_du_chantier.md. Cette cible-ci arme les hooks git, et
# rien d'autre.
#
# `--only-group hooks` : le groupe ne porte que le framework `pre-commit`. Sans
# cette borne, `uv sync` installerait les dependances de production, dont
# `sentence-transformers`, donc `torch` — epingle depuis PyPI dans `uv.lock`
# avec 43 paquets `nvidia-*`. Armer un hook git ne telecharge pas la pile CUDA.
#
# `--inexact` : sans lui, `uv sync` RETIRE du `.venv` tout ce qui n'est pas dans
# le groupe demande, donc `ruff`, `mypy` et `pytest` que le protocole du §2.2 y
# a installes. La cible armerait les hooks en desarmant la porte qualite.
#
# La seconde ligne fait ce que la premiere ne peut pas faire : git n'execute
# jamais ce qui arrive avec un clone. Le script arme les hooks ET verifie qu'ils
# le sont, en sortant en erreur sinon — un garde-fou qui repose sur la memoire
# du suivant n'est pas un garde-fou.
install:
	uv sync --inexact --only-group hooks
	sh scripts/installer-les-garde-fous.sh

# La CI appelle `make lint` puis `make test`. Le typecheck est rattache au lint
# — tous deux sont de l'analyse statique — parce que modifier le workflow exige
# un jeton avec le scope `workflow`, que le jeton de push n'a pas. Sans ce
# rattachement, `make typecheck` ne tournerait jamais en integration continue,
# ce qui a deja laisse passer 54 erreurs.
lint: typecheck
	ruff check src/ tests/ scripts/

format:
	ruff format src/ tests/
	ruff check --fix src/ tests/

# La version de mypy est epinglee dans requirements-dev.txt : `uv run --with
# mypy` en tirerait une plus recente, plus permissive sur certains points, et
# la CI trouverait des erreurs invisibles en local.
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

# Campagne d'evaluation : rappel du retrieval, precision du contexte, completude
# des citations, abstention et latence par etage. Deterministe, sans juge LLM.
#
# La comparaison est APPARIEE question par question, et elle REFUSE de tourner si
# les deux jeux de questions diffèrent (code de sortie 2). La cible etait
# `runs/reference.json`, qui ne porte que 117 des 138 lignes : chaque `make eval`
# confrontait donc 138 moyennes a 117 moyennes, en silence. `runs/final.json`
# porte les 138 et c'est la configuration retenue, donc la bonne base.
eval:
	uv run python scripts/evaluate.py --golden tests/fixtures/golden_qa_generated.json \
		--out runs/$(shell date +%Y%m%d-%H%M).json --compare runs/final.json
