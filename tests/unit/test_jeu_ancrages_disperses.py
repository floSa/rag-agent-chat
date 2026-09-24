"""Le jeu à ancrages multiples et dispersés, et les trois façons de le rendre creux.

Le §4.67 du registre a mesuré que le jeu de réglage est **aveugle à la
sélection** : ses questions sont écrites pour UN passage, ce passage sort au
rang 1, et **une** section reconstruite les réussit toutes. Le jeu gardé ici
existe pour mesurer le quatrième étage, et trois façons de le rendre creux ne
lèveraient aucune erreur :

1. **deux ancrages dans la MÊME section.** `reconstruct_section` rend la section
   ET ses voisines : deux ancrages voisins arriveraient ensemble, par UNE seule
   entrée du classement, et le jeu serait mono-ancrage déguisé ;
2. **une mesure de présence du texte toujours vraie.** Comparer des jetons de
   deux lettres — « de », « of » — rend n'importe quel markdown « porteur » de
   n'importe quel chunk, et l'écart entre identifiant et texte se lirait comme
   une trouvaille ;
3. **un histogramme qui confond l'absent et le lointain.** Un ancrage jamais
   entré dans les candidats et un ancrage entré au rang 40 ne se réparent pas de
   la même façon, et les fondre dans un « au-delà » efface la distinction que le
   banc existe pour rendre.

Les témoins sont INERTES et portent LEUR COMPTE : sans compte écrit, un banc
cassé rend « une liste » et le test la trouve plausible — la leçon du témoin de
`test_mesure_de_la_selection.py`.
"""

import importlib.util
import pathlib
import re
import sys
from types import SimpleNamespace

import pytest
import yaml

_RACINE = pathlib.Path(__file__).resolve().parents[2]
_JEU = _RACINE / "tests" / "fixtures" / "jeu_ancrages_disperses.yaml"
_BANC = _RACINE / "scripts" / "mesurer_dispersion.py"
_GENERATEUR = _RACINE / "scripts" / "generer_jeu_disperse.py"

# La forme contractuelle d'un `element_id`, exigence 3 du contrat avec le
# pipeline. Recopiée ici pour que le garde soit lisible au site où il s'exerce.
_FORME_ELEMENT_ID = re.compile(r"^[a-f0-9]{10}$")

# LE PLANCHER DEMANDÉ AU LOT, et il est écrit ici pour que le jeu ne puisse pas
# maigrir en silence à la prochaine régénération.
_MIN_QUESTIONS = 40


def _charger(chemin: pathlib.Path):
    spec = importlib.util.spec_from_file_location(chemin.stem, chemin)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[chemin.stem] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def jeu():
    return yaml.safe_load(_JEU.read_text(encoding="utf-8"))


# ─── Le jeu lui-même ─────────────────────────────────────────────────────────


def test_le_jeu_porte_assez_de_questions_ancrees(jeu):
    """Le plancher du lot, sur les questions qui portent RÉELLEMENT un ancrage."""
    ancrees = [q for q in jeu["questions"] if q.get("gold_element_ids")]
    assert len(ancrees) >= _MIN_QUESTIONS
    assert len(ancrees) == jeu["_statistiques"]["questions"]


def test_chaque_question_porte_au_moins_deux_ancrages_distincts(jeu):
    """C'est la propriété qui sépare ce jeu du jeu de réglage, et elle est gardée.

    Un seul ancrage, ou deux fois le même, rendrait la question réussie dès
    qu'UNE section arrive — exactement le plateau que ce jeu vient corriger.
    """
    for q in jeu["questions"]:
        ancrages = q["gold_element_ids"]
        assert len(ancrages) >= 2, q["id"]
        assert len(set(ancrages)) == len(ancrages), q["id"]


def test_les_deux_ancrages_vivent_dans_des_sections_differentes(jeu):
    """Les `section_id` sont ceux que le GRAPHE a rendus, pas les métadonnées du chunk.

    Le générateur les relève par `reconstruct_section` et les écrit dans
    `_origine` ; les confondre avec le `reference_id` de ChromaDB laisserait
    passer deux ancrages que le graphe rattache au même en-tête.
    """
    for q in jeu["questions"]:
        a = q["_origine"]["ancrage_a"]
        b = q["_origine"]["ancrage_b"]
        assert a["section_id"] != b["section_id"], q["id"]
        assert a["element_id"] != b["element_id"], q["id"]
        assert a["element_id"] in q["gold_element_ids"], q["id"]
        assert b["element_id"] in q["gold_element_ids"], q["id"]


def test_les_ancrages_sont_en_forme(jeu):
    """Un identifiant mal formé rendrait un rappel nul sans dire pourquoi."""
    for q in jeu["questions"]:
        for eid in q["gold_element_ids"]:
            assert _FORME_ELEMENT_ID.match(eid), f"{q['id']}: {eid}"


def test_aucune_question_n_est_declaree_relue(jeu):
    """`reviewed: false` partout tant qu'aucun humain n'a relu le jeu."""
    assert all(q["reviewed"] is False for q in jeu["questions"])


def test_la_reserve_et_la_limite_voyagent_avec_le_fichier(jeu):
    """La réserve et la LIMITE de la méthode sont dans le fichier, pas dans un rapport.

    Le jeu de réglage a été lu pendant trois semaines comme s'il arbitrait un
    réglage ; ce qui manquait n'était pas la mesure, c'était la phrase qui dit
    ce que le jeu ne peut pas faire — et elle doit voyager avec lui.
    """
    reserve = jeu["_reserve"]
    assert "TOUS les ancrages" in reserve
    assert "QUESTIONS" in reserve
    lisez_moi = "\n".join(jeu["_lisez_moi"])
    # La circularité DÉPLACÉE, et non supprimée : c'est la limite de la méthode,
    # et un jeu qui la tairait se lirait comme un instrument sans biais.
    assert "DEPLACEE" in lisez_moi or "DÉPLACÉE" in lisez_moi
    assert "reviewed: false" in lisez_moi


def test_les_statistiques_concordent_avec_le_contenu(jeu):
    """Un en-tête qui ment sur son propre fichier est pire qu'un en-tête absent."""
    stats = jeu["_statistiques"]
    assert stats["ancrages"] == sum(len(q["gold_element_ids"]) for q in jeu["questions"])
    langues: dict[str, int] = {}
    for q in jeu["questions"]:
        langues[q["language"]] = langues.get(q["language"], 0) + 1
    assert stats["par_langue_de_la_question"] == langues


# ─── Le banc ─────────────────────────────────────────────────────────────────


def test_les_jetons_courts_sont_ecartes():
    """Sans ce filtre, la mesure de présence du TEXTE serait toujours vraie.

    Contrôle positif dans les deux sens : le jeton long est gardé, le court est
    écarté. Un test qui n'asserterait que l'absence passerait sur une fonction
    qui ne rend jamais rien.
    """
    banc = _charger(_BANC)
    rendus = banc.jetons("de la of gouvernance MLflow")
    assert "gouvernance" in rendus
    assert "mlflow" in rendus
    assert "de" not in rendus
    assert "la" not in rendus
    assert "of" not in rendus


def test_les_accents_ne_separent_pas_deux_ecritures_du_meme_mot():
    """Le markdown soumis et le chunk ne portent pas toujours la même accentuation."""
    banc = _charger(_BANC)
    assert banc.jetons("déploiement") == banc.jetons("deploiement")


def test_le_rang_est_1_indexe_et_absent_vaut_none():
    """Un rang 0-indexé se lirait de travers à côté des tableaux du §4.67."""
    banc = _charger(_BANC)
    classement = [SimpleNamespace(element_id=e) for e in ("aaaaaaaaa0", "bbbbbbbbb0")]
    assert banc.rang_de("aaaaaaaaa0", classement) == 1
    assert banc.rang_de("bbbbbbbbb0", classement) == 2
    assert banc.rang_de("ccccccccc0", classement) is None


# TÉMOIN INERTE, ET IL PORTE SON COMPTE. Cinq ancrages, cinq rangs choisis pour
# tomber un par tranche, plus un absent : le total attendu est écrit tranche par
# tranche, donc un histogramme qui décalerait ses bornes d'un cran rougirait.
_RANGS_TEMOIN = [
    {"rangs": {"a": {"rerank": 1}, "b": {"rerank": 2}}},
    {"rangs": {"c": {"rerank": 3}, "d": {"rerank": 7}}},
    {"rangs": {"e": {"rerank": 40}, "f": {"rerank": None}}},
]
_HISTOGRAMME_ATTENDU = {
    "<= 1": 1, "<= 2": 1, "<= 3": 1, "<= 5": 0, "<= 10": 1,
    "<= 20": 0, "<= 50": 1, "au-dela": 0, "absent": 1,
}


def test_l_histogramme_place_chaque_rang_dans_sa_tranche_et_compte_l_absent_a_part():
    """Le compte est écrit tranche par tranche : une borne décalée rougit.

    Et `absent` est compté SÉPARÉMENT : un ancrage jamais entré dans les
    candidats ne se répare pas comme un ancrage entré au rang 40.
    """
    banc = _charger(_BANC)
    assert banc.histogramme_des_rangs(_RANGS_TEMOIN, "rerank") == _HISTOGRAMME_ATTENDU
    assert sum(_HISTOGRAMME_ATTENDU.values()) == 6


# ─── Le générateur ───────────────────────────────────────────────────────────


def _contexte(section_id, presents):
    markdown = "\n".join(f"[src:{e}]" for e in presents)
    return SimpleNamespace(section_id=section_id, markdown=markdown)


@pytest.mark.parametrize(
    ("markdown_a", "markdown_b", "sections", "attendu"),
    [
        # Disjointes dans les deux sens, chacune portant SON ancrage : la seule
        # configuration acceptable.
        (["aaaaaaaaa0"], ["bbbbbbbbb0"], ("S1", "S2"), True),
        # B est ramené par la reconstruction de A : une seule entrée du
        # classement suffirait, la question ne testerait pas la sélection.
        (["aaaaaaaaa0", "bbbbbbbbb0"], ["bbbbbbbbb0"], ("S1", "S2"), False),
        # A est ramené par la reconstruction de B : le sens inverse, et il doit
        # rougir aussi. Une condition testée dans un seul sens laisse l'autre
        # mourir en silence.
        (["aaaaaaaaa0"], ["bbbbbbbbb0", "aaaaaaaaa0"], ("S1", "S2"), False),
        # LE CONTRÔLE POSITIF DE LA CONDITION : une reconstruction qui ne rend
        # RIEN satisfait la disjonction. Sans l'exigence « chaque ancrage est
        # dans SA propre reconstruction », le jeu se remplirait de paires que
        # rien n'a vérifiées.
        ([], [], ("S1", "S2"), False),
        # Même section des deux côtés : la propriété centrale du jeu tombe.
        (["aaaaaaaaa0"], ["bbbbbbbbb0"], ("S1", "S1"), False),
    ],
)
def test_la_condition_de_reconstruction_tient_ses_quatre_directions(
    monkeypatch, markdown_a, markdown_b, sections, attendu
):
    """Les deux sens de la disjonction, le contrôle positif, et l'unicité de section."""
    generateur = _charger(_GENERATEUR)
    rendus = {
        "aaaaaaaaa0": _contexte(sections[0], markdown_a),
        "bbbbbbbbb0": _contexte(sections[1], markdown_b),
    }
    import src.agent.graph_context as graph_context

    monkeypatch.setattr(graph_context, "reconstruct_section", lambda eid: rendus[eid])
    ok, _ = generateur.sections_reconstruites_disjointes("aaaaaaaaa0", "bbbbbbbbb0")
    assert ok is attendu


_PASSAGE_A = {
    "texte": "La gouvernance des modeles impose un registre unique et une revue documentee "
             "avant toute mise en service du modele candidat."
}
_PASSAGE_B = {
    "texte": "Le deploiement progressif compare le challenger au champion sur le trafic reel "
             "avant de basculer la totalite des requetes."
}
_BONNE = {
    "question": "Quelle revue de gouvernance des modeles precede le deploiement progressif "
                "du challenger face au champion ?",
    "preuve_a": "La gouvernance des modeles impose un registre unique",
    "preuve_b": "Le deploiement progressif compare le challenger au champion",
}


def test_une_question_bien_formee_est_acceptee():
    """LE CONTRÔLE POSITIF DES GARDES LEXICAUX.

    Sans lui, des gardes qui refuseraient TOUT rendraient un jeu vide, et chacun
    des refus ci-dessous passerait pour une preuve.
    """
    generateur = _charger(_GENERATEUR)
    assert generateur._question_tient_debout(_BONNE, _PASSAGE_A, _PASSAGE_B) is not None


@pytest.mark.parametrize(
    ("champ", "valeur"),
    [
        # Une preuve REFORMULÉE, pas recopiée : rien ne garantit plus que le
        # passage porte le fait.
        ("preuve_a", "La gouvernance impose une validation externe permanente"),
        # La preuve de B cherchée dans B : si le modèle y met du texte de A, les
        # deux faits viennent du même extrait et la question est mono-ancrage.
        ("preuve_b", "La gouvernance des modeles impose un registre unique"),
        # Une question vide de vocabulaire distinctif : n'importe quel passage
        # du corpus « y répondrait ».
        ("question", "Comment faire pour que cela fonctionne correctement dans tous les cas ?"),
        # UNE QUESTION QUI NE PARLE QUE DE A, ET ELLE EST LA DIRECTION QUI
        # MANQUAIT. Trouvée par mutation contre ce fichier : retirer l'exigence
        # de vocabulaire partagé avec B laissait les trois scènes ci-dessus
        # VERTES, parce que la question générique tombait déjà sur l'exigence
        # côté A. Une garde à deux côtés doit être éprouvée des deux côtés.
        # Elle est écrite POUR NE PAS mourir par un autre chemin : une première
        # version reprenait les mots de `preuve_a`, donc elle tombait sur la
        # garde « la question recopie sa preuve » et la mutation restait VERTE.
        ("question", "Quelle revue documentee la gouvernance exige-t-elle avant la "
                     "mise en service du modele candidat ?"),
    ],
)
def test_les_gardes_lexicaux_refusent_chacun_son_defaut(champ, valeur):
    generateur = _charger(_GENERATEUR)
    donnees = dict(_BONNE)
    donnees[champ] = valeur
    assert generateur._question_tient_debout(donnees, _PASSAGE_A, _PASSAGE_B) is None


# LA GRANDEUR CENTRALE, ET SON TÉMOIN PORTE SON COMPTE. Quatre états écrits à la
# main, et le verdict attendu pour chacun : sans compte écrit, un banc qui
# rendrait `any` au lieu de `all` passerait — c'est la confusion qui a fait lire
# le plateau du jeu de réglage comme « 3 suffit » (§4.67).
_ETATS = {
    "les deux arrivent": (
        {"a": {"identifiant": True, "texte": True}, "b": {"identifiant": True, "texte": True}},
        {"identifiant": True, "texte": True},
    ),
    "un seul arrive": (
        {"a": {"identifiant": True, "texte": True}, "b": {"identifiant": False, "texte": False}},
        {"identifiant": False, "texte": False},
    ),
    "aucun n'arrive": (
        {"a": {"identifiant": False, "texte": False}, "b": {"identifiant": False, "texte": False}},
        {"identifiant": False, "texte": False},
    ),
    # Un ancrage sans texte dans les vecteurs : sa présence par TEXTE n'est pas
    # mesurable, elle est écartée du `all` — mais une question dont AUCUN
    # ancrage n'est mesurable ne doit pas être comptée réussie.
    "un ancrage non mesurable": (
        {"a": {"identifiant": True, "texte": True}, "b": {"identifiant": True, "texte": None}},
        {"identifiant": True, "texte": True},
    ),
    "aucun ancrage mesurable": (
        {"a": {"identifiant": True, "texte": None}, "b": {"identifiant": True, "texte": None}},
        {"identifiant": True, "texte": False},
    ),
}


@pytest.mark.parametrize("cas", sorted(_ETATS))
@pytest.mark.parametrize("nature", ["identifiant", "texte"])
def test_une_question_n_est_complete_que_si_tous_ses_ancrages_arrivent(cas, nature):
    """`all`, jamais `any` — et les deux natures, sur les mêmes cinq états."""
    ancrages, attendu = _ETATS[cas]
    assert _charger(_BANC).question_complete(ancrages, nature) is attendu[nature]


def test_l_en_tete_du_jeu_est_celui_que_son_producteur_ecrit(jeu):
    """Le `_lisez_moi` et la `_reserve` du fichier sont ceux du générateur.

    DEUX SITES QUI DIVERGENT SANS RIEN DIRE, c'est la panne que ce garde
    interdit. La méthode et sa limite sont écrites dans `generer_jeu_disperse.py`
    et recopiées dans le fichier ; corriger l'une sans l'autre laisserait le
    lecteur du jeu sur une description périmée de ce qu'il tient. Le garde compare
    la CHARGE — les deux listes, les deux chaînes — et non la forme du YAML : un
    reformatage ne le fait pas rougir, une divergence de fond si.
    """
    generateur = _charger(_GENERATEUR)
    assert jeu["_lisez_moi"] == generateur._LISEZ_MOI
    assert jeu["_reserve"] == generateur._RESERVE
