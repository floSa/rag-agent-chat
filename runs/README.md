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
| `c-deps-a-jour.json` | 138 questions | Contrôle après la montée de toutes les dépendances. Aucune métrique de recherche ne bouge. |

`.traductions.json` est le cache des traductions de questions utilisé par
`scripts/sweep_retrieval.py`. Il est versionné à dessein : sans lui, rejouer un
balayage suppose de refaire 130 appels au LLM, et les traductions changeraient
d'une exécution à l'autre — le balayage ne serait plus comparable. Le supprimer
le fait simplement se reconstruire.

## Avertissement — aucune campagne depuis la correction du budget de contexte

**À lire avant de comparer une nouvelle campagne à `final.json`.** Le budget de la
fenêtre de contexte a été corrigé (cf. [llm.md](../documentation/llm.md) et
[axes_amelioration.md](../documentation/axes_amelioration.md) §1.13 à §1.19), et
aucune campagne n'a tourné depuis : la stack n'était pas joignable. Ce que la
première fera bouger, et dans quel sens :

| Métrique | Sens attendu | Pourquoi |
|---|---|---|
| `contextes_ecartes_total` | **En hausse**, depuis 0 | Le budget ne prétend plus qu'un forfait de 512 tokens couvre le prompt système, le gabarit et l'historique. Il compte ce qui est réellement envoyé, donc il écarte plus tôt |
| `rappel_elements` | **Peut reculer** — et c'est correct | Il se mesure sur ce qui atteint le LLM. Une source écartée en moins le fait baisser, même quand l'écarter est le correctif |
| `citations_par_reponse` | En légère baisse | Moins de texte en entrée, donc moins de sources citables |
| `taux_citation_complete`, `abstention_correcte` | Stables | Rien ne change dans la résolution des citations |
| `rappel_recherche`, `mrr`, `rappel_documents` | Inchangés | Rien n'est touché en amont du reranking |
| latences | Quasi inchangées | Quelques rendus Jinja de plus par génération, négligeables devant 4,4 s |

**Un recul de `rappel_elements` n'est pas à annuler sans avoir vérifié la cause.**
Démonstration sur un cas que l'ancien budget acceptait : cinq sources de 2 500
caractères, soit 12 500 ≤ 12 544, le plafond d'alors. Le prompt réellement émis
faisait **15 062 caractères pour une fenêtre utile de 14 336** — 726 de trop, soit
~207 tokens qu'Ollama tronquait **par le début**, donc en jetant le message
système et ses règles de citation. La cinquième source ne tenait pas. Le budget
corrigé n'en retient que quatre, pour 12 428 caractères : la métrique baisse parce
que le dépassement disparaît.

### Ce que cette campagne ne verra pas

Le gain principal de la correction est la **survie du message système en
conversation** : c'est au troisième tour que le prompt débordait. Or `make eval`
ne pose que des questions isolées — le jeu doré n'a pas de fil multi-tour
exploitable. **La campagne mesurera donc le coût de la correction sans mesurer son
bénéfice.** C'est une lacune du protocole de mesure, ouverte en P2 dans
[axes_amelioration.md](../documentation/axes_amelioration.md), pas une raison de
lire les chiffres comme une régression.

Deuxième angle mort, même document : `scripts/evaluate.py` n'enregistre pas la
longueur des réponses, seulement `generation_ms`. C'est la mesure qui manque pour
régler `LLM_MAX_TOKENS`, qui réserve aujourd'hui la moitié de la fenêtre.

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

**Monter `sentence-transformers` et `chromadb` n'a rien changé.** C'était le
risque à écarter : l'un encode la question, l'autre la compare aux vecteurs
écrits par l'ingestion. Un écart aurait dégradé la recherche sans lever la
moindre erreur.

| Métrique | `final.json` | `c-deps-a-jour.json` |
|---|---|---|
| `rappel_recherche` | 0,985 | 0,985 |
| `rappel_elements` | 0,962 | 0,962 |
| `mrr` | 0,963 | 0,963 |
| génération p50 | 4 449 ms | **3 076 ms** |

Les mêmes cinq questions échouent, aux mêmes endroits — c'est ce qui prouve
l'identité, mieux qu'une moyenne égale. La génération a gagné 31 %, effet des
montées côté serveur, sans contrepartie mesurée.

Une seule valeur bouge : `citations_par_reponse`, 3,25 → 2,95. Ce n'est pas une
régression mais la variabilité du LLM d'une exécution à l'autre — le
`taux_citation_complete` reste à 1,000, donc toutes les citations émises
restent résolues et situées.

## Lire une comparaison

Les campagnes n'ont pas toutes le même nombre de questions : une coupure de
connexion ou un redémarrage du service en interrompt une. **Ne jamais comparer
deux moyennes d'effectifs différents** — reprendre l'intersection des
identifiants, comme le fait la comparaison appariée.

Ne pas non plus toucher à la stack pendant une campagne : deux d'entre elles ont
été faussées de cette façon avant qu'on s'en aperçoive.
