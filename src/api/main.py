import asyncio
import json
import logging
import re
import secrets
import threading
import time
import uuid
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit

import httpx
from anyio import CapacityLimiter, to_thread
from anyio.lowlevel import RunVar
from fastapi import Depends, FastAPI, Header, HTTPException, Path, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from langchain_core.runnables import RunnableConfig
from sse_starlette.sse import EventSourceResponse

from src.agent import sessions
from src.agent.chronometrie import decomposer
from src.agent.dialecte_llm import dialecte_courant
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
from src.agent.llm import PromptFit, generate_stream
from src.agent.minio_client import get_object_bytes
from src.agent.retriever import (
    EmbeddingModelMismatchError,
    etat_du_peripherique,
    etat_modele_embedding,
    group_by_document,
    lexical_ready,
    lexical_stale,
    rebuild_lexical_index,
    rerank,
    retrieve,
    verifier_modele_embedding,
)
from src.agent.retriever import ping as chroma_ping
from src.agent.settings import settings
from src.agent.state import AgentState
from src.agent.usage import initialiser as usage_initialiser
from src.agent.usage import record_completion, record_feedback, record_start
from src.agent.usage import stats as usage_stats
from src.api.identite_du_code import identite_du_code
from src.api.schemas import (
    MAX_HISTORY_MESSAGES,
    AnswerRequest,
    AnswerResponse,
    ChatRequest,
    ChatResponse,
    Citation,
    EmbeddingModelHealth,
    FeedbackRequest,
    FeedbackResponse,
    GenerationMeasure,
    HealthResponse,
    ImageRef,
    MoteurLlmHealth,
    ReindexResponse,
    RetrievedContext,
    SearchRequest,
    SearchResponse,
    SectionContext,
    SessionStats,
    SourceSelectionRequest,
    SourcesResponse,
    StageTimings,
    TorchDeviceHealth,
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


# ─── Concordance du modèle d'embedding ───────────────────────────────────────
#
# OÙ LE GARDE VIT, ET POURQUOI PAS ICI. Le garde qui REFUSE est dans
# `retriever._dense_search` : c'est le site qui produit le comportement à
# empêcher, et le seul que tout chemin de recherche traverse. Ce qui suit est sa
# VOIX — le démarrage la dit tôt, `/health` la dit en continu — et non le garde
# lui-même. Un rapport ne protège de rien : entre le moment où la divergence
# devient lisible dans `/health` et celui où quelqu'un la lit, un agent qui
# continuerait de chercher servirait des réponses fausses.
#
# CE QUE LE DÉMARRAGE NE FAIT PAS, ET C'EST UNE DÉCISION. Il ne lève pas. Lever
# ici tuerait le processus : `frontend` attend `agent-api` en `service_healthy`
# (`docker-compose.yml`), donc un agent qui ne démarre pas laisse l'exploitant
# devant un frontend absent, sans un mot sur le modèle d'embedding. Ce dépôt a
# déjà payé cette forme-là une fois, pour une autre cause — c'est tout le sujet
# de `tests/unit/test_health_parallele.py` — et la reproduire serait défaire une
# décision mesurée. Le refus est donc porté par la recherche, qui rend 503 en
# nommant les deux modèles, pendant que le processus reste debout pour l'expliquer.

def _embedding_inconnu() -> EmbeddingModelHealth:
    """Ce qu'on publie quand la sonde n'est pas revenue ou a levé."""
    return EmbeddingModelHealth(
        status="unknown", expected=settings.embedding_model_name, collection=None
    )


def _peripherique_inconnu() -> TorchDeviceHealth:
    """Ce qu'on publie quand la sonde du périphérique n'est pas revenue.

    `requested` est le SEUL champ qu'on peut encore affirmer : il vient du
    réglage, pas de torch. Les autres sont donnés au pire cas — build sans CUDA,
    carte invisible, modèles non chargés — et c'est le bon sens de repli pour
    CE champ-ci : « je n'ai pas pu lire » et « pas de GPU » se soignent par le
    même geste, ouvrir le mode d'emploi et vérifier les trois conditions, là où
    l'inverse ferait croire à un GPU en service qu'on n'a pas su voir.
    """
    return TorchDeviceHealth(
        requested=settings.torch_device,
        torch_version="",
        cuda_build=None,
        cuda_available=False,
    )


def _journaliser_concordance(etat: EmbeddingModelHealth) -> None:
    """Dit au journal ce que la sonde a trouvé, au niveau que ça mérite."""
    if etat.status == "ok":
        logger.info(
            "Modèle d'embedding : la collection '%s' est estampillée '%s', "
            "conforme au réglage.",
            settings.chroma_collection,
            etat.collection,
        )
    elif etat.status == "mismatch":
        logger.error(
            "MODÈLE D'EMBEDDING DIVERGENT : la collection '%s' a été indexée avec '%s' "
            "et le réglage nomme '%s'. Les deux rendent des vecteurs de même largeur, "
            "donc la recherche rendrait des passages plausibles et FAUX. Toute recherche "
            "est refusée en 503 jusqu'à ce que les deux côtés s'accordent.",
            settings.chroma_collection,
            etat.collection,
            etat.expected,
        )
    elif etat.status == "missing":
        logger.error(
            "MODÈLE D'EMBEDDING INVÉRIFIABLE : la collection '%s' ne porte aucune "
            "estampille `embedding_model`, donc rien ne dit avec quel modèle elle a été "
            "indexée, et l'agent la lirait avec '%s'. Toute recherche est refusée en "
            "503 : réingérer avec le pipeline courant, qui estampille.",
            settings.chroma_collection,
            etat.expected,
        )
    else:
        logger.warning(
            "Modèle d'embedding : estampille de la collection '%s' illisible (ChromaDB "
            "muet ou injoignable). La concordance sera revérifiée à la première "
            "recherche ; le réglage nomme '%s'.",
            settings.chroma_collection,
            settings.embedding_model_name,
        )


async def _concordance_embedding() -> EmbeddingModelHealth:
    """Lit l'estampille sous le plafond des sondes, et sans lâcher plus d'un fil.

    Sous le MÊME plafond que les sondes de `/health`, et par le MÊME garde « en
    vol » : la lecture est locale une fois la collection ouverte, mais l'ouvrir
    est un aller-retour réseau, et un ChromaDB muet bloquerait le fil. Employée
    aussi au démarrage, où un plafond est tout aussi nécessaire — sans lui, un
    store muet empêcherait l'agent de démarrer, ce que ce lot a précisément
    décidé de ne pas faire.
    """
    tache = asyncio.create_task(
        _sonder("modele_embedding", etat_modele_embedding, appelant="/health")
    )
    await asyncio.wait([tache], timeout=_PLAFOND_SONDES_S)
    return _relever("modele_embedding", tache, si_levee=None) or _embedding_inconnu()


async def _concordance_avant_le_flux() -> None:
    """La MÊME lecture, sous le MÊME plafond, mais qui RELÈVE la divergence.

    Sœur de `_concordance_embedding()` : même estampille, même plafond, même
    garde « en vol ». La différence tient en un point, et c'est lui qui interdit
    de réemployer `_relever` — celle-ci ABSORBE ce qu'une sonde a levé et publie
    `si_levee`, ce qui est juste pour `/health`, une route qui doit rendre 200
    même dégradée, et FAUX ici : une divergence doit atteindre le gestionnaire de
    l'application, qui en fait un 503 portant les deux noms de modèles. Absorber
    la divergence est exactement la panne que la mutation X2 de l'audit mesure.

    PREMIÈRE DÉCISION — LE DÉPASSEMENT DU PLAFOND EST TRAITÉ COMME UNE
    ESTAMPILLE ILLISIBLE, ET C'EST LE MÊME PLAFOND. Le site avait déjà tranché
    le cas de l'illisible : absorbé, journalisé, le garde restant en place dans
    le flux, fail-closed. Un dépassement est la MÊME CHOSE, pour trois raisons
    qui sont des faits et non des goûts.

    - Ce que l'appelant apprend est identique : rien. « ChromaDB a répondu par
      une panne » et « ChromaDB n'a pas répondu » ne se distinguent pas du point
      de vue de la concordance — dans les deux cas aucun verdict n'existe. Ce
      dépôt l'a déjà tranché deux fois dans ce sens : `etat_modele_embedding()`
      range la levée en `unknown`, et le plafond de `_concordance_embedding()`
      range le silence en `unknown` aussi, par `_embedding_inconnu()`. Un
      troisième traitement pour le même non-savoir serait une divergence de
      sémantique sans fait pour la porter.
    - La conséquence doit l'être aussi, et c'est l'argument décisif. Refuser sur
      le dépassement ferait dépendre de ChromaDB une route qui, la plupart du
      temps, ne cherche PAS — l'objectif que le site d'appel nomme. Ce serait
      même STRICTEMENT PIRE que refuser sur la levée : le silence est la panne
      la plus banale d'un store réseau, celle que la reprise de `_dense_search`
      existe pour rattraper.
    - Et la sûreté ne bouge pas : ce qui est perdu au dépassement est la seule
      ANTICIPATION. Le garde reste en place à l'intérieur du flux, fail-closed,
      et une divergence qui revient dans le plafond est re-levée telle quelle.

    LE PLAFOND EST RÉEMPLOYÉ, PAS DOUBLÉ. La grandeur bornée est la même — un
    aller-retour vers ChromaDB pour ouvrir la collection — et c'est la MÊME
    lecture, ce que le docstring de `_sonder` disait déjà. Un second plafond
    laisserait les deux dériver alors qu'aucun fait ne les distingue : le jour
    où l'on mesure qu'ouvrir une collection demande plus de 3 s, les deux sites
    sont faux ENSEMBLE et doivent bouger ensemble.

    Ce que ce réemploi cache, et il faut le dire : la PROVENANCE des 3 s diffère.
    À `/health` c'est une échéance imposée du dehors — `docker-compose.yml` tue
    curl à 5 s. Ici aucune échéance extérieure n'existe : 3 s est un budget que
    la route s'impose. Il reste le bon ordre de grandeur, la requête enchaînant
    de toute façon sur une génération de plusieurs secondes, et il est en tout
    état de cause infiniment meilleur que l'absence de borne qu'il remplace.

    SECONDE DÉCISION — OUI, LE GARDE « EN VOL », ET SOUS LE MÊME NOM. La menace
    que ce drapeau existe pour borner est STRICTEMENT PLUS GRANDE ici qu'à
    `/health`, et c'est ce qui tranche : le cadenceur de `/health` est un tick
    toutes les 20 s, borné par construction, alors que l'appelant d'ici est une
    requête utilisateur, dont le débit n'est borné par rien — l'audit a mesuré
    que 26 requêtes bloquées épuisent le réservoir. Un drapeau dont le motif
    écrit est « un fil lâché par sonde à la fois, quelle que soit la durée de la
    panne » est a fortiori requis là où le taux de passage EST le taux de
    requêtes.

    Le MÊME nom, parce que c'est la même lecture de la même estampille sur le
    même objet de collection : un second fil ferait un travail identique. Deux
    noms lâcheraient deux fils et prétendraient à deux faits là où il n'y en a
    qu'un.

    Ce que le partage coûte, et il est accepté : une sonde de `/health` en vol
    fait renoncer cette route à son anticipation. Cela dégrade exactement vers le
    cas absorbé — aucun verdict, garde toujours en place dans le flux — donc vers
    ce que le dépassement produit déjà, et symétriquement `/health` publie
    `unknown` pour un tick, ce qu'il traite déjà comme non dégradant. En marche
    normale la contention est nulle : la lecture est locale une fois la
    collection ouverte.
    """
    tache = asyncio.create_task(
        _sonder("modele_embedding", verifier_modele_embedding, appelant="/chat/resume")
    )
    await asyncio.wait([tache], timeout=_PLAFOND_SONDES_S)
    if not tache.done():
        logger.warning(
            "/chat/resume : la concordance du modèle d'embedding n'a pas répondu en "
            "%.1f s ; on renonce à l'attendre, et la concordance sera revérifiée si le "
            "graphe reboucle vers une recherche. Le fil est LÂCHÉ, pas interrompu — le "
            "garde « en vol » de `_sonder` borne la fuite à UN fil par panne, que la "
            "panne dure et qu'une rafale simultanée la frappe. Le fil n'est pas démon : "
            "il retiendra l'interpréteur jusqu'à ce que le store rende la main, et un "
            "arrêt du conteneur ira au bout de sa grâce avant d'être tué.",
            _PLAFOND_SONDES_S,
        )
        tache.cancel()
        return
    if tache.cancelled():
        return
    exc = tache.exception()
    if exc is not None:
        raise exc


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
    # La concordance du modèle d'embedding, dite AVANT la première question
    # plutôt qu'à la première recherche. Elle ne bloque pas le démarrage — voir
    # le commentaire en tête de cette section — mais la taire jusqu'à ce qu'un
    # utilisateur cherche laisserait un agent inutilisable passer pour sain.
    _journaliser_concordance(await _concordance_embedding())
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

# ─── Refus de servir sur un index qu'un autre modèle a produit ───────────────

@app.exception_handler(EmbeddingModelMismatchError)
async def _refus_modele_embedding(
    _request: Request, exc: EmbeddingModelMismatchError
) -> JSONResponse:
    """503, et le motif dans le corps.

    503 se lit « je ne peux pas servir dans cet état », ce qui est vrai et
    actionnable. 500 se lirait « j'ai un bug » et enverrait chercher au mauvais
    endroit : le code est intact, c'est l'accord entre le réglage et l'index qui
    ne l'est pas. Le motif voyage dans le corps parce que les journaux d'un
    conteneur ne sont pas toujours à portée de qui lit la réponse.

    Journalisé en ERROR à chaque refus, et non une fois : ce n'est pas une
    nuisance de journal, c'est là que l'exploitant voit que des requêtes RÉELLES
    se cassent sur cette panne-là.

    CE DOCSTRING A ÉCRIT « LE SEUL ENDROIT », ET C'ÉTAIT FAUX. Ce gestionnaire
    n'est appelé que si la réponse n'a pas commencé : une divergence survenue
    pendant un flux SSE ne l'atteint jamais — Starlette rend « Caught handled
    exception, but response already started » — et le flux mourait alors sans
    une seule ligne. Il y a donc DEUX chemins de refus journalisés, et le second
    est dans le `stream_generator` de `/chat/resume`. Site canonique :
    `documentation/axes_amelioration.md` §4.20, trouvaille N1.
    """
    logger.error("Recherche refusée — %s", exc)
    return JSONResponse(status_code=503, content={"detail": str(exc)})


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

# ─── LE RÉSERVOIR DE FILS DES SONDES, ET POURQUOI IL EST À ELLES SEULES ──────
#
# LA PANNE QUE CECI FERME — B-3 de l'audit du 14 septembre 2026, et elle est
# NOUVELLE, dans l'autre sens que celle que le lot 12 existait pour fermer.
# `/search` et `/sources` sont des `def` : Starlette les exécute dans le
# threadpool d'AnyIO. `_sonder` passait par `to_thread.run_sync` SANS limiteur,
# c'est-à-dire dans le MÊME réservoir, dont le limiteur par défaut vaut **40**
# (`mesuré` le 14 septembre 2026, anyio 4.15.1,
# `current_default_thread_limiter().total_tokens`).
#
# Et `borne_des_etages_torch()` fait un `.acquire()` BLOQUANT DANS LE FIL : une
# requête qui attend son permis ne rend pas son fil. La borne de concurrence
# torch convertissait donc une saturation de CARTE en saturation du réservoir
# que les sondes de santé utilisent pour interroger les stores.
#
# CE QUE `/health` PUBLIAIT ALORS : `degraded`, avec `chromadb`, `nebulagraph`
# et `index_lexical` à **false** — trois dépendances parfaitement saines,
# déclarées en panne parce qu'aucun fil n'était libre pour les interroger.
# `mesuré` par l'audit sur l'application réelle : 13 appels sur 197 à 3,00 s
# pile (`_PLAFOND_SONDES_S`) ; borne désarmée, 1 sur 29. C'est strictement plus
# difficile à diagnostiquer qu'un 503 honnête : l'exploitant part chercher une
# panne de store qui n'existe pas.
#
# LA TAILLE, ET POURQUOI ELLE N'EST PAS 40. Le nombre de fils de sonde
# simultanés est déjà borné par `_sondes_en_vol`, qui n'en laisse partir qu'UN
# par nom de sonde ; les noms sont au nombre de cinq (`chromadb`,
# `nebulagraph`, `index_lexical`, `modele_embedding`, `peripherique_torch`).
# Huit laisse donc une marge de trois noms sans que ce limiteur devienne à son
# tour le goulot — et reste assez petit pour que les sondes ne puissent pas, à
# leur tour, affamer les recherches.
#
# UN `RunVar` ET NON UNE GLOBALE : un `CapacityLimiter` appartient à la boucle
# d'événements qui l'a créé. C'est exactement la forme qu'AnyIO emploie pour son
# propre limiteur par défaut, et elle garde les bancs de test — qui ouvrent une
# boucle par scénario — indépendants les uns des autres.
#
# SUR QUELLES VERSIONS D'ANYIO CECI TIENT, et c'est R-1 de l'audit du
# 14 septembre 2026. Tout ce bloc repose sur une propriété de l'implémentation
# d'AnyIO — un limiteur distinct fait NAÎTRE des fils supplémentaires au lieu
# d'en emprunter à un pool global borné — et cette dépendance arrivait ici en
# TRANSITIF, déclarée nulle part. Elle l'est désormais : `anyio>=4.1.0,<5` dans
# `requirements.txt`, et le plancher y porte la mesure qui le soutient (20
# versions jouées une par une, banc à deux directions). Sans plancher mesuré, la
# ligne ne vaudrait pas mieux que l'absence de ligne.
_JETONS_DES_SONDES = 8

_limiteur_des_sondes: RunVar[CapacityLimiter] = RunVar("_limiteur_des_sondes")


def _reservoir_des_sondes() -> CapacityLimiter:
    """Le limiteur de fils RÉSERVÉ aux sondes, créé à la première demande."""
    try:
        return _limiteur_des_sondes.get()
    except LookupError:
        limiteur = CapacityLimiter(_JETONS_DES_SONDES)
        _limiteur_des_sondes.set(limiteur)
        return limiteur


# Sondes lancées et pas encore revenues.
#
# Une sonde SYNCHRONE ne s'interrompt pas : rien ne peut tuer un fil bloqué dans
# un appel réseau, et renoncer à l'attendre ne fait que LÂCHER le fil, qui
# continue de tourner. Sans ce garde, un healthcheck toutes les 20 s contre un
# store muet lâcherait un fil de plus par sonde à chaque passage, dans le
# réservoir que les endpoints de recherche partagent.
#
# CE QUE LE GARDE BORNE, ET C'EST MESURÉ AUX DEUX BOUTS : un fil lâché par sonde
# et par panne — que la panne dure, et qu'elle soit frappée par une RAFALE
# simultanée. La seconde moitié de cette phrase est la trouvaille bloquante de
# l'audit étroit de la couche async (§4.25, B-2), et elle était FAUSSE ici d'un
# facteur 26 : le test `if nom in _sondes_en_vol` se faisait sur la boucle et la
# POSE du drapeau dans le fil, de part et d'autre d'un `await`. Une rafale
# arrivant dans la même boucle franchissait donc le test avant qu'aucun fil
# n'ait posé le drapeau. `mesuré` le 7 septembre 2026, forme de production, une
# seule boucle et aucun entrelacement forcé, collection qui pend :
#
#   avant — rafale de  1 → 1/1 rendue  en 3,00 s →  1 fil lâché
#   avant — rafale de  8 → 8/8 rendues en 3,00 s →  8 fils lâchés
#   avant — rafale de 26 → 26/26       en 3,00 s → 26 fils lâchés
#   après — rafale de 26 → 26/26       en 3,00 s →  1 fil lâché
#
# La pose est donc passée CÔTÉ BOUCLE (`_sonder`) et le retrait est resté CÔTÉ
# FIL (`_executer_sonde`). Le test-et-pose n'a aucun `await` entre ses deux
# moitiés : sur une boucle asyncio il est donc atomique, et c'est ce qui borne
# la rafale.
#
# L'OBJECTION QUE CE SITE OPPOSAIT À CETTE POSE est traitée, et non plus
# invoquée pour refuser : « tâche annulée avant que le fil démarre → drapeau
# posé à jamais ». Elle ne pouvait de toute façon pas servir de motif, le code
# d'avant atteignant DÉJÀ la cécité définitive dès qu'un fil pend pour de bon.
# `_sonder` la ferme avec un accusé de démarrage posé par le fil : si l'offload
# se termine par une exception SANS que le fil ait démarré, la boucle retire le
# drapeau elle-même.
#
# LE RÉSIDU QUE CE SITE DISAIT « ASSUMÉ ET BORNÉ » ÉTAIT RÉEL, ET IL EST FERMÉ
# (LOT-34, §4.74 du registre). La boucle décidait « le fil n'a pas démarré » en
# LISANT un accusé que le fil posait, et lire puis agir n'est pas atomique entre
# deux fils. AnyIO ne lance pas une fonction dont le futur est déjà annulé, mais
# une annulation tombée APRÈS ce contrôle et AVANT l'accusé trouvait un fil qui
# ALLAIT tourner : la boucle retirait le drapeau, un appel suivant en posait un
# neuf, et le fil renoncé tournait quand même — puis retirait PAR NOM le drapeau
# de cet appel vivant. `mesuré` sous retard injecté : 26 appels en rafale
# relancent alors UN fil de plus sur le store qui pend ; aucune sonde ne devient
# muette. Et la fenêtre n'est pas théorique : sous contention du GIL, un fil de
# sonde démarre jusqu'à plusieurs secondes après sa mise en file, donc au-delà du
# plafond.
#
# LA FERMETURE EST UNE PRISE, ET NON UN JETON. Un `threading.Lock` neuf par appel,
# pris SANS ATTENTE par le premier des deux qui le demande : le fil à son entrée,
# la boucle quand l'offload se termine par une exception. `acquire(blocking=False)`
# est un test-et-pose atomique, donc un seul des deux gagne, et le perdant ne
# fait RIEN — ni sonde, ni retrait. Un jeton d'appartenance aurait seulement
# empêché le retrait : le fil renoncé aurait tout de même frappé le store, à côté
# du fil de l'appel suivant. Aucun des deux côtés n'attend l'autre, donc la
# boucle ne se bloque jamais sur un fil.
_sondes_en_vol: set[str] = set()


def _executer_sonde[T](
    nom: str, sonde: Callable[[], T], prise: threading.Lock
) -> T | None:
    """Exécute une sonde synchrone DANS le fil du réservoir.

    Le drapeau « en vol » est RETIRÉ ici, par le fil lui-même, et non par la
    tâche qui l'attend : celle-ci rend la main au plafond alors que le fil tourne
    encore. Retiré côté tâche, le garde laisserait repartir un second fil à
    chaque appel — exactement ce qu'il existe pour empêcher.

    Il n'est PAS posé ici, et c'est la correction de §4.25 B-2 : posé dans le
    fil, il arrivait trop tard pour une rafale déjà passée par le test de
    `_sonder`. La pose est côté boucle ; voir le commentaire de `_sondes_en_vol`.

    `prise` décide QUI retirera le drapeau, et elle est prise AVANT tout le
    reste : ce qui suit peut bloquer pour toujours, et c'est précisément le cas
    qu'on garde. Si la boucle l'a prise la première, elle a déjà retiré le
    drapeau et renoncé à ce fil : il rend None sans sonder, dans un futur que
    plus personne n'attend. Voir le commentaire de `_sondes_en_vol`.
    """
    if not prise.acquire(blocking=False):
        return None
    try:
        return sonde()
    finally:
        _sondes_en_vol.discard(nom)


async def _sonder[T](
    nom: str, sonde: Callable[[], T], *, appelant: str
) -> T | None:
    """Lance une sonde synchrone, ou renonce si son fil précédent tourne encore.

    `appelant` nomme la route qui sonde, et il n'est pas décoratif : cette
    fonction est PARTAGÉE entre `/health` et `/chat/resume` depuis que
    l'anticipation de concordance l'emploie, et sa ligne de journal était restée
    écrite pour un seul appelant — elle annonçait `/health` depuis
    `/chat/resume`. Un exploitant qui lit « /health » ne va pas chercher la
    latence d'une requête utilisateur.

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

    Générique sur le retour, et pas seulement booléenne : la lecture de
    l'estampille du modèle d'embedding passe par le même mécanisme et rend un
    rapport à quatre états. Le drapeau « en vol », lui, ne dépend pas du type de
    ce que la sonde rend.
    """
    # TEST-ET-POSE, et les deux moitiés sont côté BOUCLE, sans `await` entre
    # elles : c'est ce qui le rend atomique sur une boucle asyncio, et c'est la
    # correction de §4.25 B-2. Voir le commentaire de `_sondes_en_vol` pour la
    # rafale mesurée avant et après.
    if nom in _sondes_en_vol:
        # WARNING, et non DEBUG. Cette ligne dit qu'une sonde a été SAUTÉE parce
        # qu'un store ne rend pas la main : c'est la panne, pas une trace de
        # mise au point. En DEBUG, l'absorption était muette dès le deuxième
        # passage — `mesuré` : sur 6 requêtes contre un store qui pend, 1 seule
        # ligne WARNING et 5 en DEBUG, alors que ce fichier écrit que
        # « l'absorption n'est pas muette ». Le cadenceur de `/health` est un
        # tick toutes les 20 s : le débit de cette ligne est borné par lui, et
        # une panne de store MÉRITE une ligne toutes les 20 s.
        logger.warning(
            "%s : sonde %s encore en vol, aucun second fil lancé — un fil est déjà "
            "lâché sur cette sonde et le store n'a pas rendu la main ; ce passage "
            "renonce à son verdict",
            appelant,
            nom,
        )
        return None
    _sondes_en_vol.add(nom)
    prise = threading.Lock()
    try:
        # `limiter=` ET C'EST TOUTE LA CORRECTION DE B-3 : sans lui, cette
        # ligne puise dans le réservoir que les endpoints `def` — donc les
        # requêtes qui attendent un permis de la borne torch — occupent
        # jusqu'à 40. Voir le bloc `_reservoir_des_sondes` ci-dessus.
        return await to_thread.run_sync(
            _executer_sonde,
            nom,
            sonde,
            prise,
            abandon_on_cancel=True,
            limiter=_reservoir_des_sondes(),
        )
    except BaseException:
        # `BaseException` parce que `CancelledError` est le cas VISÉ, et qu'elle
        # n'hérite pas d'`Exception`. Justification de l'élargissement : ce bloc
        # ne rattrape rien, il RÉPARE un état de module avant de relever.
        #
        # Le drapeau n'est retiré que si la boucle GAGNE la prise : le fil n'a
        # alors pas démarré, et il ne sondera plus. Perdue, c'est le fil qui la
        # tient et qui retirera le drapeau en revenant ; le retirer ici
        # rouvrirait la fuite d'un fil par requête que ce garde existe pour
        # fermer. Lire un accusé de démarrage à la place de prendre ce verrou
        # était le résidu du §4.73 : voir le commentaire de `_sondes_en_vol`.
        if prise.acquire(blocking=False):
            _sondes_en_vol.discard(nom)
        raise


# Combien de temps on accorde au serveur LLM pour dire QUI il est, PAR REQUÊTE.
# Ce relevé est une COMMODITÉ de traçabilité, pas une sonde de santé :
# `_sonder_moteur` dit déjà si le service répond ; celui-ci dit ce qu'il est.
#
# CE DÉLAI NE BORNE PAS `/health`, ET LE COMMENTAIRE QU'IL PORTAIT LE LAISSAIT
# CROIRE — réserve R1 de l'audit du 15 septembre 2026, corrigée ici. Il vaut
# `_MOTEUR_REQUETES_MAX` fois plus en SÉQUENCE, soit 9,0 s au pire, très au-delà
# des 5 s que `docker-compose.yml` accorde au healthcheck. Ce qui protège la
# route est `_PLAFOND_SONDES_S`, et lui seul ; l'audit du 15 septembre l'a
# mesuré à 3,01 s sous quatre dépendances pendantes. Ce que ce délai-ci borne
# est la durée de vie de la TÂCHE de sonde, qui survit au plafond et continue en
# fond : elle doit finir avant le battement suivant, sans quoi les sondes
# s'empileraient. C'est cette relation-là qui est désormais épinglée, dans
# `test_health_parallele.py`.
_MOTEUR_TIMEOUT_S = 3.0

# Le nombre MAXIMAL de requêtes qu'un relevé coûte, et c'est une propriété, pas
# le compte d'une scène : la version du serveur, puis son catalogue. Il valait
# **3** tant que le dépôt savait parler à deux moteurs — la route de version de
# l'un était essayée avant celle de l'autre ; le lot 28 retire cette première
# requête avec le moteur qu'elle interrogeait. Le site canonique de ce chiffre
# est ici ; les deux tests qui le tiennent le relisent plutôt que de le recopier.
_MOTEUR_REQUETES_MAX = 2

# Le relevé, mémorisé pour la vie du processus après un premier relevé COMPLET.
#
# POURQUOI UN CACHE, ET CE QU'IL COÛTE. `/health` est battu par le healthcheck
# du compose toutes les 20 s. Deux requêtes de plus à chaque battement, vers un
# serveur d'inférence PARTAGÉ avec une autre équipe, seraient un prix permanent
# payé pour un fait qui ne change qu'au redémarrage de ce serveur. Ce qu'on y
# perd est borné et nommé : un serveur LLM remplacé SOUS un agent qui continue
# de tourner serait publié dans son état d'avant, jusqu'au prochain redémarrage
# de l'agent.
#
# L'ANALOGIE AVEC `peripherique_de_la_campagne` ÉTAIT FAUSSE, et elle est retirée
# — non bloquante §3 de l'audit du 15 septembre 2026. Celui-ci vit dans
# `scripts/evaluate.py`, un processus de campagne qui **se termine** au bout de
# quelques minutes ; ceci est un DÉMON battu toutes les 20 s pendant des jours.
# Une borne acceptable pour l'un ne l'est pas pour l'autre, et c'est précisément
# parce qu'elle ne l'est pas que le relevé porte désormais `releve_le` : le
# lecteur externe — le pipeline, l'équipe voisine — ne pouvait pas distinguer un
# relevé pris il y a dix secondes d'un relevé pris il y a onze heures. Il le peut.
#
# `_moteur_releve` EST LE SEUL ÉTAT MÉMORISÉ À VIE DE `/health` : toutes les
# autres sondes sont recréées à chaque battement.
#
# NI UN ÉCHEC NI UN RELEVÉ PARTIEL NE SONT MÉMORISÉS, et c'est la bloquante de
# l'audit du 15 septembre 2026 (§1). La phrase que ce site portait — « un serveur
# qui n'avait pas fini de démarrer resterait muet pour toujours si on gardait son
# silence » — décrivait le cas en CROYANT le couvrir : un serveur qui n'a pas
# fini de démarrer est celui dont le port HTTP répond, donc dont la route de
# version répond, mais dont le catalogue n'est pas encore servi. Son relevé
# n'était pas muet, il était PARTIEL — et figé à vie, il faisait publier
# `modele_servi: null` sur un serveur parfaitement sain, dont
# `signature_du_moteur` tire « modèle ABSENT DU SERVEUR ». Une affirmation
# fausse, pas un silence : exactement ce que la doctrine « muet n'est pas
# différent » existe pour interdire. Le prédicat porte donc maintenant sur le
# FAIT relevé et non sur le seul nom du serveur — voir `_releve_est_complet`.
_moteur_releve: MoteurLlmHealth | None = None


def _forme_comparable(nom: str) -> str:
    """Un nom de modèle réduit à ce qui le désigne : ses alphanumériques, en bas de casse.

    CE QU'ELLE JETTE EST EXACTEMENT CE QUI DIFFÈRE ENTRE LES DEUX ÉCOSYSTÈMES —
    la casse, les `/` de l'organisation, les `-` et les `:` de séparation. Ce
    qu'elle garde est la suite de caractères qui nomme le modèle et sa taille.
    """
    return re.sub(r"[^a-z0-9]", "", nom.lower())


# Les mots par lesquels l'écosystème NOMME une dérivation, et rien d'autre.
#
# NON BLOQUANTE §2 DE L'AUDIT DU 15 SEPTEMBRE 2026. La relation cherchait le nom
# demandé comme infixe du nom servi : tout ce qui PROLONGE notre nom était donc
# reconnu comme le nôtre. L'audit a construit quatre dérivés sur l'`id`
# réellement servi par ce poste — une variante ablitérée, une requantification
# tierce, une distillation, un ajustement métier — et **les quatre étaient
# acceptés**, quand son témoin inerte était bien refusé.
#
# UN DÉRIVÉ N'EST PAS UN AUTRE POIDS DU MÊME MODÈLE, et c'est ce que la borne
# écrite ne couvrait pas : elle fermait la question du POIDS et laissait dehors
# celle de la DÉRIVATION. Un catalogue servant un ajustement de notre modèle le
# faisait signer comme le nôtre, mémorisé pour la vie du processus, et une
# campagne enregistrait un moteur faux.
#
# POURQUOI DES SEGMENTS ET NON LA FORME COMPARABLE. Cherchés dans la forme
# comparable — qui jette les séparateurs —, ces mots se trouveraient là où ils
# ne sont pas : `ft` est un infixe de « microsoft », `merge` de « submerged ».
# Un marqueur ne compte donc que s'il est un SEGMENT ENTIER du nom, entre deux
# frontières que l'écosystème écrit vraiment (`/`, `-`, `_`, `:`, `.`).
#
# CE QUE CETTE LISTE NE CONTIENT PAS, ET C'EST DÉLIBÉRÉ. Aucun format de
# quantification publié par l'ÉDITEUR sous son propre `id` — `w4a16`, `fp8`,
# `int8`, `awq`, `gptq`. Les séparer reviendrait à refermer la borne du POIDS,
# qui reste ouverte parce que rien de ce que vLLM expose ne la tranche ; et un
# refus de trop n'est pas gratuit : il rend `modele_servi` nul sur un serveur
# sain, donc le re-sondage permanent contre un serveur partagé. Les six derniers
# mots ci-dessous sont des formats de REDISTRIBUTION — un tiers reprend le poids
# de l'éditeur et le republie —, jamais le nom sous lequel l'éditeur sert.
_MARQUEURS_DE_DERIVATION = frozenset(
    {
        # garde-fous retirés
        "abliterated",
        "uncensored",
        "unaligned",
        # distillation — le nôtre serait le professeur, pas l'élève
        "distill",
        "distilled",
        # réentraînement et fusion de poids
        "finetune",
        "finetuned",
        "lora",
        "qlora",
        "sft",
        "dpo",
        "orpo",
        "rlhf",
        "merge",
        "merged",
        "slerp",
        # repackaging par un tiers, sous son propre format
        "bnb",
        "gguf",
        "exl2",
        "mlx",
        "4bit",
        "8bit",
    }
)


def _segments(nom: str) -> set[str]:
    """Le nom découpé aux frontières que l'écosystème écrit vraiment, en bas de casse.

    C'est le pendant exact de `_forme_comparable`, et les deux coexistent parce
    qu'elles répondent à deux questions différentes : celle-là JETTE les
    frontières, parce qu'elles ne tombent pas au même endroit dans les deux
    écosystèmes (`gemma4:e4b` donne `gemma4|e4b`, `google/gemma-4-E4B-it…` donne
    `gemma|4|e4b`) ; celle-ci les GARDE, parce qu'un marqueur de dérivation n'a
    de sens qu'entre deux frontières.
    """
    return {s for s in re.split(r"[^a-z0-9]+", nom.lower()) if s}


def _marqueurs_de_derivation_ajoutes(identifiant: str, demande: str) -> set[str]:
    """Les mots de dérivation que le nom SERVI porte et que le nom DEMANDÉ ne porte pas.

    LA DIFFÉRENCE EST LE POINT, et pas la simple présence. Un exploitant qui
    demande `gemma4:e4b-abliterated` demande la variante ablitérée : la lui
    servir est juste, et la lui refuser serait le re-sondage permanent sur un
    serveur parfaitement conforme à ce qu'on lui demande. Ce qui est refusé est
    la dérivation que NOUS n'avons pas demandée.
    """
    return (_segments(identifiant) & _MARQUEURS_DE_DERIVATION) - _segments(demande)


def _le_serveur_sert_ce_que_nous_demandons(identifiant: str, demande: str) -> bool:
    """L'`id` d'une entrée de catalogue vLLM est-il celui du modèle que NOUS demandons ?

    CE PRÉDICAT EST DEVENU LARGE POUR SON CAS NOMINAL, ET IL EST GARDÉ —
    lot 28. Il est né quand le nom DEMANDÉ et le nom SERVI vivaient dans deux
    espaces de nommage différents : le réglage demandait un tag de l'ancien
    moteur, le serveur servait un `id`, et seule une inclusion pouvait les
    confronter. `LLM_MODEL` porte désormais l'`id` EXACT que le serveur sert, de
    sorte que le cas nominal de ce poste est une ÉGALITÉ, que l'inclusion
    satisfait trivialement.

    IL N'EST PAS RESSERRÉ EN ÉGALITÉ POUR AUTANT, et c'est un choix écrit. vLLM
    peut servir sous un nom d'emprunt (`--served-model-name`) : un déploiement
    qui demande l'alias court et lit l'`id` long est sain, et l'égalité le
    publierait en `modele_servi: null`, donc en re-sondage permanent contre un
    serveur PARTAGÉ. Resserrer serait un durcissement que rien ici ne mesure ;
    élargir est ce que la suite refuse.

    LE SENS DE LA RELATION EST DÉLIBÉRÉ : le demandé est cherché DANS le servi,
    réduits l'un et l'autre par `_forme_comparable`, et **l'inclusion inverse
    n'est pas tentée**. Un nom demandé plus spécifique que l'`id` servi n'est
    donc PAS reconnu.

    CE QUE ÇA COÛTE, CHIFFRÉ, ET CE QUE ÇA NE COÛTE PAS. Un nom non reconnu rend
    `modele_servi` nul, donc le relevé n'est jamais mémorisé : **2 requêtes par
    battement, indéfiniment**, contre 2 en tout pour un nom reconnu — mesuré par
    l'audit du 15 septembre à 9 requêtes sur 3 battements contre 3, quand le
    relevé en coûtait encore 3. À 20 s d'intervalle, c'est
    près de neuf mille lectures quotidiennes vers un serveur PARTAGÉ, et
    `signature_du_moteur` imprime alors « modèle ABSENT DU SERVEUR » sur un
    serveur qui sert exactement ce qu'on lui demande. Le coût est **inchangé par
    cette correction** : ce qui change est qu'il n'est plus justifié par une
    phrase fausse, qu'il est GARDÉ par des scènes qui comptent ces requêtes, et
    qu'il est ANNONCÉ à chaque battement par le `warning` de R-4.

    POURQUOI L'INCLUSION INVERSE N'A PAS ÉTÉ AJOUTÉE : elle élargirait
    l'acceptation dans la direction exacte que garde la mutation M1 de l'audit du
    15 septembre 2026 — « la relation accepte tout » —, et elle n'a plus de cas
    connu à régler depuis que le nom demandé est l'`id` servi. Borne écrite, non
    fermée.

    ELLE REFUSE LES MODÈLES DÉRIVÉS DU NÔTRE — non bloquante §2 du même audit, et
    c'est le cas PROBABLE, pas le cas improbable. Voir `_MARQUEURS_DE_DERIVATION`
    pour ce qui est reconnu comme dérivation et pourquoi. **Ce qui reste ouvert,
    mesuré** : une dérivation publiée sans aucun des mots de cette liste reste
    acceptée — l'`id` est tout ce que vLLM nous donne, et `…-ct-juridique-v3` est
    indiscernable d'une déclinaison de l'éditeur pour qui ne connaît pas les deux
    noms. La borne est plus étroite qu'avant, elle n'est pas nulle.

    ELLE CONFOND DEUX MODÈLES QUE LES SÉPARATEURS SÉPARENT, et cette borne-là est
    STRUCTURELLE : `qwen2:5b` est reconnu dans `Qwen/Qwen-2.5B-Chat`, deux modèles
    réels et distincts, parce que `_forme_comparable` jette les frontières.
    Exiger qu'elles s'alignent refuserait l'`id` RÉELLEMENT servi par ce poste
    (`gemma4|e4b` contre `gemma|4|e4b`) : la fermer ferme le cas nominal.

    CE QU'ELLE NE SAIT PAS, ET C'EST UNE BORNE, PAS UN OUBLI. Elle ne sépare pas
    deux QUANTIFICATIONS DE L'ÉDITEUR du même modèle : `…-qat-w4a16-ct` et un
    hypothétique `…-fp8` la satisfont tous deux. C'est la borne déjà écrite au §6 de
    `documentation/moteur_llm.md` — rien de ce que les sept routes GET de
    l'instance exposent ne distingue deux poids servis sous un même `id`. Cette
    relation ferme la question du MODÈLE ; celle du POIDS reste ouverte, et elle
    ne se fermera pas ici. C'est pourquoi le lot 28 a retiré `empreinte_du_modele`
    et `quantification` du relevé : le seul catalogue qui savait les renseigner
    était celui de l'ancien moteur.

    UN NOM DEMANDÉ VIDE NE RECONNAÎT RIEN, et c'est le défaut que j'ai trouvé
    contre ma propre relation : la chaîne vide est un infixe de **tout**. Sans ce
    refus, un `LLM_MODEL` absent ou fait de seuls séparateurs aurait reconnu
    le premier modèle venu — le défaut qu'on ferme ici, en pire. Un réglage
    dégénérément court mais non vide (`g`) reste, lui, satisfait par presque
    tout : aucun seuil de longueur ne se justifierait sans arbitraire, et c'est
    une faute de configuration que ce relevé n'a pas mandat de corriger. **Borne
    écrite, non fermée.**
    """
    aiguille = _forme_comparable(demande)
    if not aiguille:
        return False
    if aiguille not in _forme_comparable(identifiant):
        return False
    return not _marqueurs_de_derivation_ajoutes(identifiant, demande)


def _releve_est_complet(releve: MoteurLlmHealth) -> bool:
    """Le relevé a-t-il abouti au point d'être figé pour la vie du processus ?

    LE PRÉDICAT EST `modele_servi`, DES DEUX CÔTÉS, et il est unique par choix :
    c'est le champ qui sépare « le serveur a dit son nom » de « le serveur a dit
    ce qu'il sert ». Tout ce qui manque quand il manque — la fenêtre servie — est
    lu au même endroit et dans la même requête, donc un seul champ suffit à
    décider.

    CETTE PHRASE ÉTAIT VRAIE À LA LETTRE SANS L'ÊTRE EN FAIT — non bloquante §2
    de l'audit du 15 septembre 2026. `modele_servi` valait `entrees[0]["id"]`,
    jamais confronté à quoi que ce
    soit : le prédicat ne pouvait y être faux que sur un catalogue **vide**, donc
    un serveur servant le modèle d'une autre équipe était mémorisé à vie sous un
    nom faux. Le symétrique exact, en pire, de la bloquante que ce prédicat
    venait de fermer : une affirmation POSITIVE fausse là où le défaut d'origine
    figeait un silence. Les deux côtés confrontent maintenant le catalogue à ce
    que NOUS demandons, par `_le_serveur_sert_ce_que_nous_demandons` sur
    `/v1/models` — et c'est de là que le prédicat tire son sens.

    LA SCÈNE QU'IL ÉCARTE EST TRANSITOIRE, et le code la nommait déjà : le
    catalogue qui ne répond pas encore. Un fait transitoire ne se fige pas ; il
    se redemande au battement suivant, vingt secondes plus tard.

    CE N'EST PAS UN REFUS DE RENDRE : le relevé partiel est rendu à l'appelant
    tel quel, avec ce qu'on sait déjà du serveur. `signature_du_moteur` le tient
    d'ailleurs pour non muet, et c'est juste — un serveur connu reste comparable.
    Seule la MÉMORISATION lui est refusée.

    CE QUE CE PRÉDICAT COÛTE, ET IL FAUT LE DIRE. Un serveur qui ne porterait
    **jamais** le modèle demandé — une faute de tag, un modèle retiré du
    catalogue — n'atteindra jamais le relevé complet : la sonde repartira à
    chaque battement, soit deux à trois GET toutes les 20 s, indéfiniment. C'est
    exactement le prix permanent que le cache existe pour ne pas payer, et il
    est ici accepté en connaissance de cause : il ne se produit que dans un état
    **anormal et réparable**, alors que le figer publierait une affirmation
    fausse dans un état **parfaitement sain**. Le coût reste borné — des lectures
    courtes, jamais une génération, jamais un jeton — et il se voit : c'est
    précisément le cas où `/health` publie `modele_servi: null`, à côté d'un
    `releve_le` qui avance à chaque battement au lieu de rester figé.

    ET IL EST DÉSORMAIS SIGNALÉ, PAS SEULEMENT LISIBLE — réserve R-4 du même
    audit. « Il se voit » était exact et insuffisant : il fallait aller lire
    `/health` pour le voir, et rien dans les journaux ne l'annonçait. Chaque
    relevé non mémorisé écrit maintenant un `warning` au site de la mémorisation.
    """
    return releve.modele_servi is not None


def _endpoint_expurge(hote: str) -> str:
    """L'URL du serveur LLM, sans ce qu'elle pourrait porter de secret.

    CE DÉPÔT EST PUBLIC ET `runs/*.json` Y EST VERSIONNÉ. `LLM_HOST` est un
    nom de service docker sur ce poste, mais rien n'empêche un déploiement d'y
    mettre `http://utilisateur:motdepasse@hote:8000`, et ce champ finirait
    recopié dans une campagne commitée. On ne garde donc que schéma, hôte et
    port — ce qui suffit à dire « ce n'est pas le même serveur qu'hier », qui est
    tout ce qu'on lui demande.
    """
    decoupe = urlsplit(hote)
    if not decoupe.scheme or not decoupe.hostname:
        # Une URL que `urlsplit` ne sait pas découper n'est pas recopiée : on ne
        # sait pas ce qu'elle contient. Le fait « illisible » est rendu tel quel.
        return "(illisible)"
    port = f":{decoupe.port}" if decoupe.port else ""
    return f"{decoupe.scheme}://{decoupe.hostname}{port}"


async def _lire_json(client: httpx.AsyncClient, url: str) -> dict[str, Any] | None:
    """Le corps JSON d'un GET, ou `None` dès que quoi que ce soit cloche.

    L'ABSORPTION EST LARGE ET ASSUMÉE : transport, délai, statut, décodage — ici
    ils disent tous la même chose, « je n'ai pas pu lire ». La distinction
    servirait un diagnostic que ce relevé ne rend pas ; `_sonder_moteur` porte
    déjà la santé du service, et c'est elle qu'un exploitant regarde.
    """
    try:
        reponse = await client.get(url)
        if reponse.status_code != 200:
            return None
        charge = reponse.json()
    except Exception:  # noqa: BLE001 — voir la docstring : toutes ces pannes se disent pareil
        return None
    return charge if isinstance(charge, dict) else None


async def _sonder_moteur_llm() -> MoteurLlmHealth | None:
    """QUI génère réellement, relevé du serveur. `None` si on n'a pas pu lire.

    LE RELEVÉ EXIGE UNE RÉPONSE POSITIVE, ET IL N'EN DÉDUIT RIEN DE PLUS. `GET
    /version` rend 200 et un `version` sur vLLM (`mesuré` le 18 septembre 2026 à
    12:35 UTC sur l'instance de ce poste : `{"version":"0.28.0"}`). Un serveur
    qui ne répond pas à cette route laisse le champ ENTIER muet : ce relevé ne
    range pas un silence dans un nom.

    CE QUE LE LOT 28 RETIRE ICI. Le dépôt savait parler à deux moteurs et
    essayait donc la route de version de l'autre AVANT celle-ci, pour dire lequel
    des deux répondait. Cette première requête part avec le moteur qu'elle
    interrogeait, et le relevé passe de trois requêtes à DEUX. Ce que ça change
    pour un exploitant qui aurait l'autre moteur en face : `moteur_llm` est
    désormais `null` au lieu de le nommer — le dépôt ne sait plus dire de qui il
    s'agit, il sait seulement que ce n'est pas celui auquel il parle, et la sonde
    `llm` de `services` porte déjà la panne. Ne pas le nommer est le prix assumé
    de ne plus le supporter ; l'inventer serait pire.

    Au plus DEUX requêtes, toutes en LECTURE : aucune génération, aucun jeton.
    Le serveur vLLM de ce poste appartient à une autre équipe.
    """
    global _moteur_releve
    if _moteur_releve is not None:
        return _moteur_releve
    # CE QUI EST SONDÉ EST CE QUI SERT. L'hôte et le nom du modèle viennent du
    # dialecte courant, donc du même site que celui auquel l'agent POSTE ses
    # générations : sonder ailleurs ferait publier la version et le modèle d'un
    # serveur auquel personne ne parle — une affirmation fausse, pas une absence.
    dialecte = dialecte_courant()
    hote = dialecte.hote
    serveur: str | None = None
    version: str | None = None
    servi: str | None = None
    fenetre: int | None = None
    async with httpx.AsyncClient(timeout=_MOTEUR_TIMEOUT_S) as client:
        charge = await _lire_json(client, f"{hote}/version")
        if charge is not None and isinstance(charge.get("version"), str):
            serveur, version = "vllm", charge["version"]
        if serveur is None:
            # Le serveur n'a pas dit son nom. On ne DEVINE pas : le champ entier
            # est muet, et `evaluate.py` le lira « je ne sais pas ».
            return None
        # `/v1/models` liste ce que le serveur SERT, et on y cherche NOTRE
        # entrée. Ce site prenait
        # `entrees[0]` sans la confronter à quoi que ce soit : non bloquante
        # §2 de l'audit du 15 septembre 2026, et symétrique exact de la
        # bloquante que ce lot venait de fermer. Un serveur qui sert le
        # modèle d'une AUTRE ÉQUIPE — le cas de ce poste, partagé — était
        # alors mémorisé à vie sous un nom faux, et `signature_du_moteur`
        # en tirait une ligne ni muette ni vraie que `--compare` traitait
        # comme un fait. L'ordre de `data` n'est pas un contrat, et
        # `entrees[0]` n'est pas « notre » entrée.
        catalogue = await _lire_json(client, f"{hote}/v1/models")
        for entree in (catalogue or {}).get("data") or []:
            if not isinstance(entree, dict):
                continue
            identifiant = entree.get("id")
            if not isinstance(identifiant, str):
                continue
            if not _le_serveur_sert_ce_que_nous_demandons(identifiant, dialecte.modele):
                continue
            servi = identifiant
            # La fenêtre est celle de NOTRE entrée, jamais celle d'une autre.
            longueur = entree.get("max_model_len")
            fenetre = longueur if isinstance(longueur, int) else None
            break
    releve = MoteurLlmHealth(
        serveur=serveur,
        endpoint=_endpoint_expurge(hote),
        version=version,
        modele_demande=dialecte.modele,
        modele_servi=servi,
        fenetre_servie=fenetre,
        # QUAND ce relevé a été pris, et non quand il est lu. C'est la différence
        # qui compte : mémorisé, il est publié des heures durant, et sans cette
        # date un lecteur externe ne peut pas distinguer « relevé il y a dix
        # secondes » de « relevé il y a onze heures ». Le rafraîchir à la lecture
        # mentirait dans l'autre sens, et c'est gardé.
        releve_le=datetime.now(UTC).isoformat(timespec="seconds"),
        # NOTRE réglage, nommé comme tel dans le schéma. Ces cinq-là changent le
        # SENS de la réponse et non sa vitesse : le raisonnement, la façon de
        # demander l'outil, l'aléa, la fenêtre demandée, le plafond de sortie.
        options={
            "thinking": settings.llm_thinking,
            "outils_natifs": settings.native_tool_calling,
            "temperature": settings.llm_temperature,
            "num_ctx": settings.llm_num_ctx,
            "max_tokens": settings.llm_max_tokens,
        },
    )
    if _releve_est_complet(releve):
        _moteur_releve = releve
        return releve
    # RÉSERVE R-4 DE L'AUDIT DU 15 SEPTEMBRE 2026 : LE RÉGIME DE RE-SONDAGE
    # N'ÉTAIT SIGNALÉ NULLE PART. Il était LISIBLE dans `/health` pour qui le
    # lit — `modele_servi: null` à côté d'un `releve_le` qui avance — et jamais
    # ANNONCÉ : `_relever` ne journalise que si la tâche lève ou dépasse le
    # plafond, or un relevé partiel est un retour normal. À 4 320 battements par
    # jour, un relevé qui n'aboutit jamais coûte 8 640 requêtes quotidiennes vers
    # un serveur d'inférence partagé avec deux autres équipes.
    #
    # IL PARLE À CHAQUE BATTEMENT, ET AUCUN ÉTAT NE LE LISSE. Le volume EST le
    # signal : un serveur qui finit de démarrer produit une ligne ou deux, un tag
    # renommé en produit une toutes les vingt secondes. Lisser demanderait de
    # mémoriser ce qu'on a déjà dit — un second état à vie, à garder juste, pour
    # économiser des lignes de journal. Le prix n'en vaut pas la peine, et c'est
    # la raison écrite plutôt que sous-entendue.
    # IL NE CHIFFRE PAS LA CADENCE, ET C'EST UN FAUX RÉSULTAT TROUVÉ CONTRE
    # MOI-MÊME : la première écriture annonçait « toutes les 3 s » en prenant
    # `_MOTEUR_TIMEOUT_S` pour l'écart entre deux battements. L'intervalle est
    # celui du healthcheck du compose — 20 s —, et **ce module ne le connaît
    # pas** : il vit dans `docker-compose.yml`, et c'est la porte qui le lit
    # (`_intervalle_du_healthcheck`). Un garde qui affirme un chiffre qu'il n'a
    # pas relevé est exactement ce que ce chantier passe son temps à réparer.
    logger.warning(
        "/health moteur_llm: relevé PARTIEL non mémorisé (serveur=%s, modèle demandé=%s "
        "introuvable dans ce que ce serveur sert) — la sonde repartira à CHAQUE battement "
        "de /health, jusqu'à %d requêtes par battement vers un serveur PARTAGÉ",
        serveur,
        dialecte.modele,
        _MOTEUR_REQUETES_MAX,
    )
    return releve


async def _sonder_moteur() -> bool:
    """Sonde HTTP du serveur LLM.

    Seule sonde réellement interruptible des quatre : elle fait des
    entrées-sorties asynchrones, donc le plafond la coupe pour de bon, sans
    laisser de fil derrière lui. Son propre délai de 5 s est désormais dominé par
    le plafond ; il reste parce qu'il est le contrat de CETTE sonde, et qu'un
    plafond global n'en tient pas lieu.

    `httpx.InvalidURL` n'est pas rattrapée, et c'est la décision écrite dans
    `llm.py` : elle n'hérite pas de `HTTPError`, un hôte de LLM mal formé est une
    erreur de configuration et non une panne de service. Elle remonte donc à
    `_relever`, qui la journalise en nommant son type au lieu de la taire.

    L'ADRESSE ET LE CHEMIN VIENNENT DU DIALECTE COURANT (lot 25), et c'est ce
    qui garantit que la sonde interroge le serveur auquel l'agent POSTE. Une
    route écrite en dur ici ferait passer cette sonde à `false` sur un serveur
    qui répond et génère, donc `/health` à `degraded` et le healthcheck du
    compose à `unhealthy` : une panne ANNONCÉE là où il n'y en a pas est du même
    ordre qu'une panne tue. `url_sonde` vaut `{LLM_HOST}/v1/models`.

    LE NOM DE CETTE FONCTION A CHANGÉ AU LOT 28, ET SA CLÉ PUBLIÉE AUSSI : la
    sonde s'appelait par le nom de l'ancien moteur, et se publiait sous cette
    même clé. C'est une RUPTURE DE CONTRAT pour un lecteur hors dépôt,
    et elle est assumée plutôt que tue : une clé qui nomme un moteur qu'on ne
    sert plus renseigne faux. Le healthcheck de `docker-compose.yml` ne lit pas
    cette clé — il ne lit que le code HTTP — et le dépôt ne contient aucun autre
    lecteur (`git grep`, 18 septembre 2026). La rupture est écrite dans
    `documentation/moteur_llm.md`, avec la migration du `.env`.
    """
    async with httpx.AsyncClient(timeout=5.0) as client:
        resp = await client.get(dialecte_courant().url_sonde)
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
      /health, donc passer le conteneur `unhealthy`, ce que cette route existe
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
    """Vérifie réellement les trois dépendances (Chroma, Nebula, moteur LLM).

    Les quatre sondes partent EN PARALLÈLE sous un plafond global : en séquence,
    elles dépassaient le délai du healthcheck et empêchaient le frontend de
    démarrer (voir `_PLAFOND_SONDES_S`).

    Retourne toujours 200 avec le détail par service ; status passe à
    "degraded" si l'une est down.

    POURQUOI 200 MÊME DÉGRADÉ, et le motif est mesuré. Un code d'erreur ferait
    échouer le healthcheck de `docker-compose.yml`, ce qui ne REDÉMARRE rien —
    `restart:` répond à la sortie du processus, pas à la santé, et 21 échecs
    consécutifs laissent `RestartCount=0` et `StartedAt` inchangé. Ce qui arrive
    est que le conteneur passe `unhealthy`, donc que `frontend`, qui en dépend en
    `condition: service_healthy`, ne lève pas au démarrage à froid : l'exploitant
    perd la seule route qui lui aurait dit ce qui ne va pas. Site canonique :
    `documentation/axes_amelioration.md` §1.27.
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
        nom: asyncio.create_task(_sonder(nom, sonde, appelant="/health"))
        for nom, sonde in sondes.items()
    }
    taches["llm"] = asyncio.create_task(_sonder_moteur())
    # Sous le MÊME plafond, et hors de `services` pour la même raison que le
    # périphérique : ce n'est pas un booléen. Une panne du serveur LLM est déjà
    # portée par la sonde `llm` ci-dessus ; celle-ci ne dit QUE l'identité, et
    # son silence ne dégrade donc rien — il se dit dans `services_unknown`.
    tache_moteur = asyncio.create_task(_sonder_moteur_llm())
    # Sous le MÊME plafond : `usage_stats` ouvre SQLite avec un busy_timeout de
    # 5 s, donc laissée dehors elle pouvait à elle seule faire dépasser le délai
    # du healthcheck, sans qu'aucune sonde soit en cause — un plafond qui ne
    # couvre pas tout finit par mentir. Son absence se dit en null, déjà prévu
    # par le contrat ; l'inventer en zéros décrirait une base vide. Ce que le
    # plafond y lâche est borné tout seul : aiosqlite tient un fil par connexion,
    # et la connexion abandonnée le ferme en se faisant collecter — au plus une à
    # la fois, le healthcheck ne passant que toutes les 20 s.
    tache_usage = asyncio.create_task(usage_stats())
    # Sous le même plafond et le même garde « en vol » que les quatre sondes,
    # mais HORS de `services` : ce dict est un `dict[str, bool]`, et un booléen
    # ne sait pas dire lequel des quatre états est en cause — surtout pas
    # distinguer « la collection ne porte pas d'estampille » de « je n'ai pas pu
    # la lire », qui ne se soignent pas pareil.
    tache_embedding = asyncio.create_task(
        _sonder("modele_embedding", etat_modele_embedding, appelant="/health")
    )
    # Sous le même plafond, et pour une raison PRÉCISE : `etat_du_peripherique`
    # ne fait aucune entrée-sortie réseau, mais `torch.cuda.is_available()`
    # interroge le pilote de la carte au premier appel d'un build CUDA. Un
    # pilote qui ne rend pas la main est une panne comme une autre, et elle ne
    # doit pas coûter le healthcheck — donc pas de traitement de faveur.
    tache_peripherique = asyncio.create_task(
        _sonder("peripherique_torch", etat_du_peripherique, appelant="/health")
    )

    # Liste typée `Future[Any]` : les tâches n'ont pas toutes le même type de
    # résultat, et c'est bien la même attente qui les borne toutes.
    attente: list[asyncio.Future[Any]] = [
        *taches.values(),
        tache_usage,
        tache_embedding,
        tache_peripherique,
        tache_moteur,
    ]
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
    # Une concordance REFUSÉE dégrade à elle seule, quatre sondes vertes ou non :
    # l'agent répond, les stores répondent, et pourtant toute recherche rend 503.
    # Un statut « ok » décrirait alors un service qui ne sert rien.
    embedding = _relever("modele_embedding", tache_embedding, si_levee=None) or _embedding_inconnu()
    concordance_refusee = embedding.status in {"mismatch", "missing"}
    # UN PÉRIPHÉRIQUE HORS D'ATTEINTE DÉGRADE À LUI SEUL, pour le MÊME motif que
    # la concordance juste au-dessus : les stores répondent, l'agent répond, et
    # pourtant toute recherche rend **500** — les deux modèles reçoivent
    # `device=settings.torch_device` sans aucun repli, donc ils lèvent au lieu de
    # retomber sur CPU. Un statut « ok » y décrirait un service qui ne sert rien,
    # et le healthcheck `curl -sf` du compose resterait vert pour toujours
    # puisqu'il ne lit que le code HTTP. `mesuré` en grandeur réelle le
    # 14 septembre 2026 : `POST /search` 500, `GET /health` 200 `status: ok`.
    # Site canonique : `documentation/audits/2026-09-14-audit-lot-11.md` §1.
    #
    # LE VERDICT SE LIT SUR LE RÉSULTAT DE LA SONDE, JAMAIS SUR SON REPLI, et
    # c'est la même distinction que `unknown` ci-dessous. `_peripherique_inconnu`
    # publie `requested` tel quel — donc `cuda` par défaut — avec
    # `cuda_available: false` : une lecture naïve du corps y verrait un
    # périphérique hors d'atteinte et dégraderait un service dont on ne sait
    # RIEN. Le `or` de repli est donc APRÈS ce calcul, pas avant.
    peripherique = _relever("peripherique_torch", tache_peripherique, si_levee=None)
    moteur = _relever("moteur_llm", tache_moteur, si_levee=None)
    peripherique_refuse = peripherique is not None and peripherique.hors_d_atteinte is not None
    # ET L'IGNORANCE SE DIT, sinon `ok` sur une sonde muette est indiscernable
    # de `ok` sur un service sain — NB-1 de l'audit du 14 septembre 2026. Ne pas
    # dégrader est la bonne décision (ci-dessus) ; ne rien publier en était une
    # autre, jamais prise. Le geste que `pour_le_pipeline_ingestion.md` rend au
    # voisin imprimait `ok None` dans les deux cas, et seul `torch_version: ""`
    # les distinguait — un détail que ce geste ne lisait pas.
    #
    # `services_unknown` et non un champ neuf : les cinq autres sondes disent
    # déjà leur ignorance par cette liste, `_embedding_inconnu()` par
    # `status="unknown"`, et un troisième dialecte pour le même non-savoir serait
    # une divergence sans fait pour la porter. `peripherique_torch` n'est pas
    # dans `taches` — il n'est pas un `bool` — donc la boucle ci-dessus ne l'y
    # met pas : il faut le dire ici.
    if peripherique is None:
        inconnues.append("peripherique_torch")
    # LE MOTEUR MUET N'ENTRE PAS DANS `services_unknown`, ET C'EST UN ARBITRAGE
    # PESÉ, non une omission. Le précédent voisin ferait croire l'inverse :
    # `peripherique_torch` y est inscrit, mais il y est parce qu'il DÉGRADE
    # `status` et qu'un exploitant doit savoir quoi réparer. Le moteur ne dégrade
    # rien — un serveur qui refuse de dire son nom n'est pas un serveur en panne,
    # et la sonde `llm` porte déjà la panne s'il y en a une.
    #
    # Ce qui resterait est du bruit PERMANENT : sur un déploiement dont le
    # serveur LLM n'expose aucune route de version, cette liste porterait
    # `moteur_llm` à chaque battement du healthcheck, pour une information que
    # `moteur_llm: null` donne déjà sans ambiguïté. Une liste d'anomalies qui
    # porte en permanence un non-problème cesse d'être lue.
    #
    # `unknown` ne dégrade PAS : la sonde `chromadb` porte déjà le fait qu'on n'a
    # pas pu lire, et le publier deux fois ferait croire à deux pannes. Publier
    # « degraded » sur une sonde qui n'est pas revenue reviendrait aussi à faire
    # dire à l'agent « ça diverge » quand il n'en sait rien — la distinction que
    # `services_unknown` tient déjà par ailleurs.
    status = (
        "ok"
        if all(essentiels.values()) and not concordance_refusee and not peripherique_refuse
        else "degraded"
    )
    # Hors du plafond, et borné : `sessions.stats()` et `sessions.durable()` ne
    # lisent que des compteurs en mémoire et un réglage — aucune entrée-sortie,
    # donc rien qui puisse attendre. `stats` absorbe ses propres échecs et rend
    # des zéros : une sonde qui tombe parce qu'une base d'observation est
    # illisible serait une régression, pas une mesure. Le compteur `failures` dit
    # alors ce qui s'est passé.
    chemin, vivantes, purgees, echecs = sessions.stats()
    # HORS DU PLAFOND, ET POUR LA MÊME RAISON QUE `sessions.stats()` juste
    # au-dessus : trois lectures de `os.environ`, aucune entrée-sortie, rien qui
    # puisse attendre. La passer sous le plafond lui ferait partager le sort des
    # sondes réseau — et une identité de code qui devient `null` parce qu'un
    # store ne répond pas serait une régression, pas une mesure.
    #
    # ET ELLE NE DÉGRADE PAS `status`, ce qui est un arbitrage et non un oubli.
    # Une image anonyme est un défaut de PROCÉDURE DE DÉPLOIEMENT, pas une panne
    # du service : elle répond, elle sert, et la faire passer `degraded`
    # ferait passer `agent-api` `unhealthy` au healthcheck — donc empêcherait
    # `frontend` de lever au démarrage à froid, pour une image qui fonctionne.
    # C'est le raisonnement du §1.27, appliqué au cas inverse. Ce qui doit
    # rougir sur une image anonyme, c'est la CAMPAGNE qui prétend la comparer,
    # et c'est à elle de lire ce champ.
    code_servi = identite_du_code()
    return HealthResponse(
        status=status,
        # Le modèle DEMANDÉ. Le CHAMP portait le nom de l'ancien moteur jusqu'au
        # lot 28 et il est renommé avec le réglage qu'il publie — voir `schemas.py`,
        # `HealthResponse`, qui porte ce que la rupture coûte.
        llm_model=dialecte_courant().modele,
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
        embedding_model=embedding,
        torch_device=peripherique or _peripherique_inconnu(),
        moteur_llm=moteur,
        code_servi=code_servi,
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


def _sections_soumises(
    budget: list[PromptFit], candidates: list[SectionContext]
) -> list[SectionContext]:
    """Les sections réellement parties au LLM, pour la génération directe.

    Cet endpoint ne passe pas par le graphe : personne ne renseignerait
    `submitted_contexts` à sa place, d'où le rappel `on_fit` posé au point
    d'appel.

    Un budget vide **ferme** la résolution au lieu de retomber sur les
    candidates, et c'est un choix. `generate_stream` appelle `on_fit` avant sa
    requête HTTP, donc ce cas suppose déjà que le câblage a été défait ; le jour
    où il le sera, une réponse sans citations et un WARNING se voient, alors
    qu'une citation fausse ne se voit pas — c'est le critère de ce dépôt, et
    `node_postprocess` tranche pareil pour le même motif.
    """
    if budget:
        return budget[-1].contexts
    logger.warning(
        "Génération directe : aucun budget rendu par on_fit pour %d candidate(s) — "
        "aucune citation ne sera résolue, faute de savoir ce qui a été soumis.",
        len(candidates),
    )
    return []


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
            # Le budget tel qu'il a été appliqué. Cet endpoint ne passe pas par le
            # graphe, donc rien ne le renseignerait à sa place : sans ce rappel,
            # les citations se résolvaient sur les CANDIDATES, y compris celles
            # que la fenêtre avait écartées.
            budget: list[PromptFit] = []
            async for token in generate_stream(
                req.question,
                contexts,
                req.chat_history[-MAX_HISTORY_MESSAGES:],
                on_fit=budget.append,
            ):
                morceaux.append(token)
                yield {"data": json.dumps({"token": token})}
            reponse = "".join(morceaux)
            soumises = _sections_soumises(budget, contexts)
            citations, images = resolve_citations(reponse, soumises, [])
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
            # La capture reçoit les CANDIDATES, et ce n'est pas un oubli : le
            # registre porte déjà une entrée sur `submitted_element_ids`, qui
            # nomme « soumises » des sections écartées sur les trois routes. La
            # corriger ici seulement donnerait à une même colonne deux sens
            # selon la route empruntée, ce qui est pire qu'un nom trompeur
            # uniforme. Cf. §2, « La capture d'usage nomme « soumises »… ».
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
    budget: list[PromptFit] = []
    response = await generate(
        req.question,
        contexts,
        req.chat_history[-MAX_HISTORY_MESSAGES:],
        on_fit=budget.append,
    )
    soumises = _sections_soumises(budget, contexts)
    citations, images = resolve_citations(response, soumises, [])
    # Les candidates, pour la raison écrite au chemin diffusé ci-dessus.
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

    Les champs restent à `None` quand le serveur ne les a pas rendus. Ce n'est pas
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
        # CE FLUX NE PROMET AUCUNE BORNE DE SOURCES, ET C'EST POURQUOI IL N'EN
        # PORTE PAS. Son nombre de contextes est la sélection que le client
        # poste à /chat/resume, que `node_reconstruct_context` reconstruit
        # SANS l'écrêter : il ne passe par `ranking[:max_sources]` que si la
        # sélection revient vide. Aucun champ de `ChatRequest` ni de
        # `SourceSelectionRequest` ne déclare donc de plafond, et il n'y a rien
        # à y rendre honnête — contrairement à `AnswerRequest.max_sources`, qui
        # en annonçait un que le reranker ne tenait pas. `None` ici laisse
        # AUTO_SELECT_TOP_K gouverner le seul cas où le découpage s'applique.
        # Le jour où un champ de borne apparaîtrait sur cette voie,
        # `tests/unit/test_borne_des_sources.py` le trouve par balayage et exige
        # qu'il porte la borne de la chaîne.
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

    # ─── La concordance, vérifiée AVANT d'ouvrir le flux ─────────────────────
    #
    # CETTE ROUTE CHERCHE, ET APRÈS LE PREMIER OCTET. `src/agent/graph.py` porte
    # `add_conditional_edges("postprocess", should_search_more, {True:
    # "retrieve", False: END})` : le graphe reboucle vers `retrieve` après
    # `generate`, et `astream` tourne DANS le `stream_generator` ci-dessous,
    # rendu dans un `EventSourceResponse`. Le garde de `_dense_search` était donc
    # atteint alors que la réponse avait commencé — et une levée survenue là
    # n'atteint JAMAIS `_refus_modele_embedding` : Starlette rend « Caught
    # handled exception, but response already started ». Mesuré : pas de 503,
    # pas de motif dans le corps, et pas même la ligne ERROR. Le flux mourait
    # tronqué et muet, pendant que quatre documents affirmaient « toute
    # recherche est refusée en 503 ». Site canonique :
    # `documentation/axes_amelioration.md` §4.20, trouvaille N1.
    #
    # LA LECTURE EST BORNÉE ET LE FIL EST GARDÉ, et l'histoire de cette ligne
    # est la trouvaille bloquante de l'audit de la réparation — §4.23, B-1. Elle
    # a d'abord été écrite `await asyncio.to_thread(verifier_modele_embedding)`,
    # NUE : synchrone dans un fil, sans plafond et sans garde. `mesuré` avec une
    # collection qui PEND — un `threading.Event` jamais posé, aucun accès réel à
    # ChromaDB : ce motif reste bloqué après 6 s même avec un `wait_for` que le
    # site n'avait pas, la route passe de 0,030 s à AUCUNE réponse sur une
    # requête qui ne cherche pas, et le fil non-démon du réservoir asyncio
    # empêche `asyncio.run` de rendre. `chromadb 1.5.9` n'a aucun délai par
    # défaut ; 26 requêtes bloquées épuisent le réservoir.
    #
    # CE QUI REND CETTE LIGNE INSTRUCTIVE : le fichier avait DÉJÀ écrit le
    # remède, et l'absorption ci-dessous nommait l'objectif que l'appel
    # n'atteignait pas. Elle protège d'un ChromaDB qui LÈVE ; elle ne pouvait
    # rien contre un ChromaDB qui PEND — la panne la plus banale d'un store
    # réseau. *La dépendance était sur l'appel, pas sur l'exception.*
    #
    # `_concordance_avant_le_flux()` emploie donc ce que ce fichier possédait :
    # le plafond `_PLAFOND_SONDES_S`, le garde « en vol », et
    # `to_thread.run_sync(…, abandon_on_cancel=True)` — la primitive ANNULABLE,
    # dont l'annulation rend la main à la BOUCLE sans attendre le fil. C'est là
    # toute la différence avec `asyncio.to_thread`, et c'est tout ce qu'elle
    # est : ce site a écrit un temps que le fil de réservoir d'anyio « est démon
    # et ne retient plus l'interpréteur », et c'est FAUX. `mesuré` le 7 septembre
    # 2026 sur anyio 4.15.1 : le fil lâché porte `nom='AnyIO worker thread'` et
    # `daemon=False`, et un processus qui sort en le laissant bloqué est tué par
    # son échéance — `rc=124`, l'interpréteur est RETENU. Le test de ce garde
    # l'écrivait déjà juste, dans un `finally` :
    # `tests/unit/test_garde_modele_embedding.py`.
    #
    # CONSÉQUENCE, à dire plutôt qu'à taire : un `docker stop` sur une API
    # portant un fil lâché n'aboutit pas à la demande — il ira au bout de sa
    # grâce, puis le conteneur sera TUÉ. Ce que la primitive achète est la
    # disponibilité de la route, pas la propreté de l'arrêt.
    #
    # Les deux décisions que ce choix demandait — la sémantique du dépassement,
    # et le drapeau — sont argumentées dans son docstring.
    #
    # `/chat/simple` ne reçoit pas cette vérification, et c'est mesuré, pas
    # supposé : il ne passe pas par le graphe et ne cherche jamais.
    try:
        await _concordance_avant_le_flux()
    except EmbeddingModelMismatchError:
        # Avant le premier octet, donc le gestionnaire de l'application rend
        # bien 503 avec les deux noms de modèles dans le corps.
        raise
    except Exception:
        # ABSORPTION LARGE, ET VOICI SA JUSTIFICATION. Ce qui passe ici est une
        # estampille ILLISIBLE — ChromaDB muet ou injoignable — et non une
        # divergence : le client chromadb remonte ce cas par des erreurs de
        # transport, de sérialisation et de schéma sans ancêtre commun (cf.
        # `_taille_collection`). Refuser dessus ferait dépendre de ChromaDB une
        # route qui, la plupart du temps, ne cherche PAS : elle reconstruit un
        # contexte depuis Nebula et génère. On transformerait une requête qui
        # aboutit en 500. Le garde reste donc en place à l'intérieur du flux,
        # fail-closed, et la seule chose qu'on perd ici est l'anticipation.
        # L'absorption n'est pas muette.
        #
        # ET CE QUI N'ARRIVE PLUS JUSQU'ICI : le DÉPASSEMENT du plafond. Il est
        # traité au même titre que l'illisible — même perte, même garde restant
        # en place — mais `_concordance_avant_le_flux()` rend alors sans lever,
        # après avoir journalisé sa propre ligne. Deux causes, un seul sort, deux
        # lignes distinctes : l'exploitant doit pouvoir dire si son store a
        # répondu par une panne ou n'a pas répondu du tout.
        logger.warning(
            "/chat/resume : estampille du modèle d'embedding illisible avant "
            "l'ouverture du flux ; la concordance sera revérifiée si le graphe "
            "reboucle vers une recherche.",
            exc_info=True,
        )

    if req.stream:
        async def stream_generator() -> AsyncIterator[dict[str, Any]]:
            final_state: dict[str, Any] = {}
            try:
                # "custom" : tokens émis par node_generate ; "values" : état
                # complet après chaque nœud (le dernier reçu = état final).
                async for mode, chunk in interactive_graph().astream(
                    None, config, stream_mode=["custom", "values"]
                ):
                    if mode == "custom":
                        yield {"data": json.dumps(chunk)}
                    elif mode == "values" and isinstance(chunk, dict):
                        final_state = chunk
            except EmbeddingModelMismatchError as exc:
                # LE RÉSIDU DE N1, et il est tracé plutôt que caché. La
                # vérification ci-dessus ne peut pas couvrir une divergence
                # apparue APRÈS : `reset_connection()` tourne toutes les 20 s
                # depuis le `ping()` du healthcheck, et une réingestion peut
                # passer entre la vérification et le rebouclage. Le code HTTP est
                # déjà parti en 200 — aucune correction ne le reprend, et le flux
                # meurt tronqué, ce qui est fail-closed. Ce qui ne doit PAS
                # arriver est qu'il meure MUET : le gestionnaire d'exception de
                # l'application n'étant jamais appelé après le premier octet,
                # c'est ICI le seul endroit où l'exploitant peut l'apprendre.
                # Garde : tests/unit/test_garde_modele_embedding.py,
                # `test_une_divergence_apparue_en_vol_laisse_une_ligne_error`.
                # Le motif est sur la LIGNE, et pas seulement dans la pile :
                # c'est ce que fait déjà `_refus_modele_embedding`, et un
                # exploitant qui grep le nom d'un modèle doit trouver les deux
                # chemins de refus, pas un seul.
                logger.exception(
                    "Flux /chat/resume interrompu, le modèle d'embedding a "
                    "divergé pendant la réponse — %s Le flux est tronqué et la "
                    "réponse partielle n'a pas été enregistrée.",
                    exc,
                )
                raise
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
