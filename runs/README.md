# Campagnes d'évaluation

Chaque fichier est le résultat d'une exécution de `scripts/evaluate.py`. Ils sont
versionnés pour que `make eval` puisse comparer, et pour que les décisions de
réglage restent vérifiables plutôt que d'être affirmées.

| Fichier | Jeu | Ce qu'il mesure |
|---|---|---|
| `baseline.json` | 12 questions annotées au document | Point de départ, avant toute correction de retrieval |
| `c1-rewrite.json` | 15 questions | Après la réécriture des questions de suivi |
| `c2-hybride.json` | 15 questions | Après la recherche hybride BM25 + RRF |
| `c-final.json` | 15 questions | Après le lot complet : hybride, texte intégral, tool-calling |
| `reference.json` | 138 questions annotées à l'**élément** | Première mesure exploitable. C'est elle qui a révélé l'écart translinguistique. |
| `c3-translingue.json` | 138 questions | Après la recherche dans la traduction, avant réglage du vivier |
| `final.json` | 138 questions | Configuration retenue |

`.traductions.json` est le cache des traductions de questions utilisé par
`scripts/sweep_retrieval.py`. Il est versionné à dessein : sans lui, rejouer un
balayage suppose de refaire 130 appels au LLM, et les traductions changeraient
d'une exécution à l'autre — le balayage ne serait plus comparable. Le supprimer
le fait simplement se reconstruire.

## Résultat de la configuration retenue

`final.json` — 138 questions, campagne complète, aucun échec.

| Métrique | Valeur |
|---|---|
| `rappel_recherche` | **0,985** |
| `rappel_elements` | 0,962 |
| `mrr` | 0,963 |
| `rappel_documents` | **1,000** |
| `taux_citation_complete` | **1,000** |
| `abstention_correcte` | **1,000** |
| translinguistique (36 q.) | **1,000** |
| même langue (102 q.) | 0,979 |
| latence recherche p50 / p95 | 959 ms / 1 185 ms |
| latence génération p50 / p95 | 4 397 ms / 12 831 ms |

Deux questions seulement voient leur passage attendu jamais remonter, trois le
voient remonter puis écarter avant le LLM.

La recherche a triplé de coût (425 → 959 ms) : quatre classements au lieu de
deux, plus un appel LLM de traduction. Elle reste vingt fois moins chère que la
génération.

## Ce que les campagnes ont établi

**L'écart translinguistique était le premier problème du système.** Rappel de
0,988 quand la question et le document partagent leur langue, 0,743 sinon. Huit
des dix échecs en relevaient.

**Le compromis apparent n'en était pas un.** Ajouter la traduction semblait
coûter 7 points en même langue ; un balayage a montré que ce coût venait de la
coupe à 20 candidats, qui écartait avant le reranking des passages que la
question d'origine avait trouvés. À 50 candidats, le compromis disparaît.

| Configuration | rappel | translinguistique | même langue | MRR |
|---|---|---|---|---|
| référence (top-20, sans traduction) | 0,915 | 0,743 | 0,988 | 0,896 |
| retenue (top-50, traduction pleine) | **0,985** | **1,000** | 0,979 | **0,963** |

**Un défaut de schéma a failli invalider tout cela.** `AnswerRequest.top_k`
valait 20 par défaut et surchargeait `RETRIEVAL_TOP_K` : le banc mesurait 0,985,
la campagne 0,877, sur la même configuration en apparence. Ce sont les logs du
conteneur qui ont tranché — « 50 + 50 + 50 + 50 → 20 fusionnés », là où le
réglage disait 50.

## Lire une comparaison

Les campagnes n'ont pas toutes le même nombre de questions : une coupure de
connexion ou un redémarrage du service en interrompt une. **Ne jamais comparer
deux moyennes d'effectifs différents** — reprendre l'intersection des
identifiants, comme le fait la comparaison appariée.

Ne pas non plus toucher à la stack pendant une campagne : deux d'entre elles ont
été faussées de cette façon avant qu'on s'en aperçoive.
