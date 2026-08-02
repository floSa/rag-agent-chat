# Axes d'amélioration — rag-agent-chat

Document remis à plat le 2 août 2026. La version précédente cochait « corrigé »
des correctifs absents du code (`_window_around`, `RERANK_MIN_SCORE`,
`section_header_text`, alias `[src:N]`) et listait comme ouvert `tools.py`,
supprimé depuis. Un document d'audit faux est pire que pas de document : chaque
ligne ci-dessous est vérifiable dans le code ou contre les services.

---

## 1. Corrigé

### 1.1 La remontée `PARENT_OF` ne remontait rien — `graph_context.py`

Sous `REVERSELY`, nGQL fait renvoyer par `dst(edge)` le nœud de **départ**, pas
le voisin atteint : c'est `src(edge)` qui porte le parent. `_find_parent`
retournait donc l'élément lui-même, la boucle de remontée tournait dix fois sur
place, et `reconstruct_section` rendait une section vide.

La reconstruction du contexte par le graphe — la promesse centrale du projet —
était sans effet depuis l'origine. Vérifié contre le graphe en production :

```
MATCH (p)-[:PARENT_OF]->(c) WHERE id(c)=="1730443c8f"  -> "ffa6bda17d"
GO FROM "1730443c8f" ... REVERSELY YIELD dst(edge)     -> "1730443c8f"
GO FROM "1730443c8f" ... REVERSELY YIELD src(edge)     -> "ffa6bda17d"
```

### 1.2 Les citations perdaient le nom du document — `graph_context.py`, `graph.py`

La remontée s'arrêtait au premier `SectionHeader`. Comme l'ingestion rattache
tout élément à son en-tête et tout en-tête au `Document`, elle s'arrêtait donc
systématiquement au premier saut : le nœud `Document` n'était jamais atteint, et
`node_postprocess` — qui y cherchait le nom du fichier — laissait `filename`
vide. Toutes les citations issues du graphe s'affichaient `****, p.42`.

La remontée note désormais la section puis poursuit jusqu'à la racine.
`SectionContext` expose `filename` et `section_title` au lieu de laisser ses
appelants les deviner depuis les breadcrumbs.

### 1.3 VIDs de documents rejetés — `graph_context.py`

Les VIDs de documents dérivent du chemin (`doc_htms/Practical MLOps/4. …`) :
séparateurs, espaces, accents, jusqu'à 256 octets. Le motif de validation les
rejetait tous, ce qui vidait les propriétés du nœud `Document`.

Ils ne viennent jamais de l'utilisateur — ils sont découverts en remontant le
graphe : ils sont **échappés** plutôt que filtrés. La validation stricte reste
sur le seul format qu'un appelant peut fournir, le hash de 10 hexadécimaux.

### 1.4 Contexte non borné — `graph_context.py`, `llm.py`

Deux causes cumulées, désormais traitées :

- `_get_children` renvoyait tous les enfants. Un document sans `SectionHeader`
  rattache ses éléments au nœud `Document` : la « section » reconstruite était
  le document entier. `_window_around` borne à `CONTEXT_WINDOW_BEFORE/AFTER`
  éléments autour de l'ancre.
- `num_ctx` n'était jamais passé à Ollama : la fenêtre dépendait du serveur
  (8192 embarqué, 32768 central), et le même prompt donnait deux comportements.
  Elle est explicite, et `fit_contexts` écarte les sources qui dépassent le
  budget, avec un log qui dit combien et pourquoi.

Mesuré sur une question réelle : 5 sections reconstruites font 13 961
caractères pour un budget de 12 544 — une source écartée explicitement, là où
Ollama en tronquait le **début** en silence.

### 1.5 Éléments multi-chunks — `retriever.py`, `frontend/app.py`

Un bloc long produit des chunks `abc#0`, `abc#1` partageant leur `element_id`.
Ils se ressemblent, donc le reranker les remontait ensemble : plusieurs places
du top-K pour un seul passage, et deux `st.checkbox` de même `key` — soit une
`StreamlitDuplicateElementKey`. `dedupe_by_element` s'applique **avant** la
troncature au top-K.

### 1.6 Documents homonymes fusionnés — `schemas.py`, `retriever.py`

`ChunkResult` ignorait `collection`, `source_path` et `section_title`, pourtant
écrits par l'ingestion. Le groupement se faisait sur le seul nom de fichier :
la « Préface » de deux ouvrages devenait un seul document. Le groupement porte
sur `source_path`, et l'UI affiche « Ouvrage › Chapitre ».

### 1.7 Scores de rerank affichés comme des probabilités — `retriever.py`, `frontend/app.py`

`ms-marco-MiniLM-L6-v2` sort des logits non bornés. Le frontend appliquait des
seuils à 0.5 / 0.2 : une source pertinente à −2.0 ressortait en rouge et
repliée. Le champ `relevance` porte la sigmoïde du logit, affichée en
pourcentage.

### 1.8 Sessions LangGraph sans purge — `api/main.py`

Le checkpointer en mémoire ne purge rien : chaque question laissait ses chunks,
ses embeddings et ses contextes reconstruits jusqu'au redémarrage. Un registre
borne les sessions en âge (`SESSION_TTL_SECONDS`) et en nombre
(`MAX_LIVE_SESSIONS`).

### 1.9 « Avant / après » — `graph_context.py`

`reconstruct_section` ne récupérait que la section de l'élément. Les en-têtes
étant frères sous le `Document` et ordonnés par la propriété `sequence` de
l'arête, `_find_sibling` atteint la section précédente et la suivante : leur
queue et leur tête entrent dans le prompt, dans des blocs explicitement
étiquetés pour que le LLM les distingue de la section trouvée.

### 1.10 Légendes des illustrations — `graph_context.py`

L'ingestion relie chaque `Caption` à l'illustration qui la précède par une arête
`DESCRIBES`. L'agent ne la traversait jamais : le LLM recevait un `[img:ID]`
muet et devait juger seul de sa pertinence. La légende est désormais rattachée
au visuel dans le markdown.

### 1.11 `CONTEXT_DEPTH` sans effet — `settings.py`

Le paramètre était lu nulle part, et ne pouvait rien faire : l'ingestion
n'imbrique pas les titres, il n'y a aucun niveau à remonter (§3.1). Supprimé et
remplacé par les bornes de fenêtrage, qui décrivent ce qui est réellement
réglable.

### 1.12 Tests de la logique métier — `tests/unit/`

38 tests s'ajoutent aux 21 existants : résolution des citations et des images,
échappement des VIDs, fenêtrage, budget de contexte, déduplication.

---

## 1bis. Corrigé — qualité du retrieval et mesure

| Sujet | Ce qui a été fait |
|---|---|
| Modèles multilingues | Embedder et reranker alignés sur la réingestion. Mesuré : le reranker anglais rendait une étendue de scores de 0,0 % sur une question française — un classement au hasard. |
| Réécriture de requête | `node_rewrite` rend la question de suivi autonome avant l'encodage. Sans historique, aucun appel au LLM. |
| Recherche hybride | BM25 + dense fusionnés par RRF. La fusion porte sur les **rangs**, pas sur les scores : une distance cosine et un score BM25 ne sont pas comparables. |
| Texte intégral | Relu dans l'index quand le texte du graphe frôle la troncature à 2000 caractères. Les fenêtres recouvrantes sont recollées sans répéter la charnière. |
| Tool-calling natif | `search_vectors` déclaré comme outil Ollama ; le regex sur la prose reste en second rideau. |
| Endpoint `/answer` | Non interactif, expose les passages soumis au LLM et les temps par étage. C'est lui que consomme la campagne. |
| Résilience | Réouverture des clients Chroma / Nebula / MinIO après redémarrage d'un store, timeout nGQL, sessions persistées sur disque. |
| Serveur d'inférence | L'Ollama embarqué disparaît du compose : un seul serveur, celui de `llm-service`. |
| Mesure | `scripts/evaluate.py` + jeu doré : rappel, complétude des citations, abstention, latence — sans juge LLM, donc déterministe. `make eval` compare à la campagne de référence. |

---

## 2. Ouvert — agent

| Priorité | Sujet | Détail |
|---|---|---|
| P1 | Rappel annoté à l'élément | Le jeu doré n'annote qu'au **document** : un chapitre entier compte comme un succès. Cette granularité ne peut pas départager deux configurations de retrieval. Annoter les `gold_element_ids` est le seul moyen de trancher, et le seul travail non automatisable. |
| P1 | Jeu doré trop petit | 15 questions. Sur cet effectif, un écart d'un dixième est du bruit. Viser 100 à 150, stratifiées par type et par langue. |
| P2 | Branchement sur RAG-Eval-Bench | Le banc apporte les juges calibrés, la comparaison appariée et les intervalles de confiance. Il lui manque un `ExternalPipeline` qui poste sur `/answer`. |
| P2 | Latence de génération | 11 s en médiane contre 0,4 s de retrieval. Le levier est le LLM — quantisation, `num_predict`, ou un modèle plus petit — pas la recherche. |
| P2 | Index BM25 en mémoire | Construit au premier appel : la première requête après un démarrage paie ~10 s. Un corpus nettement plus gros demanderait un moteur dédié plutôt qu'un index Python. |
| P3 | Surface exposée | CORS `*` et `/media/{object_name}` sans authentification : quiconque atteint l'API lit tout le bucket. Acceptable en local, bloquant dès qu'on expose. |
| P3 | Multi-workers | Les sessions sont persistées, mais l'index BM25 et les modèles sont chargés par processus : N workers = N copies en mémoire. |

---

## 3. Ouvert — dépend de l'ingestion

À transmettre à `rag-ingestion-pipeline` ; rien n'est faisable côté agent.

### 3.1 Le graphe est plat

Mesuré sur le graphe en production : **901** `SectionHeader` enfants d'un
`Document`, **0** enfant d'un autre `SectionHeader`, et **0** chemin de
longueur 3 depuis le `Document`. L'arbre fait exactement deux niveaux.

En cause, `elements.py` : `reference_id = ROOT_REFERENCE` dès qu'un en-tête est
rencontré. Docling expose pourtant le niveau des titres, que `TAG_MAP` écrase.

Conséquence : le breadcrumb ne peut afficher qu'un seul titre — pas de
`Chapitre 3 > 3.2 > 3.2.1`. Le « avant / après » n'en dépend pas (§1.9).

Correction : stocker le niveau du titre sur le tag `SectionHeader` et chaîner
les parents. **Impose une purge du space** — le schéma Nebula n'évolue pas en
place.

### 3.2 Modèle d'embedding monolingue

`all-MiniLM-L6-v2` est un modèle anglais, tronqué à 256 tokens, utilisé sur un
corpus et des questions en partie francophones. C'est l'écart le plus coûteux à
l'état de l'art. Le modèle est décidé à l'ingestion et doit coïncider des deux
côtés : en changer (`bge-m3`, `multilingual-e5-large`) **impose une réingestion
complète**.

### 3.3 Illustrations sans légende

L'arête `DESCRIBES` couvre les visuels légendés dans le document d'origine. Une
figure sans légende reste muette : introuvable par la recherche sémantique, et
impossible à juger pertinente par le LLM. Une description générée par VLM à
l'ingestion, indexée dans ChromaDB, comblerait ce trou.
