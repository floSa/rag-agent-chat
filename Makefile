.PHONY: install lint format typecheck test audit up down logs image eval eval-controle verifier-les-ancrages mesurer-selection controle-perimetre-selection generer-jeu-disperse mesurer-dispersion traductions-du-jeu-disperse recuperation-profondeurs recuperation-sous-questions recuperation-oracle recuperation-textes recuperation-causes

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

# LE SEUL GESTE QUI CONSTRUISE UNE IMAGE IDENTIFIEE, et c'est celui que le
# redeploiement doit jouer. Sans lui, `docker compose build` construit une image
# ANONYME — licite, fonctionnelle, et qui le declare dans `/health`.
#
# CE QU'IL RELEVE, ET POURQUOI LES DEUX. Le sha seul ne suffit pas : un sha
# releve dans un arbre qui porte des modifications non commitees NOMME UN COMMIT
# QUI NE CONTIENT PAS CE QUI TOURNE. Ce build grave donc AUSSI la proprete de
# l'arbre, et `/health` publie alors `etat: arbre_sale` avec le sha et sa
# reserve, au lieu d'un `identifie` qu'on croirait.
#
# `[ -z "$$S" ]` ET NON LE CODE DE RETOUR DE `git status` : `git status
# --porcelain` rend 0 qu'il ait de la sortie ou non, et un auditeur de ce
# chantier s'est fait annoncer « arbre propre » AU-DESSUS d'un fichier mute. La
# chaine est ce qui porte le fait, jamais le `rc`.
#
# `git -C` ET NON UN `cd` : cette cible s'execute depuis le clone principal, et
# c'est SON depot qui doit etre releve. Le `.` est le repertoire de make, donc
# le contexte de build lui-meme — les deux ne peuvent pas diverger.
#
# CE QU'IL NE FAIT PAS : demarrer quoi que ce soit. Construire et deployer sont
# deux gestes, et les confondre est ce qui rend un retour arriere impossible.
# La marche a suivre complete — etiqueter AVANT de construire, verifier a quoi
# l'etiquette pend, revenir — est dans
# `documentation/identite_du_code_servi.md`.
# Garde : tests/unit/test_identite_du_code.py.
image:
	S="$$(git -C . status --porcelain)"; \
	RAG_AGENT_CODE_SHA="$$(git -C . rev-parse HEAD)" \
	RAG_AGENT_CODE_ARBRE="$$([ -z "$$S" ] && echo propre || echo sale)" \
	RAG_AGENT_CODE_CONSTRUITE_LE="$$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
	docker compose build agent-api

up:
	docker compose up -d

down:
	docker compose down

logs:
	docker compose logs -f

# Les LLM viennent du projet llm-service : c'est lui qu'on interroge, et PAR
# REQUÊTE. Cette recette invoquait le client en ligne de commande de l'ancien
# moteur DANS son conteneur (`docker exec`) ; le serveur qui sert appartient à
# l'équipe voisine et ce depot ne pose rien dedans. `/v1/models` liste ce qu'il
# sert, en lecture, depuis l'hôte — c'est le port PUBLIÉ (8100), le 8000 étant
# celui du réseau interne.
models:
	curl -s http://localhost:8100/v1/models

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
# LE QUATRIEME ETAGE DE LA CHAINE, celui que `sweep_retrieval.py` ne voit pas.
# Il s'arrete au reranking ; ces deux recettes mesurent AUTO_SELECT_TOP_K, donc
# ce qui atteint reellement le prompt. Aucune generation LLM : seules les
# traductions de questions passent par le moteur, et elles sont en cache.
#
# LES TROIS ADRESSES SONT DECOUVERTES, jamais figees. `chromadb` et `graphd`
# n'exposent aucun port sur l'hote — et le 8000 de l'hote est pris par un
# service ETRANGER a ce projet, qui repondrait sans etre le bon.
#
# LLM_NUM_CTX est LU SUR LE CONTENEUR SERVI, pas ecrit ici : il decide du budget
# de fenetre, donc du nombre de sections qui partent, et une valeur figee dans
# cette recette periemerait au prochain reglage sans que rien ne le dise. Le
# defaut du code vaut 8192 quand le conteneur en sert 32768.
#
# TORCH_DEVICE est surchargeable et vaut `cpu` par defaut : le protocole du
# §2.2 monte torch CPU, et le defaut du code (`cuda`) leve sur un tel arbre.
# LE CONTENEUR SERVI, LUI, TOURNE EN `cuda` — l'ecart est declare au §4.67.
TORCH_DEVICE ?= cpu

_ENV_SELECTION = \
	CHROMA_HOST="$$(docker inspect -f '{{.NetworkSettings.Networks.rag_network.IPAddress}}' rag-ingestion-pipeline-chromadb-1)" \
	NEBULA_HOST="$$(docker inspect -f '{{.NetworkSettings.Networks.rag_network.IPAddress}}' graphd)" \
	LLM_NUM_CTX="$$(docker inspect -f '{{range .Config.Env}}{{println .}}{{end}}' rag-agent-api | sed -n 's/^LLM_NUM_CTX=//p')" \
	TORCH_DEVICE="$(TORCH_DEVICE)"

mesurer-selection: verifier-les-ancrages controle-perimetre-selection
	$(_ENV_SELECTION) uv run --no-sync python scripts/mesurer_selection.py \
		--valeurs 1,2,3,4,5,6,8,10,20 \
		--sortie runs/$(shell date +%Y-%m-%d)-selection-auto-select-top-k.json
	$(_ENV_SELECTION) uv run --no-sync python scripts/mesurer_selection.py \
		--golden tests/fixtures/jeu_de_questions_pipeline.yaml \
		--valeurs 1,2,3,4,5,6,8,10,20 \
		--sortie runs/$(shell date +%Y-%m-%d)-selection-controle-30.json

# L'ANTECEDENT DE LA MESURE, au meme titre que `verifier-les-ancrages` l'est
# d'une campagne : un rappel est une INTERSECTION d'identifiants, et deux
# ensembles qui ne se parlent pas rendent un chiffre faux sans lever d'erreur.
controle-perimetre-selection:
	$(_ENV_SELECTION) uv run --no-sync python scripts/controle_perimetre_selection.py

verifier-les-ancrages:
	uv run --no-sync python scripts/verifier_les_ancrages.py \
		--chroma-host "$$(docker inspect -f '{{.NetworkSettings.Networks.rag_network.IPAddress}}' rag-ingestion-pipeline-chromadb-1)" \
		--nebula-host "$$(docker inspect -f '{{.NetworkSettings.Networks.rag_network.IPAddress}}' graphd)" \
		tests/fixtures/golden_qa_generated.yaml \
		tests/fixtures/jeu_de_questions_pipeline.yaml \
		tests/fixtures/jeu_ancrages_disperses.yaml

# LE JEU A ANCRAGES MULTIPLES ET DISPERSES, et ce qui le mesure. Il repond a la
# dette ouverte au §4.67 : les deux jeux anterieurs ne peuvent pas arbitrer
# AUTO_SELECT_TOP_K, le premier parce qu'il est AVEUGLE a la selection, le
# second parce qu'il ne porte que 26 questions.
#
# LA GENERATION ECRIT DANS tests/fixtures/ ET APPELLE LE MODELE : elle n'est PAS
# un antecedent de la mesure, et la rejouer produirait un AUTRE jeu — le jeu
# versionne est l'artefact de reference, comme celui de `generate_golden.py`.
# LE PLAFOND DE RECUPERATION, et pourquoi il est en AMONT de la selection. Le
# §4.76 a mesure que 67 ancrages sur 120 n'atteignent pas le top-10 du reranker
# et a laisse la cause ouverte ; ces recettes la cherchent.
#
# LES PROFONDEURS PASSENT PAR L'ENVIRONNEMENT DU LANCEMENT, jamais par `src/` ni
# par le `.env` : `FETCH_K`, `RETRIEVAL_TOP_K` et `RERANK_TOP_K` sont des alias
# de `settings.py`, et le banc ecrit dans son bilan les valeurs REELLEMENT lues.
#
# L'ORDRE EST UNE DEPENDANCE, PAS UNE COMMODITE. `recuperation-causes` refuse si
# le bilan de production ne retrouve pas, A L'UNITE PRES, les trois chiffres du
# §4.76 : elargir a partir d'une base qui ne se recoupe pas ne mesure rien.
recuperation-profondeurs:
	FETCH_K=50 RETRIEVAL_TOP_K=50 RERANK_TOP_K=10 $(_ENV_SELECTION) \
		uv run --no-sync python scripts/mesurer_recuperation.py \
		--etape profondeurs --sortie runs/$(shell date +%Y-%m-%d)-recuperation-p50.json
	FETCH_K=200 RETRIEVAL_TOP_K=200 RERANK_TOP_K=200 $(_ENV_SELECTION) \
		uv run --no-sync python scripts/mesurer_recuperation.py \
		--etape profondeurs --sortie runs/$(shell date +%Y-%m-%d)-recuperation-p200.json
	FETCH_K=1000 RETRIEVAL_TOP_K=1000 RERANK_TOP_K=1000 $(_ENV_SELECTION) \
		uv run --no-sync python scripts/mesurer_recuperation.py \
		--etape profondeurs --sortie runs/$(shell date +%Y-%m-%d)-recuperation-p1000.json

# LE PRODUCTEUR DU CACHE DE SOUS-QUESTIONS, et il est unique. Il APPELLE LE
# MODELE : ce n'est pas un antecedent de la mesure, et le rejouer produirait
# d'autres sous-questions. Le banc EXIGE le cache sans jamais le fabriquer, meme
# discipline que le cache de traductions.
recuperation-sous-questions:
	$(_ENV_SELECTION) uv run --no-sync python scripts/mesurer_recuperation.py \
		--etape sous-questions \
		--sortie runs/$(shell date +%Y-%m-%d)-recuperation-sous-questions.json

recuperation-oracle:
	FETCH_K=50 RETRIEVAL_TOP_K=50 RERANK_TOP_K=10 $(_ENV_SELECTION) \
		uv run --no-sync python scripts/mesurer_recuperation.py \
		--etape oracle --sortie runs/$(shell date +%Y-%m-%d)-recuperation-oracle.json

recuperation-textes:
	$(_ENV_SELECTION) uv run --no-sync python scripts/mesurer_recuperation.py \
		--etape textes --sortie runs/$(shell date +%Y-%m-%d)-recuperation-textes.json

# LA TABLE DES CAUSES N'OUVRE AUCUN STORE : elle assemble des bilans deja
# versionnes. C'est delibere — elle se rejoue sur les memes fichiers, et deux
# lectures du meme etat des stores ne peuvent pas diverger.
recuperation-causes:
	uv run --no-sync python scripts/mesurer_recuperation.py --etape causes \
		--prod    runs/$(shell date +%Y-%m-%d)-recuperation-p50.json \
		--profond runs/$(shell date +%Y-%m-%d)-recuperation-p200.json \
		          runs/$(shell date +%Y-%m-%d)-recuperation-p1000.json \
		--oracle  runs/$(shell date +%Y-%m-%d)-recuperation-oracle.json \
		--textes  runs/$(shell date +%Y-%m-%d)-recuperation-textes.json \
		--sortie  runs/$(shell date +%Y-%m-%d)-recuperation-causes.json

generer-jeu-disperse:
	$(_ENV_SELECTION) uv run --no-sync python scripts/generer_jeu_disperse.py \
		--count 60 \
		--chroma-host "$$(docker inspect -f '{{.NetworkSettings.Networks.rag_network.IPAddress}}' rag-ingestion-pipeline-chromadb-1)" \
		--chroma-port 8000 \
		--journal runs/$(shell date +%Y-%m-%d)-generation-jeu-disperse.json

# LE PRODUCTEUR DU CACHE DE TRADUCTIONS, et il est unique. Les deux bancs
# EXIGENT le cache sans le fabriquer : une traduction manquante deplacerait le
# rappel translinguistique en silence, et fabriquer sur place ferait de chaque
# banc un second site de traduction.
traductions-du-jeu-disperse:
	$(_ENV_SELECTION) uv run --no-sync python scripts/sweep_retrieval.py \
		--golden tests/fixtures/jeu_ancrages_disperses.yaml --traductions-seulement

# LA MESURE. `verifier-les-ancrages` d'abord, pour la meme raison que `eval` :
# un rappel mesure sur un jeu qui designe le vide rend 0 sans dire pourquoi.
# Les valeurs vont de 1 a RERANK_TOP_K=10 : au-dela, `rerank` ne rend plus rien
# a tronquer (§4.67, point 1).
mesurer-dispersion: verifier-les-ancrages
	$(_ENV_SELECTION) uv run --no-sync python scripts/controle_perimetre_selection.py \
		--jeu tests/fixtures/jeu_ancrages_disperses.yaml
	$(_ENV_SELECTION) uv run --no-sync python scripts/mesurer_dispersion.py \
		--jeu tests/fixtures/jeu_ancrages_disperses.yaml \
		--valeurs 1,2,3,4,5,6,7,8,9,10 \
		--sortie runs/$(shell date +%Y-%m-%d)-dispersion.json
