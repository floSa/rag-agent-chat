# Axes d'amélioration — rag-agent-chat

Document basé sur une revue complète du code source. Chaque point est ancré dans un fichier et une ligne précise.

---

## 1. Bugs avérés

### 1.1 Images jamais résolues dans `node_postprocess`

**Fichier** : `src/agent/graph.py` — `node_postprocess` (ligne ~110)

Le LLM génère des références `[img:ELEMENT_ID]` à partir des éléments Picture/Table reconstruits par NebulaGraph. Mais la résolution des URLs présignées s'appuie sur `chunks_map`, qui ne contient que les chunks ChromaDB reranqués :

```python
chunks_map = {c.element_id: c for c in state.get("reranked_chunks", [])}

for match in re.finditer(r"\[img:([a-f0-9]+)\]", response):
    eid = match.group(1)
    chunk = chunks_map.get(eid)          # ← presque toujours None pour les images
    if chunk and chunk.minio_url and ...:
        images.append(...)
```

Les images viennent des enfants de section reconstruits par NebulaGraph (via `_build_markdown`), pas des chunks ChromaDB. `chunks_map.get(eid)` retourne `None` dans la quasi-totalité des cas : les images ne sont jamais affichées dans le frontend.

**Correction** : construire `images_map` depuis `enriched_contexts` (éléments avec `minio_url`) en plus de `chunks_map`.

```python
images_map: dict[str, str] = {}
for ctx in state.get("enriched_contexts", []):
    for elem in ctx.elements:
        if elem.minio_url:
            images_map[elem.node_id] = elem.minio_url
```

---

### 1.2 ~~Modèle Ollama inexistant dans `.env.example`~~ — invalidé

`gemma4:e4b` est un modèle valide disponible sur ollama.com. Ce point était incorrect.

---

### 1.3 Checkbox "Tout désélectionner" inopérante dans le frontend

**Fichier** : `src/frontend/app.py` — lignes 120–131

La case "Tout sélectionner (doc)" ne déselectionne rien quand on la décoche :

```python
if doc_checked:
    for c in chunks:
        selected.add(c["element_id"])
else:
    # Ne désélectionner que si c'était coché avant
    pass     # ← branche vide, bug connu
```

**Correction** :

```python
for c in chunks:
    if doc_checked:
        selected.add(c["element_id"])
    else:
        selected.discard(c["element_id"])
```

---

### 1.4 `CONTEXT_DEPTH` jamais utilisé

**Fichier** : `src/agent/settings.py` ligne 43 / `src/agent/graph_context.py`

`context_depth: int = Field(default=1, alias="CONTEXT_DEPTH")` est défini dans `Settings` mais `_climb_to_section` ne consulte jamais `settings.context_depth`. La profondeur de remontée est toujours contrôlée par `_MAX_DEPTH = 10` et l'arrêt sur le premier `SectionHeader`.

Ce paramètre expose une option de configuration qui n'a aucun effet, ce qui est trompeur.

**Correction** : soit implémenter la logique (remonter N niveaux de sections), soit supprimer le paramètre.

---

### 1.5 `SourceSelectionRequest.question` ignoré

**Fichier** : `src/api/main.py` — `chat_resume`, `src/api/schemas.py`

Le champ `question` de `SourceSelectionRequest` est envoyé par le frontend mais jamais utilisé dans `chat_resume` : la question est déjà dans l'état checkpointé. Ce champ crée une fausse impression de contrat d'interface.

**Correction** : supprimer `question` de `SourceSelectionRequest`.

---

## 2. Architecture — code mort et incohérences

### 2.1 `tools.py` est du code mort

**Fichier** : `src/agent/tools.py`

`search_vectors` est défini comme un `@tool` LangChain et `AGENT_TOOLS = [search_vectors]` est exporté, mais ce module n'est importé nulle part dans `graph.py` ou `llm.py`. Le LLM n'est jamais configuré avec ces outils.

La boucle agentique réelle fonctionne par **parsing regex** de la réponse du LLM (`re.search(r"search_vectors\([\"'](.+?)[\"']\)")`), pas par tool-calling natif. Les deux approches coexistent sans qu'aucune soit complète :

| Approche | Fichier | État |
|----------|---------|------|
| Tool-calling LangChain (`@tool`) | `tools.py` | Défini, jamais lié au LLM |
| Regex sur la réponse texte | `graph.py` L95 | Actif mais fragile |

La voie regex est fragile (le LLM doit produire exactement `search_vectors("...")` en texte) et contourne la gestion native des outils de LangGraph/LangChain.

**Correction** : soit lier les outils via `llm.bind_tools(AGENT_TOOLS)` et passer par `tool_calls` dans la réponse, soit supprimer `tools.py` et assumer l'approche regex en la documentant.

---

### 2.2 Nœud `await_source_selection` vide

**Fichier** : `src/agent/graph.py` — lignes 39–52

Ce nœud existe uniquement comme point d'interruption (grace au paramètre `interrupt_before` à la compilation). La logique `group_by_document` qu'il contient est dupliquée dans `chat_start` (main.py) pour extraire les groupes à retourner au client.

```python
def node_await_source_selection(state: AgentState) -> dict:
    groups = group_by_document(state["reranked_chunks"])  # calculé mais non retourné
    logger.info(...)
    return {}
```

Les groupes calculés ici ne servent à rien — ils sont recalculés dans `/chat/start` via `aget_state`.

**Correction** : supprimer l'appel à `group_by_document` dans ce nœud.

---

## 3. Performances

### 3.1 `_get_node_properties` : jusqu'à 12 requêtes nGQL par nœud

**Fichier** : `src/agent/graph_context.py` — lignes 63–89

Pour déterminer le tag d'un nœud, la fonction itère sur 12 tags possibles et exécute une requête `FETCH PROP ON <tag>` pour chacun jusqu'à trouver le bon :

```python
tags = ["SectionHeader", "Paragraph", "Table", "Picture", "Code",
        "Formula", "Caption", "ListItem", "Footnote", "PageHeader",
        "PageFooter", "Document"]
for tag in tags:
    rows = _execute(f'FETCH PROP ON {tag} "{node_id}" ...')  # requête réseau
    if rows and row.get("text") is not None:
        return row
```

Pour un appel `reconstruct_section` complet (remontée + enfants), cela représente potentiellement **plusieurs dizaines de sessions NebulaGraph** ouvertes/fermées séquentiellement.

**Correction** : NebulaGraph supporte `FETCH PROP ON * "<vid>"` qui retourne les propriétés de tous les tags d'un vertex en une seule requête. À utiliser en priorité, avec fallback sur la boucle uniquement si `ON *` n'est pas disponible.

---

### 3.2 Absence de gestion de la fenêtre de contexte

**Fichier** : `src/agent/graph_context.py` — `_get_children` / `src/agent/llm.py`

Pour un document sans `SectionHeader` (ex. `statisticsfordatascience.pdf`), l'élément sélectionné est un enfant direct du nœud `Document`. `_get_children(document_id)` retourne alors **tous les éléments du document** (6030 éléments dans les tests), qui sont assemblés en un seul bloc markdown et transmis au LLM.

`gemma3:4b` a une fenêtre de contexte de 8192 tokens. Un tel contexte dépasse largement cette limite sans avertissement ni erreur explicite — Ollama tronque silencieusement.

**Corrections possibles** :
- Limiter `_get_children` à N éléments autour de l'`element_id` ciblé (fenêtre glissante par `sequence`).
- Compter les tokens avant envoi (`tiktoken` ou estimation par caractères) et tronquer si nécessaire.
- Détecter le cas "enfant direct de Document" et appliquer une stratégie différente.

---

### 3.3 ~~Reranking synchrone bloquant~~ ✅ Corrigé

`node_retrieve` et `node_rerank` sont maintenant des fonctions `async` qui délèguent l'appel CPU à un thread pool via `asyncio.get_running_loop().run_in_executor`. L'endpoint `/sources` utilise `run_in_threadpool` de Starlette pour le même effet. L'event loop reste libre pendant l'exécution du cross-encoder et de l'embedding.

---

## 4. Résilience et connexions

### 4.1 `lru_cache` sur les clients de services — pas de reconnexion

**Fichiers** : `src/agent/retriever.py` (L15–28), `src/agent/graph_context.py` (L20–27), `src/agent/minio_client.py` (L11–19)

Les clients ChromaDB, NebulaGraph et MinIO sont mis en cache via `@lru_cache(maxsize=1)`. Si un service redémarre, les clients cachés pointent vers des connexions mortes. Les requêtes suivantes lèvent des exceptions et il n'y a pas de logique de re-initialisation du cache.

**Conséquence concrète** : si ChromaDB redémarre (mis à jour, OOM, etc.) pendant que `agent-api` tourne, toutes les requêtes de retrieval échouent jusqu'au redémarrage d'`agent-api`.

**Correction** : ajouter une gestion d'erreur avec retry + invalidation du cache (`_get_chroma_collection.cache_clear()`), ou remplacer `lru_cache` par un pattern singleton avec reconnexion.

---

### 4.2 Sessions NebulaGraph non libérées en cas d'exception

**Fichier** : `src/agent/graph_context.py` — `_execute` (ligne 30)

```python
session = pool.get_session(...)
try:
    ...
finally:
    session.release()
```

Le `finally` protège la libération, mais si `pool.get_session()` lève une exception (pool épuisé, connexion refusée), `session` n'est pas définie et le `finally` lèvera une `NameError`. La session du pool est alors perdue.

**Correction** :

```python
session = pool.get_session(...)  # peut lever
try:
    ...
finally:
    session.release()
```

Ou mieux, utiliser un context manager si la librairie `nebula3` en propose un.

---

### 4.3 Pas de timeout sur les requêtes NebulaGraph

**Fichier** : `src/agent/graph_context.py`

`session.execute(nql)` n'a pas de timeout configuré. Si NebulaGraph est lent ou bloqué sur une requête coûteuse, la requête FastAPI correspondante attend indéfiniment (jusqu'au timeout httpx du frontend à 120s).

---

## 5. Tests

### 5.1 Aucun test pour le postprocessing des citations/images

**Fichier** : `tests/unit/`

`node_postprocess` (graph.py) extrait les citations et images de la réponse LLM via regex. Ce code n'est pas testé alors qu'il contient la logique métier des citations (format `[src:ID]`, déduplication) et le bug images décrit en §1.1.

### 5.2 Aucun test pour la boucle agentique

La détection `search_vectors("...")` dans `node_generate` et la condition `should_search_more` ne sont pas testées unitairement.

### 5.3 Aucun test pour `tools.py`

`search_vectors` comme outil LangChain n'est pas testé (et comme montré en §2.1, n'est pas utilisé non plus).

### 5.4 Absence de tests d'intégration

Aucun test dans `tests/integration/`. Les flux end-to-end (start → resume, simple) ne sont vérifiés que manuellement.

---

## 6. Configuration

### 6.1 `.env.example`

`gemma4:e4b` est un modèle valide sur ollama.com — ce point était incorrect. `MINIO_ROOT_USER` doit correspondre à la valeur configurée dans `rag-ingestion-pipeline` (pas de valeur universelle). La variable `RERANK_MIN_SCORE=0.0` a été ajoutée.

---

## Récapitulatif par priorité

| Priorité | Item | État | Impact |
|----------|------|------|--------|
| P0 | §1.1 Images jamais affichées | ✅ Corrigé | Fonctionnalité cassée silencieusement |
| P0 | §1.3 Checkbox désélection | ✅ Corrigé | Bug UX visible |
| P1 | §3.2 Contexte LLM non borné | ✅ Corrigé (`_window_around`, max 12 éléments) | Silently broken sur docs sans sections |
| P1 | §3.1 `_get_node_properties` 12 requêtes → max 2 | ✅ Corrigé (`FETCH PROP ON *`) | Latence réelle |
| P1 | Filtrage par score (`RERANK_MIN_SCORE`) | ✅ Corrigé | Sources non pertinentes proposées |
| P1 | Affichage SectionHeader dans sélection sources | ✅ Corrigé (`section_header_text`) | UX — contexte illisible |
| P1 | Citations hex `[src:d89fb...] `→ alias `[src:N]` | ✅ Corrigé | Réponse illisible |
| P1 | §2.1 `tools.py` dead code / incohérence agentic | Ouvert | Clarté architecturale |
| P1 | §1.4 `CONTEXT_DEPTH` sans effet | Ouvert | Config trompeuse |
| P2 | §3.3 Retrieve/rerank hors event loop | ✅ Corrigé (`run_in_executor`) | Concurrence API |
| P2 | §4.1 Reconnexion services | Ouvert | Résilience en production |
| P3 | §5.x Tests unitaires postprocess + boucle | Ouvert | Maintenabilité |
| P3 | §4.3 Timeouts NebulaGraph | Ouvert | Robustesse |
