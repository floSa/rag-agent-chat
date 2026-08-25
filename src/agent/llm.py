import json
import logging
import math
import re
from collections.abc import AsyncIterator, Callable, Sequence
from pathlib import Path
from typing import Any, NamedTuple

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
# C'est une estimation, mais elle s'applique à TOUTES les parties du prompt :
# l'appliquer aux seules sources était le défaut. `log_prompt_measure` la
# confronte au décompte réel d'Ollama à chaque génération, de quoi la calibrer.
_CHARS_PER_TOKEN = 3.5

# Balises de tour que le gabarit de chat du modèle ajoute autour de CHAQUE
# message (« <start_of_turn>user … <end_of_turn> » chez Gemma). Le gabarit exact
# dépend du modèle, d'où une provision ; l'ignorer sous-estime le prompt autant
# de fois qu'il y a de messages.
_MESSAGE_FRAMING_CHARS = 24

# Encadrement d'une source dans answer_with_context.j2 : séparateurs, numéro,
# identifiant, fil des titres. Le budget se compte sur `ctx.markdown` seul ;
# sans cette provision, dix sources glissent ~2 000 caractères dans le prompt
# que rien ne compte.
_SOURCE_FRAMING_CHARS = 200

# Part de la fenêtre utile que l'historique peut occuper au maximum.
# L'historique est du contexte de second rang : `node_rewrite` a déjà rendu la
# question de suivi autonome avant l'encodage, donc les sources répondent sans
# lui. Sans ce plafond, six messages à la borne de `Message.content` dépassent à
# eux seuls num_ctx — et c'est alors Ollama qui tranche, par le DÉBUT du prompt,
# donc en jetant le message système : les règles de citation et d'abstention
# disparaissent exactement quand la conversation devient assez longue pour en
# avoir besoin.
_HISTORY_WINDOW_SHARE = 0.25

# Marque laissée dans une source coupée. Le modèle doit pouvoir distinguer une
# section qui s'achève d'une section amputée : sans marque, il conclut sur un
# texte tronqué comme s'il était complet.
_TRUNCATION_MARKER = "\n\n[…] Section tronquée : elle dépasse à elle seule la fenêtre."

# Marqueurs que `_render_element` intercale dans le markdown, un par élément.
# Couper à un index de caractère brut les ampute : `[src:00000000` n'est plus
# résolu par le post-processing — ou, pire, correspond à un AUTRE élément. Le
# prompt système ordonne de reprendre ces identifiants tels quels, et les
# citations sont l'objet même de ce dépôt.
_MARKER_RE = re.compile(r"\[(?:src|img):[^\]\s]*\]")


def prompt_window_chars() -> int:
    """Caractères que la fenêtre laisse au prompt, génération déduite.

    `num_ctx` est partagé entre le prompt et la génération : ce qui est réservé
    à `num_predict` n'est pas disponible pour le prompt.
    """
    return max(0, int((settings.llm_num_ctx - settings.llm_max_tokens) * _CHARS_PER_TOKEN))


def history_budget_chars() -> int:
    """Caractères que l'historique de conversation peut occuper au maximum."""
    return int(prompt_window_chars() * _HISTORY_WINDOW_SHARE)


def fit_history(chat_history: Sequence[Message]) -> tuple[list[Message], int]:
    """Ne garde de l'historique que les derniers messages qui tiennent au budget.

    Sens inverse des sources : là on garde la tête du classement, ici la fin de
    la conversation — c'est le dernier échange qui situe la question. La coupe
    s'arrête au premier message qui ne tient plus, au lieu de continuer à
    remplir : sauter un message du milieu rendrait une réponse sans sa question.

    Un message trop gros à lui seul est écarté, pas tronqué : un demi-tour de
    conversation n'apporte rien, alors qu'une demi-section reste lisible.

    Returns:
        (messages retenus, dans l'ordre ; nombre de messages écartés).
    """
    budget = history_budget_chars()
    kept: list[Message] = []
    used = 0
    for msg in reversed(chat_history):
        cost = len(msg.content) + _MESSAGE_FRAMING_CHARS
        if used + cost > budget:
            break
        kept.append(msg)
        used += cost
    kept.reverse()
    return kept, len(chat_history) - len(kept)


def tools_overhead_chars() -> int:
    """Caractères de la déclaration d'outil, quand elle est envoyée.

    `tools` n'est pas un canal séparé pour le modèle : Ollama le rend DANS le
    prompt via le gabarit de chat, donc il consomme la fenêtre comme le reste.
    417 caractères, soit ~119 tokens, que rien ne comptait — le même trou que le
    forfait qu'on vient de retirer, à plus petite échelle.
    """
    return len(json.dumps(SEARCH_TOOL, ensure_ascii=False)) if settings.native_tool_calling else 0


def prompt_overhead_chars(
    question: str, chat_history: Sequence[Message], source_count: int
) -> int:
    """Caractères du prompt qui ne sont PAS du texte de source.

    Prompt système, gabarit rendu sans ses sources, historique, encadrement de
    chaque source, balises de tour. Un forfait de 512 tokens en tenait lieu et
    ne comptait jamais l'historique : six messages sont acceptés, chaque réponse
    assistante peut atteindre `LLM_MAX_TOKENS`, et le prompt dépassait num_ctx
    dès le troisième tour. Mesuré avant correctif : 31 380 caractères pour une
    fenêtre utile de 14 336.
    """
    overhead = len(_load_system_prompt())
    # Le gabarit rendu sans sources : en-tête, question, consigne de citation.
    # Mesuré plutôt que forfaitisé — c'est le seul moyen qu'une retouche de
    # answer_with_context.j2 se répercute sur le budget.
    overhead += len(_build_context_message(question, []))
    overhead += sum(len(msg.content) for msg in chat_history)
    # Un tour par message d'historique, plus le système et les sources.
    overhead += (len(chat_history) + 2) * _MESSAGE_FRAMING_CHARS
    overhead += source_count * _SOURCE_FRAMING_CHARS
    overhead += tools_overhead_chars()
    return overhead


def context_budget_chars(
    question: str, chat_history: Sequence[Message], source_count: int
) -> int:
    """Caractères de source que la fenêtre du modèle peut encore absorber.

    Calculé sur ce qui est RÉELLEMENT dans le prompt : passer un historique
    long réduit le budget, jusqu'à l'annuler. L'historique attendu ici est déjà
    borné par `fit_history` — sinon le budget décrirait un prompt que
    `_build_messages` ne construit pas.
    """
    return max(
        0, prompt_window_chars() - prompt_overhead_chars(question, chat_history, source_count)
    )


def _cut_on_marker(markdown: str, limite: int) -> str:
    """Coupe `markdown` au plus tard à `limite`, sur une frontière d'élément.

    La coupe recule jusqu'à la fin du dernier marqueur COMPLET : le texte
    conservé porte alors toujours son identifiant de citation. Un fragment
    d'élément privé de son marqueur ne serait pas attribuable, alors que le
    prompt système exige de citer chaque affirmation — le modèle le rattacherait
    au marqueur précédent, donc au mauvais passage.
    """
    tete = markdown[:limite]
    complets = list(_MARKER_RE.finditer(tete))
    if complets:
        return tete[: complets[-1].end()]

    # Aucun marqueur complet dans la tête : on écarte au moins un crochet resté
    # ouvert à la coupe ([src:, [img:, [Tableau], [Figure]).
    ouvert = tete.rfind("[")
    return tete[:ouvert] if ouvert != -1 and "]" not in tete[ouvert:] else tete


def _truncate(ctx: SectionContext, budget_chars: int) -> SectionContext:
    """Coupe une source par la FIN pour la faire tenir dans le budget."""
    # La marque compte dans le budget : sinon la troncature déplace la borne au
    # lieu de la respecter.
    garde = _cut_on_marker(ctx.markdown, max(0, budget_chars - len(_TRUNCATION_MARKER)))
    logger.warning(
        "Source %s tronquée : %d caractères conservés sur %d — elle dépasse à elle "
        "seule le budget de %d. La coupe se fait ici, par la FIN et sur une frontière "
        "d'élément ; laissée entière, c'est Ollama qui coupait, par le DÉBUT du prompt.",
        ctx.element_id,
        len(garde),
        len(ctx.markdown),
        budget_chars,
    )
    return ctx.model_copy(update={"markdown": garde + _TRUNCATION_MARKER})


def fit_contexts(
    contexts: list[SectionContext], budget_chars: int
) -> tuple[list[SectionContext], int]:
    """Écarte les sources qui ne tiennent pas dans la fenêtre de contexte.

    Sans cette borne, Ollama tronque le prompt lui-même — silencieusement, et
    par le DÉBUT, donc en jetant le message système puis les premières sources.
    Le système pouvait répondre « je n'ai pas trouvé » sur une information
    qu'il avait reçue.

    L'ordre du classement est conservé, mais le remplissage se fait **au
    mieux** : une petite source qui suit une grosse écartée est retenue. Ce
    n'est pas « la queue de la liste qui saute » — le docstring l'affirmait,
    le code ne l'a jamais fait.

    La première source est retenue même si elle dépasse seule le budget, mais
    **tronquée** : la transmettre entière rendait la main à Ollama, c'est-à-dire
    exactement au mode de panne que cette fonction existe pour éviter. Une
    section sans `SectionHeader` — fenêtre de 13 éléments, textes intégraux
    relus dans l'index — y arrive.

    Returns:
        (sources retenues, nombre de sources écartées).
    """
    if budget_chars <= 0:
        # Plus rien ne tient : ni garder ni tronquer n'a de sens. Mieux vaut une
        # abstention qu'un prompt dont Ollama ampute le message système.
        return [], len(contexts)

    kept: list[SectionContext] = []
    used = 0
    for ctx in contexts:
        cost = len(ctx.markdown)
        if not kept and cost > budget_chars:
            if budget_chars <= len(_TRUNCATION_MARKER):
                # Même vidée de son texte, la source ne tiendrait pas : seule la
                # marque de troncature entrerait, ce qui n'apprend rien au modèle.
                continue
            kept.append(_truncate(ctx, budget_chars))
            used = budget_chars
            continue
        if kept and used + cost > budget_chars:
            continue
        kept.append(ctx)
        used += cost
    return kept, len(contexts) - len(kept)


class PromptFit(NamedTuple):
    """Ce qui entre réellement dans le prompt, une fois le budget appliqué."""

    history: list[Message]
    contexts: list[SectionContext]
    dropped_contexts: int
    dropped_history: int
    budget_chars: int


def fit_prompt(
    question: str,
    contexts: list[SectionContext],
    chat_history: Sequence[Message] | None = None,
) -> PromptFit:
    """Applique le budget de fenêtre à l'historique PUIS aux sources.

    Dans cet ordre, parce que ce que l'historique occupe n'est plus disponible
    pour les sources — et que l'inverse laissait les sources remplir la fenêtre
    avant que l'historique ne la fasse déborder.

    Point d'entrée unique : `_build_messages` construit le prompt avec, et
    `/answer` chiffre ses `dropped_contexts` avec. Deux calculs séparés
    dériveraient, et la campagne d'évaluation rapporterait un autre nombre que
    ce qui a réellement atteint le LLM.
    """
    history, dropped_history = fit_history(chat_history or [])
    if dropped_history:
        logger.warning(
            "Historique tronqué : %d message(s) sur %d écarté(s) — budget %d caractères "
            "(%.0f %% de la fenêtre utile). Les plus anciens sautent.",
            dropped_history,
            len(chat_history or []),
            history_budget_chars(),
            _HISTORY_WINDOW_SHARE * 100,
        )

    budget = context_budget_chars(question, history, len(contexts))
    kept, dropped = fit_contexts(contexts, budget)
    if dropped:
        logger.warning(
            "Contexte tronqué : %d source(s) sur %d écartée(s) — budget %d caractères "
            "(num_ctx=%d, num_predict=%d, historique %d message(s)). Réduire "
            "RERANK_TOP_K ou augmenter LLM_NUM_CTX.",
            dropped,
            len(contexts),
            budget,
            settings.llm_num_ctx,
            settings.llm_max_tokens,
            len(history),
        )

    return PromptFit(history, kept, dropped, dropped_history, budget)


def estimate_prompt_tokens(messages: Sequence[dict[str, Any]]) -> int:
    """Tokens estimés du prompt, avec le ratio sur lequel le budget a tranché.

    Sert de terme de comparaison à `prompt_eval_count` : comparer autre chose
    que l'estimation qui a décidé de la coupe ne calibrerait rien.
    """
    chars = sum(len(str(msg.get("content", ""))) + _MESSAGE_FRAMING_CHARS for msg in messages)
    return math.ceil((chars + tools_overhead_chars()) / _CHARS_PER_TOKEN)


def log_prompt_measure(estimated_tokens: int, prompt_eval_count: int | None) -> None:
    """Confronte l'estimation du prompt au décompte réel rendu par Ollama.

    `prompt_eval_count` arrive dans le dernier événement du flux (celui qui
    porte `done: true`) : c'est le nombre RÉEL de tokens du prompt. Personne ne
    le lisait — le ratio caractères/token restait une devinette, et un prompt
    qui dépassait num_ctx ne laissait aucune trace, Ollama le tronquant sans
    rien dire. Le ratio mesuré journalisé ici est ce qui permettra de le
    calibrer sur des campagnes réelles au lieu de le poser au jugé.
    """
    if not prompt_eval_count or estimated_tokens <= 0:
        return

    ecart = (estimated_tokens - prompt_eval_count) / prompt_eval_count * 100
    # Le ratio mesuré est celui qu'il aurait fallu retenir pour que l'estimation
    # soit exacte : c'est lui, pas l'écart, qui se reporte dans le code.
    logger.info(
        "Prompt : estimé %d tokens, réel %d, écart %+.1f %% — ratio mesuré "
        "%.2f caractères/token (retenu : %.2f).",
        estimated_tokens,
        prompt_eval_count,
        ecart,
        _CHARS_PER_TOKEN * estimated_tokens / prompt_eval_count,
        _CHARS_PER_TOKEN,
    )

    if prompt_eval_count > settings.llm_num_ctx:
        logger.warning(
            "Prompt réel de %d tokens pour num_ctx=%d : Ollama a tronqué le prompt par "
            "le DÉBUT, donc le message système — les règles de citation et d'abstention "
            "n'encadraient pas cette réponse.",
            prompt_eval_count,
            settings.llm_num_ctx,
        )


def _build_messages(
    question: str,
    contexts: list[SectionContext],
    chat_history: list[Message],
) -> list[dict[str, Any]]:
    fit = fit_prompt(question, contexts, chat_history)

    msgs: list[dict[str, Any]] = [{"role": "system", "content": _load_system_prompt()}]
    for msg in fit.history:
        msgs.append({"role": msg.role, "content": msg.content})
    msgs.append({"role": "user", "content": _build_context_message(question, fit.contexts)})
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
            rewritten = str(resp.json().get("message", {}).get("content", "")).strip()
    except Exception:
        logger.warning("Réécriture de requête indisponible, question d'origine conservée.")
        return question

    # Le modèle peut préfixer (« Question autonome : »), commenter, ou répondre.
    rewritten = rewritten.splitlines()[0].strip() if rewritten else ""
    rewritten = re.sub(r"^[\s\-*>]*(question\s+autonome\s*:)?\s*", "", rewritten, flags=re.I)
    rewritten = rewritten.strip("\"'")

    if not rewritten or len(rewritten) > _MAX_REWRITE_CHARS:
        logger.info("Réécriture écartée (vide ou trop longue), question d'origine conservée.")
        return question

    if rewritten != question:
        logger.info("Question réécrite : %r → %r", question[:60], rewritten[:60])
    return rewritten


# Outil exposé au modèle pour relancer une recherche. Déclaré nativement plutôt
# que décrit en langage naturel : le modèle répond alors par un `tool_calls`
# structuré, au lieu d'une chaîne qu'il faut deviner dans sa prose.
SEARCH_TOOL = {
    "type": "function",
    "function": {
        "name": "search_vectors",
        "description": (
            "Rechercher des passages supplémentaires dans les documents. "
            "À utiliser uniquement si les sources fournies ne suffisent pas à "
            "répondre, avec une sous-question précise."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "La sous-question à rechercher, autonome et précise.",
                }
            },
            "required": ["query"],
        },
    },
}


def extract_tool_query(message: dict[str, Any]) -> str | None:
    """Extrait la sous-question d'un appel d'outil natif, None s'il n'y en a pas."""
    for call in message.get("tool_calls") or []:
        function = call.get("function") or {}
        if function.get("name") != "search_vectors":
            continue
        arguments = function.get("arguments")
        # Ollama rend un objet ; certains modèles rendent une chaîne JSON.
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except json.JSONDecodeError:
                continue
        query = (arguments or {}).get("query")
        if isinstance(query, str) and query.strip():
            return query.strip()
    return None


# Une traduction plus longue que cela n'en est pas une : le modèle a commenté,
# explique, ou a répondu à la question.
_MAX_TRANSLATION_RATIO = 3.0


async def translate_question(question: str) -> str | None:
    """Traduit la question dans l'autre langue du corpus, None en cas d'échec.

    Mesuré sur le corpus : quand la question et le document ne sont pas dans la
    même langue, le rappel du retrieval tombe de 0,99 à 0,74. La recherche
    lexicale, elle, ne trouve **rien** — deux langues ne partagent pas leurs
    mots. Sur cinq échecs analysés, BM25 sur la question traduite ramène le bon
    passage au rang 1 à 3, y compris pour deux passages que la recherche dense
    ne trouvait nulle part.

    La traduction n'est pas une réécriture : la question d'origine reste
    utilisée, la traduction s'y ajoute.
    """
    if not settings.cross_lingual_search:
        return None

    try:
        template = _get_jinja_env().get_template("translate_query.j2")
        prompt = template.render(question=question)
    except Exception:
        logger.warning("Gabarit de traduction introuvable, recherche monolingue.")
        return None

    payload = {
        "model": settings.ollama_model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "think": False,
        "options": {"temperature": 0.0, "num_predict": 150, "num_ctx": settings.llm_num_ctx},
    }

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(60.0)) as client:
            resp = await client.post(f"{settings.ollama_host}/api/chat", json=payload)
            resp.raise_for_status()
            traduction = str(resp.json().get("message", {}).get("content", "")).strip()
    except Exception:
        logger.warning("Traduction indisponible, recherche monolingue.")
        return None

    traduction = traduction.splitlines()[0].strip().strip("\"'") if traduction else ""
    if not traduction or len(traduction) > len(question) * _MAX_TRANSLATION_RATIO:
        return None
    # Le modèle rend parfois la question inchangée : rien à fusionner alors.
    if traduction.casefold() == question.casefold():
        return None

    logger.info("Question traduite : %r → %r", question[:50], traduction[:50])
    return traduction


async def generate_stream(
    question: str,
    contexts: list[SectionContext],
    chat_history: list[Message] | None = None,
    on_tool_call: Callable[[str], None] | None = None,
) -> AsyncIterator[str]:
    """Génère la réponse en streaming via l'API native Ollama.

    On utilise /api/chat (et non l'endpoint OpenAI-compatible) pour piloter
    `think` : Gemma 4 est un modèle à raisonnement et, sans ce flag, il peut
    consommer tout le budget num_predict en réflexion avant le premier token
    de réponse — prohibitif en CPU.
    """
    messages = _build_messages(question, contexts, chat_history or [])
    estimated_tokens = estimate_prompt_tokens(messages)

    logger.debug(
        "LLM generate : model=%s, messages=%d, contexte=%d sections, think=%s",
        settings.ollama_model,
        len(messages),
        len(contexts),
        settings.llm_thinking,
    )

    payload: dict[str, Any] = {
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
    if settings.native_tool_calling:
        payload["tools"] = [SEARCH_TOOL]

    timeout = httpx.Timeout(30.0, read=None)  # le premier token peut tarder (prefill CPU)
    prompt_eval_count: int | None = None
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
            message = data.get("message") or {}
            # Un appel d'outil arrive dans le flux, à part du contenu : il ne
            # doit jamais atteindre l'utilisateur.
            if on_tool_call:
                query = extract_tool_query(message)
                if query:
                    on_tool_call(query)
            delta = message.get("content", "")
            if delta:
                yield delta
            if data.get("done"):
                # Le dernier événement du flux porte le décompte réel des
                # tokens du prompt : la seule mesure disponible face à une
                # estimation qui, sans elle, ne se vérifie jamais.
                prompt_eval_count = data.get("prompt_eval_count")
                break

    log_prompt_measure(estimated_tokens, prompt_eval_count)


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
