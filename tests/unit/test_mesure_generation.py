"""Ce que la génération coûte réellement, et qui n'était mesuré nulle part.

`LLM_MAX_TOKENS=4096` confisque la MOITIÉ de la fenêtre de 8192 à la génération,
et rien ne disait qu'elle en avait besoin : `runs/*.json` n'enregistrait que
`generation_ms`. « Une génération qui n'arrive jamais à son plafond » était donc
une présomption, et le gain de +86 % sur le budget de sources qui en découle est
étiqueté « hypothèse de calcul, pas une mesure ».

Deux chaînes sont exercées ici, chacune parce qu'elle a déjà été cassée en
gardant la suite verte : `on_measure` → état du graphe → `/answer` → campagne, et
la décision d'écarter les décomptes pollués par le cache KV, qui doit rester
**unique**.
"""

import importlib.util
import json
import logging
import pathlib

import pytest

from src.agent import graph as graph_module
from src.agent import llm
from src.api.schemas import BreadcrumbEntry, SectionContext

_RACINE = pathlib.Path(__file__).resolve().parents[2]
_SCRIPT = _RACINE / "scripts" / "evaluate.py"

QUESTION = "Comment se mesure la dispersion ?"


def _evaluate():
    spec = importlib.util.spec_from_file_location("evaluate", _SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _flux_ollama(lignes: list[dict]):
    class Resp:
        def raise_for_status(self) -> None: ...

        async def aiter_lines(self):
            for ligne in lignes:
                yield json.dumps(ligne)

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


def _section() -> SectionContext:
    return SectionContext(
        element_id="abcdef0123",
        section_id="sssssssss1",
        breadcrumbs=[BreadcrumbEntry(node_id="doc0000001", label="Document", text="Atelier")],
        elements=[],
        markdown="La dispersion se mesure par l'écart-type. [src:abcdef0123]",
    )


# ─── Le décompte des tokens générés, lu et publié ────────────────────────────

@pytest.mark.asyncio
async def test_eval_count_est_lu_dans_l_evenement_final(monkeypatch) -> None:
    """`prompt_eval_count` était lu, `eval_count` ne l'était pas — alors qu'il
    arrive dans le même événement `done: true`, et que c'est LUI qui décide de
    `LLM_MAX_TOKENS`."""
    monkeypatch.setattr(
        llm.httpx,
        "AsyncClient",
        _flux_ollama(
            [
                {"message": {"content": "Réponse."}},
                {
                    "message": {"content": ""},
                    "done": True,
                    "prompt_eval_count": 3400,
                    "eval_count": 512,
                },
            ]
        ),
    )
    mesures: list[llm.PromptMeasure] = []

    tokens = [
        t
        async for t in llm.generate_stream(
            QUESTION, [_section()], on_measure=mesures.append
        )
    ]

    assert tokens == ["Réponse."]
    assert len(mesures) == 1
    assert mesures[0].eval_count == 512  # noqa: PLR2004
    assert mesures[0].prompt_eval_count == 3400  # noqa: PLR2004
    # Le plafond appliqué voyage avec la mesure : sans lui, « la génération a-t-
    # elle été coupée ? » n'est pas décidable depuis `eval_count` seul.
    assert mesures[0].num_predict == llm.settings.llm_max_tokens


@pytest.mark.asyncio
async def test_un_serveur_muet_ne_rend_pas_zero_token(monkeypatch) -> None:
    """« Pas de mesure » et « zéro token » sont deux choses différentes, et une
    moyenne qui les confondrait écraserait la distribution vers le bas — or c'est
    le HAUT qui décide du plafond."""
    monkeypatch.setattr(
        llm.httpx,
        "AsyncClient",
        _flux_ollama([{"message": {"content": "Réponse."}, "done": True}]),
    )
    mesures: list[llm.PromptMeasure] = []

    async for _ in llm.generate_stream(QUESTION, [_section()], on_measure=mesures.append):
        pass

    assert mesures[0].eval_count is None
    assert mesures[0].prompt_eval_count is None


@pytest.mark.asyncio
async def test_node_generate_publie_la_mesure_a_l_etat(monkeypatch) -> None:
    """La chaîne `on_measure` → état du graphe. Le lot 1 a construit
    l'instrumentation du prompt et RIEN ne l'a jamais observée, parce qu'elle ne
    sortait qu'en journal : c'est ce maillon-là qui manquait."""
    monkeypatch.setattr(
        llm.httpx,
        "AsyncClient",
        _flux_ollama(
            [
                {"message": {"content": "Réponse."}},
                {"message": {"content": ""}, "done": True, "eval_count": 77},
            ]
        ),
    )

    resultat = await graph_module.node_generate(
        {
            "question": QUESTION,
            "chat_history": [],
            "enriched_contexts": [_section()],
            "search_count": 0,
            "_metadata": {},
        }
    )

    assert resultat["generation_measure"].eval_count == 77  # noqa: PLR2004


@pytest.mark.asyncio
async def test_answer_publie_la_mesure_de_generation(monkeypatch) -> None:
    """La chaîne complète, jusqu'au corps HTTP que la campagne lit. Seule la
    couche Ollama est simulée : le vrai `node_generate` et le vrai
    `generate_stream` sont exercés."""
    from fastapi.testclient import TestClient

    from src.api import main

    monkeypatch.setattr(
        llm.httpx,
        "AsyncClient",
        _flux_ollama(
            [
                {"message": {"content": "Une réponse de douze caractères."}},
                {
                    "message": {"content": ""},
                    "done": True,
                    "prompt_eval_count": 3400,
                    "eval_count": 640,
                },
            ]
        ),
    )

    async def fake_ainvoke(state, _config=None):
        etat = {**state, "enriched_contexts": [_section()], "search_count": 0, "_metadata": {}}
        return {
            "reranked_chunks": [],
            "enriched_contexts": [_section()],
            "citations": [],
            "images": [],
            **await graph_module.node_generate(etat),
        }

    monkeypatch.setattr(main.answer_graph, "ainvoke", fake_ainvoke)
    body = TestClient(main.app).post("/answer", json={"question": QUESTION}).json()
    mesure = body["generation"]

    assert mesure["eval_count"] == 640  # noqa: PLR2004
    assert mesure["prompt_eval_count"] == 3400  # noqa: PLR2004
    assert mesure["prompt_tokens_estimated"] > 0
    assert mesure["num_predict"] == llm.settings.llm_max_tokens
    # La longueur de la réponse est celle du texte rendu, pas celle du flux : la
    # syntaxe d'appel d'outil en est retirée avant publication.
    assert mesure["answer_chars"] == len(body["answer"])


# ─── La décision « cache KV » doit rester unique ─────────────────────────────

def test_le_predicat_du_cache_kv_est_celui_du_journal(caplog) -> None:
    """**Deux prédicats séparés dériveraient.**

    Le lot 1 a documenté que `prompt_eval_count` est pollué par le cache KV
    d'Ollama et qu'il faut écarter les échantillons concernés. La campagne
    applique cette décision ; elle ne la refait pas. Ce test exige que le
    verdict et le journal disent la même chose sur la même valeur — un seuil
    recopié à deux endroits finirait par diverger, et la campagne publierait un
    ratio que le journal a refusé.
    """
    estime = 1000
    pollue = int(estime * llm._CACHE_HIT_RATIO) - 1
    propre = int(estime * llm._CACHE_HIT_RATIO) + 1

    assert llm.mesure_prompt_exploitable(estime, pollue) is False
    assert llm.mesure_prompt_exploitable(estime, propre) is True

    with caplog.at_level(logging.INFO, logger="src.agent.llm"):
        llm.log_prompt_measure(estime, pollue)
    assert "cache KV" in caplog.text

    caplog.clear()
    with caplog.at_level(logging.INFO, logger="src.agent.llm"):
        llm.log_prompt_measure(estime, propre)
    assert "cache KV" not in caplog.text


def test_sans_decompte_la_mesure_n_est_pas_exploitable() -> None:
    """Absent, zéro, ou face à une estimation nulle : dans les trois cas il n'y a
    rien à calibrer, et prétendre le contraire ferait entrer un zéro dans une
    moyenne de ratios."""
    assert llm.mesure_prompt_exploitable(1000, None) is False
    assert llm.mesure_prompt_exploitable(1000, 0) is False
    assert llm.mesure_prompt_exploitable(0, 3400) is False


@pytest.mark.asyncio
async def test_un_decompte_pollue_est_publie_mais_marque(monkeypatch) -> None:
    """La valeur brute reste rendue — l'écarter en silence perdrait l'information
    « Ollama a servi ce prompt depuis son cache ». C'est le drapeau qui décide de
    son usage, pas sa disparition."""
    monkeypatch.setattr(
        llm.httpx,
        "AsyncClient",
        _flux_ollama([{"message": {"content": "R."}, "done": True, "prompt_eval_count": 3}]),
    )
    mesures: list[llm.PromptMeasure] = []

    async for _ in llm.generate_stream(QUESTION, [_section()], on_measure=mesures.append):
        pass

    assert mesures[0].prompt_eval_count == 3  # noqa: PLR2004
    assert mesures[0].prompt_reliable is False


# ─── Ce que la campagne en fait ──────────────────────────────────────────────

def _ligne(evaluate, **generation) -> dict:
    return evaluate.evaluer(
        {"id": "G-001", "gold_element_ids": ["aaaaaaaaa1"], "language": "fr"},
        {
            "contexts": [],
            "citations": [],
            "answer": "y" * generation.pop("caracteres", 900),
            "generation": generation,
        },
    )


def test_la_campagne_compte_les_generations_qui_butent_sur_leur_plafond() -> None:
    """**Le test qui fait régresser la mesure.**

    C'est LE chiffre qui tranche `LLM_MAX_TOKENS`. Zéro sur tout le jeu = le
    plafond ne sert jamais, et les tokens qu'il réserve sont pris aux sources
    pour rien. Une valeur non nulle = le couper coûterait des réponses tronquées.
    """
    evaluate = _evaluate()
    au_plafond = [_ligne(evaluate, eval_count=4096, num_predict=4096) for _ in range(3)]
    en_dessous = [_ligne(evaluate, eval_count=300, num_predict=4096) for _ in range(3)]

    assert evaluate.resumer(au_plafond)["generations_au_plafond"] == 3  # noqa: PLR2004
    assert evaluate.resumer(en_dessous)["generations_au_plafond"] == 0
    # Et le plafond lui-même est publié : les trois centiles de `eval_count` ne
    # se lisent pas sans lui.
    assert evaluate.resumer(en_dessous)["num_predict"] == 4096  # noqa: PLR2004


def test_un_decompte_absent_ne_compte_pas_comme_une_generation_courte() -> None:
    """Un serveur qui ne rend pas `eval_count` ne doit pas peser zéro dans la
    distribution : `eval_count_sur` dit sur combien de réponses les centiles
    portent, et un zéro s'y verrait."""
    evaluate = _evaluate()
    lignes = [
        _ligne(evaluate, eval_count=800, num_predict=4096),
        _ligne(evaluate, num_predict=4096),
    ]

    resume = evaluate.resumer(lignes)

    assert resume["eval_count_sur"] == 1
    assert resume["eval_count_p50"] == 800  # noqa: PLR2004
    assert resume["generations_au_plafond"] == 0


def test_la_longueur_des_reponses_est_enregistree() -> None:
    """Aucun fichier de `runs/` ne la porte, donc les campagnes passées ne
    permettent pas de reconstituer la distribution après coup."""
    evaluate = _evaluate()
    lignes = [
        _ligne(evaluate, caracteres=100, num_predict=4096),
        _ligne(evaluate, caracteres=5000, num_predict=4096),
    ]

    resume = evaluate.resumer(lignes)

    assert resume["reponse_caracteres_max"] == 5000  # noqa: PLR2004
    assert resume["reponse_caracteres_p95"] == 5000  # noqa: PLR2004


def test_le_ratio_mesure_ecarte_les_echantillons_pollues() -> None:
    """`_CHARS_PER_TOKEN = 3,5` gouverne tout le budget de contexte et c'est un
    forfait depuis l'origine. Le calibrer sur un décompte servi depuis le cache
    KV le ferait fondre à chaque question — donc les échantillons écartés le
    sont, et leur nombre est dit."""
    evaluate = _evaluate()
    lignes = [
        # Décompte exploitable : le ratio réel vaut 3,5 × 4200/3500 = 4,2.
        _ligne(
            evaluate,
            prompt_eval_count=3500,
            prompt_tokens_estimated=4200,
            prompt_tokens_reliable=True,
            num_predict=4096,
        ),
        # Servie depuis le cache : elle rendrait un ratio absurde de 3,5 × 4200/10.
        _ligne(
            evaluate,
            prompt_eval_count=10,
            prompt_tokens_estimated=4200,
            prompt_tokens_reliable=False,
            num_predict=4096,
        ),
    ]

    resume = evaluate.resumer(lignes)

    assert resume["prompt_tokens_exploitables"] == 1
    assert resume["prompt_tokens_ecartes_cache_kv"] == 1
    assert resume["ratio_caracteres_par_token_mesure"] == pytest.approx(4.2)


def test_sans_aucun_decompte_exploitable_le_ratio_reste_indefini() -> None:
    """Rendre 3,5 — le forfait — se lirait « mesuré, et il vaut le forfait »."""
    evaluate = _evaluate()

    resume = evaluate.resumer([_ligne(evaluate, num_predict=4096)])

    assert resume["prompt_tokens_exploitables"] == 0
    assert resume["ratio_caracteres_par_token_mesure"] is None


# ─── Les strates vides ────────────────────────────────────────────────────────

def test_la_strate_des_questions_de_suivi_existe_meme_vide() -> None:
    """`chat_history` est présent sur 0 des 138 questions du jeu doré : la
    campagne ne peut RIEN voir du travail sur l'historique. Omettre la ligne se
    lit exactement comme une strate saine."""
    evaluate = _evaluate()
    autonome = evaluate.evaluer(
        {"id": "G-001", "gold_element_ids": ["aaaaaaaaa1"], "language": "fr"},
        {"contexts": [], "citations": [], "answer": "r"},
    )

    strates = evaluate.par_langue([autonome])

    assert "questions de suivi" in strates
    assert strates["questions de suivi"]["questions"] == 0
    assert strates["questions autonomes"]["questions"] == 1


def test_une_strate_vide_est_annoncee_comme_vide(capsys) -> None:
    """Elle doit dire « 0 question », pas afficher une moyenne calculée sur rien."""
    evaluate = _evaluate()
    ligne = evaluate.evaluer(
        {"id": "G-001", "gold_element_ids": ["aaaaaaaaa1"], "language": "fr"},
        {"contexts": [], "citations": [], "answer": "r"},
    )

    evaluate.afficher(evaluate.resumer([ligne]), evaluate.par_langue([ligne]), [ligne])
    sortie = capsys.readouterr().out

    assert "[questions de suivi] 0 question — STRATE VIDE" in sortie
    # Et la strate peuplée, elle, affiche bien ses moyennes.
    assert "[questions autonomes] {'questions': 1" in sortie


def test_une_question_de_suivi_peuple_la_strate() -> None:
    """Le pendant : le jour où le jeu doré porte des questions de suivi, la
    strate doit se remplir. Sans ce test, un `suivi` toujours faux resterait
    vert."""
    evaluate = _evaluate()
    suivi = evaluate.evaluer(
        {
            "id": "G-900",
            "gold_element_ids": ["aaaaaaaaa1"],
            "language": "fr",
            "chat_history": [{"role": "user", "content": "Et pour les femmes ?"}],
        },
        {"contexts": [], "citations": [], "answer": "r"},
    )

    strates = evaluate.par_langue([suivi])

    assert strates["questions de suivi"]["questions"] == 1
    assert strates["questions autonomes"]["questions"] == 0


def test_la_decoupe_translinguistique_est_publiee_meme_vide() -> None:
    """Elle n'apparaissait que lorsqu'elle était peuplée : le même défaut qu'au-
    dessus, à un cran de moins de gravité."""
    evaluate = _evaluate()
    ligne = evaluate.evaluer(
        {
            "id": "G-001",
            "gold_element_ids": ["aaaaaaaaa1"],
            "language": "fr",
            "doc_language": "fr",
        },
        {"contexts": [], "citations": [], "answer": "r"},
    )

    strates = evaluate.par_langue([ligne])

    assert strates["translinguistique"]["questions"] == 0
    assert strates["même langue"]["questions"] == 1
