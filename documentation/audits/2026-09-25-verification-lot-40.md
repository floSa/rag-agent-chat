# VÉRIF-40 — vérification indépendante de la documentation du livrable

**Rendu le 25 septembre 2026.** Objet : `README.md`,
`documentation/etat_du_projet.md`, `documentation/prochaines_etapes.md`, et les
ajouts datés de `documentation/llm.md` et
`documentation/rag_evaluation_strategy.md`, livrés par LOT-40 (`c94b2a0`),
fusionnés en `62003e9`, journal ligne **92**.

**Base de la vérification.** `origin/main` = **`8cf5733cd275401cefb4f381efb6de40690d6d41`**
(`git fetch origin` puis `git rev-parse origin/main`). Arbre de travail créé par
`git worktree add -b verif-40 … origin/main` : **`rc_worktree_add=0`**, arbre
vérifié présent dans `git worktree list`, `HEAD` = `8cf5733`.

**Ce vérificateur n'a écrit aucune ligne de code et n'a rien corrigé.** Aucun
`docker compose`, aucun `make install`, aucune écriture dans les stores. Les
seules lectures du service sont `GET /health` et `GET /openapi.json`.

---

## 1. VERDICT

**BLOQUANT : OUI — deux constats.**

| | Constat | Classe |
|---|---|---|
| **B1** | Depuis un clone neuf, la porte qualité du README **ne tourne pas telle qu'écrite** : après la ligne d'installation (`rc=0`), `make lint` rend **`rc=2`**, `mypy: No such file or directory`. Le README ne dit nulle part d'activer le `.venv` | **BLOQUANT** — commande du README qui ne marche pas telle qu'écrite |
| **B2** | « `reviewed: false` sur les trois jeux… soit **138 + 30 + 60** questions » (`prochaines_etapes.md` §2) et « **Aucune** des questions n'a été relue par un humain » (`etat_du_projet.md` §2.4) : **faux**. Mesuré sur les fichiers eux-mêmes : **130 + 0 + 60 = 190**, et **38** questions portent `reviewed: true` | **BLOQUANT** — chiffre faux |

Six constats non bloquants suivent au §7.

**Ce qui tient, et c'est l'essentiel du document.** Les **319** chiffres de
`etat_du_projet.md` sont **317 identiques à leur site canonique**, 1 arrondi non
dit, 1 sans source, **0 faux**. Les onze routes décrites sont exactement les onze
routes servies. Les cinq fichiers ne portent **aucune** adresse IP, **aucun**
hôte ou port de stockage, **aucune** valeur de secret, **aucune** mention d'un
outil de génération de code.

---

## 2. LE README DEPUIS UN CLONE NEUF, COMMANDE PAR COMMANDE

Clone neuf du **dépôt distant** dans un répertoire temporaire — pas un arbre de
travail :

```
git clone https://github.com/floSa/rag-agent-chat.git <tmp>/clone-neuf
```

`rc_clone=0`, `HEAD` = `8cf5733`. Répertoire supprimé à la fin de ce rapport.

État du poste **avant** toute installation, mesuré dans le clone :
`uv` présent, `make` présent, `docker` présent ; **`ruff`, `mypy`, `pytest` et
`python3.12` absents du `PATH`** — l'affirmation du §4 du README sur ce point
est **vraie**.

| | Commande du README | Où | `rc` relevé | Ce qui s'est passé |
|---|---|---|---|---|
| 1 | `cp .env.example .env` (§2.2) | — | *non exécutée* | Le README la marque « non exécutée ici ». **Raison vraie** : `docker-compose.yml:72` monte bien `./prompts:/app/prompts:ro`. `.env.example` **existe** dans le clone neuf, la copie marcherait |
| 2 | `docker compose up -d --build` (§2.3) | — | *non exécutée* | Marquée « non exécutée ici ». **Raison vraie** : le port 8011 est bien occupé par un service partagé (il a répondu `200` à mes deux lectures). `make up` = `docker compose up -d` et `make image` inscrit bien le sha (`Makefile:106-111`) : **exact** |
| 3 | `make lint` sur arbre neuf, **avant** installation (§4) | clone neuf | **`rc_lint_neuf=2`** | Échoue — mais sur **`mypy: No such file or directory`** (`Makefile:69`, cible `typecheck`), **pas** sur `ruff: command not found` comme l'écrit le README. `ruff` n'est jamais atteint. **Constat N1** |
| 4 | `uv venv --python 3.12 && uv pip install torch --index-url https://download.pytorch.org/whl/cpu && uv pip install -r requirements.txt -r requirements-dev.txt` (§4) | clone neuf | **`rc_install=0`** | Passe telle qu'écrite. Confirme le `rc=0` annoncé |
| 5 | `make lint && make test` (§4), **immédiatement après** la commande 4 | clone neuf | **`rc_lint_sans=2`** | **ÉCHOUE.** `mypy: No such file or directory`. Les outils sont dans `.venv/bin` (vérifié : `ruff`, `mypy`, `pytest`, `python3.12` y sont) mais **le `PATH` ne les voit pas** : `command -v ruff mypy pytest` rend `rc=1`. **Le README ne dit jamais d'activer le `.venv`, ni de préfixer par `uv run`. Constat B1** |
| 6 | `make lint` après `. .venv/bin/activate` | clone neuf | **`rc_lint=0`** | `mypy` : **22 fichiers, aucun problème** — le compte du README à l'unité. `ruff` : *All checks passed!* |
| 7 | `make test` après `. .venv/bin/activate` | clone neuf | **`rc_test=0`** | **1263 passed in 128.92s** — **le compte attendu, à l'unité**. (Le README annonce 124 s ; une durée, cf. **N3**) |

**Ce qui manquait pour que la porte marche telle qu'écrite : une ligne
d'activation.** C'est un geste, pas une réparation de code, mais un lecteur neuf
qui suit le README à la lettre voit `rc=2` et un outil manquant, exactement ce
que le §4 dit vouloir éviter.

**Les autres « non exécutée ici » du tableau des cibles (§4)** — `make format`,
`make test-integration`, `make verifier-les-ancrages`, `make eval`,
`make eval-controle`, `make health`, `make models`, `make image`/`up`/`down`/`logs`,
`make audit`, `make install` — portent des raisons **vraies** : lues au
`Makefile`, `format` écrit bien dans l'arbre (`ruff format` + `--fix`),
`eval` et `eval-controle` **dépendent** bien de `verifier-les-ancrages`
(`Makefile:166`, `:175`), `audit` sort bien sur le réseau (`pip-audit`).
**Il n'existe effectivement pas de cible `make all`** (`grep -nE '^all:' Makefile`
→ `rc=1`, sur 35 cibles).

---

## 3. LES CHIFFRES DE `etat_du_projet.md`

### 3.1 Le relevé, par script

Relevé par `re` sur le fichier entier, jamais à l'œil. Les sha, les ancres
`fichier.py:ligne`, les dates, les heures, les renvois `§4.xx` / `ligne NN` et
les numéros de titre sont masqués **avant** comptage.

| | Compte |
|---|---|
| occurrences numériques brutes | **490** |
| dont sha, ancres de fichier, dates, heures, renvois de section et de ligne | 146 |
| dont numéros de titre et renvois internes | 25 |
| **chiffres de mesure confrontés** | **319** |

**Double du zéro.** Le relevé n'a rendu aucun zéro : contrôle positif fait sur
quatre valeurs que je sais présentes — `15 173` (2 occurrences), `0,9538` (1),
`4367` (2), `32768` (2) : toutes retrouvées par le script.

### 3.2 Le classement

| Classe | Compte | |
|---|---|---|
| **identique à son site** | **317** | Confrontés un à un à `axes_amelioration.md` §4.66, §4.67, §4.71, §4.74, §4.75, §4.76, §4.77, §4.78, §4.79, aux lignes **86 à 92** du journal, à `/health` servi, et aux fichiers de jeux eux-mêmes |
| arrondi dit | 0 | — |
| **arrondi non dit** | **1** | Cf. **N2** |
| **sans source** | **1** | Cf. **N3** |
| **faux** | **0** | — |

**Liste des « faux » : aucune.**
**Liste des « sans source » : une seule** — la durée **124 s** de `make test`
(§1.2). Aucun site ne la porte ; ma mesure indépendante rend **128,92 s**. Une
durée de porte n'est pas reproductible d'un poste à l'autre : c'est le compte
**1263** qui est le fait, et il est exact.

### 3.3 Ce que la confrontation a rendu, section par section

- **§1.1** — `/health` lu en direct (HTTP **200**) : `vllm` **0.28.0**, fenêtre
  **32768**, `services_unknown` **vide**, quatre dépendances vertes,
  `code_servi.etat` = `identifie`, sha `97bba2095bb…`, `construite_le`
  **2026-09-25T00:35:52Z**. **Tout concorde, à la seconde.**
- **§1.2** — `1263` : confirmé par ma propre porte (§2, ligne 7), par
  `tests.md` (« **1263** tests sur **61** fichiers, 07:47 UTC ») et par la ligne
  **91** du journal. Un garde du dépôt le tient bien
  (`tests/unit/test_coherence_depot.py:1869-1899`).
- **§1.3** — les effectifs des trois jeux confrontés **aux fichiers eux-mêmes**,
  pas seulement au registre : réglage **138** questions / **130** avec ancrage /
  **130** ancrages / **un seul** chacune ; contrôle **30** / **26** / **47**
  (répartition mesurée 1, 2 ou 3 par question) ; dispersé **60** / **120** /
  **109** distincts. **Identiques.** Les tableaux de rappel (0,9538 ;
  [0,903 – 0,979] ; 124 ; 124/130 ; 0,7308 ; [0,539 – 0,863] ; 19 ; 26/47) et
  les bascules (+4/0 ; +1 et +2 ancrages de 3 à 6 ; +2 et +7 de 3 à 10) sont
  **ceux du §4.67 à l'unité**. La suite `0, 2, 6, 7, 7, 7, 8, 8, 9, 10` et les
  **33,48** / **102,5** éléments sont ceux de la ligne **88**.
- **§1.4** — `56 / 46 / 67`, `53 → 64 → 62`, `+11` puis `−2`, `109/109`,
  `120/120`, et le tableau des causes `53 / 21 / 13 / 31 / 2 / 0 / 0 / 0`
  (**somme 120**, recalculée ici) : **identiques** au §4.77 et à la ligne 89.
- **§1.5** — le tableau des **sept variantes** est **cellule pour cellule** celui
  du §4.79, ligne de l'oracle comprise (`86 / 28`). Les trois faits (`7 → 19`,
  **68 %**, `+11`, `125` contre `124`, `127`, `11 manquées et 2 gagnées hors
  borne`, `6` à la fusion, `4` au reranking, `1` jamais) sont au site.
- **§1.6** — §4.66 : `2358 → 4224`, `9 712 → 13 970`, `+44 %`, `34 → 55`,
  `6 fois sur 6`, `4849` contre `32768` soit `15 %` : **identiques**, l'arrondi
  à 15 % étant écrit tel quel au site. §4.79 : les intervalles `826 – 1322`,
  `1734 – 2338`, `429 – 587`, `996 – 1029`, `102` contre `177`, `1130`, `1322`
  contre `704`, `4105`, `×1,60 – ×2,03`, `×2,51 – ×4,03` **encadrent exactement**
  les trois jeux du site (médianes 826 / 946 / 1322, facteurs 1,60 / 1,92 / 2,03
  et 2,51 / 3,62 / 4,03).
- **§1.7** — confronté à la ligne « LE VERDICT D'APRÈS LA CAMPAGNE DU PIPELINE »
  du journal (entre les lignes 90 et 91) : `4367`, `rc=0`, `0 désaccord`,
  `130/130`, `44/44`, `109/109`, `267`, `212`, `c91f5be6e24fbcba…`, `23`
  `Document`, `15 173` arêtes, `03:50:41`, `23 runs`, `23/23`, `0 déplacé`,
  « conforme sur les cinq contrôles ». **Identiques, mot pour mot.**
- **§2.5** — §4.71 **après ses deux corrections datées** : `172`, `148`, `0`
  échec, `1 751`, `20/152`, `26/289`, `20/1 698`, `46/1 751`, `202`, `727`,
  `15 173` = `15 007` + `166` (recalculé ici), `404/404`, `0` perte sèche sur
  `1 362`. **Identiques.** Les « **37** pertes sèches » sont bien citées **comme
  retirées**, ce qui est la lecture juste du site. Les deux relevés annoncés
  sont **rejoués ici** : `git grep _fill_full_texts -- src/` rend **0**, contrôle
  positif `git grep _restore_full_text -- src/` rend **2 lignes**
  (`graph_context.py:852` et `:968`).
- **§2.6** — `0 sur 250`, `58` lignes, `5` appelants, `18` résidus,
  « 55 sur 500 », `4000` appels, `32 957` fermetures : **identiques** aux §4.74,
  §4.75 et à la ligne 86.

---

## 4. `prochaines_etapes.md` ET LA PARTIE MESURES DU README

### 4.1 `prochaines_etapes.md` — **155** chiffres de mesure

| Classe | Compte | Détail |
|---|---|---|
| identique à son site | **151** | §4.76 (`4` sur `139`, `8`, `67`, `30` au rang 1, `0` française sur `60`), §4.77 (`52`, `53/64/62`, `+11`, `−2`, `58 ms` p50 GPU du §4.47), §4.78/§4.79 (`7`, `19`, `18`, `19`, `28`, `68 %`, `127/124/125/127`, `14`), la répartition par étage `72/12/11/25`, `72/13/8/27`, `73/9/18/20` — **cellule pour cellule** celle du §4.79, et les trois lignes somment à **120** (recalculé ici) —, §4.74 (`1 rouge sur 1126`, `58`, `5`, `18`, `55 sur 500`), §4.75 (`4000`, `32 957`), §4.71 (`172`, `148`, `1 751`, `20/152`, `26/289`, `20/1 698`, `46`, `727`, `1 362`) |
| **arrondi dit** | **1** | « **2,6 %** (calculé ici depuis les deux chiffres du site) » : 46 / 1 751 = 2,627 %. **L'arrondi ET le calcul sont dits.** C'est la bonne pratique |
| **arrondi non dit** | **1** | « p95 de **8,5 s** en `cpu` » — cf. **N2** |
| **faux** | **2** | « 138 + 30 + 60 questions » : **138** devrait être **130**, **30** devrait être **0**. Cf. **B2**. Le troisième terme, **60**, est juste |

### 4.2 La partie mesures du README — **79** chiffres de mesure

**Tous identiques**, sauf la durée `124 s` (**N3**). Confrontés au code, aux
dépendances et au service :

- les quatre étages : `FETCH_K` **50** (`settings.py:404`), `RETRIEVAL_TOP_K`
  **50** (`:394`), `RERANK_TOP_K` **10** (`:407`), `AUTO_SELECT_TOP_K` **3**
  (`:415`), `RRF_K` **60** (`:406`) — **les quatre lignes citées portent bien
  le champ annoncé** ;
- `CROSS_LINGUAL_SEARCH` **true** (`:423`), `TRANSLATION_WEIGHT` **1.0**
  (`:440`), `QUERY_REWRITE` **true** (`:418`), `_MAX_TRANSLATION_RATIO` **3.0**
  (`llm.py:935`), `RESTRICT_MEDIA_TO_GRAPH` **true** (`:35`) ;
- `MAX_HISTORY_PAYLOAD` **50** et `MAX_HISTORY_MESSAGES` **6**
  (`schemas.py:38`, `:31`), `chat_history` bien aux lignes **104, 196, 260**,
  `HISTORY_WINDOW_SHARE` **0.25** (`settings.py:100`) ;
- `max_sources` borné par `MAX_SOURCES_SERVIES` et **non** par une valeur en dur
  (`schemas.py:282-287`), avec la justification écrite au site ;
- `graph_text_truncation` défaut **2000** (`settings.py:499`), `_restore_full_text`
  bien à **852**, le seuil dérivé bien à **870** ;
- `git grep -n minio_url -- src` → **28 lignes, 7 fichiers** : **exactement ce
  que le README annonce** ;
- les badges : Python **3.12**, FastAPI **0.141**(.1), LangGraph **1.2**(.10),
  Streamlit **1.60**(.0), vLLM **0.28**(.0 au `/health`), `minio==7.2.20` :
  tous exacts contre `requirements.txt` et `pyproject.toml` ;
- la porte : `mypy` **22 fichiers**, **1263** tests — **remesurés ici**.

### 4.3 Les ajouts datés de `llm.md` et `rag_evaluation_strategy.md`

| Affirmation | Mesure de ce rapport | |
|---|---|---|
| `llm.md` : `.env.example` porte `LLM_NUM_CTX=8192` **l. 66** | `grep -n` → **ligne 66**, valeur `8192` | **exact** |
| `llm.md` : `settings.py:86` porte `default=8192` | `sed -n '86p'` → `llm_num_ctx: int = Field(default=8192, …)` | **exact** |
| `llm.md` : `/health` publie `num_ctx` et `fenetre_servie` à **32768** | `moteur_llm.options.num_ctx` = **32768**, `fenetre_servie` = **32768** | **exact** |
| `strategy` : `git grep -ci 'deux jeux' e1324e4 -- …` rend **4** lignes | rejoué : **4** (lignes 49, 52, 369, 417) | **exact** |
| `strategy` : `git grep -ci dispers e1324e4 -- …` rend **0** | rejoué : **rc=1**, aucune ligne | **exact** |
| `strategy` : contrôle positif, même motif sur `tests.md` au même sha rend **2** | rejoué : **2** | **exact** |
| `strategy` : « 120 ancrages sur 130 au prompt à `k=1`, plus aucun de `k=3` à `k=20` » | §4.67 : k=1 → 120/130 ; k=3 à k=20 → 124, constant | **exact** |

**Les deux relevés du bandeau sont faits contre le sha de base `e1324e4` et le
disent** — c'est ce qui les garde vrais après l'ajout du bandeau lui-même : au
`HEAD` d'aujourd'hui, le même motif rend **8** lignes. Bonne pratique, relevée
comme telle.

---

## 5. L'API DÉCRITE EST-ELLE L'API SERVIE ?

**Le service n'était pas rouge.** `GET /openapi.json` → **HTTP 200**,
`GET /health` → **HTTP 200**, quatre dépendances vertes, `services_unknown` vide.
Les deux lectures sont donc exploitables, et rien n'est déduit d'un service
indisponible.

**Onze routes servies, onze routes décrites, listes identiques :**

| Route | `/openapi.json` servi | `src/api/main.py` | README §3 |
|---|---|---|---|
| `/health` | `GET` | `:1178` | `GET` ✓ |
| `/search` | `POST` | `:1390` | `POST` ✓ |
| `/reindex` | `POST` | `:1399` | `POST` ✓ |
| `/sources` | `POST` | `:1424` | `POST` ✓ |
| `/context/{element_id}` | `GET` | `:1435` | `GET` ✓ |
| `/chat/simple` | `POST` | `:1502` | `POST` ✓ |
| `/answer` | `POST` | `:1643` | `POST` ✓ |
| `/chat/start` | `POST` | `:1807` | `POST` ✓ |
| `/chat/resume` | `POST` | `:1909` | `POST` ✓ |
| `/feedback` | `POST` | `:2081` | `POST` ✓ |
| `/media/{object_name}` | `GET` | `:2114` | `GET` ✓ |

**Aucune route en trop, aucune manquante, aucune méthode fausse.** L'ancre
`main.py:2114` citée par le §1.6 est **juste** (le code écrit
`{object_name:path}`, que l'OpenAPI rend `{object_name}` — même route).

**Les champs cités sont servis** : `chat_history` sur **les trois** routes
annoncées ; `role` est un `Literal["user", "assistant"]` (`schemas.py:48`) —
« un client ne peut pas glisser un message `system` » est **vrai** ;
`max_sources` rend bien `422` au-delà de la borne, et la borne est bien
**dérivée** de `RERANK_TOP_K` ; `CHECKPOINT_DB_PATH`, `SESSION_TTL_SECONDS`
(défaut 3600) et `MAX_LIVE_SESSIONS` (défaut 200) existent
(`settings.py:510-512`), et `sessions.py` porte bien une notion de registre
**durable** (`def durable()`, l. 101).

**« Les dix routes autres que `/health` portent `Depends(require_api_key)` »** :
**vrai**, 10 décorateurs sur 11 le portent, `/health` seul ne l'a pas.

---

## 6. LES AFFIRMATIONS BORNÉES

Relevé par motif sur les trois fichiers :

```
grep -oniE '\b(aucun[e]?[s]?|jamais|toujours|tous|toutes|seul[e]?[s]?|rien)\b'
```

**106 occurrences** — README **25**, `etat_du_projet.md` **43**,
`prochaines_etapes.md` **38** (« toujours » ne sort nulle part). Par motif : `rien` 24, `aucun` 19, `jamais` 17, `seule` 15,
`aucune` 13, `seul` 10, `toutes` 4, `tous` 4, `toujours` 0.

**La grande majorité est bornée, et souvent bornée explicitement** — ce qui est
la qualité principale de ces trois documents :

- « aucun ancrage et aucune question n'est perdu quand `k` monte — **borné à ces
  huit transitions, ces deux jeux, cette campagne** » (etat §1.3) ;
- « aucun ancrage n'est hors d'atteinte du classement — **borné à ce jeu et à
  cette campagne** » (§1.4) ;
- « **Borné à tout ce qui est publié aux §4.66 à §4.79** : aucun des bancs ne
  génère de réponse » (§2.2) ;
- « Il n'existe **pas** de jeu de réponses de référence **dans ce dépôt au
  25 septembre 2026** » (§2.2) — borné en lieu et en date ;
- les deux « jamais » du `-wal` sont **cités comme dettes** et portent leurs
  bornes (`0 sur 250`, `4000` appels contre `32 957` fermetures) — le document
  écrit lui-même *« un “jamais” reste une affirmation qui périme »*.

**Les affirmations que je relève comme NON bornées ou non gardées :**

| | Où | Affirmation | Jugement |
|---|---|---|---|
| a | `etat` §2.4 / `prochaines` §2 | « `reviewed: false` sur les trois jeux », « **Aucune** des questions n'a été relue par un humain » | **Non bornée ET fausse.** Cf. **B2** |
| b | `prochaines` §1 | « **Registre : aucune section ne la porte** » | Non bornée : aucune commande, aucun motif de relevé n'est donné pour ce zéro. Le zéro est plausible mais **non doublé**, alors que le même document double le sien ailleurs |
| c | README §1.6 | « l'agent lit [le stockage] **sans jamais y écrire** » | Non bornée en forme, mais **vraie à la mesure** : `grep -rnE '\.(put_object\|fput_object\|remove_object\|make_bucket\|copy_object)\(' src/` rend **rc=1**, aucune ligne ; contrôle positif sur les lectures de `minio_client.py` : **1** ligne |
| d | README §2.4 | « laissée vide, **toutes** les routes répondent sans authentification » | Bornée par le code : `require_api_key` ne mord que si `API_KEY` est posée, et `/health` n'en dépend pas. **Vraie** |
| e | README §3 | « Onze routes, et ce sont **exactement** les onze que le service publie » | Bornée : datée, et adossée à deux lectures indépendantes. **Vérifiée vraie ici** |
| f | `prochaines` §4 | « le §4.78 **refuse** le reranking par sous-question » | Le §4.78 écrit *« ne propose aucun réglage, et il ne recommande pas d'implémenter la décomposition »*. « Refuser » **durcit** le site. Cf. **N4** |

---

## 7. LE DÉPÔT EST PUBLIC

Relevé par motif sur les cinq fichiers de l'objet
(`F="README.md documentation/etat_du_projet.md documentation/prochaines_etapes.md documentation/llm.md documentation/rag_evaluation_strategy.md"`) :

| Ce qui est cherché | Commande | Compte |
|---|---|---|
| adresse IP | `grep -nE '\b([0-9]{1,3}\.){3}[0-9]{1,3}\b' $F` | **0** |
| hôte ou port de stockage | `grep -nE 'minio[:.]\|:9000\|:9001\|seaweed\|s3\.\|bucket *=\|MINIO_[A-Z_]*=' $F` | **0** (`rc=1`) |
| valeur de secret | `grep -nE 'PASSWORD *= *\S\|SECRET *= *\S\|API_KEY *= *\S\|TOKEN *= *\S' $F` | **0** (`rc=1`) |
| outil de génération de code | `grep -niE` sur un motif de **dix** noms d'assistants et de signatures automatiques, insensible à la casse | **1** correspondance, et ce n'en est pas une : `llm.md:28`, « le **dialecte OpenAI** » — un nom de **protocole d'API**, pas un outil de génération. Motif tenu hors de ce rapport, qui entre lui aussi dans un dépôt public |

**Les seuls ports cités dans les cinq fichiers sont `8506`, `8011` et `8000`** —
l'interface, l'API et l'endpoint d'inférence, tous décrits comme des interfaces
du projet. **Aucun port de stockage.** Le §1.6 du README nomme les **cinq
variables** du stockage sans en publier une seule valeur, et l'écrit
(« Aucune valeur n'est reproduite ici : ce dépôt est public ») : conforme.

**Hors des cinq fichiers, et donc hors du lot 40**, le dépôt porte des adresses
internes anciennes — `axes_amelioration.md` (l. 4399, 7583, 12630, 13185),
`documentation/campagnes/2026-09-11-…md`, `runs/2026-09-08-ancrages.json`,
`tests/unit/test_verification_des_ancrages.py` — et des mentions d'outil dans
`.gitignore`, `.dockerignore` et d'anciens rapports d'audit. **Antérieures au
lot 40, non introduites par lui** : je les signale sans les lui imputer.

---

## 8. LES CONSTATS

### BLOQUANTS

**B1 — La porte qualité du README ne tourne pas telle qu'écrite depuis un clone
neuf.**
*Mesure* : clone neuf `8cf5733`, commande d'installation du §4 → `rc_install=0` ;
puis `make lint` → **`rc_lint_sans=2`**, `mypy: No such file or directory`
(`Makefile:69`). `command -v ruff mypy pytest` → `rc=1`. Les binaires existent
dans `.venv/bin`. Après `. .venv/bin/activate` : `rc_lint=0`, `rc_test=0`,
**1263 passed**.
*Ce qui manque au README* : la ligne d'activation du `.venv`, ou le préfixe
`uv run --no-sync`, entre la commande d'installation et `make lint && make test`.

**B2 — « `reviewed: false` sur les trois jeux » est faux, et le compte qui en
découle l'est aussi.**
*Mesure*, sur les fichiers de jeux eux-mêmes, par `yaml.safe_load` :

| jeu | `reviewed: false` | `reviewed: true` |
|---|---|---|
| `golden_qa_generated.yaml` | **130** | **8** (`N-001` à `N-008`) |
| `jeu_de_questions_pipeline.yaml` | **0** | **30** |
| `jeu_ancrages_disperses.yaml` | **60** | 0 |
| **total** | **190** | **38** |

`prochaines_etapes.md` §2 écrit « soit **138 + 30 + 60** questions » : deux des
trois termes sont faux. `etat_du_projet.md` §2.4 écrit « **Aucune** des
questions n'a été relue par un humain » : **38** portent le contraire, et le jeu
de contrôle **entier** est marqué relu — ce que `etat_du_projet.md` §1.3 dit
lui-même en le décrivant comme « **écrit à la main**, après l'ingestion », et ce
que le fichier confirme (`_lisez_moi` : *« Écrit à la main APRÈS l'ingestion »*).
*Origine* : l'erreur vient du site canonique cité, **§4.79 réserve 8**, qui
généralise aux trois jeux une phrase que le registre portait correctement bornée
ailleurs (`axes_amelioration.md:1546` : « `reviewed: false` sur **les 130
questions générées** »). Les deux documents du lot 40 ont donc **repris
fidèlement un site fautif** — mais `prochaines_etapes.md` y a ajouté une
arithmétique qui rend l'erreur chiffrable, et donc mesurablement fausse.

### NON BLOQUANTS

**N1 — Le message d'erreur annoncé pour un arbre neuf n'est pas celui qui sort.**
README §4 : « un `make lint` depuis un arbre neuf échoue sur
`ruff: command not found` ». *Mesuré* : `rc=2`, `mypy: No such file or directory`,
`Makefile:69`. `ruff` n'est jamais atteint, puisque `lint` dépend de `typecheck`
— ce que le README écrit **trois lignes plus haut**. La conclusion (« échoue sur
l'environnement, pas sur une faute de code ») reste vraie.

**N2 — « 8,5 s » est un arrondi non dit de 8483 ms.**
`etat_du_projet.md` §2.3 et `prochaines_etapes.md` §4. Le site §4.78 publie
**8483 ms** ; la ligne **90** du journal écrit déjà « p95 8,5 s en cpu ». Le
document reprend donc un de ses deux sites, mais il s'engage en tête à ce que
*« rien ne soit arrondi sans que l'arrondi soit dit »*.

**N3 — La durée `124 s` de `make test` n'a pas de site.**
Ma mesure indépendante rend **128,92 s** sur le même compte de tests. Une durée
dépend du poste ; c'est le **1263** qui est le fait, et il est exact.

**N4 — « Le §4.78 refuse le reranking par sous-question » durcit son site.**
Le §4.78 écrit *« ne propose aucun réglage, et il ne recommande pas
d'implémenter la décomposition »*. Ne pas recommander n'est pas refuser, et le
motif invoqué (le p95) n'est pas celui que le site donne.

**N5 — Le « 30 » du jeu de contrôle n'est pas au §4.67, le site cité en regard.**
Le §4.67 ne porte que « les **26** questions [qui] portent **47** ancrages ». Le
**30** est sourcé ailleurs dans le même registre (`axes_amelioration.md:1473`,
`:1606`, `:1638`) et **exact à la mesure du fichier**. Renvoi imprécis, chiffre
juste.

**N6 — Le zéro du §1 de `prochaines_etapes.md` n'est pas doublé.**
« Registre : **aucune section** ne la porte » : aucune commande, aucun motif, pas
de contrôle positif — alors que le même lot double correctement ses autres zéros
(`_fill_full_texts`, `dispers`). Le zéro est plausible ; il n'est pas mesuré.

---

## 9. CE QUE CE RAPPORT N'A PAS FAIT

- **Aucun `docker compose`**, aucun `make up`, `make image`, `make install`,
  `make eval`, `make verifier-les-ancrages` : hors mandat, et ils écrivent.
- **Aucune écriture dans les stores**, aucune requête au service autre que
  `GET /health` et `GET /openapi.json`.
- **Les chiffres des sites canoniques ne sont pas remesurés** : ce rapport
  vérifie que `etat_du_projet.md` et `prochaines_etapes.md` **disent ce que
  leurs sites disent**, et que les chiffres vérifiables contre le code, le
  service, les fichiers de jeux et la porte sont exacts. Il ne rejoue ni le
  §4.77, ni le §4.78, ni le §4.79.
- **Les licences du §8 du README ne sont pas vérifiées** au-delà des versions de
  paquets, ce que le journal signale déjà comme non vérifié à la ligne 92.
