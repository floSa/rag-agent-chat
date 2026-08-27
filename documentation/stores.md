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
| `PARENT_OF(sequence)` | Hiérarchie **et** ordre de lecture. C'est `sequence` qui permet d'atteindre la section voisine. |
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
