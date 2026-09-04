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

import logging
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

    class _FauxModele:
        def encode(self, _texte):
            class _Vecteur:
                @staticmethod
                def tolist() -> list[float]:
                    return [0.0] * 384

            return _Vecteur()

    collection = _FausseCollection({"embedding_model": _MODELE_QUI_A_INDEXE})
    monkeypatch.setattr(settings, "embedding_model_name", _MODELE_QUI_A_INDEXE)
    monkeypatch.setattr(settings, "hybrid_search", False)
    monkeypatch.setattr(retriever, "_get_embedding_model", lambda: _FauxModele())
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

    Rendre 500 ou 503 ici ferait redémarrer le service en boucle, ce que cette
    route existe pour éviter (cf. `test_health_parallele.py`). Le statut dégradé
    est le canal prévu.
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
