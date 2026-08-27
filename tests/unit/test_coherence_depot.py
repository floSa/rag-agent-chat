"""Deux endroits qui doivent s'accorder, et que rien ne forçait à s'accorder.

Ces vérifications ne testent pas de la logique : elles empêchent une divergence
silencieuse entre deux fichiers dont un seul est lu à l'exécution. Tous les cas
présents ont réellement divergé — y compris le dernier, qui ne porte pas sur une
constante mais sur une **mesure** recopiée à trois endroits.
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


# La même mesure vit dans un docstring de code et dans deux documents. Les
# laisser dériver a produit TROIS triplets pour une seule grille : 1 083 / 4 106
# dans `llm.py`, 1 172 / 3 964 dans les deux documents, et un troisième au rejeu
# du protocole publié. Le site canonique est le registre, §1.30.
_MESURE_DU_REMPLISSAGE = (
    "1 355 caractères de fenêtre inutilisés en moyenne et 7 970 au maximum sur "
    "88 configurations, ramenés à 408 en moyenne — 70 % de la marge reprise, "
    "38 configurations gagnées et aucune perdue"
)

_PORTEURS_DE_LA_MESURE = (
    Path("src") / "agent" / "llm.py",
    Path("documentation") / "llm.md",
    Path("documentation") / "axes_amelioration.md",
)


def test_la_mesure_du_remplissage_est_la_meme_aux_trois_endroits() -> None:
    """Trois copies d'un même chiffre mesuré, et rien ne les forçait à s'accorder.

    Le rapprochement se fait sur le texte à espaces normalisés : le docstring de
    `fit_contexts` et les deux documents ne coupent pas leurs lignes aux mêmes
    endroits, et exiger le même retour à la ligne ferait rougir ce test sur une
    reformulation innocente. Ce qui est gardé, c'est la phrase, pas sa mise en
    page.

    Remesurer, c'est éditer les trois — et c'est voulu : le protocole qui produit
    ces chiffres est publié dans `llm.md`, il tourne à sec, et sa sortie est
    recopiée telle quelle.
    """
    attendu = " ".join(_MESURE_DU_REMPLISSAGE.split())

    for relatif in _PORTEURS_DE_LA_MESURE:
        texte = " ".join((_RACINE / relatif).read_text(encoding="utf-8").split())
        assert texte.count(attendu) == 1, (
            f"{relatif} ne porte pas exactement une fois la mesure du remplissage — "
            "remesurer avec le protocole de documentation/llm.md et recopier sa "
            "sortie aux trois endroits"
        )
