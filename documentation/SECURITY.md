# Sécurité

Ce document décrit la posture de **rag-agent-chat**. La sécurité des stores
(ChromaDB, NebulaGraph, MinIO) relève de
[rag-ingestion-pipeline](https://github.com/floSa/rag-ingestion-pipeline), celle
des modèles de [llm-service](https://github.com/floSa/llm-service).

> La version précédente de ce fichier décrivait la stack d'ingestion — Dagster,
> PostgreSQL, Python 3.10 — et annonçait des mesures « quand la couche RAG agent
> sera ajoutée ». Elle l'est depuis des mois.

## Ce que l'API expose

| Surface | État | Réglage |
|---|---|---|
| Authentification | **Optionnelle**, désactivée par défaut | `API_KEY` |
| CORS | Origines déclarées, pas de `*` | `CORS_ORIGINS` |
| Proxy média | Borné aux objets référencés par le graphe | `RESTRICT_MEDIA_TO_GRAPH` |
| Chiffrement | Aucun — HTTP en clair | — |
| Limitation de débit | Aucune | — |
| Capture d'usage | **Active par défaut**, sur le disque local | `USAGE_CAPTURE` |

**Le déploiement par défaut convient à un poste local derrière un pare-feu, pas
à une exposition.** Avant d'exposer l'API, au minimum : renseigner `API_KEY`,
restreindre `CORS_ORIGINS` aux origines réelles, et placer un reverse proxy TLS
devant.

## Les trois défenses, et ce qu'elles couvrent

### Clé d'API

Renseigner `API_KEY` fait exiger l'en-tête `X-API-Key` sur toutes les routes
sauf `/health` — une sonde qui exige un secret n'est plus surveillée par
grand-chose. La comparaison passe par `secrets.compare_digest`, pas par `==` :
une comparaison naïve fuit la longueur du préfixe correct par son temps
d'exécution.

Vide, la dépendance ne fait rien. C'est un choix assumé pour l'usage local, pas
un oubli.

### CORS

`allow_origins=["*"]` laissait n'importe quelle page web ouverte dans le
navigateur de l'utilisateur interroger l'API — et, tant qu'aucune clé n'est
exigée, lire le corpus. Les origines sont déclarées, les méthodes bornées à
`GET`/`POST`, les en-têtes à ce qui sert.

### Proxy média

`GET /media/{chemin}` servait n'importe quel objet du bucket à qui devinait son
chemin. Deux contrôles, dans cet ordre :

1. **Anti-traversal** — le chemin est validé contre un motif et `..` est refusé.
   Cela empêche de sortir du bucket, pas d'y fouiller.
2. **Référencement** — l'objet doit être cité par un nœud `Picture` ou `Table`
   du graphe. Un objet inconnu déclenche une relecture unique de la liste, pour
   qu'un document fraîchement ingéré n'exige pas un redémarrage.

L'ordre compte, et un test le vérifie : un chemin malformé ne doit pas atteindre
le graphe.

## Injection nGQL

Les identifiants de nœuds sont **interpolés** dans les requêtes NebulaGraph — le
pilote ne propose pas de requêtes paramétrées. Deux régimes :

- **Identifiants d'éléments** : hash `^[a-f0-9]{10}$`, validé strictement. C'est
  le seul format qu'un appelant extérieur peut fournir, et le type `ElementId`
  le contraint dès le schéma Pydantic.
- **Identifiants de documents** : dérivés d'un chemin — séparateurs, espaces,
  accents, jusqu'à 256 octets. Aucun motif raisonnable ne les couvre sans
  devenir une passoire. Ils ne viennent jamais de l'utilisateur : ils sont
  découverts en remontant le graphe, et **échappés** plutôt que filtrés.
  L'antislash est échappé en premier, sans quoi les séquences produites seraient
  invalides.

Les caractères de contrôle sont refusés : ce sont les seuls capables de casser
une littérale une fois guillemets et antislashs échappés.

## Ce qui n'est pas protégé

- **Injection de prompt.** Un document ingéré peut contenir des instructions que
  le LLM suivra. Le corpus est réputé de confiance ; il ne l'est que parce que
  c'est vous qui l'alimentez.
- **Données personnelles.** Aucune détection ni anonymisation. Un corpus en
  contenant les verrait ressortir dans les réponses.
- **Journalisation.** Les questions, les sources proposées et les réponses sont
  désormais **enregistrées sur le disque local** — cf. « Ce qui est enregistré »
  ci-dessous. La version précédente de ce document affirmait le contraire ; ce
  n'est plus vrai.
- **Épuisement de ressources.** Rien ne limite le débit. Une boucle sur `/answer`
  saturerait le serveur d'inférence partagé.

## Ce qui est enregistré

Depuis la capture d'usage, le service tient un journal de ce qu'il sert. Le
détail du schéma et des requêtes est dans
[capture_usage.md](capture_usage.md) ; ce qui suit est la posture.

| | |
|---|---|
| **Quoi** | la question telle qu'elle a été posée, sa réécriture et sa traduction, le classement complet des sources, celles que l'utilisateur a retenues ou décochées, la réponse, les citations, les latences, et l'appréciation quand elle est donnée |
| **Où** | `/app/data/usage.sqlite`, volume Docker `rag_agent_state`, sur la machine hôte |
| **Combien de temps** | indéfiniment — **aucune purge**, c'est un jeu de données et non un cache |
| **Sortie réseau** | aucune, rien ne quitte le disque local |
| **Comment le désactiver** | `USAGE_CAPTURE=false` (ou `USAGE_DB_PATH=` vide) : le fichier n'est alors même pas créé |
| **Comment le voir grossir** | `GET /health` porte le nombre de lignes et le poids du fichier ; le démarrage les journalise |

### Pourquoi le drapeau est à VRAI par défaut

C'est une décision assumée, pas un oubli. Un drapeau à faux annule le dispositif :
personne ne le basculera avant les premiers utilisateurs, et les premières
semaines d'usage sont les plus instructives — elles ne se rattrapent pas.

Ce qui rend la décision tenable est que **l'exposition n'est pas nouvelle**. Le
checkpointer LangGraph persiste **déjà** l'état complet du graphe — question,
historique, chunks, contextes reconstruits, réponse — dans le même volume, sous
`/app/data/checkpoints.sqlite`.

Une purge est bien écrite : `_register_thread` appelle `delete_thread` sur les
sessions périmées par l'âge ou par le nombre. **Elle n'aboutit jamais.**
`delete_thread` est la méthode SYNCHRONE d'`AsyncSqliteSaver`, appelée depuis
`chat_start`, donc depuis le fil de la boucle d'événements ; la bibliothèque
refuse explicitement ce cas et lève `asyncio.InvalidStateError` — « *Synchronous
calls to AsyncSqliteSaver are only allowed from a different thread* ». Cette
exception hérite d'`Exception`, donc le `except Exception: logger.debug(…)` qui
entoure l'appel l'absorbe, et `LOG_LEVEL` vaut `INFO` par défaut : rien ne
paraît. Pire, la ligne `INFO « Sessions purgées : N »` est journalisée juste
après, et affirme une purge qui n'a pas eu lieu.

Vérifié : après deux passages de `_register_thread` sur une session périmée, la
table `checkpoints` porte toujours sa ligne et la question s'y relit en clair.
**Aucune ligne n'est jamais supprimée de `checkpoints.sqlite`** — l'état complet
de toutes les sessions y persiste indéfiniment, pas seulement celles antérieures
à un redémarrage.

Ce défaut appartient à un lot ultérieur, avec les autres fuites silencieuses ;
il est ouvert dans [axes_amelioration.md](axes_amelioration.md). Il ne change
pas la posture de la capture, il la renforce : la capture ne crée **aucune**
classe d'exposition nouvelle. Elle rend **interrogeable et mesurable** ce qui
est déjà durable et invisible.

### Ce que la capture ne protège pas

- **Aucune détection de données personnelles.** Une question saisie par un
  utilisateur peut en contenir ; elle est stockée **telle quelle**, sans
  anonymisation ni masquage. C'est un fait à connaître avant d'exposer l'API à
  des tiers, pas un chantier de ce lot.
- **Aucun chiffrement au repos.** Le fichier est lisible par qui accède au
  volume, comme les checkpoints à côté de lui.
- **Aucun contrôle d'accès propre.** Les enregistrements se lisent avec
  `sqlite3` sur l'hôte, ou par `scripts/usage_export.py`. Il n'existe aucun
  endpoint de lecture : la capture écrit, elle ne sert rien.

## Secrets

- `.env` est ignoré par git ; `.env.example` documente les clés sans valeurs.
- Vérifier avant de publier : `git ls-files | grep -c '^\.env$'` doit rendre `0`.
- `MINIO_ROOT_PASSWORD` doit valoir la même chose que dans le projet
  d'ingestion — c'est le seul secret partagé.

## Dépendances

```bash
make audit          # pip-audit sur requirements.txt
```

**État au 3 août 2026 : 1 vulnérabilité connue, dans `chromadb`**
(PYSEC-2026-311). Aucune version corrigée n'est publiée à ce jour : il n'y a
rien à faire d'autre que la surveiller.

**Toutes les autres dépendances sont à leur dernière version publiée**, celles
du projet comme celles de développement. C'est un état, pas une garantie : rien
ne le maintient. `make audit` existe mais ne tourne pas en intégration
continue, et aucun outil ne signale une version qui vieillit sans faille
connue — c'est précisément ce qui a laissé passer quinze mois de retard.

### D'où venaient les 58 précédentes

L'audit n'avait jamais été lancé. Il en comptait **58 dans 10 paquets**, et la
cause tient en une phrase : **le projet a démarré, le 30 avril 2026, sur des
versions publiées le 7 mai 2025.** Elles avaient déjà onze mois le premier
jour, et aucun des commits suivants ne les a montées.

| Paquet | Avant | Après |
|---|---|---|
| `langgraph` | 0.4.3 *(mai 2025)* | 1.2.10 |
| `langchain-core` | 0.3.59 *(mai 2025)* | 1.5.3 |
| `langgraph-checkpoint-sqlite` | 2.0.11 | 3.1.1 |
| `aiosqlite` | 0.20.0 | 0.22.1 |
| `fastapi` (et `starlette`) | 0.115.12 | 0.141.1 |
| `streamlit` | 1.44.1 | 1.60.0 |
| `python-multipart` | 0.0.20 | 0.0.32 |

Un second passage a rattrapé les onze paquets restants — `uvicorn`,
`sse-starlette`, `pydantic`, `pydantic-settings`, `sentence-transformers`,
`chromadb`, `ruff`, `mypy`, `pytest`, `pytest-asyncio`, `pip-audit` — dont
aucun n'était signalé par l'audit, et dont la plupart dataient d'avril 2025.

Deux d'entre eux touchaient la **qualité** et non la sécurité :
`sentence-transformers` produit les vecteurs de la question, et `chromadb` les
compare à ceux que l'ingestion a écrits. Un écart aurait dégradé la recherche
sans lever la moindre erreur — le mode de panne le plus coûteux du système.
Vérifié avant de monter : les deux versions encodent les mêmes phrases en
vecteurs **identiques au bit près**, puis une campagne complète l'a confirmé
sur les 138 questions.

Le passage en LangGraph 1.x avait été annoncé ici comme un « chantier à part
entière ». C'était faux, et l'erreur mérite d'être écrite : la surface d'appel
tient en six imports, et le seul code à changer a été l'annotation de type de
`build_graph`. Le diagnostic avait été posé sur le **nombre** de failles, sans
lire ce que chacune faisait ni vérifier ce que le projet utilisait vraiment.

L'épinglage `aiosqlite<0.21` a sauté avec : il existait parce que
`langgraph-checkpoint-sqlite` 2.x appelait `conn.is_alive()`, ce que la 3.x ne
fait plus.

Validé après montée, **le 3 août 2026** : `mypy` + `ruff`, les 173 tests
unitaires d'alors, 10 tests d'intégration contre la stack, et le flux SSE vérifié
à la main — le streaming et l'interruption `interrupt_before` étaient les deux
points de rupture plausibles. Le décompte courant vit dans
[tests.md](tests.md) ; celui-ci date la validation, il ne la remplace pas.

`mypy` était épinglé en 1.15.0 avec cette justification : « une version plus
récente est plus permissive sur les valeurs `Any` traversant une frontière
JSON ». Elle était fausse. Mise à l'épreuve sur le défaut qu'elle prétendait
protéger — une fonction déclarée `-> int` qui renvoie le résultat d'un
`json.loads` — la 1.15 et la 2.3 lèvent **la même erreur** `no-any-return`.
L'épinglage a donc sauté, et avec lui le contournement PEP 696 qu'il imposait
sur les paramètres génériques de `StateGraph`.

La leçon vaut plus que le paquet : **un épinglage doit porter une raison
vérifiable, et la raison doit être vérifiée avant d'être écrite.** Celle-ci a
figé un outil pendant dix-huit mois.
