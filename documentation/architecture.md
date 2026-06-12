# Architecture de rag-agent-chat

## Vue d'ensemble

Agent RAG conversationnel qui consomme **en lecture seule** les stores produits
par `rag-ingestion-pipeline` (ChromaDB, NebulaGraph, MinIO) et génère les
réponses avec un LLM local servi par Ollama. Le flux est orchestré par une
machine à états LangGraph avec sélection des sources par l'utilisateur
(human-in-the-loop).

## Services Docker

| Service   | Image / Build       | Port interne | Port hôte | Rôle                                  |
|-----------|---------------------|--------------|-----------|----------------------------------------|
| ollama    | ollama/ollama       | 11434        | —         | LLM local (Gemma 4 E4B par défaut)     |
| agent-api | Dockerfile.agent    | 8000         | 8000      | Backend FastAPI (flux LangGraph, SSE)  |
| frontend  | Dockerfile.frontend | 8501         | 8501      | UI Streamlit                           |

Deux réseaux :
- `rag_network` (externe, créé par rag-ingestion-pipeline) : accès aux stores
  `chromadb:8000`, `graphd:9669`, `minio:9000`
- `internal` (bridge) : communication frontend ↔ agent-api ↔ ollama

Volumes : `rag_models_cache` (modèles Ollama), `rag_hf_cache` (modèles
HuggingFace : embedding + cross-encoder, téléchargés au premier démarrage).

## Flux de bout en bout

1. **`POST /chat/start`** (question + historique) : embedding de la question
   (`all-MiniLM-L6-v2`, le même modèle que l'ingestion), retrieval ChromaDB
   (top-20), reranking cross-encoder (top-10). Le graphe LangGraph s'interrompt
   (`interrupt_before`) et l'état est persisté par le checkpointer sous un
   `thread_id`.
2. **Sélection des sources** : le frontend affiche les chunks groupés par
   document ; l'utilisateur coche/décoche.
3. **`POST /chat/resume`** (thread_id + ids sélectionnés) : reprise du graphe.
   Pour chaque élément, **reconstruction du contexte** via NebulaGraph —
   remontée `PARENT_OF` jusqu'au `SectionHeader`, récupération de tous les
   enfants ordonnés, assemblage en markdown avec breadcrumb et marqueurs
   `[src:ID]` par élément.
4. **Génération** : Ollama via son API native `/api/chat` (avec `think: false`
   par défaut — voir décisions), tokens streamés en SSE jusqu'au frontend.
5. **Post-processing** : extraction des citations `[src:ID]` (résolues vers
   fichier/page) et des images `[img:ID]` (servies via le proxy `GET /media`).
6. **Boucle agentique** : si le LLM émet `search_vectors("sous-question")`,
   nouvelle passe retrieval → rerank → reconstruction (sans re-sélection
   utilisateur, contextes accumulés), max `MAX_SEARCH_ITERATIONS` itérations.

## Machine à états LangGraph

```
retrieve → rerank ─┬─(1ʳᵉ passe)──→ await_source_selection ─→ reconstruct_context
                   └─(itération)──────────────────────────────↗
reconstruct_context → generate → postprocess ─┬─(search_vectors & < max)─→ retrieve
                                              └─(sinon)─→ END
```

Compilé avec `MemorySaver` (checkpointer) + `interrupt_before=["await_source_selection"]`.
La reprise se fait par `aupdate_state(config, {...})` puis `ainvoke(None, config)`.

## Décisions d'architecture

- **Reconstruction par le graphe** plutôt que chunks isolés : le LLM reçoit la
  section complète avec hiérarchie, images et tableaux.
- **API native Ollama + thinking désactivé par défaut** (`LLM_THINKING=false`) :
  Gemma 4 est un modèle à raisonnement — sans ce flag, la réflexion peut
  consommer tout le budget `num_predict` avant le premier token de réponse
  (rédhibitoire en CPU). L'endpoint OpenAI-compatible ne permet pas de piloter
  `think`, d'où l'API native. Activer le thinking sur GPU si souhaité.
  Exige une image Ollama récente (les versions antérieures à Gemma 4 bouclent
  à l'infini sans erreur sur cette architecture).
- **Protocole textuel `search_vectors(...)`** plutôt que tool-calling natif :
  robuste quel que soit le support tools du modèle servi par Ollama ; la
  syntaxe est nettoyée de la réponse finale.
- **Proxy `/media`** : les URLs MinIO internes (`minio:9000`) ne sont pas
  résolvables par le navigateur ; l'API sert les objets (chemin validé contre
  le path traversal).
- **Endpoints synchrones en `def`** : l'inférence CPU (embedding,
  cross-encoder) tourne dans le threadpool FastAPI, l'event loop reste libre.
- **`SessionPool` NebulaGraph** lié au space : sessions réutilisées, pas de
  `USE` par requête ; propriétés d'un nœud en une requête `FETCH PROP ON *`.
- **VIDs validés** (`^[a-f0-9]{10}$` / `doc_*`) avant toute interpolation nGQL.
- **Torch CPU-only** dans l'image agent : pas de libs CUDA embarquées.
- **`OLLAMA_CONTEXT_LENGTH=8192`** : sans ça, Ollama tronque silencieusement
  le prompt — fatal quand on injecte des sections entières.

## Contrat d'interface avec l'ingestion

Voir [llm_integration_plan.md](llm_integration_plan.md). Points clés :
- ChromaDB `rag_documents` : métadonnées `element_id`, `graph_node_id`,
  `filename`, `label`, `page_no`, `minio_url`
- NebulaGraph `rag_space` : hiérarchie `Document → SectionHeader → Éléments`
  via edges `PARENT_OF(sequence)` ; VIDs = sha256[:10] (éléments) ou
  `doc_{stem}` (documents)
- MinIO bucket `documents` : crops PNG sous `images/{stem}/{id}_{type}.png`
- Embedding : `all-MiniLM-L6-v2` (384 dim) — obligatoirement le même des deux côtés
