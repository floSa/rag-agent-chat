"""Mesure, en LECTURE SEULE, ce que l'agent doit savoir du graphe pour le lire.

Cet artefact existe parce que les chiffres des trois réserves de lecture de
`sequence` sont un ÉTAT DE STORE : ils périment à chaque réingestion. Une page
qui les affirme sans laisser de quoi les rejouer devient fausse en silence.

    docker exec -i rag-agent-api python - < scripts/mesurer_le_graphe.py

`graphd` n'expose aucun port sur ce poste (`docker port graphd` rend une sortie
vide, `mesuré` le 3 septembre 2026) : la commande passe donc par un conteneur
déjà branché au réseau `rag_network`, et lit sa configuration dans
l'environnement de l'agent. Aucune écriture, aucun `INSERT`, aucun `DROP` — le
script ne fait que des `MATCH`.

Ce qu'il rend, et où ça vit :

- les trois réserves de `sequence` → `documentation/stores.md` ;
- la forme du graphe (profondeur, imbrication des titres) → §4.6 de
  `documentation/axes_amelioration.md` ;
- **les trois définitions de « section voisine » — (A), (B), (C) — confrontées
  en en-têtes servis ET en éléments réellement servis**, plus le sous-choix de
  (C) éprouvé contre l'ordre de lecture → même §4.6. C'EST LA RÉSERVE 1 DE CE
  §4.6 QUI SE FERME ICI : ses chiffres y étaient `mesuré` **et sans site
  rejouable**, les sondes du pilote ayant vécu dans un répertoire temporaire, ce
  que le paragraphe ci-dessus interdit précisément ;
- ce qu'un encadrement `sequence ∈ [s−k, s+k]` amputerait → `stores.md` ;
- les écritures d'un même encadrement, et l'ordre rendu avec et sans
  `ORDER BY` → `stores.md`, section « Ce que le bouchon modélise ».

LA DERNIÈRE SECTION A ÉTÉ AJOUTÉE PARCE QUE TROIS CHIFFRES PUBLIÉS N'AVAIENT
PAS DE SITE REJOUABLE. Les `334` parents à treize enfants ou plus, le `80 sur
80` de l'ordre non trié, et l'accord entre deux écritures d'un même encadrement
étaient affirmés dans des docstrings et dans le registre, et aucun instrument ne
les imprimait — le dernier n'était même publié nulle part. C'est exactement ce
que le paragraphe ci-dessus interdit ; il valait aussi pour ce que ce fichier ne
mesurait pas encore.

Le garde qui rend le découpage positionnel non négociable est ailleurs, et il
ne dépend pas de ce script : `tests/unit/test_lecture_sequence.py`.
"""

from __future__ import annotations

import collections
import os
import sys
from collections.abc import Callable
from typing import Any

# Fenêtre par défaut de `settings.py`. Le script la lit dans l'environnement
# quand il tourne dans le conteneur de l'agent, qui la porte.
_AVANT = int(os.environ.get("CONTEXT_WINDOW_BEFORE", "6"))
_APRES = int(os.environ.get("CONTEXT_WINDOW_AFTER", "6"))
# Nebula rend ses résultats par pages ; au-delà, il tronque sans le dire.
_PAGE = 5000
# Un parent doit avoir au moins deux enfants pour que la contiguïté de leurs
# `sequence` soit une question : une suite d'un seul élément est contiguë par
# définition. C'est la population sur laquelle le taux de non-contiguïté se
# mesure, et la nommer évite de la reconfondre avec « tous les parents ».
_MIN_ENFANTS_ELIGIBLES = 2
# Nombre de parents confrontes par `rapporter_les_ecritures`. Borne parce que
# chaque parent coute six aller-retours nGQL ; c'est la meme taille que celle
# des chiffres publies au §4.14 de `documentation/axes_amelioration.md`, ce qui
# rend les deux mesures directement comparables.
_ECHANTILLON = 80


def _pool() -> Any:
    """Ouvre une session NebulaGraph depuis la configuration de l'agent."""
    from nebula3.Config import SessionPoolConfig
    from nebula3.gclient.net.SessionPool import SessionPool

    pool = SessionPool(
        os.environ["NEBULA_USER"],
        os.environ["NEBULA_PASSWORD"],
        os.environ["NEBULA_SPACE"],
        [(os.environ["NEBULA_HOST"], int(os.environ["NEBULA_PORT"]))],
    )
    if not pool.init(SessionPoolConfig()):
        raise SystemExit("NebulaGraph injoignable")
    return pool


def _run(pool: Any, nql: str) -> Any:
    resultat = pool.execute(nql)
    if not resultat.is_succeeded():
        raise SystemExit(f"nGQL échoué : {nql[:120]} — {resultat.error_msg()}")
    return resultat


def _pages(pool: Any, gabarit: str, colonnes: int) -> list[tuple[Any, ...]]:
    """Parcourt une requête paginée jusqu'à épuisement."""
    lignes: list[tuple[Any, ...]] = []
    decalage = 0
    while True:
        resultat = _run(pool, f"{gabarit} SKIP {decalage} LIMIT {_PAGE};")
        avant = len(lignes)
        for i in range(resultat.row_size()):
            valeurs = resultat.row_values(i)
            lignes.append(tuple(valeurs[j] for j in range(colonnes)))
        if len(lignes) - avant < _PAGE:
            return lignes
        decalage += _PAGE


def _entier(valeur: Any) -> int | None:
    return None if valeur.is_null() or valeur.is_empty() else int(valeur.as_int())


def lire_le_graphe(pool: Any) -> tuple[list[tuple[str, str, int | None]], dict[str, str]]:
    """Rend (arêtes PARENT_OF, tag de chaque nœud)."""
    aretes = [
        (p.as_string(), c.as_string(), _entier(s))
        for p, c, s in _pages(
            pool,
            "MATCH (p)-[e:PARENT_OF]->(c) RETURN id(p) AS p, id(c) AS c, e.sequence AS s",
            colonnes=3,
        )
    ]
    resultat = _run(pool, "SHOW TAGS;")
    noms = [resultat.row_values(i)[0].as_string() for i in range(resultat.row_size())]
    tags: dict[str, str] = {}
    for nom in noms:
        for (vid,) in _pages(pool, f"MATCH (v:`{nom}`) RETURN id(v) AS i", colonnes=1):
            tags[vid.as_string()] = nom
    return aretes, tags


def _index(
    aretes: list[tuple[str, str, int | None]],
) -> tuple[dict[str, list[tuple[int, str]]], dict[str, str]]:
    enfants: dict[str, list[tuple[int, str]]] = collections.defaultdict(list)
    parent: dict[str, str] = {}
    for p, c, s in aretes:
        if s is not None:
            enfants[p].append((s, c))
        parent[c] = p
    for cle in enfants:
        enfants[cle].sort()
    return enfants, parent


def _hauteur(noeud: str, parent: dict[str, str], plafond: int = 60) -> int:
    sauts = 0
    courant = noeud
    while courant in parent and sauts < plafond:
        courant = parent[courant]
        sauts += 1
    return sauts


def _taille_du_sous_arbre(
    noeud: str, enfants: dict[str, list[tuple[int, str]]], cache: dict[str, int]
) -> int:
    if noeud not in cache:
        cache[noeud] = 1 + sum(
            _taille_du_sous_arbre(c, enfants, cache) for _, c in enfants.get(noeud, [])
        )
    return cache[noeud]


def rapporter(aretes: list[tuple[str, str, int | None]], tags: dict[str, str]) -> None:
    """Écrit sur la sortie standard tout ce que les pages citent."""
    enfants, parent = _index(aretes)
    entetes = [v for v, t in tags.items() if t == "SectionHeader"]

    print(f"arêtes PARENT_OF            : {len(aretes)}")
    print(f"dont sequence nulle         : {sum(1 for _, _, s in aretes if s is None)}")
    print(f"documents                   : {sum(1 for t in tags.values() if t == 'Document')}")
    print(f"parents distincts           : {len(enfants)}")

    print("\n── Réserve 1 : `sequence` repart à 0 dans chaque document ──")
    racines = [v for v in tags if v not in parent]
    bornes: dict[str, list[int]] = {}
    for p, _, s in aretes:
        if s is None:
            continue
        courant = p
        while courant in parent:
            courant = parent[courant]
        bornes.setdefault(courant, [s, s])
        bornes[courant][0] = min(bornes[courant][0], s)
        bornes[courant][1] = max(bornes[courant][1], s)
    print(f"racines                     : {len(racines)}")
    print(f"documents dont min(seq) = 0 : {sum(1 for b in bornes.values() if b[0] == 0)}")
    print(f"valeurs de min rencontrées  : {sorted({b[0] for b in bornes.values()})}")
    recouvrements = sum(
        1
        for a in bornes
        for b in bornes
        if a < b and bornes[a][0] <= bornes[b][1] and bornes[b][0] <= bornes[a][1]
    )
    print(f"paires de documents qui se recouvrent : {recouvrements}")

    print("\n── Réserve 2 : non-contiguïté sous un parent ──")
    non_contigus = [
        p
        for p, fils in enfants.items()
        if len(fils) >= _MIN_ENFANTS_ELIGIBLES
        and [s for s, _ in fils] != list(range(fils[0][0], fils[0][0] + len(fils)))
    ]
    # La POPULATION ÉLIGIBLE, et c'est une correction. La version précédente
    # imprimait « 167 sur 763 », où 763 est le nombre de parents TOUS ENFANTS
    # CONFONDUS : elle rapportait donc un numérateur compté sur les parents à
    # deux enfants ou plus à un dénominateur compté sur tous les parents. Un
    # parent à un seul enfant ne PEUT PAS être non contigu — la contiguïté d'une
    # suite d'un élément est vraie par définition —, si bien que les 71 parents
    # à un enfant unique ne faisaient que diluer le taux.
    eligibles = sum(1 for f in enfants.values() if len(f) >= _MIN_ENFANTS_ELIGIBLES)
    print(f"parents (tous, y compris à un enfant) : {len(enfants)}")
    print(f"parents éligibles (>= 2 enfants)      : {eligibles}")
    print(f"parents NON contigus                  : {len(non_contigus)} sur {eligibles}")
    cache: dict[str, int] = {}
    concordent = discordent = 0
    for fils in enfants.values():
        for (sa, ca), (sb, _) in zip(fils, fils[1:], strict=False):
            if sb - sa == _taille_du_sous_arbre(ca, enfants, cache):
                concordent += 1
            else:
                discordent += 1
    print(f"couples de frères consécutifs : {concordent + discordent}")
    print(f"  écart == taille du sous-arbre du précédent : {concordent}")
    print(f"  écart != taille du sous-arbre              : {discordent}")

    print("\n── Réserve 3 : plus grand écart entre deux enfants d'un même parent ──")
    pire = (0, "", 0, 0)
    for p, fils in enfants.items():
        for (sa, _), (sb, _b) in zip(fils, fils[1:], strict=False):
            if sb - sa > pire[0]:
                pire = (sb - sa, p, sa, sb)
    print(f"écart max                   : {pire[0]} ({pire[0] - 1} valeurs intercalaires)")
    print(f"  parent                    : {pire[1]}")
    print(f"  entre sequence {pire[2]} et {pire[3]}")

    print(f"\n── Ce qu'un encadrement [s−{_AVANT}, s+{_APRES}] amputerait ──")
    ampute = 0
    perte_max = 0
    parents_touches = set()
    for p, fils in enfants.items():
        for rang, (s, _c) in enumerate(fils):
            positionnel = fils[max(0, rang - _AVANT) : rang + _APRES + 1]
            encadre = [x for x in fils if s - _AVANT <= x[0] <= s + _APRES]
            if len(encadre) < len(positionnel):
                ampute += 1
                parents_touches.add(p)
                perte_max = max(perte_max, len(positionnel) - len(encadre))
    print(f"ancres possibles            : {len(aretes)}")
    print(f"ancres amputées             : {ampute} ({100 * ampute / len(aretes):.1f} %)")
    print(f"parents touchés             : {len(parents_touches)}")
    print(f"perte max sur une ancre     : {perte_max} éléments sur {_AVANT + _APRES + 1}")

    print("\n── Forme du graphe : imbrication des titres (§4.6) ──")
    par_document = sum(1 for v in entetes if tags.get(parent.get(v, "")) == "Document")
    par_entete = sum(1 for v in entetes if tags.get(parent.get(v, "")) == "SectionHeader")
    print(f"SectionHeader               : {len(entetes)}")
    print(f"  parent = Document         : {par_document}")
    part = 100 * par_entete / len(entetes) if entetes else 0.0
    print(f"  parent = SectionHeader    : {par_entete} ({part:.1f} %)")

    def profondeur_en_titres(vid: str) -> int:
        niveau = 0
        courant = vid
        while courant in parent and tags.get(parent[courant]) == "SectionHeader":
            courant = parent[courant]
            niveau += 1
        return niveau

    repartition = collections.Counter(profondeur_en_titres(v) for v in entetes)
    print(f"  profondeur en titres      : {dict(sorted(repartition.items()))}")
    print(f"  sauts max jusqu'à la racine, tous nœuds : {max(_hauteur(v, parent) for v in tags)}")

    # Le rang est compté 1-BASÉ : le frère immédiatement adjacent est au rang 1,
    # pas au rang 0. La convention est nommée ici parce qu'elle ne l'était nulle
    # part, et que le chiffre est PUBLIÉ — « le rang du premier frère en-tête
    # vaut 1 au pire cas », §4.6 de `documentation/axes_amelioration.md`. La
    # version précédente imprimait le même fait en 0-basé, et les deux écritures
    # se lisaient donc comme deux mesures différentes du même graphe.
    #
    # 1-basé est la convention retenue parce que c'est celle qui rend le chiffre
    # DIRECTEMENT comparable à `_SIBLING_CANDIDATES` : « rang max = 1 » et « un
    # seul candidat suffit » sont alors la même phrase.
    print("\n── _SIBLING_CANDIDATES : rang 1-basé du premier frère en-tête ──")
    sans_frere: dict[str, set[str]] = {}
    for direction in ("before", "after"):
        rang_max = 0
        sans: set[str] = set()
        for vid in entetes:
            fils = enfants[parent[vid]]
            propre = next(s for s, c in fils if c == vid)
            if direction == "before":
                candidats = [c for s, c in sorted(fils, reverse=True) if s < propre]
            else:
                candidats = [c for s, c in fils if s > propre]
            # Nom distinct de la variable de boucle `rang` employée plus haut
            # dans cette fonction : la réutiliser rendait `mypy scripts/`
            # rouge, `int | None` étant affecté à un `int` déjà lié.
            rang_trouve = next(
                (
                    i
                    for i, c in enumerate(candidats, start=1)
                    if tags.get(c) == "SectionHeader"
                ),
                None,
            )
            if rang_trouve is None:
                sans.add(vid)
            else:
                rang_max = max(rang_max, rang_trouve)
        print(
            f"  {direction:7s} : rang max (1-basé) = {rang_max}, "
            f"sans frère en-tête = {len(sans)}"
        )
        sans_frere[direction] = sans
    avant, apres = sans_frere["before"], sans_frere["after"]
    print(f"  ensembles identiques ?    : {avant == apres}")
    print(f"  intersection / union      : {len(avant & apres)} / {len(avant | apres)}")


# ── (A), (B), (C) : les trois définitions de « section voisine », confrontées ──
#
# CETTE SECTION EXISTE PARCE QUE LA MESURE QUI A TRANCHÉ LA DÉFINITION N'AVAIT
# PAS D'INSTRUMENT. Le §4.6 de `documentation/axes_amelioration.md` portait ses
# chiffres comme `mesuré` **et sans site rejouable** — les sondes du pilote ont
# vécu dans un répertoire temporaire —, et le docstring en tête de ce fichier
# interdit précisément cela : « une page qui les affirme sans laisser de quoi les
# rejouer devient fausse en silence ». C'est un état de store : il périme à la
# prochaine réingestion.
#
# CE QUI AUTORISE À CROIRE LES CHIFFRES NEUFS : cette section reproduit d'abord
# les quatre chiffres que le §4.6 portait DÉJÀ — 214 sans frère avant, 214 après,
# intersection 47, union 381 — plus les 25 en-têtes premiers sous leur parent.
# Ils sont imprimés par la section `_SIBLING_CANDIDATES` ci-dessus et par
# `_controle_des_chiffres_deja_publies`. Si l'un ne tombe pas, c'est
# l'instrument qu'il faut corriger avant d'y croire.

# Le rang du premier frère en-tête vaut 1 au pire cas, donc la LIMITE de
# `_find_sibling` ne coupe jamais rien — mais la reproduire est le seul moyen de
# le PROUVER plutôt que de le supposer. C'est la valeur de production.
_CANDIDATS_FRERES = 5


def _entetes_et_poids(
    tags: dict[str, str], parent: dict[str, str]
) -> tuple[list[str], dict[str, int], int]:
    """Les en-têtes, et le nombre d'éléments NON-TITRES que chacun sert.

    LA PONDÉRATION EST CE QUI DONNE SON SENS AU CHIFFRE. « 214 en-têtes sans
    frère » et « 4 157 éléments servis sans encadrement » mesurent le même
    défaut ; seul le second dit ce que l'exploitant subit, parce qu'un en-tête
    qui porte 60 paragraphes ne pèse pas comme un en-tête qui en porte 2.
    """
    entetes = [v for v, t in tags.items() if t == "SectionHeader"]
    poids: dict[str, int] = collections.Counter(
        parent[c]
        for c in parent
        if tags.get(parent[c]) == "SectionHeader" and tags.get(c) != "SectionHeader"
    )
    return entetes, poids, sum(poids.values())


def _frere_a(
    entete: str,
    direction: str,
    enfants: dict[str, list[tuple[int, str]]],
    parent: dict[str, str],
    rang: dict[str, int],
    tags: dict[str, str],
) -> str | None:
    """Reproduit `_find_sibling`, **LIMITE COMPRISE** — définition (A).

    La limite est reproduite parce qu'un instrument qui l'ignore mesure une
    fonction que la production n'a pas. Elle ne change rien sur ce graphe, et
    c'est un résultat, pas une hypothèse.
    """
    p = parent.get(entete)
    if p is None:
        return None
    propre = rang[entete]
    fils = enfants[p]
    if direction == "before":
        candidats = [c for s, c in sorted(fils, reverse=True) if s < propre]
    else:
        candidats = [c for s, c in fils if s > propre]
    for candidat in candidats[:_CANDIDATS_FRERES]:
        if tags.get(candidat) == "SectionHeader":
            return candidat
    return None


def _frere_c(
    entete: str,
    direction: str,
    enfants: dict[str, list[tuple[int, str]]],
    parent: dict[str, str],
    rang: dict[str, int],
    tags: dict[str, str],
) -> tuple[str | None, int]:
    """(A) puis la REMONTÉE AUX ONCLES, bornée au document — définition (C).

    Rend (l'oncle trouvé, le nombre de crans supplémentaires). La borne est le
    fait que le parent cesse d'être un `SectionHeader` : au-dessus il y a le
    `Document`, et `sequence` repart à 0 dans le suivant.
    """
    courant, crans = entete, 0
    while True:
        trouve = _frere_a(courant, direction, enfants, parent, rang, tags)
        if trouve is not None:
            return trouve, crans
        p = parent.get(courant)
        if p is None or tags.get(p) != "SectionHeader":
            return None, crans
        courant, crans = p, crans + 1


def _descendant_entete(
    entete: str, enfants: dict[str, list[tuple[int, str]]], tags: dict[str, str], dernier: bool
) -> str:
    """Le dernier (ou le premier) descendant en-tête — le SOUS-CHOIX de (C)."""
    courant = entete
    while True:
        fils = [c for _, c in enfants.get(courant, []) if tags.get(c) == "SectionHeader"]
        if not fils:
            return courant
        courant = fils[-1] if dernier else fils[0]


def _ordre_de_lecture(
    tags: dict[str, str], enfants: dict[str, list[tuple[int, str]]], parent: dict[str, str]
) -> tuple[list[str], dict[str, int], dict[str, int], dict[str, str]]:
    """Le parcours en profondeur par `sequence` — l'ordre où un humain LIT.

    C'est la seule référence contre laquelle « le voisin réel en lecture » peut
    être éprouvé, et c'est ce qui manquait au §4.6 : son sous-choix y était
    `calculé`, déduit de la forme du parcours, jamais confronté au parcours.

    Rend (l'ordre à plat, le rang de chaque nœud, la taille de son sous-arbre,
    le document de chaque nœud).
    """
    racines = sorted(v for v in tags if v not in parent)
    ordre: list[str] = []
    for racine in racines:
        pile = [racine]
        while pile:
            noeud = pile.pop()
            ordre.append(noeud)
            pile.extend(c for _, c in reversed(enfants.get(noeud, [])))
    rang_dfs = {v: i for i, v in enumerate(ordre)}
    taille: dict[str, int] = {}
    for noeud in reversed(ordre):
        taille[noeud] = 1 + sum(taille[c] for _, c in enfants.get(noeud, []))
    document: dict[str, str] = {}
    for noeud in ordre:
        courant = noeud
        while courant in parent:
            courant = parent[courant]
        document[noeud] = courant
    return ordre, rang_dfs, taille, document


def _controle_des_chiffres_deja_publies(
    entetes: list[str],
    enfants: dict[str, list[tuple[int, str]]],
    parent: dict[str, str],
    rang: dict[str, int],
    tags: dict[str, str],
) -> None:
    """Les chiffres que le §4.6 portait DÉJÀ — c'est le contrôle de l'instrument.

    Un instrument qui rend des chiffres neufs sans reproduire les anciens ne
    mesure pas le même graphe que la page qu'il prétend fonder.

    ET UNE COÏNCIDENCE QUI EST NOMMÉE ICI, parce que le §4.6 la juxtapose sans
    la nommer : « 25 en-têtes premiers sous leur parent » et « (C) ne trouve
    jamais rien pour 25 en-têtes en avant » valent tous deux 25, **et ce ne sont
    pas les mêmes 25**. C'est la faute exacte que le lot 2 a corrigée sur les
    « mêmes 214 dans les deux directions » : deux ensembles de même cardinal ne
    sont pas le même ensemble. L'instrument imprime donc l'intersection.
    """
    premiers = {v for v in entetes if enfants[parent[v]][0][1] == v}
    print(f"en-têtes premiers sous leur parent    : {len(premiers)}")
    for direction in ("before", "after"):
        echecs = {
            v
            for v in entetes
            if _frere_c(v, direction, enfants, parent, rang, tags)[0] is None
        }
        print(
            f"  (C) ne trouve rien, {direction:6s}         : {len(echecs)} "
            f"— mêmes en-têtes que « premiers » ? {premiers == echecs} "
            f"(intersection {len(premiers & echecs)})"
        )


def _rapporter_les_definitions(
    entetes: list[str],
    poids: dict[str, int],
    total_elements: int,
    enfants: dict[str, list[tuple[int, str]]],
    parent: dict[str, str],
    rang: dict[str, int],
    tags: dict[str, str],
) -> None:
    """(A) et (C), en en-têtes servis ET en éléments réellement servis."""
    print(f"\néléments non-titres sous un en-tête   : {total_elements}")
    def definition_a(entete: str, direction: str) -> tuple[str | None, int]:
        return _frere_a(entete, direction, enfants, parent, rang, tags), 0

    def definition_c(entete: str, direction: str) -> tuple[str | None, int]:
        return _frere_c(entete, direction, enfants, parent, rang, tags)

    definitions: tuple[tuple[str, Callable[[str, str], tuple[str | None, int]]], ...] = (
        ("(A) frère sous le parent commun", definition_a),
        ("(C) (A) puis remontée aux oncles", definition_c),
    )
    for nom, calcule in definitions:
        for direction in ("before", "after"):
            sans = [v for v in entetes if calcule(v, direction)[0] is None]
            prives = sum(poids.get(v, 0) for v in sans)
            part = 100 * prives / total_elements if total_elements else 0.0
            print(
                f"  {nom:34s} {direction:6s} : servis {len(entetes) - len(sans)}"
                f"/{len(entetes)}, éléments privés d'encadrement {prives} ({part:.1f} %)"
            )

    print("\n  ── le coût de (C), en crans de remontée ──")
    for direction in ("before", "after"):
        distribution: collections.Counter[str] = collections.Counter()
        for entete in entetes:
            trouve, crans = _frere_c(entete, direction, enfants, parent, rang, tags)
            distribution["jamais trouvé" if trouve is None else f"{crans} cran(s)"] += 1
        detail = ", ".join(f"{k} : {n}" for k, n in sorted(distribution.items()))
        print(f"  {direction:6s} : {detail}")

    # Le rang du premier frère en-tête, SÉPARÉMENT au cran 0 et aux crans de la
    # remontée. Le §4.6 publiait « 1 au pire cas » — mesuré pour (A) seulement.
    # La fratrie d'un ONCLE n'est pas celle d'une section : rien n'autorisait à
    # transporter le chiffre, et c'est pourquoi il est refait ici.
    print("\n  ── _SIBLING_CANDIDATES : rang 1-basé, au cran 0 ET aux crans de (C) ──")
    for direction in ("before", "after"):
        rang_max = {0: 0, 1: 0}
        for entete in entetes:
            courant, crans = entete, 0
            while True:
                p = parent.get(courant)
                if p is None:
                    break
                propre_du_cran = rang[courant]
                fils = enfants[p]
                if direction == "before":
                    candidats = [c for s, c in sorted(fils, reverse=True) if s < propre_du_cran]
                else:
                    candidats = [c for s, c in fils if s > propre_du_cran]
                rang_du_frere = next(
                    (i for i, c in enumerate(candidats, start=1) if tags.get(c) == "SectionHeader"),
                    None,
                )
                if rang_du_frere is not None:
                    cle = 0 if crans == 0 else 1
                    rang_max[cle] = max(rang_max[cle], rang_du_frere)
                    break
                if tags.get(p) != "SectionHeader":
                    break
                courant, crans = p, crans + 1
        print(
            f"  {direction:6s} : rang max au cran 0 = {rang_max[0]} ; "
            f"aux crans >= 1 (fratrie d'un oncle) = {rang_max[1]} "
            f"— limite de production : {_CANDIDATS_FRERES}"
        )


def _rapporter_la_lecture(
    entetes: list[str],
    enfants: dict[str, list[tuple[int, str]]],
    parent: dict[str, str],
    rang: dict[str, int],
    tags: dict[str, str],
) -> None:
    """LE SOUS-CHOIX, ÉPROUVÉ CONTRE L'ORDRE DE LECTURE — et il est partagé.

    Le §4.6 écrivait le sous-choix comme « le voisin RÉEL EN LECTURE, côté par
    côté », en signalant lui-même que l'asymétrie était `calculé` et non
    `mesuré` : déduite de la forme du parcours, jamais confrontée à lui. Cette
    section la confronte, et le verdict est partagé :

    - « après » → l'ONCLE lui-même : **CONFIRMÉ**, 188 des 190 remontées ;
    - « avant » → le dernier descendant en-tête de l'oncle : la règle est le
      bon choix PARMI les descendants de l'oncle (186 / 189), mais elle ne rend
      PAS « le texte qui précède réellement » (2 / 189). Ce qui précède
      vraiment, dans 186 des 189 cas, est l'INTRODUCTION DU PARENT de la
      section — les frères non-titres qui la précèdent sous le parent commun.
      Le motif écrit au §4.6 est donc faux ; la règle reste la meilleure
      disponible sous (C), et c'est ce que cette section imprime.

    (B), le voisin en ordre de lecture, est mesurée ici aussi, avec ses
    dégénérescences **EN UNITÉS EXPLICITES** : le §4.6 publiait « 191 cas »
    sans dire de quoi. Ce sont 191 ADJACENCES, soit 382 couples (en-tête,
    direction) — les deux chiffres sont justes sous leur unité, et l'unité
    manquait.
    """
    ordre, rang_dfs, taille, document = _ordre_de_lecture(tags, enfants, parent)
    est_titre = {v: tags.get(v) == "SectionHeader" for v in tags}

    def element_voisin(entete: str, direction: str) -> str | None:
        """Le nœud non-titre réellement lu juste avant / juste après le sous-arbre."""
        if direction == "before":
            indices = range(rang_dfs[entete] - 1, -1, -1)
        else:
            indices = range(rang_dfs[entete] + taille[entete], len(ordre))
        for i in indices:
            noeud = ordre[i]
            if document[noeud] != document[entete]:
                return None
            if not est_titre[noeud] and tags.get(noeud) != "Document":
                return noeud
        return None

    print("\n  ── le SOUS-CHOIX, confronté à l'ordre de lecture réel ──")
    for direction in ("before", "after"):
        population = [
            (v, oncle)
            for v in entetes
            for oncle, crans in [_frere_c(v, direction, enfants, parent, rang, tags)]
            if oncle is not None and crans >= 1
        ]
        familles: collections.Counter[str] = collections.Counter()
        for entete, oncle in population:
            voisin = element_voisin(entete, direction)
            porteur = parent.get(voisin) if voisin is not None else None
            if voisin is None:
                familles["aucun élément de ce côté"] += 1
            elif porteur == parent.get(entete):
                familles["le PARENT de la section (son intro)"] += 1
            elif porteur == oncle:
                familles["l'ONCLE lui-même"] += 1
            elif porteur == _descendant_entete(oncle, enfants, tags, dernier=True):
                familles["le DERNIER descendant en-tête de l'oncle"] += 1
            else:
                familles["ailleurs"] += 1
        print(f"  {direction:6s} : {len(population)} remontées — qui porte le voisin RÉEL ?")
        for famille, nombre in familles.most_common():
            print(f"      {famille:42s} : {nombre}")

    # Seule la direction « avant » descend dans l'oncle : « après » sert l'oncle
    # lui-même, donc il n'y a rien à confronter de ce côté.
    print("\n  ── la règle « dernier descendant » est-elle juste DANS le sous-arbre ? ──")
    juste = faux = 0
    for entete in entetes:
        oncle_trouve, crans = _frere_c(entete, "before", enfants, parent, rang, tags)
        if oncle_trouve is None or crans < 1:
            continue
        fin = rang_dfs[oncle_trouve] + taille[oncle_trouve] - 1
        dernier_lu = next(
            (
                ordre[i]
                for i in range(fin, rang_dfs[oncle_trouve] - 1, -1)
                if not est_titre[ordre[i]] and tags.get(ordre[i]) != "Document"
            ),
            None,
        )
        if dernier_lu is None:
            continue
        queue = _descendant_entete(oncle_trouve, enfants, tags, dernier=True)
        if parent.get(dernier_lu) == queue:
            juste += 1
        else:
            faux += 1
    print(
        "  before : le dernier élément lu du sous-arbre de l'oncle est porté "
        f"par le « dernier descendant en-tête » — juste {juste}, faux {faux}"
    )

    print("\n  ── (B), le voisin en ORDRE DE LECTURE, et ses dégénérescences ──")
    plats = [v for v in ordre if est_titre[v]]
    position = {v: i for i, v in enumerate(plats)}

    def lie(a: str, b: str) -> bool:
        for depart, cible in ((a, b), (b, a)):
            courant: str | None = depart
            while courant is not None:
                if courant == cible:
                    return True
                courant = parent.get(courant)
        return False

    couples = 0
    adjacences: set[tuple[str, str]] = set()
    for direction, pas in (("before", -1), ("after", 1)):
        servis = 0
        for entete in plats:
            j = position[entete] + pas
            voisin = plats[j] if 0 <= j < len(plats) else None
            if voisin is None or document[voisin] != document[entete]:
                continue
            servis += 1
            if lie(entete, voisin):
                couples += 1
                adjacences.add((min(entete, voisin), max(entete, voisin)))
        print(f"  {direction:6s} : en-têtes servis {servis}/{len(entetes)}")
    print(
        f"  DÉGÉNÉRÉS : {len(adjacences)} adjacences, "
        f"soit {couples} couples (en-tête, direction)"
    )


def rapporter_les_definitions_de_voisine(
    aretes: list[tuple[str, str, int | None]], tags: dict[str, str]
) -> None:
    """Le point d'entrée de la section — les trois définitions, bout à bout."""
    enfants, parent = _index(aretes)
    rang = {c: s for _, c, s in aretes if s is not None}
    entetes, poids, total = _entetes_et_poids(tags, parent)

    print("\n── « Section voisine » : (A), (B), (C) confrontées (§4.6) ──")
    _controle_des_chiffres_deja_publies(entetes, enfants, parent, rang, tags)
    _rapporter_les_definitions(entetes, poids, total, enfants, parent, rang, tags)
    _rapporter_la_lecture(entetes, enfants, parent, rang, tags)


def rapporter_les_ecritures(pool: Any, aretes: list[tuple[str, str, int | None]]) -> None:
    """Les écritures d'un même encadrement, confrontées sur le graphe EN SERVICE.

    CETTE SECTION EXISTE PARCE QUE TROIS CHIFFRES ÉTAIENT PUBLIÉS SANS SITE
    REJOUABLE. Le docstring en tête de ce fichier dit qu'« une page qui les
    affirme sans laisser de quoi les rejouer devient fausse en silence » ; la
    phrase valait aussi pour ce qu'elle ne mesurait pas encore.

    Ce qui est confronté, et pourquoi c'est cette question-là : le graphe
    factice de `tests/unit/test_lecture_sequence.py` doit se comporter comme
    NebulaGraph sur les écritures d'un encadrement de `sequence`. S'il en
    ignore une, une mutation qui l'emploie passe en vert. Les quatre écritures
    ci-dessous sont donc mesurées ICI, sur le vrai moteur, et c'est ce qui
    interdit de les traiter comme des formes de laboratoire.

    LECTURE SEULE : quatre `GO FROM`, aucun `INSERT`, aucun `MATCH` d'écriture.
    """
    enfants: dict[str, list[tuple[int, str]]] = {}
    for parent_id, enfant, seq in aretes:
        if seq is not None:
            enfants.setdefault(parent_id, []).append((seq, enfant))

    eligibles = sorted(
        p for p, fils in enfants.items() if len(fils) >= _AVANT + _APRES + 1
    )
    echantillon = eligibles[:_ECHANTILLON]
    print("\n── Les écritures d'un même encadrement, sur le graphe en service ──")
    print(f"parents à {_AVANT + _APRES + 1} enfants ou plus : {len(eligibles)}")
    print(f"parents testés                : {len(echantillon)}")

    accords = dict.fromkeys(("tube", "in", "arithmetique"), 0)
    lignes_alias = 0
    tries_sans_ordre = 0
    tries_avec_ordre = 0
    for parent_id in echantillon:
        fils = sorted(enfants[parent_id])
        milieu = fils[len(fils) // 2]
        bas, haut = milieu[0] - _AVANT, milieu[0] + _APRES
        depart = f'GO FROM "{parent_id}" OVER PARENT_OF '
        projection = "YIELD dst(edge) AS child_id, properties(edge).sequence AS seq "
        liste = ", ".join(str(v) for v in range(bas, haut + 1))
        formes = {
            "classique": depart
            + f"WHERE properties(edge).sequence >= {bas} "
            + f"AND properties(edge).sequence <= {haut} "
            + projection,
            "tube": depart
            + projection
            + "| YIELD $-.child_id AS child_id, $-.seq AS seq "
            + f"WHERE $-.seq >= {bas} AND $-.seq <= {haut}",
            "in": depart
            + f"WHERE properties(edge).sequence IN [{liste}] "
            + projection,
            "arithmetique": depart
            + f"WHERE properties(edge).sequence - {bas} >= 0 "
            + f"AND {haut} - properties(edge).sequence >= 0 "
            + projection,
            "alias": depart
            + projection
            + "| YIELD $-.child_id AS child_id, $-.seq AS rang "
            + f"WHERE $-.rang >= {bas} AND $-.rang <= {haut}",
        }
        rendus = {}
        for nom, nql in formes.items():
            resultat = _run(pool, nql + ";")
            rendus[nom] = {
                resultat.row_values(i)[0].as_string() for i in range(resultat.row_size())
            }
        for nom in accords:
            if rendus[nom] == rendus["classique"]:
                accords[nom] += 1
        lignes_alias += len(rendus["alias"])

        # …et l'ordre que NebulaGraph rend, avec et sans `ORDER BY`. C'est le
        # second chiffre qui n'avait pas de site : le bouchon ne doit pas
        # FABRIQUER un ordre que le moteur ne promet pas.
        brut = _run(pool, depart + projection + ";")
        seqs = [int(brut.row_values(i)[1].as_int()) for i in range(brut.row_size())]
        trie = _run(pool, depart + projection + "| ORDER BY $-.seq ASC;")
        seqs_tries = [int(trie.row_values(i)[1].as_int()) for i in range(trie.row_size())]
        tries_sans_ordre += seqs == sorted(seqs)
        tries_avec_ordre += seqs_tries == sorted(seqs_tries)

    n = len(echantillon)
    print(f"  classique == aval d'un tube ($-.seq)   : {accords['tube']} sur {n}")
    print(f"  classique == IN sur une liste          : {accords['in']} sur {n}")
    print(f"  classique == forme arithmétique        : {accords['arithmetique']} sur {n}")
    print(f"  alias de YIELD : lignes rendues au total : {lignes_alias}")
    print(f"  enfants NON triés sans `ORDER BY`      : {n - tries_sans_ordre} sur {n}")
    print(f"  enfants triés avec `ORDER BY`          : {tries_avec_ordre} sur {n}")


def main() -> int:
    pool = _pool()
    aretes, tags = lire_le_graphe(pool)
    rapporter(aretes, tags)
    rapporter_les_definitions_de_voisine(aretes, tags)
    rapporter_les_ecritures(pool, aretes)
    return 0


if __name__ == "__main__":
    sys.exit(main())
