"""La définition de « section voisine » — (C), la remontée aux oncles — gardée par mutation.

CE QUE CE FICHIER GARDE, ET POURQUOI IL A FALLU L'ÉCRIRE

`_find_sibling` définissait « section voisine » comme « le frère en-tête sous le
parent commun » — définition (A). Elle coïncidait avec « la section suivante du
document » tant que l'ingestion ne produisait pas de titres imbriqués, et elle a
cessé de coïncider le 2 septembre 2026 sans que personne la rediscute. Quand
elle rend `None`, `_neighbour_elements` rend `[], ""` : **tout le bloc
d'encadrement disparaît de ce côté, titre compris**. Ce n'est pas un contexte
moins bon, c'est une absence — et elle touchait 4 157 des 14 424 éléments servis
avant (28,8 %) et 4 678 après (32,4 %), `mesuré` le 9 septembre 2026 sur le
graphe en service. Les chiffres et leur commande sont au §4.6 de
`documentation/axes_amelioration.md`, leur site canonique, et l'instrument qui
les rejoue est `scripts/mesurer_le_graphe.py`.

LE CONSTAT QUI REND CE FICHIER NÉCESSAIRE, ET IL EST `mesuré`

Le passage de (A) à (C) change le chemin de lecture de CHAQUE recherche, et
**les 697 tests de la suite restent verts des deux côtés** (`mesuré` le
9 septembre 2026 : `pytest tests/unit/` rend `rc=0`, 697 passés, avant comme
après le changement). Aucune fixture du dépôt ne construisait un en-tête dont le
parent a des frères en-tête : le cas des 189 remontées n'existait nulle part. Un
lot qui aurait reverti (C) l'aurait donc fait en `rc=0`. C'est le trou que ce
fichier ferme, et c'est la même forme de trou que celle du §4.6 — un garde vert
sous une scène que le défaut ne rencontre jamais.

LE MONTAGE EST EMPRUNTÉ, ET C'EST DÉLIBÉRÉ

`GrapheFactice` vient de `test_lecture_sequence.py` : il est posé à la frontière
nGQL (`_execute`) et il **honore** les clauses `WHERE properties(edge).sequence`,
l'`ORDER BY` et le `LIMIT`. Un bouchon qui rendrait tous les enfants quelle que
soit la requête laisserait passer une remontée qui filtre mal. Le réemployer
plutôt que d'en écrire un second garde aussi les deux fichiers du même côté du
même moteur.

CE QUE CE FICHIER NE GARDE PAS. Les trois réserves de lecture de `sequence` —
dont le découpage POSITIONNEL de `_neighbour_elements`, la réserve 3 — restent
gardées par `test_lecture_sequence.py`, et ce lot n'y touche pas. Le seul point
de contact est vérifié ici : la remontée ne doit pas rendre un découpage moins
positionnel qu'il ne l'était.
"""

import pytest

from src.agent import graph_context
from src.agent.graph_context import (
    _find_sibling,
    _last_header_descendant,
    _neighbour_section,
    reconstruct_section,
)
from tests.unit.test_lecture_sequence import GrapheFactice, _branche

# Rangs du graphe des oncles. Nommés plutôt qu'écrits en clair : PLR2004
# refuserait les littéraux, et une règle muselée n'est pas une correction.
_SEQ_ONCLE_AVANT = 0
_SEQ_PARENT = 100
_SEQ_CIBLE = 110
_SEQ_ONCLE_APRES = 300
# Nombre d'éléments servis par côté — `adjacent_section_elements`, tel que
# `_branche` le règle.
_VOISINS = 3


def _element(g: GrapheFactice, vid: str, parent: str, seq: int, texte: str) -> str:
    return g.noeud(vid, "Text", "text", texte, parent, seq)


def _entete(g: GrapheFactice, vid: str, parent: str, seq: int, texte: str) -> str:
    return g.noeud(vid, "SectionHeader", "section_header", texte, parent, seq)


@pytest.fixture
def graphe_des_oncles() -> tuple[GrapheFactice, dict[str, str]]:
    """Un graphe où (A) rend `None` DES DEUX CÔTÉS et où (C) trouve des deux côtés.

    C'est la forme des 189 remontées « avant » et 190 « après » du graphe en
    service : la section de l'ancre est le SEUL en-tête sous son parent, mais
    elle a des frères non-titres des deux côtés — donc (A) échoue sans que la
    section soit première ni dernière sous son parent.

        Document « Livre.pdf »                           doc
        ├── Chapitre 1                     (seq   0)     oncle_avant
        │   ├── a1  élément                (seq   1)
        │   └── Section 1.9                (seq  10)     queue_avant
        │       ├── x1 x2 x3  éléments     (seq 11-13)
        ├── Chapitre 2                     (seq 100)     parent
        │   ├── p1  élément                (seq 101)     ← le VRAI prédécesseur
        │   ├── Section 2.1                (seq 110)     cible ← section de l'ancre
        │   │   ├── c1 c2 c3  éléments     (seq 111-113) ← c2 est l'ancre
        │   └── p2  élément                (seq 200)
        └── Chapitre 3                     (seq 300)     oncle_apres
            ├── b1  élément                (seq 301)
            └── Section 3.1                (seq 310)     tete_apres
                └── y1 y2 y3  éléments     (seq 311-313)

    La forme est choisie pour que les DEUX réponses possibles du sous-choix
    diffèrent dans les deux directions : `queue_avant != oncle_avant` et
    `tete_apres != oncle_apres`. Sans cela le sous-choix serait invisible.
    """
    g = GrapheFactice()
    v: dict[str, str] = {}
    v["doc"] = g.document("doc_essai/Livre/Chapitres", "Livre.pdf", collection="Ouvrage")

    v["oncle_avant"] = _entete(g, "aa00000001", v["doc"], _SEQ_ONCLE_AVANT, "Chapitre 1")
    _element(g, "aa00000002", v["oncle_avant"], 1, "a1")
    v["queue_avant"] = _entete(g, "aa00000010", v["oncle_avant"], 10, "Section 1.9")
    for i in range(3):
        _element(g, f"aa0000001{i + 1}", v["queue_avant"], 11 + i, f"x{i + 1}")

    v["parent"] = _entete(g, "bb00000001", v["doc"], _SEQ_PARENT, "Chapitre 2")
    v["intro_parent"] = _element(g, "bb00000002", v["parent"], 101, "p1")
    v["cible"] = _entete(g, "bb00000010", v["parent"], _SEQ_CIBLE, "Section 2.1")
    v["ancre"] = ""
    for i in range(3):
        vid = _element(g, f"bb0000001{i + 1}", v["cible"], 111 + i, f"c{i + 1}")
        if i == 1:
            v["ancre"] = vid
    v["queue_parent"] = _element(g, "bb00000020", v["parent"], 200, "p2")

    v["oncle_apres"] = _entete(g, "cc00000001", v["doc"], _SEQ_ONCLE_APRES, "Chapitre 3")
    _element(g, "cc00000002", v["oncle_apres"], 301, "b1")
    v["tete_apres"] = _entete(g, "cc00000010", v["oncle_apres"], 310, "Section 3.1")
    for i in range(3):
        _element(g, f"cc0000001{i + 1}", v["tete_apres"], 311 + i, f"y{i + 1}")

    return g, v


# ─── (1) La remontée trouve ce que (A) manquait, DANS LES DEUX DIRECTIONS ─────


class TestLaRemonteeAuxOnclesTrouve:
    """(C) sert un encadrement là où (A) rendait un bloc vide.

    C'est la fermeture elle-même. Un revert de `_neighbour_section` vers
    `_find_sibling` rougit ici, et nulle part ailleurs dans la suite.
    """

    @pytest.mark.parametrize("direction", ["before", "after"])
    def test_la_definition_a_rend_none_la_ou_c_trouve(
        self, graphe_des_oncles: tuple, monkeypatch: pytest.MonkeyPatch, direction: str
    ) -> None:
        """PREUVE D'ATTEINTE, et elle est la précondition de tout ce fichier.

        Sans elle, les gardes ci-dessous seraient verts sur un graphe où (A)
        suffit — ils n'éprouveraient alors que leur propre mise en scène.
        """
        g, v = graphe_des_oncles
        _branche(monkeypatch, g)

        # — (A), sous le parent réel de la cible : aucun frère EN-TÊTE.
        assert _find_sibling(v["parent"], _SEQ_CIBLE, direction) is None, (
            "(A) trouve un frère en-tête : le graphe ne construit pas le cas des "
            "189 remontées, et tout ce fichier est décoratif"
        )
        # — et la cible n'est NI première NI dernière sous son parent : elle a
        #   des frères des deux côtés, simplement aucun n'est un en-tête. C'est
        #   la forme des 189, distincte des 25 en-têtes premiers sous leur parent.
        rangs = [s for s, _ in g.enfants[v["parent"]]]
        assert min(rangs) < _SEQ_CIBLE < max(rangs)
        # — (C), elle, trouve.
        assert _neighbour_section(v["parent"], _SEQ_CIBLE, direction) is not None

    def test_avant_la_remontee_sert_la_queue_de_l_oncle(
        self, graphe_des_oncles: tuple, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        g, v = graphe_des_oncles
        _branche(monkeypatch, g)

        contexte = reconstruct_section(v["ancre"])

        assert contexte.before_title == "Section 1.9", (
            "la remontée « avant » ne sert pas la queue de l'oncle"
        )
        assert [e.text for e in contexte.before] == ["x1", "x2", "x3"]

    def test_apres_la_remontee_sert_l_oncle_lui_meme(
        self, graphe_des_oncles: tuple, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        g, v = graphe_des_oncles
        _branche(monkeypatch, g)

        contexte = reconstruct_section(v["ancre"])

        assert contexte.after_title == "Chapitre 3", (
            "la remontée « après » ne sert pas l'oncle lui-même"
        )
        assert [e.text for e in contexte.after] == ["b1", "Section 3.1"]

    def test_le_bloc_d_encadrement_porte_bien_les_deux_titres(
        self, graphe_des_oncles: tuple, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Le titre est ce que (A) faisait disparaître, et c'est le markdown qui compte.

        Les champs `before` / `after` peuvent être justes pendant que le
        markdown servi au LLM, lui, ne porte rien : c'est ce dernier qui part
        dans le prompt.
        """
        g, v = graphe_des_oncles
        _branche(monkeypatch, g)

        contexte = reconstruct_section(v["ancre"])

        assert "Section 1.9" in contexte.markdown
        assert "Chapitre 3" in contexte.markdown
        assert "x3" in contexte.markdown
        assert "b1" in contexte.markdown


# ─── (2) Le SOUS-CHOIX, et il est asymétrique ────────────────────────────────


class TestLeSousChoixEstAsymetrique:
    """« avant » descend au dernier descendant en-tête, « après » ne descend pas.

    L'asymétrie était `calculé` au §4.6 et non `mesuré`. Elle a été ÉPROUVÉE
    contre l'ordre de lecture du graphe en service le 9 septembre 2026, et le
    verdict est partagé — il est écrit au docstring de
    `_last_header_descendant` :

    - « après » → l'oncle porte le premier élément réellement lu ensuite dans
      **188 des 190** remontées : CONFIRMÉ ;
    - « avant » → le dernier descendant de l'oncle est le bon choix PARMI les
      descendants de l'oncle (186 / 189), mais il n'est pas « le texte qui
      précède réellement » : dans 186 des 189 cas c'est l'introduction du
      PARENT de la section. Le motif écrit au §4.6 est donc faux ; la règle,
      elle, est la meilleure disponible sous (C).

    Ces gardes tiennent la RÈGLE tranchée par l'utilisateur, pas le motif.
    """

    def test_les_deux_reponses_du_sous_choix_different_bien(
        self, graphe_des_oncles: tuple, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """PREUVE D'ATTEINTE du sous-choix, dans les deux directions."""
        g, v = graphe_des_oncles
        _branche(monkeypatch, g)

        assert _last_header_descendant(v["oncle_avant"]) == v["queue_avant"]
        assert v["queue_avant"] != v["oncle_avant"], (
            "l'oncle n'a pas de descendant en-tête : le sous-choix « avant » "
            "rendrait la même chose des deux façons"
        )
        assert _last_header_descendant(v["oncle_apres"]) == v["tete_apres"]
        assert v["tete_apres"] != v["oncle_apres"], (
            "l'oncle d'après n'a pas de descendant en-tête : le sous-choix "
            "« après » rendrait la même chose des deux façons"
        )

    def test_avant_descend_et_apres_ne_descend_pas(
        self, graphe_des_oncles: tuple, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        g, v = graphe_des_oncles
        _branche(monkeypatch, g)

        assert _neighbour_section(v["parent"], _SEQ_CIBLE, "before") == v["queue_avant"], (
            "« avant » sert l'oncle au lieu de son dernier descendant en-tête"
        )
        assert _neighbour_section(v["parent"], _SEQ_CIBLE, "after") == v["oncle_apres"], (
            "« après » descend dans l'oncle au lieu de servir l'oncle lui-même"
        )

    def test_la_descente_prend_le_dernier_enfant_en_tete_et_non_le_premier(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Un oncle à deux sous-sections : la queue est la SECONDE.

        Le graphe des oncles n'en porte qu'une par oncle, donc « dernier » et
        « premier » y coïncident et la mutation `headers[-1]` → `headers[0]`
        y passerait en vert.
        """
        g = GrapheFactice()
        doc = g.document("doc_essai/Deux/Sections", "Deux.pdf")
        oncle = _entete(g, "aa00000001", doc, 0, "Chapitre 1")
        premiere = _entete(g, "aa00000002", oncle, 1, "Section 1.1")
        _element(g, "aa00000003", premiere, 2, "u1")
        derniere = _entete(g, "aa00000004", oncle, 10, "Section 1.2")
        _element(g, "aa00000005", derniere, 11, "u2")
        _branche(monkeypatch, g)

        # — le cas est-il atteint ? l'oncle porte DEUX enfants en-tête.
        entetes = [c for _, c in g.enfants[oncle] if g.noeuds[c]["tag"] == "SectionHeader"]
        assert entetes == [premiere, derniere]

        assert _last_header_descendant(oncle) == derniere, (
            "la descente prend le premier enfant en-tête au lieu du dernier"
        )

    def test_la_descente_est_recursive_et_non_d_un_seul_cran(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Trois niveaux : la queue est la plus profonde, pas la fille directe."""
        g = GrapheFactice()
        doc = g.document("doc_essai/Trois/Niveaux", "Trois.pdf")
        oncle = _entete(g, "aa00000001", doc, 0, "Chapitre 1")
        fille = _entete(g, "aa00000002", oncle, 1, "Section 1.1")
        petite = _entete(g, "aa00000003", fille, 2, "Section 1.1.1")
        _element(g, "aa00000004", petite, 3, "w1")
        _branche(monkeypatch, g)

        # — le cas est-il atteint ? la descente doit valoir DEUX crans.
        assert g.enfants[oncle][0][1] == fille
        assert g.enfants[fille][0][1] == petite

        assert _last_header_descendant(oncle) == petite, (
            "la descente s'arrête au premier cran au lieu d'aller à la queue"
        )


# ─── (3) Le sous-choix ne s'applique QU'APRÈS une remontée ───────────────────


class TestAuCran0RienNeChange:
    """Le comportement des 532 en-têtes que (A) sert déjà est INCHANGÉ.

    C'est ce qui rend la mesure de coût du §4.6 vraie : « zéro aller-retour
    nGQL supplémentaire pour 532 des 746 en-têtes ». Appliquer le sous-choix
    au cran 0 changerait le nœud servi pour **157 de ces 532** (`mesuré` le
    9 septembre 2026) et ajouterait des aller-retours à un chemin que la
    décision annonce inchangé.

    LE PILOTE A UNE DÉCISION À PRENDRE ICI, et elle n'est pas dans ce lot :
    descendre au cran 0 aussi ferait passer la fidélité à l'ordre de lecture de
    378 / 532 à 527 / 532 pour la direction « avant » (`mesuré`, même commande).
    C'est un gain réel, au prix du coût annoncé. Décision de plan.
    """

    def test_au_cran_0_le_frere_est_servi_tel_quel(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        g = GrapheFactice()
        doc = g.document("doc_essai/Cran0/Sections", "Cran0.pdf")
        frere = _entete(g, "aa00000001", doc, 0, "Chapitre 1")
        sous = _entete(g, "aa00000002", frere, 1, "Section 1.1")
        _element(g, "aa00000003", sous, 2, "v1")
        cible = _entete(g, "bb00000001", doc, 100, "Chapitre 2")
        ancre = _element(g, "bb00000002", cible, 101, "z1")
        _branche(monkeypatch, g)

        # — le cas est-il atteint ? (A) doit RÉUSSIR, et les deux réponses du
        #   sous-choix doivent différer, sinon la mutation serait invisible.
        assert _find_sibling(doc, 100, "before") == frere
        assert _last_header_descendant(frere) == sous != frere

        assert _neighbour_section(doc, 100, "before") == frere, (
            "le sous-choix s'applique au cran 0 : le coût annoncé au §4.6 "
            "— zéro aller-retour pour 532 en-têtes — devient faux"
        )
        contexte = reconstruct_section(ancre)
        assert contexte.before_title == "Chapitre 1"


# ─── (4) LA BORNE : la remontée s'arrête au document ─────────────────────────


class TestLaRemonteeEstBorneeAuDocument:
    """`_ROOT_TAGS` arrête la remontée, et c'est la réserve 1 de `sequence`.

    `sequence` repart à 0 dans chaque document : un voisin cherché au-delà de la
    racine rapprocherait deux ouvrages. Sur le graphe EN SERVICE la borne n'est
    jamais atteinte autrement que par `_find_parent`, qui rend déjà `None` au
    sommet — les 23 racines sont les 23 documents, `mesuré`. Une borne dont
    aucune scène n'éprouve l'effet est exactement le garde vert que ce chantier
    a payé huit fois : ces deux gardes construisent donc la scène où elle est
    le SEUL rempart, un nœud au-dessus du `Document`.

    C'est une forme que l'ingestion ne produit pas aujourd'hui. Elle est le
    seul montage sous lequel retirer la borne se voit, et c'est à cela qu'une
    borne sert : tenir si la forme apparaît.
    """

    @staticmethod
    def _graphe_avec_un_etage_au_dessus_du_document(
        seq_errant: int,
    ) -> tuple[GrapheFactice, dict[str, str]]:
        g = GrapheFactice()
        v: dict[str, str] = {}
        # La racine porte un tag qui n'est ni Document ni SectionHeader.
        v["racine"] = g.noeud("ff00000001", "Collection", "collection", "Rayon", "", 0)
        del g.enfants[""]
        del g.parent[v["racine"]]
        v["errant"] = _entete(g, "ff00000002", v["racine"], seq_errant, "Titre errant")
        _element(g, "ff00000003", v["errant"], seq_errant + 1, "hors-document")

        v["doc"] = g.document("doc_essai/A/Chapitre", "A.pdf")
        g.enfants.setdefault(v["racine"], []).append((10, v["doc"]))
        g.parent[v["doc"]] = (v["racine"], 10)
        v["chapitre"] = _entete(g, "aa00000001", v["doc"], 11, "Chapitre A")
        v["ancre"] = _element(g, "aa00000002", v["chapitre"], 12, "a1")
        return g, v

    @pytest.mark.parametrize(
        ("direction", "seq_errant"), [("before", 0), ("after", 500)]
    )
    def test_la_remontee_ne_franchit_pas_la_racine_du_document(
        self, monkeypatch: pytest.MonkeyPatch, direction: str, seq_errant: int
    ) -> None:
        g, v = self._graphe_avec_un_etage_au_dessus_du_document(seq_errant)
        _branche(monkeypatch, g)

        # — le cas est-il atteint ? IL FAUT TROIS CHOSES.
        # 1. (A) échoue sous le Document, donc la remontée est bien tentée ;
        assert _find_sibling(v["doc"], 11, direction) is None
        # 2. le Document a bien un parent — sans quoi `_find_parent` rendrait
        #    `None` et la borne serait redondante, donc non éprouvée ;
        assert g.parent[v["doc"]][0] == v["racine"]
        # 3. et un en-tête EST joignable au-dessus, du bon côté.
        assert _find_sibling(v["racine"], 10, direction) == v["errant"], (
            "aucun en-tête errant du bon côté : retirer la borne ne se verrait pas"
        )

        assert _neighbour_section(v["doc"], 11, direction) is None, (
            "la remontée franchit la racine du document : elle sert une section "
            "d'un autre ouvrage, et la réserve 1 de `sequence` est violée"
        )

        contexte = reconstruct_section(v["ancre"])
        assert contexte.before == [] and contexte.before_title == ""
        assert contexte.after == [] and contexte.after_title == ""
        assert "Titre errant" not in contexte.markdown
        assert "hors-document" not in contexte.markdown


# ─── (5) L'ANCRAGE suit la remontée ──────────────────────────────────────────


class TestLAncrageSuitLaRemontee:
    """Chaque cran repasse par `_find_parent` : le couple (parent, rang) reste cohérent.

    `sequence` repart à 0 dans chaque document, donc une comparaison non ancrée
    rapprocherait deux ouvrages — réserve 1. La remontée CHANGE DE PARENT à
    chaque cran : elle doit donc changer de rang en même temps. Réutiliser le
    rang de la section sous son ancien parent est la faute naturelle, et elle
    est silencieuse : la requête reste ancrée sur un VID, seul le rang est faux.
    """

    def test_le_rang_change_de_parent_en_meme_temps_que_le_vid(
        self, graphe_des_oncles: tuple, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Garder le rang de la section en changeant de parent sert LE PARENT.

        `sequence` est un ordre de lecture GLOBAL : le rang d'une section sous
        son parent est toujours plus grand que celui du parent sous le
        grand-parent. Un cran qui garderait le rang de la section — la faute
        naturelle, et la seule que la remontée rende possible — chercherait donc
        « avant 110 » sous le document là où il faut chercher « avant 100 », et
        le premier en-tête qu'il trouverait serait **le parent lui-même**.

        La faute est silencieuse : la requête reste ancrée sur un VID, elle
        rend un en-tête, elle ne lève pas. Elle sert simplement un ancêtre de la
        section comme sa section précédente.
        """
        g, v = graphe_des_oncles
        _branche(monkeypatch, g)

        # — le cas est-il atteint ? les deux rangs doivent donner des réponses
        #   DIFFÉRENTES sous le document, sinon rien n'est éprouvé.
        assert _SEQ_CIBLE > _SEQ_PARENT
        avec_le_bon_rang = _find_sibling(v["doc"], _SEQ_PARENT, "before")
        avec_le_rang_perime = _find_sibling(v["doc"], _SEQ_CIBLE, "before")
        assert avec_le_bon_rang == v["oncle_avant"]
        assert avec_le_rang_perime == v["parent"], (
            "le rang périmé ne désigne pas le parent : la faute serait invisible"
        )
        assert avec_le_bon_rang != avec_le_rang_perime

        assert _neighbour_section(v["parent"], _SEQ_CIBLE, "before") == v["queue_avant"], (
            "la remontée garde le rang de la section en changeant de parent : "
            "elle sert le PARENT de la section comme sa section précédente"
        )

    def test_toute_requete_qui_compare_sequence_reste_ancree_sur_un_vid(
        self, graphe_des_oncles: tuple, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Le garde structurel de la réserve 1, appliqué à la REMONTÉE.

        `test_lecture_sequence.py` porte le même garde, mais sur une scène
        SANS remontée : ses fixtures n'imbriquent pas les en-têtes au point
        qu'un cran soit franchi. Une remontée qui abandonnerait l'ancre y
        resterait verte.
        """
        g, v = graphe_des_oncles
        _branche(monkeypatch, g)

        reconstruct_section(v["ancre"])

        comparaisons = [q for q in g.requetes if GrapheFactice.filtre_sur_sequence(q)]
        assert comparaisons, "aucune requête ne compare sequence : garde vide"
        # — le cas est-il atteint ? la remontée doit avoir eu lieu, donc des
        #   requêtes doivent partir du DOCUMENT et non du seul parent.
        ancres = {GrapheFactice._VID.search(q).group(1) for q in comparaisons}  # type: ignore[union-attr]
        assert v["doc"] in ancres, "aucune requête ne part du document : pas de remontée"
        assert v["parent"] in ancres
        for requete in comparaisons:
            assert GrapheFactice._VID.search(requete) is not None, (
                f"requête non ancrée sur un VID : {requete}"
            )


# ─── (6) (C) ne peut pas dégénérer — ce qui a écarté (B) ─────────────────────


class TestAucuneDegenerescence:
    """(C) ne rend jamais un ancêtre ni un descendant de la section de départ.

    C'est ce qui a écarté la définition (B), le voisin en ordre de lecture :
    elle gagne 2 en-têtes sur (C) et les paie de **191 adjacences dégénérées**
    — 382 couples (en-tête, direction) —, le titre suivant en ordre de lecture
    après un titre à enfants ÉTANT son propre premier enfant. On servirait
    comme « section suivante » un morceau de la section courante. (C) ne peut
    pas produire ce cas par construction ; ce garde tient la construction.
    """

    @pytest.mark.parametrize("direction", ["before", "after"])
    def test_la_voisine_n_est_ni_la_section_ni_un_de_ses_parents(
        self, graphe_des_oncles: tuple, monkeypatch: pytest.MonkeyPatch, direction: str
    ) -> None:
        g, v = graphe_des_oncles
        _branche(monkeypatch, g)

        voisine = _neighbour_section(v["parent"], _SEQ_CIBLE, direction)

        assert voisine is not None
        assert voisine != v["cible"]
        # — pas un ancêtre
        ancetres = set()
        courant = v["cible"]
        while courant in g.parent:
            courant = g.parent[courant][0]
            ancetres.add(courant)
        assert v["parent"] in ancetres and v["doc"] in ancetres, "fixture sans ancêtres"
        assert voisine not in ancetres
        # — pas un descendant
        descendants: set[str] = set()
        pile = [v["cible"]]
        while pile:
            n = pile.pop()
            for _, enfant in g.enfants.get(n, []):
                descendants.add(enfant)
                pile.append(enfant)
        assert descendants, "fixture sans descendants"
        assert voisine not in descendants

    def test_un_titre_a_enfants_ne_se_sert_pas_son_propre_premier_enfant(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """LE CAS EXACT des 191 dégénérescences de (B), construit ici.

        « Chapitre 1 » a pour successeur en ORDRE DE LECTURE sa propre
        « Section 1.1 ». Une implémentation de (B) servirait celle-ci comme
        section suivante ; (C) doit rendre l'en-tête suivant HORS du sous-arbre,
        ou rien.
        """
        g = GrapheFactice()
        doc = g.document("doc_essai/Degen/Chapitre", "Degen.pdf")
        chap = _entete(g, "aa00000001", doc, 0, "Chapitre 1")
        sous = _entete(g, "aa00000002", chap, 1, "Section 1.1")
        ancre = _element(g, "aa00000003", sous, 2, "d1")
        _branche(monkeypatch, g)

        # — le cas est-il atteint ? le successeur en ordre de lecture de
        #   « Chapitre 1 » est bien son premier enfant.
        assert g.enfants[chap][0][1] == sous
        assert g.parent[sous][0] == chap

        assert _neighbour_section(doc, 0, "after") is None, (
            "(C) sert le premier enfant du chapitre comme section suivante : "
            "c'est la dégénérescence qui a fait écarter (B)"
        )
        contexte = reconstruct_section(ancre)
        assert "Section 1.1" not in [e.text for e in contexte.after]


# ─── (7) Le `None` qui reste `None` est une DÉCISION ─────────────────────────


class TestLeBlocVideEstUneDecision:
    """Les 25 en-têtes « avant » et 24 « après » sans voisine gardent un bloc vide.

    `mesuré` le 9 septembre 2026 : après remontée, (C) ne trouve rien pour 25
    en-têtes en « avant » et 24 en « après » — ceux qui ouvrent ou ferment leur
    document. La tentation est d'emprunter au document suivant ; la réserve 1
    l'interdit. Ce `None` est donc une décision écrite, et ce garde est ce qui
    la rend écrite plutôt que restante.

    UNE MESURE QUI BORNE LA LECTURE DU §4.6, et elle corrige une coïncidence.
    Le §4.6 juxtapose « 25 en-têtes premiers sous leur parent » et « jamais
    trouvé pour 25 » : les deux comptes valent 25, **les ENSEMBLES non** —
    intersection 22 (`mesuré`, même commande). C'est la même faute que les
    « mêmes 214 dans les deux directions » que le lot 2 a corrigée : deux
    ensembles de même cardinal ne sont pas le même ensemble.
    """

    @pytest.mark.parametrize(
        ("direction", "seq"), [("before", 0), ("after", 100)]
    )
    def test_un_document_a_section_unique_garde_un_bloc_vide(
        self, monkeypatch: pytest.MonkeyPatch, direction: str, seq: int
    ) -> None:
        """Un document à un seul en-tête n'emprunte rien, dans aucune direction."""
        g = GrapheFactice()
        doc_a = g.document("doc_essai/A/Chapitre", "A.pdf")
        doc_b = g.document("doc_essai/B/Chapitre", "B.pdf")
        seule = _entete(g, "aa00000001", doc_a, 50, "Seule A")
        ancre = _element(g, "aa00000002", seule, 51, "a1")
        # Le document B porte un en-tête aux DEUX rangs qu'une remontée non
        # bornée atteindrait : avant 50 et après 50.
        autre = _entete(g, "bb00000001", doc_b, seq, "Titre B")
        _element(g, "bb00000002", autre, seq + 1, "b1")
        _branche(monkeypatch, g)

        # — le cas est-il atteint ? un balayage NON ancré atteindrait bien
        #   l'en-tête de B du bon côté du rang 50.
        globales = g.execute(
            f"LOOKUP ON PARENT_OF WHERE properties(edge).sequence "
            f"{'<' if direction == 'before' else '>'} 50 "
            "YIELD dst(edge) AS sibling_id, properties(edge).sequence AS seq "
            f"| ORDER BY $-.seq {'DESC' if direction == 'before' else 'ASC'} | LIMIT 5;"
        )
        assert autre in [r["sibling_id"] for r in globales], (
            "le montage ne peut pas franchir la frontière : garde décoratif"
        )

        assert _neighbour_section(doc_a, 50, direction) is None

        contexte = reconstruct_section(ancre)
        assert contexte.before == [] and contexte.before_title == ""
        assert contexte.after == [] and contexte.after_title == ""
        assert "Titre B" not in contexte.markdown


# ─── (8) Le point de contact avec la réserve 3 ────────────────────────────────


def test_le_decoupage_de_la_voisine_reste_positionnel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """La remontée ne rend pas le découpage moins positionnel qu'il ne l'était.

    C'est la réserve 3, dont le site canonique est `test_lecture_sequence.py` :
    `sequence` n'est pas contiguë sous un parent, donc `_neighbour_elements`
    découpe sur des POSITIONS (`rows[-budget:]` / `rows[:budget]`). Ce garde ne
    remplace pas celui-là ; il vérifie que la SECTION ATTEINTE PAR REMONTÉE est
    découpée de la même façon — un encadrement sur les valeurs rendrait moins
    d'éléments que le budget.
    """
    ecart = 1000
    g = GrapheFactice()
    doc = g.document("doc_essai/Espace/Chapitre", "Espace.pdf")
    oncle = _entete(g, "aa00000001", doc, 0, "Chapitre 1")
    queue = _entete(g, "aa00000010", oncle, 10, "Section 1.9")
    # Enfants très espacés : un encadrement `sequence ∈ [s−k, s+k]` n'en
    # attraperait qu'un seul là où le budget en demande trois.
    attendus = [
        _element(g, f"aa0000002{i}", queue, 100 + i * ecart, f"x{i}") for i in range(5)
    ]
    parent = _entete(g, "bb00000001", doc, 100_000, "Chapitre 2")
    _element(g, "bb00000002", parent, 100_001, "p1")
    cible = _entete(g, "bb00000010", parent, 100_010, "Section 2.1")
    ancre = _element(g, "bb00000011", cible, 100_011, "c1")
    _element(g, "bb00000020", parent, 100_100, "p2")
    _branche(monkeypatch, g)

    # — le cas est-il atteint ? la voisine est trouvée PAR REMONTÉE, et ses
    #   enfants sont non contigus au-delà du budget.
    assert _find_sibling(parent, 100_010, "before") is None
    assert _neighbour_section(parent, 100_010, "before") == queue
    rangs = [s for s, _ in g.enfants[queue]]
    assert min(b - a for a, b in zip(rangs, rangs[1:], strict=False)) > _VOISINS

    contexte = reconstruct_section(ancre)

    assert [e.node_id for e in contexte.before] == attendus[-_VOISINS:], (
        "le découpage de la voisine atteinte par remontée n'est plus positionnel"
    )


# ─── (9) LE COÛT DE LA DESCENTE ──────────────────────────────────────────────


class TestLeCoutDeLaDescenteEstBorne:
    """La descente demande UN tag par niveau, pas un tag par enfant.

    CE GARDE EXISTE PARCE QUE LA PREMIÈRE ÉCRITURE DE `_last_header_descendant`
    NE L'AVAIT PAS. Elle établissait la liste des enfants en-tête avant de
    prendre le dernier, donc elle demandait le tag de **chaque** enfant, et
    `_get_node_properties` n'est pas mémoïsée : un aller-retour nGQL par enfant.
    `mesuré` le 9 septembre 2026 sur le graphe en service, sur les 189 remontées
    « avant » et leurs 136 niveaux de descente : **2 018** tags évalués contre
    **136** à rebours, et **pire cas 180 pour une seule reconstruction** contre
    **1**. Un en-tête du corpus porte 183 enfants.

    C'est le chemin de lecture de CHAQUE recherche. La suite était verte des
    deux côtés : aucun garde du dépôt ne compte les aller-retours, et une
    régression de latence ne rougit nulle part. Celui-ci les compte.
    """

    @staticmethod
    def _oncle_a_larges_epaules(
        nb_enfants: int,
    ) -> tuple[GrapheFactice, dict[str, str]]:
        """Un oncle dont le DERNIER enfant est l'en-tête, et les autres non.

        C'est la forme du graphe en service : le sous-titre suivant vient après
        le corps de la section, donc en dernier. Un balayage avant paie tous les
        éléments du corps ; un balayage arrière n'en paie aucun.
        """
        g = GrapheFactice()
        v: dict[str, str] = {}
        v["doc"] = g.document("doc_essai/Large/Chapitre", "Large.pdf")
        v["oncle"] = _entete(g, "aa00000001", v["doc"], 0, "Chapitre 1")
        for i in range(nb_enfants):
            _element(g, f"ac{i:08d}", v["oncle"], 1 + i, f"corps {i}")
        v["queue"] = _entete(g, "ab00000001", v["oncle"], 1 + nb_enfants, "Section 1.9")
        _element(g, "ab00000002", v["queue"], 2 + nb_enfants, "queue")

        v["parent"] = _entete(g, "bb00000001", v["doc"], 100_000, "Chapitre 2")
        _element(g, "bb00000002", v["parent"], 100_001, "p1")
        v["cible"] = _entete(g, "bb00000010", v["parent"], 100_010, "Section 2.1")
        v["ancre"] = _element(g, "bb00000011", v["cible"], 100_011, "c1")
        _element(g, "bb00000020", v["parent"], 100_100, "p2")
        return g, v

    def test_un_seul_tag_est_demande_par_niveau_de_descente(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        nb_enfants = 40
        g, v = self._oncle_a_larges_epaules(nb_enfants)
        _branche(monkeypatch, g)

        demandes: list[str] = []
        vraies_proprietes = g.proprietes

        def compte(node_id: str) -> dict[str, object]:
            demandes.append(node_id)
            return vraies_proprietes(node_id)

        monkeypatch.setattr(graph_context, "_get_node_properties", compte)

        # — le cas est-il atteint ? IL FAUT TROIS CHOSES.
        # 1. la voisine « avant » doit être trouvée PAR REMONTÉE, sinon aucune
        #    descente n'a lieu et le compte serait vide de sens ;
        assert _find_sibling(v["parent"], 100_010, "before") is None
        assert _neighbour_section(v["parent"], 100_010, "before") == v["queue"]
        # 2. l'oncle doit porter beaucoup d'enfants, et
        # 3. son en-tête doit être le DERNIER — c'est la forme qui sépare les
        #    deux sens de balayage. Sans elle, les deux coûteraient pareil.
        fils = g.enfants[v["oncle"]]
        assert len(fils) == nb_enfants + 1
        assert fils[-1][1] == v["queue"]

        demandes.clear()
        graph_context._last_header_descendant(v["oncle"])

        # Un niveau de descente (l'oncle), puis un second qui ne trouve rien
        # sous `queue` : deux niveaux, et au plus un tag demandé par niveau
        # au-delà du premier candidat examiné.
        assert len(demandes) <= 2 * 2, (
            f"{len(demandes)} tags demandés pour deux niveaux de descente : le "
            f"balayage repart vers l'avant et paie les {nb_enfants} éléments du "
            "corps de l'oncle — c'est le chemin de lecture de chaque recherche"
        )
        assert v["queue"] in demandes, "la descente n'a pas examiné le bon nœud"

    def test_une_reconstruction_complete_ne_paie_pas_le_corps_de_l_oncle(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Le même compte, mais par `reconstruct_section` — le vrai chemin.

        Le garde ci-dessus appelle `_last_header_descendant` directement. Une
        réécriture qui pousserait le balayage ailleurs dans le module le
        laisserait vert ; celui-ci compte sur le point d'entrée réel.
        """
        nb_enfants = 40
        g, v = self._oncle_a_larges_epaules(nb_enfants)
        _branche(monkeypatch, g)

        demandes: list[str] = []
        vraies_proprietes = g.proprietes

        def compte(node_id: str) -> dict[str, object]:
            demandes.append(node_id)
            return vraies_proprietes(node_id)

        monkeypatch.setattr(graph_context, "_get_node_properties", compte)

        contexte = reconstruct_section(v["ancre"])

        # — le cas est-il atteint ? la descente doit avoir servi la queue.
        assert contexte.before_title == "Section 1.9"
        corps = {c for _, c in g.enfants[v["oncle"]] if c != v["queue"]}
        payes = corps & set(demandes)
        assert not payes, (
            f"{len(payes)} éléments du corps de l'oncle ont coûté un aller-retour "
            "nGQL : le balayage de la descente est reparti vers l'avant"
        )


# ─── (10) LE TÉMOIN INERTE ────────────────────────────────────────────────────


def test_temoin_inerte_le_graphe_plat_est_servi_comme_avant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """LE TÉMOIN. Sur un graphe PLAT, (A) et (C) rendent la MÊME chose.

    Un graphe plat — tous les en-têtes enfants directs du `Document`, la forme
    d'avant le 2 septembre 2026 — n'offre aucun oncle : la remontée ne peut
    rien changer. Ce test doit donc rester VERT sous toute mutation de la
    remontée, et rougir seulement si la définition (A) elle-même est cassée.

    C'est ce qui distingue « la remontée est fausse » de « le module est
    cassé » dans le tableau des mutations : une mutation qui rougit ICI n'a pas
    éprouvé la remontée, elle a cassé autre chose.
    """
    g = GrapheFactice()
    doc = g.document("doc_essai/Plat/Chapitre", "Plat.pdf")
    avant = _entete(g, "aa00000001", doc, 0, "Chapitre 1")
    for i in range(3):
        _element(g, f"aa0000000{i + 2}", avant, 1 + i, f"a{i + 1}")
    cible = _entete(g, "bb00000001", doc, 100, "Chapitre 2")
    ancre = _element(g, "bb00000002", cible, 101, "z1")
    apres = _entete(g, "cc00000001", doc, 200, "Chapitre 3")
    for i in range(3):
        _element(g, f"cc0000000{i + 2}", apres, 201 + i, f"c{i + 1}")
    _branche(monkeypatch, g)

    # — le témoin est-il bien INERTE ? aucun en-tête ne doit avoir d'en-tête
    #   pour parent, sinon la remontée aurait prise et le témoin ne témoignerait
    #   plus de rien.
    for vid, props in g.noeuds.items():
        if props["tag"] != "SectionHeader":
            continue
        parent_du_titre = g.parent[vid][0]
        assert g.noeuds[parent_du_titre]["tag"] == "Document", (
            f"{vid} a un en-tête pour parent : le graphe n'est pas plat"
        )
    # — et (A) doit suffire des deux côtés : aucun cran à monter.
    assert _find_sibling(doc, 100, "before") == avant
    assert _find_sibling(doc, 100, "after") == apres

    contexte = reconstruct_section(ancre)

    assert contexte.before_title == "Chapitre 1"
    assert contexte.after_title == "Chapitre 3"
    assert [e.text for e in contexte.before] == ["a1", "a2", "a3"]
    assert [e.text for e in contexte.after] == ["c1", "c2", "c3"]
