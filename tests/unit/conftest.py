"""Ce que le montage des tests UNITAIRES garantit par construction.

Ce fichier est délibérément séparé de `tests/conftest.py` : ses garanties ne
valent que pour `tests/unit/`. `tests/integration/` ouvre de VRAIES connexions,
c'est sa raison d'être, et une barrière posée à la racine l'aurait cassé.
"""

import chromadb
import pytest


class ConnexionChromaInterditeError(RuntimeError):
    """Un test unitaire a tenté d'ouvrir une vraie connexion ChromaDB."""


@pytest.fixture(autouse=True)
def _aucune_vraie_connexion_chromadb(monkeypatch) -> None:
    """Aucun test unitaire n'ouvre de connexion réseau vers ChromaDB.

    CE QUE CETTE BARRIÈRE REMPLACE, et c'est `mesuré` : 41 tests ouvraient une
    vraie connexion `chromadb` — 48 tentatives, contre 0 avant ce lot — toutes
    depuis `_lire_estampille`, appelée par la sonde de concordance de `/health`.
    Elles restaient vertes et rapides pour une seule raison : l'hôte `chromadb`
    ne se résout pas depuis un poste de développement. *Le montage tenait par
    absorption, pas par construction.* Le jour où ce nom se résout — tests
    lancés dans le réseau Docker, entrée dans `/etc/hosts` — ces 48 tentatives
    deviennent 48 allers-retours réseau, et une sonde qui ne revient pas coûte
    le plafond de `/health` à chaque fois. C'est la même classe de défaut que
    celui refermé en `ba81bf0` : un test qui ne tient que par un échec de
    résolution DNS.

    LA FORME EST CELLE-CI ET PAS UN BRANCHEMENT PAR FICHIER, parce qu'un
    branchement ne couvre que les tests déjà écrits. Ce qu'on veut interdire est
    la PROCHAINE fois : la barrière lève avec un message qui nomme le geste,
    plutôt que de laisser un test dépendre du réseau du poste qui l'exécute.

    Ce qu'elle NE fait pas : décider de la concordance. Un test qui a besoin
    d'une collection branche `retriever._get_chroma_collection` et n'atteint
    jamais cette barrière ; un test qui ne la branche pas obtient une estampille
    illisible, ce que `etat_modele_embedding` publie en `unknown` — un état
    prévu, documenté et gardé, et non un accident de résolution de nom.

    Garde : `tests/unit/test_montage_des_tests.py`.
    """

    def _interdit(*_args, **_kwargs):
        raise ConnexionChromaInterditeError(
            "un test unitaire a tenté d'ouvrir une vraie connexion ChromaDB. Un "
            "test qui dépend du réseau du poste qui l'exécute n'est pas un test "
            "unitaire : branche `retriever._get_chroma_collection` sur une "
            "collection de test — cf. `_brancher_collection` dans "
            "tests/unit/test_garde_modele_embedding.py — ou, si c'est bien une "
            "vraie connexion que tu veux, écris ce test dans tests/integration/."
        )

    monkeypatch.setattr(chromadb, "HttpClient", _interdit)
