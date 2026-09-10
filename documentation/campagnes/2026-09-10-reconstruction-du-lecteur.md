# Reconstruction du lecteur en service — 10 septembre 2026

**Ce document est le SITE CANONIQUE des chiffres du lot 8.** Chaque chiffre porte
sa commande, son heure UTC (`date -u` relevée avant chaque bloc) et son étiquette
— `mesuré` (sortie d'un programme), `calculé` (dérivé, dérivation écrite),
`cité` (recopié d'un autre site, nommé). Aucun `supposé`.

**Ce que ce lot est** : le premier du chantier à toucher un service en marche,
sur décision explicite de l'utilisateur. L'agent `rag-agent-api` faisait tourner
depuis le 3 septembre 2026 une image construite **avant** les lots 2 à 7 : le
garde du modèle d'embedding (lot 3) et le garde du reranker (lot 6) n'avaient
jamais exécuté une ligne en production — §4.42 du registre.

---

## 0. Où, et contre quoi

| | |
|---|---|
| arbre de travail | `/home/ubuntu/RAG/rag-agent-chat/.claude/worktrees/lot-8-rag-agent-deploy-45d55d`, branche `claude/lot-8-rag-agent-deploy-45d55d`, **repartie de la branche du lot 4** (`0cd1c48`, 0 en retard sur `main`) |
| `docker compose` | lancé **depuis le clone principal uniquement** (`--project-directory /home/ubuntu/RAG/rag-agent-chat`), pour le seul service `agent-api`, `main` = `origin/main` = `85b5a7a` dans le clone, arbre propre |
| environnement | monté par le §2.2 du mandat dans l'arbre du lot ; `UV_NO_SYNC=1` devant `make eval` — voir §5 |
| stores | ChromaDB `rag_documents`, **4 367** chunks, estampille `paraphrase-multilingual-MiniLM-L12-v2` ; NebulaGraph `rag_space` ; **aucune écriture** dans l'un ni l'autre |
| jeux | `tests/fixtures/golden_qa_generated.yaml` (138) et `tests/fixtures/jeu_de_questions_pipeline.yaml` (30), ancrages **130 / 130** et **44 / 44** revérifiés par `make verifier-les-ancrages` avant chacune des quatre campagnes (`mesuré`, 13:47 et 14:05 UTC, puis 14:13 et après) |

## 1. Les deux concordances, remesurées — c'est ce qui autorisait la reconstruction

Armer le garde du lot 3 rend **503** si le réglage du lecteur ne concorde pas
avec l'estampille de la collection. `mesuré` à **13:45 puis de nouveau à 14:12
UTC**, en lecture seule, depuis l'arbre du lot :

```
python : chromadb.HttpClient(host=<IP de rag-ingestion-pipeline-chromadb-1>, port=8000)
         .get_collection("rag_documents") → count, metadata["embedding_model"]
grep -E '^(EMBEDDING_MODEL_NAME|RERANK_MODEL)=' /home/ubuntu/RAG/rag-agent-chat/.env
```

| | `mesuré` |
|---|---|
| estampille de `rag_documents` | `paraphrase-multilingual-MiniLM-L12-v2`, 4 367 chunks |
| `EMBEDDING_MODEL_NAME` du `.env` du clone principal — celui que la nouvelle image lit | `paraphrase-multilingual-MiniLM-L12-v2` |
| **concordance 1** | ✅ identiques : le garde ne produira pas de 503 |
| `RERANK_MODEL` du `.env` | `cross-encoder/mmarco-mMiniLMv2-L12-H384-v1` |
| `_RERANKERS_MESURES` de `main` (`retriever.py`, identique à `main` dans l'arbre) | ce seul nom |
| **concordance 2** | ✅ au registre : `verdict_langue_du_reranker` rend `None`, aucun bruit neuf |

Les deux concordances du prompt du pilote sont **confirmées**, comme ses cinq
mesures sur le conteneur (§2).

## 2. L'état du service AVANT, remesuré à 13:44 UTC

```
docker inspect rag-agent-api --format '{{.Image}} {{.Created}}'
docker image inspect <id> --format '{{.Created}}'
docker exec rag-agent-api sh -c 'sha256sum src/agent/graph_context.py src/agent/retriever.py ; grep -c verifier_modele_embedding -r src/ ; grep -c verdict_langue_du_reranker -r src/'
git log --format=%h main -- <fichier> | … sha256sum   # pour dater le code embarqué
```

| | `mesuré` | le pilote disait |
|---|---|---|
| image | `946dc14c631a…`, construite le **3 septembre 2026 à 09:57:02 UTC** | idem ✅ |
| `graph_context.py` du conteneur | `a9457963…` = celui du commit **`8bc0485`** du 26 août 2026 (`calculé` : premier commit de `main` dont le fichier porte cette empreinte) | `a9457963…` ✅ |
| `retriever.py` du conteneur | `58ecbe7a…` = commit **`e2fcac2`** du 26 août 2026 | `58ecbe7a…` ✅ |
| `verifier_modele_embedding` dans le conteneur | **0** occurrence dans tout `src/` | 0 ✅ |
| `verdict_langue_du_reranker` | **0** | 0 ✅ |
| `/health` | HTTP 200, `status: ok`, quatre services `true`, `index_lexical: true`, 789 interactions | idem ✅ |
| conteneur | `Up 4 hours`, démarré à **09:20:10 UTC** ce jour, quand les autres conteneurs de l'hôte sont à `Up 5 hours` — un redémarrage propre à l'agent, cohérent avec la restauration du conteneur par le lot 4 consignée au §4.42 | — |

## 3. (a) L'ancien lecteur rejoue les deux références À L'UNITÉ

**Fait en premier, avant toute reconstruction** : une fois l'image remplacée,
l'occasion de mesurer ce que sept lots avaient changé en production disparaît.

```
date -u ; UV_NO_SYNC=1 make eval          # 13:47:21 → 14:05:49 UTC
date -u ; UV_NO_SYNC=1 make eval-controle # 14:05:49 → 14:10:26 UTC
mv runs/20260910-1347-reglage.json  runs/2026-09-10-ancien-lecteur-reglage.json
mv runs/20260910-1405-controle.json runs/2026-09-10-ancien-lecteur-controle.json
```

`make eval` `rc=0`, `make eval-controle` `rc=0` (`rc` du processus `make`, non
filtré). Les artefacts sont **versionnés** — `runs/README.md` les décrit.

| comparaison appariée (`comparer_apparie`, empreintes identiques) | 138 questions | 30 questions |
|---|---|---|
| `rappel_recherche`, `rappel_elements`, `rang_reciproque`, `rappel_documents`, `taux_contexte_utile`, `part_utile_caracteres`, `rappel_contexte` | **130 / 130 ex æquo**, Δ = 0, p = 1 | **26 / 26 ex æquo** |
| `taux_citation_complete` | 129 / 129 | 27 / 27 |
| `caracteres_retenus ↓`, `contextes_retenus ↓` | **138 / 138** | **30 / 30** |
| `contextes_ecartes_total` | 26 → 26 | 8 → 8 |
| `prompt_eval_count_p50` | 3 131 → 3 131 | 3 198 → 3 198 |

**Rien n'a bougé sous les antécédents du 8 septembre** : ni l'index, ni les
modèles, ni la recherche. Ne bougent que ce que le LLM produit
(`citations_par_reponse` 3,217 → 3,109 ; `reponse_caracteres_p50` 607 → 570 sur
138 ; 781 → 781 sur 30) et les latences.

**Les latences de ce rejeu ne valent rien, et je le dis contre moi** : pendant
`make eval`, j'ai lancé `make lint` puis `make test` (50 s de CPU) et huit
mutations sur le même hôte. Les colonnes `*_ms` de
`2026-09-10-ancien-lecteur-*.json` sont contaminées. Les métriques de rappel et
de contexte sont déterministes et ne le sont pas.

## 4. (b) La définition (C) derrière un réglage éteint

Décision de l'utilisateur, sur la campagne du lot 4 (§4.41, **cité** ici, site
canonique là-bas) : la remontée aux oncles n'est pas fusionnée comme
comportement. Le code survit derrière `NEIGHBOUR_SECTION_UNCLES`
(`settings.neighbour_section_uncles`), **faux par défaut**, et son prix est
écrit à son site dans `src/agent/settings.py`.

**La preuve que le réglage éteint rend le comportement de `main`** — elle est
comportementale, l'AST ne pouvant pas être identique :

1. **AST hors docstrings**, `calculé` (script : `ast.parse`, docstrings
   retirées, `ast.dump` par définition) entre `main:src/agent/graph_context.py`
   et l'arbre du lot : **deux définitions ajoutées** (`_last_header_descendant`,
   `_neighbour_section`), **zéro retirée**, **une modifiée** —
   `_neighbour_elements`, dont le seul diff est la substitution
   `_find_sibling(…)` → `_neighbour_section(…)` ; énoncés hors définitions
   identiques ;
2. **éteint, `_neighbour_section` rend pointwise ce que `_find_sibling` rend**
   — l'appel exact de `main` à ce site — et une reconstruction complète émet
   **exactement le même flux de requêtes nGQL**, dans le même ordre, et sert le
   même markdown que le site de `main` reconstitué (`_neighbour_section`
   remplacé par `_find_sibling`). Une remontée faite puis jetée y rougit (M3).

Gardé dans `tests/unit/test_section_voisine.py`,
`TestLeReglageEteintRendLeComportementDeMain` (quatre tests, six cas), témoin
inerte rejoué dans les **deux** positions. `mesuré` : sans la fixture qui
allume (C), **13 des 23** tests du lot 4 rougissent sous le défaut — c'est le
réglage qui décide.

## 5. Ce que ce lot a trouvé en chemin

- **`make eval` = `uv run …`, et `uv run` SYNCHRONISE l'environnement sur
  `uv.lock` avant de lancer.** `mesuré` (`uv sync --inexact --dry-run`) : il
  aurait rétrogradé `transformers` 5.17.0 → 5.14.1 et installé `triton`, donc le
  `torch` CUDA de PyPI, dans un `.venv` monté par le §2.2 avec le `torch` CPU.
  La recette a été lancée sous `UV_NO_SYNC=1`, vérifié avant : `torch
  2.14.0+cpu`, `transformers 5.17.0` inchangés. Ni le `Makefile` ni le mandat ne
  le disent — dette écrite, non fermée ici (§7).
- La **première forme de la mutation M1** laissait une `IndentationError` :
  `rc=2` pour la mauvaise raison. Refaite proprement — `rc=1`, trois rouges.

## 6. (c) La reconstruction, et ce que sept lots ont changé en service

**Ordre tenu** : (a) achevé à 14:10 UTC, les deux concordances remesurées à
14:12 UTC, l'image ancienne **étiquetée** avant tout pour que le chemin de
retour survive au `build` :

```
docker tag sha256:946dc14c631a… rag-agent-chat-agent-api:2026-09-03-ancien-lecteur      # 13:58 UTC
docker compose --project-directory /home/ubuntu/RAG/rag-agent-chat -f …/docker-compose.yml build agent-api   # 14:12:46 → 14:12:47 UTC, rc=0
docker run --rm --entrypoint sh 2f4f1aa93f55 -c 'sha256sum src/agent/*.py …'            # l'image, AVANT de la servir
docker compose --project-directory /home/ubuntu/RAG/rag-agent-chat -f …/docker-compose.yml up -d --no-deps agent-api   # 14:13:12 → 14:13:15 UTC, rc=0
```

Le `build` a rendu en **une seconde** : `requirements.txt` et `Dockerfile.agent`
sont identiques entre le commit embarqué (`8bc0485`) et `main` (`git diff
--stat 8bc0485 main -- requirements.txt Dockerfile.agent` : vide), donc les
couches `pip` sont sorties du cache et seules les couches `COPY src/…` ont été
refaites. `mesuré` : le clone principal était à `main` = `85b5a7a`, arbre propre
(`git status --short` : `?? .claude/` seulement), et les trois fichiers copiés
portaient l'empreinte de `main` avant le `build`.

**Le chemin de retour, si quelque chose casse** — non exercé, écrit ici :

```
docker tag rag-agent-chat-agent-api:2026-09-03-ancien-lecteur rag-agent-chat-agent-api:latest
docker compose --project-directory /home/ubuntu/RAG/rag-agent-chat -f /home/ubuntu/RAG/rag-agent-chat/docker-compose.yml up -d --no-deps agent-api
```

### 6.1 L'état APRÈS, et la preuve que les gardes sont présents ET atteints

| | `mesuré` |
|---|---|
| image du conteneur | **`2f4f1aa93f55…`**, construite le 10 septembre 2026 à 14:12:47 UTC ; conteneur démarré à 14:13:15 UTC, `healthy` à 14:13:27 |
| `graph_context.py` / `retriever.py` / `main.py` du conteneur | `9b4a0739…` / `78affe08…` / `df48d6f4…` = **`main`** à l'octet |
| `verifier_modele_embedding` | **5** occurrences dans `retriever.py`, **3** dans `main.py` (`grep -c`, dans le conteneur) |
| `verdict_langue_du_reranker` | **3** dans `retriever.py` |
| `neighbour_section_uncles` | **0** — l'image vient de `main`, pas de la branche du lot |
| `/health` à 14:13:27 | HTTP **200**, `status: ok`, `chromadb`/`nebulagraph`/`ollama` `true`, **`index_lexical: false`** (paresseux, attendu), **`embedding_model: {status: ok, expected: …L12-v2, collection: …L12-v2}`** — un champ que l'ancien `/health` n'avait pas |
| autres conteneurs | `rag-frontend`, les dix du pipeline, `ollama-central` : `Up 6 hours`, **non touchés** ; `dagster-daemon` : `Up 6 hours` à 14:13 UTC, relevé sans numéro |

**Le garde du modèle d'embedding est ATTEINT au démarrage**, journal du conteneur
à 14:13:22 UTC, avant `Application startup complete` :

```
INFO src.api.main — Modèle d'embedding : la collection 'rag_documents' est estampillée
'paraphrase-multilingual-MiniLM-L12-v2', conforme au réglage.
```

**Le garde du reranker est ATTEINT à la première recherche**, et son silence est
celui du registre — trois preuves, parce qu'un silence ne se distingue pas d'un
appel jamais fait :

1. la chauffe de `scripts/evaluate.py` (14:14:00 → 14:14:06 UTC) a écrit au
   journal `Chargement du modèle d'embedding`, `Index lexical BM25 construit :
   4367 chunks`, puis **`Chargement du modèle de reranking :
   cross-encoder/mmarco-mMiniLMv2-L12-H384-v1`** — la ligne écrite par
   `_get_rerank_model` immédiatement avant l'appel du verdict ;
2. `grep -c "Reranker '"` sur le journal : **0** — aucune des trois phrases du
   verdict ;
3. sonde en LECTURE dans un processus séparé du conteneur (`docker exec -i
   rag-agent-api python -`, 14:36 UTC) : vocabulaire lu **250 002**, `verdict_langue_du_reranker(<réglé>, 250002)` → **`None`**, et la
   contre-épreuve `verdict_langue_du_reranker("un-modele-hors-registre",
   250002)` → **`info`** : la fonction parle dès que le nom sort du registre.

Deux `WARNING` au journal, aucun des deux n'est un garde : `huggingface_hub`
sur l'absence de `HF_TOKEN`, et `Contexte tronqué : 1 source(s) sur 5
écartée(s)` — l'éviction ordinaire que `contextes_ecartes_total` compte.

**L'index lexical** : `index_lexical: false` à 14:13:27, construit par la
chauffe de la campagne à 14:14:05, `true` ensuite. La campagne a dit `index
lexical : chauffé pour cette campagne` et n'a pas refusé.

### 6.2 Les deux campagnes du lecteur neuf

```
date -u ; UV_NO_SYNC=1 make eval          # 14:13:58 → 14:31:40 UTC, rc=0
date -u ; UV_NO_SYNC=1 make eval-controle # 14:31:40 → 14:36:10 UTC, rc=0
mv runs/20260910-1413-reglage.json  runs/2026-09-10-lecteur-neuf-reglage.json
mv runs/20260910-1431-controle.json runs/2026-09-10-lecteur-neuf-controle.json
```

| comparaison appariée à la référence du 8 septembre | 138 | 30 |
|---|---|---|
| les huit métriques de rappel et de contexte | **130 / 130 ex æquo** (129 pour `taux_citation_complete`), Δ = 0, p = 1 | **26 / 26** (27) |
| `caracteres_retenus ↓`, `contextes_retenus ↓` | **138 / 138** | **30 / 30** |
| `contextes_ecartes_total` | 26 → 26 | 8 → 8 |
| `prompt_eval_count_p50` / `p95` | 3 131 / 3 582 → identiques | 3 198 / 3 536 → identiques |
| strates | même unique « écarté avant le LLM » (G-053), mêmes cinq « jamais trouvé » | q25 ; q09, q29 |

**Ce que sept lots ont changé en service : RIEN de ce que ces deux jeux
mesurent — et c'est le résultat attendu, pas une déception.** Les lots 2 à 7
ont livré des gardes (identité, modèle d'embedding, reranker, sûreté des
affectations, `push`), des instruments (ancrages, empreinte, chauffe) et une
lecture de `sequence` corrigée. Sur ce graphe et ces 168 questions, la lecture
corrigée sert **le même contenu au caractère près** (`caracteres_retenus` ex
æquo sur 168/168) : ses trois réserves portaient sur des formes de graphe que ce
corpus ne présente pas, ce que `test_lecture_sequence.py` disait déjà en les
gardant sur des fixtures construites.

Ce qui a changé et que la campagne ne note pas : un lecteur qui **refuse en
503** un index lu avec le mauvais modèle au lieu de servir des passages
plausibles et faux, un `/health` qui **dit** l'état de cette concordance, et un
reranker hors registre qui **parle** au journal.

**Les latences du lecteur neuf, et leur comparateur honnête** : contre la
référence du 8 septembre, `rerank_ms_p50` 498 → 622 et `reconstruction_ms_p50`
114 → 121 ; mais le rejeu de l'ANCIEN lecteur le même jour donnait déjà 585 et
123. L'écart est celui de l'hôte ce jour-là, pas du code. Les p95 sont tous
meilleurs (`total_ms_p95` 29 166 → 13 358), pour la même raison à l'envers. Une
seule sonde légère a partagé l'hôte avec cette campagne : la lecture du reranker
dans le conteneur, à 14:14:30 UTC, environ deux secondes.

## 7. Ce que ce lot n'a pas fermé

- **`uv run` synchronise sur `uv.lock`** (§5) : `make eval` depuis un `.venv`
  du §2.2 réécrirait l'environnement — `torch` CUDA compris — au premier
  lancement sans `UV_NO_SYNC=1`. Ni le `Makefile` ni le mandat ne le disent. Je
  n'ai pas touché au `Makefile` : la décision — `uv run --no-sync` dans la
  recette, ou une ligne au §2.2 — est de pilotage ;
- **le registre** : ce lot n'ajoute pas de §4.43. Le §4.42 vit sur la branche du
  pilote et le §4.41 sur celle du lot 4 ; un §4.43 posé ici ouvrirait le trou
  que le garde de numérotation refuse. Ce document est le site des chiffres, le
  pilote y renverra ;
- **`HF_TOKEN`** : le lecteur neuf interroge le Hub sans jeton à chaque
  démarrage (un `WARNING`). Sans conséquence mesurée, non instruit ;
- **le rollback n'a pas été exercé** : rien n'a cassé. Le chemin est écrit au §6.

## 8. (b), suite : la colonne « après » du lot 4 a désormais un artefact

Le §4.42 relevait que la campagne qui a **décidé** de ne pas fusionner (C)
n'avait aucun fichier de run. Rejouée ici sans toucher au service : un lecteur
lancé sur l'hôte depuis l'arbre du lot (`5a98e41`), `uvicorn` sur `127.0.0.1:8012`,
`NEIGHBOUR_SECTION_UNCLES=true`, les mêmes stores et le même LLM par leurs
adresses de conteneur, `HF_HOME` dans le répertoire de travail de la session
(le cache de l'hôte refusait l'écriture — premier essai refusé en 2 par la
chauffe, `500` sur `/search`, `PermissionError` au journal du lecteur ; c'est le
refus qui a servi, comme prévu).

```
python scripts/evaluate.py --api http://127.0.0.1:8012 --golden tests/fixtures/golden_qa_generated.yaml \
  --out runs/2026-09-10-definition-c-allumee-reglage.json --compare runs/2026-09-08-reference.json   # 14:39:52 → 14:58:00 UTC, rc=0
python scripts/evaluate.py --api http://127.0.0.1:8012 --golden tests/fixtures/jeu_de_questions_pipeline.yaml \
  --out runs/2026-09-10-definition-c-allumee-controle.json --compare runs/2026-09-08-controle-30.json  # 14:58 → 15:02 UTC, rc=0
```

| 138 questions, apparié à la référence | le lot 4 disait (`cité`, §4.41) | rejoué ici (`mesuré`) |
|---|---|---|
| cinq métriques de rappel | 130/130 ex æquo | **130/130 ex æquo** |
| `caracteres_retenus_p50` | 10 633 | **10 633** |
| `prompt_eval_count_p50` | 3 291 | **3 291** |
| `contextes_ecartes_total` | 32 | **32** |
| `caracteres_retenus ↓` apparié | — | 119 ▼ / 8 ▲ / 11 =, Δ = +915, p = 0,000 |
| `reconstruction_ms_p50` / `p95` | 197 / 571 | 191 / 550 — processus hôte, ordre de grandeur |

Le contrôle de 30 dit la même chose : rappel 26/26 ex æquo, `contextes_ecartes_total`
8 → 11, `caracteres_retenus_p50` 9 651 → 10 916 ; `rappel_contexte` 0,712 →
0,731 sur **une** question (q04), ce qui est du bruit au sens de la réserve du
jeu. **La décision du §4.42 tient sur un artefact rejouable, pas plus sur une
affirmation.**

Le lecteur hors service a été arrêté à 15:03 UTC ; le service sur 8011 n'a pas
bougé (même image `2f4f1aa9…`, même heure de démarrage 14:13:15 UTC).
