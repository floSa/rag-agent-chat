# Architecture de l'agent RAG

## Vue d'ensemble

`rag-agent-chat` est une application de question-réponse documentaire basée sur un agent LangGraph avec interruption humaine (*human-in-the-loop*). Il consomme en lecture seule les données produites par `rag-ingestion-pipeline` (ChromaDB, NebulaGraph, MinIO) et expose une API FastAPI ainsi qu'une interface Streamlit.

---

## Vue contexte

```
┌─────────────────────────────────────────────────────────────────┐
│                   rag-ingestion-pipeline                        │
│   Documents ──▶ Docling ──▶ ChromaDB │ NebulaGraph │ MinIO     │
└────────────────────────────┬────────────────────────────────────┘
                             │ réseau Docker : rag-ingestion-pipeline_rag_network
┌────────────────────────────▼────────────────────────────────────┐
│                       rag-agent-chat                            │
│                                                                 │
│  Streamlit (8501) ◀──▶ FastAPI/LangGraph (8001) ◀──▶ Ollama   │
│                                │                                │
│              ChromaDB │ NebulaGraph │ MinIO (lecture seule)    │
└─────────────────────────────────────────────────────────────────┘
```

**Interactions externes** :
- ChromaDB `:8080` — recherche vectorielle (lecture)
- NebulaGraph `:9669` — reconstruction contextuelle (lecture)
- MinIO `:9000` — URLs présignées pour images/tableaux (lecture)
- Ollama `:11434` — inférence LLM (appels locaux)

---

## Vue logique : flux de l'agent

### Graphe LangGraph

```
          ┌──────────┐
 START ──▶│ rewrite  │  Question de suivi → question autonome
          └────┬─────┘     (aucun appel LLM sans historique)
               │
          ┌────▼─────┐
          │ retrieve │  Dense ChromaDB + BM25 lexical, fusionnés par RRF
          └────┬─────┘
               │
          ┌────▼─────┐
          │  rerank  │  Cross-encoder multilingue, dédup par element_id
          └────┬─────┘     AVANT la troncature au top-K
               │
          ┌────▼──────────────────┐
          │ await_source_selection│  ← INTERRUPT (flux interactif seulement)
          └────┬──────────────────┘    /answer ne passe pas par là
               │  selected_element_ids injectés via /chat/resume
          ┌────▼──────────────────┐
          │ reconstruct_context   │  NebulaGraph : fil des titres, fenêtre
          └────┬──────────────────┘  d'éléments, sections voisines, légendes,
               │                     texte intégral relu dans l'index
          ┌────▼─────┐
          │ generate │  Ollama, num_ctx explicite, sources bornées, streaming
          └────┬─────┘
               │
          ┌────▼───────────┐
          │  postprocess   │  Citations [src:ID] → document/ouvrage/page/section
          └────┬───────────┘  Images [img:ID] → proxy /media
               │
        ┌──────▼──────┐
        │ needs_more? │  Appel d'outil natif search_vectors, ou repli regex
        └──┬──────────┘
           │ True (≤ 3x)      │ False
           └──▶ retrieve      └──▶ END
```

### Deux compilations du même graphe

| Compilation    | Interruption                                 | Checkpointer | Consommé par |
|----------------|----------------------------------------------|--------------|--------------|
| `agent_graph`  | `interrupt_before=["await_source_selection"]` | SQLite       | `/chat/start` + `/chat/resume` |
| `answer_graph` | aucune                                       | aucun        | `/answer` |

Le flux interactif attend un humain : il n'est pas rejouable en batch. Sans
`answer_graph`, aucune campagne d'évaluation ne pourrait mesurer le système.

**Protocole du flux interactif** :

1. `POST /chat/start` — `ainvoke(initial_state, config)` s'arrête avant
   `await_source_selection`, retourne `thread_id` et les groupes de sources.
2. `POST /chat/resume` — `aupdate_state(config, {selected_element_ids})` puis
   `ainvoke(None, config)` reprend au point d'interruption.

Le checkpointer écrit dans un fichier SQLite monté sur le volume
`rag_agent_state` : une session en attente de sélection survit au redémarrage
de `agent-api`, et plusieurs workers uvicorn partagent leurs threads. Repli en
mémoire si le fichier est inaccessible. Les sessions sont purgées par âge
(`SESSION_TTL_SECONDS`) et par nombre (`MAX_LIVE_SESSIONS`) : sans purge, la
persistance ne ferait que déplacer la fuite sur le disque.

Le registre de cette purge vit **dans la base du checkpointer** (table
`sessions_agent`), et non en mémoire : un registre de processus n'atteint que
les sessions qu'il a lui-même créées, et tout ce qui précédait le dernier
redémarrage restait sur le disque indéfiniment. Aucune purge n'a lieu au
démarrage — ce serait détruire la raison d'être du fichier — mais les sessions
qu'il porte sans registre y sont adoptées, donc redeviennent purgeables. Détail
dans [architecture.md](architecture.md#purge-durable-des-sessions), état publié
par `GET /health` sous `sessions`.

---

## Vue applicative : composants

### `src/agent/`

| Module              | Responsabilité                                                  |
|---------------------|-----------------------------------------------------------------|
| `graph.py`          | Nœuds, arêtes, conditions, compilation du graphe, résolution des citations |
| `graph_context.py`  | Reconstruction via NebulaGraph : fil des titres, fenêtre d'éléments, sections voisines, légendes |
| `llm.py`            | Client Ollama (API native), réécriture et traduction de requête, budget de contexte, outil `search_vectors` |
| `retriever.py`      | Recherche dense + lexicale, reranking, déduplication, texte intégral |
| `lexical.py`        | Index BM25 en mémoire et fusion Reciprocal Rank Fusion          |
| `minio_client.py`   | Lecture des objets MinIO servis par le proxy `/media`           |
| `state.py`          | `AgentState` — TypedDict LangGraph (question, chunks, contextes, réponse, chronométrage) |
| `settings.py`       | Configuration via `pydantic-settings` (lecture `.env`)          |
| `usage.py`          | Capture d'usage : questions posées, sources proposées et décochées, réponses, appréciations ([capture_usage.md](capture_usage.md)) |

### `src/api/`

| Module       | Responsabilité                               |
|--------------|----------------------------------------------|
| `main.py`    | Endpoints FastAPI (11 routes), middleware CORS, branchement de la capture d'usage |
| `schemas.py` | Modèles Pydantic v2 (requêtes et réponses)   |

### `src/frontend/`

| Module  | Responsabilité                                                           |
|---------|--------------------------------------------------------------------------|
| `app.py`| Interface Streamlit 3 phases : saisie question → sélection sources → affichage réponse |

---

## Vue données

### Contrat de lecture ChromaDB

- Collection : `rag_documents`
- Embedding : `paraphrase-multilingual-MiniLM-L12-v2` (384 dimensions) — **doit être identique à l'ingestion**. Ce document a longtemps annoncé `all-MiniLM-L6-v2`, un modèle anglais : c'est faux depuis la réingestion multilingue, et c'est la plus coûteuse des fausses valeurs possibles — un embedder qui ne correspond pas à celui de l'ingestion rend des passages au hasard, sans exception, sans log et sans sonde. La valeur qui s'exécute est dans `settings.py`
- Métadonnées disponibles par chunk : `element_id`, `graph_node_id`, `filename`, `collection`, `source_path`, `section_title`, `language`, `depth`, `page_no`, `minio_url`, `chunk_index`, `chunk_count`. Ce que l'agent fait de chacune est dans [stores.md](stores.md), qui fait référence — `source_path` est l'**identité** du document, et non `filename`
- Paramètres de retrieval : `RETRIEVAL_TOP_K=50` (candidats après fusion) → `RERANK_TOP_K=10` (après reranking). La table des paramètres de ce document disait déjà 50 ; cette ligne était restée à 20, la valeur d'avant l'élargissement du vivier
- **Aucun filtre de pertinence.** `rerank` rend les `RERANK_TOP_K` mieux classées quel que soit leur score : le système n'a pas de seuil, et une question hors corpus reçoit dix sources comme les autres. Ce document a décrit un `RERANK_MIN_SCORE=0.0` qui n'a jamais existé dans `settings.py` — l'affirmation est retirée, le manque est ouvert dans [axes_amelioration.md](axes_amelioration.md) avec les deux autres manifestations du même problème (badge de pertinence purement relatif, `min_length=1` sur la sélection)
- Situer le passage dans l'interface de sélection ne coûte **aucun** appel au graphe : le titre de section est lu dans la métadonnée `section_title` de ChromaDB, portée par `ChunkResult` et affichée telle quelle. Ce document décrivait un enrichissement par NebulaGraph via `get_section_text`, produisant un champ `section_header_text` : ces deux symboles n'existent nulle part dans `src/`. Le graphe n'est traversé qu'après la sélection, par `reconstruct_section`

### Contrat de lecture NebulaGraph

- Space : `rag_space`
- Tags lus : `Document`, `SectionHeader`, `Paragraph`, `Table`, `Picture`, `Code`, `Formula`, `Caption`, `ListItem`, `Footnote`, `PageHeader`, `PageFooter`
- Propriétés lues : `label`, `text`, `minio_url`, `page_no`
- Edge utilisé : `PARENT_OF(sequence)` — traversal ascendant (`REVERSELY`) et descendant
- Requête propriétés : `FETCH PROP ON * "vid"` (1 requête pour tous les tags) + fallback `FETCH PROP ON Document` pour les nœuds racines
- Requête ascendante : `GO FROM v OVER PARENT_OF REVERSELY YIELD src(edge) AS parent_id`
- Requête descendante : `GO FROM section_id OVER PARENT_OF YIELD dst(edge) AS child_id ... | ORDER BY seq`
- Fenêtrage du contexte : `_window_around` limite les éléments retournés à `_MAX_CONTEXT_ELEMENTS=12`, centrés sur l'`element_id` ciblé. Pour les nœuds Document racine (pas de SectionHeader intermédiaire), les éléments Picture/Table/SectionHeader sont en plus filtrés avant fenêtrage.

**Note sur `REVERSELY`** : `YIELD src(edge)` retourne l'origine de l'arête originale (le parent), pas la destination. Utiliser `dst(edge)` retournerait le nœud de départ lui-même.

### Contrat de lecture MinIO

- Bucket : `documents`
- Accès : URLs présignées via `minio_client.get_presigned_url(minio_url)` (TTL 1 heure par défaut)
- Les `minio_url` sont stockées dans NebulaGraph comme chemin relatif : `bucket/path/to/image.png`

### État de l'agent (`AgentState`)

Recopié de `src/agent/state.py`, qui fait foi. L'extrait avait divergé : il
omettait la question réécrite, sa traduction, les deux bornes de sélection et le
nombre de sources écartées.

```python
class AgentState(TypedDict):
    question: str
    chat_history: list[Message]
    search_query: str | None            # question rendue autonome
    search_translation: str | None      # la même dans l'autre langue du corpus
    retrieved_chunks: list[ChunkResult]
    reranked_chunks: list[ChunkResult]
    selected_element_ids: list[str]     # sélection humaine, vide pour /answer
    max_sources: int | None             # None = AUTO_SELECT_TOP_K
    top_k: int | None                   # None = RETRIEVAL_TOP_K
    enriched_contexts: list[SectionContext]   # sections CANDIDATES
    submitted_contexts: list[SectionContext]  # celles que le budget a retenues
    response: str
    citations: list[Citation]
    images: list[ImageRef]
    search_count: int
    needs_more_info: bool
    next_query: str | None
    dropped_contexts: int               # écartées par le budget de fenêtre
    generation_measure: PromptMeasure | None  # décomptes réels d'Ollama
    _metadata: dict                     # chronométrage par étage
```

Deux champs demandent un mot, parce qu'ils existent pour la MESURE et non pour la
réponse. `enriched_contexts` porte les sections reconstruites, `submitted_contexts`
celles que `fit_prompt` a réellement retenues — tronquées si elles l'ont été. Une
métrique de précision du contexte calculée sur les premières mesure une intention ;
celle qui compte mesure ce qui a été payé en tokens. `generation_measure` porte les
décomptes de tokens rendus par le serveur d'inférence : ils ne sortaient qu'en
journal, donc personne ne les avait jamais observés.

---

## Vue IA générative

### Stratégie RAG

Le projet implémente un **RAG structurel, hybride et citable** :

1. **Réécriture de requête** — la question de suivi est rendue autonome avant
   l'encodage. Sans historique, la question est déjà autonome : aucun appel LLM.
2. **Recherche hybride et translingue** — la question est traduite dans l'autre
   langue du corpus, et quatre classements entrent dans la fusion : dense et
   lexical, pour la question et pour sa traduction. `FETCH_K` candidats chacun,
   fusionnés par Reciprocal Rank Fusion — sur les **rangs**, car une distance
   cosine et un score BM25 ne vivent pas sur la même échelle.

   Mesuré sur 130 questions : sans traduction, le rappel translinguistique
   plafonne à 0,806 ; avec, il atteint **1,000**. La recherche lexicale seule ne
   trouvait alors *rien* — deux langues ne partagent pas leurs mots.
3. **Reranking** — cross-encoder `mmarco-mMiniLMv2-L12-H384-v1`, multilingue.
   Déduplication par `element_id` avant la troncature au top-K. Le score exposé
   à l'utilisateur est la **sigmoïde** du logit : le brut est non borné et
   l'afficher comme une similarité induisait en erreur.
4. **Sélection** — interactive (l'utilisateur coche, sources groupées par
   document avec ouvrage, section, langue et pertinence) ou automatique
   (`AUTO_SELECT_TOP_K` mieux classées) pour `/answer`.
5. **Enrichissement structurel** — NebulaGraph reconstruit le fil des titres
   jusqu'au document, une fenêtre d'éléments autour de l'ancre, la fin de la
   section précédente et le début de la suivante, et rattache aux illustrations
   la légende que l'arête `DESCRIBES` désigne. Le texte intégral est relu dans
   l'index quand celui du graphe frôle sa troncature.
6. **Génération citée** — le LLM reçoit chaque élément suivi de son marqueur
   `[src:ELEMENT_ID]` et ne peut donc citer que de vrais identifiants. C'est du
   *citation anchoring* : ancrer les identifiants dans le prompt réduit les
   citations inventées, là où une extraction post-hoc doit deviner.
7. **Post-processing** — les `[src:ID]` sont résolus vers ouvrage, document,
   page et section ; les illustrations vers le proxy `/media`. Un identifiant
   inventé par le modèle est simplement ignoré.

   Deux subtilités, apprises à l'écran :

   Le modèle groupe volontiers plusieurs sources dans un seul crochet —
   `[src:aaa, src:bbb]`. Un motif exigeant le crochet fermant juste après
   l'identifiant n'en résolvait aucune, et les marqueurs restaient affichés
   bruts. Le bloc entier est capturé, puis tous les identifiants en sont
   extraits.

   Le modèle n'émet presque jamais `[img:ID]` : une illustration n'a pas de
   texte, il ne peut donc ni juger sa pertinence ni deviner qu'il faut la
   montrer. Ce sont les **illustrations des sections d'où viennent les
   citations** qui sont affichées — si une affirmation est tirée d'une section,
   la figure de cette section illustre ce dont on parle. Borné par `MAX_IMAGES`.

### Prompts

Versionnés dans `prompts/`, chargés dynamiquement. Le dossier configuré est
celui de l'image Docker ; hors conteneur, repli sur celui du dépôt.

| Fichier                    | Rôle                                                        |
|----------------------------|-------------------------------------------------------------|
| `system.txt`               | Règles : citer chaque affirmation, ne rien inventer, admettre l'ignorance, appeler l'outil plutôt que répondre partiellement |
| `answer_with_context.j2`   | Injecte les contextes enrichis et la question               |
| `rewrite_query.j2`         | Rend une question de suivi autonome                         |

### Boucle agentique

`search_vectors` est déclaré comme **outil natif** Ollama : le modèle répond par
un `tool_calls` structuré, capté au fil du flux et jamais rendu à l'utilisateur.
Le repérage de `search_vectors("…")` dans la prose reste actif en second rideau,
pour les modèles sans tool-calling ; le log indique lequel des deux canaux a
parlé. Limite : `MAX_SEARCH_ITERATIONS`.

### Budget de contexte

`num_ctx` est passé explicitement à chaque requête. Sans lui, la fenêtre dépend
de l'`OLLAMA_CONTEXT_LENGTH` du serveur interrogé — 8192 ou 32768 selon le
déploiement — et le même prompt produit deux comportements.

Le budget de sources vaut la fenêtre **moins la génération, moins tout ce que le
prompt contient déjà** : prompt système, gabarit rendu, historique retenu,
encadrement des sources. L'historique n'y entrait pas — un forfait de 512 tokens
en tenait lieu — et le prompt dépassait `num_ctx` dès le troisième tour d'une
conversation. Ollama tronque alors par le **début** du prompt, donc il jette le
message système et ses règles de citation, puis les sources les mieux classées —
en silence.

Ce qui dépasse est écarté **ici**, avec un log qui dit combien et pourquoi ;
`prompt_eval_count`, rendu par Ollama sur l'événement final du flux, confronte
l'estimation au décompte réel. Formule, chiffres et lecture des logs dans
[llm.md](llm.md).

### Paramètres

| Paramètre                  | Défaut | Rôle                                              |
|----------------------------|--------|---------------------------------------------------|
| `LLM_TEMPERATURE`          | `0.1`  | Faible, pour des réponses factuelles              |
| `LLM_MAX_TOKENS`           | `4096` | Plafond de génération (`num_predict`)             |
| `LLM_NUM_CTX`              | `8192` | Fenêtre demandée par requête                      |
| `LLM_THINKING`             | `false`| Raisonnement de Gemma 4, coûteux en CPU           |
| `HYBRID_SEARCH`            | `true` | BM25 en plus du dense                             |
| `FETCH_K`                  | `50`   | Candidats par moteur avant fusion                 |
| `RRF_K`                    | `60`   | Amortissement RRF                                 |
| `RETRIEVAL_TOP_K`          | `50`   | Candidats conservés après fusion, soumis au reranking |
| `CROSS_LINGUAL_SEARCH`     | `true` | Cherche aussi dans la traduction de la question    |
| `TRANSLATION_WEIGHT`       | `1.0`  | Poids de la traduction dans la fusion RRF          |
| `RERANK_TOP_K`             | `10`   | Éléments distincts conservés après reranking      |
| `QUERY_REWRITE`            | `true` | Réécriture des questions de suivi                 |
| `NATIVE_TOOL_CALLING`      | `true` | Outil Ollama plutôt que repli par regex           |
| `AUTO_SELECT_TOP_K`        | `3`    | Sources reconstruites sans sélection humaine      |
| `CONTEXT_WINDOW_BEFORE/AFTER` | `6`  | Éléments retenus autour de l'ancre                |
| `ADJACENT_SECTION_ELEMENTS`| `3`    | Éléments repris des sections voisines (0 désactive) |
| `MAX_IMAGES`               | `4`    | Illustrations affichées au maximum dans une réponse |
| `FULL_TEXT_FROM_VECTORS`   | `true` | Texte intégral relu dans l'index                  |
| `MAX_SEARCH_ITERATIONS`    | `3`    | Plafond de la boucle agentique                    |
| `GRAPH_TEXT_TRUNCATION`    | `2000` | Doit suivre le `graph_text_max_chars` de l'ingestion |
| `HISTORY_WINDOW_SHARE`     | `0.25` | Part de la fenêtre de prompt laissée à l'historique — forfait, cf. [llm.md](llm.md) |
| `CHECKPOINT_DB_PATH`       | `/app/data/checkpoints.sqlite` | Sessions LangGraph **et** registre de leur purge. Vide = checkpointer en mémoire, sessions perdues au redémarrage |
| `SESSION_TTL_SECONDS`      | `3600` | Âge au-delà duquel une session est purgée du checkpointer |
| `MAX_LIVE_SESSIONS`        | `200`  | Nombre de sessions gardées ; l'excédent le plus ancien est purgé |
| `USAGE_CAPTURE`            | `true` | Capture d'usage, cf. [capture_usage.md](capture_usage.md). **Sans effet sur la purge des sessions**, qui ne s'appuie pas sur cette base |
| `USAGE_DB_PATH`            | `/app/data/usage.sqlite` | Même volume que le checkpointer |
| `RESTRICT_MEDIA_TO_GRAPH`  | `true` | Le proxy `/media` ne sert que les objets référencés par le graphe |
| `NEBULA_TIMEOUT_MS`        | `15000`| Sans lui, une requête lente du graphd fige la requête FastAPI qui l'attend |
| `API_KEY` / `CORS_ORIGINS` | vide / `localhost` | Vide = aucune authentification, acceptable en local seulement |
| `LOG_LEVEL`                | `INFO` | Attention : un `logger.debug` est invisible à ce niveau, et c'est ainsi qu'une purge en panne est restée cachée |

La table n'est pas exhaustive et ne prétend pas l'être : `.env.example` est la
liste complète, et `settings.py` la seule source de vérité. Aucun paramètre
n'existe ici qui ne s'y trouve — c'est la règle qu'un `RERANK_MIN_SCORE`
fantôme avait enfreinte.

---

## Vue déploiement

### Services Docker

```
docker-compose.yml
│
├── ollama          (ollama/ollama:latest)
│   ├── Volumes     : models_cache → /root/.ollama
│   ├── Entrypoint  : ollama_entrypoint.sh (pull modèle si absent)
│   ├── Réseaux     : rag_network + internal
│   └── Healthcheck : ollama list | grep -q '.'
│
├── agent-api       (Dockerfile.agent — python:3.12-slim multi-stage)
│   ├── Ports       : 8001:8000
│   ├── Volumes     : ./prompts:/app/prompts:ro
│   ├── Réseaux     : rag_network + internal
│   ├── Depends     : ollama (healthy)
│   └── Healthcheck : curl /health
│
└── frontend        (Dockerfile.frontend — python:3.12-slim multi-stage)
    ├── Ports       : 8501:8501
    ├── Réseaux     : internal uniquement
    └── Depends     : agent-api (healthy)
```

### Réseaux

| Réseau      | Type     | Rôle                                                     |
|-------------|----------|----------------------------------------------------------|
| `rag_network` | external | Réseau partagé avec `rag-ingestion-pipeline` — accès ChromaDB, NebulaGraph, MinIO |
| `internal`  | bridge   | Réseau interne : Streamlit → agent-api → Ollama          |

Le frontend n'est pas connecté au réseau `rag_network` (il ne communique qu'avec `agent-api`).

### Ordre de démarrage

```
rag-ingestion-pipeline (prérequis externe, déjà démarré)
    └── ChromaDB, NebulaGraph, MinIO disponibles sur rag_network

ollama (pull modèle ~3,3 Go au premier démarrage)
    └── healthy après ~5-10 min (premier démarrage)

agent-api (attend ollama healthy)
    └── healthy après ~30s

frontend (attend agent-api healthy)
    └── disponible sur http://localhost:8506
```

---

## Endpoints API

| Méthode | Route                    | Description                                          |
|---------|--------------------------|------------------------------------------------------|
| GET     | `/health`                | Statut API + modèle Ollama actif                    |
| POST    | `/search`                | Retrieval brut ChromaDB (sans reranking)             |
| POST    | `/sources`               | Retrieval + reranking + groupement par document      |
| GET     | `/context/{element_id}`  | Contexte enrichi NebulaGraph (breadcrumbs + section) |
| POST    | `/answer`                | Question → réponse sans sélection humaine. Expose le classement, les sections reconstruites — `retained` distinguant celles qui sont réellement parties au LLM —, la partition du temps par étage (résidu compris) et les décomptes de tokens du serveur d'inférence : c'est le point d'entrée de la campagne d'évaluation |
| POST    | `/chat/simple`           | Génération directe sans LangGraph (SSE optionnel)   |
| POST    | `/chat/start`            | Démarre session agentique → interrupt source selection |
| POST    | `/chat/resume`           | Reprend après sélection sources → génération        |
| POST    | `/feedback`              | Appréciation binaire d'une réponse + commentaire libre |
| POST    | `/reindex`               | Reconstruit l'index lexical BM25 sur le corpus courant. **Appelé par l'ingestion en fin de pipeline** : sans lui, un document ingéré après le démarrage reste invisible en recherche lexicale |
| GET     | `/media/{object_name}`   | Proxy des objets MinIO — les URLs internes ne sont pas résolvables par le navigateur. Borné aux objets référencés par le graphe |

Onze routes. `/health` est la seule qui n'exige pas `X-API-Key` quand une clé
est configurée : une sonde doit rester interrogeable sans secret.

Documentation interactive : `http://localhost:8001/docs`

---

## Limitations connues

| Aspect                  | Limitation                                                     |
|-------------------------|----------------------------------------------------------------|
| Granularité de la mesure | Le jeu doré n'annote qu'au **document** : un chapitre entier compte comme un succès. Cette granularité ne peut pas départager deux configurations de retrieval. |
| Taille du jeu doré      | 15 questions. Sur cet effectif, un écart d'un dixième est du bruit. |
| Latence de génération   | ~10 s en médiane contre 0,4 s de retrieval. Le levier est le LLM, pas la recherche. |
| Index BM25              | Construit en mémoire au premier appel : la **première** requête après un démarrage paie ~9 s — chiffre **non mesuré**, cf. [axes_amelioration.md](axes_amelioration.md) §2 — et c'est la seule qui paie encore. Un corpus qui grandit sous l'index déclenche une reconstruction en tâche de fond, et `POST /reindex` la force ; `/health` rend `index_lexical: false` sur un index périmé. Un corpus nettement plus gros demanderait un moteur dédié. |
| Coût de la traduction   | Un appel LLM par question s'ajoute à la recherche. Un cache, ou un modèle plus petit dédié, l'amortirait. |
| Multi-workers           | Les sessions et leur purge sont persistées, mais l'index BM25 et les modèles sont chargés par processus : N workers = N copies en mémoire, et **`POST /reindex` ne reconstruit que l'index du worker qui reçoit la requête**. Le contrat de réindexation suppose aujourd'hui un worker unique. |
| Authentification        | Absente. CORS `*` et `/media` ouvert : quiconque atteint l'API lit tout le bucket. Acceptable en local, bloquant dès qu'on expose. |
| Streaming E2E           | SSE implémenté, non couvert par un test de bout en bout.       |
| Observabilité           | Logs console uniquement, pas de tracing distribué.             |
