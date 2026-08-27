import json
import logging
import math
import re
from collections.abc import AsyncIterator, Callable, Sequence
from pathlib import Path
from typing import Any, NamedTuple

import httpx
from jinja2 import Environment, FileSystemLoader, TemplateError, select_autoescape

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
# message. FORFAIT : le gabarit exact dépend du modèle. La valeur est celle de
# Gemma, comptée — « <start_of_turn>user\n » 20 caractères plus
# « <end_of_turn>\n » 14. Elle valait 24, soit 30 % de moins que le gabarit que
# son propre commentaire citait, et dans le sens dangereux : sous-estimer le
# prompt autant de fois qu'il y a de messages.
_MESSAGE_FRAMING_CHARS = 34

# Marque laissée dans une source coupée. Le modèle doit pouvoir distinguer une
# section qui s'achève d'une section amputée : sans marque, il conclut sur un
# texte tronqué comme s'il était complet.
_TRUNCATION_MARKER = "\n\n[…] Section tronquée : elle dépasse à elle seule la fenêtre."

# Tolérance sous num_ctx en deçà de laquelle on considère qu'Ollama a tronqué le
# prompt. Il tronque AVANT d'évaluer, donc `prompt_eval_count` ne peut jamais
# dépasser num_ctx : un décompte qui affleure la fenêtre est la seule trace
# observable de l'événement. Quelques tokens de jeu, le gabarit de chat pouvant
# ne pas retomber pile sur la borne.
_TRUNCATION_SUSPICION_TOKENS = 8

# En dessous de cette fraction de l'estimation, `prompt_eval_count` ne mesure
# plus le prompt : Ollama ne réévalue que le préfixe absent de son cache KV.
# Calibrer `_CHARS_PER_TOKEN` sur une telle mesure le ferait fondre à chaque
# tour de conversation.
_CACHE_HIT_RATIO = 0.6

# Marqueurs que `_render_element` intercale dans le markdown, un par élément.
# Couper à un index de caractère brut les ampute : `[src:00000000` n'est plus
# résolu par le post-processing — ou, pire, correspond à un AUTRE élément. Le
# prompt système ordonne de reprendre ces identifiants tels quels, et les
# citations sont l'objet même de ce dépôt.
#
# Même forme que `_BLOC_SRC` dans graph.py, à dessein : « marqueur complet » doit
# vouloir dire la même chose ici et dans le post-processing qui les résout. Un
# marqueur reconnu d'un côté seulement rouvrirait l'écart qu'on vient de fermer.
_MARKER_RE = re.compile(r"\[\s*(?:src|img):[^\]]*\]", re.I)


def prompt_window_chars() -> int:
    """Caractères que la fenêtre laisse au prompt, génération déduite.

    `num_ctx` est partagé entre le prompt et la génération : ce qui est réservé
    à `num_predict` n'est pas disponible pour le prompt.
    """
    return max(0, int((settings.llm_num_ctx - settings.llm_max_tokens) * _CHARS_PER_TOKEN))


def history_budget_chars() -> int:
    """Caractères que l'historique de conversation peut occuper au maximum.

    `HISTORY_WINDOW_SHARE` est un forfait, pas une mesure : l'historique est du
    contexte de second rang — `node_rewrite` a déjà rendu la question de suivi
    autonome avant l'encodage, donc les sources répondent sans lui. Trancher le
    partage autrement demanderait une mesure de la qualité multi-tour, qui
    n'existe pas ici.
    """
    return int(prompt_window_chars() * settings.history_window_share)


def fit_history(chat_history: Sequence[Message]) -> tuple[list[Message], int]:
    """Ne garde de l'historique que les derniers TOURS qui tiennent au budget.

    Sens inverse des sources : là on garde la tête du classement, ici la fin de
    la conversation — c'est le dernier échange qui situe la question.

    La coupe porte sur des tours, pas sur des messages. Couper par message
    produisait exactement ce que le docstring prétendait éviter : avec six
    messages de 2 000 caractères, seul le dernier survivait — l'assistant, sans
    la question à laquelle il répondait. Le prompt valait alors
    `['system', 'assistant', 'user']`, et un gabarit de chat strict sur
    l'alternance recevait un tour « model » juste après le système.

    Un tour est reconnu à son message `user` d'ouverture : on accumule depuis la
    fin, et on ne retient un bloc que lorsqu'il en a un. Un message d'assistant
    orphelin en tête de conversation ne part donc jamais seul.

    Un tour trop gros à lui seul est écarté, pas tronqué : un demi-échange
    n'apporte rien, alors qu'une demi-section reste lisible.

    Returns:
        (messages retenus, dans l'ordre ; nombre de messages écartés).
    """
    budget = history_budget_chars()
    kept: list[Message] = []
    tour: list[Message] = []
    used = 0

    for msg in reversed(chat_history):
        tour.insert(0, msg)
        if msg.role != "user":
            # Le début du tour n'est pas encore atteint : rien à arbitrer.
            continue
        cost = sum(len(m.content) + _MESSAGE_FRAMING_CHARS for m in tour)
        if used + cost > budget:
            break
        kept = tour + kept
        used += cost
        tour = []

    return kept, len(chat_history) - len(kept)


def source_framing_chars(question: str, contexts: Sequence[SectionContext]) -> list[int]:
    """Encadrement de CHAQUE source dans le gabarit, mesuré source par source.

    Séparateurs, numéro de source, identifiant, et surtout le fil des titres :
    « Chemin : … » est imprimé en clair, et en production `breadcrumbs` est
    toujours peuplé — c'est le résultat de la remontée `PARENT_OF`. L'encadrement
    va donc de 34 caractères sans fil des titres à 275 avec cinq niveaux (mesuré,
    cf. `test_l_encadrement_est_mesure_source_par_source`) : un forfait unique est
    faux dans les deux sens selon le document.

    Mesuré par décomposition : `rendu([source]) − rendu([]) − len(markdown)`.
    Le gabarit n'a aucune dépendance entre ses sources, la décomposition est donc
    exacte — vérifié sur douze sources, à un caractère près par source au-delà du
    neuvième rang, que `len(str(rang))` corrige : `Source {{ loop.index }}` gagne
    un chiffre. Le rang retenu est celui de la candidate, donc majorant : une
    source écartée renumérote celles qui suivent, jamais dans l'autre sens.
    """
    base = len(_build_context_message(question, []))
    return [
        len(_build_context_message(question, [ctx])) - base - len(ctx.markdown)
        + len(str(rang)) - 1
        for rang, ctx in enumerate(contexts, start=1)
    ]


def tools_overhead_chars() -> int:
    """Caractères de la déclaration d'outil, quand elle est envoyée.

    `tools` n'est pas un canal séparé pour le modèle : Ollama le rend DANS le
    prompt via le gabarit de chat, donc il consomme la fenêtre comme le reste.
    417 caractères, soit ~119 tokens, que rien ne comptait — le même trou que le
    forfait qu'on vient de retirer, à plus petite échelle.
    """
    return len(json.dumps(SEARCH_TOOL, ensure_ascii=False)) if settings.native_tool_calling else 0


def prompt_overhead_chars(question: str, chat_history: Sequence[Message]) -> int:
    """Caractères du prompt qui ne sont ni du texte de source ni leur encadrement.

    Prompt système, gabarit rendu sans ses sources, historique, balises de tour,
    déclaration d'outil. Un forfait de 512 tokens en tenait lieu et ne comptait
    jamais l'historique : six messages sont acceptés, chaque réponse assistante
    peut atteindre `LLM_MAX_TOKENS`, et le prompt dépassait num_ctx dès le
    troisième tour. Mesuré avant correctif : 31 380 caractères pour une fenêtre
    utile de 14 336.

    L'encadrement des sources n'est PAS ici : il dépend de la source, et n'est dû
    que par celles qui sont retenues. Le compter d'avance sur les candidates
    réservait la place de sources jamais rendues — dix candidates dont six
    retenues, et une septième qui aurait tenu se faisait écarter.
    """
    overhead = len(_load_system_prompt())
    # Le gabarit rendu sans sources : en-tête, question, consigne de citation.
    # Mesuré plutôt que forfaitisé — c'est le seul moyen qu'une retouche de
    # answer_with_context.j2 se répercute sur le budget.
    overhead += len(_build_context_message(question, []))
    overhead += sum(len(msg.content) for msg in chat_history)
    # Un tour par message d'historique, plus le système et les sources.
    overhead += (len(chat_history) + 2) * _MESSAGE_FRAMING_CHARS
    overhead += tools_overhead_chars()
    return overhead


def context_budget_chars(question: str, chat_history: Sequence[Message]) -> int:
    """Caractères que les sources — texte ET encadrement — peuvent occuper.

    Calculé sur ce qui est RÉELLEMENT dans le prompt : passer un historique
    long réduit le budget, jusqu'à l'annuler. L'historique attendu ici est déjà
    borné par `fit_history` — sinon le budget décrirait un prompt que
    `_build_messages` ne construit pas.
    """
    return max(0, prompt_window_chars() - prompt_overhead_chars(question, chat_history))


def _sans_crochet_ouvert(tete: str) -> str:
    """Retire de `tete` un crochet que la coupe a laissé ouvert.

    N'avoir croisé aucun marqueur COMPLET ne veut pas dire qu'on n'a croisé aucun
    crochet : la coupe peut tomber À L'INTÉRIEUR du premier — « [src:00000 »,
    « [Tableau ». Rendre la tête telle quelle laisse ce début de marqueur dans le
    prompt, et le post-processing ne résout pas un identifiant amputé.

    La bande où cela se produit est étroite — entre la coupe minimale et la fin
    du premier marqueur — et c'est ce qui l'avait fait disparaître d'un lot sans
    que rien ne rougisse : le balayage qui la surveillait commençait au-dessus
    d'elle.
    """
    ouvert = tete.rfind("[")
    return tete[:ouvert] if ouvert != -1 and "]" not in tete[ouvert:] else tete


def _cut_on_marker(markdown: str, limite: int, *, exiger_marqueur: bool) -> str:
    """Coupe `markdown` au plus tard à `limite`, sur une frontière d'élément.

    Tronquer une source déplace la frontière entre ce que le modèle **lit** et ce
    qu'il peut **citer**. Deux dérives symétriques, et les deux sont mauvaises.

    Le marqueur survit, son contenu part → le modèle cite une source dont il n'a
    pas vu le texte. Elle est impossible par construction, et non pas évitée :
    `_render_element` écrit « texte [src:ID] », le marqueur SUIT son élément.
    Toute coupe est un préfixe, donc tout marqueur retenu a son texte devant lui.
    C'est structurel, pas une précaution — et c'est ce qui compte, parce que
    `resolve_citations` résout un `[src:ID]` depuis le modèle `SectionContext` et
    non depuis le texte soumis : un marqueur orphelin rendrait une citation vers
    un extrait que le modèle n'a jamais reçu.

    Le contenu survit, son marqueur part → le modèle lit un passage qu'il ne peut
    pas attribuer, donc il l'utilisera sans référence ou le rattachera au
    marqueur précédent, c'est-à-dire au mauvais élément. C'est celle-ci qu'il
    faut écarter activement, et c'est tout le travail de cette fonction : la
    coupe recule jusqu'à la fin du dernier marqueur COMPLET.

    Aucun marqueur complet dans la tête ? Alors la tête est un préfixe du PREMIER
    élément : les marqueurs suivent leur texte, donc n'en avoir croisé aucun veut
    dire qu'on n'a pas fini le premier. Il n'y a alors aucun marqueur voisin
    auquel le modèle pourrait rattacher le fragment par erreur — seulement une
    perte de précision, l'attribution retombant sur la section, que le gabarit
    annonce par « Source N — element_id ».

    `exiger_marqueur` porte ce choix. Vrai, on rend une chaîne vide et l'appelant
    écarte la source : une autre est déjà retenue, la précision d'attribution
    vaut mieux qu'un préfixe d'élément. Faux, on rend la tête : c'est le cas où
    la refuser enverrait un prompt sans aucune source, et « mieux vaut une source
    amputée que zéro source » l'a déjà tranché (registre 1.14).

    Une source qui ne porte aucun marqueur du tout se coupe librement dans les
    deux cas : il n'y a pas de précision à perdre. « Librement » ne veut pas dire
    « à l'index brut » pour autant : `_sans_crochet_ouvert` retire ce que la coupe
    a laissé entamé.

    L'ancienne version rendait la tête telle quelle dès qu'un crochet
    quelconque — « [Tableau] », une note « [1] » — s'y trouvait refermé, et elle
    la rendait TOUJOURS. C'était la seconde dérive, produite par le garde-fou
    censé l'éviter.
    """
    tete = markdown[:limite]
    complets = list(_MARKER_RE.finditer(tete))
    if complets:
        return tete[: complets[-1].end()]
    if exiger_marqueur and _MARKER_RE.search(markdown):
        return ""
    return _sans_crochet_ouvert(tete)


def truncation_floor_chars(ctx: SectionContext) -> int:
    """Caractères qu'un fragment de `ctx` doit atteindre pour valoir sa place.

    Une part de la source, pas un nombre absolu — et c'est l'arbitrage. Le
    dommage visé est un fragment qui **ne représente pas** sa section : le modèle
    en voit assez pour la citer, pas assez pour savoir ce qu'elle dit. C'est une
    proportion, pas une longueur. Un plancher absolu se tromperait dans un cas
    que la grille contient : une source de 300 caractères coupée à 250 en garde
    83 %, elle est parfaitement lisible, et tout plancher absolu supérieur à 250
    l'écarterait.

    Un plancher absolu existe déjà, et il est structurel : quand le marqueur est
    exigé, `_cut_on_marker` n'accepte de coupe qu'à la fin d'un marqueur, donc le
    fragment porte au minimum **un élément entier avec son identifiant**. Rien
    n'est réglable là. Il ne couvre en revanche ni le cas relâché — plus rien
    d'autre à retenir — ni une source qui ne porte aucun marqueur : c'est
    exactement là que ce plancher-ci reste seul à décider.
    """
    return math.ceil(settings.truncation_floor_share * len(ctx.markdown))


def _truncate(
    ctx: SectionContext, budget_chars: int, *, exiger_marqueur: bool, exiger_plancher: bool
) -> SectionContext | None:
    """Coupe une source par la FIN pour la faire tenir dans `budget_chars`.

    Rend `None` quand la coupe ne vaut pas la place qu'elle prendrait — trois
    raisons, toutes journalisées : la marque de troncature ne tiendrait même pas,
    aucun marqueur de citation ne tient dans la tête (cf. `_cut_on_marker`), ou
    le fragment n'atteint pas `truncation_floor_chars`.

    Les deux exigences sont portées par **deux** paramètres, et ce n'est pas une
    coquetterie : elles n'arbitrent pas la même chose. `exiger_marqueur` demande
    si le fragment est **attribuable** — porte-t-il un identifiant de citation.
    `exiger_plancher` demande s'il **représente** sa source — en montre-t-il
    assez pour qu'on sache ce qu'elle dit. Un fragment peut satisfaire l'une et
    pas l'autre dans les deux sens.

    Elles se relâchent aujourd'hui sur la même condition — aucune autre source
    retenue — et un seul booléen les portait. Rien ne garantit que les réponses
    continueront de coïncider, et un test qui ne peut pas les séparer ne garde
    ni l'une ni l'autre : forcer l'ancien booléen à faux ne faisait rougir
    personne.
    """
    place = budget_chars - len(_TRUNCATION_MARKER)
    if place <= 0:
        logger.info(
            "Source %s écartée : %d caractères de fenêtre restants, la seule marque "
            "de troncature en demande %d.",
            ctx.element_id,
            budget_chars,
            len(_TRUNCATION_MARKER),
        )
        return None

    garde = _cut_on_marker(ctx.markdown, place, exiger_marqueur=exiger_marqueur)
    if not garde:
        logger.info(
            "Source %s écartée : aucun marqueur de citation ne tient dans les %d "
            "caractères restants, et une autre source est déjà retenue. Le fragment "
            "serait un préfixe d'élément attribuable à la section seulement.",
            ctx.element_id,
            place,
        )
        return None

    minimum = truncation_floor_chars(ctx)
    if exiger_plancher and len(garde) < minimum:
        logger.info(
            "Source %s écartée : %d caractères tiendraient sur %d, soit %.0f %% de la "
            "source — sous le plancher de %.0f %% (TRUNCATION_FLOOR_SHARE). Le modèle "
            "en verrait assez pour la citer et pas assez pour savoir ce qu'elle dit.",
            ctx.element_id,
            len(garde),
            len(ctx.markdown),
            100 * len(garde) / len(ctx.markdown),
            100 * settings.truncation_floor_share,
        )
        return None

    logger.warning(
        "Source %s tronquée : %d caractères conservés sur %d (%.0f %%) — elle ne tenait "
        "pas entière dans les %d restants. La coupe se fait ici, par la FIN et sur une "
        "frontière d'élément ; laissée à Ollama, elle se ferait par le DÉBUT du prompt.",
        ctx.element_id,
        len(garde),
        len(ctx.markdown),
        100 * len(garde) / len(ctx.markdown),
        budget_chars,
    )
    return ctx.model_copy(update={"markdown": garde + _TRUNCATION_MARKER})


def fit_contexts(
    contexts: list[SectionContext],
    budget_chars: int,
    framing_chars: Sequence[int] | None = None,
) -> tuple[list[SectionContext], int]:
    """Fait entrer dans la fenêtre ce qui y entre, et tronque ce qui la remplit.

    Sans cette borne, Ollama tronque le prompt lui-même — silencieusement, et
    par le DÉBUT, donc en jetant le message système puis les premières sources.
    Le système pouvait répondre « je n'ai pas trouvé » sur une information
    qu'il avait reçue.

    Deux passes, et la seconde est ce que ce lot ajoute.

    **Remplissage au mieux.** Les sources arrivent classées par pertinence
    décroissante — c'est `node_reconstruct_context` qui le garantit, pas
    l'appelant. Chacune est retenue si elle tient entière ; sinon elle est mise
    de côté, et une source plus petite qui la suit peut encore passer. Ce n'est
    pas « la queue de la liste qui saute ».

    **La marge revient à la mieux classée des écartées, tronquée.** Elle restait
    vide : mesuré sur la grille, 1 355 caractères de fenêtre inutilisés en
    moyenne et 7 970 au maximum sur 88 configurations, ramenés à 408 en
    moyenne — 70 % de la marge reprise, 38 configurations gagnées et aucune
    perdue. Une source presque entièrement finançable était rejetée pour quelques
    centaines de caractères manquants.

    Cette phrase est reprise **mot pour mot** dans `documentation/llm.md` et dans
    le registre, et `test_coherence_depot` exige qu'elles restent identiques : la
    même grille avait fini par porter trois triplets différents, un par endroit
    où elle était recopiée. Le protocole qui la produit est dans `llm.md`, et il
    tourne à sec.

    La coupe n'est pas systématique. `_truncate` refuse un fragment qui
    n'atteint pas `TRUNCATION_FLOOR_SHARE` de sa source : sous ce seuil, le
    modèle en voit assez pour la citer et pas assez pour savoir ce qu'elle dit,
    et un défaut silencieux vaut moins qu'une abstention visible. Quand la
    mieux classée est refusée, la suivante est essayée — plus petite, elle a plus
    de chances d'atteindre sa part. La première qui passe prend la marge, et la
    boucle s'arrête : il n'y a qu'une marge à donner.

    Le plancher ne joue que si une source est déjà retenue, et l'exigence de
    marqueur avec lui — mais ce sont **deux** décisions, portées par deux
    paramètres de `_truncate` : « ce fragment représente-t-il sa source » et « ce
    fragment est-il attribuable ». Sinon il n'y a rien à arbitrer, et « mieux
    vaut une source amputée que zéro source » reste le choix du budget : une
    section sans `SectionHeader` — fenêtre de 13 éléments, textes intégraux
    relus dans l'index — dépasse à elle seule la fenêtre, et l'écarter rendrait
    une abstention sur un document qu'on venait de trouver.

    `framing_chars` porte l'encadrement mesuré de chaque source
    (`source_framing_chars`). Il est facturé au moment où la source est
    retenue — donc jamais pour une candidate écartée. Absent, il vaut zéro :
    la fonction reste alors de l'arithmétique pure sur des longueurs.

    Returns:
        (sources retenues, nombre de sources écartées).
    """
    if budget_chars <= 0:
        # Plus rien ne tient : ni garder ni tronquer n'a de sens. Mieux vaut une
        # abstention qu'un prompt dont Ollama ampute le message système.
        return [], len(contexts)

    framing = list(framing_chars) if framing_chars is not None else [0] * len(contexts)
    kept: list[SectionContext] = []
    ecartees: list[tuple[SectionContext, int]] = []
    used = 0
    for ctx, encadrement in zip(contexts, framing, strict=True):
        cost = len(ctx.markdown) + encadrement
        if used + cost <= budget_chars:
            kept.append(ctx)
            used += cost
        else:
            ecartees.append((ctx, encadrement))

    for ctx, encadrement in ecartees:
        # Deux décisions distinctes, relâchées aujourd'hui par la même condition :
        # tant que rien n'est retenu, refuser la coupe enverrait un prompt sans
        # aucune source. Elles restent deux paramètres pour que la prochaine
        # raison de relâcher l'une ne relâche pas l'autre par inadvertance.
        seule_chance = not kept
        tronquee = _truncate(
            ctx,
            budget_chars - used - encadrement,
            exiger_marqueur=not seule_chance,
            exiger_plancher=not seule_chance,
        )
        if tronquee is None:
            continue
        kept.append(tronquee)
        used += len(tronquee.markdown) + encadrement
        break

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
            "(%.0f %% de la fenêtre utile, HISTORY_WINDOW_SHARE). Les tours les plus "
            "anciens sautent, entiers.",
            dropped_history,
            len(chat_history or []),
            history_budget_chars(),
            settings.history_window_share * 100,
        )

    budget = context_budget_chars(question, history)
    kept, dropped = fit_contexts(contexts, budget, source_framing_chars(question, contexts))
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


def prompt_window_tokens() -> int:
    """Tokens que la fenêtre laisse au prompt, `num_predict` réservé."""
    return max(0, settings.llm_num_ctx - settings.llm_max_tokens)


class PromptMeasure(NamedTuple):
    """Ce que le serveur d'inférence a réellement compté sur une génération.

    Publié par `generate_stream` via `on_measure`, comme `PromptFit` l'est par
    `on_fit`, et pour la même raison : la valeur n'existait qu'en journal, donc
    RIEN ne l'observait — `prompt_eval_count` a été instrumenté au lot 1 et
    n'avait toujours produit aucune mesure.
    """

    estimated_tokens: int
    prompt_eval_count: int | None
    # Tokens générés. C'est la grandeur dont dépend le réglage de
    # `LLM_MAX_TOKENS`, qui confisque la moitié de la fenêtre à la génération
    # sans que rien ne dise qu'elle en ait besoin.
    eval_count: int | None
    # Le plafond qui s'appliquait. Sans lui, « la génération a-t-elle été
    # coupée ? » n'est pas décidable depuis `eval_count` seul.
    num_predict: int
    # Faux = `prompt_eval_count` est inexploitable, cf.
    # `mesure_prompt_exploitable`.
    prompt_reliable: bool


def mesure_prompt_exploitable(estimated_tokens: int, prompt_eval_count: int | None) -> bool:
    """`prompt_eval_count` mesure-t-il bien le prompt entier ?

    **Point de décision unique.** `log_prompt_measure` l'applique pour écarter la
    mesure de la calibration ; la campagne l'applique pour ne pas moyenner des
    échantillons pollués. Deux prédicats séparés dériveraient, et la campagne
    publierait un ratio caractères/token que le journal aurait refusé.

    Ollama ne réévalue que le préfixe absent de son cache KV : au deuxième tour
    d'une conversation — et, pour une campagne, à chaque question, le message
    système étant identique — le décompte ne mesure plus le prompt. En dessous de
    `_CACHE_HIT_RATIO` fois l'estimation, l'écart est trop grand pour être une
    erreur d'estimation.
    """
    if not prompt_eval_count or estimated_tokens <= 0:
        return False
    return prompt_eval_count >= estimated_tokens * _CACHE_HIT_RATIO


def log_prompt_measure(estimated_tokens: int, prompt_eval_count: int | None) -> None:
    """Confronte l'estimation du prompt au décompte réel rendu par Ollama.

    `prompt_eval_count` arrive dans le dernier événement du flux (celui qui
    porte `done: true`) : c'est le nombre RÉEL de tokens du prompt. Personne ne
    le lisait — le ratio caractères/token restait une devinette, et un prompt
    trop long ne laissait aucune trace, Ollama le tronquant sans rien dire.

    Deux pièges, tous deux dus à la façon dont Ollama compte.

    La première version avertissait sur `prompt_eval_count > num_ctx`, condition
    structurellement inatteignable : Ollama tronque le prompt AVANT de l'évaluer,
    donc le décompte est majoré par num_ctx par construction. Le détecteur ne
    pouvait pas voir ce qu'il cherchait. Ce sont les deux zones en dessous de la
    borne qui parlent : un décompte qui affleure num_ctx (troncature très
    probable) et un décompte au-delà de la fenêtre de prompt (la génération se
    fait rogner son `num_predict`, en silence).

    Second piège : le cache KV. Ollama ne réévalue que le préfixe absent de son
    cache, donc au deuxième tour d'une conversation `prompt_eval_count` ne
    mesure plus le prompt. Une telle valeur est écartée de la calibration, sans
    quoi le ratio fondrait à chaque tour.
    """
    if not prompt_eval_count or estimated_tokens <= 0:
        return

    if not mesure_prompt_exploitable(estimated_tokens, prompt_eval_count):
        logger.info(
            "Prompt : réel %d tokens pour %d estimés — écart trop grand pour être une "
            "erreur d'estimation. Ollama n'a réévalué que le préfixe absent de son "
            "cache KV : mesure écartée de la calibration de _CHARS_PER_TOKEN.",
            prompt_eval_count,
            estimated_tokens,
        )
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

    if prompt_eval_count >= settings.llm_num_ctx - _TRUNCATION_SUSPICION_TOKENS:
        logger.warning(
            "Prompt réel de %d tokens, à %d tokens de num_ctx=%d : Ollama tronque avant "
            "d'évaluer, donc un décompte qui affleure la fenêtre signale une troncature "
            "PAR LE DÉBUT — le message système, et avec lui les règles de citation et "
            "d'abstention, a pu ne pas encadrer cette réponse.",
            prompt_eval_count,
            settings.llm_num_ctx - prompt_eval_count,
            settings.llm_num_ctx,
        )
    elif prompt_eval_count > prompt_window_tokens():
        logger.warning(
            "Prompt réel de %d tokens pour une fenêtre de prompt de %d (num_ctx=%d − "
            "num_predict=%d) : il ne reste que %d tokens à la génération, qui sera "
            "rognée sans le dire. Le budget de contexte a sous-estimé le prompt.",
            prompt_eval_count,
            prompt_window_tokens(),
            settings.llm_num_ctx,
            settings.llm_max_tokens,
            settings.llm_num_ctx - prompt_eval_count,
        )


def _build_messages(
    question: str,
    contexts: list[SectionContext],
    chat_history: list[Message],
) -> tuple[list[dict[str, Any]], PromptFit]:
    """Construit le prompt, et rend avec lui le budget tel qu'il a été appliqué."""
    fit = fit_prompt(question, contexts, chat_history)

    msgs: list[dict[str, Any]] = [{"role": "system", "content": _load_system_prompt()}]
    for msg in fit.history:
        msgs.append({"role": msg.role, "content": msg.content})
    msgs.append({"role": "user", "content": _build_context_message(question, fit.contexts)})
    return msgs, fit


# Une question de suivi est courte : au-delà, le modèle a paraphrasé ou répondu
# au lieu de réécrire, et sa sortie ne doit pas être utilisée comme requête.
_MAX_REWRITE_CHARS = 400


def _contenu_message(corps: Any) -> str:
    """Extrait `message.content` d'une réponse Ollama, "" si la forme diffère.

    **Nomme la forme acceptée** — objet, puis objet, puis chaîne — au lieu
    d'élargir l'absorption qui entoure l'appel. Un corps peut être du JSON
    parfaitement VALIDE sans avoir cette forme : `{"message": null}`,
    `{"message": "…"}`, `{"message": []}`, ou un corps qui n'est pas un objet.
    C'est ce qu'un changement de version d'Ollama, un proxy en erreur, ou un
    backend « compatible » produit — et `.get("message", {}).get("content", "")`
    lève alors `AttributeError`. `node_rewrite` n'ayant aucun try/except,
    l'exception traversait le graphe jusqu'à la route : /chat/start et /answer
    rendaient 500.

    Ajouter `AttributeError` et `TypeError` au tuple aurait suffi à éteindre le
    500, et aurait ramené exactement ce que le resserrement sert à empêcher : une
    erreur de programmation dans le bloc, absorbée et journalisée comme une
    « réécriture indisponible ». Un `AttributeError` authentique remonte donc
    encore ; une réponse mal formée devient une chaîne vide.

    La feuille est vérifiée aussi, et ce n'est pas du zèle : `content` à `null`
    ne lève rien, mais `str(None)` rend la chaîne « None », quatre caractères qui
    passent le garde-fou aval et partent en requête de recherche. Un 500 se voit ;
    une recherche sur « None » ne se voit pas.

    Le "" rendu ici n'est jamais utilisé tel quel : les deux appelants ont un
    garde-fou aval — « vide ou trop longue → question d'origine » pour la
    réécriture, « vide → pas de traduction » pour la traduction. Sans eux, une
    chaîne vide partirait en requête de recherche, et à `TRANSLATION_WEIGHT=1.0`
    une traduction vide entrerait dans la fusion RRF : strictement pire que le
    500 qu'on corrige.
    """
    message = corps.get("message") if isinstance(corps, dict) else None
    contenu = message.get("content") if isinstance(message, dict) else None
    return contenu.strip() if isinstance(contenu, str) else ""


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
    except (TemplateError, OSError):
        # Gabarit absent, illisible, ou syntaxe Jinja fautive. Resserré depuis
        # `Exception` : celui-ci avalait aussi une erreur de programmation dans
        # ce bloc, et la réécriture se serait déclarée « indisponible » à chaque
        # question sans que rien ne dise pourquoi.
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
            rewritten = _contenu_message(resp.json())
    except (httpx.HTTPError, ValueError):
        # Deux des TROIS façons dont l'appel peut échouer sans que le code soit
        # en cause : le transport (HTTPError couvre le statut, le délai et la
        # connexion) et un corps qui n'est pas du JSON (JSONDecodeError hérite de
        # ValueError). La troisième — un corps qui EST du JSON valide mais n'a pas
        # la forme attendue — n'est PAS traitée ici : elle l'est par
        # `_contenu_message`, qui nomme la forme acceptée. Élargir ce tuple
        # ramènerait les erreurs de programmation que le resserrement écarte.
        #
        # `httpx.InvalidURL` n'y entre pas non plus, et c'est délibéré : elle
        # hérite directement d'`Exception`, et un OLLAMA_HOST mal formé est une
        # erreur de CONFIGURATION. Elle casse aussi `generate_stream` : la
        # rattraper ici dégraderait la recherche en monolingue en laissant croire
        # que le service fonctionne, au lieu de dire qu'il est mal configuré.
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
    except (TemplateError, OSError):
        # Même raisonnement que pour la réécriture : seules les pannes du
        # gabarit justifient le repli, pas une erreur de programmation.
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
            traduction = _contenu_message(resp.json())
    except (httpx.HTTPError, ValueError):
        # Transport ou corps non-JSON, comme pour la réécriture — et comme là-bas,
        # la forme du corps est traitée par `_contenu_message` et non par le
        # tuple, `httpx.InvalidURL` restant volontairement dehors.
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
    on_fit: Callable[[PromptFit], None] | None = None,
    on_measure: Callable[[PromptMeasure], None] | None = None,
) -> AsyncIterator[str]:
    """Génère la réponse en streaming via l'API native Ollama.

    On utilise /api/chat (et non l'endpoint OpenAI-compatible) pour piloter
    `think` : Gemma 4 est un modèle à raisonnement et, sans ce flag, il peut
    consommer tout le budget num_predict en réflexion avant le premier token
    de réponse — prohibitif en CPU.

    `on_fit` reçoit le budget tel qu'il a été appliqué. Sans ce rappel, /answer
    devait refaire `fit_prompt` pour chiffrer ses `dropped_contexts` : chaque
    troncature était journalisée deux fois, et le gabarit rendu une fois de plus
    par source candidate.

    `on_measure` reçoit les décomptes réels du serveur d'inférence. Même motif,
    même raison : `prompt_eval_count` ne sortait qu'en journal, donc personne ne
    l'a jamais observé, et `eval_count` n'était même pas lu — alors que c'est la
    seule grandeur qui puisse dire si `LLM_MAX_TOKENS` sert à quelque chose.
    """
    messages, fit = _build_messages(question, contexts, chat_history or [])
    if on_fit:
        on_fit(fit)
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
    eval_count: int | None = None
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
                # Et le décompte des tokens GÉNÉRÉS, au même endroit. Personne ne
                # le lisait : `runs/*.json` n'enregistrait que `generation_ms`,
                # donc « la génération n'atteint jamais son plafond » restait une
                # présomption.
                eval_count = data.get("eval_count")
                break

    log_prompt_measure(estimated_tokens, prompt_eval_count)
    if on_measure:
        on_measure(
            PromptMeasure(
                estimated_tokens=estimated_tokens,
                prompt_eval_count=prompt_eval_count,
                eval_count=eval_count,
                num_predict=settings.llm_max_tokens,
                prompt_reliable=mesure_prompt_exploitable(estimated_tokens, prompt_eval_count),
            )
        )


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
