# Politique de securite

## Gestion des secrets

- Tous les secrets sont dans `.env` (ignore par git)
- `.env.example` documente les cles attendues sans valeurs sensibles
- Les mots de passe sont generes avec `openssl rand -base64 24`
- `detect-secrets` avec baseline (`.secrets.baseline`) integre au pre-commit

## Audit des dependances

```bash
# Depuis le venv
pip-audit -r requirements.txt
```

Les versions sont pinnees dans `requirements.txt` avec `==`.
Mettre a jour regulierement et re-auditer.

## Isolation reseau

- Les services internes (ChromaDB, MinIO, NebulaGraph, PostgreSQL, Docling) ne sont
  pas exposes sur l'hote (`expose:` au lieu de `ports:`)
- Seuls Dagster (3000) et Nebula Studio (7001) sont accessibles depuis l'hote
- `docker-compose.override.yml` (non commite) permet d'exposer les ports en debug

## Containers

- Images de base pinnees (`python:3.10.17-slim`)
- Utilisateur non-root dans les Dockerfiles custom (`dagster`, `docling`)
- `--no-install-recommends` pour minimiser la surface d'attaque

## Rotation des secrets

1. Generer de nouveaux secrets : `openssl rand -base64 24`
2. Mettre a jour `.env`
3. Redemarrer les services : `docker compose down && docker compose up -d`

## Preparation future (couche LLM/agent)

Quand la couche RAG agent sera ajoutee :

- **Presidio** ou **NeMo Guardrails** pour la detection/anonymisation de PII
  dans les prompts et les reponses
- **Rate limiting** sur les endpoints exposes
- **Audit logging** des requetes LLM (prompts, tokens, latence)
- Ne jamais stocker de cles API LLM en dur — utiliser les settings pydantic
