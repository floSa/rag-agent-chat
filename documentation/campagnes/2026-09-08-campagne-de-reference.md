# Campagne de référence de l'agent — 8 septembre 2026

**Ce document est le SITE CANONIQUE de tous les chiffres de cette campagne.** Ils
ne sont recopiés nulle part ailleurs : le registre, `runs/README.md` et
`rag_evaluation_strategy.md` renvoient ici. Chaque chiffre porte sa commande et
son étiquette — `mesuré` (sortie d'un programme), `calculé` (dérivé d'une sortie,
avec la dérivation écrite), `supposé` (rien ici).

**Elle remplace `runs/final.json` comme antécédent**, et aucune comparaison ne
traverse le remplacement de corpus du 2 septembre 2026. Motif : §4.3 de
[`../axes_amelioration.md`](../axes_amelioration.md).

---

## 0. La réserve, avant les chiffres — et elle n'est pas négociable

**Le jeu de 30 questions est un CONTRÔLE DE BON FONCTIONNEMENT, jamais une
décision d'architecture.** Un écart de deux points sur trente questions est du
bruit. La réserve vit dans le fichier de données lui-même — champ `_reserve` de
`tests/fixtures/jeu_de_questions_pipeline.yaml` — et un test refuse qu'elle en
sorte.

**Le jeu de 138 questions régénérées est AUTO-RÉFÉRENTIEL** : chaque question a
été écrite *pour* le passage qu'elle désigne, par le même modèle qui sert
l'agent. Il porte du volume de réglage ; il ne sait pas se contredire. Ses
chiffres ne sont pas une note de qualité du système, ce sont le **plancher de son
instrument de réglage**.

**Aucun réglage n'est décidé ici**, et rien dans ce document n'en propose. Ce que
la campagne établit est un antécédent : la prochaine campagne aura de quoi se
comparer, appariée, question par question.

---

## 1. Où, quand, et contre quoi

| | |
|---|---|
| date | **8 septembre 2026**, `date -u` relevée à chaque bloc de mesure |
| arbre de travail | `/home/ubuntu/RAG/rag-agent-chat/.claude/worktrees/nifty-gates-28edab`, branche `claude/lot-5-jeu-et-campagne`, créée depuis `main` = `4eedb2a` — **pas** le clone principal |
| agent | `rag-agent-api`, `GET /health` → HTTP **200**, `status: ok`, port **8011** de l'hôte |
| ChromaDB | `rag_documents`, **4 367** chunks, **3 750** `element_id` distincts, estampille `paraphrase-multilingual-MiniLM-L12-v2` |
| NebulaGraph | `rag_space`, **15 196** sommets, **15 173** arêtes `PARENT_OF`, **23** documents |
| corpus | **entièrement anglais** : **4 367 chunks sur 4 367** portent `language: en` |
| modèle de génération | `gemma4:e4b` sur `ollama-central` |

**Toutes les sondes de ce document sont en LECTURE SEULE**, et ce n'est pas une
promesse : `scripts/verifier_les_ancrages.py` est gardée en lecture seule par
lecture de son arbre syntaxique — aucun appel nommé `add`, `upsert`, `modify`,
`delete` ou `update`, aucune requête nGQL d'écriture
(`tests/unit/test_verification_des_ancrages.py::TestLaSondeEstEnLectureSeule`).
Les seuls appels de store faits ici sont `get_collection`, `count`, `get` côté
ChromaDB, et `FETCH PROP ON *` côté NebulaGraph. Aucune écriture dans ChromaDB ni
dans NebulaGraph, aucune réingestion, aucun `docker compose`, aucun démarrage ni
arrêt du démon d'orchestration du pipeline — dont l'état a été **relevé et non
touché** : `Up 42 minutes` au début du lot, inchangé à la fin.

### Le chemin de code mesuré, et il n'est pas celui du pipeline

`mesuré` le 8 septembre 2026 dans l'environnement du conteneur en service :

```
HYBRID_SEARCH=true        FETCH_K=50            RETRIEVAL_TOP_K=50
QUERY_REWRITE=true        RERANK_TOP_K=10       AUTO_SELECT_TOP_K=3
TRANSLATION_WEIGHT=1.0    CONTEXT_WINDOW_BEFORE/AFTER=6/6
ADJACENT_SECTION_ELEMENTS=3   FULL_TEXT_FROM_VECTORS=true
RERANK_MODEL=cross-encoder/mmarco-mMiniLMv2-L12-H384-v1
```

Donc : dense **et** BM25, sur la question **et** sa traduction, fusion RRF,
**puis reranking par cross-encoder**, déduplication par élément, coupe au top-10.
`retrieved_element_ids` — la liste sur laquelle `rappel_recherche` et le MRR sont
calculés — est **exactement** ce top-10 post-reranking
(`src/api/main.py:1096`, `retriever.rerank`). `rappel_recherche` est donc un
**rappel@10 sur éléments distincts, après recherche hybride et reranking.**

**Un piège de la sonde `/health`, relevé au passage.** `index_lexical` était à
`false` au premier relevé et à `true` après la première recherche : l'index BM25
se construit **paresseusement**. Un `/health` lu juste après un redémarrage
annonce donc une recherche amputée qui ne l'est pas — la première recherche la
construit synchroniquement. La campagne a été lancée **après** une recherche de
mise en chauffe, et `index_lexical: true` a été vérifié avant de commencer : les
138 questions ont toutes emprunté le chemin hybride complet.

---

## 2. L'antécédent — les ancrages existent, et c'est prouvé AVANT toute mesure

**C'est la leçon la plus chère de ce chantier.** Un jeu de questions qui rend 0 %
de rappel ne dit pas si la recherche est cassée ou si le jeu désigne le vide. Les
deux produisent le même zéro, et le second est arrivé — pendant deux mois.

```bash
CH=$(docker inspect -f '{{.NetworkSettings.Networks.rag_network.IPAddress}}' \
     rag-ingestion-pipeline-chromadb-1)
NB=$(docker inspect -f '{{.NetworkSettings.Networks.rag_network.IPAddress}}' graphd)
uv run python scripts/verifier_les_ancrages.py --chroma-host "$CH" --nebula-host "$NB" \
    --json runs/2026-09-08-ancrages.json \
    tests/fixtures/golden_qa_generated.yaml \
    tests/fixtures/jeu_de_questions_pipeline.yaml
```

`mesuré` le 8 septembre 2026, `rc=0`, bilan versionné à
`runs/2026-09-08-ancrages.json` :

| Le jeu | questions | ancrages distincts | dans NebulaGraph | dans ChromaDB |
|---|---|---|---|---|
| `golden_qa_generated.yaml` | **138** | **130** | **130 / 130** | **130 / 130** |
| `jeu_de_questions_pipeline.yaml` | **30** | **44** | **44 / 44** | **44 / 44** |

**0 désaccord** — ni ancrage manquant, ni document discordant, ni strate
incohérente.

### Et la sonde ATTEINT SON CAS — le rouge est mesuré, pas relu

Une sonde qui rend 0 et rend 0 aussi sur le cas défectueux ne prouve rien. Le
même programme, sur le jeu que ce lot retire :

```bash
uv run python scripts/verifier_les_ancrages.py --chroma-host "$CH" --nebula-host "$NB" \
    tests/fixtures/golden_qa_generated.json      # le jeu du 3 août 2026
```

`mesuré` le 8 septembre 2026 : **`rc=1`**, **0 / 129** dans le graphe et
**0 / 129** dans ChromaDB, chaque ancrage nommé. C'est la reproduction exacte du
constat du §4.3 du 3 septembre 2026, cinq jours plus tard, par un autre
instrument.

**Les deux stores sont interrogés, et ce n'est pas une redondance.**
`retrieved_element_ids` sort des métadonnées de l'index vectoriel : c'est
ChromaDB qui décide du rappel, le graphe ne servant qu'à la reconstruction de
contexte. Or les deux populations diffèrent — **15 196** sommets au graphe contre
**3 750** `element_id` distincts dans l'index. Un ancrage présent au graphe et
absent de l'index a l'air bon et **ne peut jamais être trouvé** : c'est le pire
des deux cas, et il n'est visible qu'en interrogeant les deux.

---

## 3. Le jeu régénéré — comment, et ce qu'il porte

```bash
CH=$(docker inspect -f '{{.NetworkSettings.Networks.rag_network.IPAddress}}' \
     rag-ingestion-pipeline-chromadb-1)
uv run python scripts/generate_golden.py --count 130 --seed 42 \
    --chroma-host "$CH" --chroma-port 8000 \
    --out tests/fixtures/golden_qa_generated.yaml
```

`mesuré` le 8 septembre 2026, `rc=0` :

| | |
|---|---|
| passages exploitables lus | **1 266** sur **4 367** chunks |
| documents porteurs | **23 sur 23** — aucun document du corpus n'est absent du jeu |
| candidats tirés (graine 42) | **234** |
| questions générées | **130**, plus **8** sans réponse = **138** |
| rejetées par les garde-fous du générateur | **36** |
| par langue de la question | **93** anglaises, **45** françaises |
| par type | **89** factuelles, **41** factuelles-translinguistiques, **8** sans réponse |
| relues par un humain | **8** sur 138 — les seules `unanswerable`. **`reviewed: false` sur les 130 autres : c'est du SILVER** |

**L'axe translinguistique est coupé en deux, et cela ne dépend pas de ce dépôt.**
Le corpus est entièrement anglais (`mesuré` : 4 367 / 4 367 en `language: en`),
donc « question française → document anglais » est mesurable — 41 questions — et
« question anglaise → document français » a disparu avec le corpus français.
La borne est celle que le pipeline publie ; elle est reprise ici et non remesurée
comme si elle était de ce côté-ci.

**Le jeu inscrit désormais l'index contre lequel il a été écrit** — chunks,
passages exploitables, documents porteurs, langues du corpus. Un jeu qui ne le
dit pas ne peut pas être déclaré périmé, et c'est exactement ce qui est arrivé au
précédent.

---

## 4. LE CONTRÔLE — les 30 questions du pipeline, et c'est le résultat qui compte

```bash
uv run python scripts/evaluate.py --api http://localhost:8011 \
    --golden tests/fixtures/jeu_de_questions_pipeline.yaml \
    --out runs/2026-09-08-controle-30.json
```

`mesuré` le 8 septembre 2026, 08:12:58 → 08:17:40 UTC, `rc=0`, 30 questions
abouties sur 30.

| | `mesuré` |
|---|---|
| `rappel_recherche` (macro, sur les 26 questions à réponse) | **0,801** |
| `rappel_elements` — a atteint le LLM | **0,686** |
| `mrr` | **0,770** |
| `rappel_documents` | **0,962** |
| `abstention_correcte` | **1,000** — **4 sur 4** |
| `taux_citation_complete` | **1,000** |
| `rappel_contexte` — l'or dans le contexte payé, fenêtre du graphe comprise | **0,712** sur 26 questions |
| `taux_contexte_utile` | **0,315** |
| `part_utile_caracteres` | **0,306** |
| `total_ms` p50 / p95 | **8 326** / **16 411** |

### Par strate, et voici la table qui décide de la lecture

Les deux colonnes `micro` et `au moins un` sont **`calculé`**, dérivées des
lignes par question de `runs/2026-09-08-controle-30.json` ainsi — même
dérivation que celle du pipeline, ce qui rend les deux tables comparables :

- `micro` = `somme(round(rappel_recherche × attendus)) / somme(attendus)` ;
- `au moins un` = `compte(rappel_recherche > 0) / n`.

```bash
uv run python - runs/2026-09-08-controle-30.json \
    tests/fixtures/jeu_de_questions_pipeline.yaml <<'EOF'
import collections, json, pathlib, sys, yaml
camp = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
jeu = yaml.safe_load(pathlib.Path(sys.argv[2]).read_text(encoding="utf-8"))
att = {q["id"]: len(q.get("gold_element_ids") or []) for q in jeu["questions"]}
par = collections.defaultdict(lambda: [0, 0, 0, 0])
for r in camp["questions"]:
    n = att[r["id"]]
    if not n:
        continue
    s = par[r["type"]]
    rr = r["rappel_recherche"] or 0.0
    s[0] += 1; s[1] += round(rr * n); s[2] += n; s[3] += 1 if rr > 0 else 0
for strate, (n, tr, ex, au) in sorted(par.items()):
    print(f"{strate:16s} n={n:3d}  {tr:3d}/{ex:3d} = {tr/ex:6.1%}   au moins un {au}/{n}")
EOF
```

| Strate | n | `rappel_recherche` macro (`mesuré`) | micro (`calculé`) | au moins un (`calculé`) |
|---|---|---|---|---|
| `simple` | 8 | **1,000** | **8 / 8 = 100,0 %** | **8 / 8** |
| `multi_passages` | 12 | 0,736 | 22 / 31 = 71,0 % | 11 / 12 |
| `de_suivi` | 4 | 0,875 | 4 / 5 = 80,0 % | 4 / 4 |
| `reformulee` | 2 | **0,250** | **1 / 3 = 33,3 %** | 1 / 2 |
| `sans_reponse` | 4 | — | — | — (abstention **4 / 4**) |
| **toutes à réponse** | **26** | **0,801** | **35 / 47 = 74,5 %** | **24 / 26** |

**Trois lectures, et aucune n'est une décision de réglage.**

**Le plancher de contrôle tient : 8 sur 8 à `simple`, et 4 sur 4 à
l'abstention.** C'est ce que ces deux strates existent pour dire, et c'est la
preuve que la chaîne fonctionne de bout en bout — extraction, découpage, encodage,
indexation avec métadonnées, recherche hybride, reranking, reconstruction par le
graphe, citation, et refus quand le corpus est muet.

**La strate `reformulee` est le point bas, et à `n = 2` on ne peut rien en
dire.** Une question sur deux échoue : c'est **une** question. La réserve du jeu
s'applique à la lettre, et un `n = 2` ne supporte aucune conclusion. La seule
chose qu'on puisse écrire est celle-ci : *si un défaut existe sur les questions
reformulées, ce jeu ne peut pas le distinguer du bruit ; il faudrait une strate
peuplée.* La question échouée est `q29` — « How do I stop the assistant from
wandering off… », dont le passage parle de `guardrails` sans qu'aucun mot de la
question n'y figure.

**`multi_passages` à 71,0 % micro pour 11/12 « au moins un »** dit exactement où
est la difficulté : l'agent trouve presque toujours *un* des passages attendus, et
rarement *tous*. Avec `RERANK_TOP_K=10` et trois ancrages sur certaines questions,
c'est le comportement attendu d'une coupe à 10, pas un défaut identifié.

### Ce que ces chiffres ne sont PAS : le plancher du pipeline

Le pipeline publie un plancher de rappel **recherche vectorielle seule**, question
encodée **sans son historique** — site canonique et seul endroit où ces chiffres
vivent :
`rag-ingestion-pipeline/documentation/campagnes/2026-09-02-premiere-campagne-de-reference.md`,
qui les donne à `k = 5`, `10` et `20` et les étiquette `calculé`.

**Ce n'est pas une cible, et la comparaison des totaux n'a pas de sens** : quatre
choses diffèrent **à la fois** entre les deux mesures — BM25 en plus du dense, un
reranking par cross-encoder, une recherche menée aussi dans la traduction de la
question, et le `chat_history` **transmis** à l'agent. Aucun écart ne peut donc
être attribué à l'une d'entre elles. Les deux tables sont mises côte à côte pour
une seule raison : **la strate `de_suivi`**, où le mécanisme est nommé et
prévisible.

| Strate, à `k = 10` | pipeline — dense seul, question seule | **ici** — hybride + rerank, historique transmis |
|---|---|---|
| `simple` | 100 % | **100,0 %** |
| `multi_passages` | 58,1 % | **71,0 %** |
| `reformulee` | 66,7 % | **33,3 %** — soit **une** question, `n = 2` |
| `de_suivi` | **20,0 %** | **80,0 %** |
| toutes | 61,7 % | **74,5 %** |

**La strate `de_suivi` se comporte comme le pipeline l'avait annoncé, et c'est la
seule ligne de cette table qui vaut une lecture.** Le pipeline mesure 20 % parce
que son script encode la question **seule** — « Et laquelle des trois demande un
identifiant de plus ? » ne porte, hors contexte, presque aucun signal — et il a
mesuré **60 %** en concaténant l'historique. Ce n'est pas un défaut de l'index,
c'est le périmètre de sa mesure ; la résolution de l'antécédent est le travail de
l'agent. `evaluate.interroger` **transmet** `chat_history` à `POST /answer`, donc
cette strate mesure ici ce travail-là, et elle rend **80 %**. Les deux chiffres ne
sont pas comparables comme des deltas ; ce qui est vérifié est la **direction**
annoncée de l'autre côté.

**Et la ligne `reformulee` va dans l'autre sens.** 33,3 % ici contre 66,7 % chez
le pipeline : le chemin plus riche fait **moins bien** sur cette strate. À
`n = 2`, c'est du bruit par construction et je n'en tire rien — mais je l'écris,
parce qu'un lot qui ne publierait que les lignes favorables ne publierait pas une
mesure.

---

## 5. LA RÉFÉRENCE — les 138 questions régénérées

```bash
uv run python scripts/evaluate.py --api http://localhost:8011 \
    --golden tests/fixtures/golden_qa_generated.yaml \
    --out runs/2026-09-08-reference.json
```

`mesuré` le 8 septembre 2026, 07:48:59 → 08:12:58 UTC, `rc=0`, **138 questions
abouties sur 138**, aucun échec.

| | `mesuré` |
|---|---|
| `rappel_recherche` (macro, 130 questions à réponse) | **0,962** |
| `rappel_elements` | **0,954** |
| `mrr` | **0,942** |
| `rappel_documents` | **1,000** |
| `abstention_correcte` | **1,000** — **8 sur 8** |
| `taux_citation_complete` | **1,000** |
| `rappel_contexte` | **0,946** sur 130 questions |
| `taux_contexte_utile` | **0,273** |
| `part_utile_caracteres` | **0,281** |
| `contextes_ecartes_total` | **26** |
| `generations_au_plafond` | **0** sur 138, `num_predict` = 4096, `eval_count` max **755** |
| `total_ms` p50 / p95 | **7 298** / **29 166** |

| Strate | n | `rappel_recherche` macro (`mesuré`) | micro (`calculé`) | au moins un (`calculé`) |
|---|---|---|---|---|
| `factuelle` | 89 | 0,944 | 84 / 89 = 94,4 % | 84 / 89 |
| `factuelle-translinguistique` (question FR → doc EN) | 41 | **1,000** | **41 / 41 = 100,0 %** | **41 / 41** |
| `sans-reponse` | 8 | — | — | — (abstention **8 / 8**) |
| `questions de suivi` | **0** | — | — | **STRATE VIDE**, et la campagne le dit en clair |

Les cinq questions jamais trouvées : `G-005`, `G-024`, `G-096`, `G-101`, `G-112`
— toutes anglaises et factuelles. Une sixième, `G-053`, a été trouvée par la
recherche puis **écartée avant le LLM** : deux échecs distincts, et le second
appelle un meilleur reranking ou plus de sources, pas un meilleur retrieval.

### Ce que ce 0,962 vaut, et il faut le borner tout de suite

**Il ne dit pas que le système répond bien à 96 % des questions.** Il dit que
l'instrument de réglage a un plancher haut, et c'est ce qu'on lui demande : un
jeu dont le rappel serait déjà bas n'aurait pas de marge pour montrer une
dégradation.

**La strate translinguistique à 41/41 est le meilleur exemple de cette
auto-référentialité.** Une question française écrite *depuis* un passage anglais
par un modèle multilingue partage avec ce passage un vocabulaire technique que le
modèle a lui-même choisi. Le rappel parfait mesure cette parenté au moins autant
qu'une capacité translinguistique du retrieval. **La seule question française
écrite à la main du corpus** — `q30` du jeu de contrôle, « Pourquoi une recette
de cuisine sert-elle à expliquer… » — rend `0,500` sur ses deux ancrages. À
`n = 1`, on ne compare rien ; on constate que les deux instruments ne disent pas
la même chose au même endroit, et qu'**une seule question française relue est un
effectif sur lequel rien ne se décide.**

### La mesure qui borne l'auto-référentialité, et elle renverse la lecture facile

L'écart brut entre les deux jeux est de **21,7 points** de rappel micro
(96,2 % contre 74,5 %). Il serait tentant d'en conclure que le jeu généré est
« gonflé de 22 points ». **C'est faux, et voici la mesure.** Les deux jeux ne
posent pas des questions de même difficulté : 12 des 26 questions à réponse du
jeu de contrôle ont **plusieurs** ancrages, quand les 130 du jeu régénéré en ont
**exactement un**. En neutralisant cette différence — `calculé` depuis les deux
fichiers de campagne, questions à **ancrage unique** seulement :

| | n | micro (`calculé`) | au moins un (`calculé`) |
|---|---|---|---|
| contrôle 30, écrites à la main | **12** | **11 / 12 = 91,7 %** | 11 / 12 |
| référence 138, générées depuis le passage | **130** | **125 / 130 = 96,2 %** | 125 / 130 |
| *contrôle, ancrage unique **et** question autonome* | *9* | *8 / 9 = 88,9 %* | *8 / 9* |

**L'écart tombe de 21,7 à 4,5 points**, soit — à `n = 12` — **une** question.
La conclusion honnête est donc : *la majeure partie de l'écart entre les deux
instruments est la difficulté multi-passages du jeu écrit à la main, pas son
auteur.* L'effet d'auto-référentialité est au plus de quelques points, et
l'effectif disponible **ne permet pas de le distinguer du bruit**. Il reste réel
comme raisonnement — la question est écrite pour son passage — et il justifie de
garder les deux jeux ; il ne justifie pas de chiffrer un abattement.

---

## 6. Ce que la campagne établit d'autre

### Les métriques de recherche sont DÉTERMINISTES, et c'est mesuré

La campagne de contrôle a tourné **deux fois** le 8 septembre 2026, à 35 minutes
d'intervalle, sur le même index : `rappel_recherche` **0,801**, `rappel_elements`
**0,686**, `mrr` **0,770**, `rappel_documents` **0,962**, `rappel_contexte`
**0,712**, `taux_contexte_utile` **0,315**, `contextes_ecartes_total` **8** — les
deux fois, à la troisième décimale.

**La génération, elle, ne l'est pas** : `citations_par_reponse` a rendu **3,8**
puis **3,5**. C'est la bonne répartition, et elle décide de ce qui se compare :
un écart de recherche entre deux campagnes est un résultat, un écart de citations
peut être du modèle.

### Les latences, et pourquoi elles ne s'apparient pas

`rerank_ms` p50 **498** / p95 **2 943** sur la référence, `translation_ms` p50
**1 215**, `dense_ms` p50 **120**, `lexical_ms` p50 **56**, `reconstruction_ms`
p50 **114**, `generation_ms` p50 **4 682** / p95 **14 858**. Le résidu que nul
étage ne réclame est de **18 ms** en p50.

**Ces chiffres décrivent CETTE machine à CE moment**, partagée avec deux autres
piles Docker dont un second Ollama. `evaluate.py` exclut délibérément les
latences des métriques appariées : un écart apparié de latence mesurerait la
charge du moment et le test des signes lui donnerait une p-value, donc un air de
résultat là où il n'y a que du bruit d'ordonnancement.

### La strate d'abstention atteint son cas, et ce n'est pas gratuit

`abstention_correcte` = **1,000** des deux côtés (8/8 et 4/4). Un « sans
réponse » dont la réponse serait dans le corpus mesurerait l'inverse de ce qu'il
annonce. `mesuré` le 8 septembre 2026, balayage lexical des 4 367 chunks sur les
termes distinctifs des 8 questions du jeu régénéré : **0 chunk ne répond à
aucune des huit.** Deux termes ont un porteur, et les deux sont incidentels — ils
sont nommés ici pour que personne n'ait à refaire la lecture :

- `legal team` → `0c76abce09`, *AI Governance* : « …protect their bottom line,
  not just their legal team » — aucun effectif ;
- `tokyo` → `d71f8b0cd6`, *Evaluating GenAI Applications with MLflow* : un exemple
  de requête « My flight UA217 was delayed in Tokyo » dans un jeu d'évaluation —
  aucun bureau, aucun effectif.

**La borne, et elle est nette : les 4 questions françaises sans réponse du jeu
régénéré sont FACILES**, parce que le corpus est entièrement anglais. Elles ne
valent pas le test d'abstention du jeu de contrôle, dont la plus dure — `q24`,
le nombre de pages du manuel Samsung — a pour plus proche voisin vectoriel
**précisément le passage qui mentionne ce manuel**. C'est cette question-là qui
mesure l'abstention ; les quatre françaises mesurent surtout l'absence du sujet.

---

## 7. `detect-secrets` — mesuré avant de commiter, et un garde de ce lot y a été pris

Ce dépôt est **public** et ce lot produit des fichiers de données. La mesure a
donc été faite **avant** le commit, avec la version que le dépôt jumeau arme :

```bash
git ls-files -z | xargs -0 detect-secrets-hook   # v1.5.0
```

| | `mesuré` le 8 septembre 2026 | détail |
|---|---|---|
| à `main` = `4eedb2a` | **36** détections | **34** dans le seul `tests/fixtures/golden_qa_generated.json`, plus 2 antérieures à ce chantier |
| après ce lot | **2** détections | `documentation/capture_usage.md:402` et `tests/unit/test_context_assembly.py:95` — les deux antérieures, aucune de ce lot |

`detect-secrets` **n'est pas armé** sur ce dépôt, et `.pre-commit-config.yaml`
dit pourquoi : l'armer demande sa propre mesure, qui n'a jamais été faite ici.
Ce lot ne l'arme pas ; il le rend **armable**, ce qu'il n'était pas — 34
détections dans un fichier de données auraient bloqué le premier commit venu, et
c'est ainsi qu'on apprend à passer `--no-verify`.

**AUCUNE des 36 ni des 2 ne masque un secret.** Les 34 étaient des `element_id`
— dix hexadécimaux dérivés du contenu d'un passage public, exigence 2 du contrat.

### Et un garde de ce lot avait rajouté 6 détections

**Mesuré, et corrigé.** `empreinte_des_ancrages` s'écrit dans un fichier JSON, où
aucun `pragma: allowlist secret` n'est possible — le JSON n'admet pas de
commentaire. Une empreinte de 64 hexadécimaux en valeur de mapping est exactement
ce que le détecteur relève : **6** détections, les deux campagnes de ce lot et les
quatre campagnes synthétiques de `tests/fixtures/`. *Le lot faisait tomber
l'inventaire de 36 à 2 d'un côté et en rajoutait 6 de l'autre.*

`mesuré` le 8 septembre 2026, même valeur sous trois formes :

```
{"empreinte_des_ancrages": "59ed79…6806"}          -> rc=1, 1 détection
{"empreinte_des_ancrages": "sha256:59ed79…6806"}   -> rc=0
{"empreinte_des_ancrages": "ancrages-sha256-59…"}  -> rc=0
```

Le détecteur exige que la chaîne **entière** soit hexadécimale : le préfixe la
disqualifie, et il ne cache rien — il **nomme** l'algorithme, ce que la valeur
nue laissait deviner. L'empreinte est donc `sha256:<64 hexadécimaux>`, et
`test_comparaison_appariee.test_l_empreinte_ne_se_lit_pas_comme_un_secret`
refuse qu'elle redevienne une chaîne purement hexadécimale.

**Les empreintes des deux campagnes ont été recalculées, pas retouchées.**
`empreinte_des_ancrages` est une fonction **pure** du jeu de questions : la
valeur écrite est exactement celle que le script produit, et elle se rejoue sans
relancer la campagne —

```bash
uv run python -c "
import importlib.util, pathlib
s = importlib.util.spec_from_file_location('e', 'scripts/evaluate.py')
e = importlib.util.module_from_spec(s); s.loader.exec_module(e)
print(e.empreinte_des_ancrages(e.charger_questions(
    pathlib.Path('tests/fixtures/golden_qa_generated.yaml'))))"
```

### Le format des deux jeux de questions, pour la même raison

| Le fichier | `mesuré` |
|---|---|
| `tests/fixtures/golden_qa_generated.json` — le jeu retiré | `rc=1`, **34** détections |
| les deux jeux de ce lot, en YAML | **`rc=0`** |
| `jeu_de_questions_pipeline.yaml` **privé de son pragma** | `rc=1`, **1** détection, ligne 26 — l'empreinte de provenance |

La cause a son **site canonique chez le pipeline**, en tête de
`documentation/campagnes/2026-09-02-jeu-de-questions.yaml`, qui l'a mesurée le
3 septembre 2026 : son transformateur YAML rend les **valeurs de mapping** et pas
les **éléments de séquence**. Les `element_id` d'un jeu de questions vivent en
éléments de séquence ; l'empreinte de provenance est une valeur de mapping, d'où
l'unique pragma du fichier. Et `yaml.safe_dump` n'écrit pas de commentaire : le
pragma posé dans le script y **restait**, ce que la troisième ligne du tableau a
mesuré. C'est `adopter_le_jeu_du_pipeline.poser_le_pragma` qui l'émet.

---

## 8. Ce que cette campagne ne mesure pas

- **la qualité des réponses.** Aucun juge, par décision : un juge LLM non
  confronté à une vérité terrain produit une opinion. `taux_citation_complete` dit
  que chaque citation nomme son document et situe le passage — pas que la réponse
  est juste ;
- **la strate de suivi sur le jeu de réglage.** Elle est **vide**, et la campagne
  l'imprime en clair plutôt que d'afficher une moyenne sur zéro question.
  `generate_golden.py` n'écrit aucun `chat_history`. Les quatre questions du jeu
  de contrôle la peuplent, et quatre questions ne règlent rien ;
- **l'axe « question anglaise → document français ».** Il a disparu avec le
  corpus français, et le rétablir demanderait une ingestion — interdite à ce lot ;
- **une comparaison avec quoi que ce soit d'avant le 2 septembre 2026.** Elle est
  impossible, et ce n'est pas une perte qu'on choisit : elle est déjà consommée ;
- **l'ablation du graphe.** `taux_contexte_utile` et `part_utile_caracteres` sont
  les seules métriques qu'elle déplacerait, et elles sont désormais mesurées avec
  leur dénominateur — mais l'ablation n'a pas été faite ;
- **le flux interactif.** `evaluate.py` passe par `POST /answer`. `/chat/resume`
  et la sélection par l'utilisateur ne sont pas dans le chemin mesuré.

---

## 9. Rejouer cette campagne

```bash
make verifier-les-ancrages   # l'ANTÉCÉDENT — rc=1 si un ancrage a disparu
make eval                    # réglage,  comparé APPARIÉ à 2026-09-08-reference.json
make eval-controle           # contrôle, comparé APPARIÉ à 2026-09-08-controle-30.json
```

Les deux cibles d'évaluation **dépendent** de la vérification : l'ordre est porté
par le `Makefile` et non par la mémoire de celui qui lance la campagne.

`make eval` comparé à cette campagne-ci rendra des deltas nuls et une p-value de
1,0 : c'est l'état normal d'une référence qui vient d'être posée. La comparaison
**refuse** de tourner, code **2**, si les deux jeux divergent, si la référence ne
porte pas la même `empreinte_des_ancrages` — ou n'en porte pas du tout — ou si le
fichier visé n'existe pas.

**L'empreinte de cette campagne** est inscrite dans les deux fichiers de `runs/`,
champ `empreinte_des_ancrages`. Elle change avec le corpus et **ne change pas**
avec une reformulation de question, ce qui est exactement le comportement
qu'une comparaison appariée demande.
