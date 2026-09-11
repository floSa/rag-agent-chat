.PHONY: install lint format typecheck test audit up down logs eval eval-controle verifier-les-ancrages

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

# La version de mypy est epinglee dans requirements-dev.txt : l'invoquer par
# le drapeau `--with mypy` d'uv en tirerait une plus recente, plus permissive
# sur certains points, et la CI trouverait des erreurs invisibles en local.
# La periphrase est deliberee : le garde de forme de
# tests/unit/test_coherence_depot.py refuse, dans un fichier de code, toute
# invocation nue de l executeur d'uv — y compris citee en commentaire.
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

# DEUX INSTRUMENTS, DEUX CIBLES, ET AUCUN NE REMPLACE L'AUTRE. La decision est
# celle du §4.3 de `documentation/axes_amelioration.md`, prise le 3 septembre
# 2026 : le jeu REGENERE porte le volume de reglage, les 30 questions du
# pipeline portent le controle independant du generateur. Le premier ne sait pas
# se contredire — la question est ecrite POUR le passage qu'elle designe — le
# second est trop peu nombreux pour arbitrer un reglage.
#
# Campagne d'evaluation : rappel du retrieval, precision du contexte, completude
# des citations, abstention et latence par etage. Deterministe, sans juge LLM.
#
# La comparaison est APPARIEE question par question, et elle REFUSE de tourner
# (code de sortie 2) dans trois cas : les deux jeux de questions divergent, la
# reference ne porte pas d'empreinte d'ancrages, ou la cible n'existe pas.
#
# CE QUE CE LOT A RETIRE, ET POURQUOI. La cible etait `runs/final.json`, commite
# le 3 aout 2026. Elle est l'antecedent d'un corpus REMPLACE le 2 septembre
# 2026, et le piege etait arme : `generate_golden.py` numerote ses questions
# dans l'ordre de generation, donc le jeu regenere porte EXACTEMENT les memes
# 138 identifiants. Le refus sur desaccord de jeu ne voyait rien, et cette
# recette aurait imprime des fleches sur 138 paires dont les deux moities
# mesurent deux corpus. C'est pourquoi une campagne inscrit desormais
# l'empreinte de ses ancrages, et pourquoi les huit campagnes anterieures de
# `runs/` sont retirees comme cibles — elles n'en portent pas.
# Gardes : tests/unit/test_comparaison_appariee.py,
# `test_la_cible_retiree_de_make_eval_est_desormais_refusee` et
# `test_l_empreinte_distingue_deux_corpus_a_numerotation_identique`.
#
# L'ORDRE N'EST PAS INDIFFERENT : `verifier-les-ancrages` d'abord. Un rappel
# mesure sur un jeu qui designe le vide rend 0 sans dire si la recherche est
# cassee ou si le jeu est perime, et c'est la panne exacte que ce lot repare.
# La cible `eval` en depend donc, et un desaccord d'ancrage arrete la campagne
# avant qu'elle ne coute une demi-heure de generation.
eval: verifier-les-ancrages
	uv run --no-sync python scripts/evaluate.py --golden tests/fixtures/golden_qa_generated.yaml \
		--out runs/$(shell date +%Y%m%d-%H%M)-reglage.json \
		--compare runs/2026-09-08-reference.json

# Le CONTROLE : les 30 questions du pipeline, ecrites a la main apres
# l'ingestion. Sa reserve n'est pas negociable et elle voyage avec le fichier —
# controle de bon fonctionnement, JAMAIS decision d'architecture. Un ecart de
# deux points sur trente questions est du bruit.
eval-controle: verifier-les-ancrages
	uv run --no-sync python scripts/evaluate.py --golden tests/fixtures/jeu_de_questions_pipeline.yaml \
		--out runs/$(shell date +%Y%m%d-%H%M)-controle.json \
		--compare runs/2026-09-08-controle-30.json

# L'ANTECEDENT DE TOUTE CAMPAGNE. Sort en 1 au premier ancrage qui n'existe pas
# dans les stores, en 2 si un store est injoignable — un jeu sain derriere un
# store eteint ne doit pas passer pour un jeu perime.
#
# `chromadb` et `graphd` n'exposent aucun port sur l'hote : les adresses sont
# DECOUVERTES ici plutot que figees, une adresse ecrite en dur perimant a la
# premiere reconstruction de la pile.
verifier-les-ancrages:
	uv run --no-sync python scripts/verifier_les_ancrages.py \
		--chroma-host "$$(docker inspect -f '{{.NetworkSettings.Networks.rag_network.IPAddress}}' rag-ingestion-pipeline-chromadb-1)" \
		--nebula-host "$$(docker inspect -f '{{.NetworkSettings.Networks.rag_network.IPAddress}}' graphd)" \
		tests/fixtures/golden_qa_generated.yaml \
		tests/fixtures/jeu_de_questions_pipeline.yaml
