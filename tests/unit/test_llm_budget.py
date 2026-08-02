"""Budget de contexte : ce qui ne tient pas dans la fenêtre du modèle doit être
écarté ici, explicitement — sinon Ollama tronque en silence, et par le DÉBUT du
prompt, donc en jetant les sources les mieux classées."""

from src.agent.llm import context_budget_chars, fit_contexts
from src.api.schemas import SectionContext


def _context(element_id: str, taille: int) -> SectionContext:
    return SectionContext(
        element_id=element_id,
        section_id=element_id,
        breadcrumbs=[],
        elements=[],
        markdown="x" * taille,
    )


def test_budget_deduit_la_generation_de_la_fenetre() -> None:
    """num_ctx est partagé : ce qui est réservé à num_predict n'est pas du contexte."""
    assert context_budget_chars() > 0


def test_toutes_les_sources_passent_si_le_budget_suffit() -> None:
    contexts = [_context("a", 100), _context("b", 100)]
    kept, dropped = fit_contexts(contexts, budget_chars=1000)

    assert len(kept) == 2  # noqa: PLR2004
    assert dropped == 0


def test_la_queue_saute_quand_le_budget_est_depasse() -> None:
    """Les sources sont ordonnées par pertinence : on garde les premières."""
    contexts = [_context("a", 400), _context("b", 400), _context("c", 400)]
    kept, dropped = fit_contexts(contexts, budget_chars=900)

    assert [c.element_id for c in kept] == ["a", "b"]
    assert dropped == 1


def test_la_meilleure_source_est_gardee_meme_seule_trop_grosse() -> None:
    """Mieux vaut une source tronquée par Ollama que zéro source."""
    kept, dropped = fit_contexts([_context("a", 10_000)], budget_chars=100)

    assert [c.element_id for c in kept] == ["a"]
    assert dropped == 0


def test_sans_source() -> None:
    assert fit_contexts([], budget_chars=1000) == ([], 0)
