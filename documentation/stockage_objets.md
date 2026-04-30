# Stockage Objets Structurés (MinIO)

## 📌 Présentation du Service
MinIO agit comme le coffre-fort de tous les médias lourds récupérés durant l'ingestion (notamment Images et Tableaux visuels complexes). Ce composant est extrêmement important dans le cadre de votre IA car les futurs modèles RAG Multimodaux pourront générer des interfaces de discussion incluant directement les images source du PDF.

Il reproduit le comportement d'un Amazon S3 et héberge de manière sécurisée et distribuée l'ensemble des éléments non-textuels, de manière à alléger les autres bases de données.

## 🔗 Accès au service
- **Interface Console UI** : [http://localhost:9101](http://localhost:9101)
- **Serveur API Interne** : `minio:9000` (utilisé par Docling pour envoyer les images).
- **Credentials** : voir fichier `.env` (variables `MINIO_ROOT_USER` / `MINIO_ROOT_PASSWORD`)

## 🗂️ Structure et définition des données
Les données envoyées dans MinIO sont uniquement visuelles (`image/png` par exemple).
Leur structure respecte l'arborescence : `documents/images/{NomDuLivre}/{Hash_ID}_{Type_element}.png`
- **Exemple** : `documents/images/statisticsfordatascience/3af24_picture.png`
- **Bucket principal** : Le système vérifie l'existence et crée en cas d'absence dès son démarrage un bucket réservé nommé **`documents`**.
La totalité de ces chemin d'accès public/interne sont stockés dans le graphe NebulaGraph sous la propriété `minio_url` de chaque élément de type Table ou Picture extraits.

## 💻 Commandes Utiles
Pour vos flux de RAG Agentiques à l'avenir :
- En Python (boto3 ou minio client), vous pouvez récupérer l'image via son URL directement depuis le point d'entrée `9000`.
- **Commandes pour diagnostiquer MinIO** :
  ```bash
  docker compose logs minio --tail 50
  ```

## 🛠️ Problèmes rencontrés et Solutions
- **Défaillance Silencieuse Initiale (Images fantômes)** : 
  - *Problème* : Il pouvait arriver que MinIO soit inaccessible la première micro-seconde de démarrage ou que le DNS Docker `minio` soit indisponible. Le service docling crashait sans tentative persistante. Les images obtenaient des hauteurs négatives depuis Docling.
  - *Solution réseau* : Côté MinIO, une robuste boucle `while` (de 15 tentatives max espacées de 5 secs) a été incluse dans la routine `init_minio()` du script d'IA pour pallier ce soucis de résolution de nom silencieuse et garantir un démarrage des uploads quoi qu'il arrive.
