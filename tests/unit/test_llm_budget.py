"""Budget de contexte : ce qui ne tient pas dans la fenêtre du modèle doit être
écarté ici, explicitement — sinon Ollama tronque en silence, et par le DÉBUT du
prompt, donc en jetant les sources les mieux classées."""

from src.agent.llm import _TRUNCATION_MARKER, context_budget_chars, fit_contexts
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
    """IMP-6 : elle était transmise entière, et Ollama coupait — par le DÉBUT.

    Le choix de garder la meilleure source coûte que coûte est assumé : mieux
    vaut une source amputée que zéro source. Mais la transmettre entière rendait
    la main à Ollama, c'est-à-dire au mode de panne que `fit_contexts` existe
    pour éviter. La coupe se fait ici, par la fin, et elle se voit.
    """
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
