"""Deux endroits qui doivent s'accorder, et que rien ne forçait à s'accorder.

Ces vérifications ne testent pas de la logique : elles empêchent une divergence
silencieuse entre deux fichiers dont un seul est lu à l'exécution. Tous les cas
présents ont réellement divergé — y compris le dernier, qui ne porte pas sur une
constante mais sur une **mesure** recopiée à trois endroits.
"""

import importlib.util
import re
import subprocess
import sys
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
    # Le site canonique de cet inventaire, qui porte forcément son aiguille.
    "tests/unit/test_coherence_depot.py": 2,
    # Le garde du modèle d'embedding : ce nom EST le cas de test.
    "tests/unit/test_garde_modele_embedding.py": 1,
}

_MODELE_ANGLAIS = "all-MiniLM-L6-v2"


def _fichiers_suivis() -> list[str]:
    """Tous les fichiers SUIVIS par git, et c'est la bonne borne.

    CE QUE CE BALAYAGE REMPLACE. Il ne regardait que `documentation/*.md` **non
    récursif** plus `README.md`. Échappaient `documentation/audits/` (qui
    existe), `.env.example`, `src/`, `scripts/` et `tests/` — et c'était
    ironique, la trouvaille que cet inventaire consigne étant précisément *« une
    ligne de `.env` d'apparence exécutable »*. Un inventaire avec un angle mort
    autorise n'importe quoi dans cet angle.

    « Suivi par git » plutôt qu'une liste de répertoires : ce dépôt est PUBLIC,
    donc l'ensemble des fichiers suivis est exactement ce qu'un lecteur peut
    copier — la borne décrit le risque au lieu de décrire l'arborescence, et elle
    n'a aucun angle mort à tenir à jour. Un répertoire neuf y entre tout seul.
    """
    acheve = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=_RACINE,
        capture_output=True,
        text=True,
        check=True,
    )
    return [nom for nom in acheve.stdout.split("\0") if nom]


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
    for relatif in _fichiers_suivis():
        chemin = _RACINE / relatif
        if not chemin.is_file():
            continue
        compte = chemin.read_text(encoding="utf-8", errors="ignore").count(_MODELE_ANGLAIS)
        if compte:
            trouves[relatif] = compte

    assert trouves == _VESTIGES_AUTORISES, (
        f"l'inventaire de '{_MODELE_ANGLAIS}' dans la documentation a bougé : "
        f"attendu {_VESTIGES_AUTORISES}, trouvé {trouves}. Une mention de ce nom "
        "hors de cette table est une instruction que quelqu'un peut suivre — les "
        "deux candidats rendent des vecteurs de même largeur, et le mauvais "
        "produit un index que l'agent refuse."
    )


# ─── La prémisse Docker fausse, et où elle a le droit d'être citée ────────────

# CE QUE CETTE PRÉMISSE AFFIRME, ET POURQUOI ELLE EST FAUSSE. Sept sites de ce
# dépôt ont écrit qu'un `/health` en erreur ferait « redémarrer le service en
# boucle ». `mesuré` deux fois indépendamment : un healthcheck en échec ne
# redéclenche AUCUN conteneur sous Docker Compose — `restart:` répond à la sortie
# du processus, pas à la santé — et 21 échecs consécutifs laissent
# `RestartCount=0` et `StartedAt` inchangé. Ce qui arrive vraiment est que le
# conteneur passe `unhealthy`, donc que `frontend`, qui en dépend en
# `condition: service_healthy`, ne lève pas au démarrage à froid.
#
# POURQUOI UN GARDE ET PAS SEULEMENT UNE CORRECTION. Les décisions de `/health`
# restent les mêmes ; c'est leur MOTIF qui change. Un raisonnement juste sur un
# antécédent faux se relit comme une preuve, et se recopie comme telle — ce nom
# de panne a essaimé sur sept sites sans que personne ne le remesure. Une
# affirmation de cette famille ne se recopie plus : elle se compte, et le compte
# rougit. Site canonique : `documentation/axes_amelioration.md` §1.27.
#
# LA BORNE EST TOUT LE SUIVI GIT, comme celle de l'inventaire jumeau ci-dessus,
# ET C'EST UNE CORRECTION — trouvaille NB-3 de l'audit du lot 3 (§4.23). Ce test
# a d'abord filtré sur `src/` et `tests/`, là où `_fichiers_suivis()` rend tout
# le suivi. `mesuré` : **115 fichiers suivis, 68 dans le périmètre, 47 dehors** —
# et parmi ces 47 se trouvait **`docker-compose.yml`**, le fichier même dont la
# prémisse parle, celui qui porte le `healthcheck` et le `condition:
# service_healthy` sur lesquels tout ce raisonnement porte. C'est l'endroit où
# une phrase de cette famille serait la PLUS dangereuse, et c'était un angle
# mort. Avec lui : `README.md`, `Dockerfile.agent` et les sept fichiers de
# `scripts/`. *Un inventaire avec un angle mort autorise n'importe quoi dans cet
# angle* — la leçon est déjà écrite au docstring de `_fichiers_suivis`, et ce
# test ne la suivait pas.
#
# CE QUI RESTE EXEMPTÉ, ET NOMMÉ PLUTÔT QUE FILTRÉ PAR RÉPERTOIRE. Le registre et
# le journal de pilotage ont pour métier de CITER une affirmation afin de la
# démentir, et leurs comptes sont gouvernés par l'historique du dépôt et non par
# cette branche. `mesuré`, et c'est ce qui justifie l'exemption au lieu de la
# supposer : `main` porte une occurrence dans `documentation/pilotage_du_chantier.md`
# que cette branche n'a pas — un compte exact y rendrait ce test rouge à la
# FUSION, pour une raison qui n'est pas celle de ce garde.
#
# L'exemption est une LISTE DE NOMS, jamais un préfixe de répertoire, et la
# différence est tout l'objet de NB-3 : un préfixe aurait rendu muet tout ce qui
# viendra s'ajouter derrière lui, alors qu'un nom ne couvre que le fichier qu'il
# nomme. Un document neuf de `documentation/` qui se mettrait à FONDER une
# décision sur cette prémisse rougit donc, comme rougirait `docker-compose.yml`.
_PREMISSE_DOCKER_FAUSSE = (
    "redémarrer le service en boucle",
    "redémarre en boucle",
    "restart en boucle",
    "redémarrage en boucle",
)

# Les deux documents dont le métier EST de citer pour démentir. Exemptés par leur
# NOM, pour le motif mesuré ci-dessus. Toute autre absence de cette table vaut
# zéro occurrence, `docker-compose.yml` compris.
_CITE_POUR_DEMENTIR = (
    "documentation/axes_amelioration.md",
    "documentation/pilotage_du_chantier.md",
)

# Une CITATION n'est pas une prémisse : les trois entrées ci-dessous portent
# l'aiguille sans fonder quoi que ce soit dessus. Elles sont inventoriées quand
# même, et c'est le prix de l'autre sens — sans elles, la table autoriserait
# n'importe quoi. Écrire une réfutation sans l'aiguille aurait rendu ce dépôt
# ingrepable sur exactement le nom qu'on vient de mesurer faux.
_CITATIONS_AUTORISEES = {
    # Cite la prémisse pour la DÉMENTIR, et nomme le mécanisme mesuré à la place.
    "src/agent/retriever.py": 1,
    # Idem : le docstring dit désormais ce qui arrive vraiment, en nommant ce que
    # ce n'est pas.
    "tests/unit/test_health_parallele.py": 1,
    # Le site canonique de cet inventaire, qui porte forcément ses aiguilles.
    "tests/unit/test_coherence_depot.py": 4,
}


def test_la_premisse_docker_fausse_ne_sert_de_motif_a_rien() -> None:
    """Aucun fichier suivi ne fonde une décision sur cette prémisse.

    Le test rougit dans les deux sens, comme l'inventaire du modèle anglais :
    une citation NOUVELLE est une prémisse fausse qui repart, et un compte qui
    DESCEND dit que cette table décrit un état révolu.

    La borne est tout le suivi git moins deux documents nommés — voir le
    commentaire en tête de cette section, et la mesure des 47 fichiers qui
    échappaient au filtre `src/` + `tests/`, `docker-compose.yml` en tête.
    """
    trouves: dict[str, int] = {}
    for relatif in _fichiers_suivis():
        if relatif in _CITE_POUR_DEMENTIR:
            continue
        chemin = _RACINE / relatif
        if not chemin.is_file():
            continue
        texte = chemin.read_text(encoding="utf-8", errors="ignore")
        compte = sum(texte.count(aiguille) for aiguille in _PREMISSE_DOCKER_FAUSSE)
        if compte:
            trouves[relatif] = compte

    assert trouves == _CITATIONS_AUTORISEES, (
        f"l'inventaire de la prémisse Docker fausse a bougé : attendu "
        f"{_CITATIONS_AUTORISEES}, trouvé {trouves}. Un healthcheck en échec ne "
        "redémarre RIEN sous Docker Compose — `restart:` répond à la sortie du "
        "processus, pas à la santé — et fonder une décision sur ce mécanisme "
        "inexistant se relit comme une preuve. Le vrai motif est que le "
        "conteneur passe `unhealthy`, donc que `frontend` ne lève pas au "
        "démarrage à froid : cf. documentation/axes_amelioration.md §1.27."
    )


# ─── Le compte de tests annoncé par `tests.md` ────────────────────────────────
#
# LE GARDE QUE §4.13 RÉCLAMAIT, ET QUE §4.21 A LAISSÉ OUVERT. Le compte de tests
# publié par `documentation/tests.md` a pris 25 tests de retard sans que le lot
# ni son audit le voient, puis a été **faux dans le commit même qui le
# corrigeait** — il annonçait 520 sur 36 quand le dépôt en portait 539 sur 37.
# Corrigé deux fois à la main, jamais gardé. *Le corriger une troisième fois sans
# garde serait exactement le geste que le §4.13 sanctionne*, et cette passe l'a
# rendu faux une troisième fois en ajoutant quatre cas.
#
# POURQUOI CE GARDE MESURE PAR `pytest` ET NON PAR L'AST, et c'est la seule forme
# valide. `mesuré` : un comptage par AST des `def test_*` rend **527**, quand
# `pytest` en collecte **557** — huit `parametrize` en déplient trente de plus.
# Ce sont DEUX GRANDEURS DIFFÉRENTES, et ce chantier en a déjà payé deux
# confusions du même genre (« 202 lignes » pour 175 insertions + 27 suppressions,
# et « le plus gros fichier de tests » du §4.14). Un garde qui compare le chiffre
# publié à un AST rendrait rouge un dépôt juste, ou vert un dépôt faux.
#
# La recette employée ici est CELLE QUE LE DOCUMENT PUBLIE, mot pour mot dans son
# intention : la somme des comptes par fichier de `--collect-only`. Le document et
# son garde ne mesurent donc pas deux choses.
#
# LE SOUS-PROCESSUS EST LE PRIX DE LA JUSTESSE. Un décompte pris sur la session
# courante — via un `pytest_collection_modifyitems` — serait gratuit, mais il
# rendrait le compte de la SÉLECTION : un `pytest -k` le ferait rougir pour une
# raison qui n'est pas la bonne, et le rattraper demanderait un `skip`
# conditionnel, ce que ce dépôt n'autorise pas. Le sous-processus collecte
# toujours `tests/unit/` en entier, quelle que soit la manière dont la campagne a
# été lancée.

_PAGE_DES_TESTS = "documentation/tests.md"


def _comptes_annonces() -> tuple[int, int, int]:
    """Les chiffres écrits dans `tests.md` : le titre, puis la note `mesuré`.

    Les DEUX sites sont relevés, et pas seulement un. C'est ce qui a laissé
    passer 520 : un chiffre recopié à deux endroits dont un seul est relu.
    """
    texte = (_RACINE / _PAGE_DES_TESTS).read_text(encoding="utf-8")
    titre = re.search(r"^## Unitaire — (\d+) tests", texte, re.M)
    note = re.search(r"\*\*(\d+)\*\* tests sur \*\*(\d+)\*\* fichiers", texte)
    assert titre is not None, (
        f"le titre « ## Unitaire — N tests » n'a pas été trouvé dans "
        f"{_PAGE_DES_TESTS} : ce garde ne mesure plus rien, et c'est un rouge"
    )
    assert note is not None, (
        f"la note « **N** tests sur **M** fichiers » n'a pas été trouvée dans "
        f"{_PAGE_DES_TESTS} : ce garde ne mesure plus rien, et c'est un rouge"
    )
    return int(titre.group(1)), int(note.group(1)), int(note.group(2))


def _comptes_collectes() -> tuple[int, int]:
    """Ce que `pytest` collecte réellement, par la recette que le document publie."""
    acheve = subprocess.run(
        [
            sys.executable, "-m", "pytest", "tests/unit/",
            "--collect-only", "-q", "-p", "no:cacheprovider",
        ],
        cwd=_RACINE,
        capture_output=True,
        text=True,
        check=False,
    )
    par_fichier = re.findall(r"^tests/unit/\S+: (\d+)$", acheve.stdout, re.M)
    assert par_fichier, (
        "la collecte n'a rien rendu, donc ce garde ne mesure rien. Sortie de "
        f"pytest (rc={acheve.returncode}) :\n{acheve.stdout[-2000:]}\n"
        f"{acheve.stderr[-2000:]}"
    )
    return sum(int(n) for n in par_fichier), len(par_fichier)


def test_le_compte_de_tests_annonce_est_celui_que_pytest_collecte() -> None:
    """Les trois chiffres publiés doivent être ceux que la collecte rend.

    Le test rougit dans les deux sens, comme les deux inventaires ci-dessus : un
    test ajouté sans mise à jour de la page rougit, et une page qui annonce plus
    que le dépôt ne porte rougit aussi. Le geste attendu au rouge est d'écrire le
    chiffre mesuré — c'est un décompte, pas une décision.

    Le titre et la note sont confrontés SÉPARÉMENT à la mesure, et non l'un à
    l'autre : deux sites qui s'accordent entre eux peuvent être faux ensemble, et
    c'est exactement ce qui est arrivé.
    """
    titre, note_tests, note_fichiers = _comptes_annonces()
    tests, fichiers = _comptes_collectes()

    assert (titre, note_tests, note_fichiers) == (tests, tests, fichiers), (
        f"{_PAGE_DES_TESTS} annonce {titre} tests dans son titre et "
        f"{note_tests} tests sur {note_fichiers} fichiers dans sa note `mesuré`, "
        f"quand pytest en collecte {tests} sur {fichiers}. Ce compte a déjà pris "
        "25 tests de retard sans que personne ne le voie, et il a été faux dans "
        "le commit même qui le corrigeait (§4.13, §4.21) : écris le chiffre "
        "mesuré, la recette est publiée dans le document."
    )
