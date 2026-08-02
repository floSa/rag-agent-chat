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
| top-20, sans traduction | 0,900 | 0,889 | 0,904 | 0,883 |
| top-50, traduction pleine | 0,985 | 1,000 | 0,979 | 0,963 |

## Lire une comparaison

Les campagnes n'ont pas toutes le même nombre de questions : une coupure de
connexion ou un redémarrage du service en interrompt une. **Ne jamais comparer
deux moyennes d'effectifs différents** — reprendre l'intersection des
identifiants, comme le fait la comparaison appariée.

Ne pas non plus toucher à la stack pendant une campagne : deux d'entre elles ont
été faussées de cette façon avant qu'on s'en aperçoive.
