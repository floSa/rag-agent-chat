import json
import logging
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
from jinja2 import Environment, FileSystemLoader, select_autoescape

from src.agent.settings import settings
from src.api.schemas import Message, SectionContext

logger = logging.getLogger(__name__)


def _load_system_prompt() -> str:
    path = Path(settings.prompts_dir) / "system.txt"
    if path.exists():
        return path.read_text(encoding="utf-8").strip()
    logger.warning(
        "system.txt introuvable dans %s, utilisation du prompt par défaut.",
        settings.prompts_dir,
    )
    return "Tu es un assistant utile. Réponds en te basant uniquement sur les sources fournies."


def _get_jinja_env() -> Environment:
    return Environment(
        loader=FileSystemLoader(settings.prompts_dir),
        autoescape=select_autoescape(enabled_extensions=()),
    )


def _build_context_message(
    question: str,
    contexts: list[SectionContext],
) -> str:
    """Rend le template answer_with_context.j2 avec les contextes enrichis."""
    env = _get_jinja_env()
    template = env.get_template("answer_with_context.j2")
    return template.render(question=question, contexts=contexts)


def _build_messages(
    question: str,
    contexts: list[SectionContext],
    chat_history: list[Message],
) -> list[dict]:
    msgs: list[dict] = [{"role": "system", "content": _load_system_prompt()}]

    for msg in chat_history:
        msgs.append({"role": msg.role, "content": msg.content})

    msgs.append({"role": "user", "content": _build_context_message(question, contexts)})
    return msgs


async def generate_stream(
    question: str,
    contexts: list[SectionContext],
    chat_history: list[Message] | None = None,
) -> AsyncIterator[str]:
    """Génère la réponse en streaming via l'API native Ollama.

    On utilise /api/chat (et non l'endpoint OpenAI-compatible) pour piloter
    `think` : Gemma 4 est un modèle à raisonnement et, sans ce flag, il peut
    consommer tout le budget num_predict en réflexion avant le premier token
    de réponse — prohibitif en CPU.
    """
    messages = _build_messages(question, contexts, chat_history or [])

    logger.debug(
        "LLM generate : model=%s, messages=%d, contexte=%d sections, think=%s",
        settings.ollama_model,
        len(messages),
        len(contexts),
        settings.llm_thinking,
    )

    payload = {
        "model": settings.ollama_model,
        "messages": messages,
        "stream": True,
        "think": settings.llm_thinking,
        "options": {
            "temperature": settings.llm_temperature,
            "num_predict": settings.llm_max_tokens,
        },
    }

    timeout = httpx.Timeout(30.0, read=None)  # le premier token peut tarder (prefill CPU)
    async with (
        httpx.AsyncClient(timeout=timeout) as client,
        client.stream("POST", f"{settings.ollama_host}/api/chat", json=payload) as resp,
    ):
        resp.raise_for_status()
        async for line in resp.aiter_lines():
            if not line.strip():
                continue
            data = json.loads(line)
            if data.get("error"):
                raise RuntimeError(f"Ollama : {data['error']}")
            delta = data.get("message", {}).get("content", "")
            if delta:
                yield delta
            if data.get("done"):
                break


async def generate(
    question: str,
    contexts: list[SectionContext],
    chat_history: list[Message] | None = None,
) -> str:
    """Génère la réponse complète (non-streaming)."""
    parts: list[str] = []
    async for token in generate_stream(question, contexts, chat_history):
        parts.append(token)
    return "".join(parts)
