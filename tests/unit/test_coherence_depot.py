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


# ─── Le nom du modèle anglais, et où il a le droit de vivre ───────────────────

# Inventaire des documents qui portent encore `all-MiniLM-L6-v2`, avec le nombre
# d'occurrences et le MOTIF qui l'autorise. Ce nom est celui de l'autre candidat
# d'embedding : il rend des vecteurs de la même largeur que celui en service
# (384, `mesuré` — site canonique `documentation/axes_amelioration.md` §4.4),
# donc une conversation d'ingestion qui le recopierait produirait un index que
# l'agent refuse — et, avant le lot 3, une recherche silencieusement fausse.
#
# CE QUE CE TEST REMPLACE. `pour_le_pipeline_ingestion.md` affirmait que « toutes
# les mentions ont été corrigées ». C'était faux : sept vivaient dans
# `llm_integration_plan.md`, dont une ligne de `.env` d'apparence exécutable.
# Une affirmation de cette forme — « toutes », « aucune », « il n'y a plus » —
# survit indéfiniment quand elle est fausse, contrairement à un bug. Celle-ci est
# désormais un compte, et le compte rougit.
_VESTIGES_AUTORISES = {
    # Document historique, dont le bandeau de tête nomme explicitement cet écart
    # comme le plus dangereux du fichier.
    "documentation/llm_integration_plan.md": 7,
    # Décrit le vestige au lieu de le prescrire.
    "documentation/pour_le_pipeline_ingestion.md": 1,
    # Le §3.2 raconte la correction, le §4.4 nomme les deux candidats et publie
    # la mesure de leur largeur commune.
    "documentation/axes_amelioration.md": 3,
    # Dit que ce document l'a annoncé et que c'était faux.
    "documentation/agent_architecture.md": 1,
}

_MODELE_ANGLAIS = "all-MiniLM-L6-v2"


def test_le_nom_du_modele_anglais_ne_vit_que_la_ou_il_est_justifie() -> None:
    """Un inventaire qui rougit, plutôt qu'une phrase qui vieillit en silence.

    Le test échoue dans les deux sens, et c'est ce qui en fait un garde :

    - une occurrence NOUVELLE dans un fichier absent de la table, ou un compte
      qui monte, signale une mention non justifiée — c'est le cas dangereux,
      celui qu'une réingestion recopierait ;
    - un compte qui DESCEND signale que la table décrit un état révolu. La
      corriger est alors le geste attendu, et ce rouge-là est le prix de
      l'autre : sans lui, la table pourrait autoriser n'importe quoi.

    Ce test est le site canonique de ces comptes. Les documents y renvoient au
    lieu de les recopier.
    """
    trouves: dict[str, int] = {}
    for chemin in sorted((_RACINE / "documentation").glob("*.md")) + [_RACINE / "README.md"]:
        compte = chemin.read_text(encoding="utf-8").count(_MODELE_ANGLAIS)
        if compte:
            trouves[str(chemin.relative_to(_RACINE))] = compte

    assert trouves == _VESTIGES_AUTORISES, (
        f"l'inventaire de '{_MODELE_ANGLAIS}' dans la documentation a bougé : "
        f"attendu {_VESTIGES_AUTORISES}, trouvé {trouves}. Une mention de ce nom "
        "hors de cette table est une instruction que quelqu'un peut suivre — les "
        "deux candidats rendent des vecteurs de même largeur, et le mauvais "
        "produit un index que l'agent refuse."
    )
