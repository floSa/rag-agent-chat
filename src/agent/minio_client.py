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

    minio_url est au format http://minio:9000/documents/images/{stem}/{id}_{type}.png
    On retire le host et le premier segment du path (nom du bucket).
    """
    parsed = urlparse(minio_url)
    path_parts = parsed.path.lstrip("/").split("/", 1)
    if len(path_parts) < 2:  # noqa: PLR2004
        return None
    return path_parts[1]


def to_media_path(minio_url: str) -> str:
    """Convertit une URL MinIO interne en chemin proxy /media servi par l'API.

    Les URLs (même pré-signées) construites sur l'endpoint interne minio:9000
    sont inaccessibles depuis le navigateur de l'utilisateur : c'est l'API
    FastAPI qui sert les objets via GET /media/{object_name}.
    """
    object_name = object_name_from_url(minio_url)
    if object_name is None:
        return minio_url  # URL non reconnue, retournée telle quelle
    return f"/media/{object_name}"


@lru_cache(maxsize=1)
def _allowed_objects() -> frozenset[str]:
    """Objets que le proxy accepte de servir, lus dans le graphe."""
    from src.agent.graph_context import media_object_names

    noms = frozenset(media_object_names())
    logger.info("Proxy média : %d objets autorisés.", len(noms))
    return noms


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
