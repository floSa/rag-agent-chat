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
from typing import Any

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


class LexicalIndex:
    """Index BM25 en mémoire, construit une fois et interrogé ensuite."""

    def __init__(self) -> None:
        self._bm25: BM25Okapi | None = None
        self._chunk_ids: list[str] = []
        self._lock = threading.Lock()

    @property
    def ready(self) -> bool:
        return self._bm25 is not None

    @property
    def size(self) -> int:
        return len(self._chunk_ids)

    def build(self, chunk_ids: list[str], documents: list[str]) -> None:
        """Construit l'index à partir des textes de la collection."""
        with self._lock:
            corpus = [tokenize(doc) for doc in documents]
            # BM25Okapi divise par la longueur moyenne des documents : un corpus
            # vide la rendrait nulle et ferait échouer chaque recherche.
            if not corpus:
                logger.warning("Index lexical non construit : corpus vide.")
                return
            self._bm25 = BM25Okapi(corpus)
            self._chunk_ids = chunk_ids
            logger.info("Index lexical BM25 construit : %d chunks.", len(chunk_ids))

    def search(self, question: str, top_k: int) -> list[tuple[str, float]]:
        """Retourne les (chunk_id, score) les mieux classés pour cette question."""
        if self._bm25 is None:
            return []
        jetons = tokenize(question)
        if not jetons:
            return []
        scores = self._bm25.get_scores(jetons)
        meilleurs = sorted(enumerate(scores), key=lambda t: t[1], reverse=True)[:top_k]
        return [(self._chunk_ids[i], float(s)) for i, s in meilleurs if s > 0]


def reciprocal_rank_fusion(
    classements: list[list[str]], k: int = 60
) -> dict[str, float]:
    """Fusionne plusieurs classements par Reciprocal Rank Fusion.

    RRF n'additionne pas les scores : ceux d'une recherche dense (distance
    cosine) et d'un BM25 (fréquence pondérée) ne vivent pas sur la même échelle
    et ne sont pas comparables. Il n'additionne que des RANGS, ce qui rend la
    fusion insensible à la calibration de chaque moteur.

    Args:
        classements: Listes d'identifiants, du mieux classé au moins bien.
        k: Constante d'amortissement. À 60 — la valeur de l'article d'origine —
            l'écart entre le 1er et le 2e pèse plus que celui entre le 50e et le
            51e, ce qui est le comportement voulu.

    Returns:
        Dict {identifiant: score fusionné}, à trier par score décroissant.
    """
    scores: dict[str, float] = {}
    for classement in classements:
        for rang, identifiant in enumerate(classement, start=1):
            scores[identifiant] = scores.get(identifiant, 0.0) + 1.0 / (k + rang)
    return scores


def fuse(classements: list[list[ChunkResult]], top_k: int) -> list[ChunkResult]:
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
    """
    par_id: dict[str, ChunkResult] = {}
    for classement in reversed(classements):
        par_id.update({c.chunk_id: c for c in classement})

    scores = reciprocal_rank_fusion(
        [[c.chunk_id for c in classement] for classement in classements],
        k=settings.rrf_k,
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
