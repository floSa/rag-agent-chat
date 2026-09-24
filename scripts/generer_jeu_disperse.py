#!/usr/bin/env python
"""Genere un jeu de questions dont chaque question exige DEUX sections distinctes.

POURQUOI CE JEU EXISTE, ET CE QU'IL REPARE. La chaine a quatre etages —
`FETCH_K=50` → `RETRIEVAL_TOP_K=50` → `RERANK_TOP_K=10` → `AUTO_SELECT_TOP_K=3`
— et le §4.67 du registre a mesure que le jeu de reglage est **aveugle au
quatrieme** : 120 de ses 130 ancrages atteignent le prompt des `k=1`, 4 de plus
a `k=2`, et **plus aucun jusqu'a k=20**. La cause est ecrite dans son propre
`_lisez_moi` : *la question a ete ecrite POUR le passage*. Une question quasi
paraphrase de son unique passage sort au rang 1, et **une** section reconstruite
la reussit. Son plateau ne dit pas « 3 suffit » ; il dit « ce jeu ne teste pas
k ».

CE QUE CE GENERATEUR CHANGE, ET C'EST STRUCTUREL, PAS COSMETIQUE. Une question
est ecrite a partir de **deux** passages vivant dans **deux sections
differentes**, et le jeu ne la garde que si trois conditions independantes
tiennent. Aucune des trois ne regarde le retrieval : un filtre qui selectionnerait
les questions sur le rang mesure de leurs ancrages rendrait l'instrument
tautologique — il mesurerait ce pour quoi il a ete trie.

1. **LA CONDITION DE RECONSTRUCTION, et c'est la seule qui soit une PREUVE.**
   `reconstruct_section` ne rend pas un element : il rend sa section ET ses
   voisines. Deux ancrages voisins seraient donc ramenes par UNE seule
   reconstruction, et la question se reussirait a k=1 en ne selectionnant qu'un
   element. On reconstruit donc la section de chaque ancrage et on EXIGE que le
   markdown de l'une ne porte pas l'autre, **dans les deux sens**. C'est une
   mesure, pas une heuristique : elle etablit qu'il faut **deux** entrees du
   classement pour que les deux ancrages atteignent le prompt.
2. **LA CONDITION DE NON-SUFFISANCE**, jugee par le modele sur chaque passage
   PRIS SEUL, en deux appels separes : un passage qui suffit a repondre rend la
   question mono-ancrage deguisee. Sa limite est ecrite au `_lisez_moi` du jeu :
   le juge est le modele qui a ecrit la question, il n'est pas independant.
3. **LES GARDES LEXICAUX**, repris de `generate_golden.py` : preuve recopiee mot
   pour mot dans SON passage, vocabulaire distinctif partage avec **chacun** des
   deux passages, et la question ne recopie aucune des deux preuves.

CE QUE CE JEU NE CASSE PAS, ET IL FAUT LE DIRE ICI. La question reste ecrite
POUR ses deux passages. La circularite n'est pas supprimee, elle est **deplacee**
: chaque moitie de la question peut encore retrouver son passage au rang 1. Ce
que le jeu casse, c'est l'equivalence « une section reconstruite suffit », et
c'est exactement ce que le quatrieme etage tronque.

    uv run --no-sync python scripts/generer_jeu_disperse.py --count 60

LE JEU S'ECRIT EN YAML, pour la raison mesuree au docstring de
`scripts/generate_golden.py` : le transformateur YAML de `detect-secrets` ne lit
pas les elements de sequence, et les `element_id` y vivent.
"""

from __future__ import annotations

import argparse
import collections
import json
import random
import re
import sys
import time
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

# APRES les `sys.path.insert` : ni la racine du depot ni `scripts/` ne sont des
# paquets, et ces imports n'existent qu'une fois les deux chemins poses.
from generate_golden import (  # noqa: E402 — voir ci-dessus
    _MAX_CHARS,
    _MAX_PART_CODE,
    _MIN_CHARS,
    _MIN_SHARED_TERMS,
    _normalise,
    ecrire,
    part_de_code,
)

from src.agent.dialecte_llm import dialecte_courant  # noqa: E402 — voir ci-dessus
from src.agent.flux_llm import charge_du_corps  # noqa: E402 — voir ci-dessus

# CE QUI A ETE AVALE, GARDE POUR ETRE DIT A LA FIN. Meme geste que
# `generate_golden._PANNES` et pour la meme raison : une panne de dialecte
# repetee a chaque appel se lit comme un taux de rejet eleve, donc comme un
# corpus difficile, et la campagne rend un jeu vide en sortant a zero.
_PANNES: list[str] = []
# LES RAISONS DE FIN, RELEVEES A CHAQUE GENERATION. Une reponse tronquee par le
# plafond de sortie (`finish_reason: length`) rend un JSON invalide, donc un
# rejet — indiscernable d'un refus de garde si on ne compte pas les deux.
_RAISONS_DE_FIN: list[str] = []

_MIN_QUESTION_CHARS = 40
_MAX_QUESTION_CHARS = 320

# ECART MINIMAL, EN RANG DE SECTION DANS LE CHAPITRE, entre les deux sections
# d'une paire intra-document. Ce n'est PAS la garantie — la garantie est la
# condition de reconstruction, qui est mesuree paire par paire — c'est ce qui
# rend la paire PLAUSIBLE avant de payer un appel au modele : `reconstruct_section`
# ramene la section et ses voisines, donc deux sections contigues seraient
# ramenees ensemble et la paire serait rejetee plus tard, apres l'appel.
_ECART_MIN_SECTIONS = 6

# TITRES DE SECTION ECARTES, ET LA RAISON N'EST PAS LE GOUT. Une section de
# resume — conclusion, points cles, « ce que vous allez apprendre » — REDIT ce
# que d'autres sections disent en detail. Son passage n'y est donc plus le seul
# a porter le fait, et l'ancrage cesse d'etre une verite terrain : le retrieval
# peut rendre le passage detaille, qui repond, et le banc le comptera perdu.
# Le filtre porte sur le TITRE, jamais sur le rang mesure d'un ancrage.
_TITRES_ECARTES = re.compile(
    r"^\s*(conclusion|summary|key takeaways?|what you will learn|preface|foreword|"
    r"introduction|table of contents|index|about the author|acknowledg)",
    re.I,
)

_LANGUES = {"fr": "français", "en": "anglais"}
# Part des questions posees dans une AUTRE langue que le corpus. Le corpus est
# entierement anglais (`mesure` : 4 367 chunks sur 4 367 en `language: en`),
# donc seul le sens « question francaise → document anglais » est mesurable.
#
# CE REGLAGE NE MORD PAS, ET C'EST `mesure`, PAS SUPPOSE : sur les 139 paires
# examinees le 24 septembre 2026, le jeu produit porte **60 questions anglaises
# et ZERO francaise**. La cause est le garde de vocabulaire partage, qui exige
# deux jetons communs avec CHACUN des deux passages : les passages sont anglais,
# et une question francaise n'en partage pas deux. Les questions francaises
# tirees ici sont donc toutes tombees dans `gardes_lexicaux`, ce qui explique
# aussi le taux de rejet. LE JEU EST MONOLINGUE, son `_statistiques` le dit, et
# la reparation — juger le vocabulaire partage sur la TRADUCTION de la question
# — n'est pas faite : elle ferait dependre la fabrication du jeu d'un second
# appel au modele, et elle merite sa propre mesure. Question ouverte au §4.76.
_PART_TRANSLINGUISTIQUE = 0.30

PROMPT_QUESTION = """Tu lis DEUX extraits distincts d'une documentation technique.

Écris UNE question dont la réponse complète exige un fait de l'extrait A **et**
un fait de l'extrait B. Aucun des deux extraits pris seul ne doit suffire.

Contraintes impératives :
- Écris la question EN {langue_nom}, quelle que soit la langue des extraits.
- Ne recopie pas les phrases des extraits : reformule.
- Elle doit se comprendre seule, sans avoir les extraits sous les yeux.
- Elle ne doit PAS contenir sa propre réponse.
- N'écris pas « selon l'extrait », « dans ce texte », ni aucune référence aux documents.
- Une seule question, pas deux questions collées par « et » qui seraient
  indépendantes : la réponse doit relier les deux faits.
- Cite ensuite la phrase EXACTE de A qui porte le premier fait, puis la phrase
  EXACTE de B qui porte le second, recopiées mot pour mot.

Réponds en JSON strict, sans rien autour :
{{"question": "...", "preuve_a": "...", "preuve_b": "..."}}

Extrait A ({titre_a}) :
---
{passage_a}
---

Extrait B ({titre_b}) :
---
{passage_b}
---
"""

PROMPT_SUFFISANCE = """Voici une question, et UN SEUL extrait de documentation.

Question : {question}

Extrait :
---
{passage}
---

Cet extrait, PRIS SEUL, permet-il de répondre COMPLÈTEMENT à la question ?
Réponds « true » seulement si rien d'autre n'est nécessaire.

Réponds en JSON strict, sans rien autour :
{{"suffit": true ou false, "manque": "ce qui manque, en une phrase"}}
"""

_LISEZ_MOI = [
    "JEU A ANCRAGES MULTIPLES ET DISPERSES. Chaque question exige",
    "l'information de DEUX sections distinctes, et porte un ancrage par",
    "section. Il repond a la dette ouverte au §4.67 du registre : les deux",
    "jeux anterieurs ne peuvent pas arbitrer AUTO_SELECT_TOP_K — le jeu de",
    "reglage est AVEUGLE a la selection (120 ancrages sur 130 au prompt des",
    "k=1, plus aucun de k=3 a k=20), et le jeu de controle la voit mais ne",
    "porte que 26 questions.",
    "",
    "METHODE DE CONSTRUCTION, par scripts/generer_jeu_disperse.py. Deux",
    "passages de deux sections differentes sont tires du corpus, puis une",
    "question est ecrite a partir des DEUX. Trois conditions independantes",
    "la retiennent, et AUCUNE ne regarde le retrieval :",
    "",
    "  1. CONDITION DE RECONSTRUCTION, la seule qui soit une preuve. La",
    "     section de chaque ancrage est reconstruite par reconstruct_section,",
    "     et le markdown de l'une ne doit PAS porter l'autre ancrage, dans",
    "     les DEUX sens. Sans elle, deux ancrages voisins seraient ramenes",
    "     par UNE seule reconstruction et la question se reussirait a k=1.",
    "  2. CONDITION DE NON-SUFFISANCE : le modele juge chaque passage PRIS",
    "     SEUL, en deux appels separes ; la question n'est gardee que si",
    "     aucun des deux ne suffit.",
    "  3. GARDES LEXICAUX repris de generate_golden.py : preuve recopiee mot",
    "     pour mot dans SON passage, vocabulaire distinctif partage avec",
    "     CHACUN des deux passages, question qui ne recopie aucune preuve.",
    "",
    "Les sections de RESUME sont ecartees en amont, par leur titre :",
    "conclusion, points cles, preface, sommaire. Elles redisent ce que",
    "d'autres sections detaillent, donc leur passage n'est plus le seul a",
    "porter le fait et l'ancrage cesse d'etre une verite terrain.",
    "",
    "LA LIMITE, ET ELLE EST STRUCTURELLE. La question reste ecrite POUR ses",
    "deux passages : la circularite n'est pas supprimee, elle est DEPLACEE.",
    "Chaque moitie de la question peut encore retrouver son passage au rang",
    "1. Ce que ce jeu casse est l'equivalence « une section reconstruite",
    "suffit », qui est exactement ce que le quatrieme etage tronque. Et le",
    "juge de non-suffisance est le MODELE QUI A ECRIT LA QUESTION : il n'est",
    "pas independant, et une paire qu'il declare a tort insuffisante passe.",
    "",
    "LE JEU EST MONOLINGUE ANGLAIS, et ce n'etait pas voulu : le generateur",
    "tirait 30 % de questions francaises, et le garde de vocabulaire partage",
    "les a TOUTES rejetees — les passages sont anglais, une question",
    "francaise n'en partage pas deux jetons. L'axe translinguistique que les",
    "deux autres jeux portent est donc ABSENT de celui-ci.",
    "",
    "reviewed: false = non relu par un humain, sur AUCUNE question.",
    "",
    "CE JEU NE PROUVE RIEN TANT QUE SES `gold_element_ids` N'ONT PAS ETE",
    "CONFRONTES AUX STORES : un jeu qui designe le vide rend 0 % de rappel",
    "sans dire si la recherche est cassee ou si le jeu est perime.",
    "L'instrument est scripts/verifier_les_ancrages.py, et il sort en 1 au",
    "premier desaccord.",
]

_RESERVE = (
    "INSTRUMENT DE SELECTION, PAS VERDICT. Ce jeu est fait pour voir k, et "
    "il ne dit rien d'autre : le rappel d'un ancrage au prompt n'est pas la "
    "qualite d'une reponse, et aucune generation n'entre dans sa fabrication "
    "au-dela de l'ecriture des questions. Tout ecart se lit sur le nombre de "
    "QUESTIONS qui ont bascule, jamais sur la difference des pourcentages. La "
    "grandeur qui compte ici est le nombre de questions dont TOUS les ancrages "
    "atteignent le prompt : celle d'AU MOINS UN se sature des k=1 par "
    "construction et ne mesure que la recuperation. Et ce jeu decrit L'ETAT DES "
    "STORES A SA DATE : il ne survit pas a une reingestion."
)


def charger_passages(host: str, port: int) -> tuple[list[dict[str, Any]], int]:
    """Lit tout l'index et rend les passages exploitables, section par section.

    Memes filtres que `generate_golden.charger_passages` — bornes de taille,
    part de code, titre de section present — plus `reference_id` et
    `page_position`, que l'appelant a besoin de lire pour APPARIER : le premier
    identifie la section, le second ordonne les sections dans le chapitre.
    """
    import chromadb

    collection = chromadb.HttpClient(host=host, port=port).get_collection("rag_documents")
    total = collection.count()
    passages: list[dict[str, Any]] = []

    for offset in range(0, total, 2000):
        lot = collection.get(limit=2000, offset=offset, include=["documents", "metadatas"])
        for doc, meta in zip(lot.get("documents") or [], lot.get("metadatas") or [], strict=False):
            texte = (doc or "").strip()
            if not (_MIN_CHARS <= len(texte) <= _MAX_CHARS):
                continue
            if part_de_code(texte) > _MAX_PART_CODE:
                continue
            if not meta.get("section_title"):
                continue
            if not meta.get("reference_id"):
                continue
            if _TITRES_ECARTES.search(meta.get("section_title") or ""):
                continue
            passages.append(
                {
                    "texte": texte,
                    "element_id": meta.get("element_id", ""),
                    "reference_id": meta.get("reference_id", ""),
                    "source_path": meta.get("source_path", ""),
                    "language": meta.get("language", ""),
                    "section_title": meta.get("section_title", ""),
                    "page_no": int(meta.get("page_no") or 0),
                    "page_position": int(meta.get("page_position") or 0),
                }
            )

    print(f"{len(passages)} passages exploitables sur {total} chunks indexes.")
    return passages, total


def un_passage_par_section(passages: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Garde le passage le PLUS LONG de chaque section.

    Un ancrage par section est la regle du jeu ; il faut donc choisir lequel. Le
    plus long est celui qui porte le plus de matiere pour ecrire une question
    specifique, et le choix est DETERMINISTE — a longueur egale, l'`element_id`
    departage — pour qu'une regeneration ne deplace pas les ancrages sans raison.
    """
    meilleur: dict[str, dict[str, Any]] = {}
    for p in passages:
        ancien = meilleur.get(p["reference_id"])
        cle = (len(p["texte"]), p["element_id"])
        if ancien is None or cle > (len(ancien["texte"]), ancien["element_id"]):
            meilleur[p["reference_id"]] = p
    return meilleur


def apparier(
    sections: dict[str, dict[str, Any]], combien: int, graine: int
) -> list[tuple[dict[str, Any], dict[str, Any], str]]:
    """Construit des paires de sections, en DEUX strates, sans toucher au retrieval.

    - `intra_chapitre` : deux sections du meme chapitre, separees d'au moins
      `_ECART_MIN_SECTIONS` rangs. L'ecart n'est pas la garantie, c'est
      l'economie : la garantie est la condition de reconstruction, qui coute une
      lecture du graphe, et on evite de la payer sur des paires contigues.
    - `inter_chapitres` : deux sections de deux chapitres differents. C'est la
      strate qui DISPERSE le plus, parce que la question y porte deux sujets que
      le corpus ne rapproche nulle part.

    Les chapitres sont parcourus en TOURNIQUET : chacun contribue avant qu'aucun
    ne contribue deux fois. Sans cela, le chapitre le plus fourni monopoliserait
    le jeu — `generate_golden.echantillonner` avait deja paye cette lecon.
    """
    hasard = random.Random(graine)
    par_chapitre: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
    for s in sections.values():
        par_chapitre[s["source_path"]].append(s)
    for chapitre in par_chapitre:
        par_chapitre[chapitre].sort(
            key=lambda s: (s["page_no"], s["page_position"], s["element_id"])
        )

    chapitres = sorted(par_chapitre)
    hasard.shuffle(chapitres)

    paires: list[tuple[dict[str, Any], dict[str, Any], str]] = []
    vues: set[tuple[str, str]] = set()

    def ajouter(a: dict[str, Any], b: dict[str, Any], strate: str) -> None:
        cle = tuple(sorted((a["reference_id"], b["reference_id"])))
        if cle in vues or a["reference_id"] == b["reference_id"]:
            return
        vues.add(cle)  # type: ignore[arg-type]
        paires.append((a, b, strate))

    # Moitie / moitie entre les deux strates, et le tourniquet alterne pour que
    # l'arret a `combien` ne coupe pas une strate entiere.
    tour = 0
    while len(paires) < combien and tour < 200:  # noqa: PLR2004 — borne d'arret, non un reglage
        avant = len(paires)
        for chapitre in chapitres:
            liste = par_chapitre[chapitre]
            if len(liste) > _ECART_MIN_SECTIONS:
                i = hasard.randrange(len(liste) - _ECART_MIN_SECTIONS)
                j = hasard.randrange(i + _ECART_MIN_SECTIONS, len(liste))
                ajouter(liste[i], liste[j], "intra_chapitre")
            autre = chapitres[(chapitres.index(chapitre) + 1 + tour) % len(chapitres)]
            if autre != chapitre and par_chapitre[autre]:
                a = liste[hasard.randrange(len(liste))]
                b = par_chapitre[autre][hasard.randrange(len(par_chapitre[autre]))]
                ajouter(a, b, "inter_chapitres")
            if len(paires) >= combien:
                break
        if len(paires) == avant:
            break
        tour += 1
    return paires[:combien]


def _appeler(
    prompt: str, hote: str, modele: str, timeout: float, graine: int, max_tokens: int
) -> dict[str, Any] | None:
    """Un appel non-flux, par le site unique du dialecte, et sa raison de fin relevee.

    `thinking=False` passe par `chat_template_kwargs`, PAR REQUETE : rien n'est
    pose cote serveur, `vllm-central` appartenant a l'equipe voisine.

    LA RAISON DE FIN EST RELEVEE A CHAQUE APPEL, et ce n'est pas decoratif : une
    reponse coupee par `max_tokens` rend `finish_reason: length` et un JSON
    invalide, donc un rejet — que rien ne distinguerait d'un refus de garde si
    les deux n'etaient pas comptes separement.
    """
    dialecte = dialecte_courant()._replace(hote=hote, modele=modele)
    charge = dialecte.charge(
        [{"role": "user", "content": prompt}],
        stream=False,
        temperature=0.4,
        max_tokens=max_tokens,
        thinking=False,
        graine=graine,
        format_json=True,
    )
    try:
        reponse = httpx.post(dialecte.url_chat, json=charge, timeout=timeout)
        reponse.raise_for_status()
        corps = reponse.json()
        choix = corps.get("choices") or [{}]
        _RAISONS_DE_FIN.append(str(choix[0].get("finish_reason")))
        return json.loads(charge_du_corps(corps).get("content") or "")
    except Exception as panne:  # noqa: BLE001 — absorption large ASSUMEE, et DITE
        _PANNES.append(f"{type(panne).__name__}: {panne}")
        return None


def _question_tient_debout(
    donnees: dict[str, Any], a: dict[str, Any], b: dict[str, Any]
) -> tuple[str, str, str] | None:
    """Les gardes LEXICAUX, sans aucun appel : question, preuve A, preuve B.

    Chacun rend `None` pour un motif different, et le motif est compte par
    l'appelant : un taux de rejet global ne dit pas si le modele reformule trop
    (preuve non recopiee) ou pas assez (question qui recopie sa preuve).
    """
    question = (donnees.get("question") or "").strip()
    preuve_a = (donnees.get("preuve_a") or "").strip()
    preuve_b = (donnees.get("preuve_b") or "").strip()
    if not (_MIN_QUESTION_CHARS <= len(question) <= _MAX_QUESTION_CHARS):
        return None
    if not preuve_a or not preuve_b:
        return None
    # Le modele doit RECOPIER la phrase, chacune dans SON passage. Croiser les
    # deux — la preuve de A cherchee dans B — laisserait passer une question
    # dont les deux faits viennent du meme extrait.
    if _normalise(preuve_a) - _normalise(a["texte"]):
        return None
    if _normalise(preuve_b) - _normalise(b["texte"]):
        return None
    # Du vocabulaire distinctif avec CHACUN des deux passages. Le exiger du seul
    # couple rendrait vert une question qui ne parle en fait que de A.
    if len(_normalise(question) & _normalise(a["texte"])) < _MIN_SHARED_TERMS:
        return None
    if len(_normalise(question) & _normalise(b["texte"])) < _MIN_SHARED_TERMS:
        return None
    reference = r"\b(extrait|ce texte|ce document|this (text|excerpt|document))\b"
    if re.search(reference, question, re.I):
        return None
    # Une question qui contient deja l'une de ses preuves ne teste rien.
    if _normalise(preuve_a) <= _normalise(question) or _normalise(preuve_b) <= _normalise(question):
        return None
    return question, preuve_a, preuve_b


def sections_reconstruites_disjointes(a: str, b: str) -> tuple[bool, dict[str, Any]]:
    """LA CONDITION DE RECONSTRUCTION, mesuree, dans les DEUX sens.

    `reconstruct_section(x)` rend la section de `x` ET ses voisines. Si le
    markdown de la section de `a` porte deja `b`, alors UNE seule entree du
    classement suffit a amener les deux ancrages au prompt, et la question ne
    teste pas la selection. On l'exige donc disjoint dans les deux sens, et on
    rend aussi les `section_id` reellement calcules — le `reference_id` de
    ChromaDB est une metadonnee du chunk, le `section_id` est ce que le GRAPHE
    repond, et rien ne garantit ici que les deux coincident.
    """
    from src.agent.graph import element_ids_presents
    from src.agent.graph_context import reconstruct_section

    ctx_a = reconstruct_section(a)
    ctx_b = reconstruct_section(b)
    dans_a = element_ids_presents(ctx_a.markdown)
    dans_b = element_ids_presents(ctx_b.markdown)
    detail = {
        "section_id_a": ctx_a.section_id,
        "section_id_b": ctx_b.section_id,
        "b_dans_a": b in dans_a,
        "a_dans_b": a in dans_b,
        "a_dans_a": a in dans_a,
        "b_dans_b": b in dans_b,
    }
    # LE CONTROLE POSITIF EST DANS LA CONDITION ELLE-MEME : on exige que chaque
    # ancrage soit present dans SA PROPRE reconstruction. Sans lui, une
    # reconstruction qui ne rendrait RIEN satisferait la disjonction et le jeu
    # se remplirait de paires que rien n'a verifiees.
    ok = (
        detail["a_dans_a"]
        and detail["b_dans_b"]
        and not detail["b_dans_a"]
        and not detail["a_dans_b"]
        and ctx_a.section_id != ctx_b.section_id
    )
    return ok, detail


def main() -> int:  # noqa: PLR0915 — une seule campagne, lue de haut en bas
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", type=int, default=60, help="Questions visees")
    parser.add_argument("--chroma-host", default="127.0.0.1")
    parser.add_argument("--chroma-port", type=int, default=8000)
    parser.add_argument("--llm-host", default="http://localhost:8100")
    parser.add_argument("--model", default="google/gemma-4-E4B-it-qat-w4a16-ct")
    parser.add_argument("--timeout", type=float, default=300.0)
    parser.add_argument("--seed", type=int, default=36)
    parser.add_argument(
        "--out", type=Path, default=ROOT / "tests" / "fixtures" / "jeu_ancrages_disperses.yaml"
    )
    parser.add_argument(
        "--journal",
        type=Path,
        default=None,
        help="Journal des rejets, ECRIT A CHAQUE PAIRE — un banc qui n'ecrit qu'a la fin "
             "perd tout au premier depassement de delai",
    )
    args = parser.parse_args()

    passages, total_chunks = charger_passages(args.chroma_host, args.chroma_port)
    if not passages:
        print("Aucun passage exploitable — l'index est-il peuple ?")
        return 1
    sections = un_passage_par_section(passages)
    print(f"{len(sections)} sections porteuses d'au moins un passage exploitable.")

    paires = apparier(sections, int(args.count * 3), args.seed)
    print(f"{len(paires)} paires appariees, generation en cours…")

    hasard = random.Random(args.seed)
    motifs: collections.Counter[str] = collections.Counter()
    questions: list[dict[str, Any]] = []
    journal: list[dict[str, Any]] = []
    index = 0
    t0 = time.perf_counter()

    for index, (a, b, strate) in enumerate(paires, 1):
        if len(questions) >= args.count:
            break
        langue_question = "fr" if hasard.random() < _PART_TRANSLINGUISTIQUE else "en"

        # LA CONDITION DE RECONSTRUCTION D'ABORD : elle ne coute qu'une lecture
        # du graphe, la generation coute trois appels au modele. Rejeter avant
        # de payer.
        try:
            disjointes, detail = sections_reconstruites_disjointes(a["element_id"], b["element_id"])
        except Exception as panne:  # noqa: BLE001 — une reconstruction qui leve est un rejet, et il est DIT
            _PANNES.append(f"reconstruction {type(panne).__name__}: {panne}")
            motifs["reconstruction_en_panne"] += 1
            journal.append({"paire": index, "motif": "reconstruction_en_panne"})
            continue
        if not disjointes:
            motifs["sections_non_disjointes"] += 1
            journal.append({"paire": index, "motif": "sections_non_disjointes", "detail": detail})
            continue

        donnees = _appeler(
            PROMPT_QUESTION.format(
                langue_nom=_LANGUES[langue_question],
                titre_a=a["section_title"],
                titre_b=b["section_title"],
                passage_a=a["texte"],
                passage_b=b["texte"],
            ),
            args.llm_host, args.model, args.timeout, args.seed, 500,
        )
        if donnees is None:
            motifs["json_illisible"] += 1
            journal.append({"paire": index, "motif": "json_illisible"})
            continue
        tient = _question_tient_debout(donnees, a, b)
        if tient is None:
            motifs["gardes_lexicaux"] += 1
            journal.append({"paire": index, "motif": "gardes_lexicaux"})
            continue
        question, preuve_a, preuve_b = tient

        # LA CONDITION DE NON-SUFFISANCE, en DEUX appels separes. Les deux
        # prompts different par le passage ET par la question : le cache de
        # prefixe de vLLM ne peut pas resservir l'un pour l'autre.
        verdicts = []
        for passage in (a, b):
            juge = _appeler(
                PROMPT_SUFFISANCE.format(question=question, passage=passage["texte"]),
                args.llm_host, args.model, args.timeout, args.seed, 200,
            )
            verdicts.append(None if juge is None else bool(juge.get("suffit")))
        if any(v is None for v in verdicts):
            motifs["juge_illisible"] += 1
            journal.append({"paire": index, "motif": "juge_illisible"})
            continue
        if any(verdicts):
            motifs["un_passage_suffit"] += 1
            journal.append({"paire": index, "motif": "un_passage_suffit", "verdicts": verdicts})
            continue

        questions.append(
            {
                "id": f"D-{len(questions) + 1:03d}",
                "question": question,
                "language": langue_question,
                "doc_language": a["language"],
                "type": f"deux-sections-{strate}",
                "gold_element_ids": [a["element_id"], b["element_id"]],
                "gold_documents": sorted(
                    {
                        a["source_path"].rsplit("/", 1)[0] or a["source_path"],
                        b["source_path"].rsplit("/", 1)[0] or b["source_path"],
                    }
                ),
                "unanswerable": False,
                "_origine": {
                    "strate": strate,
                    "ancrage_a": {
                        "element_id": a["element_id"],
                        "section_id": detail["section_id_a"],
                        "source_path": a["source_path"],
                        "section_title": a["section_title"],
                        "page_no": a["page_no"],
                        "preuve": preuve_a[:300],
                    },
                    "ancrage_b": {
                        "element_id": b["element_id"],
                        "section_id": detail["section_id_b"],
                        "source_path": b["source_path"],
                        "section_title": b["section_title"],
                        "page_no": b["page_no"],
                        "preuve": preuve_b[:300],
                    },
                },
                "reviewed": False,
            }
        )
        journal.append({"paire": index, "motif": "retenue", "id": questions[-1]["id"]})
        if args.journal:
            # ECRIT A CHAQUE PAIRE. Une campagne de plusieurs centaines d'appels
            # qui n'ecrirait qu'a la fin perdrait tout au premier depassement.
            args.journal.parent.mkdir(parents=True, exist_ok=True)
            args.journal.write_text(
                json.dumps(
                    {"journal": journal, "motifs": dict(motifs),
                     "raisons_de_fin": dict(collections.Counter(_RAISONS_DE_FIN))},
                    ensure_ascii=False, indent=2,
                ),
                encoding="utf-8",
            )
        print(f"  {len(questions)}/{args.count} retenues, {index} paires vues")

    secondes = time.perf_counter() - t0

    # IMPRIMES MEME A ZERO : un compteur qui ne s'affiche qu'au-dessus de zero ne
    # se lit jamais comme « zero », il se lit comme « rien n'a ete mesure ».
    print(f"\npannes d'appel absorbees : {len(_PANNES)}")
    for panne, occurrences in collections.Counter(_PANNES).most_common(3):
        print(f"    {occurrences}x {panne}")
    print(f"raisons de fin : {dict(collections.Counter(_RAISONS_DE_FIN))}")
    print(f"motifs de rejet : {dict(motifs)}")

    langues: collections.Counter[str] = collections.Counter(q["language"] for q in questions)
    strates: collections.Counter[str] = collections.Counter(q["type"] for q in questions)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    ecrire(
        args.out,
        {
            "_lisez_moi": _LISEZ_MOI,
            "_reserve": _RESERVE,
            "_statistiques": {
                "questions": len(questions),
                "ancrages": sum(len(q["gold_element_ids"]) for q in questions),
                "ancrages_par_question": 2,
                "par_langue_de_la_question": dict(sorted(langues.items())),
                "par_strate": dict(sorted(strates.items())),
                "paires_examinees": min(len(paires), index),
                "rejetees": dict(sorted(motifs.items())),
                "raisons_de_fin": dict(sorted(collections.Counter(_RAISONS_DE_FIN).items())),
                "pannes_d_appel": len(_PANNES),
                "graine": args.seed,
                "secondes": round(secondes, 1),
                "corpus": {
                    "chunks_indexes": total_chunks,
                    "passages_exploitables": len(passages),
                    "sections_porteuses": len(sections),
                    "chapitres_porteurs": len({p["source_path"] for p in passages}),
                },
            },
            "questions": questions,
        },
    )
    print(f"\n{len(questions)} questions ecrites dans {args.out} en {secondes:.0f} s")
    return 0 if questions else 1


if __name__ == "__main__":
    sys.exit(main())
