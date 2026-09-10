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

    uv run --no-sync python scripts/generate_golden.py --count 120
    uv run --no-sync python scripts/generate_golden.py --count 20 --out tests/fixtures/essai.yaml

LE JEU S'ECRIT EN YAML, ET C'EST UNE RAISON MESUREE, PAS UN GOUT. Un jeu de
questions porte des `element_id` — dix hexadecimaux derives du contenu d'un
passage public (contrat, exigence 2) — et `detect-secrets` les lit comme des
chaines hexadecimales a forte entropie. `mesure` le 8 septembre 2026,
`detect-secrets-hook` v1.5.0 sur le jeu de 138 questions que ce lot remplace :

    tests/fixtures/golden_qa_generated.json   -> rc=1, 34 detections
    le jeu de 30 questions du pipeline, YAML  -> rc=0

La cause vit chez le pipeline, qui l'a mesuree le 3 septembre 2026 et qui en est
le site canonique — l'en-tete de
`documentation/campagnes/2026-09-02-jeu-de-questions.yaml` : le transformateur
YAML de `detect-secrets` rend les VALEURS DE MAPPING et pas les ELEMENTS DE
SEQUENCE. Les `element_id` d'un jeu de questions vivent en elements de sequence.
Donc : `--out` en `.yaml` ou `.yml` ecrit du YAML, tout autre suffixe du JSON, et
le defaut est le YAML.

`detect-secrets` n'est PAS arme sur ce depot (`.pre-commit-config.yaml` le dit
et dit pourquoi), donc rien ne rougirait d'un jeu en JSON aujourd'hui. C'est
precisement l'argument INVERSE de celui qu'on croit : un jeu en JSON rend ce
hook inarmable sans un audit de ses 34 detections. Le YAML le laisse armable.
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
import yaml

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

_LISEZ_MOI = [
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
    "",
    "CE JEU NE PROUVE RIEN TANT QUE SES `gold_element_ids` N'ONT PAS ÉTÉ",
    "CONFRONTÉS AUX STORES : un jeu qui désigne le vide rend 0 % de rappel",
    "sans dire si la recherche est cassée ou si le jeu est périmé. C'est la",
    "panne exacte que le jeu précédent a portée. L'instrument est",
    "scripts/verifier_les_ancrages.py, et il sort en 1 au premier désaccord.",
]

# Suffixes qui déclenchent l'écriture en YAML. Voir le docstring du module : le
# YAML n'est pas un goût, il garde les `element_id` hors de portée du
# transformateur de `detect-secrets`.
_SUFFIXES_YAML = (".yaml", ".yml")


def ecrire(chemin: Path, contenu: dict[str, Any]) -> None:
    """Écrit le jeu, en YAML par défaut, en JSON si le suffixe le demande.

    `default_flow_style=False` est ce qui rend les `gold_element_ids` en
    ÉLÉMENTS DE SÉQUENCE (`- 05f988efec`) et non en style de flux
    (`[05f988efec]`) : le style de flux les rendrait à nouveau visibles au
    transformateur YAML de `detect-secrets`, qui ne les voit pas en style de
    bloc. La mesure qui l'établit est au docstring du module.

    `sort_keys=False` préserve l'ordre d'écriture, `allow_unicode=True` garde
    les questions françaises lisibles dans le diff.
    """
    if chemin.suffix.lower() in _SUFFIXES_YAML:
        chemin.write_text(
            yaml.safe_dump(
                contenu,
                allow_unicode=True,
                default_flow_style=False,
                sort_keys=False,
                width=100,
            ),
            encoding="utf-8",
        )
        return
    chemin.write_text(
        json.dumps(contenu, ensure_ascii=False, indent=2), encoding="utf-8"
    )


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


def charger_passages(host: str, port: int) -> tuple[list[dict[str, Any]], int]:
    """Lit tout l'index et ne garde que les passages exploitables.

    Returns:
        Les passages retenus, et le nombre TOTAL de chunks indexés. Le second
        est rendu parce qu'il va dans le jeu : un jeu de questions dont on ne
        sait pas contre quel index il a été écrit ne peut pas être déclaré
        périmé, et c'est exactement ce qui est arrivé au jeu précédent.
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
    return passages, total


def echantillonner(passages: list[dict], combien: int, graine: int) -> list[dict]:
    """Tire des passages en équilibrant documents et langues.

    Sans stratification, le document le plus gros monopoliserait le jeu : sur le
    corpus du 8 septembre 2026, `Hands-On_RAG_for_Production` porte 124 des
    1 266 passages exploitables, et deux ouvrages HTML en portent 1 142.

    LA MOITIÉ RÉSERVÉE À LA LANGUE MINORITAIRE NE MORD PLUS, et il faut le
    savoir avant de lire un chiffre translinguistique. Une version antérieure de
    ce docstring donnait « le français (10 % du corpus) » : `mesuré` le
    8 septembre 2026 contre ChromaDB, les 4 367 chunks portent
    `language: en` — **4 367 sur 4 367**, aucun autre. La stratification par
    langue est donc un no-op sur ce corpus (une seule langue, un seul quota), et
    l'axe translinguistique ne survit que par `_PART_TRANSLINGUISTIQUE`, qui pose
    la QUESTION dans l'autre langue. « Question française → document anglais »
    reste mesurable ; l'inverse a disparu avec le corpus français.
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
    passage: dict, langue_cible: str, host: str, model: str, timeout: float, graine: int
) -> dict | None:
    """Fait écrire une question par le LLM, et vérifie qu'elle tient debout.

    **LA GRAINE EST TRANSMISE À OLLAMA, ET ELLE NE L'ÉTAIT PAS.** Voir
    `main` pour ce que cela change et ce que cela ne rattrape pas.
    """
    prompt = PROMPT.format(
        passage=passage["texte"], langue_nom=_LANGUES.get(langue_cible, "français")
    )
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "think": False,
        "format": "json",
        # `seed` TRANSMISE, et c'est une correction du 8 septembre 2026. Sans
        # elle, `temperature: 0.4` rendait la génération non déterministe, donc
        # le MOTIF DE REJET variait d'une exécution à l'autre, donc l'ensemble
        # des ancrages retenus pouvait varier — voir `main`. `mesuré` sur
        # `ollama-central`, `gemma4:e4b`, même prompt, trois paires d'appels :
        #
        #   sans `seed`     : deux appels -> deux textes DIFFÉRENTS
        #   `seed: 42`      : deux appels -> textes IDENTIQUES
        #   `seed: 43`      : différent de `seed: 42` — la graine mord
        "options": {
            "temperature": 0.4,
            "num_predict": 300,
            "num_ctx": 8192,
            "seed": graine,
        },
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
    """Génère le jeu, et voici EXACTEMENT ce que `--seed` reproduit.

    **LA GRAINE NE SUFFISAIT PAS, ET LA DOCUMENTATION LAISSAIT ENTENDRE LE
    CONTRAIRE** — trouvaille N7 de l'audit du lot 5, corrigée le 8 septembre
    2026. Le mécanisme, en trois faits :

    1. la graine fixe le TIRAGE : `echantillonner(passages, int(count * 1.8),
       seed)` rend toujours les mêmes candidats, dans le même ordre ;
    2. mais les candidats sont consommés **dans l'ordre jusqu'à `count`
       ACCEPTATIONS**, et ce qui est accepté dépend du LLM. Un rejet qui tombe
       autrement **décale la suite des ancrages** : ce n'est pas la même liste
       qu'on obtient, c'est une liste voisine ;
    3. et le `hasard.random()` qui décide de la langue de la question est tiré
       DANS cette boucle. Un rejet de plus ou de moins ne déplace donc pas
       seulement les ancrages : il réaffecte les langues de tout ce qui suit.

    `mesuré` par l'audit du lot 5 : deux exécutions à `--seed 42` ont rendu les
    **mêmes ancrages** — même nombre de rejets, donc même découpe — mais **7
    textes de question sur 16** différaient. *Reproductible en pratique, pas par
    construction.*

    **CE QUE LA CORRECTION FAIT.** La graine est désormais TRANSMISE à Ollama
    (`options.seed`, voir `demander_question`). `mesuré` le 8 septembre 2026 sur
    `ollama-central` / `gemma4:e4b` : sans graine, deux appels identiques rendent
    deux textes différents ; avec `seed: 42`, deux appels rendent le même texte ;
    avec `seed: 43`, un autre. Le motif de rejet devient donc déterministe, et la
    reproductibilité passe de « en pratique » à « par construction ».

    **CE QU'ELLE NE RATTRAPE PAS, ET IL FAUT LE DIRE TROIS FOIS.**

    - La reproductibilité est relative au SERVEUR : même modèle, même version de
      modèle, même version d'Ollama, même backend. Un `gemma4:e4b` reconstruit
      ailleurs ne rend pas la même chose, et rien ici ne peut le garantir.
    - **Le jeu VERSIONNÉ n'a PAS été produit avec cette graine transmise.**
      `tests/fixtures/golden_qa_generated.yaml` date du 8 septembre 2026, d'avant
      cette correction : relancer ce script à `--seed 42` produira un jeu
      DIFFÉRENT de celui du dépôt. Le jeu versionné reste l'artefact de
      référence, et `runs/2026-09-08-reference.json` s'apparie à lui — c'est
      pourquoi ce lot n'a PAS régénéré le jeu.
    - Elle ne rend pas le jeu comparable à un jeu produit sur un autre corpus :
      c'est le travail de `evaluate.empreinte_des_ancrages`, pas celui de la
      graine.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", type=int, default=120, help="Questions à générer")
    parser.add_argument("--chroma-host", default="127.0.0.1")
    parser.add_argument("--chroma-port", type=int, default=8080)
    parser.add_argument("--ollama", default="http://localhost:11434")
    parser.add_argument("--model", default="gemma4:e4b")
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Graine du tirage ET de la génération (transmise à Ollama) — voir le "
             "docstring de `main` pour ce qu'elle reproduit et ce qu'elle ne "
             "reproduit pas",
    )
    parser.add_argument(
        "--out", type=Path, default=ROOT / "tests" / "fixtures" / "golden_qa_generated.yaml"
    )
    args = parser.parse_args()

    passages, total_chunks = charger_passages(args.chroma_host, args.chroma_port)
    if not passages:
        print("Aucun passage exploitable — l'index est-il peuplé ?")
        return 1
    # Les langues du CORPUS, comptées sur les passages exploitables. Elles
    # bornent la mesure translinguistique et ne sont pas décoratives : le
    # 2 septembre 2026, le corpus a été remplacé par un corpus ENTIÈREMENT
    # ANGLAIS, ce qui a coupé en deux l'axe translinguistique — « question
    # française → document anglais » reste mesurable, l'inverse a disparu. Un
    # jeu qui n'inscrit pas cette borne laisse le lecteur suivant croire qu'il
    # mesure les deux sens.
    langues_du_corpus: dict[str, int] = defaultdict(int)
    for passage in passages:
        langues_du_corpus[passage["language"] or "??"] += 1
    langues_du_corpus = dict(sorted(langues_du_corpus.items()))

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
        genere = demander_question(
            passage, langue_question, args.ollama, args.model, args.timeout, args.seed
        )
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
    ecrire(
        args.out,
        {
            "_lisez_moi": _LISEZ_MOI,
            "_statistiques": {
                "questions": len(questions),
                "par_langue": dict(langues),
                "rejetees_par_les_garde_fous": rejets,
                "graine": args.seed,
                "corpus": {
                    "chunks_indexes": total_chunks,
                    "passages_exploitables": len(passages),
                    "documents_porteurs": len({p["source_path"] for p in passages}),
                    "langues_du_corpus": langues_du_corpus,
                },
            },
            "questions": questions,
        },
    )

    print(f"\n{len(questions)} questions écrites dans {args.out}")
    print(f"  par langue : {dict(langues)}")
    print(f"  rejetées par les garde-fous : {rejets}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
