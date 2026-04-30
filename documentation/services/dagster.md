# Dagster (Orchestrateur ETL)

## Role

Orchestre le pipeline d'ingestion documentaire : detection de fichiers, appel au
service Docling, construction du graphe de connaissances, vectorisation.

## Containers

- `dagster-webserver` : UI web (port 3000)
- `dagster-daemon` : execution des sensors et runs en arriere-plan
- `postgres-dagster` : base PostgreSQL pour les metadonnees Dagster

## Variables d'environnement

| Variable               | Description                     | Defaut            |
|------------------------|---------------------------------|-------------------|
| DAGSTER_POSTGRES_USER  | Utilisateur PostgreSQL          | dagster           |
| DAGSTER_POSTGRES_PASSWORD | Mot de passe PostgreSQL      | (voir .env)       |
| DAGSTER_POSTGRES_DB    | Nom de la base                  | dagster           |
| DAGSTER_POSTGRES_HOST  | Hostname du conteneur Postgres  | postgres-dagster  |

## Dependances

- `postgres-dagster` (metadonnees)
- `docling-service` (extraction via HTTP)
- `chromadb` (vectorisation)
- `graphd` (graphe de connaissances via nebula3-python)

## Assets

- `pre_process_pdf` / `pre_process_html` : preparation du fichier
- `extract_structured_json` : appel POST au service Docling
- `build_knowledge_graph` : insertion dans NebulaGraph
- `vectorize_content` : chunking + embeddings + upsert ChromaDB

## Sensors

- `pdf_sensor` : surveille `Datas/` pour les .pdf (interval 30s)
- `html_sensor` : surveille `Datas/` pour les .html (interval 30s)

## Healthcheck

```bash
curl -s http://localhost:3000/server_info | python3 -m json.tool
```

## Volumes

- `./src` monte dans `/opt/dagster/app/src`
- `./Datas` monte dans `/opt/dagster/app/Datas`
- `./dagster.yaml` monte dans `/opt/dagster/dagster_home/dagster.yaml`
