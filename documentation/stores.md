# Les stores, vus du consommateur

Ce projet **lit** trois stores qu'il ne possède pas. Ils sont produits et
maintenus par
[rag-ingestion-pipeline](https://github.com/floSa/rag-ingestion-pipeline) : leur
configuration, leur schéma et leur exploitation sont documentés là-bas.

Cette page décrit uniquement ce que l'agent en attend, et ce qui casse quand
l'attente n'est pas tenue.

> Cinq documents décrivaient ici Dagster, Docling et PostgreSQL — des services
> de l'ingestion, absents de ce projet. C'étaient des copies, et elles avaient
> dérivé. Dupliquer la documentation d'un dépôt voisin garantit qu'elle devienne
> fausse ; un lien, non.

## ChromaDB — la recherche

| | |
|---|---|
| Adresse | `chromadb:8000` (réseau `rag_network`) |
| Collection | `rag_documents`, 384 dimensions |
| Utilisé par | `src/agent/retriever.py`, `src/agent/lexical.py` |

L'agent y fait trois choses : la recherche dense, la **relecture du texte
intégral** quand celui du graphe est tronqué, et la construction de l'index
BM25 au premier appel.

### L'index BM25 vit dans le processus de l'agent, le corpus non

C'est l'asymétrie à connaître de ce store. La recherche dense interroge Chroma à
chaque requête : elle suit le corpus sans rien faire. L'index BM25, lui, est une
copie en mémoire — et l'ingestion écrit pendant que l'agent tourne.

Un document ingéré après la construction de l'index était donc trouvable en
dense et **invisible en lexical** jusqu'au prochain redémarrage. La recherche
devenait silencieusement asymétrique.

**Ce que l'ingestion doit faire :** appeler `POST /reindex` en fin de pipeline.
C'est un contrat, et la réponse porte le nombre de chunks indexés — confrontable
à ce qui vient d'être écrit.

**Ce que l'agent fait si elle ne le fait pas :** il compare `collection.count()`
au nombre de chunks de son index et reconstruit en tâche de fond quand les deux
divergent. C'est un filet, pas une garantie — **un corpus dont on a retiré
autant de chunks qu'on en a ajouté affiche le même compte**, et l'index reste
alors périmé sans que rien ne le signale.

`GET /health` rend `index_lexical: false` dans les deux états dégradés : pas
encore construit, et construit sur un corpus qui n'existe plus. La distinction
n'intéresse pas l'utilisateur — la recherche est amputée dans les deux cas.

### Métadonnées lues

| Clé | Ce que l'agent en fait |
|---|---|
| `element_id` | Pivot vers le graphe. Hash `^[a-f0-9]{10}$`. |
| `source_path` | **Identité du document.** Clé de groupement des sources. |
| `filename` | Nom du chapitre, affiché dans la citation. |
| `collection` | Ouvrage. Repli quand le graphe ne le donne pas. |
| `section_title` | Situe le passage dans la citation. |
| `language` | Stratifie l'évaluation, annoncée dans l'UI. |
| `page_no` | Situe le passage. Vaut 1 pour les formats non paginés. |
| `chunk_index` | Remet les fenêtres d'un élément long dans l'ordre. |
| `minio_url` | Résolu vers le proxy `/media`. |
| `depth` | Lu, mais la remontée du graphe fait mieux. |

### Ce qui casse

**Le modèle d'embedding doit être identique des deux côtés.** Sinon la recherche
rend des passages au hasard, sans erreur ni avertissement — c'est le mode de
défaillance le plus coûteux de tout le système. La valeur est dans
`EMBEDDING_MODEL_NAME`, actuellement
`paraphrase-multilingual-MiniLM-L12-v2`.

Un élément long est réparti sur plusieurs chunks (`abc#0`, `abc#1`) partageant
leur `element_id`. L'agent déduplique **avant** de couper au top-K ; sans cela,
plusieurs fenêtres d'un même passage occupent plusieurs places, et le frontend
produit deux cases à cocher de même identifiant.

## NebulaGraph — la structure

| | |
|---|---|
| Adresse | `graphd:9669`, space `rag_space` |
| Utilisé par | `src/agent/graph_context.py` |

L'agent remonte de l'élément trouvé jusqu'au `Document` en notant les titres
traversés, puis redescend chercher une fenêtre d'éléments, la fin de la section
précédente et le début de la suivante.

### Ce que l'agent attend du schéma

| Élément | Attente |
|---|---|
| VIDs | Hash 10 hexadécimaux, ou `doc_{chemin}` jusqu'à 256 octets |
| `PARENT_OF(sequence)` | Hiérarchie **et** ordre de lecture. C'est `sequence` qui permet d'atteindre la section voisine. Elle porte **trois réserves de lecture** — voir plus bas, c'est leur site canonique. |
| Arête légende → visuel | Cherchée dans le schéma parmi `LINKED_TO` puis `DESCRIBES` |
| `Document.collection` | Ouvrage, source préférée pour les citations |
| Propriété `text` | Tronquée à l'ingestion — voir plus bas |

**Deux pièges rencontrés :**

`GO … OVER … REVERSELY` : `dst(edge)` renvoie le nœud de **départ**, pas le
voisin atteint. C'est `src(edge)` qui porte le parent. L'erreur est silencieuse —
la remontée n'avance simplement jamais.

L'arête des légendes a déjà été renommée une fois (`DESCRIBES` → `LINKED_TO`).
Son nom est donc lu dans le schéma, et l'absence totale d'arête est traitée
comme un cas normal : l'illustration reste proposée, sans légende.

### Le graphe porte la structure, pas le corpus

L'ingestion tronque le texte des nœuds à 2000 caractères. L'agent relit donc
dans ChromaDB le texte des éléments qui frôlent cette limite — un tableau
exporté par Docling la dépasse souvent, et arrivait amputé au LLM.
`GRAPH_TEXT_TRUNCATION` doit suivre le `graph_text_max_chars` de l'ingestion.

### Les trois réserves de lecture de `sequence`

> **Site canonique.** Le contrat d'ingestion garantit que `sequence` porte
> l'ordre de lecture et qu'elle est monotone. Ce que cette garantie ne dit pas,
> c'est comment on la **lit** — et c'est ici, parce que c'est une propriété du
> consommateur, pas du store. Les autres pages renvoient à celle-ci.

Toutes les mesures de cette section se rejouent par un seul geste, en lecture
seule (`graphd` n'expose aucun port sur ce poste) :

```bash
docker exec -i rag-agent-api python - < scripts/mesurer_le_graphe.py
```

**1. `sequence` repart à 0 dans chaque document.** Elle n'est pas un rang
global : `mesuré` le 3 septembre 2026, les **23** documents commencent tous à
`0`, et **toutes** les paires de documents ont des intervalles qui se recouvrent
(253 paires, soit les 23 × 22 / 2 possibles). Deux éléments de deux ouvrages
portent donc couramment la même valeur.

Conséquence : **tout « avant / après » se borne au document.** En pratique
l'ancrage est structurel — `_get_children` et `_find_sibling` partent d'un VID
de parent, jamais d'une valeur de `sequence` seule. Une comparaison non ancrée
(un `LOOKUP` sur l'arête, par exemple) rapprocherait deux ouvrages sans erreur
visible.

**2. Elle n'est pas contiguë sous un parent, et ce n'est pas une perte.**
`mesuré` le 3 septembre 2026 : **167** parents sur les **692** qui ont au moins
deux enfants portent des valeurs non contiguës.
Le dénominateur est la population
**éligible**, et non les 763 parents du graphe : un parent à enfant unique ne peut
pas être non contigu, et les **71** parents de ce genre ne faisaient que diluer le
taux. La version précédente de cette page écrivait « 167 sur 763 », un numérateur
compté sur une population et un dénominateur sur une autre. L'écart s'explique **entièrement** par la taille du sous-arbre
du frère précédent — vérifié sur les **14 410** couples de frères consécutifs
du graphe, **0** discordance. `sequence` numérote l'ordre de lecture de
l'ouvrage entier, pas les enfants d'un parent : un frère dont le sous-arbre
compte 40 nœuds fait donc avancer le suivant de 40.

**3. L'écart entre deux enfants d'un même parent peut être grand.** `mesuré` le
3 septembre 2026 : le plus grand vaut **994**, soit 993 valeurs intercalaires,
sous `doc_htms/MLOps with Databricks/7. Foundation Models and Context
Engineering`.

#### Ce que ces trois réserves interdisent

**La fenêtre d'éléments se découpe sur des POSITIONS de liste, jamais sur des
VALEURS de `sequence`.** C'est ce que fait le code : `_get_children` va chercher
tous les enfants avec un `ORDER BY` et **sans filtre d'intervalle**, puis
`_window_around` découpe par `rows[start:stop]`.

L'optimisation qui se présente d'elle-même — pousser la fenêtre dans la requête
nGQL sous la forme d'un encadrement `sequence ∈ [s−k, s+k]`, ce qui économise un
aller-retour et du transfert — serait juste sur la plupart des sections et
**silencieusement amputée** ailleurs. `mesuré` le 3 septembre 2026, à la fenêtre
par défaut (`CONTEXT_WINDOW_BEFORE=CONTEXT_WINDOW_AFTER=6`, soit 13 éléments) :

| | `mesuré` |
|---|---|
| ancres qui rendraient MOINS d'éléments | **1 141** sur 15 173, soit **7,5 %** |
| parents touchés | **162** |
| perte maximale sur une ancre | **12** éléments sur 13 — l'ancre revient seule |

> La perte se borne à `before + after`, jamais aux 993 valeurs intercalaires de
> la réserve 3 : le découpage positionnel ne demande que 13 éléments, donc on ne
> peut pas en perdre plus de 12. L'écart de 994 mesure un **trou de
> numérotation**, pas un nombre d'éléments manquants.

**Ce découpage est gardé, pas seulement documenté — et voici jusqu'où.**
`tests/unit/test_lecture_sequence.py` pilote `reconstruct_section` contre un
graphe factice qui **honore** les clauses `WHERE` des requêtes, et qui rend ses
enfants dans un ordre **non trié**, comme le fait NebulaGraph sans `ORDER BY`.

Ce que la phrase couvrait mal, et c'est mesuré, pas relu. Le garde porte sur une
composition à **trois** maillons — « chercher tous les enfants, **ordonnés**,
puis découper par position » — et le fichier n'en éprouvait que deux : son
graphe factice triait ses enfants à l'insertion, donc il FABRIQUAIT
l'ordonnancement au lieu de l'éprouver. `mesuré` le 3 septembre 2026 : retirer
le `| ORDER BY $-.seq ASC` de `_get_children` laissait alors la suite entière
verte, `rc=0`, 496 passés, zéro rouge. Et un encadrement écrit **en aval d'un
tube** — `| YIELD … WHERE $-.seq >= …`, du nGQL aussi légitime que l'autre —
était invisible au bouchon, qui rendait donc toutes les lignes.

**La borne de ce qui est gardé aujourd'hui**, `mesuré` le 3 septembre 2026 dans
un environnement monté par le protocole du §2.2 du registre de pilotage — huit
mutations passées, huit rouges, sur le code sain `rc=0` et 502 passés :

| mutation | `rc` | rouges |
|---|---|---|
| encadrement `sequence ∈ [s−k, s+k]` dans le `WHERE` de l'arête | 2 | 3 |
| le `ORDER BY $-.seq ASC` retiré de `_get_children` | 2 | 4 |
| ce même `ORDER BY` retourné en `DESC` | 2 | 3 |
| encadrement écrit en aval d'un tube (`$-.seq`) | 2 | 3 |
| encadrement aux opérandes échangées (`N <= …`) | 2 | 3 |
| la prémisse morte remise dans le code — voisine cherchée sous le `Document` | 2 | 1 |
| `_MAX_DEPTH` ramené à 2 | 2 | 1 |
| la remontée s'arrête au premier en-tête | 2 | 2 |

**Ce qui n'est PAS gardé, et il faut le lire avant de s'appuyer sur la phrase
ci-dessus** : la définition de « section voisine » elle-même — « le frère
en-tête sous le parent commun » — n'est éprouvée par aucun garde, parce que ce
n'est pas un défaut mais une décision ouverte (les **381** en-têtes concernés,
§4.6 de [`axes_amelioration.md`](axes_amelioration.md)). Le bouchon reconnaît
les comparaisons de `sequence` à un littéral entier, dans les deux écritures
(`properties(edge).sequence` et `$-.seq`) et les deux ordres d'opérandes ; il ne
reconnaît ni une comparaison entre deux colonnes, ni un `IN` sur une liste —
aucune des deux n'écrit une fenêtre de lecture. Les tests qui appellent
`_window_around` seul, enfin, restent verts des deux côtés du défaut.

Pour la forme du graphe elle-même — profondeur, imbrication des titres, et les
214 en-têtes sans frère en-tête — le site canonique est le **§4.6** de
[`axes_amelioration.md`](axes_amelioration.md).

## MinIO — les illustrations

| | |
|---|---|
| Adresse | `minio:9000`, bucket `documents` |
| Utilisé par | `src/agent/minio_client.py` |

Les URLs stockées pointent sur `minio:9000`, que le navigateur de l'utilisateur
ne sait pas résoudre : l'API les sert via `GET /media/{chemin}`. Ce proxy est
borné aux objets référencés par le graphe — voir [SECURITY.md](SECURITY.md).

## Quand un store tombe

Les clients sont mémorisés. Un redémarrage de store rendait donc l'agent
inutilisable jusqu'à son propre redémarrage ; chaque module sait désormais
oublier son cache et retenter une fois. Un redémarrage devient invisible, au
prix d'une requête perdue.

`GET /health` sonde les trois, plus l'état de l'index BM25 — ce dernier
n'entrant pas dans le calcul du statut, puisque son absence dégrade la recherche
sans l'empêcher.

Les quatre sondes partent **ensemble**, sous un plafond global de 3 s : en
séquence, elles dépassaient le délai de 5 s que `docker-compose.yml` accorde au
healthcheck, et le frontend — qui attend `agent-api` en `service_healthy` — ne
démarrait alors jamais (§1.27 du registre). Une sonde qui n'est pas revenue avant
le plafond vaut `false` dans `services`, comme une panne : « je n'ai pas eu le
temps de regarder » ne doit pas se lire « ça répond ». Les deux cas se
distinguent quand même, à côté — `services_unknown` nomme les sondes qui n'ont
pas répondu — parce qu'un store qui **avale** les paquets et un store qui refuse
la connexion ne se soignent pas de la même façon.

Un compte de collection **illisible** n'est pas traité comme un index périmé :
Chroma injoignable est déjà rapporté par `services.chromadb` dans la même
réponse, et le déduire une seconde fois transformerait une panne de store en
reconstructions inutiles. Le doute est rendu tel quel.

Le seul store que l'agent **écrit** est le sien : `checkpoints.sqlite`, dans le
volume `rag_agent_state`. Il y ajoute une table `sessions_agent`, le registre
qui rend la purge des sessions durable — voir
[architecture.md](architecture.md#purge-durable-des-sessions). `GET /health`
publie `sessions.purged` et `sessions.failures` : un `purged` qui reste à zéro
alors que le fichier grossit est le symptôme à surveiller.
