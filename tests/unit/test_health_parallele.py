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
import yaml
from fastapi.testclient import TestClient

# ─── Outillage ────────────────────────────────────────────────────────────────

_RACINE = Path(__file__).resolve().parents[2]

# Plafond de sécurité des sondes muettes. Il ne borne PAS la durée du test quand
# le correctif est en place — le plafond de /health revient bien avant — mais il
# borne celle d'un ÉCHEC : sur une implémentation séquentielle, /health attend
# ici quatre fois cette valeur avant de rendre. Assez grand pour dépasser le
# délai du healthcheck, assez petit pour qu'un rouge reste lisible.
_CAP_SECURITE_S = 8.0


# Les unités de durée que docker accepte, et leur valeur en secondes. `ms` doit
# précéder `m` et `s` dans l'alternance : sans cela `500ms` serait lu `500m`.
_UNITES_DE_DUREE = {"h": 3600.0, "ms": 0.001, "us": 1e-6, "ns": 1e-9, "m": 60.0, "s": 1.0}
_UNE_DUREE = r"(\d+(?:\.\d+)?)(h|ms|us|ns|m|s)"


def _secondes_docker(duree: object) -> float:
    """Une durée du compose en secondes. `1m30s` vaut 90,0, et l'illisible ROUGIT.

    L'ANCIENNE LECTURE NE CONNAISSAIT QUE `<entier>s`, et c'est la moitié du
    défaut de la non bloquante §3 : sur `interval: 1m`, parfaitement valide pour
    docker, elle ne trouvait rien. Un lecteur qui n'en lirait qu'une partie
    serait pire encore — `1m30s` rendrait 1 ou 30 au lieu de 90, donc un verdict
    faux au lieu d'un rouge. La chaîne entière doit donc être consommée, sans
    quoi on rougit en nommant ce qu'on n'a pas su lire.
    """
    texte = str(duree).strip()
    assert re.fullmatch(f"(?:{_UNE_DUREE})+", texte), (
        f"durée `{texte}` illisible dans docker-compose.yml : attendu un format docker "
        "comme `20s`, `1m` ou `1m30s`, unité comprise"
    )
    return sum(
        float(valeur) * _UNITES_DE_DUREE[unite] for valeur, unite in re.findall(_UNE_DUREE, texte)
    )


# Les fichiers que docker Compose fusionne AUTOMATIQUEMENT par-dessus
# `docker-compose.yml`, sans qu'aucun `-f` soit écrit sur la ligne de commande.
#
# NON BLOQUANTE §4 DE L'AUDIT DU 15 SEPTEMBRE 2026 — LE GARDE PROMETTAIT ET NE
# TENAIT PAS. Il ne lisait que `docker-compose.yml` ; docker lit celui-là **et**
# son override. L'audit a posé un override de quatre lignes portant
# `interval: 8s` : docker appliquait 8 s, le garde lisait 20,0 s, et les 870
# tests restaient **verts** — alors que la docstring de
# `test_le_budget_de_la_sonde_du_moteur_tient_entre_deux_battements` promet
# explicitement que « ramener l'intervalle du compose à 8 s rougirait ici ».
# **Un garde qui promet et ne tient pas est pire qu'un garde absent**, parce
# qu'on cesse de regarder : c'est le faux vert S4 du cahier des charges,
# réintroduit par un autre chemin, et par une modification anodine prise seule.
#
# LES DEUX NOMS, ET PAS QUATRE. Avec `docker-compose.yml` pour fichier de base,
# docker cherche `docker-compose.override.yml` puis `.yaml` — et **pas**
# `compose.override.yml`, qui n'est l'override que de `compose.yaml`. Le chemin
# par lequel `compose.yaml` prendrait la main est fermé séparément, ci-dessous.
_OVERRIDES_AUTOMATIQUES = ("docker-compose.override.yml", "docker-compose.override.yaml")

# Les noms qui, s'ils apparaissaient, feraient que docker ne lirait PLUS
# `docker-compose.yml` du tout : il les prend dans cet ordre et s'arrête au
# premier trouvé. Ce garde lit `docker-compose.yml` ; si l'un de ceux-là
# existait, il lirait un fichier que docker a cessé d'ouvrir.
_BASES_PRIORITAIRES = ("compose.yaml", "compose.yml", "docker-compose.yaml")


def _fusion_docker(base: object, dessus: object) -> object:
    """La fusion que docker Compose applique entre le fichier de base et son override.

    LES MAPPINGS FUSIONNENT EN PROFONDEUR, LE RESTE REMPLACE. C'est exactement la
    règle de docker pour un healthcheck : `interval`, `timeout` et `retries` sont
    des scalaires qu'un override écrase, et `test` est une séquence qu'il
    remplace entière.

    CE QUE CETTE FUSION NE REPRODUIT PAS, ÉCRIT COMME BORNE. Docker CONCATÈNE
    certaines séquences — `ports`, `volumes`, `dns` — au lieu de les remplacer.
    Aucune ne vit sous `healthcheck`, qui est tout ce que ce garde lit, et
    étendre la fusion à ces clés-là sans les lire serait de la complexité sans
    mesure. La borne est écrite, pas franchie.
    """
    if isinstance(base, dict) and isinstance(dessus, dict):
        fusionne = dict(base)
        for cle, valeur in dessus.items():
            fusionne[cle] = _fusion_docker(fusionne.get(cle), valeur)
        return fusionne
    return dessus


def _compose_tel_que_docker_le_lit(
    texte: str | None = None, texte_override: str | None = None
) -> dict[str, object]:
    """Le compose fusionné, lu comme docker le lit : le fichier de base ET son override.

    `texte` et `texte_override` N'EXISTENT QUE POUR LES TESTS DE CE LECTEUR, et
    c'est assumé pour la même raison qu'avant : sans eux, éprouver les scènes
    exigerait de muter les vrais fichiers pendant que la porte tourne. Le défaut
    est ce que le DÉPÔT porte, et un contrôle positif épingle que c'est bien lui.
    """
    if texte is None:
        for prioritaire in _BASES_PRIORITAIRES:
            assert not (_RACINE / prioritaire).exists(), (
                f"`{prioritaire}` est apparu à la racine : docker le lit AVANT "
                "`docker-compose.yml` et cesse alors d'ouvrir celui-ci. Ce garde lirait "
                "un fichier que docker n'applique plus — le faux vert exact que la non "
                "bloquante §4 de l'audit du 15 septembre 2026 a mesuré sur l'override"
            )
        texte = (_RACINE / "docker-compose.yml").read_text(encoding="utf-8")
        if texte_override is None:
            for nom in _OVERRIDES_AUTOMATIQUES:
                if (_RACINE / nom).exists():
                    texte_override = (_RACINE / nom).read_text(encoding="utf-8")
                    break
    fusionne = yaml.safe_load(texte) or {}
    if texte_override is not None:
        fusionne = _fusion_docker(fusionne, yaml.safe_load(texte_override) or {})
    assert isinstance(fusionne, dict)
    return fusionne


def _reglage_du_healthcheck(
    cle: str,
    texte: str | None = None,
    service: str = "agent-api",
    texte_override: str | None = None,
) -> float:
    """Un réglage du healthcheck D'UN SERVICE NOMMÉ, lu dans le compose.

    NON BLOQUANTE §3 DE L'AUDIT DU 15 SEPTEMBRE 2026 — LE GARDE ÉTAIT CREUX.
    Les deux lecteurs qui vivaient ici cherchaient `interval:` et `timeout:` dans
    **tout** le fichier par expression rationnelle et exigeaient un unique
    résultat. Ils ne rattachaient la valeur à **aucun service** : l'audit a
    mesuré que deux modifications parfaitement anodines du compose — un
    commentaire de fin de ligne, un healthcheck sur un second service —
    suffisaient à leur faire rendre l'intervalle **d'un autre service**, sans
    rougir. Le garde du budget comparait alors le pire cas de 9,0 s de la sonde
    du moteur à 20 s quand l'agent battait toutes les 8 s, et se taisait pendant
    que les sondes s'empilaient sur un serveur d'inférence partagé avec deux
    autres équipes.

    LE FICHIER EST DONC PARSÉ COMME DOCKER LE PARSE, et la valeur est cherchée
    là où docker la cherche : sous `services.<service>.healthcheck`. Une
    expression rationnelle sur un fichier structuré lit une ressemblance ; un
    parseur lit la valeur.

    IL ROUGIT EN NOMMANT CE QUI MANQUE — réserve R-2 du même audit. L'ancien
    message disait « plusieurs intervals » **aussi quand il y en avait zéro**,
    envoyant chercher le contraire du problème. Les trois échecs possibles sont
    ici distincts : le service absent, le healthcheck absent, la clé absente.

    `texte` N'EXISTE QUE POUR LES TESTS DE CE LECTEUR, et c'est assumé : sans
    lui, éprouver les scènes de l'audit exigerait de muter le vrai compose
    pendant que la porte tourne. Le défaut par défaut est le fichier du dépôt,
    et un contrôle positif épingle que c'est bien lui qui est lu.
    """
    services = _compose_tel_que_docker_le_lit(texte, texte_override).get("services") or {}
    assert service in services, (
        f"le service `{service}` est absent de docker-compose.yml : ce garde lit la "
        "valeur d'un service NOMMÉ, et ne se rabat sur aucun autre"
    )
    healthcheck = (services[service] or {}).get("healthcheck") or {}
    assert cle in healthcheck, (
        f"`{cle}` absent du healthcheck de `{service}` dans docker-compose.yml : "
        "cette valeur est le contrat de déploiement dont ce garde tire son sens"
    )
    return _secondes_docker(healthcheck[cle])


def _intervalle_du_healthcheck(
    texte: str | None = None, service: str = "agent-api", texte_override: str | None = None
) -> float:
    """L'intervalle entre deux battements DE L'AGENT, LU dans le fichier.

    C'est le budget dont dépend la sonde du moteur LLM : elle survit au plafond
    de la route et poursuit en fond, donc ce qui la borne utilement n'est pas le
    délai de `curl` mais l'écart au battement suivant.
    """
    return _reglage_du_healthcheck("interval", texte, service, texte_override)


def _delai_du_healthcheck(
    texte: str | None = None, service: str = "agent-api", texte_override: str | None = None
) -> float:
    """Le délai que docker-compose accorde à /health DE L'AGENT, LU dans le fichier.

    Recopié en dur ici, le lien entre le plafond du code et le contrat de
    déploiement serait invisible : c'est ce contrat qui donne au plafond sa
    valeur, et il vit dans un autre fichier que celui qu'on corrige.
    """
    return _reglage_du_healthcheck("timeout", texte, service, texte_override)


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
    # prétend. Le compte des lignes de ce motif — combien mordent, combien sont
    # inertes, combien de tests elles tiennent — et la recette qui le reproduit
    # ont UN SEUL SITE : le §4.52 du registre. Il n'est pas recopié ici.
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


def test_le_budget_de_la_sonde_du_moteur_tient_entre_deux_battements() -> None:
    """RÉSERVE R1 DE L'AUDIT DU 15 SEPTEMBRE 2026, et elle n'était épinglée nulle part.

    `_MOTEUR_TIMEOUT_S` vaut 3,0 s **par requête**, et la sonde en enchaîne
    jusqu'à `_MOTEUR_REQUETES_MAX` en SÉQUENCE. Son pire cas n'est donc pas 3,0 s
    mais **9,0 s** — et l'audit lui-même l'a sous-estimé à 6,0 s en ne comptant
    que les deux lectures de version, alors que la lecture du catalogue suit la
    seconde d'entre elles.

    CE QUE CE TEST TIENT, ET CE QU'IL NE TIENT PAS. Il ne prétend pas que ce
    délai protège `/health` : il ne le protège pas, et le commentaire du site le
    disait mal — c'est `_PLAFOND_SONDES_S` qui coupe la route à 3 s, mesuré à
    3,01 s sous quatre dépendances pendantes. Mais la TÂCHE de sonde, elle,
    survit à ce plafond et poursuit en fond ; si son pire cas dépassait
    l'intervalle du healthcheck, chaque battement en lancerait une nouvelle
    par-dessus la précédente, sur un serveur d'inférence PARTAGÉ avec une autre
    équipe. C'est cette relation-là qui compte, et c'est elle qui est épinglée.

    Les deux valeurs sont tenues ENSEMBLE : porter le délai par requête à 7 s, ou
    ramener l'intervalle du compose à 8 s, rougirait ici et nulle part ailleurs.

    ET CETTE PROMESSE EST DÉSORMAIS TENUE PAR LE CHEMIN QUE DOCKER EMPRUNTE —
    non bloquante §4 de l'audit du 15 septembre 2026. Elle ne l'était pas : le
    lecteur n'ouvrait que `docker-compose.yml`, quand docker fusionne
    automatiquement `docker-compose.override.yml` par-dessus. L'audit a mesuré un
    override de quatre lignes portant `interval: 8s` — docker appliquait 8 s, ce
    test lisait 20,0 s et restait VERT. « Rougirait ici » était faux par le seul
    chemin qui compte, et un garde qui promet sans tenir est pire qu'un garde
    absent : on cesse de regarder. `_compose_tel_que_docker_le_lit` ouvre
    maintenant les deux fichiers et les fusionne comme docker les fusionne.
    """
    from src.api import main

    pire_cas = main._MOTEUR_TIMEOUT_S * main._MOTEUR_REQUETES_MAX
    assert pire_cas > main._PLAFOND_SONDES_S, (
        "contrôle de cohérence de ce test : si le pire cas de la sonde passait "
        "sous le plafond, c'est le plafond qui deviendrait la borne et cette "
        "assertion cesserait de décrire quoi que ce soit"
    )
    assert pire_cas < _intervalle_du_healthcheck(), (
        "une sonde de moteur peut encore tourner quand le battement suivant en "
        "lance une autre : les requêtes s'empileraient sur un serveur partagé"
    )


# ─── Le garde du budget lit la valeur DU BON SERVICE ─────────────────────────


def _compose_simule(agent: str | None, voisin: str | None = None, commentaire: str = "") -> str:
    """Un `docker-compose.yml` construit, pour éprouver le LECTEUR et non le fichier.

    Les scènes jouées ici sont celles que l'audit du 15 septembre 2026 a mesurées
    sur l'ancien lecteur (§3, S1 à S4), et elles sont toutes **anodines prises
    une par une** : un commentaire de fin de ligne, un healthcheck sur un second
    service, un intervalle écrit `1m` au lieu de `60s`.
    """
    texte = "services:\n  agent-api:\n    healthcheck:\n      test: [\"CMD\", \"true\"]\n"
    if agent is not None:
        texte += f"      interval: {agent}{commentaire}\n"
    texte += "      timeout: 5s\n      retries: 5\n"
    if voisin is not None:
        texte += f"  voisin:\n    healthcheck:\n      interval: {voisin}\n      timeout: 3s\n"
    return texte


class TestLeGardeDuBudgetLitLaValeurDuBonService:
    """NON BLOQUANTE §3 DE L'AUDIT DU 15 SEPTEMBRE 2026 — le garde était CREUX.

    `_intervalle_du_healthcheck` cherchait `^\\s+interval:\\s*(\\d+)s\\s*$` dans
    **tout** le fichier et exigeait un seul résultat. Il ne rattachait cet
    `interval:` à **aucun service**. Un garde qui lit un fichier de configuration
    doit lire la valeur du BON service, et rougir quand il ne peut plus le faire.

    CE QUE ÇA COÛTAIT, ET POURQUOI C'EST PIRE QUE L'AUTRE LECTEUR DE CE FICHIER.
    `_delai_du_healthcheck`, préexistant, portait la même faiblesse et la
    réparation l'avait imitée par symétrie — c'est défendable. Mais la valeur
    neuve garde une propriété de **charge sur un serveur d'inférence partagé
    avec deux autres équipes** : si le pire cas de la sonde dépassait
    l'intervalle, chaque battement empilerait une sonde sur la précédente. Là où
    l'ancien lecteur ne gardait qu'une marge locale, celui-ci garde le voisin.

    LES DEUX FAUX VERTS SONT REPRODUITS ICI, contre l'ancienne lecture elle-même
    (`test_l_ancienne_lecture_rendait_deux_verdicts_faux`) : sans cette
    contre-épreuve, rien ne distinguerait « le lecteur neuf est juste » de « la
    scène ne mordait déjà pas ».
    """

    _ANCIENNE_LECTURE = r"^\s+interval:\s*(\d+)s\s*$"

    def test_l_intervalle_lu_est_celui_de_l_agent_et_non_celui_d_un_voisin(self) -> None:
        """S2 ET S4 DE L'AUDIT — les deux scènes où l'ancien lecteur se taisait à faux.

        S4 est la plus chère : l'agent bat réellement toutes les **8 s** et
        l'ancien lecteur comparait le pire cas de 9,0 s à **20 s**, celui d'un
        autre service. Le garde du budget se taisait pendant que les sondes
        s'empilaient.
        """
        # S4 — l'agent à 8 s avec un commentaire de fin de ligne, un voisin à 20 s
        assert _intervalle_du_healthcheck(_compose_simule("8s", "20s", "  # resserré")) == 8.0
        # S2 — l'agent à `1m` (format docker valide), un voisin à 20 s
        assert _intervalle_du_healthcheck(_compose_simule("1m", "20s")) == 60.0

    def test_l_ancienne_lecture_rendait_deux_verdicts_faux(self) -> None:
        """LA CONTRE-ÉPREUVE, et sans elle le test ci-dessus ne prouve rien.

        Elle applique l'ANCIENNE expression aux MÊMES textes et montre qu'elle
        rendait `20` là où la vérité était 8 puis 60. C'est la mesure qui établit
        que la correction en est une, et non un test écrit autour d'un
        comportement qui n'avait jamais posé problème.
        """
        import re as _re

        for texte, vrai in (
            (_compose_simule("8s", "20s", "  # resserré"), 8.0),
            (_compose_simule("1m", "20s"), 60.0),
        ):
            trouves = _re.findall(self._ANCIENNE_LECTURE, texte, _re.MULTILINE)
            assert trouves == ["20"], "la scène du faux vert n'est plus celle que l'audit a mesurée"
            assert float(trouves[0]) != vrai, (
                "l'ancienne lecture rendait la BONNE valeur : il n'y avait pas de défaut"
            )
            assert _intervalle_du_healthcheck(texte) == vrai, "la lecture neuve n'est pas juste"

    def test_un_second_service_a_healthcheck_ne_fait_plus_rougir_a_tort(self) -> None:
        """S1 — le garde rougissait, et c'était déjà trop.

        « Plusieurs intervals : préciser lequel » demandait une intervention
        humaine pour un fichier parfaitement valide. Un healthcheck sur un second
        service est une modification banale ; elle ne doit ni faire rougir la
        porte ni la faire mentir.
        """
        assert _intervalle_du_healthcheck(_compose_simule("20s", "30s")) == 20.0

    def test_un_healthcheck_sans_intervalle_rougit_en_nommant_la_bonne_chose(self) -> None:
        """RÉSERVE R-2 DE L'AUDIT — le message mentait sur le sens de son échec.

        « plusieurs intervals dans docker-compose.yml » s'imprimait aussi quand
        il y en avait **zéro** (S3 : l'agent seul à `1m`, que l'ancienne
        expression ne savait pas lire). Le garde rougissait — l'essentiel — mais
        il envoyait chercher le contraire du problème.
        """
        with pytest.raises(AssertionError, match=r"interval.*agent-api"):
            _intervalle_du_healthcheck(_compose_simule(None))

    def test_un_service_absent_rougit_et_ne_se_rabat_sur_personne(self) -> None:
        """Renommer le service ne doit pas faire lire l'intervalle d'un autre."""
        with pytest.raises(AssertionError, match=r"agent-api"):
            _intervalle_du_healthcheck(_compose_simule("20s", "30s"), service="un-autre-nom")

    def test_les_formats_de_duree_de_docker_sont_lus_et_les_autres_rougissent(self) -> None:
        """`1m30s` N'EST PAS `1` NI `30`, et un format inconnu ne vaut pas zéro.

        L'ancienne expression ne lisait que `<entier>s`. Docker accepte les
        durées composées, et un lecteur qui n'en lirait qu'une partie
        produirait un verdict faux au lieu de rougir.
        """
        assert _intervalle_du_healthcheck(_compose_simule("1m30s")) == 90.0
        assert _intervalle_du_healthcheck(_compose_simule("1h")) == 3600.0
        assert _intervalle_du_healthcheck(_compose_simule("500ms")) == 0.5
        with pytest.raises(AssertionError, match="durée"):
            _intervalle_du_healthcheck(_compose_simule("20"))
        with pytest.raises(AssertionError, match="durée"):
            _intervalle_du_healthcheck(_compose_simule("bientot"))

    def test_le_controle_positif_le_vrai_fichier_est_bien_lu(self) -> None:
        """SANS LUI, TOUT CE QUI PRÉCÈDE PASSERAIT SUR UN LECTEUR QUI NE LIT QUE MES TEXTES.

        Les deux valeurs du `docker-compose.yml` du dépôt, lues par défaut, sans
        texte fourni — c'est cette lecture-là que les tests du budget et du
        plafond utilisent réellement.
        """
        assert _intervalle_du_healthcheck() == 20.0
        assert _delai_du_healthcheck() == 5.0


# ─── Le garde lit ce que DOCKER lit, override compris ────────────────────────


class TestLeGardeLitLOverrideCommeDockerLeLit:
    """NON BLOQUANTE §4 DE L'AUDIT DU 15 SEPTEMBRE 2026 — le cinquième scénario.

    Les quatre formes que le mandat précédent nommait — ancres YAML, alias, clé
    de fusion `<<:`, fragments `x-` — sont **toutes correctement traitées**, et
    l'audit l'a vérifié une par une : `yaml.safe_load` les résout, et le lecteur
    cherche sous `services.<service>.healthcheck` comme docker le fait. Il n'y
    avait rien là.

    LE CINQUIÈME EST AILLEURS, ET IL EST MESURÉ. Docker Compose charge
    **automatiquement** `docker-compose.override.yml` et le fusionne par-dessus
    le fichier de base ; le lecteur n'ouvrait que le fichier de base. Mesuré par
    l'audit, et remesuré ici avec son contrôle positif : sous un override de
    quatre lignes portant `interval: 8s`, `docker compose config` rend **8s**,
    sans override il rend **20s**, et le lecteur rendait **20,0** dans les deux
    cas — 870 tests verts, pendant que le budget de la sonde (pire cas 9,0 s)
    dépassait l'intervalle réel.

    LE SENS DE L'ÉCHEC EST LE BON, et c'est pour ça que la première voie a été
    prise plutôt que la seconde : entre « le garde lit ce que docker lit » et
    « la docstring cesse de promettre », la seconde aurait laissé le faux vert en
    place et se serait contentée de ne plus mentir dessus. Ici, chaque battement
    empilerait une sonde sur la précédente, sur un serveur d'inférence partagé
    avec deux autres équipes — le dommage exact que ce garde existe pour
    empêcher.

    AUCUN OVERRIDE N'EXISTE DANS LE DÉPÔT AUJOURD'HUI, et ces scènes sont donc
    prospectives, comme S4 l'était. Elles jouent le fichier par le paramètre de
    texte, sans jamais en écrire un à la racine pendant que la porte tourne.
    """

    _BASE = (
        "services:\n"
        "  agent-api:\n"
        "    healthcheck:\n"
        '      test: ["CMD", "curl", "-sf", "http://localhost:8000/health"]\n'
        "      interval: 20s\n"
        "      timeout: 5s\n"
    )

    def test_le_temoin_sans_override_la_valeur_du_fichier_de_base_est_rendue(self) -> None:
        """LE TÉMOIN INERTE DE CETTE CLASSE : sans override, rien ne bouge.

        Il établit que les scènes suivantes mesurent bien la FUSION et non un
        lecteur qui se serait mis à rendre n'importe quoi.
        """
        assert _intervalle_du_healthcheck(self._BASE) == 20.0
        assert _delai_du_healthcheck(self._BASE) == 5.0

    def test_un_override_qui_ramene_l_intervalle_a_8s_est_bien_lu(self) -> None:
        """LA SCÈNE EXACTE DE L'AUDIT, et c'est elle qui rougissait nulle part.

        Quatre lignes, un geste anodin pris seul, et docker applique 8 s.
        """
        override = "services:\n  agent-api:\n    healthcheck:\n      interval: 8s\n"
        assert _intervalle_du_healthcheck(self._BASE, texte_override=override) == 8.0, (
            "docker fusionne cet override et applique 8 s ; un garde qui lit encore 20 s "
            "reste vert pendant que les sondes s'empilent sur un serveur partagé"
        )

    def test_l_override_ne_touche_que_ce_qu_il_nomme(self) -> None:
        """LA FUSION EST PROFONDE, ET C'EST LA MOITIÉ QUI SE CASSE EN SILENCE.

        Un override qui ne nomme que `interval` ne doit pas emporter `timeout`
        avec lui. Une fusion qui REMPLACERAIT le healthcheck entier ferait rougir
        le garde du plafond (`_delai_du_healthcheck`) sur un compose sain — un
        faux ROUGE, moins grave que le faux vert, mais un faux tout de même.
        """
        override = "services:\n  agent-api:\n    healthcheck:\n      interval: 8s\n"
        assert _delai_du_healthcheck(self._BASE, texte_override=override) == 5.0, (
            "l'override a emporté une clé qu'il ne nomme pas : la fusion n'est pas profonde"
        )

    def test_un_override_sur_un_autre_service_ne_deplace_pas_notre_valeur(self) -> None:
        """Le lecteur lit toujours la valeur d'un service NOMMÉ, override compris.

        C'est la non bloquante §3 du cahier des charges précédent, rejouée par le
        chemin neuf : un healthcheck posé sur un voisin ne doit pas devenir le
        nôtre.
        """
        override = "services:\n  frontend:\n    healthcheck:\n      interval: 3s\n"
        assert _intervalle_du_healthcheck(self._BASE, texte_override=override) == 20.0
        assert _intervalle_du_healthcheck(self._BASE, "frontend", override) == 3.0

    def test_un_override_qui_ajoute_le_healthcheck_absent_de_la_base_est_lu(self) -> None:
        """L'override peut CRÉER ce que la base n'a pas, et docker l'applique.

        Sans la fusion, ce cas-là rougirait en disant « healthcheck absent » sur
        un service que docker surveille parfaitement.
        """
        base = "services:\n  agent-api:\n    image: rien\n"
        override = "services:\n  agent-api:\n    healthcheck:\n      interval: 8s\n"
        assert _intervalle_du_healthcheck(base, texte_override=override) == 8.0

    def test_un_override_vide_ou_muet_ne_change_rien(self) -> None:
        """Un fichier d'override vide est légal, et il ne doit pas faire lever le lecteur."""
        assert _intervalle_du_healthcheck(self._BASE, texte_override="") == 20.0
        assert _intervalle_du_healthcheck(self._BASE, texte_override="# rien\n") == 20.0

    def test_le_controle_positif_le_depot_n_a_pas_d_override_et_c_est_verifie(self) -> None:
        """SANS LUI, LA LECTURE PAR DÉFAUT POURRAIT ÊTRE CELLE D'UN FICHIER FANTÔME.

        Deux choses ensemble, et il faut les deux : aucun override n'existe
        aujourd'hui à la racine — la trouvaille est prospective, l'audit l'avait
        vérifié et ce test le maintient —, et la lecture par défaut rend bien les
        valeurs du fichier du dépôt.

        SI CE TEST ROUGIT PARCE QU'UN OVERRIDE EST APPARU, il ne faut pas le
        supprimer : il faut lire la valeur que docker applique alors, et vérifier
        que le budget de la sonde tient encore devant elle.
        """
        for nom in _OVERRIDES_AUTOMATIQUES:
            assert not (_RACINE / nom).exists(), (
                f"`{nom}` est apparu : docker le fusionne, et l'intervalle réel du "
                "healthcheck n'est plus celui de `docker-compose.yml`"
            )
        assert _intervalle_du_healthcheck() == 20.0

    def test_un_fichier_compose_prioritaire_ferait_ignorer_celui_que_ce_garde_lit(self) -> None:
        """LE CHEMIN VOISIN, FERMÉ AVEC L'AUTRE PARCE QU'IL A LA MÊME FORME.

        Docker prend le premier de `compose.yaml`, `compose.yml`,
        `docker-compose.yaml`, `docker-compose.yml` et **s'arrête là**. Si l'un
        des trois premiers apparaissait, docker cesserait d'ouvrir
        `docker-compose.yml` — et ce garde lirait un fichier que docker
        n'applique plus. Même faux vert, autre porte.
        """
        for nom in _BASES_PRIORITAIRES:
            assert not (_RACINE / nom).exists(), (
                f"`{nom}` prend la main sur `docker-compose.yml` : ce garde lit un "
                "fichier que docker n'ouvre plus"
            )


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
    # LE RELEVÉ DU MOTEUR EST ÉPINGLÉ CHAUD, et il faut dire pourquoi. Il passe
    # par le MÊME `httpx.AsyncClient` que la sonde `ollama` ci-dessous — c'est
    # lui que le faux client remplace — donc il arriverait EN CINQUIÈME sur une
    # barrière de quatre et la casserait. Ce que ce test mesure est la
    # simultanéité des QUATRE sondes de `services` ; le moteur n'en fait pas
    # partie, il ne publie rien dans `services` et ne dégrade pas `status`.
    #
    # Épinglé chaud plutôt que neutralisé : c'est l'état RÉEL du service dès le
    # second appel à `/health`, le relevé étant mémorisé pour la vie du
    # processus. La scène reste donc celle d'un agent en marche.
    monkeypatch.setattr(main, "_moteur_releve", main.MoteurLlmHealth(modele_demande="épinglé"))

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
