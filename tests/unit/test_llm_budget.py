"""Budget de contexte : ce qui ne tient pas dans la fenêtre du modèle doit être
écarté ici, explicitement — sinon Ollama tronque en silence, et par le DÉBUT du
prompt, donc en jetant le message système (les règles de citation et
d'abstention) puis les sources les mieux classées.

Le budget se calcule sur ce qui est RÉELLEMENT dans le prompt. Il ne comptait
que les sources : l'historique de conversation n'entrait dans aucun calcul, et
six messages suffisaient à faire dépasser num_ctx — 31 380 caractères mesurés
pour une fenêtre utile de 14 336."""

import json
import logging

import pytest

from src.agent import llm
from src.agent.llm import (
    _TRUNCATION_MARKER,
    _build_messages,
    _load_system_prompt,
    context_budget_chars,
    estimate_prompt_tokens,
    fit_contexts,
    fit_history,
    fit_prompt,
    history_budget_chars,
    log_prompt_measure,
    prompt_window_chars,
)
from src.agent.settings import settings
from src.api.schemas import MAX_MESSAGE_CHARS, Message, SectionContext


def _context(element_id: str, taille: int) -> SectionContext:
    return SectionContext(
        element_id=element_id,
        section_id=element_id,
        breadcrumbs=[],
        elements=[],
        markdown="x" * taille,
    )


def _historique(nb: int, taille: int) -> list[Message]:
    return [
        Message(role="user" if i % 2 == 0 else "assistant", content="m" * taille)
        for i in range(nb)
    ]


# ─── Le budget compte ce qui est réellement dans le prompt ────────────────────

def test_budget_deduit_la_generation_de_la_fenetre() -> None:
    """num_ctx est partagé : ce qui est réservé à num_predict n'est pas du contexte."""
    assert context_budget_chars("question", [], source_count=1) > 0
    assert prompt_window_chars() < settings.llm_num_ctx * 3.5


def test_un_historique_long_reduit_le_budget_des_sources() -> None:
    """Le trou d'ALG-2 : l'historique n'entrait dans aucun calcul.

    Un forfait de 512 tokens était censé le couvrir. Six messages sont acceptés
    et chaque réponse assistante peut atteindre LLM_MAX_TOKENS : le forfait
    était dépassé d'un ordre de grandeur.
    """
    sans = context_budget_chars("question", [], source_count=3)
    avec = context_budget_chars("question", _historique(4, 800), source_count=3)

    assert avec < sans
    # Ce que l'historique occupe est retiré caractère pour caractère.
    assert sans - avec >= 4 * 800


def test_le_prompt_systeme_est_compte_dans_le_budget() -> None:
    """Le message système est le premier que tronque Ollama : il doit être compté."""
    budget = context_budget_chars("question", [], source_count=0)

    assert budget <= prompt_window_chars() - len(_load_system_prompt())


def test_le_gabarit_rendu_est_compte_dans_le_budget() -> None:
    """Le gabarit est mesuré, pas forfaitisé : une retouche s'y répercute."""
    question_courte = context_budget_chars("q", [], source_count=0)
    question_longue = context_budget_chars("q" * 2000, [], source_count=0)

    assert question_longue < question_courte
    assert question_courte - question_longue >= 1999  # noqa: PLR2004


def test_l_encadrement_des_sources_est_compte() -> None:
    """Séparateurs, numéro, identifiant et fil des titres entrent dans le prompt."""
    assert context_budget_chars("q", [], source_count=10) < context_budget_chars(
        "q", [], source_count=1
    )


def test_la_declaration_d_outil_est_comptee(monkeypatch) -> None:
    """`tools` n'est pas un canal séparé : Ollama le rend dans le prompt.

    417 caractères que rien ne comptait — le même trou que le forfait retiré,
    à plus petite échelle.
    """
    from src.agent import llm

    avec = context_budget_chars("q", [], source_count=1)
    cout = llm.tools_overhead_chars()
    monkeypatch.setattr(llm.settings, "native_tool_calling", False)
    sans = context_budget_chars("q", [], source_count=1)

    assert llm.tools_overhead_chars() == 0
    assert sans - avec == cout > 0


def test_le_budget_ne_devient_jamais_negatif() -> None:
    """Un historique qui dépasse la fenêtre donne 0, pas un budget négatif.

    Le pire cas que l'API accepte : six messages à la borne de Message.content.
    """
    pire_cas = _historique(6, MAX_MESSAGE_CHARS)

    assert context_budget_chars("q", pire_cas, source_count=5) == 0


# ─── Le prompt construit tient dans la fenêtre ────────────────────────────────

def test_le_prompt_construit_tient_dans_la_fenetre() -> None:
    """Le mode de panne d'ALG-2, de bout en bout.

    Avant correctif : 31 380 caractères de prompt pour une fenêtre utile de
    14 336 — Ollama tronquait par le DÉBUT, donc jetait le message système.
    """
    msgs = _build_messages(
        "Quelle est la question ?",
        [_context("a", 12_000), _context("b", 12_000)],
        _historique(6, 3000),
    )
    total = sum(len(str(m["content"])) for m in msgs)

    assert total <= prompt_window_chars()


def test_le_prompt_garde_toujours_le_message_systeme() -> None:
    """Même sous un historique démesuré, c'est le système qui reste."""
    msgs = _build_messages("q", [_context("a", 50_000)], _historique(6, MAX_MESSAGE_CHARS))

    assert msgs[0]["role"] == "system"
    assert estimate_prompt_tokens(msgs) <= settings.llm_num_ctx


# ─── Historique : les plus récents survivent ──────────────────────────────────

def test_l_historique_garde_les_messages_les_plus_recents() -> None:
    """Sens inverse des sources : c'est le dernier échange qui situe la question."""
    historique = [Message(role="user", content=f"{i}" * 2000) for i in range(6)]
    kept, dropped = fit_history(historique)

    assert kept == historique[-len(kept) :]
    assert dropped == 6 - len(kept)


def test_l_historique_est_borne_a_une_part_de_la_fenetre() -> None:
    kept, _ = fit_history(_historique(6, 4000))

    assert sum(len(m.content) for m in kept) <= history_budget_chars()
    assert history_budget_chars() < prompt_window_chars()


def test_un_historique_court_passe_entier() -> None:
    historique = _historique(4, 100)

    assert fit_history(historique) == (historique, 0)


def test_un_message_trop_gros_est_ecarte_pas_tronque() -> None:
    """Un demi-tour de conversation n'apporte rien ; node_rewrite a déjà rendu
    la question autonome, donc l'historique est du confort, pas un prérequis."""
    kept, dropped = fit_history([Message(role="user", content="m" * MAX_MESSAGE_CHARS)])

    assert kept == []
    assert dropped == 1


# ─── Sources : ordre, remplissage au mieux, troncature ────────────────────────

def test_toutes_les_sources_passent_si_le_budget_suffit() -> None:
    contexts = [_context("a", 100), _context("b", 100)]
    kept, dropped = fit_contexts(contexts, budget_chars=1000)

    assert len(kept) == 2  # noqa: PLR2004
    assert dropped == 0


def test_la_queue_saute_a_taille_egale() -> None:
    """Les sources sont ordonnées par pertinence : on garde les premières."""
    contexts = [_context("a", 400), _context("b", 400), _context("c", 400)]
    kept, dropped = fit_contexts(contexts, budget_chars=900)

    assert [c.element_id for c in kept] == ["a", "b"]
    assert dropped == 1


def test_le_remplissage_est_au_mieux_pas_une_coupe_de_la_queue() -> None:
    """`continue` et non `break` : une petite source après une grosse écartée
    est conservée.

    Le comportement est raisonnable, mais le docstring annonçait « c'est la
    queue de la liste qui saute » — ce que le code n'a jamais fait. À tailles
    égales les deux comportements sont indistinguables : il faut une grosse
    source au milieu pour les séparer, ce que le test précédent ne faisait pas.
    """
    contexts = [_context("a", 300), _context("b", 900), _context("c", 300)]
    kept, dropped = fit_contexts(contexts, budget_chars=700)

    assert [c.element_id for c in kept] == ["a", "c"]  # « queue qui saute » dirait ["a"]
    assert dropped == 1


def test_la_source_unique_trop_grosse_est_tronquee() -> None:
    """IMP-6 : elle était transmise entière, et Ollama coupait — par le DÉBUT."""
    kept, dropped = fit_contexts([_context("a", 10_000)], budget_chars=1000)

    assert [c.element_id for c in kept] == ["a"]
    assert len(kept[0].markdown) <= 1000  # noqa: PLR2004
    assert dropped == 0


def test_la_troncature_conserve_le_debut_et_se_signale() -> None:
    """Coupée par la fin, et marquée : le modèle doit voir qu'il manque du texte."""
    source = _context("a", 10_000)
    kept, _ = fit_contexts([source], budget_chars=1000)

    assert kept[0].markdown.endswith(_TRUNCATION_MARKER)
    assert source.markdown.startswith(kept[0].markdown[: -len(_TRUNCATION_MARKER)])


def test_un_budget_epuise_ecarte_tout() -> None:
    """Budget nul : mieux vaut une abstention qu'un prompt amputé de son système."""
    kept, dropped = fit_contexts([_context("a", 100), _context("b", 100)], budget_chars=0)

    assert kept == []
    assert dropped == 2  # noqa: PLR2004


def test_sans_source() -> None:
    assert fit_contexts([], budget_chars=1000) == ([], 0)


# ─── Point d'entrée unique ────────────────────────────────────────────────────

def test_fit_prompt_borne_historique_et_sources_ensemble() -> None:
    """/answer et _build_messages doivent compter la même chose."""
    fit = fit_prompt("q", [_context("a", 20_000)], _historique(6, 4000))

    assert fit.dropped_history > 0
    assert sum(len(c.markdown) for c in fit.contexts) <= fit.budget_chars
    assert fit.budget_chars == context_budget_chars("q", fit.history, source_count=1)


def test_fit_prompt_sans_historique() -> None:
    fit = fit_prompt("q", [_context("a", 100)], None)

    assert fit.history == []
    assert fit.dropped_history == 0
    assert fit.dropped_contexts == 0


# ─── L'estimation confrontée à la mesure ──────────────────────────────────────

def test_estimate_prompt_tokens_compte_les_balises_de_tour() -> None:
    """Le gabarit de chat encadre chaque message : trois messages, trois tours.

    Même texte total, découpé autrement : c'est l'encadrement qui fait l'écart.
    """
    groupe = estimate_prompt_tokens([{"role": "system", "content": "abc" * 3}])
    eclate = estimate_prompt_tokens([{"role": "system", "content": "abc"}] * 3)

    assert eclate > groupe


def test_l_ecart_entre_estimation_et_reel_est_journalise(caplog) -> None:
    """`prompt_eval_count` était rendu par Ollama et lu par personne : le ratio
    caractères/token restait une devinette qu'aucune mesure ne corrigeait."""
    with caplog.at_level(logging.INFO, logger="src.agent.llm"):
        log_prompt_measure(1000, 1200)

    assert "estimé 1000" in caplog.text
    assert "réel 1200" in caplog.text
    assert "-16.7 %" in caplog.text


def test_un_prompt_hors_fenetre_leve_un_avertissement(caplog) -> None:
    """Aujourd'hui invisible : Ollama tronque par le DÉBUT sans rien dire."""
    with caplog.at_level(logging.INFO, logger="src.agent.llm"):
        log_prompt_measure(1000, settings.llm_num_ctx + 1)

    avertissements = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert len(avertissements) == 1
    assert "tronqué le prompt par le DÉBUT" in avertissements[0].getMessage()


def test_un_prompt_dans_la_fenetre_ne_leve_pas_d_avertissement(caplog) -> None:
    with caplog.at_level(logging.INFO, logger="src.agent.llm"):
        log_prompt_measure(1000, settings.llm_num_ctx - 1)

    assert [r for r in caplog.records if r.levelno >= logging.WARNING] == []


def test_sans_prompt_eval_count_rien_n_est_journalise(caplog) -> None:
    """Une version d'Ollama qui ne rend pas le champ ne doit pas faire de bruit."""
    with caplog.at_level(logging.INFO, logger="src.agent.llm"):
        log_prompt_measure(1000, None)

    assert caplog.records == []


def _flux_ollama(lignes: list[dict]):
    class Resp:
        def raise_for_status(self) -> None: ...

        async def aiter_lines(self):
            for ligne in lignes:
                yield json.dumps(ligne)

    class Stream:
        async def __aenter__(self):
            return Resp()

        async def __aexit__(self, *_):
            return False

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return False

        def stream(self, *_args, **_kwargs):
            return Stream()

    return lambda **_kwargs: Client()


@pytest.mark.asyncio
async def test_le_prompt_eval_count_est_lu_dans_l_evenement_final(monkeypatch, caplog) -> None:
    """Il n'arrive que sur l'événement `done: true` — celui dont la boucle
    sortait sans le lire."""
    monkeypatch.setattr(
        llm.httpx,
        "AsyncClient",
        _flux_ollama(
            [
                {"message": {"content": "Réponse."}},
                {"message": {"content": ""}, "done": True, "prompt_eval_count": 4321},
            ]
        ),
    )

    with caplog.at_level(logging.INFO, logger="src.agent.llm"):
        tokens = [t async for t in llm.generate_stream("q", [_context("a", 100)])]

    assert tokens == ["Réponse."]
    assert "réel 4321" in caplog.text
