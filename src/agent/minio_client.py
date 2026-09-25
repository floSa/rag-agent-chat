import logging
import re
from functools import lru_cache
from urllib.parse import urlparse

from minio import Minio

from src.agent.settings import settings

logger = logging.getLogger(__name__)

# Chemins d'objets autorisés (protection contre l'injection / traversal)
_OBJECT_NAME_RE = re.compile(r"^[\w\-./]+$")


def reset_connection() -> None:
    """Oublie le client mis en cache, pour le recréer au prochain appel."""
    _get_minio_client.cache_clear()


@lru_cache(maxsize=1)
def _get_minio_client() -> Minio:
    client = Minio(
        settings.minio_endpoint,
        access_key=settings.minio_root_user,
        secret_key=settings.minio_root_password,
        secure=settings.minio_secure,
    )
    logger.info("MinIO connecté : %s", settings.minio_endpoint)
    return client


def object_name_from_url(minio_url: str) -> str | None:
    """Extrait le chemin objet d'une URL MinIO interne.

    minio_url est au format http://seaweedfs:8333/documents/images/{stem}/{id}_{type}.png
    On retire le host et le premier segment du path (nom du bucket).
    """
    parsed = urlparse(minio_url)
    path_parts = parsed.path.lstrip("/").split("/", 1)
    if len(path_parts) < 2:  # noqa: PLR2004
        return None
    return path_parts[1]


def cle_objet(object_key: str | None, url: str | None) -> str | None:
    """La clé d'un objet du bucket : `object_key` s'il est publié, sinon déduite de l'URL.

    `object_key` est la propriété que le pipeline publie depuis la bascule de
    son stockage objet — §4.82 de `documentation/axes_amelioration.md`. Elle
    porte la clé NUE, et nous affranchit du décodage positionnel de l'URL, que
    le §4.62 a mesuré faux sur une URL en virtual-host style. Tant que les
    stores servis n'ont pas été réingérés, elle manque : la clé est alors
    déduite de l'URL, par la même règle qu'avant.
    """
    if object_key:
        return object_key
    if url:
        return object_name_from_url(url)
    return None


def to_media_path(minio_url: str, object_key: str | None = None) -> str:
    """Convertit une URL MinIO interne en chemin proxy /media servi par l'API.

    Les URLs (même pré-signées) construites sur l'endpoint interne seaweedfs:8333
    sont inaccessibles depuis le navigateur de l'utilisateur : c'est l'API
    FastAPI qui sert les objets via GET /media/{object_name}. La clé est
    `object_key` quand la source l'a publié — `cle_objet`.
    """
    object_name = cle_objet(object_key, minio_url)
    if object_name is None:
        return minio_url  # URL non reconnue, retournée telle quelle
    return f"/media/{object_name}"


class _ObjetsAutorises:
    """Le cache de la liste blanche du proxy — qui NE RETIENT JAMAIS UN VIDE.

    Un `lru_cache` mémorise ce qu'on lui rend, y compris `frozenset()`. Le
    25 septembre 2026 à 08:59 UTC, la session NebulaGraph du processus était
    périmée par une purge du pipeline, `media_object_names()` a rendu 0 clé, et
    ce 0 est devenu la vérité du proxy : TOUS les `GET /media/<clé>` ont rendu
    404 — §4.80 de `documentation/axes_amelioration.md`. Le graphe, lui, portait
    ses 212 objets ; un processus NEUF les rendait au même instant.

    Une liste blanche vide est donc traitée comme un SYMPTÔME et non comme un
    fait : elle est rendue à l'appelant — qui refusera, et c'est correct tant
    que le graphe ne dit rien — mais elle n'est pas retenue, si bien que l'appel
    suivant repart au graphe. Une liste NON vide reste mise en cache : le proxy
    est sur le chemin de CHAQUE image affichée, et la relire à chaque octet
    servi coûterait une requête nGQL par image.

    Cette classe remplace un `lru_cache` et en garde la surface exacte —
    `_allowed_objects()` et `_allowed_objects.cache_clear()` — parce que c'est
    la seule chose qu'un `lru_cache` ne sait pas faire : décider, au vu de la
    valeur, si elle mérite d'être retenue.
    """

    def __init__(self) -> None:
        self._noms: frozenset[str] | None = None

    def __call__(self) -> frozenset[str]:
        if self._noms is not None:
            return self._noms
        from src.agent.graph_context import media_object_names

        noms = frozenset(media_object_names())
        logger.info("Proxy média : %d objets autorisés.", len(noms))
        if noms:
            self._noms = noms
        return noms

    def cache_clear(self) -> None:
        self._noms = None


_allowed_objects = _ObjetsAutorises()


def is_allowed(object_name: str) -> bool:
    """L'objet est-il référencé par le graphe ?

    Un objet inconnu déclenche une relecture — un document fraîchement ingéré
    apporte de nouvelles illustrations, et l'agent ne redémarre pas pour
    autant. La relecture n'a lieu que sur un échec, donc jamais en régime
    normal.
    """
    if object_name in _allowed_objects():
        return True
    _allowed_objects.cache_clear()
    return object_name in _allowed_objects()


def get_object_bytes(object_name: str) -> bytes | None:
    """Télécharge un objet du bucket. Retourne None si invalide ou introuvable."""
    if ".." in object_name or not _OBJECT_NAME_RE.fullmatch(object_name):
        logger.warning("Chemin d'objet MinIO rejeté : %s", object_name[:120])
        return None

    if settings.restrict_media_to_graph and not is_allowed(object_name):
        logger.warning("Objet MinIO non référencé par le graphe : %s", object_name[:120])
        return None

    for attempt in (1, 2):
        response = None
        try:
            response = _get_minio_client().get_object(settings.minio_bucket, object_name)
            return response.read()
        except Exception:
            # Le client est mis en cache : si MinIO a redémarré, il pointe vers
            # une connexion morte. On le recrée et on retente une fois avant
            # de conclure que l'objet est introuvable.
            # Absorption LARGE parce que le SDK minio mêle ses `S3Error` aux
            # erreurs urllib3 d'un socket mort, sans ancêtre commun. Jamais
            # muette : WARNING au premier essai, pile complète au second.
            if attempt == 1:
                logger.warning("MinIO injoignable, recréation du client et nouvel essai.")
                reset_connection()
                continue
            logger.exception("Objet MinIO introuvable : %s", object_name)
            return None
        finally:
            if response is not None:
                response.close()
                response.release_conn()
    return None
