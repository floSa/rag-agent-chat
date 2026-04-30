# PostgreSQL (Metadonnees Dagster)

## Role

Base de donnees relationnelle stockant les metadonnees de Dagster : runs, events,
schedules, sensors state, asset materializations.

## Container

- `postgres-dagster` : image `postgres:15-alpine`, port interne 5432

## Variables d'environnement

| Variable                 | Description      | Defaut           |
|--------------------------|------------------|------------------|
| DAGSTER_POSTGRES_USER    | Utilisateur      | dagster          |
| DAGSTER_POSTGRES_PASSWORD| Mot de passe     | (voir .env)      |
| DAGSTER_POSTGRES_DB      | Nom de la base   | dagster          |
| DAGSTER_POSTGRES_HOST    | Hostname         | postgres-dagster |

## Dependances

Aucune (service autonome).

## Persistence

Volume : `./Datas/database/postgres:/var/lib/postgresql/data`

## Healthcheck

```bash
pg_isready -h postgres-dagster -U dagster
```

## Notes

Cette instance PostgreSQL est exclusivement dediee a Dagster. Les donnees metier
(documents, elements) sont dans NebulaGraph et ChromaDB.
