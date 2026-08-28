"""La précision du contexte remis au LLM.

Le rappel et le MRR mesurent le CLASSEMENT. La reconstruction par le graphe ne le
change pas : elle change la COMPOSITION du contexte. Mesurer « avec / sans
graphe » sur le rappel afficherait donc « aucun changement » sur le pari central
du projet, et cette conclusion serait un artefact de l'instrument.

Chaque métrique ajoutée a ici un test qui la fait **RÉGRESSER** sur une entrée
construite pour la dégrader. Un test qui vérifie qu'un chiffre se calcule est
vert des deux côtés du défaut ; seul un test qui le fait baisser montre qu'il
mesure quelque chose.

Les trois pièges du dénominateur — candidates au lieu de retenues, sections
écartées comptées comme du bruit, questions sans or moyennées avec les autres —
ont chacun leur test, parce que chacun rendrait la métrique verte sur un
instrument cassé.
"""

import importlib.util
import pathlib

import pytest
from fastapi.testclient import TestClient

from src.api.schemas import SectionContext

_RACINE = pathlib.Path(__file__).resolve().parents[2]
_SCRIPT = _RACINE / "scripts" / "evaluate.py"

OR = "aaaaaaaaa1"
AUTRE_OR = "aaaaaaaaa2"


def _evaluate():
    """Charge scripts/evaluate.py sans faire de `scripts/` un paquet."""
    spec = importlib.util.spec_from_file_location("evaluate", _SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _contexte(
    section: str,
    element_ids: list[str],
    caracteres: int = 100,
    retained: bool = True,
) -> dict:
    """Une section telle que `/answer` la rend, réduite à ce qui est mesuré."""
    return {
        "section_id": section,
        "element_id": element_ids[0],
        "element_ids": element_ids,
        "retained": retained,
        "text": "x" * caracteres,
    }


# ─── taux_contexte_utile : la part des sections payées qui servent ───────────

def test_le_taux_vaut_un_sur_un_contexte_net() -> None:
    """Le point de départ : une seule section, et elle porte l'or."""
    mesure = _evaluate().precision_contexte({OR}, [_contexte("s1", [OR])])

    assert mesure["taux_contexte_utile"] == 1.0
    assert mesure["rappel_contexte"] == 1.0


def test_un_or_noye_dans_neuf_sections_inutiles_fait_chuter_le_taux() -> None:
    """**Le test qui fait régresser la métrique.**

    Ces deux réponses ont le MÊME rappel : l'or a atteint le LLM dans les deux
    cas. Aujourd'hui elles rendent le même chiffre, et c'est précisément le
    défaut — une question dont l'or est trouvé mais noyé dans neuf sections
    inutiles n'est pas le même succès qu'une question dont le contexte est net.
    """
    evaluate = _evaluate()
    net = evaluate.precision_contexte({OR}, [_contexte("s1", [OR])])
    noye = evaluate.precision_contexte(
        {OR},
        [_contexte("s1", [OR]), *(_contexte(f"s{i}", [f"bbbbbbbbb{i}"]) for i in range(2, 11))],
    )

    assert net["rappel_contexte"] == noye["rappel_contexte"] == 1.0
    assert noye["taux_contexte_utile"] == pytest.approx(0.1)
    assert noye["taux_contexte_utile"] < net["taux_contexte_utile"]


# ─── part_utile_caracteres : la part des tokens payés qui servent ────────────

def test_la_part_utile_chute_quand_le_contexte_inutile_grossit() -> None:
    """**Le test qui fait régresser la métrique qui porte le lot.**

    Même nombre de sections, même rappel, même or : seule la TAILLE du contexte
    inutile change. `taux_contexte_utile` ne bouge pas — il compte des sections —
    là où la part de caractères s'effondre. C'est ce qui coûte des tokens.
    """
    evaluate = _evaluate()
    serre = evaluate.precision_contexte(
        {OR}, [_contexte("s1", [OR], 100), _contexte("s2", ["bbbbbbbbb2"], 100)]
    )
    large = evaluate.precision_contexte(
        {OR}, [_contexte("s1", [OR], 100), _contexte("s2", ["bbbbbbbbb2"], 900)]
    )

    assert serre["taux_contexte_utile"] == large["taux_contexte_utile"] == 0.5
    assert serre["part_utile_caracteres"] == pytest.approx(0.5)
    assert large["part_utile_caracteres"] == pytest.approx(0.1)
    assert large["part_utile_caracteres"] < serre["part_utile_caracteres"]


def test_une_fenetre_qui_double_le_contexte_pour_le_meme_or_double_le_cout() -> None:
    """La borne de `part_utile_caracteres`, écrite parce qu'elle compte.

    La métrique raisonne à la SECTION : élargir la fenêtre **à l'intérieur** de
    la section qui porte l'or ne la fait pas bouger — tous ces caractères
    appartiennent à une section utile. Elle expose « trop de sections », pas
    « fenêtre trop large ».

    Ce que l'ablation de la taille de fenêtre lit, c'est donc le COUPLE :
    `caracteres_retenus` double pendant que `rappel_contexte` reste plat. Même
    or, deux fois le prix. Sans ce test, quelqu'un lirait un
    `part_utile_caracteres` stable comme « la fenêtre ne coûte rien ».
    """
    evaluate = _evaluate()
    etroite = evaluate.precision_contexte({OR}, [_contexte("s1", [OR, "bbbbbbbbb1"], 500)])
    large = evaluate.precision_contexte(
        {OR}, [_contexte("s1", [OR, "bbbbbbbbb1", "bbbbbbbbb2"], 1000)]
    )

    assert etroite["part_utile_caracteres"] == large["part_utile_caracteres"] == 1.0
    assert etroite["rappel_contexte"] == large["rappel_contexte"] == 1.0
    assert large["caracteres_retenus"] == 2 * etroite["caracteres_retenus"]


# ─── Le dénominateur : ce qui a été PAYÉ ─────────────────────────────────────

def test_une_section_ecartee_n_entre_ni_au_numerateur_ni_au_denominateur() -> None:
    """**Le piège du dénominateur, et le test qui l'attrape.**

    Une section écartée faute de place dans la fenêtre n'est pas un contexte
    inutile : c'est un contexte NON PAYÉ. La compter ferait chuter la métrique au
    moment précis où le budget fait son travail — soit l'inverse de ce qu'on
    veut lire.

    Sur ce montage, un dénominateur pris sur les candidates rendrait 0,25.
    """
    mesure = _evaluate().precision_contexte(
        {OR},
        [
            _contexte("s1", [OR]),
            *(_contexte(f"s{i}", [f"bbbbbbbbb{i}"], retained=False) for i in range(2, 5)),
        ],
    )

    assert mesure["contextes_retenus"] == 1
    assert mesure["taux_contexte_utile"] == 1.0
    assert mesure["part_utile_caracteres"] == 1.0


def test_une_section_ecartee_qui_portait_l_or_ne_compte_pas_comme_arrivee() -> None:
    """Le pendant : écartée, elle n'a pas atteint le LLM. Le rappel au contexte
    doit valoir zéro — c'est exactement l'échec « trouvé puis écarté », qui
    n'est pas le même que « jamais trouvé »."""
    mesure = _evaluate().precision_contexte(
        {OR}, [_contexte("s1", [OR], retained=False), _contexte("s2", ["bbbbbbbbb2"])]
    )

    assert mesure["rappel_contexte"] == 0.0
    assert mesure["taux_contexte_utile"] == 0.0


def test_un_service_qui_ne_publie_pas_les_retenues_ne_rend_aucune_precision() -> None:
    """Sans le champ, on ne sait pas ce qui a été payé. Rendre la métrique
    calculée sur les candidates serait pire que ne rien rendre : le chiffre
    s'afficherait, plausible, et mesurerait une intention."""
    sans_champ = [{"section_id": "s1", "element_id": OR, "element_ids": [OR], "text": "x" * 100}]

    mesure = _evaluate().precision_contexte({OR}, sans_champ)

    assert mesure["contextes_retenus"] == 0
    assert mesure["taux_contexte_utile"] is None
    assert mesure["part_utile_caracteres"] is None


# ─── Les questions sans or ────────────────────────────────────────────────────

def test_une_question_sans_or_est_exclue_des_trois_metriques() -> None:
    """Sur une `unanswerable`, la part utile vaut 0/N par construction. La
    moyenner avec les autres ferait baisser le chiffre sans qu'aucune dégradation
    n'ait eu lieu — les huit questions du jeu doré en relèvent."""
    mesure = _evaluate().precision_contexte(set(), [_contexte("s1", ["bbbbbbbbb1"])])

    assert mesure["taux_contexte_utile"] is None
    assert mesure["part_utile_caracteres"] is None
    assert mesure["rappel_contexte"] is None
    # Le dénominateur reste publié : c'est le coût en caractères d'une réponse
    # que le corpus ne portait pas, et il n'y a aucune raison de le perdre.
    assert mesure["contextes_retenus"] == 1


def test_le_resume_dit_sur_combien_de_questions_la_precision_porte() -> None:
    """Une métrique dont on ne sait pas sur combien de questions elle porte n'est
    pas lisible, et une moyenne qui a perdu la moitié du jeu ne se distingue pas
    d'une moyenne saine."""
    evaluate = _evaluate()
    lignes = [
        evaluate.evaluer(
            {"id": "G-001", "gold_element_ids": [OR], "language": "fr", "doc_language": "fr"},
            {"contexts": [_contexte("s1", [OR])], "citations": [], "answer": "r"},
        ),
        evaluate.evaluer(
            {"id": "N-001", "unanswerable": True, "language": "fr", "doc_language": "fr"},
            {"contexts": [_contexte("s2", ["bbbbbbbbb2"])], "citations": [], "answer": "r"},
        ),
        evaluate.evaluer(
            {"id": "G-002", "gold_element_ids": [OR], "language": "fr", "doc_language": "fr"},
            {"contexts": [_contexte("s3", [OR], retained=False)], "citations": [], "answer": "r"},
        ),
    ]

    resume = evaluate.resumer(lignes)

    assert resume["precision_contexte_sur"] == 1
    assert resume["precision_contexte_exclues_sans_or"] == 1
    assert resume["precision_contexte_exclues_sans_retenue"] == 1
    # `rappel_contexte` porte sur une population DIFFÉRENTE : la question dont
    # rien n'est retenu y compte pour 0,0 — l'or n'a rien atteint, ce qui est une
    # mesure — là où `taux` et `part` l'excluent. Deux moyennes voisines dans le
    # même résumé, sur deux populations : son effectif doit être écrit.
    assert resume["rappel_contexte_sur"] == 2
    assert resume["rappel_contexte_sur"] != resume["precision_contexte_sur"]
    # Les trois buckets couvrent le jeu : aucune question ne disparaît en
    # silence entre « comptée » et « exclue ».
    assert (
        resume["precision_contexte_sur"]
        + resume["precision_contexte_exclues_sans_or"]
        + resume["precision_contexte_exclues_sans_retenue"]
        == resume["questions"]
    )


# ─── Le prix du contexte, et la séparation de ses DEUX causes ────────────────

def _campagne(evaluate, sections_par_question: list[tuple[int, int]]) -> dict:
    """Résume une campagne où chaque question porte (nb de sections, taille de chacune)."""
    lignes = [
        evaluate.evaluer(
            {"id": f"G-{i:03d}", "gold_element_ids": [OR], "language": "fr"},
            {
                "contexts": [_contexte(f"s{j}", [OR], taille) for j in range(nombre)],
                "citations": [],
                "answer": "r",
            },
        )
        for i, (nombre, taille) in enumerate(sections_par_question, 1)
    ]
    return evaluate.resumer(lignes)


def test_le_quotient_separe_plus_de_sections_de_sections_plus_grosses() -> None:
    """**Le test qui porte le point.**

    Deux campagnes au prix TOTAL identique — 6 000 caractères payés par question
    — et à la cause opposée : l'une paie six sections de mille caractères, l'autre
    trois sections de deux mille. `caracteres_retenus` ne les distingue pas, et
    c'est exactement l'ambiguïté dans laquelle la première mesure de l'ablation
    du graphe serait tombée.

    Le quotient les sépare, et son dénominateur — publié ici pour la première
    fois — dit laquelle des deux causes a bougé.
    """
    evaluate = _evaluate()
    beaucoup = _campagne(evaluate, [(6, 1000)] * 4)
    grosses = _campagne(evaluate, [(3, 2000)] * 4)

    assert beaucoup["caracteres_retenus_p50"] == grosses["caracteres_retenus_p50"] == 6000
    assert beaucoup["contextes_retenus_p50"] == 6
    assert grosses["contextes_retenus_p50"] == 3
    assert beaucoup["caracteres_par_section_p50"] == 1000
    assert grosses["caracteres_par_section_p50"] == 2000


def test_les_questions_sans_section_retenue_comptent_dans_le_denominateur() -> None:
    """Zéro section retenue est une VALEUR du compte, pas une absence de compte.

    Les exclure ferait remonter `contextes_retenus_p50` au moment précis où le
    budget affame les questions — soit l'inverse de ce qu'on veut lire.
    """
    evaluate = _evaluate()
    lignes = [
        evaluate.evaluer(
            {"id": f"G-{i:03d}", "gold_element_ids": [OR], "language": "fr"},
            {"contexts": contextes, "citations": [], "answer": "r"},
        )
        for i, contextes in enumerate(
            [[_contexte("s1", [OR], 900)], [], [], []], 1
        )
    ]

    resume = evaluate.resumer(lignes)

    assert resume["contextes_retenus_p50"] == 0
    assert resume["contextes_retenus_p95"] == 1


def test_le_quotient_exclut_les_questions_sans_section_retenue() -> None:
    """Le pendant, et la décision inverse pour une bonne raison.

    Une moyenne PAR SECTION n'a pas de valeur quand il n'y a pas de section :
    elle est indéfinie, pas nulle. Un zéro s'y moyennerait avec les autres et se
    lirait « les sections ont maigri », alors qu'aucune n'a été payée. Même
    raisonnement que pour `part_utile_caracteres`.

    **Le montage est dimensionné pour que la médiane BOUGE.** Deux questions
    servies et TROIS vides : les zéros inclus, ils sont majoritaires et le
    centile tombe à 0. À deux zéros sur quatre, la médiane resterait à 900 et le
    test serait vert des deux côtés du défaut — c'est le piège que ce dépôt
    connaît, un test qui ne peut pas rougir.
    """
    evaluate = _evaluate()
    lignes = [
        evaluate.evaluer(
            {"id": f"G-{i:03d}", "gold_element_ids": [OR], "language": "fr"},
            {"contexts": contextes, "citations": [], "answer": "r"},
        )
        for i, contextes in enumerate(
            [[_contexte("s1", [OR], 900)], [_contexte("s1", [OR], 900)], [], [], []], 1
        )
    ]

    resume = evaluate.resumer(lignes)

    assert resume["caracteres_par_section_p50"] == 900
    # Et la population écartée reste nommée, elle ne disparaît pas.
    assert resume["precision_contexte_exclues_sans_retenue"] == 3


def test_sans_aucune_section_retenue_le_quotient_est_indefini() -> None:
    """Rendre 0 affirmerait « des sections de zéro caractère », ce qui n'existe
    pas. `_centile` sur une liste vide rend 0 : c'est ce zéro-là qu'on refuse
    de publier."""
    evaluate = _evaluate()
    ligne = evaluate.evaluer(
        {"id": "G-001", "gold_element_ids": [OR], "language": "fr"},
        {"contexts": [], "citations": [], "answer": "r"},
    )

    resume = evaluate.resumer([ligne])

    assert resume["caracteres_par_section_p50"] is None
    assert resume["contextes_retenus_p50"] == 0


# ─── Le rappel au contexte, là où la fenêtre du graphe se voit ───────────────

def test_le_rappel_au_contexte_dit_sur_combien_de_questions_il_porte() -> None:
    """**La règle du lot, appliquée à la métrique qui y échappait.**

    « Une métrique dont on ne sait pas sur combien de questions elle porte n'est
    pas lisible. » Les trois compteurs somment au nombre de questions, mais aucun
    ne nomme la population de `rappel_contexte` — qui inclut les questions sans
    section retenue et exclut les questions sans or.

    Sur ce montage : 4 questions, 1 sans or, 2 sans section retenue. `taux` porte
    sur 1, `rappel_contexte` sur 3 — trois fois plus, dans le même tableau.
    """
    evaluate = _evaluate()
    lignes = [
        evaluate.evaluer(question, {"contexts": contextes, "citations": [], "answer": "r"})
        for question, contextes in (
            ({"id": "G-001", "gold_element_ids": [OR], "language": "fr"},
             [_contexte("s1", [OR])]),
            ({"id": "G-002", "gold_element_ids": [OR], "language": "fr"}, []),
            ({"id": "G-003", "gold_element_ids": [OR], "language": "fr"}, []),
            ({"id": "N-001", "unanswerable": True, "language": "fr"},
             [_contexte("s9", ["bbbbbbbbb9"])]),
        )
    ]

    resume = evaluate.resumer(lignes)

    assert resume["precision_contexte_sur"] == 1
    assert resume["rappel_contexte_sur"] == 3
    # Et il vaut bien la somme des deux compteurs qui le composent : l'écrire
    # évite au lecteur de faire l'addition, en silence, dans sa tête.
    assert resume["rappel_contexte_sur"] == (
        resume["precision_contexte_sur"] + resume["precision_contexte_exclues_sans_retenue"]
    )


def test_l_or_ramene_par_la_fenetre_sans_avoir_ete_trouve_compte() -> None:
    """C'est la valeur que le graphe prétend apporter, et elle était invisible.

    `rappel_elements` se mesure sur la GRAINE du retrieval : un élément d'or
    ramené par la fenêtre de la section — sans avoir été classé — y compte pour
    zéro alors qu'il a bel et bien atteint le LLM. `rappel_contexte` lit les
    marqueurs du texte payé, donc il le voit.
    """
    mesure = _evaluate().precision_contexte(
        # La graine est `bbbbbbbbb1` ; l'or est un voisin dans la même section.
        {OR}, [_contexte("s1", ["bbbbbbbbb1", OR])]
    )

    assert mesure["rappel_contexte"] == 1.0
    assert mesure["taux_contexte_utile"] == 1.0


def test_un_or_sur_deux_dans_le_contexte_rend_un_demi() -> None:
    """Le rappel est une part, pas un booléen : deux éléments d'or attendus dont
    un seul arrive n'est pas un succès entier."""
    mesure = _evaluate().precision_contexte({OR, AUTRE_OR}, [_contexte("s1", [OR])])

    assert mesure["rappel_contexte"] == pytest.approx(0.5)
    assert mesure["taux_contexte_utile"] == 1.0


def test_sans_aucune_section_retenue_le_rappel_est_zero_et_la_precision_indefinie() -> None:
    """Un budget qui a tout écarté : l'or n'a rien atteint (rappel nul), mais
    aucune précision n'est définissable — il n'y a pas de dénominateur. Rendre
    zéro serait affirmer qu'un contexte inutile a été payé."""
    mesure = _evaluate().precision_contexte({OR}, [_contexte("s1", [OR], retained=False)])

    assert mesure["rappel_contexte"] == 0.0
    assert mesure["taux_contexte_utile"] is None
    assert mesure["part_utile_caracteres"] is None
    assert mesure["caracteres_retenus"] == 0


# ─── La chaîne réelle : ce que /answer rend vraiment ─────────────────────────

QUESTION = "Comment mesurer la dispersion ?"


def _flux_ollama_minimal():
    import json as _json

    class Resp:
        def raise_for_status(self) -> None: ...

        async def aiter_lines(self):
            yield _json.dumps({"message": {"content": "Une réponse."}})
            yield _json.dumps({"message": {"content": ""}, "done": True})

    class Stream:
        async def __aenter__(self):
            return Resp()

        async def __aexit__(self, *_):
            return False

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return False

        def stream(self, *_args, **_kwargs):
            return Stream()

    return lambda **_kwargs: Client()


def _grosses_sections(nombre: int, taille: int) -> list[SectionContext]:
    return [
        SectionContext(
            element_id=f"abcdef01{i:02d}",
            section_id=f"sssssssss{i}",
            breadcrumbs=[],
            elements=[],
            markdown=f"Section {i}. " + "x" * taille + f" [src:abcdef01{i:02d}]",
        )
        for i in range(nombre)
    ]


def _client_sur(contextes: list[SectionContext], monkeypatch) -> TestClient:
    """`/answer` avec le VRAI node_generate : seule la couche HTTP est simulée.

    Le budget est celui du vrai `fit_prompt`, donc c'est bien lui qui décide de
    ce qui est retenu — un stub qui souffle la réponse ne prouverait rien de la
    chaîne `on_fit` → état → endpoint.
    """
    from src.agent import graph as graph_module
    from src.agent import llm
    from src.api import main

    monkeypatch.setattr(llm.httpx, "AsyncClient", _flux_ollama_minimal())

    async def fake_ainvoke(state, _config=None):
        etat = {**state, "enriched_contexts": contextes, "search_count": 0, "_metadata": {}}
        return {
            "reranked_chunks": [],
            "enriched_contexts": contextes,
            "citations": [],
            "images": [],
            **await graph_module.node_generate(etat),
        }

    monkeypatch.setattr(main.answer_graph, "ainvoke", fake_ainvoke)
    return TestClient(main.app)


def test_answer_rend_les_candidates_ecartees_et_les_marque(monkeypatch) -> None:
    """**Ce que `/answer` rend réellement dans `contexts`, vérifié.**

    Il rend TOUTES les sections reconstruites, y compris celles que le budget a
    écartées — et jusqu'à ce lot, sans rien qui les distingue et avec leur texte
    ENTIER, jamais celui qui est parti. Une campagne qui comptait `contexts`
    comptait donc des sections non payées.

    Elles restent dans la réponse — savoir ce qui a été reconstruit pour rien a
    de la valeur — mais `retained` les nomme, et le compte doit s'accorder avec
    `dropped_contexts`, qui vient du même `PromptFit`.
    """
    from src.agent.llm import fit_prompt

    contextes = _grosses_sections(6, 4000)
    attendu = fit_prompt(QUESTION, contextes, []).dropped_contexts
    assert attendu > 0, "le cas de test ne provoque aucune mise à l'écart"

    body = _client_sur(contextes, monkeypatch).post(
        "/answer", json={"question": QUESTION}
    ).json()

    assert len(body["contexts"]) == 6
    assert body["dropped_contexts"] == attendu
    retenues = [c for c in body["contexts"] if c["retained"]]
    assert len(retenues) == 6 - attendu
    # L'invariant : les deux chiffres viennent du même budget et ne peuvent pas
    # se contredire.
    assert len(retenues) + body["dropped_contexts"] == len(body["contexts"])


def test_le_texte_publie_est_celui_qui_est_parti_troncature_comprise(monkeypatch) -> None:
    """Une source unique trop grosse est retenue mais TRONQUÉE. Publier son
    markdown entier surestimerait les caractères payés — et `part_utile_
    caracteres` est un rapport de caractères."""
    from src.agent.llm import _TRUNCATION_MARKER, fit_prompt

    contextes = _grosses_sections(1, 40_000)
    fit = fit_prompt(QUESTION, contextes, [])
    assert len(fit.contexts[0].markdown) < len(contextes[0].markdown)

    body = _client_sur(contextes, monkeypatch).post(
        "/answer", json={"question": QUESTION}
    ).json()
    ctx = body["contexts"][0]

    assert ctx["retained"] is True
    assert ctx["text"] == fit.contexts[0].markdown
    assert ctx["text"].endswith(_TRUNCATION_MARKER)
    assert len(ctx["text"]) < len(contextes[0].markdown)


def test_une_incoherence_du_budget_est_annoncee(monkeypatch, caplog) -> None:
    """Asserté depuis `/answer`, qui PRODUIT l'avertissement.

    Le nombre d'écartées et le marquage des retenues viennent du MÊME
    `PromptFit` : ils ne peuvent pas se contredire tant que la chaîne tient. Cet
    avertissement dit qu'elle a cédé — et sans lui, une campagne calculerait la
    précision du contexte sur un dénominateur muet et la publierait comme une
    mesure.

    Le montage force la contradiction à la main, ce qui est le seul moyen de
    l'obtenir : deux candidates, aucune retenue, et `dropped_contexts` à zéro.
    """
    import logging

    from src.api import main

    contextes = _grosses_sections(2, 100)

    async def ainvoke_incoherent(_state, _config=None):
        return {
            "reranked_chunks": [],
            "enriched_contexts": contextes,
            # Rien de retenu, mais rien d'écarté non plus : impossible.
            "submitted_contexts": [],
            "dropped_contexts": 0,
            "citations": [],
            "images": [],
            "response": "r",
            "_metadata": {},
        }

    monkeypatch.setattr(main.answer_graph, "ainvoke", ainvoke_incoherent)
    with caplog.at_level(logging.WARNING, logger="src.api.main"):
        body = TestClient(main.app).post("/answer", json={"question": QUESTION}).json()

    assert "Incohérence du budget" in caplog.text
    assert [c["retained"] for c in body["contexts"]] == [False, False]


def test_un_budget_coherent_n_avertit_de_rien(monkeypatch, caplog) -> None:
    """Le pendant : un avertissement qui se déclencherait toujours ne
    signalerait rien, il ferait du bruit à chaque réponse."""
    import logging

    contextes = _grosses_sections(2, 100)

    with caplog.at_level(logging.WARNING, logger="src.api.main"):
        _client_sur(contextes, monkeypatch).post("/answer", json={"question": QUESTION})

    assert "Incohérence du budget" not in caplog.text


def test_les_element_ids_publies_sont_ceux_du_texte_soumis(monkeypatch) -> None:
    """Les marqueurs du texte réellement envoyé, pas les éléments de la section.

    La troncature coupe à une frontière de marqueur : des éléments de la section
    restent donc listés par le modèle `SectionContext` sans être dans le texte
    parti. Lire le texte est la seule lecture qui ne surestime pas ce qui a
    atteint le LLM.
    """
    contextes = _grosses_sections(2, 200)

    body = _client_sur(contextes, monkeypatch).post(
        "/answer", json={"question": QUESTION}
    ).json()

    assert [c["element_ids"] for c in body["contexts"]] == [
        ["abcdef0100"],
        ["abcdef0101"],
    ]


# ─── Ce que la troncature déplace entre « lu » et « citable » ─────────────────

def _section_marquee(rang: int, nb_elements: int) -> SectionContext:
    """Une section rendue comme `_render_element` la rend, éléments compris.

    `elements` est peuplé pour de vrai, et le markdown porte les marqueurs
    correspondants : c'est le décalage entre les deux — le modèle garde tous ses
    éléments, le texte soumis n'en porte que la tête — que ces tests éclairent.
    `resolve_citations` lit désormais le second.
    """
    from src.api.schemas import SectionElement

    elements = [
        SectionElement(
            node_id=f"{rang:04d}{i:06d}",
            label="paragraph",
            text=f"Paragraphe {i} de la section {rang}, avec assez de texte pour peser.",
            sequence=i,
            page_no=88,
        )
        for i in range(nb_elements)
    ]
    return SectionContext(
        element_id=f"abcdef01{rang:02d}",
        section_id=f"section{rang:04d}",
        breadcrumbs=[],
        elements=elements,
        markdown="\n\n".join(f"{e.text} [src:{e.node_id}]" for e in elements),
        filename="3. Statistical Toolbox",
        section_title="Dispersion",
    )


def test_aucun_identifiant_soumis_ne_designe_un_texte_absent_du_prompt() -> None:
    """La première dérive du point C, mesurée avec l'instrument du lot 4.

    `element_ids_presents` lit les marqueurs du texte RÉELLEMENT soumis. Chacun
    doit avoir son texte dans ce même texte : sinon le modèle citerait une source
    dont il n'a pas vu le contenu.

    Balayé sur toute la plage de budgets qui tronque, parce qu'un seul point
    tombe rarement à l'endroit gênant.
    """
    from src.agent.graph import element_ids_presents
    from src.agent.llm import _TRUNCATION_MARKER, fit_contexts

    sections = [_section_marquee(0, 20), _section_marquee(1, 20)]
    textes = {e.node_id: e.text for s in sections for e in s.elements}
    tronquees = 0

    entiere = len(sections[0].markdown)
    for pas in range(0, len(sections[1].markdown), 29):
        kept, _ = fit_contexts(list(sections), entiere + pas)
        for ctx in kept:
            if ctx.markdown.endswith(_TRUNCATION_MARKER):
                tronquees += 1
            for eid in element_ids_presents(ctx.markdown):
                assert textes[eid] in ctx.markdown, (
                    f"budget {entiere + pas} : [src:{eid}] soumis sans son texte"
                )
    assert tronquees > 0, "le balayage n'a rien tronqué"


def test_un_element_coupe_disparait_des_identifiants_soumis() -> None:
    """Le pendant : ce qui a été coupé ne doit plus être annoncé comme soumis.

    C'est ce que `/answer` publie sous `element_ids`, et ce sur quoi la campagne
    calcule `part_utile_caracteres`. Le lire dans `SectionContext.elements`
    surestimerait le contexte payé de tout ce que la troncature a enlevé.
    """
    from src.agent.graph import element_ids_presents
    from src.agent.llm import fit_contexts

    sections = [_section_marquee(0, 20), _section_marquee(1, 20)]
    entiers = element_ids_presents(sections[1].markdown)
    kept, _ = fit_contexts(list(sections), len(sections[0].markdown)
                           + len(sections[1].markdown) // 2)

    assert len(kept) == 2  # la seconde est entrée, tronquée
    soumis = element_ids_presents(kept[1].markdown)
    assert set(soumis) < set(entiers), "la troncature doit retirer des éléments"
    assert [e.node_id for e in kept[1].elements] == entiers, (
        "le modèle SectionContext garde tous ses éléments : c'est bien pour cela "
        "qu'il ne faut pas le lire pour savoir ce qui a été soumis"
    )


def test_le_post_processing_refuse_un_identifiant_que_le_prompt_ne_portait_pas() -> None:
    """Le grain de la restriction est l'ÉLÉMENT, et c'est ce test qui le tranche.

    La section est RETENUE — donc restreindre à la section ne suffirait pas — mais
    tronquée, et l'élément dont le marqueur est tombé à la coupe n'a pas été
    soumis pour autant. Sa citation est refusée.

    Ce test disait exactement l'inverse jusqu'ici, et il avait raison de le dire :
    `resolve_citations` construisait sa table depuis `SectionContext.elements` —
    le MODÈLE, qui garde tout — et non depuis le texte soumis. Il épinglait le
    fait désagréable pour que personne ne croie la garantie logée dans le
    résolveur : elle était dans la coupe, et nulle part ailleurs. Elle est
    maintenant dans les deux, et c'est ce que ce test garde : si quelqu'un
    assouplit `_cut_on_marker`, la citation ne sortira plus quand même.
    """
    from src.agent.graph import resolve_citations
    from src.agent.llm import fit_contexts

    sections = [_section_marquee(0, 20), _section_marquee(1, 20)]
    kept, _ = fit_contexts(list(sections), len(sections[0].markdown)
                           + len(sections[1].markdown) // 2)
    assert len(kept) == 2, "la seconde section doit être RETENUE, tronquée"
    coupe = next(
        e.node_id for e in sections[1].elements if f"[src:{e.node_id}]" not in kept[1].markdown
    )
    garde = next(
        e.node_id for e in sections[1].elements if f"[src:{e.node_id}]" in kept[1].markdown
    )

    citations, _ = resolve_citations(
        f"Une affirmation. [src:{coupe}] Une autre. [src:{garde}]", kept, []
    )

    # Les deux espèces comptées séparément : le refus ne doit pas être un refus
    # de tout. L'élément dont le marqueur a survécu reste citable, avec son
    # extrait — sans quoi ce test serait vert sur un résolveur qui ne rend rien.
    assert [c.element_id for c in citations] == [garde]
    assert citations[0].text_excerpt, "l'élément soumis garde son extrait"
