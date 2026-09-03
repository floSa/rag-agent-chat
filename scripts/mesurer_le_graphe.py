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
- ce qu'un encadrement `sequence ∈ [s−k, s+k]` amputerait → `stores.md`.

Le garde qui rend le découpage positionnel non négociable est ailleurs, et il
ne dépend pas de ce script : `tests/unit/test_lecture_sequence.py`.
"""

from __future__ import annotations

import collections
import os
import sys
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


def main() -> int:
    pool = _pool()
    aretes, tags = lire_le_graphe(pool)
    rapporter(aretes, tags)
    return 0


if __name__ == "__main__":
    sys.exit(main())
