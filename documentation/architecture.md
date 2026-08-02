# Architecture de rag-agent-chat

## Vue d'ensemble

Agent RAG conversationnel qui consomme **en lecture seule** les stores produits
par `rag-ingestion-pipeline` (ChromaDB, NebulaGraph, MinIO) et génère les
réponses avec un LLM servi par le projet `llm-service`. Le flux est orchestré
par une machine à états LangGraph, avec deux points d'entrée : un flux
interactif où l'utilisateur choisit ses sources, et un flux direct destiné à
l'évaluation.

## Services Docker

| Service   | Image / Build       | Port interne | Port hôte | Rôle                                 |
|-----------|---------------------|--------------|-----------|--------------------------------------|
| agent-api | Dockerfile.agent    | 8000         | 8011      | Backend FastAPI (LangGraph, SSE)     |
| frontend  | Dockerfile.frontend | 8501         | 8506      | UI Streamlit                         |

**Aucun serveur d'inférence n'est embarqué.** Les LLM viennent du conteneur
`ollama-central` du projet `llm-service`. Une instance Ollama vivait ici : elle
faisait doublon et retéléchargeait plusieurs gigaoctets d'un modèle déjà servi.

Trois réseaux :

- `rag_network` (externe, créé par `rag-ingestion-pipeline`) : accès aux stores
  `chromadb:8000`, `graphd:9669`, `minio:9000` ;
- `llm-net` (externe, créé par `llm-service`) : accès à `ollama-central:11434` ;
- `internal` (bridge) : frontend ↔ agent-api.

Volumes : `rag_hf_cache` (modèles HuggingFace — embedding et cross-encoder,
téléchargés au premier démarrage), `rag_agent_state` (sessions LangGraph).

## Machine à états LangGraph

```
rewrite → retrieve → rerank ─┬─(1ʳᵉ passe)──→ await_source_selection ─→ reconstruct_context
                             └─(itération)────────────────────────────────↗
reconstruct_context → generate → postprocess ─┬─(recherche demandée & < max)─→ retrieve
                                              └─(sinon)─→ END
```

Le même graphe est compilé de deux façons :

| Compilation   | Interruption | Checkpointer | Consommé par |
|---------------|--------------|--------------|--------------|
| `agent_graph`  | `interrupt_before=["await_source_selection"]` | SQLite | `/chat/start` + `/chat/resume` |
| `answer_graph` | aucune       | aucun        | `/answer` |

Le flux interactif attend un humain : il n'est pas rejouable en batch. C'est
pourquoi `answer_graph` existe — sans lui, aucune campagne d'évaluation ne peut
mesurer le système.

## Flux de bout en bout

1. **Réécriture** (`node_rewrite`) : la question de suivi est rendue autonome
   avant d'être encodée. « Et comment la calcule-t-on ? » embarqué tel quel ne
   retrouve rien. Sans historique, aucun appel au LLM.
2. **Recherche** (`node_retrieve`) : recherche dense ChromaDB **et** BM25
   lexical, chacun ramenant `FETCH_K` candidats, fusionnés par Reciprocal Rank
   Fusion. Le dense rate ce qui ne se paraphrase pas — acronymes, noms propres,
   références, chiffres.
3. **Reranking** (`node_rerank`) : cross-encoder multilingue, déduplication par
   `element_id` **avant** la troncature au top-K (plusieurs fenêtres d'un même
   passage occupaient sinon plusieurs places).
4. **Sélection** : interactive (l'utilisateur coche) ou automatique
   (`AUTO_SELECT_TOP_K` mieux classés).
5. **Reconstruction** (`node_reconstruct_context`) : remontée `PARENT_OF`
   jusqu'au `Document` en notant les titres traversés, fenêtre d'éléments autour
   de l'ancre, fin de la section précédente et début de la suivante, légendes
   rattachées aux illustrations via `DESCRIBES`, texte intégral relu dans
   l'index quand celui du graphe frôle sa troncature.
6. **Génération** (`node_generate`) : Ollama `/api/chat`, `num_ctx` explicite,
   sources écartées avec un log si le budget de fenêtre est dépassé, tokens
   streamés en SSE.
7. **Post-processing** (`node_postprocess`) : citations `[src:ID]` résolues vers
   document, ouvrage, page et section ; images `[img:ID]` servies par `/media`.
8. **Boucle agentique** : si le modèle appelle l'outil `search_vectors`, une
   nouvelle passe recherche → rerank → reconstruction s'enchaîne sans
   re-sélection, contextes accumulés, dans la limite de `MAX_SEARCH_ITERATIONS`.

## Décisions d'architecture

- **Reconstruction par le graphe** plutôt que chunks isolés : le LLM reçoit la
  section, ses voisines et ses illustrations. C'est le pattern
  *parent-document retrieval*.
- **Le graphe porte la structure, l'index porte le texte.** L'ingestion tronque
  le texte des nœuds à 2000 caractères ; le texte intégral est relu dans
  ChromaDB pour les éléments qui frôlent cette limite. Un tableau Docling
  dépasse souvent la limite et arrivait amputé.
- **Recherche hybride fusionnée par RRF, pas par somme de scores** : une
  distance cosine et un score BM25 ne vivent pas sur la même échelle. RRF
  n'additionne que des rangs, ce qui rend la fusion insensible à la calibration
  de chaque moteur.
- **Modèles multilingues des deux côtés.** Le corpus mêle français et anglais.
  Mesuré : un cross-encoder anglais rendait une étendue de scores de 0,0 % sur
  une question française — un classement au hasard, qui défaisait le travail de
  l'embedder multilingue.
- **`num_ctx` explicite** dans chaque requête : sans lui la fenêtre dépend du
  serveur interrogé, et le même prompt produit deux comportements. Les sources
  qui dépassent le budget sont écartées **ici**, avec un log ; Ollama, lui,
  tronque par le début, donc par les sources les mieux classées.
- **Tool-calling natif, repli par regex.** `search_vectors` est déclaré comme
  outil ; le repérage de l'appel dans la prose reste actif pour les modèles sans
  tool-calling.
- **API native Ollama + thinking désactivé** (`LLM_THINKING=false`) : sans ce
  flag, la réflexion peut consommer tout le budget `num_predict` avant le
  premier token. L'endpoint OpenAI-compatible ne permet pas de piloter `think`.
- **Proxy `/media`** : les URLs MinIO internes ne sont pas résolvables par le
  navigateur ; l'API sert les objets, chemin validé contre le path traversal.
- **Sessions persistées sur disque** (SQLite) : en mémoire, une session en
  attente de sélection ne survivait pas au redémarrage, et deux workers uvicorn
  ne partageaient pas leurs threads. Purge par âge et par nombre.
- **Réouverture des connexions** : les clients Chroma / Nebula / MinIO sont
  mémorisés ; sans réouverture, le redémarrage d'un store cassait l'agent
  jusqu'au sien.
- **VIDs échappés, pas filtrés.** Les identifiants de documents dérivent d'un
  chemin — séparateurs, espaces, accents — et aucun motif ne les couvre sans
  devenir une passoire. Ils ne viennent jamais de l'utilisateur. La validation
  stricte (`^[a-f0-9]{10}$`) reste sur le seul format qu'un appelant fournit.
- **Endpoints synchrones en `def`** : l'inférence CPU tourne dans le threadpool
  FastAPI, l'event loop reste libre.
- **Torch CPU-only** dans l'image : pas de libs CUDA embarquées.

## Contrat d'interface avec l'ingestion

Voir [llm_integration_plan.md](llm_integration_plan.md). Points clés :

- **ChromaDB** `rag_documents` : `element_id`, `graph_node_id`, `filename`,
  `collection`, `source_path`, `section_title`, `language`, `depth`, `label`,
  `page_no`, `minio_url`, `chunk_index`, `chunk_count`.
  Un élément long est réparti sur plusieurs chunks `#0`, `#1` partageant leur
  `element_id` : la déduplication en dépend.
- **NebulaGraph** `rag_space` : `Document → SectionHeader → SectionHeader → …`
  via `PARENT_OF(sequence)`, plus `DESCRIBES` de chaque légende vers son
  illustration. VIDs = sha256[:10] (éléments) ou `doc_{chemin}` (documents).
- **MinIO** bucket `documents` : crops PNG sous `images/{stem}/{id}_{type}.png`.
- **Embedding** : `paraphrase-multilingual-MiniLM-L12-v2` (384 dim) —
  obligatoirement le même des deux côtés. En changer impose une réingestion
  complète du corpus.

## Évaluation

`scripts/evaluate.py` interroge `/answer` sur un jeu doré et calcule ce qui se
mesure sans juge LLM. Voir [rag_evaluation_strategy.md](rag_evaluation_strategy.md).
