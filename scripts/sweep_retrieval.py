#!/usr/bin/env python
"""Balayage de paramètres de recherche, sans générer une seule réponse.

Une campagne complète prend une demi-heure : la génération LLM y pèse pour
l'essentiel, alors que régler la recherche n'en a pas besoin. Ce script rejoue
le retrieval seul sur le jeu doré et mesure le rappel — quelques secondes par
configuration au lieu de trente minutes.

Les traductions de questions sont calculées une fois puis mises en cache sur
disque : elles sont indépendantes des paramètres balayés, et les recalculer à
chaque configuration coûterait plus cher que tout le reste réuni.

    uv run --no-sync python scripts/sweep_retrieval.py
    uv run --no-sync python scripts/sweep_retrieval.py \
        --param translation_weight --valeurs 0,0.3,0.5,1
"""

from __future__ import annotations

import argparse
import collections
import json
import statistics
import sys
from pathlib import Path
from typing import Any

import httpx
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

CACHE_TRADUCTIONS = ROOT / "runs" / ".traductions.json"


def charger_questions(chemin: Path) -> list[dict[str, Any]]:
    """Lit un jeu de questions, YAML ou JSON selon son suffixe.

    Le motif du YAML est au docstring de `evaluate.charger_questions` — il est
    mesuré, et il concerne `detect-secrets`.
    """
    texte = chemin.read_text(encoding="utf-8")
    en_yaml = chemin.suffix.lower() in (".yaml", ".yml")
    data = yaml.safe_load(texte) if en_yaml else json.loads(texte)
    # Sans passage attendu, une question ne dit rien du rappel.
    return [q for q in data["questions"] if q.get("gold_element_ids")]


# CE QUI A ÉTÉ AVALÉ, GARDÉ POUR ÊTRE DIT. Une traduction manquante ne fait pas
# lever ce script : elle retire la question du versant translinguistique, donc
# elle DÉPLACE le rappel mesuré sans qu'aucune erreur n'apparaisse. Un balayage
# dont la moitié des traductions a échoué compare des configurations sur un jeu
# amputé, et conclut.
_PANNES_DE_TRADUCTION: list[str] = []


def traduire(question: str, ollama: str, model: str) -> str | None:
    """Traduit une question, en réutilisant le gabarit de production.

    CE POSTE EST PASSÉ PAR LE SITE UNIQUE LE 16 SEPTEMBRE 2026 — NB-5 de l'audit
    du lot 25. Il postait `/api/chat` en dur et lisait `message.content` à la
    racine : pointé vers un serveur vLLM, il aurait rendu `None` pour CHAQUE
    question, en silence, et le balayage aurait comparé ses configurations sur
    un jeu sans aucune traduction — en concluant.

    L'adresse et le modèle restent ceux des arguments, pour la même raison que
    dans `generate_golden.py` : ce script s'exécute depuis le poste et non
    depuis le réseau compose. Ce qui vient du dialecte est la FORME.
    """
    from src.agent.dialecte_llm import dialecte_courant
    from src.agent.flux_llm import charge_du_corps
    from src.agent.llm import _get_jinja_env

    prompt = _get_jinja_env().get_template("translate_query.j2").render(question=question)
    dialecte = dialecte_courant()._replace(hote=ollama, modele=model)
    try:
        reponse = httpx.post(
            dialecte.url_chat,
            json=dialecte.charge(
                [{"role": "user", "content": prompt}],
                stream=False,
                temperature=0.0,
                max_tokens=150,
                thinking=False,
            ),
            timeout=180.0,
        )
        reponse.raise_for_status()
        texte = (charge_du_corps(reponse.json()).get("content") or "").strip()
    except Exception as panne:  # noqa: BLE001 — absorption large ASSUMÉE, et DITE
        # Toutes ces pannes se disent pareil ici — « je n'ai pas de traduction »
        # — et les distinguer par leur type serait fragile. Ce qui manquait
        # n'est pas la distinction, c'est la TRACE : `cache_traductions` imprime
        # désormais le compte et les trois premières.
        _PANNES_DE_TRADUCTION.append(f"{type(panne).__name__}: {panne}")
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
        # IMPRIMÉ MÊME À ZÉRO : un compteur qui ne s'affiche qu'au-dessus de
        # zéro ne se lit jamais comme « zéro », il se lit comme « rien n'a été
        # mesuré ». Une panne répétée autant de fois qu'il y a de questions est
        # la signature d'un serveur qui ne parle pas le dialecte qu'on lui
        # envoie ; elle se voyait autrefois comme un cache simplement plus petit.
        print(f"  pannes de traduction absorbées : {len(_PANNES_DE_TRADUCTION)}")
        for panne, occurrences in collections.Counter(_PANNES_DE_TRADUCTION).most_common(3):
            print(f"    {occurrences}x {panne}")
        CACHE_TRADUCTIONS.parent.mkdir(parents=True, exist_ok=True)
        CACHE_TRADUCTIONS.write_text(
            json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    return cache


def evaluer_config(
    questions: list[dict],
    traductions: dict[str, str],
    utiliser_traduction: bool,
    avec_rerank: bool = False,
) -> dict[str, Any]:
    """Rejoue le retrieval sur toutes les questions et mesure le rappel.

    Avec ``avec_rerank``, le cross-encoder est appliqué : on mesure alors ce qui
    atteint vraiment le LLM. Sans lui, élargir le vivier améliore le rappel
    mécaniquement, ce qui ne prouve rien — c'est la coupe finale qui compte.
    """
    from src.agent.retriever import rerank, retrieve

    lignes = []
    for q in questions:
        attendus = set(q["gold_element_ids"])
        traduction = traductions.get(q["question"]) if utiliser_traduction else None
        chunks = retrieve(q["question"], translation=traduction)
        if avec_rerank:
            chunks = rerank(q["question"], chunks)
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
        "--golden", type=Path, default=ROOT / "tests" / "fixtures" / "golden_qa_generated.yaml"
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
    parser.add_argument(
        "--rerank",
        action="store_true",
        help="Applique le cross-encoder : mesure ce qui atteint le LLM",
    )
    parser.add_argument("--entier", action="store_true", help="Le réglage balayé est un entier")
    args = parser.parse_args()

    from src.agent.settings import settings

    questions = charger_questions(args.golden)
    print(f"{len(questions)} questions avec passage attendu")

    traductions = (
        {} if args.sans_traduction else cache_traductions(questions, args.ollama, args.model)
    )

    if args.sans_traduction:
        resultat = resumer(evaluer_config(questions, {}, False, args.rerank)["lignes"])
        print(f"\nTÉMOIN sans traduction : {resultat}")
        return 0

    valeurs: list[Any] = [
        int(v) if args.entier else float(v) for v in args.valeurs.split(",")
    ]
    mesure = "après reranking" if args.rerank else "avant reranking"
    print(f"\nBalayage de {args.param} sur {valeurs} ({mesure})\n")
    print(f"{args.param:>18s} {'rappel':>8s} {'mrr':>7s} {'transling.':>11s} {'même lg':>9s}")

    for valeur in valeurs:
        setattr(settings, args.param, valeur)
        resultat = resumer(evaluer_config(questions, traductions, True, args.rerank)["lignes"])
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
