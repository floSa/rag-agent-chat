"""Recherche lexicale BM25, et fusion avec la recherche dense.

La recherche vectorielle seule rate ce qui ne se paraphrase pas : un acronyme,
un nom propre, une référence de norme, un identifiant, un chiffre. Deux termes
proches en sens ont des vecteurs proches, mais « ISO 27001 » n'a pas de
synonyme — il faut le retrouver à la lettre. BM25 fait exactement cela, et les
deux approches échouent sur des cas différents : les fusionner récupère les deux.

L'index BM25 est construit en mémoire au démarrage à partir des documents de
ChromaDB. Pour un corpus de quelques dizaines de milliers de chunks, c'est
quelques secondes et quelques dizaines de mégaoctets — au-delà, il faudrait un
moteur dédié (OpenSearch, Vespa) plutôt qu'un index Python.
"""

from __future__ import annotations

import logging
import re
import threading
import unicodedata
from collections.abc import Callable
from typing import Any, NamedTuple

from rank_bm25 import BM25Okapi

from src.agent.settings import settings
from src.api.schemas import ChunkResult

logger = logging.getLogger(__name__)

# Découpage sur tout ce qui n'est ni lettre ni chiffre. Les mots composés et les
# références (« ISO-27001 », « scikit-learn ») se scindent en composants, ce qui
# les rend trouvables par chacun de leurs morceaux.
_TOKEN = re.compile(r"\w+", re.UNICODE)
# Un mot d'une lettre ne porte pas d'information et gonfle l'index.
_MIN_TOKEN_LEN = 2


def tokenize(text: str) -> list[str]:
    """Découpe un texte en jetons comparables, accents et casse neutralisés.

    Le corpus mêle français et anglais : « inférence » et « inference » doivent
    tomber sur le même jeton, sans quoi une question accentuée ne retrouve pas
    un texte qui ne l'est pas — et réciproquement.
    """
    normalise = unicodedata.normalize("NFKD", text.lower())
    sans_accents = "".join(c for c in normalise if not unicodedata.combining(c))
    return [t for t in _TOKEN.findall(sans_accents) if len(t) >= _MIN_TOKEN_LEN]


class _Etat(NamedTuple):
    """Index BM25 et les identifiants qu'il numérote, indissociables.

    Les deux vivaient dans deux attributs distincts. Une reconstruction les
    remplaçait l'un après l'autre, et une recherche qui s'intercalait entre les
    deux affectations lisait les rangs du NOUVEAU BM25 dans l'ANCIENNE liste
    d'identifiants — donc les mauvais chunks, ou un `IndexError` si la liste a
    rétréci. Tant que l'index était construit une fois pour toutes, la fenêtre
    n'existait pas ; elle s'ouvre dès qu'une reconstruction a lieu pendant que
    le service répond. Un tuple remplacé d'un seul coup la referme.
    """

    bm25: BM25Okapi
    chunk_ids: tuple[str, ...]


class LexicalIndex:
    """Index BM25 en mémoire, construit une fois et interrogé ensuite."""

    def __init__(self) -> None:
        self._etat: _Etat | None = None
        self._lock = threading.Lock()
        self._constructions = 0

    @property
    def ready(self) -> bool:
        return self._etat is not None

    @property
    def size(self) -> int:
        etat = self._etat
        return len(etat.chunk_ids) if etat is not None else 0

    @property
    def constructions(self) -> int:
        """Nombre de constructions abouties depuis le démarrage.

        Exposé pour être VÉRIFIÉ : un test qui se contente de constater que
        l'index finit construit reste vert quand N requêtes concurrentes le
        construisent N fois. Ce qui voit ce défaut-là, c'est un compteur.
        """
        return self._constructions

    def build(self, chunk_ids: list[str], documents: list[str]) -> None:
        """Construit l'index à partir de textes déjà lus."""
        with self._lock:
            self._construire(chunk_ids, documents)

    def ensure(
        self, charger: Callable[[], tuple[list[str], list[str]]], *, force: bool = False
    ) -> bool:
        """Construit l'index une seule fois, même sous N appels concurrents.

        La LECTURE du corpus est passée en rappel et exécutée SOUS LE VERROU.
        C'est tout l'objet de la méthode : l'appelant testait `ready` puis
        lisait le corpus hors verrou, et seule la construction finale était
        protégée. N requêtes arrivant avant que l'index soit prêt déclenchaient
        donc N lectures complètes de la collection et N tokenisations — N fois
        le temps, N fois la mémoire, N−1 résultats jetés. Les endpoints de
        recherche sont des `def`, donc servis par le threadpool FastAPI : deux
        utilisateurs qui ouvrent l'interface après un redéploiement suffisent.

        Args:
            charger: Rend (chunk_ids, documents). Appelé au plus une fois par
                construction, jamais si l'index est déjà prêt.
            force: Reconstruit même si l'index est prêt. Sert la réindexation
                explicite, quand le corpus a bougé sous l'index.

        Returns:
            Vrai si CET appel a construit l'index.
        """
        with self._lock:
            if self._etat is not None and not force:
                return False
            chunk_ids, documents = charger()
            return self._construire(chunk_ids, documents)

    def _construire(self, chunk_ids: list[str], documents: list[str]) -> bool:
        """Tokenise et remplace l'état. À appeler verrou tenu."""
        corpus = [tokenize(doc) for doc in documents]
        # BM25Okapi divise par la longueur moyenne des documents : un corpus
        # vide la rendrait nulle et ferait échouer chaque recherche.
        if not corpus:
            logger.warning("Index lexical non construit : corpus vide.")
            return False
        self._etat = _Etat(BM25Okapi(corpus), tuple(chunk_ids))
        self._constructions += 1
        logger.info("Index lexical BM25 construit : %d chunks.", len(chunk_ids))
        return True

    def search(self, question: str, top_k: int) -> list[tuple[str, float]]:
        """Retourne les (chunk_id, score) les mieux classés pour cette question."""
        # Lu une fois dans une locale : une reconstruction concurrente remplace
        # l'état pendant la recherche, et les rangs doivent être résolus dans la
        # liste d'identifiants qui les a produits.
        etat = self._etat
        if etat is None:
            return []
        jetons = tokenize(question)
        if not jetons:
            return []
        scores = etat.bm25.get_scores(jetons)
        meilleurs = sorted(enumerate(scores), key=lambda t: t[1], reverse=True)[:top_k]
        return [(etat.chunk_ids[i], float(s)) for i, s in meilleurs if s > 0]


def reciprocal_rank_fusion(
    classements: list[list[str]], k: int = 60, poids: list[float] | None = None
) -> dict[str, float]:
    """Fusionne plusieurs classements par Reciprocal Rank Fusion.

    RRF n'additionne pas les scores : ceux d'une recherche dense (distance
    cosine) et d'un BM25 (fréquence pondérée) ne vivent pas sur la même échelle
    et ne sont pas comparables. Il n'additionne que des RANGS, ce qui rend la
    fusion insensible à la calibration de chaque moteur.

    Les poids servent quand un classement est moins digne de confiance que les
    autres. Mesuré sur ce corpus : ajouter à poids égal les résultats de la
    question traduite gagne 16,7 points de rappel en translinguistique, mais en
    perd 6,9 sur les questions dont le document est déjà dans la bonne langue —
    la traduction y ramène du bruit qui chasse la bonne réponse du top-K.

    Args:
        classements: Listes d'identifiants, du mieux classé au moins bien.
        k: Constante d'amortissement. À 60 — la valeur de l'article d'origine —
            l'écart entre le 1er et le 2e pèse plus que celui entre le 50e et le
            51e, ce qui est le comportement voulu.
        poids: Un poids par classement. Absent, tous valent 1.

    Returns:
        Dict {identifiant: score fusionné}, à trier par score décroissant.
    """
    if poids is None:
        poids = [1.0] * len(classements)

    scores: dict[str, float] = {}
    for classement, poids_liste in zip(classements, poids, strict=False):
        for rang, identifiant in enumerate(classement, start=1):
            scores[identifiant] = scores.get(identifiant, 0.0) + poids_liste / (k + rang)
    return scores


def fuse(
    classements: list[list[ChunkResult]], top_k: int, poids: list[float] | None = None
) -> list[ChunkResult]:
    """Fusionne des classements hétérogènes et retourne les top_k.

    Un chunk présent dans plusieurs classements remonte : c'est tout l'intérêt
    de la fusion, et ce qu'aucun moteur ne sait faire seul. Le nombre de
    classements est libre — dense et lexical, dans la langue de la question et
    dans sa traduction, font quatre listes.

    Args:
        classements: Listes ordonnées, de la mieux classée à la moins bien. Les
            premières font foi sur les métadonnées en cas de doublon : la
            recherche dense y est placée en tête, car elle seule porte une
            distance vectorielle réelle.
        top_k: Nombre de résultats conservés.
        poids: Un poids par classement, pour ceux qui méritent moins de
            confiance — les résultats d'une question traduite, notamment.
    """
    par_id: dict[str, ChunkResult] = {}
    for classement in reversed(classements):
        par_id.update({c.chunk_id: c for c in classement})

    scores = reciprocal_rank_fusion(
        [[c.chunk_id for c in classement] for classement in classements],
        k=settings.rrf_k,
        poids=poids,
    )

    ordonnes = sorted(scores.items(), key=lambda t: t[1], reverse=True)
    resultat: list[ChunkResult] = []
    for chunk_id, score in ordonnes[:top_k]:
        chunk = par_id.get(chunk_id)
        if chunk is not None:
            chunk.fusion_score = score
            resultat.append(chunk)
    return resultat


def chunk_from_record(chunk_id: str, document: str, meta: dict[str, Any]) -> ChunkResult:
    """Construit un ChunkResult depuis un enregistrement ChromaDB brut.

    Utilisé pour les résultats lexicaux, qui n'ont pas de distance vectorielle :
    elle est laissée à 1.0 (la valeur la plus défavorable) pour qu'un départage
    par distance ne les avantage jamais indûment.
    """
    return ChunkResult(
        chunk_id=chunk_id,
        element_id=meta.get("element_id", ""),
        graph_node_id=meta.get("graph_node_id", ""),
        document=document,
        filename=meta.get("filename", ""),
        collection=meta.get("collection") or "",
        source_path=meta.get("source_path") or "",
        section_title=meta.get("section_title") or "",
        language=meta.get("language") or "",
        depth=int(meta.get("depth") or 0),
        page_no=int(meta.get("page_no") or 0),
        label=meta.get("label", ""),
        minio_url=meta.get("minio_url") or None,
        page_position=int(meta.get("page_position") or 0),
        ref_position=int(meta.get("ref_position") or 0),
        distance=1.0,
    )
