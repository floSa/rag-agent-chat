# Docling Service (Extraction documentaire)

## Role

Microservice FastAPI d'extraction structuree de documents. Utilise Docling (IBM)
pour l'analyse de layout et PyMuPDF pour le crop d'images. Seul service avec acces GPU.

## Container

- `docling-service` : FastAPI + CUDA 12.1, port interne 8000

## API

| Methode | Endpoint   | Body                                    | Reponse              |
|---------|------------|-----------------------------------------|----------------------|
| POST    | /extract   | `{"filepath": "/opt/.../fichier.pdf"}`  | `{"status": "success"}` |

## Variables d'environnement

| Variable             | Description                | Defaut        |
|----------------------|----------------------------|---------------|
| MINIO_ENDPOINT       | Endpoint MinIO             | minio:9000    |
| MINIO_ROOT_USER      | Access key MinIO           | (voir .env)   |
| MINIO_ROOT_PASSWORD  | Secret key MinIO           | (voir .env)   |
| MINIO_BUCKET         | Bucket pour les medias     | documents     |
| NEBULA_HOST          | Hostname NebulaGraph       | graphd        |
| NEBULA_PORT          | Port NebulaGraph           | 9669          |
| CHROMA_HOST          | Hostname ChromaDB          | chromadb      |
| CHROMA_PORT          | Port ChromaDB              | 8000          |
| EMBEDDING_MODEL_NAME | Modele SentenceTransformers | all-MiniLM-L6-v2 |

## Dependances

- `minio` (stockage images/tables croppees)
- `graphd` (insertion noeuds NebulaGraph)
- `chromadb` (vectorisation des elements texte)

## Ressources

- GPU NVIDIA (CUDA 12.1)
- RAM : 10 Go max (`deploy.resources.limits.memory`)
- SHM : 2 Go (`shm_size`)

## Healthcheck

```bash
curl -s http://docling-service:8000/docs
```
