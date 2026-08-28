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
| `reference.json` | **117 lignes, et biaisées**, annotées à l'**élément** | Première mesure exploitable. C'est elle qui a révélé l'écart translinguistique. La ligne annonçait 138 : le fichier n'en porte que 117, et le compte n'est pas le vrai problème — **aucune** des 8 questions `unanswerable` n'y figure, et l'anglais y survit moins bien (79 % contre 90 %). Ce qui en est tiré sur l'abstention est sans objet ; son résumé porte d'ailleurs `abstention_correcte: None`, l'instrument s'étant abstenu. **Il ne peut pas servir de base à une comparaison appariée**, et `make eval` ne le prend plus pour cible. |
| `c3-translingue.json` | 138 questions | Après la recherche dans la traduction, avant réglage du vivier |
| `final.json` | 138 questions | Configuration retenue |
| `c-deps-a-jour.json` | 138 questions | Contrôle après la montée de toutes les dépendances. Aucune métrique de recherche ne bouge. |

`.traductions.json` est le cache des traductions de questions utilisé par
`scripts/sweep_retrieval.py`. Il est versionné à dessein : sans lui, rejouer un
balayage suppose de refaire 130 appels au LLM, et les traductions changeraient
d'une exécution à l'autre — le balayage ne serait plus comparable. Le supprimer
le fait simplement se reconstruire.

## Avertissement — le remplissage au plus juste invalide les comparaisons de contexte

**À lire avec celui qui suit, et avant de comparer quoi que ce soit à
`final.json`.** Depuis le lot du remplissage des sources (cf.
[axes_amelioration.md](../documentation/axes_amelioration.md) §1.29 et §1.30),
une source qui ne tient pas entière dans la fenêtre n'est plus écartée : elle est
**tronquée sur une frontière d'élément et retenue**, tant que le fragment
atteint `TRUNCATION_FLOOR_SHARE` de sa source. La fenêtre part donc plus pleine.

| Métrique | Sens attendu | Pourquoi |
|---|---|---|
| `contextes_ecartes_total` | **En baisse** — et ce n'est PAS un gain de retrieval | Une source hier écartée est aujourd'hui tronquée et retenue, donc elle ne compte plus. Le classement n'a pas changé d'un rang |
| `contextes_retenus` | En hausse, du même mouvement | Ce sont les mêmes sources, passées d'un compteur à l'autre |
| `caracteres_retenus` | En hausse | C'est l'objet du lot : mesuré sur la grille, 70 % de la marge de fenêtre inutilisée est reprise |
| `part_utile_caracteres` | **Sens indécidable a priori** | Le dénominateur grossit avec les caractères retenus. Si le fragment ajouté porte de l'or, la part monte ; sinon elle baisse. C'est la métrique à lire en premier, et la seule qui puisse dire si le remplissage sert la réponse |
| `taux_contexte_utile` | **Sens indécidable a priori** | Il compte des sections : une retenue de plus entre au dénominateur, et au numérateur seulement si elle porte de l'or. Mesuré sur le calcul de `scripts/evaluate.py` : à une utile sur deux, une section de plus sans or fait 0,500 → 0,333, la même porteuse d'or fait 0,500 → 0,667. La flèche à un seul sens qui figurait ici était fausse — une métrique qui ne peut pas se tromper n'est pas gardée |
| `rappel_contexte` | En hausse ou stable | Un élément d'or dans la partie conservée d'une source tronquée atteint désormais le LLM. Vérifié monotone sur les 144 configurations de la grille : aucune configuration ne perd de source |
| `rappel_recherche`, `mrr`, `rappel_documents`, `rappel_elements` | Inchangés | Rien n'est touché en amont du reranking, et `rappel_elements` se calcule sur la graine de chaque section (cf. l'avertissement suivant) |

Un quatrième effet, non déclaré d'abord : une source **sans aucun marqueur** — le texte brut d'un élément orphelin de section, que `reconstruct_section` ajoute tel quel — sort avec `element_ids = []`. Elle peut donc entrer au dénominateur de `taux_contexte_utile` et de `part_utile_caracteres`, jamais au numérateur. Ce lot en retient davantage, puisqu'il reprend la marge : ces deux métriques peuvent baisser du seul fait qu'une population qui ne peut pas les faire monter grossit. À population comparable, c'est `rappel_contexte` qui reste lisible.

**Aucune comparaison de ces métriques à une campagne antérieure n'est valide.**
Ce ne sont pas les mêmes définitions de part et d'autre : `contextes_ecartes` ne
compte plus la même population, et `caracteres_retenus` inclut des fragments qui
n'existaient pas. Une nouvelle campagne de référence doit précéder toute
comparaison.

**Second effet, sur le flux interactif seulement.** La sélection de l'utilisateur
est désormais reconstruite par pertinence décroissante et non dans l'ordre du
client (§1.29). `make eval` passe par `/answer`, qui ne coche rien et prenait déjà
le classement : **la campagne ne verra pas ce correctif**. Il change ce que
`/chat/resume` envoie au modèle, et rien de ce que la campagne mesure. C'est une
lacune du protocole, pas un signe que le défaut était sans effet.

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
| `citations_par_reponse` | **En baisse**, deux causes | La première était seule inscrite : moins de texte en entrée, donc moins de sources citables. La seconde vient de la restriction des citations aux éléments réellement soumis ([axes_amelioration.md](../documentation/axes_amelioration.md) §1.31) — un identifiant que le modèle n'a pas eu sous les yeux n'est plus résolu. Elle est plus grande que la première, et son mécanisme est **mesuré** : le gabarit imprime `Source N — {{ ctx.element_id }}` en clair, hors de tout marqueur, et sa dernière ligne ordonne de reprendre les identifiants tels quels ; or l'élément d'ancrage est celui que la recherche a matché, donc il est au MILIEU de la section, et la troncature coupe par la fin. Sur une section de 12 éléments dont l'ancre est le 7e, **10 budgets de troncature sur 10** laissent cette ancre sans son texte dans le markdown soumis. Un modèle qui obéit au prompt émet donc une citation désormais refusée, à juste titre. L'**ampleur** de la baisse en campagne est **supposée** : la stack est éteinte, aucun chiffre n'est avancé. Cf. l'entrée §2 « Le gabarit imprime un identifiant qui n'est attaché à aucun texte » |
| `taux_citation_complete` | Stable en VALEUR, sur une population qui rétrécit | La justification d'origine — « rien ne change dans la résolution des citations » — est fausse depuis §1.31 : c'est précisément ce qui change. Le verdict survit pour une autre raison : la métrique vaut `citations_completes / citations`, donc elle porte sur les citations qui EXISTENT. Une citation refusée est absente, pas incomplète : elle n'entre ni au numérateur ni au dénominateur, et elle ne peut pas faire baisser le taux. Ce qu'elle déplace est ailleurs — une réponse dont la seule citation est refusée passe de 1,000 à `None`, et `_moyenne` écarte les `None` en silence. Le taux peut donc rester à 1,000 sur moins de réponses, sans qu'aucun champ ne le dise : cette métrique n'a pas de compagnon `_sur`, contrairement à `precision_contexte_sur`. C'est `citations_par_reponse`, ligne du dessus, qui porte l'effet |
| `abstention_correcte` | Stable | Séparée de la ligne précédente, parce que sa raison n'est pas la même — une justification unique pour deux métriques est exactement ce qui a laissé passer l'erreur ci-dessus. Elle se lit dans le TEXTE de la réponse (`REFUS` cherché dans `answer`), que §1.31 ne touche pas : la résolution des citations n'écrit rien dans la réponse |
| `rappel_recherche`, `mrr`, `rappel_documents` | Inchangés | Rien n'est touché en amont du reranking |
| latences | Quasi inchangées | Quelques rendus Jinja de plus par génération, négligeables devant 4,4 s. §1.31 y ajoute un balayage de marqueurs par section soumise et par réponse (`element_ids_presents`), du même ordre : non mesuré séparément, et non nul — le dire plutôt que l'appeler zéro |

### Ce que la restriction des citations ne déplace pas, métrique par métrique

**Passées en revue exprès, y compris celles où la réponse est « non ».** Une
métrique qui se tait ressemble à une métrique saine, et la moitié du travail est
de dire laquelle ne bouge pas et pourquoi.

| Métrique | Déplacée par §1.31 ? | Pourquoi |
|---|---|---|
| `rappel_recherche`, `mrr`, `rang_reciproque`, `rappel_documents` | Non | Elles se calculent sur le CLASSEMENT, en amont de la génération. La résolution des citations est en aval de tout |
| `rappel_elements` | Non | Sur `contexts` et sur la seule graine de chaque section, comme le dit la ligne du tableau ci-dessus. §1.31 ne touche pas la liste `contexts` que `/answer` publie |
| `contextes_ecartes`, `contextes_retenus`, `caracteres_retenus` | Non | Renseignés par `on_fit` depuis `node_generate`. §1.31 LIT ce que le budget a retenu, il ne change pas ce qu'il retient |
| `taux_contexte_utile`, `part_utile_caracteres`, `rappel_contexte` | Non | Elles lisent déjà `retained` et `element_ids` — c'est-à-dire `element_ids_presents(markdown soumis)`, depuis le lot 4. §1.31 aligne le RÉSOLVEUR sur l'instrument que ces métriques utilisaient déjà ; il ne déplace pas l'instrument. C'est la raison de fond du choix du grain : une seule définition de « soumis » dans tout le dépôt |
| `precision_contexte_sur` et ses deux compteurs d'exclusion | Non | Même raison : ils comptent les questions dont `taux_contexte_utile` est calculable, ce qui ne dépend que du budget |
| `hallucination_probable` | Non | Lue dans le texte de la réponse, comme `abstention_correcte` |
| `reponse_caracteres`, `eval_count`, `prompt_eval_count`, `generations_au_plafond`, `num_predict` | Non | Le prompt et la génération sont identiques : §1.31 n'intervient qu'APRÈS la réponse, sur la publication des citations |
| étages de latence et résidu | Non, à la marge près notée au tableau | Un balayage de marqueurs par section soumise s'ajoute au post-traitement, qui n'a pas d'étage à lui : il tombe dans le résidu |
| `citations`, `citations_par_reponse` | **Oui**, en baisse | Seule famille déplacée. Cf. le tableau ci-dessus |
| `citations_completes`, `taux_citation_complete` | Valeur non, population oui | Cf. le tableau ci-dessus |

**Ce que la campagne ne verra PAS, et il faut le dire.** Le chemin par lequel le
défaut était atteignable en production est le multi-tour : le modèle recite un
`[src:ID]` d'un tour précédent, que `fit_history` resoumet marqueurs compris.
Aucune campagne de ce dépôt ne l'exerce. **Mesuré** sur les deux jeux :
`golden_qa_generated.json`, les 138 questions que vise `make eval`, porte
`chat_history` sur **0** d'entre elles ; `golden_qa.json`, le jeu de 15 questions
utilisé par défaut, en porte 3, mais leurs historiques sont écrits à la main et
contiennent **0 marqueur `[src:]`**. La campagne verra donc les deux autres causes
— l'ancre imprimée sans son texte, et un identifiant de section entièrement
écartée — pas celle qui a motivé le lot. C'est une lacune du protocole, pas un
signe que le défaut était sans effet : même espèce que celle notée plus haut pour
le flux interactif.

Le lot 4 ajoute des champs que **aucun** fichier de ce dossier ne porte, donc
qu'aucune comparaison appariée ne pourra apparier contre eux : la précision du
contexte (`taux_contexte_utile`, `part_utile_caracteres`, `rappel_contexte`), la
partition du temps par étage, le coût réel de la génération (`eval_count`,
`generations_au_plafond`) et le décompte réel du prompt. La comparaison le dira
elle-même — « aucune paire » plutôt qu'un delta nul. La première campagne qui
tournera devient la référence de ces métriques ; les anciennes restent la
référence du rappel et du MRR, qui n'ont pas changé de définition.

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
