"""Les trois réserves de lecture de `sequence`, gardées par mutation.

`sequence` porte l'ordre de lecture et le pipeline la garantit monotone. Ce que
sa monotonie ne dit pas, et que ce fichier garde, c'est comment on la LIT :

1. elle repart à 0 dans chaque document — deux éléments de deux documents
   portent la même valeur, donc tout « avant / après » se borne au document ;
2. elle n'est pas contiguë sous un parent — l'écart entre deux frères vaut la
   taille du sous-arbre du premier ;
3. l'écart entre deux enfants d'un même parent peut être grand.

La conséquence tient en une phrase : **la fenêtre d'éléments se découpe sur des
POSITIONS de liste, jamais sur des VALEURS de `sequence`.** Un encadrement
`sequence ∈ [s−k, s+k]` — l'optimisation naturelle, celle qui économise un
aller-retour — rend silencieusement moins d'éléments que demandé. Les chiffres
qui mesurent cette perte sont au §4.5 de `documentation/axes_amelioration.md`,
leur site canonique.

POURQUOI CE FICHIER PASSE PAR `reconstruct_section` ET NON PAR `_window_around`

La propriété gardée n'est pas dans `_window_around` : elle est dans la
COMPOSITION « aller chercher tous les enfants sans filtre, puis découper par
position ». Les tests de `test_context_assembly.py` appellent `_window_around`
sur une liste qu'ils fabriquent eux-mêmes ; ils sont donc verts des deux côtés
du défaut, parce qu'une réécriture qui pousse la fenêtre dans la requête nGQL
laisse `_window_around` intact et le sort simplement du chemin. `mesuré` le
3 septembre 2026 : sous cette réécriture, les 486 tests de la suite restent
verts. Un garde posé sur ce maillon-là serait décoratif.

Le bouchon est donc posé au plus bas, à la frontière nGQL (`_execute`), et le
graphe factice HONORE les clauses `WHERE properties(edge).sequence …` — sans
quoi un code qui filtre dans la requête recevrait quand même toutes les lignes,
et les gardes seraient verts pour rien. `TestLeGrapheFacticeVoitLesFiltres` est
là pour prouver que ce bouchon voit encore passer une mutation.
"""

import re

import pytest

from src.agent import graph_context
from src.agent.graph_context import _window_around, reconstruct_section

# Fenêtre utilisée par tous les gardes de ce fichier. Fixée ici, et non lue dans
# la configuration : un garde dont le cas dépend de l'environnement ne prouve
# pas qu'il a atteint son cas.
_AVANT = 6
_APRES = 6
_VOISINS = 3
# Format des VIDs d'éléments, tel que `reconstruct_section` l'exige.
_VID_LEN = 10
_VID_HEX = re.compile(r"^[a-f0-9]{10}$")
# Taille des sections de test, et rang de l'ancre dans la plus grande. Ces
# valeurs sont nommées plutôt qu'écrites en clair : la règle PLR2004 les
# refuserait littérales, et une règle muselée n'est pas une correction.
_NB_ENFANTS = 15
_RANG_ANCRE = 7
_NB_ENFANTS_COURTE = 3
# Écart entre deux frères du graphe factice. Il vaut plus que la demi-fenêtre,
# donc un encadrement `sequence ∈ [s−6, s+6]` n'attrape que l'ancre elle-même.
_ECART = 10


class GrapheFactice:
    """Répond aux requêtes nGQL de `graph_context` comme le ferait NebulaGraph.

    Il n'imite pas tout NebulaGraph : il imite ce dont les trois réserves
    dépendent — le parcours `PARENT_OF`, la propriété `sequence` de l'arête, et
    **les clauses qui filtrent sur elle**. Les comparaisons, l'ordre et le
    `LIMIT` sont appliqués pour de vrai, à partir du texte de la requête.

    C'est délibéré et c'est le cœur du montage : un bouchon qui rendrait tous
    les enfants quelle que soit la requête laisserait passer exactement la
    réécriture que ce fichier garde.
    """

    def __init__(self) -> None:
        # node_id -> propriétés telles que `_get_node_properties` les rend
        self.noeuds: dict[str, dict[str, object]] = {}
        # parent_id -> [(sequence, child_id)], trié par sequence
        self.enfants: dict[str, list[tuple[int, str]]] = {}
        # child_id -> (parent_id, sequence)
        self.parent: dict[str, tuple[str, int]] = {}
        # Texte de chaque requête reçue, dans l'ordre — matière des gardes
        # structurels.
        self.requetes: list[str] = []

    # ── construction ────────────────────────────────────────────────────────

    def document(self, vid: str, filename: str, collection: str = "Essais") -> str:
        self.noeuds[vid] = {
            "tag": "Document",
            "label": "document",
            "text": filename,
            "collection": collection,
            "minio_url": None,
            "page_no": 0,
        }
        return vid

    def noeud(self, vid: str, tag: str, label: str, text: str, parent: str, sequence: int) -> str:
        self.noeuds[vid] = {
            "tag": tag,
            "label": label,
            "text": text,
            "minio_url": None,
            "page_no": 0,
        }
        self.enfants.setdefault(parent, []).append((sequence, vid))
        self.enfants[parent].sort()
        self.parent[vid] = (parent, sequence)
        return vid

    # ── moteur de requêtes ──────────────────────────────────────────────────

    _VID = re.compile(r'GO FROM "((?:[^"\\]|\\.)*)"')
    _FILTRE = re.compile(r"properties\(edge\)\.sequence\s*(>=|<=|!=|==|>|<)\s*(-?\d+)")
    _ORDRE = re.compile(r"ORDER BY \$-\.seq (ASC|DESC)")
    _LIMITE = re.compile(r"LIMIT (\d+)")

    _COMPARE = {
        ">=": lambda a, b: a >= b,
        "<=": lambda a, b: a <= b,
        ">": lambda a, b: a > b,
        "<": lambda a, b: a < b,
        "==": lambda a, b: a == b,
        "!=": lambda a, b: a != b,
    }

    def _vid_de(self, nql: str) -> str | None:
        trouve = self._VID.search(nql)
        if trouve is None:
            return None
        return trouve.group(1).replace(r"\"", '"').replace(r"\\", "\\")

    def _applique_les_filtres(
        self, nql: str, lignes: list[tuple[int, str]]
    ) -> list[tuple[int, str]]:
        """Applique au résultat les comparaisons portées par la requête."""
        for operateur, valeur in self._FILTRE.findall(nql):
            compare = self._COMPARE[operateur]
            lignes = [(s, c) for s, c in lignes if compare(s, int(valeur))]
        return lignes

    def _applique_ordre_et_limite(
        self, nql: str, lignes: list[tuple[int, str]]
    ) -> list[tuple[int, str]]:
        ordre = self._ORDRE.search(nql)
        if ordre is not None:
            lignes = sorted(lignes, reverse=ordre.group(1) == "DESC")
        limite = self._LIMITE.search(nql)
        if limite is not None:
            lignes = lignes[: int(limite.group(1))]
        return lignes

    def _portee(self, nql: str) -> list[tuple[int, str]]:
        """Les arêtes que la requête balaie, AVANT filtrage.

        Une requête ancrée (`GO FROM "<vid>"`) ne voit que les enfants de ce
        VID. Une requête NON ancrée — un `LOOKUP` sur l'arête, par exemple —
        balaie **tout le graphe**, donc les 23 documents. C'est ce que rendrait
        NebulaGraph, et c'est précisément ce que la réserve 1 interdit de faire
        avec `sequence` : ses valeurs repartent à 0 dans chaque document, donc
        une comparaison non ancrée rapproche des éléments de deux ouvrages.

        Un bouchon qui rendrait une liste vide pour une requête non ancrée
        laisserait passer ce défaut-là en le faisant ressembler à « aucun
        voisin trouvé ».
        """
        vid = self._vid_de(nql)
        if vid is not None:
            return list(self.enfants.get(vid, []))
        return [paire for enfants in self.enfants.values() for paire in enfants]

    def execute(self, nql: str) -> list[dict[str, object]]:
        """Le remplaçant de `graph_context._execute`."""
        self.requetes.append(nql)
        vid = self._vid_de(nql)

        if "REVERSELY" in nql:
            if vid is None or vid not in self.parent:
                return []
            parent, sequence = self.parent[vid]
            return [{"parent_id": parent, "seq": sequence}]

        if "AS sibling_id" in nql:
            lignes = self._applique_ordre_et_limite(
                nql, self._applique_les_filtres(nql, self._portee(nql))
            )
            return [{"sibling_id": c, "seq": s} for s, c in lignes]

        if "AS child_id" in nql:
            lignes = self._applique_ordre_et_limite(
                nql, self._applique_les_filtres(nql, self._portee(nql))
            )
            return [
                {
                    "child_id": c,
                    "label": self.noeuds[c]["label"],
                    "text": self.noeuds[c]["text"],
                    "minio_url": self.noeuds[c]["minio_url"],
                    "page_no": self.noeuds[c]["page_no"],
                    "seq": s,
                }
                for s, c in lignes
            ]

        return []

    def proprietes(self, node_id: str) -> dict[str, object]:
        """Le remplaçant de `graph_context._get_node_properties`.

        Bouchonné à part : le tag et le libellé d'un nœud ne décident pas de
        l'appartenance à la fenêtre, qui est la seule propriété gardée ici.
        """
        return dict(self.noeuds.get(node_id, {}))


def _branche(monkeypatch: pytest.MonkeyPatch, graphe: GrapheFactice) -> None:
    monkeypatch.setattr(graph_context, "_execute", graphe.execute)
    monkeypatch.setattr(graph_context, "_get_node_properties", graphe.proprietes)
    monkeypatch.setattr(graph_context.settings, "context_window_before", _AVANT)
    monkeypatch.setattr(graph_context.settings, "context_window_after", _APRES)
    monkeypatch.setattr(graph_context.settings, "adjacent_section_elements", _VOISINS)


def _section_espacee(
    graphe: GrapheFactice, doc: str, section: str, nb: int, depart: int = 0, prefixe: str = "e"
) -> list[str]:
    """Une section dont les enfants sont espacés de `_ECART`, comme le vrai graphe.

    L'espacement reproduit le mécanisme mesuré : la `sequence` d'un frère avance
    de la taille du sous-arbre du précédent, jamais de 1.

    Les VIDs produits respectent le format que `reconstruct_section` exige —
    dix hexadécimaux. C'est le validateur réel qui les contrôle, et il a refusé
    la première version de ce montage : le préfixe doit donc rester hexadécimal.
    """
    ids = []
    for i in range(nb):
        vid = f"{prefixe}{i:0{_VID_LEN - len(prefixe)}x}"
        assert _VID_HEX.fullmatch(vid), f"VID de test invalide : {vid}"
        graphe.noeud(
            vid, "Paragraph", "paragraph", f"Texte {i}.", section, depart + i * _ECART
        )
        ids.append(vid)
    return ids


@pytest.fixture
def graphe_non_contigu() -> tuple[GrapheFactice, list[str], str]:
    """Un document, une section, 15 enfants aux `sequence` espacées de 10.

    Reproduit le pire cas mesuré sur le graphe en service : un encadrement
    `sequence ∈ [s−6, s+6]` n'y attrape que l'ancre, là où le découpage
    positionnel rend 13 éléments.
    """
    g = GrapheFactice()
    doc = g.document("doc_essai/Ouvrage/Chapitre", "Chapitre.pdf")
    section = g.noeud("aaaaaaaa01", "SectionHeader", "section_header", "Titre", doc, 0)
    elements = _section_espacee(g, doc, section, nb=_NB_ENFANTS, depart=1)
    return g, elements, section


# ─── Le montage voit-il encore passer une mutation ? ──────────────────────────


class TestLeGrapheFacticeVoitLesFiltres:
    """Sans ces deux tests, tous les gardes de ce fichier pourraient être verts
    parce que le bouchon ignore les filtres, et non parce que le code est juste.
    """

    def test_un_encadrement_de_sequence_retire_bien_des_lignes(self) -> None:
        g = GrapheFactice()
        doc = g.document("doc_x", "x.pdf")
        _section_espacee(g, doc, doc, nb=_NB_ENFANTS, depart=0)

        sans_filtre = g.execute('GO FROM "doc_x" OVER PARENT_OF YIELD dst(edge) AS child_id;')
        encadre = g.execute(
            'GO FROM "doc_x" OVER PARENT_OF '
            "WHERE properties(edge).sequence >= 64 "
            "AND properties(edge).sequence <= 76 "
            "YIELD dst(edge) AS child_id;"
        )

        assert len(sans_filtre) == _NB_ENFANTS
        # 70 est le seul multiple de 10 dans [64, 76] : le filtre MORD.
        assert len(encadre) == 1
        assert encadre[0]["seq"] == _RANG_ANCRE * _ECART

    def test_l_ordre_et_la_limite_sont_appliques(self) -> None:
        g = GrapheFactice()
        doc = g.document("doc_x", "x.pdf")
        _section_espacee(g, doc, doc, nb=_NB_ENFANTS, depart=0)

        rows = g.execute(
            'GO FROM "doc_x" OVER PARENT_OF '
            "WHERE properties(edge).sequence < 100 "
            "YIELD dst(edge) AS sibling_id, properties(edge).sequence AS seq "
            "| ORDER BY $-.seq DESC | LIMIT 2;"
        )

        assert [r["seq"] for r in rows] == [90, 80]


# ─── Réserve 2 et 3 : la fenêtre se découpe sur des POSITIONS ────────────────


class TestLaFenetreEstPositionnelle:
    def test_une_section_non_contigue_rend_la_fenetre_complete(
        self, monkeypatch: pytest.MonkeyPatch, graphe_non_contigu: tuple
    ) -> None:
        """LE garde du lot. Rouge dès que la fenêtre passe dans la requête."""
        g, elements, section = graphe_non_contigu
        _branche(monkeypatch, g)
        ancre = elements[_RANG_ANCRE]

        contexte = reconstruct_section(ancre)

        # — le cas est-il bien atteint ? (un test qui choisit son cas le prouve)
        sequences = [s for s, _ in g.enfants[section]]
        ecarts = {b - a for a, b in zip(sequences, sequences[1:], strict=False)}
        assert ecarts == {_ECART}, "la section de test doit être NON contiguë"
        assert len(sequences) == _NB_ENFANTS, "il faut plus d'enfants que la fenêtre"
        assert _RANG_ANCRE - _AVANT >= 0, "la fenêtre avant doit mordre"
        assert _RANG_ANCRE + _APRES < _NB_ENFANTS, "la fenêtre après doit mordre"

        # — la propriété gardée
        attendus = elements[_RANG_ANCRE - _AVANT : _RANG_ANCRE + _APRES + 1]
        assert len(contexte.elements) == _AVANT + _APRES + 1
        assert [e.node_id for e in contexte.elements] == attendus
        assert contexte.truncated is True

    def test_les_voisins_positionnels_et_non_ceux_de_l_encadrement(
        self, monkeypatch: pytest.MonkeyPatch, graphe_non_contigu: tuple
    ) -> None:
        """L'ancre seule survivrait à un encadrement : nommer les 13 attendus."""
        g, elements, _ = graphe_non_contigu
        _branche(monkeypatch, g)
        ancre = elements[_RANG_ANCRE]

        rendus = [e.node_id for e in reconstruct_section(ancre).elements]

        assert ancre in rendus
        # Les 12 voisins positionnels sont TOUS hors de [seq−6, seq+6].
        ancre_seq = g.parent[ancre][1]
        for voisin in elements[_RANG_ANCRE - _AVANT : _RANG_ANCRE + _APRES + 1]:
            if voisin == ancre:
                continue
            assert abs(g.parent[voisin][1] - ancre_seq) > _APRES
            assert voisin in rendus, f"{voisin} manque : la fenêtre a été encadrée"

    def test_une_section_qui_tient_n_est_pas_annoncee_tronquee(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Le pendant : `truncated` ne doit pas devenir vrai par les écarts."""
        g = GrapheFactice()
        doc = g.document("doc_essai/O/C", "C.pdf")
        section = g.noeud("aaaaaaaa01", "SectionHeader", "section_header", "T", doc, 0)
        elements = _section_espacee(g, doc, section, nb=_NB_ENFANTS_COURTE, depart=1)
        _branche(monkeypatch, g)

        contexte = reconstruct_section(elements[1])

        assert len(contexte.elements) == _NB_ENFANTS_COURTE
        assert contexte.truncated is False

    def test_la_queue_et_la_tete_des_sections_voisines_sont_positionnelles(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`_neighbour_elements` découpe aussi par position : même réserve."""
        g = GrapheFactice()
        doc = g.document("doc_essai/O/C", "C.pdf")
        precedente = g.noeud("bbbbbbbb01", "SectionHeader", "section_header", "Avant", doc, 0)
        courante = g.noeud("aaaaaaaa01", "SectionHeader", "section_header", "Ici", doc, 500)
        suivante = g.noeud("cccccccc01", "SectionHeader", "section_header", "Après", doc, 900)
        avant = _section_espacee(g, doc, precedente, nb=8, depart=1, prefixe="ba")
        ici = _section_espacee(g, doc, courante, nb=3, depart=501, prefixe="bb")
        apres = _section_espacee(g, doc, suivante, nb=8, depart=901, prefixe="bc")
        _branche(monkeypatch, g)

        contexte = reconstruct_section(ici[1])

        assert [e.node_id for e in contexte.before] == avant[-_VOISINS:]
        assert [e.node_id for e in contexte.after] == apres[:_VOISINS]
        assert contexte.before_title == "Avant"
        assert contexte.after_title == "Après"


# ─── Réserve 1 : `sequence` repart à 0 dans chaque document ──────────────────


class TestLaLectureEstBorneeAuDocument:
    def test_la_fenetre_ne_franchit_pas_la_frontiere_du_document(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Deux documents portent les MÊMES valeurs de `sequence`.

        C'est la réserve 1 : elle repart à 0 partout. Une lecture qui
        rapprocherait deux éléments par leur seule `sequence` mélangerait les
        deux ouvrages.
        """
        g = GrapheFactice()
        doc_a = g.document("doc_essai/A/Chapitre", "A.pdf", collection="A")
        doc_b = g.document("doc_essai/B/Chapitre", "B.pdf", collection="B")
        sect_a = g.noeud("aaaaaaaa01", "SectionHeader", "section_header", "Titre A", doc_a, 0)
        sect_b = g.noeud("bbbbbbbb01", "SectionHeader", "section_header", "Titre B", doc_b, 0)
        elements_a = _section_espacee(g, doc_a, sect_a, nb=_NB_ENFANTS, depart=1, prefixe="ca")
        elements_b = _section_espacee(g, doc_b, sect_b, nb=_NB_ENFANTS, depart=1, prefixe="cb")
        _branche(monkeypatch, g)

        # — le cas est-il atteint ? les deux documents partagent leurs valeurs
        valeurs_a = {s for s, _ in g.enfants[sect_a]}
        valeurs_b = {s for s, _ in g.enfants[sect_b]}
        assert valeurs_a == valeurs_b, "les deux documents doivent se recouvrir"

        contexte = reconstruct_section(elements_a[_RANG_ANCRE])

        rendus = {e.node_id for e in contexte.elements}
        assert rendus <= set(elements_a)
        assert rendus.isdisjoint(set(elements_b))
        assert contexte.filename == "A.pdf"
        assert contexte.collection == "A"

    def test_les_sections_voisines_ne_franchissent_pas_la_frontiere(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Un document à section unique n'emprunte pas de voisine au suivant.

        C'est le cas que 214 en-têtes du graphe en service présentent dans une
        direction donnée (§4.6) : aucun frère en-tête, donc `None`. La
        « correction » tentante est d'élargir la recherche quand le parent ne
        rend rien — et elle franchit la frontière du document, parce que les
        `sequence` des 23 documents se recouvrent. Le document B porte donc
        ici un en-tête qu'une recherche non ancrée ATTEINDRAIT.
        """
        g = GrapheFactice()
        doc_a = g.document("doc_essai/A/Chapitre", "A.pdf")
        doc_b = g.document("doc_essai/B/Chapitre", "B.pdf")
        sect_a = g.noeud("aaaaaaaa01", "SectionHeader", "section_header", "Seule A", doc_a, 0)
        sect_b = g.noeud("bbbbbbbb01", "SectionHeader", "section_header", "Seule B", doc_b, 2)
        elements_a = _section_espacee(g, doc_a, sect_a, nb=3, depart=1, prefixe="ca")
        _section_espacee(g, doc_b, sect_b, nb=3, depart=3, prefixe="cb")
        _branche(monkeypatch, g)

        # — le cas est-il atteint ? l'en-tête de B est joignable sans ancre, et
        #   il est le premier en-tête que rencontrerait un balayage global.
        globales = g.execute(
            "LOOKUP ON PARENT_OF WHERE properties(edge).sequence > 0 "
            "YIELD dst(edge) AS sibling_id, properties(edge).sequence AS seq "
            f"| ORDER BY $-.seq ASC | LIMIT {graph_context._SIBLING_CANDIDATES};"
        )
        joignables = [r["sibling_id"] for r in globales]
        assert sect_b in joignables, "le montage ne peut pas franchir la frontière"
        assert sect_a not in joignables

        contexte = reconstruct_section(elements_a[1])

        assert contexte.before == []
        assert contexte.after == []
        assert contexte.before_title == ""
        assert contexte.after_title == ""

    def test_aucune_requete_ne_filtre_sequence_sans_ancre(
        self, monkeypatch: pytest.MonkeyPatch, graphe_non_contigu: tuple
    ) -> None:
        """Le garde structurel de la réserve 1.

        Une comparaison sur `sequence` n'a de sens que sous un parent donné :
        les valeurs se répètent d'un document à l'autre. Toute requête qui
        compare `sequence` doit donc partir d'un VID.
        """
        g, elements, _ = graphe_non_contigu
        _branche(monkeypatch, g)

        reconstruct_section(elements[_RANG_ANCRE])

        comparaisons = [q for q in g.requetes if GrapheFactice._FILTRE.search(q)]
        assert comparaisons, "aucune requête ne compare sequence : garde vide"
        for requete in comparaisons:
            assert GrapheFactice._VID.search(requete) is not None, (
                f"requête non ancrée sur un VID : {requete}"
            )


# ─── Réserve 3, au maillon unitaire : le découpage ignore les valeurs ─────────


def test_le_decoupage_ignore_les_valeurs_de_sequence() -> None:
    """`_window_around` ne doit lire QUE des positions.

    Les quatre autres tests de la fenêtre (`test_context_assembly.py`) passent
    des lignes SANS clé `seq` : ils ne peuvent donc pas voir un découpage qui se
    mettrait à la lire. Celui-ci en porte, et non contiguës.
    """
    rows = [{"child_id": f"e{i}", "seq": i * 1000} for i in range(9)]

    fenetre, tronquee = _window_around(rows, "e4", before=2, after=2)

    assert [r["child_id"] for r in fenetre] == ["e2", "e3", "e4", "e5", "e6"]
    assert tronquee is True
