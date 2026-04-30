import logging
from functools import lru_cache

from minio import Minio

from src.agent.settings import settings

logger = logging.getLogger(__name__)


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


def get_presigned_url(minio_url: str, expires_seconds: int = 3600) -> str:
    """Génère une URL pré-signée valide pour l'affichage dans le frontend.

    minio_url est au format http://minio:9000/documents/images/{stem}/{id}_{type}.png
    On extrait le chemin de l'objet (object_name) depuis l'URL.
    """
    from datetime import timedelta
    from urllib.parse import urlparse

    parsed = urlparse(minio_url)
    # Le path est /documents/images/... → on retire le premier segment (bucket name)
    path_parts = parsed.path.lstrip("/").split("/", 1)
    if len(path_parts) < 2:  # noqa: PLR2004
        return minio_url  # URL déjà publique ou non reconnue

    object_name = path_parts[1]
    client = _get_minio_client()

    try:
        url = client.presigned_get_object(
            settings.minio_bucket,
            object_name,
            expires=timedelta(seconds=expires_seconds),
        )
        return url
    except Exception:
        logger.exception("Impossible de générer l'URL pré-signée pour %s", minio_url)
        return minio_url
