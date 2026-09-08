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
    # la mesure de leur largeur commune. Les deux dernières sont arrivées par la
    # FUSION du lot 3, et non par son diff : le pilote cite le nom du modèle dans
    # les §4.19 et §4.25 pour décrire les sondes qui ont mesuré le garde — une
    # collection bouchonnée sur ce modèle, et la table où il s'écarte de son
    # auditeur. Ce garde les a attrapées sur le résultat de la fusion, là où
    # aucune relecture de branche ne pouvait les voir : c'est la famille (f) du
    # §4.14, et c'est la première fois qu'un garde la trouve au lieu d'un
    # auditeur. Aucune des cinq n'est une instruction — pas une affectation
    # `EMBEDDING_MODEL_NAME=` parmi elles, `vérifié` le 7 septembre 2026.
    "documentation/axes_amelioration.md": 5,
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

# ─── Les recettes de `make eval`, et les fichiers qu'elles nomment ───────────


def _recettes_eval() -> dict[str, str]:
    """Les lignes de commande des cibles d'évaluation du `Makefile`.

    Lues dans le fichier plutôt que par `make -n` : `make -n eval` déclenche la
    dépendance `verifier-les-ancrages`, qui appelle `docker inspect`. Un test
    unitaire ne parle ni à Docker ni au réseau.
    """
    texte = (_RACINE / "Makefile").read_text(encoding="utf-8")
    recettes: dict[str, str] = {}
    cible = None
    for ligne in texte.splitlines():
        if ligne and not ligne[0].isspace() and ":" in ligne and not ligne.startswith("#"):
            nom = ligne.split(":", 1)[0].strip()
            cible = nom if nom.startswith("eval") or nom.startswith("verifier") else None
            if cible:
                recettes[cible] = ""
        elif cible and ligne.startswith("\t"):
            recettes[cible] += " " + ligne.strip().rstrip("\\")
    return recettes


def test_les_cibles_d_evaluation_ne_nomment_que_des_fichiers_qui_existent() -> None:
    """**LE DÉFAUT QUE CE GARDE FERME, ET IL A ÉTÉ ARMÉ DEUX MOIS.**

    `make eval` visait `tests/fixtures/golden_qa_generated.json`, un jeu dont
    **0** des 129 ancrages existait dans le graphe, et `--compare
    runs/final.json`, l'antécédent d'un corpus remplacé. Aucun des deux ne
    rendait d'erreur : la recette tournait et rendait un tableau faux.
    §4.3 de `documentation/axes_amelioration.md`.

    Ce garde ne peut pas juger la fraîcheur d'un jeu — cela demande les stores,
    et c'est `scripts/verifier_les_ancrages.py`. Il ferme le cas plus bête et
    tout aussi silencieux : un chemin qui ne désigne AUCUN fichier. Un `--golden`
    absent fait lever la campagne, mais un `--compare` absent la faisait sortir
    en 0 sans comparaison jusqu'au 8 septembre 2026 — corrigé, et gardé par
    `test_comparaison_appariee.test_un_compare_qui_pointe_un_fichier_absent_sort_en_deux`.
    """
    recettes = _recettes_eval()
    assert set(recettes) >= {"eval", "eval-controle", "verifier-les-ancrages"}

    manquants: list[str] = []
    for cible, commande in recettes.items():
        for jeton in commande.split():
            # Les chemins que la recette DÉSIGNE, pas ceux qu'elle produit :
            # `--out` porte un nom horodaté qui n'existe pas encore.
            designe = jeton.startswith(("tests/fixtures/", "runs/")) and "$" not in jeton
            if designe and not (_RACINE / jeton).is_file():
                manquants.append(f"{cible} → {jeton}")
    assert not manquants, (
        f"cible(s) d'évaluation pointant un fichier absent : {manquants}. "
        "Un `--compare` absent a fait sortir `make eval` en 0 sans comparaison."
    )


def test_make_eval_ne_vise_plus_aucun_jeu_ni_aucune_cible_retires_par_le_lot_5() -> None:
    """Les noms retirés le 8 septembre 2026, épinglés par leur nom.

    Un chemin qui existe encore dans l'histoire de `git` revient facilement
    dans une recette par copie d'un ancien document. Les trois retirés :

    - `tests/fixtures/golden_qa_generated.json` — 0 / 129 ancrages dans le
      graphe, et 34 des 36 détections `detect-secrets` du dépôt ;
    - `tests/fixtures/golden_qa.json` — 15 questions à réponse portant **0**
      `gold_element_ids` : toutes ses métriques de rappel valaient `None` ;
    - `runs/final.json` — antécédent d'un corpus remplacé, et il porte les MÊMES
      138 identifiants que le jeu régénéré, donc le refus sur désaccord de jeu ne
      le voyait pas.
    """
    commandes = " ".join(_recettes_eval().values())
    for retire in (
        "golden_qa_generated.json",
        "golden_qa.json",
        "runs/final.json",
        "runs/reference.json",
    ):
        assert retire not in commandes, (
            f"`{retire}` est revenu dans une cible d'évaluation : il a été retiré "
            "par le lot 5, et son motif est au §4.3 du registre."
        )


def test_la_verification_des_ancrages_est_l_antecedent_des_deux_campagnes() -> None:
    """Un rappel mesuré sur un jeu qui désigne le vide rend 0 et ne dit pas pourquoi.

    L'ordre est donc porté par le `Makefile` et non par la mémoire de celui qui
    lance la campagne : les deux cibles d'évaluation DÉPENDENT de la
    vérification. Sans cette dépendance, la panne du §4.3 se rejoue à
    l'identique au prochain remplacement de corpus.
    """
    texte = (_RACINE / "Makefile").read_text(encoding="utf-8")
    for cible in ("eval", "eval-controle"):
        motif = rf"^{re.escape(cible)}:\s*(.*)$"
        trouve = re.search(motif, texte, re.MULTILINE)
        assert trouve, f"cible `{cible}` absente du Makefile"
        assert "verifier-les-ancrages" in trouve.group(1), (
            f"`{cible}` ne dépend pas de `verifier-les-ancrages`"
        )

# ─── La promesse retirée au pipeline ─────────────────────────────────────────

# LA PHRASE, MOT POUR MOT, ET C'EST VOULU. Le §4.3 du registre l'a mesurée
# fausse : `documentation/pour_le_pipeline_ingestion.md` promettait au pipeline
# que le déterminisme d'`element_id` « permet au jeu doré de survivre à une
# réingestion ». Le déterminisme est tenu — l'exigence 2 du contrat l'est — mais
# ce qui a changé le 2 septembre 2026 est le CORPUS, ce qu'aucune convention
# d'identifiant ne peut couvrir : un passage qui n'existe plus n'a pas
# d'identifiant valide. La phrase attribuait au mauvais mécanisme une garantie
# qu'il n'a jamais donnée, et le prix a été une campagne morte pendant deux mois.
_PROMESSE_RETIREE = "permet au jeu doré de survivre à une réingestion"


def _est_citee(texte: str, position: int, longueur: int) -> bool:
    """L'occurrence à `position` est-elle DANS des guillemets français ?

    C'est la distinction que ce garde doit faire, et une première écriture ne la
    faisait pas : elle interdisait la phrase partout, donc elle rougissait sur
    les DEUX sites qui la citent pour la réfuter — le §4.3 du registre et le
    paragraphe de correction lui-même. **Un garde qui interdit d'écrire la
    rétractation à son propre site est retiré par le suivant**, donc désarmé.

    La règle est donc : le guillemet le plus proche AVANT l'occurrence doit être
    un ouvrant, et le plus proche APRÈS un fermant. Une prose qui affirme la
    promesse hors guillemets n'en a aucun, et rougit.
    """
    avant = texte[:position]
    apres = texte[position + longueur :]
    dernier_ouvrant = avant.rfind("\u00ab")
    dernier_fermant = avant.rfind("\u00bb")
    prochain_fermant = apres.find("\u00bb")
    prochain_ouvrant = apres.find("\u00ab")
    ouverte = dernier_ouvrant > dernier_fermant
    fermee = prochain_fermant != -1 and (
        prochain_ouvrant == -1 or prochain_fermant < prochain_ouvrant
    )
    return ouverte and fermee


def test_la_promesse_retiree_au_pipeline_n_est_plus_affirmee_nulle_part() -> None:
    """La phrase peut être CITÉE pour être réfutée ; elle ne peut plus être AFFIRMÉE.

    Le garde porte sur tous les fichiers suivis et non sur le seul document
    corrigé : la phrase est adressée au pipeline, et c'est le genre d'assurance
    qu'on recopie dans un `README`, un rapport de lot ou une réponse à une
    question. Ce que le déterminisme garantit VRAIMENT est écrit au site
    corrigé, `documentation/pour_le_pipeline_ingestion.md`.
    """
    affirmations: list[str] = []
    for relatif in _fichiers_suivis():
        chemin = _RACINE / relatif
        if not chemin.is_file() or relatif == "tests/unit/test_coherence_depot.py":
            continue
        texte = chemin.read_text(encoding="utf-8", errors="ignore")
        depart = 0
        while (position := texte.find(_PROMESSE_RETIREE, depart)) != -1:
            if not _est_citee(texte, position, len(_PROMESSE_RETIREE)):
                affirmations.append(f"{relatif}:{texte.count(chr(10), 0, position) + 1}")
            depart = position + 1
    assert not affirmations, (
        f"la promesse retirée au pipeline est AFFIRMÉE, hors guillemets, en "
        f"{affirmations}. Le déterminisme d'`element_id` garantit qu'une "
        "réingestion du MÊME corpus rend les MÊMES identifiants — pas qu'un jeu "
        "de questions survive au REMPLACEMENT d'un corpus. §4.3 du registre."
    )


def test_le_garde_de_la_promesse_distingue_une_citation_d_une_affirmation() -> None:
    """Et il en est CAPABLE : les deux cas, sur le même appel.

    Sans ce test, la fonction pourrait rendre vrai partout — le garde
    ci-dessus serait alors vert pour la mauvaise raison, exactement comme une
    sonde qui rend 0 sur le code sain et sur le code défectueux.
    """
    cite = f"Elle disait : \u00ab c'est ce qui {_PROMESSE_RETIREE} \u00bb, et c'est faux."
    affirme = f"Le d\u00e9terminisme {_PROMESSE_RETIREE}, donc le jeu tient."

    assert _est_citee(cite, cite.index(_PROMESSE_RETIREE), len(_PROMESSE_RETIREE))
    assert not _est_citee(
        affirme, affirme.index(_PROMESSE_RETIREE), len(_PROMESSE_RETIREE)
    )
