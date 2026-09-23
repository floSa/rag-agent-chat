"""Ce que le montage des tests UNITAIRES garantit par construction.

Ce fichier est délibérément séparé de `tests/conftest.py` : ses garanties ne
valent que pour `tests/unit/`. `tests/integration/` ouvre de VRAIES connexions,
c'est sa raison d'être, et une barrière posée à la racine l'aurait cassé.
"""

import threading

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


# ─── LE DRAPEAU « EN VOL », ET LE FIL QU'UN TEST LAISSE DERRIÈRE LUI ──────────
#
# CE QUE CETTE BARRIÈRE REMPLACE, et c'est `mesuré` : le 23 septembre 2026 la CI
# rougissait sur `test_le_drapeau_est_retire_quand_le_store_rend_la_main` —
# `assert 'modele_embedding' in set()` — alors que le MÊME commit rendait 1124
# verts sur le poste, et le test seul 20 fois d'affilée. Le code n'y était pour
# rien : la course était dans le montage des tests.
#
# LE MÉCANISME, ÉTABLI PAR UN MOUCHARD POSÉ SUR L'ENSEMBLE LUI-MÊME, et non
# déduit. `_sonder` POSE le drapeau côté boucle ; `_executer_sonde` le RETIRE
# côté fil, dans son `finally`, ET IL LE RETIRE PAR NOM. Un test qui abandonne
# sa sonde au plafond laisse donc derrière lui un fil VIVANT qui retirera ce nom
# plus tard — après la fin du test, et après que le test SUIVANT a posé le même
# nom. Relevé du mouchard, les deux tests s'enchaînant :
#
#   POSE   modele_embedding par fil=…169984              (la boucle, test N)
#   ENTREE lecture rang=1   par fil=…835200              (le fil, test N)
#   POSE   modele_embedding par fil=…169984              (la boucle, test N+1)
#   ENTREE lecture rang=2   par fil=…442496              (le fil, test N+1)
#   RETIRE modele_embedding par fil=…835200 present=True ← le fil du test N
#
# CE N'EST DONC PAS « le drapeau n'est pas encore posé ». Il l'est, et le
# mouchard le montre posé par la BOUCLE, conformément à ce que `_sondes_en_vol`
# écrit. C'est « il a DÉJÀ été retiré », par un fil à qui il n'appartient plus.
#
# VIDER L'ENSEMBLE ENTRE DEUX TESTS N'Y SUFFISAIT PAS, ET L'AGGRAVAIT : le
# `clear()` ORPHELINE le fil encore vivant, qui garde le droit de retirer un nom
# qu'il ne détient plus. La seule fermeture est d'ATTENDRE son dernier geste
# avant de rendre la main au test suivant.
#
# ET ON L'ATTEND, ON NE LE SONDE PAS À L'HORLOGE : l'ensemble est rendu
# OBSERVABLE, et c'est le fil lui-même qui réveille la barrière en retirant son
# drapeau. Un `sleep` plus long serait la même course avec une marge — et la
# marge d'un poste n'est pas celle de la CI, ce qui est exactement l'écart dans
# lequel ce défaut vivait.
#
# LA FORME EST CELLE-CI, ET PAS UN BRANCHEMENT PAR FICHIER, pour le motif déjà
# écrit plus haut : un branchement ne couvre que les tests déjà écrits, et deux
# modules lancent déjà des sondes — `test_garde_modele_embedding.py` et
# `test_health_parallele.py`, qui partagent cet état de module sans s'importer.
#
# Garde : `tests/unit/test_montage_des_tests.py`, dans les DEUX directions.


class DrapeauxDesSondes(set):
    """`main._sondes_en_vol`, rendu OBSERVABLE pour qu'on puisse l'ATTENDRE.

    Le dernier geste d'un fil de sonde est `discard(nom)`. En faire une mutation
    observable, c'est se donner le droit d'attendre CE geste au lieu de lui
    accorder un délai — et donc de ne rien devoir à la vitesse de la machine.
    """

    def __init__(self, *args) -> None:
        super().__init__(*args)
        self._mutation = threading.Condition()

    def add(self, element):
        with self._mutation:
            super().add(element)
            self._mutation.notify_all()

    def discard(self, element):
        with self._mutation:
            super().discard(element)
            self._mutation.notify_all()

    def clear(self):
        with self._mutation:
            super().clear()
            self._mutation.notify_all()

    def attendre_le_vide(self, plafond: float) -> bool:
        """Rend la main dès qu'aucune sonde n'est plus en vol. `False` au plafond.

        Le plafond n'est pas une marge dont dépend le résultat : c'est le filet
        qui transforme un fil qui ne revient JAMAIS en rouge nommé, au lieu d'une
        suite qui se fige.
        """
        with self._mutation:
            return self._mutation.wait_for(lambda: not self, timeout=plafond)


# Le filet, et rien d'autre. En marche normale la barrière est réveillée par le
# fil dans la microseconde qui suit sa libération ; ce chiffre n'est atteint que
# par un test qui abandonne une sonde SANS jamais la débloquer, et il vaut alors
# un rouge qui le nomme.
_PLAFOND_DE_LA_BARRIERE_S = 10.0


@pytest.fixture(autouse=True)
def _aucune_sonde_en_vol_ne_franchit_la_fin_d_un_test():
    """Aucun fil de sonde ne survit au test qui l'a lancé."""
    from src.api import main

    ancien = main._sondes_en_vol
    drapeaux = DrapeauxDesSondes()
    main._sondes_en_vol = drapeaux
    try:
        yield
    finally:
        # La barrière tourne AUSSI quand le test a rougi — c'est le test SUIVANT
        # qu'elle protège, et il n'a pas à payer l'échec de celui-ci. Mais elle
        # ne se PLAINT que si le test avait par ailleurs réussi : deux rouges
        # pour une cause égarent.
        revenues = drapeaux.attendre_le_vide(_PLAFOND_DE_LA_BARRIERE_S)
        restantes = sorted(drapeaux)
        main._sondes_en_vol = ancien
        ancien.clear()
    assert revenues, (
        f"ce test rend la main en laissant {len(restantes)} sonde(s) EN VOL "
        f"— {restantes} — après {_PLAFOND_DE_LA_BARRIERE_S} s. Le fil de cette "
        "sonde est vivant, et son `finally` retirera ce nom PLUS TARD : il "
        "effacera le drapeau que le test suivant aura posé, et c'est un rouge "
        "qui ne tombera que sur une machine plus lente que celle-ci. Débloque "
        "ce que la sonde attend avant de sortir du test"
    )
