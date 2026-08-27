"""La comparaison appariée, et son refus de comparer deux jeux différents.

`comparer()` lisait `["resume"]` et diffait métrique par métrique, sans jamais
joindre sur la question. Conséquence : sur 138 questions, un écart de deux points
est indistinguable du bruit, et personne ne peut savoir si un changement a
amélioré 30 questions en dégradant 28, ou amélioré 2 sans rien casser. Ce sont
deux résultats OPPOSÉS qui s'affichent identiques.

Les campagnes synthétiques de `tests/fixtures/campagne_*.json` sont construites
pour que la réponse soit connue à la main. `campagne_echange.json` est la pièce
maîtresse : elle a **exactement le même MRR moyen** que la référence alors que
huit questions sur dix ont basculé.

Tout est déterministe : test des signes exact — aucun tirage — et bootstrap à
graine fixe.
"""

import importlib.util
import json
import os
import pathlib
import subprocess
import sys

import pytest

_RACINE = pathlib.Path(__file__).resolve().parents[2]
_SCRIPT = _RACINE / "scripts" / "evaluate.py"
_FIXTURES = _RACINE / "tests" / "fixtures"


def _evaluate():
    """Charge scripts/evaluate.py sans faire de `scripts/` un paquet."""
    spec = importlib.util.spec_from_file_location("evaluate", _SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _campagne(nom: str) -> list[dict]:
    chemin = _FIXTURES / f"{nom}.json"
    return json.loads(chemin.read_text(encoding="utf-8"))["questions"]


# ─── Ce que l'appariement rend visible et que la moyenne cache ───────────────

def test_un_echange_a_moyenne_constante_est_invisible_sans_appariement() -> None:
    """**Le test qui porte la section.**

    Quatre questions montent, quatre descendent : le MRR moyen ne bouge PAS. Un
    diff de résumés affiche « → 0.500 » et se lit « rien n'a changé », alors que
    huit questions sur dix ont basculé. L'appariement les compte.
    """
    evaluate = _evaluate()
    reference = _campagne("campagne_reference")
    echange = _campagne("campagne_echange")

    # Le diff non apparié : le chiffre que `comparer()` aurait affiché.
    def moyenne(lignes):
        rangs = [r["rang_reciproque"] for r in lignes if r["rang_reciproque"] is not None]
        return sum(rangs) / len(rangs)

    assert moyenne(echange) == moyenne(reference)

    apparie = evaluate.apparier(echange, reference, "rang_reciproque")

    assert (len(apparie["ameliorees"]), len(apparie["degradees"])) == (4, 4)
    assert apparie["delta_moyen"] == 0.0
    assert apparie["inchangees"] == 0


def test_un_gain_net_se_distingue_d_un_echange() -> None:
    """Deux moyennes différentes ne suffisent pas : il faut que la STRUCTURE se
    distingue. Trois questions améliorées sans rien casser et huit questions qui
    s'échangent doivent rendre des verdicts opposés."""
    evaluate = _evaluate()
    reference = _campagne("campagne_reference")

    gain = evaluate.apparier(_campagne("campagne_gain_net"), reference, "rang_reciproque")
    echange = evaluate.apparier(_campagne("campagne_echange"), reference, "rang_reciproque")

    assert (len(gain["ameliorees"]), len(gain["degradees"])) == (3, 0)
    # Le gain net écarte l'hypothèse nulle bien mieux que l'échange, dont le
    # test des signes ne conclut rien du tout.
    assert gain["p_signe"] < echange["p_signe"]
    assert echange["p_signe"] == 1.0
    # Et l'intervalle de confiance range les deux du bon côté de zéro.
    assert gain["ic95"][0] > 0
    assert echange["ic95"][0] < 0 < echange["ic95"][1]


def test_les_questions_qui_basculent_sont_nommees() -> None:
    """C'est ce qu'on va lire pour comprendre POURQUOI. Un compte sans
    identifiants ne mène à aucune investigation."""
    apparie = _evaluate().apparier(
        _campagne("campagne_echange"), _campagne("campagne_reference"), "rang_reciproque"
    )

    assert apparie["ameliorees"] == ["G-001", "G-002", "G-003", "G-004"]
    assert apparie["degradees"] == ["G-005", "G-006", "G-007", "G-008"]


def test_les_questions_sans_or_ne_sont_pas_appariees() -> None:
    """Les deux `unanswerable` de la référence n'ont pas de rang réciproque : les
    apparier à zéro les ferait compter comme inchangées, donc gonflerait la
    population sur laquelle le test des signes ne conclut rien."""
    apparie = _evaluate().apparier(
        _campagne("campagne_gain_net"), _campagne("campagne_reference"), "rang_reciproque"
    )

    assert apparie["appariees"] == 8
    assert apparie["sans_paire"] == 2


def test_une_metrique_absente_de_la_reference_ne_se_lit_pas_zero_ameliorees() -> None:
    """Une métrique ajoutée depuis la campagne de référence n'a aucune paire.
    Rendre « 0 amélioré, 0 dégradé » se lirait « rien n'a changé » sur une
    comparaison qui n'a jamais eu lieu : le compte des non appariables le dit."""
    evaluate = _evaluate()
    reference = [
        {k: v for k, v in ligne.items() if k != "part_utile_caracteres"}
        for ligne in _campagne("campagne_reference")
    ]

    apparie = evaluate.apparier(
        _campagne("campagne_gain_net"), reference, "part_utile_caracteres"
    )

    assert apparie["appariees"] == 0
    assert apparie["sans_paire"] == 10
    assert apparie["delta_moyen"] is None
    assert apparie["ic95"] is None


# L'exclusion des latences de l'appariement, et le sens de lecture des métriques
# de prix, sont assertés dans `test_sens_des_metriques.py` : ils relèvent du même
# sujet, et la raison écrite ici — « le voisinage, pas le changement » — y est
# reprise avec le garde-fou qui manquait.


# ─── Le test des signes ───────────────────────────────────────────────────────

def test_le_test_de_signe_ignore_les_inchangees() -> None:
    """C'est ce qui fait sa puissance : deux améliorations sur 138 questions dont
    136 immobiles sont un signal, pas du bruit — et une moyenne les noie."""
    evaluate = _evaluate()

    assert evaluate.test_de_signe(2, 0) == pytest.approx(0.5)
    assert evaluate.test_de_signe(8, 0) == pytest.approx(2 / 2**8)


def test_le_test_de_signe_ne_conclut_rien_quand_rien_ne_bouge() -> None:
    """Aucune bascule : l'hypothèse nulle est indiscernable de la vérité. Rendre
    autre chose que 1 fabriquerait une significativité."""
    assert _evaluate().test_de_signe(0, 0) == 1.0


def test_le_test_de_signe_est_bilateral() -> None:
    """Une dégradation franche doit être aussi significative que l'amélioration
    symétrique : un test unilatéral ne verrait pas les régressions."""
    evaluate = _evaluate()

    assert evaluate.test_de_signe(0, 6) == evaluate.test_de_signe(6, 0)


# ─── Le bootstrap : déterministe, ou il ne sert à rien ───────────────────────

def test_le_bootstrap_rend_le_meme_intervalle_a_chaque_execution() -> None:
    """Sans graine fixe, deux exécutions sur les mêmes fichiers rendraient deux
    intervalles, et personne ne saurait si l'écart vient du changement mesuré ou
    du tirage."""
    evaluate = _evaluate()
    differences = [0.5, 0.5, 0.5, 0.0, 0.0, -0.25, 0.125, 0.0]

    premier = evaluate.intervalle_bootstrap(differences)
    second = evaluate.intervalle_bootstrap(differences)
    # Et un module rechargé, donc un `random` neuf : la graine est passée
    # explicitement, elle ne dépend pas de l'état global du processus.
    troisieme = _evaluate().intervalle_bootstrap(differences)

    assert premier == second == troisieme


def test_l_intervalle_s_elargit_quand_les_ecarts_se_dispersent() -> None:
    """Un intervalle qui ne bougerait pas avec la dispersion ne mesurerait rien
    — c'est exactement le défaut du badge de pertinence, toujours vert."""
    evaluate = _evaluate()

    serre = evaluate.intervalle_bootstrap([0.1] * 20)
    disperse = evaluate.intervalle_bootstrap([1.0, -1.0] * 10)

    assert serre is not None and disperse is not None
    assert (disperse[1] - disperse[0]) > (serre[1] - serre[0])


def test_sans_paire_il_n_y_a_pas_d_intervalle() -> None:
    """Rendre [0, 0] affirmerait « aucune différence, avec certitude »."""
    assert _evaluate().intervalle_bootstrap([]) is None


# ─── Le refus, et il est le cœur du sujet ────────────────────────────────────

def test_deux_jeux_de_questions_differents_font_refuser_la_comparaison() -> None:
    """Une intersection tacite est la façon exacte dont on compare 100 questions
    en croyant en comparer 138."""
    evaluate = _evaluate()

    desaccord = evaluate.desaccord_de_jeu(
        _campagne("campagne_jeu_tronque"), _campagne("campagne_reference")
    )

    assert desaccord is not None
    # Le message NOMME l'écart : les deux tailles et les identifiants.
    assert "7 question(s)" in desaccord
    assert "10 dans la référence" in desaccord
    assert "G-008" in desaccord


def test_deux_jeux_identiques_ne_font_pas_refuser() -> None:
    """Le pendant : un refus qui se déclencherait toujours ne protégerait de
    rien, il désactiverait la comparaison."""
    evaluate = _evaluate()

    assert evaluate.desaccord_de_jeu(
        _campagne("campagne_gain_net"), _campagne("campagne_reference")
    ) is None


def test_un_identifiant_repete_fait_refuser() -> None:
    """Deux lignes de même identifiant rendent l'appariement ambigu, et le
    dictionnaire qui les indexe en perdrait une sans le dire."""
    evaluate = _evaluate()
    reference = _campagne("campagne_reference")
    doublonnee = [*reference, dict(reference[0])]

    desaccord = evaluate.desaccord_de_jeu(doublonnee, reference)

    assert desaccord is not None
    assert "répété" in desaccord
    assert "G-001" in desaccord


def test_la_comparaison_appariee_refuse_et_le_dit(capsys) -> None:
    """Le refus doit être imprimé et rendu, pas seulement pensé : c'est le
    booléen qui décide du code de sortie."""
    evaluate = _evaluate()
    chemin = _FIXTURES / "campagne_reference.json"

    resultat = evaluate.comparer_apparie(_campagne("campagne_jeu_tronque"), chemin)
    sortie = capsys.readouterr().out

    assert resultat is False
    assert "REFUSÉE" in sortie
    assert "G-008" in sortie
    # Et aucun chiffre de comparaison n'est affiché : refuser puis comparer
    # quand même serait pire que ne pas refuser.
    assert "Δ moyen" not in sortie


def test_une_reference_sans_lignes_par_question_refuse(tmp_path) -> None:
    """Les campagnes de `runs/` portent toutes leurs lignes, mais un fichier
    réduit à son résumé ne s'apparie pas — et comparer les seuls résumés est
    précisément ce qu'on cherche à éviter."""
    evaluate = _evaluate()
    chemin = tmp_path / "resume_seul.json"
    chemin.write_text(json.dumps({"resume": {"questions": 10, "mrr": 0.5}}), encoding="utf-8")

    assert evaluate.comparer_apparie(_campagne("campagne_reference"), chemin) is False


def test_la_comparaison_appariee_aboutit_sur_deux_jeux_identiques(capsys) -> None:
    """Le chemin nominal, et ce qu'il doit imprimer : le tableau, et les
    identifiants qui basculent."""
    evaluate = _evaluate()

    resultat = evaluate.comparer_apparie(
        _campagne("campagne_echange"), _FIXTURES / "campagne_reference.json"
    )
    sortie = capsys.readouterr().out

    assert resultat is True
    assert "10 questions communes" in sortie
    assert "rang_reciproque" in sortie
    assert "G-005" in sortie  # une question dégradée, nommée


# ─── Le couple réel du dépôt, celui qui a motivé le refus ────────────────────

def test_la_cible_historique_de_make_eval_serait_refusee() -> None:
    """**Le défaut, sur les fichiers du dépôt.**

    `make eval` comparait à `runs/reference.json`, que `runs/README.md` annonçait
    à 138 questions : le fichier n'en porte que **117**, 21 questions n'ayant pas
    abouti lors de cette campagne. Toute comparaison à cette cible confrontait
    donc 138 moyennes à 117 moyennes, en silence.

    Épinglage, pas un vœu : le jour où `reference.json` sera rejoué sur les 138
    questions, ce test devra être retiré — et avec lui la ligne du registre.
    """
    evaluate = _evaluate()

    def lire(nom):
        return json.loads((_RACINE / "runs" / nom).read_text(encoding="utf-8"))["questions"]

    desaccord = evaluate.desaccord_de_jeu(lire("final.json"), lire("reference.json"))

    assert desaccord is not None
    assert "138 question(s) dans la campagne" in desaccord
    assert "117 dans la référence" in desaccord


def test_la_nouvelle_cible_de_make_eval_s_apparie() -> None:
    """`runs/final.json` porte les 138 lignes du jeu doré : c'est la seule cible
    du dépôt qui s'apparie avec une campagne complète, et `make eval` la prend
    désormais."""
    evaluate = _evaluate()
    final = json.loads((_RACINE / "runs" / "final.json").read_text(encoding="utf-8"))
    dore = json.loads(
        (_FIXTURES / "golden_qa_generated.json").read_text(encoding="utf-8")
    )["questions"]

    assert {q["id"] for q in dore} == {r["id"] for r in final["questions"]}
    assert evaluate.desaccord_de_jeu(final["questions"], final["questions"]) is None


# ─── Le script comme commande ────────────────────────────────────────────────

def _lancer(*arguments, pythonpath: str | None = None):
    """Exécute le script comme le ferait un humain, dans un sous-processus.

    Un script n'est pas testé tant qu'il n'a pas été lancé comme une commande :
    en processus, l'import réussit parce que pytest tourne depuis la racine.
    PYTHONPATH retiré, seul un sous-processus reproduit la vraie invocation.

    `pythonpath` sert au seul cas qui a besoin d'un agent : il y place le faux
    `httpx` ci-dessous, à la place du vrai. C'est la seule façon d'atteindre le
    CODE DE SORTIE sans réseau — et le code de sortie est ce qu'un `make eval`
    lit, donc il ne s'observe que d'ici.
    """
    environnement = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    if pythonpath is not None:
        environnement["PYTHONPATH"] = pythonpath
    return subprocess.run(
        [sys.executable, str(_SCRIPT), *arguments],
        capture_output=True,
        text=True,
        cwd=str(_RACINE),
        env=environnement,
        check=False,
    )


# Faux `httpx`, réduit à EXACTEMENT ce que `evaluate.interroger` utilise :
# `httpx.post(...)`, puis `.raise_for_status()` et `.json()` sur la réponse. Un
# faux qui ne ressemble pas à la bibliothèque ne prouve rien d'elle — celui-ci
# ne prétend rien d'autre que ce contrat-là, qui est tout ce que le script
# touche. Il rend une réponse `/answer` minimale mais VALIDE : la campagne doit
# aboutir, sinon c'est le code 1 qu'on mesurerait, pas le code 2.
_FAUX_HTTPX = '''"""Faux httpx, posé sur PYTHONPATH pour un test de code de sortie."""


class _Reponse:
    def raise_for_status(self):
        return None

    def json(self):
        return {
            "answer": "La dispersion se mesure par l'écart-type [src:aaaaaaaaa1].",
            "contexts": [],
            "citations": [],
            "retrieved_element_ids": ["aaaaaaaaa1"],
            "retrieval_ms": 0,
            "generation_ms": 0,
            "dropped_contexts": 0,
        }


def post(url, json=None, timeout=None):
    return _Reponse()
'''


def _agent_simule(racine: pathlib.Path) -> str:
    """Installe le faux `httpx` et retourne le PYTHONPATH qui le sert."""
    (racine / "httpx.py").write_text(_FAUX_HTTPX, encoding="utf-8")
    return str(racine)


def _jeu_dore(chemin: pathlib.Path, *ids: str) -> pathlib.Path:
    chemin.write_text(
        json.dumps(
            {
                "questions": [
                    {"id": i, "question": "q", "gold_element_ids": ["aaaaaaaaa1"]} for i in ids
                ]
            }
        ),
        encoding="utf-8",
    )
    return chemin


def _campagne_fichier(chemin: pathlib.Path, *ids: str) -> pathlib.Path:
    lignes = [{"id": i, "rang_reciproque": 1.0} for i in ids]
    chemin.write_text(
        json.dumps({"resume": {"questions": len(lignes)}, "questions": lignes}),
        encoding="utf-8",
    )
    return chemin


def test_le_script_s_invoque(tmp_path) -> None:
    """`--help` suffit à attraper une erreur d'import ou d'`argparse` — le mode
    de panne qui a déjà tué un script de ce dépôt dès sa première ligne."""
    resultat = _lancer("--help")

    assert resultat.returncode == 0
    assert "--compare" in resultat.stdout


def test_sans_agent_joignable_le_script_sort_en_un(tmp_path) -> None:
    """Code 1 : aucune question n'a abouti. Il doit se distinguer du code 2 —
    « la comparaison a été refusée » — sans quoi un `make eval` rouge ne dit pas
    lequel des deux s'est produit.

    Le port 1 refuse la connexion sans attendre : aucun réseau n'est sollicité.
    """
    dore = tmp_path / "dore.json"
    dore.write_text(
        json.dumps(
            {"questions": [{"id": "G-001", "question": "q", "gold_element_ids": ["aaaaaaaaa1"]}]}
        ),
        encoding="utf-8",
    )

    resultat = _lancer("--api", "http://127.0.0.1:1", "--golden", str(dore), "--timeout", "2")

    assert resultat.returncode == 1
    assert "Aucune question n'a abouti" in resultat.stdout


def test_une_comparaison_refusee_sort_en_deux(tmp_path) -> None:
    """**Le code de sortie 2, asserté depuis le côté qui le PRODUIT.**

    C'est l'unique mécanisme qui fait qu'un `make eval` rouge signale un refus,
    et c'est la justification même de ce code. Vérifié par mutation : remplacer
    `return 0 if appariement_possible else 2` par `return 0` laissait toute la
    suite verte — une comparaison refusée serait passée en vert, c'est-à-dire
    exactement la panne que ce code existe pour empêcher.

    Le refus était gardé par cinq tests, mais tous du côté de la LOGIQUE
    (`desaccord_de_jeu`, `comparer_apparie`). Aucun ne descendait jusqu'au code
    rendu au shell. Un garde-fou qui ne joue que d'un côté est le défaut de
    l'espèce que ce dépôt corrige lot après lot.
    """
    pythonpath = _agent_simule(tmp_path)
    dore = _jeu_dore(tmp_path / "dore.json", "G-001")
    # La référence porte deux questions, le jeu une seule : les jeux diffèrent.
    reference = _campagne_fichier(tmp_path / "reference.json", "G-001", "G-002")
    sortie = tmp_path / "campagne.json"

    resultat = _lancer(
        "--golden", str(dore), "--compare", str(reference), "--out", str(sortie),
        pythonpath=pythonpath,
    )

    assert resultat.returncode == 2
    assert "REFUSÉE" in resultat.stdout
    # Et la campagne est écrite QUAND MÊME : elle coûte une demi-heure de
    # génération, et c'est la comparaison qui n'a pas eu lieu, pas la mesure.
    assert sortie.exists()
    assert json.loads(sortie.read_text(encoding="utf-8"))["resume"]["questions"] == 1


def test_une_comparaison_qui_aboutit_sort_en_zero(tmp_path) -> None:
    """Le pendant, sur le même chemin : sans lui, un `return 2` en dur serait
    vert au test précédent.

    `--help` sort aussi en 0, mais par `argparse`, qui s'arrête avant `main()` :
    il ne dit rien du code que rend la campagne elle-même.
    """
    pythonpath = _agent_simule(tmp_path)
    dore = _jeu_dore(tmp_path / "dore.json", "G-001")
    reference = _campagne_fichier(tmp_path / "reference.json", "G-001")

    resultat = _lancer(
        "--golden", str(dore), "--compare", str(reference), pythonpath=pythonpath
    )

    assert resultat.returncode == 0
    assert "REFUSÉE" not in resultat.stdout
    assert "1 questions communes" in resultat.stdout
