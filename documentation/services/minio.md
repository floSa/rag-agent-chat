# MinIO (Object Storage)

## Role

Stockage objet S3-compatible pour les medias extraits des documents (images croppees,
tableaux en PNG). Les URLs sont referencees dans le graphe de connaissances et les
metadonnees ChromaDB.

## Container

- `minio` : image pinnee, ports internes 9000 (API S3) et 9001 (console web)

## API

API S3-compatible standard. Consommee par le service Docling
(`crop_and_upload_image`) et la ressource Dagster `MinIOResource`.

## Bucket

- `documents` : bucket principal
  - Structure : `images/{filename_stem}/{element_id}_{type}.png`

## Variables d'environnement

| Variable            | Description      | Defaut     |
|---------------------|------------------|------------|
| MINIO_ROOT_USER     | Access key       | (voir .env)|
| MINIO_ROOT_PASSWORD | Secret key       | (voir .env)|
| MINIO_ENDPOINT      | Hostname:port    | minio:9000 |
| MINIO_BUCKET        | Nom du bucket    | documents  |

## Dependances

Aucune (service autonome).

## Persistence

Volume : `./Datas/database/minio:/data`

## Console

En mode debug (`docker-compose.override.yml`), la console est accessible sur
`http://localhost:9001`. Login avec les credentials de `.env`.
