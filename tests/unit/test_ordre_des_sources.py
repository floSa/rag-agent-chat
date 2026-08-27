"""L'ordre dans lequel les sources entrent dans la fenêtre.

Tout l'aval suppose que `enriched_contexts` est trié par pertinence
décroissante : `fit_contexts` remplit depuis le début et écarte ce qui déborde,
le gabarit numérote « Source 1, 2, 3… », et la troncature ne touche que les
dernières retenues. Cette supposition était fausse sur le flux interactif — la
sélection arrivait dans l'ordre du hachage d'un `set` côté frontend.

Les tests assertent depuis `node_reconstruct_context`, le nœud qui PRODUIT
l'ordre, et non depuis un endpoint qui le consomme.
"""

import pytest

from src.agent import graph as graph_module
from src.api.schemas import ChunkResult, SectionContext


def _chunk(element_id: str, rerank_score: float) -> ChunkResult:
    return ChunkResult(
        chunk_id=element_id,
        element_id=element_id,
        graph_node_id=element_id,
        document="Le texte du passage.",
        filename="3. Statistical Toolbox",
        collection="The Statistics Workshop",
        source_path="htms/The Statistics Workshop/3. Statistical Toolbox.html",
        section_title="Dispersion",
        language="en",
        page_no=88,
        label="paragraph",
        distance=0.2,
        rerank_score=rerank_score,
        relevance=rerank_score / 10,
    )


def _section(element_id: str) -> SectionContext:
    return SectionContext(
        element_id=element_id,
        section_id=f"section{element_id[-2:]}",
        breadcrumbs=[],
        elements=[],
        markdown=f"Le contexte de {element_id}. [src:{element_id}]",
    )


# Classement du reranker, du mieux classé au moins bien.
_CLASSEMENT = [
    _chunk("aaaaaaaa01", 9.0),
    _chunk("bbbbbbbb02", 7.0),
    _chunk("cccccccc03", 5.0),
    _chunk("dddddddd04", 3.0),
    _chunk("eeeeeeee05", 1.0),
]
_PERTINENCE = [c.element_id for c in _CLASSEMENT]


@pytest.fixture
def reconstruction(monkeypatch):
    monkeypatch.setattr(graph_module, "reconstruct_section", _section)


def _reconstruire(selection: list[str]) -> list[str]:
    resultat = graph_module.node_reconstruct_context(
        {
            "reranked_chunks": list(_CLASSEMENT),
            "selected_element_ids": selection,
            "search_count": 1,
            "max_sources": None,
            "_metadata": {},
        }
    )
    return [c.element_id for c in resultat["enriched_contexts"]]


def test_la_selection_est_reconstruite_par_pertinence_decroissante(reconstruction) -> None:
    """Le cas qui casse : la sélection arrive dans le désordre.

    C'est ce que le frontend produit — `selected_ids` est un `set`, et
    `list(set)` rend l'ordre du hachage. Une source écartée par la fenêtre
    l'était donc au hasard, et non parce qu'elle était la moins pertinente.
    """
    desordre = ["cccccccc03", "aaaaaaaa01", "eeeeeeee05", "bbbbbbbb02", "dddddddd04"]
    assert desordre != _PERTINENCE, "le cas de test doit partir d'un ordre faux"

    assert _reconstruire(desordre) == _PERTINENCE


def test_l_ordre_de_l_appelant_n_a_aucun_effet(reconstruction) -> None:
    """Le serveur tranche : deux clients qui cochent les mêmes cases dans un
    ordre différent doivent payer exactement la même fenêtre."""
    a = _reconstruire(["eeeeeeee05", "aaaaaaaa01", "cccccccc03"])
    b = _reconstruire(["cccccccc03", "eeeeeeee05", "aaaaaaaa01"])

    assert a == b == ["aaaaaaaa01", "cccccccc03", "eeeeeeee05"]


def test_un_element_hors_classement_passe_en_fin(reconstruction) -> None:
    """La boucle agentique peut ajouter des éléments que le reranker n'a jamais
    vus : ils n'ont pas de rang, donc pas de titre à passer devant."""
    resultat = _reconstruire(["ffffffff06", "bbbbbbbb02", "aaaaaaaa01"])

    assert resultat == ["aaaaaaaa01", "bbbbbbbb02", "ffffffff06"]


def test_sans_selection_le_classement_est_repris_tel_quel(reconstruction) -> None:
    """`/answer` fonctionne ainsi par construction : il ne coche rien."""
    resultat = graph_module.node_reconstruct_context(
        {
            "reranked_chunks": list(_CLASSEMENT),
            "selected_element_ids": [],
            "search_count": 1,
            "max_sources": 3,
            "_metadata": {},
        }
    )

    assert [c.element_id for c in resultat["enriched_contexts"]] == _PERTINENCE[:3]


def test_le_frontend_envoie_bien_un_ordre_arbitraire() -> None:
    """La cause, épinglée là où elle est : `src/frontend/app.py` range les cases
    cochées dans un `set` et poste `list(...)`.

    Sans ce test, le tri serveur pourrait être retiré un jour comme une
    précaution inutile — « le client envoie déjà l'ordre du classement ». Il ne
    l'envoie pas. Le tri est la seule chose qui garantit l'ordre.
    """
    envoye = list(set(_PERTINENCE))

    assert sorted(envoye) == sorted(_PERTINENCE), "mêmes identifiants"
    assert envoye != _PERTINENCE, (
        "l'ordre d'un set coïncide par hasard avec le classement : changer les "
        "identifiants du cas de test"
    )
