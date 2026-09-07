"""Les garanties que le montage des tests apporte, gardées comme du code.

Une fixture `autouse` est une décision invisible : elle s'applique à tout et
n'est nommée nulle part dans les tests qu'elle protège. Deux d'entre elles ont
été mesurées INERTES ou NON GARDÉES sur ce dépôt — retirées, la suite restait
verte — et une décision argumentée que rien ne fait rougir est une décision qui
se défera sans avertissement. Ce fichier est leur rouge.
"""

import chromadb
import pytest

from src.agent import retriever
from src.agent.settings import settings
from tests.unit.conftest import ConnexionChromaInterditeError

# ─── La barrière réseau ───────────────────────────────────────────────────────

def test_ouvrir_une_vraie_connexion_chromadb_leve_en_test_unitaire() -> None:
    """La barrière de `tests/unit/conftest.py` doit MORDRE.

    Asserté depuis le côté qui produit la garantie — l'appel réel à
    `chromadb.HttpClient` — et non depuis l'existence de la fixture, qu'on peut
    laisser en place et vider de tout effet.
    """
    with pytest.raises(ConnexionChromaInterditeError) as leve:
        chromadb.HttpClient(host="chromadb", port=8000)

    # Le message doit nommer le GESTE, pas seulement le refus : c'est ce qui
    # distingue une barrière d'un mur.
    assert "tests/integration/" in str(leve.value)


def test_la_lecture_de_l_estampille_ne_sort_pas_sur_le_reseau(monkeypatch) -> None:
    """Le chemin qui produisait les 48 tentatives, pris depuis son entrée.

    `_lire_estampille` est le seul appelant mesuré ; ce test le prend sans rien
    brancher, exactement comme le faisaient les 41 tests concernés, et exige que
    la barrière l'arrête au lieu du réseau.
    """
    retriever._get_chroma_collection.cache_clear()
    monkeypatch.setattr(settings, "chroma_host", "chromadb")

    with pytest.raises(ConnexionChromaInterditeError):
        retriever._lire_estampille()

    retriever._get_chroma_collection.cache_clear()


def test_une_estampille_hors_reseau_se_publie_en_unknown(monkeypatch) -> None:
    """Et le témoin : la barrière ne doit pas transformer ce cas en panne.

    `etat_modele_embedding` absorbe l'illisible et le publie `unknown`. C'est
    l'état sous lequel tournent les tests qui ne branchent pas de collection —
    prévu et documenté, là où l'échec de résolution DNS ne l'était pas.
    """
    retriever._get_chroma_collection.cache_clear()
    monkeypatch.setattr(settings, "chroma_host", "chromadb")

    etat = retriever.etat_modele_embedding()

    retriever._get_chroma_collection.cache_clear()
    assert etat.status == "unknown"
    assert etat.collection is None


# ─── Le verdict de concordance ne se transmet pas d'un test à l'autre ────────
#
# LA FIXTURE GARDÉE ICI est `_verdict_du_modele_embedding_neuf`, dans
# `tests/conftest.py`. Elle a été mesurée INERTE — retirée, 539 verts, `rc=0` —
# et son motif est pourtant juste : `retriever` mémoïse la concordance dans un
# état de MODULE, donc un test qui l'établit rendrait verts tous ceux qui suivent
# sans qu'aucun garde ne regarde quoi que ce soit. C'est le faux vert exact qu'un
# garde décoratif produirait.
#
# LES DEUX TESTS CI-DESSOUS SONT ORDONNÉS, et c'est leur mécanisme : pytest
# exécute les tests d'un module dans leur ordre de déclaration. Le premier
# ÉTABLIT le verdict, le second exige de ne pas en hériter. Sans la fixture, le
# second rougit. Les renommer ou les réordonner casse le garde : c'est écrit ici
# pour que personne ne le fasse sans le savoir.

def test_a_ce_test_etablit_le_verdict_de_concordance(monkeypatch) -> None:
    """Premier des deux : il laisse derrière lui un verdict favorable établi."""

    def _ouvrir():
        class _Collection:
            metadata = {"embedding_model": settings.embedding_model_name}

        return _Collection()

    _ouvrir.cache_clear = lambda: None
    monkeypatch.setattr(retriever, "_get_chroma_collection", _ouvrir)

    retriever.verifier_modele_embedding()

    assert retriever._concordance_etablie is True, (
        "ce test doit VRAIMENT établir le verdict, sinon le suivant ne mesure rien"
    )


def test_b_le_verdict_du_test_precedent_n_est_pas_herite() -> None:
    """Second des deux : le verdict établi juste avant ne doit pas subsister.

    Ce test ne branche rien et n'a pas à le faire — c'est précisément un test
    qui ne s'occupe pas de la concordance, la population que la fixture protège.
    """
    assert retriever._concordance_etablie is False, (
        "le verdict de concordance a survécu au test précédent : la fixture "
        "`_verdict_du_modele_embedding_neuf` de tests/conftest.py ne réarme plus, "
        "et tout test suivant est vert sans qu'un garde regarde quoi que ce soit"
    )
