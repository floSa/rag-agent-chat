"""Surface exposée par l'API.

Trois défenses indépendantes : CORS restreint aux origines déclarées, clé d'API
optionnelle, et un proxy média qui ne sert que les objets référencés par le
graphe. Aucune ne suffit seule — le garde-fou anti-traversal empêche de sortir
du bucket, pas d'y fouiller.
"""

import pytest
from fastapi.testclient import TestClient

from src.agent import minio_client
from src.agent.settings import Settings


# ─── Clé d'API ────────────────────────────────────────────────────────────────

@pytest.fixture
def client(monkeypatch):
    from src.api import main

    monkeypatch.setattr(main.settings, "api_key", "secret-de-test")
    return TestClient(main.app)


def test_route_sans_cle_refusee(client) -> None:
    assert client.post("/search", json={"question": "test"}).status_code == 401  # noqa: PLR2004


def test_route_avec_mauvaise_cle_refusee(client) -> None:
    reponse = client.post("/search", json={"question": "q"}, headers={"X-API-Key": "faux"})
    assert reponse.status_code == 401  # noqa: PLR2004


def test_health_reste_interrogeable_sans_cle(client) -> None:
    """Une sonde doit fonctionner sans secret, sinon plus rien ne la surveille."""
    assert client.get("/health").status_code == 200  # noqa: PLR2004


def test_aucune_cle_configuree_laisse_passer(monkeypatch) -> None:
    """Déploiement local derrière un pare-feu : la dépendance ne fait rien."""
    from src.api import main

    monkeypatch.setattr(main.settings, "api_key", "")
    # Le corps invalide suffit : on vérifie qu'on dépasse l'authentification.
    assert TestClient(main.app).post("/search", json={}).status_code == 422  # noqa: PLR2004


# ─── CORS ─────────────────────────────────────────────────────────────────────

def test_origines_cors_par_defaut_ne_sont_pas_ouvertes() -> None:
    assert "*" not in Settings().cors_origin_list


def test_origines_cors_decoupees_et_nettoyees() -> None:
    settings = Settings(CORS_ORIGINS=" https://a.fr , https://b.fr ,, ")
    assert settings.cors_origin_list == ["https://a.fr", "https://b.fr"]


# ─── Proxy média ──────────────────────────────────────────────────────────────

def test_objet_non_reference_par_le_graphe_refuse(monkeypatch) -> None:
    appels = []
    monkeypatch.setattr(minio_client.settings, "restrict_media_to_graph", True)
    monkeypatch.setattr(minio_client, "is_allowed", lambda _n: False)
    monkeypatch.setattr(minio_client, "_get_minio_client", lambda: appels.append(True))

    assert minio_client.get_object_bytes("images/secret/dump.png") is None
    assert appels == []  # MinIO n'est même pas interrogé


def test_objet_reference_est_servi(monkeypatch) -> None:
    class Response:
        def read(self) -> bytes:
            return b"PNG"

        def close(self) -> None: ...

        def release_conn(self) -> None: ...

    class Client:
        def get_object(self, _bucket, _name):
            return Response()

    monkeypatch.setattr(minio_client.settings, "restrict_media_to_graph", True)
    monkeypatch.setattr(minio_client, "is_allowed", lambda _n: True)
    monkeypatch.setattr(minio_client, "_get_minio_client", Client)

    assert minio_client.get_object_bytes("images/doc/a_picture.png") == b"PNG"


def test_traversal_refuse_avant_toute_verification(monkeypatch) -> None:
    """L'ordre compte : un chemin malformé ne doit pas atteindre le graphe."""
    appels = []
    monkeypatch.setattr(minio_client, "is_allowed", lambda _n: appels.append(True) or True)

    assert minio_client.get_object_bytes("../../etc/passwd") is None
    assert appels == []


def test_relecture_de_l_autorisation_sur_objet_inconnu(monkeypatch) -> None:
    """Un document fraîchement ingéré apporte des illustrations ; l'agent ne
    redémarre pas pour autant."""
    etat = {"appels": 0}

    def noms() -> set[str]:
        etat["appels"] += 1
        # Absent au premier appel, présent après relecture.
        return {"images/doc/neuf.png"} if etat["appels"] > 1 else set()

    monkeypatch.setattr("src.agent.graph_context.media_object_names", noms)
    minio_client._allowed_objects.cache_clear()

    assert minio_client.is_allowed("images/doc/neuf.png") is True
    assert etat["appels"] == 2  # noqa: PLR2004
    minio_client._allowed_objects.cache_clear()
