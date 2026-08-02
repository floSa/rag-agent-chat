import json
import logging
import re
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
from jinja2 import Environment, FileSystemLoader, select_autoescape

from src.agent.settings import settings
from src.api.schemas import Message, SectionContext

logger = logging.getLogger(__name__)


def _load_system_prompt() -> str:
    path = _prompts_dir() / "system.txt"
    if path.exists():
        return path.read_text(encoding="utf-8").strip()
    logger.warning(
        "system.txt introuvable dans %s, utilisation du prompt par défaut.",
        settings.prompts_dir,
    )
    return "Tu es un assistant utile. Réponds en te basant uniquement sur les sources fournies."


# Dossier de prompts embarqué dans le dépôt. `settings.prompts_dir` vaut le
# chemin monté dans l'image Docker ; hors conteneur (tests, exécution locale) il
# n'existe pas, et sans repli tout rendu de gabarit échouait.
_PROMPTS_FALLBACK = Path(__file__).resolve().parent.parent.parent / "prompts"


def _prompts_dir() -> Path:
    configured = Path(settings.prompts_dir)
    return configured if configured.is_dir() else _PROMPTS_FALLBACK


def _get_jinja_env() -> Environment:
    return Environment(
        loader=FileSystemLoader(str(_prompts_dir())),
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


# Estimation grossière du ratio caractères/token. Le tokenizer réel dépend du
# modèle ; ~3.5 est prudent pour du français, plus dense en tokens que l'anglais.
_CHARS_PER_TOKEN = 3.5
# Marge pour le prompt système, le gabarit et l'historique.
_PROMPT_OVERHEAD_TOKENS = 512


def context_budget_chars() -> int:
    """Nombre de caractères de contexte que la fenêtre du modèle peut absorber.

    `num_ctx` est partagé entre le prompt et la génération : ce qui est réservé
    à `num_predict` n'est pas disponible pour les sources.
    """
    available = settings.llm_num_ctx - settings.llm_max_tokens - _PROMPT_OVERHEAD_TOKENS
    return max(0, int(available * _CHARS_PER_TOKEN))


def fit_contexts(
    contexts: list[SectionContext], budget_chars: int
) -> tuple[list[SectionContext], int]:
    """Écarte les sources qui ne tiennent pas dans la fenêtre de contexte.

    Sans cette borne, Ollama tronque le prompt lui-même — silencieusement, et
    par le DÉBUT, donc en jetant les premières sources. Le système pouvait
    répondre « je n'ai pas trouvé » sur une information qu'il avait reçue.

    Les sources sont conservées dans leur ordre (le meilleur classement
    d'abord) : c'est la queue de la liste qui saute.

    Returns:
        (sources retenues, nombre de sources écartées).
    """
    kept: list[SectionContext] = []
    used = 0
    for ctx in contexts:
        cost = len(ctx.markdown)
        if kept and used + cost > budget_chars:
            continue
        kept.append(ctx)
        used += cost
    return kept, len(contexts) - len(kept)


def _build_messages(
    question: str,
    contexts: list[SectionContext],
    chat_history: list[Message],
) -> list[dict]:
    msgs: list[dict] = [{"role": "system", "content": _load_system_prompt()}]

    for msg in chat_history:
        msgs.append({"role": msg.role, "content": msg.content})

    budget = context_budget_chars()
    kept, dropped = fit_contexts(contexts, budget)
    if dropped:
        logger.warning(
            "Contexte tronqué : %d source(s) sur %d écartée(s) — budget %d caractères "
            "(num_ctx=%d, num_predict=%d). Réduire RERANK_TOP_K ou augmenter LLM_NUM_CTX.",
            dropped,
            len(contexts),
            budget,
            settings.llm_num_ctx,
            settings.llm_max_tokens,
        )

    msgs.append({"role": "user", "content": _build_context_message(question, kept)})
    return msgs


# Une question de suivi est courte : au-delà, le modèle a paraphrasé ou répondu
# au lieu de réécrire, et sa sortie ne doit pas être utilisée comme requête.
_MAX_REWRITE_CHARS = 400


async def rewrite_question(question: str, chat_history: list[Message] | None) -> str:
    """Reformule une question de suivi en question autonome.

    « Et pour les femmes ? » est embarqué tel quel par le modèle d'embedding :
    le vecteur ne porte aucun des termes qui comptent, et la recherche ne
    retrouve rien. La réécriture restitue le sujet avant l'encodage.

    Sans historique, la question est déjà autonome et rendue telle quelle —
    aucun appel au LLM n'est fait. En cas d'échec ou de sortie douteuse, on
    retombe sur la question d'origine : mieux vaut une recherche non réécrite
    qu'une recherche sur du bruit.
    """
    if not chat_history or not settings.query_rewrite:
        return question

    try:
        template = _get_jinja_env().get_template("rewrite_query.j2")
        prompt = template.render(question=question, chat_history=chat_history)
    except Exception:
        logger.warning("Gabarit de réécriture introuvable, question d'origine conservée.")
        return question

    payload = {
        "model": settings.ollama_model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "think": False,
        "options": {"temperature": 0.0, "num_predict": 120, "num_ctx": settings.llm_num_ctx},
    }

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(60.0)) as client:
            resp = await client.post(f"{settings.ollama_host}/api/chat", json=payload)
            resp.raise_for_status()
            rewritten = resp.json().get("message", {}).get("content", "").strip()
    except Exception:
        logger.warning("Réécriture de requête indisponible, question d'origine conservée.")
        return question

    # Le modèle peut préfixer (« Question autonome : »), commenter, ou répondre.
    rewritten = rewritten.splitlines()[0].strip() if rewritten else ""
    rewritten = re.sub(r"^[\s\-*>]*(question\s+autonome\s*:)?\s*", "", rewritten, flags=re.I)
    rewritten = rewritten.strip('"\'')

    if not rewritten or len(rewritten) > _MAX_REWRITE_CHARS:
        logger.info("Réécriture écartée (vide ou trop longue), question d'origine conservée.")
        return question

    if rewritten != question:
        logger.info("Question réécrite : %r → %r", question[:60], rewritten[:60])
    return rewritten


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
            # Explicite : sans ce champ la fenêtre dépend de l'OLLAMA_CONTEXT_LENGTH
            # du serveur, qui diffère entre l'Ollama embarqué (8192) et le service
            # central (32768). Le même prompt donnait deux comportements.
            "num_ctx": settings.llm_num_ctx,
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
