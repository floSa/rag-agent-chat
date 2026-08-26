"""Deux endroits qui doivent s'accorder, et que rien ne forçait à s'accorder.

Ces vérifications ne testent pas de la logique : elles empêchent une divergence
silencieuse entre deux fichiers dont un seul est lu à l'exécution. Les deux cas
présents ont réellement divergé.
"""

import importlib.util
from pathlib import Path

from src.agent.chronometrie import ETAGES
from src.api.schemas import MAX_HISTORY_MESSAGES, StageTimings

_RACINE = Path(__file__).resolve().parents[2]


def test_le_frontend_ne_derive_pas_de_la_borne_du_schema() -> None:
    """`src/frontend/app.py` duplique la constante : l'image du frontend ne
    contient que `src/frontend` et ne peut pas importer les schémas.

    Sans ce garde-fou, les deux valeurs divergent en silence — et le frontend
    enverrait soit plus que ce que l'API lit, soit moins qu'elle accepte.
    """
    from src.frontend import app

    assert app.MAX_HISTORY_MESSAGES == MAX_HISTORY_MESSAGES


def test_l_image_du_frontend_suit_les_versions_declarees() -> None:
    """`Dockerfile.frontend` réinstalle ses dépendances à la main, sans lire
    requirements.txt : l'image tournait sur streamlit 1.44.1 et pydantic 2.11.4
    quand le dépôt déclarait tester 1.60.0 et 2.13.4.

    Une divergence entre l'image et les versions déclarées est le vieillissement
    silencieux que décrit documentation/SECURITY.md — que rien ne signalait ici.
    """
    dockerfile = (_RACINE / "Dockerfile.frontend").read_text(encoding="utf-8")
    declarees = dict(
        ligne.split("==", 1)
        for ligne in (_RACINE / "requirements.txt").read_text(encoding="utf-8").splitlines()
        if "==" in ligne and not ligne.startswith("#")
    )

    for paquet in ("streamlit", "httpx", "pydantic"):
        assert f"{paquet}=={declarees[paquet]}" in dockerfile, (
            f"Dockerfile.frontend n'epingle pas {paquet}=={declarees[paquet]}"
        )


def test_la_campagne_connait_exactement_les_etages_de_la_partition() -> None:
    """`scripts/evaluate.py` recopie la liste des étages au lieu de l'importer.

    Le choix est délibéré et documenté au site : le script interroge un service
    DISTANT, dont la version peut différer de celle du dépôt — un étage absent de
    la réponse doit valoir zéro, pas casser la campagne. Mais recopier crée
    exactement la divergence que ce fichier existe pour empêcher : un étage
    ajouté à `chronometrie.ETAGES` et oublié dans le script serait mesuré sans
    être jamais publié, et la table de latence s'afficherait complète.

    L'accord porte sur les étages plus `residual_ms` et `total_ms`, que le script
    enregistre au même titre — sans le résidu, la partition ne se vérifie pas.
    """
    chemin = _RACINE / "scripts" / "evaluate.py"
    spec = importlib.util.spec_from_file_location("evaluate", chemin)
    assert spec and spec.loader
    evaluate = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(evaluate)

    assert set(evaluate.ETAGES) == set(StageTimings.model_fields)
    assert set(evaluate.ETAGES) == set(ETAGES) | {"residual_ms", "total_ms"}
