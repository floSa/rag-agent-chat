#!/usr/bin/env python
"""Export des enregistrements de capture d'usage en JSON.

C'est **le robinet, pas la décision**. Décider quelles questions promeuvent en
jeu doré, et avec quelle annotation, est le travail d'un lot ultérieur : ce
script sort ce qui a été capturé, sous une forme documentée, et s'arrête là.

    uv run python scripts/usage_export.py
    uv run python scripts/usage_export.py --db data/usage.sqlite --out runs/usage.json
    uv run python scripts/usage_export.py --endpoint chat --since 2026-09-01

Le schéma de sortie est documenté dans documentation/capture_usage.md. Chaque
interaction porte ses sources proposées, chacune avec son rang, sa pertinence et
son sort — c'est cette imbrication qui rend les décochages lisibles sans
jointure côté lecteur.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
# Sans cette ligne, `python scripts/usage_export.py` meurt sur
# « ModuleNotFoundError: No module named 'src' » : l'interpréteur met `scripts/`
# sur le chemin d'import, pas la racine du dépôt. Les deux autres scripts qui
# importent `src` la portent déjà.
sys.path.insert(0, str(ROOT))

# Colonnes stockées en JSON : réhydratées à l'export, sinon le lecteur reçoit
# des chaînes échappées dans un document déjà JSON.
_COLONNES_JSON = (
    "ranked_element_ids",
    "submitted_element_ids",
    "submitted_section_ids",
    "citations",
    "images",
    "config_json",
)


def _decoder(valeur: Any) -> Any:
    if not isinstance(valeur, str):
        return valeur
    try:
        return json.loads(valeur)
    except json.JSONDecodeError:
        # Une ligne écrite par une version antérieure du schéma vaut mieux
        # brute que perdue : l'export n'est pas un validateur.
        return valeur


def exporter(
    chemin: Path, endpoint: str | None = None, since: str | None = None
) -> dict[str, Any]:
    """Lit la base et rend le document d'export, interactions et sources jointes."""
    conditions: list[str] = []
    params: list[Any] = []
    if endpoint:
        conditions.append("endpoint = ?")
        params.append(endpoint)
    if since:
        # Comparaison lexicographique sur de l'ISO 8601 : elle est correcte
        # tant que les horodatages sont écrits en UTC, ce qu'ils sont.
        conditions.append("started_at >= ?")
        params.append(since)
    filtre = f" WHERE {' AND '.join(conditions)}" if conditions else ""

    # URI en lecture seule : un export ne doit pas créer la base ni la modifier,
    # et surtout pas pendant qu'un service écrit dedans.
    with sqlite3.connect(f"file:{chemin}?mode=ro", uri=True) as conn:
        conn.row_factory = sqlite3.Row
        interactions = [
            {
                cle: (_decoder(valeur) if cle in _COLONNES_JSON else valeur)
                for cle, valeur in dict(ligne).items()
            }
            for ligne in conn.execute(
                f"SELECT * FROM interactions{filtre} ORDER BY started_at", params
            )
        ]
        par_thread: dict[str, list[dict[str, Any]]] = {}
        for ligne in conn.execute(
            "SELECT * FROM sources_proposees ORDER BY thread_id, rang"
        ):
            source = dict(ligne)
            par_thread.setdefault(str(source.pop("thread_id")), []).append(source)
        version = conn.execute("PRAGMA user_version").fetchone()[0]

    for interaction in interactions:
        interaction["sources_proposees"] = par_thread.get(interaction["thread_id"], [])

    return {
        "schema_version": version,
        "source": str(chemin),
        "count": len(interactions),
        "interactions": interactions,
    }


def main() -> int:
    from src.agent.settings import settings

    parseur = argparse.ArgumentParser(description=__doc__)
    parseur.add_argument(
        "--db",
        default=settings.usage_db_path,
        help="Base de capture (défaut : USAGE_DB_PATH).",
    )
    parseur.add_argument("--out", help="Fichier de sortie (défaut : la sortie standard).")
    parseur.add_argument(
        "--endpoint",
        choices=("chat", "answer", "chat_simple"),
        help="Ne garder qu'un chemin. « chat » est le seul à porter une sélection humaine.",
    )
    parseur.add_argument("--since", help="Horodatage ISO 8601 minimum (ex. 2026-09-01).")
    args = parseur.parse_args()

    chemin = Path(args.db)
    if not chemin.exists():
        print(
            f"Aucune base de capture à {chemin}. "
            "USAGE_CAPTURE est-il actif, et le service a-t-il déjà servi ?",
            file=sys.stderr,
        )
        return 1

    document = exporter(chemin, endpoint=args.endpoint, since=args.since)
    texte = json.dumps(document, ensure_ascii=False, indent=2)
    if args.out:
        Path(args.out).write_text(texte + "\n", encoding="utf-8")
        print(f"{document['count']} interaction(s) écrite(s) dans {args.out}", file=sys.stderr)
    else:
        print(texte)
    return 0


if __name__ == "__main__":
    sys.exit(main())
