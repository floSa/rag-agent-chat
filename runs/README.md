# Campagnes d'évaluation

Chaque fichier est le résultat d'une exécution de `scripts/evaluate.py`. Ils sont
versionnés pour que `make eval` puisse comparer, et pour que les décisions de
réglage restent vérifiables plutôt que d'être affirmées.

**La comparaison est appariée question par question, et elle refuse de tourner si
les deux jeux diffèrent.** Le tableau ci-dessous donne le nombre de lignes
réellement présentes dans chaque fichier — pas le nombre de questions du jeu
doré : seuls les fichiers qui portent les 138 lignes s'apparient avec une
campagne complète. Compter les lignes est ce qui a révélé que `make eval`
comparait 138 moyennes à 117.

| Fichier | Jeu | Ce qu'il mesure |
|---|---|---|
| `baseline.json` | 12 questions annotées au document | Point de départ, avant toute correction de retrieval |
| `c1-rewrite.json` | 15 questions | Après la réécriture des questions de suivi |
| `c2-hybride.json` | 15 questions | Après la recherche hybride BM25 + RRF |
| `c-final.json` | 15 questions | Après le lot complet : hybride, texte intégral, tool-calling |
| `reference.json` | **117 lignes**, annotées à l'**élément** | Première mesure exploitable. C'est elle qui a révélé l'écart translinguistique. La ligne annonçait 138 : le fichier n'en porte que 117, 21 questions (G-118 à G-138) n'ayant pas abouti. **Il ne peut donc pas servir de base à une comparaison appariée**, et `make eval` ne le prend plus pour cible. |
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
| `rappel_elements` | **Inchangé** — et l'affirmation d'origine était fausse | Elle annonçait « il se mesure sur ce qui atteint le LLM, une source écartée en moins le fait baisser ». Vérifié au lot 4 : la métrique se calcule sur `contexts`, qui contient les sections ÉCARTÉES par le budget, et sur la seule GRAINE de chaque section. Elle ne bouge donc ni quand une source est écartée, ni quand la fenêtre du graphe ramène l'or. C'est `rappel_contexte`, ajouté au lot 4, qui recule dans ce cas |
| `citations_par_reponse` | En légère baisse | Moins de texte en entrée, donc moins de sources citables |
| `taux_citation_complete`, `abstention_correcte` | Stables | Rien ne change dans la résolution des citations |
| `rappel_recherche`, `mrr`, `rappel_documents` | Inchangés | Rien n'est touché en amont du reranking |
| latences | Quasi inchangées | Quelques rendus Jinja de plus par génération, négligeables devant 4,4 s |

**Un recul de `rappel_elements` n'est pas à annuler sans avoir vérifié la cause.**
Démonstration sur un cas que l'ancien budget acceptait : cinq sources de 2 500
caractères, soit 12 500 ≤ 12 544, le plafond d'alors. Le prompt réellement émis
faisait **15 062 caractères pour une fenêtre utile de 14 336** — 726 de trop, soit
**208 tokens qui rognaient la génération sans le dire**. La cinquième source ne
tenait pas. Le budget corrigé n'en retient que quatre, pour 12 428 caractères : la
métrique baisse parce que le dépassement disparaît.

Le régime de panne, précisément, parce qu'il y en a deux et que ce cas relève du
second : 15 062 caractères font 4 304 tokens estimés. C'est au-delà de la fenêtre
de prompt (`num_ctx − num_predict` = 4 096) mais **en deçà de `num_ctx` (8 192)**,
donc Ollama ne tronque rien ici — il n'accorde plus que 3 888 tokens à la
génération au lieu des 4 096 demandés, en silence. C'est exactement la seconde
zone que `log_prompt_measure` avertit désormais (« il ne reste que N tokens à la
génération, qui sera rognée sans le dire »). La troncature par le début, elle,
suppose de dépasser `num_ctx` : c'est le régime des 31 380 caractères mesurés sur
six messages d'historique, pas celui-ci.

Corroboration : si le message système avait été jeté sur ces campagnes,
`final.json` ne donnerait pas `taux_citation_complete` = 1,000 et
`abstention_correcte` = 1,000.

La comptabilité des 15 062, pour qui voudrait la refaire — `sum(len(content))`
donne 14 577 et non 15 062, parce que deux termes ne sont pas dans les contenus :

| Terme | Caractères |
|---|---|
| Contenus des messages (système + message utilisateur rendu) | 14 577 |
| Déclaration de l'outil `search_vectors`, rendue dans le prompt par Ollama | 417 |
| Balises de tour du gabarit de chat, deux messages × 34 | 68 |
| **Total réellement soumis** | **15 062** |

### L'écart n'est pas un cas favorable

Balayé sur 144 configurations à comptabilité identique — 3 profondeurs de fil des
titres × 8 tailles de source × 6 nombres de candidates :

- l'ancien budget dépasse la fenêtre utile dans **43** cas, le nouveau dans **0** ;
- l'ensemble des 43 dépassements est **exactement** l'ensemble des 43
  configurations où le nouveau retient une source de moins. Différence symétrique
  nulle.

Autrement dit : le nouveau budget n'écarte jamais une source que l'ancien
transmettait sans déborder. C'est ce qui autorise à ne pas annuler un recul de
`rappel_elements` — mais à vérifier, campagne en main, qu'il porte bien sur des
questions de ce régime.

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
| latence recherche p50 / p95 | 954 ms / 1 200 ms |
| latence génération p50 / p95 | 4 449 ms / 12 378 ms |

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
