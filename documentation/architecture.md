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
téléchargés au premier démarrage), `rag_agent_state` (sessions LangGraph **et
base de capture d'usage** — deux fichiers SQLite dans le même volume).

`checkpoints.sqlite` porte une table de plus que celles de LangGraph :
`sessions_agent`, le registre de la purge. Elle vit là et pas ailleurs pour
qu'un fichier de sessions effacé emporte son registre avec lui — voir
« Purge durable des sessions » plus bas.

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
   historique puis sources bornés au budget de fenêtre avec un log, prompt
   estimé confronté au `prompt_eval_count` réel, tokens streamés en SSE.
7. **Post-processing** (`node_postprocess`) : citations `[src:ID]` résolues vers
   document, ouvrage, page et section ; images `[img:ID]` servies par `/media`.
8. **Boucle agentique** : si le modèle appelle l'outil `search_vectors`, une
   nouvelle passe recherche → rerank → reconstruction s'enchaîne sans
   re-sélection, contextes accumulés, dans la limite de `MAX_SEARCH_ITERATIONS`.

## Capture d'usage

`src/agent/usage.py` enregistre ce que le service sert : la question posée, le
classement proposé, les sources retenues ou décochées, la réponse, les latences
et l'appréciation. Détail du schéma et requêtes dans
[capture_usage.md](capture_usage.md), posture dans [SECURITY.md](SECURITY.md).

**Le branchement appartient à l'API, pas au graphe**, et ce n'est pas un détail
d'implémentation : c'est `/chat/start` qui sait ce qui a été **proposé** et
`/chat/resume` qui sait ce qui a été **retenu**. Aucun nœud du graphe ne voit
les deux. Un enregistrement couvre donc deux requêtes HTTP, jointes par
`thread_id` — inséré au start, complété au resume.

```
/chat/start  ──→ graphe (rewrite → retrieve → rerank) ──→ record_start      (1 ligne + N sources)
                                                              ↓ thread_id
/chat/resume ──→ graphe (reconstruct → generate → postprocess)
                 ──→ dernier événement SSE ──→ record_completion  (retenue, réponse, latences)
/answer      ──→ graphe complet ──→ record_start + record_completion  (endpoint = 'answer')
/feedback    ──→ record_feedback  (note binaire, commentaire libre)
```

Trois propriétés portées par le code, chacune pour une raison :

- **l'écriture de `/chat/resume` a lieu après le dernier événement SSE** — la
  diffusion est le chemin critique, et une écriture qui s'y glisse retarde une
  réponse déjà lente ;
- **aucun échec ne remonte** — base verrouillée, disque plein, schéma divergent :
  WARNING et on continue de servir. La capture est de l'observation, pas une
  fonctionnalité ;
- **le mode de journalisation SQLite est fixé au démarrage** (`usage.initialiser`
  appelé par le `lifespan`), jamais dans le chemin d'écriture : le changer exige
  un verrou exclusif qui ne respecte pas le délai d'attente, et faisait perdre
  des interactions simultanées.

## Purge durable des sessions

Le checkpointer ne purge rien de lui-même. Ce que l'API doit garantir, et ce
qu'un lecteur doit pouvoir attendre :

- **une session en attente de sélection survit au redémarrage de l'API.** C'est
  la raison d'être du fichier ; aucune purge n'a lieu au démarrage pour cette
  raison ;
- **une session périmée finit par disparaître du disque, même si personne ne
  l'a jamais vue vivante.** Le registre est sur disque, dans la base du
  checkpointer : il survit au redémarrage. Les sessions présentes dans
  `checkpoints` mais absentes du registre sont adoptées au démarrage — sans
  quoi rien ne pouvait plus les atteindre ;
- **ce que le journal annonce est ce qui a eu lieu.** La ligne de purge compte
  les suppressions abouties, pas les candidates. Un échec sort en WARNING avec
  sa trace, et `GET /health` publie `sessions.purged` et `sessions.failures` :
  la purge est vérifiable sans lire les logs.

Deux bornes la déclenchent, `SESSION_TTL_SECONDS` et `MAX_LIVE_SESSIONS`, et la
purge tourne au démarrage puis à chaque `POST /chat/start`. La session en cours
de création est épargnée : elle est inscrite avant que le graphe ne tourne, donc
son horodatage précède le « maintenant » de la purge qui suit.

L'horloge est celle du mur et non `time.monotonic` : c'est la seule qui survive
à un redémarrage. Un compteur qui repart à zéro n'est pas un âge.

## L'index lexical face à un corpus qui bouge

L'ingestion est un service **séparé** : elle écrit dans ChromaDB pendant que
l'agent tourne. La recherche dense le suit sans effort — la requête part à
Chroma à chaque fois — mais l'index BM25 vit en mémoire dans le processus de
l'agent. Ce qu'un lecteur doit attendre :

- **un document ingéré après le démarrage devient trouvable en lexical**, sans
  redémarrer l'agent. Deux mécanismes, et ils ne font pas double emploi :
  `POST /reindex`, que l'ingestion appelle en fin de pipeline — un contrat — et
  la comparaison de `collection.count()` au nombre de chunks indexés — un
  filet, qui ne voit pas un corpus dont on a retiré autant de chunks qu'on en a
  ajouté ;
- **la reconstruction n'est pas payée par une requête utilisateur.** Elle coûte
  le parcours du corpus entier (~9 s — chiffre **non mesuré**, réserve et protocole
  en [axes_amelioration.md](axes_amelioration.md) §2). Déclenchée par le filet, elle tourne dans
  un fil démon et l'index périmé continue de servir pendant ce temps ;
  déclenchée par `/reindex`, elle est payée par le pipeline qui appelle ;
- **`/health` ne déclare pas prêt un index périmé.** `index_lexical: false`
  couvre les deux états dégradés — pas encore construit, et construit sur un
  corpus disparu — parce qu'ils sont indistinguables pour l'utilisateur ;
- **la première construction, elle, est toujours payée par la première
  requête.** Ce n'est pas résolu, c'est arbitré : la déplacer au démarrage
  retarderait la mise en service d'autant.

Une seule construction a lieu même sous N requêtes concurrentes : la lecture du
corpus est passée en rappel à `LexicalIndex.ensure`, qui l'exécute sous son
verrou. Les endpoints de recherche étant des `def`, ils sont servis par le
threadpool, et N requêtes arrivant avant que l'index soit prêt en déclenchaient
N.

**Limite connue en multi-workers :** `POST /reindex` ne reconstruit que l'index
du processus qui reçoit la requête. Le contrat suppose aujourd'hui un worker
unique ; les autres attendent leur filet.

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
  tronque par le début, donc le message système puis les sources les mieux
  classées.
- **Le budget se calcule sur ce qui est réellement dans le prompt** — système,
  gabarit, historique, sources — et non sur les sources seules. Un forfait
  couvrait le reste ; il ignorait l'historique, et le prompt dépassait la fenêtre
  dès le troisième tour. Le prompt estimé est confronté au `prompt_eval_count`
  d'Ollama à chaque génération : une devinette instrumentée vaut mieux qu'une
  devinette.
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
- **Le registre de la purge est sur disque, dans la base du checkpointer.** En
  mémoire, il n'atteignait que les sessions créées par le processus courant : la
  purge ne supprimait rien de ce qui précédait le dernier redémarrage. Il n'est
  pas adossé à la base de capture d'usage, qui porte pourtant `thread_id` et
  `started_at` : celle-ci est désactivable par `USAGE_CAPTURE`, et la purge du
  checkpointer serait devenue conditionnelle à un réglage sans rapport.
- **L'invalidation de l'index lexical est un contrat, doublé d'un filet.**
  `POST /reindex` est ce que l'ingestion appelle ; la comparaison des comptes
  rattrape l'ingestion qui ne le fait pas. Une heuristique seule aurait un angle
  mort — autant de chunks retirés qu'ajoutés — et un contrat seul dépend d'un
  dépôt voisin.
- **Un journal n'affirme que ce qui a eu lieu.** Les compteurs publiés par
  `/health` comptent les actions abouties, pas tentées. La purge des sessions a
  passé la vie du projet à annoncer des suppressions qui échouaient, absorbées
  par un `logger.debug` invisible au niveau de journal par défaut.
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
- **La capture d'usage est branchée sur l'API, non sur le graphe**, et son
  drapeau est à vrai par défaut. Un drapeau à faux annulerait le dispositif :
  personne ne le basculera avant les premiers utilisateurs, et les premières
  semaines d'usage ne se rattrapent pas. L'exposition n'est pas nouvelle — le
  checkpointer persiste déjà l'état complet du graphe dans le même volume.

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
