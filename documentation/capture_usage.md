# La capture d'usage

Ce document décrit ce que le service enregistre de son propre usage, sous quelle
forme, et comment l'interroger. Il ne décrit pas ce qu'on en fait :
**l'exploitation des données est un lot à venir**, et rien ici ne promeut
automatiquement quoi que ce soit.

## Pourquoi

Le dépôt n'enregistrait rien de ce qu'il servait : ni les questions, ni les
sources proposées, ni celles que l'utilisateur décochait, ni les réponses, ni la
moindre appréciation. Ce n'était pas seulement l'absence d'une piste d'audit,
c'était le renoncement à **la seule vérité terrain non biaisée qui puisse
exister ici**. Le jeu doré de 138 questions est généré depuis le corpus et
jamais relu ([axes_amelioration.md](axes_amelioration.md)) ; il sert à régler un
retriever, il ne dit pas ce que les gens demandent.

La capture précède l'usage, et c'est délibéré : il n'y a aucun utilisateur
aujourd'hui, les premières semaines sont les plus instructives, et elles ne se
rattrapent pas.

## Les trois usages, qui dictent la forme du schéma

Le schéma est conçu pour ces trois questions, pas pour « tout enregistrer au cas
où ». Les requêtes sont données plus bas et ont toutes été exécutées contre une
base réelle. Une version précédente de ce document s'arrêtait là : deux d'entre
elles étaient **syntaxiquement** exécutables et **faussées**, faute du filtre
qui écarte les interactions sans décision humaine. Elles lisent désormais des
vues, ou portent le filtre et la raison de l'avoir.

1. **Les décochages.** Quand quelqu'un décoche une source que le reranker avait
   classée deuxième avec 0,81 de pertinence, il produit gratuitement
   l'annotation négative qu'aucun jeu généré ne contient. D'où **une ligne par
   source proposée**, portant son rang, sa pertinence, son document, sa section,
   sa langue, et son sort.
2. **Un jeu doré réel.** Les questions réellement posées, les sources qu'un
   humain a validées, et son appréciation de la réponse.
3. **La distribution des classes de questions.** Trois classes ne sont pas
   couvertes par l'architecture — « résume ce document », l'agrégation
   (« combien de documents parlent de X »), le multi-saut réel. On ne sait pas
   si c'est un manque coûteux ou une inquiétude théorique : seul l'usage le
   dira, d'où la question stockée **telle qu'elle a été posée**, sans
   normalisation.

## Ce qui est capturé, et où

| | |
|---|---|
| Fichier | `/app/data/usage.sqlite` (`USAGE_DB_PATH`), volume `rag_agent_state` |
| Activation | `USAGE_CAPTURE=true` **par défaut** — cf. [SECURITY.md](SECURITY.md) |
| Durée de conservation | illimitée, **aucune purge** |
| Taille | journalisée au démarrage, exposée par `GET /health` |
| Sortie réseau | aucune, tout reste sur le disque local |

Un enregistrement couvre **deux requêtes HTTP** : `/chat/start` connaît les
sources proposées, `/chat/resume` connaît celles qui ont été retenues et la
réponse. Les deux phases sont jointes par `thread_id`, inséré à la première et
complété à la seconde.

Trois chemins sont capturés, et la colonne `endpoint` les distingue — ce n'est
pas cosmétique, **toute lecture des décochages doit filtrer dessus** :

| `endpoint` | Chemin | Sélection des sources | Lignes `sources_proposees` |
|---|---|---|---|
| `chat` | `/chat/start` + `/chat/resume` | **humaine** | oui |
| `answer` | `/answer` | automatique (`AUTO_SELECT_TOP_K`) | oui |
| `chat_simple` | `/chat/simple` | faite par le client en amont | non — rien n'a été proposé |

`/chat/simple` **rend son `thread_id`** — dans l'événement final en SSE, dans
`ChatResponse` sinon. C'est la seule route qui en crée un que l'appelant ne
connaît pas : sans lui, ses interactions seraient enregistrées puis muettes,
jamais notables par `/feedback`, et l'usage « jeu doré réel » les exclurait en
silence. `/answer` n'en rend pas, et c'est différent : personne n'est là pour
noter une question de campagne.

`/answer` est capturé parce qu'il permet de comparer une campagne à l'usage
réel. Conséquence à connaître : **une campagne `make eval` écrit 138
interactions**, toutes en `endpoint = 'answer'`. Sans le filtre, elles noient
l'usage humain.

## Le schéma

### `interactions` — une ligne par interaction

| Colonne | Type | Contenu |
|---|---|---|
| `thread_id` | TEXT, clé primaire | identifiant de session LangGraph — la jointure |
| `endpoint` | TEXT | `chat`, `answer` ou `chat_simple` (cf. ci-dessus) |
| `started_at` / `completed_at` | TEXT | horodatage ISO 8601 UTC ; `completed_at` NULL = abandonné avant la réponse |
| `question` | TEXT | la question **telle qu'elle a été posée** |
| `search_query` | TEXT | la question rendue autonome par `node_rewrite` |
| `search_translation` | TEXT | la question traduite, qui n'a servi qu'à chercher |
| `ranked_element_ids` | TEXT (JSON) | le classement complet, du mieux au moins bien classé |
| `submitted_element_ids` | TEXT (JSON) | les éléments dont la section a réellement été soumise |
| `submitted_section_ids` | TEXT (JSON) | les sections correspondantes — deux éléments d'une même section n'en font qu'une. Ce sont les sections **reconstruites**, avant la coupe de fenêtre : à lire avec `dropped_contexts` |
| `response` | TEXT | la réponse, marqueurs `[src:…]` compris |
| `citations` / `images` | TEXT (JSON) | les identifiants effectivement cités et illustrés |
| `search_count` | INTEGER | itérations de la boucle agentique (> 1 = le modèle a redemandé) |
| `dropped_contexts` | INTEGER | sections reconstruites que le budget de fenêtre a écartées avant le modèle. `submitted_section_ids` moins celles-ci = ce qui a réellement atteint le LLM, seul chiffre qu'aucune colonne ne stocke |
| `retrieval_ms` / `rerank_ms` / `generation_ms` | INTEGER | latences par étage |
| `config_hash` | TEXT | empreinte courte de la configuration — sert à grouper |
| `config_json` | TEXT (JSON) | son détail |
| `rating` | TEXT | `utile`, `inutile`, ou NULL — personne n'est obligé de répondre |
| `rating_comment` | TEXT | commentaire libre, facultatif |
| `rated_at` | TEXT | horodatage de l'appréciation |

### `sources_proposees` — une ligne par source proposée

| Colonne | Type | Contenu |
|---|---|---|
| `thread_id` + `element_id` | TEXT, clé primaire | la jointure et l'élément |
| `rang` | INTEGER | rang dans le classement du reranker, 1 = le mieux classé |
| `filename` / `collection` / `source_path` | TEXT | le document, son ouvrage, son identité réelle |
| `section_title` | TEXT | la section porteuse |
| `language` | TEXT | la langue du document (le corpus est mixte) |
| `page_no` | INTEGER | la page |
| `relevance` | REAL | pertinence dans [0, 1] — la sigmoïde du logit |
| `rerank_score` | REAL | le logit brut du cross-encoder |
| `retenue` | INTEGER | **1** retenue, **0** écartée, **NULL** la sélection n'a jamais eu lieu |

Les trois états de `retenue` sont distincts et doivent le rester : compter un
abandon devant l'écran de sélection comme un décochage fabriquerait une
annotation négative que personne n'a produite — précisément le biais que le jeu
doré généré a déjà.

### Les deux vues, et pourquoi elles existent

| Vue | Contenu |
|---|---|
| `sources_humaines` | les sources d'interactions `endpoint = 'chat'`, les trois états de `retenue` conservés, augmentées de `question`, `started_at` et `rating` |
| `decochages` | `sources_humaines` restreinte à `retenue = 0` |

**Elles ne sont pas une commodité d'écriture.** `/answer` retient
`AUTO_SELECT_TOP_K` sources — trois par défaut — et écrit `retenue = 0` sur
toutes les autres : ce sont des zéros produits par une décision automatique que
personne n'a prise, et **rien ne les distingue en SQL d'un décochage humain**. À
`RERANK_TOP_K = 10`, cela fait sept faux décochages par question, près de mille
par campagne de 138 questions, dans la table dont dépend tout l'intérêt du lot.

La version précédente de ce document répondait « toute lecture DOIT filtrer sur
`endpoint` ». C'était une convention, et une convention ne survit pas à une
requête écrite de mémoire dans six mois — deux des requêtes de ce document même
l'avaient déjà perdue. Les vues rendent l'erreur impossible au lieu de la
déconseiller.

Mesuré sur une base contenant une interaction interactive à trois décochages
humains et une interaction `/answer` à trois zéros automatiques :
`SELECT COUNT(*) FROM sources_proposees WHERE retenue = 0` rend **6**,
`SELECT COUNT(*) FROM decochages` rend **3**.

`decochages` est nommée par ce qu'elle contient, et rien d'autre : une vue
« décochages » qui rendrait aussi les sources retenues serait un second piège de
la même espèce.

Deux limites du `rang`, à connaître avant de l'interpréter :

- c'est le rang du **reranker**, pas l'ordre dans lequel l'interface a présenté
  les sources : le frontend les regroupe par document ;
- les sources ajoutées par une itération de la boucle agentique ne sont pas dans
  cette table — elles n'ont jamais été proposées à personne. Elles apparaissent
  dans `submitted_element_ids`.

## L'empreinte de configuration

Un enregistrement sans la configuration qui l'a produit est illisible dans six
mois : on ne sait plus si un écart vient du corpus, d'un réglage ou du prompt.
Chaque interaction porte donc `config_json` (le détail) et `config_hash` (12
caractères, pour grouper) :

```json
{
  "embedding_model": "paraphrase-multilingual-MiniLM-L12-v2",
  "rerank_model": "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1",
  "retrieval_top_k": 50, "rerank_top_k": 10, "translation_weight": 1.0,
  "llm_num_ctx": 8192, "llm_max_tokens": 4096, "ollama_model": "gemma4:e4b",
  "prompts_sha256": "5c71fd1d6414"
}
```

Le dernier champ est un **condensat du contenu de `prompts/`**, et il règle un
défaut connu : jusqu'ici, une modification de prompt n'était attribuable dans
aucune campagne. Deux réponses différentes portaient la même configuration
apparente.

```sql
-- Ce que chaque configuration a produit, et comment elle a été jugée.
SELECT i.config_hash,
       json_extract(i.config_json, '$.ollama_model')   AS modele,
       json_extract(i.config_json, '$.prompts_sha256') AS prompts,
       COUNT(*)                      AS interactions,
       -- Dénominateur des deux colonnes suivantes : une interaction de
       -- campagne ne peut jamais être notée. Sans cette colonne, on divise les
       -- avis par 138 questions rejouées et on lit « 2 % d'utiles ».
       SUM(i.endpoint = 'chat')      AS interactives,
       SUM(i.rating = 'utile')       AS utiles,
       SUM(i.rating = 'inutile')     AS inutiles
FROM   interactions i
GROUP  BY i.config_hash
ORDER  BY interactions DESC;
```

Celle-ci ne filtre pas, délibérément : l'attribution à une configuration vaut
pour **toutes** les interactions, campagne comprise — c'est même son intérêt.
Ce qui manquait était le dénominateur des appréciations, pas le filtre.

## Les requêtes des trois usages

### 1. Les décochages

Ces deux requêtes lisent les **vues**, jamais `sources_proposees` directement.
Ce n'est pas un raccourci d'écriture : c'est ce qui empêche l'erreur décrite
plus haut.

```sql
-- Quelles sources bien classées les gens écartent-ils, et qu'ont-elles en commun ?
SELECT collection, filename, section_title, language,
       COUNT(*)                 AS decochages,
       MIN(rang)                AS meilleur_rang,
       ROUND(AVG(relevance), 3) AS pertinence_moyenne
FROM   decochages              -- humains uniquement, retenue = 0
WHERE  relevance >= 0.5        -- « bien classée » : le reranker y croyait
GROUP  BY collection, filename, section_title
ORDER  BY decochages DESC, meilleur_rang;
```

```sql
-- Le taux de retenue par rang : à partir d'où le classement cesse-t-il de convaincre ?
SELECT rang,
       COUNT(*)     AS proposees,
       SUM(retenue) AS retenues,
       ROUND(1.0 * SUM(retenue) / COUNT(*), 3) AS taux_de_retenue
FROM   sources_humaines        -- les trois états, mais aucun /answer
WHERE  retenue IS NOT NULL     -- NULL = sélection jamais faite, pas un rejet
GROUP  BY rang
ORDER  BY rang;
```

### 2. Un jeu doré réel

```sql
-- Question posée, sources validées par un humain, réponse, appréciation.
-- Ajouter « AND i.rating = 'utile' » pour ne lire que ce qui a convaincu.
SELECT i.question, i.response, i.rating, i.rating_comment,
       json_group_array(s.element_id) AS sources_validees
FROM   interactions     i
JOIN   sources_humaines s ON s.thread_id = i.thread_id AND s.retenue = 1
WHERE  i.completed_at IS NOT NULL
GROUP  BY i.thread_id
ORDER  BY i.started_at;
```

Ce que cette requête rend possible n'est pas fait ici : **décider quelles
questions promeuvent, et avec quelle annotation, est le travail d'un lot
ultérieur.**

### 3. La distribution des classes de questions

```sql
-- Classement par mots-clés : une première coupe, pas une vérité. Ce qui compte
-- est que la question soit stockée telle quelle — un meilleur classificateur
-- pourra être passé plus tard sur les mêmes lignes.
SELECT CASE
         WHEN lower(i.question) LIKE '%résume%'
           OR lower(i.question) LIKE '%résumé%'
           OR lower(i.question) LIKE '%summar%'         THEN 'résumé de document'
         WHEN lower(i.question) LIKE '%combien%'
           OR lower(i.question) LIKE '%how many%'
           OR lower(i.question) LIKE '%quels documents%' THEN 'agrégation'
         ELSE 'factuelle ou autre'
       END                              AS classe,
       COUNT(*)                         AS questions,
       ROUND(AVG(i.search_count), 2)    AS recherches_moyennes,
       SUM(i.rating = 'inutile')        AS jugees_inutiles
FROM   interactions i
WHERE  i.endpoint = 'chat'
GROUP  BY classe
ORDER  BY questions DESC;
```

```sql
-- Le multi-saut réel : le modèle a-t-il redemandé à chercher, et sur quoi ?
SELECT i.question, i.search_count, i.dropped_contexts
FROM   interactions i
WHERE  i.search_count > 1
  AND  i.endpoint = 'chat'   -- cette section porte sur ce que les GENS demandent
ORDER  BY i.started_at;
```

Le filtre manquait ici, et son absence n'était pas neutre : une campagne de 138
questions rejouées chaque jour aurait dominé le comptage. Retirez-le et la
question change de nature — elle porte alors sur le comportement du **graphe**,
où une question de campagne est une observation aussi valable qu'une question
humaine. Sachez seulement laquelle des deux vous lisez.

## L'appréciation

`POST /feedback` attache une note à une interaction déjà enregistrée :

```bash
curl -X POST http://localhost:8011/feedback \
  -H 'Content-Type: application/json' \
  -d '{"thread_id": "…", "rating": "utile", "comment": "facultatif"}'
```

Le rating est **binaire** et pas une échelle : personne ne remplit une échelle,
et un 3/5 ne se lit pas. Deux boutons dans la phase de réponse du frontend
écrivent dessus. Le `thread_id` vient de `/chat/start` sur le flux interactif,
et de la réponse de `/chat/simple` sur la génération directe. Un `thread_id` inconnu rend 404 ; la capture désactivée rend
200 avec `recorded: false` — ce n'est pas une erreur du client.

## Le coût

Mesuré sur le module seul, la stack étant absente (100 interactions
séquentielles de 10 sources chacune, réponse d'environ 1 000 caractères) :

**Le support de stockage domine ces chiffres**, et c'est la première chose à
lire. Cent interactions séquentielles de dix sources, réponse d'environ mille
caractères, même code, même machine :

| Support | `record_start` | `record_completion` |
|---|---|---|
| ext4, disque virtuel WSL2 | médiane **5,2 ms**, p95 6,8 ms | médiane **4,6 ms**, p95 6,6 ms |
| tmpfs (`/dev/shm`) | médiane **1,3 ms**, p95 1,8 ms | médiane **1,1 ms**, p95 1,4 ms |

Un facteur quatre entre les deux, sur la même machine. L'audit du lot relève
17,6 / 16,4 ms sur un support plus lent encore : **citer une durée sans nommer
le support ne veut rien dire**, et c'est le seul chiffre du lot qui n'ait pas
été reproduit d'emblée. Retenir l'ordre de grandeur — quelques millisecondes
par écriture — et remesurer sur le support de déploiement.

| | |
|---|---|
| Poids d'un enregistrement | environ **4,6 ko** (11 lignes : 1 interaction + 10 sources) — granulaire à la page SQLite, donc peu sensible à la longueur de la réponse |
| 20 interactions simultanées | 91 à 370 ms au total selon le tirage, aucune écriture perdue |
| Part synchrone sur la boucle d'événements | médiane **0,114 ms**, p95 0,327 ms — le condensat des prompts et le `mkdir`, seules E/S non déportées |

Ce sont les chiffres du module, pas ceux du service : **la stack n'est pas
disponible**, donc la latence réellement ajoutée à `/chat/resume` n'a pas été
mesurée de bout en bout. Elle vaut ces quelques millisecondes, payées après le
dernier événement SSE — contre une génération qui dure de 3 à 10 secondes.

Rien de tout cela n'est dans le chemin de diffusion : l'écriture de
`/chat/resume` a lieu **après** le dernier événement SSE. Les 5 ms de
`/chat/start` s'ajoutent à une requête qui en dure plusieurs centaines.

Trois réglages SQLite portent ces chiffres, et chacun a une raison :

- `PRAGMA journal_mode = WAL` **au démarrage seulement** — le changer exige un
  verrou exclusif, et ce changement-là ne respecte pas le délai d'attente. C'est
  le seul défaut auquel la perte d'écritures simultanées ait pu être imputée, et
  il a été isolé : avec le PRAGMA dans le chemin d'écriture, dix interactions
  simultanées perdaient **six écritures sur vingt** ; sans lui, vingt écritures
  concurrentes n'en perdent aucune sur trois tirages ;
- `BEGIN IMMEDIATE` avec `isolation_level=None` — ce qui rend une capture
  atomique : sans lui, l'interaction et ses sources partiraient en deux
  transactions, et un arrêt entre les deux laisserait une interaction sans son
  classement. Il évite en outre le `SQLITE_BUSY` qu'une transaction *deferred*
  reçoit en promouvant son verrou, et que le délai d'attente ne rejoue pas.
  Cette seconde raison est une précaution documentée, **pas** un correctif
  mesuré : retiré seul, il ne fait rien perdre dans les conditions du test ;
- `PRAGMA synchronous = NORMAL` — perdre la dernière transaction lors d'une
  coupure de courant est acceptable pour de l'observation ; faire attendre une
  requête le temps d'un `fsync` ne l'est pas. Mesuré : 1 162 ms pour vingt
  interactions simultanées en synchronisation complète, contre 213 ms ici.

## Exporter

```bash
uv run python scripts/usage_export.py                       # sur la sortie standard
uv run python scripts/usage_export.py --out runs/usage.json
uv run python scripts/usage_export.py --endpoint chat --since 2026-09-01
```

La base est ouverte **en lecture seule** (`file:…?mode=ro`) : l'export peut
tourner pendant que le service écrit, et ne fabrique jamais une base vide quand
le chemin est faux — il le dit et rend 1.

Le document de sortie imbrique les sources dans leur interaction, ce qui rend
les décochages lisibles sans jointure côté lecteur — et met le piège des vues
hors d'atteinte : une source y est toujours accompagnée de l'`endpoint` de
l'interaction qui la porte. `--endpoint chat` rend directement le sous-ensemble
humain.

```json
{
  "schema_version": 1,
  "source": "/app/data/usage.sqlite",
  "count": 1,
  "interactions": [
    {
      "thread_id": "…", "endpoint": "chat",
      "started_at": "2026-09-01T09:12:44.108+00:00",
      "completed_at": "2026-09-01T09:13:02.771+00:00",
      "question": "Comment mesurer la dispersion ?",
      "search_query": "mesure de la dispersion statistique",
      "search_translation": "how to measure dispersion",
      "ranked_element_ids": ["…"], "submitted_element_ids": ["…"],
      "submitted_section_ids": ["…"],
      "response": "…", "citations": ["…"], "images": [],
      "search_count": 1, "dropped_contexts": 0,
      "retrieval_ms": 480, "rerank_ms": 340, "generation_ms": 8400,
      "config_hash": "9f9c2cc8130d", "config_json": {"...": "..."},
      "rating": "utile", "rating_comment": null, "rated_at": "…",
      "sources_proposees": [
        {"rang": 1, "element_id": "…", "filename": "…", "collection": "…",
         "source_path": "…", "section_title": "…", "language": "en",
         "page_no": 88, "relevance": 0.95, "rerank_score": 3.2, "retenue": 1}
      ]
    }
  ]
}
```

`schema_version` est lu **dans le fichier** (`PRAGMA user_version`), pas dans le
code : un export doit dire quelles colonnes existaient au moment de l'écriture,
pas celles que le code d'aujourd'hui connaît.

Les colonnes stockées en JSON sont réhydratées — sans quoi le lecteur reçoit des
chaînes échappées à l'intérieur d'un document déjà JSON.

## Ce que la capture ne fait pas

- **Aucune détection de données personnelles.** Une question saisie par un
  utilisateur peut en contenir ; elle est stockée telle quelle. C'est un fait à
  connaître, pas un chantier de ce lot.
- **Aucune purge.** C'est un jeu de données, pas un cache : le vider serait
  détruire l'actif que la capture construit. La contrepartie est que sa taille
  doit rester **visible** — `GET /health` la porte, et le démarrage la
  journalise. Un actif qui grossit sans qu'on le sache redevient une fuite.
- **Aucun échec remonté à l'appelant.** Base verrouillée, disque plein, schéma
  divergent : on journalise en WARNING et on continue de servir. Le compteur
  `usage.failures` de `/health` dit combien d'interactions ont été servies sans
  être enregistrées.
- **Aucune exploitation.** Ni promotion en jeu doré, ni réglage automatique. Ce
  document décrit un robinet, pas une décision.

## Désactiver

```bash
USAGE_CAPTURE=false     # ou USAGE_DB_PATH= (vide)
```

Le drapeau est un vrai interrupteur : désactivé, **le fichier n'est même pas
créé**. Un fichier vide suffirait à faire croire à une capture en cours.
