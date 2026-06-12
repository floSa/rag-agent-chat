#!/bin/bash
set -e

MODEL="${OLLAMA_MODEL:-gemma4:e4b}"

echo "[ollama-init] Démarrage du serveur Ollama..."
ollama serve &
OLLAMA_PID=$!

echo "[ollama-init] Attente de la disponibilité de l'API..."
# Le CLI ollama interroge l'API locale : pas besoin de curl (absent de l'image)
until ollama list > /dev/null 2>&1; do
    sleep 2
done
echo "[ollama-init] API disponible."

if ollama list | grep -q "^${MODEL}"; then
    echo "[ollama-init] Modèle ${MODEL} déjà présent dans le volume."
else
    echo "[ollama-init] Téléchargement du modèle ${MODEL}..."
    ollama pull "${MODEL}"
    echo "[ollama-init] Modèle ${MODEL} téléchargé."
fi

echo "[ollama-init] Prêt. Modèles disponibles :"
ollama list

wait $OLLAMA_PID
