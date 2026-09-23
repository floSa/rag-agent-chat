"""Le banc qui mesure la sélection, et ce qui le ferait mentir.

`scripts/mesurer_selection.py` rejoue le quatrième étage de la chaîne —
`AUTO_SELECT_TOP_K`, `graph.py:204` — pour plusieurs valeurs de k. Son chiffre
est un rappel, donc une INTERSECTION d'ensembles, et trois façons de le rendre
faux sans lever la moindre erreur :

1. **oublier la déduplication par section.** `node_reconstruct_context` écarte
   une graine dont la section a déjà été vue : k graines peuvent tomber dans
   MOINS de k sections. Un banc qui les compterait toutes annoncerait un
   contexte plus large que celui qui part réellement ;
2. **oublier la troncature.** Un banc qui rendrait la même chose pour k=1 et
   k=10 ne mesurerait pas k — il mesurerait le classement entier, et la courbe
   serait plate pour une raison qui n'a rien à voir avec la sélection ;
3. **publier un intervalle qui sort de [0, 1].** À n = 130 et un taux proche de
   1, l'approximation normale rend une borne haute au-dessus de 1 : l'écart
   deviendrait injugeable au moment précis où il faut le juger.

Le témoin est INERTE et il porte SON COMPTE : six graines réparties dans trois
sections, et le nombre de sections attendu est écrit pour chaque k. Sans ce
compte, un banc cassé rendrait « une liste » et le test la trouverait plausible.
"""

import importlib.util
import pathlib
import sys
from types import SimpleNamespace

import pytest

_RACINE = pathlib.Path(__file__).resolve().parents[2]
_SCRIPT = _RACINE / "scripts" / "mesurer_selection.py"


def _banc():
    """Charge le script sans faire de `scripts/` un paquet."""
    spec = importlib.util.spec_from_file_location("mesurer_selection", _SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["mesurer_selection"] = module
    spec.loader.exec_module(module)
    return module


# SIX graines, TROIS sections, deux graines par section. Le compte de sections
# uniques attendu est écrit pour chaque k : c'est lui qui distingue un banc qui
# tronque et déduplique d'un banc qui fait l'un, l'autre, ou ni l'un ni l'autre.
_GRAINES = ["aaaaaaaaa0", "aaaaaaaaa1", "bbbbbbbbb0", "bbbbbbbbb1", "ccccccccc0", "ccccccccc1"]
_SECTIONS = {
    "aaaaaaaaa0": SimpleNamespace(section_id="S1", element_id="aaaaaaaaa0"),
    "aaaaaaaaa1": SimpleNamespace(section_id="S1", element_id="aaaaaaaaa1"),
    "bbbbbbbbb0": SimpleNamespace(section_id="S2", element_id="bbbbbbbbb0"),
    "bbbbbbbbb1": SimpleNamespace(section_id="S2", element_id="bbbbbbbbb1"),
    "ccccccccc0": SimpleNamespace(section_id="S3", element_id="ccccccccc0"),
    "ccccccccc1": SimpleNamespace(section_id="S3", element_id="ccccccccc1"),
}
# k → (sections uniques attendues, leurs identifiants dans l'ordre)
_ATTENDU = {
    1: (1, ["S1"]),
    2: (1, ["S1"]),
    3: (2, ["S1", "S2"]),
    4: (2, ["S1", "S2"]),
    5: (3, ["S1", "S2", "S3"]),
    6: (3, ["S1", "S2", "S3"]),
    10: (3, ["S1", "S2", "S3"]),
}


@pytest.mark.parametrize("k", sorted(_ATTENDU))
def test_le_compte_de_sections_par_k_est_celui_du_temoin(k):
    """La troncature ET la déduplication, tenues ensemble sur un compte écrit.

    Les deux sont asserties au même endroit parce qu'elles peuvent se
    compenser : un banc sans troncature ni déduplication rendrait 3 sections à
    k=10, ce qui est la bonne réponse — pour deux mauvaises raisons.
    """
    attendu_n, attendu_ids = _ATTENDU[k]
    retenues = _banc().sections_pour_k(_GRAINES, _SECTIONS, k)
    assert [c.section_id for c in retenues] == attendu_ids
    assert len(retenues) == attendu_n


def test_k_petit_et_k_grand_ne_rendent_pas_la_meme_chose():
    """Le banc doit DISTINGUER les k, sinon il mesure autre chose que k.

    Assertion de propriété et non d'instantané : ce qui est exigé est la
    stricte croissance du nombre de sections entre k=1 et le plafond du témoin,
    pas deux valeurs particulières.
    """
    banc = _banc()
    petit = banc.sections_pour_k(_GRAINES, _SECTIONS, 1)
    grand = banc.sections_pour_k(_GRAINES, _SECTIONS, len(_GRAINES))
    assert len(petit) < len(grand)


def test_une_graine_sans_section_est_sautee_sans_decaler_les_suivantes():
    """Une reconstruction qui a échoué ne doit ni lever, ni manger un rang.

    `node_reconstruct_context` absorbe l'échec et la source DISPARAÎT. Le banc
    fait pareil — et un `sections[eid]` sans garde lèverait `KeyError` au milieu
    d'une campagne de 130 questions.
    """
    sections = {eid: ctx for eid, ctx in _SECTIONS.items() if eid != "aaaaaaaaa0"}
    retenues = _banc().sections_pour_k(_GRAINES, sections, 3)
    assert [c.section_id for c in retenues] == ["S1", "S2"]


def test_l_intervalle_reste_dans_les_bornes_d_une_proportion():
    """Wilson, et pas l'approximation normale — c'est le régime du banc.

    À 130 succès sur 130, l'intervalle normal rend [1.0, 1.0] : largeur nulle,
    donc « aucune incertitude » sur une mesure qui en porte. Wilson rend une
    borne basse STRICTEMENT inférieure à 1, et c'est elle qui empêche de lire
    un plafond comme une certitude.
    """
    banc = _banc()
    bas, haut = banc.wilson(130, 130)
    assert 0.0 <= bas < 1.0
    assert haut == pytest.approx(1.0)
    for succes in (0, 1, 65, 129, 130):
        bas, haut = banc.wilson(succes, 130)
        assert 0.0 <= bas <= succes / 130 <= haut <= 1.0


def test_un_cache_de_traductions_qui_ne_couvre_pas_le_jeu_est_refuse(tmp_path, monkeypatch, capsys):
    """Le refus qui a servi : un cache de la BONNE TAILLE et du MAUVAIS jeu.

    Le 23 septembre 2026, `runs/.traductions.json` portait 130 entrées pour un
    jeu de 130 questions — et l'intersection exacte des clés valait **0**. Sans
    ce refus, le banc aurait joué toutes ses questions sans traduction, aurait
    déplacé le rappel translinguistique, et aurait conclu.
    """
    import json

    banc = _banc()
    jeu = tmp_path / "jeu.yaml"
    jeu.write_text(
        "questions:\n"
        "- id: Q-1\n  question: Une question\n  gold_element_ids: [aaaaaaaaa0]\n",
        encoding="utf-8",
    )
    cache = tmp_path / "traductions.json"
    cache.write_text(json.dumps({"une AUTRE question": "another one"}), encoding="utf-8")
    monkeypatch.setattr(banc, "CACHE_TRADUCTIONS", cache)
    monkeypatch.setattr(sys, "argv", ["mesurer_selection.py", "--golden", str(jeu)])

    assert banc.main() == 2
    # LE MESSAGE, pas le code seul : un `return 2` peut venir d'un autre chemin
    # — le cache absent en rend un aussi — et le banc dirait alors la mauvaise
    # cause au pilote qui lit sa sortie.
    assert "sans traduction en cache" in capsys.readouterr().out
