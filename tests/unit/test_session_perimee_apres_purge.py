"""Une session NebulaGraph que le processus garde depuis son démarrage, et que
la purge du pipeline voisin a rendue aveugle au schéma.

LE DÉFAUT, `mesuré` le 25 septembre 2026 à 08:59 UTC sur le conteneur servi et
consigné au §4.80 de `documentation/axes_amelioration.md` : le pipeline purge le
graphe et RECRÉE son schéma ; la session longue du processus ne connaît plus les
tags ; `media_object_names()` rend 0 clé ; la liste blanche du proxy `/media`
vaut 0 ; TOUS les `GET /media/<clé>` rendent 404 ; et `/health` publie
`nebulagraph: true` pendant tout ce temps. Un processus NEUF rend les 212 clés
au même instant : c'est la session qui est périmée, pas le graphe.

LA FORME EXACTE DE L'ERREUR, `mesuré` le 25 septembre 2026 contre le graphd
RÉEL de ce poste (`vesoft/nebula-graphd:v3.6.0`, client `nebula3-python` 3.8.3),
en LECTURE SEULE — la mesure interroge un élément de schéma que le space ne
connaît pas, ce qui est exactement ce qu'une session périmée croit du schéma
recréé, et n'écrit RIEN :

    MATCH (n:<tag inconnu>) …   is_succeeded()=False  error_code()=-1009
                                error_msg()="SemanticError: `<tag>': Unknown tag"
    GO … OVER <arête inconnue>  is_succeeded()=False  error_code()=-1009
                                error_msg()="SemanticError: <arête> not found in space [rag_space]."
    FETCH PROP ON * "<vid>"     is_succeeded()=True   0 ligne — INSENSIBLE au schéma
    LOOKUP ON <tag inconnu>     is_succeeded()=False  error_code()=-1005 (E_EXECUTION_ERROR)
                                error_msg()="Schema not exist: <tag>"
    YIELD 1 AS ok               is_succeeded()=True   1 ligne — INSENSIBLE au schéma

CE QUE CELA DIT DU CODE, et c'est la charnière : **ce n'est PAS une exception**.
`nebula3` rend un `ResultSet` EN ÉCHEC. La reprise que `_execute_raw` porte déjà
est dans un `except` — elle ne voit donc RIEN de ce défaut, et le pool n'est
jamais rouvert. Et `ping()`, la sonde que `/health` publie sous `nebulagraph`,
n'interroge que `YIELD 1 AS ok`, qui est insensible au schéma : elle reste VRAIE
sous la session périmée. Les deux gardes ci-dessous en découlent directement.

CE QUI N'EST PAS REPRODUIT ICI, ET POURQUOI. Reproduire une session RÉELLEMENT
périmée exigerait de purger le graphe partagé, ce que ce lot s'interdit. Le
double ci-dessous rejoue donc la forme d'erreur RELEVÉE sur le graphd réel, pas
une session réellement périmée. Ce que le double ne peut pas prouver : qu'une
session périmée rende EXACTEMENT ces messages-là pour un tag qui, lui, existe
bien dans le schéma recréé. Le journal du conteneur du 25 septembre le dit pour
`MATCH` (`Picture` et `Table` existaient) ; pour `GO`, `FETCH` et `LOOKUP`, rien
n'a été mesuré sous une vraie session périmée, et l'ancien journal est perdu.
"""

import re

import anyio
import pytest

from src.agent import graph_context, minio_client

# ─── Le double : la forme relevée, et rien d'autre ────────────────────────────

# Le message que le graphd RÉEL rend, mot pour mot (mesure en tête de fichier).
_MESSAGE_TAG_INCONNU = "SemanticError: `{nom}': Unknown tag"
_MESSAGE_ARETE_INCONNUE = "SemanticError: {nom} not found in space [rag_space]."
# `nebula3.common.ttypes.ErrorCode.E_SEMANTIC_ERROR`, relevé dans la version
# installée. Écrit en clair : le double ne doit pas dépendre du module testé.
_E_SEMANTIC_ERROR = -1009

_TAG_DU_MATCH = re.compile(r"\(n:(\w+)\)")
_ARETE_DU_GO = re.compile(r"\bOVER\s+(\w+)")
# Les colonnes d'un `RETURN n.<tag>.<propriété> AS <alias>` : le double rend
# les colonnes que la requête NOMME, et non une forme figée — LOT-42 a changé
# l'alias `url` en trois colonnes nommées, et le double ne doit pas en décider.
_COLONNE_DU_RETURN = re.compile(r"n\.\w+\.(\w+) AS (\w+)")


class _Valeur:
    """Le strict nécessaire d'un `ValueWrapper` pour `_to_primitive`."""

    def __init__(self, brut: str | None) -> None:
        self._brut = brut

    def is_string(self) -> bool:
        return self._brut is not None

    def as_string(self) -> str:
        assert self._brut is not None
        return self._brut

    def is_int(self) -> bool:
        return False

    def is_null(self) -> bool:
        # Une propriété absente du schéma du tag : `__NULL__`, mesuré au §4.82.
        return self._brut is None


class _ResultatEnEchec:
    """Un `ResultSet` en échec : ce que le graphd rend sur un schéma inconnu.

    Ce n'est PAS une exception, et c'est tout l'objet de ce fichier.
    """

    def __init__(self, message: str) -> None:
        self._message = message

    def is_succeeded(self) -> bool:
        return False

    def error_code(self) -> int:
        return _E_SEMANTIC_ERROR

    def error_msg(self) -> str:
        return self._message


class _ResultatOk:
    def __init__(self, colonnes: list[str], lignes: list[list[str | None]]) -> None:
        self._colonnes = colonnes
        self._lignes = lignes

    def is_succeeded(self) -> bool:
        return True

    def error_code(self) -> int:
        return 0

    def error_msg(self) -> str:
        return ""

    def row_size(self) -> int:
        return len(self._lignes)

    def keys(self) -> list[str]:
        return list(self._colonnes)

    def row_values(self, i: int) -> list[_Valeur]:
        return [_Valeur(v) for v in self._lignes[i]]


class _SessionPerimee:
    """Double du pool : la session ignore le schéma jusqu'à sa RÉOUVERTURE.

    `guerit` à faux rejoue le cas où rouvrir ne suffirait pas — il sert au
    contrôle positif et à la sonde de `/health`, qui doit dire faux quand
    l'aveuglement PERSISTE.
    """

    def __init__(self, urls_par_tag: dict[str, list[str]], *, guerit: bool = True) -> None:
        self.urls_par_tag = urls_par_tag
        self.guerit = guerit
        self.rouvertures = 0
        self.requetes: list[str] = []

    def rouvrir(self) -> None:
        """Ce que `reset_connection()` fait au vrai pool : la session suivante
        est neuve, donc elle relit le schéma auprès du metad."""
        self.rouvertures += 1

    @property
    def _connait_le_schema(self) -> bool:
        return self.guerit and self.rouvertures > 0

    def execute(self, nql: str) -> object:
        self.requetes.append(nql)
        tag = _TAG_DU_MATCH.search(nql)
        arete = _ARETE_DU_GO.search(nql)
        if not self._connait_le_schema:
            if tag is not None:
                return _ResultatEnEchec(_MESSAGE_TAG_INCONNU.format(nom=tag.group(1)))
            if arete is not None:
                return _ResultatEnEchec(_MESSAGE_ARETE_INCONNUE.format(nom=arete.group(1)))
        if tag is not None and "minio_url" in nql:
            # Le graphe d'AUJOURD'HUI : seul `minio_url` est porté, toute autre
            # propriété nommée rend NULL.
            urls = self.urls_par_tag.get(tag.group(1), [])
            colonnes = _COLONNE_DU_RETURN.findall(nql)
            return _ResultatOk(
                [alias for _prop, alias in colonnes],
                [[u if prop == "minio_url" else None for prop, _alias in colonnes] for u in urls],
            )
        if arete is not None:
            return _ResultatOk(["parent_id", "seq"], [["ffa6bda17d", "7"]])
        return _ResultatOk(["ok"], [["1"]])


_URL_PICTURE = "http://minio:9000/documents/images/ouvrage/086f1173cb_picture.png"
_URL_TABLE = "http://minio:9000/documents/tables/ouvrage/0d1e2f3a4b_table.png"
_CLE_PICTURE = "images/ouvrage/086f1173cb_picture.png"
_CLE_TABLE = "tables/ouvrage/0d1e2f3a4b_table.png"


def _brancher(monkeypatch, pool: _SessionPerimee) -> None:
    """Branche le double à la place du pool, et la réouverture à la place de
    `reset_connection` — c'est le seul geste qui rend une session neuve."""
    monkeypatch.setattr(graph_context, "_get_pool", lambda: pool)
    monkeypatch.setattr(graph_context, "reset_connection", pool.rouvrir)


# ─── Contrôles positifs : le double peut réellement échouer ───────────────────


def test_controle_positif_le_double_rend_la_forme_relevee_sur_les_trois_natures() -> None:
    """Sans ce contrôle, un vert des gardes pourrait venir d'un double inerte.

    Les TROIS natures que le chemin de réponse emprunte sont témoignées : le
    `MATCH` par tag (liste blanche du proxy), le `GO` par arête (remontée au
    parent, section voisine, enfants) et la requête insensible au schéma
    (`YIELD`, celle que la sonde actuelle utilise).
    """
    pool = _SessionPerimee({"Picture": [_URL_PICTURE]}, guerit=False)

    par_tag = pool.execute('MATCH (n:Picture) WHERE n.Picture.minio_url != "" RETURN 1;')
    assert par_tag.is_succeeded() is False
    assert par_tag.error_code() == _E_SEMANTIC_ERROR
    assert par_tag.error_msg() == "SemanticError: `Picture': Unknown tag"

    par_arete = pool.execute('GO FROM "1730443c8f" OVER PARENT_OF REVERSELY YIELD src(edge);')
    assert par_arete.is_succeeded() is False
    assert par_arete.error_code() == _E_SEMANTIC_ERROR
    assert par_arete.error_msg() == "SemanticError: PARENT_OF not found in space [rag_space]."

    insensible = pool.execute("YIELD 1 AS ok;")
    assert insensible.is_succeeded() is True, (
        "une requête sans tag ni arête doit RÉUSSIR sous la session périmée : "
        "c'est précisément pourquoi la sonde actuelle de /health ne voit rien"
    )


def test_controle_positif_sans_reouverture_la_liste_blanche_reste_vide(monkeypatch) -> None:
    """Le témoin du défaut lui-même : si rien ne rouvre, 0 clé, comme le 25/09."""
    pool = _SessionPerimee({"Picture": [_URL_PICTURE], "Table": [_URL_TABLE]}, guerit=False)
    _brancher(monkeypatch, pool)

    assert graph_context.media_object_names() == set()


# ─── Garde 1 — la liste blanche revient après UNE réouverture ─────────────────


def test_garde_1_media_object_names_rend_les_cles_apres_une_reouverture(monkeypatch) -> None:
    """Le cas du 25 septembre, à l'échelle d'un appel.

    UNE réouverture, pas une par tag : `_VISUAL_TAGS` en compte deux, et la
    session rouverte connaît le schéma entier — rouvrir deux fois signalerait
    une reprise posée au mauvais étage.
    """
    pool = _SessionPerimee({"Picture": [_URL_PICTURE], "Table": [_URL_TABLE]})
    _brancher(monkeypatch, pool)

    cles = graph_context.media_object_names()

    assert cles == {_CLE_PICTURE, _CLE_TABLE}, (
        f"la liste blanche du proxy /media vaut {sorted(cles)} sous une session "
        "périmée par une purge, alors que le graphe porte ces deux objets : tous "
        "les GET /media/<clé> rendront 404, exactement comme le 25/09 à 08:59 UTC"
    )
    assert pool.rouvertures == 1, (
        f"{pool.rouvertures} réouverture(s) du pool pour deux tags ; la reprise "
        "attendue est UNE réouverture suivie d'un SEUL nouvel essai par requête"
    )


def test_garde_1_bis_un_semantic_error_qui_persiste_ne_boucle_pas(monkeypatch) -> None:
    """La reprise rejoue UNE fois. Deux essais par requête, pas davantage."""
    pool = _SessionPerimee({"Picture": [_URL_PICTURE]}, guerit=False)
    _brancher(monkeypatch, pool)

    assert graph_context.media_object_names() == set()
    assert len(pool.requetes) == 4, (  # 2 tags × (essai + nouvel essai)
        f"{len(pool.requetes)} requêtes émises pour deux tags : la reprise doit "
        "rejouer UNE fois, pas tourner en rond sur un graphe réellement muet"
    )


# ─── Garde 2 — un vide n'est pas mis en cache comme une vérité ────────────────


def test_garde_2_une_liste_blanche_vide_n_est_pas_mise_en_cache(monkeypatch) -> None:
    """La liste blanche vide est un SYMPTÔME, jamais un fait établi.

    Le 25 septembre, `_allowed_objects()` a mémorisé `frozenset()` et l'a rendu
    à chaque appel suivant. Un cache qui retient le vide transforme une panne
    passagère de session en refus durable : le pool a beau être rouvert, le
    proxy continue de rendre 404 sur les 212 objets.
    """
    etat = {"lectures": 0}

    def noms() -> set[str]:
        etat["lectures"] += 1
        return set()

    monkeypatch.setattr("src.agent.graph_context.media_object_names", noms)
    minio_client._allowed_objects.cache_clear()

    assert minio_client._allowed_objects() == frozenset()
    assert minio_client._allowed_objects() == frozenset()

    assert etat["lectures"] == 2, (
        f"le graphe n'a été lu que {etat['lectures']} fois pour deux appels : la "
        "liste blanche VIDE a été mise en cache comme une vérité, et le proxy "
        "/media refusera tout jusqu'au redémarrage du processus"
    )
    minio_client._allowed_objects.cache_clear()


def test_garde_2_bis_une_liste_blanche_pleine_reste_mise_en_cache(monkeypatch) -> None:
    """Le revers, sans quoi on aurait supprimé le cache au lieu de le corriger :
    une liste NON vide se lit une seule fois. Le proxy est sur le chemin de
    chaque image affichée."""
    etat = {"lectures": 0}

    def noms() -> set[str]:
        etat["lectures"] += 1
        return {_CLE_PICTURE}

    monkeypatch.setattr("src.agent.graph_context.media_object_names", noms)
    minio_client._allowed_objects.cache_clear()

    assert minio_client._allowed_objects() == frozenset({_CLE_PICTURE})
    assert minio_client._allowed_objects() == frozenset({_CLE_PICTURE})

    assert etat["lectures"] == 1, (
        f"{etat['lectures']} lectures du graphe pour deux appels : une liste "
        "blanche pleine doit rester mise en cache, le proxy étant sur le chemin "
        "de CHAQUE image affichée"
    )
    minio_client._allowed_objects.cache_clear()


def test_garde_2_ter_is_allowed_autorise_apres_la_reouverture(monkeypatch) -> None:
    """Le défaut bout à bout : le proxy refuse sous la session périmée, puis
    autorise dès que la session connaît de nouveau les tags."""
    pool = _SessionPerimee({"Picture": [_URL_PICTURE]}, guerit=False)
    _brancher(monkeypatch, pool)
    minio_client._allowed_objects.cache_clear()

    assert minio_client.is_allowed(_CLE_PICTURE) is False

    pool.guerit = True
    pool.rouvrir()

    assert minio_client.is_allowed(_CLE_PICTURE) is True, (
        "le proxy /media refuse encore l'objet alors que la session rouverte "
        "connaît de nouveau le tag : le refus a survécu à sa cause"
    )
    minio_client._allowed_objects.cache_clear()


# ─── Garde 3 — /health nomme l'aveuglement ────────────────────────────────────


def test_garde_3_ping_est_faux_quand_la_session_ne_connait_plus_les_tags(
    monkeypatch,
) -> None:
    """La sonde doit LIRE un tag. `YIELD 1 AS ok` est insensible au schéma
    (mesuré en tête de fichier) : elle réussissait, et /health publiait
    `nebulagraph: true` pendant que le proxy rendait 404 sur tout."""
    pool = _SessionPerimee({"Picture": [_URL_PICTURE]}, guerit=False)
    _brancher(monkeypatch, pool)

    assert graph_context.ping() is False, (
        "/health publie nebulagraph VRAI alors que la session ne connaît plus "
        "aucun tag : le seul symptôme visible du défaut du 25/09 était un 404 "
        "sur les images, et la route de santé disait que tout allait bien"
    )


def test_garde_3_bis_ping_reste_vrai_sur_un_graphe_sain_mais_sans_illustration(
    monkeypatch,
) -> None:
    """Le revers, et il est indispensable : une sonde qui lit un tag doit
    distinguer « le tag est inconnu » de « le tag n'a aucun nœud ». Zéro ligne
    sur une requête RÉUSSIE est un graphe sain, pas une panne."""

    class _PoolVideMaisSain:
        """Répond parfaitement à tout. La requête insensible au schéma rend sa
        ligne ; la lecture d'un tag RÉUSSIT mais ne rend AUCUN nœud."""

        def execute(self, nql: str) -> object:
            if _TAG_DU_MATCH.search(nql) is not None:
                return _ResultatOk(["id"], [])
            return _ResultatOk(["ok"], [["1"]])

    monkeypatch.setattr(graph_context, "_get_pool", lambda: _PoolVideMaisSain())

    assert graph_context.ping() is True, (
        "la sonde rend FAUX sur un graphe qui répond parfaitement mais ne porte "
        "aucun nœud du tag sondé : elle ferait passer le conteneur en dégradé "
        "sur un corpus légitimement vide"
    )


def test_garde_3_ter_health_publie_nebulagraph_faux_sous_la_session_perimee(
    monkeypatch,
) -> None:
    """Le corps publié, qui est ce que l'exploitant lit.

    `main.nebula_ping` EST `graph_context.ping` — l'identité est assérée ici,
    sans quoi ce test mesurerait un câblage imaginaire.
    """
    from src.api import main

    assert main.nebula_ping is graph_context.ping, (
        "/health ne publie plus `nebulagraph` depuis graph_context.ping : ce "
        "garde mesurerait autre chose que la route"
    )

    pool = _SessionPerimee({"Picture": [_URL_PICTURE]}, guerit=False)
    _brancher(monkeypatch, pool)
    monkeypatch.setattr(main.settings, "api_key", "")
    monkeypatch.setattr(main.settings, "torch_device", "cpu")
    monkeypatch.setattr(main, "chroma_ping", lambda: True)
    monkeypatch.setattr(main, "lexical_ready", lambda: True)

    corps: dict[str, object] = {}

    async def scenario() -> None:
        reponse = await main.health()
        corps["services"] = dict(reponse.services)
        corps["status"] = reponse.status

    anyio.run(scenario)

    services = corps["services"]
    assert isinstance(services, dict)
    assert services.get("nebulagraph") is False, (
        f"/health publie nebulagraph={services.get('nebulagraph')!r} alors que la "
        "session ne connaît plus les tags et que TOUS les GET /media rendent 404"
    )
    assert corps["status"] == "degraded", (
        f"/health rend « {corps['status']} » alors qu'une dépendance est aveugle"
    )


# ─── Ce que la session périmée fait aux AUTRES requêtes du chemin ─────────────


def test_la_remontee_au_parent_survit_a_une_session_perimee(monkeypatch) -> None:
    """`GO … OVER PARENT_OF` porte la remontée, la section voisine et les
    enfants. Sous une session qui ne connaît plus l'arête, le graphd rend le
    MÊME `E_SEMANTIC_ERROR` (mesure en tête de fichier), et la reconstruction de
    section rendait un contexte vide sans que rien ne le dise."""
    pool = _SessionPerimee({})
    _brancher(monkeypatch, pool)

    parent, rang = graph_context._find_parent("1730443c8f")

    assert (parent, rang) == ("ffa6bda17d", 7), (
        f"la remontée au parent rend {(parent, rang)} sous une session périmée : "
        "la reconstruction de section perd son ancrage, et la réponse part sans "
        "sa source"
    )
    assert pool.rouvertures == 1


def test_fetch_prop_on_etoile_est_insensible_au_schema() -> None:
    """MESURE, pas garde. `FETCH PROP ON * "<vid>"` a RÉUSSI contre le graphd
    réel pour un VID inconnu (0 ligne) : il ne nomme aucun tag ni aucune arête,
    donc une session périmée ne le fait pas échouer. `_get_node_properties` est
    le seul chemin du module qui traverse la purge sans broncher — et c'est
    pourquoi la panne du 25/09 s'est vue sur les images avant tout le reste."""
    pool = _SessionPerimee({}, guerit=False)

    resultat = pool.execute('FETCH PROP ON * "1730443c8f" YIELD vertex AS node;')

    assert resultat.is_succeeded() is True


@pytest.mark.parametrize(
    ("message", "rattrape"),
    [
        ("SemanticError: `Picture': Unknown tag", True),
        ("SemanticError: PARENT_OF not found in space [rag_space].", True),
        ("SemanticError: Type error `1 + \"a\"'", False),
    ],
)
def test_seuls_les_schemas_inconnus_declenchent_la_reouverture(
    monkeypatch, message: str, rattrape: bool
) -> None:
    """La reprise est ÉTROITE, et ce garde le tient.

    Un `SemanticError` qui ne nomme pas un élément de schéma est une faute de
    requête : rouvrir le pool n'y change rien, et retenter doublerait la charge
    sans aucune chance d'aboutir.
    """
    etat = {"essais": 0}

    class _Pool:
        def execute(self, _nql: str) -> object:
            etat["essais"] += 1
            return _ResultatEnEchec(message)

    rouvertures = []
    monkeypatch.setattr(graph_context, "_get_pool", lambda: _Pool())
    monkeypatch.setattr(graph_context, "reset_connection", lambda: rouvertures.append(True))

    assert graph_context._execute_raw("MATCH (n:Picture) RETURN n;") is None
    assert etat["essais"] == (2 if rattrape else 1), (
        f"{etat['essais']} essai(s) sur « {message} » : la reprise doit se "
        "déclencher sur un élément de schéma inconnu, et sur rien d'autre"
    )
    assert bool(rouvertures) is rattrape
