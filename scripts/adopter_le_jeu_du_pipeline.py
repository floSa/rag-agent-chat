#!/usr/bin/env python
"""Adopte le jeu de 30 questions du pipeline d'ingestion, sans le recopier à la main.

CE QUE CE SCRIPT EST, ET CE QU'IL N'EST PAS. Il n'écrit aucune question : il
TRANSPOSE celles du pipeline dans le schéma que `scripts/evaluate.py` lit, et il
grave la provenance — chemin de la source, son empreinte SHA-256, la date de la
transposition. Le site canonique du jeu reste chez le pipeline :

    /home/ubuntu/RAG/rag-ingestion-pipeline/documentation/campagnes/
        2026-09-02-jeu-de-questions.yaml

Un jeu recopié à la main est un second site pour trente questions et
quarante-quatre identifiants. Un jeu transposé par un script est une
DÉRIVATION : on la rejoue, et l'empreinte dit si la source a bougé sous elle.

    uv run python scripts/adopter_le_jeu_du_pipeline.py
    uv run python scripts/adopter_le_jeu_du_pipeline.py --source <chemin> --out <chemin>

LA RÉSERVE DU JEU VOYAGE AVEC LUI, ET ELLE N'EST PAS NÉGOCIABLE. Trente
questions prouvent que la chaîne fonctionne et montrent un défaut grossier ;
elles ne suffisent pas à arbitrer un réglage — un écart de deux points sur
trente questions est du bruit. Première mesure = contrôle de bon
fonctionnement, jamais décision d'architecture. Le champ `_reserve` du fichier
produit la porte, et `tests/unit/test_jeux_de_questions.py` rougit si elle
disparaît : une réserve qu'on peut perdre en éditant un fichier de données n'en
est pas une.

DEUX BORNES SONT MESURÉES DE L'AUTRE CÔTÉ, et elles ne sont pas recopiées ici
comme des mesures de ce dépôt — elles renvoient au site du pipeline,
`documentation/campagnes/2026-09-02-premiere-campagne-de-reference.md` :

  - la strate « de suivi » rend 20 % chez le pipeline PARCE QUE son script
    encode la question SANS son `chat_history` (60 % avec). C'est le périmètre
    de sa mesure, pas un défaut de l'index. De ce côté-ci, `evaluate.py`
    TRANSMET `chat_history` à `/answer`, donc la strate y mesure autre chose —
    la résolution de l'antécédent par l'agent — et les deux chiffres ne sont pas
    comparables ;
  - le corpus est entièrement anglais (`mesuré` : 4 367 chunks sur 4 367 en
    `language: en`), donc l'axe translinguistique est coupé en deux : « question
    française → document anglais » reste mesurable, l'inverse a disparu.

Codes de sortie : 0 écrit, 2 source illisible ou incohérente.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent
SOURCE = Path(
    "/home/ubuntu/RAG/rag-ingestion-pipeline/documentation/campagnes/"
    "2026-09-02-jeu-de-questions.yaml"
)
SORTIE = ROOT / "tests" / "fixtures" / "jeu_de_questions_pipeline.yaml"

# Les cinq strates de la spécification du pipeline, et leurs effectifs. Ils sont
# vérifiés à la transposition : une source qui aurait perdu une question rendrait
# un jeu plus petit sans un mot, et le rappel calculé dessus serait comparable à
# rien.
_STRATES_ATTENDUES = {
    "multi_passages": 12,
    "simple": 8,
    "sans_reponse": 4,
    "de_suivi": 4,
    "reformulee": 2,
}

# Le corpus est entièrement anglais — `mesuré` le 8 septembre 2026 contre
# ChromaDB, 4 367 chunks sur 4 367 en `language: en`. C'est ce qui fait de la
# seule question française du jeu (q30) le dernier témoin de l'axe
# translinguistique, et `evaluate.py` ne le voit QUE si `doc_language` est
# renseigné : sans lui, `translinguistique` retombe sur la langue de la question
# et la strate devient vide en silence.
_LANGUE_DU_CORPUS = "en"


def empreinte(chemin: Path) -> str:
    return hashlib.sha256(chemin.read_bytes()).hexdigest()


def transposer(source: dict[str, Any]) -> list[dict[str, Any]]:
    """Réécrit les trente questions dans le schéma de `evaluate.py`.

    Deux traductions de vocabulaire, et chacune décide d'une mesure :

    - `element_ids` → `gold_element_ids`, la clé que `evaluate` lit ;
    - `strate: sans_reponse` → `unanswerable: true`, sans quoi les quatre
      questions d'abstention seraient comptées comme des échecs de rappel au
      lieu d'être mesurées sur l'abstention.

    Et un champ DÉRIVÉ, `gold_documents` : le répertoire du `source_path` de
    chaque ancrage, tel que le construit `generate_golden.construire`. Même
    convention des deux côtés, sans quoi `rappel_documents` ne se compare pas
    d'un jeu à l'autre.
    """
    ancrages = source["ancrages"]
    questions: list[dict[str, Any]] = []
    for brute in source["questions"]:
        identifiants = list(brute.get("element_ids") or [])
        documents = sorted(
            {
                str(ancrages[eid]["source_path"]).rsplit("/", 1)[0]
                or str(ancrages[eid]["source_path"])
                for eid in identifiants
                if eid in ancrages
            }
        )
        question: dict[str, Any] = {
            "id": brute["id"],
            "question": brute["question"],
            "language": brute["langue"],
            # La langue du DOCUMENT, pas celle de la question : c'est l'écart
            # entre les deux que la strate translinguistique mesure.
            "doc_language": _LANGUE_DU_CORPUS,
            "type": brute["strate"],
            "gold_element_ids": identifiants,
            "gold_documents": documents,
            "unanswerable": brute["strate"] == "sans_reponse",
            # Relu par un humain à l'écriture, en lisant quatre chapitres dans
            # le store : c'est ce qui le distingue du jeu généré, dont les
            # questions sortent `reviewed: false`.
            "reviewed": True,
        }
        if brute.get("chat_history"):
            question["chat_history"] = brute["chat_history"]
        question["_origine"] = {
            "strate": brute["strate"],
            "reponse_attendue": brute["reponse_attendue"],
        }
        if brute.get("motif_de_la_reformulation"):
            question["_origine"]["motif_de_la_reformulation"] = brute[
                "motif_de_la_reformulation"
            ]
        questions.append(question)
    return questions


# Le pragma que `detect-secrets` lit, et le seul du fichier produit.
#
# POURQUOI IL EST POSÉ APRÈS COUP, ET PAS DANS LE DICTIONNAIRE. `yaml.safe_dump`
# ne sait pas écrire de commentaire : le `# pragma: allowlist secret` posé sur la
# ligne `"source_sha256": empreinte(...)` de ce script reste DANS ce script et
# ne voyage pas dans le YAML. `mesuré` le 8 septembre 2026, `detect-secrets-hook`
# v1.5.0 sur le fichier produit sans ce post-traitement : `rc=1`, UNE détection,
# ligne 26 — l'empreinte, exactement la ligne que le pragma du script croyait
# couvrir. Avec le post-traitement : `rc=0`.
#
# C'est le même mécanisme que celui mesuré chez le pipeline, et son site
# canonique est l'en-tête de son jeu de questions : le transformateur YAML de
# `detect-secrets` rend les VALEURS DE MAPPING et pas les ÉLÉMENTS DE SÉQUENCE.
# L'empreinte est une valeur de mapping ; les 44 `gold_element_ids` du fichier
# vivent en éléments de séquence et ne sont jamais détectés.
#
# Garde : `tests/unit/test_jeux_de_questions.py`,
# `test_l_empreinte_de_provenance_porte_son_pragma`.
_LIGNE_EMPREINTE = "  source_sha256: "
_PRAGMA = "  # pragma: allowlist secret"


def poser_le_pragma(rendu: str) -> str:
    """Annote l'empreinte SHA-256 du fichier produit, et RIEN d'autre.

    Un pragma posé au petit bonheur sur tout ce qui ressemble à de
    l'hexadécimal désarmerait le hook sur les vraies lignes. Celui-ci ne vise
    que la ligne de l'empreinte, et lève si elle n'est pas là — un
    post-traitement qui ne trouve pas sa cible et se tait est pire que pas de
    post-traitement : le fichier sortirait sans pragma, sans un mot.
    """
    lignes = rendu.split("\n")
    vises = [i for i, ligne in enumerate(lignes) if ligne.startswith(_LIGNE_EMPREINTE)]
    if len(vises) != 1:
        raise ValueError(
            f"{len(vises)} ligne(s) `{_LIGNE_EMPREINTE.strip()}` dans le rendu, une attendue"
        )
    lignes[vises[0]] += _PRAGMA
    return "\n".join(lignes)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=SOURCE)
    parser.add_argument("--out", type=Path, default=SORTIE)
    args = parser.parse_args()

    if not args.source.is_file():
        print(f"source absente : {args.source}", file=sys.stderr)
        return 2
    source = yaml.safe_load(args.source.read_text(encoding="utf-8"))

    questions = transposer(source)
    effectifs: dict[str, int] = {}
    for question in questions:
        effectifs[question["type"]] = effectifs.get(question["type"], 0) + 1
    if effectifs != _STRATES_ATTENDUES:
        print(
            f"la source ne porte plus les cinq strates attendues : {effectifs} "
            f"au lieu de {_STRATES_ATTENDUES}",
            file=sys.stderr,
        )
        return 2

    ancres = {a for q in questions for a in q["gold_element_ids"]}
    contenu = {
        "_lisez_moi": [
            "LES 30 QUESTIONS DU PIPELINE D'INGESTION, TRANSPOSÉES — pas récrites.",
            "Site canonique du jeu, et seul endroit où on le modifie :",
            f"  {SOURCE}",
            "Ce fichier est une DÉRIVATION, produite par",
            "scripts/adopter_le_jeu_du_pipeline.py. Rejoue le script plutôt que",
            "d'éditer ce fichier : une édition à la main en fait un second site.",
            "",
            "CE QUE CE JEU VAUT, ET CE QU'IL NE VAUT PAS. Écrit à la main APRÈS",
            "l'ingestion, en lisant quatre chapitres dans le store, il est un",
            "CONTRÔLE INDÉPENDANT du générateur de questions — il sait le",
            "contredire, ce que le jeu généré ne sait pas faire. Il est trop peu",
            "nombreux pour arbitrer un réglage.",
            "",
            "L'AUTRE INSTRUMENT est tests/fixtures/golden_qa_generated.yaml, et",
            "aucun des deux ne remplace l'autre : le généré règle, ces trente",
            "contrôlent. Le motif est au §4.3 de documentation/axes_amelioration.md.",
        ],
        "_reserve": (
            "CONTRÔLE DE BON FONCTIONNEMENT, PAS DÉCISION D'ARCHITECTURE. "
            "30 questions suffisent à prouver que la chaîne marche de bout en bout "
            "et à voir un défaut grossier ; elles ne suffisent pas à arbitrer un "
            "réglage. Un écart de deux points est du bruit."
        ),
        "_provenance": {
            "source": str(SOURCE),
            "campagne_source": source.get("campagne"),
            "date_source": str(source.get("date")),
            "specification": source.get("specification"),
            # L'empreinte de la SOURCE, pas d'un secret : elle dit si le jeu du
            # pipeline a bougé depuis la transposition. `detect-secrets` la lit
            # comme une chaîne hexadécimale à forte entropie, ce qu'elle est, et
            # elle vit ici en VALEUR DE MAPPING — le seul endroit du fichier que
            # son transformateur YAML rende. D'où le pragma, et il est le seul du
            # fichier : les `gold_element_ids` vivent en éléments de séquence, que
            # ce transformateur ne rend pas. Mesure et cause : en-tête du fichier
            # source.
            "source_sha256": empreinte(args.source),  # pragma: allowlist secret
            "transpose_par": "scripts/adopter_le_jeu_du_pipeline.py",
        },
        "_statistiques": {
            "questions": len(questions),
            "par_strate": effectifs,
            "ancrages_distincts": len(ancres),
            "par_langue_de_la_question": {
                langue: sum(1 for q in questions if q["language"] == langue)
                for langue in sorted({q["language"] for q in questions})
            },
            "langue_du_corpus": _LANGUE_DU_CORPUS,
        },
        "questions": questions,
    }

    rendu = yaml.safe_dump(
        contenu, allow_unicode=True, default_flow_style=False, sort_keys=False, width=100
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(poser_le_pragma(rendu), encoding="utf-8")
    print(f"{len(questions)} questions transposées dans {args.out}")
    print(f"  par strate        : {effectifs}")
    print(f"  ancrages distincts: {len(ancres)}")
    print(f"  source            : {args.source}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
