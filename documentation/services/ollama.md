# Ollama — service central

Ce projet **n'embarque aucune instance Ollama**. Les modèles sont servis par le
projet [`llm-service`](https://github.com/floSa/llm-service), qui expose le
conteneur `ollama-central` sur le réseau Docker `llm-net`.

## Pourquoi

Une instance Ollama vivait dans le `docker-compose.yml` de ce projet, avec son
propre volume de modèles. Elle faisait doublon avec le service central : un
`docker compose up -d` la recréait et retéléchargeait plusieurs gigaoctets d'un
modèle déjà servi à côté. Un seul serveur d'inférence pour tous les projets
évite d'en héberger un par dépôt, et de multiplier les copies des poids.

## Configuration

| Variable | Valeur | Rôle |
|---|---|---|
| `OLLAMA_HOST` | `http://ollama-central:11434` | Endpoint du service central |
| `OLLAMA_MODEL` | `gemma4:e4b` | Modèle de génération |
| `LLM_NUM_CTX` | `32768` | Fenêtre de contexte demandée par requête |
| `LLM_MAX_TOKENS` | `4096` | Plafond de génération (`num_predict`) |
| `LLM_TEMPERATURE` | `0.1` | Température |
| `LLM_THINKING` | `false` | Raisonnement de Gemma 4, coûteux en CPU |

`LLM_NUM_CTX` est passé explicitement dans chaque requête. Sans lui, la fenêtre
dépendrait de l'`OLLAMA_CONTEXT_LENGTH` du serveur, et le même prompt
produirait deux comportements selon le serveur interrogé.

Le budget de sources vaut `LLM_NUM_CTX - LLM_MAX_TOKENS` : au-delà, les sources
excédentaires sont écartées avec un log explicite, plutôt que tronquées en
silence par Ollama — qui coupe par le **début** du prompt, donc par les sources
les mieux classées.

## Prérequis

```bash
cd ~/mes_projets/llm-service && make up
```

Vérifier que le modèle attendu est servi :

```bash
make models
```

## Dépannage

| Symptôme | Cause probable |
|---|---|
| `/health` renvoie `ollama: false` | `llm-service` n'est pas démarré, ou le réseau `llm-net` n'existe pas |
| `network llm-net not found` | Lancer `make up` dans `llm-service` d'abord |
| Réponse vide ou tronquée | `LLM_NUM_CTX` supérieur à l'`OLLAMA_CONTEXT_LENGTH` du serveur central |
