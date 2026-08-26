"""Les absorptions resserrées, et le garde-fou qui les empêche de s'élargir.

`except Exception: logger.debug(...)` est le mécanisme exact qui a caché la
panne de la purge des sessions pendant toute la vie du projet. Le balayage du
lot 3 a décidé site par site : resserrer le type, remonter le niveau de journal,
ou garder l'absorption avec un commentaire qui dit ce qu'elle protège.

Ce fichier garde les décisions **vérifiables** — celles qui changent le
comportement. Un resserrement qui redevient large fait tomber un test d'ici :
c'est tout son objet. Les absorptions gardées volontairement larges ne sont pas
testées ici ; leur justification vit dans le commentaire du site, et l'inventaire
complet dans axes_amelioration.md.
"""

import logging

import httpx
import pytest

from src.agent import graph, llm
from src.api.schemas import Message

HISTORIQUE = [
    Message(role="user", content="Quel est l'écart-type des salaires ?"),
    Message(role="assistant", content="Il est de 12 000 euros."),
]


# ─── Réécriture et traduction : (TemplateError, OSError) et (HTTPError, ValueError) ───

@pytest.mark.asyncio
async def test_une_panne_inattendue_de_la_reecriture_remonte(monkeypatch) -> None:
    """Le repli couvre les pannes du gabarit, pas une erreur de programmation.

    Sous `except Exception`, une faute dans ce bloc rendait la question
    d'origine et journalisait « Gabarit de réécriture introuvable » : le message
    accusait le gabarit, la réécriture était silencieusement désactivée à chaque
    question, et rien ne pointait vers la vraie cause.
    """
    def env_casse():
        raise RuntimeError("attribut inexistant dans le code de rendu")

    monkeypatch.setattr(llm, "_get_jinja_env", env_casse)

    with pytest.raises(RuntimeError):
        await llm.rewrite_question("Et pour les femmes ?", HISTORIQUE)


@pytest.mark.asyncio
async def test_une_panne_inattendue_de_la_traduction_remonte(monkeypatch) -> None:
    """Même décision que pour la réécriture, même raison."""
    def env_casse():
        raise RuntimeError("attribut inexistant dans le code de rendu")

    monkeypatch.setattr(llm.settings, "cross_lingual_search", True)
    monkeypatch.setattr(llm, "_get_jinja_env", env_casse)

    with pytest.raises(RuntimeError):
        await llm.translate_question("Question ?")


@pytest.mark.asyncio
async def test_le_repli_couvre_bien_la_panne_de_transport_reelle(monkeypatch) -> None:
    """Le resserrement ne doit pas casser le cas qu'il existe pour couvrir.

    `httpx.ConnectError` ⊂ `TransportError` ⊂ `HTTPError` : Ollama injoignable
    reste un repli, pas une erreur 500.
    """
    def transport_mort(**_kwargs):
        raise httpx.ConnectError("ollama-central absent")

    monkeypatch.setattr(llm.httpx, "AsyncClient", transport_mort)

    assert await llm.rewrite_question("Et pour les femmes ?", HISTORIQUE) == "Et pour les femmes ?"


@pytest.mark.asyncio
async def test_un_corps_de_reponse_qui_n_est_pas_du_json_reste_un_repli(monkeypatch) -> None:
    """`resp.json()` lève `JSONDecodeError`, sous-classe de `ValueError`.

    C'est la seconde moitié du couple retenu : sans `ValueError`, un Ollama qui
    répond du HTML — un proxy en erreur, typiquement — remonterait en 500.
    """
    class Resp:
        def raise_for_status(self) -> None: ...

        def json(self) -> dict:
            raise ValueError("Expecting value: line 1 column 1 (char 0)")

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return False

        async def post(self, *_args, **_kwargs):
            return Resp()

    monkeypatch.setattr(llm.httpx, "AsyncClient", lambda **_kwargs: Client())

    assert await llm.rewrite_question("Et pour les femmes ?", HISTORIQUE) == "Et pour les femmes ?"


# ─── Le rappel de streaming : RuntimeError, pas Exception ─────────────────────

@pytest.mark.asyncio
async def test_node_generate_ne_masque_pas_une_panne_de_langgraph(monkeypatch) -> None:
    """`get_stream_writer` hors contexte de stream lève `RuntimeError`, et rien d'autre.

    Sous `except Exception`, toute autre panne de LangGraph faisait simplement
    `writer = None` : la génération continuait, muette, et le frontend ne
    recevait aucun token sans qu'une ligne de journal existe pour le dire.
    """
    def panne_de_bibliotheque():
        raise ValueError("changement d'API incompatible")

    async def generation(**_kwargs):
        yield "une réponse"

    monkeypatch.setattr(graph, "get_stream_writer", panne_de_bibliotheque)
    # Neutralisé pour que l'échec attendu soit « la panne n'a pas remonté », et
    # non un appel réseau vers un Ollama absent.
    monkeypatch.setattr(graph, "generate_stream", generation)

    with pytest.raises(ValueError, match="changement d'API"):
        await graph.node_generate({"question": "q", "enriched_contexts": []})


@pytest.mark.asyncio
async def test_node_generate_tolere_l_absence_de_contexte_de_stream(monkeypatch) -> None:
    """Le cas que le resserrement doit continuer de couvrir : un `ainvoke` simple.

    C'est ce que fait `/answer` : le nœud tourne hors d'un `astream`, personne
    n'écoute les tokens, et ce n'est pas une panne.
    """
    def hors_contexte():
        raise RuntimeError("Called get_config outside of a runnable context")

    async def generation(**_kwargs):
        yield "une réponse"

    monkeypatch.setattr(graph, "get_stream_writer", hors_contexte)
    monkeypatch.setattr(graph, "generate_stream", generation)

    resultat = await graph.node_generate({"question": "q", "enriched_contexts": []})

    assert resultat["response"] == "une réponse"


# ─── La fermeture du checkpointer : WARNING, pas debug ────────────────────────

@pytest.mark.asyncio
async def test_une_fermeture_de_checkpointer_en_echec_sort_en_warning(caplog) -> None:
    """`logger.debug` était invisible à `LOG_LEVEL=INFO`, le défaut par défaut.

    Une fermeture qui échoue laisse une connexion SQLite ouverte sur le fichier
    des sessions, donc un journal WAL non replié et un verrou possible au
    prochain démarrage. C'est exactement le motif qui a caché la panne de la
    purge : un niveau de journal sous celui qui est configuré.
    """
    class GestionnaireRecalcitrant:
        async def __aexit__(self, *_):
            raise OSError("fichier déjà fermé")

    graph._ouverts.append(GestionnaireRecalcitrant())
    try:
        with caplog.at_level(logging.DEBUG):
            await graph.close_checkpointers()
    finally:
        graph._ouverts.clear()

    fermeture = [
        enregistrement
        for enregistrement in caplog.records
        if "checkpointer" in enregistrement.getMessage().lower()
    ]
    assert fermeture, "l'échec de fermeture doit laisser une trace"
    assert all(e.levelno >= logging.WARNING for e in fermeture), (
        f"niveaux journalisés : {[logging.getLevelName(e.levelno) for e in fermeture]}"
    )


# ─── Les absorptions gardées larges disent ce qu'elles perdent ────────────────

def test_une_source_illisible_est_annoncee_comme_ecartee(monkeypatch, caplog) -> None:
    """L'absorption reste large — une source ne doit pas emporter la réponse.

    Mais son message doit dire la conséquence : l'utilisateur reçoit une réponse
    construite sur moins de sources qu'il n'en a coché. « Erreur reconstruction
    section » laissait croire à un incident sans suite.
    """
    def reconstruction_impossible(_eid):
        raise RuntimeError("graphd muet")

    monkeypatch.setattr(graph, "reconstruct_section", reconstruction_impossible)

    with caplog.at_level(logging.ERROR):
        resultat = graph.node_reconstruct_context(
            {"selected_element_ids": ["abcdef0123"], "reranked_chunks": [], "enriched_contexts": []}
        )

    assert resultat["enriched_contexts"] == []
    messages = [e.getMessage() for e in caplog.records if e.levelno >= logging.ERROR]
    assert any("écartée" in m and "abcdef0123" in m for m in messages)


# ─── Un corps JSON VALIDE mais mal formé : la troisième classe de panne ───────

# Quatre formes, quatre chemins distincts dans le parsing défensif — pas quatre
# habillages du même. `{"message": null}` et `{"message": "…"}` échouent sur le
# type de `message` ; `{"message": []}` aussi, mais par une branche différente du
# `isinstance` ; un corps qui n'est pas un objet échoue avant d'avoir lu
# `message`. Chacune est ce qu'un changement de version d'Ollama, un proxy, ou un
# backend « compatible » peut produire.
_CORPS_MAL_FORMES = [
    pytest.param({"message": None}, id="message-null"),
    pytest.param({"message": "une chaîne"}, id="message-chaine"),
    pytest.param({"message": []}, id="message-liste"),
    pytest.param(["pas", "un", "objet"], id="corps-non-objet"),
]


def _client_ollama(corps):
    """Faux client httpx qui rend `corps` tel quel — JSON valide, forme libre."""
    class Resp:
        def raise_for_status(self) -> None: ...

        def json(self):
            return corps

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return False

        async def post(self, *_args, **_kwargs):
            return Resp()

    return lambda **_kwargs: Client()


@pytest.mark.asyncio
@pytest.mark.parametrize("corps", _CORPS_MAL_FORMES)
async def test_un_corps_json_mal_forme_rend_la_question_d_origine(monkeypatch, corps) -> None:
    """`(httpx.HTTPError, ValueError)` ne couvrait pas ce cas, et il atteignait l'utilisateur.

    Un corps qui EST du JSON valide sans avoir la forme attendue faisait lever
    `AttributeError` à `.get("message", {}).get("content", "")`. `node_rewrite`
    n'a aucun try/except : l'exception traversait le graphe jusqu'à la route.

    Le correctif ne réélargit PAS l'absorption — cela ramènerait les erreurs de
    programmation que le resserrement sert à faire remonter. Il nomme la forme
    acceptée, et tout le reste devient une chaîne vide, que le garde-fou aval
    convertit en « on garde la question d'origine ».
    """
    monkeypatch.setattr(llm.httpx, "AsyncClient", _client_ollama(corps))

    assert await llm.rewrite_question("Et pour les femmes ?", HISTORIQUE) == "Et pour les femmes ?"


@pytest.mark.asyncio
@pytest.mark.parametrize("corps", _CORPS_MAL_FORMES)
async def test_un_corps_json_mal_forme_ne_donne_aucune_traduction(monkeypatch, corps) -> None:
    """Et surtout PAS une traduction vide.

    À `TRANSLATION_WEIGHT=1.0`, une chaîne vide entrée dans la fusion RRF serait
    strictement pire que le 500 : la recherche translinguistique ramènerait du
    bruit sans que rien ne le signale. C'est le garde-fou aval qui l'empêche, et
    c'est pour cela que le test asserte `None` et non « pas d'exception ».
    """
    monkeypatch.setattr(llm.settings, "cross_lingual_search", True)
    monkeypatch.setattr(llm.httpx, "AsyncClient", _client_ollama(corps))

    assert await llm.translate_question("Question ?") is None


@pytest.mark.asyncio
async def test_un_content_non_textuel_ne_devient_pas_une_requete(monkeypatch) -> None:
    """`{"message": {"content": null}}` : la forme est bonne jusqu'à la feuille.

    Aucune exception ici, et c'est pire : `str(None)` rend la chaîne « None »,
    longue de quatre caractères, qui passe le garde-fou aval et part en requête
    de recherche. Un 500 se voit ; une recherche sur « None » ne se voit pas. La
    forme acceptée est donc nommée jusqu'à la feuille — `content` doit être une
    chaîne.
    """
    monkeypatch.setattr(llm.settings, "cross_lingual_search", True)
    monkeypatch.setattr(llm.httpx, "AsyncClient", _client_ollama({"message": {"content": None}}))

    assert await llm.rewrite_question("Et pour les femmes ?", HISTORIQUE) == "Et pour les femmes ?"
    assert await llm.translate_question("Question ?") is None


@pytest.mark.asyncio
async def test_une_url_ollama_invalide_remonte(monkeypatch) -> None:
    """`httpx.InvalidURL` n'est PAS attrapée, et c'est une décision.

    `InvalidURL` hérite directement d'`Exception`, pas de `HTTPError` : elle
    n'entre donc pas dans le tuple. Elle ne doit pas y entrer. Un `OLLAMA_HOST`
    mal formé est une erreur de CONFIGURATION, et elle casse aussi
    `generate_stream` : la rattraper ici dégraderait la recherche en monolingue
    en laissant croire que le service fonctionne, au lieu de dire qu'il est mal
    configuré.
    """
    def url_invalide(**_kwargs):
        raise httpx.InvalidURL("URL sans schéma : 'ollama-central:11434'")

    monkeypatch.setattr(llm.settings, "cross_lingual_search", True)
    monkeypatch.setattr(llm.httpx, "AsyncClient", url_invalide)

    with pytest.raises(httpx.InvalidURL):
        await llm.rewrite_question("Et pour les femmes ?", HISTORIQUE)
    with pytest.raises(httpx.InvalidURL):
        await llm.translate_question("Question ?")


# ─── Le même défaut, vu de la route : c'est là qu'il atteignait l'utilisateur ──

@pytest.fixture
def client_avec_reecriture_reelle(monkeypatch):
    """L'application, avec `rewrite_question` et `translate_question` RÉELLES.

    Seul le transport HTTP vers Ollama est simulé. C'est ce qui distingue ce
    garde des tests unitaires ci-dessus : la régression n'atteignait
    l'utilisateur que parce que `node_rewrite` n'a aucun try/except, et un test
    unitaire seul resterait vert le jour où quelqu'un en ajoute un autour du
    nœud.
    """
    from fastapi.testclient import TestClient

    from src.agent import graph as graph_module
    from src.agent.settings import settings
    from src.api import main
    from src.api.schemas import ChunkResult, SectionContext

    monkeypatch.setattr(settings, "checkpoint_db_path", "")
    monkeypatch.setattr(settings, "usage_capture", False)
    monkeypatch.setattr(settings, "query_rewrite", True)
    monkeypatch.setattr(settings, "cross_lingual_search", True)

    def _chunk(eid: str) -> ChunkResult:
        return ChunkResult(
            chunk_id=eid, element_id=eid, graph_node_id=eid,
            document="Le texte du passage.", filename="3. Statistical Toolbox",
            page_no=88, label="paragraph", distance=0.2, rerank_score=3.0, relevance=0.95,
        )

    monkeypatch.setattr(
        graph_module, "retrieve",
        lambda _q, top_k=None, translation=None, chrono=None: [_chunk("abcdef0123")],
    )
    monkeypatch.setattr(graph_module, "rerank", lambda _q, chunks: chunks)
    monkeypatch.setattr(graph_module, "reconstruct_section", lambda eid: SectionContext(
        element_id=eid, section_id="sssssssss1", breadcrumbs=[], elements=[],
        markdown="Le contexte reconstruit.", filename="3. Statistical Toolbox",
    ))

    async def generation(**_kwargs):
        yield "La dispersion se mesure [src:abcdef0123]."

    monkeypatch.setattr(graph_module, "generate_stream", generation)

    with TestClient(main.app) as testclient:
        yield testclient


@pytest.mark.parametrize("corps", _CORPS_MAL_FORMES)
def test_chat_start_ne_rend_pas_500_sur_un_corps_ollama_mal_forme(
    client_avec_reecriture_reelle, monkeypatch, corps
) -> None:
    """La preuve au niveau HTTP : c'est ce que l'utilisateur voyait.

    `node_rewrite` n'a aucun try/except, donc l'`AttributeError` traversait le
    graphe jusqu'à la route. Un historique non vide est nécessaire : sans lui,
    `rewrite_question` rend la question telle quelle sans appeler le LLM.
    """
    monkeypatch.setattr(llm.httpx, "AsyncClient", _client_ollama(corps))

    reponse = client_avec_reecriture_reelle.post("/chat/start", json={
        "question": "Et pour les femmes ?",
        "chat_history": [
            {"role": "user", "content": "Quel est l'écart-type des salaires des hommes ?"},
            {"role": "assistant", "content": "Il est de 12 000 euros."},
        ],
    })

    assert reponse.status_code == 200, reponse.text  # noqa: PLR2004
    assert reponse.json()["thread_id"]


@pytest.mark.parametrize("corps", _CORPS_MAL_FORMES)
def test_answer_ne_rend_pas_500_sur_un_corps_ollama_mal_forme(
    client_avec_reecriture_reelle, monkeypatch, corps
) -> None:
    """Même chose sur la route d'évaluation, qui traverse le graphe entier."""
    monkeypatch.setattr(llm.httpx, "AsyncClient", _client_ollama(corps))

    reponse = client_avec_reecriture_reelle.post("/answer", json={
        "question": "Et pour les femmes ?",
        "chat_history": [
            {"role": "user", "content": "Quel est l'écart-type des salaires des hommes ?"},
            {"role": "assistant", "content": "Il est de 12 000 euros."},
        ],
        "stream": False,
    })

    assert reponse.status_code == 200, reponse.text  # noqa: PLR2004
