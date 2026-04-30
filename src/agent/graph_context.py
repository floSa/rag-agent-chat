import logging
from functools import lru_cache

from nebula3.Config import Config
from nebula3.gclient.net import ConnectionPool

from src.agent.settings import settings
from src.api.schemas import BreadcrumbEntry, SectionContext, SectionElement

logger = logging.getLogger(__name__)

# Tags NebulaGraph qui correspondent à des en-têtes de section
_SECTION_TAGS = {"SectionHeader"}
# Tags racine (on s'arrête avant de remonter au-delà)
_ROOT_TAGS = {"Document"}
# Profondeur max de remontée pour éviter les boucles
_MAX_DEPTH = 10


@lru_cache(maxsize=1)
def _get_pool() -> ConnectionPool:
    config = Config()
    config.max_connection_pool_size = 5
    pool = ConnectionPool()
    pool.init([(settings.nebula_host, settings.nebula_port)], config)
    logger.info("NebulaGraph pool initialisé : %s:%d", settings.nebula_host, settings.nebula_port)
    return pool


def _execute(nql: str) -> list[dict]:  # type: ignore[return]
    """Exécute une requête nGQL et retourne les lignes sous forme de dicts."""
    pool = _get_pool()
    session = pool.get_session(settings.nebula_user, settings.nebula_password)
    try:
        session.execute(f"USE {settings.nebula_space};")
        result = session.execute(nql)
        if not result.is_succeeded():
            logger.error("nGQL échoué : %s — %s", nql, result.error_msg())
            return []
        rows = []
        for i in range(result.row_size()):
            row = {}
            for j, col in enumerate(result.keys()):
                val = result.row_values(i)[j]
                # Extraire la valeur primitive
                if val.is_string():
                    row[col] = val.as_string()
                elif val.is_int():
                    row[col] = val.as_int()
                elif val.is_null():
                    row[col] = None
                else:
                    row[col] = str(val)
            rows.append(row)
        return rows
    finally:
        session.release()


def _get_node_properties(node_id: str) -> dict:
    """Récupère les propriétés d'un nœud (label, text, minio_url, page_no)."""
    # On essaie plusieurs tags possibles
    tags = [
        "SectionHeader", "Paragraph", "Table", "Picture", "Code",
        "Formula", "Caption", "ListItem", "Footnote", "PageHeader",
        "PageFooter", "Document",
    ]
    for tag in tags:
        rows = _execute(
            f'FETCH PROP ON {tag} "{node_id}" '
            f'YIELD properties(vertex).label AS label, '
            f'properties(vertex).text AS text, '
            f'properties(vertex).minio_url AS minio_url, '
            f'properties(vertex).page_no AS page_no;'
        )
        if rows:
            return rows[0]
    return {}


def _find_parent(node_id: str) -> str | None:
    """Retourne le VID du parent direct via PARENT_OF REVERSELY."""
    rows = _execute(
        f'GO FROM "{node_id}" OVER PARENT_OF REVERSELY '
        f'YIELD dst(edge) AS parent_id;'
    )
    return rows[0]["parent_id"] if rows else None


def _get_children(section_id: str) -> list[dict]:
    """Retourne les enfants d'une section, ordonnés par sequence."""
    return _execute(
        f'GO FROM "{section_id}" OVER PARENT_OF '
        f'YIELD dst(edge) AS child_id, '
        f'properties($$).label AS label, '
        f'properties($$).text AS text, '
        f'properties($$).minio_url AS minio_url, '
        f'properties(edge).sequence AS seq '
        f'| ORDER BY $-.seq ASC;'
    )


def _climb_to_section(element_id: str) -> tuple[str, list[BreadcrumbEntry]]:
    """Remonte jusqu'au SectionHeader (ou Document) le plus proche.

    Retourne (section_id, breadcrumbs_du_haut_vers_le_bas).
    """
    breadcrumbs_reversed: list[BreadcrumbEntry] = []
    current_id = element_id
    section_id = element_id

    for _ in range(_MAX_DEPTH):
        parent_id = _find_parent(current_id)
        if parent_id is None:
            break

        props = _get_node_properties(parent_id)
        label = props.get("label", "")
        text = props.get("text", "") or ""

        breadcrumbs_reversed.append(
            BreadcrumbEntry(node_id=parent_id, label=label, text=text[:120])
        )

        if label in _SECTION_TAGS | _ROOT_TAGS:
            section_id = parent_id
            # Si on a trouvé un SectionHeader, on s'arrête selon CONTEXT_DEPTH
            if label in _SECTION_TAGS:
                break

        current_id = parent_id

    # Remettre dans l'ordre document → section
    breadcrumbs = list(reversed(breadcrumbs_reversed))
    return section_id, breadcrumbs


def _build_markdown(
    breadcrumbs: list[BreadcrumbEntry],
    elements: list[SectionElement],
    section_text: str,
) -> str:
    """Assemble le contexte enrichi en markdown structuré."""
    parts: list[str] = []

    if breadcrumbs:
        trail = " > ".join(b.text[:60] or b.label for b in breadcrumbs)
        parts.append(f"[Contexte] {trail}\n")

    if section_text:
        parts.append(f"## {section_text}\n")

    for elem in elements:
        label = elem.label.lower()
        if label in ("paragraph", "text", "listitem"):
            parts.append(elem.text)
        elif label == "table":
            parts.append(f"[Tableau] {elem.text}")
            if elem.minio_url:
                parts.append(f"[img:{elem.node_id}]")
        elif label == "picture":
            if elem.minio_url:
                parts.append(f"[img:{elem.node_id}]")
        elif label == "caption":
            parts.append(f"_{elem.text}_")
        elif label in ("code", "formula"):
            parts.append(f"```\n{elem.text}\n```")
        else:
            if elem.text:
                parts.append(elem.text)

    return "\n\n".join(p for p in parts if p.strip())


def reconstruct_section(element_id: str) -> SectionContext:
    """Point d'entrée principal : reconstruit le contexte complet d'un élément.

    1. Remonte via PARENT_OF jusqu'au SectionHeader le plus proche
    2. Récupère tous les enfants de la section (ordonnés)
    3. Assemble en markdown structuré avec breadcrumbs
    """
    section_id, breadcrumbs = _climb_to_section(element_id)

    # Propriétés de la section
    section_props = _get_node_properties(section_id)
    section_text = section_props.get("text", "") or ""

    # Enfants de la section
    children_rows = _get_children(section_id)
    elements: list[SectionElement] = []
    for row in children_rows:
        elements.append(
            SectionElement(
                node_id=row.get("child_id", ""),
                label=row.get("label", ""),
                text=row.get("text", "") or "",
                minio_url=row.get("minio_url") or None,
                sequence=int(row.get("seq", 0)),
            )
        )

    markdown = _build_markdown(breadcrumbs, elements, section_text)

    logger.debug(
        "Reconstruction : element=%s → section=%s (%d enfants)",
        element_id,
        section_id,
        len(elements),
    )

    return SectionContext(
        element_id=element_id,
        section_id=section_id,
        breadcrumbs=breadcrumbs,
        elements=elements,
        markdown=markdown,
    )
