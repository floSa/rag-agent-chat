# Microservice d'Extraction de Donnees (Docling)

## Presentation

Le service `docling-service` est le moteur d'ingestion du projet. Developpe avec FastAPI,
il traite les documents (PDF, HTML) de maniere structuree via **Docling** (bibliotheque IBM
d'analyse de layout assistee par IA).

- **URL interne** : `http://docling-service:8000`
- **Endpoint** : `POST /extract` avec body JSON `{"filepath": "/opt/dagster/app/Datas/pdfs/mon_livre.pdf"}`
- **GPU** : CUDA 12.1, `shm_size: 2gb`, limite memoire 10 Go

## Algorithme d'extraction (Docling v9.1)

L'extraction structuree suit un pipeline en 3 passes :

### Passe 1 -- Extraction brute et hierarchie

Docling itere sur chaque element du document via `doc.iterate_items()`. Chaque element
recoit un ID cryptographique `sha256(filename|page_no|order|text[:50])[:10]` et est classe
par label (`section_header`, `text`, `picture`, `table`, `code`, etc.).

Les `section_header` sont empiles pour maintenir la hierarchie parent-enfant via
`reference_id`. La numerotation est parsee (decimale, alphabetique, romaine) pour
determiner le niveau de profondeur.

### Passe 1.5 -- Liaison Caption -> Ressource

Les captions sont rattachees a la ressource visuelle la plus proche sur la meme page,
par distance geometrique (Manhattan) sur les bounding boxes. Seuil : 300 unites.

### Passe 2 -- Positions et mapping final

Chaque element recoit :
- `page_position` : ordre sequentiel dans la page
- `ref_position` : ordre sous son parent (`reference_id`)
- `type` : `text` ou `resource`

Les ressources (`picture`, `table`) recuperent le texte de leur caption dans `text`,
et le contenu brut (code, formule) va dans `content`.

## Crop et upload des medias

Pour les elements visuels (`picture`, `table`), le service :

1. Ouvre le PDF avec **PyMuPDF** (fitz) sur le volume partage
2. Crop aux coordonnees exactes de la bounding box avec matrice de zoom (haute resolution)
3. Pousse le pixmap en bytes sur le bucket MinIO `documents`
4. Stocke l'URL dans `minio_url` du noeud JSON

**Attention** : Docling utilise un axe Y Bottom-Left, PyMuPDF un axe Y Top-Left.
La conversion des coordonnees est necessaire pour un crop correct.

## Format de sortie JSON

```json
{
  "metadata": {
    "filename": "2408.09869",
    "type_file": "pdf",
    "total_pages": 9
  },
  "elements": [
    {
      "id": "a950b65a3b",
      "label": "picture",
      "page_no": 1,
      "bbox": {"l": 256.38, "t": 719.3, "r": 355.54, "b": 622.85},
      "reference_id": "DOC",
      "reference_ressources": null,
      "content": null,
      "page_position": 1,
      "ref_position": 1,
      "type": "resource",
      "text": "",
      "minio_url": "http://minio:9000/documents/..."
    },
    {
      "id": "023351d5f4",
      "label": "section_header",
      "page_no": 1,
      "bbox": {"l": 108.0, "t": 267.8, "r": 190.81, "b": 257.05},
      "reference_id": "DOC",
      "page_position": 8,
      "ref_position": 8,
      "type": "text",
      "text": "1 Introduction"
    },
    {
      "id": "93c9713358",
      "label": "text",
      "page_no": 1,
      "bbox": {"l": 108.0, "t": 239.37, "r": 504.0, "b": 143.55},
      "reference_id": "023351d5f4",
      "page_position": 9,
      "ref_position": 1,
      "type": "text",
      "text": "Converting PDF..."
    }
  ]
}
```

## Configuration Docling

```python
pipeline_options = PdfPipelineOptions(
    do_ocr=False,
    do_table_structure=True,
    table_structure_options=TableStructureOptions(mode=TableFormerMode.FAST),
    do_code_enrichment=False,
    do_formula_enrichment=False,
)
```

## Problemes connus et solutions

- **OOM (Out Of Memory)** : 14 Go de RAM sur une machine WSL 16 Go crashait les autres
  services. Solution : limite a 10 Go, `do_table_structure=False` si necessaire,
  `BATCH_PAGE_SIZE=5`, `FLUSH_BUFFER_SIZE=1`.

- **Crop muet** : Les images n'etaient pas envoyees a MinIO sans erreur.
  Cause : coordonnees Y inversees (Bottom-Left Docling vs Top-Left PyMuPDF).
  Solution : conversion d'axe dans `crop_and_upload_image`.

## Commandes utiles

```bash
# Logs en temps reel
docker compose logs docling-service --tail 100 -f

# Extraction manuelle (sans Dagster)
curl -X POST "http://localhost:8000/extract" \
  -H "Content-Type: application/json" \
  -d '{"filepath": "/opt/dagster/app/Datas/pdfs/mon_livre.pdf"}'
```
