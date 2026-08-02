#!/usr/bin/env python
"""Campagne d'évaluation contre un agent en marche.

Mesure ce qui est mesurable **sans juge LLM** : le rappel du retrieval, la
complétude des citations, l'abstention sur les questions sans réponse, et la
latence décomposée. Ces chiffres sont déterministes — deux exécutions sur le
même index donnent le même résultat, ce qu'aucune métrique jugée par un modèle
ne garantit.

Ce script ne remplace pas RAG-Eval-Bench, qui apporte les juges calibrés, la
comparaison appariée et les intervalles de confiance. Il donne la boucle courte :
un chiffre en deux minutes après chaque changement de retrieval ou de prompt.

    uv run python scripts/evaluate.py
    uv run python scripts/evaluate.py --api http://localhost:8011 --out runs/base.json
    uv run python scripts/evaluate.py --compare runs/base.json
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
GOLDEN = ROOT / "tests" / "fixtures" / "golden_qa.json"

# Formulations par lesquelles le prompt système fait dire au modèle qu'il ne sait
# pas. Une abstention est une bonne réponse quand le corpus est muet.
REFUS = ("je n'ai pas trouvé", "i could not find", "i did not find", "aucune information")


def charger_questions(chemin: Path) -> list[dict]:
    data = json.loads(chemin.read_text(encoding="utf-8"))
    return [q for q in data["questions"] if not q.get("_skip")]


def interroger(api: str, question: dict, timeout: float) -> dict[str, Any]:
    """Pose une question à l'agent et retourne sa réponse brute."""
    response = httpx.post(
        f"{api}/answer",
        json={
            "question": question["question"],
            "max_sources": 5,
            # Présent, il déclenche la réécriture : c'est ce qui distingue une
            # question de suivi d'une question autonome.
            "chat_history": question.get("chat_history") or [],
        },
        timeout=timeout,
    )
    response.raise_for_status()
    return response.json()


def evaluer(question: dict, reponse: dict[str, Any]) -> dict[str, Any]:
    """Confronte une réponse à la vérité terrain de sa question."""
    contexts = reponse.get("contexts", [])
    citations = reponse.get("citations", [])
    texte = (reponse.get("answer") or "").lower()

    trouves_ids = {c["element_id"] for c in contexts}
    trouves_docs = {c.get("source_path", "") for c in contexts}

    attendus_ids = set(question.get("gold_element_ids") or [])
    attendus_docs = set(question.get("gold_documents") or [])

    # Rappel au niveau de l'élément quand l'annotation est fine, au niveau du
    # document sinon. Le second est plus permissif : on ne mélange pas les deux
    # dans une moyenne, on les rapporte séparément.
    rappel_elements = (
        len(trouves_ids & attendus_ids) / len(attendus_ids) if attendus_ids else None
    )
    rappel_documents = (
        sum(1 for d in attendus_docs if any(d in t for t in trouves_docs)) / len(attendus_docs)
        if attendus_docs
        else None
    )

    a_refuse = any(marqueur in texte for marqueur in REFUS)
    sans_reponse = bool(question.get("unanswerable"))

    # Une citation complète nomme le document ET situe le passage. C'est
    # l'exigence produit : « une source, c'est un document, une page, une section ».
    completes = sum(
        1 for c in citations if c.get("filename") and (c.get("page_no") or c.get("section_title"))
    )

    return {
        "id": question["id"],
        "langue": question.get("language", ""),
        "type": question.get("type", ""),
        "rappel_elements": rappel_elements,
        "rappel_documents": rappel_documents,
        "abstention_correcte": a_refuse if sans_reponse else None,
        "hallucination_probable": (not a_refuse) if sans_reponse else None,
        "citations": len(citations),
        "citations_completes": completes,
        "taux_citation_complete": completes / len(citations) if citations else None,
        "contextes": len(contexts),
        "contextes_ecartes": reponse.get("dropped_contexts", 0),
        "langues_sources": sorted({c.get("language", "") for c in contexts if c.get("language")}),
        "retrieval_ms": reponse.get("retrieval_ms", 0),
        "generation_ms": reponse.get("generation_ms", 0),
    }


def _moyenne(valeurs: list[float | None]) -> float | None:
    reelles = [v for v in valeurs if v is not None]
    return round(statistics.mean(reelles), 3) if reelles else None


def _centile(valeurs: list[int], part: float) -> int:
    if not valeurs:
        return 0
    ordonnees = sorted(valeurs)
    return ordonnees[min(int(len(ordonnees) * part), len(ordonnees) - 1)]


def resumer(lignes: list[dict]) -> dict[str, Any]:
    sans_reponse = [r for r in lignes if r["abstention_correcte"] is not None]
    retrieval = [r["retrieval_ms"] for r in lignes]
    generation = [r["generation_ms"] for r in lignes]

    return {
        "questions": len(lignes),
        "rappel_elements": _moyenne([r["rappel_elements"] for r in lignes]),
        "rappel_documents": _moyenne([r["rappel_documents"] for r in lignes]),
        "taux_citation_complete": _moyenne([r["taux_citation_complete"] for r in lignes]),
        "citations_par_reponse": _moyenne([float(r["citations"]) for r in lignes]),
        "abstention_correcte": (
            round(sum(1 for r in sans_reponse if r["abstention_correcte"]) / len(sans_reponse), 3)
            if sans_reponse
            else None
        ),
        "contextes_ecartes_total": sum(r["contextes_ecartes"] for r in lignes),
        "retrieval_ms_p50": _centile(retrieval, 0.5),
        "retrieval_ms_p95": _centile(retrieval, 0.95),
        "generation_ms_p50": _centile(generation, 0.5),
        "generation_ms_p95": _centile(generation, 0.95),
    }


def par_langue(lignes: list[dict]) -> dict[str, Any]:
    """Le corpus est mixte : une moyenne globale masquerait un écart par langue."""
    resultat = {}
    for langue in sorted({r["langue"] for r in lignes if r["langue"]}):
        sous_ensemble = [r for r in lignes if r["langue"] == langue]
        resultat[langue] = {
            "questions": len(sous_ensemble),
            "rappel_documents": _moyenne([r["rappel_documents"] for r in sous_ensemble]),
            "taux_citation_complete": _moyenne(
                [r["taux_citation_complete"] for r in sous_ensemble]
            ),
        }
    return resultat


def afficher(resume: dict, langues: dict, lignes: list[dict]) -> None:
    print(f"\n{'=' * 72}\nRÉSUMÉ — {resume['questions']} questions\n{'=' * 72}")
    for cle, valeur in resume.items():
        if cle != "questions":
            print(f"  {cle:28s} {valeur}")

    print("\nPar langue de la question")
    for langue, valeurs in langues.items():
        print(f"  [{langue}] {valeurs}")

    manques = [r for r in lignes if (r["rappel_documents"] or 1.0) < 1.0]
    if manques:
        print(f"\nRappel incomplet sur {len(manques)} question(s) :")
        for r in manques:
            print(f"  {r['id']} ({r['langue']}, {r['type']}) — rappel {r['rappel_documents']}")

    fautives = [r for r in lignes if r["hallucination_probable"]]
    if fautives:
        print(f"\nA répondu alors que le corpus est muet : {[r['id'] for r in fautives]}")


def comparer(actuel: dict, chemin: Path) -> None:
    """Affiche l'écart avec une campagne précédente, métrique par métrique."""
    precedent = json.loads(chemin.read_text(encoding="utf-8"))["resume"]
    print(f"\n{'=' * 72}\nCOMPARAISON avec {chemin.name}\n{'=' * 72}")
    for cle, valeur in actuel.items():
        ancien = precedent.get(cle)
        if isinstance(valeur, int | float) and isinstance(ancien, int | float):
            delta = valeur - ancien
            fleche = "→" if delta == 0 else ("▲" if delta > 0 else "▼")
            print(f"  {cle:28s} {ancien}  {fleche}  {valeur}   ({delta:+.3f})")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api", default="http://localhost:8011", help="URL de l'agent")
    parser.add_argument("--golden", type=Path, default=GOLDEN, help="Jeu doré")
    parser.add_argument("--out", type=Path, help="Fichier où écrire la campagne")
    parser.add_argument("--compare", type=Path, help="Campagne précédente à comparer")
    parser.add_argument("--timeout", type=float, default=600.0, help="Délai par question (s)")
    args = parser.parse_args()

    questions = charger_questions(args.golden)
    print(f"{len(questions)} questions — agent : {args.api}")

    lignes = []
    for index, question in enumerate(questions, 1):
        print(f"  [{index}/{len(questions)}] {question['id']} …", end="", flush=True)
        try:
            reponse = interroger(args.api, question, args.timeout)
        except Exception as exc:  # noqa: BLE001
            print(f" ÉCHEC : {exc}")
            continue
        ligne = evaluer(question, reponse)
        lignes.append(ligne)
        print(f" {ligne['contextes']} sources, {ligne['citations']} citations")

    if not lignes:
        print("Aucune question n'a abouti.")
        return 1

    resume = resumer(lignes)
    langues = par_langue(lignes)
    afficher(resume, langues, lignes)

    if args.compare and args.compare.exists():
        comparer(resume, args.compare)

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(
            json.dumps({"resume": resume, "par_langue": langues, "questions": lignes},
                       ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"\nCampagne écrite dans {args.out}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
