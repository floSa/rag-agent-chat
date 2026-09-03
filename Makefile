.PHONY: install lint format typecheck test audit up down logs

# UN SEUL GESTE arme ce que ce depot sait garder de son historique, et c'est
# celui-ci. Il installe les outils de la porte qualite, puis arme les hooks git.
# La porte elle-meme (`make lint`, `make test`) continue d'appeler ses outils
# NUS, comme la CI — cette cible ne s'interpose pas entre elle et eux.
#
# POURQUOI `requirements-dev.txt` ENTIER, ET PAS UN GROUPE BORNE
#
# La version du framework de hooks n'a QU'UN site, et c'est
# `requirements-dev.txt` : c'est le seul fichier que la CI installe et dont
# `make test` a besoin — voir le commentaire en tete du groupe absent dans
# `pyproject.toml`. Installer ce fichier entier plutot qu'un paquet nomme evite
# d'en recopier la version ici, ce qui en ferait deux.
#
# Et ce fichier ne tire pas la pile de production : `mesure` le 3 septembre
# 2026, `uv pip install --dry-run` dans un venv nu, 47 paquets, dont zero
# `torch` et zero `nvidia-*`. C'est ce qui rend la borne inutile — la cible
# precedente passait par `uv sync --only-group hooks` pour eviter la pile CUDA,
# et payait cette borne d'un second site pour la version.
#
# `uv pip install` ET NON `uv sync` : il n'AJOUTE que. `uv sync` reconcilie
# l'environnement avec `uv.lock` et RETIRE tout ce qui n'est pas dans le groupe
# demande — `mesure` le 3 septembre 2026, `uv sync --only-group hooks` dans le
# `.venv` du protocole §2.2 : 183 paquets ramenes a 10, `ruff`, `mypy` et
# `pytest` retires, `rc=0`, et `make lint` ensuite en `rc=2` sur
# « mypy: No such file or directory ». La cible armerait les hooks en desarmant
# la porte qualite, sans un seul rouge.
# Garde : tests/unit/test_installation_des_garde_fous.py,
# `TestLaCibleInstallNeDesarmeRien`.
#
# CE QUE CETTE FORME COUTE, ET C'EST ASSUME. `uv pip install` exige un `.venv`
# deja cree, quand `uv sync` en creait un au besoin : sur un poste nu, cette
# cible echoue en `rc=2` sur « No virtual environment found; run `uv venv` »
# (`mesure` le 3 septembre 2026). L'ordre documente reste celui du §2.2 —
# monter l'environnement, puis armer — et l'echec nomme sa cause et son geste,
# ce qui vaut mieux qu'un environnement monte de travers en silence.
#
# La seconde ligne fait ce que la premiere ne peut pas faire : git n'execute
# jamais ce qui arrive avec un clone. Le script arme les hooks ET verifie qu'ils
# le sont, en sortant en erreur sinon — un garde-fou qui repose sur la memoire
# du suivant n'est pas un garde-fou. La retirer laisse cette cible sortir en 0
# sans rien armer.
# Garde : tests/unit/test_installation_des_garde_fous.py,
# `TestLaCibleInstallArmeVraiment`.
install:
	uv pip install -r requirements-dev.txt
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
