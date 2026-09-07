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
