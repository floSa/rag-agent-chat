"""Le lecteur de flux, et l'accumulation des appels d'outil fragmentés.

LES LIGNES DE CE FICHIER NE SONT PAS ÉCRITES DE MÉMOIRE. Elles ont été
capturées sur les deux moteurs du poste le 16 septembre 2026 entre 04:00 et
04:04 UTC, six requêtes, prompts tous distincts — un prompt répété est servi par
le cache de préfixe et ne mesure plus rien. Les recopier telles quelles est le
point : un test écrit d'après la forme qu'on CROIT connaître valide la croyance,
pas le serveur. C'est ce que le banc go/no-go demandait explicitement.

Deux défauts sont gardés ici, et ils vivent l'un derrière l'autre :

1. le lecteur cassait BRUYAMMENT sur le SSE (`json.loads` sur `data: {…}`) ;
2. derrière ce mur, SILENCIEUSEMENT : l'appel d'outil arrive fragmenté sur
   quatre événements dont aucun n'est jugeable seul, donc le rappel ne part
   jamais et la recherche supplémentaire disparaît sans erreur ni log.

Réparer (1) sans (2) rend (2) INVISIBLE : le flux passe, l'écran se remplit, et
l'agent a perdu sa capacité à relancer une recherche. Les scènes qui gardent (2)
sont donc les plus importantes du fichier, et ce sont celles qu'une lecture
distraite prendrait pour du zèle.
"""

import json

import pytest

from src.agent import llm
from src.agent.flux_llm import LecteurDeFlux
from src.agent.repli_outil import lire_et_retirer
from src.api.schemas import BreadcrumbEntry, SectionContext

# ─── les lignes RÉELLES, recopiées de la capture ─────────────────────────────

# `OLLAMA-STREAM-OUTIL-C`, 16/09 04:01:22 UTC — l'appel entier dans UN événement,
# `arguments` en OBJET, et l'index au niveau de la FONCTION.
OLLAMA_OUTIL = [
    '{"model":"gemma4:e4b","created_at":"2026-09-16T04:01:22.753887444Z","message":'
    '{"role":"assistant","content":"","tool_calls":[{"id":"call_t4f68yu2","function":'
    '{"index":0,"name":"search_vectors","arguments":{"query":"calcul de l\'ancienneté '
    'pour les contrats saisonniers agricoles"}}}]},"done":false}',
    '{"model":"gemma4:e4b","created_at":"2026-09-16T04:01:22.770357682Z","message":'
    '{"role":"assistant","content":""},"done":true,"done_reason":"stop",'
    '"total_duration":1260647990,"load_duration":762578893,"prompt_eval_count":108,'
    '"prompt_eval_duration":54316000,"eval_count":27,"eval_duration":427678000}',
]

# `OLLAMA-STREAM-TEXTE-D`, 16/09 04:01:36 UTC — le cas ORDINAIRE, sans outil.
OLLAMA_TEXTE = [
    '{"model":"gemma4:e4b","created_at":"2026-09-16T04:01:36.640366006Z","message":'
    '{"role":"assistant","content":"L"},"done":false}',
    '{"model":"gemma4:e4b","created_at":"2026-09-16T04:01:36.658774734Z","message":'
    '{"role":"assistant","content":"\'"},"done":false}',
    '{"model":"gemma4:e4b","created_at":"2026-09-16T04:01:36.679891095Z","message":'
    '{"role":"assistant","content":"ast"},"done":false}',
    '{"model":"gemma4:e4b","created_at":"2026-09-16T04:01:36.695325783Z","message":'
    '{"role":"assistant","content":"rol"},"done":false}',
    '{"model":"gemma4:e4b","created_at":"2026-09-16T04:01:36.712867139Z","message":'
    '{"role":"assistant","content":"abe"},"done":false}',
    '{"model":"gemma4:e4b","created_at":"2026-09-16T04:01:37.000000000Z","message":'
    '{"role":"assistant","content":""},"done":true,"done_reason":"stop",'
    '"prompt_eval_count":31,"eval_count":25}',
]

# `VLLM-STREAM-OUTIL-A`, 16/09 04:00:55 UTC — QUATRE événements pour UN appel,
# les lignes vides du SSE, la sentinelle finale. Rien n'est retiré ni réordonné.
VLLM_OUTIL = [
    'data: {"id":"chatcmpl-a5120c936915b91a","object":"chat.completion.chunk",'
    '"created":1789531255,"model":"google/gemma-4-E4B-it-qat-w4a16-ct","choices":'
    '[{"index":0,"delta":{"role":"assistant","content":""},"logprobs":null,'
    '"finish_reason":null}],"prompt_token_ids":null,"prompt_text":null}',
    "",
    'data: {"id":"chatcmpl-a5120c936915b91a","object":"chat.completion.chunk",'
    '"created":1789531255,"model":"google/gemma-4-E4B-it-qat-w4a16-ct","choices":'
    '[{"index":0,"delta":{"tool_calls":[{"id":"chatcmpl-tool-8194d2d4a1cec831",'
    '"type":"function","index":0,"function":{"name":"search_vectors"}}]},'
    '"logprobs":null,"finish_reason":null,"token_ids":null}]}',
    "",
    'data: {"id":"chatcmpl-a5120c936915b91a","object":"chat.completion.chunk",'
    '"created":1789531255,"model":"google/gemma-4-E4B-it-qat-w4a16-ct","choices":'
    '[{"index":0,"delta":{"tool_calls":[{"index":0,"function":{"arguments":'
    '"{\\"query\\": \\""}}]},"logprobs":null,"finish_reason":null,"token_ids":null}]}',
    "",
    'data: {"id":"chatcmpl-a5120c936915b91a","object":"chat.completion.chunk",'
    '"created":1789531255,"model":"google/gemma-4-E4B-it-qat-w4a16-ct","choices":'
    '[{"index":0,"delta":{"tool_calls":[{"index":0,"function":{"arguments":'
    '"régime indemnitaire des astreintes de nuit en foyer médicalisé"}}]},'
    '"logprobs":null,"finish_reason":null,"token_ids":null}]}',
    "",
    'data: {"id":"chatcmpl-a5120c936915b91a","object":"chat.completion.chunk",'
    '"created":1789531255,"model":"google/gemma-4-E4B-it-qat-w4a16-ct","choices":'
    '[{"index":0,"delta":{"tool_calls":[{"index":0,"function":{"arguments":'
    '"\\"}"}}]},"logprobs":null,"finish_reason":null,"token_ids":null}]}',
    "",
    'data: {"id":"chatcmpl-a5120c936915b91a","object":"chat.completion.chunk",'
    '"created":1789531255,"model":"google/gemma-4-E4B-it-qat-w4a16-ct","choices":'
    '[{"index":0,"delta":{},"logprobs":null,"finish_reason":"tool_calls",'
    '"stop_reason":50,"token_ids":null}],"system_fingerprint":"vllm-0.28.0-54757788"}',
    "",
    "data: [DONE]",
    "",
]

QUERY_VLLM = "régime indemnitaire des astreintes de nuit en foyer médicalisé"
QUERY_OLLAMA = "calcul de l'ancienneté pour les contrats saisonniers agricoles"

# `VLLM-STREAM-USAGE-B`, 16/09 04:01:09 UTC — la fin d'un flux demandé avec
# `stream_options: {"include_usage": true}`. L'événement d'usage porte
# `"choices": []`, une liste VIDE : `choices[0]` y lèverait `IndexError`.
VLLM_FIN_AVEC_USAGE = [
    'data: {"id":"chatcmpl-9c160edd762b3fa6","object":"chat.completion.chunk",'
    '"created":1789531269,"model":"google/gemma-4-E4B-it-qat-w4a16-ct","choices":'
    '[{"index":0,"delta":{"content":" mercure"},"logprobs":null,'
    '"finish_reason":null,"token_ids":null}]}',
    "",
    'data: {"id":"chatcmpl-9c160edd762b3fa6","object":"chat.completion.chunk",'
    '"created":1789531269,"model":"google/gemma-4-E4B-it-qat-w4a16-ct","choices":'
    '[{"index":0,"delta":{},"logprobs":null,"finish_reason":"stop",'
    '"stop_reason":106,"token_ids":null}]}',
    "",
    'data: {"id":"chatcmpl-9c160edd762b3fa6","object":"chat.completion.chunk",'
    '"created":1789531269,"model":"google/gemma-4-E4B-it-qat-w4a16-ct","choices":[],'
    '"usage":{"prompt_tokens":34,"total_tokens":56,"completion_tokens":22},'
    '"system_fingerprint":"vllm-0.28.0-54757788"}',
    "",
    "data: [DONE]",
    "",
]


def _lire_tout(lignes: list[str]) -> tuple[str, LecteurDeFlux]:
    lecteur = LecteurDeFlux()
    morceaux = []
    for ligne in lignes:
        morceaux.append(lecteur.lire(ligne))
        if lecteur.termine:
            break
    return "".join(morceaux), lecteur


# ─── le flux Ollama d'aujourd'hui, inchangé ──────────────────────────────────


def test_ollama_texte_ordinaire_rend_le_meme_texte() -> None:
    """Le cas ORDINAIRE, et il doit rester ordinaire : pas d'appel d'outil.

    C'est la scène qui garde la production d'aujourd'hui. Une régression ici
    n'est pas un risque futur, c'est une panne réelle.
    """
    texte, lecteur = _lire_tout(OLLAMA_TEXTE)
    assert texte == "L'astrolabe"
    assert lecteur.termine is True
    assert lecteur.message_outils() == {"tool_calls": []}
    assert llm.extract_tool_query(lecteur.message_outils()) is None


def test_ollama_decomptes_lus_dans_l_evenement_final() -> None:
    _, lecteur = _lire_tout(OLLAMA_TEXTE)
    assert lecteur.decomptes.prompt_eval_count == 31
    assert lecteur.decomptes.eval_count == 25


def test_ollama_appel_entier_dans_un_evenement() -> None:
    """L'appel qu'Ollama émet d'un bloc, avec `arguments` en OBJET."""
    texte, lecteur = _lire_tout(OLLAMA_OUTIL)
    assert texte == ""
    assert llm.extract_tool_query(lecteur.message_outils()) == QUERY_OLLAMA
    assert lecteur.decomptes.prompt_eval_count == 108
    assert lecteur.decomptes.eval_count == 27


def test_ollama_arguments_objet_ne_sont_pas_concatenes() -> None:
    """Un objet REMPLACE, il ne se concatène pas : la règle qui sépare les deux
    dialectes tient sur le type, et l'inverser rendrait ici une chaîne."""
    _, lecteur = _lire_tout(OLLAMA_OUTIL)
    arguments = lecteur.message_outils()["tool_calls"][0]["function"]["arguments"]
    assert isinstance(arguments, dict)
    assert arguments == {"query": QUERY_OLLAMA}


# ─── le flux vLLM, et l'appel fragmenté ──────────────────────────────────────


def test_vllm_quatre_evenements_rendent_un_appel_complet() -> None:
    """LA SCÈNE QUI DÉCIDE DU LOT.

    Quatre événements, aucun jugeable seul. Avant l'accumulation, le lecteur
    rendait `None` sur les quatre et le rappel ne partait jamais.
    """
    texte, lecteur = _lire_tout(VLLM_OUTIL)
    assert texte == ""
    appels = lecteur.message_outils()["tool_calls"]
    assert len(appels) == 1
    assert appels[0]["function"]["name"] == "search_vectors"
    assert llm.extract_tool_query(lecteur.message_outils()) == QUERY_VLLM


def test_vllm_aucun_fragment_pris_seul_ne_rend_une_query() -> None:
    """LE CONTRÔLE POSITIF DE LA SCÈNE AU-DESSUS.

    Sans lui, « l'accumulation marche » pourrait vouloir dire « un des fragments
    portait déjà l'appel entier », et la scène ne mesurerait rien. Elle mesure
    donc d'abord que le défaut EST là : chacune des quatre lignes, jugée seule
    comme l'ancien code le faisait, rend `None`.
    """
    vus = 0
    for ligne in VLLM_OUTIL:
        charge = ligne.removeprefix("data: ").strip()
        if not charge or charge == "[DONE]":
            continue
        delta = json.loads(charge)["choices"][0]["delta"]
        if llm.extract_tool_query(delta) is not None:
            vus += 1
    assert vus == 0


def test_arguments_en_trois_morceaux_dont_aucun_n_est_du_json() -> None:
    """La raison pour laquelle la décision ne se prend qu'À LA FIN."""
    morceaux = ['{"query": "', "durée du congé parental", '"}']
    for morceau in morceaux:
        with pytest.raises(json.JSONDecodeError):
            json.loads(morceau)

    lecteur = LecteurDeFlux()
    for morceau in morceaux:
        lecteur.lire(
            json.dumps(
                {
                    "choices": [
                        {
                            "delta": {
                                "tool_calls": [
                                    {"index": 0, "function": {"arguments": morceau}}
                                ]
                            }
                        }
                    ]
                }
            )
        )
    lecteur.lire(
        json.dumps(
            {
                "choices": [
                    {
                        "delta": {
                            "tool_calls": [
                                {"index": 0, "function": {"name": "search_vectors"}}
                            ]
                        }
                    }
                ]
            }
        )
    )
    assert llm.extract_tool_query(lecteur.message_outils()) == "durée du congé parental"


def test_sentinelle_de_fin_ne_leve_pas() -> None:
    """`data: [DONE]` n'est PAS du JSON. C'est la ligne qui faisait lever
    `json.loads`, et elle doit être reconnue avant lui."""
    lecteur = LecteurDeFlux()
    assert lecteur.lire("data: [DONE]") == ""
    assert lecteur.termine is True


def test_lignes_vides_du_sse_sautees() -> None:
    lecteur = LecteurDeFlux()
    for ligne in ("", "   ", "\t"):
        assert lecteur.lire(ligne) == ""
    assert lecteur.termine is False


def test_evenement_d_usage_a_choices_vide_et_ne_leve_pas() -> None:
    """Le piège que le banc n'avait pas relevé : `"choices": []`.

    C'est le SEUL événement qui porte les décomptes de vLLM, et c'est celui sur
    lequel `choices[0]` lève `IndexError`.
    """
    texte, lecteur = _lire_tout(VLLM_FIN_AVEC_USAGE)
    assert texte == " mercure"
    assert lecteur.termine is True
    assert lecteur.decomptes.prompt_eval_count == 34
    assert lecteur.decomptes.eval_count == 22


def test_sans_include_usage_les_decomptes_sont_une_absence_declaree() -> None:
    """`None` veut dire « le serveur ne l'a pas dit », pas zéro.

    Le flux `VLLM_OUTIL` a été demandé SANS `stream_options` et ne porte donc
    aucun `usage` — mesuré, pas supposé. Inventer un zéro ferait passer pour
    mesurée une fenêtre que personne n'a mesurée.
    """
    _, lecteur = _lire_tout(VLLM_OUTIL)
    assert lecteur.decomptes.prompt_eval_count is None
    assert lecteur.decomptes.eval_count is None


# ─── deux appels dans le même flux ───────────────────────────────────────────


def test_deux_appels_vllm_accumules_separement_par_index() -> None:
    """Mesuré 16/09 04:01:49 UTC : vLLM incrémente bien l'index (0 puis 1).

    Sans clé d'index, les fragments des deux appels se concatèneraient en une
    seule chaîne — et `json.loads` rendrait alors `None` sur les DEUX.
    """
    lecteur = LecteurDeFlux()
    fragments = [
        (0, {"name": "search_vectors"}),
        (0, {"arguments": '{"query": "'}),
        (0, {"arguments": "duree du preavis de demission d'un cadre"}),
        (0, {"arguments": '"}'}),
        (1, {"name": "search_vectors"}),
        (1, {"arguments": '{"query": "'}),
        (1, {"arguments": "calcul de l'indemnite de licenciement d'un ouvrier"}),
        (1, {"arguments": '"}'}),
    ]
    for index, fonction in fragments:
        lecteur.lire(
            json.dumps(
                {
                    "choices": [
                        {
                            "delta": {
                                "tool_calls": [{"index": index, "function": fonction}]
                            }
                        }
                    ]
                }
            )
        )
    appels = lecteur.message_outils()["tool_calls"]
    assert len(appels) == 2
    assert json.loads(appels[0]["function"]["arguments"])["query"] == (
        "duree du preavis de demission d'un cadre"
    )
    assert json.loads(appels[1]["function"]["arguments"])["query"] == (
        "calcul de l'indemnite de licenciement d'un ouvrier"
    )


def test_deux_appels_ollama_sur_deux_evenements() -> None:
    """Mesuré 16/09 04:03:57 UTC : Ollama AUSSI étale deux appels sur deux
    événements et incrémente `function.index`. La lecture ligne à ligne n'en
    voyait donc jamais que le premier, y compris sur le moteur servi."""
    lecteur = LecteurDeFlux()
    for index, query in ((0, "heures supplementaires"), (1, "prime de panier")):
        lecteur.lire(
            json.dumps(
                {
                    "message": {
                        "content": "",
                        "tool_calls": [
                            {
                                "id": f"call_{index}",
                                "function": {
                                    "index": index,
                                    "name": "search_vectors",
                                    "arguments": {"query": query},
                                },
                            }
                        ],
                    },
                    "done": False,
                }
            )
        )
    appels = lecteur.message_outils()["tool_calls"]
    assert len(appels) == 2
    assert appels[0]["function"]["arguments"] == {"query": "heures supplementaires"}
    assert appels[1]["function"]["arguments"] == {"query": "prime de panier"}


def test_deux_appels_sans_index_ne_se_recouvrent_pas() -> None:
    """Le dernier repli : sans index d'aucune sorte, c'est la POSITION dans la
    liste qui sépare. Sans lui, les deux appels partageraient la clé `None` et
    le second écraserait le premier."""
    lecteur = LecteurDeFlux()
    lecteur.lire(
        json.dumps(
            {
                "message": {
                    "tool_calls": [
                        {"function": {"name": "search_vectors", "arguments": {"query": "un"}}},
                        {"function": {"name": "search_vectors", "arguments": {"query": "deux"}}},
                    ]
                }
            }
        )
    )
    appels = lecteur.message_outils()["tool_calls"]
    assert len(appels) == 2
    assert appels[0]["function"]["arguments"] == {"query": "un"}
    assert appels[1]["function"]["arguments"] == {"query": "deux"}


# ─── la fuite dans le texte ──────────────────────────────────────────────────


def test_le_lecteur_cede_la_fuite_en_sentinelles_comme_du_texte() -> None:
    """CE QUE NOTRE LECTEUR FAIT de la forme `<|tool_call>…<tool_call|>`.

    Il la cède comme du texte, et c'est une limite ASSUMÉE, pas un oubli : un
    flux se cède token par token, et une sentinelle à cheval sur deux tokens ne
    se retire pas sans retenir tout le flux — ce qui rendrait l'écran muet. Le
    retrait a UN site, et il travaille sur la réponse assemblée : voir la scène
    suivante.
    """
    fuite = '<|tool_call>call:search_vectors{"query": "duree du preavis"}<tool_call|>'
    lecteur = LecteurDeFlux()
    texte = "".join(
        lecteur.lire(json.dumps({"message": {"content": morceau}}))
        for morceau in ("Je cherche. ", fuite)
    )
    assert texte == "Je cherche. " + fuite
    # Et elle n'est PAS prise pour un appel structuré : rien ne s'accumule.
    assert lecteur.message_outils() == {"tool_calls": []}


def test_la_fuite_en_sentinelles_est_retiree_de_la_reponse_assemblee() -> None:
    """Le rideau la reconnaît ET la retire, du même motif, en un passage.

    Sans ce garde, la forme partait à l'écran telle quelle : le motif du lot 19
    exige une parenthèse et une chaîne entre guillemets, que cette forme n'a pas.
    """
    fuite = '<|tool_call>call:search_vectors{"query": "duree du preavis"}<tool_call|>'
    query, texte = lire_et_retirer(f"Je cherche. {fuite} Voilà.")
    assert query == "duree du preavis"
    assert "tool_call" not in texte
    assert texte == "Je cherche.  Voilà."


def test_la_fuite_sans_arguments_part_quand_meme_de_l_ecran() -> None:
    """`{}` ne porte aucune sous-question — le bloc reste du bruit d'écran."""
    query, texte = lire_et_retirer("Réponse. <|tool_call>call:search_vectors{}<tool_call|>")
    assert query is None
    assert texte == "Réponse."


def test_un_texte_ordinaire_traverse_le_rideau_intact() -> None:
    """LE CONTRÔLE POSITIF DU RIDEAU : il doit DISCRIMINER, pas seulement
    trouver. Une sonde qui attrape tout ne prouve rien."""
    ordinaire = "Le préavis est de trois mois selon l'article 12."
    assert lire_et_retirer(ordinaire) == (None, ordinaire)


# ─── le rappel, et il ne part QU'UNE FOIS ────────────────────────────────────


def _section() -> SectionContext:
    return SectionContext(
        element_id="abcdef0123",
        section_id="sssssssss1",
        breadcrumbs=[BreadcrumbEntry(node_id="doc0000001", label="Document", text="Atelier")],
        elements=[],
        markdown="Le préavis est de trois mois. [src:abcdef0123]",
    )


def _flux_brut(lignes: list[str]):
    """Un double de client httpx qui rend les lignes TELLES QUELLES.

    Il ne ré-encode rien : c'est ce qui permet de donner au lecteur le `data: `
    et les lignes vides du SSE, que tout double travaillant en `json.dumps` sur
    des dicts effacerait — et le test validerait alors une forme que le serveur
    n'émet pas.
    """

    class Resp:
        def raise_for_status(self) -> None: ...

        async def aiter_lines(self):
            for ligne in lignes:
                yield ligne

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


async def _collecter(monkeypatch, lignes: list[str]) -> tuple[str, list[str]]:
    monkeypatch.setattr(llm.httpx, "AsyncClient", _flux_brut(lignes))
    appels: list[str] = []
    morceaux = [
        token
        async for token in llm.generate_stream(
            "Quelle est la durée du préavis ?",
            [_section()],
            on_tool_call=appels.append,
        )
    ]
    return "".join(morceaux), appels


@pytest.mark.asyncio
async def test_rappel_appele_une_seule_fois_sur_quatre_fragments(monkeypatch) -> None:
    """LE GARDE DU PLAFOND D'ITÉRATIONS.

    Quatre fragments, UN rappel. Un rappel posé dans la boucle en ferait partir
    quatre : l'agent lancerait quatre recherches pour un appel et
    `max_search_iterations` avalerait son plafond en silence.
    """
    _, appels = await _collecter(monkeypatch, VLLM_OUTIL)
    assert appels == [QUERY_VLLM]


@pytest.mark.asyncio
async def test_rappel_appele_une_seule_fois_sur_ollama(monkeypatch) -> None:
    """Le moteur SERVI aujourd'hui : même compte, même query qu'avant le lot."""
    texte, appels = await _collecter(monkeypatch, OLLAMA_OUTIL)
    assert texte == ""
    assert appels == [QUERY_OLLAMA]


@pytest.mark.asyncio
async def test_flux_ollama_ordinaire_ne_declenche_aucun_rappel(monkeypatch) -> None:
    texte, appels = await _collecter(monkeypatch, OLLAMA_TEXTE)
    assert texte == "L'astrolabe"
    assert appels == []


@pytest.mark.asyncio
async def test_flux_vllm_ordinaire_rend_son_texte_et_ne_leve_pas(monkeypatch) -> None:
    """Le SSE de bout en bout à travers `generate_stream` : préfixe, lignes
    vides, `[DONE]`. C'est ce parcours-là qui levait `JSONDecodeError`."""
    texte, appels = await _collecter(monkeypatch, VLLM_FIN_AVEC_USAGE)
    assert texte == " mercure"
    assert appels == []


@pytest.mark.asyncio
async def test_ligne_ni_vide_ni_sentinelle_ni_json_leve_toujours(monkeypatch) -> None:
    """Le bruit RESTE bruyant.

    Un dialecte inconnu doit casser fort : c'est ce bruit qui a permis au banc
    de MESURER le défaut du SSE au lieu de le subir. L'absorber rendrait ce
    lecteur silencieux sur sa propre panne — exactement la famille de défaut
    que ce chantier poursuit.
    """
    with pytest.raises(json.JSONDecodeError):
        await _collecter(monkeypatch, ["ceci n'est pas du json"])


@pytest.mark.asyncio
async def test_erreur_annoncee_par_le_serveur_leve(monkeypatch) -> None:
    with pytest.raises(RuntimeError, match="modèle introuvable"):
        await _collecter(monkeypatch, ['{"error":"modèle introuvable"}'])
