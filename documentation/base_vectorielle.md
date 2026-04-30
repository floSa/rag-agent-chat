# Stockage et Recherche Vectorielle (ChromaDB)

## 📌 Présentation du Service
La base vectorielle **ChromaDB** est le composant indispensable à l'algorithme "Retrieval" de tout système RAG. Pendant que NebulaGraph gère la logique de la structure et les relations d'ordres, ChromaDB va chercher précisément le fond, l'idée et la signification textuelle à la demande d'un Agent IA.

Grâce aux *embeddings* générés par le composant IA (`all-MiniLM-L6-v2`), ChromaDB place chaque paragraphe extrait dans un espace mathématique multi-dimensionnel permettant de trouver instantanément un texte ayant un sens et un contexte similaire à la requête utilisateur.

## 🔗 Accès au service
- **Type** : API Serveur Vectoriel HTTP
- **URL / Point d'Entrée API** : `http://localhost:8080/api/v1` (Accès Docker interne : `chromadb:8000`)
- Le client se connecte via la librairie Python officielle : `chromadb.HttpClient`.

## 🗂️ Structure et définition des données
Gérée comme une "Collection" de documents et de vecteurs, son arborescence se complexifie intelligemment par la conservation de métadonnées.
- **Identifiant Unique** : Exactement le même identifiant cryptographique (Hash ID) unique que celui inséré dans NebulaGraph. C’est la clé de pivot ou la "clé étrangère" parfaite entre la base sémantique graphe et la base vectorielle. 
- **Embeddings** : Représentation mathématique d’un `Paragraph` de texte.
- **Documents** : Le contenu en texte pur de l’élément extrait depuis le PDF/HTML.
- **Métadonnées intégrées** :
  - `label` : Tag qui permet de filtrer très rapidement et isoler les requêtes (ex: chercher uniquement dans du tag `Table`).
  - `page_no` : Page source pour un système de référencement (citer la source au client RAG).
  - `filename` : Fichier de référence pour ne chercher que dans des ressources spécifiques.

## 💻 Commandes Utiles
Lors de vos futurs développements du système RAG Agentique, vous nécessiterez régulièrement ces concepts :
- **Intérroger la collection en Python :** 
  ```python
  import chromadb
  client = chromadb.HttpClient(host='localhost', port=8080)
  collection = client.get_or_create_collection(name="documents")
  
  # Requête sur un contexte RAG métier (ici: cibler que les paragraphes et les formules avec un texte lié aux analyses statistiques)
  results = collection.query(
      query_texts=["Comment calculer la médiane ?"],
      n_results=3,
      where={"label": {"$in": ["paragraph", "formula"]}} # Utilisation filtrée indispensable !
  )
  ```
- **Diagnostic système global de maintien docker** :
  ```bash
  docker compose logs chromadb --tail 50
  ```

## 🛠️ Problèmes rencontrés et Solutions
- **Intégrité de Base Perdue au Reboot** : 
  - *Problème* : L'inexistence de `restart: unless-stopped` en politique de redémarrage sur le conteneur ChromaDB faisait disparaître ou arrêter inopinément le service dès réveil d'une nuit de fermeture du terminal (WSL). Le service demandeur `docling-service` ne parvenait alors plus à trouver son système cible et jetait les paquets vectoriels dans le vide.
  - *Solution* : Ajouté ce jour des conditions optimales `restart: unless-stopped` sur la déclaration docker, forçant chroma à se relancer instantanément et récupérer automatiquement ses collections depuis son montage `/Datas/database/chromadb`.
