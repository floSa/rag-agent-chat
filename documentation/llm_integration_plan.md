# Plan d'integration LLM / Agent RAG

## 1. Contexte et vision

Le pipeline d'ingestion (`rag-ingestion-pipeline`) est complet :
documents PDF/HTML -> extraction structuree (Docling) -> graphe de connaissances
(NebulaGraph) + base vectorielle (ChromaDB) + medias (MinIO).

L'agent RAG sera un **projet separe** qui consomme ces stores en lecture.
Ce document est le contrat d'interface entre les deux projets.

### Principe directeur

Le RAG classique balance des chunks isoles. Notre approche est differente :
on utilise le **graphe de connaissances pour reconstruire le contexte structurel**
du document autour de chaque chunk trouve. L'utilisateur garde le controle
en selectionnant les sources avant la generation.

---

## 2. Architecture du flux agent

```
Utilisateur
    |
    | 1. Question
    v
[Query Processing]
    |
    | 2. Embedding de la question
    v
[ChromaDB] -----> top-K chunks + metadatas (graph_node_id, document, score)
    |
    | 3. Reranking (cross-encoder)
    v
[Source Preview]
    |
    | 4. Affichage groupé par document, avec extraits et scores
    | 5. L'utilisateur selectionne / elimine des sources
    v
[Graph Context Reconstruction]  <-- ETAPE CLE
    |
    | 6. Pour chaque chunk selectionne :
    |    - NebulaGraph: remonter PARENT_OF jusqu'au section_header
    |    - NebulaGraph: redescendre pour recuperer tous les enfants de la section
    |    - MinIO: recuperer les images/tables de la section
    v
[Enriched Context Builder]
    |
    | 7. Assemblage : markdown structure avec hierarchie,
    |    images en base64/URL, metadatas de position
    v
[LLM Generation]
    |
    | 8. Reponse avec citations [source:element_id]
    |    + images jointes si pertinentes
    v
[Post-processing]
    |
    | 9. Extraction des citations, validation guardrails
    | 10. Si le modele a besoin de plus : TOOL search_vectors(query)
    |     -> retour a l'etape 6 (max 3 iterations)
    v
Reponse finale a l'utilisateur
    (texte + citations + images)
```

---

## 3. Detail des etapes

### 3.1 Retrieval initial (ChromaDB)

```python
collection.query(
    query_embeddings=[embed(question)],
    n_results=20,                          # sur-recuperer pour le reranking
    include=["documents", "metadatas", "distances"],
)
```

Chaque resultat contient dans ses metadatas :
- `graph_node_id` : ID du noeud NebulaGraph (= `element_id`)
- `element_id` : hash sha256[:10] de l'element
- `page_position`, `ref_position` : position dans la page et sous le parent
- `minio_url` : URL de l'image/table si applicable

### 3.2 Reranking

Apres le retrieval brut, un **cross-encoder** re-score les chunks par rapport
a la question pour ameliorer la precision. On garde les top-10.

Pourquoi : les embeddings bi-encoder (all-MiniLM-L6-v2) sont rapides mais
imprecis. Le cross-encoder est lent mais beaucoup plus precis sur le ranking.

### 3.3 Source Preview et selection utilisateur

Affichage groupe par document :

```
Resultats pour "Comment Docling gere-t-il les tableaux ?"

[x] 2408.09869.pdf (score: 0.92)
    - "Table structure recognition..." (p.4, section 3.3)
    - "TableFormer model..." (p.5, section 3.3)

[x] docling_manual.pdf (score: 0.78)
    - "Configuration options..." (p.12, section 5.1)

[ ] unrelated_paper.pdf (score: 0.45)
    - "Table of contents..." (p.1)

> Deselectionner les sources non pertinentes, puis valider.
```

L'utilisateur peut :
- Decocher des documents entiers
- Decocher des chunks individuels
- Valider pour lancer la generation

### 3.4 Graph Context Reconstruction (etape cle)

C'est le coeur de l'avantage. Pour chaque chunk selectionne :

**Phase 1 — Remonter au section_header**

```ngql
-- Trouver le chemin du chunk vers le section_header parent
GO FROM "element_id" OVER PARENT_OF REVERSELY
YIELD dst(edge) AS parent_id
| GO FROM $-.parent_id OVER PARENT_OF REVERSELY
YIELD dst(edge) AS grandparent_id;
```

On remonte les edges `PARENT_OF` jusqu'a trouver un noeud avec le tag
`SectionHeader` (ou `Document` si pas de section parent). Par defaut,
on s'arrete au premier `SectionHeader` rencontre.

**Strategie de profondeur** : si le chunk est dans la section 3.2.1 :
- On reconstruit la section **immediate** (3.2.1) avec tous ses enfants
- On remonte la **chaine de breadcrumbs** jusqu'au Document :
  `Document > 3. Processing Pipeline > 3.2 Layout Analysis > 3.2.1 Table Recognition`
- Les sections parentes sont **mentionnees par leur titre** (pas reconstruites)
  pour donner au modele le contexte hierarchique sans exploser le budget tokens

Exemple de contexte injecte :

```
[Breadcrumb] 2408.09869.pdf > 3. Processing Pipeline > 3.2 Layout Analysis

## 3.2.1 Table Recognition

TableFormer is a deep learning model that predicts the structure of tables...
[paragraphe complet]

[Table: structure_example.png] (img:28b88acbd9)

Caption: Figure 3 - Example of table structure prediction.
```

**Phase 2 — Redescendre pour recuperer le contexte complet**

```ngql
-- Recuperer tous les enfants de la section, dans l'ordre
GO FROM "section_header_id" OVER PARENT_OF
YIELD properties($$).label AS label,
      properties($$).text AS text,
      properties($$).minio_url AS minio_url,
      properties(edge).sequence AS seq
| ORDER BY $-.seq ASC;
```

**Phase 3 — Recuperer les images/tables**

Pour chaque enfant ayant un `minio_url` non vide :
- Telecharger l'image depuis MinIO
- L'encoder en base64 pour injection dans le prompt (LLM multimodal)
- Ou fournir l'URL pour affichage dans la reponse

**Resultat** : au lieu d'un chunk isole de 500 caracteres, le modele recoit
la section complete avec sa hierarchie, ses images, et ses tableaux.

### 3.5 Generation LLM

Le prompt systeme :

```
Tu es un assistant qui repond aux questions en te basant UNIQUEMENT
sur les sources fournies. Chaque source est une section de document
avec sa hierarchie, ses images et ses tableaux.

Regles :
- Cite tes sources avec [src:ELEMENT_ID] apres chaque affirmation
- Si une image ou un tableau est pertinent, inclus-le dans ta reponse
  avec la reference [img:ELEMENT_ID]
- Si tu as besoin de plus d'informations, utilise l'outil search_vectors
- Ne reponds JAMAIS au-dela de ce que disent les sources
- Si les sources ne permettent pas de repondre, dis-le explicitement
```

### 3.6 Agentic loop (recherche iterative)

Le modele dispose d'un tool `search_vectors(query: str)` qui :
1. Effectue une nouvelle recherche ChromaDB avec la sous-question
2. Reranke les resultats
3. Reconstruit le contexte via le graphe (SANS repasser par la selection user)
4. Injecte le nouveau contexte dans la conversation

**Garde-fous** :
- Maximum **3 iterations** de recherche par question
- Budget total de tokens (ex: 100K tokens de contexte max)
- Le modele doit justifier pourquoi il a besoin de plus d'info

### 3.7 Post-processing de la reponse

1. **Extraction des citations** : parser les `[src:ELEMENT_ID]` pour construire
   la liste des sources utilisees
2. **Inclusion des images** : pour chaque `[img:ELEMENT_ID]`, recuperer l'URL
   MinIO et l'attacher a la reponse
3. **Validation guardrails** : verifier que la reponse ne contient pas de PII,
   que chaque affirmation a une citation, etc.

---

## 4. Modele de donnees (contrat d'interface)

### 4.1 ChromaDB — Collection `rag_documents`

| Champ          | Type          | Description                                |
|----------------|---------------|--------------------------------------------|
| id             | string        | `{element_id}_part{i}` (chunk ID)          |
| embedding      | float[384]    | Vecteur all-MiniLM-L6-v2                   |
| document       | string        | Texte du chunk (max 500 chars)             |
| metadata.element_id    | string | Hash ID de l'element source         |
| metadata.graph_node_id | string | = element_id, cle pour NebulaGraph  |
| metadata.page_position | int    | Position dans la page               |
| metadata.ref_position  | int    | Position sous le parent             |
| metadata.minio_url     | string | URL MinIO si image/table            |

**Modele d'embedding** : `all-MiniLM-L6-v2` (384 dimensions).
L'agent doit utiliser le MEME modele pour encoder les questions.

**Chunking** : 500 caracteres sans overlap. Un element long produit
plusieurs chunks (`_part0`, `_part1`, ...).

### 4.2 NebulaGraph — Space `rag_space`

**Tags (types de noeuds)** :

| Tag            | Proprietes                                      |
|----------------|-------------------------------------------------|
| Document       | filename: string, type_file: string             |
| SectionHeader  | label: string, page_no: int, text: string, minio_url: string |
| Paragraph      | label: string, page_no: int, text: string, minio_url: string |
| Table          | label: string, page_no: int, text: string, minio_url: string |
| Picture        | label: string, page_no: int, text: string, minio_url: string |
| ListItem       | label: string, page_no: int, text: string, minio_url: string |
| Caption        | label: string, page_no: int, text: string, minio_url: string |
| Code           | label: string, page_no: int, text: string, minio_url: string |
| Formula        | label: string, page_no: int, text: string, minio_url: string |
| Footnote       | label: string, page_no: int, text: string, minio_url: string |
| PageHeader     | label: string, page_no: int, text: string, minio_url: string |
| PageFooter     | label: string, page_no: int, text: string, minio_url: string |

**Edges (relations)** :

| Edge       | Proprietes      | Description                                |
|------------|------------------|--------------------------------------------|
| PARENT_OF  | sequence: int    | Document -> SectionHeader -> Elements      |
| LINKED_TO  | relation: string | Caption -> Picture/Table ("describes")     |

**VID format** : `FIXED_STRING(64)`
- Document : `doc_{filename}`
- Elements : hash sha256[:10] (ex: `a950b65a3b`)

**Requetes utiles pour l'agent** :

```ngql
-- Trouver les parents d'un element (remonter la hierarchie)
GO FROM "element_id" OVER PARENT_OF REVERSELY YIELD dst(edge) AS parent;

-- Trouver les enfants d'une section (reconstruire le contexte)
GO FROM "section_id" OVER PARENT_OF
YIELD dst(edge) AS child, properties(edge).sequence AS seq
| ORDER BY $-.seq;

-- Trouver le document d'un element
GO FROM "element_id" OVER PARENT_OF REVERSELY
YIELD dst(edge) AS p
| GO FROM $-.p OVER PARENT_OF REVERSELY
YIELD dst(edge) AS doc;

-- Trouver les images liees a un element
GO FROM "element_id" OVER LINKED_TO
YIELD dst(edge) AS linked, properties(edge).relation AS rel;
```

### 4.3 MinIO — Bucket `documents`

| Champ         | Description                                        |
|---------------|----------------------------------------------------|
| Endpoint      | `minio:9000` (interne) ou via override              |
| Bucket        | `documents`                                         |
| Object path   | `images/{filename_stem}/{element_id}_{type}.png`    |
| Content-Type  | `image/png`                                         |
| Acces         | Via SDK MinIO (S3-compatible), credentials dans .env |

### 4.4 Schemas Pydantic (reutilisables)

Les modeles de `src/pipeline/schemas.py` dans le projet d'ingestion :

```python
class BoundingBox(BaseModel):
    left: float = Field(alias="l")
    top: float = Field(alias="t")
    right: float = Field(alias="r")
    bottom: float = Field(alias="b")

class DocumentElement(BaseModel):
    id: str                        # hash sha256[:10]
    label: str                     # section_header, text, picture, table, ...
    page_no: int = 1
    bbox: BoundingBox | None = None
    text: str = ""
    order: int = 0
    minio_url: str | None = None
    content: str | None = None
    reference_id: str = "DOC"      # ID du parent
    page_position: int = 0
    ref_position: int = 0
    type: str = "text"             # "text" ou "resource"

class DocumentMetadata(BaseModel):
    filename: str
    type_file: str
    total_pages: int = 0

class ExtractedDocument(BaseModel):
    metadata: DocumentMetadata
    elements: list[DocumentElement]
```

L'agent peut copier ces schemas ou les importer comme dependance.

---

## 5. Stack technologique recommandee

| Composant        | Choix                   | Raison                                          |
|------------------|-------------------------|-------------------------------------------------|
| Framework agent  | **LangGraph**           | Machine a etats, tools natifs, debug avec LangSmith |
| LLM principal    | **Claude Sonnet/Opus**  | Long context (200K), multimodal natif, tool-use |
| LLM fallback     | **GPT-4o**              | Alternative si besoin                           |
| Embedding query  | **all-MiniLM-L6-v2**   | Obligatoire : meme modele que l'ingestion       |
| Reranking        | **cross-encoder/ms-marco-MiniLM-L6-v2** | Local, pas de cout API, bon compromis |
| Frontend         | **Streamlit** ou **Gradio** | Prototypage rapide, selection interactive    |
| API backend      | **FastAPI**             | Meme stack que le service Docling               |
| Observabilite    | **Langfuse**            | Open-source, self-hostable en Docker            |
| Guardrails       | **NeMo Guardrails**     | Validation input/output, anti-hallucination     |
| PII detection    | **Presidio**            | Detection/anonymisation d'informations personnelles |

### Pourquoi LangGraph plutot que LangChain classique

L'agentic loop (le modele qui re-cherche) est un **workflow a etats** :
- Etat initial -> Retrieval -> Attente selection user -> Reconstruction ->
  Generation -> (boucle si besoin) -> Reponse finale

LangGraph modelise ca naturellement comme un graphe d'etats avec des
transitions conditionnelles. LangChain classique (chains) ne gere pas
bien les boucles ni le human-in-the-loop.

---

## 6. Architecture projet agent-llm-rag

```
agent-llm-rag/
    docker-compose.yml        # Langfuse + agent API + Streamlit
    .env.example
    requirements.txt
    src/
        agent/
            __init__.py
            graph.py           # LangGraph state machine (noeud central)
            state.py           # AgentState dataclass
            retriever.py       # ChromaDB query + reranking
            graph_context.py   # Reconstruction via NebulaGraph
            minio_client.py    # Recuperation images MinIO
            llm.py             # Client LLM (Claude/GPT)
            tools.py           # Tool search_vectors pour l'agentic loop
            guardrails.py      # Validation input/output
            settings.py        # pydantic-settings
        api/
            __init__.py
            main.py            # FastAPI endpoints
            schemas.py         # Request/Response models
        frontend/
            app.py             # Streamlit UI
        prompts/
            system.txt
            answer_with_context.j2
            rewrite_query.j2
    tests/
    documentation/
```

---

## 7. LangGraph State Machine

```python
from langgraph.graph import StateGraph, END

class AgentState(TypedDict):
    question: str
    chat_history: list[dict]
    retrieved_chunks: list[ChunkResult]
    reranked_chunks: list[ChunkResult]
    selected_sources: list[str]           # element_ids apres selection user
    enriched_context: list[SectionContext] # sections reconstruites
    response: str
    citations: list[Citation]
    images: list[ImageRef]
    search_count: int                     # compteur agentic loop (max 3)
    needs_more_info: bool

graph = StateGraph(AgentState)

graph.add_node("retrieve", retrieve_chunks)
graph.add_node("rerank", rerank_chunks)
graph.add_node("await_source_selection", present_sources_to_user)
graph.add_node("reconstruct_context", reconstruct_via_graph)
graph.add_node("generate", generate_response)
graph.add_node("postprocess", extract_citations_and_images)

graph.add_edge("retrieve", "rerank")
graph.add_edge("rerank", "await_source_selection")
graph.add_edge("await_source_selection", "reconstruct_context")
graph.add_edge("reconstruct_context", "generate")
graph.add_edge("generate", "postprocess")

# Agentic loop : si le modele veut plus d'info ET < 3 iterations
graph.add_conditional_edges("postprocess", should_search_more, {
    True: "retrieve",    # re-chercher avec la sous-question du modele
    False: END,
})

graph.set_entry_point("retrieve")
agent = graph.compile(interrupt_before=["await_source_selection"])
```

---

## 8. Connexion aux stores (acces reseau)

L'agent doit acceder aux 3 stores de donnees. Deux options :

**Option A — Meme reseau Docker** (recommande pour le dev)
L'agent tourne sur `rag_network` et accede directement :
- ChromaDB : `http://chromadb:8000`
- NebulaGraph : `graphd:9669`
- MinIO : `minio:9000`

**Option B — Acces externe** (prod ou projet separe)
Exposer les ports via `docker-compose.override.yml` du projet d'ingestion :
- ChromaDB : `http://localhost:8080`
- NebulaGraph : `localhost:9669`
- MinIO : `localhost:9000`

Les credentials sont les memes que dans `.env` du projet d'ingestion.

---

## 9. Variables d'environnement de l'agent

```env
# --- Stores (du projet d'ingestion) ---
CHROMA_HOST=chromadb
CHROMA_PORT=8000
NEBULA_HOST=graphd
NEBULA_PORT=9669
NEBULA_USER=root
NEBULA_PASSWORD=nebula
MINIO_ENDPOINT=minio:9000
MINIO_ROOT_USER=admin
MINIO_ROOT_PASSWORD=            # meme que le projet d'ingestion
MINIO_BUCKET=documents

# --- LLM ---
ANTHROPIC_API_KEY=              # ou OPENAI_API_KEY
LLM_MODEL=claude-sonnet-4-20250514
LLM_TEMPERATURE=0.1
LLM_MAX_TOKENS=4096

# --- Retrieval ---
EMBEDDING_MODEL_NAME=all-MiniLM-L6-v2   # DOIT etre le meme que l'ingestion
RERANK_MODEL=cross-encoder/ms-marco-MiniLM-L6-v2
RETRIEVAL_TOP_K=20
RERANK_TOP_K=10
MAX_SEARCH_ITERATIONS=3
CONTEXT_DEPTH=1                  # profondeur de reconstruction graphe

# --- Observabilite ---
LANGFUSE_HOST=http://langfuse:3000
LANGFUSE_PUBLIC_KEY=
LANGFUSE_SECRET_KEY=
```

---

## 10. Plan d'implementation par phases

### Phase 1 — Retrieval basique + UI (2-3 jours)
- Setup projet, settings, ChromaDB client
- Retrieval simple (query -> top-K chunks)
- Frontend Streamlit : input question, affichage resultats
- Pas de reranking, pas de graphe

### Phase 2 — Reranking + selection sources (2 jours)
- Integrer cross-encoder pour le reranking
- UI : affichage groupe par document, checkboxes de selection
- API FastAPI pour le backend

### Phase 3 — Graph Context Reconstruction (3-4 jours)
- Client NebulaGraph (nebula3-python)
- Algorithme de remontee PARENT_OF -> section_header
- Algorithme de descente -> enfants de la section
- Recuperation images MinIO
- Assemblage du contexte enrichi en markdown structure

### Phase 4 — LLM Generation (2 jours)
- Integration Claude via Anthropic SDK
- Prompt systeme avec instructions de citation
- Injection du contexte enrichi (texte + images multimodal)
- Streaming de la reponse

### Phase 5 — Agentic Loop + LangGraph (3 jours)
- Modeliser le flux complet en LangGraph
- Tool `search_vectors` pour la recherche iterative
- Human-in-the-loop pour la selection sources (interrupt)
- Garde-fous : max iterations, budget tokens

### Phase 6 — Post-processing + Guardrails (2 jours)
- Extraction automatique des citations
- Attachement des images dans la reponse
- Integration NeMo Guardrails ou Presidio
- Multi-turn (historique de conversation)

### Phase 7 — Observabilite + Evaluation (2 jours)
- Deploy Langfuse en Docker
- Tracer chaque requete (retrieval, generation, latence, tokens)
- Evaluer avec Ragas sur le jeu golden (voir `rag_evaluation_strategy.md`)

---

## 11. Risques et mitigations

| Risque                                    | Impact | Mitigation                              |
|-------------------------------------------|--------|-----------------------------------------|
| Contexte trop large (section entiere)     | Tokens | Budget max par section, truncation       |
| Boucle infinie de recherche               | Cout   | Max 3 iterations, budget tokens global   |
| Latence NebulaGraph sur graphes larges    | UX     | Cache des reconstructions recentes       |
| Images trop lourdes en base64             | Tokens | Redimensionner avant injection (max 1MB) |
| Modele d'embedding different query/index  | Qualite| Forcer all-MiniLM-L6-v2 dans les settings|
| Utilisateur deselectionne toutes sources  | UX     | Minimum 1 source requise pour generer    |
