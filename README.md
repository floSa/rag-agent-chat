# RAG Agent Chat

`rag-agent-chat` est un **agent conversationnel de question-réponse documentaire**.
Il ne possède aucune donnée : il lit, **en lecture seule**, les trois stores que
produit [rag-ingestion-pipeline](https://github.com/floSa/rag-ingestion-pipeline)
— une base vectorielle, un graphe de structure et un stockage d'objets — et il
génère ses réponses avec un modèle servi par le projet
[llm-service](https://github.com/floSa/llm-service). L'orchestration est une
machine à états LangGraph, et l'utilisateur **choisit lui-même les sources**
avant que la réponse ne soit écrite (*human-in-the-loop*).

![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)
![uv](https://img.shields.io/badge/uv-package_manager-DE5FE9?logo=uv&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-Compose-2496ED?logo=docker&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.141-009688?logo=fastapi&logoColor=white)
![LangGraph](https://img.shields.io/badge/LangGraph-1.2-1C3C3C?logo=langchain&logoColor=white)
![Streamlit](https://img.shields.io/badge/Streamlit-1.60-FF4B4B?logo=streamlit&logoColor=white)
![vLLM](https://img.shields.io/badge/vLLM-0.28-FF6B35)

> **Ce document décrit le livrable du 25 septembre 2026.** Pour l'état mesuré du
> système à cette date — ce qui marche, avec les chiffres qui le prouvent, et ce
> qui n'est pas mesuré —, lire [documentation/etat_du_projet.md](documentation/etat_du_projet.md).
> Pour les questions ouvertes et leur ordre, [documentation/prochaines_etapes.md](documentation/prochaines_etapes.md).
>
> **Chaque commande de ce README a été exécutée**, dans un arbre de travail
> détaché partant de `origin/main` = `e1324e4`, le 25 septembre 2026 entre 08:10
> et 08:33 UTC (`date -u`) — **ou bien elle porte la mention « non exécutée
> ici », avec la raison**. Rien n'est recopié d'une documentation antérieure.

---

## 1. Ce que l'agent fait

### 1.1 La chaîne de récupération, en quatre étages

C'est le cœur du système, et c'est **quatre coupes successives**, chacune
gouvernée par un réglage. Les valeurs ci-dessous sont les **défauts du code**,
lus dans [`src/agent/settings.py`](src/agent/settings.py) (`FETCH_K` l. 404,
`RETRIEVAL_TOP_K` l. 394, `RERANK_TOP_K` l. 407, `AUTO_SELECT_TOP_K` l. 415).

| | Étage | Réglage | Défaut | Ce que l'étage fait |
|---|---|---|---|---|
| **1** | Recherche | `FETCH_K` | `50` | Chaque moteur ramène `FETCH_K` candidats. Il y a **jusqu'à quatre classements** : dense et lexical BM25, **pour la question et pour sa traduction** (`retrieve`, [`retriever.py:1387`](src/agent/retriever.py)). |
| **2** | Fusion | `RETRIEVAL_TOP_K` | `50` | Les classements sont fondus par *Reciprocal Rank Fusion* (`RRF_K` = `60`), et la liste fondue est coupée à `RETRIEVAL_TOP_K`. Élargir en amont est ce qui donne à la fusion de quoi travailler : deux listes identiques ne fusionnent rien. |
| **3** | Reranking | `RERANK_TOP_K` | `10` | Un cross-encoder multilingue rescore les candidats contre la question et n'en garde que `RERANK_TOP_K`, **déduplication faite avant la troncature** (`rerank`, [`retriever.py:1625`](src/agent/retriever.py)). C'est l'étage qui coûte le plus cher. |
| **4** | Sélection | `AUTO_SELECT_TOP_K` | `3` | Les sources réellement reconstruites et envoyées au modèle. Dans le flux avec sélection humaine, c'est l'utilisateur qui décide ; sans lui, le défaut s'applique (`graph.py:204`, qui lit `state["max_sources"]` **avant** le réglage). |

**La borne de `max_sources` est celle que la chaîne sert réellement.** Le champ
`max_sources` des requêtes est borné à `RERANK_TOP_K` et non à une valeur écrite
en dur : demander davantage rend un `422` au lieu d'un silence
([`src/api/schemas.py:267-287`](src/api/schemas.py)).

### 1.2 La reconstruction de section par le graphe

C'est ce qui sépare cet agent d'un RAG qui injecte des fragments isolés. Pour
chaque passage retenu, `reconstruct_section`
([`graph_context.py:940`](src/agent/graph_context.py)) remonte les arêtes
`PARENT_OF` du graphe jusqu'au `Document` en notant les titres traversés, puis
redescend chercher :

- une **fenêtre d'éléments** autour du passage (`CONTEXT_WINDOW_BEFORE/AFTER`) ;
- la **fin de la section précédente** et le **début de la suivante**
  (`ADJACENT_SECTION_ELEMENTS`, `0` désactive) ;
- les **illustrations** rencontrées, avec leur légende.

Le modèle reçoit donc une section **située dans son document**, et chaque
élément porte son marqueur `[src:ID]` — ce qui permet de citer sans inventer.

### 1.3 La traduction de la question

`CROSS_LINGUAL_SEARCH` (défaut `true`) fait traduire la question par le modèle
avant la recherche, et la traduction entre dans la fusion **à côté** de la
question d'origine, au poids `TRANSLATION_WEIGHT` (défaut `1.0`,
[`settings.py:423` et `:440`](src/agent/settings.py)). La traduction est
refusée si elle est vide ou si elle dépasse trois fois la longueur de la
question (`_MAX_TRANSLATION_RATIO`, [`llm.py:935-987`](src/agent/llm.py)) :
une chaîne vide partirait en requête de recherche.

`QUERY_REWRITE` (défaut `true`) est un geste distinct et antérieur : il rend une
question de suivi autonome avant qu'elle ne soit encodée.

### 1.4 Le moteur : vLLM, et un seul

Ce projet **n'embarque aucun serveur d'inférence**. Il parle à `vllm-central`,
servi par [llm-service](https://github.com/floSa/llm-service) sur le réseau
Docker `llm-net`. **Un seul moteur est supporté depuis le lot 28** : le réglage
qui en choisissait un parmi deux a été retiré — ce n'est pas le nom qui a
disparu, c'est le **support** ([`src/agent/flux_llm.py:21`](src/agent/flux_llm.py),
[`src/agent/dialecte_llm.py:28`](src/agent/dialecte_llm.py)). Le retour arrière
ne passe donc plus par un réglage mais par l'image étiquetée d'avant la bascule :
[identite_du_code_servi.md](documentation/identite_du_code_servi.md).

`/health` distingue le modèle **demandé** (un réglage) du moteur **réellement
servi** (un fait), et les deux ont divergé par le passé —
[moteur_llm.md](documentation/moteur_llm.md). `mesuré` le 25 septembre 2026 à
08:10 UTC, `curl -s http://localhost:8011/health` : serveur `vllm`, version
`0.28.0`, fenêtre servie `32768`.

### 1.5 La mémoire est portée par le client

**Le serveur ne garde pas la conversation pour l'appelant.** L'historique voyage
dans la requête, champ `chat_history`, sur les trois routes qui en acceptent un
([`schemas.py:104, 196, 260`](src/api/schemas.py)). Deux bornes le tiennent :
`MAX_HISTORY_PAYLOAD = 50` messages acceptés par requête, et
`MAX_HISTORY_MESSAGES = 6` derniers retenus pour le prompt ; au-delà,
`HISTORY_WINDOW_SHARE` (défaut `0.25`) plafonne la part de la fenêtre de prompt
que l'historique peut occuper, le reste allant aux sources. Un client ne peut
pas glisser un message `system` : le schéma le refuse.

Ce que le serveur garde, c'est autre chose : l'**état d'une session LangGraph
suspendue** entre `/chat/start` et `/chat/resume`, dans
`CHECKPOINT_DB_PATH`. Cet état est purgé par âge (`SESSION_TTL_SECONDS`) et par
nombre (`MAX_LIVE_SESSIONS`), et la purge est **durable** : elle atteint une
session antérieure à un redémarrage ([`sessions.py`](src/agent/sessions.py)).

### 1.6 Le stockage d'objets, et le proxy `/media`

Les illustrations et les tableaux découpés vivent dans un **stockage d'objets
compatible S3**, que l'agent lit sans jamais y écrire. Il est configuré par cinq
variables — `MINIO_ENDPOINT`, `MINIO_BUCKET`, `MINIO_SECURE`, `MINIO_ROOT_USER`
et `MINIO_ROOT_PASSWORD` (`.env.example`, [`settings.py:25-30`](src/agent/settings.py)).
**Aucune valeur n'est reproduite ici : ce dépôt est public.**

Le navigateur ne voit pas le réseau Docker interne. L'agent expose donc
`GET /media/{object_name}`, qui relaie l'objet
([`main.py:2114`](src/api/main.py)). Quand `RESTRICT_MEDIA_TO_GRAPH` vaut `true`
(défaut), le proxy ne sert que les objets que le **graphe** désigne.

> **Le produit qui sert ce stockage bascule aujourd'hui, 25 septembre 2026**, à
> l'initiative du pipeline voisin, et le corpus est entièrement réingéré — il
> n'y a rien à migrer de notre côté. Le principe retenu des deux côtés est
> écrit : **on ne nomme pas le produit dans le contrat**. Le champ externe
> `minio_url` deviendra `media_url`, et un champ `object_key` portera la clé
> nue. Inventaire complet, avec ce qui casserait en silence si le renommage
> arrivait sans prévenir : [axes_amelioration.md](documentation/axes_amelioration.md)
> §4.62. Le code de ce dépôt lit **encore** `minio_url` (`git grep -n minio_url -- src`,
> `mesuré` le 25 septembre 2026 à 08:32 UTC : 7 fichiers, 28 lignes).

---

## 2. Installer et lancer

### 2.1 Prérequis

Deux piles doivent tourner **avant** celle-ci :

- **rag-ingestion-pipeline** — il crée le réseau Docker `rag_network`, héberge
  la base vectorielle, le graphe et le stockage d'objets, et doit avoir ingéré
  au moins un document ;
- **llm-service** — il monte `vllm-central` sur le réseau `llm-net`.

### 2.2 Le `.env`

```bash
cp .env.example .env
```

> **Non exécutée ici.** Le `.env` vit dans le clone principal et **jamais dans
> un arbre de travail** : `docker-compose.yml` monte `./prompts`, et un `up`
> lancé depuis un arbre l'ancrerait au mauvais endroit. Ce lot travaille dans un
> arbre détaché et n'a lu aucun `.env`.

`.env.example` est versionné et complet. Les valeurs de secret — dont
`MINIO_ROOT_PASSWORD`, qui doit être **la même** que celle du projet
d'ingestion — ne sont écrites nulle part dans ce dépôt, qui est public.

### 2.3 Démarrer la pile

```bash
docker compose up -d --build
```

> **Non exécutée ici.** Le mandat de ce lot interdit `docker compose` : le
> service du port 8011 est partagé, et le pipeline voisin réingérait le corpus
> ce jour-là. La cible équivalente du `Makefile` est `make up` (= `docker
> compose up -d`), et `make image` construit l'image **en y inscrivant le sha du
> code**, ce qui est la seule façon pour `/health` de dire quel code tourne.

### 2.4 Les interfaces

| | Adresse par défaut | |
|---|---|---|
| Interface de chat (Streamlit) | `http://<hôte>:8506` | Question, sélection des sources, réponse |
| API (FastAPI) | `http://<hôte>:8011` | `…/docs` pour le Swagger |
| Sonde de santé, sans secret | `http://<hôte>:8011/health` | |

**Ce projet est un déploiement local : il n'est pas hébergé et n'a pas d'URL
publique.** Avant d'ouvrir l'accès au-delà d'un réseau de confiance, poser
`API_KEY` dans le `.env` : laissée vide, **toutes** les routes répondent sans
authentification, `POST /reindex` compris. Seule `/health` reste volontairement
ouverte, pour qu'une sonde n'ait pas besoin d'un secret —
[SECURITY.md](documentation/SECURITY.md).

### 2.5 Poser une question

1. Ouvrir l'interface et saisir la question.
2. L'agent affiche les sources trouvées, **groupées par document**, avec extrait
   et score : décocher celles qui ne sont pas pertinentes.
3. Valider : l'agent reconstruit le contexte par le graphe et écrit la réponse
   en streaming, avec ses citations `[src:ID]` et ses images `[img:ID]`.

---

## 3. L'API

**Onze routes, et ce sont exactement les onze que le service publie.** Relevé
`mesuré` le 25 septembre 2026 à 08:10 UTC, en deux lectures indépendantes qui
concordent : `curl -s http://localhost:8011/openapi.json` (HTTP 200) et
`grep -nE '@app\.(get|post)' src/api/main.py`.

| Méthode | Route | Rôle |
|---|---|---|
| `GET` | `/health` | Le seul point d'entrée **sans authentification**. Publie l'état des dépendances, le modèle demandé **et** — sous `moteur_llm` — le moteur réellement servi, ainsi que — sous `code_servi` — le sha du code que l'image contient, ou `anonyme` si elle n'a pas été construite par `make image`. |
| `POST` | `/search` | Recherche brute dans la base vectorielle, **sans reranking**. |
| `POST` | `/sources` | Récupération + reranking + groupement par document. C'est ce que l'interface affiche pour la sélection. |
| `GET` | `/context/{element_id}` | La section reconstruite autour d'un élément, telle que le modèle la recevrait. |
| `POST` | `/answer` | Question → réponse, **sans sélection humaine**. Rend aussi les sections reconstruites *en distinguant celles qui sont parties au modèle de celles que le budget a écartées*, la partition du temps par étage et les décomptes de jetons du serveur : c'est le point d'entrée évaluable. |
| `POST` | `/chat/start` | Démarre le flux LangGraph et **suspend** en attente de la sélection des sources. |
| `POST` | `/chat/resume` | Reprend après la sélection ; réponse en SSE. |
| `POST` | `/chat/simple` | Génération directe à partir de sources déjà choisies, sans boucle agentique. Refuse (`400`) si aucune source n'est sélectionnée. |
| `POST` | `/feedback` | Appréciation binaire d'une réponse et commentaire libre, rattachés au `thread_id`. |
| `POST` | `/reindex` | Reconstruit l'index lexical BM25 sur le corpus courant. **À appeler par le pipeline en fin d'ingestion** : sans lui, un document ingéré après le démarrage de l'agent reste invisible en recherche lexicale ([stores.md](documentation/stores.md)). |
| `GET` | `/media/{object_name}` | Proxy du stockage d'objets — cf. §1.6. |

Les dix routes autres que `/health` portent `Depends(require_api_key)`, qui ne
mord que si `API_KEY` est posée.

---

## 4. La porte qualité

**La porte est en deux gestes, et c'est ce que la CI appelle.** Il n'y a pas de
cible `make all` sur ce dépôt.

```bash
make lint && make test
```

- `make lint` dépend de `typecheck` : il lance `mypy src/` **puis**
  `ruff check src/ tests/ scripts/`. Le rattachement est délibéré — modifier le
  workflow de CI exige un jeton que le jeton de push n'a pas, donc un
  `make typecheck` détaché ne tournerait jamais en intégration.
- `make test` lance **`pytest tests/unit/`**, et rien d'autre. Le périmètre est
  à connaître : `tests/` complet en rend davantage, les tests d'intégration
  exigeant la pile démarrée (`make test-integration`).

**`mesuré` le 25 septembre 2026, trois fois entre 08:30 et 08:37 UTC**, arbre
détaché sur `e1324e4`, les cinq fichiers de ce lot **suivis par git** — sans quoi
les gardes qui lisent `git ls-files` ne les verraient pas. Les trois relevés sont
identiques. `rc`
relevés dans des variables et ceux de **`make`** (qui rend `2` là où `pytest`
rend `1`) :

| | commande | rc | rendu |
|---|---|---|---|
| lint | `make lint` (`rc_lint`) | **0** | `mypy` : 22 fichiers, aucun problème ; `ruff` : tout passe |
| tests | `make test` (`rc_test`) | **0** | **1263 passés** en 124 s |

Le compte **1263** est celui que [tests.md](documentation/tests.md) annonce
(61 fichiers, relevé du 25 septembre 2026 à 07:47 UTC), et un garde du dépôt le
tient.

**L'environnement se monte, il ne se suppose pas.** `ruff`, `mypy` et `pytest`
ne sont pas au `PATH` de ce poste : un `make lint` depuis un arbre neuf échoue
sur `ruff: command not found`, et non sur une faute de code. Sur un arbre neuf :

```bash
uv venv --python 3.12 && uv pip install torch --index-url https://download.pytorch.org/whl/cpu && uv pip install -r requirements.txt -r requirements-dev.txt
```

*Exécutée le 25 septembre 2026 à 08:10-08:11 UTC, `rc=0`.* **Ne jamais mesurer la
porte dans le `.venv` qu'un autre lot a laissé derrière lui** : un `.venv` de
lot porte ce que ce lot y a installé, c'est-à-dire précisément ce que la CI
n'aura pas. Le protocole complet est au §2.2 de
[pilotage_du_chantier.md](documentation/pilotage_du_chantier.md).

### Les autres cibles

| Cible | Ce qu'elle fait | Exécutée ici ? |
|---|---|---|
| `make lint` | `mypy src/` puis `ruff check` | **oui**, `rc=0` |
| `make test` | `pytest tests/unit/` | **oui**, `rc=0`, 1263 passés en 124 s |
| `make typecheck` | `mypy src/` | **oui, comme dépendance de `make lint`** ; pas appelée séparément |
| `make format` | `ruff format` + `ruff check --fix` | non — elle **écrit** dans l'arbre, et ce lot ne touche pas au code |
| `make test-integration` | `pytest tests/integration/` contre l'API | non — exige la pile démarrée et un `.env` ; hors du mandat de ce lot |
| `make verifier-les-ancrages` | prouve que les jeux désignent des passages qui existent | non — exige les stores et un `.env`, et le mandat de ce lot limite les lectures du service à `/health` et `/openapi.json` |
| `make eval` / `make eval-controle` | campagnes de rappel ; **dépendent** de `verifier-les-ancrages` | non, même raison |
| `make health` / `make models` | `curl` sur `/health` et sur le catalogue du serveur d'inférence | non ; `/health` a été lu directement par `curl`, cf. §3 |
| `make image` / `make up` / `make down` / `make logs` | construction et cycle de vie des conteneurs | non — `docker compose` est hors du mandat de ce lot |
| `make audit` | `pip-audit -r requirements.txt` | non — sortie réseau, hors du mandat |
| `make install` | installe les dépendances de dev et arme les garde-fous git | non — **jamais depuis un arbre de travail** |

---

## 5. La carte de `documentation/`

| Fichier | À quoi il sert |
|---|---|
| [etat_du_projet.md](documentation/etat_du_projet.md) | **L'état du livrable au 25 septembre 2026** : ce qui marche avec les mesures qui le prouvent, ce qui n'est pas mesuré, et les limites connues |
| [prochaines_etapes.md](documentation/prochaines_etapes.md) | Les questions ouvertes, **ordonnées par le coût de l'échec**, avec ce qu'il faudrait mesurer pour trancher chacune |
| [architecture.md](documentation/architecture.md) | Le système tel qu'il est : services, machine à états, décisions |
| [agent_architecture.md](documentation/agent_architecture.md) | Vue détaillée de l'agent : nœuds, données, prompts, table des réglages |
| [stores.md](documentation/stores.md) | Le contrat avec l'ingestion, vu du consommateur |
| [pour_le_pipeline_ingestion.md](documentation/pour_le_pipeline_ingestion.md) | Écrit **à l'intention du pipeline** : ce que l'agent attend, et ce qui casse en silence sinon |
| [llm.md](documentation/llm.md) | Le service d'inférence central, et le budget de la fenêtre de contexte |
| [moteur_llm.md](documentation/moteur_llm.md) | Quel moteur a généré une campagne, et pourquoi le nom du modèle demandé ne suffit pas. **Porte la migration du `.env` du lot 28** |
| [identite_du_code_servi.md](documentation/identite_du_code_servi.md) | Quel code tourne réellement, et comment revenir en arrière par l'image étiquetée |
| [gpu_cuda.md](documentation/gpu_cuda.md) | Installer et activer CUDA : les trois conditions, ce que ça coûte, le retour arrière |
| [rag_evaluation_strategy.md](documentation/rag_evaluation_strategy.md) | Comment le système est mesuré, et ce que la mesure a tranché |
| [tests.md](documentation/tests.md) | Les trois niveaux de test, fichier par fichier, et ce que rien ne couvre |
| [capture_usage.md](documentation/capture_usage.md) | Ce que le service enregistre de son propre usage, et les requêtes qui l'exploitent |
| [SECURITY.md](documentation/SECURITY.md) | Surface exposée, défenses, et ce qui n'est **pas** protégé |
| [axes_amelioration.md](documentation/axes_amelioration.md) | **Le registre.** Site canonique de chaque mesure et de chaque correction, par section numérotée |
| [pilotage_du_chantier.md](documentation/pilotage_du_chantier.md) | **Le journal.** Le protocole de travail, le contrat avec le pipeline, et la ligne de chaque conversation livrée |
| [llm_integration_plan.md](documentation/llm_integration_plan.md) | Plan de conception initial — **historique**, l'implémentation en diverge |
| [audits/](documentation/audits/) | Les rapports d'audit, datés et signés. **Ils ne se réécrivent pas** |
| [campagnes/](documentation/campagnes/) | Les récits de campagne datés, avec protocole et chiffres |
| [references/](documentation/references/) | Les empreintes relevées avant une bascule, pour pouvoir comparer après |

---

## 6. Le contrat avec `rag-ingestion-pipeline`

| Store | Ce que l'agent en fait |
|---|---|
| **Base vectorielle** (ChromaDB, collection `rag_documents`) | Recherche dense sur les chunks. L'agent **refuse de chercher** — `503`, `/health` en `degraded` — si l'estampille `embedding_model` de la collection ne correspond pas à `EMBEDDING_MODEL_NAME`, ou si elle est absente. |
| **Graphe** (NebulaGraph, space `rag_space`) | Remontée `PARENT_OF` → fil des titres, puis reconstruction de section (§1.2). |
| **Stockage d'objets** (compatible S3) | Illustrations et tableaux découpés, servis au navigateur par le proxy `/media` (§1.6). |

L'agent est **en lecture seule** sur les trois. Le contrat — métadonnées,
schéma du graphe, format des identifiants, et ce qui casse quand il n'est pas
tenu — est dans [stores.md](documentation/stores.md) et, écrit depuis ce dépôt à
l'intention de l'autre, dans
[pour_le_pipeline_ingestion.md](documentation/pour_le_pipeline_ingestion.md).

---

## 7. Structure du dépôt

```text
rag-agent-chat/
├── documentation/              # Cf. la carte du §5
├── prompts/                    # Prompts versionnés (system.txt, templates Jinja2)
├── runs/                       # Bilans de campagne versionnés (JSON)
├── scripts/                    # Générateurs de jeux, bancs de mesure, garde-fous
├── src/
│   ├── agent/
│   │   ├── graph.py            # Machine à états LangGraph
│   │   ├── state.py            # AgentState
│   │   ├── retriever.py        # Recherche dense + lexicale, fusion RRF, reranking
│   │   ├── lexical.py          # Index BM25
│   │   ├── graph_context.py    # Reconstruction de section par le graphe
│   │   ├── minio_client.py     # Accès au stockage d'objets
│   │   ├── llm.py              # Client du modèle : génération, traduction, réécriture
│   │   ├── flux_llm.py         # Lecture du flux de génération
│   │   ├── dialecte_llm.py     # Forme des requêtes au serveur d'inférence
│   │   ├── repli_outil.py      # Repli quand l'appel d'outil natif n'est pas tenu
│   │   ├── sessions.py         # Registre durable des sessions, et purge
│   │   ├── usage.py            # Capture d'usage
│   │   ├── chronometrie.py     # Partition du temps par étage
│   │   └── settings.py         # Configuration pydantic-settings
│   ├── api/
│   │   ├── main.py             # Les onze routes
│   │   ├── schemas.py          # Contrats d'entrée et de sortie
│   │   └── identite_du_code.py # Le sha inscrit dans l'image
│   └── frontend/app.py         # Interface Streamlit
├── tests/{unit,integration,fixtures}/
├── docker-compose.yml          # agent-api + frontend
├── Dockerfile.agent
└── Dockerfile.frontend
```

---

## 8. Licences et composants

| Composant | Rôle | Licence |
|---|---|---|
| vLLM | Serveur d'inférence (externe au dépôt) | Apache-2.0 |
| FastAPI / Uvicorn | API / serveur ASGI | MIT / BSD-3-Clause |
| Streamlit | Interface | Apache-2.0 |
| LangGraph / langchain-core | Machine à états | MIT |
| ChromaDB | Base vectorielle | Apache-2.0 |
| sentence-transformers | Embeddings et reranking | Apache-2.0 |
| Nebula Graph (nebula3-python) | Graphe | Apache-2.0 |
| SDK du stockage d'objets (`minio`) | Client S3 | Apache-2.0 |
| Jinja2 | Templating | BSD-3-Clause |
| Pydantic | Configuration et typage | MIT |
| **Ce projet** | Code applicatif | MIT — Copyright (c) 2026 floSa `<à confirmer : aucun fichier LICENSE présent>` |

> La licence du **serveur** de stockage d'objets n'est plus listée ici : le
> produit bascule le 25 septembre 2026 et le dépôt ne le nomme pas dans son
> contrat (§1.6). La ligne ci-dessus est celle du **SDK client**, qui est une
> dépendance de ce dépôt — `minio==7.2.20`, Apache-2.0.
