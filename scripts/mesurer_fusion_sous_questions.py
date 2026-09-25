#!/usr/bin/env python
"""LA DECOMPOSITION REELLE de la question : ce que rend une VRAIE fusion des
sous-requetes dans UNE seule liste de dix, et ce qu'elle coute.

Le §4.77 a mesure un ORACLE de decomposition : **86** ancrages sur 120 et **28**
questions completes sur 60, contre **53** et **7** pour la requete unique de
production. Ce chiffre est une BORNE HAUTE, et la reserve est ecrite au site :
chaque ancrage y etait juge contre la sous-question qui lui convenait le mieux,
l'affectation etant prise au mieux des deux permutations. Une decomposition
REELLE n'a pas ce choix — elle lance les sous-requetes, elle FUSIONNE, et elle
rend une seule liste de dix.

CE BANC MESURE CETTE LISTE. Il ne touche pas a `src/` : il appelle
`retrieve`, `fuse` et `rerank` tels quels, aux reglages de production.

AUCUNE REPONSE N'EST GENEREE PAR LA MESURE. Le modele n'entre que dans la
FABRICATION du cache de decompositions (`--etape decomposition`), qui est un
producteur distinct, et le banc EXIGE ce cache sans jamais le fabriquer — meme
discipline que les caches de traductions et de sous-questions.

LES QUATRE VARIANTES, ET CE QUI LES SEPARE

- `unique_avec_traduction` — LA PRODUCTION, mot pour mot : `retrieve(question,
  translation=…)` puis `rerank(question, …)`. C'est elle que le CONTROLE POSITIF
  confronte a `runs/2026-09-24-recuperation-p50.json`.
- `unique_sans_traduction` — LA BASE APPARIEE des variantes. Les sous-questions
  n'ont pas de traduction en cache et le banc n'en fabrique pas ; comparer une
  fusion sans traduction a une requete unique AVEC traduction melerait deux
  changements en un, et le §4.77 a paye ce melange.
- `fusion_rerank_entiere` — les sous-questions sont recuperees separement, les
  classements sont fondus par RRF, et le reranker score contre la QUESTION
  ENTIERE.
- `fusion_rerank_sous_questions` — meme fusion, mais le reranker score contre
  CHAQUE sous-question et chaque candidat garde son MEILLEUR score.

    uv run --no-sync python scripts/mesurer_fusion_sous_questions.py \\
        --etape fusion --jeu tests/fixtures/jeu_ancrages_disperses.yaml \\
        --sortie runs/2026-09-25-fusion-disperse.json
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from mesurer_dispersion import jetons, rang_de  # noqa: E402 — `scripts/` n'est pas un paquet
from mesurer_recuperation import etat_des_stores, stores_stables  # noqa: E402 — idem
from mesurer_selection import charger_questions  # noqa: E402 — idem

# LE HAUT DU CLASSEMENT. Meme grandeur qu'aux §4.76 et §4.77, et elle ne depend
# PAS de `RERANK_TOP_K` : sans quoi la meme phrase designerait dix ancrages a
# profondeur de production et mille ailleurs, et les tableaux compareraient deux
# grandeurs portant un seul nom. C'est aussi le `k` de la production.
_SEUIL_TOP = 10

# LE NOMBRE MAXIMAL DE SOUS-QUESTIONS, ET IL EST UN REGLAGE DU BANC, PAS DU
# MODELE. Trois, et non deux : demander exactement deux sous-questions a une
# question qui n'en porte qu'un besoin FORCE une decomposition qui n'existe pas,
# et le banc mesurerait alors sa propre contrainte sur les jeux a besoin unique.
# C'est exactement ce que la non-regression doit pouvoir voir.
_MAX_SOUS_QUESTIONS = 3

# LE SEUIL DE QUASI-IDENTITE, et c'est LA REGLE ECRITE DU « rien a decomposer ».
# Une sous-question dont les jetons recouvrent la question entiere a ce point
# n'est pas une decomposition : c'est la question recopiee. Le banc le DIT et
# retombe sur la requete unique, plutot que de compter une variante qui ne
# differe de la base que par le bruit de la recopie.
_SEUIL_QUASI_IDENTIQUE = 0.9


def dans_le_haut(rang: int | None, seuil: int = _SEUIL_TOP) -> bool:
    """Le rang est-il dans le haut du classement, au sens des §4.76 et §4.77 ?"""
    return rang is not None and rang <= seuil


def jaccard(a: str, b: str) -> float:
    """Recouvrement des jetons de deux textes, 0,0 quand l'un des deux est vide.

    `0.0` et non `None` : ici la grandeur sert un SEUIL, et deux textes dont l'un
    ne porte aucun jeton ne sont pas quasi identiques — les declarer tels ferait
    retomber sur la requete unique une decomposition vide, qui doit au contraire
    etre comptee comme une panne.
    """
    ja, jb = jetons(a), jetons(b)
    if not ja or not jb:
        return 0.0
    return len(ja & jb) / len(ja | jb)


def decomposition_utilisable(
    question: str, sous_questions: list[str], seuil: float = _SEUIL_QUASI_IDENTIQUE
) -> tuple[bool, str]:
    """Y A-T-IL QUELQUE CHOSE A DECOMPOSER ? C'est la regle, et elle est ecrite.

    Trois refus, et chacun a sa phrase, parce qu'ils ne se lisent pas pareil :

    - `vide` — le modele n'a rendu aucune sous-question exploitable. C'est une
      PANNE du producteur, pas une question indecomposable, et les fondre
      cacherait un taux d'echec dans un taux de questions simples.
    - `une_seule` — le modele a rendu UNE sous-question. C'est sa facon de dire
      « il n'y a qu'un besoin », et c'est le cas nominal des jeux a besoin unique.
    - `quasi_identique` — il en a rendu plusieurs, mais TOUTES recouvrent la
      question entiere au-dela du seuil. Une fusion de copies de la question ne
      differe de la requete unique que par le bruit, et la compter comme une
      variante ferait passer ce bruit pour un effet de la decomposition.

    Dans les trois cas la variante RETOMBE SUR LA REQUETE UNIQUE, exactement :
    c'est le seul repli qu'un decomposeur reel dans `src/` pourrait tenir, et
    c'est ce qui rend la non-regression mesurable au lieu d'etre supposee.
    """
    propres = [s.strip() for s in sous_questions if s and s.strip()]
    if not propres:
        return (False, "vide")
    if len(propres) < 2:
        return (False, "une_seule")
    if all(jaccard(question, s) >= seuil for s in propres):
        return (False, "quasi_identique")
    return (True, "decomposee")


def fusionner_les_classements(classements: list[list[Any]], top_k: int) -> list[Any]:
    """LA FUSION DES SOUS-REQUETES EN UNE SEULE LISTE, et c'est `fuse` de `src/`.

    POURQUOI RRF, ET POURQUOI CELUI-LA. `retrieve` fond deja jusqu'a QUATRE
    classements par cette fonction — dense et lexical, pour la question et pour
    sa traduction — avec le meme `settings.rrf_k`. Fondre les sous-requetes par
    un autre moyen mesurerait une fusion que la production ne sait pas faire ;
    fondre par CELLE-CI mesure exactement le geste qui serait implementable dans
    `src/`, sans y ecrire une ligne.

    LES POIDS SONT EGAUX, ET C'EST UN CHOIX QU'IL FAUT DIRE. `fuse` accepte un
    poids par classement, et la production en donne un moindre a la traduction
    parce qu'elle sait laquelle merite moins de confiance. Ici rien ne le dit :
    les sous-questions sont soeurs, aucune n'est la requete d'origine, et leur
    donner des poids differents demanderait un critere que le banc n'a pas.
    """
    from src.agent.lexical import fuse

    non_vides = [c for c in classements if c]
    if not non_vides:
        return []
    return fuse(non_vides, top_k, poids=[1.0] * len(non_vides))


def rerank_au_meilleur_score(
    sous_questions: list[str], candidats: list[Any]
) -> tuple[list[Any], int]:
    """LE RERANKING PAR SOUS-QUESTION, chaque candidat gardant son MEILLEUR score.

    LE MAXIMUM, ET NON LA MOYENNE. Un passage qui repond parfaitement a UN des
    deux besoins doit sortir : c'est la definition meme d'une question dispersee.
    Le moyenner contre la sous-question a laquelle il ne repond pas le punirait
    d'etre precis, et le banc mesurerait alors une preference pour les passages
    tiedes sur les deux besoins — exactement le defaut que la decomposition est
    censee reparer.

    `rerank` de `src/` ECRIT `rerank_score` sur TOUS les candidats qu'on lui
    passe avant de tronquer : le score de chacun est donc lisible apres l'appel,
    y compris pour ceux que la troncature ecarte. Le banc releve ces scores apres
    chaque appel plutot que de rescorer lui-meme — ce sont les MEMES paires, par
    le MEME modele, et rescorer a la main ferait mesurer un second reranker.

    Rend le classement tronque au seuil du haut, et le nombre de PAIRES scorees.
    """
    from src.agent.retriever import dedupe_by_element, rerank

    if not candidats:
        return ([], 0)
    meilleurs: dict[int, float] = {}
    paires = 0
    for sous in sous_questions:
        rerank(sous, candidats)
        paires += len(candidats)
        for candidat in candidats:
            score = candidat.rerank_score or 0.0
            cle = id(candidat)
            if cle not in meilleurs or score > meilleurs[cle]:
                meilleurs[cle] = score
    for candidat in candidats:
        candidat.rerank_score = meilleurs[id(candidat)]
    ordonnes = sorted(candidats, key=lambda c: c.rerank_score or 0.0, reverse=True)
    return (dedupe_by_element(ordonnes)[:_SEUIL_TOP], paires)


# ─── Les variantes, jouees question par question ─────────────────────────────


def _rangs(classement: list[Any], ancrages: list[str]) -> dict[str, int | None]:
    return {eid: rang_de(eid, classement) for eid in ancrages}


def jouer_les_variantes(
    question: str,
    traduction: str | None,
    ancrages: list[str],
    sous_questions: list[str],
    utilisable: bool,
) -> dict[str, Any]:
    """LES QUATRE VARIANTES SUR UNE QUESTION, et les rangs de ses ancrages.

    Les deux variantes de fusion partagent la MEME liste fusionnee : elles ne
    different que par ce contre quoi le reranker score. Les recuperer deux fois
    ferait payer deux fois la recuperation et rendrait deux listes qui peuvent
    differer par l'ordre d'insertion, ce qui melerait l'effet du reranking a un
    bruit de fusion.

    Quand la decomposition n'est pas utilisable, les deux variantes RETOMBENT sur
    la requete unique sans traduction — le meme classement, les memes rangs, le
    meme cout de reranking — et le bilan le dit par `repli`.
    """
    from src.agent.retriever import rerank, retrieve
    from src.agent.settings import settings

    mesure: dict[str, Any] = {"couts": {}, "paires_rerankees": {}}

    t0 = time.perf_counter()
    fusion_prod = retrieve(question, translation=traduction)
    t1 = time.perf_counter()
    classement_prod = rerank(question, fusion_prod)
    t2 = time.perf_counter()
    mesure["couts"]["unique_avec_traduction_recuperation_ms"] = round((t1 - t0) * 1000, 1)
    mesure["couts"]["unique_avec_traduction_rerank_ms"] = round((t2 - t1) * 1000, 1)
    mesure["paires_rerankees"]["unique_avec_traduction"] = len(fusion_prod)

    t0 = time.perf_counter()
    fusion_nue = retrieve(question, translation=None)
    t1 = time.perf_counter()
    classement_nu = rerank(question, fusion_nue)
    t2 = time.perf_counter()
    mesure["couts"]["unique_sans_traduction_recuperation_ms"] = round((t1 - t0) * 1000, 1)
    mesure["couts"]["unique_sans_traduction_rerank_ms"] = round((t2 - t1) * 1000, 1)
    mesure["paires_rerankees"]["unique_sans_traduction"] = len(fusion_nue)

    variantes = {
        "unique_avec_traduction": _rangs(classement_prod, ancrages),
        "unique_sans_traduction": _rangs(classement_nu, ancrages),
    }

    if not utilisable:
        variantes["fusion_rerank_entiere"] = dict(variantes["unique_sans_traduction"])
        variantes["fusion_rerank_sous_questions"] = dict(variantes["unique_sans_traduction"])
        mesure["couts"]["decomposition_recuperation_ms"] = mesure["couts"][
            "unique_sans_traduction_recuperation_ms"
        ]
        mesure["couts"]["fusion_rerank_entiere_ms"] = mesure["couts"][
            "unique_sans_traduction_rerank_ms"
        ]
        mesure["couts"]["fusion_rerank_sous_questions_ms"] = mesure["couts"][
            "unique_sans_traduction_rerank_ms"
        ]
        mesure["paires_rerankees"]["fusion_rerank_entiere"] = len(fusion_nue)
        mesure["paires_rerankees"]["fusion_rerank_sous_questions"] = len(fusion_nue)
        mesure["n_fusionnes"] = len(fusion_nue)
        mesure["variantes"] = variantes
        return mesure

    t0 = time.perf_counter()
    classements = [retrieve(s, translation=None) for s in sous_questions]
    fusionnes = fusionner_les_classements(classements, settings.retrieval_top_k)
    t1 = time.perf_counter()
    mesure["couts"]["decomposition_recuperation_ms"] = round((t1 - t0) * 1000, 1)
    mesure["n_par_sous_question"] = [len(c) for c in classements]
    mesure["n_fusionnes"] = len(fusionnes)

    t0 = time.perf_counter()
    classement_entiere = rerank(question, fusionnes)
    t1 = time.perf_counter()
    mesure["couts"]["fusion_rerank_entiere_ms"] = round((t1 - t0) * 1000, 1)
    mesure["paires_rerankees"]["fusion_rerank_entiere"] = len(fusionnes)
    variantes["fusion_rerank_entiere"] = _rangs(classement_entiere, ancrages)

    t0 = time.perf_counter()
    classement_sous, paires = rerank_au_meilleur_score(sous_questions, fusionnes)
    t1 = time.perf_counter()
    mesure["couts"]["fusion_rerank_sous_questions_ms"] = round((t1 - t0) * 1000, 1)
    mesure["paires_rerankees"]["fusion_rerank_sous_questions"] = paires
    variantes["fusion_rerank_sous_questions"] = _rangs(classement_sous, ancrages)

    mesure["variantes"] = variantes
    return mesure


VARIANTES = (
    "unique_avec_traduction",
    "unique_sans_traduction",
    "fusion_rerank_entiere",
    "fusion_rerank_sous_questions",
)


def depouiller(lignes: list[dict[str, Any]]) -> dict[str, Any]:
    """LES ANCRAGES ET LES QUESTIONS COMPLETES, variante par variante.

    « Questions completes » est la grandeur du §4.76 : le nombre de questions
    dont TOUS les ancrages entrent dans le haut. « Au moins un » ne dit rien sur
    un jeu ou chaque question en porte deux et ou le retrieval en trouve presque
    toujours un.
    """
    resultats: dict[str, Any] = {}
    for variante in VARIANTES:
        ancrages = sum(
            1 for ligne in lignes for r in ligne["variantes"][variante].values() if dans_le_haut(r)
        )
        completes = [
            ligne["id"]
            for ligne in lignes
            if ligne["variantes"][variante]
            and all(dans_le_haut(r) for r in ligne["variantes"][variante].values())
        ]
        resultats[variante] = {
            "ancrages_dans_le_haut": ancrages,
            "questions_completes": len(completes),
            "questions_completes_ids": completes,
        }
    return resultats


def non_regression(depouille: dict[str, Any], base: str) -> dict[str, Any]:
    """LES QUESTIONS PERDUES, UNE PAR UNE, ET C'EST LA MOITIE DU LOT.

    Une decomposition qui gagne quinze questions dispersees et en perd dix
    simples n'est pas un gain, et un solde net le cacherait. Les deux listes sont
    donc publiees NOMMEMENT, jamais leur difference seule.
    """
    reference = set(depouille[base]["questions_completes_ids"])
    tableau: dict[str, Any] = {}
    for variante in VARIANTES:
        if variante == base:
            continue
        obtenues = set(depouille[variante]["questions_completes_ids"])
        perdues = sorted(reference - obtenues)
        gagnees = sorted(obtenues - reference)
        tableau[variante] = {
            "base": base,
            "perdues": perdues,
            "gagnees": gagnees,
            "n_perdues": len(perdues),
            "n_gagnees": len(gagnees),
            "solde": len(gagnees) - len(perdues),
        }
    return tableau


def resumer_les_couts(lignes: list[dict[str, Any]]) -> dict[str, Any]:
    """Mediane et p95 de chaque cout, et le total des paires scorees."""
    cles = sorted({c for ligne in lignes for c in ligne["couts"]})
    couts: dict[str, Any] = {}
    for cle in cles:
        valeurs = sorted(ligne["couts"][cle] for ligne in lignes if cle in ligne["couts"])
        if not valeurs:
            continue
        couts[cle] = {
            "n": len(valeurs),
            "mediane": round(statistics.median(valeurs), 1),
            "p95": round(valeurs[min(len(valeurs) - 1, int(0.95 * len(valeurs)))], 1),
        }
    paires = {
        variante: sum(ligne["paires_rerankees"].get(variante, 0) for ligne in lignes)
        for variante in VARIANTES
    }
    return {"latences_ms": couts, "paires_rerankees_total": paires}


# ─── LE CONTROLE POSITIF, ET IL EST ANTERIEUR A TOUTE PUBLICATION ────────────

# Les deux chiffres du §4.77 pour la requete unique de production, sur le jeu
# disperse. Un banc qui ne les retrouve PAS a l'unite pres ne rejoue pas la
# chaine de production, et ce qu'il dirait de la decomposition n'aurait aucune
# base.
CONTROLE_4_77 = {"ancrages_dans_le_haut": 53, "questions_completes": 7}


def controle_positif(lignes: list[dict[str, Any]], reference: Path) -> dict[str, Any]:
    """LE BANC REJOUE-T-IL LA CHAINE DE PRODUCTION ? Deux comptes ET 120 RANGS.

    LES COMPTES NE SUFFISENT PAS, ET C'EST LA LECON DU §4.77. Deux bancs qui
    mesureraient deux jeux differents peuvent rendre 53 et 7 sans qu'un seul rang
    ne coincide. Le controle est donc une INTERSECTION : les cles
    `(question, ancrage)` doivent etre les MEMES, et les rangs de la variante de
    production IDENTIQUES UN A UN a ceux de `runs/2026-09-24-recuperation-p50.json`.

    Il REFUSE de publier la suite sans cet accord — un desaccord de rang dit que
    la chaine a bouge, et une mesure de la decomposition contre une base qui a
    bouge ne mesure rien.
    """
    attendus = {
        (ligne["id"], eid): r["rerank"]
        for ligne in json.loads(reference.read_text(encoding="utf-8"))["lignes"]
        for eid, r in ligne["rangs"].items()
    }
    mesures = {
        (ligne["id"], eid): rang
        for ligne in lignes
        for eid, rang in ligne["variantes"]["unique_avec_traduction"].items()
    }
    cles_communes = set(attendus) & set(mesures)
    desaccords = [
        {"cle": list(cle), "attendu": attendus[cle], "mesure": mesures[cle]}
        for cle in sorted(cles_communes)
        if attendus[cle] != mesures[cle]
    ]
    comptes = {
        "ancrages_dans_le_haut": sum(1 for r in mesures.values() if dans_le_haut(r)),
        "questions_completes": sum(
            1
            for ligne in lignes
            if ligne["variantes"]["unique_avec_traduction"]
            and all(dans_le_haut(r) for r in ligne["variantes"]["unique_avec_traduction"].values())
        ),
    }
    return {
        "reference": str(reference.name),
        "cles_attendues": len(attendus),
        "cles_mesurees": len(mesures),
        "cles_communes": len(cles_communes),
        "rangs_identiques": len(cles_communes) - len(desaccords),
        "desaccords": desaccords[:20],
        "n_desaccords": len(desaccords),
        "attendu_4_77": dict(CONTROLE_4_77),
        "mesure": comptes,
        "accord": (
            len(cles_communes) == len(attendus) == len(mesures)
            and not desaccords
            and comptes == dict(CONTROLE_4_77)
        ),
    }


# ─── Les etapes ──────────────────────────────────────────────────────────────


def cache_de_decomposition(jeu: Path) -> Path:
    """Un cache PAR JEU, nomme d'apres lui.

    Un seul fichier pour les trois jeux laisserait une campagne lire les
    decompositions d'un autre jeu des que deux questions porteraient le meme
    identifiant — et les identifiants sont locaux a leur fichier.
    """
    return ROOT / "runs" / f".decomposition-{jeu.stem}.json"


def _traductions(questions: list[dict[str, Any]]) -> dict[str, str]:
    """Le cache de traductions, EXIGE et jamais fabrique.

    Meme refus qu'aux §4.76 et §4.77 : une traduction manquante deplacerait le
    rappel de la variante de production sans un mot, et c'est elle que le
    controle positif confronte a la reference.
    """
    from mesurer_selection import CACHE_TRADUCTIONS

    if not CACHE_TRADUCTIONS.exists():
        raise SystemExit(f"ABSENT : {CACHE_TRADUCTIONS}.")
    cache: dict[str, str] = json.loads(CACHE_TRADUCTIONS.read_text(encoding="utf-8"))
    manquantes = [q["id"] for q in questions if q["question"] not in cache]
    if manquantes:
        raise SystemExit(
            f"REFUS : {len(manquantes)} question(s) sans traduction en cache "
            f"({', '.join(manquantes[:5])}…). Le rappel de la base serait fausse."
        )
    return cache


def prompt_de_decomposition(question: str, maximum: int = _MAX_SOUS_QUESTIONS) -> str:
    """LE PROMPT, ET LA QUESTION Y EST EN TETE. Ce n'est pas une coquetterie.

    `vllm-central` sert un meme prefixe depuis son cache de prefixe, et une
    latence mesuree sur un prefixe deja servi n'est pas la latence de l'appel.
    Mettre l'instruction en tete ferait partager aux soixante appels un prefixe
    de plusieurs dizaines de jetons, dont le premier appel seul paierait
    l'encodage : les cinquante-neuf suivants mesureraient un cache. La QUESTION
    d'abord rend les prefixes DISTINCTS DES LE PREMIER JETON, et chaque appel
    paie le sien.

    LE MODELE N'APPREND PAS COMBIEN DE BESOINS LA QUESTION PORTE, et c'est la
    difference avec l'oracle du §4.77, dont le prompt AFFIRMAIT qu'il y en avait
    deux. Un decomposeur reel dans `src/` ne le sait pas ; le lui dire ferait
    mesurer une decomposition impossible a implementer, et surtout rendrait la
    non-regression indechiffrable — toute question a besoin unique serait
    coupee en deux de force.
    """
    return (
        f"Question: {question}\n\n"
        "Decompose the question above for a document search engine. If it carries "
        "several DISTINCT information needs, write one standalone sub-question per "
        "need, each self-contained and answerable on its own. If it carries a "
        "single need, return the question alone, unchanged. Never write more than "
        f"{maximum} sub-questions, and never invent a need the question does not ask.\n\n"
        'Answer with JSON only: {"sub_questions": ["…"]}'
    )


def etape_decomposition(
    questions: list[dict[str, Any]],
    jeu: Path,
    hote: str,
    modele: str,
    timeout: float,
    graine: int,
) -> dict[str, Any]:
    """LE PRODUCTEUR du cache de decompositions. Il n'est PAS un antecedent du banc.

    Le modele recoit LA SEULE QUESTION — jamais les passages, jamais le nombre de
    besoins. C'est ce qu'un decomposeur de requete dans `src/` aurait, et pas
    plus.

    `thinking=False` passe par `chat_template_kwargs` PAR REQUETE : rien n'est
    pose cote serveur, `vllm-central` appartenant a l'equipe voisine. La raison
    de fin est relevee a CHAQUE generation — une reponse coupee par `max_tokens`
    rend un JSON invalide, donc un rejet, que rien ne distinguerait d'un refus de
    forme si les deux n'etaient pas comptes separement.

    UN APPEL DE CHAUFFE EST JOUE D'ABORD ET IL EST EXCLU DES STATISTIQUES : le
    premier appel paie le chargement des poids cote serveur et la mise en place
    des tampons, et le compter ferait remonter la mediane sur un cout qu'aucune
    question ne paierait en production.
    """
    from src.agent.dialecte_llm import dialecte_courant
    from src.agent.flux_llm import charge_du_corps

    dialecte = dialecte_courant()._replace(hote=hote, modele=modele)

    def _appel(texte: str) -> dict[str, Any]:
        charge = dialecte.charge(
            [{"role": "user", "content": prompt_de_decomposition(texte)}],
            stream=False,
            temperature=0.2,
            max_tokens=400,
            thinking=False,
            graine=graine,
            format_json=True,
        )
        depart = time.perf_counter()
        reponse = httpx.post(dialecte.url_chat, json=charge, timeout=timeout)
        millisecondes = (time.perf_counter() - depart) * 1000
        reponse.raise_for_status()
        corps = reponse.json()
        return {"ms": millisecondes, "corps": corps}

    chauffe: dict[str, Any] = {}
    try:
        brut = _appel("What is the stated purpose of this corpus, in one sentence?")
        chauffe = {
            "ms": round(brut["ms"], 1),
            "raison_de_fin": str((brut["corps"].get("choices") or [{}])[0].get("finish_reason")),
            "exclu_des_statistiques": True,
        }
    except Exception as panne:  # noqa: BLE001 — absorption large ASSUMEE, et DITE
        chauffe = {"panne": f"{type(panne).__name__}: {panne}", "exclu_des_statistiques": True}

    cache: dict[str, list[str]] = {}
    raisons: list[str] = []
    pannes: list[str] = []
    latences: list[float] = []
    jetons_generes: list[int] = []
    for index, q in enumerate(questions, 1):
        try:
            brut = _appel(q["question"])
            corps = brut["corps"]
            choix = (corps.get("choices") or [{}])[0]
            raisons.append(str(choix.get("finish_reason")))
            latences.append(brut["ms"])
            usage = corps.get("usage") or {}
            jetons_generes.append(int(usage.get("completion_tokens") or 0))
            donnees = json.loads(charge_du_corps(corps).get("content") or "")
            brutes = donnees.get("sub_questions")
            if isinstance(brutes, str):
                brutes = [brutes]
            sous = [str(s).strip() for s in (brutes or []) if str(s).strip()]
            if sous:
                cache[q["id"]] = sous[:_MAX_SOUS_QUESTIONS]
            else:
                pannes.append(f"{q['id']}: aucune sous-question")
        except Exception as panne:  # noqa: BLE001 — meme absorption, meme raison
            pannes.append(f"{q['id']}: {type(panne).__name__}: {panne}")
        if index % 10 == 0:
            print(f"  {index}/{len(questions)}", flush=True)

    natures = {"decomposee": 0, "vide": 0, "une_seule": 0, "quasi_identique": 0}
    for q in questions:
        _, nature = decomposition_utilisable(q["question"], cache.get(q["id"], []))
        natures[nature] += 1

    return {
        "etape": "decomposition",
        "jeu": jeu.name,
        "modele": modele,
        "max_sous_questions": _MAX_SOUS_QUESTIONS,
        "seuil_quasi_identique": _SEUIL_QUASI_IDENTIQUE,
        "appel_de_chauffe": chauffe,
        "generations": len(questions),
        "raisons_de_fin": {r: raisons.count(r) for r in sorted(set(raisons))},
        "prompts_distincts": len({prompt_de_decomposition(q["question"]) for q in questions}),
        "latence_ms": {
            "n": len(latences),
            "mediane": round(statistics.median(latences), 1) if latences else None,
            "p95": (
                round(sorted(latences)[min(len(latences) - 1, int(0.95 * len(latences)))], 1)
                if latences
                else None
            ),
            "min": round(min(latences), 1) if latences else None,
            "max": round(max(latences), 1) if latences else None,
        },
        "jetons_generes": {
            "total": sum(jetons_generes),
            "mediane": round(statistics.median(jetons_generes), 1) if jetons_generes else None,
            "max": max(jetons_generes) if jetons_generes else None,
        },
        "natures": natures,
        "pannes": pannes,
        "cache": cache,
    }


def etape_fusion(
    questions: list[dict[str, Any]], jeu: Path, port_sante: int, reference: Path | None
) -> dict[str, Any]:
    """LA MESURE : les quatre variantes, sur chaque question du jeu."""
    from src.agent.settings import settings

    chemin = cache_de_decomposition(jeu)
    if not chemin.exists():
        raise SystemExit(
            f"ABSENT : {chemin}. Joue d'abord "
            f"scripts/mesurer_fusion_sous_questions.py --etape decomposition --jeu {jeu}."
        )
    cache: dict[str, list[str]] = json.loads(chemin.read_text(encoding="utf-8"))
    manquantes = [q["id"] for q in questions if q["id"] not in cache]
    if manquantes:
        raise SystemExit(
            f"REFUS : {len(manquantes)} question(s) sans decomposition en cache "
            f"({', '.join(manquantes[:5])}…). La fusion serait mesuree sur un autre jeu."
        )

    traductions = _traductions(questions)
    debut = etat_des_stores(port_sante)

    # UN PASSAGE DE CHAUFFE, EXCLU DE TOUTE STATISTIQUE, ET IL EST ECRIT PARCE
    # QUE SANS LUI LA PREMIERE QUESTION PAIE LES DEUX MODELES. L'embedder et le
    # cross-encoder sont charges paresseusement au premier appel : la premiere
    # question du jeu porterait donc une seconde de chargement qu'aucune autre
    # ne paie, et elle remonterait le p95 sur un cout que la production amortit
    # au demarrage du service. La requete de chauffe n'est AUCUNE question du
    # jeu, pour qu'aucun cache de la chaine ne serve ensuite une mesure.
    from src.agent.retriever import rerank as _rerank_de_chauffe
    from src.agent.retriever import retrieve as _retrieve_de_chauffe

    requete_de_chauffe = "corpus warm-up probe, scored and discarded"
    depart_chauffe = time.perf_counter()
    _rerank_de_chauffe(requete_de_chauffe, _retrieve_de_chauffe(requete_de_chauffe))
    chauffe = {
        "requete": requete_de_chauffe,
        "ms": round((time.perf_counter() - depart_chauffe) * 1000, 1),
        "exclu_des_statistiques": True,
    }

    lignes: list[dict[str, Any]] = []
    natures = {"decomposee": 0, "vide": 0, "une_seule": 0, "quasi_identique": 0}
    t0 = time.perf_counter()
    for index, q in enumerate(questions, 1):
        ancrages = list(q["gold_element_ids"])
        sous = cache[q["id"]]
        utilisable, nature = decomposition_utilisable(q["question"], sous)
        natures[nature] += 1
        mesure = jouer_les_variantes(
            q["question"], traductions.get(q["question"]), ancrages, sous, utilisable
        )
        lignes.append(
            {
                "id": q["id"],
                "gold": ancrages,
                "sous_questions": sous,
                "nature": nature,
                "repli": not utilisable,
                **mesure,
            }
        )
        if index % 10 == 0:
            print(f"  {index}/{len(questions)} — {time.perf_counter() - t0:.0f} s", flush=True)
    fin = etat_des_stores(port_sante)

    depouille = depouiller(lignes)
    bilan: dict[str, Any] = {
        "etape": "fusion",
        "jeu": jeu.name,
        "questions": len(questions),
        "ancrages": sum(len(ligne["gold"]) for ligne in lignes),
        "seuil_du_haut": _SEUIL_TOP,
        "profondeurs": {
            "fetch_k": settings.fetch_k,
            "retrieval_top_k": settings.retrieval_top_k,
            "rerank_top_k": settings.rerank_top_k,
            "rrf_k": settings.rrf_k,
            "hybrid_search": settings.hybrid_search,
            "torch_device": settings.torch_device,
        },
        "natures_de_decomposition": natures,
        "passage_de_chauffe": chauffe,
        "stores": {"debut": debut, "fin": fin},
        "resultats": depouille,
        "non_regression_vs_sans_traduction": non_regression(depouille, "unique_sans_traduction"),
        "non_regression_vs_production": non_regression(depouille, "unique_avec_traduction"),
        "couts": resumer_les_couts(lignes),
        "secondes": round(time.perf_counter() - t0, 1),
        "lignes": lignes,
    }
    if reference is not None:
        bilan["controle_positif"] = controle_positif(lignes, reference)
    return bilan


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--etape", required=True, choices=["decomposition", "fusion"])
    parser.add_argument(
        "--jeu", type=Path, default=ROOT / "tests" / "fixtures" / "jeu_ancrages_disperses.yaml"
    )
    parser.add_argument("--sortie", type=Path, required=True)
    parser.add_argument("--port-sante", type=int, default=8011)
    parser.add_argument("--limite", type=int, default=0)
    parser.add_argument("--llm-host", default="http://localhost:8100")
    parser.add_argument("--model", default="google/gemma-4-E4B-it-qat-w4a16-ct")
    parser.add_argument("--timeout", type=float, default=300.0)
    parser.add_argument("--seed", type=int, default=38)
    parser.add_argument(
        "--reference",
        type=Path,
        help="Bilan de reference du controle positif (jeu disperse uniquement).",
    )
    args = parser.parse_args()

    questions = charger_questions(args.jeu)
    if args.limite:
        questions = questions[: args.limite]
    print(f"{len(questions)} questions, jeu {args.jeu.name}, etape {args.etape}", flush=True)

    if args.etape == "decomposition":
        bilan = etape_decomposition(
            questions, args.jeu, args.llm_host, args.model, args.timeout, args.seed
        )
    else:
        bilan = etape_fusion(questions, args.jeu, args.port_sante, args.reference)

    # L'ETAT DES STORES EST UN REFUS, PAS UNE NOTE. Une campagne qui a vu deux
    # etats rend un tableau dont chaque ligne est juste et dont le total ne
    # decrit rien ; elle sort en 1 et le DIT.
    if "stores" in bilan:
        stable, phrase = stores_stables(bilan["stores"]["debut"], bilan["stores"]["fin"])
        bilan["stores"]["stable"] = stable
        bilan["stores"]["verdict"] = phrase
        print(f"stores : {phrase}")
        if not stable:
            args.sortie.write_text(
                json.dumps(bilan, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            print(f"REFUS : les stores ont bouge. Bilan partiel ecrit dans {args.sortie}.")
            return 1

    args.sortie.write_text(json.dumps(bilan, ensure_ascii=False, indent=2), encoding="utf-8")

    if args.etape == "decomposition":
        chemin = cache_de_decomposition(args.jeu)
        chemin.write_text(
            json.dumps(bilan["cache"], ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"cache : {len(bilan['cache'])}/{len(questions)} dans {chemin}")
        print(f"raisons de fin : {bilan['raisons_de_fin']}")
        print(f"natures : {bilan['natures']}")
        print(f"latence ms : {bilan['latence_ms']}")
    else:
        controle = bilan.get("controle_positif")
        if controle is not None:
            print(
                f"\ncontrole positif §4.77 : {controle['mesure']} contre "
                f"{controle['attendu_4_77']}, rangs identiques "
                f"{controle['rangs_identiques']}/{controle['cles_communes']}"
            )
            if not controle["accord"]:
                # LE REFUS DE PUBLIER LA SUITE. Le bilan est ecrit — il porte la
                # preuve du desaccord — mais le banc sort en 1 et ne presente
                # AUCUN resultat de variante : une mesure de la decomposition
                # contre une base qui a bouge ne mesure rien, et l'imprimer
                # suffirait a ce qu'elle soit recopiee.
                print(
                    "REFUS : le controle positif ne passe pas. "
                    f"{controle['n_desaccords']} rang(s) en desaccord, "
                    f"{controle['cles_communes']} cle(s) commune(s) sur "
                    f"{controle['cles_attendues']} attendue(s). "
                    "Les variantes ne sont pas publiees."
                )
                return 1
        for variante in VARIANTES:
            ligne = bilan["resultats"][variante]
            print(
                f"  {variante:<30} ancrages {ligne['ancrages_dans_le_haut']:>4}"
                f"   questions completes {ligne['questions_completes']:>4}"
            )
        for variante, tableau in bilan["non_regression_vs_sans_traduction"].items():
            print(
                f"  vs sans traduction — {variante:<30} "
                f"+{tableau['n_gagnees']} / -{tableau['n_perdues']} "
                f"perdues : {', '.join(tableau['perdues']) or '—'}"
            )
    print(f"ecrit : {args.sortie}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
