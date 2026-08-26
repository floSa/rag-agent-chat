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
make eval                                    # compare à runs/reference.json
uv run python scripts/evaluate.py --golden tests/fixtures/golden_qa_generated.json \
    --out runs/essai.json --compare runs/reference.json
```

Le script interroge `POST /answer` sur le jeu doré et calcule :

| Métrique | Ce qu'elle dit | Sans juge LLM ? |
|---|---|---|
| `rappel_recherche` | Le passage attendu est-il dans le classement du retrieval ? | oui |
| `rappel_elements` | A-t-il atteint le LLM ? | oui |
| `mrr` | Était-il deuxième, ou dix-huitième ? | oui |
| `rappel_documents` | Le bon document remonte-t-il ? Plus permissif. | oui |
| `taux_citation_complete` | Chaque citation nomme-t-elle son document et situe-t-elle le passage ? | oui |
| `abstention_correcte` | Le système admet-il son ignorance quand le corpus est muet ? | oui |
| `timings` | Quel étage coûte le temps ? Huit étages, plus le résidu — cf. § La décomposition du temps | oui |
| `contextes_ecartes` | Combien de sources n'ont pas tenu dans la fenêtre ? | oui |

Les résultats sont **stratifiés par langue**. Le corpus mêle français et
anglais : une moyenne globale masquerait un écart entre les deux.

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
