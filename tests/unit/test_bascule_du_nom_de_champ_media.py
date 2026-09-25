"""Ce que coûterait, en silence, un champ média renommé par la source.

POURQUOI CES SCÈNES EXISTENT.

Ces trois scènes ne testent pas un bug : elles CLOUENT le comportement actuel.
`rag-ingestion-pipeline` va renommer le champ `minio_url` qu'il publie dans
NebulaGraph et dans les métadonnées ChromaDB. Le jour où il le fera, notre code
ne lèvera pas, ne journalisera rien, et rendra des réponses complètes — sans une
seule image. Le registre (`documentation/axes_amelioration.md` §4.62) mesure
pourquoi : NebulaGraph ne lève pas sur une propriété inconnue — un `RETURN` rend
`None`, un `WHERE` rend zéro ligne — et une métadonnée ChromaDB absente est un
`meta.get()` qui rend `None`. Les vingt-trois lignes de `tests/` qui nommaient
`minio_url` avant ce lot le POSAIENT toutes elles-mêmes dans des doubles :
aucune ne lisait une source, et la suite serait restée intégralement verte.

CE QUE CES SCÈNES SONT DEVENUES À LA BASCULE — LOT-42, §4.82 du registre. Le
code lit désormais `media_url`, `minio_url` à défaut, et `object_key`. Les
scènes ont été RETOURNÉES comme elles l'annonçaient, et non contournées :

- le nom qui ne produit aucune image n'est plus `media_url` — que nous lisons —
  mais un nom que le contrat ne porte PAS, `NOM_INCONNU`. Le constat reste le
  même, et il vaut pour la prochaine bascule : un nom renommé sans nous rend
  une réponse complète, sans image, sans un mot ;
- le contrôle positif porte sur CHACUN des noms du contrat, et non plus sur un
  seul : `media_url`, le repli `minio_url`, et `object_key` pour la liste
  blanche. Chacun de ces cas était ROUGE sur la base `b70ac8c`, qui ne lisait
  que `minio_url` ;
- `CONTRAT_DES_SOURCES`, dans `test_contrat_champs_externes.py`, reste le seul
  endroit où les noms sont écrits.

LE PRODUCTEUR EST DOUBLÉ, JAMAIS LE CONSOMMATEUR. Chaque scène remplace la
frontière — `_execute` pour le graphe, la collection pour ChromaDB — et laisse
tourner le vrai code en aval. Un test qui se contenterait de renommer le champ
dans son propre assert ne prouverait rien du tout.

CHAQUE CONSTAT À ZÉRO EST DOUBLÉ D'UN CONTRÔLE POSITIF. Un « zéro image » n'a de
valeur que si le même montage, avec le nom ATTENDU, en produit. Sans lui, un
montage cassé rendrait la scène verte pour une raison qui n'a rien à voir.
"""

from __future__ import annotations

import logging
from typing import Any

import pytest

from src.agent import graph as graph_module
from src.agent import graph_context, lexical, retriever
from src.api.schemas import SectionContext
from tests.unit.test_contrat_champs_externes import (
    CHAMP_CLE,
    CHAMP_URL,
    CHAMP_URL_DE_REPLI,
    CONTRAT_DES_SOURCES,
)

# Un nom de champ INCONNU de notre code : ce que serait une prochaine bascule
# faite sans nous. La scène resterait valable avec n'importe quel autre nom
# absent du contrat — la garde d'hygiène ci-dessous y veille.
NOM_INCONNU = "s3_url"

# Les noms d'URL au contrat, LUS depuis le site canonique et jamais recopiés :
# le nom d'après la bascule, puis son repli.
NOMS_URL = (CHAMP_URL, CHAMP_URL_DE_REPLI)
assert all(nom in CONTRAT_DES_SOURCES["graphe"] for nom in NOMS_URL)
assert all(nom in CONTRAT_DES_SOURCES["chromadb"] for nom in NOMS_URL)

_URL = "http://stockage-objet:9000/documents/images/rapport/aaaaaaaa01_picture.png"
_OBJET = "images/rapport/aaaaaaaa01_picture.png"


def test_le_nom_inconnu_est_bien_inconnu_du_contrat() -> None:
    """Garde d'hygiène : sans elle, ces scènes pourraient se vider d'elles-mêmes.

    Si le contrat se met à porter `NOM_INCONNU`, chaque « zéro image »
    ci-dessous mesurerait le contraire de son intention — en restant vert.
    Cette garde-ci rougit d'abord.
    """
    noms = {nom for noms_source in CONTRAT_DES_SOURCES.values() for nom in noms_source}
    assert NOM_INCONNU not in noms, (
        "Le nom « inconnu » est devenu un nom du contrat : choisissez-en un autre."
    )


# ─── B1 — media_object_names() : l'autorisation du proxy /media ───────────────
#
# C'est le site le plus coûteux des sept. `media_object_names()` est
# l'autorisation du proxy `/media` : avec `RESTRICT_MEDIA_TO_GRAPH` à `true` en
# service, un ensemble vide ne fait pas disparaître les images du champ perdu —
# il fait refuser TOUTES les images, y compris celles que rien n'a cassé.


def _double_execute(lignes: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Remplace la frontière du graphe et retient les requêtes qui la traversent.

    On rend les MÊMES lignes à toutes les requêtes : `media_object_names`
    interroge un tag après l'autre et la scène n'a pas à connaître cet ordre.
    """
    requetes: list[str] = []

    def _execute(nql: str) -> list[dict[str, Any]]:
        requetes.append(nql)
        return list(lignes)

    monkeypatch.setattr(graph_context, "_execute", _execute)
    return requetes


def test_b1_le_champ_renomme_vide_lautorisation_du_proxy(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Le graphe rend ses lignes, le champ y porte le nouveau nom → ensemble VIDE.

    C'est la forme la plus favorable à notre code : le graphe RÉPOND, les lignes
    ARRIVENT, et l'ensemble est vide quand même — parce que `media_object_names`
    lit l'alias `url` d'une propriété que la requête ne sait plus nommer.
    """
    _double_execute([{NOM_INCONNU: _URL}], monkeypatch)
    with caplog.at_level(logging.DEBUG):
        noms = graph_context.media_object_names()

    assert noms == set(), (
        "L'autorisation du proxy /media devrait être vide sous un champ renommé ; "
        f"obtenu : {sorted(noms)}."
    )
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING], (
        "Rien ne doit avoir été journalisé : c'est précisément ce qui rend la "
        "panne invisible, et c'est ce que cette scène cloue."
    )


def test_b1_bis_la_forme_reelle_du_where_donne_le_meme_vide(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """La forme FIDÈLE au comportement mesuré de NebulaGraph : zéro ligne.

    `mesuré` le 22 septembre 2026 contre le graphe en service (§4.62) : sur une
    propriété inconnue, un `WHERE` ne lève pas, il rend zéro ligne — contrôle
    positif de cette mesure, la vraie propriété rendait deux lignes. La scène
    précédente prend la forme la plus favorable, celle-ci la forme réelle ; les
    deux mènent au même vide, et c'est ce qui rend le constat robuste à ce que
    la passerelle fera exactement.
    """
    requetes = _double_execute([], monkeypatch)
    assert graph_context.media_object_names() == set()
    assert requetes, "le double n'a été traversé par aucune requête : montage faux"


@pytest.mark.parametrize(
    "ligne",
    [{CHAMP_URL: _URL}, {CHAMP_URL_DE_REPLI: _URL}, {CHAMP_CLE: _OBJET}],
    ids=[CHAMP_URL, CHAMP_URL_DE_REPLI, CHAMP_CLE],
)
def test_b1_controle_positif_chaque_champ_au_contrat_peuple_lautorisation(
    ligne: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """CONTRÔLE POSITIF — sans lui, les deux vides ci-dessus ne valent rien.

    Le même montage, un nom du contrat à la fois : le graphe rend la colonne
    de ce nom, et l'objet ressort. Les trois cas étaient ROUGES sur la base
    `b70ac8c` — qui lisait un alias `url` — et c'est l'accusé de réception de
    la bascule (§4.82).
    """
    requetes = _double_execute([ligne], monkeypatch)
    noms = graph_context.media_object_names()

    assert noms == {_OBJET}, f"le montage B1 ne produit plus d'objet : {sorted(noms)}"
    for nom in CONTRAT_DES_SOURCES["graphe"]:
        assert all(f".{nom}" in nql for nql in requetes), (
            f"une requête envoyée au graphe ne nomme pas « {nom} » : les "
            "scènes B1 ne mesurent plus le champ qu'elles croient."
        )


# ─── B2 — le chemin des images d'une réponse, du graphe à l'ImageRef ──────────
#
# La démonstration centrale : de la ligne nGQL jusqu'à la liste d'images, tout
# est du vrai code — `_get_children`, `_to_elements`, `_render_element`,
# `_build_markdown`, `resolve_citations`. Seule la frontière est doublée.

# VID de dix caractères hexadécimaux : la forme qu'exige `_VALID_VID`, et que
# `_ELEMENT_ID` retrouve dans les marqueurs. Un identifiant hors forme ferait
# échouer la scène pour une raison étrangère à son sujet.
_ID_SECTION = "5ec1104bcd"
_ID_TABLEAU = "aaaaaaaa01"
_ID_FIGURE = "bbbbbbbb02"


def _lignes_du_graphe(champ_media: str) -> list[dict[str, Any]]:
    """Les enfants d'une section tels que `_execute` les rend, champ média nommé.

    Le tableau garde son texte et son marqueur `[src:]` même privé d'illustration :
    c'est lui qui porte la citation, donc la section reste CITÉE et la voie qui
    attache les figures reste ouverte. Sans cela, la scène mesurerait une
    section jamais citée et le zéro image ne prouverait rien.
    """
    return [
        {
            "child_id": _ID_TABLEAU,
            "label": "table",
            "text": "Répartition des relevés par trimestre.",
            champ_media: _URL,
            "page_no": 12,
            "seq": 0,
        },
        {
            "child_id": _ID_FIGURE,
            "label": "picture",
            "text": "",
            champ_media: _URL.replace("aaaaaaaa01", "bbbbbbbb02"),
            "page_no": 12,
            "seq": 1,
        },
    ]


def _section_reconstruite(champ_media: str, monkeypatch: pytest.MonkeyPatch) -> SectionContext:
    """Reconstruit une section en partant du graphe, par le vrai code.

    `_get_children` fabrique la requête, `_to_elements` convertit les lignes,
    `_build_markdown` rend le texte qui partirait au modèle — marqueurs `[img:]`
    compris, ou non, selon ce que la conversion a su lire.
    """
    monkeypatch.setattr(
        graph_context, "_execute", lambda _nql: list(_lignes_du_graphe(champ_media))
    )
    lignes = graph_context._get_children(_ID_SECTION)
    elements = graph_context._to_elements(lignes)
    return SectionContext(
        element_id=_ID_TABLEAU,
        section_id=_ID_SECTION,
        breadcrumbs=[],
        elements=elements,
        markdown=graph_context._build_markdown([], elements, ""),
        filename="rapport.pdf",
        collection="Relevés trimestriels",
        section_title="Résultats",
    )


# Une réponse de modèle qui cite le tableau : la section est donc citée, et la
# voie qui attache les illustrations d'une section citée est ouverte.
_REPONSE = f"Les relevés progressent au dernier trimestre [src:{_ID_TABLEAU}]."


def test_b2_le_champ_renomme_ne_produit_aucune_image_et_ne_dit_rien(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """LA SCÈNE QUI REND LA PANNE VISIBLE : une réponse complète, sans image, sans un mot.

    La citation est résolue, la réponse est servie, le lecteur ne voit rien
    manquer — et aucune exception, aucun WARNING, aucune ligne de journal ne
    signale que les illustrations ont disparu. C'est la démonstration que rien
    ne rougit aujourd'hui, et c'est pour cela que cette scène existe.
    """
    contexte = _section_reconstruite(NOM_INCONNU, monkeypatch)

    with caplog.at_level(logging.DEBUG):
        citations, images = graph_module.resolve_citations(_REPONSE, [contexte], [])

    assert images == [], f"des images ont survécu au renommage : {images}"
    # Le chemin a FONCTIONNÉ — sans cette ligne, un zéro image pourrait venir
    # d'un montage mort plutôt que du champ perdu.
    assert [c.element_id for c in citations] == [_ID_TABLEAU], (
        "la citation n'est plus résolue : la scène ne mesure plus le chemin des images"
    )
    bruyants = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert not bruyants, (
        "Un journal est apparu là où la production est muette : "
        f"{[(r.levelname, r.getMessage()) for r in bruyants]}. Si c'est voulu, "
        "la panne n'est plus silencieuse — mettez le registre à jour."
    )


def test_b2_bis_le_marqueur_image_disparait_aussi_du_texte_soumis(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """La perte commence AVANT le post-traitement : le modèle ne voit plus la figure.

    `_render_element` n'émet `[img:ID]` que si l'élément porte une URL, et rend
    la chaîne VIDE pour une figure qui n'en a pas. Sous le champ renommé, la
    figure n'est donc pas seulement absente de la réponse : elle n'a jamais été
    proposée au modèle. Cloué ici parce que c'est ce qui rend la voie 1 — le
    `[img:]` émis par le modèle — inatteignable elle aussi.
    """
    renomme = _section_reconstruite(NOM_INCONNU, monkeypatch)
    assert "[img:" not in renomme.markdown
    assert f"[src:{_ID_TABLEAU}]" in renomme.markdown, "le montage ne soumet plus rien"


@pytest.mark.parametrize("nom", NOMS_URL)
def test_b2_controle_positif_chaque_nom_d_url_au_contrat_produit_les_images(
    nom: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CONTRÔLE POSITIF — le même chemin, chaque nom du contrat, des images.

    Il borne les constats à zéro ci-dessus : sans lui, un `SectionContext`
    mal monté ou une citation non résolue les rendrait verts sans rien mesurer.
    Le cas `media_url` était ROUGE sur la base `b70ac8c` (§4.82).
    """
    contexte = _section_reconstruite(nom, monkeypatch)
    assert "[img:" in contexte.markdown, "le montage B2 ne soumet plus d'illustration"

    _citations, images = graph_module.resolve_citations(_REPONSE, [contexte], [])

    assert [i.element_id for i in images] == [_ID_TABLEAU, _ID_FIGURE], (
        f"le montage B2 ne produit plus les images attendues : {images}"
    )
    assert images[0].minio_url == f"/media/{_OBJET}", (
        "l'URL n'est plus réécrite vers le proxy : le montage a changé de sujet"
    )


# ─── B3 — ChromaDB : les deux chemins de recherche ────────────────────────────


def _metadonnees(champ_media: str) -> dict[str, Any]:
    """Les métadonnées d'un chunk telles que ChromaDB les rend."""
    return {
        "element_id": _ID_TABLEAU,
        "graph_node_id": _ID_TABLEAU,
        "filename": "rapport.pdf",
        "collection": "Relevés trimestriels",
        "source_path": "htms/Relevés trimestriels/rapport.html",
        "section_title": "Résultats",
        "language": "fr",
        "depth": 2,
        "page_no": 12,
        "label": "table",
        champ_media: _URL,
        "page_position": 3,
        "ref_position": 1,
    }


@pytest.mark.parametrize(
    ("champ", "attendu"),
    [(NOM_INCONNU, None), (CHAMP_URL, _URL), (CHAMP_URL_DE_REPLI, _URL)],
    ids=["nom-inconnu", f"controle-positif-{CHAMP_URL}", f"controle-positif-{CHAMP_URL_DE_REPLI}"],
)
def test_b3_lexical_le_champ_renomme_donne_none_sans_lever(
    champ: str, attendu: str | None, caplog: pytest.LogCaptureFixture
) -> None:
    """Le chemin lexical : `minio_url` vaut None, et rien ne le dit.

    Les deux cas sont dans la même scène et sur le même montage : le contrôle
    positif ne peut donc pas diverger du cas mesuré par accident de montage.
    """
    with caplog.at_level(logging.DEBUG):
        chunk = lexical.chunk_from_record(f"{_ID_TABLEAU}_part0", "Le texte.", _metadonnees(champ))

    assert chunk.minio_url == attendu
    # Le reste du chunk est intact : la perte est SILENCIEUSE et LOCALE, ce qui
    # est exactement ce qui la rend indétectable en aval.
    assert chunk.element_id == _ID_TABLEAU
    assert chunk.section_title == "Résultats"
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]


@pytest.mark.parametrize(
    ("champ", "attendu"),
    [(NOM_INCONNU, None), (CHAMP_URL, _URL), (CHAMP_URL_DE_REPLI, _URL)],
    ids=["nom-inconnu", f"controle-positif-{CHAMP_URL}", f"controle-positif-{CHAMP_URL_DE_REPLI}"],
)
def test_b3_dense_le_champ_renomme_donne_none_sans_lever(
    champ: str,
    attendu: str | None,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Le chemin dense : la collection est doublée, `_dense_search` est le vrai code.

    Le producteur doublé est bien la COLLECTION — c'est elle qui publie les
    métadonnées — et non la fonction qui les lit. Le modèle d'embedding et le
    garde de concordance sont neutralisés parce qu'ils ne sont pas le sujet :
    ils ont leurs propres scènes ailleurs.
    """

    class _Embedder:
        def __init__(self, *_args: Any, **_kwargs: Any) -> None:
            self.device = None

        def encode(self, _question: str) -> Any:
            import numpy

            return numpy.zeros(3)

    class _Collection:
        def query(self, **_kwargs: Any) -> dict[str, Any]:
            return {
                "ids": [[f"{_ID_TABLEAU}_part0"]],
                "documents": [["Le texte."]],
                "metadatas": [[_metadonnees(champ)]],
                "distances": [[0.17]],
            }

    monkeypatch.setattr(retriever, "SentenceTransformer", _Embedder)
    monkeypatch.setattr(retriever, "verifier_modele_embedding", lambda: None)
    monkeypatch.setattr(retriever, "_get_chroma_collection", lambda: _Collection())
    retriever._get_embedding_model.cache_clear()

    try:
        with caplog.at_level(logging.DEBUG):
            chunks = retriever._dense_search("les relevés du trimestre", 5)
    finally:
        retriever._get_embedding_model.cache_clear()

    assert len(chunks) == 1, "le montage dense ne rend plus de chunk : scène morte"
    assert chunks[0].minio_url == attendu
    assert chunks[0].element_id == _ID_TABLEAU
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]
