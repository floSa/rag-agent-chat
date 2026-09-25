"""LA FUSION REELLE des sous-requetes, et les sept façons de la mal mesurer.

Le §4.77 a mesuré un **oracle** de décomposition — 86 ancrages et 28 questions
complètes sur 60 — et il a écrit sa propre réserve : *l'affectation est prise au
mieux des deux permutations, une décomposition réelle n'aurait pas ce choix*.
`scripts/mesurer_fusion_sous_questions.py` mesure la liste que cette
décomposition réelle rendrait, et une telle mesure se casse de sept façons dont
aucune ne lève d'erreur :

1. **UNE DÉCOMPOSITION QUI N'EN EST PAS UNE, COMPTÉE COMME UNE VARIANTE.** Le
   modèle qui recopie la question rend une « fusion » qui ne diffère de la
   requête unique que par le bruit. La règle du repli est donc éprouvée sur ses
   QUATRE natures, chacune par un témoin qui la porte.
2. **UNE FUSION QUI N'EN EST PAS UNE.** Un passage trouvé par les DEUX
   sous-questions doit remonter au-dessus d'un passage trouvé par une seule ;
   une concaténation rendrait le même nombre de candidats sans rien fusionner.
3. **UN RERANKING PAR SOUS-QUESTION QUI MOYENNE.** Moyenner punit le passage qui
   répond parfaitement à UN besoin, c'est-à-dire exactement ce que la
   décomposition est censée réparer. Le témoin oppose les deux lectures.
4. **UN CONTRÔLE POSITIF QUI NE COMPARE QUE DES COMPTES.** C'est la leçon du
   §4.77 : deux bancs mesurant deux jeux peuvent rendre 53 et 7 sans qu'un seul
   rang ne coïncide. Le témoin fait ACCORDER les comptes et DIVERGER un rang.
5. **UNE QUESTION SANS ANCRAGE DÉCLARÉE COMPLÈTE.** `all()` sur un dictionnaire
   vide est vrai, et une question dont aucun ancrage n'est mesurable passerait
   pour un succès à toutes les variantes.
6. **UN SOLDE NET À LA PLACE DES QUESTIONS PERDUES.** +15 dispersées et −10
   simples font +5, et ce +5 est un mensonge. Les deux listes sont exigées
   NOMMÉMENT.
7. **UN PROMPT QUI DIT COMBIEN DE BESOINS LA QUESTION PORTE.** L'oracle du §4.77
   l'affirmait ; un décomposeur réel ne le sait pas, et le lui dire couperait en
   deux toute question à besoin unique — rendant la non-régression illisible.

Les témoins portent LEUR COMPTE, et le seuil du haut est éprouvé DANS LES DEUX
SENS : un garde qui n'accepte jamais est vert pour rien.
"""

import importlib.util
import json
import pathlib
import sys

import pytest

_RACINE = pathlib.Path(__file__).resolve().parents[2]
_BANC = _RACINE / "scripts" / "mesurer_fusion_sous_questions.py"

# LES DEUX CHIFFRES DU §4.77 pour la requête unique de production sur le jeu
# dispersé, recopiés ici pour que le garde soit lisible au site où il s'exerce.
_PRODUCTION_4_77 = {"ancrages_dans_le_haut": 53, "questions_completes": 7}


def _charger(chemin: pathlib.Path):
    spec = importlib.util.spec_from_file_location(chemin.stem, chemin)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[chemin.stem] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def banc():
    return _charger(_BANC)


def _chunk(chunk_id: str, element_id: str, texte: str = "corps"):
    """Un candidat minimal, et il est un VRAI `ChunkResult`.

    Pas un double : `fuse` et `dedupe_by_element` lisent `chunk_id`,
    `element_id` et `document_key`, et un double qui porterait seulement les
    trois mesurerait l'accord de mes attributs avec eux-mêmes plutôt que la
    fusion de production.
    """
    from src.api.schemas import ChunkResult

    return ChunkResult(
        chunk_id=chunk_id,
        element_id=element_id,
        graph_node_id=f"n-{element_id}",
        document=texte,
        filename="f.md",
        source_path=f"livre/{element_id}.md",
        page_no=1,
        label="paragraph",
        distance=1.0,
    )


# ─── 1. LA RÈGLE DU « rien à décomposer », ses QUATRE natures ────────────────


@pytest.mark.parametrize(
    ("nature", "question", "sous_questions", "utilisable"),
    [
        # LE CAS NOMINAL, et il est le contrôle positif de toute la règle : sans
        # lui, une règle qui refuserait TOUT serait verte sur les trois autres.
        (
            "decomposee",
            "Which deployment strategy limits blast radius, and which metric proves it?",
            [
                "Which deployment strategy limits the blast radius of a bad release?",
                "Which metric proves that a release did not degrade the service?",
            ],
            True,
        ),
        # LA PANNE DU PRODUCTEUR, qui n'est PAS une question indécomposable. Les
        # fondre cacherait un taux d'échec dans un taux de questions simples.
        ("vide", "Which deployment strategy limits blast radius?", [], False),
        ("vide", "Which deployment strategy limits blast radius?", ["", "   "], False),
        # LA QUESTION À BESOIN UNIQUE, et c'est le cas nominal des deux jeux de
        # non-régression : le modèle rend la question seule.
        (
            "une_seule",
            "Which deployment strategy limits blast radius?",
            ["Which deployment strategy limits blast radius?"],
            False,
        ),
        # LA QUESTION RECOPIÉE EN DEUX EXEMPLAIRES. Deux sous-questions, donc la
        # marche précédente ne l'attrape pas ; et pourtant fusionner deux copies
        # de la question ne diffère de la requête unique que par le bruit.
        (
            "quasi_identique",
            "Which deployment strategy limits blast radius?",
            [
                "Which deployment strategy limits blast radius?",
                "Blast radius: which deployment strategy limits it?",
            ],
            False,
        ),
    ],
)
def test_la_regle_du_repli_nomme_les_quatre_natures(
    banc, nature, question, sous_questions, utilisable
):
    obtenu, nom = banc.decomposition_utilisable(question, sous_questions)
    assert (obtenu, nom) == (utilisable, nature)


def test_une_seule_sous_question_quasi_identique_ne_suffit_pas_a_dire_quasi_identique(banc):
    """UNE sous-question recopiée se lit `une_seule`, jamais `quasi_identique`.

    L'ordre des marches est la définition : les deux refusent, mais ils ne
    disent pas la même chose du producteur, et un bilan qui les confondrait ne
    pourrait plus distinguer « le modèle n'a vu qu'un besoin » de « le modèle a
    recopié la question deux fois ».
    """
    question = "Which deployment strategy limits blast radius?"
    assert banc.decomposition_utilisable(question, [question]) == (False, "une_seule")


def test_une_seule_des_deux_sous_questions_qui_differe_suffit_a_decomposer(banc):
    """LE SEUIL EST EXIGÉ DE TOUTES, ET LE GARDE L'ÉPROUVE DES DEUX CÔTÉS.

    `all(...)` et non `any(...)` : une décomposition dont UNE branche recopie la
    question et dont l'autre porte un besoin distinct est une décomposition
    réelle — la seconde branche ramène des passages que la question entière ne
    ramenait pas. La refuser ferait retomber sur la requête unique des cas où la
    fusion a quelque chose à fusionner.
    """
    question = "Which deployment strategy limits blast radius?"
    sous = [question, "How is the rollback budget computed for a canary release?"]
    assert banc.decomposition_utilisable(question, sous) == (True, "decomposee")


def test_un_texte_sans_jeton_n_est_pas_quasi_identique(banc):
    """`jaccard` rend 0,0 et non 1,0 sur un texte vide de jetons.

    Une sous-question sans jeton mesurable déclarée quasi identique ferait
    retomber sur la requête unique une décomposition VIDE, qui doit au contraire
    se compter comme une panne du producteur.
    """
    assert banc.jaccard("", "anything at all") == 0.0
    assert banc.jaccard("a b c", "") == 0.0
    assert banc.jaccard("blast radius deployment", "blast radius deployment") == 1.0


# ─── 2. LA FUSION, ET ELLE DOIT FAIRE REMONTER CE QUE DEUX LISTES PORTENT ────


def test_la_fusion_fait_remonter_le_candidat_vu_par_les_deux_sous_questions(banc):
    """LE TÉMOIN DE LA FUSION, et il est construit pour qu'une CONCATÉNATION échoue.

    `commun` est au rang 2 dans les deux listes ; `tete_a` et `tete_b` sont au
    rang 1 dans UNE seule. Une concaténation, ou une fusion qui garderait le
    meilleur rang, mettrait `tete_a` en tête. Le RRF de production met `commun`
    devant, parce qu'il est le seul que les deux classements portent.
    """
    tete_a, tete_b = _chunk("c-a", "aaaaaaaaaa"), _chunk("c-b", "bbbbbbbbbb")
    commun = _chunk("c-x", "xxxxxxxxxx")
    fusionnes = banc.fusionner_les_classements([[tete_a, commun], [tete_b, commun]], 10)
    assert [c.chunk_id for c in fusionnes][0] == "c-x"
    assert sorted(c.chunk_id for c in fusionnes) == ["c-a", "c-b", "c-x"]


def test_la_fusion_ignore_les_classements_vides_sans_ignorer_les_autres(banc):
    """Une sous-question qui ne ramène rien ne doit pas vider la fusion.

    Et le contrôle est dans les deux sens : la liste non vide passe ENTIÈRE, et
    la fusion de rien du tout rend une liste vide plutôt que de lever.
    """
    un = _chunk("c-1", "1111111111")
    assert [c.chunk_id for c in banc.fusionner_les_classements([[], [un]], 10)] == ["c-1"]
    assert banc.fusionner_les_classements([[], []], 10) == []


def test_la_fusion_est_bornee_par_le_top_k_demande(banc):
    """La liste fondue est coupée au `top_k` de production, jamais plus longue.

    Sans cette coupe, la variante donnerait au reranker plus de candidats que la
    requête unique, et le gain mesuré mêlerait la décomposition à un
    élargissement de profondeur — ce que le §4.77 a justement mesuré à part.
    """
    listes = [[_chunk(f"c-{i}", f"{i:010d}") for i in range(8)]]
    assert len(banc.fusionner_les_classements(listes, 3)) == 3


# ─── 3. LE RERANKING PAR SOUS-QUESTION, ET C'EST LE MAXIMUM ─────────────────


def test_le_rerank_par_sous_question_garde_le_meilleur_score_et_non_la_moyenne(
    banc, monkeypatch
):
    """LE TÉMOIN OPPOSE LES DEUX LECTURES, ET UNE SEULE PEUT ÊTRE VERTE.

    `precis` répond parfaitement à la SECONDE sous-question (9,0) et pas du tout
    à la première (−5,0) : moyenne 2,0. `tiede` répond mollement aux deux (3,0 et
    3,0) : moyenne 3,0. Une moyenne classerait donc `tiede` en tête, et le banc
    mesurerait une préférence pour les passages tièdes sur les deux besoins —
    exactement le défaut que la décomposition doit réparer. Le maximum met
    `precis` devant, et le compte de paires scorées est asserté avec lui : un
    reranking qui n'aurait joué qu'une sous-question rendrait le bon ordre pour
    une mauvaise raison.
    """
    precis, tiede = _chunk("c-p", "pppppppppp"), _chunk("c-t", "tttttttttt")
    scores = {("s1", "c-p"): -5.0, ("s1", "c-t"): 3.0, ("s2", "c-p"): 9.0, ("s2", "c-t"): 3.0}
    appels: list[str] = []

    def _rerank_double(question, chunks):
        appels.append(question)
        for chunk in chunks:
            chunk.rerank_score = scores[(question, chunk.chunk_id)]
        return sorted(chunks, key=lambda c: c.rerank_score or 0.0, reverse=True)

    import src.agent.retriever as retriever

    monkeypatch.setattr(retriever, "rerank", _rerank_double)
    classement, paires = banc.rerank_au_meilleur_score(["s1", "s2"], [precis, tiede])

    assert appels == ["s1", "s2"], "les DEUX sous-questions doivent être jouées"
    assert [c.chunk_id for c in classement] == ["c-p", "c-t"]
    assert paires == 4, "deux sous-questions × deux candidats"


def test_le_rerank_par_sous_question_ne_score_rien_sans_candidat(banc, monkeypatch):
    """Zéro candidat rend zéro paire, et c'est un coût qu'on ne doit pas inventer.

    Le contrôle positif de ce zéro est le témoin précédent, qui rend 4 : un
    compteur bloqué à 0 y serait rouge.
    """
    import src.agent.retriever as retriever

    def _jamais(question, chunks):  # pragma: no cover — il ne doit pas être appelé
        raise AssertionError("le reranker ne doit pas être appelé sans candidat")

    monkeypatch.setattr(retriever, "rerank", _jamais)
    assert banc.rerank_au_meilleur_score(["s1"], []) == ([], 0)


# ─── 4. LE SEUIL DU HAUT, ÉPROUVÉ DANS LES DEUX SENS ────────────────────────


@pytest.mark.parametrize(
    ("rang", "attendu"), [(1, True), (10, True), (11, False), (None, False), (50, False)]
)
def test_le_seuil_du_haut_accepte_dix_et_refuse_onze(banc, rang, attendu):
    assert banc.dans_le_haut(rang) is attendu


# ─── 5. LE DÉPOUILLEMENT, ET LA QUESTION SANS ANCRAGE ───────────────────────


def _ligne(identifiant, rangs_par_variante):
    return {"id": identifiant, "variantes": rangs_par_variante}


def _variantes(unique, fusion_entiere=None, fusion_sous=None):
    return {
        "unique_avec_traduction": unique,
        "unique_sans_traduction": unique,
        "fusion_rerank_entiere": unique if fusion_entiere is None else fusion_entiere,
        "fusion_rerank_sous_questions": unique if fusion_sous is None else fusion_sous,
    }


def test_une_question_n_est_complete_que_si_tous_ses_ancrages_arrivent(banc):
    """`all`, et le témoin porte les deux cas pour que `any` soit rouge.

    Q-UN a ses deux ancrages dans le haut ; Q-DEUX en a un seul. Sous `any`, les
    deux compteraient, et le banc publierait 2 au lieu de 1.
    """
    lignes = [
        _ligne("Q-UN", _variantes({"a": 1, "b": 4})),
        _ligne("Q-DEUX", _variantes({"a": 2, "b": None})),
    ]
    depouille = banc.depouiller(lignes)
    pour_la_production = depouille["unique_avec_traduction"]
    assert pour_la_production["questions_completes"] == 1
    assert pour_la_production["questions_completes_ids"] == ["Q-UN"]
    assert pour_la_production["ancrages_dans_le_haut"] == 3


def test_une_question_sans_ancrage_mesurable_n_est_pas_declaree_complete(banc):
    """`all({})` est VRAI, et une question vide passerait pour un succès partout.

    Le contrôle positif est dans le même témoin : la question qui PORTE un
    ancrage arrivé est bien comptée, donc le garde ne réussit pas en refusant
    tout.
    """
    lignes = [_ligne("Q-VIDE", _variantes({})), _ligne("Q-PLEINE", _variantes({"a": 1}))]
    depouille = banc.depouiller(lignes)
    assert depouille["unique_avec_traduction"]["questions_completes_ids"] == ["Q-PLEINE"]


# ─── 6. LA NON-RÉGRESSION, ET LES QUESTIONS PERDUES SONT NOMMÉES ────────────


def test_la_non_regression_nomme_les_perdues_et_ne_rend_pas_qu_un_solde(banc):
    """+2 gagnées et −2 perdues font un solde de 0, ET CE 0 EST UN MENSONGE.

    Le témoin est construit pour qu'un banc qui ne publierait que le solde soit
    vert : les deux listes sont donc exigées par leurs IDENTIFIANTS, et le solde
    nul est asserté À CÔTÉ d'elles pour que le garde soit rouge si l'une des deux
    listes disparaît.
    """
    lignes = [
        _ligne("Q-GARDEE", _variantes({"a": 1}, fusion_entiere={"a": 2})),
        _ligne("Q-PERDUE-1", _variantes({"a": 3}, fusion_entiere={"a": None})),
        _ligne("Q-PERDUE-2", _variantes({"a": 4}, fusion_entiere={"a": 40})),
        _ligne("Q-GAGNEE-1", _variantes({"a": None}, fusion_entiere={"a": 1})),
        _ligne("Q-GAGNEE-2", _variantes({"a": 99}, fusion_entiere={"a": 5})),
    ]
    tableau = banc.non_regression(banc.depouiller(lignes), "unique_sans_traduction")
    entiere = tableau["fusion_rerank_entiere"]
    assert entiere["perdues"] == ["Q-PERDUE-1", "Q-PERDUE-2"]
    assert entiere["gagnees"] == ["Q-GAGNEE-1", "Q-GAGNEE-2"]
    assert entiere["solde"] == 0


def test_la_non_regression_ne_se_compare_pas_a_elle_meme(banc):
    """La base est retirée du tableau : une ligne « 0 perdue » sur elle-même
    est vraie et ne dit rien, et elle diluerait la lecture des trois autres."""
    lignes = [_ligne("Q", _variantes({"a": 1}))]
    tableau = banc.non_regression(banc.depouiller(lignes), "unique_sans_traduction")
    assert "unique_sans_traduction" not in tableau
    assert set(tableau) == {
        "unique_avec_traduction",
        "fusion_rerank_entiere",
        "fusion_rerank_sous_questions",
    }


# ─── 7. LE CONTRÔLE POSITIF, ET IL EST UNE INTERSECTION ─────────────────────


def _reference(tmp_path, rangs):
    chemin = tmp_path / "reference.json"
    chemin.write_text(
        json.dumps(
            {
                "lignes": [
                    {"id": qid, "rangs": {eid: {"rerank": r} for eid, r in ancrages.items()}}
                    for qid, ancrages in rangs.items()
                ]
            }
        ),
        encoding="utf-8",
    )
    return chemin


def _lignes_de_production(rangs):
    return [
        _ligne(qid, {"unique_avec_traduction": dict(ancrages)}) for qid, ancrages in rangs.items()
    ]


def test_le_controle_positif_accorde_quand_les_rangs_coincident_un_a_un(
    banc, tmp_path, monkeypatch
):
    """LE CONTRÔLE POSITIF DU CONTRÔLE POSITIF. Sans lui, un garde qui refuserait
    TOUT serait vert sur les trois témoins de refus qui suivent."""
    monkeypatch.setattr(
        banc, "CONTROLE_4_77", {"ancrages_dans_le_haut": 2, "questions_completes": 1}
    )
    rangs = {"Q-1": {"a": 1, "b": 3}, "Q-2": {"a": None}}
    verdict = banc.controle_positif(_lignes_de_production(rangs), _reference(tmp_path, rangs))
    assert verdict["accord"] is True
    assert verdict["rangs_identiques"] == 3
    assert verdict["n_desaccords"] == 0


def test_le_controle_positif_refuse_un_rang_qui_diverge_a_comptes_egaux(
    banc, tmp_path, monkeypatch
):
    """LA LEÇON DU §4.77, ET C'EST LE TÉMOIN QUI COMPTE LE PLUS ICI.

    Les deux comptes sont IDENTIQUES — deux ancrages dans le haut, une question
    complète — et pourtant un ancrage sort au rang 3 là où la référence le met au
    rang 2. Un contrôle qui ne compare que des comptes est vert ; celui-ci doit
    être rouge, sans quoi il laisserait mesurer la décomposition contre une base
    qui a bougé.
    """
    monkeypatch.setattr(
        banc, "CONTROLE_4_77", {"ancrages_dans_le_haut": 2, "questions_completes": 1}
    )
    reference = _reference(tmp_path, {"Q-1": {"a": 1, "b": 2}})
    verdict = banc.controle_positif(_lignes_de_production({"Q-1": {"a": 1, "b": 3}}), reference)
    assert verdict["mesure"] == {"ancrages_dans_le_haut": 2, "questions_completes": 1}
    assert verdict["n_desaccords"] == 1
    assert verdict["accord"] is False


def test_le_controle_positif_refuse_un_jeu_qui_n_a_pas_les_memes_cles(banc, tmp_path, monkeypatch):
    """Des clés qui ne se recoupent pas rendent un accord VIDE sur l'intersection.

    Sans cette exigence, un banc mesurant un autre jeu passerait le contrôle en
    ne partageant aucune clé : zéro désaccord sur zéro clé commune.
    """
    monkeypatch.setattr(
        banc, "CONTROLE_4_77", {"ancrages_dans_le_haut": 1, "questions_completes": 1}
    )
    reference = _reference(tmp_path, {"Q-1": {"a": 1}})
    verdict = banc.controle_positif(_lignes_de_production({"Q-AUTRE": {"a": 1}}), reference)
    assert verdict["cles_communes"] == 0
    assert verdict["n_desaccords"] == 0
    assert verdict["accord"] is False


def test_le_controle_positif_refuse_des_comptes_qui_ne_sont_pas_ceux_du_4_77(banc, tmp_path):
    """Les rangs coïncident tous, et les comptes ne sont PAS 53 et 7 : refus.

    C'est l'autre sens du témoin précédent — les deux exigences sont portées
    ensemble, et aucune ne suffit seule.
    """
    rangs = {"Q-1": {"a": 1}}
    verdict = banc.controle_positif(_lignes_de_production(rangs), _reference(tmp_path, rangs))
    assert verdict["attendu_4_77"] == _PRODUCTION_4_77
    assert verdict["rangs_identiques"] == 1
    assert verdict["accord"] is False


# ─── 8. LE PROMPT, ET CE QU'IL NE DIT PAS ───────────────────────────────────


def test_le_prompt_porte_la_question_en_tete_pour_que_les_prefixes_soient_distincts(banc):
    """Le cache de préfixe de `vllm-central` servirait une instruction commune.

    La latence mesurée sur un préfixe déjà servi n'est pas la latence de l'appel.
    La question est donc en tête, et le garde l'assertit au PREMIER caractère :
    deux prompts de deux questions différentes divergent dès le premier jeton.
    """
    un = banc.prompt_de_decomposition("Alpha needs one thing?")
    deux = banc.prompt_de_decomposition("Beta needs another?")
    assert un.startswith("Question: Alpha needs one thing?")
    assert deux.startswith("Question: Beta needs another?")
    commun = 0
    while commun < min(len(un), len(deux)) and un[commun] == deux[commun]:
        commun += 1
    assert commun <= len("Question: "), "le préfixe commun doit s'arrêter avant la question"


def test_le_prompt_ne_dit_jamais_combien_de_besoins_la_question_porte(banc):
    """C'est ce qui sépare ce banc de l'oracle du §4.77, dont le prompt AFFIRMAIT
    qu'il y avait deux besoins. Un décomposeur réel ne le sait pas, et le lui
    dire couperait en deux toute question à besoin unique — rendant la
    non-régression sur les deux autres jeux illisible.

    Le contrôle est dans les deux sens : le prompt doit porter la borne haute et
    la permission explicite de ne rien décomposer.
    """
    prompt = banc.prompt_de_decomposition("Which metric proves it?")
    for interdit in ("TWO different sections", "exactly two", "two standalone"):
        assert interdit not in prompt
    assert "single need, return the question alone" in prompt
    assert f"more than {banc._MAX_SOUS_QUESTIONS} sub-questions" in prompt


# ─── 9. LE CACHE, ET IL EST NOMMÉ D'APRÈS SON JEU ───────────────────────────


def test_le_cache_de_decomposition_porte_le_nom_de_son_jeu(banc):
    """Un seul fichier pour les trois jeux laisserait une campagne lire les
    décompositions d'un autre dès que deux questions porteraient le même
    identifiant — et les identifiants sont locaux à leur fichier."""
    disperse = banc.cache_de_decomposition(
        pathlib.Path("tests/fixtures/jeu_ancrages_disperses.yaml")
    )
    reglage = banc.cache_de_decomposition(pathlib.Path("tests/fixtures/golden_qa_generated.yaml"))
    assert disperse != reglage
    assert disperse.name == ".decomposition-jeu_ancrages_disperses.json"
    assert reglage.name == ".decomposition-golden_qa_generated.json"
