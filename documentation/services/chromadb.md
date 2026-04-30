# ChromaDB (Base vectorielle)

## Role

Base de donnees vectorielle stockant les embeddings des elements textuels extraits
des documents. Utilisee pour la recherche semantique.

## Container

- `chromadb` : image `chromadb/chroma:0.6.3`, port interne 8000

## API

API REST standard ChromaDB. Consommee par le pipeline Dagster
(`vectorize_content`) et le service Docling (`_flush_to_chroma`).

## Collection

- `rag_documents` : collection principale
  - **embeddings** : vecteurs 384 dimensions (all-MiniLM-L6-v2)
  - **metadatas** : `element_id`, `graph_node_id`, `page_position`, `ref_position`, `minio_url`
  - **documents** : texte du chunk (max 500 caracteres)

## Variables d'environnement

| Variable   | Description    | Defaut   |
|------------|----------------|----------|
| CHROMA_HOST | Hostname      | chromadb |
| CHROMA_PORT | Port          | 8000     |

## Dependances

Aucune (service autonome).

## Persistence

Volume : `./Datas/database/chromadb:/chroma/chroma`

## Healthcheck

```bash
curl -s http://chromadb:8000/api/v1/heartbeat
```
