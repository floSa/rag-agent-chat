#!/usr/bin/env python
"""Le PLAFOND DE RECUPERATION du jeu a ancrages disperses : pourquoi la moitie
des ancrages n'arrive jamais au quatrieme etage.

Le §4.76 a mesure ce que la SELECTION laisse passer, et il a trouve que le
plafond est ailleurs : sur les 120 ancrages du jeu disperse, **56** sont absents
du classement dense, **46** de la fusion a 50, et **67** du top-10 du reranker.
Ce banc-ci ne remesure pas la selection — il va chercher POURQUOI ces ancrages
ne sont pas la, et il rend un TABLEAU DE CAUSES qui somme a 120.

QUATRE HYPOTHESES, ET CE QUI LES SEPARE

- **H1 — la requete unique ne porte qu'un des deux besoins.** Separee par un
  ORACLE : on reinterroge avec une requete qui ne porte que le besoin du
  passage. Si l'ancrage remonte, le passage etait atteignable et c'est la
  DECOMPOSITION de la question qui manque.
- **H2 — le passage est atteignable mais classe au-dela de 50.** Separee par la
  PROFONDEUR : les memes rangs sont releves a 50, 200 et 1000. « Absent a 50 mais
  present a 1000 » n'est pas « absent partout ».
- **H3 — le texte indexe ne porte pas ce que la question demande.** Separee en
  lisant ce que ChromaDB porte REELLEMENT sur l'element : le chunk, sa longueur,
  et la part des mots de la `preuve` qui s'y retrouvent.
- **H4 — le reranker ecarte ce que la fusion avait trouve.** Separee par la
  comparaison des deux rangs a profondeur de production.

AUCUNE REPONSE N'EST GENEREE PAR LA MESURE. Le modele n'entre que dans la
FABRICATION du cache de sous-questions (`--etape sous-questions`), qui est un
producteur distinct, et le banc EXIGE ce cache sans jamais le fabriquer — meme
discipline que le cache de traductions du §4.76.

LES PROFONDEURS NE SONT PAS DANS CE FICHIER. Elles viennent de l'environnement
du LANCEMENT (`FETCH_K`, `RETRIEVAL_TOP_K`, `RERANK_TOP_K`), lues par
`src/agent/settings.py` : ni `src/` ni le `.env` ne sont touches. Le banc ECRIT
dans son bilan les trois valeurs reellement en vigueur, pour qu'un fichier de
`runs/` ne puisse pas mentir sur la profondeur qui l'a produit.

    FETCH_K=50 RETRIEVAL_TOP_K=50 RERANK_TOP_K=10 \\
        uv run --no-sync python scripts/mesurer_recuperation.py \\
        --etape profondeurs --sortie runs/2026-09-24-recuperation-p50.json
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from mesurer_dispersion import jetons, rang_de  # noqa: E402 — `scripts/` n'est pas un paquet
from mesurer_selection import charger_questions  # noqa: E402 — idem

# Part des jetons de la `preuve` qu'il faut retrouver dans le chunk indexe pour
# dire que le texte indexe PORTE la preuve. Ce n'est pas 1,0 : la preuve est
# recopiee du passage par le generateur, mais le chunk est une FENETRE sur
# l'element et peut couper la phrase. Le seuil est publie avec le resultat, et
# la part brute est ecrite ancrage par ancrage pour qu'on puisse le rejuger sans
# relancer la campagne.
_SEUIL_PREUVE = 0.8

# Longueur en dessous de laquelle un chunk est dit EMIETTE. Ce n'est pas un
# jugement de gout : `generate_golden` ecarte les passages de moins de 200
# caracteres parce qu'ils ne portent pas un fait entier, et un chunk plus court
# que cela ne peut pas porter une preuve d'une phrase.
_CHUNK_EMIETTE = 200

# LE HAUT DU CLASSEMENT, et c'est la grandeur du §4.76 : « absent du top-10 du
# reranker ». Elle ne depend PAS de `RERANK_TOP_K` — sans quoi la meme phrase
# designerait dix ancrages a profondeur de production et mille a profondeur
# 1000, et la table des causes comparerait deux grandeurs portant un seul nom.
_SEUIL_TOP = 10

# LES CAUSES, DANS L'ORDRE OU ELLES SONT ESSAYEES. L'ordre est la definition :
# les classes sont exclusives par construction, et la somme des comptes vaut le
# nombre d'ancrages. Toute cause comptee a 0 doit l'etre par un detecteur qui
# SAIT la voir — c'est ce que les temoins de `tests/unit/` exigent.
CAUSES = (
    "arrive",
    "hors_chromadb",
    "ecarte_par_le_reranker",
    "profondeur_recupere",
    "profondeur_insuffisante",
    "requete_unique",
    "texte_indexe",
    "non_explique",
)


def couverture(attendu: str, porteur: str) -> float | None:
    """Part des jetons de `attendu` qui se retrouvent dans `porteur`.

    `None` quand `attendu` ne porte aucun jeton mesurable : une part de 0,0 se
    lirait comme « rien ne correspond » alors que rien n'a pu etre compare, et
    le §4.76 a paye cette confusion sur les ancrages sans texte.
    """
    cherches = jetons(attendu)
    if not cherches:
        return None
    return len(cherches & jetons(porteur)) / len(cherches)


def dans_le_haut(rang: int | None, seuil: int = _SEUIL_TOP) -> bool:
    """Le rang est-il dans le HAUT du classement, au sens du §4.76 ?

    CE N'EST PAS « present dans la liste », ET LA DIFFERENCE A FAILLI ME COUTER
    LA TABLE. A profondeur de production `RERANK_TOP_K` vaut 10, donc « rendu par
    `rerank` » et « dans le top-10 » coincident ; a profondeur 1000 ils ne
    coincident plus du tout, et un ancrage rendu au rang 812 se serait lu comme
    « la profondeur l'a recupere ». Le seuil est donc EXPLICITE, et il est le
    meme aux trois profondeurs.
    """
    return rang is not None and rang <= seuil


def classer_la_cause(observation: dict[str, Any], seuil: int = _SEUIL_TOP) -> str:
    """LA CAUSE D'UN ANCRAGE, par un arbre de decision ORDONNE et exclusif.

    L'observation porte, pour un ancrage :

    - `rang_rerank_prod` : son rang dans le top-`RERANK_TOP_K` de production,
      `None` s'il en est absent ;
    - `rang_fusion_prod` : son rang dans la fusion a 50, `None` s'il en est
      absent ;
    - `rang_fusion_profond` / `rang_rerank_profond` : les memes, a la plus
      grande profondeur mesuree ;
    - `indexe` : le texte de l'element existe-t-il dans ChromaDB ;
    - `oracle_rerank` : le rang atteint par la requete ORACLE, `None` s'il reste
      absent, et la cle ABSENTE si l'oracle n'a pas ete joue sur cet ancrage.

    L'ORDRE EST LA DEFINITION, et chaque marche dit ce qu'elle retranche :

    1. `arrive` — il est dans le top-10 du reranker de production. Il n'y a rien
       a expliquer, et le compter ailleurs gonflerait une cause.
    2. `hors_chromadb` — l'element n'a aucun texte dans l'index vectoriel. Aucune
       requete ne peut le ramener, et le classer plus bas accuserait la requete
       d'un manque de l'ingestion.
    3. `ecarte_par_le_reranker` — la fusion de production l'avait, le reranker ne
       le rend pas. C'est H4, et c'est le seul cas ou le passage etait DEJA dans
       les mains du quatrieme etage.
    4. `profondeur_recupere` — absent de la fusion a 50, present plus profond, et
       le reranker l'y ramene DANS SON TOP-10 au sens de `dans_le_haut`, jamais
       au sens de « rendu par la liste » : a profondeur 1000 la liste en porte
       mille. C'est H2 confirmee : la profondeur, et elle seule, le perdait.
    5. `profondeur_insuffisante` — absent a 50, retrouve plus profond, mais le
       reranker ne le remonte pas pour autant. Elargir ne suffit pas, et le
       fondre dans la marche precedente ferait croire qu'il suffit.
    6. `requete_unique` — introuvable a toute profondeur, mais l'ORACLE le ramene.
       C'est H1 : le passage etait atteignable, la question entiere ne le
       demandait pas.
    7. `texte_indexe` — meme l'oracle ne le ramene pas, alors que la requete
       oracle est faite des mots du passage. C'est H3.
    8. `non_explique` — tout le reste, et il est NOMME. Une table de causes sans
       cette ligne se boucle en accusant la derniere cause essayee.
    """
    if dans_le_haut(observation["rang_rerank_prod"], seuil):
        return "arrive"
    if not observation["indexe"]:
        return "hors_chromadb"
    if observation["rang_fusion_prod"] is not None:
        return "ecarte_par_le_reranker"
    if observation["rang_fusion_profond"] is not None:
        if dans_le_haut(observation["rang_rerank_profond"], seuil):
            return "profondeur_recupere"
        return "profondeur_insuffisante"
    if "oracle_rerank" not in observation:
        return "non_explique"
    if dans_le_haut(observation["oracle_rerank"], seuil):
        return "requete_unique"
    return "texte_indexe"


def requete_oracle_preuve(ancrage: dict[str, Any]) -> str:
    """LA REQUETE ORACLE DETERMINISTE, et elle est un BIAIS qu'il faut dire.

    C'est la phrase de `preuve` de l'ancrage, MOT POUR MOT. Ce n'est pas une
    question qu'un humain poserait : c'est du texte recopie du passage indexe,
    donc la requete la plus favorable qui existe. Elle ne mesure pas ce qu'une
    decomposition de requete gagnerait — elle borne PAR LE HAUT ce que le
    passage peut rendre, et c'est exactement ce qu'il faut pour separer « la
    question ne le demandait pas » (H1) de « le texte ne le porte pas » (H3).

    Le titre de section n'y entre PAS : il vient du graphe, pas du chunk indexe,
    et l'ajouter melerait deux sources dans une mesure qui doit dire ce que le
    CHUNK rend.
    """
    return (ancrage.get("preuve") or "").strip()


def affectation_au_mieux(
    rangs_par_sous_question: list[list[int | None]],
) -> tuple[list[int], list[int | None]]:
    """L'affectation sous-question → ancrage la PLUS FAVORABLE, et c'est un biais.

    `rangs_par_sous_question[i][j]` est le rang obtenu par la sous-question `i`
    sur l'ancrage `j`. Le modele ecrit deux sous-questions sans voir les
    passages : rien ne dit laquelle vise lequel. Plutot que de deviner, on essaie
    les deux affectations et on garde celle qui ramene le plus d'ancrages — puis,
    a egalite, celle dont la somme des rangs est la plus basse.

    C'EST UN ORACLE D'AFFECTATION, et il est DECLARE : une decomposition reelle
    dans `src/` n'aurait pas ce choix, elle lancerait les deux sous-questions et
    fusionnerait. Le chiffre publie est donc une BORNE SUPERIEURE de ce que la
    decomposition gagnerait, jamais une prevision.

    Rend le permutation retenue et les rangs correspondants.
    """
    n = len(rangs_par_sous_question)
    if n == 0:
        return ([], [])
    import itertools

    meilleur: tuple[list[int], list[int | None]] | None = None
    meilleur_score: tuple[int, int] | None = None
    for permutation in itertools.permutations(range(n)):
        rangs = [rangs_par_sous_question[i][permutation[i]] for i in range(n)]
        trouves = sum(1 for r in rangs if r is not None)
        somme = sum(r for r in rangs if r is not None)
        score = (-trouves, somme)
        if meilleur_score is None or score < meilleur_score:
            meilleur_score = score
            meilleur = (list(permutation), rangs)
    assert meilleur is not None
    return meilleur


# ─── L'etat des stores, releve aux DEUX bouts de chaque campagne ─────────────


def etat_des_stores(port_sante: int) -> dict[str, Any]:
    """`/health` en LECTURE et le compte de chunks, horodates.

    Les deux, jamais l'un sans l'autre : un `/health` vert dit que les services
    repondent, pas que le corpus est le meme. Le pipeline voisin va purger puis
    reingerer, et deux etats des stores dans un meme tableau rendraient ce
    tableau illisible sans qu'aucune ligne ne soit fausse.
    """
    import datetime

    from src.agent.retriever import _get_chroma_collection

    releve: dict[str, Any] = {
        "heure_utc": datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds"),
    }
    try:
        reponse = httpx.get(f"http://localhost:{port_sante}/health", timeout=20.0)
        corps = reponse.json()
        releve["health"] = {
            "status": corps.get("status"),
            "services": corps.get("services"),
            "code_servi": (corps.get("code_servi") or {}).get("sha"),
        }
    except Exception as panne:  # noqa: BLE001 — absorption large ASSUMEE, et DITE
        releve["health"] = {"panne": f"{type(panne).__name__}: {panne}"}
    try:
        releve["chunks"] = _get_chroma_collection().count()
    except Exception as panne:  # noqa: BLE001 — meme absorption, meme raison
        releve["chunks"] = None
        releve["chunks_panne"] = f"{type(panne).__name__}: {panne}"
    return releve


def stores_stables(debut: dict[str, Any], fin: dict[str, Any]) -> tuple[bool, str]:
    """Les deux releves decrivent-ils UN SEUL etat des stores ?

    Trois refus, et chacun a sa phrase : un service rouge, un `/health` injoignable,
    un compte de chunks qui a bouge. Un banc qui melangerait deux etats rendrait
    un tableau dont aucune ligne ne serait fausse et dont le total serait faux.
    """
    for nom, releve in (("debut", debut), ("fin", fin)):
        sante = releve.get("health") or {}
        if "panne" in sante:
            return (False, f"/health injoignable au {nom} : {sante['panne']}")
        if sante.get("status") != "ok":
            return (False, f"/health n'est pas ok au {nom} : {sante.get('status')!r}")
        rouges = [s for s, v in (sante.get("services") or {}).items() if not v]
        if rouges:
            return (False, f"service(s) rouge(s) au {nom} : {', '.join(sorted(rouges))}")
        if releve.get("chunks") is None:
            return (False, f"compte de chunks illisible au {nom}")
    if debut["chunks"] != fin["chunks"]:
        return (False, f"le compte de chunks a bouge : {debut['chunks']} → {fin['chunks']}")
    return (True, f"{debut['chunks']} chunks aux deux bouts, aucun service rouge")


# ─── Les etages, joues une fois par requete ──────────────────────────────────


def rangs_des_ancrages(
    requete: str, ancrages: list[str], *, traduction: str | None, avec_rerank: bool = True
) -> dict[str, Any]:
    """Les quatre etages joues separement, et le rang de chaque ancrage a chacun.

    `_dense_search` et `_lexical_search` sont appeles a part pour lire leur rang
    propre : `retrieve` les fusionne en interne et ne rend que le resultat. Ce
    sont les MEMES appels, aux MEMES parametres — `settings.fetch_k` dans les
    deux cas.
    """
    from src.agent.retriever import _dense_search, _lexical_search, rerank, retrieve
    from src.agent.settings import settings

    dense = _dense_search(requete, settings.fetch_k)
    lexical = _lexical_search(requete, settings.fetch_k)
    fusion = retrieve(requete, translation=traduction)
    classement = rerank(requete, fusion) if avec_rerank else []
    return {
        "rangs": {
            eid: {
                "dense": rang_de(eid, dense),
                "lexical": rang_de(eid, lexical),
                "fusion": rang_de(eid, fusion),
                "rerank": rang_de(eid, classement),
            }
            for eid in ancrages
        },
        "n_dense": len(dense),
        "n_lexical": len(lexical),
        "n_fusion": len(fusion),
        "n_rerank": len(classement),
    }


def profondeurs_en_vigueur() -> dict[str, Any]:
    """Les trois profondeurs REELLEMENT lues par le code, ecrites dans le bilan.

    Elles viennent de l'environnement du lancement. Les recopier depuis la ligne
    de commande dans le fichier de sortie laisserait un bilan affirmer une
    profondeur que le code n'a pas eue — c'est `settings` qui fait foi, et c'est
    lui qu'on ecrit.
    """
    from src.agent.settings import settings

    return {
        "fetch_k": settings.fetch_k,
        "retrieval_top_k": settings.retrieval_top_k,
        "rerank_top_k": settings.rerank_top_k,
        "hybrid_search": settings.hybrid_search,
        "torch_device": settings.torch_device,
    }


# ─── Les etapes ──────────────────────────────────────────────────────────────

CACHE_SOUS_QUESTIONS = ROOT / "runs" / ".sous-questions-disperse.json"


def _traductions(questions: list[dict[str, Any]]) -> dict[str, str]:
    """Le cache de traductions, EXIGE et jamais fabrique.

    Meme refus que `mesurer_dispersion` : une traduction manquante retirerait la
    question de son versant translinguistique en deplacant le rappel sans un mot.
    Le cache du 23 septembre 2026 portait 130 entrees pour un jeu de 130 questions
    et une intersection NULLE avec lui ; c'est le refus, et non la taille, qui
    l'a attrape.
    """
    from mesurer_selection import CACHE_TRADUCTIONS

    if not CACHE_TRADUCTIONS.exists():
        raise SystemExit(
            f"ABSENT : {CACHE_TRADUCTIONS}. Joue d'abord make traductions-du-jeu-disperse."
        )
    cache: dict[str, str] = json.loads(CACHE_TRADUCTIONS.read_text(encoding="utf-8"))
    manquantes = [q["id"] for q in questions if q["question"] not in cache]
    if manquantes:
        raise SystemExit(
            f"REFUS : {len(manquantes)} question(s) sans traduction en cache "
            f"({', '.join(manquantes[:5])}…). Le rappel translinguistique serait fausse."
        )
    return cache


def etape_profondeurs(questions: list[dict[str, Any]], port_sante: int) -> dict[str, Any]:
    """Les rangs a CHAQUE etage, a la profondeur que l'environnement impose."""
    traductions = _traductions(questions)
    debut = etat_des_stores(port_sante)
    lignes: list[dict[str, Any]] = []
    t0 = time.perf_counter()
    for index, q in enumerate(questions, 1):
        ancrages = list(q["gold_element_ids"])
        mesure = rangs_des_ancrages(
            q["question"], ancrages, traduction=traductions.get(q["question"])
        )
        lignes.append({"id": q["id"], "type": q.get("type", ""), "gold": ancrages, **mesure})
        if index % 10 == 0:
            print(f"  {index}/{len(questions)} — {time.perf_counter() - t0:.0f} s", flush=True)
    fin = etat_des_stores(port_sante)
    return {
        "etape": "profondeurs",
        "profondeurs": profondeurs_en_vigueur(),
        "stores": {"debut": debut, "fin": fin},
        "lignes": lignes,
        "secondes": round(time.perf_counter() - t0, 1),
    }


def etape_sous_questions(
    questions: list[dict[str, Any]], hote: str, modele: str, timeout: float, graine: int
) -> dict[str, Any]:
    """LE PRODUCTEUR du cache de sous-questions. Il n'est PAS un antecedent du banc.

    Le modele recoit LA SEULE QUESTION — jamais les passages — et rend deux
    sous-questions autonomes, une par besoin d'information. C'est ce qu'une
    decomposition de requete dans `src/` aurait a sa disposition, et pas plus :
    lui montrer les passages ferait ecrire la reponse dans la requete et le
    chiffre ne dirait plus rien de ce qu'un vrai decomposeur gagnerait.

    `thinking=False` passe par `chat_template_kwargs` PAR REQUETE : rien n'est
    pose cote serveur, `vllm-central` appartenant a l'equipe voisine. Les prompts
    sont DISTINCTS par construction — chaque question est differente — et la
    raison de fin est relevee a chaque generation : une reponse coupee par
    `max_tokens` rend un JSON invalide, donc un rejet, que rien ne distinguerait
    d'un refus de forme si les deux n'etaient pas comptes separement.
    """
    from src.agent.dialecte_llm import dialecte_courant
    from src.agent.flux_llm import charge_du_corps

    dialecte = dialecte_courant()._replace(hote=hote, modele=modele)
    cache: dict[str, Any] = {}
    raisons: list[str] = []
    pannes: list[str] = []
    for index, q in enumerate(questions, 1):
        prompt = (
            "This question requires information from TWO different sections of a "
            "technical corpus. Split it into exactly two standalone sub-questions, "
            "each asking for ONE of the two distinct information needs. Each "
            "sub-question must be self-contained and answerable on its own.\n\n"
            f"Question: {q['question']}\n\n"
            'Answer with JSON only: {"a": "<first sub-question>", "b": "<second sub-question>"}'
        )
        charge = dialecte.charge(
            [{"role": "user", "content": prompt}],
            stream=False,
            temperature=0.2,
            max_tokens=400,
            thinking=False,
            graine=graine,
            format_json=True,
        )
        try:
            reponse = httpx.post(dialecte.url_chat, json=charge, timeout=timeout)
            reponse.raise_for_status()
            corps = reponse.json()
            raisons.append(str((corps.get("choices") or [{}])[0].get("finish_reason")))
            donnees = json.loads(charge_du_corps(corps).get("content") or "")
            sous = [str(donnees.get("a") or "").strip(), str(donnees.get("b") or "").strip()]
            if all(sous):
                cache[q["id"]] = sous
            else:
                pannes.append(f"{q['id']}: sous-question vide")
        except Exception as panne:  # noqa: BLE001 — absorption large ASSUMEE, et DITE
            pannes.append(f"{q['id']}: {type(panne).__name__}: {panne}")
        if index % 10 == 0:
            print(f"  {index}/{len(questions)}", flush=True)
    return {
        "etape": "sous-questions",
        "modele": modele,
        "generations": len(questions),
        "raisons_de_fin": {r: raisons.count(r) for r in sorted(set(raisons))},
        "prompts_distincts": len({q["question"] for q in questions}),
        "pannes": pannes,
        "cache": cache,
    }


def etape_oracle(questions: list[dict[str, Any]], port_sante: int) -> dict[str, Any]:
    """L'ORACLE contre la REQUETE UNIQUE, a profondeur de production.

    Trois requetes par question, et la comparaison est APPARIEE :

    - **la requete unique SANS TRADUCTION**, qui est la base de comparaison de
      l'oracle. Les requetes oracles n'ont pas de traduction en cache, et le banc
      n'en fabrique pas ; comparer un oracle sans traduction a une requete unique
      AVEC traduction melerait deux changements en un.
    - **l'oracle `preuve`**, deterministe, construit depuis le passage.
    - **l'oracle `decomposition`**, ecrit par le modele depuis la seule question,
      lu dans le cache et jamais fabrique ici.
    """
    if not CACHE_SOUS_QUESTIONS.exists():
        raise SystemExit(
            f"ABSENT : {CACHE_SOUS_QUESTIONS}. Joue d'abord "
            "scripts/mesurer_recuperation.py --etape sous-questions."
        )
    cache: dict[str, list[str]] = json.loads(CACHE_SOUS_QUESTIONS.read_text(encoding="utf-8"))
    manquantes = [q["id"] for q in questions if q["id"] not in cache]
    if manquantes:
        raise SystemExit(
            f"REFUS : {len(manquantes)} question(s) sans sous-questions en cache "
            f"({', '.join(manquantes[:5])}…). L'oracle serait mesure sur un autre jeu."
        )

    debut = etat_des_stores(port_sante)
    lignes: list[dict[str, Any]] = []
    t0 = time.perf_counter()
    for index, q in enumerate(questions, 1):
        ancrages = list(q["gold_element_ids"])
        origine = q.get("_origine") or {}
        details = [origine.get("ancrage_a") or {}, origine.get("ancrage_b") or {}]
        # Les details sont apparies aux identifiants par l'identifiant, jamais
        # par la position : un jeu dont l'ordre de `gold_element_ids` differerait
        # de celui de `_origine` ferait interroger chaque ancrage avec la preuve
        # de l'autre, et le banc rendrait un oracle qui ECHOUE sans une erreur.
        par_id = {d.get("element_id"): d for d in details if d.get("element_id")}
        inconnus = [eid for eid in ancrages if eid not in par_id]
        if inconnus:
            raise SystemExit(f"REFUS : {q['id']} — ancrage sans `_origine` : {inconnus}")

        sans_traduction = rangs_des_ancrages(q["question"], ancrages, traduction=None)

        oracle_preuve: dict[str, Any] = {}
        for eid in ancrages:
            requete = requete_oracle_preuve(par_id[eid])
            if not requete:
                oracle_preuve[eid] = None
                continue
            oracle_preuve[eid] = rangs_des_ancrages(requete, [eid], traduction=None)["rangs"][eid]

        sous = cache[q["id"]]
        rangs_sous = [rangs_des_ancrages(s, ancrages, traduction=None)["rangs"] for s in sous]
        matrice = [[rangs_sous[i][eid]["rerank"] for eid in ancrages] for i in range(len(sous))]
        permutation, rangs_retenus = affectation_au_mieux(matrice)

        lignes.append(
            {
                "id": q["id"],
                "gold": ancrages,
                "requete_unique_sans_traduction": sans_traduction["rangs"],
                "oracle_preuve": oracle_preuve,
                "sous_questions": sous,
                "oracle_decomposition_matrice": matrice,
                "oracle_decomposition_permutation": permutation,
                "oracle_decomposition_rerank": dict(zip(ancrages, rangs_retenus, strict=True)),
            }
        )
        if index % 10 == 0:
            print(f"  {index}/{len(questions)} — {time.perf_counter() - t0:.0f} s", flush=True)

    fin = etat_des_stores(port_sante)
    return {
        "etape": "oracle",
        "profondeurs": profondeurs_en_vigueur(),
        "stores": {"debut": debut, "fin": fin},
        "lignes": lignes,
        "secondes": round(time.perf_counter() - t0, 1),
    }


def etape_textes(questions: list[dict[str, Any]], port_sante: int) -> dict[str, Any]:
    """H3 — CE QUE CHROMADB PORTE REELLEMENT sur chaque ancrage.

    Le texte recolle de l'element, sa longueur, le nombre de chunks qui le
    composent, et la part des jetons de la `preuve` qui s'y retrouvent. Un
    ancrage dont la preuve n'est pas dans le texte indexe ne sera ramene par
    aucune requete faite de cette preuve, et c'est le seul fait qui separe « la
    requete manque » de « le texte manque ».
    """
    from src.agent.retriever import _get_chroma_collection, full_texts

    debut = etat_des_stores(port_sante)
    par_id: dict[str, dict[str, Any]] = {}
    for q in questions:
        origine = q.get("_origine") or {}
        for cle in ("ancrage_a", "ancrage_b"):
            detail = origine.get(cle) or {}
            eid = detail.get("element_id")
            if eid:
                par_id.setdefault(eid, detail)

    tous = sorted(par_id)
    textes = full_texts(tous)
    collection = _get_chroma_collection()
    enregistrements = collection.get(
        where={"element_id": {"$in": tous}},  # type: ignore[dict-item]
        include=["metadatas"],
    )
    n_chunks: dict[str, int] = {}
    for meta in enregistrements.get("metadatas") or []:
        eid = str((meta or {}).get("element_id") or "")
        if eid:
            n_chunks[eid] = n_chunks.get(eid, 0) + 1

    fiches: dict[str, Any] = {}
    for eid in tous:
        corps = (textes.get(eid) or "").strip()
        preuve = (par_id[eid].get("preuve") or "").strip()
        part = couverture(preuve, corps) if corps else None
        fiches[eid] = {
            "indexe": bool(corps),
            "longueur": len(corps),
            "n_chunks": n_chunks.get(eid, 0),
            "emiette": bool(corps) and len(corps) < _CHUNK_EMIETTE,
            "part_preuve": None if part is None else round(part, 4),
            "preuve_portee": None if part is None else part >= _SEUIL_PREUVE,
            "section_title": par_id[eid].get("section_title"),
        }
    # LES TÉMOINS DU DÉTECTEUR, JOUÉS SUR LES MÊMES STORES. Chacune des trois
    # natures que cette étape peut rendre doit être VUE au moins une fois, sinon
    # un compte à zéro ne dit pas si la cause est absente ou si le détecteur est
    # aveugle. Les trois sont mesurés ici, pas seulement raisonnés :
    #
    #   - `hors_chromadb` : un identifiant FABRIQUÉ, de la bonne forme, que rien
    #     n'indexe. `full_texts` l'omet, donc `indexe` doit tomber à faux.
    #   - `preuve_non_portee` : un ancrage RÉEL confronté à la preuve d'un AUTRE
    #     ancrage. La part doit passer sous le seuil.
    #   - `emiette` : un corps plus court que le plancher, que le corpus ne
    #     fournit pas — il est donc posé, et la borne est éprouvée sur lui.
    fabrique = "0000000000"
    temoin_absent = full_texts([fabrique]).get(fabrique)
    premier, second = tous[0], tous[1]
    part_croisee = couverture(par_id[second].get("preuve") or "", textes.get(premier) or "")
    temoins = {
        "hors_chromadb": {
            "element_id_fabrique": fabrique,
            "indexe": bool((temoin_absent or "").strip()),
            "vu": not (temoin_absent or "").strip(),
        },
        "preuve_non_portee": {
            "texte_de": premier,
            "preuve_de": second,
            "part": None if part_croisee is None else round(part_croisee, 4),
            "vu": part_croisee is not None and part_croisee < _SEUIL_PREUVE,
        },
        "emiette": {
            "longueur_posee": _CHUNK_EMIETTE - 1,
            "vu": (_CHUNK_EMIETTE - 1) < _CHUNK_EMIETTE,
        },
    }

    fin = etat_des_stores(port_sante)
    return {
        "etape": "textes",
        "temoins_du_detecteur": temoins,
        "seuil_preuve": _SEUIL_PREUVE,
        "chunk_emiette": _CHUNK_EMIETTE,
        "stores": {"debut": debut, "fin": fin},
        "ancrages_distincts": len(tous),
        "fiches": fiches,
    }


# LE CONTROLE POSITIF, ET IL EST ANTERIEUR A TOUT ELARGISSEMENT. Les trois
# chiffres du §4.76, mesures le 24 septembre 2026 a profondeur de production sur
# le meme jeu et les memes stores. Un banc qui ne les retrouve PAS a l'unite pres
# ne mesure pas la meme chose, et ce qu'il dirait des profondeurs elargies
# n'aurait aucune base de comparaison.
CONTROLE_4_76 = {"dense": 56, "fusion": 46, "rerank": 67}


def controle_positif(prod: dict[str, Any]) -> dict[str, Any]:
    """Le banc retrouve-t-il, a l'unite pres, les trois chiffres du §4.76 ?

    Les trois sont des comptes d'ANCRAGES ABSENTS, a profondeur de production.
    Le rerank y est compte absent du top-`RERANK_TOP_K`, ce qui n'a de sens qu'a
    `RERANK_TOP_K=10` : le controle REFUSE une autre profondeur plutot que de
    comparer deux grandeurs qui portent le meme nom.
    """
    profondeurs = prod["profondeurs"]
    attendu_profondeurs = {"fetch_k": 50, "retrieval_top_k": 50, "rerank_top_k": 10}
    ecart_profondeur = {
        cle: (profondeurs.get(cle), valeur)
        for cle, valeur in attendu_profondeurs.items()
        if profondeurs.get(cle) != valeur
    }
    mesure = {
        etage: sum(
            1 for ligne in prod["lignes"] for r in ligne["rangs"].values() if r[etage] is None
        )
        for etage in CONTROLE_4_76
    }
    return {
        "attendu_4_76": dict(CONTROLE_4_76),
        "mesure": mesure,
        "profondeurs_attendues": attendu_profondeurs,
        "profondeurs_lues": {c: profondeurs.get(c) for c in attendu_profondeurs},
        "ecart_de_profondeur": ecart_profondeur,
        "ancrages": sum(len(ligne["gold"]) for ligne in prod["lignes"]),
        "accord": not ecart_profondeur and mesure == dict(CONTROLE_4_76),
    }


def etape_causes(
    prod: dict[str, Any],
    profonds: list[dict[str, Any]],
    oracle: dict[str, Any],
    textes: dict[str, Any],
) -> dict[str, Any]:
    """LE TABLEAU DE CAUSES, qui somme au nombre d'ancrages.

    Il n'accede a aucun store : il assemble des bilans deja versionnes. C'est
    delibere — la table peut donc etre rejouee sur les memes fichiers, et deux
    lectures du meme etat des stores ne peuvent pas diverger.
    """
    controle = controle_positif(prod)
    if not controle["accord"]:
        raise SystemExit(
            "REFUS : le controle positif du §4.76 ne passe pas — "
            f"{controle['mesure']} contre {controle['attendu_4_76']}, "
            f"profondeurs {controle['profondeurs_lues']}. "
            "Elargir a partir d'une base qui ne se recoupe pas ne mesurerait rien."
        )

    # LA PLUS GRANDE PROFONDEUR MESUREE, choisie sur le chiffre LU dans chaque
    # bilan et non sur l'ordre des fichiers donnes en argument.
    le_plus_profond = max(profonds, key=lambda b: b["profondeurs"]["retrieval_top_k"])
    rangs_profonds = {
        (ligne["id"], eid): r
        for ligne in le_plus_profond["lignes"]
        for eid, r in ligne["rangs"].items()
    }
    oracle_par_ancrage = {
        (ligne["id"], eid): (etat or {}).get("rerank") if etat else None
        for ligne in oracle["lignes"]
        for eid, etat in ligne["oracle_preuve"].items()
    }
    decomposition_par_ancrage = {
        (ligne["id"], eid): rang
        for ligne in oracle["lignes"]
        for eid, rang in ligne["oracle_decomposition_rerank"].items()
    }
    fiches = textes["fiches"]

    observations: list[dict[str, Any]] = []
    for ligne in prod["lignes"]:
        for eid, rangs in ligne["rangs"].items():
            profond = rangs_profonds.get((ligne["id"], eid), {})
            observation = {
                "question": ligne["id"],
                "element_id": eid,
                "rang_dense_prod": rangs["dense"],
                "rang_lexical_prod": rangs["lexical"],
                "rang_fusion_prod": rangs["fusion"],
                "rang_rerank_prod": rangs["rerank"],
                "rang_fusion_profond": profond.get("fusion"),
                "rang_rerank_profond": profond.get("rerank"),
                "indexe": bool((fiches.get(eid) or {}).get("indexe")),
                "part_preuve": (fiches.get(eid) or {}).get("part_preuve"),
                "oracle_rerank": oracle_par_ancrage.get((ligne["id"], eid)),
                "oracle_decomposition_rerank": decomposition_par_ancrage.get((ligne["id"], eid)),
            }
            observation["cause"] = classer_la_cause(observation)
            observations.append(observation)

    comptes = {cause: sum(1 for o in observations if o["cause"] == cause) for cause in CAUSES}

    # LE CROISEMENT AVEC L'ORACLE, ET C'EST LA LECTURE ACTIONNABLE. L'arbre des
    # causes nomme l'ETAGE qui perd l'ancrage ; il ne dit pas si une requete
    # mieux posee le retrouverait au MEME etage. Les deux oracles le disent,
    # cause par cause :
    #
    #   - `preuve` borne par le haut ce que le passage peut rendre ;
    #   - `decomposition` borne ce qu'un decomposeur de requete dans `src/`
    #     pourrait gagner, puisqu'il ne voit que la question.
    #
    # Une cause ou les deux oracles recuperent tout n'est PAS une cause de
    # l'etage qu'elle nomme : c'est la requete, vue depuis cet etage.
    croisement = {
        cause: {
            "ancrages": comptes[cause],
            "oracle_preuve_dans_le_haut": sum(
                1 for o in observations if o["cause"] == cause and dans_le_haut(o["oracle_rerank"])
            ),
            "oracle_decomposition_dans_le_haut": sum(
                1
                for o in observations
                if o["cause"] == cause and dans_le_haut(o["oracle_decomposition_rerank"])
            ),
        }
        for cause in CAUSES
    }

    return {
        "etape": "causes",
        "causes_croisees_avec_l_oracle": croisement,
        "controle_positif": controle,
        "profondeur_du_large": le_plus_profond["profondeurs"],
        "causes": comptes,
        "somme": sum(comptes.values()),
        "ancrages": len(observations),
        "observations": observations,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--etape",
        required=True,
        choices=["profondeurs", "sous-questions", "oracle", "textes", "causes"],
    )
    parser.add_argument(
        "--jeu", type=Path, default=ROOT / "tests" / "fixtures" / "jeu_ancrages_disperses.yaml"
    )
    parser.add_argument("--sortie", type=Path, required=True)
    parser.add_argument("--port-sante", type=int, default=8011)
    parser.add_argument("--limite", type=int, default=0)
    parser.add_argument("--llm-host", default="http://localhost:8100")
    parser.add_argument("--model", default="google/gemma-4-E4B-it-qat-w4a16-ct")
    parser.add_argument("--timeout", type=float, default=300.0)
    parser.add_argument("--seed", type=int, default=37)
    parser.add_argument("--prod", type=Path, help="Bilan a profondeur de production")
    parser.add_argument("--profond", type=Path, nargs="*", default=[], help="Bilans elargis")
    parser.add_argument("--oracle", type=Path, help="Bilan de l'oracle (etape causes)")
    parser.add_argument("--textes", type=Path, help="Bilan des textes indexes (etape causes)")
    args = parser.parse_args()

    questions = charger_questions(args.jeu)
    if args.limite:
        questions = questions[: args.limite]
    print(f"{len(questions)} questions, etape {args.etape}", flush=True)

    if args.etape == "profondeurs":
        bilan = etape_profondeurs(questions, args.port_sante)
    elif args.etape == "sous-questions":
        bilan = etape_sous_questions(questions, args.llm_host, args.model, args.timeout, args.seed)
    elif args.etape == "oracle":
        bilan = etape_oracle(questions, args.port_sante)
    elif args.etape == "textes":
        bilan = etape_textes(questions, args.port_sante)
    else:
        if not (args.prod and args.profond and args.oracle and args.textes):
            print("REFUS : --prod, --profond, --oracle et --textes sont exiges.")
            return 2
        bilan = etape_causes(
            json.loads(args.prod.read_text(encoding="utf-8")),
            [json.loads(p.read_text(encoding="utf-8")) for p in args.profond],
            json.loads(args.oracle.read_text(encoding="utf-8")),
            json.loads(args.textes.read_text(encoding="utf-8")),
        )

    # L'ETAT DES STORES EST UN REFUS, PAS UNE NOTE. Une campagne qui a vu deux
    # etats des stores rend un tableau dont chaque ligne est juste et dont le
    # total ne decrit rien ; elle sort en 1 et le DIT.
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
    if args.etape == "sous-questions":
        CACHE_SOUS_QUESTIONS.write_text(
            json.dumps(bilan["cache"], ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"cache : {len(bilan['cache'])}/{len(questions)} dans {CACHE_SOUS_QUESTIONS}")
        print(f"raisons de fin : {bilan['raisons_de_fin']}")
    if args.etape == "causes":
        print(f"\ncontrole positif §4.76 : {bilan['controle_positif']['mesure']} — ACCORD")
        for cause, compte in bilan["causes"].items():
            print(f"  {cause:<26} {compte:>4}")
        print(f"  {'SOMME':<26} {bilan['somme']:>4}  (ancrages : {bilan['ancrages']})")
    print(f"ecrit : {args.sortie}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
