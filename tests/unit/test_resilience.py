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
    # L'autorisation par le graphe est testée ailleurs : ici on isole la
    # réouverture de connexion.
    monkeypatch.setattr(minio_client, "is_allowed", lambda _n: True)
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
    monkeypatch.setattr(minio_client, "is_allowed", lambda _n: True)
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


def test_nebula_rouvre_le_pool_pour_les_proprietes_d_un_noeud(monkeypatch) -> None:
    """`_get_node_properties` contournait la reprise, et c'est le chemin le plus chaud.

    Elle appelait `_get_pool().execute(...)` directement, pour une raison réelle —
    elle a besoin du `ValueWrapper` de vertex brut, que `_to_primitive` aplatit —
    mais elle perdait les deux choses que `_execute` apporte : la réouverture du
    pool et le journal de l'erreur nGQL.

    Elle est appelée constamment : remontée vers le Document, recherche de section
    voisine jusqu'à cinq fois par direction, titre de chaque voisine. Après un
    redémarrage du graphd, les autres chemins se rétablissaient ; celui-là
    remontait l'exception jusqu'au try/except par élément de
    `node_reconstruct_context`, et la source disparaissait de la réponse.
    """
    class Node:
        def tags(self) -> list[str]:
            return ["SectionHeader"]

        def properties(self, _tag):
            return {"label": _Chaine("section_header"), "text": _Chaine("Dispersion")}

    class Vertex:
        def is_vertex(self) -> bool:
            return True

        def as_node(self):
            return Node()

    class Result:
        def is_succeeded(self) -> bool:
            return True

        def row_size(self) -> int:
            return 1

        def row_values(self, _i):
            return [Vertex()]

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

    props = graph_context._get_node_properties("1730443c8f")

    assert props["tag"] == "SectionHeader"
    assert props["text"] == "Dispersion"
    assert state["calls"] == 2  # noqa: PLR2004
    assert cleared == [True]


class _Chaine:
    """ValueWrapper nebula3 réduit à ce que `_to_primitive` en lit."""

    def __init__(self, valeur: str) -> None:
        self.valeur = valeur

    def is_string(self) -> bool:
        return True

    def as_string(self) -> str:
        return self.valeur

    def is_int(self) -> bool:
        return False

    def is_null(self) -> bool:
        return False


def test_une_requete_de_proprietes_en_echec_dit_pourquoi(monkeypatch, caplog) -> None:
    """Un nGQL refusé sur ce chemin ne laissait aucune trace.

    La fonction rendait `{}` sans un mot : l'appelant voyait un nœud sans
    propriétés, exactement comme un nœud qui n'existe pas. Le message d'erreur
    nGQL — le seul qui dise ce qui a été refusé — était jeté.
    """
    import logging

    class Result:
        def is_succeeded(self) -> bool:
            return False

        def error_msg(self) -> str:
            return "SemanticError: `label' unknown"

    class Pool:
        def execute(self, _nql):
            return Result()

    monkeypatch.setattr(graph_context, "_get_pool", Pool)
    monkeypatch.setattr(graph_context, "reset_connection", lambda: None)

    with caplog.at_level(logging.ERROR):
        assert graph_context._get_node_properties("1730443c8f") == {}

    messages = [e.getMessage() for e in caplog.records if e.levelno >= logging.ERROR]
    assert any("SemanticError" in m and "FETCH PROP" in m for m in messages)
