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
- **Journalisation.** Les prompts et réponses ne sont pas archivés : pas de piste
  d'audit, mais pas de fuite par les journaux non plus.
- **Épuisement de ressources.** Rien ne limite le débit. Une boucle sur `/answer`
  saturerait le serveur d'inférence partagé.

## Secrets

- `.env` est ignoré par git ; `.env.example` documente les clés sans valeurs.
- Vérifier avant de publier : `git ls-files | grep -c '^\.env$'` doit rendre `0`.
- `MINIO_ROOT_PASSWORD` doit valoir la même chose que dans le projet
  d'ingestion — c'est le seul secret partagé.

## Dépendances

```bash
make audit          # pip-audit sur requirements.txt
```

**État au 3 août 2026 : 1 vulnérabilité connue, dans `chromadb` 1.5.8**
(PYSEC-2026-311). Aucune version corrigée n'est publiée à ce jour : il n'y a
rien à faire d'autre que la surveiller.

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

Le passage en LangGraph 1.x avait été annoncé ici comme un « chantier à part
entière ». C'était faux, et l'erreur mérite d'être écrite : la surface d'appel
tient en six imports, et le seul code à changer a été l'annotation de type de
`build_graph`. Le diagnostic avait été posé sur le **nombre** de failles, sans
lire ce que chacune faisait ni vérifier ce que le projet utilisait vraiment.

L'épinglage `aiosqlite<0.21` a sauté avec : il existait parce que
`langgraph-checkpoint-sqlite` 2.x appelait `conn.is_alive()`, ce que la 3.x ne
fait plus.

Validé après montée : `mypy` + `ruff`, 173 tests unitaires, 10 tests
d'intégration contre la stack, et le flux SSE vérifié à la main — le streaming
et l'interruption `interrupt_before` étaient les deux points de rupture
plausibles.

Reste un épinglage à ne pas défaire par inadvertance : `mypy==1.15.0`. Une
version plus récente est plus permissive sur les valeurs `Any` traversant une
frontière JSON, et la CI ne verrait plus ce que le code laisse passer. En
contrepartie, elle ne résout pas encore les paramètres génériques par défaut
(PEP 696), d'où les quatre paramètres explicités sur `StateGraph`.
