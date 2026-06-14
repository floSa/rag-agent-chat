# Ollama (LLM local)

## Rôle

Moteur d'inférence LLM local. Télécharge, met en cache et sert des modèles de langage via une API compatible OpenAI. Dans ce projet, il fournit la capacité de génération de texte citée sans dépendance à un service cloud.

## Container

| Container   | Image              | Port interne | Port exposé | Rôle            |
|-------------|--------------------|--------------|-------------|-----------------|
| rag-ollama  | ollama/ollama:latest | 11434      | non exposé  | Inférence LLM   |

Le port 11434 est accessible uniquement depuis le réseau Docker interne (`internal`). Il n'est pas exposé sur l'hôte.

## Entrypoint personnalisé

Le script [`scripts/ollama_entrypoint.sh`](../../scripts/ollama_entrypoint.sh) remplace l'entrypoint par défaut de l'image pour :

1. Démarrer le serveur Ollama en arrière-plan.
2. Attendre que l'API soit disponible sur le port 11434 (via `/dev/tcp`).
3. Vérifier si le modèle configuré est déjà présent dans le volume (`ollama list`).
4. Le télécharger si absent (`ollama pull`).
5. Garder le conteneur actif (`wait`).

```bash
# Attente de disponibilité (curl absent de l'image officielle)
until bash -c "echo > /dev/tcp/localhost/11434" 2>/dev/null; do
    sleep 2
done
```

## Modèle par défaut

`gemma3:4b` — modèle Gemma 3 de Google, 4 milliards de paramètres, quantifié 4 bits (~3,3 Go).

Le modèle est configurable via la variable `OLLAMA_MODEL`. Il est stocké dans le volume Docker `rag_models_cache` (`/root/.ollama`) pour survivre aux redémarrages.

## Interface API

Ollama expose une API compatible OpenAI sur `/v1/`. Le client Python utilise `openai.AsyncOpenAI` avec `base_url` pointant vers `http://ollama:11434/v1/` :

```python
client = AsyncOpenAI(
    base_url=f"{settings.ollama_host}/v1/",
    api_key="ollama",  # valeur fictive, Ollama n'authentifie pas
)
```

Les appels utilisent `chat.completions.create` avec support du streaming (`stream=True`).

## Variables d'environnement

| Variable         | Description                         | Défaut                   |
|------------------|-------------------------------------|--------------------------|
| `OLLAMA_HOST`    | URL complète du service Ollama      | `http://ollama:11434`    |
| `OLLAMA_MODEL`   | Modèle à utiliser                   | `gemma3:4b`              |
| `LLM_TEMPERATURE`| Température d'échantillonnage       | `0.1`                    |
| `LLM_MAX_TOKENS` | Nombre maximum de tokens générés    | `4096`                   |

## Healthcheck

```yaml
test: ["CMD-SHELL", "ollama list | grep -q '.'"]
interval: 30s
timeout: 10s
retries: 10
start_period: 600s   # 10 min pour le premier téléchargement
```

Le `start_period` long est nécessaire car le premier démarrage télécharge le modèle (~3,3 Go). Les services dépendants (`agent-api`) ne démarrent qu'après ce healthcheck.

## Persistence

Le volume `rag_models_cache` (nommé `rag_models_cache`, driver local) conserve les modèles entre les redémarrages :

```yaml
volumes:
  models_cache:
    name: rag_models_cache
```

`docker compose down` ne supprime pas ce volume. `docker compose down -v` le supprimerait (re-téléchargement nécessaire).

## Réseaux

Ollama est connecté à deux réseaux :

| Réseau       | Rôle                                                    |
|--------------|---------------------------------------------------------|
| `rag_network` | Réseau externe partagé avec `rag-ingestion-pipeline`  |
| `internal`   | Réseau interne au projet (accès depuis `agent-api`)    |

## Modèles alternatifs

Tout modèle disponible sur [ollama.com/library](https://ollama.com/library) peut être utilisé. Exemples :

| Modèle          | Taille  | Usage                          |
|-----------------|---------|--------------------------------|
| `gemma3:4b`     | ~3,3 Go | Défaut — bon équilibre         |
| `llama3.2:3b`   | ~2,0 Go | Plus léger                     |
| `mistral:7b`    | ~4,1 Go | Meilleure capacité de raisonnement |
| `gemma3:12b`    | ~8,1 Go | Meilleure qualité (GPU requis) |

Changer de modèle nécessite uniquement de modifier `OLLAMA_MODEL` dans `.env` et de redémarrer le service.
