import logging
import math
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from functools import lru_cache, update_wrapper
from typing import Any, Literal, NamedTuple, cast

import chromadb
import torch
from sentence_transformers import CrossEncoder, SentenceTransformer

from src.agent.chronometrie import Chrono
from src.agent.lexical import LexicalIndex, chunk_from_record, fuse
from src.agent.settings import settings
from src.api.schemas import ChunkResult, EmbeddingModelHealth, SourceGroup, TorchDeviceHealth

logger = logging.getLogger(__name__)

# Taille des lots de lecture pour la construction de l'index lexical.
_LEXICAL_PAGE = 2000
# Recouvrement maximal cherché entre deux fenêtres consécutives d'un même
# élément. L'ingestion utilise 150 caractères ; la marge couvre un réglage
# différent sans rendre la recherche coûteuse.
_MAX_OVERLAP = 400


# ─── LA BORNE DE CONCURRENCE DES DEUX ÉTAGES TORCH ───────────────────────────
#
# Le motif complet est à `settings.torch_max_concurrency`. En deux phrases : sans
# borne, l'empreinte de cet agent sur la carte croît avec la concurrence et
# **ne redescend jamais** (l'allocateur de torch ne rend rien), donc le chiffre
# de réservation rendu au voisin de carte ne vaut rien.
#
# UN SÉMAPHORE ET NON UNE BORNE AU NIVEAU DU SERVEUR, et c'est un choix pesé.
# `uvicorn --limit-concurrency` bornerait TOUTES les requêtes, y compris celles
# qui ne touchent pas torch — `/health`, `/context`, `/feedback` — et rendrait
# **503** au-delà, ce qui ferait passer le conteneur pour saturé alors que seule
# la carte l'est. Le sémaphore borne ce qui coûte, là où ça coûte.
#
# CE QUE CE MOTIF AFFIRMAIT ET QUI ÉTAIT FAUX, jusqu'à B-3 de l'audit du
# 14 septembre 2026 : « et laisse la sonde de santé répondre ». Il ne la laissait
# pas répondre. Bloquer ici bloque un fil du réservoir d'AnyIO — celui que
# Starlette emploie pour les endpoints `def`, ET celui où `_sonder` lançait ses
# sondes. Une requête qui attend son permis ne rend pas son fil : la borne
# convertissait une saturation de carte en saturation du réservoir des sondes, et
# `/health` publiait alors `degraded` avec trois stores SAINS déclarés `false`.
# `mesuré` par l'audit sur l'application réelle : 13 appels sur 197 à 3,00 s
# pile ; borne désarmée, 1 sur 29.
#
# CE QUI REND LA PHRASE VRAIE AUJOURD'HUI, et ce n'est pas ce sémaphore : les
# sondes de `/health` ont leur PROPRE limiteur de fils
# (`src/api/main.py`, `_reservoir_des_sondes`), indépendant de celui des
# endpoints. La propriété est gardée, aux deux niveaux, par
# `tests/unit/test_health_parallele.py::…_quand_le_reservoir_des_recherches_est_plein`
# — et elle rougit si ce limiteur disparaît. Une phrase ne rougit pas ; ces deux
# tests-là, si.
#
# UN SEUL SÉMAPHORE POUR LES DEUX ÉTAGES : la mémoire est un seul pool. Une
# requête traverse l'encodage puis le reclassement l'un APRÈS l'autre, donc un
# sémaphore partagé borne bien le nombre de requêtes présentes dans un étage
# torch à un instant donné, qui est la grandeur dont l'empreinte dépend.
_borne_verrou = threading.Lock()
_borne: threading.Semaphore | None = None
_borne_taille: int | None = None


def rearmer_la_borne_des_etages_torch() -> None:
    """Reconstruit le sémaphore sur la valeur COURANTE du réglage.

    Existe pour les tests, et pour eux seuls : en service le réglage ne bouge pas
    après le démarrage. Un réarmement en vol perdrait les permis détenus, et
    c'est pourquoi il n'est pas fait automatiquement à chaque lecture.
    """
    global _borne, _borne_taille
    with _borne_verrou:
        _borne = threading.Semaphore(settings.torch_max_concurrency)
        _borne_taille = settings.torch_max_concurrency


def _semaphore() -> threading.Semaphore:
    global _borne, _borne_taille
    with _borne_verrou:
        if _borne is None or _borne_taille != settings.torch_max_concurrency:
            _borne = threading.Semaphore(settings.torch_max_concurrency)
            _borne_taille = settings.torch_max_concurrency
        return _borne


@contextmanager
def borne_des_etages_torch() -> Iterator[None]:
    """Ne laisse entrer que `TORCH_MAX_CONCURRENCY` requêtes dans un étage torch.

    Les deux endpoints qui appellent sont des `def` et non des `async def` :
    FastAPI les exécute dans le threadpool d'AnyIO, donc bloquer ici bloque un
    fil de ce réservoir et **jamais la boucle d'événements**.

    CE QUE CELA NE SUFFIT PAS À GARANTIR, et c'est B-3 : que `/health` réponde.
    La boucle reste libre, mais les SONDES de `/health` sont synchrones et
    passaient par le même réservoir — 40 jetons. Des requêtes qui attendent ici
    l'affamaient, et la route publiait `false` sur des dépendances saines. Ce
    sont les sondes qui ont été déplacées, pas cette attente : voir
    `_reservoir_des_sondes` dans `src/api/main.py`.
    """
    borne = _semaphore()
    borne.acquire()
    try:
        yield
    finally:
        borne.release()


# ─── LA MÉMOIRE DES LEVÉES AU CHARGEMENT ─────────────────────────────────────
#
# CE QU'ELLE FERME, ET LE CONTRÔLE STATIQUE NE LE PEUT PAS.
# `peripherique_hors_d_atteinte` répond à « le périphérique demandé existe-t-il
# d'ici », sans rien charger. Elle ne répond pas à « le chargement va-t-il
# aboutir », et `/health` ne peut pas le lui demander : une route de santé qui
# construit deux modèles n'est plus une sonde.
#
# Or la panne qui VIENT n'est pas celle d'un périphérique absent. `mesuré` le
# 14 septembre 2026 à 09:08 UTC, `nvidia-smi --query-compute-apps` croisé avec
# `docker inspect -f '{{.State.Pid}}' rag-agent-api` : **vLLM tient déjà
# 14 264 Mio** sur la L4, Ollama 4 584, cet agent 1 294, sur 23 034 — il reste
# **2 892 Mio**. Un agent qui redémarrerait et redemanderait ses 1,29 Go
# trouverait `cuda_available: true`, un ordinal valide, et lèverait quand même,
# sur la mémoire. Le contrôle statique ne verrait rien.
#
# UNE LEVÉE EST UN FAIT DÉJÀ PRODUIT : la relire ne charge rien et ne coûte rien.
# Elle arrive APRÈS la première recherche là où le contrôle statique arrive
# avant, et elle couvre TOUTE cause — mémoire, modèle absent du cache, droits
# refusés. Les deux moitiés sont complémentaires ; aucune ne rend l'autre
# inutile. C'est la seconde forme que l'audit du 14 septembre 2026 nommait :
# *« ou une levée mémorisée au dernier chargement »*.
#
# UN DICTIONNAIRE ET NON UNE CHAÎNE, et le motif est une erreur évitée : avec une
# chaîne unique, un rechargement RÉUSSI de l'embedder effacerait la levée encore
# vraie du reranker. Chaque modèle porte la sienne, et ne l'efface que pour lui.
_levees_au_chargement: dict[str, str] = {}


def _memoriser_la_levee(modele: str, exc: BaseException) -> None:
    """Retient POURQUOI le chargement de `modele` a échoué, pour `/health`."""
    _levees_au_chargement[modele] = f"{type(exc).__name__}: {exc}"


def _oublier_la_levee(modele: str) -> None:
    """Un chargement RÉUSSI efface la sienne, et c'est la seconde direction.

    Sans elle, un exploitant qui corrige la cause — il libère la carte, il rend
    les droits — verrait `degraded` pour toujours, sans redémarrage possible :
    le mensonge symétrique de celui que ce garde ferme.
    """
    _levees_au_chargement.pop(modele, None)


def levees_au_chargement() -> dict[str, str]:
    """Les levées retenues, copiées — l'appelant ne mute pas l'état du module."""
    return dict(_levees_au_chargement)


def oublier_les_levees_au_chargement() -> None:
    """Repart de zéro. Existe pour les tests, et pour eux seuls."""
    _levees_au_chargement.clear()


# ─── Singletons chargés une seule fois au démarrage ──────────────────────────
#
# POURQUOI PAS `lru_cache(maxsize=1)` SUR LES DEUX MODÈLES, et c'est B-1 de
# l'audit du 14 septembre 2026. **`lru_cache` ne sérialise pas les appels
# concurrents qui manquent le cache** : en CPython son verrou n'est tenu que
# pour la mise à jour du dictionnaire, jamais pendant l'exécution de la fonction
# enveloppée. `K` fils qui manquent le cache ensemble entrent donc TOUS dans le
# corps et construisent `K` modèles EN MÊME TEMPS, chacun plaçant sa copie des
# poids sur la carte. `mesuré` sur le module réel : **8** constructions
# simultanées pour 8 fils à froid.
#
# ET LES `K−1` COPIES PERDANTES NE RENDENT RIEN. Elles sont bien collectées par
# Python, mais **l'allocateur de torch ne rend pas la mémoire au pilote** — ce
# que ce module écrit lui-même à `_pic_memoire_reservee_mio`. Le pic est acquis
# pour la vie du processus, et c'est lui que le voisin de carte doit réserver.
#
# CE QUE CE REMPLACEMENT GARDE DE `lru_cache`, parce que le module et les tests
# le lisent : `cache_clear()` et `cache_info().currsize`. Le reste de la forme
# (`hits`/`misses`/`maxsize`) est tenu pour que la substitution soit complète et
# qu'un lecteur n'ait pas à vérifier laquelle des deux il a sous les yeux.


class _InfoDuSingleton(NamedTuple):
    """La forme de `lru_cache.cache_info()`, à l'identique."""

    hits: int
    misses: int
    maxsize: int | None
    currsize: int


class _SingletonVerrouille[T]:
    """Un chargement coûteux mémoïsé, dont les manques concurrents sont SÉRIALISÉS.

    LA DOUBLE VÉRIFICATION EST LE CŒUR, et elle n'est pas décorative : sans la
    seconde lecture sous verrou, les `K` fils qui ont manqué le cache
    construiraient chacun leur tour — sérialisés, mais `K` constructions quand
    même, donc `K` empreintes sur une carte qui ne rend rien. Ce qu'il faut
    fermer n'est pas « deux constructions en même temps », c'est « plus d'une
    construction ».

    La première lecture est faite HORS verrou, et c'est ce qui rend le cas
    passant gratuit : une fois chargé, servir le modèle ne prend aucun verrou.
    L'affectation d'un attribut est atomique sous le GIL, et l'ordre choisi
    (`_valeur` puis `_charge`) fait qu'un lecteur qui voit `_charge` vrai voit
    forcément la valeur.
    """

    def __init__(self, charger: Callable[[], T]) -> None:
        self._charger = charger
        self._verrou = threading.Lock()
        self._valeur: T | None = None
        self._charge = False
        self._hits = 0
        self._misses = 0
        update_wrapper(self, charger)

    def __call__(self) -> T:
        if self._charge:
            self._hits += 1
            return cast("T", self._valeur)
        with self._verrou:
            # SECONDE LECTURE : un autre fil a pu charger pendant qu'on attendait
            # le verrou. Sans elle, on reconstruirait — voir le docstring.
            if self._charge:
                self._hits += 1
                return cast("T", self._valeur)
            self._misses += 1
            valeur = self._charger()
            self._valeur = valeur
            self._charge = True
            return valeur

    def cache_clear(self) -> None:
        """Repart de zéro. Même nom que `lru_cache` : les tests l'appellent ainsi."""
        with self._verrou:
            self._valeur = None
            self._charge = False
            self._hits = 0
            self._misses = 0

    def cache_info(self) -> _InfoDuSingleton:
        """`currsize` dit « un modèle est chargé » SANS rien déclencher.

        C'est ce que lisent `_peripherique_si_charge` et
        `_pic_memoire_reservee_mio` : `/health` est appelé toutes les 20 s et ne
        doit jamais payer un chargement pour répondre.
        """
        return _InfoDuSingleton(self._hits, self._misses, 1, 1 if self._charge else 0)


@_SingletonVerrouille
def _get_embedding_model() -> SentenceTransformer:
    logger.info(
        "Chargement du modèle d'embedding : %s, périphérique demandé « %s »",
        settings.embedding_model_name,
        settings.torch_device,
    )
    try:
        model: SentenceTransformer = SentenceTransformer(
            settings.embedding_model_name, device=settings.torch_device
        )
    except Exception as exc:
        # ABSORPTION NULLE — la levée est RELANCÉE à la ligne suivante. Ce `except`
        # ne rattrape rien : il RETIENT, pour que `/health` sache dire pourquoi
        # chaque recherche rend 500. Le comportement du site d'appel est inchangé,
        # et c'est délibéré : il n'y a AUCUN repli vers CPU dans ce module, et en
        # introduire un ici changerait silencieusement le périphérique — c'est
        # exactement ce que le lot 12 existe pour rendre visible.
        # `Exception` et non une liste : torch lève `RuntimeError`,
        # `AcceleratorError`, `OSError` et `PermissionError` selon la cause, sans
        # ancêtre commun, et toutes disent ici la même chose — le modèle n'est pas
        # chargé. Une liste close périmerait à la prochaine version de torch.
        _memoriser_la_levee("embedding", exc)
        raise
    _oublier_la_levee("embedding")
    # APRÈS le chargement, et ce n'est pas la répétition de la ligne du dessus :
    # celle-là dit ce qu'on a DEMANDÉ, celle-ci ce que torch a réellement posé.
    # Les deux diffèrent dès que le réglage nomme un périphérique que le build
    # ne sait pas servir, et c'est le seul moment où la différence est visible
    # dans un journal — `/health` la publie ensuite en continu.
    logger.info(
        "Modèle d'embedding chargé sur le périphérique « %s »",
        getattr(model, "device", "inconnu"),
    )
    return model


# ─── Le garde du reranker, et pourquoi il SIGNALE au lieu de refuser ─────────
#
# LA PANNE. Le cross-encoder doit parler les mêmes langues que l'embedder, sinon
# il défait son travail. Un reranker ANGLAIS sur les **41 questions translingues
# sur 138** du jeu de référence — soit **30 %** — coûte **−2,5 points de
# rappel@10** (97,6 % → 95,1 %). Rien ne le disait : `rerank_model` avait TROIS
# usages et AUCUN contrôle.
#
# CES CHIFFRES SONT CITÉS DE L'AUDIT DU 8 SEPTEMBRE 2026, site canonique
# `documentation/axes_amelioration.md` §4.31, et NON remesurés par le lot qui
# écrit ce garde : les rejouer demande la pile démarrée et une campagne
# complète. Ce que ce lot a mesuré lui-même est le chevauchement de vocabulaire
# ci-dessous, qui est ce qui décide de la FORME du garde.
#
# CE QU'ON NE PEUT PAS COPIER DU LOT 3, ET C'EST LA PREMIÈRE DÉCISION. Le
# modèle d'embedding a une ESTAMPILLE : le pipeline inscrit `embedding_model`
# dans les métadonnées de la collection, et `verifier_modele_embedding()`
# confronte le réglage à elle — une comparaison de noms, EXACTE. Le reranker n'a
# aucune estampille et n'en aura jamais : il ne produit **rien de persistant**,
# donc rien ne peut dire quel reranker « a produit » quoi. Il n'y a pas de fait
# extérieur auquel confronter le réglage.
#
# CONTRE QUOI ON CONFRONTE DONC : une PROPRIÉTÉ DU MODÈLE LUI-MÊME, la taille de
# son vocabulaire, doublée d'un registre des modèles réellement mesurés sur ce
# corpus.
#
# ET LA MESURE QUI BORNE CETTE PROPRIÉTÉ, parce qu'elle interdit d'en faire un
# classifieur. `mesuré` le 8 septembre 2026 par lecture des seuls `config.json`
# (60 Ko, aucun poids téléchargé) :
#
#     modèle                       type            vocab_size
#     ms-marco (anglais)           bert                30 522
#     RoBERTa (anglais)            roberta             50 265
#     mBERT (MULTILINGUE)          bert               119 547
#     DeBERTa-v3 (ANGLAIS)         deberta-v2         128 100
#     le multilingue en service    xlm-roberta        250 002
#
# **Les deux classes SE CHEVAUCHENT** : mBERT, multilingue, a un vocabulaire
# PLUS PETIT que DeBERTa-v3, anglais. Aucun seuil ne les sépare donc en général,
# et ce garde ne prétend pas le faire. Le plancher ci-dessous discrimine les
# FAMILLES EN JEU pour un reranker — les cross-encoders anglais usuels sont
# bâtis sur BERT/MiniLM et plafonnent vers 30 000 — et pas le concept
# « multilingue ». C'est un INDICE, jamais un verdict.
#
# **ET C'EST CE CHEVAUCHEMENT QUI TRANCHE LA SECONDE DÉCISION.** On SIGNALE, on
# ne refuse pas, et pour deux raisons qui se cumulent :
#
# - *la proportion*. Le lot 3 refuse en 503 parce qu'un embedding qui ne
#   correspond pas rend des passages PLAUSIBLES ET FAUX : l'index est
#   inexploitable, et ne rien servir vaut mieux que servir faux. Un reranker
#   anglais ne rend pas des passages faux — il en rend MOINS DE BONS, à
#   −2,5 points. Refuser ferait passer la disponibilité de 100 % à 0 % pour
#   épargner 2,5 points de rappel : l'utilisateur n'aurait plus une réponse un
#   peu moins bien classée, il n'en aurait AUCUNE. C'est pire sur tous les axes ;
# - *la nature de la preuve*. Le lot 3 compare deux noms à une estampille : le
#   refus s'appuie sur un fait. Ici la propriété est un indice dont le
#   chevauchement mesuré ci-dessus prouve qu'il se trompe dans les deux sens. Un
#   503 sur un indice est un garde qu'on arrache au premier faux positif — et le
#   503 du lot 3, lui, a déjà coûté trois réparations et quatre bloquantes en
#   s'appuyant sur un fait EXACT.
#
# CE QUE CE GARDE NE COUVRE PAS, et la liste est le prix des deux décisions :
#
# - un modèle anglais à GROS vocabulaire passe en silence — DeBERTa-v3 (128 100)
#   est au-dessus du plancher. Faux vert assumé : un faux vert laisse l'état
#   d'aujourd'hui, un faux rouge sur le modèle en service apprendrait à
#   l'exploitant à ignorer le journal ;
# - il ne dit rien de la QUALITÉ du reranker, seulement de sa famille
#   linguistique. Un multilingue mauvais passe ;
# - il ne peut pas savoir dans quelle LANGUE sont les questions réellement
#   posées. Les −2,5 points valent pour ce jeu de référence et ses 30 % de
#   translingue, pas pour un usage tout-français ;
# - il parle au JOURNAL, une fois par processus. Il ne dégrade pas `/health` et
#   ne rejaillit pas dans la réponse ; ce qui reste ouvert est consigné dans le
#   rapport du lot.

# Les rerankers MESURÉS sur ce corpus et trouvés adéquats. Le registre ne porte
# QUE des modèles retenus : y inscrire un modèle écarté serait écrire son nom en
# clair dans un dépôt PUBLIC, et le plancher de vocabulaire suffit à le voir.
#
# **SES VALEURS SONT LUES, et c'est une correction du 9 septembre 2026.** Elles
# ne l'étaient pas : les trois usages ne parcouraient que les clés, et `mesuré`,
# les vider toutes laissait 643 tests verts — de la documentation déguisée en
# donnée. Le choix entre « en faire un ensemble » et « lire la valeur » est
# tranché par ce que le message `info` dit à l'exploitant : *« ce modèle n'a PAS
# été mesuré »*, sans jamais lui dire ce qui A été mesuré sur celui du registre,
# alors que la réponse est écrite deux lignes plus haut. Un garde qui retient
# l'information dont il constate l'absence est un garde à moitié écrit.
_RERANKERS_MESURES: dict[str, str] = {
    "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1": (
        "97,6 % de rappel@10 sur la campagne de référence du 8 septembre 2026"
    ),
}


def _registre_avec_ses_mesures() -> str:
    """Le registre tel qu'un exploitant a besoin de le lire : nom ET mesure.

    Vider les valeurs du registre fait rougir les tests qui lisent ce rendu —
    c'est ce qui les maintient vivantes.
    """
    return ", ".join(f"{nom} ({_RERANKERS_MESURES[nom]})" for nom in sorted(_RERANKERS_MESURES))

# Le plancher, et il est MESURÉ, non choisi. **LA DÉFINITION DE LA MARGE EST
# ÉCRITE, parce que les deux lectures donnent deux chiffres justes.** mBERT
# (119 547) est le plus petit vocabulaire multilingue relevé, et il est **19,5 %
# au-dessus de ce plancher — marge rapportée AU PLANCHER**. Rapportée à mBERT,
# la même marge vaut 16,4 %, et la formulation « 19,5 % sous mBERT » qui
# figurait ici se lisait spontanément comme la seconde. Troisième occurrence
# dans ce chantier de « deux écritures justes sous des définitions
# différentes » : la définition coûte deux mots, l'ambiguïté coûte un audit.
#
# Le plancher est par ailleurs 3,28 fois au-dessus des cross-encoders anglais
# usuels (30 522).
_VOCABULAIRE_MULTILINGUE_PLANCHER = 100_000


# Les deux SEULS niveaux que ce garde sait rendre, et le type le borne.
#
# **POURQUOI UN TYPE ET PAS UNE CONVENTION.** `mesuré` le 9 septembre 2026 :
# avec un `str` nu, ajouter un troisième niveau — « critical », disons — passait
# mypy et ruff en `rc=0` avec 643 tests verts, et le ternaire de
# `_get_rerank_model` le journalisait en **`INFO`**. La dégradation allait donc
# vers le BAS : un garde qui RÉTROGRADE une alarme est pire qu'un garde qui la
# promeut, puisqu'il fait disparaître du journal ce que l'auteur du niveau
# voulait rendre le plus visible. Le `Literal` transforme cette panne silencieuse
# en rouge de `make lint`, au site même où le niveau est écrit.
NiveauDuVerdict = Literal["info", "warning"]


def verdict_langue_du_reranker(
    nom: str, vocabulaire: int | None
) -> tuple[NiveauDuVerdict, str] | None:
    """Ce qu'il y a à dire du reranker configuré. `None` s'il n'y a rien à dire.

    Rend `(niveau, message)`, le niveau étant celui du journal — et les DEUX
    niveaux sont nécessaires, parce que les deux faits sont différents. C'est la
    même discipline que `etat_index_lexical` : « je ne sais pas » ne se replie ni
    sur « c'est bon » ni sur « c'est cassé ».

    - un modèle du registre : rien à dire, il a été mesuré ;
    - un vocabulaire sous le plancher : `warning`. C'est le défaut que ce garde
      existe pour rendre bruyant ;
    - un vocabulaire illisible : `warning` aussi, parce qu'on ne peut pas
      ÉCARTER le cas précédent. Le silence est le seul choix interdit ici ;
    - un modèle hors registre au vocabulaire ample : `info`. Ce n'est pas un
      défaut, c'est une absence de mesure, et l'annoncer comme un défaut
      apprendrait à ignorer le journal.

    Fonction PURE, et c'est délibéré : elle ne charge aucun modèle et ne lit
    aucun réglage, donc ses quatre branches s'éprouvent sans réseau et sans
    poids. L'extraction de la propriété vit chez l'appelant, où elle est
    défensive.
    """
    if nom in _RERANKERS_MESURES:
        return None
    if vocabulaire is None:
        return (
            "warning",
            f"Reranker '{nom}' : impossible de lire la taille de son vocabulaire, "
            f"donc impossible d'écarter qu'il soit monolingue. Un reranker anglais "
            f"coûte 2,5 points de rappel@10 sur les 30 % de questions translingues "
            f"du jeu de référence, en silence. Registre des modèles mesurés : "
            f"{_registre_avec_ses_mesures()}.",
        )
    if vocabulaire < _VOCABULAIRE_MULTILINGUE_PLANCHER:
        return (
            "warning",
            f"Reranker '{nom}' : vocabulaire de {vocabulaire} entrées, sous le "
            f"plancher de {_VOCABULAIRE_MULTILINGUE_PLANCHER} — c'est la signature "
            f"d'un cross-encoder MONOLINGUE. L'embedder de ce projet est "
            f"multilingue, et un reranker anglais défait son travail : "
            f"2,5 points de rappel@10 de moins sur les 30 % de questions "
            f"translingues du jeu de référence, sans aucune erreur visible. "
            # Les noms SEULS ici, et c'est délibéré : cette ligne est une
            # instruction que l'exploitant recopie dans son `.env`, pas un
            # relevé. La mesure de chaque modèle est donnée par les deux autres
            # messages, qui informent au lieu d'instruire.
            f"Réparation : RERANK_MODEL sur un modèle du registre "
            f"{sorted(_RERANKERS_MESURES)}, ou mesurer celui-ci par "
            f"`make eval` avant de le garder.",
        )
    return (
        "info",
        f"Reranker '{nom}' : vocabulaire de {vocabulaire} entrées, compatible avec "
        f"un modèle multilingue, mais ce modèle n'a PAS été mesuré sur ce corpus. "
        f"Ce n'est pas un défaut, c'est une absence de mesure — le rappel@10 de ce "
        f"réglage est inconnu. Ce qui A été mesuré : {_registre_avec_ses_mesures()}.",
    )


def _vocabulaire_du_reranker(model: CrossEncoder) -> int | None:
    """La taille du vocabulaire du modèle CHARGÉ, `None` si elle est illisible.

    Lue sur l'objet déjà en mémoire : aucun aller-retour réseau, aucune seconde
    lecture de `config.json`. `CrossEncoder.config` est un attribut de la
    bibliothèque (sentence-transformers 5.6.1) et non un contrat public ; la
    lecture est donc défensive, et son échec rend `None` — que
    `verdict_langue_du_reranker` traite comme un `warning`, jamais comme un
    silence. Une montée de version qui déplacerait l'attribut rendrait ce garde
    bavard, pas muet, et c'est le bon sens de l'erreur.

    **CETTE DERNIÈRE PHRASE ÉTAIT FAUSSE, ET C'EST LA CORRECTION DU 9 SEPTEMBRE
    2026.** Elle affirmait « bavard, pas muet » sans borner ce qu'elle appelait
    un échec, et l'`except` ne retenait que `TypeError` et `ValueError`.
    `mesuré` ce jour-là par une sonde de dix lignes, sans charger de modèle :

    - un objet SANS `config` rend bien `None` — `getattr` avale l'`AttributeError` ;
    - un `config` qui est une **`property` levant `RuntimeError`** — ou `OSError`,
      `KeyError`, `ImportError` — **PROPAGEAIT**. Quatre natures sur les sept
      sondées, et non une.

    **« SEPT » EST DÉFINI ICI, PARCE QUE DEUX COMPTES JUSTES COEXISTAIENT SOUS
    DEUX DÉFINITIONS DIFFÉRENTES.** Ce docstring écrit « sept » ; le test qui le
    garde énumère une liste de **six**, et nomme en tout **neuf** types. Les
    trois comptes sont exacts, et ils ne comptent pas la même chose — c'est la
    cinquième occurrence de cette forme dans ce chantier, et la première où deux
    des écritures vivent dans le même fichier. La définition retenue est donc
    écrite aux deux sites, et c'est celle-ci :

        **SEPT = les natures que la SONDE DU 9 SEPTEMBRE 2026 a soumises à
        l'`except` étroit d'alors**, à savoir `AttributeError`, `TypeError`,
        `ValueError`, `RuntimeError`, `OSError`, `KeyError` et `ImportError`.
        Trois étaient absorbées — `AttributeError` par le `default` de `getattr`,
        `TypeError` et `ValueError` par l'`except` lui-même — et **quatre**
        propageaient.

    Le compte du test relève d'une autre définition, écrite chez lui : les
    natures qu'il SONDE aujourd'hui, absorption et traversée séparées. Aucun des
    deux n'est à corriger ; c'est leur silence sur leur propre définition qui
    l'était.

    Et `_get_rerank_model()` est appelé par `rerank()`, que `node_rerank`
    appelle sans aucun `try` : la propagation ne rendait donc pas ce garde
    bavard, elle CASSAIT la recherche. *Un garde qui provoque la panne qu'il
    surveille*, et ce n'était pas théorique — en sentence-transformers 5.6.1
    `CrossEncoder.config` **est** une `property`, chaînée sur une seconde
    (`transformers_model`), donc n'importe quoi qui lève dans la hiérarchie de
    modules du modèle traverse cette lecture.

    **POURQUOI L'`except` EST ÉLARGI À `Exception`, ET C'EST UNE JUSTIFICATION
    ÉCRITE AU SITE — la règle de ce dépôt l'exige.** Les trois autres réponses
    ont été pesées et écartées :

    - *borner la phrase et laisser l'`except` étroit* : la phrase serait juste
      et la panne resterait. La version installée est mesurée et sûre, mais ce
      garde existe précisément pour la montée de version, c'est-à-dire pour le
      cas qu'il ne survivrait pas ;
    - *énumérer les quatre natures mesurées* : une liste fermée sur ce qu'une
      sonde a trouvé aujourd'hui dans une bibliothèque tierce est une liste qui
      vieillit en silence — la cinquième nature ne rendrait pas ce garde bavard,
      elle casserait la recherche, et rien ne le dirait ;
    - *envelopper l'appel de `rerank()`* : ce serait déplacer la latitude d'une
      lecture de propriété vers tout le chargement du modèle, et avaler du même
      geste les pannes que `rerank()` DOIT propager (modèle absent, poids
      illisibles).

    La latitude est donc tenue au plus petit endroit possible : **deux `getattr`
    et un `int()`**, sur un fait de configuration purement informatif, dont
    l'échec a une valeur de repli déjà définie et déjà bruyante.

    **`BaseException` N'EST PAS ATTRAPÉ, ET LA LISTE COMPTE TROIS NOMS ET NON
    DEUX.** `KeyboardInterrupt` et `SystemExit` doivent traverser cette lecture
    comme ils traversent le reste — et **`asyncio.CancelledError` aussi**, qui
    manquait à cette phrase. Elle traverse déjà, et c'est le bon choix : *une
    annulation doit propager.* Mais elle ne le devait à rien de ce qui est écrit
    ici, seulement au fait que `CancelledError` dérive de `BaseException` depuis
    Python 3.8 — `vérifié` le 9 septembre 2026, `asyncio.CancelledError.__mro__`
    rend `(CancelledError, BaseException, object)` sous Python 3.12.13, et
    `issubclass(asyncio.CancelledError, Exception)` rend `False`.

    Le nommer n'est pas décoratif sur ce dépôt-ci : `pyproject.toml` porte
    `asyncio_mode = "strict"`, et le graphe est piloté par `ainvoke` et `astream`
    (`src/api/main.py:1012`, `:1168`, `:1334`). *Précision qui compte* :
    `node_rerank` est un nœud **synchrone**, donc une annulation arrive d'abord
    sur la coroutine qui attend, et non dans le fil qui exécute cette lecture. Ce
    n'est pas une raison de l'omettre — le jour où ce nœud devient `async`, un
    `except` élargi qui aurait avalé l'annulation rendrait la requête
    inannulable, et rien ne le dirait. Une liste d'exceptions à laisser passer
    qui ne nomme pas celle du modèle de concurrence du programme est une liste
    qui vieillit en silence.

    Les trois directions sont gardées par
    `TestLaLectureDefensiveDuVocabulaireNeCassePasLaRecherche`.
    """
    try:
        taille = getattr(getattr(model, "config", None), "vocab_size", None)
        return int(taille) if taille is not None else None
    except Exception:  # justifié dans le docstring ci-dessus — voir §4.36
        return None


@_SingletonVerrouille
def _get_rerank_model() -> CrossEncoder:
    logger.info(
        "Chargement du modèle de reranking : %s, périphérique demandé « %s »",
        settings.rerank_model,
        settings.torch_device,
    )
    try:
        model: CrossEncoder = CrossEncoder(settings.rerank_model, device=settings.torch_device)
    except Exception as exc:  # relancée ci-dessous — voir `_get_embedding_model`
        _memoriser_la_levee("rerank", exc)
        raise
    _oublier_la_levee("rerank")
    logger.info(
        "Modèle de reranking chargé sur le périphérique « %s »",
        getattr(model, "device", "inconnu"),
    )
    # APRÈS le chargement, et c'est l'inverse du lot 3 — délibérément. Là-bas le
    # garde passe AVANT, parce qu'il REFUSE et qu'il ne faut pas payer le
    # téléchargement d'un modèle qu'on va rejeter. Ici on signale et on se sert
    # du modèle de toute façon : le charger d'abord donne accès à sa propriété
    # sans aucune lecture supplémentaire. Une fois par processus, le singleton
    # s'en assurant — c'est la bonne cadence pour un fait de configuration.
    verdict = verdict_langue_du_reranker(
        settings.rerank_model, _vocabulaire_du_reranker(model)
    )
    if verdict is not None:
        niveau, message = verdict
        # Le ternaire replie TOUT ce qui n'est pas `"warning"` sur `INFO`, y
        # compris un niveau plus grave — c'est ce que `NiveauDuVerdict` borne à
        # deux valeurs pour que le repli ne puisse plus rétrograder personne.
        logger.log(logging.WARNING if niveau == "warning" else logging.INFO, message)
    return model


# ─── L'ÉTAT DU PÉRIPHÉRIQUE, ET IL DISTINGUE « PRÉSENT » DE « ATTEINT » ───────
#
# LA PANNE QUE CE BLOC REND VISIBLE. Trois conditions indépendantes décident que
# ce service calcule sur le GPU, et chacune suffit à le désactiver SANS que rien
# ne le dise : (a) un build CUDA de `torch` dans l'image, (b) le périphérique
# donné au conteneur par le runtime `nvidia`, (c) le réglage `TORCH_DEVICE`. Une
# image reconstruite avec la roue CUDA et un conteneur sans réservation rend
# exactement la même chose qu'aujourd'hui — en plus lourd. Le mode d'emploi
# complet, avec la commande de vérification de chacune, est à
# `documentation/gpu_cuda.md`.
#
# CE QUE CHAQUE CHAMP RÉPOND, ET AUCUN NE RÉPOND POUR UN AUTRE :
#
#   `requested`      — ce que le réglage DEMANDE. Condition (c).
#   `torch_version`  — le build, suffixé `+cpu` ou `+cuXXX`. Condition (a).
#   `cuda_build`     — la version CUDA du build, `None` sur une roue `+cpu`.
#                      Condition (a), et c'est elle qu'on confronte au pilote.
#   `cuda_available` — `torch` VOIT-il une carte d'ici. Condition (b) — c'est
#                      elle qui tombe à faux quand la réservation manque au
#                      compose, build CUDA ou non.
#   `embedding`      — le périphérique RÉELLEMENT porté par l'embedder.
#   `rerank`         — idem pour le cross-encoder.
#
# LES DEUX DERNIERS SONT LES SEULS QUI DISENT QUE LE GPU SERT, et c'est la
# raison d'être de ce bloc : `cuda_available` vrai avec `embedding: "cpu"` est
# un GPU présent et jamais atteint, la forme dominante des défauts de ce
# chantier — trouvée neuf fois.
#
# ET ILS VALENT `None` TANT QUE LE MODÈLE N'EST PAS CHARGÉ. C'est une décision,
# pas une approximation : `/health` est appelé toutes les 20 s par le
# healthcheck, et lire le périphérique en construisant le modèle ferait payer au
# premier healthcheck un téléchargement de modèle. Un `None` se lit « personne
# n'a encore eu besoin de ce modèle » — vrai, et différent de « il est sur CPU ».
# Le `currsize` du singleton est ce qui le dit sans rien déclencher.


def _peripherique_si_charge(accesseur: Any) -> str | None:
    """Le périphérique d'un modèle SI ET SEULEMENT SI il est déjà chargé.

    `accesseur` est l'un des deux `_SingletonVerrouille` de ce module. On lit
    son `currsize` plutôt que d'appeler : appeler CHARGERAIT, et cette fonction
    sert une route de santé qui ne doit rien déclencher.

    CE SITE EST LE SEUL APPELANT DU SINGLETON QUI NE SOIT PAS SOUS LA BORNE, et
    c'est R-2 de l'audit du 14 septembre 2026. Les deux autres — `_dense_search`
    et `rerank` — prennent `borne_des_etages_torch()` avant d'appeler ; celui-ci
    est sur la route de `/health`, qui ne doit jamais attendre un permis pour
    répondre.

    POURQUOI CE N'EST PAS UNE BRÈCHE, ET LA RAISON N'EST PAS CELLE QU'ON CROIT.
    Ce n'est pas qu'aucun chemin hors borne n'existe : c'en est un. C'est que le
    `currsize == 0` ci-dessous le referme, et que rien en production ne peut
    faire échouer ce test entre sa lecture et l'appel. La fenêtre existe —
    `currsize > 0` lu, puis un `cache_clear()` concurrent, puis `accesseur()`
    qui CHARGERAIT hors borne en tenant le verrou — mais `cache_clear()` n'a
    **aucun appelant en production**. `mesuré` le 14 septembre 2026 :

        grep -rnE '_get_(embedding|rerank)_model[.]cache_clear[(]' src/ scripts/
        #   -> rien, rc(grep)=1
        grep -rcE '_get_(embedding|rerank)_model[.]cache_clear[(]' tests/
        #   -> 24 sites     <- CONTROLE POSITIF : la recette SAIT les trouver

    La parenthèse ouvrante est dans le motif à dessein : sans elle, la recette
    s'attrape elle-même dans cette docstring et rend un faux appelant — ce qui
    s'est produit, et ce que le contrôle positif a fait voir.

    CE QUI LA RENDRAIT ATTEIGNABLE, et c'est ce qu'il faut surveiller : un
    `cache_clear()` appelé depuis `src/` ou `scripts/` — un endpoint de
    rechargement à chaud, une bascule de périphérique en service, une purge
    déclenchée par un signal. Le jour où l'un de ces trois apparaît, ce chemin
    doit passer sous la borne, ou lire le périphérique sans passer par
    `accesseur()`.

    ET IL N'Y A PAS D'INTERBLOCAGE POSSIBLE, borne comprise : un fil qui tient le
    verrou de chargement l'a pris APRÈS la borne, et il ne la redemande jamais.
    Corollaire vérifié : `/health` ne peut pas non plus ATTENDRE ce verrou — si
    `currsize == 0` il rend `None` sans rien prendre, et si `currsize > 0` la
    première lecture de `__call__` sort hors verrou.

    `getattr` plutôt qu'un accès direct, et sans `try` : `SentenceTransformer` et
    `CrossEncoder` exposent tous deux `device` en `property` (`mesuré` le
    11 septembre 2026 par `inspect` sur sentence-transformers 5.6.1), mais un
    double de test n'a aucune raison de le faire, et faire lever la route de
    santé sur la forme d'un double serait un garde qui se retourne.
    """
    if accesseur.cache_info().currsize == 0:
        return None
    peripherique = getattr(accesseur(), "device", None)
    return None if peripherique is None else str(peripherique)


def peripherique_hors_d_atteinte(demande: str, cuda_disponible: bool) -> str | None:
    """Le motif pour lequel `demande` ne peut PAS servir ici, ou `None`.

    CE QUE CETTE FONCTION EXISTE POUR FERMER. Le lot 11 a créé un mode de panne
    qui n'existait pas avant lui : `SentenceTransformer(nom)` laissait
    sentence-transformers choisir un périphérique QUI EXISTE, et le chargement ne
    pouvait pas lever pour cette raison ; `SentenceTransformer(nom, device=...)`
    passe la chaîne telle quelle à torch. Il n'y a **aucun repli vers CPU** dans
    ce module — pas de `try`, pas de garde sur `is_available()` — donc les
    modèles ne « retombent » pas : **ils lèvent**, au chargement, donc à la
    PREMIÈRE recherche, donc en production. `mesuré` le 14 septembre 2026 par
    l'audit du lot 11, quatre scénarios dans l'image étiquetée :

        `cuda` sans carte        -> RuntimeError: Found no NVIDIA driver
        `cuda:7` avec une carte  -> AcceleratorError: invalid device ordinal
        `banane`                 -> RuntimeError: Expected one of cpu, cuda, …
        `cpu` ou `cuda` servis   -> charge, rc=0

    ET LA ROUTE DE SANTÉ NE CHARGE RIEN, délibérément — un `/health` qui
    construit deux modèles n'est plus une sonde, c'est un téléchargement toutes
    les 20 s. `status` ne peut donc PAS savoir « le chargement va lever » avant
    qu'il ait levé. Ce qui EST connaissable sans rien charger, c'est que le
    périphérique demandé n'existe pas d'ici — et les trois levées ci-dessus sont
    exactement celles-là. C'est la borne de ce garde, elle est écrite au champ
    `TorchDeviceHealth.hors_d_atteinte` et rappelée ici : une levée qui ne tient
    pas à l'EXISTENCE du périphérique (mémoire insuffisante, modèle absent du
    cache, droits refusés) n'est pas vue.

    POURQUOI `cuda_disponible` EST UN PARAMÈTRE ET NON UNE LECTURE. L'appelant
    vient de lire `torch.cuda.is_available()` pour le publier ; le relire ici en
    ferait deux lectures pouvant diverger, et le corps publié ne correspondrait
    plus au verdict qui l'accompagne. Un seul relevé, un seul fait.

    RENDRE LE MOTIF ET NON UN BOOLÉEN, et c'est la décision déjà prise au site
    pour `EmbeddingModelHealth.status` : les trois causes ne se soignent pas
    pareil — corriger le `.env`, rendre la carte au conteneur, corriger la
    faute de frappe — et un booléen ne dirait laquelle.

    Gardé dans les DEUX directions : `tests/unit/test_peripherique_torch.py`,
    section (6), contrôle positif inclus.
    """
    try:
        cible = torch.device(demande)
    except (RuntimeError, ValueError) as exc:
        # La MÊME levée que celle que le constructeur produirait, obtenue au
        # parsing — donc sans carte, sans modèle et sans entrée-sortie.
        return f"torch refuse le périphérique demandé « {demande} » : {exc}"
    if cible.type != "cuda":
        return None
    if not cuda_disponible:
        return (
            f"« {demande} » demande une carte CUDA et torch n'en voit aucune depuis ce "
            "processus : le chargement du premier modèle lèvera, donc toute recherche "
            "rendra 500. Voir documentation/gpu_cuda.md §1, conditions (a) et (b)"
        )
    cartes = torch.cuda.device_count()
    if cible.index is not None and cible.index >= cartes:
        return (
            f"« {demande} » nomme la carte n° {cible.index} et torch n'en voit que "
            f"{cartes} (indices 0 à {cartes - 1}) : le chargement lèvera sur "
            "« invalid device ordinal ». Voir documentation/gpu_cuda.md §4"
        )
    return None


def _pic_memoire_reservee_mio() -> float | None:
    """Le plus haut niveau de mémoire GPU jamais RÉSERVÉ par ce processus, en Mio.

    C'EST UN MAXIMUM HISTORIQUE, PAS UNE CONSOMMATION COURANTE, et le champ le
    dit à son site : l'allocateur de torch ne rend rien, donc cette valeur est un
    **cliquet** — elle monte et ne redescend pas. Lue comme une mesure
    instantanée, elle surestimerait ce que l'agent tient à cet instant ; lue comme
    ce qu'elle est, elle dit ce que le voisin de carte doit RÉSERVER.

    `None` TANT QU'AUCUN MODÈLE N'EST CHARGÉ, et c'est la même décision que pour
    `embedding` et `rerank` juste au-dessus. La route ne charge rien ; un `0.0`
    publié au repos se lirait *« mesuré, et cet agent ne prend rien »*, quand il
    veut dire *« on ne sait pas encore »*. La différence est opérationnelle et
    elle est écrite au §4.50 du registre : un voisin qui dimensionne sa
    réservation pendant que cet agent est au repos voit 1,3 Go de libre en trop,
    les prend, et fait tomber l'agent **plus tard**, sans rapport apparent avec
    la cause.

    `None` AUSSI sur un build sans CUDA : `max_memory_reserved` n'y décrit rien.

    ET IL FAUT LIRE CE CHAMP DEPUIS LE PROCESSUS QUI SERT. `mesuré` le
    14 septembre 2026 à 09:29 UTC : `docker exec rag-agent-api python -c
    "torch.cuda.max_memory_reserved()"` rend **0,0 Mio** pendant que `nvidia-smi`
    attribue **1 984 Mio** au même conteneur — `docker exec` démarre un AUTRE
    processus, avec un contexte CUDA neuf. *C'est la raison d'être de ce champ :
    de l'extérieur, ce chiffre n'est pas lisible autrement que par cette route.*
    """
    chargé = (
        _get_embedding_model.cache_info().currsize > 0
        or _get_rerank_model.cache_info().currsize > 0
    )
    if not chargé or not torch.cuda.is_available():
        return None
    return round(torch.cuda.max_memory_reserved() / 2**20, 1)


def _verdict_du_peripherique(demande: str, cuda_disponible: bool) -> str | None:
    """Les DEUX moitiés en un seul champ : le contrôle statique et les levées.

    L'ORDRE PORTE. Une levée mémorisée est un fait OBSERVÉ ; le contrôle statique
    est une prédiction. Quand les deux parlent, on rend l'observation — elle dit
    ce qui s'est réellement passé, avec le message que torch a produit.
    """
    levees = levees_au_chargement()
    if levees:
        detail = " ; ".join(f"{modele} -> {motif}" for modele, motif in sorted(levees.items()))
        return (
            f"le dernier chargement a LEVÉ sur « {demande} » : {detail}. Toute "
            "recherche rendra 500 tant que la cause tient. Un chargement qui "
            "lève ne met RIEN en cache, donc `embedding`/`rerank` resteront "
            "`null` et chaque requête retentera"
        )
    return peripherique_hors_d_atteinte(demande, cuda_disponible)


def etat_du_peripherique() -> TorchDeviceHealth:
    """Les trois conditions du GPU, lues à la source, sans rien charger.

    `torch.cuda.is_available()` est le seul appel de cette fonction qui touche
    autre chose que de la mémoire : sur un build CPU il court-circuite sur
    `torch.version.cuda is None` et ne coûte rien ; sur un build CUDA il
    interroge le pilote une fois, puis `torch` garde le compte de cartes. C'est
    pourquoi l'appelant la passe quand même sous le plafond des sondes de
    `/health` — un pilote qui ne rend pas la main est une panne comme une autre,
    et elle ne doit pas coûter le healthcheck.
    """
    disponible = torch.cuda.is_available()
    return TorchDeviceHealth(
        requested=settings.torch_device,
        torch_version=torch.__version__,
        cuda_build=torch.version.cuda,
        cuda_available=disponible,
        embedding=_peripherique_si_charge(_get_embedding_model),
        rerank=_peripherique_si_charge(_get_rerank_model),
        # LU UNE SEULE FOIS, et passé : `cuda_available` ci-dessus et le verdict
        # ci-dessous doivent décrire le MÊME relevé, sinon le corps publié
        # contredirait le statut qui l'accompagne.
        hors_d_atteinte=_verdict_du_peripherique(settings.torch_device, disponible),
        concurrence_max=settings.torch_max_concurrency,
        pic_memoire_reservee_mio=_pic_memoire_reservee_mio(),
    )


@lru_cache(maxsize=1)
def _get_chroma_collection() -> chromadb.Collection:
    client = chromadb.HttpClient(host=settings.chroma_host, port=settings.chroma_port)
    collection = client.get_collection(settings.chroma_collection)
    logger.info(
        "ChromaDB connecté : %s:%s / collection '%s'",
        settings.chroma_host,
        settings.chroma_port,
        settings.chroma_collection,
    )
    return collection


def reset_connection() -> None:
    """Oublie la collection mise en cache, pour la rouvrir au prochain appel.

    Réarme aussi le verdict de concordance : la collection rouverte peut être
    une AUTRE collection — une réingestion a pu passer entre-temps — donc un
    verdict établi sur la précédente ne vaut plus rien.

    L'ORDRE DE CES DEUX LIGNES PORTE, ET IL EST GARDÉ. `cache_clear()` d'abord,
    `rearmer_verification_modele()` ensuite. Inversés, ils réintroduisent B2 à
    l'identique — un verdict favorable MÉMORISÉ sur une collection divergente —
    par le seul entrelacement suivant :

        1. `rearmer_verification_modele()` : la génération passe à G+1 ;
        2. un autre fil vérifie : il relève G+1, puis lit l'estampille — le cache
           n'est PAS encore vidé, donc il lit l'ANCIENNE collection, concordante ;
        3. `cache_clear()` : la prochaine ouverture rendra la NOUVELLE collection,
           que rien ne garantit concordante ;
        4. le fil vérificateur conclut : la génération n'a pas bougé depuis qu'il
           l'a relevée, donc il inscrit son verdict favorable. Ce verdict décrit
           une collection que personne ne lira plus.

    Le compare-et-échange ne peut rien contre cet ordre-là, et c'est le point : il
    protège contre un réarmement survenu PENDANT la lecture, pas contre un
    réarmement survenu AVANT une lecture qui porte encore sur l'ancien cache. Dans
    le bon ordre, la lecture qui suit le vidage ouvre la nouvelle collection et
    voit la divergence ; celle qui l'a précédé voit sa génération bouger et JETTE
    son verdict. Les deux issues sont sûres.

    **`mesuré` : inversées, les 552 tests de la campagne restaient VERTS.** Une
    décision argumentée et non gardée est une décision qui se défera sans un
    rouge — et celle-ci protège exactement le bloquant que ce lot existe pour
    fermer. Garde : `tests/unit/test_garde_modele_embedding.py`,
    `test_l_ordre_de_reset_connection_ne_peut_pas_s_inverser_en_silence`.
    """
    _get_chroma_collection.cache_clear()
    rearmer_verification_modele()


# ─── Le garde du modèle d'embedding ──────────────────────────────────────────
#
# LA PANNE. Les deux modèles candidats du projet rendent des vecteurs de la même
# largeur — 384 dimensions, site canonique `documentation/axes_amelioration.md`
# §4.4. ChromaDB accepte donc sans broncher un index produit par l'un et
# interrogé par l'autre : pas d'exception, pas de ligne de journal, aucune sonde
# de forme qui voie quoi que ce soit. La recherche rend simplement des passages
# PLAUSIBLES ET FAUX. Vérifier la dimension ne protège de rien ; c'est le NOM
# qui discrimine, et c'est déjà arrivé une fois sur ce système.
#
# CE QUI REND LE GARDE POSSIBLE. Le pipeline d'ingestion estampille la
# collection : `collection.metadata["embedding_model"]` porte le nom du modèle
# qui a produit les vecteurs. Le producteur avait fait sa moitié ; ceci est
# celle du lecteur.
#
# CE QUE LA LECTURE COÛTE, ET C'EST POURQUOI ELLE PEUT VIVRE SUR LE CHEMIN DE
# CHAQUE RECHERCHE. `Collection.metadata` est une propriété LOCALE du client
# chromadb (1.5.9 : `return self._model.metadata`), remplie au `get_collection`.
# La lire ne fait aucun aller-retour — contrairement à `count()`, qui en fait un
# et dont `lexical_stale` paie le prix à chaque appel.
#
# CE QUE CETTE ÉCONOMIE COÛTE EN RETOUR, et c'est une réserve, pas un détail :
# l'estampille lue est celle capturée à l'ouverture de la collection. Une
# réingestion qui changerait de modèle pendant que l'agent tourne ne serait vue
# qu'après `reset_connection()` — donc après une panne de Chroma, ou un
# redémarrage. Le pipeline ne réingère pas sous l'agent sans que quelqu'un le
# sache ; ce qui reste ouvert est consigné dans le rapport du lot.

class EmbeddingModelMismatchError(RuntimeError):
    """La collection n'a pas été produite par le modèle avec lequel on la lit.

    Ou bien on ne sait pas ce qui l'a produite, ce qui revient au même : dans les
    deux cas, rien ne permet d'affirmer que les vecteurs de la question et ceux
    de l'index vivent dans le même espace.
    """


# Verdict favorable déjà établi. Seul le FAVORABLE est retenu : un refus est
# re-mesuré à chaque appel, pour qu'une réparation soit visible sans avoir à
# redémarrer, et parce qu'on ne sert rien pendant ce temps de toute façon.
#
# CE QUE CE SITE A AFFIRMÉ, ET QUI ÉTAIT FAUX. Il portait que « le pire cas est
# une vérification faite deux fois — un verrou coûterait plus cher que ce qu'il
# éviterait ». C'est une PERTE DE MISE À JOUR, mesurée :
# `verifier_modele_embedding()` lit l'estampille, puis écrit le verdict À LA
# FIN ; un `rearmer_verification_modele()` arrivé entre les deux était écrasé par
# cette écriture. La conséquence n'est pas une vérification en trop, c'est un
# garde DÉSARMÉ pour toute la vie du processus, servant des passages plausibles
# et faux en silence. Site canonique :
# `documentation/axes_amelioration.md` §4.20, trouvaille B2.
#
# ATTEIGNABLE, et c'est ce qui en faisait un bloquant : `reset_connection()`
# tourne dans un fil du threadpool depuis le `ping()` du healthcheck, toutes les
# 20 s, et depuis la reprise de `_dense_search`, pendant que d'autres fils
# vérifient.
#
# CE QUI TIENT LA PLACE DU VERROU SUR LE CHEMIN CHAUD. Une GÉNÉRATION, incrémentée
# à chaque réarmement. La vérification la relève avant de lire, et n'inscrit son
# verdict favorable que si elle n'a pas bougé — un compare-et-échange. Le verrou
# ne couvre donc que deux affectations en mémoire, jamais la lecture : un
# réarmement concurrent n'attend pas derrière l'ouverture d'une collection, et un
# réarmement survenu pendant la lecture fait JETER le verdict plutôt que l'écraser.
# Se tromper dans ce sens-là coûte une relecture locale ; se tromper dans l'autre
# coûte le garde.
_verrou_concordance = threading.Lock()
_concordance_etablie = False
_generation_concordance = 0


def rearmer_verification_modele() -> None:
    """Oublie le verdict favorable, pour que la prochaine lecture le refasse.

    Incrémente la génération : une vérification déjà en cours de lecture verra
    que le monde a bougé sous elle et renoncera à inscrire son verdict.
    """
    global _concordance_etablie, _generation_concordance
    with _verrou_concordance:
        _concordance_etablie = False
        _generation_concordance += 1


def _lire_estampille() -> str | None:
    """Le nom du modèle qui a produit la collection, None s'il n'est pas inscrit.

    LÈVE si le store est illisible, et c'est voulu : « je n'ai pas pu lire » ne
    doit jamais se confondre avec « la collection ne porte pas d'estampille ».
    Le premier est un fait sur ChromaDB, le second un fait sur ce qui a indexé.
    """
    metadata = _get_chroma_collection().metadata or {}
    estampille = metadata.get("embedding_model")
    return str(estampille) if estampille is not None else None


def verifier_modele_embedding() -> None:
    """Refuse de lire une collection qu'un autre modèle a produite.

    Appelée en tête de la recherche dense, AVANT tout chargement de modèle : le
    constructeur `SentenceTransformer` télécharge ce qui manque au cache, et un
    garde placé après paierait le rapatriement du mauvais modèle avant de le
    refuser.

    Une estampille ABSENTE est refusée comme une divergence. C'est la décision du
    lot, et c'est le cœur du problème : un garde qui ne comparerait que lorsque
    l'estampille est présente serait décoratif sur exactement le cas où l'on ne
    sait pas ce qui a indexé. Le prix est réel — une collection produite par un
    pipeline plus ancien n'en porte pas, et l'agent la refusera — et il est
    payé sciemment : le geste de réparation est court et nommé dans le message,
    alors qu'un index lu de travers ne se voit qu'en relisant les réponses une
    par une.

    Une estampille ILLISIBLE n'est pas refusée ici : l'erreur du store remonte
    telle quelle. La recherche échouera de toute façon, et masquer une panne de
    ChromaDB derrière une erreur de configuration enverrait chercher au mauvais
    endroit.
    """
    global _concordance_etablie
    with _verrou_concordance:
        if _concordance_etablie:
            return
        generation = _generation_concordance
    attendu = settings.embedding_model_name
    estampille = _lire_estampille()
    if estampille is None:
        raise EmbeddingModelMismatchError(
            f"La collection '{settings.chroma_collection}' ne porte aucune estampille "
            f"`embedding_model` : rien ne dit avec quel modèle elle a été indexée, et "
            f"l'agent s'apprête à la lire avec '{attendu}'. Les modèles candidats de ce "
            f"projet rendent des vecteurs de même largeur, donc une erreur ici ne "
            f"produirait aucune exception, seulement des passages plausibles et faux. "
            f"Réparation : réingérer avec le pipeline courant, qui estampille, ou "
            f"inscrire l'estampille sur la collection si l'on sait ce qui l'a produite."
        )
    if estampille != attendu:
        raise EmbeddingModelMismatchError(
            f"La collection '{settings.chroma_collection}' a été indexée avec "
            f"'{estampille}', et l'agent s'apprête à la lire avec '{attendu}'. Les deux "
            f"rendent des vecteurs de même largeur : ChromaDB ne s'en plaindra pas et la "
            f"recherche rendra des passages plausibles et faux. Réparation : aligner "
            f"EMBEDDING_MODEL_NAME sur '{estampille}', ou réingérer avec '{attendu}'."
        )
    with _verrou_concordance:
        # Le compare-et-échange. Si la génération a bougé pendant la lecture,
        # un `reset_connection()` est passé : le verdict qu'on tient décrit une
        # collection dont plus rien ne garantit qu'elle est encore celle-là, et
        # l'inscrire ÉCRASERAIT le réarmement. On le jette, la prochaine
        # recherche relira — c'est une lecture locale, elle ne coûte rien.
        if generation == _generation_concordance:
            _concordance_etablie = True


def etat_modele_embedding() -> EmbeddingModelHealth:
    """Le même fait, sous la forme d'un rapport plutôt que d'un refus.

    Sert `/health` et le démarrage. Ne lève JAMAIS : une sonde qui tombe fait
    tomber la route qui la porte, et `/health` doit répondre 200 même dégradé.

    LE MOTIF, ET C'EST LE VRAI. Ce docstring a porté que `/health` devait rendre
    200 « sous peine de faire redémarrer le service en boucle ». C'est FAUX,
    mesuré deux fois indépendamment : un healthcheck en échec ne redéclenche
    aucun conteneur sous Docker Compose — `restart:` répond à la SORTIE du
    processus, pas à la santé — et 21 échecs consécutifs laissent
    `RestartCount=0` et `StartedAt` inchangé. Ce qui arrive vraiment est que le
    conteneur passe `unhealthy`, donc que `frontend`, qui en dépend en
    `condition: service_healthy` (`docker-compose.yml`), ne lève pas au démarrage
    à froid : une panne lisible deviendrait une pile muette. Le trou reste
    acceptable, mais sur ce motif-là. Site canonique :
    `documentation/axes_amelioration.md` §1.27 et §4.20, trouvaille N2.

    L'absorption est LARGE — le client chromadb remonte des erreurs de transport,
    de sérialisation et de schéma sans ancêtre commun, cf. `_taille_collection` —
    et elle n'est pas muette : ce qu'elle attrape devient `unknown`, publié comme
    tel dans la réponse, et le démarrage le journalise en WARNING.
    """
    attendu = settings.embedding_model_name
    try:
        estampille = _lire_estampille()
    except Exception:
        return EmbeddingModelHealth(status="unknown", expected=attendu, collection=None)
    if estampille is None:
        return EmbeddingModelHealth(status="missing", expected=attendu, collection=None)
    if estampille != attendu:
        return EmbeddingModelHealth(status="mismatch", expected=attendu, collection=estampille)
    return EmbeddingModelHealth(status="ok", expected=attendu, collection=estampille)


# ─── Index lexical BM25 ───────────────────────────────────────────────────────

_lexical_index = LexicalIndex()

# Reconstruction en cours, s'il y en a une. Un seul créneau : deux requêtes qui
# constatent la même dérive ne doivent pas lancer deux parcours du corpus.
_reconstruction: threading.Thread | None = None
_verrou_reconstruction = threading.Lock()
# Une reconstruction à la fois, tous appelants confondus. Distinct du verrou de
# `LexicalIndex` : celui-ci sérialise les constructions, celui-là les FUSIONNE.
# Sans lui, N appels à POST /reindex produisaient N parcours du corpus
# sérialisés, chacun occupant un fil du threadpool FastAPI le temps d'un parcours
# complet (~9 s, non mesuré — cf. `_charger_corpus`) —
# donc affamant les endpoints de recherche, qui vivent dans le même threadpool.
_verrou_reindexation = threading.Lock()


def _charger_corpus() -> tuple[list[str], list[str]]:
    """Lit tous les textes de la collection, par lots.

    C'est la partie coûteuse, linéaire dans la taille du corpus : tout le corpus
    est lu par lots de `_LEXICAL_PAGE`, puis tokenisé.

    **Le « ~9 s » écrit ailleurs dans ce dépôt n'est PAS une mesure** — c'est un
    ordre de grandeur hérité de la documentation d'origine, qu'aucune exécution
    n'a produit. La réserve et le protocole de mesure sont au site canonique,
    axes_amelioration.md §2 « Index BM25 en mémoire ». Ce qui est
    structurellement vrai, et qui suffit à justifier ce qui l'entoure : ce
    parcours est long devant une requête.

    Elle est passée en rappel à `LexicalIndex.ensure` pour être exécutée SOUS SON
    VERROU : effectuée avant de le prendre, N requêtes concurrentes la payaient
    N fois.
    """
    collection = _get_chroma_collection()
    total = collection.count()
    chunk_ids: list[str] = []
    documents: list[str] = []

    offset = 0
    while offset < total:
        lot = collection.get(limit=_LEXICAL_PAGE, offset=offset, include=["documents"])
        chunk_ids.extend(lot.get("ids") or [])
        documents.extend(lot.get("documents") or [])
        offset += _LEXICAL_PAGE

    return chunk_ids, documents


def _taille_collection() -> int | None:
    """Nombre de chunks actuellement dans la collection, None s'il est illisible.

    L'absorption est LARGE parce que le client chromadb remonte des erreurs de
    transport, de sérialisation et de schéma sans ancêtre commun. Elle est MUETTE
    parce que ce qu'elle cache est déjà dit ailleurs : `ping()` sonde Chroma et
    /health publie le résultat dans la même réponse. Le doute est rendu tel
    quel — « je ne sais pas » — et jamais confondu avec « rien n'a changé ».
    """
    try:
        return int(_get_chroma_collection().count())
    except Exception:
        return None


def lexical_stale() -> bool:
    """L'index décrit-il un corpus qui n'existe plus ?

    L'ingestion est un service SÉPARÉ qui écrit dans ChromaDB pendant que
    l'agent tourne. Un document ingéré après la construction de l'index reste
    trouvable en recherche dense — la requête part à Chroma à chaque fois — et
    devenait invisible en recherche lexicale jusqu'au prochain redémarrage : la
    recherche devenait silencieusement asymétrique, tandis que /health
    continuait d'annoncer un index prêt. Il l'était ; il décrivait simplement
    un corpus disparu.

    Le compte de la collection est comparé au nombre de chunks indexés.

    **Ce que cette comparaison coûte, et ce n'est pas rien.** Un aller-retour
    ChromaDB par appel : mesuré au compteur, 10 recherches lexicales font 10
    `count()`, et 5 appels à `lexical_ready` — donc 5 sondes /health — en font 5.
    Une version antérieure de ce docstring affirmait que « le compte est déjà lu
    au moment de la construction, donc la comparaison ne coûte rien de neuf » :
    c'est faux, la lecture de la construction ne sert qu'à la construction. Un
    cache sur fenêtre courte est un candidat, mais c'est un arbitrage de
    performance qui demande une mesure contre les vrais stores — il est ouvert
    dans axes_amelioration.md, pas décidé ici.

    **Ce n'est qu'un filet** : un corpus dont on a retiré autant de chunks qu'on
    en a ajouté affiche le même compte. C'est pourquoi `POST /reindex` existe —
    un contrat que l'ingestion honore vaut mieux qu'une heuristique qu'elle
    ignore.
    """
    if not _lexical_index.ready:
        return False
    taille = _taille_collection()
    return taille is not None and taille != _lexical_index.size


def lexical_ready() -> bool:
    """L'index BM25 est-il construit ET à jour ? (exposé par /health)

    Un index périmé est déclaré NON prêt. Répondre vrai décrivait un corpus qui
    n'existait plus, ce qui est plus trompeur que d'admettre la dégradation :
    dans les deux cas la recherche est amputée, mais seul le faux le dit.
    """
    return _lexical_index.ready and not lexical_stale()


def rebuild_lexical_index() -> int:
    """Reconstruit l'index de force sur le corpus courant, et rend sa taille.

    Sert `POST /reindex` et la reconstruction de fond. `force` traverse le test
    « déjà prêt » d'`ensure` sans contourner son verrou : une recherche
    concurrente continue de lire l'ancien index jusqu'à ce que le nouveau le
    remplace d'un bloc.

    Les appels concurrents sont **fusionnés** et non sérialisés : celui qui
    arrive pendant une reconstruction attend son issue et rend sa taille, au lieu
    d'en enchaîner une seconde sur le même corpus. C'est ce qui distingue ce
    verrou de celui de `LexicalIndex` — sans lui, un appelant qui répète
    `POST /reindex` mobilise un fil du threadpool FastAPI par appel, le temps d'un
    parcours complet chacun (~9 s, non mesuré — cf. `_charger_corpus`), et les
    endpoints de recherche partagent ce threadpool.
    """
    if not _verrou_reindexation.acquire(blocking=False):
        with _verrou_reindexation:
            return _lexical_index.size
    try:
        _lexical_index.ensure(_charger_corpus, force=True)
        return _lexical_index.size
    finally:
        _verrou_reindexation.release()


def _planifier_reconstruction() -> None:
    """Programme une reconstruction HORS du chemin de la requête.

    La lecture du corpus et la tokenisation coûtent ~9 secondes (chiffre non
    mesuré, cf. `_charger_corpus`) : les faire payer à la requête qui découvre la
    dérive punirait un utilisateur pour une ingestion à laquelle il n'a pas
    participé. L'index périmé continue de servir
    pendant ce temps — dégradé, mais pas absent, et il ne décrit alors qu'un
    corpus plus petit que le vrai.

    Fil démon : une reconstruction interrompue par l'arrêt du service ne laisse
    rien derrière elle — l'index n'est pas persisté — alors qu'un fil non démon
    retiendrait l'arrêt jusqu'à la fin du parcours.
    """
    global _reconstruction
    with _verrou_reconstruction:
        if _reconstruction is not None and _reconstruction.is_alive():
            return
        logger.info(
            "Index lexical périmé (%d chunks indexés, %s dans la collection) : "
            "reconstruction en tâche de fond, l'index actuel continue de servir.",
            _lexical_index.size,
            _taille_collection(),
        )
        _reconstruction = threading.Thread(
            target=rebuild_lexical_index, name="reindex-lexical", daemon=True
        )
        _reconstruction.start()


def _lexical_search(question: str, k: int) -> list[ChunkResult]:
    """Recherche BM25, résolue en ChunkResult via ChromaDB."""
    if not _lexical_index.ready:
        try:
            _lexical_index.ensure(_charger_corpus)
        except Exception:
            # Absorption LARGE et assumée : la recherche dense suffit à servir
            # la requête, et l'absence de BM25 dégrade le rappel sans casser la
            # réponse. Tracée avec sa pile, et /health la publie en
            # `index_lexical: false`.
            logger.exception("Index lexical indisponible, recherche dense seule.")
            return []
    elif lexical_stale():
        _planifier_reconstruction()

    hits = _lexical_index.search(question, k)
    if not hits:
        return []

    ids = [chunk_id for chunk_id, _ in hits]
    records = _get_chroma_collection().get(ids=ids, include=["documents", "metadatas"])
    par_id: dict[str, tuple[str, dict[str, Any]]] = {
        str(rid): (str(doc), dict(meta))
        for rid, doc, meta in zip(
            records.get("ids") or [],
            records.get("documents") or [],
            records.get("metadatas") or [],
            strict=False,
        )
    }
    # L'ordre du classement BM25 est ce qui compte pour la fusion : on le
    # préserve au lieu de reprendre celui, arbitraire, du `get`.
    return [
        chunk_from_record(chunk_id, *par_id[chunk_id]) for chunk_id, _ in hits if chunk_id in par_id
    ]


def full_texts(element_ids: list[str]) -> dict[str, str]:
    """Recompose le texte intégral des éléments demandés depuis ChromaDB.

    Le graphe ne porte qu'un aperçu : l'ingestion y tronque le texte à 2000
    caractères, le corpus complet vivant dans l'index vectoriel. Un tableau
    exporté par Docling dépasse souvent cette limite et arrivait donc amputé au
    LLM — alors que sa version entière était à un `get` de distance.

    Un élément long est réparti sur plusieurs chunks recouvrants (`abc#0`,
    `abc#1`, …) : ils sont remis dans l'ordre puis recollés en retirant le
    recouvrement, sinon la jointure dupliquerait la charnière.

    Args:
        element_ids: Identifiants d'éléments (hash 10 hexadécimaux).

    Returns:
        Dict {element_id: texte complet}. Les éléments absents de l'index —
        titres, fragments trop courts pour être vectorisés — sont omis.
    """
    if not element_ids:
        return {}

    try:
        records = _get_chroma_collection().get(
            where={"element_id": {"$in": list(set(element_ids))}},  # type: ignore[dict-item]
            include=["documents", "metadatas"],
        )
    except Exception:
        # Absorption LARGE et assumée : le client chromadb remonte transport,
        # sérialisation et schéma sans ancêtre commun. La dégradation est réelle
        # mais bornée — le texte tronqué du graphe reste, donc le LLM reçoit un
        # tableau amputé plutôt que rien — et elle est tracée en WARNING.
        logger.warning("Texte intégral indisponible, le texte du graphe est conservé.")
        return {}

    par_element: dict[str, list[tuple[int, str]]] = {}
    for doc, meta in zip(
        records.get("documents") or [], records.get("metadatas") or [], strict=False
    ):
        eid = str(meta.get("element_id") or "")
        if eid:
            index = int(str(meta.get("chunk_index") or 0))
            par_element.setdefault(eid, []).append((index, doc or ""))

    return {
        eid: _join_overlapping([texte for _, texte in sorted(morceaux)])
        for eid, morceaux in par_element.items()
    }


def _join_overlapping(morceaux: list[str]) -> str:
    """Recolle des fenêtres recouvrantes en supprimant la partie commune.

    L'ingestion découpe avec un recouvrement (150 caractères par défaut) : une
    concaténation naïve répéterait la charnière. On cherche le plus long suffixe
    du texte accumulé qui soit préfixe du morceau suivant.
    """
    if not morceaux:
        return ""

    resultat = morceaux[0]
    for morceau in morceaux[1:]:
        limite = min(len(resultat), len(morceau), _MAX_OVERLAP)
        recouvrement = 0
        for taille in range(limite, 0, -1):
            if resultat.endswith(morceau[:taille]):
                recouvrement = taille
                break
        resultat += morceau[recouvrement:] if recouvrement else f" {morceau}"
    return resultat


def ping() -> bool:
    """Vérifie que ChromaDB répond (utilisé par /health).

    Absorption LARGE et assumée : une sonde ne doit jamais lever. Elle n'est pas
    muette — le faux rendu ici est ce que /health publie — et elle agit : le
    cache de collection est oublié, pour que la prochaine requête rouvre.
    """
    try:
        _get_chroma_collection().count()
        return True
    except Exception:
        reset_connection()
        return False


# ─── Retrieval ────────────────────────────────────────────────────────────────

def retrieve(
    question: str,
    top_k: int | None = None,
    translation: str | None = None,
    chrono: Chrono | None = None,
) -> list[ChunkResult]:
    """Recherche les candidats et fusionne tout ce qui a été trouvé.

    Jusqu'à quatre classements entrent dans la fusion : dense et lexical, pour
    la question et pour sa traduction. Chacun ramène FETCH_K candidats et la
    fusion RRF n'en garde que top_k — élargir en amont est ce qui donne à la
    fusion de quoi travailler, deux listes identiques ne fusionnent rien.

    Args:
        question: La question, dans sa langue d'origine.
        top_k: Candidats conservés après fusion.
        translation: La même question dans l'autre langue du corpus. Elle
            n'existe que pour la recherche : la génération ne la voit jamais.
        chrono: Accumulateur d'étages. Renseigné, il reçoit `dense_ms`,
            `lexical_ms` et `fusion_ms` séparément — sans quoi les trois
            restent noyés dans le temps mural du nœud, et « dense seul vs
            hybride » ne peut pas s'arbitrer sur le prix. Absent, la fonction
            ne mesure rien : le banc de réglage n'en a pas besoin.
    """
    chrono = chrono or Chrono()
    k = top_k or settings.retrieval_top_k
    if not settings.hybrid_search and not translation:
        with chrono.mesurer("dense_ms"):
            dense = _dense_search(question, k)
        return dense[:k]

    requetes = [(question, 1.0)]
    if translation:
        # La traduction pèse moins : elle sauve les questions dont le document
        # est dans l'autre langue, mais ramène du bruit sur les autres.
        requetes.append((translation, settings.translation_weight))

    # La recherche dense d'abord : elle seule porte une distance vectorielle
    # réelle, et fait donc foi sur les métadonnées d'un chunk vu deux fois.
    classements: list[list[ChunkResult]] = []
    poids: list[float] = []
    for requete, poids_requete in requetes:
        with chrono.mesurer("dense_ms"):
            classements.append(_dense_search(requete, settings.fetch_k))
        poids.append(poids_requete)
    if settings.hybrid_search:
        for requete, poids_requete in requetes:
            with chrono.mesurer("lexical_ms"):
                classements.append(_lexical_search(requete, settings.fetch_k))
            poids.append(poids_requete)

    retenus = [(c, p) for c, p in zip(classements, poids, strict=True) if c]
    if not retenus:
        return []
    non_vides = [c for c, _ in retenus]

    with chrono.mesurer("fusion_ms"):
        fusionnes = fuse(non_vides, k, poids=[p for _, p in retenus])
    logger.info(
        "Recherche : %s → %d fusionnés pour %r%s",
        " + ".join(str(len(c)) for c in non_vides),
        len(fusionnes),
        question[:44],
        " (+ traduction)" if translation else "",
    )
    return fusionnes


def _dense_search(question: str, k: int) -> list[ChunkResult]:
    """Recherche vectorielle seule.

    La concordance du modèle est vérifiée ICI, avant le moindre chargement : ce
    site est celui qui PRODUIT le comportement à empêcher — une collection
    interrogée avec le mauvais embedder — et il est le seul que tout chemin de
    recherche traverse. Un agent démarré avant une réingestion divergente, ou
    démarré alors que ChromaDB ne répondait pas, ne passe par aucun garde de
    démarrage ; il passe par celui-ci.
    """
    verifier_modele_embedding()
    collection = _get_chroma_collection()

    # LE CHARGEMENT EST SOUS LA BORNE, ET PAS SEULEMENT LE CALCUL — B-1 de
    # l'audit du 14 septembre 2026. Construire un modèle est le moment où la
    # carte alloue le PLUS, et un chargement laissé hors de la borne se déroule
    # pendant que `TORCH_MAX_CONCURRENCY` calculs occupent déjà la carte : le
    # chiffre de réservation rendu au voisin cesse alors de majorer la scène.
    # La sérialisation des manques, elle, est dans `_SingletonVerrouille` — la
    # borne seule ramènerait le pic de K copies à `TORCH_MAX_CONCURRENCY`
    # copies, ce qui est une atténuation et non une fermeture.
    #
    # CE QUE CE PLACEMENT COÛTE, ET IL EST ASSUMÉ — mais le chiffre publié ici
    # était FAUX, et c'est NB-B de l'audit du 14 septembre 2026. La phrase
    # retirée disait « à la borne par défaut, trois autres requêtes passent
    # quand même ». `mesuré` le 14 septembre 2026, 8 requêtes à froid, borne 4,
    # chargement de 3,0 s : **ZÉRO** requête progresse pendant le chargement.
    # Les trois autres PRENNENT un permis, puis se bloquent sur le verrou de
    # chargement — elles consomment la borne sans avancer. Contrôle positif de
    # la même sonde, modèle déjà chaud : **8 sur 8** progressent.
    #
    # CE QUI SE PASSE RÉELLEMENT AU DÉMARRAGE À FROID, et c'est la partie qui
    # compte pour l'exploitation : **le chargement d'un étage gèle l'autre**.
    # `mesuré`, quatre `/search` à froid (ils épuisent les quatre permis) pendant
    # qu'une requête `/sources` arrive, cross-encoder DÉJÀ chaud :
    #
    #     borne 4                      -> /sources attend  2,9 s
    #     borne désarmée (200)         -> /sources attend  0,0 s   (contrôle)
    #
    # ET SOUS UNE LEVÉE AU CHARGEMENT, LES ÉCHECS SONT SÉRIALISÉS — NB-C du même
    # audit. Le module décrit lui-même cette panne (`_memoriser_la_levee`) : dans
    # cette scène chaque requête prend un permis, prend le verrou, tente, lève.
    # `mesuré`, chargement qui lève après 0,5 s, 8 requêtes concurrentes,
    # borne 4 : **4,0 s** au total, soit 0,5 s × 8 — la latence du 500 croît
    # linéairement avec la file. La propriété utile est intacte et elle aussi
    # mesurée : le singleton **ne se peuple pas** sur une levée (`currsize` = 0
    # après), donc chaque appel retente et la levée mémorisée s'efface dès que la
    # cause est réparée.
    #
    # L'ARBITRAGE RESTE LE MÊME, et il est défendable : la mémoire qu'on refuse
    # de plafonner ne se récupère jamais, la latence d'un démarrage à froid se
    # rattrape, et un 500 sérialisé reste un 500. Ce qui n'était pas défendable,
    # c'est de chiffrer ce coût à l'envers.
    #
    # L'ORDRE DES DEUX VERROUS EST TOTAL SUR LES CHEMINS DE RECHERCHE : borne
    # d'abord, verrou de chargement ensuite, ici comme dans `rerank`. Aucune
    # inversion n'est donc possible **entre ces deux chemins-là**. Il existe un
    # TROISIÈME appelant du singleton, hors borne — `_peripherique_si_charge`,
    # sur la route de `/health` — et pourquoi il ne rouvre rien est écrit à son
    # site, avec ce qui le rendrait atteignable. R-2 de l'audit.
    with borne_des_etages_torch():
        embedding_model = _get_embedding_model()
        query_embedding: list[float] = embedding_model.encode(question).tolist()

    def _query(coll: chromadb.Collection) -> dict[str, Any]:
        return dict(coll.query(
            query_embeddings=[query_embedding],  # type: ignore[arg-type]
            n_results=k,
            include=["documents", "metadatas", "distances"],
        ))

    try:
        results = _query(collection)
    except Exception:
        # La collection est mise en cache : si ChromaDB a redémarré, l'objet
        # pointe vers une connexion morte et toutes les recherches échouent
        # jusqu'au redémarrage de l'agent. On la rouvre et on retente une fois.
        # Absorption LARGE parce qu'un client mort produit des erreurs de
        # transport, de sérialisation et de schéma sans ancêtre commun ; tracée
        # en WARNING, et un second échec remonte à l'appelant.
        logger.warning("ChromaDB injoignable, réouverture de la connexion et nouvel essai.")
        reset_connection()
        # LE GARDE EST REPASSÉ ICI, et ce n'est pas une précaution abstraite.
        # `reset_connection()` a désarmé le verdict précisément parce que la
        # collection rouverte peut être une AUTRE collection — et une coupure de
        # ChromaDB est exactement le moment où une réingestion a pu passer
        # dessous. Sans cette ligne, la requête en cours interrogeait la
        # collection neuve SANS repasser le garde : une réponse complète et
        # FAUSSE, sans exception ni ligne de journal, sur le seul chemin où
        # l'objet collection change d'identité en vol. Mesuré, et site canonique
        # `documentation/axes_amelioration.md` §4.20, trouvaille B1.
        # Garde : tests/unit/test_garde_modele_embedding.py,
        # `test_la_reprise_apres_reouverture_repasse_le_garde`.
        verifier_modele_embedding()
        results = _query(_get_chroma_collection())

    chunks: list[ChunkResult] = []
    docs = results.get("documents") or [[]]
    metas = results.get("metadatas") or [[]]
    dists = results.get("distances") or [[]]
    ids = results.get("ids") or [[]]

    for chunk_id, doc, meta, dist in zip(ids[0], docs[0], metas[0], dists[0], strict=False):
        chunks.append(
            ChunkResult(
                chunk_id=chunk_id,
                element_id=meta.get("element_id", ""),
                graph_node_id=meta.get("graph_node_id", ""),
                document=doc,
                filename=meta.get("filename", ""),
                collection=meta.get("collection") or "",
                source_path=meta.get("source_path") or "",
                section_title=meta.get("section_title") or "",
                language=meta.get("language") or "",
                depth=int(meta.get("depth") or 0),
                page_no=int(meta.get("page_no", 0)),
                label=meta.get("label", ""),
                minio_url=meta.get("minio_url") or None,
                page_position=int(meta.get("page_position", 0)),
                ref_position=int(meta.get("ref_position", 0)),
                distance=float(dist),
            )
        )

    logger.debug("Dense : %d chunks pour '%s'", len(chunks), question[:60])
    return chunks


# ─── Reranking ────────────────────────────────────────────────────────────────

def _sigmoid(x: float) -> float:
    """Ramène un logit de cross-encoder dans [0, 1].

    Monotone : l'ordre du classement est inchangé. Seule l'échelle devient
    interprétable — un seuil « 0.5 » veut enfin dire quelque chose.
    """
    if x >= 0:
        return 1.0 / (1.0 + math.exp(-x))
    # Forme stable pour les logits très négatifs (exp(-x) déborde sinon).
    exp_x = math.exp(x)
    return exp_x / (1.0 + exp_x)


def dedupe_by_element(chunks: list[ChunkResult]) -> list[ChunkResult]:
    """Ne garde qu'un chunk par element_id, le mieux classé.

    Un bloc long est découpé par l'ingestion en fenêtres recouvrantes qui
    partagent leur ``element_id`` (``abc#0``, ``abc#1``, …). Comme elles se
    ressemblent, le reranker les remonte ensemble : elles consommaient
    plusieurs places du top-K pour un seul passage, et produisaient deux cases
    à cocher de même clé côté frontend.

    L'ordre d'entrée est préservé — la fonction est donc sûre après un tri.
    """
    best: dict[str, ChunkResult] = {}
    for chunk in chunks:
        current = best.get(chunk.element_id)
        if current is None:
            best[chunk.element_id] = chunk
            continue
        # À défaut de score de rerank, la distance vectorielle départage
        # (plus petite = plus proche).
        if chunk.rerank_score is not None and current.rerank_score is not None:
            if chunk.rerank_score > current.rerank_score:
                best[chunk.element_id] = chunk
        elif chunk.distance < current.distance:
            best[chunk.element_id] = chunk
    return list(best.values())


def rerank(question: str, chunks: list[ChunkResult]) -> list[ChunkResult]:
    """Applique le cross-encoder et retourne les top RERANK_TOP_K éléments.

    La déduplication a lieu **avant** la troncature au top-K : sinon plusieurs
    fenêtres d'un même passage occupent des places au détriment d'autres
    documents.
    """
    if not chunks:
        return []

    pairs = [[question, c.document] for c in chunks]
    # Les stubs du cross-encoder décrivent un type d'entrée multimodal très
    # large ; une liste de paires texte est ce qu'il accepte en pratique.
    # Sous la borne, CHARGEMENT COMPRIS, et c'est L'ÉTAGE QUI COÛTE : il traite
    # `FETCH_K=50` passages par requête là où l'encodage n'en traite qu'un, et
    # son modèle est le plus lourd des deux. Le motif complet du placement est
    # à `_dense_search`, qui porte le même geste.
    with borne_des_etages_torch():
        rerank_model = _get_rerank_model()
        scores: list[float] = rerank_model.predict(pairs).tolist()  # type: ignore[arg-type]

    for chunk, score in zip(chunks, scores, strict=False):
        chunk.rerank_score = score
        chunk.relevance = _sigmoid(score)

    ranked = sorted(chunks, key=lambda c: c.rerank_score or 0.0, reverse=True)
    result = dedupe_by_element(ranked)[: settings.rerank_top_k]

    logger.info(
        "Reranking : %d chunks scorés → %d éléments distincts (top-%d)",
        len(chunks),
        len(result),
        settings.rerank_top_k,
    )
    return result


# ─── Groupement par document ──────────────────────────────────────────────────

def group_by_document(chunks: list[ChunkResult]) -> list[SourceGroup]:
    """Regroupe les chunks par document source, triés par meilleur score.

    Le groupement se fait sur ``source_path`` et non sur ``filename`` : deux
    ouvrages peuvent contenir un chapitre « Préface », et les fusionner rendait
    toute citation ambiguë. Repli sur ``filename`` si la métadonnée est absente
    (documents ingérés avant qu'elle n'existe).
    """
    groups: dict[str, list[ChunkResult]] = {}
    for chunk in dedupe_by_element(chunks):
        groups.setdefault(chunk.document_key, []).append(chunk)

    result = []
    for doc_chunks in groups.values():
        head = doc_chunks[0]
        best = max(
            (c.rerank_score for c in doc_chunks if c.rerank_score is not None),
            default=0.0,
        )
        best_relevance = max((c.relevance or 0.0 for c in doc_chunks), default=0.0)
        result.append(
            SourceGroup(
                filename=head.filename,
                collection=head.collection,
                source_path=head.source_path,
                best_score=best,
                best_relevance=best_relevance,
                chunks=sorted(doc_chunks, key=lambda c: c.rerank_score or 0.0, reverse=True),
            )
        )

    return sorted(result, key=lambda g: g.best_score, reverse=True)
