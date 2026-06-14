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
 START ──▶│ retrieve │  ChromaDB : top-K chunks par embedding
          └────┬─────┘
               │
          ┌────▼─────┐
          │  rerank  │  Cross-encoder : affine la sélection → top-N
          └────┬─────┘
               │
          ┌────▼──────────────────┐
          │ await_source_selection│  ← INTERRUPT (human-in-the-loop)
          └────┬──────────────────┘    L'utilisateur choisit ses sources
               │  selected_element_ids injectés via /chat/resume
          ┌────▼──────────────────┐
          │ reconstruct_context   │  NebulaGraph : contexte hiérarchique
          └────┬──────────────────┘
               │
          ┌────▼─────┐
          │ generate │  Ollama : génération LLM avec streaming optionnel
          └────┬─────┘
               │
          ┌────▼───────────┐
          │  postprocess   │  Extraction citations [src:ID] et images [img:ID]
          └────┬───────────┘
               │
        ┌──────▼──────┐
        │ needs_more? │  Le LLM peut demander search_vectors("query")
        └──┬──────────┘
           │ True (≤ 3x)      │ False
           └──▶ retrieve      └──▶ END
```

### Interrupt / Resume

Le graphe est compilé avec `interrupt_before=["await_source_selection"]` et un `MemorySaver` comme checkpointer :

```python
agent_graph = build_graph().compile(
    interrupt_before=["await_source_selection"],
    checkpointer=MemorySaver(),
)
```

**Protocole API** :
1. `POST /chat/start` — `ainvoke(initial_state, config)` → s'arrête avant `await_source_selection`, retourne `thread_id` + groupes de sources.
2. `POST /chat/resume` — `aupdate_state(config, {selected_element_ids})` puis `ainvoke(None, config)` → reprend depuis le point d'interruption.

**Limite** : le `MemorySaver` est in-memory. Les sessions sont perdues au redémarrage du container `agent-api`.

---

## Vue applicative : composants

### `src/agent/`

| Module              | Responsabilité                                                  |
|---------------------|-----------------------------------------------------------------|
| `graph.py`          | Définition des nœuds, arêtes, conditions et compilation du graphe LangGraph |
| `graph_context.py`  | Reconstruction contextuelle via NebulaGraph (breadcrumbs + enfants de section) |
| `llm.py`            | Client Ollama (OpenAI-compatible), rendu Jinja2 des prompts, streaming |
| `retriever.py`      | Embedding ChromaDB + reranking cross-encoder + groupement par document |
| `minio_client.py`   | Génération d'URLs présignées MinIO pour les assets visuels      |
| `state.py`          | `AgentState` — TypedDict LangGraph (question, chunks, contextes, réponse…) |
| `settings.py`       | Configuration via `pydantic-settings` (lecture `.env`)          |
| `tools.py`          | Outil `search_vectors` déclaré pour la boucle agentique         |

### `src/api/`

| Module       | Responsabilité                               |
|--------------|----------------------------------------------|
| `main.py`    | Endpoints FastAPI (7 routes), middleware CORS |
| `schemas.py` | Modèles Pydantic v2 (requêtes et réponses)   |

### `src/frontend/`

| Module  | Responsabilité                                                           |
|---------|--------------------------------------------------------------------------|
| `app.py`| Interface Streamlit 3 phases : saisie question → sélection sources → affichage réponse |

---

## Vue données

### Contrat de lecture ChromaDB

- Collection : `rag_documents`
- Embedding : `all-MiniLM-L6-v2` (384 dimensions) — **doit être identique à l'ingestion**
- Métadonnées disponibles par chunk : `element_id`, `filename`, `page_no`, `minio_url`
- Paramètres de retrieval : `RETRIEVAL_TOP_K=20` (brut) → `RERANK_TOP_K=10` (après reranking)
- Filtre de pertinence : `RERANK_MIN_SCORE=0.0` — les chunks sous ce score sont écartés (au moins 1 toujours conservé)
- Enrichissement d'affichage : après reranking, chaque chunk est enrichi via NebulaGraph (`get_section_text`) pour obtenir le texte du SectionHeader parent (`section_header_text`), affiché dans l'interface de sélection des sources

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

```python
class AgentState(TypedDict):
    question: str
    chat_history: list[Message]
    retrieved_chunks: list[RetrievedChunk]
    reranked_chunks: list[RetrievedChunk]
    selected_element_ids: list[str]
    enriched_contexts: list[SectionContext]
    response: str
    citations: list[Citation]
    images: list[ImageRef]
    search_count: int
    needs_more_info: bool
    next_query: str | None
    _metadata: dict
```

---

## Vue IA générative

### Stratégie RAG

Le projet implémente un **RAG sélectif interactif** :

1. **Retrieval dense** : embedding `all-MiniLM-L6-v2` sur la question, recherche par cosine similarity dans ChromaDB.
2. **Reranking** : cross-encoder `cross-encoder/ms-marco-MiniLM-L6-v2` pour affiner la pertinence.
3. **Sélection humaine** : l'utilisateur visualise les sources groupées par document. Chaque chunk affiche le texte de son SectionHeader parent (`section_header_text`) et son score de reranking. Seuls les chunks avec `rerank_score ≥ RERANK_MIN_SCORE` sont proposés.
4. **Enrichissement contextuel** : pour chaque source sélectionnée, NebulaGraph reconstruit la section parente, les breadcrumbs hiérarchiques et les éléments frères (max 12, images/tableaux résolus via MinIO).
5. **Génération citée** : le LLM génère une réponse avec citations numérotées `[src:N]` et références visuelles `[img:ELEMENT_ID]`. Le postprocessing résout `N` → `element_id` via `alias_map` pour constituer les citations structurées.

### Prompts

Les prompts sont versionnés dans `prompts/` et chargés dynamiquement :

| Fichier                    | Rôle                                                              |
|----------------------------|-------------------------------------------------------------------|
| `system.txt`               | Règles système : citer toutes les affirmations, ne pas halluciner, répondre en français |
| `answer_with_context.j2`   | Template Jinja2 : injecte les contextes enrichis + la question    |
| `rewrite_query.j2`         | Template de reformulation de requête (boucle agentique)           |

**Règles de citation** (system.txt) :
- Citer chaque affirmation avec `[src:N]` (N = numéro de source, 1-based)
- Référencer les images/tableaux avec `[img:ELEMENT_ID]`
- Ne jamais aller au-delà des sources fournies
- Déclarer explicitement l'absence d'information si non trouvée

### Boucle agentique (agentic loop)

Le LLM peut demander une recherche supplémentaire en incluant `search_vectors("sous-question")` dans sa réponse. Le nœud `node_generate` détecte ce pattern par regex et relance le graphe via la condition `should_search_more` (limite : `MAX_SEARCH_ITERATIONS=3`).

**Statut** : implémenté, non évalué en production.

### Paramètres LLM

| Paramètre         | Valeur    | Description                             |
|-------------------|-----------|-----------------------------------------|
| `LLM_TEMPERATURE` | `0.1`     | Faible pour des réponses factuelles     |
| `LLM_MAX_TOKENS`  | `4096`    | Limite de génération                    |
| Contexte max      | dépend du modèle | gemma3:4b : 8192 tokens         |

### Paramètres de retrieval

| Paramètre              | Valeur   | Description                                              |
|------------------------|----------|----------------------------------------------------------|
| `RETRIEVAL_TOP_K`      | `20`     | Nombre de chunks retournés par ChromaDB                  |
| `RERANK_TOP_K`         | `10`     | Chunks conservés après reranking cross-encoder           |
| `RERANK_MIN_SCORE`     | `0.0`    | Score minimum cross-encoder — chunks en dessous écartés  |
| `MAX_SEARCH_ITERATIONS`| `3`      | Limite de la boucle agentique                            |

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
| POST    | `/chat/simple`           | Génération directe sans LangGraph (SSE optionnel)   |
| POST    | `/chat/start`            | Démarre session agentique → interrupt source selection |
| POST    | `/chat/resume`           | Reprend après sélection sources → génération        |

Documentation interactive : `http://localhost:8001/docs`

---

## Limitations connues

| Aspect                 | Limitation                                                     |
|------------------------|----------------------------------------------------------------|
| Persistance sessions   | `MemorySaver` in-memory — sessions perdues au redémarrage      |
| Documents sans sections | Éléments enfants du nœud `Document` racine — contexte reconstruit = document entier (potentiellement très large) |
| Streaming E2E          | SSE implémenté, non testé de bout en bout avec le frontend     |
| Tests d'intégration    | Non implémentés                                                |
| Authentification       | Absente — API accessible sans contrôle d'accès                 |
| Observabilité          | Logs console uniquement, pas de tracing distribué              |
