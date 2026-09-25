# L'état du projet au jour du livrable

**Date du livrable : 25 septembre 2026.** Base `origin/main` = `e1324e4`, code
servi `97bba20` (publié par `/health`, `mesuré` à 08:10 UTC).

Ce document dit **ce qui marche et par quelle mesure on le sait**, puis **ce qui
ne marche pas, ce qui n'est pas mesuré, et les limites connues**. Il est écrit
pour être lu seul.

> **AUCUN CHIFFRE N'EST CRÉÉ ICI.** Chacun est repris de son **site canonique** —
> une section du registre [axes_amelioration.md](axes_amelioration.md), ou une
> ligne du journal des conversations de
> [pilotage_du_chantier.md](pilotage_du_chantier.md) §6.1 — et le renvoi est
> écrit à côté. Rien n'est arrondi sans que l'arrondi soit dit. Quand deux sites
> mesurent la même grandeur autrement, **les deux sont publiés avec leur
> définition** : c'est la seule façon de ne pas les confondre.

---

## 1. Ce qui marche

### 1.1 La chaîne répond, et le code servi est identifié

`mesuré` le **25 septembre 2026 à 08:10 UTC**, `curl -s http://localhost:8011/health`
(HTTP 200). Les quatre dépendances sont vertes — base vectorielle, graphe, index
lexical, modèle —, `services_unknown` est vide, le moteur servi est `vllm`
`0.28.0` avec une fenêtre de `32768`, et `code_servi.etat` vaut `identifie`
(sha `97bba20`, image construite le 25 septembre à 00:35:52 UTC).

Ce n'est pas rien : `/health` sait distinguer le modèle **demandé** du modèle
**servi**, et sait déclarer une image `anonyme` quand elle n'a pas été
construite par `make image` — [identite_du_code_servi.md](identite_du_code_servi.md),
[moteur_llm.md](moteur_llm.md).

### 1.2 La porte qualité est verte

`mesuré` le **25 septembre 2026, trois fois entre 08:30 et 08:37 UTC**, arbre
détaché sur `e1324e4`, environnement monté par le protocole du §2.2 du journal,
**les cinq fichiers de ce lot suivis par git** — sans quoi les gardes qui lisent
`git ls-files` ne les verraient pas. `rc` de **`make`**, relevés dans des
variables : `rc_lint = 0`, `rc_test = 0`, **1263 passés** (124 s au relevé du lot 40, 128,9 s à celui de la VÉRIF-40). Les trois
relevés sont identiques. C'est le compte que [tests.md](tests.md) annonce — 1263 tests sur 61
fichiers, `mesuré` le 25 septembre à 07:47 UTC — et le même que la ligne **91**
du journal publie pour LOT-39.

### 1.3 Le rappel, sur les trois jeux

**Il y a trois jeux de questions, et aucun des trois ne remplace les deux
autres.** Ils ne mesurent pas la même chose, et c'est pourquoi ils coexistent.

| Jeu | Effectif | Ce qu'il sait mesurer |
|---|---|---|
| `golden_qa_generated.yaml` — **réglage** | 138 questions, dont **130** portent un ancrage, **un seul** chacune (§4.67) | Classer deux configurations. **Aveugle à la sélection** : cf. plus bas |
| `jeu_de_questions_pipeline.yaml` — **contrôle** | 30 questions, dont **26** portent des ancrages, **47** ancrages (1 à 3 chacune) (§4.67) | Contredire le générateur : il est écrit à la main, après l'ingestion |
| `jeu_ancrages_disperses.yaml` — **dispersion** | **60** questions, **120** ancrages (2 par question, 2 sections distinctes), **109** distincts (§4.76, journal l. 88) | Voir le quatrième étage : une seule section reconstruite ne suffit pas |

#### a. Le rappel au prompt, par `AUTO_SELECT_TOP_K` — site canonique §4.67

*« Le contenu de l'ancrage est-il réellement dans le markdown soumis au modèle ? »*
Au défaut `k = 3` :

| Jeu | rappel au prompt | IC 95 % (Wilson) | questions | ancrages |
|---|---|---|---|---|
| réglage (130 q) | **0,9538** | [0,903 – 0,979] | 124 | 124/130 |
| contrôle (26 q) | **0,7308** | [0,539 – 0,863] | 19 | 26/47 |

**Ce que les bascules disent, et c'est là que l'écart se lit** (§4.67) : sur le
jeu de réglage, `k=1 → k=2` gagne **+4 questions, 0 perdue**, et **toutes les
autres transitions rendent +0, −0** — passer de 3 à 6 ne gagne aucune question,
de 3 à 10 non plus. Sur le contrôle, de 3 à 6 : **+1 question sur 26** et
**+2 ancrages sur 47** ; de 3 à 10 : **+2 questions** et **+7 ancrages**. Les
intervalles se recouvrent, et le jeu porte sa propre réserve : *un écart de deux
points est du bruit.* **Sur les huit transitions des deux jeux, aucun ancrage
et aucune question n'est perdu quand `k` monte** — borné à ces huit transitions,
ces deux jeux, cette campagne.

#### b. Le jeu dispersé : questions dont **tous** les ancrages arrivent — §4.76, journal l. 88

De `k=1` à `k=10` : **0, 2, 6, 7, 7, 7, 8, 8, 9, 10** — **+10 gagnées, 0 perdue**.
Le même banc sur le jeu de réglage rend **+0 à toutes les bascules après k=2** :
le plateau était une propriété du **jeu**, non du banc. Éléments au prompt, en
moyenne : **33,48** à k=3, **102,5** à k=10.

#### c. Ancrages dans le top-10 du reranker, les trois jeux ensemble — §4.79

C'est la grandeur que les trois derniers lots partagent, sous la variante de
**production**. *Ancrages / questions complètes.*

| | dispersé (60 q, 120 anc.) | contrôle (26 q, 47 anc.) | réglage (130 q, 130 anc.) |
|---|---|---|---|
| production (`unique_avec_traduction`) | 53 / **7** | 33 / **14** | 127 / **127** |

### 1.4 Le plafond de récupération est identifié — site canonique §4.77

**Il n'est ni l'index, ni la profondeur seule, ni le reranker : c'est la
REQUÊTE.** Le lot a d'abord retrouvé sa base — à profondeur de production
(`FETCH_K=50`, `RETRIEVAL_TOP_K=50`, `RERANK_TOP_K=10`), **56 / 46 / 67**
ancrages absents du dense, de la fusion et du top-10 du reranker, *les trois
chiffres du §4.76 à l'unité* —, et le recoupement est **une intersection, pas un
accord de comptes** : les 120 triplets de rangs sont identiques un à un.

| profondeur | ancrages au **top-10 du reranker** / 120 |
|---|---|
| **50** *(production)* | **53** |
| 200 | **64** |
| 1000 | **62** |

De 50 à 200 : **+11**. De 200 à 1000 : **−2**. *Donner mille candidats au
cross-encoder ne fait pas mieux que lui en donner deux cents.*

**Trois hypothèses tranchées** (§4.77) :

- **l'index est hors de cause** — 109/109 ancrages indexés, 0 émietté, 109/109
  portent leur preuve, trois détecteurs doublés par des témoins qui voient ;
- **la profondeur est réelle et bornée** — à seuil constant, +11 puis −2 ;
- **l'oracle `preuve` ramène 120/120** : *aucun ancrage n'est hors d'atteinte du
  classement* — borné à ce jeu et à cette campagne.

**Le tableau des causes somme à 120** : arrive **53**, écarté par le reranker
**21**, profondeur qui récupère **13**, profondeur insuffisante **31**, requête
unique **2**, hors base vectorielle **0**, texte indexé **0**, non expliqué **0**.

### 1.5 La décomposition de la requête, mesurée — §4.78 (sans traduction) et §4.79 (avec)

La question est découpée en **au plus trois** sous-questions par le modèle, qui
**ne voit ni les passages ni le nombre de besoins** ; chaque sous-question passe
par la récupération de production ; les listes sont fondues par le `fuse` de
`src/` au même `RRF_K` ; le reranker score contre la question entière **ou** par
sous-question, chaque candidat gardant son **meilleur** score.

**Les sept variantes sur les trois jeux** — *ancrages / questions complètes*,
site canonique §4.79 :

| variante | dispersé | contrôle | réglage |
|---|---|---|---|
| `unique_avec_traduction` *(PRODUCTION)* | 53 / **7** | 33 / **14** | 127 / **127** |
| `unique_sans_traduction` *(base appariée)* | 57 / **6** | 33 / **14** | 125 / **125** |
| `fusion_rerank_entiere` | 60 / **8** | 33 / **14** | 124 / **124** |
| `fusion_rerank_sous_questions` | **72** / **19** | 33 / **14** | 124 / **124** |
| `fusion_traduite_rerank_entiere` | 59 / **6** | 33 / **14** | 125 / **125** |
| `fusion_traduite_rerank_sous_questions` | **72** / **18** | 33 / **14** | 125 / **125** |
| `fusion_question_traduite_decomposee` *(l'autre ordre)* | **73** / **19** | 33 / **14** | **127** / **127** |
| *oracle `decomposition` du §4.77 (borne)* | *86 / **28*** | — | — |

Trois faits en sortent, et ils sont écrits à leur site :

1. **Le gain sur le jeu visé est réel** : 7 → 19 questions complètes, soit
   **68 % de la borne de l'oracle** (§4.78), et **c'est le reranking par
   sous-question qui décide** — +11 à liste fusionnée identique.
2. **La traduction ne gagne rien sur le jeu qu'elle vise** — monolingue anglais —
   mais **elle ferme presque toute la perte du jeu de réglage** : 125 contre 124,
   et 127 pour l'autre ordre, *le chiffre de la production* (§4.79).
3. **L'écart à la borne n'est pas 28 − 19 = 9** : c'est **11 manquées et 2
   gagnées hors borne**, dont **6 à la fusion**, 4 au reranking, 1 jamais
   récupérée (§4.79). L'imputation du §4.78 sur `G-119` **était fausse**, et le
   §4.79 la corrige à son site.

### 1.6 Les coûts, mesurés

**Le quatrième étage, `AUTO_SELECT_TOP_K` de 3 à 6** — site canonique §4.66,
six questions distinctes, `prompt_tokens_reliable` vrai aux douze appels :
prompt médian **2358 → 4224** jetons, durée totale médiane **9 712 → 13 970 ms**
(**+44 %**), citations cumulées **34 → 55** (en hausse 6 fois sur 6). **Le
budget n'écarte rien, ni à 3 ni à 6** : le plus gros prompt mesuré vaut **4849**
jetons contre une fenêtre servie de **32768**, soit **15 %**.

**La décomposition** — sites canoniques §4.78 (journal l. 90) et §4.79 :

| | médiane | p95 |
|---|---|---|
| appel de décomposition (§4.79, les trois jeux) | **826 – 1322 ms** | 1734 – 2338 ms |
| traduction d'une sous-question (§4.79) | **429 – 587 ms** | 996 – 1029 ms |
| récupération des sous-questions + fusion, jeu dispersé (§4.79) | **102 ms** *(contre 177 ms en production)* | 1130 ms |
| reranking par sous-question, jeu dispersé, en `cpu` (§4.79) | **1322 ms** *(contre 704 ms sur la question entière)* | 4105 ms |

**Le prix est en paires scorées, et il est publié** (§4.79) : le reranking par
sous-question coûte **×1,60 à ×2,03** selon le jeu ; l'autre ordre **×2,51 à
×4,03**. **La variante traduite ne coûte pas une paire de plus** que celle du
§4.78 — la traduction agit sur la récupération, jamais sur le nombre de
candidats à scorer.

### 1.7 La réingestion du pipeline est vérifiée conforme

**`mesuré` le 25 septembre 2026 à 06:17 UTC**, code servi `97bba20`, après la
purge et la réingestion menées par `rag-ingestion-pipeline`. Site canonique : le
journal, ligne **« LE VERDICT D'APRÈS LA CAMPAGNE DU PIPELINE »** du §6.1, entre
les lignes 90 et 91.

| Contrôle | Attestation d'avant (25 sept., 00:32–00:33 UTC) | Verdict d'après (06:17 UTC) |
|---|---|---|
| `POST /reindex` | — | **4367** chunks indexés |
| `make verifier-les-ancrages` | `rc=0`, **0 désaccord** | `rc=0`, **0 désaccord** |
| ancrages présents dans le graphe **et** dans la base vectorielle | 130/130, 44/44, 109/109 — **267** distincts | **identiques** |
| clés d'objets médias | **212**, SHA-256 `c91f5be6e24fbcba…` | **identiques** |
| graphe | **23** `Document`, **15 173** arêtes `PARENT_OF` distinctes | **identiques** |

Le pipeline date la fin de sa réingestion à **03:50:41 UTC** (23 runs `SUCCESS`,
`comparer` 23/23, **0 `element_id` déplacé**) : le relevé de 06:17 lui est donc
postérieur et **vaut verdict**. *Conforme sur les cinq contrôles.*

---

## 2. Ce qui ne marche pas, ou n'est pas mesuré

### 2.1 La décomposition est mesurée, et elle N'EST PAS implémentée

**C'est le point le plus important de ce document.** Les §4.78 et §4.79 sont des
**bancs** : ils appellent `retrieve`, `fuse` et `rerank` de `src/` *tels quels*
et relèvent un rang. **`src/` n'est pas touché**, vérifié aux deux lots (journal,
lignes 90 et 91), et les deux sections se terminent par la même phrase — *ce lot
ne propose aucun réglage et ne recommande rien.*

Autrement dit : **l'agent servi aujourd'hui ne décompose pas les questions.** Le
7 du tableau §1.5 est ce qu'il rend ; le 19 est ce qu'il rendrait si quelqu'un
écrivait le code, et ce code n'existe pas.

### 2.2 Aucune réponse n'est jugée en qualité

Borné à tout ce qui est publié aux §4.66 à §4.79 : **aucun des bancs ne génère
de réponse**, et ceux qui en génèrent ne la jugent pas.

- *Un ancrage au top-10 n'est pas une bonne réponse, et rien ici ne dit ce que
  le modèle fait du passage qui arrive* (§4.79, réserve 1).
- Le §4.66 mesure un **coût**, pas un **gain** : *plus de citations n'est pas
  une meilleure réponse.* C'est la raison écrite pour laquelle
  `AUTO_SELECT_TOP_K` **reste à 3**.
- Le §4.77 conclut : *aucun coût n'est mesuré, et aucune réponse n'est jugée*
  (journal, ligne 89).

Il n'existe **pas** de jeu de réponses de référence dans ce dépôt au
25 septembre 2026, ni de juge — ni humain, ni modèle.

### 2.3 Le banc tourne en `cpu`, le service en `cuda`

`mesuré` et **déclaré délibérément identique** aux §4.76 à §4.79, pour que les
chiffres des quatre lots se comparent. Les poids des deux modèles ont été
**sortis du conteneur servi** et confrontés octet pour octet à ceux du lot
précédent (`diff -rq`, aucun écart) : ce sont bien les mêmes poids. **Ce qu'un
écart d'arrondi flottant déplacerait dans l'ordre du reranking n'est pas
mesuré** (§4.79).

Conséquence directe sur les coûts : le §4.79 dit **combien de paires** chaque
variante ajoute ; il ne dit pas ce qu'elles coûteraient sur GPU. Le §4.78 relève
un p95 de **8 483 ms en `cpu`** pour le reranking par sous-question, et écrit que
le `cuda` du service n'est pas mesuré.

### 2.4 Les jeux ne sont pas relus, et le dispersé est monolingue

- **190 questions sur 228 ne sont pas relues** (`reviewed: false`) : 130 des 138
  du jeu de réglage et les 60 du jeu dispersé. Les **30** questions du jeu de
  contrôle sont écrites à la main et portent `reviewed: true`, ainsi que **8** du
  jeu de réglage (`mesuré` par `yaml.safe_load` le 25 septembre 2026, VÉRIF-40,
  recompté par le pilote). La réserve 8 du §4.79 disait « les trois jeux » : elle
  est corrigée au site.
- **Le jeu dispersé est monolingue anglais, et ce n'était pas voulu** (§4.76) :
  le générateur tirait **30 %** de questions françaises, le jeu en porte **0 sur
  60**. La cause est mesurée et elle est au site — le garde de vocabulaire
  partagé exige deux jetons communs avec chacun des deux passages anglais, et une
  question française n'en partage pas deux. **L'axe translinguistique est donc
  hors de portée de ce jeu**, ce qui explique aussi que la traduction n'y gagne
  rien (§1.5, fait 2).
- **La circularité est déplacée, pas supprimée** (§4.76) : la question reste
  écrite **pour** ses deux passages — **30 ancrages sur 120 sortent au rang 1 du
  reranker** —, et le juge de non-suffisance est **le modèle qui a écrit la
  question**. Les sous-questions des §4.78 et §4.79 sont écrites par ce même
  modèle : *la circularité est encore là, d'un cran plus loin* (§4.79, réserve 3).
- **60, 130 et 26 questions ne tranchent pas un réglage** (§4.79, réserve 8).

### 2.5 Le corps vide arrive au prompt, et il n'est pas réparé — §4.71

**Lire la section entière : elle porte deux corrections datées, et la première
lecture y était fausse.** Le chiffre à citer est celui du **24 septembre 2026,
15:02 UTC**, dans le conteneur servi : `reconstruct_section` sur les **172**
ancrages distincts des deux jeux rend **148** sections uniques, 0 échec, et
**1 751** éléments — dont **20 `code` vides sur 152** et **26 `list_item` vides
sur 289**.

**Les deux ne coûtent pas la même chose**, lu au site dans `_render_element` :
une puce vide rend une chaîne vide et **disparaît du markdown** ; un `code` vide
rend un bloc vide suivi d'un **marqueur `[src:ID]` citable qui ne cite rien** —
**20 sur 1 698** marqueurs. Les deux prennent une place de la fenêtre, qui se
compte en éléments **avant** le rendu : **46 places sur 1 751**.

**Ce qui a été retiré par le site lui-même, et qu'il ne faut donc pas reprendre
ailleurs :**

- les « **37 pertes sèches** » sur les puces vides **n'existent pas**
  (correction du 24 septembre 2026, décision du pipeline au message 29) : les
  202 puces vides **n'ont aucun enfant**, leur texte vit dans **727 fragments
  frères**, et il arrive donc déjà au prompt. Les **15 173** arêtes `PARENT_OF`
  partent toutes d'un `SectionHeader` (15 007) ou d'un `Document` (166),
  `mesuré` le 24 septembre à 14:49 UTC ;
- les sommets `Code` vides sont **les lignes blanches entre deux lignes de
  code** — 404 sur 404 examinés, **0 perte sèche prouvée** sur 1 362
  (correction du 23 septembre 2026, 14:05 UTC). *Leur « réparer » un texte
  inventerait du contenu ;*
- **le lot de la condition de candidature n'a plus d'objet** : faire rallonger
  une puce vide par les vecteurs **doublerait** au prompt un texte que ses
  frères y portent déjà.

**Ce qui reste, et c'est la seule chose à faire :** *la réparation juste
filtrerait AVANT le fenêtrage, et pas seulement au rendu* — le coût mesuré, 46
places sur 1 751, ne justifiait pas un lot à la date du site. Et **ce que le
modèle fait d'un bloc vide n'est pas mesuré.**

**Deux noms sont périmés dans la première moitié de la section, et elle le
dit** : la fonction s'appelle `_restore_full_text` et vit à
[`graph_context.py:852`](../src/agent/graph_context.py) — `git grep
_fill_full_texts -- src/` rend **0** (revérifié le 25 septembre 2026 à
08:32 UTC ; contrôle positif, `_restore_full_text` rend 2 lignes). Le seuil de candidature reste **dérivé** du plafond de troncature
(`graph_text_truncation`, défaut 2000, `graph_context.py:870`), alors que les
deux défauts n'ont rien à voir.

### 2.6 Les non bloquantes des audits, encore ouvertes

L'audit du lot 34 a rendu **rien de bloquant** et sept non bloquantes, inscrites
au **§4.74**. Le lot 35 a fermé la seule qui nommait une sortie fausse (constat
**E**, cf. §4.75). **Restent ouvertes**, et elles sont d'ordre méthodologique :

- **A** — une mesure étiquetée `mesuré` **sans date** dans un commentaire de
  `src/api/main.py` ;
- **B** — un « n'a jamais été atteinte sans injection » **non borné** au même
  site : l'audit l'a remesuré et il tient (0 sur 250), mais *un « jamais » reste
  une affirmation qui périme* ;
- **C** — les bancs des tableaux de coût du §4.74 sont **hors dépôt** et ne se
  rejouent pas : *ce qui n'est pas versionné n'existe pas* ;
- **D** — la barrière du lot 33 n'est défendue que par **son propre garde** ;
- **F** — un piège de relevé : `grep -rn '_sonder\b'` rend 58 lignes, dont une
  **fixture homonyme** ; les appelants de production sont **5** ;
- **G** — méthode : un détecteur de résidus mal posé rend des chiffres faux
  **dans les deux sens** — 18 résidus fabriqués sur la branche réparée, puis un
  « 55 sur 500 » retiré avant le rendu.

Le §4.75 laisse de son côté quatre choses non prouvées, dont **la fenêtre n'a
jamais été atteinte sans injection** — ni par l'audit 34 (4000 appels contre
32 957 fermetures concurrentes), ni par le lot, qui n'a pas rejoué ce banc
parce qu'il est **hors dépôt**.

### 2.7 Les réglages que rien ne tranche

- **`AUTO_SELECT_TOP_K` reste à 3** : le coût de 6 est connu et modéré, le gain
  ne l'est pas (§4.66, §4.76).
- **La profondeur reste à 50** : +11 ancrages au top-10 à 200, mais **aucun coût
  n'est mesuré** (§4.77).
- **`TRANSLATION_WEIGHT` vaut 1,0 sur ce poste** : ce que rendrait un poids
  moindre — que `settings.py` permet et que la docstring de `retrieve` décrit —
  **n'est pas mesuré** (§4.79, réserve 6).

### 2.8 Ce que ces mesures décrivent, et jusqu'à quand

**Les mesures ci-dessus décrivent l'état des stores du 25 septembre 2026,
4367 chunks** (§4.79, réserve 9). Le stockage d'objets bascule **ce jour-là**
vers un autre produit compatible S3 (§4.62) : les empreintes d'avant sont
versionnées dans [references/](references/) précisément pour qu'on puisse
comparer après, et le verdict du §1.7 dit que la réingestion les a rendues
identiques.

---

## 3. En une phrase

**La chaîne fonctionne et son plafond est nommé** — c'est la requête, pas
l'index —, **son levier le plus fort est chiffré et non implémenté** — la
décomposition, 7 → 19 questions complètes sur le jeu dispersé —, **et personne
n'a encore jugé une seule réponse.**

Les questions ouvertes, ordonnées par le coût de leur échec, sont dans
[prochaines_etapes.md](prochaines_etapes.md).
