"""Le site canonique du contrat de noms de champs rendus par les sources externes.

POURQUOI CE MODULE EXISTE.

Deux sources externes nous rendent des enregistrements dont nous lisons les
champs PAR LEUR NOM : le graphe NebulaGraph et la collection ChromaDB. Ces noms
sont un CONTRAT, et ce contrat est écrit par quelqu'un d'autre —
`rag-ingestion-pipeline`. Il a annoncé qu'il renommerait `minio_url`, et le
registre (`documentation/axes_amelioration.md` §4.62) mesure ce que ce
renommage nous ferait : NebulaGraph ne lève pas sur une propriété inconnue —
un `RETURN` rend `None`, un `WHERE` rend zéro ligne — donc
`media_object_names()` rendrait un ensemble vide et le proxy `/media`, réglé sur
`RESTRICT_MEDIA_TO_GRAPH`, refuserait la TOTALITÉ des images. Sans une ligne de
journal, sans une exception.

Avant ce module, le nom du champ était écrit à sept endroits dans `src/` et à
vingt-trois endroits dans `tests/`, où les doubles le POSAIENT eux-mêmes. Aucune
de ces vingt-trois lignes ne lisait une source réelle : la suite serait restée
INTÉGRALEMENT verte pendant que la production ne servirait plus une image.

CE QUE CE MODULE APPORTE. Un seul endroit — `CONTRAT_DES_SOURCES` — nomme le
champ attendu de chaque source, et un seul endroit — `SITES_ATTENDUS` — décrit
où ce champ est lu. Le jour de la bascule, on change `CONTRAT_DES_SOURCES`, la
suite rougit, et elle NOMME les sites à suivre.

CE QU'IL NE COUVRE PAS, ET C'EST DÉLIBÉRÉ. Le périmètre est `src/agent/`, le
seul code qui lit une source EXTERNE. `src/api/schemas.py` et
`src/frontend/app.py` portent le même nom `minio_url`, mais c'est NOTRE schéma
de réponse — un contrat interne, que nous décidons seuls, et qui n'a pas à
suivre le calendrier du pipeline. Le mélanger ici ferait rougir cette garde
pour une décision qui ne la concerne pas.

COMMENT LES SITES SONT RELEVÉS. Par AST, jamais par recherche de texte dans le
fichier, et surtout jamais par numéro de ligne : treize lignes ajoutées au-dessus
d'un site et un garde ancré sur un numéro ressort vert en ayant cessé de mesurer.
Un site est décrit par son MOTIF — (module, fonction englobante, nature) — ce qui
survit à tout déplacement et rougit sur tout ajout, retrait ou changement de nom.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from pathlib import Path

import pytest

_RACINE = Path(__file__).resolve().parents[2]
_PERIMETRE = _RACINE / "src" / "agent"

# ─── LE CONTRAT — LE SEUL ENDROIT À CHANGER LE JOUR DE LA BASCULE ─────────────
#
# `mesuré` le 22 septembre 2026 contre `main` = 890f4b9, et rendu au pipeline au
# §4.62 du registre. La bascule accordée est `minio_url` → `media_url`, plus un
# champ nouveau `object_key`. Elle n'a PAS eu lieu : tant qu'elle n'a pas eu
# lieu, ce contrat dit `minio_url`, et les scènes de
# `test_bascule_du_nom_de_champ_media.py` clouent ce que coûterait le silence.
CONTRAT_DES_SOURCES: dict[str, str] = {
    "graphe": "minio_url",
    "chromadb": "minio_url",
}

# Fonctions par lesquelles une requête part vers le graphe. Les chaînes nGQL
# qu'elles reçoivent portent des noms de propriétés, qui sont des lectures du
# contrat au même titre qu'un `.get()`.
_PORTES_NGQL = frozenset({"_execute", "_execute_raw"})

# Une référence de propriété nGQL : `n.Picture.minio_url`, `properties($$).text`.
# Ce motif ne lit PAS un fichier — il lit la valeur d'une constante de chaîne
# isolée par l'AST dans l'argument d'un appel au graphe. nGQL n'est pas du
# Python : à l'intérieur de la requête, aucune analyse syntaxique ne nous est
# offerte, et c'est la borne assumée de ce relevé.
_REFERENCE_NGQL = re.compile(r"\.([A-Za-z_][A-Za-z0-9_]*)")


@dataclass(frozen=True)
class SiteReleve:
    """Une lecture de champ effectivement présente dans `src/agent/`."""

    module: str       # chemin relatif à la racine du dépôt
    fonction: str     # fonction englobante, ou "<module>"
    nature: str       # "mapping_get" | "subscript" | "ngql_property"
    champ: str        # le nom lu
    ligne: int        # INFORMATIF — aucun assert ne s'y ancre

    @property
    def motif(self) -> tuple[str, str, str]:
        """L'identité stable du site : ce qui survit à un déplacement."""
        return (self.module, self.fonction, self.nature)


@dataclass(frozen=True)
class SiteAttendu:
    """Un site du contrat, décrit par motif et par nombre d'occurrences."""

    module: str
    fonction: str
    nature: str
    source: str        # clé de CONTRAT_DES_SOURCES
    occurrences: int   # combien de lectures du champ ce motif porte

    @property
    def motif(self) -> tuple[str, str, str]:
        return (self.module, self.fonction, self.nature)


# ─── L'INVENTAIRE, PAR MOTIF ET JAMAIS PAR NUMÉRO DE LIGNE ────────────────────
#
# `mesuré` le 22 septembre 2026 contre `main` = 890f4b9 : six fonctions, trois
# fichiers, deux sources. La somme des `occurrences` vaut sept, et c'est cette
# somme — jamais un sept recopié — que les gardes confrontent au relevé.
SITES_ATTENDUS: tuple[SiteAttendu, ...] = (
    # Le graphe, par ses lignes converties en dicts.
    SiteAttendu("src/agent/graph_context.py", "_get_node_properties", "mapping_get", "graphe", 1),
    SiteAttendu("src/agent/graph_context.py", "_to_elements", "mapping_get", "graphe", 1),
    # Le graphe, par le texte des requêtes. `media_object_names` lit la
    # propriété DEUX fois — une en WHERE, une en RETURN — et c'est la première
    # qui fait le plus de dégâts : sur une propriété inconnue, NebulaGraph rend
    # zéro ligne au lieu de lever.
    SiteAttendu("src/agent/graph_context.py", "media_object_names", "ngql_property", "graphe", 2),
    SiteAttendu("src/agent/graph_context.py", "_get_children", "ngql_property", "graphe", 1),
    # ChromaDB, par les métadonnées de chunk, sur les deux chemins de recherche.
    SiteAttendu("src/agent/lexical.py", "chunk_from_record", "mapping_get", "chromadb", 1),
    SiteAttendu("src/agent/retriever.py", "_dense_search", "mapping_get", "chromadb", 1),
)

# Champs témoins : des noms de champs que les MÊMES fonctions lisent aux MÊMES
# natures, et qui ne sont pas au contrat média. Ils servent de contrôle positif
# au releveur lui-même — un releveur cassé rend zéro partout, et un zéro partout
# rendrait VERTE la garde « aucun site inattendu » sans qu'elle mesure rien.
_TEMOINS: tuple[tuple[str, str, str, str], ...] = (
    ("src/agent/graph_context.py", "_get_node_properties", "mapping_get", "filename"),
    ("src/agent/graph_context.py", "_to_elements", "mapping_get", "page_no"),
    ("src/agent/graph_context.py", "_get_children", "ngql_property", "page_no"),
    ("src/agent/lexical.py", "chunk_from_record", "mapping_get", "section_title"),
    ("src/agent/retriever.py", "_dense_search", "mapping_get", "section_title"),
)


def _fonction_englobante(fonctions: list[ast.AST], ligne: int) -> str:
    """Nomme la fonction la plus imbriquée qui contient cette ligne."""
    retenue: ast.FunctionDef | ast.AsyncFunctionDef | None = None
    for noeud in fonctions:
        assert isinstance(noeud, ast.FunctionDef | ast.AsyncFunctionDef)
        fin = noeud.end_lineno or noeud.lineno
        if noeud.lineno <= ligne <= fin and (retenue is None or noeud.lineno > retenue.lineno):
            retenue = noeud
    return retenue.name if retenue is not None else "<module>"


def _constantes_de_chaine(noeud: ast.expr) -> list[ast.Constant]:
    """Les constantes de chaîne d'un argument, f-string comprise.

    Une f-string est un `JoinedStr` dont les morceaux littéraux sont des
    `Constant` : c'est là que vivent les noms de propriétés nGQL, les `{}`
    n'y étant que des tags ou des identifiants déjà échappés.
    """
    if isinstance(noeud, ast.Constant) and isinstance(noeud.value, str):
        return [noeud]
    if isinstance(noeud, ast.JoinedStr):
        return [
            morceau
            for morceau in noeud.values
            if isinstance(morceau, ast.Constant) and isinstance(morceau.value, str)
        ]
    return []


def _nom_appele(noeud: ast.Call) -> str:
    """Le nom de la fonction appelée, qu'elle soit nue ou qualifiée."""
    if isinstance(noeud.func, ast.Name):
        return noeud.func.id
    if isinstance(noeud.func, ast.Attribute):
        return noeud.func.attr
    return ""


def relever_les_sites() -> list[SiteReleve]:
    """Relève, par AST, toute lecture de champ nommé dans `src/agent/`.

    Trois natures, parce que trois façons d'écrire la même lecture :
    `meta.get("x")`, `meta["x"]`, et `… .x` dans une requête nGQL. Le relevé
    n'est filtré par aucun nom de champ : c'est en le filtrant APRÈS, par le
    contrat, que les gardes peuvent aussi bien voir un site disparaître qu'un
    site apparaître là où on ne l'attendait pas.
    """
    releves: list[SiteReleve] = []
    for chemin in sorted(_PERIMETRE.rglob("*.py")):
        module = chemin.relative_to(_RACINE).as_posix()
        arbre = ast.parse(chemin.read_text(encoding="utf-8"))
        fonctions = [
            n for n in ast.walk(arbre) if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)
        ]

        for noeud in ast.walk(arbre):
            if isinstance(noeud, ast.Call):
                appele = _nom_appele(noeud)
                if (
                    appele == "get"
                    and noeud.args
                    and isinstance(noeud.args[0], ast.Constant)
                    and isinstance(noeud.args[0].value, str)
                ):
                    releves.append(
                        SiteReleve(
                            module,
                            _fonction_englobante(fonctions, noeud.lineno),
                            "mapping_get",
                            noeud.args[0].value,
                            noeud.lineno,
                        )
                    )
                if appele in _PORTES_NGQL:
                    for argument in noeud.args:
                        for constante in _constantes_de_chaine(argument):
                            for trouve in _REFERENCE_NGQL.finditer(constante.value):
                                releves.append(
                                    SiteReleve(
                                        module,
                                        _fonction_englobante(fonctions, constante.lineno),
                                        "ngql_property",
                                        trouve.group(1),
                                        constante.lineno,
                                    )
                                )
            elif (
                isinstance(noeud, ast.Subscript)
                and isinstance(noeud.slice, ast.Constant)
                and isinstance(noeud.slice.value, str)
            ):
                releves.append(
                    SiteReleve(
                        module,
                        _fonction_englobante(fonctions, noeud.lineno),
                        "subscript",
                        noeud.slice.value,
                        noeud.lineno,
                    )
                )
    return releves


@pytest.fixture(scope="module")
def releves() -> list[SiteReleve]:
    return relever_les_sites()


@pytest.fixture(scope="module")
def sites_du_contrat(releves: list[SiteReleve]) -> list[SiteReleve]:
    """Les seules lectures qui portent un nom de champ du contrat média."""
    noms = set(CONTRAT_DES_SOURCES.values())
    return [site for site in releves if site.champ in noms]


def test_le_releveur_voit_quelque_chose(releves: list[SiteReleve]) -> None:
    """CONTRÔLE POSITIF DU RELEVEUR — il doit précéder tout constat à zéro.

    Un relevé vide rendrait VERTE la garde « aucun site inattendu » sans qu'elle
    mesure quoi que ce soit : le faux vert exact qu'un garde décoratif produit.
    Les témoins sont des champs voisins, lus par les mêmes fonctions et aux
    mêmes natures que les sites du contrat. S'ils manquent, c'est le RELEVEUR
    qui est en panne, pas `src/`.
    """
    presents = {(s.module, s.fonction, s.nature, s.champ) for s in releves}
    manquants = [temoin for temoin in _TEMOINS if temoin not in presents]
    assert not manquants, (
        "Le releveur AST ne retrouve plus ses champs témoins : "
        f"{manquants}. Tant que ceci rougit, AUCUN constat à zéro de ce module "
        "ne vaut — c'est le releveur qu'il faut réparer, pas src/."
    )


def test_chaque_site_attendu_lit_le_champ_du_contrat(sites_du_contrat: list[SiteReleve]) -> None:
    """Chaque motif de l'inventaire lit bien le nom que sa source nous doit.

    Rougit si un site est retiré, déplacé dans une autre fonction, ou s'il se
    met à lire un autre nom — c'est-à-dire le jour de la bascule.
    """
    par_motif: dict[tuple[str, str, str], list[SiteReleve]] = {}
    for site in sites_du_contrat:
        par_motif.setdefault(site.motif, []).append(site)

    ecarts: list[str] = []
    for attendu in SITES_ATTENDUS:
        champ = CONTRAT_DES_SOURCES[attendu.source]
        trouves = [s for s in par_motif.get(attendu.motif, []) if s.champ == champ]
        if len(trouves) != attendu.occurrences:
            ecarts.append(
                f"{attendu.module}::{attendu.fonction} ({attendu.nature}, source "
                f"« {attendu.source} ») : {attendu.occurrences} lecture(s) de "
                f"« {champ} » attendue(s), {len(trouves)} relevée(s)"
            )

    assert not ecarts, (
        "Le contrat de champs externes n'est plus tenu aux sites suivants :\n  "
        + "\n  ".join(ecarts)
        + "\nSi le pipeline a basculé, changez CONTRAT_DES_SOURCES — un seul "
        "endroit — puis suivez les sites que cette garde nomme."
    )


def test_aucune_lecture_du_champ_hors_de_l_inventaire(sites_du_contrat: list[SiteReleve]) -> None:
    """Un huitième site ajouté ailleurs doit être dit, pas découvert en production.

    C'est la moitié qui manquait : savoir que les sites connus sont justes ne
    dit rien d'un site NEUF, et c'est un site neuf, oublié le jour de la
    bascule, qui reproduirait la panne muette.
    """
    connus = {attendu.motif for attendu in SITES_ATTENDUS}
    intrus = sorted(
        f"{s.module}:{s.ligne} ({s.fonction}, {s.nature}) lit « {s.champ} »"
        for s in sites_du_contrat
        if s.motif not in connus
    )
    assert not intrus, (
        "Des lectures du champ média vivent hors de l'inventaire :\n  "
        + "\n  ".join(intrus)
        + "\nAjoutez-les à SITES_ATTENDUS — sinon elles échapperont à la bascule."
    )


def test_le_compte_total_est_celui_de_l_inventaire(sites_du_contrat: list[SiteReleve]) -> None:
    """Le compte est une PROPRIÉTÉ, pas un nombre recopié.

    Il vaut sept au 22 septembre 2026 (`mesuré`, `main` = 890f4b9), mais aucun
    sept n'est écrit ici : le total attendu est CALCULÉ depuis l'inventaire. Un
    site ajouté à l'inventaire sans son équivalent dans `src/` rougit, et
    l'inverse aussi.
    """
    attendu = sum(site.occurrences for site in SITES_ATTENDUS)
    releve = len(sites_du_contrat)
    assert releve == attendu, (
        f"{attendu} lecture(s) du champ média décrite(s) par l'inventaire, "
        f"{releve} relevée(s) dans {_PERIMETRE.relative_to(_RACINE)} :\n  "
        + "\n  ".join(
            sorted(f"{s.module}:{s.ligne} ({s.fonction}, {s.nature})" for s in sites_du_contrat)
        )
    )


def test_chaque_source_du_contrat_est_effectivement_lue() -> None:
    """Aucune source ne peut être déclarée au contrat sans un site qui la lit.

    Garde la symétrie dans l'autre sens : une source ajoutée à
    `CONTRAT_DES_SOURCES` sans inventaire serait un contrat décoratif.
    """
    couvertes = {attendu.source for attendu in SITES_ATTENDUS}
    assert couvertes == set(CONTRAT_DES_SOURCES), (
        f"Sources déclarées : {sorted(CONTRAT_DES_SOURCES)} ; "
        f"sources effectivement inventoriées : {sorted(couvertes)}."
    )


def test_les_sites_sont_repartis_sur_les_modules_annonces(
    sites_du_contrat: list[SiteReleve],
) -> None:
    """Les trois fichiers annoncés au registre portent tous des sites.

    Borne explicite : la garde vérifie que l'ensemble des modules porteurs est
    EXACTEMENT celui de l'inventaire. Un site qui migre vers un quatrième
    fichier est déjà attrapé par `test_aucune_lecture_du_champ_hors_de_l_inventaire` ;
    celui-ci attrape un fichier qui se vide entièrement.
    """
    attendus = {attendu.module for attendu in SITES_ATTENDUS}
    releves = {site.module for site in sites_du_contrat}
    assert releves == attendus, (
        f"Modules attendus : {sorted(attendus)} ; modules relevés : {sorted(releves)}."
    )


def test_le_releve_ignore_le_nom_interne_du_schema() -> None:
    """La frontière du périmètre est tenue, et elle est vérifiée.

    `src/api/schemas.py` et `src/frontend/app.py` portent le même nom
    `minio_url`, mais c'est NOTRE contrat de réponse. Il n'est pas dicté par le
    pipeline et n'a pas à rougir avec lui. Si cette garde se met à échouer,
    c'est que le périmètre a bougé — et il faut décider, pas élargir.
    """
    assert _PERIMETRE == _RACINE / "src" / "agent"
    hors_perimetre = _RACINE / "src" / "api" / "schemas.py"
    assert hors_perimetre.exists(), "le fichier témoin du contrat interne a disparu"
    assert hors_perimetre not in set(_PERIMETRE.rglob("*.py"))
