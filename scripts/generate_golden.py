#!/usr/bin/env python
"""Génère un jeu doré à partir du corpus indexé.

Le problème que ce script résout : annoter des `gold_element_ids` à la main
suppose de poser une question, de lire les passages proposés, et de désigner les
bons. C'est long, et surtout **circulaire** — les candidats proposés viennent du
retrieval qu'on cherche à évaluer, donc un passage que le retrieval ne trouve
jamais ne sera jamais annoté, et son échec restera invisible.

On inverse : on part d'un passage, et on fait écrire par un LLM une question à
laquelle CE passage répond. La vérité terrain est alors connue par construction,
avant toute recherche. C'est l'approche des générateurs de jeux de test
synthétiques (RAGAS TestsetGenerator et suivants), et elle est reconnue fiable
pour régler un retriever — moins pour arbitrer entre deux générateurs.

Le résultat est du **silver**, pas du gold : chaque question sort avec
`reviewed: false`. Une relecture humaine la promeut. Le script fait le travail
mécanique, il ne remplace pas le jugement.

    uv run python scripts/generate_golden.py --count 120
    uv run python scripts/generate_golden.py --count 20 --out tests/fixtures/essai.json
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Un passage trop court ne porte pas de quoi formuler une question spécifique ;
# un passage énorme donne des questions vagues qui portent sur son ensemble.
_MIN_CHARS = 300
_MAX_CHARS = 2500
# Une question doit partager du vocabulaire distinctif avec son passage, sinon
# elle est générique et n'importe quel passage du corpus y « répondrait ».
_MIN_SHARED_TERMS = 2
_MIN_QUESTION_CHARS = 25
_MAX_QUESTION_CHARS = 220

# Sujets absents du corpus, pour les questions sans réponse. Un RAG qui n'admet
# jamais son ignorance est inutilisable : ces cas doivent être mesurés.
_UNANSWERABLE = [
    ("fr", "Quel est le chiffre d'affaires de l'entreprise en 2024 ?"),
    ("fr", "Quelle est la procédure de remboursement des notes de frais ?"),
    ("fr", "Combien de salariés compte le service juridique ?"),
    ("fr", "Quelles sont les dates des congés annuels cette année ?"),
    ("en", "Who won the 2026 football world cup?"),
    ("en", "What is the current stock price of the company?"),
    ("en", "What is the recipe for a traditional Basque cheesecake?"),
    ("en", "How many employees work in the Tokyo office?"),
]

PROMPT = """Tu lis un extrait de document technique. Écris UNE question à laquelle
cet extrait — et lui seul — permet de répondre.

Contraintes impératives :
- Écris la question EN {langue_nom}, quelle que soit la langue de l'extrait.
- Elle doit être précise et reprendre les termes techniques propres à l'extrait.
- Elle doit se comprendre seule, sans avoir l'extrait sous les yeux.
- Elle ne doit PAS contenir sa propre réponse.
- N'écris pas « selon l'extrait », « dans ce texte », ni aucune référence au document.
- Formule une vraie question, pas une devinette ni un énoncé à trous.
- Cite ensuite la phrase EXACTE de l'extrait qui contient la réponse, recopiée mot pour mot.

Réponds en JSON strict, sans rien autour :
{{"question": "...", "preuve": "..."}}

Extrait :
---
{passage}
---
"""

_LANGUES = {"fr": "français", "en": "anglais"}
# Proportion de questions posées dans une AUTRE langue que celle du passage.
# C'est le cas qui compte : le corpus est majoritairement anglais et les
# questions arrivent souvent en français. Un modèle monolingue s'y effondrait.
_PART_TRANSLINGUISTIQUE = 0.4

# Un passage fait surtout de code ou de balisage donne des questions creuses
# (« quel est le nom de la variable ? »). Au-delà de ce taux, on l'écarte.
_MAX_PART_CODE = 0.25
_MARQUEURS_CODE = re.compile(r"[{}<>=;`|#$]|\bdef \b|\bimport \b|https?://")


def _normalise(text: str) -> set[str]:
    """Jetons comparables : minuscules, sans accents, mots courts écartés."""
    decompose = unicodedata.normalize("NFKD", text.lower())
    sans_accents = "".join(c for c in decompose if not unicodedata.combining(c))
    return {t for t in re.findall(r"\w+", sans_accents) if len(t) > 3}  # noqa: PLR2004


def charger_passages(host: str, port: int) -> list[dict[str, Any]]:
    """Lit tout l'index et ne garde que les passages exploitables."""
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
            # Un passage sans titre de section est souvent du liminaire : page de
            # garde, mention légale, table des matières résiduelle.
            if not meta.get("section_title"):
                continue
            passages.append(
                {
                    "texte": texte,
                    "element_id": meta.get("element_id", ""),
                    "source_path": meta.get("source_path", ""),
                    "collection": meta.get("collection", ""),
                    "language": meta.get("language", ""),
                    "section_title": meta.get("section_title", ""),
                    "page_no": int(meta.get("page_no") or 0),
                }
            )

    print(f"{len(passages)} passages exploitables sur {total} chunks indexés.")
    return passages


def echantillonner(passages: list[dict], combien: int, graine: int) -> list[dict]:
    """Tire des passages en équilibrant documents et langues.

    Sans stratification, `statisticsfordatascience.pdf` — un sixième de l'index —
    monopoliserait le jeu, et le français (10 % du corpus) en disparaîtrait.
    """
    hasard = random.Random(graine)
    par_langue: dict[str, list[dict]] = defaultdict(list)
    for p in passages:
        par_langue[p["language"] or "??"].append(p)

    # Moitié pour la langue minoritaire, au lieu de sa part réelle : c'est là que
    # le système est le plus faible, donc là qu'il faut mesurer.
    langues = sorted(par_langue, key=lambda lg: len(par_langue[lg]))
    quotas: dict[str, int] = {}
    reste = combien
    for index, langue in enumerate(langues):
        part = reste if index == len(langues) - 1 else min(len(par_langue[langue]), combien // 2)
        quotas[langue] = part
        reste -= part

    choisis: list[dict] = []
    for langue, quota in quotas.items():
        par_document: dict[str, list[dict]] = defaultdict(list)
        for p in par_langue[langue]:
            par_document[p["source_path"]].append(p)
        documents = sorted(par_document)
        hasard.shuffle(documents)
        # Tourniquet sur les documents : chacun contribue avant qu'aucun ne
        # contribue deux fois.
        index = 0
        while len([c for c in choisis if c["language"] == langue]) < quota and documents:
            doc = documents[index % len(documents)]
            if par_document[doc]:
                choisis.append(par_document[doc].pop(hasard.randrange(len(par_document[doc]))))
            else:
                documents.remove(doc)
                index -= 1
            index += 1

    hasard.shuffle(choisis)
    return choisis


def part_de_code(texte: str) -> float:
    """Fraction de lignes qui ressemblent à du code ou du balisage."""
    lignes = [ligne for ligne in texte.splitlines() if ligne.strip()]
    if not lignes:
        return 1.0
    return sum(1 for ligne in lignes if _MARQUEURS_CODE.search(ligne)) / len(lignes)


def demander_question(
    passage: dict, langue_cible: str, host: str, model: str, timeout: float
) -> dict | None:
    """Fait écrire une question par le LLM, et vérifie qu'elle tient debout."""
    prompt = PROMPT.format(
        passage=passage["texte"], langue_nom=_LANGUES.get(langue_cible, "français")
    )
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "think": False,
        "format": "json",
        "options": {"temperature": 0.4, "num_predict": 300, "num_ctx": 8192},
    }
    try:
        response = httpx.post(f"{host}/api/chat", json=payload, timeout=timeout)
        response.raise_for_status()
        brut = response.json().get("message", {}).get("content", "")
        donnees = json.loads(brut)
    except Exception:
        return None

    question = (donnees.get("question") or "").strip()
    preuve = (donnees.get("preuve") or "").strip()

    if not (_MIN_QUESTION_CHARS <= len(question) <= _MAX_QUESTION_CHARS):
        return None
    # Le modèle doit RECOPIER la phrase, pas la reformuler : c'est le garde-fou
    # contre une question inventée qui ne trouve pas sa réponse dans le passage.
    if not preuve or _normalise(preuve) - _normalise(passage["texte"]):
        return None
    # Une question qui ne partage rien de distinctif avec son passage est
    # générique : n'importe quel passage du corpus « y répondrait ».
    if len(_normalise(question) & _normalise(passage["texte"])) < _MIN_SHARED_TERMS:
        return None
    # Une référence au document trahit une question non autonome.
    reference = r"\b(extrait|ce texte|ce document|this (text|excerpt|document))\b"
    if re.search(reference, question, re.I):
        return None
    # Une question qui contient déjà sa réponse ne teste rien : elle la recopie.
    if _normalise(preuve) and _normalise(preuve) <= _normalise(question):
        return None

    return {"question": question, "preuve": preuve}


def construire(passage: dict, genere: dict, langue_question: str, index: int) -> dict[str, Any]:
    translinguistique = langue_question != passage["language"]
    return {
        "id": f"G-{index:03d}",
        "question": genere["question"],
        # Langue de la QUESTION : c'est elle qui stratifie l'évaluation, pas
        # celle du document. Une question française sur un corpus anglais est
        # précisément le cas que le système doit savoir traiter.
        "language": langue_question,
        "doc_language": passage["language"],
        "type": "factuelle-translinguistique" if translinguistique else "factuelle",
        "gold_element_ids": [passage["element_id"]],
        "gold_documents": [passage["source_path"].rsplit("/", 1)[0] or passage["source_path"]],
        "unanswerable": False,
        # Traçabilité : d'où vient la question, et ce qui la justifie.
        "_origine": {
            "source_path": passage["source_path"],
            "section_title": passage["section_title"],
            "page_no": passage["page_no"],
            "preuve": genere["preuve"][:300],
        },
        "reviewed": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", type=int, default=120, help="Questions à générer")
    parser.add_argument("--chroma-host", default="127.0.0.1")
    parser.add_argument("--chroma-port", type=int, default=8080)
    parser.add_argument("--ollama", default="http://localhost:11434")
    parser.add_argument("--model", default="gemma4:e4b")
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--seed", type=int, default=42, help="Rend le tirage reproductible")
    parser.add_argument(
        "--out", type=Path, default=ROOT / "tests" / "fixtures" / "golden_qa_generated.json"
    )
    args = parser.parse_args()

    passages = charger_passages(args.chroma_host, args.chroma_port)
    if not passages:
        print("Aucun passage exploitable — l'index est-il peuplé ?")
        return 1

    # Marge : une partie des générations est rejetée par les garde-fous.
    candidats = echantillonner(passages, int(args.count * 1.8), args.seed)
    print(f"{len(candidats)} passages tirés, génération en cours…")

    hasard = random.Random(args.seed)
    autres = {"fr": "en", "en": "fr"}

    questions: list[dict] = []
    rejets = 0
    for passage in candidats:
        if len(questions) >= args.count:
            break
        langue_doc = passage["language"] if passage["language"] in _LANGUES else "en"
        langue_question = (
            autres[langue_doc]
            if hasard.random() < _PART_TRANSLINGUISTIQUE
            else langue_doc
        )
        genere = demander_question(passage, langue_question, args.ollama, args.model, args.timeout)
        if genere is None:
            rejets += 1
            continue
        questions.append(construire(passage, genere, langue_question, len(questions) + 1))
        if len(questions) % 10 == 0:
            print(f"  {len(questions)}/{args.count} ({rejets} rejetées)")

    # Questions sans réponse : le corpus est muet, le système doit s'abstenir.
    for index, (langue, texte) in enumerate(_UNANSWERABLE, start=1):
        questions.append(
            {
                "id": f"N-{index:03d}",
                "question": texte,
                "language": langue,
                "type": "sans-reponse",
                "gold_element_ids": [],
                "gold_documents": [],
                "unanswerable": True,
                "reviewed": True,
            }
        )

    langues: dict[str, int] = defaultdict(int)
    for q in questions:
        langues[q["language"]] += 1

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(
            {
                "_lisez_moi": [
                    "Jeu SILVER : questions générées automatiquement à partir des passages",
                    "du corpus, par scripts/generate_golden.py. La vérité terrain est connue",
                    "par construction — la question a été écrite POUR le passage — donc sans",
                    "la circularité d'une annotation faite depuis les résultats du retrieval.",
                    "",
                    "reviewed: false = non relu par un humain. Une relecture promeut la",
                    "question en gold. Cette approche est reconnue fiable pour régler un",
                    "retriever, moins pour arbitrer entre deux générateurs.",
                    "",
                    "_origine porte la traçabilité : document, section, page et la phrase",
                    "exacte du passage qui contient la réponse.",
                ],
                "_statistiques": {
                    "questions": len(questions),
                    "par_langue": dict(langues),
                    "rejetees_par_les_garde_fous": rejets,
                    "graine": args.seed,
                },
                "questions": questions,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print(f"\n{len(questions)} questions écrites dans {args.out}")
    print(f"  par langue : {dict(langues)}")
    print(f"  rejetées par les garde-fous : {rejets}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
