import asyncio
import json
import logging
import secrets
import time
import uuid
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Any

import httpx
from anyio import to_thread
from fastapi import Depends, FastAPI, Header, HTTPException, Path, Response
from fastapi.middleware.cors import CORSMiddleware
from langchain_core.runnables import RunnableConfig
from sse_starlette.sse import EventSourceResponse

from src.agent import sessions
from src.agent.chronometrie import decomposer
from src.agent.graph import (
    answer_graph,
    build_checkpointer,
    close_checkpointers,
    compile_interactive,
    element_ids_presents,
    resolve_citations,
)
from src.agent.graph_context import ping as nebula_ping
from src.agent.graph_context import reconstruct_section
from src.agent.llm import generate_stream
from src.agent.minio_client import get_object_bytes
from src.agent.retriever import (
    group_by_document,
    lexical_ready,
    lexical_stale,
    rebuild_lexical_index,
    rerank,
    retrieve,
)
from src.agent.retriever import ping as chroma_ping
from src.agent.settings import settings
from src.agent.state import AgentState
from src.agent.usage import initialiser as usage_initialiser
from src.agent.usage import record_completion, record_feedback, record_start
from src.agent.usage import stats as usage_stats
from src.api.schemas import (
    MAX_HISTORY_MESSAGES,
    AnswerRequest,
    AnswerResponse,
    ChatRequest,
    ChatResponse,
    Citation,
    FeedbackRequest,
    FeedbackResponse,
    GenerationMeasure,
    HealthResponse,
    ImageRef,
    ReindexResponse,
    RetrievedContext,
    SearchRequest,
    SearchResponse,
    SectionContext,
    SessionStats,
    SourceSelectionRequest,
    SourcesResponse,
    StageTimings,
)

logging.basicConfig(
    level=getattr(logging, settings.log_level),
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)

# Graphe interactif, compilé au démarrage : son checkpointer ouvre une
# connexion asynchrone, ce qui ne peut pas se faire à l'import du module.
_interactive: Any = None


def interactive_graph() -> Any:
    """Graphe du flux interactif, une fois le service démarré."""
    if _interactive is None:
        raise HTTPException(status_code=503, detail="Service en cours de démarrage.")
    return _interactive


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Ouvre le checkpointer avant de servir, le referme à l'arrêt."""
    global _interactive
    checkpointer = await build_checkpointer()
    _interactive = compile_interactive(checkpointer)
    # Après l'ouverture du checkpointer, jamais avant : l'adoption des sessions
    # orphelines lit la table `checkpoints`, que `setup()` vient de créer. Cette
    # passe n'est PAS une purge totale — le checkpointer est sur disque
    # précisément pour qu'une session en attente de sélection survive au
    # redémarrage. Elle rend seulement atteignables les sessions qu'aucun
    # processus vivant n'a jamais vues.
    await sessions.initialiser(checkpointer)
    # Avant de servir : c'est le seul moment où fixer le mode de journalisation
    # de la base de capture est sûr. Le faire dans le chemin d'écriture faisait
    # perdre des interactions simultanées (cf. usage.initialiser).
    await usage_initialiser()
    # La taille de l'actif au démarrage. Aucune purge n'existe et c'est
    # délibéré : la contrepartie est qu'elle doit être VISIBLE, sans quoi un jeu
    # de données qui grossit sans qu'on le sache redevient une fuite.
    capture = await usage_stats()
    logger.info(
        "Capture d'usage %s : %d interactions, %d sources, %d ko (%s)",
        "active" if capture.enabled else "désactivée",
        capture.interactions,
        capture.sources,
        capture.size_bytes // 1024,
        capture.path,
    )
    try:
        yield
    finally:
        await close_checkpointers()


app = FastAPI(
    title="rag-agent-chat",
    description="API de l'agent RAG conversationnel",
    version="0.1.0",
    lifespan=lifespan,
)

# Origines explicites plutôt que « * » : sans cela, n'importe quelle page web
# ouverte dans le navigateur de l'utilisateur peut interroger l'API — et, tant
# qu'aucune clé n'est exigée, lire le corpus.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "X-API-Key"],
)


def require_api_key(x_api_key: str = Header(default="")) -> None:
    """Exige la clé si `API_KEY` est renseignée.

    Vide — le cas d'un déploiement local derrière un pare-feu — la dépendance
    ne fait rien. Renseignée, toute route sauf `/health` l'exige : une sonde
    doit rester interrogeable sans secret.
    """
    if not settings.api_key:
        return
    if not secrets.compare_digest(x_api_key, settings.api_key):
        raise HTTPException(status_code=401, detail="Clé d'API absente ou invalide.")

# ─── Health ───────────────────────────────────────────────────────────────────

# Plafond global des sondes de /health, en secondes.
#
# `docker-compose.yml` coupe le healthcheck à 5 s et `frontend` attend
# `agent-api` en `service_healthy`. Les quatre sondes enchaînées en SÉQUENCE
# dépassaient ce délai dès que les stores ne répondaient plus : curl était tué,
# les cinq tentatives échouaient, `agent-api` passait `unhealthy`, et le frontend
# ne démarrait JAMAIS — alors que l'API répond 200 `degraded`, ce qu'elle est
# écrite pour faire. Le healthcheck annulait l'intention de cette route.
#
# 3 s laisse 2 s de marge. Tout ce qui fait des entrées-sorties est SOUS ce
# plafond, sondes et lecture de la base de capture comprises ; ce qui reste
# dehors est du calcul en mémoire, énuméré dans `health()`.
_PLAFOND_SONDES_S = 3.0

# Sondes lancées et pas encore revenues.
#
# Une sonde SYNCHRONE ne s'interrompt pas : rien ne peut tuer un fil bloqué dans
# un appel réseau, et renoncer à l'attendre ne fait que LÂCHER le fil, qui
# continue de tourner. Sans ce garde, un healthcheck toutes les 20 s contre un
# store muet lâcherait un fil de plus par sonde à chaque passage, dans le
# threadpool que les endpoints de recherche partagent. Avec lui, une sonde déjà
# en vol n'est pas relancée, donc un fil lâché par sonde à la fois — quelle que
# soit la durée de la panne.
#
# Reste un résidu, assumé : le drapeau est posé par le FIL, et la décision de
# lancer est prise par la boucle. Deux /health VRAIMENT simultanés peuvent donc
# doubler une sonde, le temps que le premier fil démarre. Poser le drapeau côté
# boucle fermerait cette fenêtre et en ouvrirait une pire : si la tâche est
# annulée avant que le fil ne démarre (threadpool saturé), plus personne ne
# retire le drapeau et la sonde reste « en vol » à jamais — une panne remplacée
# par une cécité définitive. Le healthcheck passe toutes les 20 s ; la fenêtre
# ici dure le temps d'un démarrage de fil.
_sondes_en_vol: set[str] = set()


def _executer_sonde(nom: str, sonde: Callable[[], bool]) -> bool:
    """Exécute une sonde synchrone DANS le fil du threadpool.

    Le drapeau « en vol » est posé et retiré ici, par le fil lui-même, et non par
    la tâche qui l'attend : celle-ci rend la main au plafond, alors que le fil
    tourne encore. Retiré côté tâche, le garde laisserait repartir un second fil
    à chaque appel de /health — exactement ce qu'il existe pour empêcher.
    """
    _sondes_en_vol.add(nom)
    try:
        return sonde()
    finally:
        _sondes_en_vol.discard(nom)


async def _sonder(nom: str, sonde: Callable[[], bool]) -> bool | None:
    """Lance une sonde synchrone, ou renonce si son fil précédent tourne encore.

    Le plafond, lui, ne vient PAS de `abandon_on_cancel` : il vient de
    `asyncio.wait(timeout=…)` et du fait qu'on n'attend pas l'annulation.
    **Mesuré**, parce que le contraire semblait évident et ne l'était pas : un
    plafond anyio (`move_on_after(0,3 s)`) autour d'une sonde bloquée 6 s rend en
    **6,00 s** avec la valeur par défaut — le bouclier d'anyio diffère
    l'annulation jusqu'au retour du fil, et le plafond ne borne alors plus rien —
    et en **0,30 s** avec le drapeau ; `asyncio.wait` et `asyncio.wait_for`
    rendent en 0,30 s dans les deux cas, l'annulation d'une tâche asyncio étant
    délivrée directement au futur attendu. À refaire avec un `threading.Event`
    non levé et les quatre combinaisons.

    Le drapeau reste donc posé pour deux raisons, aucune n'étant le délai : il dit
    la vérité sur le fil — lâché, pas interrompu — et il rend cet appel
    indépendant du plafond employé, alors que remplacer `asyncio.wait` par une
    construction anyio est une modification tout à fait plausible dans une
    application qui tourne sur anyio. Aucun test ne le garde, faute d'effet
    observable ici : consigné comme tel au registre (§1.27).

    Rend None pour « pas de réponse », qui n'est pas « le service est tombé ».
    """
    if nom in _sondes_en_vol:
        logger.debug("/health: sonde %s encore en vol, aucun second fil lancé", nom)
        return None
    return await to_thread.run_sync(_executer_sonde, nom, sonde, abandon_on_cancel=True)


async def _sonder_ollama() -> bool:
    """Sonde HTTP d'Ollama.

    Seule sonde réellement interruptible des quatre : elle fait des
    entrées-sorties asynchrones, donc le plafond la coupe pour de bon, sans
    laisser de fil derrière lui. Son propre délai de 5 s est désormais dominé par
    le plafond ; il reste parce qu'il est le contrat de CETTE sonde, et qu'un
    plafond global n'en tient pas lieu.

    `httpx.InvalidURL` n'est pas rattrapée, et c'est la décision écrite dans
    `llm.py` : elle n'hérite pas de `HTTPError`, un OLLAMA_HOST mal formé est une
    erreur de configuration et non une panne de service. Elle remonte donc à
    `_relever`, qui la journalise en nommant son type au lieu de la taire.
    """
    async with httpx.AsyncClient(timeout=5.0) as client:
        resp = await client.get(f"{settings.ollama_host}/api/tags")
        return resp.status_code == 200


def _relever[T](nom: str, tache: asyncio.Task[T], *, si_levee: T | None) -> T | None:
    """Ce qu'une sonde a rendu, ou None quand elle n'a rien rendu.

    Paramétré parce que la même attente borne les quatre sondes, qui rendent des
    booléens, ET la lecture de la base de capture, qui rend un `UsageStats`.

    Trois cas, qui ne veulent pas dire la même chose :

    - **pas revenue** avant le plafond : on renonce à l'attendre, et l'événement
      est journalisé. Pour une sonde synchrone, cela LÂCHE son fil, et le journal
      ne le répète pas : les appels suivants la trouvent en vol et se taisent en
      DEBUG.
    - **revenue en levant** : les sondes absorbent déjà leurs pannes, donc une
      exception ici est un défaut de programmation. Elle est journalisée avec son
      type — ce n'est pas une absorption muette — et publiée fausse : /health n'a
      aucune preuve que le service répond. La propager ferait rendre 500 à
      /health, donc redémarrer le service en boucle, ce que cette route existe
      précisément pour éviter. `si_levee` dit ce qui est publié alors, et il est
      nommé à l'appel : faux pour une sonde, qui a répondu par une panne ; rien
      pour la base de capture, dont l'absence se dit déjà en null.
    - **revenue** : sa valeur.
    """
    if not tache.done():
        logger.warning(
            "/health: %s n'a pas répondu en %.1f s ; on renonce à l'attendre",
            nom,
            _PLAFOND_SONDES_S,
        )
        tache.cancel()
        return None
    if tache.cancelled():
        return None
    exc = tache.exception()
    if exc is not None:
        logger.warning("/health: sonde %s a levé %s: %s", nom, type(exc).__name__, exc)
        return si_levee
    return tache.result()


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """Vérifie réellement les trois dépendances (Chroma, Nebula, Ollama).

    Les quatre sondes partent EN PARALLÈLE sous un plafond global : en séquence,
    elles dépassaient le délai du healthcheck et empêchaient le frontend de
    démarrer (voir `_PLAFOND_SONDES_S`).

    Retourne toujours 200 (pour ne pas déclencher de restart en boucle) avec
    le détail par service ; status passe à "degraded" si l'une est down.
    """
    # Table construite à l'appel, pas au chargement du module : les sondes sont
    # des noms de module, et une table figée à l'import ne verrait plus leur
    # remplacement.
    sondes: dict[str, Callable[[], bool]] = {
        "chromadb": chroma_ping,
        "nebulagraph": nebula_ping,
        # Faux couvre DEUX cas, et c'est voulu : l'index pas encore construit
        # (la première requête paiera sa construction, la recherche est dense
        # seule d'ici là) et l'index construit sur un corpus qui n'existe plus.
        # Le second est celui qui trompait : l'ingestion est un service séparé
        # qui écrit dans Chroma pendant que l'agent tourne, et un `true` sur un
        # index périmé décrivait un corpus disparu — la recherche lexicale ne
        # voyait aucun document ingéré après le démarrage.
        "index_lexical": lexical_ready,
    }
    taches: dict[str, asyncio.Task[bool | None]] = {
        nom: asyncio.create_task(_sonder(nom, sonde)) for nom, sonde in sondes.items()
    }
    taches["ollama"] = asyncio.create_task(_sonder_ollama())
    # Sous le MÊME plafond : `usage_stats` ouvre SQLite avec un busy_timeout de
    # 5 s, donc laissée dehors elle pouvait à elle seule faire dépasser le délai
    # du healthcheck, sans qu'aucune sonde soit en cause — un plafond qui ne
    # couvre pas tout finit par mentir. Son absence se dit en null, déjà prévu
    # par le contrat ; l'inventer en zéros décrirait une base vide. Ce que le
    # plafond y lâche est borné tout seul : aiosqlite tient un fil par connexion,
    # et la connexion abandonnée le ferme en se faisant collecter — au plus une à
    # la fois, le healthcheck ne passant que toutes les 20 s.
    tache_usage = asyncio.create_task(usage_stats())

    # Liste typée `Future[Any]` : les tâches n'ont pas toutes le même type de
    # résultat, et c'est bien la même attente qui les borne toutes.
    attente: list[asyncio.Future[Any]] = [*taches.values(), tache_usage]
    await asyncio.wait(attente, timeout=_PLAFOND_SONDES_S)

    services: dict[str, bool] = {}
    # Une sonde qui n'est pas revenue n'est pas une sonde qui a échoué : le
    # second est un fait sur le service, le premier un fait sur l'agent.
    # `services` reste un `dict[str, bool]` — le healthcheck comme l'exploitant
    # ne doivent en aucun cas lire « je n'ai pas eu le temps de regarder » comme
    # « ça répond » — et la distinction est portée à côté, en clair.
    inconnues: list[str] = []
    for nom, tache in taches.items():
        resultat = _relever(nom, tache, si_levee=False)
        services[nom] = bool(resultat)
        if resultat is None:
            inconnues.append(nom)

    # L'index lexical n'est pas une dépendance : son absence dégrade la
    # recherche, elle ne l'empêche pas. Le healthcheck Docker ne doit pas
    # redémarrer le service pour ça.
    essentiels = {k: v for k, v in services.items() if k != "index_lexical"}
    status = "ok" if all(essentiels.values()) else "degraded"
    # Hors du plafond, et borné : `sessions.stats()` et `sessions.durable()` ne
    # lisent que des compteurs en mémoire et un réglage — aucune entrée-sortie,
    # donc rien qui puisse attendre. `stats` absorbe ses propres échecs et rend
    # des zéros : une sonde qui tombe parce qu'une base d'observation est
    # illisible serait une régression, pas une mesure. Le compteur `failures` dit
    # alors ce qui s'est passé.
    chemin, vivantes, purgees, echecs = sessions.stats()
    return HealthResponse(
        status=status,
        ollama_model=settings.ollama_model,
        services=services,
        services_unknown=inconnues,
        usage=_relever("usage", tache_usage, si_levee=None),
        sessions=SessionStats(
            path=chemin,
            durable=sessions.durable(),
            live=vivantes,
            purged=purgees,
            failures=echecs,
        ),
    )


# ─── Retrieval ────────────────────────────────────────────────────────────────

# Endpoints `def` (et non `async def`) : l'inférence des modèles (embedding,
# cross-encoder) et les requêtes Nebula sont synchrones et CPU-bound — FastAPI
# les exécute dans son threadpool, sans bloquer l'event loop.

@app.post("/search", response_model=SearchResponse, dependencies=[Depends(require_api_key)])
def search(req: SearchRequest) -> SearchResponse:
    """Retrieval brut ChromaDB sans reranking."""
    chunks = retrieve(req.question, top_k=req.top_k)
    return SearchResponse(question=req.question, chunks=chunks)


# ─── Réindexation lexicale ────────────────────────────────────────────────────

@app.post("/reindex", response_model=ReindexResponse, dependencies=[Depends(require_api_key)])
def reindex() -> ReindexResponse:
    """Reconstruit l'index lexical BM25 sur le corpus tel qu'il est maintenant.

    **À appeler par l'ingestion en fin de pipeline.** L'ingestion est un service
    séparé qui écrit dans ChromaDB pendant que l'agent tourne : un document
    ingéré après le démarrage était trouvable en recherche dense — la requête
    part à Chroma à chaque fois — et invisible en lexical jusqu'au prochain
    redémarrage. La recherche devenait silencieusement asymétrique.

    Cet endpoint est un CONTRAT, là où la détection par le compte de chunks
    (cf. `retriever.lexical_stale`) n'est qu'un filet : celle-ci ne voit pas un
    corpus dont on a retiré autant de chunks qu'on en a ajouté.

    Endpoint `def` : la reconstruction est synchrone et coûte le parcours du
    corpus entier, elle tourne donc dans le threadpool sans bloquer la boucle
    d'événements. Ce coût est payé par le pipeline d'ingestion qui appelle,
    jamais par une requête utilisateur.
    """
    chunks = rebuild_lexical_index()
    return ReindexResponse(chunks_indexed=chunks, stale=lexical_stale())


# ─── Reranking + groupement ───────────────────────────────────────────────────

@app.post("/sources", response_model=SourcesResponse, dependencies=[Depends(require_api_key)])
def sources(req: SearchRequest) -> SourcesResponse:
    """Retrieval + reranking + groupement par document."""
    chunks = retrieve(req.question)
    ranked = rerank(req.question, chunks)
    groups = group_by_document(ranked)
    return SourcesResponse(question=req.question, groups=groups)


# ─── Graph context ────────────────────────────────────────────────────────────

@app.get("/context/{element_id}", dependencies=[Depends(require_api_key)])
def context(element_id: str = Path(pattern=r"^[a-f0-9]{10}$")) -> dict[str, Any]:
    """Reconstruit le contexte enrichi pour un element_id donné."""
    try:
        ctx = reconstruct_section(element_id)
        return ctx.model_dump()
    except Exception as exc:
        # Absorption LARGE et assumée — la reconstruction traverse Nebula, Chroma
        # et le parsing de leurs réponses — mais elle était MUETTE : FastAPI ne
        # journalise pas une HTTPException, donc un 500 sur cette route ne
        # laissait aucune trace serveur. La cause est tracée avant de répondre.
        logger.exception("Reconstruction impossible pour %s, réponse en 500.", element_id)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# ─── Chat (génération directe, sans LangGraph) ────────────────────────────────

async def _capturer_generation_directe(
    thread_id: str,
    question: str,
    reponse: str,
    citations: list[Citation],
    images: list[ImageRef],
    contexts: list[SectionContext],
) -> None:
    """Enregistre une génération directe : la question et ce qu'elle a produit.

    Les deux écritures ont lieu à la fin, jamais avant la réponse : cet endpoint
    diffuse, et rien de synchrone n'entre dans le chemin de diffusion.
    """
    await record_start(thread_id=thread_id, endpoint="chat_simple", question=question)
    await record_completion(
        thread_id=thread_id,
        response=reponse,
        citations=citations,
        images=images,
        search_count=1,
        submitted=contexts,
    )


@app.post("/chat/simple", response_model=None, dependencies=[Depends(require_api_key)])
async def chat_simple(req: ChatRequest) -> EventSourceResponse | ChatResponse:
    """Génération directe (sans agentic loop) à partir des sources sélectionnées.

    Utilise les element_ids sélectionnés pour reconstruire le contexte, puis
    appelle le LLM. Supporte le streaming SSE.
    """
    if not req.selected_element_ids:
        raise HTTPException(
            status_code=400,
            detail="Sélectionnez au moins une source avant de générer.",
        )

    contexts = []
    for eid in req.selected_element_ids:
        try:
            # Reconstruction synchrone (requêtes Nebula) → threadpool
            ctx = await to_thread.run_sync(reconstruct_section, eid)
            contexts.append(ctx)
        except Exception:
            # Même absorption assumée que dans `node_reconstruct_context` : une
            # source illisible ne doit pas emporter la requête. Le message dit ce
            # qui est perdu — cette source ne sera pas soumise au LLM.
            logger.exception(
                "Reconstruction impossible pour %s : cette source est écartée du "
                "prompt (%d retenue(s) jusqu'ici).",
                eid,
                len(contexts),
            )

    if not contexts:
        raise HTTPException(
            status_code=500,
            detail="Impossible de reconstruire le contexte des sources sélectionnées.",
        )

    # La capture de cet endpoint n'écrit AUCUNE source proposée : le client
    # arrive avec ses element_ids déjà choisis, rien ne lui a été soumis. Y
    # inscrire ses sources comme « retenues » gonflerait le taux de retenue
    # d'une décision que personne n'a prise. La question, elle, compte : c'est
    # la distribution des classes de questions qu'on cherche à connaître.
    thread_id = str(uuid.uuid4())

    if req.stream:
        async def stream_generator() -> AsyncIterator[dict[str, Any]]:
            morceaux: list[str] = []
            async for token in generate_stream(
                req.question, contexts, req.chat_history[-MAX_HISTORY_MESSAGES:]
            ):
                morceaux.append(token)
                yield {"data": json.dumps({"token": token})}
            reponse = "".join(morceaux)
            citations, images = resolve_citations(reponse, contexts, [])
            yield {
                "data": json.dumps(
                    {
                        "done": True,
                        "answer": reponse,
                        # Rendu au client pour qu'il puisse noter la réponse :
                        # c'est le seul endroit où il apprend ce thread_id.
                        "thread_id": thread_id,
                        "citations": [c.model_dump() for c in citations],
                        "images": [i.model_dump() for i in images],
                    }
                )
            }
            await _capturer_generation_directe(
                thread_id, req.question, reponse, citations, images, contexts
            )

        return EventSourceResponse(stream_generator())

    from src.agent.llm import generate

    # Cet endpoint rendait `citations: []` en dur : il generait des reponses
    # truffees de marqueurs [src:...] que personne ne resolvait, dans un projet
    # dont c'est precisement l'objet.
    # Même profondeur d'historique que /chat/start et /answer : cet endpoint
    # soumettait tout ce que le client envoyait, donc un autre prompt pour la
    # même conversation selon la route empruntée.
    response = await generate(req.question, contexts, req.chat_history[-MAX_HISTORY_MESSAGES:])
    citations, images = resolve_citations(response, contexts, [])
    await _capturer_generation_directe(
        thread_id, req.question, response, citations, images, contexts
    )
    return ChatResponse(
        answer=response,
        citations=citations,
        images=images,
        search_count=1,
        thread_id=thread_id,
    )


def _mesure_generation(result: dict[str, Any]) -> GenerationMeasure:
    """Décomptes de tokens du serveur d'inférence, tels qu'il les a rendus.

    Les champs restent à `None` quand Ollama ne les a pas rendus. Ce n'est pas
    zéro : une moyenne qui confondrait « pas de mesure » et « zéro token » serait
    fausse, et c'est précisément ce genre de confusion que ce lot corrige
    ailleurs.
    """
    mesure = result.get("generation_measure")
    reponse = result.get("response") or ""
    if mesure is None:
        return GenerationMeasure(answer_chars=len(reponse))
    return GenerationMeasure(
        answer_chars=len(reponse),
        eval_count=mesure.eval_count,
        prompt_eval_count=mesure.prompt_eval_count,
        prompt_tokens_estimated=mesure.estimated_tokens,
        prompt_tokens_reliable=mesure.prompt_reliable,
        num_predict=mesure.num_predict,
    )


# ─── Réponse directe, sans sélection humaine ──────────────────────────────────

@app.post("/answer", response_model=AnswerResponse, dependencies=[Depends(require_api_key)])
async def answer(req: AnswerRequest) -> AnswerResponse:
    """Question → réponse, sans interruption ni sélection des sources.

    Le flux interactif (/chat/start + sélection + /chat/resume) n'est pas
    rejouable en batch : il attend un humain. Cet endpoint exécute le même
    graphe avec les sources les mieux classées, et retourne en plus les
    passages réellement soumis au LLM et le temps passé à chaque étage.

    Sans les contextes, une campagne d'évaluation ne peut pas distinguer un
    échec de recherche d'un échec de génération — c'est la mesure qui permet
    d'attribuer la faute.
    """
    initial_state: AgentState = {
        "question": req.question,
        "chat_history": req.chat_history[-MAX_HISTORY_MESSAGES:],
        "retrieved_chunks": [],
        "reranked_chunks": [],
        "search_query": None,
        "search_translation": None,
        "selected_element_ids": [],
        "max_sources": req.max_sources,
        "top_k": req.top_k,
        "enriched_contexts": [],
        "submitted_contexts": [],
        "generation_measure": None,
        "response": "",
        "citations": [],
        "images": [],
        "search_count": 0,
        "needs_more_info": False,
        "next_query": None,
        "dropped_contexts": 0,
        "_metadata": {},
    }

    # Un seul passage dans le graphe : la version précédente exécutait
    # retrieval et reranking ici PUIS relançait le graphe depuis son point
    # d'entrée, qui les refaisait. Les nœuds se chronomètrent eux-mêmes.
    limite: RunnableConfig = {"recursion_limit": 50}
    # Temps mural de la traversée entière : le seul chiffre qui ne dépend
    # d'aucune instrumentation interne, donc le seul contre lequel la partition
    # des étages puisse être confrontée. Ce que les nœuds n'ont pas réclamé
    # devient le résidu.
    debut = time.monotonic()
    result = await answer_graph.ainvoke(initial_state, limite)
    total_ms = int((time.monotonic() - debut) * 1000)
    timings = result.get("_metadata") or {}
    etapes = StageTimings(**decomposer(timings, total_ms))
    ranked = result.get("reranked_chunks", [])

    enriched = result.get("enriched_contexts", [])
    # Le chiffre que node_generate a réellement appliqué, remonté par l'état.
    # Le recalculer ici journalisait chaque troncature deux fois et rendait le
    # gabarit une fois de plus par candidate — et deux calculs séparés dérivent,
    # ce que ce champ sert précisément à publier.
    dropped = result.get("dropped_contexts", 0)
    by_element = {c.element_id: c for c in ranked}
    # Les sections que le budget a RETENUES, indexées par section : c'est ce qui
    # a été payé en tokens. Une métrique de précision du contexte calculée sur
    # les candidates mesurerait une intention.
    soumises = {c.section_id: c for c in result.get("submitted_contexts") or []}

    contexts = [
        RetrievedContext(
            element_id=ctx.element_id,
            section_id=ctx.section_id,
            filename=ctx.filename,
            collection=getattr(by_element.get(ctx.element_id), "collection", ""),
            source_path=getattr(by_element.get(ctx.element_id), "source_path", ""),
            section_title=ctx.section_title,
            language=getattr(by_element.get(ctx.element_id), "language", ""),
            page_no=getattr(by_element.get(ctx.element_id), "page_no", 0),
            relevance=getattr(by_element.get(ctx.element_id), "relevance", None),
            retained=ctx.section_id in soumises,
            # Le texte tel qu'il est PARTI quand la section a été retenue : la
            # troncature du budget en fait partie, et c'est elle qui décide des
            # caractères réellement payés.
            element_ids=element_ids_presents(soumises.get(ctx.section_id, ctx).markdown),
            text=soumises.get(ctx.section_id, ctx).markdown,
        )
        for ctx in enriched
    ]
    retenues = sum(1 for c in contexts if c.retained)
    if retenues + dropped != len(contexts):
        # La chaîne `on_fit` → `submitted_contexts` → endpoint est cassée : le
        # nombre d'écartées et le marquage des retenues viennent du MÊME
        # `PromptFit` et ne peuvent pas se contredire. Sans cet avertissement,
        # une campagne calculerait la précision du contexte sur un dénominateur
        # muet et la publierait comme une mesure.
        logger.warning(
            "Incohérence du budget : %d section(s) retenue(s) + %d écartée(s) pour %d "
            "candidate(s). La précision du contexte est incalculable sur cette réponse.",
            retenues,
            dropped,
            len(contexts),
        )

    # Capturé comme le flux interactif, mais sous `endpoint='answer'` : la
    # sélection est automatique ici, aucune décision humaine n'y figure. C'est
    # ce qui permet de comparer une campagne à l'usage réel — à condition de
    # filtrer, une campagne écrivant 138 interactions d'un coup.
    thread_id = str(uuid.uuid4())
    await record_start(
        thread_id=thread_id,
        endpoint="answer",
        question=req.question,
        search_query=result.get("search_query"),
        search_translation=result.get("search_translation"),
        ranking=ranked,
        timings=timings,
    )
    await record_completion(
        thread_id=thread_id,
        response=result.get("response", ""),
        citations=result.get("citations", []),
        images=result.get("images", []),
        search_count=result.get("search_count"),
        submitted=enriched,
        selected_element_ids=[c.element_id for c in enriched],
        # Seul endroit où le nombre de sources écartées est connu sans passer
        # par l'état du graphe : il vient d'être calculé juste au-dessus.
        dropped_contexts=dropped,
        timings=timings,
    )

    return AnswerResponse(
        question=req.question,
        answer=result.get("response", ""),
        retrieved_element_ids=[c.element_id for c in ranked],
        contexts=contexts,
        citations=result.get("citations", []),
        images=result.get("images", []),
        search_count=result.get("search_count", 1),
        retrieval_ms=timings.get("retrieval_ms", 0) + timings.get("rerank_ms", 0),
        generation_ms=timings.get("generation_ms", 0),
        dropped_contexts=dropped,
        timings=etapes,
        generation=_mesure_generation(result),
    )


# ─── Chat avec agentic loop (LangGraph) ───────────────────────────────────────

async def _register_thread(thread_id: str) -> None:
    """Inscrit la session au registre durable, puis purge les périmées.

    **Asynchrone, et ce n'est pas cosmétique.** La version synchrone appelait
    `checkpointer.delete_thread`, la méthode SYNCHRONE d'`AsyncSqliteSaver` :
    depuis une route `async def`, donc depuis le fil de la boucle d'événements,
    la bibliothèque lève `asyncio.InvalidStateError`. Absorbée par un
    `except Exception: logger.debug(...)` que `LOG_LEVEL=INFO` effaçait, elle
    laissait le journal annoncer une purge qui n'avait jamais eu lieu. Aucune
    ligne n'a jamais été supprimée de `checkpoints.sqlite`.

    Le registre vit dans la base du checkpointer et non plus en mémoire : un
    registre de processus n'atteint que ce que le processus courant a lui-même
    créé, et toute session antérieure au dernier redémarrage restait sur le
    disque pour toujours. Cf. `src/agent/sessions.py`.
    """
    await sessions.enregistrer(thread_id)
    await sessions.purger(interactive_graph().checkpointer, epargner=thread_id)


@app.post("/chat/start", dependencies=[Depends(require_api_key)])
async def chat_start(req: SearchRequest) -> dict[str, Any]:
    """Démarre le flux LangGraph : retrieval + reranking, puis suspend en attente
    de la sélection des sources.

    Retourne un thread_id à passer à /chat/resume.
    """
    thread_id = str(uuid.uuid4())
    await _register_thread(thread_id)
    config: RunnableConfig = {"configurable": {"thread_id": thread_id}}

    initial_state: AgentState = {
        "question": req.question,
        # Multi-turn : derniers échanges seulement, pour borner le contexte
        "chat_history": req.chat_history[-MAX_HISTORY_MESSAGES:],
        "search_query": None,
        "search_translation": None,
        "retrieved_chunks": [],
        "reranked_chunks": [],
        "selected_element_ids": [],
        "max_sources": None,
        "top_k": req.top_k,
        "enriched_contexts": [],
        "submitted_contexts": [],
        "generation_measure": None,
        "response": "",
        "citations": [],
        "images": [],
        "search_count": 0,
        "needs_more_info": False,
        "next_query": None,
        "dropped_contexts": 0,
        "_metadata": {},
    }

    # Exécuter jusqu'à l'interruption (avant await_source_selection) ;
    # l'état est persisté par le checkpointer LangGraph sous ce thread_id.
    result = await interactive_graph().ainvoke(initial_state, config)

    groups = group_by_document(result.get("reranked_chunks", []))

    # Ouverture de l'enregistrement de capture. C'est ici, et nulle part
    # ailleurs, qu'on sait ce qui a été PROPOSÉ : /chat/resume ne verra que ce
    # qui a été retenu, et l'écart entre les deux est la donnée que ce lot
    # récolte. Les deux phases sont jointes par thread_id.
    await record_start(
        thread_id=thread_id,
        endpoint="chat",
        question=req.question,
        search_query=result.get("search_query"),
        search_translation=result.get("search_translation"),
        ranking=result.get("reranked_chunks", []),
        timings=result.get("_metadata") or {},
    )

    return {
        "thread_id": thread_id,
        "question": req.question,
        "groups": [g.model_dump() for g in groups],
    }


async def _completer_capture(
    thread_id: str, etat: dict[str, Any], selection: list[str]
) -> None:
    """Complète l'enregistrement d'usage avec ce que la génération a produit.

    `dropped_contexts` est lu dans l'état plutôt que recalculé : c'est le chiffre
    que `node_generate` a réellement appliqué au prompt, publié par le rappel
    `on_fit`. Le `.get` reste défensif — un état sans la clé enregistre NULL
    plutôt que 0, parce que 0 affirmerait qu'aucune source n'a été écartée — mais
    le graphe la porte désormais sur les trois chemins, et un test l'exerce sur
    des sections qui dépassent réellement la fenêtre.
    """
    await record_completion(
        thread_id=thread_id,
        response=etat.get("response", ""),
        citations=etat.get("citations", []),
        images=etat.get("images", []),
        search_count=etat.get("search_count"),
        submitted=etat.get("enriched_contexts", []),
        # La sélection HUMAINE, pas les sections soumises : deux éléments d'une
        # même section n'en produisent qu'une, et la boucle agentique peut en
        # ajouter que personne n'a jamais vues.
        selected_element_ids=selection,
        dropped_contexts=etat.get("dropped_contexts"),
        timings=etat.get("_metadata") or {},
    )


@app.post("/chat/resume", response_model=None, dependencies=[Depends(require_api_key)])
async def chat_resume(req: SourceSelectionRequest) -> EventSourceResponse | ChatResponse:
    """Reprend le flux LangGraph après sélection des sources par l'utilisateur.

    Reconstruit le contexte, génère la réponse, post-traite les citations.
    """
    config: RunnableConfig = {"configurable": {"thread_id": req.thread_id}}

    snapshot = await interactive_graph().aget_state(config)
    if not snapshot.values or not snapshot.next:
        raise HTTPException(
            status_code=404,
            detail="Session introuvable ou déjà terminée. Relancez /chat/start.",
        )

    # Injecter la sélection dans l'état persisté, puis reprendre là où le
    # graphe s'était interrompu (input None = resume, pas un nouveau run).
    await interactive_graph().aupdate_state(
        config, {"selected_element_ids": req.selected_element_ids}
    )

    if req.stream:
        async def stream_generator() -> AsyncIterator[dict[str, Any]]:
            final_state: dict[str, Any] = {}
            # "custom" : tokens émis par node_generate ; "values" : état complet
            # après chaque nœud (le dernier reçu = état final).
            async for mode, chunk in interactive_graph().astream(
                None, config, stream_mode=["custom", "values"]
            ):
                if mode == "custom":
                    yield {"data": json.dumps(chunk)}
                elif mode == "values" and isinstance(chunk, dict):
                    final_state = chunk
            yield {
                "data": json.dumps({
                    "done": True,
                    "answer": final_state.get("response", ""),
                    "citations": [c.model_dump() for c in final_state.get("citations", [])],
                    "images": [i.model_dump() for i in final_state.get("images", [])],
                    "search_count": final_state.get("search_count", 1),
                })
            }
            # APRÈS le dernier événement : la réponse est servie, l'écriture ne
            # coûte rien à qui attendait. Rien de synchrone n'entre dans le
            # chemin de diffusion, c'est la contrainte du lot.
            await _completer_capture(req.thread_id, final_state, req.selected_element_ids)

        return EventSourceResponse(stream_generator())

    result = await interactive_graph().ainvoke(None, config)
    await _completer_capture(req.thread_id, result, req.selected_element_ids)
    return ChatResponse(
        answer=result.get("response", ""),
        citations=result.get("citations", []),
        images=result.get("images", []),
        search_count=result.get("search_count", 1),
    )


# ─── Appréciation d'une réponse ───────────────────────────────────────────────

@app.post("/feedback", response_model=FeedbackResponse, dependencies=[Depends(require_api_key)])
async def feedback(req: FeedbackRequest) -> FeedbackResponse:
    """Attache une appréciation à une interaction déjà enregistrée.

    Note binaire : personne ne remplit une échelle, et un 3/5 ne se lit pas.
    Deux valeurs se comptent, et c'est ce qui rendra un jour un jeu doré réel
    utilisable — une question, ses sources validées, et un humain qui dit si la
    réponse valait quelque chose.

    Un `thread_id` inconnu rend 404 : c'est une erreur du client, il a inventé
    ou périmé son identifiant. Une capture désactivée ou en échec rend 200 avec
    `recorded: false` — ce n'est pas au client d'en porter la faute, et un 500
    ferait échouer une requête pour une observation perdue.
    """
    sort = await record_feedback(
        thread_id=req.thread_id, rating=req.rating, comment=req.comment
    )
    if sort == "inconnu":
        raise HTTPException(
            status_code=404,
            detail="Aucune interaction enregistrée sous ce thread_id.",
        )
    if sort == "desactive":
        return FeedbackResponse(recorded=False, detail="Capture d'usage désactivée.")
    if sort == "echec":
        return FeedbackResponse(
            recorded=False, detail="Enregistrement impossible, cf. journal du service."
        )
    return FeedbackResponse(recorded=True)


# ─── Médias (proxy MinIO) ─────────────────────────────────────────────────────

@app.get("/media/{object_name:path}", dependencies=[Depends(require_api_key)])
def media(object_name: str) -> Response:
    """Sert un objet MinIO (image croppée) au navigateur.

    L'endpoint interne minio:9000 n'est pas résolvable hors du réseau Docker :
    l'API joue le rôle de proxy pour les images référencées dans les réponses.
    """
    data = get_object_bytes(object_name)
    if data is None:
        raise HTTPException(status_code=404, detail="Objet introuvable.")
    return Response(content=data, media_type="image/png")
