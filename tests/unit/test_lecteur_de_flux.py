"""Le lecteur de flux, et l'accumulation des appels d'outil fragmentés.

CE FICHIER MÊLE DES SCÈNES RELEVÉES ET DES SCÈNES CONSTRUITES, ET IL LE DIT
SCÈNE PAR SCÈNE. Sa première rédaction affirmait en capitales que ses lignes
« ne sont pas écrites de mémoire », ce qui ne vaut que pour une partie d'entre
elles ; un audit l'a relevé, et c'était le même piège qu'un audit précédent
avait relevé au même endroit de ce chantier. Une scène construite qui se
présente comme mesurée est une mesure fausse qui se présente comme honnête —
la famille de défaut que ce chantier poursuit — et elle est plus chère ici
qu'ailleurs, parce que c'est sur ces lignes que le lecteur est jugé.

L'INVENTAIRE, REFAIT À LA MAIN LE 16 SEPTEMBRE 2026 SUR LES 27 SCÈNES D'ALORS :

- **12 RELEVÉES** — elles s'appuient sur l'une des quatre constantes capturées
  ci-dessous (`OLLAMA_OUTIL`, `OLLAMA_TEXTE`, `VLLM_OUTIL`,
  `VLLM_FIN_AVEC_USAGE`), recopiées telles quelles d'un flux réel.
- **1 RECOPIÉE** — `test_sentinelle_de_fin_ne_leve_pas` écrit en littéral une
  ligne (`data: [DONE]`) qui figure telle quelle dans la capture.
- **1 MIXTE** — `test_lignes_vides_du_sse_sautees` : la ligne vide est relevée,
  l'espace et la tabulation sont construites.
- **13 CONSTRUITES** — lignes fabriquées pour présenter une forme au lecteur.
  Chacune porte désormais dans sa docstring ce qu'elle construit et pourquoi.

Les quatre constantes, elles, ont bien été capturées sur les deux moteurs du
poste le 16 septembre 2026 entre 04:00 et 04:04 UTC, six requêtes, prompts tous
distincts — un prompt répété est servi par le cache de préfixe et ne mesure plus
rien. Les recopier telles quelles est le point : un test écrit d'après la forme
qu'on CROIT connaître valide la croyance, pas le serveur.

UNE SCÈNE CONSTRUITE N'EST PAS UNE SCÈNE MOINS BONNE. Elle est le seul moyen de
tenir une ligne défensive — une ligne que les moteurs du poste n'exercent pas et
qu'un refactor pourrait donc retirer sans que rien ne rougisse. Ce qu'elle ne
peut pas faire, c'est prétendre qu'un serveur écrit ce qu'elle écrit.

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
from src.agent.flux_llm import Decomptes, LecteurDeFlux
from src.agent.repli_outil import lire_et_retirer
from src.api.schemas import BreadcrumbEntry, SectionContext

# ─── les lignes RÉELLES, recopiées de la capture ─────────────────────────────

# LES DEUX CAPTURES DE L'ANCIEN MOTEUR ONT ÉTÉ RETIRÉES AU LOT 28, avec les
# quatre scènes qui les lisaient. Elles décrivaient un dialecte dont le lecteur
# ne connaît plus la forme : `message` à la racine, la fin par `done: true`, les
# décomptes qu'elle portait, l'index d'appel rangé sous `function`, et les
# arguments rendus en OBJET. Un garde qui fige une forme que le dépôt ne lit plus
# ne garde rien — il fait croire qu'il garde.
#
# CE QUI LES REMPLACE N'EST PAS RIEN : `test_la_forme_de_l_ancien_moteur_ne_cede
# _plus_rien` tient le CONTRÔLE NÉGATIF du retrait, en vérifiant qu'un flux de
# cette forme ne cède aucun texte et n'accumule aucun appel. Sans lui, la lecture
# de l'autre dialecte pourrait revenir sans que rien ne le dise.

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


# ─── LE CONTRÔLE NÉGATIF DU RETRAIT ──────────────────────────────────────────


def test_la_forme_de_l_ancien_moteur_ne_cede_plus_rien() -> None:
    """CE QUE LE LOT 28 A RETIRÉ, MESURÉ PLUTÔT QU'AFFIRMÉ.

    Quatre scènes lisaient ici les captures NDJSON de l'ancien moteur. Elles
    partent avec son support ; ce qui reste est la vérification que sa forme
    n'est PLUS lue — sans quoi elle pourrait revenir sans que rien ne le dise,
    et un lecteur qui accepte deux formes n'est plus le lecteur d'UNE forme.

    Les trois marques de ce dialecte sont éprouvées ensemble, parce qu'un retrait
    partiel serait le pire des deux mondes : le texte à la racine, la fin par
    `done: true`, et les décomptes que cet événement portait.
    """
    lecteur = LecteurDeFlux()
    cede = lecteur.lire(
        json.dumps({"message": {"role": "assistant", "content": "L'astrolabe"}, "done": False})
    )
    assert cede == "", "le texte de l'ancien dialecte est encore cédé"

    fin = lecteur.lire(
        json.dumps(
            {
                "message": {"content": ""},
                "done": True,
                "prompt_eval_count": 31,
                "eval_count": 25,
            }
        )
    )
    assert fin == ""
    assert lecteur.termine is False, "la fin par `done: true` est encore reconnue"
    assert lecteur.decomptes == Decomptes(), (
        "les décomptes de l'ancien dialecte sont encore lus : une campagne les "
        "publierait comme s'ils venaient du serveur qui sert"
    )


def test_un_appel_d_outil_de_l_ancien_moteur_n_est_plus_accumule() -> None:
    """La seconde moitié du contrôle négatif, et c'est la plus silencieuse.

    L'appel entier dans UN événement, `arguments` en OBJET, l'index sous
    `function` : les trois marques de l'autre dialecte, dans la même ligne. Rien
    ne doit s'accumuler — et si quelque chose s'accumulait, la recherche partirait
    sur une sous-question qu'aucun serveur du poste n'a demandée.
    """
    lecteur = LecteurDeFlux()
    lecteur.lire(
        json.dumps(
            {
                "message": {
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call_t4f68yu2",
                            "function": {
                                "index": 0,
                                "name": "search_vectors",
                                "arguments": {"query": "calcul de l'ancienneté"},
                            },
                        }
                    ],
                },
                "done": False,
            }
        )
    )
    assert lecteur.message_outils() == {"tool_calls": []}
    assert llm.extract_tool_query(lecteur.message_outils()) is None


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


def test_json_valide_qui_n_est_pas_un_objet_ne_leve_pas() -> None:
    """Trois mutations de ce fichier ont SURVÉCU au premier jet, et celle-ci en
    était une : le garde `isinstance(data, dict)` n'était couvert par rien.

    Le texte qui sépare le code servi du mutant : une ligne de JSON PARFAITEMENT
    VALIDE qui n'est pas un objet. Sans le garde, `data.get("error")` lève
    `AttributeError: 'NoneType' object has no attribute 'get'` — une panne qui
    traverse le graphe jusqu'à la route, comme `_contenu_message` l'a déjà payé
    en non-streaming. C'est la forme qu'un proxy en erreur ou un backend
    « compatible » produit.
    """
    for ligne in ("null", '"un texte"', "[]", "42"):
        lecteur = LecteurDeFlux()
        assert lecteur.lire(ligne) == ""
        assert lecteur.message_outils() == {"tool_calls": []}


def test_sentinelle_avec_espace_surnumeraire_termine_quand_meme() -> None:
    """Le second survivant : le `.strip()` posé après le retrait du préfixe.

    Le texte qui sépare : `data:  [DONE]`, avec DEUX espaces. Sans le `strip`,
    la charge vaut ` [DONE]`, la comparaison échoue, et `json.loads` lève sur la
    sentinelle — exactement le défaut d'origine, en plus rare.

    AUCUN DES DEUX MOTEURS DU POSTE N'ÉMET CETTE FORME : les quatorze lignes
    capturées le 16/09 portent toutes une espace unique. Ce garde tient donc une
    tolérance DÉFENSIVE, pas un dialecte mesuré — et il est écrit ici pour que
    le `strip` ne puisse pas disparaître en silence, pas pour prétendre qu'un
    serveur l'exige.
    """
    lecteur = LecteurDeFlux()
    assert lecteur.lire("data:  [DONE]") == ""
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


# ─── les décomptes : une branche n'efface pas ce que l'autre a donné ─────────
#
# LE DÉFAUT QUE CES QUATRE SCÈNES FERMENT. `_lire_decomptes` écrivait ses deux
# branches INCONDITIONNELLEMENT, l'une après l'autre, chacune construisant un
# `Decomptes` neuf. Un événement portant `done: true`, ses compteurs, ET un
# `usage` — même vide — rendait donc `(None, None)`. Une mesure RÉELLE devenait
# une absence DÉCLARÉE, et `mesure_prompt_exploitable` la croyait honnête : le
# contraire exact de ce que la docstring de `Decomptes` promet.
#
# CES QUATRE SCÈNES SONT CONSTRUITES, sauf la dernière. Aucun moteur du poste
# n'écrit les deux dialectes dans le même flux, et c'est mesuré DANS LES DEUX
# SENS le 16 septembre 2026 à 07:26 UTC : `ollama-central` n'émet aucun `usage`
# (61 événements, 0 occurrence), `vllm-central` n'émet aucun `done` (62
# événements JSON, 0 occurrence). Le chemin gardé est celui d'un PROXY qui mêle
# les deux — et le module se présente comme lisant « la FORME, pas un réglage ».


def test_un_usage_partiel_n_efface_pas_un_decompte_deja_lu() -> None:
    """SCÈNE CONSTRUITE : deux événements d'usage, dont le second incomplet.

    LE DÉFAUT QU'ELLE GARDE A SURVÉCU AU LOT 28. Il naissait de deux branches
    qui s'écrasaient l'une l'autre ; il n'en reste qu'une, et la règle qu'elle
    porte — `_renseigner` ne remplace QUE ce qu'on lui donne — reste exerçable
    par un serveur qui émettrait plusieurs `usage`. C'est le cas de
    `continuous_usage_stats`, que `dialecte_llm` ne demande pas mais que le
    serveur accepte (`mesuré` 16/09 07:49 UTC, 42 événements).

    Sans cette règle, un second événement qui ne renseigne que `total_tokens`
    ferait retomber deux décomptes RÉELS à `None` — une mesure vraie changée en
    absence déclarée, que `mesure_prompt_exploitable` croirait honnête.
    """
    lecteur = LecteurDeFlux()
    lecteur.lire(
        "data: " + json.dumps(
            {"choices": [], "usage": {"prompt_tokens": 108, "completion_tokens": 27}}
        )
    )
    lecteur.lire("data: " + json.dumps({"choices": [], "usage": {"total_tokens": 135}}))
    assert lecteur.decomptes.prompt_eval_count == 108
    assert lecteur.decomptes.eval_count == 27


def test_un_usage_vide_n_efface_pas_un_decompte_deja_lu() -> None:
    """SCÈNE CONSTRUITE : la variante la plus discrète du même défaut.

    Un objet vide est bien un `dict`, donc la branche s'exécute — et sans la
    règle de préservation, elle écraserait tout avec rien.
    """
    lecteur = LecteurDeFlux()
    lecteur.lire(
        "data: " + json.dumps(
            {"choices": [], "usage": {"prompt_tokens": 108, "completion_tokens": 27}}
        )
    )
    lecteur.lire("data: " + json.dumps({"choices": [], "usage": {}}))
    assert lecteur.decomptes == Decomptes(prompt_eval_count=108, eval_count=27)


def test_un_usage_cumulatif_rend_le_dernier_compte_et_non_le_premier() -> None:
    """SCÈNE RELEVÉE, et c'est elle qui TRANCHE la règle de conflit.

    `mesuré` le 16 septembre 2026 à 07:49 UTC sur `vllm-central` : avec
    `stream_options: {"include_usage": true, "continuous_usage_stats": true}`,
    le serveur émet un `usage` sur CHAQUE événement, cumulatif —
    `completion_tokens` monte de 0 à 40 sur 42 événements. Les trois lignes
    ci-dessous sont recopiées de cette capture, allégées de leurs champs
    d'identité.

    C'EST CE QUI INTERDIT LA RÈGLE « LE PREMIER RENSEIGNÉ GAGNE ». Elle paraît
    plus sûre — une mesure acquise ne bougerait plus — et elle figerait ici le
    compte à ZÉRO token généré, c'est-à-dire la mesure fausse même que les
    trois scènes au-dessus existent pour empêcher. La règle servie est donc :
    chaque champ est remplacé par la DERNIÈRE valeur qui le renseigne.
    """
    lignes = [
        'data: {"choices":[{"index":0,"delta":{"content":"Le"},"finish_reason":null}],'
        '"usage":{"prompt_tokens":29,"total_tokens":30,"completion_tokens":1}}',
        'data: {"choices":[{"index":0,"delta":{"content":" pendule"},"finish_reason":null}],'
        '"usage":{"prompt_tokens":29,"total_tokens":31,"completion_tokens":2}}',
        'data: {"choices":[{"index":0,"delta":{},"finish_reason":"length"}],'
        '"usage":{"prompt_tokens":29,"total_tokens":69,"completion_tokens":40}}',
        "data: [DONE]",
    ]
    texte, lecteur = _lire_tout(lignes)
    assert texte == "Le pendule"
    assert lecteur.decomptes.prompt_eval_count == 29
    assert lecteur.decomptes.eval_count == 40


# ─── les trois lignes DÉFENSIVES, et elles sont nommées comme telles ─────────
#
# Une ligne défensive gardée est un acquis ; une ligne défensive muette est une
# dette — rien ne rougit si un refactor la retire, et personne ne sait dire si
# elle protégeait quelque chose. Les trois scènes qui suivent tiennent des
# lignes que LES MOTEURS DU POSTE N'EXERCENT PAS, et chacune dit laquelle et
# pourquoi le moteur ne l'exerce pas.


def test_un_nom_vide_n_ecrase_pas_le_nom_acquis() -> None:
    """DÉFENSIVE — la ligne tenue est `and nom` dans `_accumuler`.

    POURQUOI LES MOTEURS NE L'EXERCENT PAS : vLLM OMET `name` dans les
    fragments qui suivent le premier (`mesuré`, capture `VLLM_OUTIL` : le nom
    n'est que dans le deuxième événement) — il ne l'y met pas à `""`. La scène
    présente donc une forme construite : un fragment portant `"name": ""`
    APRÈS celui qui portait le nom.

    Sans `and nom`, `fragment["name"]` retomberait à la chaîne vide, le nom ne
    serait plus `search_vectors`, et `extract_tool_query` rendrait `None` — la
    recherche partirait à la poubelle sans erreur ni log.
    """
    lecteur = LecteurDeFlux()
    for fonction in (
        {"name": "search_vectors"},
        {"arguments": '{"query": "prime de nuit"}'},
        {"name": ""},
    ):
        lecteur.lire(
            json.dumps(
                {"choices": [{"delta": {"tool_calls": [{"index": 0, "function": fonction}]}}]}
            )
        )
    assert lecteur.message_outils()["tool_calls"][0]["function"]["name"] == "search_vectors"
    assert llm.extract_tool_query(lecteur.message_outils()) == "prime de nuit"


def test_l_ordre_d_apparition_prime_sur_l_ordre_des_index() -> None:
    """DÉFENSIVE — la ligne tenue est `self._ordre`, et non un tri des clés.

    POURQUOI LE SERVEUR NE L'EXERCE PAS : il émet ses index dans l'ordre
    croissant (`mesuré`, 0 puis 1), donc un tri rendrait aujourd'hui exactement
    la même chose. La scène construit l'ordre
    inverse — index 1 PUIS index 0 — que seule une clé non comparable ou un
    serveur qui réordonne produirait.

    CE QUE LA LIGNE ÉVITE N'EST PAS UNE ERREUR VISIBLE : c'est que l'agent
    parte chercher L'AUTRE sous-question que celle que le modèle a demandée en
    premier. Un tri change la réponse servie, silencieusement.
    """
    lecteur = LecteurDeFlux()
    for index, query in ((1, "PREMIER demande"), (0, "SECOND demande")):
        lecteur.lire(
            "data: " + json.dumps(
                {
                    "choices": [
                        {
                            "delta": {
                                "tool_calls": [
                                    {
                                        "index": index,
                                        "function": {
                                            "name": "search_vectors",
                                            "arguments": json.dumps({"query": query}),
                                        },
                                    }
                                ]
                            }
                        }
                    ]
                }
            )
        )
    appels = lecteur.message_outils()["tool_calls"]
    # Les arguments sont une CHAÎNE JSON dans ce dialecte : on la relit plutôt
    # que de la supposer déjà décodée.
    assert [json.loads(a["function"]["arguments"])["query"] for a in appels] == [
        "PREMIER demande",
        "SECOND demande",
    ]
    assert llm.extract_tool_query(lecteur.message_outils()) == "PREMIER demande"


def test_un_usage_qui_n_est_pas_un_objet_ne_leve_pas() -> None:
    """DÉFENSIVE — la ligne tenue est `isinstance(usage, dict)`.

    POURQUOI LES MOTEURS NE L'EXERCENT PAS : `vllm-central` n'écrit un `usage`
    que sous forme d'objet, et n'en met aucun sur les chunks ordinaires sans
    `include_usage` (`mesuré` 16/09 07:26 UTC : 1 `usage` sur 62 événements,
    zéro `usage: null`). La scène construit un `usage` scalaire, tel qu'un
    proxy en erreur pourrait l'écrire.

    Écrire `usage is not None` à la place ferait lever `AttributeError:
    'int' object has no attribute 'get'` AU MILIEU du flux — une panne qui
    traverse le graphe jusqu'à la route, sur l'événement qui porte les
    décomptes et lui seul.
    """
    for aberrant in (42, "34", [34, 22], True):
        lecteur = LecteurDeFlux()
        assert lecteur.lire(json.dumps({"choices": [], "usage": aberrant})) == ""
        assert lecteur.decomptes == Decomptes()


# ─── deux appels dans le même flux ───────────────────────────────────────────


def test_deux_appels_vllm_accumules_separement_par_index() -> None:
    """SCÈNE CONSTRUITE d'après un FAIT mesuré, et les deux mots comptent.

    LE FAIT est mesuré : le 16/09 à 04:01:49 UTC, vLLM incrémente bien l'index
    (0 puis 1) sur deux appels — remesuré depuis, il se reproduit. LES LIGNES,
    elles, sont reconstruites par `json.dumps` : elles ne portent ni `id`, ni
    `created`, ni `logprobs`, et ne sont donc PAS les lignes du serveur. La
    rédaction d'origine disait « Mesuré » tout court, ce qui laissait croire
    l'inverse — une scène construite qui se présente comme mesurée, exactement
    ce que l'en-tête de ce fichier interdit désormais.

    Ce que la scène garde : sans clé d'index, les fragments des deux appels se
    concatèneraient en une seule chaîne — et `json.loads` rendrait alors `None`
    sur les DEUX.
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


def test_deux_appels_sans_index_ne_se_recouvrent_pas() -> None:
    """Le dernier repli : sans index d'aucune sorte, c'est la POSITION dans la
    liste qui sépare. Sans lui, les deux appels partageraient la clé `None` et
    le second écraserait le premier."""
    lecteur = LecteurDeFlux()
    lecteur.lire(
        "data: " + json.dumps(
            {
                "choices": [
                    {
                        "delta": {
                            "tool_calls": [
                                {
                                    "function": {
                                        "name": "search_vectors",
                                        "arguments": json.dumps({"query": "un"}),
                                    }
                                },
                                {
                                    "function": {
                                        "name": "search_vectors",
                                        "arguments": json.dumps({"query": "deux"}),
                                    }
                                },
                            ]
                        }
                    }
                ]
            }
        )
    )
    appels = lecteur.message_outils()["tool_calls"]
    assert len(appels) == 2
    assert json.loads(appels[0]["function"]["arguments"]) == {"query": "un"}
    assert json.loads(appels[1]["function"]["arguments"]) == {"query": "deux"}


# ─── un événement qui porte du texte ET un appel ─────────────────────────────


def test_un_evenement_qui_porte_du_texte_et_un_appel_ne_perd_pas_l_appel() -> None:
    """SCÈNE CONSTRUITE, ET JE LE DÉCLARE : je n'ai pas su la faire produire.

    CE QUE LA SCÈNE GARDE. Le lecteur accumule les `tool_calls` d'un événement
    SANS regarder son `content`. Lier les deux — n'accumuler que lorsque le
    contenu est vide — fait disparaître l'appel sans erreur, sans log, avec un
    HTTP 200 et des tokens qui s'affichent normalement : la famille de défaut
    exacte que ce module existe pour fermer.

    CE QUE JE N'AI PAS SU MESURER, ET JE NE L'ÉCRIS PAS AUTREMENT. Trois
    requêtes ont demandé explicitement du texte PUIS un appel dans la même
    réponse (`mesuré` 16/09 entre 07:26 et 07:27 UTC). `vllm-central`,
    `finish_reason: "tool_calls"` : les quatre fragments portant `tool_calls`
    ont `content: null`.

    Le serveur SÉPARE. La forme ci-dessous est donc fabriquée, et sa
    représentabilité aujourd'hui n'est PAS établie — une requête ne fait pas
    une propriété, dans un sens comme dans l'autre. Ce que ce garde tient est
    une ligne non exercée, pas un dialecte mesuré.
    """
    lecteur = LecteurDeFlux()
    texte = lecteur.lire(
        "data: " + json.dumps(
            {
                "choices": [
                    {
                        "delta": {
                            "content": "Je consulte les textes. ",
                            "tool_calls": [
                                {
                                    "id": "call_mele",
                                    "index": 0,
                                    "function": {
                                        "name": "search_vectors",
                                        "arguments": json.dumps({"query": "titres restaurant"}),
                                    },
                                }
                            ],
                        }
                    }
                ]
            }
        )
    )
    assert texte == "Je consulte les textes. "
    assert llm.extract_tool_query(lecteur.message_outils()) == "titres restaurant"


# ─── l'erreur n'arrive pas toujours en première ligne ────────────────────────


def test_une_erreur_arrivant_apres_des_tokens_leve_aussi() -> None:
    """SCÈNE CONSTRUITE d'après une forme documentée d'Ollama.

    LE GARDE QUI EXISTAIT NE TENAIT QUE LE PREMIER ÉVÉNEMENT. Une variante du
    lecteur qui ne lève que sur la toute première ligne lue passait les 937
    tests du dépôt : le cas était correct dans le code et absent des scènes.

    Il n'est pas théorique. Un moteur qui meurt EN COURS de génération annonce
    son erreur après avoir déjà cédé des tokens. Sans levée, la réponse est
    tronquée EN SILENCE : l'écran montre un début de phrase et l'utilisateur le
    lit comme une réponse.
    """
    def jeton(texte: str) -> str:
        return "data: " + json.dumps({"choices": [{"delta": {"content": texte}}]})

    lecteur = LecteurDeFlux()
    assert lecteur.lire(jeton("Le préavis ")) == "Le préavis "
    assert lecteur.lire(jeton("est de ")) == "est de "
    with pytest.raises(RuntimeError, match="engine core proc died unexpectedly"):
        lecteur.lire("data: " + json.dumps({"error": "engine core proc died unexpectedly"}))


def test_une_erreur_enveloppee_en_sse_apres_des_tokens_leve_aussi() -> None:
    """SCÈNE CONSTRUITE : la même erreur, dans l'autre enveloppe.

    Le préfixe `data: ` est retiré avant le `json.loads`, donc le garde
    d'erreur doit valoir pour les deux dialectes — et pour un événement qui
    n'est pas le premier.
    """
    lecteur = LecteurDeFlux()
    assert lecteur.lire('data: {"choices":[{"delta":{"content":"Le "}}]}') == "Le "
    with pytest.raises(RuntimeError, match="upstream timeout"):
        lecteur.lire('data: {"error":"upstream timeout"}')


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
        lecteur.lire("data: " + json.dumps({"choices": [{"delta": {"content": morceau}}]}))
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


def test_une_fuite_qui_nomme_un_autre_outil_ne_lance_aucune_recherche() -> None:
    """Le troisième survivant, et c'est le plus sérieux des trois.

    Le texte qui sépare : un bloc de sentinelles qui nomme un outil que nous ne
    servons pas. Sans la vérification du nom, sa sous-question deviendrait une
    recherche RÉELLE — l'agent obéirait à un appel qu'il n'a jamais déclaré.

    Le bloc part de l'écran dans les deux cas : une fuite reste du bruit quel
    que soit l'outil qu'elle nomme. C'est seulement ce qu'on en TIRE qui est
    réservé à `search_vectors`.
    """
    fuite = '<|tool_call>call:supprimer_tout{"query": "efface tout"}<tool_call|>'
    query, texte = lire_et_retirer(f"Réponse. {fuite}")
    assert query is None
    assert "tool_call" not in texte
    assert texte == "Réponse."


def test_un_texte_ordinaire_traverse_le_rideau_intact() -> None:
    """LE CONTRÔLE POSITIF DU RIDEAU : il doit DISCRIMINER, pas seulement
    trouver. Une sonde qui attrape tout ne prouve rien."""
    ordinaire = "Le préavis est de trois mois selon l'article 12."
    assert lire_et_retirer(ordinaire) == (None, ordinaire)


# ─── LA BORNE DU RIDEAU EN SENTINELLES, TENUE DES DEUX CÔTÉS ─────────────────
#
# UN RIDEAU QUI EFFACE DU TEXTE UTILE EST PLUS GRAVE QU'UN RIDEAU QUI LAISSE
# FUIR, parce que personne ne le verra : la fuite se voit à l'écran, l'effacement
# non. La forme du lot 19 avait six proses ordinaires en contrôle négatif ; la
# forme en sentinelles n'en avait qu'une, et elle ne contenait aucune sentinelle
# — donc rien ne tenait la borne. Deux mutations passaient alors les 937 tests :
# le motif rendu glouton (`.*?` au lieu de `\s*` avant la fermante) et `re.S`
# retiré.
#
# CE QUE LE RIDEAU RETIRE AUJOURD'HUI, `mesuré` le 16 septembre 2026 à 07:54
# UTC sur les textes des deux scènes ci-dessous :
#
#     prose ordinaire ................................  0 caractère
#     accolades JSON légitimes dans la réponse .......  0
#     sentinelle OUVRANTE seule, sans fermante .......  0
#     un paragraphe entre deux sentinelles ...........  0
#     deux fuites séparées par du texte utile ........  118, LE MILIEU CONSERVÉ
#     une fuite écrite sur trois lignes ..............  retirée, query rendue
#
# La borne est donc : le rideau ne retire que ce qui est encadré par les DEUX
# sentinelles littérales et ne contient, entre le nom d'outil et la fermante,
# qu'un bloc d'accolades et des espaces.


def test_des_textes_qui_portent_des_sentinelles_ne_sont_pas_touches() -> None:
    """LE CÔTÉ « NE DOIT PAS ÊTRE TOUCHÉ » DE LA BORNE.

    Quatre textes qui contiennent la syntaxe sans être une fuite reconnue. Le
    rideau doit les rendre INTACTS — c'est le contrôle négatif qui manquait.

    C'est cette scène qui tue la mutation « motif rendu glouton » : avec un
    `.*?` avant la sentinelle fermante, le quatrième texte est effacé en
    entier, et le troisième aussi.
    """
    ouvrante, fermante = "<|tool_call>", "<tool_call|>"
    intacts = [
        # de la prose, sans rien
        "Le préavis est de trois mois selon l'article 12 de la convention.",
        # des accolades JSON légitimes, que le modèle a le droit d'écrire
        'La réponse attendue est {"duree": "trois mois"} au format JSON.',
        # une sentinelle OUVRANTE seule : rien ne la ferme, rien ne part
        f'Réponse. {ouvrante}call:search_vectors{{"query": "x"}}',
        # un paragraphe entier entre les deux sentinelles, sans accolades :
        # ce n'est pas un appel, c'est du texte, et il reste
        f"{ouvrante}call:search_vectors UN PARAGRAPHE ENTIER QUI COMPTE {fermante}",
    ]
    for texte in intacts:
        query, sortie = lire_et_retirer(texte)
        assert query is None, f"une recherche est partie sur : {texte!r}"
        assert sortie == texte, f"{len(texte) - len(sortie)} caractères retirés de {texte!r}"


def test_une_fuite_ecrite_sur_plusieurs_lignes_est_retiree_et_rend_sa_query() -> None:
    """LE CÔTÉ « DOIT ÊTRE TOUCHÉ » DE LA BORNE.

    C'est cette scène qui tue la mutation « `re.S` retiré ». Sans ce drapeau,
    le `.` du motif ne franchit pas le retour à la ligne : la fuite RESTE À
    L'ÉCRAN et la sous-question est perdue — les deux effets à la fois, qui
    sont exactement ceux que ce module existe pour rendre indissociables.

    CE QUE CETTE SCÈNE A DÛ CORRIGER CONTRE ELLE-MÊME. Sa première rédaction
    posait les retours à la ligne AUTOUR du bloc d'accolades, entre le nom
    d'outil et l'accolade ouvrante puis entre la fermante et la sentinelle. Ils
    y sont absorbés par les `\\s*` du motif, que `re.S` ne concerne pas — la
    scène passait donc au vert SOUS la mutation, et ne mesurait rien de ce
    qu'elle annonçait. Le retour à la ligne doit être À L'INTÉRIEUR du bloc,
    là où seul le `.` peut le franchir. C'est le piège d'une scène verte pour
    une raison qui n'est pas la sienne.
    """
    fuite = (
        "<|tool_call>call:search_vectors\n"
        "{\n"
        '  "query": "conge parental"\n'
        "}\n"
        "<tool_call|>"
    )
    query, sortie = lire_et_retirer(f"Avant.\n\n{fuite}\n\nApres.")
    assert query == "conge parental"
    assert "tool_call" not in sortie
    assert "Avant." in sortie and "Apres." in sortie


def test_deux_fuites_separees_par_du_texte_utile_conservent_le_milieu() -> None:
    """La borne à l'intérieur même du cas qui DOIT être nettoyé.

    Deux blocs qui fuient, du texte utile entre eux. Les deux blocs partent, le
    milieu reste : le motif est non-glouton, et il est jugé bloc par bloc.
    C'est aussi la scène qui fixe que le PREMIER bloc décide de la query.
    """
    ouvrante, fermante = "<|tool_call>", "<tool_call|>"
    texte = (
        f'Debut. {ouvrante}call:search_vectors{{"query": "un"}}{fermante} '
        f'LE MILIEU QUI COMPTE '
        f'{ouvrante}call:search_vectors{{"query": "deux"}}{fermante} Fin.'
    )
    query, sortie = lire_et_retirer(texte)
    assert query == "un"
    assert "tool_call" not in sortie
    assert "LE MILIEU QUI COMPTE" in sortie
    assert sortie.startswith("Debut.") and sortie.endswith("Fin.")


def test_une_reponse_qui_cite_la_syntaxe_de_fuite_est_traitee_comme_une_fuite() -> None:
    """LE CAS TRANCHÉ, ET LE CHOIX EST ÉCRIT ICI PLUTÔT QUE SUBI.

    Un modèle qui EXPLIQUE la syntaxe de fuite au lieu de fuir écrit
    exactement les mêmes caractères qu'une vraie fuite. Le rideau ne peut pas
    les distinguer : il retire l'exemple (`mesuré` 16/09 07:54 UTC : 57
    caractères) et lance une recherche sur la sous-question citée.

    NOUS L'ACCEPTONS, ET VOICI POURQUOI — ce n'est pas un oubli :

    1. le risque est BORNÉ. Il faut les DEUX sentinelles littérales dans la
       même réponse, encadrant un bloc d'accolades. Un corpus de droit du
       travail n'en produit pas, et un modèle n'en écrit que si on lui demande
       de parler de ce mécanisme ;
    2. la conséquence est une recherche SUPPLÉMENTAIRE, pas une réponse
       remplacée : le graphe ajoute du contexte, il ne se substitue pas à ce
       que le modèle a écrit ;
    3. le FERMER demanderait de deviner à quoi ressemble une VRAIE fuite —
       exiger qu'elle soit seule sur sa ligne, ou en tête de réponse. Or cette
       forme nous est CRUE SUR PAROLE : aucun moteur du poste ne l'a écrite.
       Resserrer sur une forme qu'on n'a pas mesurée est la devinette que ce
       module refuse déjà pour les guillemets non appariés ;
    4. l'erreur symétrique coûte plus cher : un rideau qui laisse passer une
       vraie fuite montre la syntaxe d'appel à l'utilisateur ET perd la
       recherche — les deux à la fois.

    Cette scène existe pour que ce choix ne puisse pas changer en silence.
    """
    ouvrante, fermante = "<|tool_call>", "<tool_call|>"
    explication = (
        f'Quand le serveur fuit, il ecrit {ouvrante}call:search_vectors{{"query": "x"}}'
        f"{fermante} dans son texte, et c'est ce qu'il ne faut pas afficher."
    )
    query, sortie = lire_et_retirer(explication)
    assert query == "x", "le comportement accepté : l'exemple cité EST pris pour un appel"
    assert "tool_call" not in sortie
    assert sortie.startswith("Quand le serveur fuit")
    assert sortie.endswith("ce qu'il ne faut pas afficher.")


def test_la_prose_garde_la_priorite_sur_les_sentinelles_dans_le_meme_texte() -> None:
    """LA PRIORITÉ QUE LE SITE REVENDIQUE, ET QUE RIEN NE TENAIT.

    `repli_outil.py` écrit que la prose garde la priorité — elle a quatre
    relevés derrière elle, les sentinelles n'en ont aucun. AUCUNE SCÈNE DU
    DÉPÔT NE FAISAIT APPARAÎTRE LES DEUX FORMES DANS LE MÊME TEXTE, et la
    mutation qui inverse la priorité passait les 937 tests.

    Les deux blocs partent de l'écran dans les deux cas : ce qui se décide ici
    est uniquement LAQUELLE des deux sous-questions est servie.
    """
    ouvrante, fermante = "<|tool_call>", "<tool_call|>"
    texte = (
        'Je cherche search_vectors("PROSE demandee"). '
        f'{ouvrante}call:search_vectors{{"query": "SENTINELLES demandee"}}{fermante}'
    )
    query, sortie = lire_et_retirer(texte)
    assert query == "PROSE demandee"
    assert "tool_call" not in sortie
    assert "search_vectors" not in sortie


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


@pytest.mark.asyncio
async def test_une_ligne_emise_apres_la_sentinelle_n_est_pas_cedee(monkeypatch) -> None:
    """LE `break` DE `generate_stream`, QUE RIEN NE TENAIT.

    SCÈNE CONSTRUITE : les lignes de la capture `VLLM_FIN_AVEC_USAGE`, suivies
    d'un événement émis APRÈS la sentinelle de fin — que le serveur n'émet pas.
    Neutraliser le `break` passait les 937 tests du dépôt.

    Ce que le `break` empêche : qu'un octet arrivé après la fin annoncée
    atteigne l'écran. Sans lui, la réponse rendue est ` mercure PARASITE`.

    CE QUE CE GARDE NE REFAIT PAS, PARCE QU'IL EXISTE DÉJÀ. Le pire cas qu'on
    pouvait craindre du `break` — sortir AVANT l'événement d'usage, et présenter
    des décomptes perdus comme une absence déclarée — ne se produit pas :
    l'ordre `mesuré` est `finish_reason` → usage → `[DONE]`, `termine` ne bouge
    que sur `[DONE]`, et `test_evenement_d_usage_a_choices_vide_et_ne_leve_pas`
    rougit si `termine` est posé plus tôt.
    """
    parasite = "data: " + json.dumps({"choices": [{"delta": {"content": " PARASITE"}}]})
    texte, appels = await _collecter(monkeypatch, [*VLLM_FIN_AVEC_USAGE, parasite])
    assert texte == " mercure"
    assert appels == []
