"""Réouverture des connexions mises en cache.

Les clients ChromaDB, NebulaGraph et MinIO sont mémorisés par `lru_cache`. Si un
store redémarre, l'objet mémorisé pointe vers une connexion morte et toutes les
requêtes échouent — jusqu'au redémarrage de l'agent lui-même. Chaque module doit
savoir oublier son cache et retenter une fois.
"""

import pytest

from src.agent import graph_context, minio_client, retriever

# ─── ChromaDB ─────────────────────────────────────────────────────────────────

def test_chroma_rouvre_la_collection_et_retente(monkeypatch) -> None:
    class DeadThenAlive:
        def __init__(self) -> None:
            self.calls = 0

        def query(self, **_):
            self.calls += 1
            if self.calls == 1:
                raise ConnectionError("ChromaDB a redémarré")
            return {"ids": [[]], "documents": [[]], "metadatas": [[]], "distances": [[]]}

    collection = DeadThenAlive()
    cleared = []

    monkeypatch.setattr(retriever, "_get_chroma_collection", lambda: collection)
    monkeypatch.setattr(retriever, "reset_connection", lambda: cleared.append(True))
    fake_model = type("M", (), {"encode": lambda _s, _q: _Vec()})()
    monkeypatch.setattr(retriever, "_get_embedding_model", lambda: fake_model)

    assert retriever.retrieve("question") == []
    assert collection.calls == 2  # noqa: PLR2004
    assert cleared == [True]


class _Vec:
    def tolist(self) -> list[float]:
        return [0.0, 0.1]


def test_chroma_ping_en_echec_oublie_le_cache(monkeypatch) -> None:
    cleared = []
    monkeypatch.setattr(retriever, "reset_connection", lambda: cleared.append(True))
    monkeypatch.setattr(
        retriever, "_get_chroma_collection", lambda: (_ for _ in ()).throw(ConnectionError())
    )

    assert retriever.ping() is False
    assert cleared == [True]


# ─── NebulaGraph ──────────────────────────────────────────────────────────────

def test_nebula_rouvre_le_pool_et_retente(monkeypatch) -> None:
    class Result:
        def is_succeeded(self) -> bool:
            return True

        def row_size(self) -> int:
            return 0

        def keys(self) -> list[str]:
            return []

    state = {"calls": 0}

    class Pool:
        def execute(self, _nql):
            state["calls"] += 1
            if state["calls"] == 1:
                raise ConnectionError("graphd a redémarré")
            return Result()

    cleared = []
    monkeypatch.setattr(graph_context, "_get_pool", Pool)
    monkeypatch.setattr(graph_context, "reset_connection", lambda: cleared.append(True))

    assert graph_context._execute("YIELD 1;") == []
    assert state["calls"] == 2  # noqa: PLR2004
    assert cleared == [True]


def test_nebula_propage_l_echec_si_la_reouverture_ne_suffit_pas(monkeypatch) -> None:
    class Pool:
        def execute(self, _nql):
            raise ConnectionError("graphd est mort")

    monkeypatch.setattr(graph_context, "_get_pool", Pool)
    monkeypatch.setattr(graph_context, "reset_connection", lambda: None)

    with pytest.raises(ConnectionError):
        graph_context._execute("YIELD 1;")


# ─── MinIO ────────────────────────────────────────────────────────────────────

def test_minio_recree_le_client_et_retente(monkeypatch) -> None:
    class Response:
        def read(self) -> bytes:
            return b"PNG"

        def close(self) -> None: ...

        def release_conn(self) -> None: ...

    state = {"calls": 0}

    class Client:
        def get_object(self, _bucket, _name):
            state["calls"] += 1
            if state["calls"] == 1:
                raise ConnectionError("MinIO a redémarré")
            return Response()

    cleared = []
    monkeypatch.setattr(minio_client, "_get_minio_client", Client)
    monkeypatch.setattr(minio_client, "reset_connection", lambda: cleared.append(True))

    assert minio_client.get_object_bytes("images/a/b.png") == b"PNG"
    assert state["calls"] == 2  # noqa: PLR2004
    assert cleared == [True]


def test_minio_abandonne_apres_un_second_echec(monkeypatch) -> None:
    class Client:
        def get_object(self, _bucket, _name):
            raise ConnectionError("MinIO est mort")

    monkeypatch.setattr(minio_client, "_get_minio_client", Client)
    monkeypatch.setattr(minio_client, "reset_connection", lambda: None)

    assert minio_client.get_object_bytes("images/a/b.png") is None


def test_minio_refuse_toujours_les_chemins_douteux(monkeypatch) -> None:
    """La réouverture ne doit pas affaiblir le garde-fou anti-traversal."""
    appels = []
    monkeypatch.setattr(minio_client, "_get_minio_client", lambda: appels.append(True))

    assert minio_client.get_object_bytes("../../etc/passwd") is None
    assert appels == []
