# Architecture du RAG Ingestion Pipeline

## Vue d'ensemble

Pipeline d'ingestion documentaire qui transforme des PDF et HTML en données structurées,
stockées dans une base vectorielle (ChromaDB) et un graphe de connaissances (NebulaGraph).
Pas de couche LLM/agent pour le moment — c'est une pipeline d'ingestion pure.

## Services Docker

| Service           | Image / Build          | Port interne | Port hôte        | Rôle                                   |
|-------------------|------------------------|--------------|------------------|-----------------------------------------|
| chromadb          | chromadb/chroma:0.6.3  | 8000         | — (expose only)  | Base vectorielle                        |
| metad             | nebula-metad:v3.6.0    | 9559         | —                | NebulaGraph — métadonnées               |
| storaged          | nebula-storaged:v3.6.0 | 9779         | —                | NebulaGraph — stockage distribué        |
| graphd            | nebula-graphd:v3.6.0   | 9669         | — (expose only)  | NebulaGraph — moteur de requête         |
| nebula-studio     | nebula-studio:v3.8.0   | 7001         | 7001             | UI de visualisation du graphe           |
| minio             | minio (pinned)         | 9000, 9001   | — (expose only)  | Object storage S3-compatible            |
| postgres-dagster  | postgres:15-alpine     | 5432         | — (expose only)  | Métadonnées Dagster                     |
| dagster-webserver | Dockerfile.dagster     | 3000         | 3000             | UI Dagster                              |
| dagster-daemon    | Dockerfile.dagster     | —            | —                | Exécution des sensors et runs           |
| docling-service   | Dockerfile.docling     | 8000         | — (expose only)  | Extraction documentaire (GPU, FastAPI)  |

Tous les services communiquent sur le réseau bridge `rag_network`.
Pour le debug local, `docker-compose.override.yml` expose les ports internes.

## Workflow de bout en bout

1. **Dépôt** d'un fichier (PDF/HTML) dans `Datas/pdfs/` ou `Datas/htms/`
2. **Dagster Sensor** (`pdf_sensor` / `html_sensor`) détecte le nouveau fichier
3. **Pre-process** (HTML uniquement) : nettoyage DOM via BeautifulSoup — suppression des
   balises `nav`, `header`, `footer` et classes éditeurs (`.packt-header`, `.sbo-site-nav`)
4. **Docling Service** reçoit le chemin en POST, extrait la structure via Docling v9.1,
   crop les images/tableaux via PyMuPDF, les pousse sur MinIO, retourne un JSON structuré
5. **build_knowledge_graph** : crée les nœuds et relations dans NebulaGraph via nGQL
6. **vectorize_content** : découpe le texte en chunks (500 chars), génère les embeddings
   avec `all-MiniLM-L6-v2` (384 dim), upsert dans ChromaDB avec métadonnées de liaison
   vers le graphe (`graph_node_id`)

## Décisions d'architecture

- **ChromaDB** plutôt que Weaviate : plus simple, pas besoin d'UI intégrée pour le vectoriel
- **NebulaGraph** pour le graphe de connaissances : distribué (metad/storaged/graphd),
  Studio UI pour la visualisation
- **Volume partagé** `/Datas` monté dans Dagster et Docling : évite le transfert réseau
  de gros fichiers PDF
- **Docling sur GPU** : seul service avec accès CUDA, isole la charge lourde
- **Embeddings locaux** : `all-MiniLM-L6-v2` via SentenceTransformers, pas d'appel API
  externe (pas d'OpenAI)
- **Sensors séparés** PDF/HTML : découplage des pipelines, chacun avec son job Dagster
- **Flush buffer = 1** : envoi quasi temps réel des résultats, pas d'accumulation

## Dossiers de données

| Dossier                    | Contenu                              |
|----------------------------|--------------------------------------|
| `Datas/pdfs/`              | Documents PDF sources                |
| `Datas/htms/`              | Documents HTML sources               |
| `Datas/database/chromadb/` | Persistence ChromaDB                 |
| `Datas/database/nebula/`   | Persistence NebulaGraph              |
| `Datas/database/minio/`    | Persistence MinIO                    |
| `Datas/database/postgres/` | Persistence PostgreSQL (Dagster)     |
