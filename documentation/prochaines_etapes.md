# Les prochaines étapes, ordonnées par le COÛT DE L'ÉCHEC

**Écrit le 25 septembre 2026**, base `origin/main` = `e1324e4`.

> **L'ORDRE N'EST PAS CELUI DU GAIN.** Il serait facile de mettre la
> décomposition en tête : c'est le plus gros levier chiffré du chantier. Ce
> n'est pas ce que fait ce document. **Il classe par ce que coûte de se
> tromper**, ce qui est le motif écrit au §4.71 du registre le jour où le
> pilote s'y est pris lui-même : *ordonner par le coût de l'échec, pas par la
> taille du pourcentage.* Une question dont l'échec invalide tout le reste
> passe devant une question dont l'échec coûte onze ancrages.
>
> **Aucun chiffre n'est créé ici** : chacun renvoie à sa section du registre
> [axes_amelioration.md](axes_amelioration.md) ou à une ligne du journal
> [pilotage_du_chantier.md](pilotage_du_chantier.md) §6.1. **Chaque estimation
> d'effort porte l'étiquette `supposé`** — ce sont des suppositions, elles n'ont
> pas été mesurées, et aucune ne doit être citée comme un chiffre du chantier.

---

## 1. Juger la qualité des réponses

**Registre : aucune section ne la porte, et c'est précisément le sujet.** Elle
est nommée comme manquante aux §4.66, §4.77 (journal l. 89), §4.78 (journal
l. 90) et §4.79 (réserve 1).

**Le chiffre.** Zéro. **Aucune réponse n'est jugée** dans ce dépôt au
25 septembre 2026 — ni par un humain, ni par un modèle, ni contre un jeu de
réponses de référence, qui n'existe pas.

**Pourquoi le coût de l'échec est le plus haut.** Tout ce que le chantier mesure
depuis le lot 31 est une **procuration** : *un ancrage au top-10 n'est pas une
bonne réponse* (§4.79). Si la procuration ne prédit pas la qualité, alors le
plafond du §4.77, le +12 du §4.78 et la répartition par étage du §4.79 ne disent
rien de ce qui intéresse un lecteur — et le §4.66 le dit déjà à sa façon :
*plus de citations n'est pas une meilleure réponse.* **C'est la seule question
dont l'échec rend les sept autres sans objet.**

**Ce qu'il faudrait mesurer pour la trancher.**
1. Un jeu de **réponses** de référence, distinct des jeux d'ancrages : sur un
   sous-ensemble des questions des trois jeux, une réponse attendue écrite à la
   main, pas par le modèle qui a écrit la question — la circularité du §4.76
   s'appliquerait sinon d'un cran de plus (§4.79, réserve 3).
2. La **corrélation** entre « les ancrages sont au prompt » et « la réponse est
   juste », sur ce sous-ensemble. C'est elle qui valide ou invalide la
   procuration, et elle se mesure **avant** tout jugement en masse.
3. Seulement ensuite, un protocole de jugement — humain d'abord, pour savoir ce
   qu'un juge-modèle devrait imiter.

**Effort — `supposé` :** deux lots. Un pour le jeu de référence et la mesure de
corrélation, un pour le protocole de jugement. Le premier est le seul qui
compte : s'il montre que la procuration tient, tout le reste du chantier est
validé rétroactivement ; s'il montre qu'elle ne tient pas, l'ordre ci-dessous
change entièrement.

---

## 2. Faire relire les jeux par un humain

**Registre : §4.67, §4.76 ; §4.79 réserve 8.**

**Les chiffres.** **190 questions sur 228 portent `reviewed: false`** : 130 des
138 du jeu de réglage et les 60 du jeu dispersé ; les 30 du jeu de contrôle et 8
du jeu de réglage sont relues (`mesuré` le 25 septembre 2026, VÉRIF-40 ; la
réserve 8 du §4.79 est corrigée au site). Sur le jeu dispersé, **30 ancrages sur 120
sortent au rang 1 du reranker** et *le juge de non-suffisance est le modèle qui
a écrit la question* (§4.76). **4** paires rejetées par la condition de
reconstruction sur 139 examinées, **8** par la non-suffisance, **67** par les
gardes lexicaux (§4.76) — les conditions mordent, mais aucune n'est un humain.

**Pourquoi le coût de l'échec est haut.** Une question mal écrite ne rend pas un
résultat faux : elle rend un résultat **plausible et faux**, qui ne se voit pas.
Et les trois jeux sont le dénominateur de tous les chiffres de
[etat_du_projet.md](etat_du_projet.md). *Un jeu périmé rend 0 % de rappel, ce
qui se voit* — un jeu **subtilement** faux rend 95 %, ce qui ne se voit pas.

**Ce qu'il faudrait mesurer.** Le taux de désaccord entre un relecteur humain et
les conditions automatiques, sur un échantillon tiré au sort des trois jeux :
combien de questions déclarées « non suffisantes par un seul passage » le sont
vraiment, et combien d'ancrages sont les bons. Si le désaccord est sous quelques
pour cent, les jeux valent ce qu'ils prétendent ; au-delà, les intervalles de
confiance du §4.67 sont trop étroits.

**Effort — `supposé` :** un lot pour le protocole et l'échantillon, puis du
temps humain hors chantier — c'est le seul poste de cette liste que du code ne
peut pas faire. **Corollaire déjà connu et déjà chiffré** : le jeu dispersé est
**monolingue anglais, 0 question française sur 60** (§4.76), avec sa cause
mesurée au site. L'axe translinguistique n'a donc **pas** de jeu, ce qui est
aussi pourquoi la traduction n'y gagne rien (§4.79).

---

## 3. La décomposition de requête, et sa traduction

**Registre : §4.78 et §4.79. Journal : lignes 90 et 91.**

**Les chiffres.** Jeu dispersé, questions complètes sur 60 : production **7**,
`fusion_rerank_sous_questions` **19**, variante traduite **18**, autre ordre
(question traduite puis décomposée) **19** ; borne de l'oracle **28**, soit
**68 %** de la borne atteints par la meilleure variante (§4.78). Jeu de
réglage : **127** en production, **124** sans traduction, **125** avec, **127**
pour l'autre ordre. Jeu de contrôle : **14** partout, aux sept variantes.

**LES PERTES À LA FUSION, ET C'EST LE FAIT NEUF DU §4.79.** L'écart à la borne
**n'est pas** 28 − 19 = 9 : c'est **11 manquées et 2 gagnées hors borne**, dont
**6 à la fusion**, 4 au reranking, 1 jamais récupérée. Réparti par étage sur les
120 ancrages du jeu dispersé :

| variante | `arrive` | perdu au `rerank` | perdu à la `fusion` | `jamais` |
|---|---|---|---|---|
| `fusion_rerank_sous_questions` | 72 | 12 | **11** | 25 |
| `fusion_traduite_rerank_sous_questions` | 72 | 13 | **8** | 27 |
| `fusion_question_traduite_decomposee` | 73 | 9 | **18** | 20 |

**La fusion coupée à 50 est donc un étage qui perd**, et il perd d'autant plus
que l'on fond de sous-requêtes. Le diagnostic question par question le montre :
`G-119` est perdue **à la fusion**, au rang 49 d'une sous-requête (§4.79) — et
*l'imputation du §4.78 était fausse*, ce que le §4.79 corrige à son site.

**Pourquoi ce rang, et pas le premier.** Le gain est le plus gros du chantier,
mais l'échec est **visible et réversible** : on le verrait sur le jeu de
contrôle et sur le jeu de réglage, qui sont appariés. Contre la production, le
bilan du §4.78 est **+12 sur le jeu visé et −3 hors de lui**, et le §4.79 montre
que la traduction ferme presque toute cette perte. On saurait donc qu'on s'est
trompé — ce qui n'est pas le cas des deux questions ci-dessus.

**Ce qu'il faudrait mesurer pour trancher.**
1. **Ce que coûte la fusion coupée à 50 quand on fond des sous-requêtes.** Les
   6 à 18 ancrages perdus là sont le premier poste ; le §4.79 les compte mais ne
   mesure pas ce que rendrait une coupe plus haute **pour la seule fusion des
   sous-requêtes** — ce serait mêler ce sujet à celui du §5 ci-dessous, et le
   §4.78 s'en est délibérément gardé.
2. **Les poids.** Les sous-requêtes sont fondues **à poids égaux**, et c'est un
   choix déclaré : la production donne un poids moindre à la traduction parce
   qu'elle sait laquelle mérite moins de confiance (§4.78).
3. **Le coût en `cuda`.** Cf. §4 ci-dessous : les latences de reranking du §4.79
   sont en `cpu`.
4. **Le 127 de l'autre ordre repose en partie sur une panne du producteur**
   (`G-024`), et *ce qu'il rendrait sans cette panne n'est pas mesuré*
   (§4.79, réserve 2).

**Effort — `supposé` :** un lot de mesure pour (1) et (2), puis un lot
d'implémentation dans `src/` si la mesure tient. L'implémentation est bornée :
le §4.79 écrit que la variante principale est *le geste implémentable sans
écrire une ligne de fusion neuve* — `retrieve(requête, translation=…)` est
exactement l'appel que `graph.py` émet, et *la seule chose qui change est le
texte qu'on lui donne*.

---

## 4. L'écart `cpu` / `cuda`

**Registre : §4.79, section « L'ENVIRONNEMENT » et réserve 7 ; même écart aux
§4.76 à §4.78, tenu délibérément identique.**

**Les chiffres.** Le service tourne en `cuda` — `/health` publie
`torch_device.requested: cuda`, `cuda_available: true`, torch `2.14.0+cu130`
(`mesuré` le 25 septembre 2026 à 08:10 UTC). Les quatre bancs tournent en `cpu`,
avec **les mêmes poids**, sortis du conteneur servi et confrontés octet pour
octet (`diff -rq`, aucun écart, §4.79). Ordre de grandeur de l'écart, au site du
§4.47 cité par le §4.77 : `rerank_ms` p50 **58 ms sur GPU pour 50 paires**, là
où le §4.79 relève une **médiane de 704 ms** pour le reranking sur la question
entière en `cpu`.

**Pourquoi l'échec coûte cher ici.** Tous les arbitrages de coût du chantier
sont posés sur des latences `cpu`. Un facteur dix mal placé peut **inverser** une
décision : le §4.78 ne recommande pas le reranking par sous-question, qui coûte un p95 de
**8 483 ms en `cpu`** qui, sur GPU, ne serait peut-être pas un obstacle. Et l'écart touche
aussi la **justesse** : *ce qu'un écart d'arrondi flottant déplacerait dans
l'ordre du reranking n'est pas mesuré* (§4.79).

**Ce qu'il faudrait mesurer.** Rejouer **un** banc déjà versionné — le plus
simple est le contrôle positif du §4.77, dont les 120 triplets de rangs sont
publiés — sur GPU, et confronter **rang par rang**, pas compte par compte : une
intersection, comme le §4.77 l'a fait pour le §4.76. Puis relever les latences
des mêmes étages.

**Effort — `supposé` :** un demi-lot. Le banc existe, les recettes existent, le
jeu est versionné ; ce qui manque est un environnement GPU pour le banc, que le
service occupe déjà.

---

## 5. Le reranker face à une question à deux besoins

**Registre : §4.77, question ouverte 3.**

**Le chiffre.** **52** ancrages sont **dans la fusion** et n'atteignent jamais
son top-10, alors que l'oracle `preuve` les y met **tous les 52**. *Ce n'est pas
une incapacité à scorer.*

**Pourquoi ici.** L'échec est borné et connu : c'est **le même geste** que la
question 3 ci-dessus, vu du quatrième étage — le §4.79 l'a d'ailleurs déjà
mesuré, et le reranking par sous-question rend **+11 à liste fusionnée
identique** (§4.78). Le reste — pourquoi le cross-encoder préfère un passage
tiède sur deux besoins à un passage parfait sur un seul — n'est pas expliqué, et
c'est ce qui reste ouvert.

**Ce qu'il faudrait mesurer.** Ce que rend un reranking par sous-question
**sans** décomposition par le modèle, c'est-à-dire sur une segmentation moins
coûteuse (par proposition, par clause) ; et si le choix du **maximum** plutôt que
de la moyenne, déclaré et gardé par une scène au §4.78, tient hors du jeu
dispersé.

**Effort — `supposé` :** compris dans le lot de mesure du §3 ci-dessus si on le
lui rattache ; un lot à part sinon.

---

## 6. La profondeur `50 → 200`

**Registre : §4.77, question ouverte 2.**

**Les chiffres.** À seuil constant — le top-10 du reranker aux trois
profondeurs — : **53** ancrages sur 120 à profondeur 50, **64** à 200, **62** à
1000. De 50 à 200 : **+11**. De 200 à 1000 : **−2**. Le gain est **réel et
borné**, et il est le plus simple de cette liste : deux variables
d'environnement, pas une ligne de code.

**Pourquoi si bas dans l'ordre, alors que c'est le moins cher à faire.** Parce
que l'échec est un **coût continu et silencieux**, payé à chaque requête : le
cross-encoder scorerait **200** paires au lieu de 50, et c'est déjà l'étage le
plus cher (§4.77, citant le §4.47). Un réglage qu'on pousse sans mesurer son
prix est exactement ce que le §4.66 refuse de faire pour `AUTO_SELECT_TOP_K`. Et
le +11 n'est établi que sur **un** jeu.

**Ce qu'il faudrait mesurer.** (a) le prix, à 200 paires par requête, **en
`cuda`** — donc après le §4 ci-dessus ; (b) si le +11 **survit sur les deux
autres jeux**, dont le plateau est ailleurs (§4.77).

**Effort — `supposé` :** un demi-lot de mesure. Le changement lui-même est deux
variables ; c'est sa justification qui coûte.

---

## 7. Filtrer les corps vides AVANT le fenêtrage

**Registre : §4.71 — et il faut lire la section entière, elle porte deux
corrections datées qui retirent ses premières conclusions.**

**Les chiffres à jour** (`mesuré` le 24 septembre 2026 à 15:02 UTC, dans le
conteneur servi) : sur les 172 ancrages distincts des deux jeux, **148** sections
reconstruites, **1 751** éléments rendus, dont **20 `code` vides sur 152** et
**26 `list_item` vides sur 289**. Une puce vide **disparaît du markdown** ; un
`code` vide laisse un **marqueur `[src:ID]` citable qui ne cite rien** — 20 sur
1 698. Coût réel : **46 places de fenêtre sur 1 751**, et la fenêtre se compte en
éléments **avant** le rendu.

**Ce que le site a retiré, et qu'il ne faut pas reprendre** : les « 37 pertes
sèches » n'existent pas, les puces vides n'ont **aucun enfant** et leur texte
arrive déjà au prompt par **727 fragments frères** ; les sommets `Code` vides
sont des **lignes blanches**, 0 perte sèche prouvée sur 1 362. Le pipeline a
tranché l'option (a) : **elles ne sont pas réparées**.

**Pourquoi tout en bas.** L'échec coûte 46 places de fenêtre sur 1 751 — **2,6 %**
(calculé ici depuis les deux chiffres du site), sans sortie fausse et sans perte
de contenu. Le site l'écrit : *un coût mesuré de cet ordre ne justifie pas un
lot.*

**Ce qu'il faudrait mesurer.** Ce que le filtrage **avant le fenêtrage** rend en
places récupérées, et surtout **ce que le modèle fait d'un bloc vide** — non
mesuré, et c'est la seule chose qui pourrait remonter ce point dans l'ordre : un
marqueur citable qui ne cite rien est une invitation à citer du vide.

**Effort — `supposé` :** un quart de lot pour la mesure, un petit lot de `src/`
ensuite. **Attention à un piège de relevé** consigné au site : la fonction
concernée s'appelle `_restore_full_text` (`graph_context.py:852`), et
`git grep _fill_full_texts -- src/` rend **0**.

---

## 8. Les non bloquantes des audits encore ouvertes

**Registre : §4.74 (les sept de l'audit du lot 34) et §4.75 (ce que le lot 35
n'a pas prouvé).** La seule qui nommait une **sortie fausse** — le constat E,
`/health` publiant 0 interaction et 0 octet pour une base pleine — a été fermée
par le lot 35 (journal l. 87).

| | Ce qui reste ouvert | Ce qu'il faudrait mesurer |
|---|---|---|
| **A** | Une mesure étiquetée `mesuré` **sans date** dans un commentaire de `src/api/main.py` | Rien : retrouver la date dans le journal et l'écrire. Correction, pas mesure |
| **B** | « n'a JAMAIS été atteinte sans injection », au même site : **instantané non borné**. Remesuré par l'audit, il tient (**0 sur 250** sous une autre contention) | Borner la phrase à sa campagne, ou la remesurer et la redater. *Un « jamais » reste une affirmation qui périme* |
| **C** | Les bancs de coût des tableaux du §4.74 sont **hors dépôt** et ne se rejouent pas | Les verser en `scripts/` avec leur recette. *Ce qui n'est pas versionné n'existe pas : ces tableaux sont des témoignages, pas des instruments* |
| **D** | La barrière du lot 33 n'est défendue que par **son propre garde** (sous mutation : 1 rouge sur 1126) | Un second garde d'une autre nature, ou l'acceptation écrite du risque |
| **F** | Piège de relevé : `grep -rn '_sonder\b'` rend **58** lignes à cause d'une **fixture homonyme** ; les appelants de production sont **5** | Rien à réparer dans le code. À savoir avant de compter |
| **G** | Méthode : un détecteur de résidus mal posé rend des chiffres faux **dans les deux sens** — 18 résidus fabriqués sur la branche réparée, puis un « 55 sur 500 » retiré avant le rendu | Rien à réparer. C'est une leçon de banc, et elle est déjà écrite |
| **§4.75** | La fenêtre du `-wal` **n'a jamais été atteinte sans injection** — ni sur 4000 appels contre 32 957 fermetures (audit 34), ni au lot 35, qui **n'a pas rejoué** ce banc, hors dépôt | Rejouer le banc s'il est versé (cf. **C**). Le `-shm` est couvert par le même rattrapage mais **n'a pas été exercé séparément** |

**Pourquoi en dernier.** Aucune ne nomme une sortie fausse depuis la fermeture
du constat E. Ce sont des **dettes de méthode** : un « jamais » non borné, un
banc non versionné, un garde seul. Elles coûtent le jour où quelqu'un s'appuie
dessus — d'où leur présence ici plutôt que leur oubli.

**Effort — `supposé` :** un lot pour A, B et C ensemble ; D et le `-shm` du
§4.75 relèvent d'un lot de gardes ; F et G n'appellent rien.

---

## L'ordre en une ligne

**Valider la procuration (1) → valider les jeux (2) → décomposer (3) → savoir ce
que coûte le GPU (4) → le reranker à deux besoins (5) → la profondeur (6) → les
corps vides (7) → les dettes de méthode (8).**

Les deux premières ne changent aucun réglage et ne gagnent aucun point de
rappel. Elles décident seulement si les six autres veulent dire quelque chose.
