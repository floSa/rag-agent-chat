#!/usr/bin/env python
"""Ce que la SELECTION laisse passer, sur un jeu a ancrages multiples et disperses.

`scripts/mesurer_selection.py` mesure le quatrieme etage sur des jeux dont les
questions portent UN ancrage (le jeu de reglage) ou quelques-uns (le jeu du
pipeline). Sa grandeur principale est « au moins un ancrage au prompt », et sur
un jeu mono-ancrage elle se confond avec le rappel. Ce banc-ci mesure ce que ce
jeu-la ne pouvait pas mesurer, et il ajoute quatre choses :

1. **LE RANG DES ANCRAGES A CHAQUE ETAGE** — dense, fusion, rerank, selection —
   et non le seul resultat final. Un ancrage perdu au prompt n'a pas la meme
   cause selon qu'il n'est jamais entre dans les 50 candidats ou qu'il est entre
   au rang 7 et que la troncature a 3 l'a coupe. Seule la seconde est une
   question de selection.
2. **LE COMPTE DES QUESTIONS DONT *TOUS* LES ANCRAGES ARRIVENT.** C'est la seule
   grandeur qui puisse bouger sur ce jeu : « au moins un » se sature des k=1 par
   construction — chaque question a deux ancrages et le retrieval en trouve
   presque toujours un.
3. **LES DEUX MESURES DE PRESENCE, ET LEUR ECART.** Le §4.67 b a mesure que le
   banc de la selection teste la presence de l'IDENTIFIANT d'ancrage dans le
   prompt, pas celle de son TEXTE : deux questions comptees « perdues » avaient
   leur texte au prompt, porte par des fragments freres d'une puce vide. Les
   deux comptes sont donc publies cote a cote, et leur ecart avec eux.
4. **LE CONTROLE POSITIF DANS LES DEUX SENS, EN QUESTIONS.** Un jeu qui rendrait
   le meme chiffre a k=1 et a k=RERANK_TOP_K serait aveugle a la selection,
   comme l'est le jeu de reglage — et ce banc doit le DIRE, pas le taire.

AUCUNE REPONSE N'EST GENEREE. Le banc rejoue `retrieve` → `rerank` →
`ranking[:k]` → `reconstruct_section` → `fit_prompt`, et lit le markdown
REELLEMENT soumis. Seules les traductions de questions passent par le moteur, et
elles sont EXIGEES en cache : une traduction manquante deplacerait le rappel
translinguistique en silence.

    uv run --no-sync python scripts/mesurer_dispersion.py \\
        --jeu tests/fixtures/jeu_ancrages_disperses.yaml \\
        --sortie runs/2026-09-24-dispersion.json
"""

from __future__ import annotations

import argparse
import collections
import json
import re
import sys
import time
import unicodedata
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from mesurer_selection import (  # noqa: E402 — `scripts/` n'est pas un paquet
    CACHE_TRADUCTIONS,
    charger_questions,
    sections_pour_k,
    wilson,
)

# Part des jetons du chunk qu'il faut retrouver dans le markdown pour dire que
# le TEXTE de l'ancrage est arrive. Ce n'est pas 1,0, et c'est mesure : le
# §4.67 b a relevé 20 jetons sur 22 et 55 sur 63 pour deux ancrages dont le
# texte ARRIVAIT bien — la reconstruction reecrit la mise en forme, elle ne
# recopie pas le chunk octet pour octet. Le seuil est publie avec le resultat,
# et le banc rend AUSSI la part brute par ancrage pour qu'on puisse le rejuger
# sans relancer la campagne.
_SEUIL_TEXTE = 0.8
# Jetons de moins de 3 caracteres ecartes : « de », « la », « of » se retrouvent
# dans n'importe quel markdown et rendraient la mesure de texte toujours vraie.
_MIN_JETON = 3


def jetons(texte: str) -> set[str]:
    """Jetons comparables : minuscules, sans accents, jetons courts ecartes."""
    decompose = unicodedata.normalize("NFKD", texte.lower())
    sans_accents = "".join(c for c in decompose if not unicodedata.combining(c))
    return {t for t in re.findall(r"\w+", sans_accents) if len(t) >= _MIN_JETON}


def rang_de(element_id: str, classement: list[Any]) -> int | None:
    """Rang 1-indexe d'un ancrage dans un classement, `None` s'il en est absent.

    1-indexe et non 0-indexe : le registre parle de « rang 1 » et de « rang 2 »,
    et une table des rangs qui commencerait a 0 se lirait de travers a cote des
    tableaux du §4.67.
    """
    for rang, chunk in enumerate(classement, 1):
        if chunk.element_id == element_id:
            return rang
    return None


def mesurer_une_question(
    question: str, traduction: str | None, ancrages: list[str], valeurs_k: list[int]
) -> dict[str, Any]:
    """Rejoue la chaine une fois, et rend l'etat de chaque ancrage a chaque etage."""
    from src.agent.graph import element_ids_presents
    from src.agent.graph_context import reconstruct_section
    from src.agent.llm import fit_prompt
    from src.agent.retriever import _dense_search, full_texts, rerank, retrieve
    from src.agent.settings import settings

    # LES QUATRE ETAGES, JOUES SEPAREMENT. `retrieve` fusionne jusqu'a quatre
    # classements ; pour lire le rang DENSE il faut le demander a part, et c'est
    # le meme appel que `retrieve` fait en interne, aux memes parametres.
    dense = _dense_search(question, settings.fetch_k)
    fusion = retrieve(question, translation=traduction)
    classement = rerank(question, fusion)

    textes = full_texts(ancrages)

    sections: dict[str, Any] = {}
    echecs: list[str] = []
    for chunk in classement:
        try:
            sections[chunk.element_id] = reconstruct_section(chunk.element_id)
        except Exception as panne:  # noqa: BLE001 — meme absorption que `graph.node_reconstruct_context`, et COMPTEE
            echecs.append(f"{chunk.element_id}: {type(panne).__name__}: {panne}")

    rangs = {
        eid: {
            "dense": rang_de(eid, dense),
            "fusion": rang_de(eid, fusion),
            "rerank": rang_de(eid, classement),
        }
        for eid in ancrages
    }

    par_k: dict[str, Any] = {}
    for k in valeurs_k:
        contextes = sections_pour_k([c.element_id for c in classement], sections, k)
        fit = fit_prompt(question, contextes, [])
        markdown = "\n\n".join(ctx.markdown for ctx in fit.contexts)
        atteints = set()
        for ctx in fit.contexts:
            atteints.update(element_ids_presents(ctx.markdown))
        jetons_prompt = jetons(markdown)

        etat_ancrages: dict[str, Any] = {}
        for eid in ancrages:
            # LA PRESENCE DE L'IDENTIFIANT : egalite EXACTE de chaines, jamais un
            # `endswith` ni une inclusion — ce dépôt a déjà fait accuser un code
            # juste par un test de suffixe.
            par_identifiant = eid in atteints
            # LA PRESENCE DU TEXTE : la part des jetons du chunk retrouves dans
            # le markdown soumis. Un ancrage sans texte dans les vecteurs rend
            # une part `None`, et n'est compte NI present NI absent — le taire
            # ferait passer une mesure impossible pour une mesure negative.
            corps = (textes.get(eid) or "").strip()
            attendus = jetons(corps)
            part = len(attendus & jetons_prompt) / len(attendus) if attendus else None
            etat_ancrages[eid] = {
                "identifiant": par_identifiant,
                "part_texte": None if part is None else round(part, 4),
                "texte": None if part is None else part >= _SEUIL_TEXTE,
            }
        par_k[str(k)] = {
            "ancrages": etat_ancrages,
            "n_sections_retenues": len(fit.contexts),
            "sections_ecartees": fit.dropped_contexts,
            "n_elements_au_prompt": len(atteints),
            # LE RANG DE SELECTION : le rang du premier ancrage qui SURVIT a la
            # troncature a k. C'est l'etage que ce banc vient mesurer.
            "graines_retenues": [c.element_id for c in classement[:k]],
        }

    return {
        "rangs": rangs,
        "n_dense": len(dense),
        "n_fusion": len(fusion),
        "n_rerank": len(classement),
        "par_k": par_k,
        "echecs_reconstruction": echecs,
    }


def question_complete(ancrages: dict[str, Any], nature: str) -> bool:
    """TOUS les ancrages de la question sont-ils arrives, selon `nature` ?

    C'EST LA SEULE GRANDEUR QUI BOUGE SUR CE JEU, et elle a un site unique pour
    cette raison. « Au moins un ancrage » se sature des k=1 par construction —
    chaque question en porte deux et le retrieval en trouve presque toujours un
    — donc un banc qui publierait `any` la ou il faut `all` rendrait un plateau
    et le lirait comme « k ne sert a rien ». C'est exactement la confusion que
    le §4.67 a payee sur le jeu de reglage.

    Pour le TEXTE, les ancrages non mesurables — aucun texte dans les vecteurs —
    sont ECARTES du `all`, et une question dont AUCUN ancrage n'est mesurable
    rend `False` : la compter reussie ferait passer une mesure impossible pour
    une mesure positive.
    """
    if nature == "identifiant":
        return all(a["identifiant"] for a in ancrages.values())
    mesurables = [a["texte"] for a in ancrages.values() if a["texte"] is not None]
    return bool(mesurables) and all(mesurables)


def histogramme_des_rangs(lignes: list[dict[str, Any]], etage: str) -> dict[str, int]:
    """Combien d'ANCRAGES a chaque tranche de rang, pour un etage.

    Les tranches sont cumulatives comme celles du §4.67, et `absent` est compte
    SEPAREMENT : un ancrage jamais entre dans les candidats et un ancrage entre
    au rang 40 ne se reparent pas de la meme facon, et les confondre dans un
    « > 10 » effacerait la distinction.
    """
    seuils = [1, 2, 3, 5, 10, 20, 50]
    compte = {f"<= {s}": 0 for s in seuils}
    compte["au-dela"] = 0
    compte["absent"] = 0
    for ligne in lignes:
        for rang in (r[etage] for r in ligne["rangs"].values()):
            if rang is None:
                compte["absent"] += 1
                continue
            place = False
            for s in seuils:
                if rang <= s:
                    compte[f"<= {s}"] += 1
                    place = True
                    break
            if not place:
                compte["au-dela"] += 1
    return compte


def main() -> int:  # noqa: PLR0915 — une campagne, lue de haut en bas
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--jeu", type=Path, default=ROOT / "tests" / "fixtures" / "jeu_ancrages_disperses.yaml"
    )
    parser.add_argument("--valeurs", default="1,2,3,4,5,6,7,8,9,10")
    parser.add_argument("--sortie", type=Path, default=None)
    parser.add_argument("--limite", type=int, default=0)
    args = parser.parse_args()

    valeurs_k = sorted({int(v) for v in args.valeurs.split(",")})
    questions = charger_questions(args.jeu)
    if args.limite:
        questions = questions[: args.limite]

    # LE CACHE EST EXIGE, PAS FABRIQUE — meme refus que `mesurer_selection.py`,
    # et pour la meme raison : ce banc n'appelle aucun LLM, et une traduction
    # manquante retirerait la question de son versant translinguistique en
    # deplacant le rappel sans un mot. Le cache versionne du 23 septembre 2026
    # portait 130 entrees pour un jeu de 130 questions et une intersection NULLE
    # avec lui : c'est le refus, et non la taille, qui l'a attrape.
    if not CACHE_TRADUCTIONS.exists():
        print(f"ABSENT : {CACHE_TRADUCTIONS}. Joue d'abord scripts/sweep_retrieval.py.")
        return 2
    traductions: dict[str, str] = json.loads(CACHE_TRADUCTIONS.read_text(encoding="utf-8"))
    manquantes = [q["id"] for q in questions if q["question"] not in traductions]
    if manquantes:
        print(
            f"REFUS : {len(manquantes)} question(s) sans traduction en cache "
            f"({', '.join(manquantes[:5])}…). Le rappel translinguistique serait fausse."
        )
        return 2

    print(f"{len(questions)} questions avec ancrage, k ∈ {valeurs_k}")

    lignes: list[dict[str, Any]] = []
    echecs_totaux: list[str] = []
    t_debut = time.perf_counter()
    for index, q in enumerate(questions, 1):
        ancrages = list(q["gold_element_ids"])
        mesure = mesurer_une_question(
            q["question"], traductions.get(q["question"]), ancrages, valeurs_k
        )
        echecs_totaux.extend(mesure["echecs_reconstruction"])
        lignes.append(
            {
                "id": q["id"],
                "type": q.get("type", ""),
                "language": q.get("language", ""),
                "gold": ancrages,
                "rangs": mesure["rangs"],
                "n_dense": mesure["n_dense"],
                "n_fusion": mesure["n_fusion"],
                "n_rerank": mesure["n_rerank"],
                "k": mesure["par_k"],
            }
        )
        if index % 10 == 0:
            print(f"  {index}/{len(questions)}")

    secondes = time.perf_counter() - t_debut
    print(f"\nechecs de reconstruction absorbes : {len(echecs_totaux)}")
    for echec in echecs_totaux[:3]:
        print(f"  {echec}")

    n = len(lignes)
    ancrages_total = sum(len(r["gold"]) for r in lignes)
    # LES ANCRAGES SANS TEXTE DANS LES VECTEURS, comptes a part et DITS : leur
    # presence par texte n'est pas mesurable, et les compter absents ferait
    # passer une mesure impossible pour une mesure negative.
    sans_texte = sorted(
        {
            eid
            for r in lignes
            for eid, etat in r["k"][str(valeurs_k[0])]["ancrages"].items()
            if etat["part_texte"] is None
        }
    )

    resume: dict[str, Any] = {}
    for k in valeurs_k:
        cle = str(k)
        etats = [r["k"][cle]["ancrages"] for r in lignes]
        tous_id = sum(1 for e in etats if question_complete(e, "identifiant"))
        un_id = sum(1 for e in etats if any(a["identifiant"] for a in e.values()))
        tous_txt = sum(1 for e in etats if question_complete(e, "texte"))
        un_txt = sum(1 for e in etats if any(a["texte"] for a in e.values()))
        anc_id = sum(1 for e in etats for a in e.values() if a["identifiant"])
        anc_txt = sum(1 for e in etats for a in e.values() if a["texte"])
        bas, haut = wilson(tous_id, n)
        resume[cle] = {
            "questions": n,
            "questions_tous_ancrages_identifiant": tous_id,
            "questions_un_ancrage_identifiant": un_id,
            "questions_tous_ancrages_texte": tous_txt,
            "questions_un_ancrage_texte": un_txt,
            "ancrages_total": ancrages_total,
            "ancrages_identifiant": anc_id,
            "ancrages_texte": anc_txt,
            "ecart_texte_moins_identifiant_ancrages": anc_txt - anc_id,
            "rappel_questions_tous": round(tous_id / n, 4) if n else None,
            "ic95_bas": round(bas, 4),
            "ic95_haut": round(haut, 4),
            "sections_retenues_moy": round(
                sum(r["k"][cle]["n_sections_retenues"] for r in lignes) / n, 2
            ) if n else None,
            "elements_au_prompt_moy": round(
                sum(r["k"][cle]["n_elements_au_prompt"] for r in lignes) / n, 2
            ) if n else None,
            "questions_avec_section_ecartee": sum(
                1 for r in lignes if r["k"][cle]["sections_ecartees"] > 0
            ),
        }

    def bascules(critere: str) -> list[dict[str, Any]]:
        sortie = []
        for petit, grand in zip(valeurs_k, valeurs_k[1:], strict=False):
            def tous(r: dict[str, Any], k: int) -> bool:
                return question_complete(r["k"][str(k)]["ancrages"], critere)

            gagnees = [r["id"] for r in lignes if not tous(r, petit) and tous(r, grand)]
            perdues = [r["id"] for r in lignes if tous(r, petit) and not tous(r, grand)]
            sortie.append(
                {"de": petit, "vers": grand, "gagnees": len(gagnees), "perdues": len(perdues),
                 "ids_gagnees": gagnees, "ids_perdues": perdues}
            )
        return sortie

    petit, grand = valeurs_k[0], valeurs_k[-1]
    controle = {
        "k_petit": petit,
        "k_grand": grand,
        "questions_tous_a_k_petit": resume[str(petit)]["questions_tous_ancrages_identifiant"],
        "questions_tous_a_k_grand": resume[str(grand)]["questions_tous_ancrages_identifiant"],
        "questions_gagnees_de_petit_a_grand": sum(
            1
            for r in lignes
            if not question_complete(r["k"][str(petit)]["ancrages"], "identifiant")
            and question_complete(r["k"][str(grand)]["ancrages"], "identifiant")
        ),
        "questions_perdues_de_petit_a_grand": sum(
            1
            for r in lignes
            if question_complete(r["k"][str(petit)]["ancrages"], "identifiant")
            and not question_complete(r["k"][str(grand)]["ancrages"], "identifiant")
        ),
    }
    # LA CONDITION DE RECETTE, ECRITE DANS LE BILAN ET NON LAISSEE AU LECTEUR :
    # un jeu qui rend le meme compte a k=1 et a k grand est AVEUGLE a la
    # selection, et le banc doit le dire au lieu de publier un plateau.
    controle["voit_k"] = (
        controle["questions_tous_a_k_grand"] > controle["questions_tous_a_k_petit"]
    )

    histogrammes = {e: histogramme_des_rangs(lignes, e) for e in ("dense", "fusion", "rerank")}

    # L'ETAGE DE SELECTION, et il ne se lit pas comme les trois autres. Un
    # ancrage n'y a pas de « rang » : il a un k MINIMAL a partir duquel il
    # atteint le prompt. C'est la meme grandeur vue de l'autre cote — un rang
    # dans le classement reranque ne dit pas a quel k l'ancrage arrive, parce
    # que la deduplication par section et la reconstruction deplacent les deux
    # l'un par rapport a l'autre (§4.67 d, G-053 : rang 2 au reranker, jamais au
    # prompt). Les deux sont donc publies, et leur ECART est la trouvaille
    # possible.
    for ligne in lignes:
        ligne["k_minimal"] = {}
        for eid in ligne["gold"]:
            premier_id = next(
                (k for k in valeurs_k if ligne["k"][str(k)]["ancrages"][eid]["identifiant"]), None
            )
            premier_txt = next(
                (k for k in valeurs_k if ligne["k"][str(k)]["ancrages"][eid]["texte"]), None
            )
            ligne["k_minimal"][eid] = {"identifiant": premier_id, "texte": premier_txt}
    def par_k_minimal(nature: str) -> dict[str, int]:
        compte = collections.Counter(
            ligne["k_minimal"][eid][nature] for ligne in lignes for eid in ligne["gold"]
        )
        # `None` en dernier, et sous son nom : un ancrage qui n'arrive a AUCUN k
        # n'est pas « k = 0 », et l'ecrire ainsi le ferait lire comme le cas le
        # plus favorable.
        return {
            ("aucun" if k is None else str(k)): compte[k]
            for k in sorted(compte, key=lambda x: (x is None, x))
        }

    histogrammes["selection_k_minimal"] = par_k_minimal("identifiant")
    histogrammes["selection_k_minimal_texte"] = par_k_minimal("texte")

    print(f"\n{'k':>3s} {'Q toutes (id)':>14s} {'IC95':>16s} {'Q toutes (txt)':>15s} "
          f"{'anc. id':>8s} {'anc. txt':>9s} {'sect.':>6s} {'elem.':>6s}")
    for k in valeurs_k:
        r = resume[str(k)]
        print(
            f"{k:>3d} {r['questions_tous_ancrages_identifiant']:>14d} "
            f"{'[' + str(r['ic95_bas']) + ', ' + str(r['ic95_haut']) + ']':>16} "
            f"{r['questions_tous_ancrages_texte']:>15d} "
            f"{str(r['ancrages_identifiant']) + '/' + str(ancrages_total):>8} "
            f"{str(r['ancrages_texte']) + '/' + str(ancrages_total):>9} "
            f"{r['sections_retenues_moy']:>6} {r['elements_au_prompt_moy']:>6}"
        )

    print("\nRangs des ancrages par etage (cumulatif, `absent` compte a part) :")
    for etage in ("dense", "fusion", "rerank"):
        print(f"  {etage:>7s} : {histogrammes[etage]}")
    print("Selection — k MINIMAL auquel chaque ancrage atteint le prompt "
          "(`None` = a aucun k) :")
    print(f"  identifiant : {histogrammes['selection_k_minimal']}")
    print(f"  texte       : {histogrammes['selection_k_minimal_texte']}")

    print("\nBascules sur TOUS les ancrages (identifiant) :")
    for b in bascules("identifiant"):
        print(f"  k={b['de']:>2d} → k={b['vers']:>2d} : +{b['gagnees']}, -{b['perdues']}")

    print(
        f"\nCONTROLE POSITIF — k={petit} : {controle['questions_tous_a_k_petit']} questions ; "
        f"k={grand} : {controle['questions_tous_a_k_grand']} ; "
        f"+{controle['questions_gagnees_de_petit_a_grand']} gagnees, "
        f"-{controle['questions_perdues_de_petit_a_grand']} perdues ; "
        f"voit_k={controle['voit_k']}"
    )
    print(f"ancrages sans texte dans les vecteurs : {len(sans_texte)} {sans_texte[:5]}")

    bilan = {
        "jeu": str(args.jeu),
        "questions": n,
        "ancrages": ancrages_total,
        "valeurs_k": valeurs_k,
        "seuil_texte": _SEUIL_TEXTE,
        "resume": resume,
        "histogrammes_de_rang": histogrammes,
        "bascules_identifiant": bascules("identifiant"),
        "bascules_texte": bascules("texte"),
        "controle_positif": controle,
        "ancrages_sans_texte": sans_texte,
        "echecs_reconstruction": len(echecs_totaux),
        "par_strate": dict(collections.Counter(r["type"] for r in lignes)),
        "secondes_total": round(secondes, 1),
        "lignes": lignes,
    }
    if args.sortie:
        args.sortie.parent.mkdir(parents=True, exist_ok=True)
        args.sortie.write_text(
            json.dumps(bilan, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"\nBilan ecrit : {args.sortie}")
    print(f"Duree totale : {secondes:.1f} s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
