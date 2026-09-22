"""LE VERDICT DE CES SCÈNES NE DÉPEND PAS DE LA FENÊTRE DU POSTE.

CE QUE CE FICHIER GARDE, ET POURQUOI IL N'EXISTAIT PAS. Le 22 septembre 2026,
`LLM_NUM_CTX` est passé de 8192 à 32768 dans le `.env` du clone principal. Onze
scènes de `tests/unit/` sont devenues rouges le jour même, et **personne ne l'a
vu pendant deux jours** : les lots et le pilote mesurent dans des arbres de
travail, qui n'ont pas de `.env`, et la porte y était verte à bon droit. Le seul
arbre qui porte la configuration réelle est le clone principal, et la porte n'y
avait plus été lancée depuis le changement.

L'écart entre les deux arbres est exactement la surface où un réglage peut
casser sans bruit, et **rien ne la gardait**. C'est la dette que le constat
§4.63 du registre laissait ouverte ; ce fichier la solde.

CE QUI EST ASSERTÉ EST UNE PROPRIÉTÉ, PAS UN INSTANTANÉ : *le verdict de ces
scènes est le même sous des `LLM_NUM_CTX` opposés*. Ni un compte du jour, ni la
présence d'un appel à `poser_la_fenetre` dans le texte des fichiers — un garde
qui lit la FORME rougit au premier refactor et reste vert devant une scène qui
pose la fenêtre trop tard, après le premier calcul de budget. Ce qui est mesuré
est ce qui SORT : `rc`, et le compte de scènes passées.

POURQUOI DES SOUS-PROCESSUS, ET ILS SONT LE PRIX DE LA JUSTESSE. `settings` est
construit à l'import de `src.agent.settings` ; changer `LLM_NUM_CTX` dans la
session courante n'aurait donc plus aucun effet sur lui. Surtout, deux des onze
scènes ne lisent pas le singleton mais **reconstruisent** un `Settings` — et
`pydantic-settings` fait de l'environnement une source de priorité SUPÉRIEURE au
fichier `.env` (`mesuré` le 22 septembre 2026 : un `.env` à 32768 face à une
variable d'environnement à 8192 rend 8192). Seul un vrai lancement sous une
vraie variable d'environnement reproduit ce que fait le poste — et, par la même
priorité, ce garde reste mordant DANS le clone principal, où le `.env` existe :
la variable qu'il pose y prime sur le fichier.

CE QUE CE GARDE NE PROUVE PAS, et c'est écrit plutôt que supposé :

- il balaie `LLM_NUM_CTX`, et lui seul. Le budget dépend aussi de
  `LLM_MAX_TOKENS` et de `HISTORY_WINDOW_SHARE`, tous deux lisibles dans
  l'environnement. `poser_la_fenetre` les pose **avec** la fenêtre, donc les
  onze scènes en sont affranchies par construction ; mais aucun lancement de ce
  fichier ne fait varier ces deux-là, et une scène AUTRE que les onze pourrait
  en hériter sans que rien ne rougisse. **Borne écrite, non fermée** ;
- il garde les onze scènes NOMMÉES ci-dessous. Une scène neuve qui hériterait de
  la fenêtre ne s'y ajoute pas toute seule.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

from src.agent.settings import Settings
from tests.unit.fenetre_du_prompt import REGLAGES_POSES

_RACINE = Path(__file__).resolve().parents[2]

# ─── LES SCÈNES GARDÉES ──────────────────────────────────────────────────────
#
# Les onze que le passage de 8192 à 32768 a rendues rouges, `mesuré` le
# 22 septembre 2026 sur `main` = `651940f` : `rc(make)=2`, 11 échecs / 1 093
# passés sous 32768, contre `rc(make)=0` et 1 104 passés sous 8192.
#
# Le registre §4.63 en comptait DIX, sur quatre fichiers, et c'est exact pour la
# manière dont le poste pose la valeur — par le FICHIER `.env`. La onzième,
# `test_aucune_valeur_attendue_n_est_un_defaut`, ne se révèle que sous une
# VARIABLE D'ENVIRONNEMENT, parce qu'elle reconstruit un `Settings` avec
# `_env_file=None` : le fichier était bien neutralisé, l'environnement ne
# l'était pas. Les deux formes sont le même défaut — hériter du réglage — et ce
# garde les couvre toutes les deux.
_SCENES: tuple[str, ...] = (
    "tests/unit/test_llm_budget.py::test_aucune_source_ecartee_n_aurait_tenu",
    "tests/unit/test_llm_budget.py::test_le_budget_ne_devient_jamais_negatif",
    "tests/unit/test_llm_budget.py::test_un_tour_trop_gros_est_ecarte_entier",
    "tests/unit/test_llm_budget.py::test_un_message_trop_gros_est_ecarte_pas_tronque",
    "tests/unit/test_llm_budget.py::test_fit_prompt_borne_historique_et_sources_ensemble",
    "tests/unit/test_llm_budget.py::test_node_generate_publie_le_budget_reellement_applique",
    "tests/unit/test_answer_endpoint.py::test_answer_publie_le_chiffre_calcule_par_le_graphe",
    "tests/unit/test_precision_contexte.py::test_answer_rend_les_candidates_ecartees_et_les_marque",
    "tests/unit/test_precision_contexte.py"
    "::test_le_texte_publie_est_celui_qui_est_parti_troncature_comprise",
    "tests/unit/test_capture_branchement.py::test_le_budget_ecarte_des_sources_et_la_colonne_le_porte",
    "tests/unit/test_champs_du_dialecte.py::test_aucune_valeur_attendue_n_est_un_defaut",
)

# Les fenêtres balayées. 8192 et 32768 sont les deux valeurs du basculement
# mesuré ; 16384 est la valeur d'épreuve de `_REGLAGES_EPROUVES` dans
# `test_champs_du_dialecte.py`, et elle est ici parce que le second garde
# anti-défaut de ce fichier aurait rougi sous elle et sous elle seule — une
# scène verte par coïncidence de chiffres n'est pas une scène gardée.
_FENETRES: tuple[int, ...] = (8192, 16384, 32768)

_BILAN = re.compile(r"(\d+) passed")


def _lancer(fenetre: int) -> tuple[int, int, str]:
    """Lance les scènes gardées sous `LLM_NUM_CTX=fenetre`. Rend (rc, passés, sortie).

    `-q` n'est pas passé : il est déjà dans `addopts` de `pyproject.toml`, et le
    recumuler rendrait la sortie trop avare pour qu'un échec se lise.
    """
    sortie = subprocess.run(  # noqa: S603
        [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", *_SCENES],
        cwd=_RACINE,
        env={**_environnement_sans_fenetre(), "LLM_NUM_CTX": str(fenetre)},
        capture_output=True,
        text=True,
        timeout=600,
    )
    texte = sortie.stdout + sortie.stderr
    trouve = _BILAN.search(texte)
    return sortie.returncode, int(trouve.group(1)) if trouve else 0, texte


def _environnement_sans_fenetre() -> dict[str, str]:
    import os

    return {c: v for c, v in os.environ.items() if c != "LLM_NUM_CTX"}


def test_le_verdict_des_scenes_gardees_ne_depend_pas_de_llm_num_ctx() -> None:
    """LA GARDE QUI MANQUAIT, et elle mord sur le producteur.

    Le producteur est la scène : c'est elle qui produit — ou non — la propriété
    « mon verdict ne dépend pas du réglage ». Rendre une seule des onze à
    l'héritage, c'est-à-dire lui retirer son `poser_la_fenetre`, suffit à faire
    rougir ici sous la fenêtre large, tandis que le lancement ordinaire de cette
    même scène, dans un arbre sans `.env`, resterait vert.

    Les trois lancements doivent rendre `rc=0` ET le même compte. Le compte
    attendu n'est pas un chiffre écrit ici : c'est le nombre de scènes gardées,
    de sorte qu'une scène renommée ou disparue fait rougir au lieu de rétrécir
    silencieusement le périmètre — un garde qui mesure un ensemble vide est vert
    pour la pire des raisons.
    """
    assert _SCENES, "aucune scène gardée : ce fichier ne mesurerait rien"

    releves = {fenetre: _lancer(fenetre) for fenetre in _FENETRES}

    rouges = {f: (rc, texte) for f, (rc, _, texte) in releves.items() if rc != 0}
    assert not rouges, (
        "le verdict de ces scènes dépend encore de `LLM_NUM_CTX` : "
        + " ; ".join(f"sous {f}, rc(pytest)={rc}" for f, (rc, _) in rouges.items())
        + ". Une scène qui HÉRITE de la fenêtre au lieu de la POSER change de "
        "sujet le jour où le réglage change — elle ne mesure alors plus rien, et "
        "elle le dit. Appelle `poser_la_fenetre` AVANT le premier calcul de "
        "budget de la scène. Sortie du premier lancement rouge :\n"
        + next(iter(rouges.values()))[1][-4000:]
    )

    comptes = {fenetre: passes for fenetre, (_, passes, _) in releves.items()}
    assert set(comptes.values()) == {len(_SCENES)}, (
        f"comptes relevés {comptes} pour {len(_SCENES)} scènes gardées. Vert "
        "n'est pas une preuve tant que le compte n'est pas celui qu'on attend : "
        "un identifiant de scène périmé fait passer moins de tests que la liste "
        "n'en nomme, et le garde mesurerait alors un autre arbre que celui qu'il "
        "croit."
    )


def test_aucune_valeur_posee_n_est_un_defaut_declare() -> None:
    """LE GARDE ANTI-« MESURÉ SOUS LE DÉFAUT », appliqué à la fenêtre posée.

    Poser 8192 rendrait aux onze scènes leur sujet tout en les laissant vertes
    sous une mutation qui écrirait `8192` en dur à la place de
    `settings.llm_num_ctx` — c'est NB-4 de l'audit du 16 septembre 2026, et une
    mutation survivante l'avait déjà trouvé dans ce dépôt.

    Les défauts sont lus sur le CHAMP déclaré, donc sans instancier : ni le
    `.env` du poste ni l'environnement du lancement n'entrent ici.
    """
    declares = {
        champ: Settings.model_fields[champ].default for champ in REGLAGES_POSES
    }
    confondus = {
        champ: valeur
        for champ, valeur in REGLAGES_POSES.items()
        if valeur == declares[champ]
    }
    assert not confondus, (
        f"valeur(s) posée(s) égale(s) au défaut déclaré : {confondus} (défauts "
        f"{declares}). Une scène qui pose un réglage à sa propre valeur par "
        "défaut ne peut pas distinguer la variable de la constante : elle "
        "retrouve son sujet et perd son pouvoir de séparation."
    )


@pytest.mark.parametrize("champ", sorted(REGLAGES_POSES))
def test_chaque_reglage_pose_est_un_champ_de_settings(champ: str) -> None:
    """Un réglage posé qui ne serait plus un champ ne poserait rien du tout.

    `monkeypatch.setattr` sur un attribut absent lève, donc la faute se verrait ;
    sur un attribut RENOMMÉ, elle poserait un champ mort pendant que le vrai
    resterait hérité, et les scènes seraient vertes pour rien.
    """
    assert champ in Settings.model_fields, (
        f"`{champ}` est posé par `fenetre_du_prompt` mais n'est plus un champ de "
        "`Settings` : les scènes qui croient le poser héritent en réalité du "
        "réglage qui l'a remplacé"
    )
