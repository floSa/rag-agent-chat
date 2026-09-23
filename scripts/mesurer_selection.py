#!/usr/bin/env python
"""Rappel APRÈS la sélection, pour plusieurs `AUTO_SELECT_TOP_K`, sans LLM.

`sweep_retrieval.py` s'arrête au reranking. Il mesure donc ce qui franchit le
troisième étage de la chaîne, et laisse le quatrième sans instrument :

    FETCH_K=50 → RETRIEVAL_TOP_K=50 → RERANK_TOP_K=10 → AUTO_SELECT_TOP_K=3

Ce banc mesure le quatrième. Il rejoue `node_reconstruct_context` puis le budget
de fenêtre, et lit ce qui atteint RÉELLEMENT le prompt — sans générer une seule
réponse.

**POURQUOI LA TRONCATURE DU CLASSEMENT NE SUFFIT PAS.** `graph.py:204` fait
`ranking[:top_k]` puis `reconstruct_section(eid)` pour chacun, et une section
reconstruite porte PLUSIEURS éléments : la fenêtre du graphe en ramène les
voisins. Un ancrage peut donc être ABSENT du top-k et PRÉSENT dans le prompt,
parce qu'il vit dans la section d'un chunk retenu. Mesurer `ranking[:k]` seul
sous-estimerait le rappel. Les deux grandeurs sont donc rendues côte à côte, et
leur écart est le travail de la reconstruction.

**CE QUE k NE COÛTE PAS.** Retrieval, reranking et reconstruction ne dépendent
PAS de k : le classement est le même, et les sections des k premiers sont un
sous-ensemble de celles du top-RERANK_TOP_K. Tout est donc calculé UNE FOIS par
question, puis chaque k rejoue la seule troncature. Balayer quatre valeurs coûte
le prix d'une seule.

    uv run --no-sync python scripts/mesurer_selection.py --valeurs 1,3,5,6,10
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

CACHE_TRADUCTIONS = ROOT / "runs" / ".traductions.json"

# Forme contractuelle d'un `element_id`, exigence 3 du contrat avec le pipeline
# et validée par `graph_context._VALID_VID`. Recopiée ici pour que le CONTRÔLE
# DE PÉRIMÈTRE soit lisible au site où il s'exerce.
FORME_ELEMENT_ID = r"^[a-f0-9]{10}$"


def charger_questions(chemin: Path) -> list[dict[str, Any]]:
    """Lit le jeu et ne garde que les questions qui portent un ancrage.

    Même geste que `sweep_retrieval.charger_questions`, et pour la même raison :
    sans passage attendu, une question ne dit rien du rappel. Le jeu en annonce
    138 ; **130** en portent un, et c'est le dénominateur de tout ce banc.
    """
    data = yaml.safe_load(chemin.read_text(encoding="utf-8"))
    return [q for q in data["questions"] if q.get("gold_element_ids")]


def wilson(succes: int, total: int, z: float = 1.96) -> tuple[float, float]:
    """Intervalle de Wilson à 95 %, sur une proportion binomiale.

    PAS l'intervalle normal : à n = 130 et des taux proches de 1, l'approximation
    normale sort des bornes au-dessus de 1 et donne une largeur fausse — c'est
    précisément le régime de ce banc.
    """
    if total == 0:
        return (0.0, 0.0)
    p = succes / total
    d = 1 + z * z / total
    centre = (p + z * z / (2 * total)) / d
    demi = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / d
    return (max(0.0, centre - demi), min(1.0, centre + demi))


def sections_pour_k(
    graines: list[str], sections: dict[str, Any], k: int
) -> list[Any]:
    """Les sections que `node_reconstruct_context` reconstruirait pour ce k.

    Reproduit `graph.py:204-222` et RIEN d'autre : on coupe le classement à k,
    puis on écarte les graines dont la section a déjà été vue. **k graines
    peuvent tomber dans MOINS de k sections** — deux chunks voisins partagent
    la leur — et compter k sections là où le graphe en rend moins ferait croire
    à un contexte plus large qu'il n'est.

    Une graine absente de `sections` est une reconstruction qui a échoué : elle
    est sautée, comme le nœud la saute, et l'appelant en tient le compte.
    """
    retenues: list[Any] = []
    vues: set[str] = set()
    for eid in graines[:k]:
        ctx = sections.get(eid)
        if ctx is not None and ctx.section_id not in vues:
            retenues.append(ctx)
            vues.add(ctx.section_id)
    return retenues


def mesurer_une_question(
    question: str,
    traduction: str | None,
    valeurs_k: list[int],
) -> dict[str, Any]:
    """Rejoue la chaîne complète pour une question, et rend un état par k.

    Le retrieval, le reranking et la reconstruction sont joués UNE fois ; seule
    la troncature est rejouée par valeur de k.
    """
    from src.agent.graph import element_ids_presents
    from src.agent.graph_context import reconstruct_section
    from src.agent.llm import fit_prompt
    from src.agent.retriever import rerank, retrieve

    chunks = retrieve(question, translation=traduction)
    ranking = rerank(question, chunks)

    # Reconstruction de TOUT le classement, une seule fois. Les échecs sont
    # gardés à part : `node_reconstruct_context` les absorbe et la source
    # DISPARAÎT de la réponse, ce qui déplace le rappel sans qu'aucune erreur
    # n'apparaisse — la même panne que les traductions manquantes du sweep.
    sections: dict[str, Any] = {}
    echecs: list[str] = []
    t0 = time.perf_counter()
    for chunk in ranking:
        try:
            sections[chunk.element_id] = reconstruct_section(chunk.element_id)
        except Exception as panne:  # noqa: BLE001 — absorption large ASSUMÉE, et DITE
            # Même geste que `graph.node_reconstruct_context`, qui absorbe pour
            # qu'une source illisible n'emporte pas la réponse. Ici la trace est
            # COMPTÉE et remontée : un banc qui perdrait des sections en silence
            # publierait un rappel bas sans dire qu'il mesure une panne.
            echecs.append(f"{chunk.element_id}: {type(panne).__name__}: {panne}")
    ms_reconstruction = (time.perf_counter() - t0) * 1000

    par_k: dict[int, dict[str, Any]] = {}
    for k in valeurs_k:
        graines = [c.element_id for c in ranking[:k]]
        contextes = sections_pour_k([c.element_id for c in ranking], sections, k)
        # Le budget de fenêtre, tel que `_build_messages` l'applique. Sans
        # historique : /answer en est dépourvu par construction.
        fit = fit_prompt(question, contextes, [])
        atteints: set[str] = set()
        for ctx in fit.contexts:
            atteints.update(element_ids_presents(ctx.markdown))
        par_k[k] = {
            "graines": graines,
            "atteints": sorted(atteints),
            "n_sections_candidates": len(contextes),
            "n_sections_retenues": len(fit.contexts),
            "sections_ecartees": fit.dropped_contexts,
        }

    return {
        "par_k": par_k,
        "n_classement": len(ranking),
        "echecs_reconstruction": echecs,
        "ms_reconstruction": round(ms_reconstruction, 1),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--golden", type=Path, default=ROOT / "tests" / "fixtures" / "golden_qa_generated.yaml"
    )
    parser.add_argument("--valeurs", default="1,3,5,6,10,20")
    parser.add_argument("--sortie", type=Path, default=None)
    parser.add_argument(
        "--limite", type=int, default=0, help="N premières questions (mise au point)"
    )
    args = parser.parse_args()

    valeurs_k = sorted({int(v) for v in args.valeurs.split(",")})

    questions = charger_questions(args.golden)
    if args.limite:
        questions = questions[: args.limite]

    # LE CACHE EST EXIGÉ, PAS FABRIQUÉ. Ce banc n'appelle aucun LLM ; une
    # traduction manquante retirerait la question de son versant translinguistique
    # et DÉPLACERAIT le rappel en silence. On refuse plutôt que de mesurer un jeu
    # amputé — `sweep_retrieval.py` sait les produire.
    if not CACHE_TRADUCTIONS.exists():
        print(f"ABSENT : {CACHE_TRADUCTIONS}. Joue d'abord scripts/sweep_retrieval.py.")
        return 2
    traductions: dict[str, str] = json.loads(CACHE_TRADUCTIONS.read_text(encoding="utf-8"))
    manquantes = [q["id"] for q in questions if q["question"] not in traductions]
    if manquantes:
        print(
            f"REFUS : {len(manquantes)} question(s) sans traduction en cache "
            f"({', '.join(manquantes[:5])}…). Le rappel translinguistique serait faussé."
        )
        return 2

    print(f"{len(questions)} questions avec ancrage, k ∈ {valeurs_k}")

    lignes: list[dict[str, Any]] = []
    echecs_totaux: list[str] = []
    ms_total = 0.0
    t_debut = time.perf_counter()
    for index, q in enumerate(questions, 1):
        mesure = mesurer_une_question(q["question"], traductions.get(q["question"]), valeurs_k)
        attendus = set(q["gold_element_ids"])
        echecs_totaux.extend(mesure["echecs_reconstruction"])
        ms_total += mesure["ms_reconstruction"]
        doc_langue = q.get("doc_language") or q.get("language", "")
        ligne: dict[str, Any] = {
            "id": q["id"],
            "gold": sorted(attendus),
            "translinguistique": bool(doc_langue) and doc_langue != q.get("language"),
            "n_classement": mesure["n_classement"],
            "k": {},
        }
        for k in valeurs_k:
            etat = mesure["par_k"][k]
            # ÉGALITÉ EXACTE d'identifiants, jamais un test de suffixe ni
            # d'inclusion de chaîne : un `endswith` a déjà fait accuser un code
            # juste dans ce dépôt. Les deux ensembles sont des ensembles de
            # chaînes, et `&` ne connaît que l'égalité.
            survivants_prompt = attendus & set(etat["atteints"])
            survivants_graine = attendus & set(etat["graines"])
            ligne["k"][str(k)] = {
                "n_gold_au_prompt": len(survivants_prompt),
                "n_gold_en_graine": len(survivants_graine),
                "au_moins_un_au_prompt": bool(survivants_prompt),
                "au_moins_un_en_graine": bool(survivants_graine),
                "n_sections_candidates": etat["n_sections_candidates"],
                "n_sections_retenues": etat["n_sections_retenues"],
                "sections_ecartees": etat["sections_ecartees"],
                "n_elements_au_prompt": len(etat["atteints"]),
            }
        lignes.append(ligne)
        if index % 20 == 0:
            print(f"  {index}/{len(questions)}")

    secondes = time.perf_counter() - t_debut

    # IMPRIMÉ MÊME À ZÉRO : un compteur qui ne s'affiche qu'au-dessus de zéro ne
    # se lit jamais comme « zéro », il se lit comme « rien n'a été mesuré ».
    print(f"\néchecs de reconstruction absorbés : {len(echecs_totaux)}")
    for echec in echecs_totaux[:3]:
        print(f"  {echec}")

    n = len(lignes)
    resume: dict[str, Any] = {}
    for k in valeurs_k:
        cle = str(k)
        au_prompt = sum(1 for r in lignes if r["k"][cle]["au_moins_un_au_prompt"])
        en_graine = sum(1 for r in lignes if r["k"][cle]["au_moins_un_en_graine"])
        bas, haut = wilson(au_prompt, n)
        # LA SECONDE GRANDEUR DEMANDÉE : parmi les ancrages d'une question,
        # combien survivent. Elle ne se distingue de la première que sur un jeu
        # où une question en porte PLUSIEURS — le jeu généré n'en porte qu'un,
        # le jeu du pipeline jusqu'à trois. **Aucun intervalle n'est publié
        # dessus** : les ancrages d'une même question ne sont pas indépendants
        # — ils vivent souvent dans la même section — et un Wilson les traiterait
        # comme des tirages séparés, donc rendrait un intervalle trop étroit.
        ancrages_total = sum(len(r["gold"]) for r in lignes)
        ancrages_au_prompt = sum(r["k"][cle]["n_gold_au_prompt"] for r in lignes)
        resume[cle] = {
            "questions": n,
            "gold_au_prompt": au_prompt,
            "ancrages_total": ancrages_total,
            "ancrages_au_prompt": ancrages_au_prompt,
            "rappel_ancrages": round(ancrages_au_prompt / ancrages_total, 4)
            if ancrages_total
            else None,
            "rappel_prompt": round(au_prompt / n, 4) if n else None,
            "ic95_bas": round(bas, 4),
            "ic95_haut": round(haut, 4),
            "gold_en_graine": en_graine,
            "rappel_graine": round(en_graine / n, 4) if n else None,
            "sections_retenues_moy": round(
                sum(r["k"][cle]["n_sections_retenues"] for r in lignes) / n, 2
            )
            if n
            else None,
            "elements_au_prompt_moy": round(
                sum(r["k"][cle]["n_elements_au_prompt"] for r in lignes) / n, 2
            )
            if n
            else None,
            "questions_avec_section_ecartee": sum(
                1 for r in lignes if r["k"][cle]["sections_ecartees"] > 0
            ),
        }

    # LES BASCULES, et c'est ce qui rend un écart jugeable. Les questions sont
    # APPARIÉES — la même question est jouée à tous les k — donc un écart de
    # pourcentages se lit sur les questions qui ont CHANGÉ d'état, jamais sur la
    # différence des taux. Les deux sens sont comptés : `perdues` doit valoir 0
    # quand k croît, et une valeur non nulle serait la trouvaille du banc.
    bascules: list[dict[str, Any]] = []
    for petit, grand in zip(valeurs_k, valeurs_k[1:], strict=False):
        gagnees = [
            r["id"]
            for r in lignes
            if not r["k"][str(petit)]["au_moins_un_au_prompt"]
            and r["k"][str(grand)]["au_moins_un_au_prompt"]
        ]
        perdues = [
            r["id"]
            for r in lignes
            if r["k"][str(petit)]["au_moins_un_au_prompt"]
            and not r["k"][str(grand)]["au_moins_un_au_prompt"]
        ]
        bascules.append(
            {
                "de": petit,
                "vers": grand,
                "gagnees": len(gagnees),
                "perdues": len(perdues),
                "ids_gagnees": gagnees,
                "ids_perdues": perdues,
            }
        )

    print(f"\n{'k':>4s} {'rappel prompt':>14s} {'IC95':>16s} {'n gold':>7s} "
          f"{'ancrages':>9s} {'rappel graine':>14s} {'sect.':>6s} {'élém.':>6s}")
    for k in valeurs_k:
        r = resume[str(k)]
        print(
            f"{k:>4d} {r['rappel_prompt']:>14} "
            f"{'[' + str(r['ic95_bas']) + ', ' + str(r['ic95_haut']) + ']':>16} "
            f"{r['gold_au_prompt']:>7d} "
            f"{str(r['ancrages_au_prompt']) + '/' + str(r['ancrages_total']):>9} "
            f"{r['rappel_graine']:>14} "
            f"{r['sections_retenues_moy']:>6} {r['elements_au_prompt_moy']:>6}"
        )

    print("\nBascules entre k consécutifs (questions concernées, pas des points) :")
    for b in bascules:
        print(f"  k={b['de']:>2d} → k={b['vers']:>2d} : +{b['gagnees']} gagnée(s), "
              f"-{b['perdues']} perdue(s)")

    bilan = {
        "questions": n,
        "valeurs_k": valeurs_k,
        "resume": resume,
        "bascules": bascules,
        "echecs_reconstruction": len(echecs_totaux),
        "secondes_total": round(secondes, 1),
        "ms_reconstruction_total": round(ms_total, 1),
        "lignes": lignes,
    }
    if args.sortie:
        args.sortie.parent.mkdir(parents=True, exist_ok=True)
        args.sortie.write_text(
            json.dumps(bilan, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"\nBilan écrit : {args.sortie}")
    print(f"Durée totale : {secondes:.1f} s dont {ms_total / 1000:.1f} s de reconstruction")
    return 0


if __name__ == "__main__":
    sys.exit(main())
