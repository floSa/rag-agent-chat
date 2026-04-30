# Orchestrateur ETL (Dagster)

## 📌 Présentation du Service
Dagster est le système nerveux central du projet RAG Assistant. C'est l'orchestrateur de données chargé de détecter les ajouts de documents dans les répertoires et d'automatiser (trigger) l'exécution des requêtes vers le service d'extraction, sans intervention humaine.

Il se compose de plusieurs sous-services distincts :
- **postgres-dagster** : Base de données PostgreSQL pour stocker les métadonnées de l'orchestrateur (historique d'exécution, états des senseurs).
- **dagster-webserver** : Interface utilisateur pour gérer et visualiser les pipelines (Jobs, Assets, Sensors).
- **dagster-daemon** : Composant de fond chargé d'activer régulièrement les Sensors définis dans le code Python.

## 🔗 Accès au service
- **Interface UI Webserver** : [http://localhost:3000](http://localhost:3000)
- **Base de données interne** : `postgres-dagster:5432` (credentials : voir `.env`)

## 🗂️ Structure et définition des données
Côté développement, les éléments vitaux composant le graphe de données Dagster sont :
- **Les Sensors (`sensors.py`)** : Ce sont les écouteurs. Le `pdf_sensor` parcours continuellement le dossier source `/opt/dagster/app/Datas` pour y trouver des PDFs.
- **La persistance des tâches (Le Curseur)** : Pour éviter qu'un livre ne soit ingéré à chaque redémarrage, Dagster utilise un objet appelé "curseur". À chaque découverte d'un document, la date et l'heure exacte de sa modification (`mtime`) est sauvegardée dans le curseur PostgreSQL. Si le fichier n'a pas été modifié depuis son traitement, Dagster l'ignore de manière silencieuse et robuste.
- **Les Assets (`core_assets.py`)** : Ils représentent des lots "matériels" à créer, qui vont appeler la fonction API FastAPI (`/extract`). 
- **Les Partitions** : Définie de façon dynamique, chaque type ou nom de document est une "Partition" pour simplifier la réexécution d'un échec sur un livre précis (au lieu de réexécuter tout le pipeline global).

## 💻 Commandes Utiles
Lors des phases d'architecture ou lorsque vous surveillez RAG Assistant :
- Dans l'interface Web (`http://localhost:3000`), allez dans l'onglet **Overview > Sensors** pour activer/désactiver l'ingestion automatique logicielle.
- **Vérifier l'état de l'Orchestrateur** (en cas de plantage d'un Job) :
  ```bash
  docker compose logs dagster-daemon --tail 50
  docker compose logs dagster-webserver --tail 50
  ```

## 🛠️ Problèmes rencontrés et Solutions
- **Rechargement Intempestif des Tâches lors du Reboot** : 
  - *Problème* : Au redémarrage (ex: fermeture WSL), tous les services Docker n'étaient pas gardés persistants sauf Docling. La base PostgreSQL de Dagster étant perdue lors d'un restart, l'orchestrateur relançait le processus de traitement de tous les livres à zéro car il avait oublié les curseurs.
  - *Solution* : Ajout de la contrainte `restart: unless-stopped` sur tous les conteneurs dans le `docker-compose.yml`, pour qu'ils soient tous persistants tout comme la base d'états Dagster, verrouillant ainsi et pour de bon les données extraites au premier passage.
