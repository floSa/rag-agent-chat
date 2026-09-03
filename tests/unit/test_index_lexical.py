"""L'index lexical face à un corpus qui bouge, et à des requêtes concurrentes.

Deux défauts d'une même origine : l'index était construit UNE fois, au premier
besoin, et rien ne le reconstruisait jamais.

- l'ingestion est un service SÉPARÉ qui écrit dans ChromaDB pendant que l'agent
  tourne. Un document ingéré après le démarrage restait trouvable en recherche
  dense — la requête part à Chroma à chaque fois — et devenait invisible en
  lexical jusqu'au prochain redémarrage. /health continuait d'annoncer
  `index_lexical: true` : il l'était, il décrivait un corpus disparu ;
- le test « déjà prêt » se faisait HORS VERROU, et la lecture du corpus avec
  lui. N requêtes arrivant avant que l'index soit prêt payaient N fois le
  parcours complet du corpus (« ~9 s » dans la documentation — chiffre non
  mesuré, cf. `retriever._charger_corpus`).

Le second ne se voit pas avec un test « ça tient » : compter les constructions
est ce qui le rend visible, pas constater que l'index finit construit.
"""

import threading

import pytest

from src.agent import retriever
from src.agent.lexical import LexicalIndex

# Trois documents au minimum, et ce n'est pas cosmétique : l'IDF de BM25 vaut
# exactement zéro pour un terme présent dans 1 document sur 2
# (log(N−n+0.5) − log(n+0.5) = 0), donc `search` filtre le résultat comme nul.
# Un corpus à deux documents rend la recherche lexicale intestable.
CORPUS_INITIAL = {
    "c1": "La norme ISO 27001 encadre la sécurité de l'information.",
    "c2": "Le calcul de l'écart-type mesure la dispersion.",
    "c4": "Le théorème central limite fonde l'inférence statistique.",
}
DOCUMENT_INGERE_APRES = {"c3": "Les conteneurs Docker isolent les dépendances."}
# Corpus de remplacement complet : aucun identifiant de CORPUS_INITIAL n'y
# survit, et trois documents pour que l'IDF reste exploitable.
CORPUS_REMPLACE = {
    "z9": "La norme ISO 27001 encadre la sécurité.",
    "z8": "Le calcul de la médiane résiste aux valeurs extrêmes.",
    "z7": "Les journaux structurés facilitent la corrélation.",
}


class CollectionFactice:
    """ChromaDB réduit à ce dont l'index lexical a besoin, et qui COMPTE ses lectures.

    Le nombre de parcours complets est l'observable : c'est lui qui distingue
    « l'index finit construit » de « l'index n'est construit qu'une fois ».
    """

    def __init__(self, documents: dict[str, str], latence: float = 0.0) -> None:
        self.documents = dict(documents)
        self.lectures = 0
        self.latence = latence

    def count(self) -> int:
        return len(self.documents)

    def get(self, **kwargs):
        if "ids" in kwargs:
            ids = [i for i in kwargs["ids"] if i in self.documents]
            return {
                "ids": ids,
                "documents": [self.documents[i] for i in ids],
                "metadatas": [
                    {"element_id": i, "filename": "f.html", "page_no": 1, "label": "paragraph"}
                    for i in ids
                ],
            }
        self.lectures += 1
        if self.latence:
            # Élargit la fenêtre pendant laquelle une autre requête peut décider
            # de construire elle aussi : sans cela le défaut est invisible sur
            # une machine rapide.
            threading.Event().wait(self.latence)
        offset = int(kwargs.get("offset", 0))
        limite = int(kwargs.get("limit", len(self.documents)))
        items = list(self.documents.items())[offset : offset + limite]
        return {"ids": [i for i, _ in items], "documents": [d for _, d in items]}


@pytest.fixture
def collection(monkeypatch):
    """Index lexical neuf et collection factice, pour chaque test."""
    coll = CollectionFactice(CORPUS_INITIAL)
    monkeypatch.setattr(retriever, "_lexical_index", LexicalIndex())
    monkeypatch.setattr(retriever, "_get_chroma_collection", lambda: coll)
    monkeypatch.setattr(retriever, "_reconstruction", None)
    return coll


# ─── Un corpus qui grandit sous l'index ───────────────────────────────────────

def test_un_document_ingere_apres_la_construction_devient_trouvable(collection) -> None:
    """Le défaut : « Docker » restait introuvable en lexical jusqu'au redémarrage.

    La reconstruction est programmée en tâche de fond — la requête qui découvre
    la dérive ne doit pas payer le parcours du corpus d'une ingestion à laquelle elle
    n'a pas participé — donc le test l'attend explicitement au lieu de supposer
    qu'elle a eu lieu.
    """
    assert retriever._lexical_search("ISO 27001", 5), "l'index doit d'abord se construire"
    assert retriever._lexical_search("Docker conteneurs", 5) == []

    collection.documents.update(DOCUMENT_INGERE_APRES)

    # Cette requête constate la dérive et programme la reconstruction ; elle est
    # servie par l'index périmé, ce qui est le comportement voulu.
    retriever._lexical_search("Docker conteneurs", 5)
    retriever._reconstruction.join(timeout=10)

    trouves = retriever._lexical_search("Docker conteneurs", 5)
    assert [c.chunk_id for c in trouves] == ["c3"]


def test_health_ne_declare_pas_pret_un_index_perime(collection) -> None:
    """« index_lexical: true » décrivait un corpus qui n'existait plus.

    Les deux états sont indistinguables pour l'utilisateur — la recherche est
    amputée dans les deux cas — mais seul le faux le dit.
    """
    retriever._lexical_search("ISO 27001", 5)
    assert retriever.lexical_ready() is True

    collection.documents.update(DOCUMENT_INGERE_APRES)

    assert retriever.lexical_ready() is False


def test_un_compte_de_collection_illisible_ne_declare_pas_l_index_perime(
    collection, monkeypatch
) -> None:
    """« je ne sais pas » ne doit pas devenir « c'est périmé ».

    Chroma injoignable est déjà rapporté par `services.chromadb` dans la même
    réponse de /health. Le déduire une seconde fois ici transformerait une panne
    de store en index déclaré faux, donc en reconstructions inutiles.
    """
    retriever._lexical_search("ISO 27001", 5)

    def compte_illisible() -> int:
        raise ConnectionError("ChromaDB a redémarré")

    monkeypatch.setattr(collection, "count", compte_illisible)

    assert retriever.lexical_stale() is False
    assert retriever.lexical_ready() is True


def test_la_reconstruction_de_fond_n_est_programmee_qu_une_fois(collection) -> None:
    """Dix requêtes qui constatent la même dérive ne lancent qu'une reconstruction."""
    retriever._lexical_search("ISO 27001", 5)
    lectures_apres_construction = collection.lectures
    collection.documents.update(DOCUMENT_INGERE_APRES)
    collection.latence = 0.05

    fils = [
        threading.Thread(target=retriever._lexical_search, args=("ISO 27001", 5))
        for _ in range(10)
    ]
    for fil in fils:
        fil.start()
    for fil in fils:
        fil.join(timeout=10)
    retriever._reconstruction.join(timeout=10)

    assert collection.lectures == lectures_apres_construction + 1


# ─── Le serrage : N requêtes, UNE construction ────────────────────────────────

def test_n_requetes_concurrentes_ne_construisent_l_index_qu_une_fois(collection) -> None:
    """Le test de SERRAGE, et non « l'index finit construit ».

    Le test « ça tient » est vert des deux côtés du défaut : l'index EST
    construit dans les deux cas. Ce qui voit la panne, c'est le compteur —
    huit requêtes arrivant avant que l'index soit prêt déclenchaient huit
    parcours complets du corpus et huit constructions de BM25, dont sept étaient
    jetées. La latence de lecture élargit la fenêtre : sans elle, un corpus de
    test se lit trop vite pour que deux fils se croisent.
    """
    collection.latence = 0.05
    resultats: list[int] = []

    def chercher() -> None:
        retriever._lexical_search("ISO 27001", 5)
        resultats.append(1)

    fils = [threading.Thread(target=chercher) for _ in range(8)]
    for fil in fils:
        fil.start()
    for fil in fils:
        fil.join(timeout=20)

    assert len(resultats) == 8, "les huit requêtes doivent aboutir"
    # Les lectures d'abord : c'est l'observable qui existe des deux côtés du
    # correctif, et celle qui coûte le parcours complet du corpus.
    assert collection.lectures == 1
    assert retriever._lexical_index.constructions == 1


# ─── Le contrat, plutôt que l'heuristique ─────────────────────────────────────

def test_reindex_reconstruit_sur_le_corpus_courant(collection) -> None:
    """`POST /reindex` est ce que l'ingestion appelle en fin de pipeline.

    L'heuristique du compte de chunks ne voit pas un corpus dont on a retiré
    autant d'éléments qu'on en a ajouté ; un contrat explicite, oui.
    """
    retriever._lexical_search("ISO 27001", 5)
    collection.documents.update(DOCUMENT_INGERE_APRES)

    assert retriever.rebuild_lexical_index() == 4  # noqa: PLR2004
    assert retriever.lexical_stale() is False
    assert [c.chunk_id for c in retriever._lexical_search("Docker conteneurs", 5)] == ["c3"]


def test_l_endpoint_reindex_rend_la_taille_de_l_index(collection, monkeypatch) -> None:
    """La réponse porte un nombre que l'ingestion peut confronter au sien."""
    from fastapi.testclient import TestClient

    from src.agent.settings import settings
    from src.api import main

    monkeypatch.setattr(settings, "checkpoint_db_path", "")
    monkeypatch.setattr(settings, "usage_capture", False)

    with TestClient(main.app) as client:
        corps = client.post("/reindex").json()

    assert corps == {"chunks_indexed": 3, "stale": False}


# ─── Le remplacement d'index sous une recherche ───────────────────────────────

def test_un_index_reconstruit_ne_rend_jamais_un_identifiant_de_l_ancien(collection) -> None:
    """L'index et ses identifiants sont remplacés d'un seul coup.

    Ils vivaient dans deux attributs distincts, affectés l'un après l'autre : une
    recherche qui s'intercalait lisait les rangs du NOUVEAU BM25 dans l'ANCIENNE
    liste — donc les mauvais chunks, ou un `IndexError` si la liste a rétréci. La
    fenêtre n'existait pas tant que l'index était construit une seule fois ; elle
    s'ouvre dès qu'une reconstruction a lieu pendant que le service répond.
    """
    retriever._lexical_search("ISO 27001", 5)
    collection.documents.clear()
    collection.documents.update(CORPUS_REMPLACE)

    retriever.rebuild_lexical_index()

    assert [c for c, _ in retriever._lexical_index.search("ISO 27001", 5)] == ["z9"]


def test_des_reindexations_concurrentes_sont_fusionnees(collection) -> None:
    """Répéter `POST /reindex` ne doit pas enchaîner N parcours du corpus.

    Le verrou de `LexicalIndex` sérialise les constructions ; il ne les fusionne
    pas. Six appels simultanés produisaient donc six parcours à la queue leu leu,
    chacun mobilisant un fil du threadpool FastAPI le temps d'un parcours — et les
    endpoints de recherche vivent dans ce même threadpool.
    """
    retriever._lexical_search("ISO 27001", 5)
    lectures_apres_construction = collection.lectures
    collection.latence = 0.05
    tailles: list[int] = []

    fils = [
        threading.Thread(target=lambda: tailles.append(retriever.rebuild_lexical_index()))
        for _ in range(6)
    ]
    for fil in fils:
        fil.start()
    for fil in fils:
        fil.join(timeout=20)

    assert len(tailles) == 6, "les six appels doivent aboutir"  # noqa: PLR2004
    assert set(tailles) == {len(CORPUS_INITIAL)}, "tous rendent la taille de l'index"
    assert collection.lectures == lectures_apres_construction + 1


# ─── Ce que POST /reindex fait et que le filet ne fait pas ────────────────────

def test_reindex_repare_une_derive_que_le_compte_ne_peut_pas_voir(collection) -> None:
    """Le contrat couvre le cas exact où le filet est aveugle, et rien ne le tenait.

    Trois docstrings l'affirment — `retriever.lexical_stale`,
    `api.main.reindex`, et `pipeline/reindex.py` du dépôt d'ingestion — et
    AUCUN test ne l'assertait : « un corpus dont on a retiré autant de chunks
    qu'on en a ajouté affiche le même compte ». Une phrase ne rougit pas.

    Le scénario est celui d'une réingestion d'un corpus déjà présent : tous les
    identifiants changent, le compte ne bouge pas. `lexical_stale()` compare
    deux entiers, donc il ne voit rien, et `/health` continue d'annoncer un
    index prêt — alors que la recherche lexicale ne rend PLUS RIEN, ses rangs
    désignant des chunks que ChromaDB ne contient plus.

    `mesuré` le 3 septembre 2026 contre un vrai ChromaDB 0.6.3 jetable et le
    module de production, 100 chunks échangés à compte constant, 0 identifiant
    commun : `lexical_stale()` reste `False` et `lexical_ready()` reste `True`
    aux trois instants, tandis que les rangs BM25 résolus tombent de 20 à 0,
    puis remontent à 20 après l'appel. Le compte rendu par l'appel est le même
    (100) avant et après — c'est précisément pourquoi il ne peut pas se déduire
    du compte.
    """
    retriever._lexical_search("ISO 27001", 5)
    compte_avant = collection.count()

    collection.documents.clear()
    collection.documents.update(CORPUS_REMPLACE)

    # Le test doit prouver qu'il a atteint SON cas : sans compte constant, la
    # dérive serait visible du filet et ce test parlerait d'autre chose.
    assert collection.count() == compte_avant, (
        "le corpus de remplacement n'a pas la même taille : ce test ne mesure "
        "plus la dérive à compte constant"
    )
    assert not set(CORPUS_REMPLACE) & set(CORPUS_INITIAL), (
        "les deux corpus partagent un identifiant : la dérive est partielle"
    )
    # La prémisse, et non la propriété gardée : le filet ne peut pas voir ce
    # cas-là. Si cette assertion devient fausse un jour, c'est que le filet a
    # été renforcé — et il faudra relire ce test, pas le supprimer.
    assert retriever.lexical_stale() is False, (
        "le filet voit désormais cette dérive : la prémisse de ce test a changé"
    )
    assert retriever.lexical_ready() is True, "/health devrait encore annoncer un index prêt"

    # L'amputation est réelle : les rangs de l'index désignent des chunks
    # disparus, donc la résolution contre ChromaDB ne rend rien.
    assert retriever._lexical_search("ISO 27001", 5) == [], (
        "la recherche lexicale rend encore quelque chose : la dérive n'est pas installée"
    )

    taille = retriever.rebuild_lexical_index()

    assert taille == compte_avant, "l'appel rend la taille du corpus courant"
    retrouves = [chunk.chunk_id for chunk in retriever._lexical_search("ISO 27001", 5)]
    assert retrouves == ["z9"], (
        f"l'appel n'a pas rendu la recherche lexicale au corpus courant : {retrouves}"
    )
