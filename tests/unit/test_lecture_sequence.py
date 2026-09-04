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
# En deçà de deux lignes, aucun ordre n'est observable : une liste de zéro ou un
# élément est triée quoi qu'on fasse, et la rotation du bouchon serait l'identité.
_MIN_POUR_DESORDRE = 2
# `LIMIT` de la SONDE d'atteignabilité de
# `test_les_sections_voisines_ne_franchissent_pas_la_frontiere`, et non de la
# production. Il est FIGÉ, et c'est une correction : la sonde empruntait
# `graph_context._SIBLING_CANDIDATES`, si bien que régler la constante à 1 —
# ce que son propre commentaire annonce comme suffisant — rendait la suite
# rouge sur la PRÉCONDITION de la sonde, jamais sur la propriété gardée
# (`mesuré` : `assert 'bbbbbbbb01' in ['ca00000000']`). Un garde dont le cas
# n'est atteint que pour une valeur de réglage n'éprouve pas ce réglage : il
# éprouve sa propre mise en scène.
_LIMITE_DE_SONDE = 5
_NB_ENFANTS_COURTE = 3
# Écart entre deux frères du graphe factice. Il vaut plus que la demi-fenêtre,
# donc un encadrement `sequence ∈ [s−6, s+6]` n'attrape que l'ancre elle-même.
_ECART = 10


class ClauseNonEvaluableError(RuntimeError):
    """Le bouchon a reçu une clause qu'il ne sait pas évaluer ENTIÈREMENT.

    C'EST LA FORME FAIL-CLOSED, ET ELLE REMPLACE UNE BORNE PAR ÉNUMÉRATION QUI
    ÉTAIT FAUSSE. La version précédente modélisait un `WHERE` nGQL par recherche
    de sous-chaîne dans le texte de la requête, et ignorait la liste `YIELD` :
    une écriture qu'elle ne reconnaissait pas ne filtrait rien, donc le bouchon
    rendait TOUTES les lignes, donc la mutation passait en vert. `mesuré` le
    4 septembre 2026 au site de `reconstruct_section`, `make test` : trois
    écritures d'un même encadrement rendaient `rc=0`, 0 rouge, 502 passés.

    | l'écriture | ce que la version précédente en tirait |
    |---|---|
    | `properties(edge).sequence IN [65…77]` | rien — invisible |
    | `sequence - 65 >= 0 AND 77 - sequence >= 0` | `sequence >= 0` — MAL LUE |
    | `| YIELD … $-.seq AS rang WHERE $-.rang >= 65` | rien — `YIELD` ignorée |

    La deuxième est la plus insidieuse : le bouchon ne « ne reconnaissait pas »,
    il MÉSINTERPRÉTAIT — un filtre qui ne retire rien, dont le vert se lit comme
    un garde juste.

    ET LES TROIS SONT DU nGQL RÉEL, pas des formes de laboratoire. `mesuré` en
    LECTURE SEULE contre NebulaGraph en service le 4 septembre 2026 — parent
    `cde213aee4`, `sequence` 341, fenêtre `[335, 347]`, ancre réellement
    amputée : les deux premières sont ACCEPTÉES et rendent l'ensemble
    IDENTIQUE à l'encadrement classique, **12 éléments là où le découpage
    positionnel en rend 13** ; la troisième est acceptée et rend **0 ligne**,
    nGQL refusant l'alias en entrée du `WHERE` du `YIELD` qui le définit.

    POURQUOI LEVER, ET NON AJOUTER DEUX MOTIFS DE PLUS

    La cause est de NATURE, pas d'énumération : une grammaire d'expressions ne
    se borne pas par une liste d'exceptions, et la classe resterait ouverte sur
    le membre suivant. Le bouchon lève donc sur toute clause portant `sequence`
    qui ne se réduit pas entièrement à une comparaison à un littéral entier. Un
    garde dont la cécité produit un rouge est seulement bruyant ; un garde dont
    la cécité produit un vert est décoratif.
    """


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
        self.parent[vid] = (parent, sequence)
        return vid

    # ── moteur de requêtes ──────────────────────────────────────────────────

    # ── le modèle de requête : des étages, une projection, une condition ────
    #
    # Ce que le bouchon sait lire est BORNÉ, et la borne est écrite ici plutôt
    # que dans une prose qu'aucun rouge ne relit : une clause `WHERE` réduite à
    # une conjonction (`AND`) de comparaisons entre la `sequence` de l'arête —
    # ou une colonne d'amont qui la porte — et un littéral entier. Tout ce qui
    # touche à `sequence` sans se réduire à cela LÈVE.
    _VID = re.compile(r'GO FROM "((?:[^"\\]|\\.)*)"')
    _TUBE = re.compile(r"\|")
    _ET = re.compile(r"\bAND\b")
    _VIRGULE = re.compile(r",")
    _MOT_WHERE = re.compile(r"\bWHERE\b")
    _MOT_YIELD = re.compile(r"\bYIELD\b")
    _ALIAS = re.compile(r"\s+AS\s+")
    # La `sequence` telle que l'arête la porte, et telle qu'un étage aval la
    # reprend. La seconde est résolue contre les colonnes RÉELLEMENT projetées
    # par l'étage amont : c'est ce qui distingue `$-.seq` — une colonne qui
    # existe — de `$-.rang` — un alias que nGQL refuse en entrée du `WHERE` du
    # `YIELD` qui le définit.
    _SEQUENCE_ARETE = "properties(edge).sequence"
    _COLONNE_AMONT = re.compile(r"\$-\.(\w+)")
    _MOT_SEQUENCE = re.compile(r"\bsequence\b")
    _OPERATEUR = r"(>=|<=|!=|==|>|<)"
    _ENTIER = r"(-?\d+)"
    _ORDRE = re.compile(r"ORDER BY\s+\$-\.(\w+)\s+(ASC|DESC)")
    _LIMITE = re.compile(r"LIMIT (\d+)")

    _COMPARE = {
        ">=": lambda a, b: a >= b,
        "<=": lambda a, b: a <= b,
        ">": lambda a, b: a > b,
        "<": lambda a, b: a < b,
        "==": lambda a, b: a == b,
        "!=": lambda a, b: a != b,
    }
    # `N op sequence` equivaut a `sequence op' N` avec l'operateur retourne.
    _RETOURNE = {">=": "<=", "<=": ">=", ">": "<", "<": ">", "==": "==", "!=": "!="}

    def _vid_de(self, nql: str) -> str | None:
        trouve = self._VID.search(nql)
        if trouve is None:
            return None
        return trouve.group(1).replace(r'\"', '"').replace(r"\\", "\\")

    # ── le découpage, et pourquoi il ne se fait pas à la lettre ─────────────

    @staticmethod
    def _au_premier_niveau(texte: str, motif: re.Pattern[str]) -> list[str]:
        """Découpe `texte` sur `motif`, hors guillemets, parenthèses et crochets.

        Découper à la lettre suffirait pour les requêtes que ce dépôt écrit ; il
        ne suffit pas pour celles qu'une MUTATION écrit, et ce sont celles-là
        que le bouchon doit voir passer. `IN [65, 66, …]` porte des virgules qui
        n'ouvrent aucun item de projection, et un VID peut porter n'importe
        quoi entre guillemets.
        """
        morceaux: list[str] = []
        debut = profondeur = position = 0
        guillemets = False
        while position < len(texte):
            lettre = texte[position]
            if guillemets:
                if lettre == "\\":
                    position += 2
                    continue
                if lettre == '"':
                    guillemets = False
                position += 1
                continue
            if lettre == '"':
                guillemets = True
            elif lettre in "([":
                profondeur += 1
            elif lettre in ")]":
                profondeur -= 1
            elif profondeur == 0:
                trouve = motif.match(texte, position)
                if trouve is not None:
                    morceaux.append(texte[debut:position])
                    position = debut = trouve.end()
                    continue
            position += 1
        morceaux.append(texte[debut:])
        return morceaux

    @classmethod
    def _clauses(cls, etage: str) -> tuple[str, str]:
        """Sépare la liste `YIELD` d'un étage de sa clause `WHERE`.

        C'EST LA DISTINCTION QUE LA VERSION PRÉCÉDENTE NE FAISAIT PAS, et c'est
        elle qui rend le fail-closed possible sans rougir sur le code SAIN :
        `_get_children` NOMME `properties(edge).sequence`, dans sa liste
        `YIELD`, où c'est une PROJECTION et non un filtre. Un garde-fou du
        genre « lever si `sequence` apparaît et qu'aucun motif ne matche »
        rendrait la suite rouge sur du code juste. Seule la clause `WHERE` est
        examinée, et c'est pourquoi elle est isolée avant toute chose.

        L'ordre des deux mots-clés dépend de l'étage — `GO … WHERE … YIELD …`
        d'un côté, `| YIELD … WHERE …` de l'autre — donc chacun borne l'autre.
        """
        ou = cls._MOT_WHERE.search(etage)
        quoi = cls._MOT_YIELD.search(etage)
        if quoi is None:
            projection = ""
        elif ou is not None and ou.start() > quoi.start():
            projection = etage[quoi.end() : ou.start()]
        else:
            projection = etage[quoi.end() :]
        if ou is None:
            condition = ""
        elif quoi is not None and quoi.start() > ou.start():
            condition = etage[ou.end() : quoi.start()]
        else:
            condition = etage[ou.end() :]
        return projection.strip().rstrip(";").strip(), condition.strip().rstrip(";").strip()

    @classmethod
    def _projette(
        cls, projection: str, colonnes: set[str], sequences: set[str]
    ) -> tuple[set[str], set[str]]:
        """Les colonnes qu'un étage rend, et celles qui portent la `sequence`.

        Un étage sans `YIELD` — `| ORDER BY …`, `| LIMIT …` — laisse passer les
        colonnes de son amont.
        """
        if not projection:
            return colonnes, sequences
        sorties: set[str] = set()
        sorties_sequence: set[str] = set()
        for item in cls._au_premier_niveau(projection, cls._VIRGULE):
            morceaux = cls._ALIAS.split(item)
            if len(morceaux) < 2:
                continue
            nom = morceaux[-1].strip()
            expression = " AS ".join(morceaux[:-1])
            sorties.add(nom)
            if cls._SEQUENCE_ARETE in expression or any(
                reprise in sequences for reprise in cls._COLONNE_AMONT.findall(expression)
            ):
                sorties_sequence.add(nom)
        return sorties, sorties_sequence

    # ── le point de décision UNIQUE, et il est fail-closed ──────────────────

    @classmethod
    def _comparaison(
        cls, conjonction: str, sequences: set[str], nql: str
    ) -> tuple[str, int] | None:
        """Rend la comparaison portée par une conjonction, ou lève.

        Trois issues, et pas une quatrième :

        - la conjonction ne parle ni de `sequence` ni d'une colonne d'amont :
          elle est hors sujet, et le bouchon l'ignore — c'est la BORNE, et elle
          est dite ici plutôt que supposée ;
        - elle se réduit ENTIÈREMENT à `ref op N` ou `N op ref` : elle est
          appliquée ;
        - tout le reste lève.

        Le `fullmatch` est ce qui ferme la classe. Un `search` y lisait
        `sequence >= 0` dans `77 - properties(edge).sequence >= 0` — un filtre
        qui ne retire rien, dont le vert se lit comme un garde juste.
        """
        texte = conjonction.strip()
        if not texte:
            return None
        if not cls._MOT_SEQUENCE.search(texte) and not cls._COLONNE_AMONT.search(texte):
            return None
        references = [re.escape(cls._SEQUENCE_ARETE)] + [
            rf"\$-\.{re.escape(nom)}" for nom in sorted(sequences)
        ]
        reference = "(?:" + "|".join(references) + ")"
        directe = re.fullmatch(rf"{reference}\s*{cls._OPERATEUR}\s*{cls._ENTIER}", texte)
        if directe is not None:
            return directe.group(1), int(directe.group(2))
        inverse = re.fullmatch(rf"{cls._ENTIER}\s*{cls._OPERATEUR}\s*{reference}", texte)
        if inverse is not None:
            return cls._RETOURNE[inverse.group(2)], int(inverse.group(1))
        raise ClauseNonEvaluableError(
            "clause portant `sequence` que le bouchon ne sait pas évaluer "
            f"entièrement : {texte!r}\nrequête : {nql}"
        )

    @classmethod
    def _verifie_l_ordre(cls, etage: str, sequences: set[str], nql: str) -> None:
        """Un `ORDER BY` doit trier une colonne qui porte la `sequence`.

        Même famille que le reste : un tri sur une colonne que le bouchon ne
        sait pas résoudre ne doit pas se traduire par « pas de tri », qui est un
        vert.
        """
        if "ORDER BY" not in etage:
            return
        trouve = cls._ORDRE.search(etage)
        if trouve is None or trouve.group(1) not in sequences:
            raise ClauseNonEvaluableError(
                "`ORDER BY` que le bouchon ne sait pas résoudre — la colonne "
                f"triée ne porte pas la `sequence` de l'arête : {etage.strip()!r}"
                f"\nrequête : {nql}"
            )

    @classmethod
    def _comparaisons(cls, nql: str) -> list[tuple[str, int]]:
        """Les comparaisons de `sequence` que porte la requête, tous étages.

        La clause `WHERE` d'un étage est évaluée contre les colonnes de son
        AMONT — c'est la sémantique de nGQL, et c'est elle qui fait qu'un alias
        défini par le `YIELD` d'un étage n'est pas lisible dans le `WHERE` de
        ce même étage. Les colonnes ne sont donc mises à jour qu'APRÈS.
        """
        colonnes: set[str] = set()
        sequences: set[str] = set()
        trouvees: list[tuple[str, int]] = []
        for etage in cls._au_premier_niveau(nql, cls._TUBE):
            projection, condition = cls._clauses(etage)
            for conjonction in cls._au_premier_niveau(condition, cls._ET):
                comparaison = cls._comparaison(conjonction, sequences, nql)
                if comparaison is not None:
                    trouvees.append(comparaison)
            cls._verifie_l_ordre(etage, sequences, nql)
            colonnes, sequences = cls._projette(projection, colonnes, sequences)
        return trouvees

    @classmethod
    def filtre_sur_sequence(cls, nql: str) -> bool:
        """La requête compare-t-elle `sequence` ? Lève si elle le fait autrement.

        Le garde structurel de la réserve 1 passe par ici. C'est délibéré, et
        c'est la moitié qui manquait : l'expression `_FILTRE` était PARTAGÉE
        entre le bouchon et ce garde, si bien qu'une seule cécité en défaisait
        deux — le critère exact qui avait fait coter la trouvaille bloquante. Le
        point de décision reste unique ; il ne rend simplement plus « rien à
        filtrer » sur ce qu'il ne comprend pas.
        """
        return bool(cls._comparaisons(nql))

    def _applique_les_filtres(
        self, nql: str, lignes: list[tuple[int, str]]
    ) -> list[tuple[int, str]]:
        """Applique au résultat les comparaisons portées par la requête."""
        for operateur, valeur in self._comparaisons(nql):
            compare = self._COMPARE[operateur]
            lignes = [(s, c) for s, c in lignes if compare(s, valeur)]
        return lignes

    def _applique_ordre_et_limite(
        self, nql: str, lignes: list[tuple[int, str]]
    ) -> list[tuple[int, str]]:
        ordre = self._ORDRE.search(nql)
        if ordre is not None:
            lignes = sorted(lignes, reverse=ordre.group(2) == "DESC")
        limite = self._LIMITE.search(nql)
        if limite is not None:
            lignes = lignes[: int(limite.group(1))]
        return lignes

    @staticmethod
    def _desordonne(lignes: list[tuple[int, str]]) -> list[tuple[int, str]]:
        """Rend les lignes dans un ordre GARANTI non trié dès qu'il y en a deux.

        C'EST LE CŒUR DU MONTAGE, et il a manqué à la première version de ce
        fichier. NebulaGraph ne promet AUCUN ordre à un `GO FROM` sans
        `ORDER BY` : `mesuré` le 3 septembre 2026 sur les 334 parents à treize
        enfants ou plus du graphe en service, 80 sur 80 des parents testés
        rendent leurs enfants dans un ordre non trié — un exemple commençant
        `226, 157, 182, 224, 258…`.

        LE RENVOI QUI SE TROUVAIT ICI ÉTAIT FAUX : il envoyait chercher ces deux
        chiffres au « §4.6 », où ils ne sont pas. `mesuré` le 4 septembre 2026,
        ils sont au **§4.14** de `documentation/axes_amelioration.md`. Et ils
        sont désormais REJOUABLES, ce qu'ils n'étaient pas : les lignes
        « parents à 13 enfants ou plus » et « enfants NON triés sans `ORDER BY` »
        de `scripts/mesurer_le_graphe.py` les impriment — `rejoué` le
        4 septembre 2026, 334 parents, 80 sur 80 non triés, 80 sur 80 triés avec
        `ORDER BY`.

        Un bouchon qui rendrait ses enfants triés FABRIQUERAIT la précondition
        que ce fichier doit éprouver : retirer le `| ORDER BY $-.seq ASC` de
        `_get_children` ne changerait alors rien à ce qu'il rend, et le garde
        serait décoratif. C'est exactement ce qui était arrivé — `mesuré` : sous
        cette mutation, les 496 tests restaient verts.

        POURQUOI UNE ROTATION, ET NON UN TIRAGE ALÉATOIRE

        Une rotation d'une demi-longueur est non triée **par construction** pour
        `n ≥ 2` : faire tourner une suite strictement croissante de `k` rangs,
        avec `0 < k < n`, ne peut pas rendre une suite croissante. Un
        `random.shuffle`, même à graine fixe, ne l'est que par constatation — et
        un garde dont le cas n'est atteint que par chance n'est pas un garde.
        La rotation est en outre distincte de l'ordre inverse dès `n ≥ 3`, donc
        elle ne confond pas une mutation `ASC → DESC` avec elle-même.
        """
        if len(lignes) < _MIN_POUR_DESORDRE:
            return lignes
        milieu = len(lignes) // 2
        return lignes[milieu:] + lignes[:milieu]

    def _portee(self, nql: str) -> list[tuple[int, str]]:
        """Les arêtes que la requête balaie, AVANT filtrage et AVANT tout ordre.

        Une requête ancrée (`GO FROM "<vid>"`) ne voit que les enfants de ce
        VID. Une requête NON ancrée — un `LOOKUP` sur l'arête, par exemple —
        balaie **tout le graphe**, donc les 23 documents. C'est ce que rendrait
        NebulaGraph, et c'est précisément ce que la réserve 1 interdit de faire
        avec `sequence` : ses valeurs repartent à 0 dans chaque document, donc
        une comparaison non ancrée rapproche des éléments de deux ouvrages.

        Un bouchon qui rendrait une liste vide pour une requête non ancrée
        laisserait passer ce défaut-là en le faisant ressembler à « aucun
        voisin trouvé ».

        L'ordre rendu est délibérément non trié — voir `_desordonne`. Seul un
        `ORDER BY` porté par la requête trie, parce que c'est la seule chose qui
        trie dans NebulaGraph.
        """
        vid = self._vid_de(nql)
        if vid is not None:
            return self._desordonne(list(self.enfants.get(vid, [])))
        toutes = [paire for enfants in self.enfants.values() for paire in enfants]
        return self._desordonne(toutes)

    def execute(self, nql: str) -> list[dict[str, object]]:
        """Le remplaçant de `graph_context._execute`.

        La requête est validée AVANT tout aiguillage : une clause que le bouchon
        ne sait pas évaluer lève, quelle que soit la branche qui l'aurait
        servie. Valider dans la seule branche qui filtre laisserait une écriture
        non évaluable passer par `REVERSELY` sans un mot.
        """
        self.requetes.append(nql)
        self._comparaisons(nql)
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


@pytest.fixture
def graphe_imbrique() -> tuple[GrapheFactice, list[str], dict[str, str]]:
    """Un graphe où les en-têtes s'IMBRIQUENT, comme le graphe en service.

    POURQUOI CETTE FIXTURE EXISTE

    Aucune fixture du dépôt n'en construisait : les neuf `SectionHeader` des
    fixtures existantes ont tous le `Document` pour parent. Le cas de **583
    en-têtes sur 746** — ceux qui ont pour parent un autre `SectionHeader`,
    `mesuré` le 3 septembre 2026, §4.6 de `documentation/axes_amelioration.md` —
    n'était donc construit nulle part, dans un lot dont le sujet est précisément
    que le graphe s'imbrique.

    Conséquence `mesuré` avant qu'elle existe : remettre la prémisse morte dans
    `_climb_to_section` — faire partir la recherche de voisine du `Document` au
    lieu du parent réel — laissait les 500 tests VERTS, et `_MAX_DEPTH = 2` les
    laissait verts aussi tout en reperdant le nom du document, c'est-à-dire en
    réintroduisant le défaut du §1.2 du registre de pilotage.

    LA FORME, ET CE QUE CHAQUE ARÊTE Y FAIT

        Document « Livre.pdf »
        ├── Chapitre 1                       (seq 0)   ← ce que la prémisse
        │   ├── Section 1.1                  (seq 1)      morte trouverait
        │   │   ├── Sous-section 1.1.1       (seq 2)   ← section de l'ancre
        │   │   │   └── trois éléments
        │   │   └── Sous-section 1.1.2       (seq 50)  ← la VRAIE voisine
        │   │       └── trois éléments
        │   └── Section 1.2                  (seq 200)
        └── Chapitre 2                       (seq 300) ← ce que la prémisse
            └── trois éléments                            morte trouverait

    La forme est choisie pour que « voisine sous le parent réel » et « voisine
    sous le Document » donnent des réponses DIFFÉRENTES dans les deux
    directions — sans quoi la prémisse morte resterait invisible ici aussi :

    - après : le parent réel donne `Sous-section 1.1.2`, le Document donne
      `Chapitre 2` ;
    - avant : le parent réel n'a AUCUN frère avant le rang 2, le Document donne
      `Chapitre 1`.

    L'ancre est à quatre sauts du `Document`, donc `_MAX_DEPTH = 2` ne l'atteint
    plus et le nom du fichier se reperd.

    Returns:
        (graphe, éléments de la sous-section de l'ancre, VIDs nommés).
    """
    g = GrapheFactice()
    doc = g.document("doc_essai/Ouvrage/Livre", "Livre.pdf", collection="Ouvrage")
    ch1 = g.noeud("aaaaaaaa01", "SectionHeader", "section_header", "Chapitre 1", doc, 0)
    s11 = g.noeud("aaaaaaaa02", "SectionHeader", "section_header", "Section 1.1", ch1, 1)
    ss111 = g.noeud(
        "aaaaaaaa03", "SectionHeader", "section_header", "Sous-section 1.1.1", s11, 2
    )
    ss112 = g.noeud(
        "aaaaaaaa04", "SectionHeader", "section_header", "Sous-section 1.1.2", s11, 50
    )
    g.noeud("aaaaaaaa05", "SectionHeader", "section_header", "Section 1.2", ch1, 200)
    ch2 = g.noeud("aaaaaaaa06", "SectionHeader", "section_header", "Chapitre 2", doc, 300)

    elements = _section_espacee(g, doc, ss111, nb=_NB_ENFANTS_COURTE, depart=3, prefixe="da")
    _section_espacee(g, doc, ss112, nb=_NB_ENFANTS_COURTE, depart=51, prefixe="db")
    _section_espacee(g, doc, ch2, nb=_NB_ENFANTS_COURTE, depart=301, prefixe="dc")

    vids = {
        "doc": doc, "ch1": ch1, "s11": s11,
        "ss111": ss111, "ss112": ss112, "ch2": ch2,
    }
    return g, elements, vids


class TestLeGrapheSImbrique:
    """Les propriétés que seul un graphe à en-têtes imbriqués peut éprouver.

    Le code livré était JUSTE sur ces points — ces gardes ne corrigent aucun
    défaut. Ils ferment un trou de COUVERTURE : sans eux, deux régressions
    parmi les plus probables du module passaient en `rc=0`, dont celle qui
    remet dans le code une prémisse qu'un commit venait d'en retirer.
    """

    def test_la_voisine_est_cherchee_sous_le_parent_reel_et_non_sous_le_document(
        self, monkeypatch: pytest.MonkeyPatch, graphe_imbrique: tuple
    ) -> None:
        """La prémisse morte, gardée.

        « Les en-têtes sont tous enfants directs du Document » était la prémisse
        la plus fausse qu'ait portée ce module. Elle a été retirée de six sites
        de commentaire ; rien n'empêchait de la remettre dans le CODE.
        """
        g, elements, vids = graphe_imbrique
        _branche(monkeypatch, g)

        # — le cas est-il atteint ? la section de l'ancre doit avoir pour parent
        #   un SectionHeader, et non le Document.
        parent_de_la_section, rang = g.parent[vids["ss111"]]
        assert parent_de_la_section == vids["s11"]
        assert g.noeuds[parent_de_la_section]["tag"] == "SectionHeader", (
            "la fixture n'imbrique pas : le garde serait décoratif"
        )
        # — et les deux lectures doivent DIVERGER, sinon rien n'est éprouvé.
        sous_le_parent = [c for sq, c in g.enfants[vids["s11"]] if sq > rang]
        sous_le_document = [c for sq, c in g.enfants[vids["doc"]] if sq > rang]
        assert sous_le_parent != sous_le_document

        contexte = reconstruct_section(elements[1])

        assert contexte.after_title == "Sous-section 1.1.2", (
            "la voisine d'après est cherchée sous le Document : la prémisse "
            "morte est de retour dans le code"
        )
        # Sous le parent réel, aucun frère en-tête ne précède le rang 2 — là où
        # le Document en offrirait un (Chapitre 1, rang 0).
        assert contexte.before == []
        assert contexte.before_title == ""

    def test_le_fil_d_ariane_traverse_les_quatre_niveaux(
        self, monkeypatch: pytest.MonkeyPatch, graphe_imbrique: tuple
    ) -> None:
        """`_MAX_DEPTH` doit porter jusqu'au `Document`, gardé.

        Le §1.2 du registre de pilotage : « les citations perdaient le nom du
        document ». La cause était une remontée qui s'arrêtait trop tôt. Une
        constante trop basse le réintroduit, et sur un graphe PLAT rien ne le
        voit — deux sauts suffisent quand tout en-tête pend du Document.
        """
        g, elements, _ = graphe_imbrique
        _branche(monkeypatch, g)

        contexte = reconstruct_section(elements[1])

        textes = [b.text for b in contexte.breadcrumbs]
        assert textes == [
            "Livre.pdf", "Chapitre 1", "Section 1.1", "Sous-section 1.1.1",
        ], "le fil d'Ariane ne traverse pas l'imbrication entière"
        assert contexte.filename == "Livre.pdf", (
            "le nom du document est reperdu : le défaut du §1.2 est de retour"
        )
        assert contexte.collection == "Ouvrage"


# ─── Le montage voit-il encore passer une mutation ? ──────────────────────────


class TestLeGrapheFacticeVoitLesFiltres:
    """Sans ces tests, tous les gardes de ce fichier pourraient être verts parce
    que le bouchon ignore ce que la requête demande, et non parce que le code
    est juste.

    Les trois derniers gardent la RÉPARATION elle-même : un bouchon qui se
    remettrait à trier ses enfants, ou qui redeviendrait aveugle à un
    encadrement écrit en aval d'un tube, rendrait décoratifs tous les autres
    gardes du fichier — silencieusement, et sans qu'une ligne rougisse.
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

    def test_le_bouchon_ne_rend_pas_ses_enfants_tries(self) -> None:
        """Le garde de la réparation de T1, et la contrepartie du précédent.

        NebulaGraph ne trie pas sans `ORDER BY`. Si le bouchon triait — ce que
        faisait la première version de ce fichier, en triant à l'insertion —
        alors retirer le `| ORDER BY $-.seq ASC` de `_get_children` ne
        changerait rien à ce qu'il rend, et les trois gardes de
        `TestLaFenetreEstPositionnelle` seraient verts des deux côtés du défaut.

        Le tri à l'insertion est la forme la plus facile à réintroduire : elle
        rend le bouchon « plus réaliste » en apparence.
        """
        g = GrapheFactice()
        doc = g.document("doc_x", "x.pdf")
        _section_espacee(g, doc, doc, nb=_NB_ENFANTS, depart=0)

        brut = g.execute('GO FROM "doc_x" OVER PARENT_OF YIELD dst(edge) AS child_id;')
        seqs = [r["seq"] for r in brut]

        assert len(seqs) == _NB_ENFANTS, "le cas n'est pas atteint : pas assez d'enfants"
        assert seqs != sorted(seqs), (
            "le bouchon rend ses enfants triés : il FABRIQUE la précondition "
            "que ce fichier doit éprouver"
        )
        # …et il n'est pas non plus simplement inversé : sinon une mutation
        # `ASC → DESC` se confondrait avec l'ordre naturel du bouchon.
        assert seqs != sorted(seqs, reverse=True)
        # L'ORDER BY, lui, trie pour de vrai — sans quoi l'assertion ci-dessus
        # serait satisfaite par un bouchon qui ne trie JAMAIS rien.
        trie = g.execute(
            'GO FROM "doc_x" OVER PARENT_OF '
            "YIELD dst(edge) AS child_id, properties(edge).sequence AS seq "
            "| ORDER BY $-.seq ASC;"
        )
        assert [r["seq"] for r in trie] == sorted(seqs)

    def test_un_encadrement_en_aval_d_un_tube_est_vu(self) -> None:
        """Le garde de la réparation de T2.

        `| YIELD … WHERE $-.seq >= …` est du nGQL aussi légitime que
        `WHERE properties(edge).sequence >= …`, et contre le graphe en service
        les deux formes rendent le même ensemble de lignes. Le bouchon ne
        reconnaissait que la seconde : la première recevait donc TOUTES les
        lignes, la fenêtre paraissait juste, et la mutation passait en `rc=0`.

        LE CHIFFRE QUI SE TROUVAIT ICI — « 40 parents sur 40 testés » — N'AVAIT
        AUCUN SITE : ni dans `documentation/`, ni dans aucun instrument.
        `mesuré` le 4 septembre 2026, il n'était donc pas rejouable, ce que le
        docstring de `scripts/mesurer_le_graphe.py` interdit en toutes lettres —
        « une page qui les affirme sans laisser de quoi les rejouer devient
        fausse en silence ». Il est remplacé par une mesure qui en a un :
        `rejoué` le 4 septembre 2026 par cet instrument, sur 80 parents à treize
        enfants ou plus, **80 sur 80** — et l'accord vaut aussi pour l'écriture
        `IN` et pour la forme arithmétique, 80 sur 80 chacune. Le site publié
        est `documentation/stores.md`, section « Ce que le bouchon modélise ».
        """
        g = GrapheFactice()
        doc = g.document("doc_x", "x.pdf")
        _section_espacee(g, doc, doc, nb=_NB_ENFANTS, depart=0)

        encadre = g.execute(
            'GO FROM "doc_x" OVER PARENT_OF '
            "YIELD dst(edge) AS child_id, properties(edge).sequence AS seq "
            "| ORDER BY $-.seq ASC "
            "| YIELD $-.child_id AS child_id, $-.seq AS seq "
            "WHERE $-.seq >= 64 AND $-.seq <= 76;"
        )

        # Même encadrement que `test_un_encadrement_de_sequence_retire_bien_des
        # _lignes`, écrit en aval d'un tube : il doit MORDRE pareil.
        assert len(encadre) == 1
        assert encadre[0]["seq"] == _RANG_ANCRE * _ECART

    def test_un_encadrement_aux_operandes_echangees_est_vu(self) -> None:
        """`64 <= properties(edge).sequence` est le même encadrement retourné.

        Troisième écriture du même filtre. La borne de ce que le bouchon
        ÉVALUE est donc : la `sequence` de l'arête, ou une colonne d'amont qui
        la porte, comparée à un littéral entier, dans les deux ordres
        d'opérandes, en conjonction.

        LA PHRASE QUI SE TROUVAIT ICI ÉTAIT FAUSSE, et sa moitié `IN` l'était de
        façon mesurable : elle affirmait que le bouchon ne reconnaissait « ni
        une comparaison entre deux colonnes, ni un `IN` sur une liste — aucune
        des deux n'écrit une fenêtre de lecture ». Un `IN` sur une liste écrit
        exactement une fenêtre de lecture : `mesuré` en lecture seule contre
        NebulaGraph en service le 4 septembre 2026, il rend l'ensemble IDENTIQUE
        à l'encadrement classique, avec la même perte — 12 éléments sur 13.
        Une énumération close ne se rouvre pas, et celle-ci autorisait à croire
        gardé ce qui ne l'était pas.

        Ce que le bouchon ne sait pas évaluer, il ne l'ignore plus : il LÈVE.
        La borne ci-dessus n'est donc plus une promesse d'exhaustivité, c'est la
        description du seul cas qui passe — et son complément est gardé par
        `TestLeBouchonLeveSurCeQuIlNeSaitPasEvaluer`.
        """
        g = GrapheFactice()
        doc = g.document("doc_x", "x.pdf")
        _section_espacee(g, doc, doc, nb=_NB_ENFANTS, depart=0)

        encadre = g.execute(
            'GO FROM "doc_x" OVER PARENT_OF '
            "WHERE 64 <= properties(edge).sequence "
            "AND 76 >= properties(edge).sequence "
            "YIELD dst(edge) AS child_id;"
        )

        assert len(encadre) == 1
        assert encadre[0]["seq"] == _RANG_ANCRE * _ECART


# ─── La borne du bouchon, gardée plutôt qu'affirmée ──────────────────────────

# Les écritures d'un encadrement de `sequence` que le bouchon ne sait PAS
# évaluer. Elles sont ici parce qu'une borne affirmée en prose ne rougit jamais,
# et que celle qui se trouvait dans ce fichier était fausse.
#
# Chaque entrée est (nom, requête). Les trois premières sont mesurées contre
# NebulaGraph en service — voir `ClauseNonEvaluableError` — donc ce ne sont pas des
# formes de laboratoire : nGQL les accepte, et deux d'entre elles amputent
# exactement comme l'encadrement classique.
_ECRITURES_NON_EVALUABLES = [
    (
        "IN sur une liste",
        'GO FROM "doc_x" OVER PARENT_OF '
        "WHERE properties(edge).sequence IN [64, 66, 68, 70, 72, 74, 76] "
        "YIELD dst(edge) AS child_id;",
    ),
    (
        "forme arithmétique",
        'GO FROM "doc_x" OVER PARENT_OF '
        "WHERE properties(edge).sequence - 64 >= 0 "
        "AND 76 - properties(edge).sequence >= 0 "
        "YIELD dst(edge) AS child_id;",
    ),
    (
        "alias de la liste YIELD, filtré dans le WHERE du même YIELD",
        'GO FROM "doc_x" OVER PARENT_OF '
        "YIELD dst(edge) AS child_id, properties(edge).sequence AS seq "
        "| YIELD $-.child_id AS child_id, $-.seq AS rang "
        "WHERE $-.rang >= 64 AND $-.rang <= 76;",
    ),
    (
        "comparaison entre deux colonnes",
        'GO FROM "doc_x" OVER PARENT_OF '
        "WHERE properties(edge).sequence <= properties($$).page_no "
        "YIELD dst(edge) AS child_id;",
    ),
    (
        "disjonction",
        'GO FROM "doc_x" OVER PARENT_OF '
        "WHERE properties(edge).sequence >= 64 OR properties(edge).sequence <= 76 "
        "YIELD dst(edge) AS child_id;",
    ),
    (
        "négation",
        'GO FROM "doc_x" OVER PARENT_OF '
        "WHERE NOT properties(edge).sequence < 64 "
        "YIELD dst(edge) AS child_id;",
    ),
    (
        "borne non entière",
        'GO FROM "doc_x" OVER PARENT_OF '
        "WHERE properties(edge).sequence >= 64.0 "
        "YIELD dst(edge) AS child_id;",
    ),
    (
        "ORDER BY sur une colonne qui ne porte pas la sequence",
        'GO FROM "doc_x" OVER PARENT_OF '
        "YIELD dst(edge) AS child_id, properties(edge).sequence AS seq "
        "| ORDER BY $-.child_id ASC;",
    ),
]


class TestLeBouchonLeveSurCeQuIlNeSaitPasEvaluer:
    """Le garde de la BORNE elle-même, et il n'existait pas.

    La règle du chantier veut que toute phrase du genre « aucun », « les deux
    seules », « il n'y a plus » soit BORNÉE ou GARDÉE PAR UN TEST. Celle que ce
    fichier et `documentation/stores.md` portaient n'était ni l'une ni l'autre,
    et elle était fausse — un `IN` sur une liste écrit bel et bien une fenêtre
    de lecture, et nGQL la sert avec la même perte que l'écriture classique.

    Ces gardes remplacent la phrase par une mesure. Ils ne prétendent pas
    énumérer la classe des écritures que le bouchon ne sait pas lire — c'est
    justement ce qui ne se peut pas — ils éprouvent que son COMPORTEMENT sur
    cette classe est de lever, et non de rendre toutes les lignes.
    """

    @staticmethod
    def _graphe() -> GrapheFactice:
        g = GrapheFactice()
        doc = g.document("doc_x", "x.pdf")
        _section_espacee(g, doc, doc, nb=_NB_ENFANTS, depart=0)
        return g

    @pytest.mark.parametrize(("nom", "requete"), _ECRITURES_NON_EVALUABLES)
    def test_le_bouchon_leve(self, nom: str, requete: str) -> None:
        """Lever, et non rendre toutes les lignes.

        C'est toute la différence entre un garde bruyant et un garde décoratif.
        L'assertion de contre-épreuve est dans le même test : sans elle, un
        bouchon qui lèverait sur TOUT — y compris sur les requêtes justes — la
        satisferait aussi, et ce n'est pas la propriété gardée.
        """
        g = self._graphe()

        with pytest.raises(ClauseNonEvaluableError):
            g.execute(requete)

        # — contre-épreuve : le même bouchon sert sans broncher l'écriture qu'il
        #   sait lire. Sans elle, « il lève » ne dirait rien.
        assert len(g.execute('GO FROM "doc_x" OVER PARENT_OF '
                             "YIELD dst(edge) AS child_id;")) == _NB_ENFANTS

    @pytest.mark.parametrize(("nom", "requete"), _ECRITURES_NON_EVALUABLES)
    def test_le_garde_structurel_leve_sur_les_memes(self, nom: str, requete: str) -> None:
        """Une cécité, deux gardes — c'est le critère qui a fait coter bloquant.

        `filtre_sur_sequence` sert le garde structurel de la réserve 1, et il
        partage son point de décision avec le bouchon. Le partage n'est pas le
        défaut : le défaut était que ce point rendait « rien à filtrer » sur ce
        qu'il ne comprenait pas, donc `False`, donc un garde vide qui se lit
        comme un garde satisfait.
        """
        with pytest.raises(ClauseNonEvaluableError):
            GrapheFactice.filtre_sur_sequence(requete)


class TestLeBouchonNeLevePasSurLeCodeSain:
    """Le piège, et il est réel : le code JUSTE nomme `sequence` sans la comparer.

    `_get_children` projette `properties(edge).sequence AS seq` dans sa liste
    `YIELD`. Un garde-fou naïf — « lever si `sequence` apparaît et qu'aucun
    motif ne matche » — rendrait donc la suite rouge sur le code sain, et la
    correction se serait payée d'un faux rouge. Distinguer une clause de
    FILTRAGE d'une PROJECTION est le cœur du travail, et c'est ce que ces deux
    gardes éprouvent.

    Sans eux, la borne du bouchon pourrait se resserrer jusqu'à l'absurde sans
    qu'une ligne rougisse : ils sont la contrepartie de
    `TestLeBouchonLeveSurCeQuIlNeSaitPasEvaluer`, et aucun des deux ne vaut
    seul.
    """

    def test_la_requete_reelle_de_get_children_ne_leve_pas(
        self, monkeypatch: pytest.MonkeyPatch, graphe_non_contigu: tuple
    ) -> None:
        """La requête de production, telle quelle, à l'octet près.

        Elle n'est pas recopiée ici : elle est PRISE au module de production en
        le pilotant. Une copie se désynchroniserait du site réel sans un rouge,
        et ce fichier a déjà payé cette leçon.
        """
        g, _, section = graphe_non_contigu
        _branche(monkeypatch, g)

        rows = graph_context._get_children(section)

        assert len(rows) == _NB_ENFANTS
        # — le cas est-il atteint ? la requête doit NOMMER `sequence`, sans quoi
        #   ce garde serait vert quel que soit le garde-fou du bouchon.
        emises = [q for q in g.requetes if "PARENT_OF" in q]
        assert emises, "aucune requête émise : le garde serait décoratif"
        assert any("properties(edge).sequence" in q for q in emises), (
            "la requête de production ne nomme plus `sequence` : le piège que "
            "ce garde surveille n'existe plus sous cette forme"
        )
        # — et elle ne la COMPARE pas : c'est une projection.
        for requete in emises:
            assert GrapheFactice.filtre_sur_sequence(requete) is False

    def test_un_predicat_etranger_a_sequence_est_ignore_et_non_leve(self) -> None:
        """La BORNE de la borne, dite plutôt que supposée.

        Le bouchon ne modélise que `sequence`. Une clause qui ne la touche pas
        n'est ni évaluée ni refusée — elle est hors sujet. L'écrire ici est ce
        qui empêche la prochaine lecture de croire le bouchon fail-closed sur
        TOUT le nGQL, ce qu'il n'est pas et n'a pas à être.
        """
        g = GrapheFactice()
        doc = g.document("doc_x", "x.pdf")
        _section_espacee(g, doc, doc, nb=_NB_ENFANTS, depart=0)

        lignes = g.execute(
            'GO FROM "doc_x" OVER PARENT_OF '
            'WHERE properties($$).minio_url != "" '
            "YIELD dst(edge) AS child_id;"
        )

        assert len(lignes) == _NB_ENFANTS
        assert GrapheFactice.filtre_sur_sequence(
            'GO FROM "doc_x" OVER PARENT_OF '
            'WHERE properties($$).minio_url != "" '
            "YIELD dst(edge) AS child_id;"
        ) is False



# ─── Réserve 2 et 3 : la fenêtre se découpe sur des POSITIONS ────────────────


class TestLaCompositionADeuxMaillonsEtNonUn:
    """Le maillon du milieu : « tous les enfants, ORDONNÉS, puis par position ».

    La composition que garde ce fichier a TROIS maillons, et le fichier n'en
    gardait que deux — aller chercher tous les enfants, et découper par
    position. Que la liste soit ORDONNÉE entre les deux n'était éprouvé par
    rien : `mesuré` le 3 septembre 2026, retirer le `| ORDER BY $-.seq ASC` de
    `_get_children` laissait les 496 tests verts.

    La conséquence en service n'est pas une amputation, c'est un contexte FAUX :
    `_window_around` découpe par position, donc treize frères ARBITRAIRES
    seraient présentés au modèle comme les voisins de lecture de l'ancre.
    `mesuré` sur le graphe en service, 80 des 334 parents à treize enfants ou
    plus testés : 80 sur 80 rendent leurs enfants non triés sans `ORDER BY`, 80
    sur 80 triés avec. Site canonique : **§4.14** de
    `documentation/axes_amelioration.md` — et non le §4.6, où le renvoi
    précédent envoyait chercher des chiffres qui n'y sont pas. `rejoué` le
    4 septembre 2026 par `scripts/mesurer_le_graphe.py`, qui les imprime
    désormais.

    C'est la mutation la plus probable des trois, et c'est pourquoi elle a son
    garde nommé plutôt que le seul effet de bord des trois tests de fenêtre : un
    développeur retire un `ORDER BY` jugé redondant — « les données arrivent
    triées » — bien plus volontiers qu'il ne réécrit une requête.
    """

    def test_les_enfants_arrivent_ordonnes_avant_tout_decoupage(
        self, monkeypatch: pytest.MonkeyPatch, graphe_non_contigu: tuple
    ) -> None:
        g, _, section = graphe_non_contigu
        _branche(monkeypatch, g)

        # — le cas est-il atteint ? le bouchon doit rendre du DÉSORDRE en amont,
        #   sinon ce garde serait vert quoi que fasse la requête.
        brut = [s for s, _ in g._portee(f'GO FROM "{section}" OVER PARENT_OF')]
        assert len(brut) == _NB_ENFANTS
        assert brut != sorted(brut), "le bouchon ne présente aucun désordre à trier"

        rows = graph_context._get_children(section)

        seqs = [r["seq"] for r in rows]
        assert len(seqs) == _NB_ENFANTS, "la requête a perdu des enfants"
        assert seqs == sorted(seqs), (
            "`_get_children` rend les enfants dans l'ordre du graphe et non "
            "dans l'ordre de lecture : le découpage positionnel qui suit "
            "fabriquerait un contexte faux"
        )


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
            f"| ORDER BY $-.seq ASC | LIMIT {_LIMITE_DE_SONDE};"
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

        Ce garde passe par `filtre_sur_sequence`, c'est-à-dire par le MÊME point
        de décision que le bouchon. C'était déjà le cas — il empruntait
        l'expression `_FILTRE` — et c'est précisément ce qui rendait une cécité
        capable de défaire deux gardes d'un coup. La différence est que ce point
        de décision LÈVE désormais au lieu de rendre « rien à filtrer » : le
        partage reste, la cécité silencieuse a disparu.
        """
        g, elements, _ = graphe_non_contigu
        _branche(monkeypatch, g)

        reconstruct_section(elements[_RANG_ANCRE])

        comparaisons = [q for q in g.requetes if GrapheFactice.filtre_sur_sequence(q)]
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
