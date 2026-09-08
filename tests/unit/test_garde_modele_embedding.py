"""Le garde du modèle d'embedding, côté lecteur.

**La panne que ces tests existent pour rendre impossible.** Les deux modèles
candidats du projet rendent des vecteurs de la MÊME largeur — 384 dimensions,
site canonique `documentation/axes_amelioration.md` §4.4. ChromaDB accepte donc
sans broncher un index produit par l'un et interrogé par l'autre, aucune sonde
de forme ne voit rien, et la recherche rend des passages **plausibles et faux**.
Vérifier la dimension ne protège de rien : c'est le NOM qui discrimine, et c'est
le nom que le garde confronte.

Le pipeline garde déjà ses deux bouts et **estampille la collection**
(`metadata["embedding_model"]`). L'agent, qui LIT, n'avait aucun garde. Ces
tests sont la moitié manquante.

**Trois pièges ont dicté la forme de ces tests.**

- `retriever._get_embedding_model()` CHARGE le modèle, et `SentenceTransformer`
  le télécharge s'il est absent du cache. Un garde placé après ce chargement
  paierait le téléchargement du mauvais modèle avant de le refuser. Le test
  `test_une_divergence_refuse_avant_de_charger_le_moindre_modele` asserte depuis
  le côté qui PRODUIT ce coût — le constructeur `SentenceTransformer` lui-même,
  espionné — et non depuis l'ordre des lignes, qu'on peut lire faux.
- un garde qui ne compare QUE lorsque l'estampille est présente est décoratif
  sur exactement le cas où l'on ne sait pas ce qui a indexé. L'absence est donc
  traitée comme une divergence, et c'est gardé ici, pas seulement écrit.
- « je n'ai pas pu lire » n'est pas « ça diverge ». Les deux se ressemblent et ne
  se soignent pas pareil : le premier est un fait sur les stores, le second un
  fait sur la configuration. `/health` les publie distinctement, et seul le
  second dégrade le statut à lui seul.
"""

import asyncio
import json
import logging
import threading
import time

import pytest
from fastapi.testclient import TestClient

from src.agent import retriever
from src.agent.settings import settings

# Les deux candidats du projet. Site canonique du fait qu'ils partagent la même
# largeur de vecteur : `documentation/axes_amelioration.md` §4.4.
_MODELE_QUI_A_INDEXE = "paraphrase-multilingual-MiniLM-L12-v2"
_AUTRE_CANDIDAT = "all-MiniLM-L6-v2"


# ─── Outillage ────────────────────────────────────────────────────────────────

class _FausseCollection:
    """Collection ChromaDB réduite à ce que le garde et la recherche en lisent.

    `metadata` est une propriété LOCALE du client chromadb (1.5.9), remplie au
    `get_collection` : la lire ne coûte aucun aller-retour. C'est ce qui rend la
    vérification tenable à chaque recherche.
    """

    def __init__(self, metadata: dict[str, str] | None, taille: int = 4367) -> None:
        self.metadata = metadata
        self._taille = taille
        self.requetes = 0

    def count(self) -> int:
        return self._taille

    def query(self, **_kwargs) -> dict:
        self.requetes += 1
        return {"ids": [[]], "documents": [[]], "metadatas": [[]], "distances": [[]]}


class _CollectionIllisible:
    """Ce que le client chromadb fait quand le store ne répond pas : il lève."""

    def count(self) -> int:
        raise ConnectionError("chromadb injoignable")

    @property
    def metadata(self) -> dict[str, str]:
        raise ConnectionError("chromadb injoignable")


def _fausse_ouverture(collection):
    """Un substitut de `_get_chroma_collection` qui porte AUSSI `cache_clear`.

    `reset_connection()` appelle `cache_clear()` sur cette fonction : sans cet
    attribut, un test qui exerce la réouverture rougirait sur son propre montage
    au lieu de mesurer le code — un rouge qui se lit comme un vrai et n'en est
    pas un.
    """

    def _ouvrir():
        return collection

    _ouvrir.cache_clear = lambda: None
    return _ouvrir


def _brancher_collection(monkeypatch, collection) -> None:
    """Substitue la collection ET réarme le verdict mis en cache.

    Sans le réarmement, un test qui a établi la concordance rendrait le suivant
    vert sans que son garde ne regarde quoi que ce soit.
    """
    monkeypatch.setattr(retriever, "_get_chroma_collection", _fausse_ouverture(collection))
    retriever.rearmer_verification_modele()


class _CollectionMorteALaRequete:
    """Une collection dont l'OBJET est mort : elle s'ouvre, puis la requête lève.

    C'est ce que laisse derrière lui un ChromaDB redémarré sous l'agent — le
    `metadata` capturé à l'ouverture se lit encore, et c'est la requête qui
    tombe. Exactement le cas que la reprise de `_dense_search` existe pour
    rattraper.
    """

    def __init__(self, metadata: dict[str, str] | None) -> None:
        self.metadata = metadata
        self.requetes = 0

    def count(self) -> int:
        return 4367

    def query(self, **_kwargs) -> dict:
        self.requetes += 1
        raise ConnectionError("chromadb injoignable")


class _FauxModeleEmbedding:
    """Ce que `_get_embedding_model()` rend, réduit à ce que la recherche en lit.

    Substitué et non espionné : le vrai constructeur TÉLÉCHARGE, et un test qui
    l'atteindrait paierait le rapatriement d'un modèle pour mesurer autre chose.
    """

    def encode(self, _texte):
        class _Vecteur:
            @staticmethod
            def tolist() -> list[float]:
                return [0.0] * 384

        return _Vecteur()


def _ouverture_memoisee(collections):
    """Un substitut de `_get_chroma_collection` FIDÈLE au `lru_cache`.

    LE PIÈGE QUE CE BOUCHON EXISTE POUR NE PAS RETOMBER DEDANS. Le vrai
    `_get_chroma_collection` est mémoïsé : il rend le MÊME objet à chaque appel
    et ne change QU'AU `cache_clear()`. Un bouchon qui ferait avancer la
    collection à chaque appel mesurerait son propre montage — il rendrait un
    « faux servi » qui ne viendrait pas de la reprise mais de lui-même, et le
    site canonique de cette leçon est `documentation/axes_amelioration.md`
    §4.20, où elle a coûté au pilote une contradiction qui n'existait pas.

    Ici la file n'avance donc qu'au `cache_clear`, c'est-à-dire au
    `reset_connection()` — le seul endroit où la vraie collection change
    d'identité en vol.
    """
    etat = {"courante": collections[0], "suivantes": list(collections[1:])}

    def _ouvrir():
        return etat["courante"]

    def _cache_clear() -> None:
        if etat["suivantes"]:
            etat["courante"] = etat["suivantes"].pop(0)

    _ouvrir.cache_clear = _cache_clear
    return _ouvrir


# ─── Le garde lui-même ────────────────────────────────────────────────────────

def test_un_reglage_divergent_face_a_une_collection_estampillee_est_refuse(monkeypatch) -> None:
    """LE cas du lot : le réglage nomme l'autre candidat, l'index vient du premier.

    Les deux rendent 384 dimensions, donc rien d'autre dans la chaîne ne peut
    voir cette panne.
    """
    monkeypatch.setattr(settings, "embedding_model_name", _AUTRE_CANDIDAT)
    _brancher_collection(monkeypatch, _FausseCollection({"embedding_model": _MODELE_QUI_A_INDEXE}))

    with pytest.raises(retriever.EmbeddingModelMismatchError) as leve:
        retriever.verifier_modele_embedding()

    # Le message doit NOMMER les deux, sans quoi l'exploitant ne sait pas
    # lequel des deux côtés corriger.
    message = str(leve.value)
    assert _AUTRE_CANDIDAT in message
    assert _MODELE_QUI_A_INDEXE in message


@pytest.mark.parametrize("metadata", [None, {}, {"autre_cle": "valeur"}])
def test_une_estampille_absente_est_refusee(monkeypatch, metadata) -> None:
    """Fail-closed, et c'est LA décision du lot.

    Une collection sans estampille est une collection dont on ne sait pas ce qui
    l'a produite — exactement la situation que le garde existe pour couvrir. Un
    garde qui ne comparerait que lorsque l'estampille est présente serait
    décoratif sur ce cas-là, donc sur le seul où l'on est aveugle.

    Les trois formes d'absence sont couvertes : `metadata` nulle (collection
    créée sans métadonnées), vide, et renseignée sans la clé.
    """
    monkeypatch.setattr(settings, "embedding_model_name", _MODELE_QUI_A_INDEXE)
    _brancher_collection(monkeypatch, _FausseCollection(metadata))

    with pytest.raises(retriever.EmbeddingModelMismatchError) as leve:
        retriever.verifier_modele_embedding()

    assert "estampille" in str(leve.value).lower()


def test_une_estampille_concordante_ne_rougit_pas(monkeypatch) -> None:
    """Le cas sain. Un garde qui refuse aussi l'état correct n'est pas un garde."""
    monkeypatch.setattr(settings, "embedding_model_name", _MODELE_QUI_A_INDEXE)
    _brancher_collection(monkeypatch, _FausseCollection({"embedding_model": _MODELE_QUI_A_INDEXE}))

    retriever.verifier_modele_embedding()  # ne lève pas


def test_un_store_illisible_n_est_pas_une_divergence(monkeypatch) -> None:
    """« Je n'ai pas pu lire » ne doit ni valoir « ça concorde » ni « ça diverge ».

    L'erreur du store remonte telle quelle : la recherche ne part pas — c'est
    déjà vrai sans garde, ChromaDB étant injoignable — et surtout le verdict
    n'est PAS mis en cache, sinon une panne passagère de Chroma vaudrait
    concordance pour toute la vie du processus.
    """
    monkeypatch.setattr(settings, "embedding_model_name", _MODELE_QUI_A_INDEXE)
    _brancher_collection(monkeypatch, _CollectionIllisible())

    with pytest.raises(ConnectionError):
        retriever.verifier_modele_embedding()

    assert retriever.etat_modele_embedding().status == "unknown"


# ─── Le piège du téléchargement ───────────────────────────────────────────────

def test_une_divergence_refuse_avant_de_charger_le_moindre_modele(monkeypatch) -> None:
    """Le garde doit précéder le CHARGEMENT, pas seulement la requête.

    `SentenceTransformer(nom)` télécharge le modèle absent du cache : un garde
    placé après paierait le téléchargement du mauvais modèle avant de le
    refuser — plusieurs centaines de mégaoctets pour finir en erreur.

    Asserté depuis le côté qui produit ce coût : le constructeur est espionné.
    Un test qui se contenterait de lire l'ordre des lignes resterait vert le jour
    où l'appel remonterait d'un cran.
    """
    appels: list[str] = []

    def _espion(nom: str, *_args, **_kwargs):
        appels.append(nom)
        raise AssertionError("le modèle a été chargé alors que la concordance est fausse")

    monkeypatch.setattr(retriever, "SentenceTransformer", _espion)
    monkeypatch.setattr(settings, "embedding_model_name", _AUTRE_CANDIDAT)
    _brancher_collection(monkeypatch, _FausseCollection({"embedding_model": _MODELE_QUI_A_INDEXE}))
    retriever._get_embedding_model.cache_clear()

    with pytest.raises(retriever.EmbeddingModelMismatchError):
        retriever.retrieve("une question", top_k=5)

    assert appels == [], "aucun modèle ne doit être chargé quand la concordance est fausse"


def test_la_recherche_dense_ne_part_pas_sur_une_collection_divergente(monkeypatch) -> None:
    """Le garde vit sur le chemin de la recherche, pas seulement au démarrage.

    C'est ce site-ci qui PRODUIT le comportement à empêcher : une collection
    interrogée avec le mauvais embedder. Un agent démarré avant une réingestion
    divergente, ou démarré alors que Chroma ne répondait pas, ne passe par aucun
    garde de démarrage.
    """
    collection = _FausseCollection({"embedding_model": _MODELE_QUI_A_INDEXE})
    monkeypatch.setattr(retriever, "SentenceTransformer", lambda *_a, **_k: None)
    monkeypatch.setattr(settings, "embedding_model_name", _AUTRE_CANDIDAT)
    _brancher_collection(monkeypatch, collection)
    retriever._get_embedding_model.cache_clear()

    with pytest.raises(retriever.EmbeddingModelMismatchError):
        retriever.retrieve("une question", top_k=5)

    assert collection.requetes == 0, "aucune requête ne doit atteindre ChromaDB"


def test_la_concordance_laisse_la_recherche_dense_passer(monkeypatch) -> None:
    """Le cas sain, au site de la recherche : le garde ne doit rien empêcher."""

    collection = _FausseCollection({"embedding_model": _MODELE_QUI_A_INDEXE})
    monkeypatch.setattr(settings, "embedding_model_name", _MODELE_QUI_A_INDEXE)
    monkeypatch.setattr(settings, "hybrid_search", False)
    monkeypatch.setattr(retriever, "_get_embedding_model", _FauxModeleEmbedding)
    _brancher_collection(monkeypatch, collection)

    assert retriever.retrieve("une question", top_k=5) == []
    assert collection.requetes == 1


# ─── Le verdict mis en cache ──────────────────────────────────────────────────

def test_le_verdict_favorable_ne_survit_pas_a_une_reouverture_de_collection(
    monkeypatch,
) -> None:
    """Le cache du verdict doit être remis à zéro avec la connexion.

    `reset_connection()` existe parce que la collection est mise en cache et
    qu'un ChromaDB redémarré laisse un objet mort derrière lui. La collection
    rouverte peut être une AUTRE collection — une réingestion a pu passer
    entre-temps — donc le verdict établi sur la précédente ne vaut plus.
    """
    monkeypatch.setattr(settings, "embedding_model_name", _MODELE_QUI_A_INDEXE)
    saine = _FausseCollection({"embedding_model": _MODELE_QUI_A_INDEXE})
    _brancher_collection(monkeypatch, saine)
    retriever.verifier_modele_embedding()

    divergente = _FausseCollection({"embedding_model": _AUTRE_CANDIDAT})
    monkeypatch.setattr(retriever, "_get_chroma_collection", _fausse_ouverture(divergente))
    retriever.reset_connection()

    with pytest.raises(retriever.EmbeddingModelMismatchError):
        retriever.verifier_modele_embedding()


# ─── Ce que /health en publie ─────────────────────────────────────────────────

def _brancher_health(monkeypatch) -> None:
    from src.api import main

    def _ollama_vrai():
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

    monkeypatch.setattr(main.settings, "api_key", "")
    monkeypatch.setattr(main, "chroma_ping", lambda: True)
    monkeypatch.setattr(main, "nebula_ping", lambda: True)
    monkeypatch.setattr(main, "lexical_ready", lambda: True)
    monkeypatch.setattr(main.httpx, "AsyncClient", _ollama_vrai())


def test_health_publie_une_divergence_et_degrade_sans_tomber(monkeypatch) -> None:
    """La divergence doit être LISIBLE, et /health doit rester en 200.

    Rendre 500 ou 503 ici ferait échouer le healthcheck de `docker-compose.yml`.
    Cela ne REDÉMARRE rien — `restart:` répond à la sortie du processus, pas à la
    santé, `mesuré` : 21 échecs consécutifs, `RestartCount=0`, `StartedAt`
    inchangé. Ce qui arrive est que le conteneur passe `unhealthy`, donc que
    `frontend`, qui en dépend en `condition: service_healthy`, ne lève pas au
    démarrage à froid — l'exploitant perdrait la seule route qui lui aurait
    nommé la divergence. Le statut dégradé est le canal prévu. Site canonique :
    `documentation/axes_amelioration.md` §1.27 et §4.20, trouvaille N2.
    """
    from src.api import main

    monkeypatch.setattr(settings, "embedding_model_name", _AUTRE_CANDIDAT)
    _brancher_collection(monkeypatch, _FausseCollection({"embedding_model": _MODELE_QUI_A_INDEXE}))
    _brancher_health(monkeypatch)

    reponse = TestClient(main.app).get("/health")

    assert reponse.status_code == 200
    corps = reponse.json()
    assert corps["embedding_model"]["status"] == "mismatch"
    assert corps["embedding_model"]["expected"] == _AUTRE_CANDIDAT
    assert corps["embedding_model"]["collection"] == _MODELE_QUI_A_INDEXE
    assert corps["status"] == "degraded"
    # Les quatre sondes répondent : la dégradation ne vient QUE de la divergence.
    assert all(corps["services"].values())


def test_health_publie_une_estampille_absente_et_degrade(monkeypatch) -> None:
    """L'absence est publiée comme telle, et dégrade comme une divergence."""
    from src.api import main

    monkeypatch.setattr(settings, "embedding_model_name", _MODELE_QUI_A_INDEXE)
    _brancher_collection(monkeypatch, _FausseCollection({}))
    _brancher_health(monkeypatch)

    corps = TestClient(main.app).get("/health").json()

    assert corps["embedding_model"]["status"] == "missing"
    assert corps["embedding_model"]["collection"] is None
    assert corps["status"] == "degraded"


def test_health_ne_degrade_pas_sur_une_collection_concordante(monkeypatch) -> None:
    """Le cas sain ne doit pas dégrader : sinon le statut ne veut plus rien dire."""
    from src.api import main

    monkeypatch.setattr(settings, "embedding_model_name", _MODELE_QUI_A_INDEXE)
    _brancher_collection(monkeypatch, _FausseCollection({"embedding_model": _MODELE_QUI_A_INDEXE}))
    _brancher_health(monkeypatch)

    corps = TestClient(main.app).get("/health").json()

    assert corps["embedding_model"]["status"] == "ok"
    assert corps["status"] == "ok"


def test_health_dit_l_inconnu_sans_le_confondre_avec_une_divergence(monkeypatch) -> None:
    """Un store illisible rend l'estampille inconnue, pas divergente.

    À lui seul il ne dégrade pas le statut : la sonde `chromadb` porte déjà ce
    fait-là, et le publier deux fois ferait croire à deux pannes. Ici la sonde
    est branchée à vrai — un montage qui n'existe pas en production — précisément
    pour isoler ce que la seule lecture de l'estampille décide.
    """
    from src.api import main

    monkeypatch.setattr(settings, "embedding_model_name", _MODELE_QUI_A_INDEXE)
    _brancher_collection(monkeypatch, _CollectionIllisible())
    _brancher_health(monkeypatch)

    corps = TestClient(main.app).get("/health").json()

    assert corps["embedding_model"]["status"] == "unknown"
    assert corps["embedding_model"]["collection"] is None
    assert corps["status"] == "ok"


def test_une_estampille_qui_ne_revient_pas_ne_retarde_pas_health(monkeypatch) -> None:
    """La lecture de l'estampille est sous le plafond des sondes, comme le reste.

    Un plafond qui ne couvre pas tout finit par mentir : `docker-compose.yml`
    coupe le healthcheck à 5 s, et une lecture laissée hors du plafond ferait
    dépasser ce délai à elle seule — `agent-api` passerait `unhealthy` et le
    frontend ne démarrerait jamais, la pathologie que
    `tests/unit/test_health_parallele.py` existe pour interdire.

    La sonde est rendue MUETTE, pas lente : c'est une lecture qui ne revient pas
    qu'il faut simuler, et elle est débloquée au démontage pour ne pas laisser un
    fil non-démon retenir l'interpréteur.
    """
    import threading

    from src.api import main

    debloquer = threading.Event()

    def _estampille_muette():
        debloquer.wait(8.0)
        raise AssertionError("jamais atteint")

    monkeypatch.setattr(main, "_PLAFOND_SONDES_S", 0.2)
    monkeypatch.setattr(main, "etat_modele_embedding", _estampille_muette)
    _brancher_health(monkeypatch)

    try:
        debut = time.monotonic()
        reponse = TestClient(main.app).get("/health")
        ecoule = time.monotonic() - debut
    finally:
        debloquer.set()
        main._sondes_en_vol.clear()

    assert reponse.status_code == 200
    assert ecoule < 5.0, f"/health a mis {ecoule:.1f} s sur la seule lecture de l'estampille"
    # Pas revenue : « je ne sais pas », et surtout pas « ça concorde ».
    assert reponse.json()["embedding_model"]["status"] == "unknown"
    assert reponse.json()["status"] == "ok"


# ─── Ce qu'une requête utilisateur reçoit ─────────────────────────────────────

def test_une_recherche_sur_index_divergent_rend_503_et_non_500(monkeypatch) -> None:
    """Refus de servir, et le code de sortie le dit.

    503 se lit « je ne peux pas servir dans cet état », ce qui est vrai et
    actionnable ; 500 se lit « j'ai un bug », ce qui enverrait chercher au
    mauvais endroit. Le motif doit être dans le corps : les journaux d'un
    conteneur ne sont pas toujours à portée de celui qui lit la réponse.

    Asserté depuis le côté qui produit le comportement — la réponse HTTP — et
    non depuis le gestionnaire d'exception, qu'on peut brancher et ne jamais
    atteindre.
    """
    from src.api import main

    monkeypatch.setattr(main.settings, "api_key", "")
    monkeypatch.setattr(settings, "embedding_model_name", _AUTRE_CANDIDAT)
    monkeypatch.setattr(retriever, "SentenceTransformer", lambda *_a, **_k: None)
    _brancher_collection(monkeypatch, _FausseCollection({"embedding_model": _MODELE_QUI_A_INDEXE}))

    reponse = TestClient(main.app).post("/search", json={"question": "une question"})

    assert reponse.status_code == 503
    detail = reponse.json()["detail"]
    assert _AUTRE_CANDIDAT in detail
    assert _MODELE_QUI_A_INDEXE in detail


# ─── Ce que le démarrage en dit ───────────────────────────────────────────────

def test_le_demarrage_journalise_la_divergence_sans_tuer_le_processus(
    monkeypatch, caplog
) -> None:
    """DÉCISION DU LOT, et son prix : le processus démarre, la recherche refuse.

    Lever dans le `lifespan` tuerait le processus. Ce dépôt a déjà payé cette
    forme-là : `frontend` attend `agent-api` en `service_healthy`, et un
    `agent-api` qui ne démarre pas laisse l'exploitant devant un frontend absent,
    sans message sur le modèle d'embedding. `/health` répond 200 `degraded` en
    nommant la cause, et toute recherche rend 503 : rien de faux n'est servi, et
    la cause est lisible là où on la cherche.

    Ce test entre VRAIMENT dans le `lifespan` — c'est lui le site — avec ses
    dépendances externes branchées.
    """
    from src.api import main
    from src.api.schemas import UsageStats

    async def _rien(*_args, **_kwargs) -> None:
        return None

    async def _faux_stats() -> UsageStats:
        return UsageStats(
            enabled=False, path="/dev/null", interactions=0, sources=0, size_bytes=0
        )

    monkeypatch.setattr(main, "build_checkpointer", _rien)
    monkeypatch.setattr(main, "compile_interactive", lambda _c: object())
    monkeypatch.setattr(main.sessions, "initialiser", _rien)
    monkeypatch.setattr(main, "usage_initialiser", _rien)
    monkeypatch.setattr(main, "usage_stats", _faux_stats)
    monkeypatch.setattr(main, "close_checkpointers", _rien)

    monkeypatch.setattr(settings, "embedding_model_name", _AUTRE_CANDIDAT)
    _brancher_collection(monkeypatch, _FausseCollection({"embedding_model": _MODELE_QUI_A_INDEXE}))
    # Les quatre sondes aussi : non branchées, `nebula_ping` ouvrirait un vrai
    # pool vers un hôte inexistant, dont le `__del__` lève au ramasse-miettes —
    # un bruit qui n'a rien à voir avec ce qui est mesuré ici et qui apparaît ou
    # non selon le moment du GC.
    _brancher_health(monkeypatch)

    with caplog.at_level(logging.ERROR, logger="src.api.main"), TestClient(main.app) as client:
        assert client.get("/health").status_code == 200

    messages = [m for m in caplog.messages if _MODELE_QUI_A_INDEXE in m]
    assert messages, "le démarrage doit nommer la divergence au journal, en ERROR"
    assert any(_AUTRE_CANDIDAT in m for m in messages)


# ─── Deux endroits qui doivent s'accorder ─────────────────────────────────────

def test_le_defaut_du_reglage_est_celui_que_le_contrat_du_pipeline_annonce() -> None:
    """La documentation du contrat recopie le nom du modèle ; rien ne l'y forçait.

    `documentation/pour_le_pipeline_ingestion.md` §1 annonce au producteur le
    modèle que le lecteur attend. Changer le défaut de `settings.py` sans
    corriger ce document laisserait le pipeline estampiller un nom que l'agent
    refuse — le garde de ce lot transformerait alors une documentation périmée en
    déni de service, ce qui est un progrès mais un progrès désagréable.
    """
    from pathlib import Path

    contrat = (
        Path(__file__).resolve().parents[2] / "documentation" / "pour_le_pipeline_ingestion.md"
    ).read_text(encoding="utf-8")
    section = contrat.split("## 2.")[0]

    defaut = type(settings).model_fields["embedding_model_name"].default
    assert defaut in section


# ─── La reprise sur ChromaDB injoignable ──────────────────────────────────────
#
# LA PANNE QUE CETTE SECTION EXISTE POUR RENDRE IMPOSSIBLE, et elle a été
# mesurée sur ce lot avant d'être refermée — `documentation/axes_amelioration.md`
# §4.20, trouvaille B1. `_dense_search` rattrape un ChromaDB redémarré en
# rouvrant la connexion et en retentant UNE fois. `reset_connection()` désarme
# bien le verdict, mais la requête en cours ne repassait pas le garde : la
# collection rouverte pouvait être une AUTRE collection, interrogée sans
# vérification. Une réponse complète et FAUSSE, sans exception ni ligne de
# journal — et une coupure de ChromaDB est précisément le moment où une
# réingestion a pu passer dessous.

def test_la_reprise_apres_reouverture_repasse_le_garde(monkeypatch) -> None:
    """La collection ROUVERTE doit être vérifiée avant d'être interrogée.

    Le montage est fidèle au `lru_cache` — cf. `_ouverture_memoisee` : la
    collection n'avance qu'au `cache_clear()`, donc le seul événement qui la
    change ici est la réouverture de la reprise. Sans cette fidélité, le test
    mesurerait son bouchon et non le code.
    """
    morte = _CollectionMorteALaRequete({"embedding_model": _MODELE_QUI_A_INDEXE})
    divergente = _FausseCollection({"embedding_model": _AUTRE_CANDIDAT})

    monkeypatch.setattr(settings, "embedding_model_name", _MODELE_QUI_A_INDEXE)
    monkeypatch.setattr(settings, "hybrid_search", False)
    monkeypatch.setattr(retriever, "_get_embedding_model", _FauxModeleEmbedding)
    monkeypatch.setattr(
        retriever, "_get_chroma_collection", _ouverture_memoisee([morte, divergente])
    )
    retriever.rearmer_verification_modele()

    with pytest.raises(retriever.EmbeddingModelMismatchError) as leve:
        retriever.retrieve("une question", top_k=5)

    assert _AUTRE_CANDIDAT in str(leve.value)
    assert divergente.requetes == 0, (
        "la collection rouverte a été interrogée sans repasser le garde : "
        "c'est la réponse complète et fausse que ce lot existe pour empêcher"
    )


def test_la_reprise_sert_bien_ce_qu_une_collection_concordante_rend(monkeypatch) -> None:
    """Le témoin de la précédente : la reprise doit continuer de RATTRAPER.

    Un garde qui refuserait aussi la réouverture légitime transformerait la
    résilience de `_dense_search` en panne. Ici la collection rouverte porte la
    même estampille, et la requête doit aboutir.
    """
    morte = _CollectionMorteALaRequete({"embedding_model": _MODELE_QUI_A_INDEXE})
    vivante = _FausseCollection({"embedding_model": _MODELE_QUI_A_INDEXE})

    monkeypatch.setattr(settings, "embedding_model_name", _MODELE_QUI_A_INDEXE)
    monkeypatch.setattr(settings, "hybrid_search", False)
    monkeypatch.setattr(retriever, "_get_embedding_model", _FauxModeleEmbedding)
    monkeypatch.setattr(
        retriever, "_get_chroma_collection", _ouverture_memoisee([morte, vivante])
    )
    retriever.rearmer_verification_modele()

    assert retriever.retrieve("une question", top_k=5) == []
    assert morte.requetes == 1, "la première tentative doit avoir eu lieu"
    assert vivante.requetes == 1, "la reprise doit avoir servi la collection rouverte"


# ─── Le réarmement concurrent ─────────────────────────────────────────────────
#
# LA PANNE, mesurée sur ce lot — §4.20, trouvaille B2. Le site portait que « le
# pire cas est une vérification faite deux fois — un verrou coûterait plus cher
# que ce qu'il éviterait ». C'était FAUX. `verifier_modele_embedding()` LIT
# l'estampille, puis écrit le verdict favorable À LA FIN : un `reset_connection()`
# arrivé entre les deux était ÉCRASÉ par cette écriture. Perte de mise à jour, et
# la conséquence est pire que B1 — le garde reste désarmé pour toute la vie du
# processus, et chaque recherche sert des passages plausibles et faux en silence.
#
# ATTEIGNABLE, et c'est ce qui en fait un bloquant : `reset_connection()` tourne
# dans un fil du threadpool depuis le `ping()` du healthcheck, toutes les 20 s,
# et depuis la reprise de B1.
#
# COMMENT CETTE COURSE EST RENDUE DÉTERMINISTE, et c'est la forme qui compte.
# Deux fils lancés en espérant un entrelacement donnent un test vert par chance
# et rouge au hasard : un garde dont le cas n'est atteint que par chance n'est
# pas un garde. Le réarmement est donc déclenché DEPUIS LE POINT OBSERVABLE DE
# LA LECTURE — `_lire_estampille` — c'est-à-dire exactement dans la fenêtre où
# la perte de mise à jour se produit. L'écriture concurrente vient d'un VRAI
# autre fil, et elle est jointe avant que la lecture ne rende : la course est
# réelle et son ordonnancement est certain.

def _lire_en_rearmant_depuis_un_autre_fil(compte: list[int]):
    """Un `_lire_estampille` qui fait réarmer un AUTRE fil pendant sa lecture.

    Le réarmement est joint avant le retour : quand la lecture rend, l'écriture
    concurrente a EU LIEU, sans dépendre de l'ordonnanceur.
    """
    vrai = retriever._lire_estampille

    def _lire() -> str | None:
        valeur = vrai()
        compte.append(1)
        if len(compte) == 1:
            fil = threading.Thread(target=retriever.reset_connection)
            fil.start()
            fil.join()
        return valeur

    return _lire


def test_un_rearmement_concurrent_pendant_la_lecture_n_est_pas_ecrase(monkeypatch) -> None:
    """Le verdict favorable ne doit pas écraser un réarmement arrivé entre-temps.

    Asserté sur l'état que le réarmement existe pour poser, et non sur le retour
    de la fonction : c'est l'écrasement qui est la panne.
    """
    lectures: list[int] = []
    monkeypatch.setattr(settings, "embedding_model_name", _MODELE_QUI_A_INDEXE)
    _brancher_collection(
        monkeypatch, _FausseCollection({"embedding_model": _MODELE_QUI_A_INDEXE})
    )
    monkeypatch.setattr(
        retriever, "_lire_estampille", _lire_en_rearmant_depuis_un_autre_fil(lectures)
    )

    retriever.verifier_modele_embedding()

    assert lectures == [1], "la lecture doit avoir eu lieu une fois — sinon rien n'est mesuré"
    assert retriever._concordance_etablie is False, (
        "le réarmement concurrent a été écrasé par le verdict favorable : le garde "
        "est désarmé pour toute la vie du processus"
    )


def test_le_garde_refuse_encore_apres_un_rearmement_concurrent(monkeypatch) -> None:
    """La CONSÉQUENCE de la perte de mise à jour, mesurée au comportement.

    C'est ce test-ci qui dit pourquoi B2 est pire que B1 : le verdict écrasé ne
    se répare pas tout seul. Après le réarmement perdu, une collection divergente
    passait — chaque recherche servant alors des passages plausibles et faux, en
    silence, jusqu'au redémarrage du processus.
    """
    lectures: list[int] = []
    monkeypatch.setattr(settings, "embedding_model_name", _MODELE_QUI_A_INDEXE)
    _brancher_collection(
        monkeypatch, _FausseCollection({"embedding_model": _MODELE_QUI_A_INDEXE})
    )
    monkeypatch.setattr(
        retriever, "_lire_estampille", _lire_en_rearmant_depuis_un_autre_fil(lectures)
    )
    retriever.verifier_modele_embedding()
    assert lectures == [1]

    # La réingestion divergente que la coupure a laissée passer.
    monkeypatch.setattr(
        retriever,
        "_get_chroma_collection",
        _fausse_ouverture(_FausseCollection({"embedding_model": _AUTRE_CANDIDAT})),
    )

    with pytest.raises(retriever.EmbeddingModelMismatchError):
        retriever.verifier_modele_embedding()


# ─── Le flux interactif, qui cherche APRÈS le premier octet ───────────────────
#
# CE QUE L'AUDIT A RENVERSÉ, et le pilote avec lui — §4.20, trouvaille N1. Le
# lot avait noté au futur le risque « si une route SSE se met un jour à
# chercher ». C'était déjà le présent : `src/agent/graph.py` porte
# `add_conditional_edges("postprocess", should_search_more, {True: "retrieve",
# False: END})`, donc le graphe REBOUCLE vers `retrieve` après `generate`, et
# `/chat/resume` fait tourner `astream` DANS son `stream_generator`, rendu dans
# un `EventSourceResponse`. `NATIVE_TOOL_CALLING=true` et
# `MAX_SEARCH_ITERATIONS=3` sont les défauts : ce n'est pas un chemin exotique.
#
# CE QUI ÉTAIT MESURÉ AVANT LA CORRECTION : pas de 503, pas de motif dans le
# corps, et pas même la ligne ERROR — la levée arrive après que la réponse a
# commencé, donc le gestionnaire d'exception de l'application n'est jamais
# appelé. Le flux mourait tronqué, sans trace, pendant que quatre documents
# affirmaient « toute recherche est refusée en 503 ».
#
# LA SÛRETÉ, ELLE, TENAIT : la levée est fail-closed, rien de faux n'est servi.
# C'est la PHRASE qui ne tenait pas, et le trou d'observabilité.
#
# `/chat/simple` ne cherche jamais — il n'passe pas par le graphe — et n'est donc
# pas concerné. C'est la seule autre route qui streame.

class _GrapheQuiRebouclleVersRetrieve:
    """Le graphe interactif réduit à la forme qui produit la panne de N1.

    La recherche part de l'INTÉRIEUR du flux, après des jetons déjà servis, et
    c'est le VRAI garde qui est appelé là — pas une exception fabriquée. Un
    bouchon qui lèverait un `EmbeddingModelMismatchError` de sa main mesurerait
    sa propre levée.
    """

    def __init__(self, jetons_avant_recherche: int = 2, avant_la_recherche=None) -> None:
        self.jetons_avant_recherche = jetons_avant_recherche
        self.jetons_servis = 0
        self.avant_la_recherche = avant_la_recherche

    async def aget_state(self, _config):
        class _Instantane:
            values = {"question": "une question"}
            next = ("await_source_selection",)

        return _Instantane()

    async def aupdate_state(self, _config, _valeurs) -> None:
        return None

    async def astream(self, _entree, _config, stream_mode=None):
        for _ in range(self.jetons_avant_recherche):
            self.jetons_servis += 1
            yield "custom", {"token": "La "}
        if self.avant_la_recherche is not None:
            self.avant_la_recherche()
        # Le rebouclage `postprocess → retrieve` : une recherche part ICI, alors
        # que la réponse a commencé. C'est le garde réel qui la filtre.
        retriever.verifier_modele_embedding()
        yield "values", {"response": "jamais atteint"}


_CORPS_RESUME = {
    "thread_id": "un-thread",
    "selected_element_ids": ["abcdef0123"],
    "stream": True,
}


def _flux_resume(client) -> list[dict]:
    """Les événements SSE réellement reçus, jusqu'à ce que le flux s'arrête.

    `raise_server_exceptions=False` est OBLIGATOIRE ici, et c'est le montage qui
    dit la vérité : en production, une levée survenue après le premier octet ne
    remonte pas au client, elle TRONQUE le flux — Starlette rend
    « Caught handled exception, but response already started ». Un `TestClient`
    qui relève l'exception donnerait à ce test une forme que l'exploitant ne
    voit jamais.
    """
    with client.stream("POST", "/chat/resume", json=_CORPS_RESUME) as flux:
        return [
            json.loads(ligne[len("data:"):].strip())
            for ligne in flux.iter_lines()
            if ligne.startswith("data:")
        ]


def test_chat_resume_refuse_en_503_avant_d_ouvrir_le_flux(monkeypatch, caplog) -> None:
    """La route qui streame doit refuser AVANT le premier octet.

    Deux 503 de causes différentes sont indiscernables par le seul code : sans
    `lifespan` monté, `/chat/resume` rend un 503 qui dit « Service en cours de
    démarrage » et n'a jamais vu le garde. Le motif est donc EXIGÉ dans le corps,
    et le graphe est branché pour que ce 503-là ne puisse pas être celui du
    démarrage.
    """
    from src.api import main

    graphe = _GrapheQuiRebouclleVersRetrieve()
    monkeypatch.setattr(main, "_interactive", graphe)
    monkeypatch.setattr(main.settings, "api_key", "")
    monkeypatch.setattr(settings, "embedding_model_name", _AUTRE_CANDIDAT)
    _brancher_collection(
        monkeypatch, _FausseCollection({"embedding_model": _MODELE_QUI_A_INDEXE})
    )

    with caplog.at_level(logging.ERROR, logger="src.api.main"):
        reponse = TestClient(main.app).post("/chat/resume", json=_CORPS_RESUME)

    assert reponse.status_code == 503
    detail = reponse.json()["detail"]
    assert _AUTRE_CANDIDAT in detail and _MODELE_QUI_A_INDEXE in detail, (
        "le corps doit porter le motif : c'est ce qui distingue ce 503 de celui "
        f"du démarrage — reçu {detail!r}"
    )
    assert graphe.jetons_servis == 0, "aucun octet ne doit partir avant le refus"
    assert [m for m in caplog.messages if _AUTRE_CANDIDAT in m], (
        "le refus doit laisser une ligne ERROR : c'est là que l'exploitant "
        "apprend que des requêtes réelles se cassent sur cette panne"
    )


def test_une_divergence_apparue_en_vol_laisse_une_ligne_error(monkeypatch, caplog) -> None:
    """LE RÉSIDU, écrit plutôt que caché.

    La vérification faite avant l'ouverture du flux ne peut pas couvrir une
    divergence qui apparaît APRÈS : `reset_connection()` tourne toutes les 20 s
    depuis le `ping()` du healthcheck, et une réingestion peut passer entre la
    vérification et le rebouclage. Le flux meurt alors tronqué — c'est
    fail-closed, rien de faux n'est servi — mais il ne doit pas mourir MUET.

    Ce test asserte la seule chose qui reste vraie dans ce cas : la trace. Le
    code HTTP, lui, est déjà parti en 200 ; aucune correction ne peut le
    reprendre, et prétendre le contraire serait la phrase que N1 a sanctionnée.
    """
    from src.api import main

    concordante = _FausseCollection({"embedding_model": _MODELE_QUI_A_INDEXE})
    divergente = _FausseCollection({"embedding_model": _AUTRE_CANDIDAT})

    def _la_reingestion_passe_dessous() -> None:
        monkeypatch.setattr(
            retriever, "_get_chroma_collection", _fausse_ouverture(divergente)
        )
        retriever.reset_connection()

    graphe = _GrapheQuiRebouclleVersRetrieve(
        jetons_avant_recherche=2, avant_la_recherche=_la_reingestion_passe_dessous
    )
    monkeypatch.setattr(main, "_interactive", graphe)
    monkeypatch.setattr(main.settings, "api_key", "")
    monkeypatch.setattr(settings, "embedding_model_name", _MODELE_QUI_A_INDEXE)
    _brancher_collection(monkeypatch, concordante)

    client = TestClient(main.app, raise_server_exceptions=False)
    with caplog.at_level(logging.ERROR, logger="src.api.main"):
        evenements = _flux_resume(client)

    assert graphe.jetons_servis == 2, "le flux avait bien commencé — c'est tout le sujet"
    assert not [e for e in evenements if e.get("done")], (
        "le flux doit mourir tronqué : c'est fail-closed, et aucune correction "
        "ne peut reprendre un 200 déjà parti"
    )
    assert [m for m in caplog.messages if _AUTRE_CANDIDAT in m], (
        "une divergence apparue en vol tuait le flux SANS une seule ligne de "
        "journal : le gestionnaire d'exception n'est jamais appelé après le "
        "premier octet"
    )


# ─── Le contrat de la réponse /health ─────────────────────────────────────────

def test_la_reponse_health_exige_le_champ_de_concordance() -> None:
    """`embedding_model` n'est PAS optionnel, et c'est gardé ici.

    La décision est longuement argumentée dans `schemas.py` — une réponse muette
    sur la concordance se lit comme une réponse RASSURANTE, donc l'inconnu a un
    nom (`unknown`) plutôt qu'un null. Elle n'était gardée par rien : le rendre
    optionnel laissait la suite entièrement verte.

    Asserté depuis le côté qui produit la garantie — la validation du modèle —
    et non depuis l'annotation, qu'un `| None` suffit à démentir.
    """
    import pydantic

    from src.api.schemas import HealthResponse

    with pytest.raises(pydantic.ValidationError) as leve:
        HealthResponse(status="ok", ollama_model="un-modele")

    assert "embedding_model" in str(leve.value)


# ─── B-1 : la route ne dépend plus d'un ChromaDB qui PEND ─────────────────────
#
# LA PANNE, trouvaille bloquante de l'audit de la réparation — §4.23, B-1. La
# vérification anticipée de N1 avait été écrite `await
# asyncio.to_thread(verifier_modele_embedding)`, NUE : sans plafond et sans
# garde, sur une opération qui ouvre une collection ChromaDB. `mesuré` avec une
# collection qui pend — un `Event` jamais posé, aucun accès réel au store :
#
#   - ce motif reste bloqué après 6 s, et même avec un `wait_for` que le site
#     n'avait pas ; sans ce `wait_for` il attendrait indéfiniment ;
#   - au niveau de la route, une requête qui NE CHERCHE PAS passait de 0,030 s à
#     AUCUNE réponse ;
#   - `asyncio.run` lui-même ne rend plus la main : sa fermeture joint le fil
#     non-démon du réservoir asyncio ;
#   - 26 requêtes bloquées lâchent 26 fils et n'en rendent AUCUNE.
#
# `chromadb 1.5.9` n'a aucun délai par défaut. L'absorption large du site
# protégeait d'un ChromaDB qui LÈVE ; elle ne pouvait rien contre un ChromaDB qui
# PEND — la panne la plus banale d'un store réseau, et celle que la reprise de
# `_dense_search` existe pour rattraper. *La dépendance était sur l'appel, pas
# sur l'exception.*
#
# LA FORME DE CES TESTS EST DICTÉE PAR UNE CONTRAINTE, et elle mérite d'être
# dite : sur le motif d'avant, un test écrit en appel direct ne rougirait pas —
# il PENDRAIT. Un test qui pend est pire qu'un rouge : il emporte la campagne
# entière au lieu de nommer sa cause. La requête part donc dans un fil DÉMON
# avec une échéance, et ce qui est asserté est qu'elle est REVENUE.

# Échéance accordée à la requête, et plafond de sécurité de la lecture bloquée.
# L'ORDRE DES TROIS VALEURS PORTE, et c'est la condition de validité de la
# mesure : plafond des sondes (0,2 s, monkeypatché) < échéance de la requête
# (5 s) < plafond de sécurité de la lecture (8 s). Si le dernier passait sous
# l'échéance, la lecture rendrait d'elle-même et le test mesurerait son bouchon
# au lieu du code.
#
# Le plafond de sécurité n'est pas une commodité : `to_thread.run_sync(…,
# abandon_on_cancel=True)` ABANDONNE un fil de réservoir anyio qui n'est PAS
# démon — `mesuré` sur anyio 4.15.1, le fil survivant porte
# `nom='AnyIO worker thread'` et `daemon=False`, et un processus qui sort en le
# laissant bloqué est tué par son échéance en `rc=124` — donc un `wait()` sans
# borne retiendrait l'interpréteur à la fin de toute la campagne. C'est CE
# fichier qui l'écrivait juste quand `src/api/main.py` écrivait le contraire ;
# le site est désormais d'accord avec lui.
# Même motif et même valeur qu'à `tests/unit/test_health_parallele.py`, recopiés
# parce que les modules de test de ce dépôt ne s'importent pas entre eux.
_ECHEANCE_REQUETE_S = 5.0
_CAP_SECURITE_S = 8.0
# La charge de la sonde du drapeau, et elle vaut le chiffre que le registre
# PUBLIE. Elle a tourné à 8 pendant un lot alors que la mesure citée partout
# était 26 : un garde qui tourne sous la charge qu'il ne nomme pas laisse
# croire que le chiffre publié est celui qui est tenu. 26 est la charge qui
# épuise le réservoir asyncio, et c'est celle à laquelle la rafale de §4.25 B-2
# lâchait 26 fils.
_CHARGE = 26


class _CollectionQuiPend:
    """Collection dont la LECTURE DE L'ESTAMPILLE ne rend la main que sur ordre.

    C'est le ChromaDB muet, sans ChromaDB : `metadata` est la propriété que
    `_lire_estampille` touche, et c'est là que le vrai client paie son
    aller-retour d'ouverture.

    Compte ses entrées ET les IDENTITÉS des fils qui y passent : le drapeau « en
    vol » ne s'observe nulle part ailleurs. Un second fil lancé se verrait ici.

    PAR IDENTITÉ, ET LE NOM NE SUFFIT PAS — `mesuré` le 7 septembre 2026, et
    c'est ce qui rendait le garde de la rafale structurellement aveugle : TOUS
    les fils du réservoir anyio portent le même `name`,
    `'AnyIO worker thread'`. Un ensemble de NOMS vaut donc 1 même quand 26 fils
    distincts sont passés, et une assertion sur sa taille est verte sur le
    défaut. `ident` est unique par fil vivant ; c'est lui qui compte.
    """

    def __init__(self, plafond: float = _CAP_SECURITE_S) -> None:
        self.debloquer = threading.Event()
        self.entrees = 0
        self.fils: set[int] = set()
        self._verrou = threading.Lock()
        self._plafond = plafond

    @property
    def metadata(self) -> dict[str, str]:
        with self._verrou:
            self.entrees += 1
            ident = threading.current_thread().ident
            assert ident is not None
            self.fils.add(ident)
        self.debloquer.wait(self._plafond)
        return {"embedding_model": _MODELE_QUI_A_INDEXE}

    def count(self) -> int:
        return 4367

    def query(self, **_kwargs) -> dict:
        return {"ids": [[]], "documents": [[]], "metadatas": [[]], "distances": [[]]}


@pytest.fixture
def _drapeau_en_vol_neuf():
    """Le drapeau des sondes vidé avant ET après.

    C'est un état de MODULE, et il est partagé avec la sonde de `/health` — par
    décision, cf. le docstring de `_concordance_avant_le_flux`. Un test qui
    laisserait `modele_embedding` posé ferait SAUTER la lecture des tests
    suivants, qui passeraient verts sans rien lire : le faux vert exact que la
    fixture `autouse` de `tests/conftest.py` existe pour empêcher sur le verdict.
    Même forme qu'à `tests/unit/test_health_parallele.py`.
    """
    from src.api import main

    main._sondes_en_vol.clear()
    yield
    main._sondes_en_vol.clear()


class _GrapheQuiNeCherchePas:
    """Le cas MAJORITAIRE de `/chat/resume` : reconstruire et générer, sans chercher.

    C'est celui que l'absorption large du site existe pour servir, et celui que
    la dépendance non bornée cassait — une requête qui ne touche jamais ChromaDB
    ne rendait plus rien parce qu'une VÉRIFICATION la précédait.
    """

    def __init__(self) -> None:
        self.jetons_servis = 0

    async def aget_state(self, _config):
        class _Instantane:
            values = {"question": "une question"}
            next = ("await_source_selection",)

        return _Instantane()

    async def aupdate_state(self, _config, _valeurs) -> None:
        return None

    async def astream(self, _entree, _config, stream_mode=None):
        self.jetons_servis += 1
        yield "custom", {"token": "La "}
        yield "values", {"response": "une réponse complète"}


def test_chat_resume_rend_meme_quand_l_estampille_ne_repond_jamais(
    monkeypatch, caplog, _drapeau_en_vol_neuf
) -> None:
    """Une requête qui NE CHERCHE PAS ne doit pas dépendre d'un ChromaDB muet.

    Le rouge d'avant n'est pas une assertion, c'est une absence : la requête ne
    revient jamais. C'est pourquoi elle est portée par un fil démon sous
    échéance, et pourquoi l'assertion principale est « elle est revenue ».

    Le flux est exigé COMPLET — pas seulement une réponse HTTP : un 503 rendu par
    la route serait aussi un « retour », et ce serait la panne inverse, celle que
    l'absorption large existe pour empêcher.
    """
    from src.api import main

    pend = _CollectionQuiPend()
    graphe = _GrapheQuiNeCherchePas()
    monkeypatch.setattr(main, "_interactive", graphe)
    monkeypatch.setattr(main.settings, "api_key", "")
    monkeypatch.setattr(main, "_PLAFOND_SONDES_S", 0.2)
    monkeypatch.setattr(settings, "embedding_model_name", _MODELE_QUI_A_INDEXE)
    _brancher_collection(monkeypatch, pend)

    recu: dict = {}

    def _requete() -> None:
        client = TestClient(main.app, raise_server_exceptions=False)
        debut = time.monotonic()
        recu["evenements"] = _flux_resume(client)
        recu["duree"] = time.monotonic() - debut

    fil = threading.Thread(target=_requete, daemon=True)
    try:
        with caplog.at_level(logging.WARNING, logger="src.api.main"):
            fil.start()
            fil.join(timeout=_ECHEANCE_REQUETE_S)

        assert not fil.is_alive(), (
            f"la route n'a rien rendu en {_ECHEANCE_REQUETE_S:.0f} s alors que la "
            "requête ne cherche PAS : une vérification non bornée fait dépendre de "
            "ChromaDB une route qui ne le touche jamais"
        )
        assert pend.entrees == 1, (
            "la lecture bloquée doit avoir été atteinte une fois — sinon ce test "
            f"ne mesure rien du tout (entrées : {pend.entrees})"
        )
        assert graphe.jetons_servis == 1, "le flux doit s'être ouvert malgré le silence du store"
        assert recu["evenements"], "le flux doit avoir servi des événements"
        assert [m for m in caplog.messages if "n'a pas répondu en" in m], (
            "le dépassement doit laisser une ligne : une absorption muette rend "
            "l'exploitant aveugle à un store qui pend"
        )
    finally:
        # Sans quoi le fil de réservoir abandonné — non démon — retient
        # l'interpréteur à la fin de la campagne entière.
        pend.debloquer.set()


@pytest.mark.asyncio
async def test_le_silence_du_store_ne_lache_qu_un_fil_meme_en_rafale_simultanee(
    monkeypatch, _drapeau_en_vol_neuf
) -> None:
    """LA SECONDE DÉCISION, gardée — et gardée sous la forme QUE LA PRODUCTION A.

    Un fil bloqué dans un appel réseau ne s'interrompt pas : renoncer à
    l'attendre le LÂCHE. À `/health` le cadenceur est un tick toutes les 20 s ;
    ici c'est le débit des requêtes utilisateur, que rien ne borne. Sans le
    drapeau, la fuite est d'un fil PAR REQUÊTE.

    CE GARDE A ÉTÉ DÉCORATIF, ET IL FAUT LE DIRE ICI PARCE QUE C'EST ICI QU'ON
    LE CROIRAIT. Dans sa forme d'avant il ATTENDAIT que le drapeau soit posé
    avant de lancer les autres tâches — « l'entrelacement est forcé, et non
    espéré » — donc il CONSTRUISAIT une sérialisation que la production n'a
    jamais, et il restait vert sur un défaut qui lâchait 26 fils. Trouvaille
    bloquante de l'audit étroit de la couche async, §4.25 B-2. Il portait un
    second aveuglement, indépendant du premier : il comptait les fils par NOM,
    et tous les fils du réservoir anyio portent le même. Son assertion aurait
    donc lu « 1 fil » même sous l'entrelacement réel.

    LA FORME EST DONC CELLE DE LA PRODUCTION : la rafale part d'un seul coup,
    dans la MÊME boucle, sans aucune attente entre les tâches — c'est ce que
    font N requêtes HTTP simultanées — et les fils sont comptés par `ident`.

    **CETTE SONDE ATTEINT SON CAS, et c'est mesuré des deux côtés** avec les
    26 requêtes du registre, forme de production, plafond du site à 3,0 s :

        avant §4.25 B-2 — 26/26 rendues en 3,00 s → **26** fils lâchés
        après           — 26/26 rendues en 3,00 s → **1** fil lâché

    et elle a été retournée contre le site d'avant DANS SA FORME DE TEST, où
    elle rougit sur les deux assertions : 26 fils et 26 entrées.
    """
    from src.api import main

    pend = _CollectionQuiPend()
    monkeypatch.setattr(main, "_PLAFOND_SONDES_S", 0.2)
    monkeypatch.setattr(settings, "embedding_model_name", _MODELE_QUI_A_INDEXE)
    _brancher_collection(monkeypatch, pend)

    try:
        # AUCUNE attente ici, et c'est tout le sujet : la rafale est créée en un
        # seul passage, et rien ne laisse à un fil le temps de poser le drapeau.
        rafale = [
            asyncio.create_task(main._concordance_avant_le_flux()) for _ in range(_CHARGE)
        ]
        rendues, restantes = await asyncio.wait(rafale, timeout=_ECHEANCE_REQUETE_S)
        for tache in restantes:
            tache.cancel()

        assert not restantes, (
            f"{len(restantes)} requêtes sur {_CHARGE} n'ont pas rendu la main : "
            "le plafond ne borne rien"
        )
        assert len(pend.fils) == 1, (
            f"{len(pend.fils)} fils lâchés pour une rafale de {_CHARGE} requêtes "
            "simultanées. Le test-et-pose du drapeau doit être ENTIER du côté de "
            "la boucle : posé dans le fil, il arrive après qu'une rafale de la "
            "même boucle a déjà franchi le test, et la fuite redevient d'un fil "
            "par requête — l'audit a mesuré que 26 suffisent à épuiser le "
            "réservoir"
        )
        assert pend.entrees == 1, (
            f"{pend.entrees} entrées dans la lecture bloquée pour {_CHARGE} "
            "requêtes : un seul fil doit y passer. Cette assertion est celle qui "
            "voit la rafale même si le compte des fils se trompe"
        )
        assert "modele_embedding" in main._sondes_en_vol, (
            "le drapeau doit rester POSÉ après la rafale : le fil est lâché, pas "
            "interrompu, et c'est lui qui le retirera en revenant. S'il n'y est "
            "plus, soit il n'a jamais été posé — la fuite redevient d'un fil par "
            "requête — soit cette sonde n'atteint pas son cas"
        )
    finally:
        pend.debloquer.set()


# Budget d'attente qu'une requête utilisateur de `/chat/resume` peut payer pour
# une vérification qu'elle n'a pas demandée. Ce n'est PAS le délai du
# healthcheck : les deux gardes qui bornaient `_PLAFOND_SONDES_S` sont tous deux
# du côté de `/health` — ils exigent `délai du healthcheck > plafond`, soit
# `5 > plafond` —, et la direction dangereuse pour CETTE route est justement
# celle qu'ils laissent libre. `mesuré` : porter `_PLAFOND_SONDES_S` à 4,9 s
# laisse la suite ENTIÈREMENT verte, donc le budget d'une requête utilisateur
# peut passer de 3,0 à 4,9 s — +63 % — sans un seul rouge. La borne existait
# par ACCIDENT, pas par un garde qui la nomme.
_BUDGET_REQUETE_UTILISATEUR_S = 3.0


def test_le_plafond_ne_depasse_pas_le_budget_d_une_requete_utilisateur() -> None:
    """Le plafond des sondes est AUSSI le budget d'une requête, et il est borné ici.

    `_PLAFOND_SONDES_S` a deux emplois depuis que l'anticipation de concordance
    l'emprunte : la latence que `/health` s'accorde, et **le temps qu'une requête
    utilisateur attend pour une vérification qu'elle n'a pas demandée**. Le
    second n'était borné par rien dans la bande sous 5 s.

    Ce garde nomme la direction dangereuse pour la route. Relever le plafond est
    une modification tout à fait plausible — c'est le geste naturel quand une
    sonde devient lente — et elle doit heurter une ligne qui dit ce qu'elle
    coûte, pas passer inaperçue parce que `/health` a encore sa marge.

    Il est délibérément SÉPARÉ du garde de `/health` : les deux bornes se lisent
    en sens inverse et une seule assertion ne peut pas les tenir toutes deux.
    """
    from src.api import main

    assert main._PLAFOND_SONDES_S <= _BUDGET_REQUETE_UTILISATEUR_S, (
        f"le plafond des sondes vaut {main._PLAFOND_SONDES_S} s, et c'est ce "
        f"qu'une requête `/chat/resume` attend pour une vérification qu'elle n'a "
        f"pas demandée. Au-delà de {_BUDGET_REQUETE_UTILISATEUR_S} s la décision "
        "n'est plus « borner une sonde » mais « faire payer l'utilisateur », et "
        "elle demande d'être écrite. La marge du healthcheck (5 s) n'autorise "
        "pas cette hausse : elle ne parle pas de cette route"
    )


@pytest.mark.asyncio
async def test_le_depassement_rend_son_jeton_au_reservoir(
    monkeypatch, _drapeau_en_vol_neuf
) -> None:
    """`tache.cancel()` au dépassement, et ce que son absence coûterait.

    Ce que cette ligne achète n'est pas le délai — il vient d'`asyncio.wait` —
    mais la RESTITUTION du jeton de réservoir anyio. Sans elle, la tâche reste
    en attente et son jeton avec elle : `borrowed` ne retombe pas, et le
    réservoir que les endpoints de recherche partagent se vide pour de bon au
    bout de 40 dépassements.

    `mesuré` : à l'annulation, `borrowed` retombe à **0** alors que le fil tourne
    TOUJOURS — c'est bien le jeton qui est rendu, pas le fil qui est mort.

    LA RESTITUTION N'EST PAS SYNCHRONE, et ce test a commencé par échouer
    là-dessus : `tache.cancel()` ne fait que DEMANDER l'annulation, qui est
    délivrée au tour de boucle suivant. Le jeton revient donc après un `await`,
    pas au retour de la route. C'est sans conséquence en production — la route
    rend la main aussitôt après — mais il faut le dire, sans quoi la boucle
    d'attente ci-dessous ressemblerait à une commodité.

    Rien ne gardait cet appel : le supprimer laissait la suite verte, alors que
    c'est lui qui rend la route survivable à répétition.
    """
    from anyio import to_thread

    from src.api import main

    pend = _CollectionQuiPend()
    monkeypatch.setattr(main, "_PLAFOND_SONDES_S", 0.2)
    monkeypatch.setattr(settings, "embedding_model_name", _MODELE_QUI_A_INDEXE)
    _brancher_collection(monkeypatch, pend)

    limiteur = to_thread.current_default_thread_limiter()
    try:
        await main._concordance_avant_le_flux()

        assert pend.entrees == 1, (
            "la lecture bloquée n'a pas été atteinte : sans jeton emprunté, ce "
            "test ne mesure rien"
        )
        # L'annulation est délivrée au tour de boucle suivant ; on lui laisse des
        # tours, bornés, plutôt qu'un délai en dur.
        for _ in range(100):
            if limiteur.borrowed_tokens == 0:
                break
            await asyncio.sleep(0.01)

        # Le fil tourne toujours — c'est la condition de validité : ce qui est
        # asserté est que le JETON est rendu malgré un fil vivant.
        assert pend.debloquer.is_set() is False, (
            "le fil doit être ENCORE bloqué : si la lecture avait rendu d'elle-même, "
            "le jeton serait revenu sans que `tache.cancel()` y soit pour rien"
        )
        assert limiteur.borrowed_tokens == 0, (
            f"{limiteur.borrowed_tokens} jeton(s) de réservoir encore emprunté(s) "
            "après le dépassement. `tache.cancel()` est ce qui les rend : sans "
            "lui, 40 dépassements épuisent le réservoir partagé et plus aucune "
            "recherche ne peut s'offloader"
        )
        assert limiteur.statistics().tasks_waiting == 0, (
            "une tâche attend encore une place : le dépassement n'a pas relâché "
            "son attente"
        )
    finally:
        pend.debloquer.set()


@pytest.mark.asyncio
async def test_un_fil_qui_ne_demarre_jamais_ne_laisse_pas_le_drapeau_pose(
    monkeypatch, _drapeau_en_vol_neuf
) -> None:
    """L'OBJECTION QUE LE SITE OPPOSAIT À LA POSE CÔTÉ BOUCLE, gardée.

    Poser le drapeau côté boucle ouvre une fenêtre que le site nommait pour
    refuser cette pose : *si la tâche est annulée avant que le fil ne démarre —
    réservoir saturé —, plus personne ne retire le drapeau et la sonde reste
    « en vol » à jamais.* L'objection ne pouvait pas servir de motif de refus, le
    code d'avant atteignant déjà la cécité définitive dès qu'un fil pend pour de
    bon ; mais elle est réelle, et elle est traitée plutôt que laissée ouverte.

    `_sonder` la ferme avec l'accusé de démarrage que le fil pose : si l'offload
    se termine par une exception SANS que le fil ait démarré, la boucle retire le
    drapeau elle-même. Sans ce retrait, la sonde serait morte pour la vie du
    processus.

    CETTE SONDE ATTEINT SON CAS, et deux assertions le vérifient AVANT celle qui
    porte : le réservoir est ramené à une seule place et cette place est
    occupée, donc `tasks_waiting == 1` — le fil ne peut PAS démarrer. Retournée
    contre la suppression du retrait, elle rougit : le drapeau reste posé.
    """
    from anyio import to_thread

    from src.api import main

    limiteur = to_thread.current_default_thread_limiter()
    jetons_initiaux = limiteur.total_tokens
    occupe = threading.Event()
    dedans = threading.Event()

    def _squatteur() -> None:
        dedans.set()
        occupe.wait(_CAP_SECURITE_S)

    try:
        # Une seule place, et elle sera prise : le fil de la sonde ne démarrera
        # pas, quoi qu'il arrive.
        limiteur.total_tokens = 1
        squat = asyncio.create_task(
            to_thread.run_sync(_squatteur, abandon_on_cancel=True)
        )
        for _ in range(400):
            if dedans.is_set():
                break
            await asyncio.sleep(0.01)
        assert dedans.is_set(), (
            "le squatteur n'a jamais pris la place du réservoir : cette sonde "
            "n'atteint pas son cas et son vert ne prouverait rien"
        )

        sonde = asyncio.create_task(
            main._sonder("sonde_du_montage", lambda: True, appelant="/montage")
        )
        for _ in range(400):
            if limiteur.statistics().tasks_waiting == 1:
                break
            await asyncio.sleep(0.01)
        assert limiteur.statistics().tasks_waiting == 1, (
            "la sonde n'attend PAS une place de réservoir : son fil a pu démarrer, "
            "donc ce test ne mesure pas la fenêtre qu'il existe pour garder"
        )
        assert "sonde_du_montage" in main._sondes_en_vol, (
            "le drapeau doit être posé par la BOUCLE avant que le fil démarre — "
            "c'est la correction de §4.25 B-2 ; s'il n'y est pas, la rafale n'est "
            "plus bornée"
        )

        sonde.cancel()
        with pytest.raises(asyncio.CancelledError):
            await sonde

        assert "sonde_du_montage" not in main._sondes_en_vol, (
            "le fil n'a JAMAIS démarré, donc personne ne retirera le drapeau : la "
            "sonde est morte pour la vie du processus. `/health` publierait "
            "`unknown` à jamais et l'anticipation de `/chat/resume` ne "
            "reprendrait plus. C'est la fenêtre que la pose côté boucle ouvre, et "
            "que la boucle doit refermer elle-même"
        )
    finally:
        occupe.set()
        squat.cancel()
        limiteur.total_tokens = jetons_initiaux


@pytest.mark.asyncio
async def test_l_absorption_n_est_pas_muette_au_deuxieme_passage(
    monkeypatch, caplog, _drapeau_en_vol_neuf
) -> None:
    """« L'absorption n'est pas muette » — et elle l'était, dès le passage 2.

    `mesuré` : sur 6 requêtes contre un store qui pend, le site n'émettait
    **1 seule** ligne `WARNING` — celle du premier dépassement — et 5 en `DEBUG`.
    Les passages 2..N sautaient leur anticipation SANS trace exploitable, alors
    que le site écrit que l'absorption n'est pas muette. Un exploitant qui ne
    monte pas le niveau à DEBUG en production — c'est-à-dire tous — voyait une
    seule ligne pour une panne qui dure.

    Et la ligne NOMME SA ROUTE. `_sonder` est partagée entre `/health` et
    `/chat/resume` depuis l'anticipation de concordance, et son journal était
    resté écrit pour un seul appelant : émise depuis `/chat/resume`, elle
    annonçait `/health`. Un exploitant qui lit « /health » ne va pas chercher la
    latence d'une requête utilisateur.
    """
    from src.api import main

    pend = _CollectionQuiPend()
    monkeypatch.setattr(main, "_PLAFOND_SONDES_S", 0.2)
    monkeypatch.setattr(settings, "embedding_model_name", _MODELE_QUI_A_INDEXE)
    _brancher_collection(monkeypatch, pend)

    passages = 6
    try:
        with caplog.at_level(logging.WARNING, logger="src.api.main"):
            for _ in range(passages):
                await main._concordance_avant_le_flux()

        assert pend.entrees == 1, (
            "le drapeau doit avoir fait sauter les passages 2..N — sinon ce test "
            f"ne mesure pas le silence de l'absorption (entrées : {pend.entrees})"
        )

        renonces = [m for m in caplog.messages if "encore en vol" in m]
        assert len(renonces) == passages - 1, (
            f"{len(renonces)} ligne(s) WARNING pour {passages - 1} passages qui "
            "ont renoncé à leur verdict. En DEBUG, ces passages sont muets pour "
            "l'exploitant : la panne dure et le journal n'en dit plus rien"
        )
        assert all("/chat/resume" in m for m in renonces), (
            "la ligne doit nommer la route qui sonde. `_sonder` est partagée ; "
            f"un journal qui annonce la mauvaise route égare : {renonces[:1]}"
        )
        assert not any("/health" in m for m in renonces), (
            "émise depuis `/chat/resume`, cette ligne annonçait `/health` — le "
            "journal de `_sonder` était resté écrit pour un seul appelant"
        )
    finally:
        pend.debloquer.set()


@pytest.mark.asyncio
async def test_le_drapeau_est_retire_quand_le_store_rend_la_main(
    monkeypatch, _drapeau_en_vol_neuf
) -> None:
    """LE TÉMOIN DE LA CORRECTION DE B-2 : borner la rafale sans acheter la cécité.

    Poser le drapeau côté boucle borne la rafale ; le poser SANS que personne ne
    le retire échangerait une fuite bornée contre une sonde morte à jamais —
    `/health` publierait `unknown` pour toujours et l'anticipation de
    `/chat/resume` ne reprendrait jamais. C'est l'objection que le site opposait
    à cette pose, et ce test est ce qui autorise à ne plus l'invoquer.

    Le retrait est resté CÔTÉ FIL, donc il arrive quand le store rend la main —
    et pas au plafond, où le fil tourne encore.
    """
    from src.api import main

    pend = _CollectionQuiPend()
    monkeypatch.setattr(main, "_PLAFOND_SONDES_S", 0.2)
    monkeypatch.setattr(settings, "embedding_model_name", _MODELE_QUI_A_INDEXE)
    _brancher_collection(monkeypatch, pend)

    try:
        await main._concordance_avant_le_flux()
        assert "modele_embedding" in main._sondes_en_vol, (
            "sans drapeau posé pendant que le fil tourne, ce test ne mesure rien"
        )

        pend.debloquer.set()
        for _ in range(400):
            if "modele_embedding" not in main._sondes_en_vol:
                break
            await asyncio.sleep(0.01)
        assert "modele_embedding" not in main._sondes_en_vol, (
            "le store a rendu la main et le drapeau est TOUJOURS posé : la sonde "
            "est morte pour la vie du processus, et la fuite bornée a été payée "
            "d'une cécité définitive"
        )
    finally:
        pend.debloquer.set()

    # Et la sonde repart pour de bon : le drapeau retiré ne suffit pas à le dire,
    # encore faut-il qu'une lecture neuve soit RÉELLEMENT effectuée.
    revenue = _CollectionQuiPend()
    revenue.debloquer.set()
    _brancher_collection(monkeypatch, revenue)
    await main._concordance_avant_le_flux()
    assert revenue.entrees == 1, (
        "après réparation du store, la sonde suivante doit lire à nouveau "
        f"(entrées : {revenue.entrees})"
    )


@pytest.mark.asyncio
async def test_une_divergence_revenue_dans_le_plafond_est_toujours_relevee(
    monkeypatch, _drapeau_en_vol_neuf
) -> None:
    """TÉMOIN DU PLAFOND : il ne doit pas avaler ce qu'il existe pour laisser passer.

    Borner la lecture et absorber son dépassement ouvre une manière de tout
    perdre : réemployer `_relever`, qui ABSORBE ce qu'une sonde a levé et publie
    `si_levee`. C'est juste pour `/health`, qui doit rendre 200 même dégradée, et
    faux ici — le 503 et les deux noms de modèles dans le corps en dépendent.

    Ce témoin est le pendant de celui de B1 : un garde qui refuserait la
    réouverture légitime transformerait la résilience en panne ; un plafond qui
    avalerait la divergence transformerait la borne en cécité.
    """
    from src.api import main

    monkeypatch.setattr(main, "_PLAFOND_SONDES_S", 0.2)
    monkeypatch.setattr(settings, "embedding_model_name", _AUTRE_CANDIDAT)
    _brancher_collection(
        monkeypatch, _FausseCollection({"embedding_model": _MODELE_QUI_A_INDEXE})
    )

    with pytest.raises(retriever.EmbeddingModelMismatchError) as leve:
        await main._concordance_avant_le_flux()

    assert _AUTRE_CANDIDAT in str(leve.value) and _MODELE_QUI_A_INDEXE in str(leve.value)


# ─── NB-1 : l'ordre des deux lignes de `reset_connection()` ───────────────────
#
# CE QUE CE GARDE EXISTE POUR RENDRE IMPOSSIBLE — §4.23, NB-1. `reset_connection()`
# fait `cache_clear()` PUIS `rearmer_verification_modele()`, et c'est le bon
# ordre. `mesuré` par le pilote : **inversé, les 552 tests restaient VERTS**,
# `rc=0`, zéro rouge. L'ordre inverse rend un verdict favorable MÉMORISÉ sur une
# collection divergente — c'est B2 réintroduit à l'identique, par un
# réordonnancement de deux lignes adjacentes que rien ne documentait.
#
# LE COMPARE-ET-ÉCHANGE NE PEUT RIEN CONTRE ÇA, et c'est ce qui rend le cas
# contre-intuitif : il protège d'un réarmement survenu PENDANT la lecture, pas
# d'un réarmement survenu AVANT une lecture qui porte encore sur l'ancien cache.
#
# LA FENÊTRE EST ÉTROITE EN PRODUCTION — deux appels C successifs — et la sonde
# de concurrence de l'auditeur, sur des millions d'itérations, ne l'a pas
# touchée. C'est pourquoi ce garde emploie l'ENTRELACEMENT FORCÉ que ce fichier
# emploie déjà : espérer la course la rendrait injoignable, donc décorative.
#
# CE QUI CHANGE PAR RAPPORT À L'ENTRELACEMENT DE B2, et c'est la difficulté de ce
# garde : là-bas le point observable était la LECTURE, ici c'est la COUTURE entre
# les deux lignes. Le test ne connaît donc pas leur ordre — il instrumente les
# DEUX primitives et fait vérifier un autre fil juste après celle qui passe la
# PREMIÈRE. C'est ce qui le rend sensible à l'inversion sans qu'il ait à la
# nommer, et c'est la seule forme qui interdit de le satisfaire en réordonnant le
# test lui-même.

def _coudre_une_verification_entre_les_deux_lignes(monkeypatch, collections, journal):
    """Instrumente les deux lignes de `reset_connection()` et coud la course.

    Après la PREMIÈRE des deux qui passe — quelle qu'elle soit — un VRAI autre
    fil vérifie la concordance, et il est JOINT avant de rendre la main. La
    course est réelle, elle traverse une frontière de fil, et son ordonnancement
    est certain : aucun `sleep`, aucune attente d'ordonnanceur.

    Le bouchon d'ouverture est fidèle au `lru_cache` — la collection n'avance
    QU'AU `cache_clear()`, cf. `_ouverture_memoisee` — sans quoi le test
    mesurerait son montage.
    """
    ouverture = _ouverture_memoisee(collections)
    vrai_vidage = ouverture.cache_clear
    vrai_rearmement = retriever.rearmer_verification_modele
    coupee = {"faite": False}

    def _verifier_depuis_un_autre_fil() -> None:
        if coupee["faite"]:
            return
        coupee["faite"] = True

        def _cible() -> None:
            try:
                retriever.verifier_modele_embedding()
                journal.append("verdict")
            except retriever.EmbeddingModelMismatchError:
                journal.append("refus")

        fil = threading.Thread(target=_cible)
        fil.start()
        fil.join()

    def _vidage_instrumente() -> None:
        vrai_vidage()
        journal.append("vidage")
        _verifier_depuis_un_autre_fil()

    def _rearmement_instrumente() -> None:
        vrai_rearmement()
        journal.append("rearmement")
        _verifier_depuis_un_autre_fil()

    ouverture.cache_clear = _vidage_instrumente
    monkeypatch.setattr(retriever, "_get_chroma_collection", ouverture)
    monkeypatch.setattr(retriever, "rearmer_verification_modele", _rearmement_instrumente)


def test_l_ordre_de_reset_connection_ne_peut_pas_s_inverser_en_silence(monkeypatch) -> None:
    """Vider le cache AVANT de réarmer, sous peine de rendre B2 à l'identique.

    Asserté sur la CONSÉQUENCE et non sur l'ordre des lignes, qu'on peut lire
    faux : après la réouverture, la collection est divergente, et le garde doit
    la refuser. Dans l'ordre inversé il ne la refuse pas — un verdict favorable
    établi sur l'ancienne collection a été mémorisé, et il ne se répare pas tout
    seul : chaque recherche servirait des passages plausibles et faux jusqu'au
    redémarrage du processus.
    """
    concordante = _FausseCollection({"embedding_model": _MODELE_QUI_A_INDEXE})
    divergente = _FausseCollection({"embedding_model": _AUTRE_CANDIDAT})
    journal: list[str] = []

    monkeypatch.setattr(settings, "embedding_model_name", _MODELE_QUI_A_INDEXE)
    retriever.rearmer_verification_modele()
    _coudre_une_verification_entre_les_deux_lignes(
        monkeypatch, [concordante, divergente], journal
    )

    retriever.reset_connection()

    assert "vidage" in journal and "rearmement" in journal, (
        f"les deux lignes doivent avoir été exercées — sinon ce test ne mesure "
        f"rien (journal : {journal})"
    )
    assert journal.count("verdict") + journal.count("refus") == 1, (
        f"la vérification concurrente doit avoir eu lieu exactement une fois, "
        f"cousue entre les deux lignes (journal : {journal})"
    )
    assert retriever._concordance_etablie is False, (
        "un verdict favorable a été MÉMORISÉ pendant `reset_connection()`, alors "
        "que la collection rouverte n'a pas encore été lue : c'est B2 réintroduit "
        "par l'ordre des deux lignes — `cache_clear()` doit passer AVANT "
        f"`rearmer_verification_modele()` (journal : {journal})"
    )

    with pytest.raises(retriever.EmbeddingModelMismatchError):
        retriever.verifier_modele_embedding()
