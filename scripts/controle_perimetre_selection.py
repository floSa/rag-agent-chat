#!/usr/bin/env python
"""Contrôle de périmètre : les `gold_element_ids` et les identifiants de la chaîne.

Un rappel se calcule en intersectant deux ensembles d'identifiants. Si les deux
n'étaient pas de la même NATURE, le chiffre serait faux sans qu'aucune erreur
n'apparaisse — et c'est un chiffre faux publié comme un vrai. Ce contrôle établit
ce que `mesurer_selection.py` suppose, et il sort en 1 au premier désaccord.

**IL COUVRE LES TROIS NATURES QUE LE BANC TRAVERSE**, parce qu'un contrôle
partiel laisse une branche aveugle :

  1. `ChunkResult.element_id` — ce que le classement du reranker porte ;
  2. `SectionContext.element_id` — la GRAINE passée à `reconstruct_section` ;
  3. les identifiants lus dans le markdown soumis, `[src:ID]` **et** `[img:ID]` —
     deux familles distinctes, la seconde étant la seule voie d'une illustration.

**ET IL ÉPROUVE LA COMPARAISON ELLE-MÊME.** Un double qui reconnaît par SUFFIXE
a déjà fait accuser un code juste dans ce dépôt : `/api/version` se termine par
`/version`. Le banc compare par `&` d'ensembles, donc par égalité exacte ; ce
contrôle le prouve en montrant qu'un suffixe et un préfixe d'un identifiant
VRAI sont rejetés, là où un `endswith` ou un `in` les accepterait.

    uv run --no-sync python scripts/controle_perimetre_selection.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Exigence 3 du contrat avec le pipeline : `element_id` déterministe, 10
# hexadécimaux. `graph_context._VALID_VID` la fait respecter côté agent.
FORME = re.compile(r"^[a-f0-9]{10}$")

# Questions de sondage, choisies pour traverser les deux langues du jeu. Elles
# n'ont pas à être nombreuses : ce contrôle porte sur la NATURE des
# identifiants, pas sur le rappel.
N_SONDAGE = 12


def echec(message: str, desaccords: list[str]) -> None:
    print(f"[NON] {message}")
    for ligne in desaccords[:10]:
        print(f"      {ligne}")


def main() -> int:
    from src.agent.graph import _BLOC_IMG, _BLOC_SRC, element_ids_cites, element_ids_presents
    from src.agent.graph_context import reconstruct_section
    from src.agent.retriever import rerank, retrieve

    jeu = ROOT / "tests" / "fixtures" / "golden_qa_generated.yaml"
    data = yaml.safe_load(jeu.read_text(encoding="utf-8"))
    questions = [q for q in data["questions"] if q.get("gold_element_ids")]
    golds = sorted({eid for q in questions for eid in q["gold_element_ids"]})

    rate = 0

    # ── 1. La forme, côté jeu ────────────────────────────────────────────────
    mal_formes = [eid for eid in golds if not FORME.fullmatch(eid)]
    if mal_formes:
        echec(f"{len(mal_formes)} gold_element_ids hors forme ^[a-f0-9]{{10}}$", mal_formes)
        rate = 1
    else:
        print(f"[OK ] {len(golds)} gold_element_ids, tous en ^[a-f0-9]{{10}}$")

    # ── 2. La forme, côté chaîne, sur les TROIS natures ──────────────────────
    natures: dict[str, set[str]] = {
        "classement": set(), "graine": set(), "src": set(), "img": set()
    }
    blocs_a_un_id = 0
    blocs_total = 0
    gold_retrouves = 0
    for q in questions[:N_SONDAGE]:
        ranking = rerank(q["question"], retrieve(q["question"]))
        natures["classement"].update(c.element_id for c in ranking)
        gold_ici = False
        for chunk in ranking[:3]:
            ctx = reconstruct_section(chunk.element_id)
            natures["graine"].add(ctx.element_id)
            natures["src"].update(element_ids_cites(ctx.markdown, _BLOC_SRC))
            natures["img"].update(element_ids_cites(ctx.markdown, _BLOC_IMG))
            # UN bloc, UN identifiant. `_ELEMENT_ID` n'est pas ancré : s'il
            # mordait dans un identifiant plus long, il en tirerait un morceau
            # qui a la bonne forme sans être le bon élément — un faux muet.
            for motif in (_BLOC_SRC, _BLOC_IMG):
                for bloc in motif.findall(ctx.markdown):
                    blocs_total += 1
                    blocs_a_un_id += 1 if len(re.findall(r"[a-f0-9]{10}", bloc)) == 1 else 0
            if set(q["gold_element_ids"]) & set(element_ids_presents(ctx.markdown)):
                gold_ici = True
        # PAR QUESTION, ET LE DÉNOMINATEUR EST DES QUESTIONS. Compté par
        # section, ce numérateur dépassait son dénominateur — il s'affichait
        # « 17/12 », un rapport qu'aucune lecture ne rend juste.
        gold_retrouves += 1 if gold_ici else 0

    for nom, ensemble in natures.items():
        hors = [eid for eid in ensemble if not FORME.fullmatch(eid)]
        if hors:
            echec(f"nature « {nom} » : {len(hors)} identifiant(s) hors forme", hors)
            rate = 1
        elif not ensemble:
            # UNE NATURE VIDE N'EST PAS UNE NATURE CONFORME. Sans cette branche,
            # « aucun hors-forme » se lirait comme un succès là où rien n'a été
            # échantillonné — et la branche des illustrations serait aveugle.
            echec(f"nature « {nom} » : AUCUN identifiant échantillonné", ["rien à contrôler"])
            rate = 1
        else:
            print(f"[OK ] nature « {nom} » : {len(ensemble)} identifiant(s), tous en forme")

    if blocs_total and blocs_a_un_id == blocs_total:
        print(f"[OK ] {blocs_total} marqueurs lus, chacun rendant exactement 1 identifiant")
    else:
        echec(
            f"{blocs_total - blocs_a_un_id} marqueur(s) sur {blocs_total} ne rendent pas 1 seul "
            "identifiant",
            ["l'extraction a mordu, ou un marqueur est vide"],
        )
        rate = 1

    # ── 3. La chaîne rend-elle vraiment des golds ? ──────────────────────────
    # CONTRÔLE POSITIF DE L'INSTRUMENT : un ensemble « atteints » systématiquement
    # disjoint des golds rendrait 0 % de rappel sans dire si la chaîne est cassée
    # ou si les identifiants ne se parlent pas.
    if gold_retrouves:
        print(f"[OK ] {gold_retrouves}/{N_SONDAGE} sondages où un gold est PRÉSENT au prompt")
    else:
        echec("aucun gold retrouvé sur le sondage : les deux ensembles ne se parlent pas", [])
        rate = 1

    # ── 4. L'égalité est EXACTE, ni suffixe ni préfixe ───────────────────────
    vrais = natures["classement"] | natures["src"]
    temoin = sorted(vrais)[0]
    leurres = {
        "suffixe": temoin[3:],
        "prefixe": temoin[:7],
        "englobant": "ff" + temoin,
        "meme_forme": "0123456789",
    }
    faux_positifs = [nom for nom, leurre in leurres.items() if leurre in vrais]
    if faux_positifs:
        echec(f"leurre(s) reconnu(s) par le jeu réel : {faux_positifs}", [])
        rate = 1
    else:
        # Ce que le banc ferait : `&` d'ensembles. Ce qu'un test relâché ferait :
        # `endswith`. Les deux sont joués sur les MÊMES leurres, et leur
        # désaccord est ce qui rend le contrôle concluant — s'ils s'accordaient,
        # ce contrôle ne distinguerait pas une comparaison exacte d'une laxiste.
        par_egalite = {nom for nom, leurre in leurres.items() if {leurre} & vrais}
        par_suffixe = {
            nom
            for nom, leurre in leurres.items()
            if any(v.endswith(leurre) or leurre.endswith(v) for v in vrais)
        }
        print(f"[OK ] témoin {temoin} : égalité exacte accepte {sorted(par_egalite) or 'rien'}, "
              f"un endswith en accepterait {sorted(par_suffixe)}")
        if not par_suffixe:
            echec(
                "le test laxiste n'accepte AUCUN leurre : ce contrôle ne prouve rien",
                ["il ne distingue pas l'égalité exacte d'un endswith"],
            )
            rate = 1

    print("\nDÉSACCORD" if rate else "\n0 désaccord.")
    return rate


if __name__ == "__main__":
    sys.exit(main())
