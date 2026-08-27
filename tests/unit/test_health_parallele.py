"""/health ne doit pas empêcher le démarrage.

`docker-compose.yml` coupe le healthcheck à 5 s et `frontend` attend `agent-api`
en `service_healthy`. Quatre sondes enchaînées en séquence, sans stores
joignables, dépassent ce délai : curl est tué, les cinq tentatives échouent,
`agent-api` finit `unhealthy` et le frontend ne démarre JAMAIS — alors que l'API
aurait répondu 200 `degraded`, ce qu'elle est écrite pour faire. Le healthcheck
annulait l'intention du code.

Trois pièges ont dicté la forme de ces tests.

- Un test qui n'assère que « moins de 5 s » reste vert sur des sondes
  SÉQUENTIELLES rapides : il ne prouve pas le parallélisme. Celui-ci est donc
  prouvé par une BARRIÈRE à quatre parties — une implémentation séquentielle ne
  peut pas la franchir, quelle que soit la vitesse de chaque sonde. C'est plus
  fort qu'un chronomètre, et ça n'attend aucune seconde quand c'est vert.
- Une sonde qui DORT ne prouve rien de ce qui nous intéresse : c'est une sonde
  qui NE REVIENT PAS qu'il faut simuler, et il faut pouvoir la débloquer au
  démontage, sans quoi les fils du threadpool retiennent l'interpréteur à la
  sortie. D'où `_SondeMuette`, débloquée dans un `finally`.
- Un plafond ne se vérifie qu'à sa valeur réelle : un test qui règle lui-même le
  plafond reste vert le jour où la valeur par défaut passe à 60 s. Un seul test
  paie donc le plafond réel (~3 s) ; les autres le raccourcissent pour ne rien
  coûter.
"""

import re
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# ─── Outillage ────────────────────────────────────────────────────────────────

_RACINE = Path(__file__).resolve().parents[2]

# Plafond de sécurité des sondes muettes. Il ne borne PAS la durée du test quand
# le correctif est en place — le plafond de /health revient bien avant — mais il
# borne celle d'un ÉCHEC : sur une implémentation séquentielle, /health attend
# ici quatre fois cette valeur avant de rendre. Assez grand pour dépasser le
# délai du healthcheck, assez petit pour qu'un rouge reste lisible.
_CAP_SECURITE_S = 8.0


def _delai_du_healthcheck() -> float:
    """Le délai que docker-compose accorde à /health, LU dans le fichier.

    Recopié en dur ici, le lien entre le plafond du code et le contrat de
    déploiement serait invisible : c'est ce contrat qui donne au plafond sa
    valeur, et il vit dans un autre fichier que celui qu'on corrige.
    """
    texte = (_RACINE / "docker-compose.yml").read_text(encoding="utf-8")
    delais = re.findall(r"^\s+timeout:\s*(\d+)s\s*$", texte, re.MULTILINE)
    assert len(delais) == 1, "plusieurs timeouts dans docker-compose.yml : préciser lequel"
    return float(delais[0])


class _SondeMuette:
    """Sonde synchrone qui ne rend la main que sur ordre du test.

    Compte ses ENTRÉES : c'est le seul moyen de voir qu'un fil abandonné n'a pas
    été relancé à l'appel suivant. Le plafond de sécurité évite qu'un test
    oublieux laisse un fil non-démon retenir l'interpréteur.
    """

    def __init__(self, plafond: float = _CAP_SECURITE_S) -> None:
        self.debloquer = threading.Event()
        self.entrees = 0
        self._plafond = plafond

    def __call__(self) -> bool:
        self.entrees += 1
        self.debloquer.wait(self._plafond)
        return True


class _SondesMuettes:
    """Les trois sondes synchrones, plus le faux client Ollama, toutes muettes."""

    def __init__(self, plafond: float = _CAP_SECURITE_S) -> None:
        self.chromadb = _SondeMuette(plafond)
        self.nebulagraph = _SondeMuette(plafond)
        self.index_lexical = _SondeMuette(plafond)
        self.ollama = _SondeMuette(plafond)

    def liberer(self) -> None:
        for sonde in (self.chromadb, self.nebulagraph, self.index_lexical, self.ollama):
            sonde.debloquer.set()

    def client_ollama(self):
        """Faux `httpx.AsyncClient` dont le GET passe par la sonde muette.

        La sonde tourne dans le threadpool, comme les trois autres : sans cela le
        GET bloquerait la boucle et les autres tâches n'auraient jamais démarré.
        """
        from anyio import to_thread

        sonde = self.ollama

        class Client:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *_):
                return False

            async def get(self, *_args, **_kwargs):
                await to_thread.run_sync(sonde, abandon_on_cancel=True)

                # Une fois débloquée, la sonde répond NON : elle a répondu, donc
                # ce n'est plus un inconnu. Lever ici confondrait les deux cas.
                class Reponse:
                    status_code = 503

                return Reponse()

        return lambda **_kwargs: Client()


def _ollama_repond_vrai():
    class Reponse:
        status_code = 200

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return False

        async def get(self, *_args, **_kwargs):
            return Reponse()

    return lambda **_kwargs: Client()


def _brancher(monkeypatch, sondes: _SondesMuettes) -> None:
    from src.api import main

    monkeypatch.setattr(main.settings, "api_key", "")
    monkeypatch.setattr(main, "chroma_ping", sondes.chromadb)
    monkeypatch.setattr(main, "nebula_ping", sondes.nebulagraph)
    monkeypatch.setattr(main, "lexical_ready", sondes.index_lexical)
    monkeypatch.setattr(main.httpx, "AsyncClient", sondes.client_ollama())


@pytest.fixture(autouse=True)
def _sans_sonde_en_vol():
    """Les drapeaux « en vol » sont un état de module : un test qui abandonne une
    sonde le laisse posé, et le test suivant croirait la sonde encore en vol.
    """
    from src.api import main

    main._sondes_en_vol.clear()
    yield
    main._sondes_en_vol.clear()


# ─── Le défaut ────────────────────────────────────────────────────────────────

def test_quatre_dependances_muettes_repondent_sous_le_delai_du_healthcheck(monkeypatch) -> None:
    """LE test du lot : rouge sur main, où les quatre sondes s'enchaînent.

    Le plafond réel est en jeu ici — aucun raccourci — parce que c'est la seule
    valeur que Docker mesure. Le prix est une attente d'environ un plafond.
    """
    from src.api import main

    sondes = _SondesMuettes()
    _brancher(monkeypatch, sondes)
    try:
        debut = time.monotonic()
        reponse = TestClient(main.app).get("/health")
        ecoule = time.monotonic() - debut
    finally:
        sondes.liberer()

    assert reponse.status_code == 200
    assert ecoule < _delai_du_healthcheck(), (
        f"/health a mis {ecoule:.1f} s : curl est tué avant, donc agent-api "
        "passe unhealthy et le frontend n'est jamais démarré"
    )
    corps = reponse.json()
    assert corps["status"] == "degraded"
    assert corps["services"] == {
        "chromadb": False,
        "nebulagraph": False,
        "index_lexical": False,
        "ollama": False,
    }
    # L'exécution n'est plus ordonnée, la RÉPONSE doit l'être : les deux champs
    # sont publiés dans l'ordre de la table des sondes, pas dans celui des
    # retours, sans quoi un exploitant lirait un ordre qui change à chaque appel.
    assert corps["services_unknown"] == [
        "chromadb",
        "nebulagraph",
        "index_lexical",
        "ollama",
    ]


def test_le_plafond_laisse_une_marge_au_delai_du_healthcheck() -> None:
    """Le plafond n'a de sens que devant le délai de docker-compose.

    Épingle les deux valeurs ensemble : relever le plafond à 6 s, ou abaisser le
    délai du healthcheck à 2 s, rendrait le correctif inopérant sans qu'aucun
    autre test ne bouge.
    """
    from src.api import main

    assert _delai_du_healthcheck() > main._PLAFOND_SONDES_S


# ─── Le parallélisme, et non la seule borne ───────────────────────────────────

def test_les_quatre_sondes_tournent_bien_en_meme_temps(monkeypatch) -> None:
    """Barrière à quatre : une sonde ne la franchit que si les trois autres y sont.

    Une implémentation séquentielle ne peut pas la franchir — la première sonde
    attend trois arrivantes qui ne partiront qu'après elle — et la barrière casse
    au bout de son délai. C'est ce qui distingue ce test d'un chronomètre : il
    reste rouge sur des sondes séquentielles RAPIDES, où « moins de 5 s » passe.
    """
    from anyio import to_thread

    from src.api import main

    barriere = threading.Barrier(4)
    cassees: list[str] = []

    def sonde(nom: str):
        def _sonde() -> bool:
            try:
                barriere.wait(timeout=2.0)
            except threading.BrokenBarrierError:
                cassees.append(nom)
                return False
            return True

        return _sonde

    monkeypatch.setattr(main.settings, "api_key", "")
    monkeypatch.setattr(main, "chroma_ping", sonde("chromadb"))
    monkeypatch.setattr(main, "nebula_ping", sonde("nebulagraph"))
    monkeypatch.setattr(main, "lexical_ready", sonde("index_lexical"))

    sonde_ollama = sonde("ollama")

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return False

        async def get(self, *_args, **_kwargs):
            joint = await to_thread.run_sync(sonde_ollama)

            class Reponse:
                status_code = 200 if joint else 503

            return Reponse()

    monkeypatch.setattr(main.httpx, "AsyncClient", lambda **_kwargs: Client())

    corps = TestClient(main.app).get("/health").json()

    assert cassees == [], f"sondes qui n'ont pas trouvé les autres à la barrière : {cassees}"
    assert corps["services"] == {
        "chromadb": True,
        "nebulagraph": True,
        "index_lexical": True,
        "ollama": True,
    }
    assert corps["status"] == "ok"


# ─── Ce qu'une sonde qui n'est pas revenue vaut dans la réponse ───────────────

def test_une_sonde_non_revenue_est_publiee_fausse_et_nommee(monkeypatch) -> None:
    """« Pas revenue » n'est pas « tombée », et les deux doivent être lisibles.

    `services` reste un `dict[str, bool]` : le healthcheck et l'exploitant ne
    doivent en aucun cas lire « je n'ai pas eu le temps de regarder » comme « ça
    répond ». Mais l'information existe — c'est un fait sur l'agent, pas sur le
    service — et `services_unknown` la porte.
    """
    from src.api import main

    monkeypatch.setattr(main, "_PLAFOND_SONDES_S", 0.2)
    sondes = _SondesMuettes()
    _brancher(monkeypatch, sondes)
    monkeypatch.setattr(main, "nebula_ping", lambda: True)
    monkeypatch.setattr(main, "lexical_ready", lambda: True)
    try:
        corps = TestClient(main.app).get("/health").json()
    finally:
        sondes.liberer()

    assert corps["services"]["chromadb"] is False
    assert corps["services"]["nebulagraph"] is True
    assert corps["services_unknown"] == ["chromadb", "ollama"]
    assert corps["status"] == "degraded"


def test_un_index_lexical_non_revenu_ne_degrade_pas_le_statut(monkeypatch) -> None:
    """Décision du lot 3, inchangée : l'index n'est pas une dépendance.

    Son absence dégrade la recherche, elle ne l'empêche pas, et le healthcheck ne
    doit pas redémarrer le service pour ça. Une sonde d'index qui EXPIRE ne doit
    donc pas plus dégrader le statut que son faux.
    """
    from src.api import main

    monkeypatch.setattr(main, "_PLAFOND_SONDES_S", 0.2)
    monkeypatch.setattr(main.settings, "api_key", "")
    monkeypatch.setattr(main, "chroma_ping", lambda: True)
    monkeypatch.setattr(main, "nebula_ping", lambda: True)
    monkeypatch.setattr(main.httpx, "AsyncClient", _ollama_repond_vrai())
    muette = _SondeMuette()
    monkeypatch.setattr(main, "lexical_ready", muette)
    try:
        corps = TestClient(main.app).get("/health").json()
    finally:
        muette.debloquer.set()

    assert corps["services_unknown"] == ["index_lexical"]
    assert corps["services"]["index_lexical"] is False
    assert corps["status"] == "ok"


# ─── Les fils abandonnés ──────────────────────────────────────────────────────

def test_une_sonde_toujours_en_vol_ne_relance_pas_un_second_fil(monkeypatch, caplog) -> None:
    """Le piège de ce lot : un plafond n'interrompt pas un fil, il le lâche.

    `to_thread.run_sync` ne peut pas tuer un fil bloqué dans un appel réseau.
    Sans garde, un healthcheck toutes les 20 s contre un store muet pendant deux
    minutes lâcherait six fils par sonde — dans le threadpool que les endpoints
    de recherche partagent. Le garde plafonne à UN fil par sonde : tant que le
    précédent n'est pas revenu, /health ne relance rien et republie l'inconnu.
    """
    import logging

    from src.api import main

    monkeypatch.setattr(main, "_PLAFOND_SONDES_S", 0.2)
    sondes = _SondesMuettes()
    _brancher(monkeypatch, sondes)
    try:
        client = TestClient(main.app)
        with caplog.at_level(logging.WARNING, logger="src.api.main"):
            premier = client.get("/health").json()
        deuxieme = client.get("/health").json()
        troisieme = client.get("/health").json()
    finally:
        sondes.liberer()

    assert sondes.chromadb.entrees == 1, "un second fil a été lâché sur une sonde déjà en vol"
    assert sondes.nebulagraph.entrees == 1
    assert sondes.index_lexical.entrees == 1
    for corps in (premier, deuxieme, troisieme):
        assert corps["services"]["chromadb"] is False
        assert "chromadb" in corps["services_unknown"]
    assert any("chromadb" in message for message in caplog.messages), (
        "l'abandon d'un fil doit se voir dans le journal, une fois"
    )


def test_le_fil_revenu_rend_la_sonde_a_nouveau_interrogeable(monkeypatch) -> None:
    """Le garde ne doit pas être un aller simple.

    Sans le retrait du drapeau par le fil lui-même, la sonde resterait
    définitivement « en vol » et /health publierait un inconnu perpétuel : la
    panne serait remplacée par une cécité.
    """
    from src.api import main

    monkeypatch.setattr(main, "_PLAFOND_SONDES_S", 0.2)
    sondes = _SondesMuettes()
    _brancher(monkeypatch, sondes)
    client = TestClient(main.app)
    try:
        client.get("/health")
    finally:
        sondes.liberer()

    for _ in range(50):
        if not main._sondes_en_vol:
            break
        time.sleep(0.02)

    corps = client.get("/health").json()

    assert sondes.chromadb.entrees == 2, "la sonde revenue doit être réinterrogée"
    assert corps["services"]["chromadb"] is True
    assert corps["services_unknown"] == [], "toutes les sondes ont répondu au second appel"


# ─── 200 dans tous les cas de panne ───────────────────────────────────────────

def test_une_sonde_qui_leve_ne_fait_pas_tomber_health(monkeypatch, caplog) -> None:
    """Une sonde qui lève est un défaut de programmation, pas une panne.

    Elle doit être JOURNALISÉE et publiée fausse, jamais absorbée en silence, et
    surtout pas propagée : /health qui rend 500 fait redémarrer le service en
    boucle, ce que le code dit vouloir éviter depuis toujours.
    """
    import logging

    from src.api import main

    def sonde_cassee() -> bool:
        raise RuntimeError("le pilote Chroma a changé de signature")

    monkeypatch.setattr(main.settings, "api_key", "")
    monkeypatch.setattr(main, "chroma_ping", sonde_cassee)
    monkeypatch.setattr(main, "nebula_ping", lambda: True)
    monkeypatch.setattr(main, "lexical_ready", lambda: True)
    monkeypatch.setattr(main.httpx, "AsyncClient", _ollama_repond_vrai())

    with caplog.at_level(logging.WARNING, logger="src.api.main"):
        reponse = TestClient(main.app).get("/health")

    assert reponse.status_code == 200
    corps = reponse.json()
    assert corps["services"]["chromadb"] is False
    # Elle a répondu, en levant : ce n'est pas un inconnu, c'est un non.
    assert corps["services_unknown"] == []
    assert corps["status"] == "degraded"
    assert any("chroma" in message.lower() for message in caplog.messages)


def test_une_url_ollama_invalide_ne_fait_pas_tomber_health(monkeypatch, caplog) -> None:
    """`httpx.InvalidURL` n'hérite pas de `HTTPError` — décision écrite au lot 3.

    La sonde ne l'attrape donc pas, et c'est voulu : un OLLAMA_HOST mal formé est
    une erreur de configuration, pas une panne de service. Mais /health ne doit
    pas tomber pour autant, sinon le service redémarre en boucle sur une faute de
    frappe dans un `.env`.

    Le host est choisi pour lever cette exception-là, et l'épinglage ci-dessous
    est ce qui rend ce test honnête : une URL sans schéma lève
    `httpx.UnsupportedProtocol`, qui EST une `HTTPError` et que la sonde
    rattrape. Écrite ainsi, l'assertion serait passée par le chemin ordinaire en
    prétendant vérifier l'autre — c'est le premier host que j'avais mis.
    """
    import logging

    import httpx

    from src.api import main

    host = "http://héberge ur:8000"
    with pytest.raises(httpx.InvalidURL):
        httpx.URL(f"{host}/api/tags")

    monkeypatch.setattr(main.settings, "api_key", "")
    monkeypatch.setattr(main, "chroma_ping", lambda: True)
    monkeypatch.setattr(main, "nebula_ping", lambda: True)
    monkeypatch.setattr(main, "lexical_ready", lambda: True)
    monkeypatch.setattr(main.settings, "ollama_host", host)

    with caplog.at_level(logging.WARNING, logger="src.api.main"):
        reponse = TestClient(main.app).get("/health")

    assert reponse.status_code == 200
    assert reponse.json()["services"]["ollama"] is False
    assert reponse.json()["status"] == "degraded"
    assert any("ollama" in message.lower() for message in caplog.messages)


# ─── Ce qui reste hors du plafond ─────────────────────────────────────────────

def test_la_lecture_de_la_base_de_capture_est_sous_le_plafond(monkeypatch) -> None:
    """Un plafond qui ne couvre pas tout est un plafond qui mentira un jour.

    `usage_stats` ouvre SQLite avec un `busy_timeout` de 5 s : posé autour des
    seules sondes, le plafond de 3 s laisserait /health dépasser le délai du
    healthcheck sans qu'aucune sonde soit en cause.
    """
    import asyncio

    from src.api import main

    monkeypatch.setattr(main, "_PLAFOND_SONDES_S", 0.2)
    monkeypatch.setattr(main.settings, "api_key", "")
    monkeypatch.setattr(main, "chroma_ping", lambda: True)
    monkeypatch.setattr(main, "nebula_ping", lambda: True)
    monkeypatch.setattr(main, "lexical_ready", lambda: True)
    monkeypatch.setattr(main.httpx, "AsyncClient", _ollama_repond_vrai())

    async def base_verrouillee():
        await asyncio.sleep(30)
        raise AssertionError("jamais atteint")

    monkeypatch.setattr(main, "usage_stats", base_verrouillee)

    debut = time.monotonic()
    reponse = TestClient(main.app).get("/health")
    ecoule = time.monotonic() - debut

    assert reponse.status_code == 200
    assert ecoule < 5.0, f"/health a mis {ecoule:.1f} s hors sondes"
    # `usage` est déjà optionnel dans le contrat : l'absence se dit en null,
    # elle ne s'invente pas en zéros — qui décriraient une base vide.
    assert reponse.json()["usage"] is None
    assert reponse.json()["status"] == "ok"
