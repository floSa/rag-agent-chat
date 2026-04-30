# NebulaGraph (Graphe de connaissances)

## Role

Base de donnees graphe distribuee stockant la hierarchie structurelle des documents :
noeuds (Document, SectionHeader, Paragraph, Table, Picture...) et relations
(PARENT_OF, LINKED_TO).

## Containers

| Container       | Image                         | Port interne | Role                     |
|-----------------|-------------------------------|--------------|--------------------------|
| metad           | nebula-metad:v3.6.0           | 9559         | Service de metadonnees   |
| storaged        | nebula-storaged:v3.6.0        | 9779         | Stockage distribue       |
| graphd          | nebula-graphd:v3.6.0          | 9669         | Moteur de requete nGQL   |
| nebula-studio   | nebula-graph-studio:v3.8.0    | 7001 (expose)| UI de visualisation      |

## Schema nGQL

```ngql
CREATE SPACE rag_space(partition_num=10, replica_factor=1, vid_type=FIXED_STRING(64));

-- Tags (types de noeuds)
CREATE TAG Document(filename string, type_file string);
CREATE TAG SectionHeader(label string, page_no int, text string, minio_url string);
CREATE TAG Paragraph(label string, page_no int, text string, minio_url string);
CREATE TAG Table(label string, page_no int, text string, minio_url string);
CREATE TAG Picture(label string, page_no int, text string, minio_url string);
-- ... (ListItem, Caption, Code, Formula, Footnote, PageHeader, PageFooter)

-- Edges (relations)
CREATE EDGE PARENT_OF(sequence int);
CREATE EDGE LINKED_TO(relation string);

-- Index
CREATE TAG INDEX doc_index ON Document(filename(20));
```

## Variables d'environnement

| Variable     | Description         | Defaut  |
|--------------|---------------------|---------|
| NEBULA_HOST  | Hostname graphd     | graphd  |
| NEBULA_PORT  | Port graphd         | 9669    |
| NEBULA_USER  | Utilisateur         | root    |
| NEBULA_PASSWORD | Mot de passe     | nebula  |

## Dependances

`metad` -> `storaged` -> `graphd` (demarrage sequentiel)

## Persistence

- `./Datas/database/nebula/meta:/data/meta`
- `./Datas/database/nebula/storage:/data/storage`

## Healthcheck

```bash
curl -s http://graphd:19669/status
```

## UI

Nebula Studio accessible sur `http://localhost:7001`. Se connecter avec
`graphd:9669`, user `root`, password `nebula`.
