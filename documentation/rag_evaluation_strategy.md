# Stratégie d'évaluation

## Le principe

Évaluer un RAG, ce n'est pas produire un score : c'est pouvoir répondre à
« cette modification a-t-elle amélioré quelque chose, et où ça casse-t-il ? »

Deux exigences en découlent, et elles structurent tout ce qui suit.

**Séparer les étages.** Un score global ne dit pas s'il faut changer le
retriever ou le prompt. Une réponse fausse a deux causes possibles : le passage
n'a pas été trouvé, ou il a été trouvé et mal exploité. `/answer` retourne les
contextes réellement soumis au LLM précisément pour permettre de trancher.

**Se méfier des juges.** Un juge LLM non confronté à une vérité terrain produit
une opinion, pas une métrique. Tout ce qui peut se mesurer sans lui doit se
mesurer sans lui — c'est déterministe, gratuit et reproductible.

## Deux outils, deux usages

| | `scripts/evaluate.py` | [RAG-Eval-Bench](https://github.com/floSa/RAG-Eval-Bench) |
|---|---|---|
| Rôle | Boucle courte | Campagne de fond |
| Métriques | Déterministes, sans LLM | + juges calibrés, comparaison appariée, intervalles de confiance |
| Coût | ~3 minutes | Heures de GPU |
| Quand | Après chaque changement | Avant de trancher entre deux architectures |

Le premier ne remplace pas le second. Il donne un chiffre tout de suite ; le
second dit si l'écart est significatif.

## La boucle courte

```bash
make eval                                    # compare, APPARIÉ, à runs/final.json
uv run python scripts/evaluate.py --golden tests/fixtures/golden_qa_generated.json \
    --out runs/essai.json --compare runs/final.json
```

Codes de sortie : `0` la campagne a abouti, `1` aucune question n'a abouti, `2`
la comparaison a été **refusée** — les deux jeux de questions diffèrent. La
campagne est écrite dans les trois cas.

Le script interroge `POST /answer` sur le jeu doré et calcule :

| Métrique | Ce qu'elle dit | Sans juge LLM ? |
|---|---|---|
| `rappel_recherche` | Le passage attendu est-il dans le classement du retrieval ? | oui |
| `rappel_elements` | A-t-il atteint le LLM ? | oui |
| `mrr` | Était-il deuxième, ou dix-huitième ? | oui |
| `rappel_documents` | Le bon document remonte-t-il ? Plus permissif. | oui |
| `taux_citation_complete` | Chaque citation nomme-t-elle son document et situe-t-elle le passage ? | oui |
| `abstention_correcte` | Le système admet-il son ignorance quand le corpus est muet ? | oui |
| `taux_contexte_utile` | Parmi les sections PAYÉES, quelle part porte un élément d'or ? | oui |
| `part_utile_caracteres` | Parmi les caractères PAYÉS, quelle part appartient à une section qui porte un élément d'or ? | oui |
| `rappel_contexte` | L'élément d'or est-il dans le contexte réellement soumis, fenêtre du graphe comprise ? | oui |
| `timings` | Quel étage coûte le temps ? Huit étages, plus le résidu — cf. § La décomposition du temps | oui |
| `contextes_ecartes` | Combien de sources n'ont pas tenu dans la fenêtre ? | oui |

Les résultats sont **stratifiés par langue**. Le corpus mêle français et
anglais : une moyenne globale masquerait un écart entre les deux.

## La précision du contexte

**Le rappel et le MRR mesurent le CLASSEMENT, et la reconstruction par le graphe
ne le change pas.** Elle change la COMPOSITION du contexte remis au LLM : une
fenêtre de ±6 éléments dans la section, ±3 dans les sections voisines, plus la
relecture du texte intégral depuis ChromaDB. Le rappel et le MRR sont donc
insensibles à une ablation du graphe **par construction** — mesurer « avec / sans
graphe » sur eux afficherait « aucun changement » sur le pari central du projet,
et cette conclusion serait un artefact de l'instrument, pas un résultat.

Trois métriques comblent le trou. Leur dénominateur est ce qui les rend justes,
et il vaut d'être écrit en entier.

| Métrique | Définition exacte |
|---|---|
| `taux_contexte_utile` | Sections retenues portant un élément d'or ÷ sections retenues |
| `part_utile_caracteres` | Caractères des sections retenues portant un élément d'or ÷ caractères des sections retenues |
| `rappel_contexte` | Éléments d'or présents dans les sections retenues ÷ éléments d'or attendus |

**Le dénominateur, ce sont les sources RETENUES**, après la troncature de
`fit_prompt` — pas les candidates. Une métrique calculée sur ce qui a été
*proposé* mesure une intention ; celle qui compte mesure ce qui a été **payé en
tokens**. `/answer` rend les deux : `contexts` liste toutes les sections
reconstruites, et `retained` dit lesquelles sont parties. Le texte publié est
celui qui est parti, troncature comprise.

**Une section écartée n'entre ni au numérateur ni au dénominateur.** Faute de
place dans la fenêtre, elle n'est pas un contexte inutile : c'est un contexte
**non payé**. La compter comme du bruit ferait chuter la métrique au moment
précis où le budget fait son travail.

**Les huit questions sans or sont exclues.** Sur une `unanswerable`, la part
utile vaut 0/N par construction ; la moyenner ferait baisser le chiffre sans
qu'aucune dégradation n'ait eu lieu. Le résumé publie trois compteurs —
`precision_contexte_sur`, `..._exclues_sans_or`, `..._exclues_sans_retenue` —
dont la somme égale le nombre de questions. Une métrique dont on ne sait pas sur
combien de questions elle porte n'est pas lisible.

### Ce que `rappel_contexte` voit et que `rappel_elements` ne voit pas

`rappel_elements` se mesure sur la **graine** du retrieval : les `element_id` que
la recherche a classés. Un élément d'or ramené par la fenêtre de la section —
sans avoir jamais été classé — y compte pour zéro, alors qu'il a bel et bien
atteint le LLM. C'est exactement la valeur que le graphe prétend apporter, et
elle était invisible.

`rappel_contexte` lit les marqueurs `[src:ID]` et `[img:ID]` du texte payé, donc
il la voit. Les deux ne se remplacent pas : l'écart entre eux **est** l'apport de
la reconstruction.

### La borne de `part_utile_caracteres`, et comment lire la taille de fenêtre

La métrique raisonne à la SECTION. Élargir la fenêtre *à l'intérieur* de la
section qui porte l'or ne la fait donc pas bouger — tous ces caractères
appartiennent à une section utile. Elle expose « trop de **sections** »
(`AUTO_SELECT_TOP_K`, `RERANK_TOP_K`), pas « fenêtre trop **large** »
(`CONTEXT_WINDOW_*`, `ADJACENT_SECTION_ELEMENTS`).

Ce que l'ablation de la taille de fenêtre lit, c'est le **couple** :
`caracteres_retenus` (p50 et p95) qui double pendant que `rappel_contexte` reste
plat. Même or, deux fois le prix. Un test épingle cette borne, pour que personne
ne lise un `part_utile_caracteres` stable comme « la fenêtre ne coûte rien ».

## La décomposition du temps

`AnswerResponse` ne portait que `retrieval_ms` et `generation_ms` : deux chiffres
pour sept étages, dont celui qui n'avait **jamais** été chronométré — la
reconstruction par le graphe, c'est-à-dire le pari central du projet. On ne peut
pas arbitrer la suppression d'une étape dont on ignore le prix.

`timings` porte une **partition** : chaque milliseconde appartient à un seul
étage, et ce qu'aucun étage ne réclame va au résidu.

| Étage | Ce qu'il mesure |
|---|---|
| `rewrite_ms` | Réécriture de la question de suivi (un appel LLM) |
| `translation_ms` | Traduction de la question réécrite (un appel LLM) |
| `dense_ms` | Recherche vectorielle — cumulée sur les classements de la question et de sa traduction |
| `lexical_ms` | Recherche BM25, idem |
| `fusion_ms` | Fusion RRF des classements |
| `rerank_ms` | Cross-encoder |
| `reconstruction_ms` | Remontée du graphe, fenêtrage, relecture des textes intégraux |
| `generation_ms` | Génération, du premier au dernier token |
| `residual_ms` | **Le temps que personne ne réclame** : ordonnancement LangGraph, post-traitement des citations, assemblage de la réponse |
| `total_ms` | Temps mural mesuré autour de la traversée entière |

Trois décisions valent d'être écrites, parce que ce sont elles qui rendent le
tableau lisible plutôt que vraisemblable.

**L'invariant est testé.** Somme des huit étages plus `residual_ms` égale
`total_ms`, exactement. Sans ce test, la partition dérive au premier refactor :
un étage mesuré à l'intérieur d'un autre fait dépasser la somme du total, et rien
ne le signale.

**`retrieval_ms` n'est pas un étage.** C'est le temps mural du nœud de
recherche : il CONTIENT `dense_ms`, `lexical_ms` et `fusion_ms`. Il survit —
la capture d'usage a une colonne de ce nom et tous les fichiers de `runs/` le
portent — mais l'ajouter à la partition doublerait le comptage de toute la
recherche. `chronometrie.AGREGATS` le nomme, et un test tombe si quelqu'un le
promeut en étage « pour compléter le tableau ».

**Le résidu peut être négatif, et on ne le borne pas.** Un résidu négatif est la
seule trace observable d'un double comptage ; le ramener à zéro effacerait
précisément ce qu'on cherche à voir. Un résidu large, lui, est en soi un
résultat : c'est du temps que personne ne sait expliquer.

Le résumé donne **p50 et p95** par étage. Une moyenne de latence cache la queue,
et c'est la queue qui décide de l'expérience.

## La comparaison appariée

`--compare` joignait les **résumés**, jamais les questions. Sur 138 questions, un
écart de deux points est alors indistinguable du bruit, et personne ne peut
savoir si un changement a amélioré 30 questions en dégradant 28, ou amélioré 2
sans rien casser. Ce sont deux résultats opposés, et ils s'affichent identiques.

L'appariement est désormais le mode par défaut. Par métrique, il rend :

- le nombre de questions **améliorées / dégradées / inchangées** ;
- la **liste des identifiants** qui basculent, dans chaque sens — c'est ce qu'on
  lit pour comprendre pourquoi ;
- un **test des signes exact** (binomial, bilatéral) sur les seules questions qui
  bougent. Les inchangées sont exclues : c'est la définition du test, et c'est ce
  qui lui donne sa puissance — deux améliorations sur 136 questions immobiles
  sont un signal qu'une moyenne noie ;
- un **intervalle de confiance à 95 %** de la différence appariée moyenne, par
  bootstrap sur les différences par question.

Les deux sont **déterministes**. Le test des signes est exact, donc sans tirage ;
le bootstrap a une graine fixe (`GRAINE_BOOTSTRAP`) et 2 000 rééchantillonnages,
de sorte que deux exécutions sur les mêmes fichiers rendent le même intervalle.
Sans cela, personne ne saurait si un écart vient du changement mesuré ou du
tirage. Aucun juge LLM n'intervient.

Les latences ne sont pas appariées : elles dépendent de la charge de la machine,
donc un écart apparié y mesurerait le voisinage plutôt que le changement. Elles
restent lues sur le diff des résumés, en p50 et p95.

### Le refus, et pourquoi il vaut mieux qu'une intersection

**Quand les deux jeux de questions diffèrent, la comparaison refuse de tourner.**
Elle nomme l'écart — les deux effectifs, et les identifiants absents de chaque
côté — et le script sort en code 2. Une intersection tacite est la façon exacte
dont on compare 100 questions en croyant en comparer 138.

Ce dépôt en portait le cas : `make eval` visait `runs/reference.json`, que
`runs/README.md` annonçait à 138 questions. Le fichier n'en contient que **117**
— 21 questions (G-118 à G-138) n'ont pas abouti lors de cette campagne. Chaque
`make eval` confrontait donc 138 moyennes à 117 moyennes sans que rien ne le
dise. La cible est passée à `runs/final.json`, qui porte les 138 lignes du jeu
doré, et un test épingle le refus sur l'ancienne.

C'est la même règle que celle du banc et de la campagne, appliquée un cran plus
loin : **un écart entre deux mesures n'est jamais du bruit.**

Deux autres cas font refuser, pour la même raison : un identifiant **répété**
d'un côté (l'appariement serait ambigu) et une référence sans lignes par question
(l'appariement est impossible, et comparer les seuls résumés est ce qu'on cherche
à éviter).

## Le jeu doré

`tests/fixtures/golden_qa_generated.json` — 138 questions, 70 françaises et
68 anglaises. Chaque question porte :

- `gold_element_ids` — les identifiants des éléments qui contiennent la réponse.
  Ils sont **déterministes** : l'ingestion les dérive du contenu, ils survivent
  à une réingestion. C'est ce qui rend le rappel calculable exactement.
- `gold_documents` — repli quand on n'annote qu'au niveau du document. Plus
  rapide à produire, mais beaucoup moins discriminant.
- `chat_history` — présent, la question est une question de **suivi**. C'est ce
  qui met la réécriture de requête à l'épreuve.
- `unanswerable` — le corpus ne contient pas la réponse. Un RAG qui n'admet
  jamais son ignorance est inutilisable ; ces cas se mesurent.

### Comment il est produit

`scripts/generate_golden.py` part d'un passage et fait écrire par un LLM une
question à laquelle **ce** passage répond. La vérité terrain est donc connue par
construction, avant toute recherche.

C'est l'inverse de l'annotation manuelle, et ce n'est pas un détail de confort :
annoter revient à poser une question, lire les passages proposés par le
retrieval, et désigner les bons — donc à ne jamais annoter un passage que le
retrieval ne trouve pas. Son échec resterait invisible, et c'est précisément
celui qui coûte le plus cher.

Cinq garde-fous écartent les mauvaises questions : la preuve doit être
**recopiée** du passage et non reformulée, la question doit partager du
vocabulaire distinctif avec lui, ne pas contenir sa propre réponse, ne pas
référencer « l'extrait », et tenir dans des bornes de longueur. Les passages
faits surtout de code sont écartés en amont — ils donnent des questions creuses.

40 % des questions sont posées dans une **autre langue** que leur document.
C'est le cas qui compte sur ce corpus, et `language` désigne la langue de la
question, pas celle du document.

Le résultat est du **silver** : chaque question sort avec `reviewed: false`.
L'approche est reconnue fiable pour régler un retriever, moins pour arbitrer
entre deux générateurs.

### Le banc de réglage rapide

Une campagne complète dure une demi-heure, dont l'essentiel en génération LLM —
inutile pour régler la **recherche**. `scripts/sweep_retrieval.py` rejoue le
retrieval seul et balaie un paramètre :

```bash
uv run python scripts/sweep_retrieval.py --param translation_weight --valeurs 0,0.5,1 --rerank
uv run python scripts/sweep_retrieval.py --param retrieval_top_k --valeurs 20,30,50 --entier --rerank
```

Trois règles apprises à ses dépens :

- **`--rerank` ou rien.** Sans le cross-encoder, élargir le vivier améliore le
  rappel mécaniquement, ce qui ne prouve rien. C'est la coupe finale, celle qui
  atteint le LLM, qui compte.
- **Vérifier ce que le `.env` impose.** Un balayage a conclu à un compromis
  inexistant parce que `RETRIEVAL_TOP_K=20` y écrasait en silence le défaut du
  code.
- **Quand le banc et la campagne divergent, regarder le chemin entre les deux.**
  Le banc mesurait 0,985 de rappel, la campagne 0,877, sur la même configuration
  en apparence. En cause : `AnswerRequest.top_k` valait 20 par défaut et
  surchargeait le réglage du service. Ce sont les **logs du conteneur** qui ont
  tranché — `50 + 50 + 50 + 50 → 20 fusionnés`, là où le réglage disait 50.

  Le banc mesure la bibliothèque, la campagne mesure le service. Un écart entre
  les deux n'est jamais du bruit : c'est un défaut dans ce qui les sépare.

## Ce que la mesure a déjà tranché

**L'écart translinguistique était le premier problème du système.** Rappel de
0,988 quand question et document partagent leur langue, 0,743 sinon. Huit des
dix échecs du corpus en relevaient.

Diagnostic : la recherche dense classait le bon passage aux rangs 16 à 29 — sous
la coupe — et la recherche lexicale ne trouvait **rien**, deux langues ne
partageant pas leurs mots. Traduire la question et chercher avec les deux
ramenait le bon passage au rang 1 à 3 dans les cinq cas examinés.

**Le compromis apparent n'existait pas.** Ajouter la traduction semblait coûter
7 points en même langue. Un balayage a montré que ce coût venait d'ailleurs :
la coupe à 20 candidats chassait, avant le reranking, des passages que la
question d'origine avait bien trouvés. À 50 candidats, le compromis disparaît.

| Configuration | rappel | translinguistique | même langue | MRR |
|---|---|---|---|---|
| top-20, sans traduction | 0,900 | 0,889 | 0,904 | 0,883 |
| top-50, traduction pleine | **0,985** | **1,000** | 0,979 | **0,963** |

## Les ablations qui restent à faire

1. avec / sans reconstruction de section, et taille de fenêtre — c'est le pari
   central du projet, et il n'est **pas encore vérifié**. Son prix est désormais
   lisible (`reconstruction_ms`) ; ce qu'elle change au contexte l'est aussi
   (cf. § La précision du contexte) ;
2. dense seul vs hybride BM25 + RRF, maintenant que le vivier est large ;
3. `AUTO_SELECT_TOP_K` et `RERANK_TOP_K` — plus de sources n'est pas
   nécessairement mieux : au-delà du budget de fenêtre, elles sont écartées ;
4. avec / sans réécriture de requête, sur les questions de suivi seules ;
5. modèles d'embedding — impose une réingestion complète, donc à faire une fois.

## Ce qui n'est pas encore mesuré

- **Fidélité au contexte** : la réponse dit-elle ce que disent les sources ?
  Demande un juge calibré — c'est le domaine de RAG-Eval-Bench.
- **Précision des citations** : un `[src:ID]` pointe-t-il vers un passage qui
  *soutient* l'affirmation ? Aujourd'hui on vérifie seulement qu'il est
  résoluble.
- **Pertinence des images** : les `[img:ID]` proposés servent-ils la réponse ?
