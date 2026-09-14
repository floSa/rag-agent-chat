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
    # CETTE LIGNE EST INERTE AUJOURD'HUI, et le motif gardien qu'elle portait a
    # été retiré le 14 septembre 2026 — NB-D de l'audit de REPAR-13. Il disait
    # « sans cette ligne, cette scène mesurerait la propriété qu'elle vise SUR UN
    # SERVICE DÉGRADÉ », et c'est faux ici : `mesuré` par retrait de cette seule
    # ligne, `rc(pytest)=0` sur les trois fichiers du motif. Les quatre tests qui
    # passent par cette aide (`:381`, `:510`, `:574`, `:606`) n'asserent rien qui
    # dépende du périphérique.
    #
    # ELLE EST CONSERVÉE QUAND MÊME, comme les huit autres lignes inertes du
    # motif : le jour où une scène branchée par `_brancher` lira `/health`, le
    # défaut `cuda` dans un venv torch CPU la dégraderait à lui seul. Elle
    # protège une scène à venir, pas celle-ci — et c'est tout ce qu'elle
    # prétend. Le compte complet (15 lignes, 6 qui mordent, 9 inertes, 8 tests)
    # et sa recette sont au §4.52 du registre, son seul site canonique.
    monkeypatch.setattr(main.settings, "torch_device", "cpu")
    monkeypatch.setattr(main, "chroma_ping", sondes.chromadb)
    monkeypatch.setattr(main, "nebula_ping", sondes.nebulagraph)
    monkeypatch.setattr(main, "lexical_ready", sondes.index_lexical)
    monkeypatch.setattr(main.httpx, "AsyncClient", sondes.client_ollama())


@pytest.fixture(autouse=True)
def _concordance_du_modele_embedding_neutre(monkeypatch):
    """Ce fichier mesure le parallélisme de /health, pas la concordance.

    Depuis le lot 3, /health lit aussi l'estampille du modèle d'embedding de la
    collection. Non branchée, cette lecture ouvrirait une VRAIE connexion vers
    l'hôte `chromadb` : ces tests dépendraient alors d'un échec de résolution DNS
    pour rester rapides et verts — un montage qui tient par accident et qui
    changerait de comportement le jour où ce nom se résout.

    Branchée sur l'état concordant, elle ne dégrade rien et ne coûte rien. Ce que
    /health publie de la concordance est gardé dans
    `tests/unit/test_garde_modele_embedding.py`, pas ici.
    """
    from src.agent.settings import settings
    from src.api import main
    from src.api.schemas import EmbeddingModelHealth

    monkeypatch.setattr(
        main,
        "etat_modele_embedding",
        lambda: EmbeddingModelHealth(
            status="ok",
            expected=settings.embedding_model_name,
            collection=settings.embedding_model_name,
        ),
    )


@pytest.fixture(autouse=True)
def _sans_sonde_en_vol():
    """Les drapeaux « en vol » sont un état de module : un test qui abandonne une
    sonde le laisse posé, et le test suivant croirait la sonde encore en vol.
    """
    from src.api import main

    main._sondes_en_vol.clear()
    yield
    main._sondes_en_vol.clear()


# ─── Le RÉSERVOIR DE FILS, et la sonde qu'il affamait ────────────────────────
#
# CE QUE CES DEUX GARDES FERMENT — B-3 de l'audit du 14 septembre 2026, et c'est
# un mensonge NOUVEAU, dans l'autre sens que celui que le lot 12 existait pour
# fermer. `/search` et `/sources` sont des `def` : Starlette les exécute dans le
# threadpool d'AnyIO. `_sonder` passe par `to_thread.run_sync`, c'est-à-dire LE
# MÊME réservoir, dont le limiteur par défaut vaut **40** (`mesuré`, anyio
# 4.15.1). Et `borne_des_etages_torch()` fait un `.acquire()` BLOQUANT DANS LE
# FIL : une requête qui attend son permis ne rend pas son fil. Le sémaphore
# convertissait donc une saturation de carte en saturation du réservoir que les
# sondes de `/health` utilisent.
#
# CE QUE `/health` PUBLIAIT ALORS, et c'est pire qu'un 503 honnête : `degraded`
# avec `chromadb`, `nebulagraph` et `index_lexical` à **false** — trois stores
# parfaitement sains, déclarés en panne parce qu'aucun fil n'était libre pour
# les interroger. `mesuré` par l'audit sur l'application réelle : 13 appels sur
# 197 à 3,00 s pile (le plafond des sondes) ; borne désarmée, 1 sur 29.
#
# LE GESTE : les sondes ont leur PROPRE limiteur de capacité, indépendant de
# celui des endpoints. Les deux gardes ci-dessous éprouvent les deux moitiés —
# le mécanisme (une sonde revient) et le corps publié (les stores sont vrais).
#
# LES DEUX SATURENT LE RÉSERVOIR À SA VALEUR RÉELLE, lue sur le limiteur et non
# recopiée : un test qui fixerait lui-même 2 jetons resterait vert le jour où le
# défaut d'AnyIO change, et c'est la forme de garde que ce chantier a payée.


async def _saturer_le_reservoir_par_defaut(tg, liberer: threading.Event) -> int:
    """Occupe TOUS les jetons du limiteur de fils par défaut, et rend leur nombre.

    C'est la scène de `/search` sous une borne pleine : des fils du réservoir
    partagé, pris et non rendus, pour une raison qui n'a rien à voir avec la
    santé du service.

    L'ATTENTE EST ASYNCHRONE, ET C'EST UNE CORRECTION CONTRE MOI-MÊME. La
    première version de ce banc attendait les fils par un `Semaphore.acquire()`
    synchrone : il bloquait la boucle d'événements, donc les tâches posées par
    `start_soon` ne DÉMARRAIENT jamais, et le réservoir n'était jamais saturé.
    Les deux gardes rougissaient — mais sur le banc, pas sur le défaut. Un rouge
    dont on n'a pas vérifié la RAISON ne vaut pas mieux qu'un vert.
    """
    from functools import partial

    import anyio
    import anyio.to_thread

    jetons = int(anyio.to_thread.current_default_thread_limiter().total_tokens)
    compte = {"entres": 0}
    verrou = threading.Lock()

    def _occuper() -> None:
        with verrou:
            compte["entres"] += 1
        liberer.wait(_CAP_SECURITE_S)

    for _ in range(jetons):
        tg.start_soon(partial(anyio.to_thread.run_sync, _occuper, abandon_on_cancel=True))

    limite = time.monotonic() + _CAP_SECURITE_S
    while True:
        with verrou:
            if compte["entres"] >= jetons:
                return jetons
        assert time.monotonic() < limite, (
            f"le réservoir n'a pas été saturé — {compte['entres']} fils entrés sur "
            f"{jetons}. Le banc ne mesure pas sa scène"
        )
        await anyio.sleep(0.005)


def test_une_sonde_de_health_revient_quand_le_reservoir_des_recherches_est_plein() -> None:
    """LE MÉCANISME : `_sonder` ne fait pas la queue derrière les requêtes torch.

    Éprouvé sur `_sonder` lui-même et non sur un double : c'est le site qui
    choisit le réservoir, et c'est donc le seul endroit où la propriété existe.

    La sonde employée est INERTE — elle rend `True` sans rien toucher. Si elle
    ne revient pas, ce n'est pas parce qu'elle est lente : c'est parce qu'aucun
    fil ne lui a été accordé.
    """
    import anyio

    from src.api import main

    resultat: dict[str, object] = {}

    async def scenario() -> None:
        liberer = threading.Event()
        async with anyio.create_task_group() as tg:
            resultat["jetons"] = await _saturer_le_reservoir_par_defaut(tg, liberer)
            debut = time.monotonic()
            # Plafond de banc, très en deçà des 3,00 s du plafond des sondes :
            # une sonde inerte qui met plus d'une seconde n'attend pas son
            # verdict, elle attend un FIL.
            with anyio.move_on_after(1.0):
                resultat["rendu"] = await main._sonder(
                    "essai", lambda: True, appelant="/health"
                )
            resultat["duree"] = round(time.monotonic() - debut, 3)
            liberer.set()

    anyio.run(scenario)

    assert resultat.get("rendu") is True, (
        f"la sonde n'est pas revenue en 1,0 s avec {resultat.get('jetons')} fils du "
        f"réservoir par défaut occupés (durée {resultat.get('duree')} s). Les sondes "
        "de `/health` font la queue derrière les requêtes de recherche : sous une "
        "borne torch pleine, la route de santé publie `false` sur des dépendances "
        "saines. Il leur faut leur propre limiteur"
    )


def test_health_publie_ses_stores_vrais_quand_le_reservoir_des_recherches_est_plein(
    monkeypatch,
) -> None:
    """LE CORPS PUBLIÉ, qui est ce que l'exploitant lit.

    Le jumeau du précédent, un cran plus haut : celui-là prouve qu'une sonde
    revient, celui-ci que `/health` ne dit plus « trois stores en panne » quand
    les trois vont bien. C'est l'affirmation exacte que l'audit a mesurée fausse
    — `degraded`, `chromadb`/`nebulagraph`/`index_lexical` à `false`.

    `health()` est appelée directement et non par `TestClient` : le limiteur de
    fils est un `RunVar`, donc propre à la boucle, et le portal du client en
    ouvrirait une AUTRE — le banc ne saturerait alors pas le réservoir que les
    sondes utilisent, et resterait vert sans rien mesurer.
    """
    import anyio

    from src.api import main

    monkeypatch.setattr(main.settings, "api_key", "")
    monkeypatch.setattr(main.settings, "torch_device", "cpu")
    # Les trois stores vont BIEN et répondent instantanément. Tout `false`
    # publié ci-dessous vient donc du réservoir, et de rien d'autre.
    monkeypatch.setattr(main, "chroma_ping", lambda: True)
    monkeypatch.setattr(main, "nebula_ping", lambda: True)
    monkeypatch.setattr(main, "lexical_ready", lambda: True)
    monkeypatch.setattr(main.httpx, "AsyncClient", _ollama_repond_vrai())

    corps: dict[str, object] = {}

    async def scenario() -> None:
        liberer = threading.Event()
        async with anyio.create_task_group() as tg:
            await _saturer_le_reservoir_par_defaut(tg, liberer)
            debut = time.monotonic()
            reponse = await main.health()
            corps["duree"] = round(time.monotonic() - debut, 3)
            corps["status"] = reponse.status
            corps["services"] = dict(reponse.services)
            liberer.set()

    anyio.run(scenario)

    assert corps["services"] == {
        "chromadb": True,
        "nebulagraph": True,
        "index_lexical": True,
        "ollama": True,
    }, (
        f"/health publie {corps['services']} alors que les quatre dépendances "
        f"répondent en microsecondes (rendu en {corps['duree']} s). Un `false` ici "
        "dit « ce service est tombé » à un exploitant, alors que le fait est « je "
        "n'avais pas de fil pour regarder » — strictement plus difficile à "
        "diagnostiquer qu'un 503 honnête"
    )
    assert corps["status"] == "ok", (
        f"/health rend « {corps['status']} » sur un service intégralement sain, du "
        "seul fait que les endpoints de recherche occupent le réservoir de fils"
    )


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
    # Le périphérique est ÉPINGLÉ, et ce n'est pas une commodité : depuis le
    # lot 12, un périphérique hors d'atteinte dégrade à lui seul, et le défaut
    # `cuda` dans un venv torch CPU en est un. Sans cette ligne, cette scène
    # mesurerait la propriété qu'elle vise SUR UN SERVICE DÉGRADÉ pour une
    # autre raison — un `rc` juste pour une raison fausse, la forme que ce
    # chantier a payée huit fois.
    monkeypatch.setattr(main.settings, "torch_device", "cpu")
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
    # Le périphérique est ÉPINGLÉ, et ce n'est pas une commodité : depuis le
    # lot 12, un périphérique hors d'atteinte dégrade à lui seul, et le défaut
    # `cuda` dans un venv torch CPU en est un. Sans cette ligne, cette scène
    # mesurerait la propriété qu'elle vise SUR UN SERVICE DÉGRADÉ pour une
    # autre raison — un `rc` juste pour une raison fausse, la forme que ce
    # chantier a payée huit fois.
    monkeypatch.setattr(main.settings, "torch_device", "cpu")
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
    # Le périphérique est épinglé PAR PRÉCAUTION, et cette ligne n'est PAS un
    # épinglage : cette scène-ci n'atteint jamais le verdict du périphérique —
    # elle asserte `degraded` de toute façon, ou ne passe pas par `/health`.
    # `mesuré` le 14 septembre 2026 (REPAR-13, mutation M-B : les 15 lignes de ce
    # motif retirées des trois fichiers → 8 tests rouges sur 58, celui-ci n'en
    # est pas). Le motif qui figurait ici — « sans cette ligne, cette scène
    # mesurerait sa propriété SUR UN SERVICE DÉGRADÉ » — était donc FAUX à ce
    # site précis : c'est NB-2 de l'audit du lot 12. La ligne RESTE, parce
    # qu'elle protégera le jour où cette scène lira `/health` ; ce qui part est
    # la déclaration qu'elle garde quelque chose aujourd'hui.
    monkeypatch.setattr(main.settings, "torch_device", "cpu")
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
    pas tomber pour autant : une faute de frappe dans un `.env` ferait échouer le
    healthcheck, donc passer le conteneur `unhealthy` — et `frontend`, qui attend
    `agent-api` en `condition: service_healthy`, ne lèverait pas. Ce n'est PAS un
    redémarrage en boucle : `restart:` répond à la sortie du processus, pas à la
    santé (`mesuré`, cf. `documentation/axes_amelioration.md` §1.27).

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
    # Le périphérique est épinglé PAR PRÉCAUTION, et cette ligne n'est PAS un
    # épinglage : cette scène-ci n'atteint jamais le verdict du périphérique —
    # elle asserte `degraded` de toute façon, ou ne passe pas par `/health`.
    # `mesuré` le 14 septembre 2026 (REPAR-13, mutation M-B : les 15 lignes de ce
    # motif retirées des trois fichiers → 8 tests rouges sur 58, celui-ci n'en
    # est pas). Le motif qui figurait ici — « sans cette ligne, cette scène
    # mesurerait sa propriété SUR UN SERVICE DÉGRADÉ » — était donc FAUX à ce
    # site précis : c'est NB-2 de l'audit du lot 12. La ligne RESTE, parce
    # qu'elle protégera le jour où cette scène lira `/health` ; ce qui part est
    # la déclaration qu'elle garde quelque chose aujourd'hui.
    monkeypatch.setattr(main.settings, "torch_device", "cpu")
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
    # Le périphérique est ÉPINGLÉ, et ce n'est pas une commodité : depuis le
    # lot 12, un périphérique hors d'atteinte dégrade à lui seul, et le défaut
    # `cuda` dans un venv torch CPU en est un. Sans cette ligne, cette scène
    # mesurerait la propriété qu'elle vise SUR UN SERVICE DÉGRADÉ pour une
    # autre raison — un `rc` juste pour une raison fausse, la forme que ce
    # chantier a payée huit fois.
    monkeypatch.setattr(main.settings, "torch_device", "cpu")
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
