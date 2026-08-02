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
make eval                                    # compare à runs/baseline.json
uv run python scripts/evaluate.py --out runs/essai.json --compare runs/baseline.json
```

Le script interroge `POST /answer` sur le jeu doré et calcule :

| Métrique | Ce qu'elle dit | Sans juge LLM ? |
|---|---|---|
| `rappel_documents` | Les bons documents remontent-ils ? | oui |
| `rappel_elements` | Les bons **passages** remontent-ils ? | oui — suppose les `gold_element_ids` annotés |
| `taux_citation_complete` | Chaque citation nomme-t-elle son document et situe-t-elle le passage ? | oui |
| `abstention_correcte` | Le système admet-il son ignorance quand le corpus est muet ? | oui |
| `retrieval_ms` / `generation_ms` | Quel étage coûte le temps ? | oui |
| `contextes_ecartes` | Combien de sources n'ont pas tenu dans la fenêtre ? | oui |

Les résultats sont **stratifiés par langue**. Le corpus mêle français et
anglais : une moyenne globale masquerait un écart entre les deux.

## Le jeu doré

`tests/fixtures/golden_qa.json`. Chaque question porte :

- `gold_element_ids` — les identifiants des éléments qui contiennent la réponse.
  Ils sont **déterministes** : l'ingestion les dérive du contenu, ils survivent
  à une réingestion. C'est ce qui rend le rappel calculable exactement.
- `gold_documents` — repli quand on n'annote qu'au niveau du document. Plus
  rapide à produire, mais beaucoup moins discriminant.
- `chat_history` — présent, la question est une question de **suivi**. C'est ce
  qui met la réécriture de requête à l'épreuve.
- `unanswerable` — le corpus ne contient pas la réponse. Un RAG qui n'admet
  jamais son ignorance est inutilisable ; ces cas se mesurent.

### La limite qui bloque tout le reste

Le jeu doré n'annote qu'au **document**. Sur un corpus où un chapitre entier
compte comme un succès, deux configurations de retrieval très différentes
obtiennent le même score. C'est exactement ce qui s'est produit en mesurant la
recherche hybride : rappel identique, alors que le nombre de citations par
réponse montait de 5,3 à 6,3.

Annoter les `gold_element_ids` est le seul moyen de trancher, et le seul travail
qui ne s'automatise pas entièrement : un outil peut proposer les candidats, le
choix reste humain.

Second point : quinze questions ne distinguent pas un écart d'un dixième du
bruit. Viser 100 à 150, stratifiées par type et par langue.

## Les ablations qui valent le coup

Une fois la mesure fiable, chaque hypothèse devient un chiffre. Par gain attendu
décroissant :

1. avec / sans reconstruction de section, et taille de fenêtre — c'est le pari
   central du projet, et il n'est pas encore vérifié ;
2. dense seul vs hybride BM25 + RRF ;
3. `AUTO_SELECT_TOP_K` et `RERANK_TOP_K` — plus de sources n'est pas
   nécessairement mieux : au-delà du budget, elles sont écartées ;
4. avec / sans réécriture de requête, sur les questions de suivi seules ;
5. modèles d'embedding — impose une réingestion complète, donc à faire une fois.

## Ce qui n'est pas encore mesuré

- **Fidélité au contexte** : la réponse dit-elle ce que disent les sources ?
  Demande un juge calibré — c'est le domaine de RAG-Eval-Bench.
- **Précision des citations** : un `[src:ID]` pointe-t-il vers un passage qui
  *soutient* l'affirmation ? Aujourd'hui on vérifie seulement qu'il est
  résoluble.
- **Pertinence des images** : les `[img:ID]` proposés servent-ils la réponse ?
