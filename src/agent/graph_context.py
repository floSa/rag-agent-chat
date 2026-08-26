import logging
import re
from functools import lru_cache
from typing import Any, NamedTuple

from nebula3.Config import SessionPoolConfig
from nebula3.gclient.net.SessionPool import SessionPool

from src.agent.retriever import full_texts
from src.agent.settings import settings
from src.api.schemas import BreadcrumbEntry, SectionContext, SectionElement

logger = logging.getLogger(__name__)

# Tags NebulaGraph qui correspondent à des en-têtes de section
_SECTION_TAGS = {"SectionHeader"}
# Tags racine (on s'arrête avant de remonter au-delà)
_ROOT_TAGS = {"Document"}
# Profondeur max de remontée pour éviter les boucles. L'ingestion produit
# aujourd'hui un arbre à deux niveaux (Document > SectionHeader > éléments),
# donc deux sauts suffisent ; la marge couvre une future imbrication réelle
# des titres sans rien changer ici.
_MAX_DEPTH = 10
# Frères examinés de chaque côté avant d'abandonner la recherche d'une section
# voisine. Les enfants d'un Document ne sont pas tous des en-têtes : quelques
# candidats suffisent pour tomber sur le premier vrai SectionHeader.
_SIBLING_CANDIDATES = 5
# Marge sous la limite de troncature en deçà de laquelle on ne soupçonne pas de
# coupure : un texte nettement plus court que la limite est forcément entier.
_TRUNCATION_MARGIN = 50

# Identifiant d'élément : hash sha256[:10] produit par l'ingestion. C'est le
# SEUL format qu'un appelant extérieur peut fournir, et il est validé
# strictement — les VIDs sont interpolés dans les requêtes nGQL.
_VALID_VID = re.compile(r"^[a-f0-9]{10}$")

# Les VIDs de documents sont dérivés du chemin du fichier : ils contiennent des
# séparateurs, des espaces, des accents, et pèsent jusqu'à 256 octets
# (« doc_htms/Practical MLOps/4. Continuous Delivery for ML Models »). Aucun
# motif raisonnable ne les couvre sans devenir une passoire, et ils ne viennent
# jamais de l'utilisateur : ils sont découverts en remontant le graphe. On les
# échappe donc au lieu de les filtrer.
_DOC_VID_PREFIX = "doc_"
# Caractères de contrôle : jamais légitimes dans un VID, et seuls capables de
# casser une littérale nGQL une fois les guillemets et antislashs échappés.
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")


def _quote_vid(vid: str) -> str | None:
    """Rend un VID sous forme de littérale nGQL échappée, None s'il est refusé.

    Accepte les identifiants d'éléments (hash) et les identifiants de documents
    (dérivés d'un chemin). L'antislash est échappé en premier, sans quoi les
    séquences produites seraient invalides — même règle que l'échappement côté
    ingestion.
    """
    if _VALID_VID.fullmatch(vid):
        return f'"{vid}"'
    if not vid.startswith(_DOC_VID_PREFIX) or len(vid.encode()) > 256:  # noqa: PLR2004
        return None
    if _CONTROL_CHARS.search(vid):
        return None
    escaped = vid.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def reset_connection() -> None:
    """Oublie le pool mis en cache, pour le rouvrir au prochain appel."""
    _get_pool.cache_clear()
    _caption_edge.cache_clear()


@lru_cache(maxsize=1)
def _get_pool() -> SessionPool:
    """Pool de sessions lié au space : gère USE, réutilisation et reconnexion.

    En cas d'échec d'init (Nebula pas encore prêt), l'exception empêche la mise
    en cache et l'init sera retentée au prochain appel.
    """
    pool = SessionPool(
        settings.nebula_user,
        settings.nebula_password,
        settings.nebula_space,
        [(settings.nebula_host, settings.nebula_port)],
    )
    # Sans délai d'expiration, une requête lente du graphd fige la requête
    # FastAPI qui l'attend, jusqu'au timeout du client HTTP en bout de chaîne.
    config = SessionPoolConfig()
    config.timeout = settings.nebula_timeout_ms
    if not pool.init(config):
        raise RuntimeError("Impossible d'initialiser le pool de sessions NebulaGraph")
    logger.info(
        "NebulaGraph session pool initialisé : %s:%d (space %s)",
        settings.nebula_host,
        settings.nebula_port,
        settings.nebula_space,
    )
    return pool


def _to_primitive(val: Any) -> Any:
    """Convertit un ValueWrapper nebula3 en valeur Python primitive."""
    if val.is_string():
        return val.as_string()
    if val.is_int():
        return val.as_int()
    if val.is_null():
        return None
    return str(val)


def _execute_raw(nql: str) -> Any | None:
    """Exécute une requête nGQL et rend le ResultSet NON converti, None en échec.

    Seul point de passage vers le pool : il porte les deux choses qu'une requête
    écrite à la main perd, la réouverture du pool après un redémarrage de
    NebulaGraph et le journal de l'erreur nGQL.

    Le pool est mis en cache : si NebulaGraph a redémarré, il pointe vers des
    connexions mortes et toutes les requêtes échouent jusqu'au redémarrage de
    l'agent. Un échec de transport le fait rouvrir, avec un nouvel essai. Si le
    second essai échoue aussi, l'exception remonte — le graphe est réellement
    absent, et l'appelant décide.

    L'absorption est LARGE parce que nebula3 remonte des erreurs de transport,
    d'authentification et de session sans ancêtre commun, et qu'un pool mort les
    produit toutes. Elle est TRACÉE en WARNING et suivie d'un nouvel essai : rien
    n'est perdu en silence.

    Cette variante existe pour `_get_node_properties`, qui a besoin du
    `ValueWrapper` de vertex brut — `_to_primitive` l'aplatirait en chaîne. Elle
    appelait donc le pool directement, et perdait la reprise : après un
    redémarrage du graphd, les autres chemins se rétablissaient, celui-là
    remontait l'exception jusqu'au try/except par élément de
    `node_reconstruct_context`, et la source disparaissait de la réponse sans
    que rien ne le dise.
    """
    try:
        result = _get_pool().execute(nql)
    except Exception:
        logger.warning("NebulaGraph injoignable, réouverture du pool et nouvel essai.")
        reset_connection()
        result = _get_pool().execute(nql)
    if not result.is_succeeded():
        logger.error("nGQL échoué : %s — %s", nql, result.error_msg())
        return None
    return result


def _execute(nql: str) -> list[dict[str, Any]]:
    """Exécute une requête nGQL et retourne les lignes sous forme de dicts."""
    result = _execute_raw(nql)
    if result is None:
        return []
    rows = []
    for i in range(result.row_size()):
        row = {}
        for j, col in enumerate(result.keys()):
            row[col] = _to_primitive(result.row_values(i)[j])
        rows.append(row)
    return rows


def _get_node_properties(node_id: str) -> dict[str, Any]:
    """Récupère le tag Nebula et les propriétés d'un nœud en UNE requête.

    La propriété `label` contient le label Docling en minuscules
    ("section_header", "paragraph", …) ; c'est le tag Nebula ("SectionHeader",
    "Document", …) qui identifie le type de nœud lors de la remontée.

    Passe par `_execute_raw` et non par le pool directement : cette fonction est
    appelée constamment — remontée vers le Document, recherche de section voisine
    jusqu'à cinq fois par direction, titre de chaque voisine — et sans la reprise
    du pool elle était le seul chemin qui ne survivait pas à un redémarrage du
    graphd. Elle a besoin du ResultSet brut, pas des lignes converties : le
    `ValueWrapper` de vertex est ce qui porte les tags et les propriétés, et
    `_to_primitive` l'aplatirait en chaîne.
    """
    quoted = _quote_vid(node_id)
    if quoted is None:
        logger.warning("VID Nebula rejeté : %s", node_id[:80])
        return {}

    result = _execute_raw(f"FETCH PROP ON * {quoted} YIELD vertex AS node;")
    if result is None or result.row_size() == 0:
        return {}

    val = result.row_values(0)[0]
    if not val.is_vertex():
        return {}
    node = val.as_node()
    tags = node.tags()

    def props_of(tag: str) -> dict[str, Any]:
        try:
            return {k: _to_primitive(v) for k, v in node.properties(tag).items()}
        except Exception:
            # Absorption LARGE et MUETTE, délibérément : un nœud sans propriétés
            # pour ce tag est le cas NORMAL, pas une panne — le tag Document n'a
            # ni `label` ni `text`. Cette fonction est appelée plusieurs fois par
            # élément reconstruit ; y journaliser quoi que ce soit inonderait le
            # journal en régime nominal. L'appelant traite un dict vide comme
            # « pas de propriétés », ce qui est exactement l'information.
            return {}

    # Le tag Document n'a pas de propriétés label/text : cas particulier.
    # Il porte en revanche l'ouvrage, seule source fiable quand la citation ne
    # vient pas d'un chunk — l'endpoint de génération directe, notamment.
    if "Document" in tags:
        props = props_of("Document")
        return {
            "tag": "Document",
            "label": "document",
            "text": props.get("filename") or "",
            "collection": props.get("collection") or "",
            "minio_url": None,
            "page_no": 0,
        }

    if not tags:
        return {}

    tag = "SectionHeader" if "SectionHeader" in tags else tags[0]
    props = props_of(tag)
    return {
        "tag": tag,
        "label": props.get("label") or "",
        "text": props.get("text") or "",
        "minio_url": props.get("minio_url") or None,
        "page_no": props.get("page_no") or 0,
    }


def _find_parent(node_id: str) -> tuple[str | None, int]:
    """Retourne (VID du parent direct, rang du nœud sous ce parent).

    Le rang est la propriété `sequence` de l'arête PARENT_OF, c'est-à-dire
    l'ordre de lecture global attribué par l'ingestion. Il sert à situer une
    section parmi ses sœurs pour atteindre la précédente et la suivante.

    ATTENTION à la sémantique nGQL : sous ``REVERSELY``, ``dst(edge)`` renvoie
    le nœud de DÉPART, pas le voisin atteint. C'est ``src(edge)`` qui porte le
    parent. La requête retournait donc l'élément lui-même, la remontée
    n'avançait jamais, et toute la reconstruction par le graphe était sans
    effet — vérifié contre le graphe :

        MATCH (p)-[:PARENT_OF]->(c) WHERE id(c)=="1730443c8f" -> "ffa6bda17d"
        GO FROM "1730443c8f" OVER PARENT_OF REVERSELY YIELD dst(edge) -> "1730443c8f"
        GO FROM "1730443c8f" OVER PARENT_OF REVERSELY YIELD src(edge) -> "ffa6bda17d"
    """
    quoted = _quote_vid(node_id)
    if quoted is None:
        return None, 0
    rows = _execute(
        f"GO FROM {quoted} OVER PARENT_OF REVERSELY "
        f"YIELD src(edge) AS parent_id, properties(edge).sequence AS seq;"
    )
    if not rows:
        return None, 0
    return str(rows[0]["parent_id"]), int(rows[0].get("seq") or 0)


def _find_sibling(parent_id: str, sequence: int, direction: str) -> str | None:
    """Retourne le SectionHeader frère juste avant ou juste après `sequence`.

    Les en-têtes sont tous enfants directs du Document (l'ingestion ne les
    imbrique pas) : la section voisine est donc un frère, atteint par un
    encadrement sur la propriété `sequence` de l'arête. Le LIMIT borne le coût
    sur un ouvrage de plusieurs centaines de sections.

    Args:
        parent_id: VID du parent commun (en pratique, le Document).
        sequence: Rang de la section de départ.
        direction: "before" ou "after".
    """
    if direction == "before":
        comparison, order = f"< {sequence}", "DESC"
    else:
        comparison, order = f"> {sequence}", "ASC"

    quoted = _quote_vid(parent_id)
    if quoted is None:
        return None
    rows = _execute(
        f"GO FROM {quoted} OVER PARENT_OF "
        f"WHERE properties(edge).sequence {comparison} "
        f"YIELD dst(edge) AS sibling_id, properties(edge).sequence AS seq "
        f"| ORDER BY $-.seq {order} | LIMIT {_SIBLING_CANDIDATES};"
    )
    for row in rows:
        sibling_id = row.get("sibling_id")
        if sibling_id and _get_node_properties(str(sibling_id)).get("tag") in _SECTION_TAGS:
            return str(sibling_id)
    return None


# Noms successifs de l'arête qui relie une légende à son illustration. Le
# pipeline d'ingestion l'a nommée DESCRIBES puis LINKED_TO : plutôt que de
# suivre chaque renommage, on interroge le schéma et on prend celle qui existe.
_CAPTION_EDGES = ("LINKED_TO", "DESCRIBES")


@lru_cache(maxsize=1)
def _caption_edge() -> str | None:
    """Nom de l'arête légende → illustration présente dans le space."""
    disponibles = {str(row.get("Name") or "") for row in _execute("SHOW EDGES;")}
    for nom in _CAPTION_EDGES:
        if nom in disponibles:
            return nom
    logger.info(
        "Aucune arête de légende dans le graphe (attendu : %s). Les illustrations "
        "seront proposées sans légende.",
        " ou ".join(_CAPTION_EDGES),
    )
    return None


def _caption_links(caption_ids: list[str]) -> dict[str, str]:
    """Relie chaque visuel à la légende qui le décrit, via l'arête DESCRIBES.

    L'ingestion relie chaque Caption à l'illustration qui la précède. Sans
    cette traversée, le LLM reçoit un `[img:ID]` sans le moindre texte et ne
    peut pas juger si l'image sert la réponse — alors que le prompt système lui
    demande précisément d'en juger.

    Args:
        caption_ids: VIDs des éléments de label ``caption`` de la section.
            L'arête est cherchée dans le schéma : son nom a déjà changé une
            fois côté ingestion, et l'ancien produisait une erreur nGQL à
            chaque reconstruction — sans casser la réponse, mais en privant
            silencieusement les illustrations de leur légende.

    Returns:
        Dict {VID du visuel: VID de sa légende}. Les textes sont repris par
        l'appelant, qui les a déjà dans la liste des enfants.
    """
    quoted = [q for q in (_quote_vid(cid) for cid in caption_ids) if q]
    arete = _caption_edge()
    if not quoted or arete is None:
        return {}

    sources = ", ".join(quoted)
    rows = _execute(
        f"GO FROM {sources} OVER {arete} "
        f"YIELD src(edge) AS caption_id, dst(edge) AS visual_id;"
    )
    links: dict[str, str] = {}
    for row in rows:
        visual_id, caption_id = row.get("visual_id"), row.get("caption_id")
        if visual_id and caption_id:
            links[visual_id] = caption_id
    return links


# Tags porteurs d'une illustration exportée vers MinIO.
_VISUAL_TAGS = ("Picture", "Table")


def media_object_names() -> set[str]:
    """Chemins d'objets MinIO réellement référencés par le graphe.

    Sert d'autorisation au proxy `/media` : sans elle, l'endpoint sert
    n'importe quel objet du bucket à qui devine son chemin. Le garde-fou
    anti-traversal existant empêche de sortir du bucket, pas d'y fouiller.

    La liste vient du graphe et non de l'index vectoriel : une illustration n'a
    pas de texte, elle n'est donc pas vectorisée et manquerait à l'appel.
    """
    noms: set[str] = set()
    for tag in _VISUAL_TAGS:
        rows = _execute(
            f'MATCH (n:{tag}) WHERE n.{tag}.minio_url != "" '
            f"RETURN n.{tag}.minio_url AS url;"
        )
        for row in rows:
            url = str(row.get("url") or "")
            # http://minio:9000/{bucket}/{objet} → {objet}
            parts = url.split("/", 4)
            if len(parts) == 5:  # noqa: PLR2004
                noms.add(parts[4])
    return noms


def ping() -> bool:
    """Vérifie que NebulaGraph répond (utilisé par /health).

    Absorption LARGE et assumée : une sonde ne doit jamais lever, sans quoi
    /health tomberait au lieu de rapporter. Elle n'est pas muette pour autant —
    `_execute` a déjà journalisé la panne en WARNING avant de la laisser passer,
    et le faux rendu ici est publié par /health.
    """
    try:
        return bool(_execute("YIELD 1 AS ok;"))
    except Exception:
        return False


def _get_children(section_id: str) -> list[dict[str, Any]]:
    """Retourne les enfants d'une section, ordonnés par sequence."""
    quoted = _quote_vid(section_id)
    if quoted is None:
        return []
    return _execute(
        f'GO FROM {quoted} OVER PARENT_OF '
        f'YIELD dst(edge) AS child_id, '
        f'properties($$).label AS label, '
        f'properties($$).text AS text, '
        f'properties($$).minio_url AS minio_url, '
        f'properties($$).page_no AS page_no, '
        f'properties(edge).sequence AS seq '
        f'| ORDER BY $-.seq ASC;'
    )


class _Ancestry(NamedTuple):
    """Résultat de la remontée d'un élément vers la racine de son document."""

    section_id: str            # SectionHeader porteur, ou l'élément lui-même
    section_sequence: int      # rang de cette section sous son parent
    section_parent_id: str     # parent de la section — le Document en pratique
    breadcrumbs: list[BreadcrumbEntry]   # du Document jusqu'à la section
    filename: str              # nom du document, "" s'il n'a pas été atteint
    collection: str            # ouvrage dont le document fait partie


def _climb_to_section(element_id: str) -> _Ancestry:
    """Remonte de l'élément jusqu'au Document, en notant sa section au passage.

    La version précédente s'arrêtait au premier SectionHeader rencontré. Comme
    l'ingestion rattache tout élément à son en-tête et tout en-tête au
    Document, la remontée s'arrêtait donc systématiquement au premier saut : le
    nœud Document n'était jamais atteint, et le nom du fichier — que le
    post-processing des citations y cherchait — restait vide. Toutes les
    citations issues du graphe s'affichaient sans document source.

    On mémorise désormais la première section traversée, puis on poursuit
    jusqu'au tag racine.
    """
    breadcrumbs_reversed: list[BreadcrumbEntry] = []
    current_id = element_id
    section_id = element_id
    section_sequence = 0
    section_parent_id = ""
    filename = ""
    collection = ""
    section_found = False

    for _ in range(_MAX_DEPTH):
        parent_id, sequence = _find_parent(current_id)
        if parent_id is None:
            break

        props = _get_node_properties(parent_id)
        tag = props.get("tag", "")
        label = props.get("label", "") or tag
        text = props.get("text", "") or ""

        breadcrumbs_reversed.append(
            BreadcrumbEntry(node_id=parent_id, label=label, text=text[:120])
        )

        if tag in _SECTION_TAGS and not section_found:
            section_id = parent_id
            section_found = True
        elif not section_found:
            # L'élément est enfant direct du Document : c'est lui qui porte son
            # propre rang, et il n'y a pas de section intermédiaire.
            section_sequence = sequence

        if tag in _ROOT_TAGS:
            filename = text
            collection = str(props.get("collection") or "")
            if section_found and not section_parent_id:
                section_parent_id = parent_id
            break

        current_id = parent_id

    # Le rang de la section sous le Document n'est connu qu'au saut suivant.
    if section_found:
        parent_id, sequence = _find_parent(section_id)
        section_parent_id = parent_id or section_parent_id
        section_sequence = sequence

    return _Ancestry(
        section_id=section_id,
        section_sequence=section_sequence,
        section_parent_id=section_parent_id,
        breadcrumbs=list(reversed(breadcrumbs_reversed)),
        filename=filename,
        collection=collection,
    )


def _window_around(
    rows: list[dict[str, Any]], anchor_id: str, before: int, after: int
) -> tuple[list[dict[str, Any]], bool]:
    """Restreint les enfants d'une section à une fenêtre autour de l'ancre.

    Un document dépourvu de SectionHeader rattache tous ses éléments au nœud
    Document : sans borne, la « section » reconstruite est le document entier,
    et Ollama tronque le prompt en silence, par le début — donc en jetant les
    premières sources.

    Args:
        rows: Enfants de la section, déjà ordonnés par `sequence`.
        anchor_id: VID de l'élément trouvé par la recherche vectorielle.
        before: Nombre d'éléments conservés avant l'ancre.
        after: Nombre d'éléments conservés après.

    Returns:
        (fenêtre, des éléments ont-ils été écartés).
    """
    if not rows:
        return [], False

    index = next(
        (i for i, row in enumerate(rows) if row.get("child_id") == anchor_id), None
    )
    if index is None:
        # L'ancre est la section elle-même : on prend la tête de la section.
        window = rows[: before + after + 1]
        return window, len(window) < len(rows)

    start = max(0, index - before)
    stop = min(len(rows), index + after + 1)
    return rows[start:stop], (start > 0 or stop < len(rows))


def _render_element(elem: SectionElement) -> str:
    """Rend un élément en markdown, suivi de son identifiant de citation.

    Le marqueur `[src:ID]` est ce qui permet au LLM de citer précisément, et au
    post-processing de résoudre la citation vers document / page / section.
    """
    label = elem.label.lower()
    src = f"[src:{elem.node_id}]"

    if label in ("paragraph", "text", "listitem"):
        return f"{elem.text} {src}"
    if label == "table":
        header = f"[Tableau] {elem.caption}".rstrip() if elem.caption else "[Tableau]"
        body = f"{header} {elem.text} {src}"
        return f"{body}\n\n[img:{elem.node_id}]" if elem.minio_url else body
    if label == "picture":
        if not elem.minio_url:
            return ""
        # La légende est le seul texte dont dispose le LLM pour juger si
        # l'illustration sert la réponse.
        header = f"[Figure] {elem.caption}" if elem.caption else "[Figure]"
        return f"{header}\n\n[img:{elem.node_id}]"
    if label == "caption":
        return f"_{elem.text}_ {src}"
    if label in ("code", "formula"):
        return f"```\n{elem.text}\n```\n{src}"
    return f"{elem.text} {src}" if elem.text else ""


def _build_markdown(
    breadcrumbs: list[BreadcrumbEntry],
    elements: list[SectionElement],
    section_text: str,
    before: list[SectionElement] | None = None,
    after: list[SectionElement] | None = None,
    before_title: str = "",
    after_title: str = "",
) -> str:
    """Assemble le contexte enrichi en markdown structuré.

    Les éléments repris des sections voisines sont rendus dans des blocs
    explicitement étiquetés : le LLM doit pouvoir distinguer ce qui appartient
    à la section trouvée de ce qui l'entoure.
    """
    if not breadcrumbs and not elements:
        return ""

    parts: list[str] = []

    if breadcrumbs:
        trail = " > ".join(b.text[:60] or b.label for b in breadcrumbs)
        parts.append(f"[Contexte] {trail}\n")

    if before:
        parts.append(f"[Fin de la section précédente — {before_title}]".rstrip(" —"))
        parts.extend(_render_element(e) for e in before)

    if section_text:
        parts.append(f"## {section_text}\n")

    parts.extend(_render_element(e) for e in elements)

    if after:
        parts.append(f"[Début de la section suivante — {after_title}]".rstrip(" —"))
        parts.extend(_render_element(e) for e in after)

    return "\n\n".join(p for p in parts if p.strip())


def _to_elements(rows: list[dict[str, Any]]) -> list[SectionElement]:
    """Convertit des lignes nGQL d'enfants en éléments de section."""
    return [
        SectionElement(
            node_id=row.get("child_id", ""),
            label=row.get("label", "") or "",
            text=row.get("text", "") or "",
            minio_url=row.get("minio_url") or None,
            sequence=int(row.get("seq", 0)),
            page_no=int(row.get("page_no") or 0),
        )
        for row in rows
    ]


def _restore_full_text(elements: list[SectionElement]) -> int:
    """Remplace le texte tronqué du graphe par le texte intégral de l'index.

    Le graphe porte la structure, pas le corpus : l'ingestion y tronque le texte
    à 2000 caractères. Un tableau exporté par Docling dépasse souvent cette
    limite et arrivait amputé au LLM. On ne demande le texte complet que pour
    les éléments qui frôlent la troncature — inutile d'interroger l'index pour
    un paragraphe de 300 caractères.

    Returns:
        Nombre d'éléments dont le texte a été rallongé.
    """
    if not settings.full_text_from_vectors:
        return 0

    candidats = [
        e.node_id
        for e in elements
        if len(e.text) >= settings.graph_text_truncation - _TRUNCATION_MARGIN
    ]
    if not candidats:
        return 0

    textes = full_texts(candidats)
    rallonges = 0
    for elem in elements:
        complet = textes.get(elem.node_id)
        # Strictement plus long : l'index ne doit jamais raccourcir un texte.
        if complet and len(complet) > len(elem.text):
            elem.text = complet
            rallonges += 1
    return rallonges


def _attach_captions(elements: list[SectionElement]) -> None:
    """Reporte sur chaque visuel le texte de la légende qui le décrit."""
    caption_ids = [e.node_id for e in elements if e.label.lower() == "caption"]
    if not caption_ids:
        return

    texts = {e.node_id: e.text for e in elements}
    for visual_id, caption_id in _caption_links(caption_ids).items():
        caption = texts.get(caption_id)
        if not caption:
            continue
        for elem in elements:
            if elem.node_id == visual_id:
                elem.caption = caption


def _neighbour_elements(
    ancestry: _Ancestry, direction: str, budget: int
) -> tuple[list[SectionElement], str]:
    """Retourne la queue de la section précédente, ou la tête de la suivante.

    Répond au besoin « récupérer les informations avant et après » : les
    en-têtes étant frères sous le Document et ordonnés par `sequence`, la
    section voisine s'atteint sans imbrication réelle des titres.
    """
    if budget <= 0 or not ancestry.section_parent_id:
        return [], ""

    sibling_id = _find_sibling(
        ancestry.section_parent_id, ancestry.section_sequence, direction
    )
    if sibling_id is None:
        return [], ""

    rows = _get_children(sibling_id)
    # Avant : la fin de la section qui précède. Après : le début de la suivante.
    selected = rows[-budget:] if direction == "before" else rows[:budget]
    title = _get_node_properties(sibling_id).get("text", "") or ""
    return _to_elements(selected), title[:120]


def reconstruct_section(element_id: str) -> SectionContext:
    """Point d'entrée principal : reconstruit le contexte complet d'un élément.

    1. Remonte via PARENT_OF jusqu'au Document, en notant la section au passage
    2. Récupère les enfants de la section, fenêtrés autour de l'élément trouvé
    3. Rattache les légendes aux illustrations (arête DESCRIBES)
    4. Ajoute la fin de la section précédente et le début de la suivante
    5. Assemble en markdown structuré avec breadcrumbs
    """
    if not _VALID_VID.fullmatch(element_id):
        raise ValueError(f"Identifiant d'élément invalide : {element_id[:80]}")

    ancestry = _climb_to_section(element_id)
    section_id = ancestry.section_id

    # Propriétés de la section (ou de l'élément lui-même si aucune section parente)
    section_props = _get_node_properties(section_id)
    section_text = section_props.get("text", "") or ""
    is_header = section_props.get("tag") in _SECTION_TAGS

    children_rows = _get_children(section_id)
    window, truncated = _window_around(
        children_rows,
        element_id,
        settings.context_window_before,
        settings.context_window_after,
    )
    elements = _to_elements(window)
    rallonges = _restore_full_text(elements)
    _attach_captions(elements)

    budget = settings.adjacent_section_elements
    before, before_title = _neighbour_elements(ancestry, "before", budget)
    after, after_title = _neighbour_elements(ancestry, "after", budget)

    markdown = _build_markdown(
        ancestry.breadcrumbs,
        elements,
        section_text if is_header else "",
        before=before,
        after=after,
        before_title=before_title,
        after_title=after_title,
    )
    if not is_header and section_text:
        # Élément orphelin de section : son propre texte est le contexte
        markdown = "\n\n".join(p for p in (markdown, section_text) if p)

    logger.info(
        "Reconstruction %s → section %s : %d/%d éléments%s, voisins %d/%d, "
        "%d texte(s) complété(s), doc='%s'",
        element_id,
        section_id,
        len(elements),
        len(children_rows),
        " (fenêtrés)" if truncated else "",
        len(before),
        len(after),
        rallonges,
        ancestry.filename,
    )

    return SectionContext(
        element_id=element_id,
        section_id=section_id,
        breadcrumbs=ancestry.breadcrumbs,
        elements=elements,
        markdown=markdown,
        filename=ancestry.filename,
        collection=ancestry.collection,
        section_title=section_text if is_header else "",
        before=before,
        after=after,
        before_title=before_title,
        after_title=after_title,
        truncated=truncated,
    )
