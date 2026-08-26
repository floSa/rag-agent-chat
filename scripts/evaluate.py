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

# Étages de latence publiés par `/answer` sous `timings`, plus le résidu et le
# total. Recopiés ici plutôt qu'importés : ce script tourne contre un service
# distant, dont la version peut différer de celle du dépôt — un étage absent de
# la réponse vaut zéro, il ne casse pas la campagne.
#
# `residu_ms` porte le temps qu'aucun étage ne réclame. Il est publié parce qu'un
# résidu large est en soi un résultat : c'est du temps que personne ne sait
# expliquer. `retrieval_ms` et `generation_ms` restent lus à part — ils sont dans
# tous les fichiers de `runs/` et les campagnes passées ne portent pas la
# partition.
ETAGES = (
    "rewrite_ms",
    "translation_ms",
    "dense_ms",
    "lexical_ms",
    "fusion_ms",
    "rerank_ms",
    "reconstruction_ms",
    "generation_ms",
    "residual_ms",
    "total_ms",
)


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


def precision_contexte(
    attendus_ids: set[str], contexts: list[dict[str, Any]]
) -> dict[str, Any]:
    """Précision du contexte réellement remis au LLM.

    Le rappel et le MRR mesurent le CLASSEMENT. La reconstruction par le graphe
    ne le change pas : elle change la COMPOSITION du contexte — une fenêtre de
    ±6 éléments dans la section, ±3 dans les voisines, plus la relecture du texte
    intégral. Les deux métriques ci-dessous sont donc les seules qu'une ablation
    du graphe déplace, et `part_utile_caracteres` la seule qui exposerait une
    fenêtre trop large.

    Trois décisions gouvernent le calcul, et chacune ferme un piège.

    **Le dénominateur, ce sont les sections RETENUES.** Après la troncature de
    `fit_prompt`, pas avant. Une métrique calculée sur les candidates mesure une
    intention ; celle qui compte mesure ce qui a été payé en tokens.

    **Une section écartée n'entre ni au numérateur ni au dénominateur.** Faute de
    place dans la fenêtre, elle n'est pas un contexte inutile : c'est un contexte
    NON PAYÉ. La compter comme du bruit ferait baisser la métrique au moment
    précis où le budget fait son travail.

    **Une question sans élément d'or est exclue.** Sur une `unanswerable`, la
    part utile vaut 0/N par construction : la moyenner avec les autres ferait
    baisser le chiffre sans qu'aucune dégradation ait eu lieu. Les huit exclues
    sont comptées dans le résumé — une métrique dont on ne sait pas sur combien
    de questions elle porte n'est pas lisible.

    Returns:
        Les trois métriques, `None` quand elles ne s'appliquent pas, et le
        dénominateur qui a servi.
    """
    # `retained` faux = reconstruite puis écartée par le budget. Un service qui
    # ne publie pas le champ ne retient donc RIEN ici, et `contextes_retenus`
    # tombe à zéro : la campagne exclut ces questions et le dit, au lieu de
    # calculer sur les candidates en croyant mesurer ce qui a été payé.
    retenus = [c for c in contexts if c.get("retained")]
    caracteres = {c["section_id"]: len(c.get("text") or "") for c in retenus}
    utiles = [c for c in retenus if attendus_ids & set(c.get("element_ids") or [])]
    total_caracteres = sum(caracteres.values())

    presents = {eid for c in retenus for eid in (c.get("element_ids") or [])}
    return {
        "contextes_retenus": len(retenus),
        "caracteres_retenus": total_caracteres,
        "taux_contexte_utile": len(utiles) / len(retenus) if attendus_ids and retenus else None,
        "part_utile_caracteres": (
            sum(caracteres[c["section_id"]] for c in utiles) / total_caracteres
            if attendus_ids and total_caracteres
            else None
        ),
        # Le rappel au niveau du contexte PAYÉ, à ne pas confondre avec
        # `rappel_elements`, qui se mesure sur la graine du retrieval. C'est la
        # fenêtre du graphe qui les sépare : un élément d'or ramené par la
        # fenêtre sans avoir été trouvé par la recherche a bel et bien atteint le
        # LLM, et seul celui-ci le voit.
        "rappel_contexte": (
            len(presents & attendus_ids) / len(attendus_ids) if attendus_ids else None
        ),
    }


def evaluer(question: dict, reponse: dict[str, Any]) -> dict[str, Any]:
    """Confronte une réponse à la vérité terrain de sa question."""
    contexts = reponse.get("contexts", [])
    citations = reponse.get("citations", [])
    texte = (reponse.get("answer") or "").lower()

    trouves_ids = {c["element_id"] for c in contexts}
    trouves_docs = {c.get("source_path", "") for c in contexts}
    # Classement complet de la recherche, avant la coupe qui décide de ce qui
    # part au LLM.
    classement = reponse.get("retrieved_element_ids") or []

    attendus_ids = set(question.get("gold_element_ids") or [])
    attendus_docs = set(question.get("gold_documents") or [])

    # Rang du premier attendu dans le classement, pour le MRR : il dit si le bon
    # passage était deuxième ou dix-huitième, là où un rappel binaire les
    # confond.
    rang = next((i for i, eid in enumerate(classement, 1) if eid in attendus_ids), None)
    rappel_recherche = (
        len(set(classement) & attendus_ids) / len(attendus_ids) if attendus_ids else None
    )

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

    # Une question posée dans une autre langue que son document est le cas
    # difficile : c'est celui qu'un modèle monolingue rate systématiquement.
    doc_langue = question.get("doc_language") or question.get("language", "")

    # La partition du temps, étage par étage. Un service plus ancien ne la rend
    # pas : les étages valent alors zéro, et le résumé le dira en affichant un
    # total nul plutôt qu'en omettant les lignes.
    etapes = reponse.get("timings") or {}
    chronos = {cle: int(etapes.get(cle) or 0) for cle in ETAGES}
    # `generation_ms` existe des deux côtés : la partition fait foi quand elle est
    # là, le champ historique sert de repli. Sans ce repli, brancher la campagne
    # sur un service sans partition remplacerait en silence une latence de
    # génération réelle par un zéro.
    chronos["generation_ms"] = chronos["generation_ms"] or int(
        reponse.get("generation_ms") or 0
    )

    return {
        "id": question["id"],
        "langue": question.get("language", ""),
        "translinguistique": bool(doc_langue) and doc_langue != question.get("language", ""),
        "type": question.get("type", ""),
        "rappel_elements": rappel_elements,
        "rappel_recherche": rappel_recherche,
        "rang_reciproque": 1.0 / rang if rang else (0.0 if attendus_ids else None),
        "rappel_documents": rappel_documents,
        "abstention_correcte": a_refuse if sans_reponse else None,
        "hallucination_probable": (not a_refuse) if sans_reponse else None,
        "citations": len(citations),
        "citations_completes": completes,
        "taux_citation_complete": completes / len(citations) if citations else None,
        "contextes": len(contexts),
        "contextes_ecartes": reponse.get("dropped_contexts", 0),
        "langues_sources": sorted({c.get("language", "") for c in contexts if c.get("language")}),
        **precision_contexte(attendus_ids, contexts),
        # Agrégat historique — recherche + reranking — présent dans tous les
        # fichiers de `runs/`. Ce n'est PAS un étage : il contient `dense_ms`,
        # `lexical_ms`, `fusion_ms` et `rerank_ms`, et l'additionner à la
        # partition doublerait le comptage de toute la recherche.
        "retrieval_ms": reponse.get("retrieval_ms", 0),
        **chronos,
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

    return {
        "questions": len(lignes),
        "rappel_recherche": _moyenne([r["rappel_recherche"] for r in lignes]),
        "rappel_elements": _moyenne([r["rappel_elements"] for r in lignes]),
        "mrr": _moyenne([r["rang_reciproque"] for r in lignes]),
        "rappel_documents": _moyenne([r["rappel_documents"] for r in lignes]),
        "taux_citation_complete": _moyenne([r["taux_citation_complete"] for r in lignes]),
        "citations_par_reponse": _moyenne([float(r["citations"]) for r in lignes]),
        "abstention_correcte": (
            round(sum(1 for r in sans_reponse if r["abstention_correcte"]) / len(sans_reponse), 3)
            if sans_reponse
            else None
        ),
        "contextes_ecartes_total": sum(r["contextes_ecartes"] for r in lignes),
        # ─── Précision du contexte ────────────────────────────────────────────
        "taux_contexte_utile": _moyenne([r["taux_contexte_utile"] for r in lignes]),
        "part_utile_caracteres": _moyenne([r["part_utile_caracteres"] for r in lignes]),
        "rappel_contexte": _moyenne([r["rappel_contexte"] for r in lignes]),
        # Sur combien de questions les trois lignes ci-dessus portent, et
        # combien sont écartées et pourquoi. Une métrique dont on ne sait pas sur
        # combien de questions elle porte n'est pas lisible — et une moyenne qui
        # a silencieusement perdu la moitié du jeu ne se distingue pas d'une
        # moyenne saine.
        "precision_contexte_sur": sum(
            1 for r in lignes if r["taux_contexte_utile"] is not None
        ),
        "precision_contexte_exclues_sans_or": sum(
            1 for r in lignes if r["rappel_contexte"] is None
        ),
        "precision_contexte_exclues_sans_retenue": sum(
            1
            for r in lignes
            if r["rappel_contexte"] is not None and r["taux_contexte_utile"] is None
        ),
        "caracteres_retenus_p50": _centile([r["caracteres_retenus"] for r in lignes], 0.5),
        "caracteres_retenus_p95": _centile([r["caracteres_retenus"] for r in lignes], 0.95),
        "retrieval_ms_p50": _centile(retrieval, 0.5),
        "retrieval_ms_p95": _centile(retrieval, 0.95),
        # p50 ET p95 par étage : une moyenne de latence cache la queue, et c'est
        # la queue qui décide de l'expérience.
        **{
            f"{cle}_{nom}": _centile([r.get(cle, 0) for r in lignes], part)
            for cle in ETAGES
            for nom, part in (("p50", 0.5), ("p95", 0.95))
        },
    }


def _tranche(sous_ensemble: list[dict]) -> dict[str, Any]:
    return {
        "questions": len(sous_ensemble),
        "rappel_recherche": _moyenne([r["rappel_recherche"] for r in sous_ensemble]),
        "rappel_elements": _moyenne([r["rappel_elements"] for r in sous_ensemble]),
        "mrr": _moyenne([r["rang_reciproque"] for r in sous_ensemble]),
        "rappel_documents": _moyenne([r["rappel_documents"] for r in sous_ensemble]),
        "taux_citation_complete": _moyenne([r["taux_citation_complete"] for r in sous_ensemble]),
        "part_utile_caracteres": _moyenne([r["part_utile_caracteres"] for r in sous_ensemble]),
    }


def par_langue(lignes: list[dict]) -> dict[str, Any]:
    """Le corpus est mixte : une moyenne globale masquerait un écart par langue."""
    resultat = {
        langue: _tranche([r for r in lignes if r["langue"] == langue])
        for langue in sorted({r["langue"] for r in lignes if r["langue"]})
    }
    # Découpe orthogonale : la difficulté ne vient pas de la langue de la
    # question, mais de l'écart entre elle et celle du document.
    translinguistiques = [r for r in lignes if r["translinguistique"]]
    if translinguistiques:
        resultat["translinguistique"] = _tranche(translinguistiques)
        resultat["même langue"] = _tranche([r for r in lignes if not r["translinguistique"]])
    return resultat


def afficher(resume: dict, langues: dict, lignes: list[dict]) -> None:
    print(f"\n{'=' * 72}\nRÉSUMÉ — {resume['questions']} questions\n{'=' * 72}")
    for cle, valeur in resume.items():
        if cle != "questions":
            print(f"  {cle:28s} {valeur}")

    print("\nPar langue de la question")
    for langue, valeurs in langues.items():
        print(f"  [{langue}] {valeurs}")

    # Le rappel à l'ÉLÉMENT fait foi quand il est disponible : le rappel au
    # document laisse passer une recherche qui trouve le bon livre au mauvais
    # endroit.
    # Deux échecs distincts : jamais trouvé par la recherche, ou trouvé puis
    # écarté avant la génération. Le premier appelle un meilleur retrieval, le
    # second un meilleur reranking ou plus de sources.
    jamais = [r for r in lignes if r["rappel_recherche"] == 0.0]
    ecartes = [
        r for r in lignes if r["rappel_recherche"] and r["rappel_recherche"] > 0
        and r["rappel_elements"] == 0.0
    ]
    if ecartes:
        print(f"\nTrouvé par la recherche mais écarté avant le LLM — {len(ecartes)} question(s) :")
        for r in ecartes[:10]:
            print(f"  {r['id']} ({r['langue']}, {r['type']})")

    rate = jamais
    if rate:
        print(f"\nPassage attendu jamais trouvé — {len(rate)} question(s) :")
        for r in rate[:15]:
            langue = f"{r['langue']}→doc" if r["translinguistique"] else r["langue"]
            print(f"  {r['id']} ({langue}, {r['type']})")
        if len(rate) > 15:  # noqa: PLR2004
            print(f"  … et {len(rate) - 15} autres")

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
