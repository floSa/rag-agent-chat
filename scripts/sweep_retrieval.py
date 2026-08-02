#!/usr/bin/env python
"""Balayage de paramètres de recherche, sans générer une seule réponse.

Une campagne complète prend une demi-heure : la génération LLM y pèse pour
l'essentiel, alors que régler la recherche n'en a pas besoin. Ce script rejoue
le retrieval seul sur le jeu doré et mesure le rappel — quelques secondes par
configuration au lieu de trente minutes.

Les traductions de questions sont calculées une fois puis mises en cache sur
disque : elles sont indépendantes des paramètres balayés, et les recalculer à
chaque configuration coûterait plus cher que tout le reste réuni.

    uv run python scripts/sweep_retrieval.py
    uv run python scripts/sweep_retrieval.py --param translation_weight --valeurs 0,0.3,0.5,1
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

CACHE_TRADUCTIONS = ROOT / "runs" / ".traductions.json"


def charger_questions(chemin: Path) -> list[dict[str, Any]]:
    data = json.loads(chemin.read_text(encoding="utf-8"))
    # Sans passage attendu, une question ne dit rien du rappel.
    return [q for q in data["questions"] if q.get("gold_element_ids")]


def traduire(question: str, ollama: str, model: str) -> str | None:
    """Traduit une question, en réutilisant le gabarit de production."""
    from src.agent.llm import _get_jinja_env

    prompt = _get_jinja_env().get_template("translate_query.j2").render(question=question)
    try:
        reponse = httpx.post(
            f"{ollama}/api/chat",
            json={
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "stream": False,
                "think": False,
                "options": {"temperature": 0.0, "num_predict": 150},
            },
            timeout=180.0,
        )
        reponse.raise_for_status()
        texte = reponse.json().get("message", {}).get("content", "").strip()
    except Exception:
        return None
    texte = texte.splitlines()[0].strip().strip("\"'") if texte else ""
    return texte or None


def cache_traductions(
    questions: list[dict], ollama: str, model: str
) -> dict[str, str]:
    """Traduit ce qui ne l'est pas encore, et conserve le résultat."""
    cache: dict[str, str] = {}
    if CACHE_TRADUCTIONS.exists():
        cache = json.loads(CACHE_TRADUCTIONS.read_text(encoding="utf-8"))

    manquantes = [q for q in questions if q["question"] not in cache]
    if manquantes:
        print(f"Traduction de {len(manquantes)} questions (mises en cache)…")
        for index, q in enumerate(manquantes, 1):
            traduction = traduire(q["question"], ollama, model)
            if traduction:
                cache[q["question"]] = traduction
            if index % 20 == 0:
                print(f"  {index}/{len(manquantes)}")
        CACHE_TRADUCTIONS.parent.mkdir(parents=True, exist_ok=True)
        CACHE_TRADUCTIONS.write_text(
            json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    return cache


def evaluer_config(
    questions: list[dict], traductions: dict[str, str], utiliser_traduction: bool
) -> dict[str, Any]:
    """Rejoue le retrieval sur toutes les questions et mesure le rappel."""
    from src.agent.retriever import retrieve

    lignes = []
    for q in questions:
        attendus = set(q["gold_element_ids"])
        traduction = traductions.get(q["question"]) if utiliser_traduction else None
        chunks = retrieve(q["question"], translation=traduction)
        classement = [c.element_id for c in chunks]

        rang = next((i for i, eid in enumerate(classement, 1) if eid in attendus), None)
        doc_langue = q.get("doc_language") or q.get("language", "")
        lignes.append(
            {
                "id": q["id"],
                "translinguistique": bool(doc_langue) and doc_langue != q.get("language"),
                "rappel": 1.0 if rang else 0.0,
                "rang_reciproque": 1.0 / rang if rang else 0.0,
            }
        )
    return {"lignes": lignes}


def resumer(lignes: list[dict]) -> dict[str, Any]:
    def moyenne(sous_ensemble: list[dict], cle: str) -> float | None:
        return (
            round(statistics.mean([r[cle] for r in sous_ensemble]), 3)
            if sous_ensemble
            else None
        )

    trans = [r for r in lignes if r["translinguistique"]]
    meme = [r for r in lignes if not r["translinguistique"]]
    return {
        "rappel": moyenne(lignes, "rappel"),
        "mrr": moyenne(lignes, "rang_reciproque"),
        "rappel_translinguistique": moyenne(trans, "rappel"),
        "rappel_meme_langue": moyenne(meme, "rappel"),
        "n_translinguistique": len(trans),
        "n_meme_langue": len(meme),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--golden", type=Path, default=ROOT / "tests" / "fixtures" / "golden_qa_generated.json"
    )
    parser.add_argument("--ollama", default="http://localhost:11434")
    parser.add_argument("--model", default="gemma4:e4b")
    parser.add_argument(
        "--param",
        default="translation_weight",
        help="Réglage à balayer (attribut de Settings)",
    )
    parser.add_argument("--valeurs", default="0,0.25,0.5,0.75,1.0")
    parser.add_argument("--sans-traduction", action="store_true", help="Témoin monolingue")
    args = parser.parse_args()

    from src.agent.settings import settings

    questions = charger_questions(args.golden)
    print(f"{len(questions)} questions avec passage attendu")

    traductions = (
        {} if args.sans_traduction else cache_traductions(questions, args.ollama, args.model)
    )

    if args.sans_traduction:
        resultat = resumer(evaluer_config(questions, {}, False)["lignes"])
        print(f"\nTÉMOIN sans traduction : {resultat}")
        return 0

    valeurs = [float(v) for v in args.valeurs.split(",")]
    print(f"\nBalayage de {args.param} sur {valeurs}\n")
    print(f"{args.param:>18s} {'rappel':>8s} {'mrr':>7s} {'transling.':>11s} {'même lg':>9s}")

    for valeur in valeurs:
        setattr(settings, args.param, valeur)
        resultat = resumer(evaluer_config(questions, traductions, True)["lignes"])
        print(
            f"{valeur:>18} {resultat['rappel']:>8} {resultat['mrr']:>7} "
            f"{resultat['rappel_translinguistique']:>11} {resultat['rappel_meme_langue']:>9}"
        )

    print(
        f"\n(n = {resultat['n_translinguistique']} translinguistiques, "
        f"{resultat['n_meme_langue']} même langue)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
