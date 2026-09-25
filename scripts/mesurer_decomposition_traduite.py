#!/usr/bin/env python
"""LA DECOMPOSITION AVEC TRADUCTION, LES QUESTIONS PERDUES DIAGNOSTIQUEES, ET
L'ECART A LA BORNE REPARTI PAR ETAGE.

Le §4.78 a mesure la decomposition REELLE : sur le jeu disperse, **19**
questions completes sur 60 contre **7** en production, la borne de l'oracle du
§4.77 etant a **28**. Il a laisse TROIS reserves ecrites au site, et ce banc
etend le sien pour les trois.

1. LA COMPARAISON AVEC LA PRODUCTION EST BOITEUSE, et le §4.78 le DIT : la
   production traduit la question, les variantes decomposees ne traduisent pas.
   Sur le jeu de reglage la production rend 127 et la meilleure variante 124, et
   DEUX des trois questions perdues sont imputees au retrait de la traduction
   SANS QU'AUCUNE VARIANTE NE LE MESURE. Ce banc joue cette variante.
2. TROIS PERTES NE SONT PAS DIAGNOSTIQUEES — `D-003`, `G-110`, `q18`. Ce banc
   releve le rang de CHAQUE ancrage a CHAQUE etage, pour CHAQUE variante.
3. LES NEUF QUESTIONS D'ECART A LA BORNE NE SONT PAS REPARTIES entre « perdue a
   la fusion » et « perdue au reranking », le §4.78 ne versionnant le rang de
   FUSION que pour la variante de production. Ce banc le versionne pour TOUTES.

AUCUNE REPONSE N'EST GENEREE PAR LA MESURE. Le banc rejoue `retrieve`, `fuse` et
`rerank` de `src/` tels quels, et releve un RANG. `src/` n'est pas touche. Le
modele n'entre que dans la FABRICATION des caches — traductions de
sous-questions, decompositions de la question traduite —, qui sont des
producteurs distincts, et le banc EXIGE ces caches sans jamais les fabriquer.

LES DECOMPOSITIONS DU §4.78 SONT REUTILISEES TELLES QUELLES, depuis
`runs/.decomposition-<jeu>.json`, et c'est ce qui rend la mesure lisible : la
SEULE difference entre `fusion_rerank_*` et `fusion_traduite_rerank_*` est la
traduction. Les refabriquer ferait varier les sous-questions en meme temps que
la traduction, et l'ecart ne serait imputable a rien.

    uv run --no-sync python scripts/mesurer_decomposition_traduite.py \\
        --etape fusion --jeu tests/fixtures/jeu_ancrages_disperses.yaml \\
        --reference runs/2026-09-24-recuperation-p50.json \\
        --lot38 runs/2026-09-25-fusion-disperse.json \\
        --sortie runs/2026-09-25-traduite-disperse.json
"""

from __future__ import annotations

import argparse
import datetime
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

from mesurer_dispersion import rang_de  # noqa: E402 — `scripts/` n'est pas un paquet
from mesurer_fusion_sous_questions import (  # noqa: E402 — idem
    _MAX_SOUS_QUESTIONS,
    _SEUIL_TOP,
    cache_de_decomposition,
    dans_le_haut,
    decomposition_utilisable,
    fusionner_les_classements,
)
from mesurer_recuperation import etat_des_stores, stores_stables  # noqa: E402 — idem
from mesurer_selection import CACHE_TRADUCTIONS, charger_questions  # noqa: E402 — idem

# ─── LES SEPT VARIANTES, ET CE QUI LES SEPARE ────────────────────────────────
#
# Les QUATRE PREMIERES sont celles du §4.78, rejouees a l'identique : sans elles
# le controle positif n'aurait rien a confronter, et les trois nouvelles
# seraient comparees a des chiffres recopies d'un document au lieu de chiffres
# mesures sur les memes stores, le meme jour, par le meme banc.
#
# `unique_avec_traduction`      — LA PRODUCTION, mot pour mot.
# `unique_sans_traduction`      — LA BASE APPARIEE du §4.78.
# `fusion_rerank_entiere`       — fusion des sous-questions, rerank sur la question.
# `fusion_rerank_sous_questions`— fusion, rerank par sous-question au maximum.
#
# LES TROIS NOUVELLES, et le choix de leur construction est argumente a
# `jouer_les_variantes` :
#
# `fusion_traduite_rerank_entiere`       — CHAQUE sous-question est traduite et
#     recuperee comme la production recupere la question : `retrieve(sous,
#     translation=…)`. Rerank sur la question entiere.
# `fusion_traduite_rerank_sous_questions`— meme fusion, rerank par sous-question.
# `fusion_question_traduite_decomposee`  — L'AUTRE ORDRE : la question est
#     traduite PUIS decomposee, et les deux familles de sous-questions sont
#     fondues, celle de la traduction au poids de la production.
VARIANTES = (
    "unique_avec_traduction",
    "unique_sans_traduction",
    "fusion_rerank_entiere",
    "fusion_rerank_sous_questions",
    "fusion_traduite_rerank_entiere",
    "fusion_traduite_rerank_sous_questions",
    "fusion_question_traduite_decomposee",
)

VARIANTES_DU_LOT_38 = VARIANTES[:4]
VARIANTES_NEUVES = VARIANTES[4:]

# LES DOUZE COUPLES DU §4.78, ET ILS SONT LA REFERENCE LITTERALE DU CONTROLE.
# Quatre variantes sur trois jeux, ancrages ET questions : le banc etendu doit
# les retrouver A L'UNITE, sans quoi il ne rejoue pas le lot 38 et ce qu'il
# dirait de la traduction n'aurait aucune base. Ces chiffres sont recopies du
# §4.78 et de ses bilans versionnes `runs/2026-09-25-fusion-{disperse,reglage,
# controle}.json`, ou ils sont lus a l'identique.
CONTROLE_4_78: dict[str, dict[str, tuple[int, int]]] = {
    "jeu_ancrages_disperses.yaml": {
        "unique_avec_traduction": (53, 7),
        "unique_sans_traduction": (57, 6),
        "fusion_rerank_entiere": (60, 8),
        "fusion_rerank_sous_questions": (72, 19),
    },
    "golden_qa_generated.yaml": {
        "unique_avec_traduction": (127, 127),
        "unique_sans_traduction": (125, 125),
        "fusion_rerank_entiere": (124, 124),
        "fusion_rerank_sous_questions": (124, 124),
    },
    "jeu_de_questions_pipeline.yaml": {
        "unique_avec_traduction": (33, 14),
        "unique_sans_traduction": (33, 14),
        "fusion_rerank_entiere": (33, 14),
        "fusion_rerank_sous_questions": (33, 14),
    },
}


def cache_de_traduction_des_sous_questions(jeu: Path) -> Path:
    """Un cache PAR JEU, nomme d'apres lui — meme raison qu'au §4.78.

    Un seul fichier pour les trois jeux laisserait une campagne lire les
    traductions d'un autre jeu des que deux sous-questions coincideraient, et
    les sous-questions sont locales a leur jeu.
    """
    return ROOT / "runs" / f".traductions-sous-questions-{jeu.stem}.json"


def cache_de_decomposition_traduite(jeu: Path) -> Path:
    """Le cache des decompositions de la question TRADUITE, un par jeu."""
    return ROOT / "runs" / f".decomposition-traduite-{jeu.stem}.json"


# ─── LA TRADUCTION, ET ELLE EST CELLE DE LA PRODUCTION ───────────────────────


def post_traitement_de_la_production(question: str, brut: str | None) -> str | None:
    """LES QUATRE REFUS DE `translate_question`, ET ILS NE SONT PAS RECOPIES.

    `src/agent/llm.py:translate_question` ne rend pas ce que le modele ecrit : il
    garde la PREMIERE LIGNE, retire guillemets et apostrophes encadrants, puis
    refuse dans trois cas — une traduction vide, une traduction plus de
    `_MAX_TRANSLATION_RATIO` fois plus longue que la question, et une traduction
    egale a la question a la casse pres. Chacun de ces refus rend `None`, et
    `retrieve` recoit alors `translation=None` : la recherche redevient
    monolingue POUR CETTE QUESTION.

    UN BANC QUI OUBLIERAIT UN DE CES REFUS NE MESURERAIT PAS LA PRODUCTION. Il
    donnerait a `retrieve` une traduction que la production aurait jetee, et le
    gain attribue a la traduction porterait en partie sur des requetes que le
    service n'emet jamais.

    LE SEUIL N'EST PAS RECOPIE, IL EST IMPORTE. `_MAX_TRANSLATION_RATIO` vient de
    `src/agent/llm.py` : ecrire `3.0` ici ferait deux sites pour une seule
    valeur, et le banc continuerait de mesurer l'ancien le jour ou la production
    changerait le sien.
    """
    from src.agent.llm import _MAX_TRANSLATION_RATIO

    traduction = brut.splitlines()[0].strip().strip("\"'") if brut else ""
    if not traduction or len(traduction) > len(question) * _MAX_TRANSLATION_RATIO:
        return None
    if traduction.casefold() == question.casefold():
        return None
    return traduction


def traduire_comme_la_production(
    texte: str, hote: str, modele: str, timeout: float
) -> dict[str, Any]:
    """UN APPEL DE TRADUCTION, ET LE GABARIT EST CELUI DE `src/`.

    LE GABARIT N'EST PAS RECOPIE, IL EST RENDU. `prompts/translate_query.j2` est
    charge par l'environnement Jinja de la production, `_get_jinja_env()` : un
    prompt recopie ici divergerait du jour ou la production changerait le sien,
    et le banc mesurerait une traduction que le service n'emet plus. Les quatre
    reglages de l'appel sont ceux de `translate_question` — temperature `0.0`,
    `max_tokens` 150, `thinking=False`, une seule generation.

    `thinking=False` passe par `chat_template_kwargs` PAR REQUETE : rien n'est
    pose cote serveur, `vllm-central` appartenant a l'equipe voisine.
    """
    from src.agent.dialecte_llm import dialecte_courant
    from src.agent.llm import _contenu_message, _get_jinja_env

    prompt = _get_jinja_env().get_template("translate_query.j2").render(question=texte)
    dialecte = dialecte_courant()._replace(hote=hote, modele=modele)
    charge = dialecte.charge(
        [{"role": "user", "content": prompt}],
        stream=False,
        temperature=0.0,
        max_tokens=150,
        thinking=False,
    )
    depart = time.perf_counter()
    reponse = httpx.post(dialecte.url_chat, json=charge, timeout=timeout)
    millisecondes = (time.perf_counter() - depart) * 1000
    reponse.raise_for_status()
    corps = reponse.json()
    # LE LECTEUR DE FORME EST CELUI DE LA PRODUCTION, ET IL N'EST PAS RECOPIE.
    # `_contenu_message` rend "" sur un corps valide mais de forme inattendue —
    # `content` a `null`, `content` qui n'est pas une chaine —, la ou un
    # `.get("content").strip()` ecrit ici leverait ou rendrait « None ». Le §4.55
    # a paye cette confusion une fois : les deux appels non-flux de `llm.py`
    # tombaient sur leur repli en HTTP 200, sans qu'une ligne de journal accuse
    # autre chose que le serveur.
    contenu = _contenu_message(corps)
    usage = corps.get("usage") or {}
    return {
        "ms": millisecondes,
        "raison_de_fin": str((corps.get("choices") or [{}])[0].get("finish_reason")),
        "jetons": int(usage.get("completion_tokens") or 0),
        "brut": contenu,
        "traduction": post_traitement_de_la_production(texte, contenu),
    }


# ─── LES RANGS, ETAGE PAR ETAGE ──────────────────────────────────────────────

# LES QUATRE ETAGES, ET ILS SONT EXCLUSIFS PAR CONSTRUCTION — l'ordre ou ils
# sont essayes les rend exclusifs, exactement comme la table des causes du
# §4.77. Un ancrage tombe dans le PREMIER qui le reconnait.
ETAGES = ("arrive", "perdu_au_reranking", "perdu_a_la_fusion", "jamais_recupere")


def etage_de_perte(rangs: dict[str, Any]) -> str:
    """A QUEL ETAGE L'ANCRAGE SORT-IL ? Et c'est la reponse a la reserve du §4.78.

    - `arrive` — il est dans le haut du classement final : rien a expliquer.
    - `perdu_au_reranking` — la liste fusionnee l'avait, le reranker ne le rend
      pas dans ses dix. C'est l'etage que le §4.78 soupconnait sans pouvoir le
      nommer, faute de versionner le rang de fusion des variantes.
    - `perdu_a_la_fusion` — au moins une sous-requete l'avait ramene, et la
      fusion RRF coupee a `retrieval_top_k` ne l'a pas garde.
    - `jamais_recupere` — aucune sous-requete ne l'a ramene. Ni la fusion ni le
      reranking n'y peuvent rien, et c'est le seul etage qu'un changement de
      classement ne repare pas.
    """
    if dans_le_haut(rangs.get("rerank")):
        return "arrive"
    if rangs.get("fusion") is not None:
        return "perdu_au_reranking"
    if any(r is not None for r in (rangs.get("par_requete") or [])):
        return "perdu_a_la_fusion"
    return "jamais_recupere"


# L'ORDRE DES ETAGES POUR UNE QUESTION, DU PLUS AMONT AU PLUS AVAL. Une question
# est classee par l'etage le plus AMONT ou l'UN de ses ancrages sort : reparer
# un etage aval ne la rendrait pas complete tant que l'amont perd l'autre
# ancrage. Prendre l'aval ferait croire qu'un reranking suffirait.
_AMONT_VERS_AVAL = ("jamais_recupere", "perdu_a_la_fusion", "perdu_au_reranking", "arrive")


def etage_de_la_question(etages: list[str]) -> str:
    """L'etage le plus AMONT parmi les ancrages de la question."""
    for etage in _AMONT_VERS_AVAL:
        if etage in etages:
            return etage
    return "arrive"


def _rangs_par_etage(
    ancrages: list[str], classements_amont: list[list[Any]], fusionnes: list[Any], final: list[Any]
) -> dict[str, dict[str, Any]]:
    """Le rang de chaque ancrage aux TROIS etages, et le rang de fusion EN EST.

    C'est la reserve nommee du §4.78 : il ne versionnait le rang de fusion que
    pour la variante de production, et savoir si une question se perd a la
    fusion ou au reranking etait donc hors d'atteinte pour les variantes.
    """
    return {
        eid: {
            "par_requete": [rang_de(eid, c) for c in classements_amont],
            "fusion": rang_de(eid, fusionnes),
            "rerank": rang_de(eid, final),
        }
        for eid in ancrages
    }


def jouer_les_variantes(
    question: str,
    traduction: str | None,
    ancrages: list[str],
    sous_questions: list[str],
    utilisable: bool,
    traductions_des_sous: dict[str, str | None],
    sous_questions_traduites: list[str],
    traduite_utilisable: bool,
) -> dict[str, Any]:
    """LES SEPT VARIANTES SUR UNE QUESTION, ET LEURS RANGS AUX TROIS ETAGES.

    L'ORDRE DES QUATRE PREMIERES EST CELUI DU §4.78, ET CE N'EST PAS UNE
    COQUETTERIE : c'est ce qui permet au controle positif de confronter les
    rangs UN A UN a `runs/2026-09-25-fusion-*.json`. Les trois neuves sont
    jouees APRES, sur des listes qu'elles recuperent elles-memes, et ne peuvent
    donc pas deplacer les quatre premieres.

    ─── LE CHOIX DE LA VARIANTE TRADUITE, ET IL EST ARGUMENTE ────────────────

    Le §4.78 a laisse la question ouverte en deux termes : traduire CHAQUE
    SOUS-QUESTION, ou traduire la question PUIS la decomposer. Les deux sont
    joues, et voici pourquoi l'une est la variante principale et l'autre la
    contre-epreuve.

    `fusion_traduite_*` — CHAQUE SOUS-QUESTION EST TRADUITE, ET LA RECUPERATION
    EST CELLE DE LA PRODUCTION, MOT POUR MOT. `retrieve(sous, translation=…)`
    est exactement l'appel que `graph.py` emet pour la question : quatre
    classements — dense et lexical, pour la sous-question et pour sa traduction
    — fondus par `fuse` au `settings.translation_weight` de la production, qui
    donne MOINS de confiance a la traduction. C'est le geste implementable dans
    `src/` sans y ecrire une ligne de fusion neuve, et c'est la SEULE difference
    avec `fusion_rerank_*` du §4.78 : memes sous-questions, lues du meme cache.

    `fusion_question_traduite_decomposee` — L'AUTRE ORDRE, ET IL CHANGE DEUX
    CHOSES A LA FOIS, CE QUI EST DIT. Decomposer la question traduite rend des
    sous-questions QUI NE SONT PAS LES TRADUCTIONS DES PREMIERES : le modele
    recoupe les besoins autrement. Les apparier par leur rang dans la liste
    serait un ORACLE D'AFFECTATION, exactement celui que le §4.77 s'etait
    reproche et que le §4.78 a retire. Elles ne sont donc PAS appariees : les
    classements des sous-questions d'origine entrent au poids 1,0, ceux des
    sous-questions traduites au `translation_weight` que `retrieve` applique a
    la traduction de la question entiere — lu du reglage, et valant 1,0 sur ce
    poste, c'est-a-dire l'egalite. Le reranking par sous-question score
    contre les DEUX familles et garde le maximum, comme au §4.78 : un passage
    qui repond parfaitement a un besoin dans une seule des deux langues doit
    sortir.

    ─── LE REPLI, ET IL EST APPARIE A LA VARIANTE ────────────────────────────

    Quand il n'y a rien a decomposer, les variantes du §4.78 retombaient sur la
    requete unique SANS traduction, parce qu'elles n'en avaient pas. Les
    variantes traduites, elles, retombent sur la requete unique AVEC traduction
    — c'est-a-dire sur LA PRODUCTION EXACTE. C'est le seul repli coherent : un
    decomposeur traduisant, place dans `src/`, ne perdrait pas la recherche
    translingue sur les questions qu'il renonce a decomposer. Tenir l'autre
    repli ferait payer a ces questions une perte que l'implementation n'aurait
    pas, et les 69 questions a besoin unique du jeu de reglage la porteraient.
    """
    from mesurer_fusion_sous_questions import rerank_au_meilleur_score

    from src.agent.retriever import rerank, retrieve
    from src.agent.settings import settings

    mesure: dict[str, Any] = {"couts": {}, "paires_rerankees": {}, "n_fusionnes": {}}
    variantes: dict[str, dict[str, Any]] = {}

    def _noter(nom: str, amont: list[list[Any]], fusionnes: list[Any], final: list[Any]) -> None:
        variantes[nom] = _rangs_par_etage(ancrages, amont, fusionnes, final)
        mesure["n_fusionnes"][nom] = len(fusionnes)

    # ── 1. LA PRODUCTION, mot pour mot ───────────────────────────────────────
    t0 = time.perf_counter()
    fusion_prod = retrieve(question, translation=traduction)
    t1 = time.perf_counter()
    classement_prod = rerank(question, fusion_prod)
    t2 = time.perf_counter()
    mesure["couts"]["unique_avec_traduction_recuperation_ms"] = round((t1 - t0) * 1000, 1)
    mesure["couts"]["unique_avec_traduction_rerank_ms"] = round((t2 - t1) * 1000, 1)
    mesure["paires_rerankees"]["unique_avec_traduction"] = len(fusion_prod)
    _noter("unique_avec_traduction", [fusion_prod], fusion_prod, classement_prod)

    # ── 2. LA BASE APPARIEE du §4.78 ─────────────────────────────────────────
    t0 = time.perf_counter()
    fusion_nue = retrieve(question, translation=None)
    t1 = time.perf_counter()
    classement_nu = rerank(question, fusion_nue)
    t2 = time.perf_counter()
    mesure["couts"]["unique_sans_traduction_recuperation_ms"] = round((t1 - t0) * 1000, 1)
    mesure["couts"]["unique_sans_traduction_rerank_ms"] = round((t2 - t1) * 1000, 1)
    mesure["paires_rerankees"]["unique_sans_traduction"] = len(fusion_nue)
    _noter("unique_sans_traduction", [fusion_nue], fusion_nue, classement_nu)

    # ── 3 et 4. LA FUSION DU §4.78, SANS TRADUCTION ──────────────────────────
    if utilisable:
        t0 = time.perf_counter()
        amont = [retrieve(s, translation=None) for s in sous_questions]
        fusionnes = fusionner_les_classements(amont, settings.retrieval_top_k)
        t1 = time.perf_counter()
        mesure["couts"]["decomposition_recuperation_ms"] = round((t1 - t0) * 1000, 1)

        t0 = time.perf_counter()
        entiere = rerank(question, fusionnes)
        t1 = time.perf_counter()
        mesure["couts"]["fusion_rerank_entiere_ms"] = round((t1 - t0) * 1000, 1)
        mesure["paires_rerankees"]["fusion_rerank_entiere"] = len(fusionnes)
        _noter("fusion_rerank_entiere", amont, fusionnes, entiere)

        t0 = time.perf_counter()
        par_sous, paires = rerank_au_meilleur_score(sous_questions, fusionnes)
        t1 = time.perf_counter()
        mesure["couts"]["fusion_rerank_sous_questions_ms"] = round((t1 - t0) * 1000, 1)
        mesure["paires_rerankees"]["fusion_rerank_sous_questions"] = paires
        _noter("fusion_rerank_sous_questions", amont, fusionnes, par_sous)
    else:
        for nom in ("fusion_rerank_entiere", "fusion_rerank_sous_questions"):
            _noter(nom, [fusion_nue], fusion_nue, classement_nu)
            mesure["paires_rerankees"][nom] = len(fusion_nue)
        mesure["couts"]["decomposition_recuperation_ms"] = mesure["couts"][
            "unique_sans_traduction_recuperation_ms"
        ]
        for nom in ("fusion_rerank_entiere_ms", "fusion_rerank_sous_questions_ms"):
            mesure["couts"][nom] = mesure["couts"]["unique_sans_traduction_rerank_ms"]

    # ── 5 et 6. LA FUSION TRADUITE, chaque sous-question traduite ────────────
    if utilisable:
        t0 = time.perf_counter()
        amont_t = [retrieve(s, translation=traductions_des_sous.get(s)) for s in sous_questions]
        fusionnes_t = fusionner_les_classements(amont_t, settings.retrieval_top_k)
        t1 = time.perf_counter()
        mesure["couts"]["decomposition_traduite_recuperation_ms"] = round((t1 - t0) * 1000, 1)

        t0 = time.perf_counter()
        entiere_t = rerank(question, fusionnes_t)
        t1 = time.perf_counter()
        mesure["couts"]["fusion_traduite_rerank_entiere_ms"] = round((t1 - t0) * 1000, 1)
        mesure["paires_rerankees"]["fusion_traduite_rerank_entiere"] = len(fusionnes_t)
        _noter("fusion_traduite_rerank_entiere", amont_t, fusionnes_t, entiere_t)

        t0 = time.perf_counter()
        par_sous_t, paires_t = rerank_au_meilleur_score(sous_questions, fusionnes_t)
        t1 = time.perf_counter()
        mesure["couts"]["fusion_traduite_rerank_sous_questions_ms"] = round((t1 - t0) * 1000, 1)
        mesure["paires_rerankees"]["fusion_traduite_rerank_sous_questions"] = paires_t
        _noter("fusion_traduite_rerank_sous_questions", amont_t, fusionnes_t, par_sous_t)
    else:
        # LE REPLI DES VARIANTES TRADUITES EST LA PRODUCTION EXACTE, et non la
        # requete nue : elles traduisent, et une question qu'elles renoncent a
        # decomposer garde sa recherche translingue.
        for nom in ("fusion_traduite_rerank_entiere", "fusion_traduite_rerank_sous_questions"):
            _noter(nom, [fusion_prod], fusion_prod, classement_prod)
            mesure["paires_rerankees"][nom] = len(fusion_prod)
        mesure["couts"]["decomposition_traduite_recuperation_ms"] = mesure["couts"][
            "unique_avec_traduction_recuperation_ms"
        ]
        for nom in (
            "fusion_traduite_rerank_entiere_ms",
            "fusion_traduite_rerank_sous_questions_ms",
        ):
            mesure["couts"][nom] = mesure["couts"]["unique_avec_traduction_rerank_ms"]

    # ── 7. L'AUTRE ORDRE : la question traduite PUIS decomposee ──────────────
    if utilisable:
        # LES SOUS-QUESTIONS DE LA TRADUCTION NE SONT PAS APPARIEES AUX AUTRES,
        # et c'est le refus de l'oracle d'affectation. Quand la question traduite
        # ne se decompose pas, la famille traduite se reduit a la traduction
        # ENTIERE — ce que la production donne deja a `retrieve`.
        familles_t = (
            sous_questions_traduites
            if traduite_utilisable
            else ([traduction] if traduction else [])
        )
        t0 = time.perf_counter()
        amont_o = [retrieve(s, translation=None) for s in sous_questions]
        amont_tr = [retrieve(s, translation=None) for s in familles_t]
        poids = [1.0] * len(amont_o) + [settings.translation_weight] * len(amont_tr)
        tous = amont_o + amont_tr
        retenus = [(c, p) for c, p in zip(tous, poids, strict=True) if c]
        fusionnes_o = (
            fuse_pondere([c for c, _ in retenus], settings.retrieval_top_k, [p for _, p in retenus])
            if retenus
            else []
        )
        t1 = time.perf_counter()
        mesure["couts"]["question_traduite_decomposee_recuperation_ms"] = round((t1 - t0) * 1000, 1)

        t0 = time.perf_counter()
        toutes_les_sous = list(sous_questions) + list(familles_t)
        par_sous_o, paires_o = rerank_au_meilleur_score(toutes_les_sous, fusionnes_o)
        t1 = time.perf_counter()
        mesure["couts"]["fusion_question_traduite_decomposee_ms"] = round((t1 - t0) * 1000, 1)
        mesure["paires_rerankees"]["fusion_question_traduite_decomposee"] = paires_o
        _noter("fusion_question_traduite_decomposee", tous, fusionnes_o, par_sous_o)
        mesure["n_sous_questions_traduites"] = len(familles_t)
    else:
        _noter("fusion_question_traduite_decomposee", [fusion_prod], fusion_prod, classement_prod)
        mesure["paires_rerankees"]["fusion_question_traduite_decomposee"] = len(fusion_prod)
        mesure["couts"]["question_traduite_decomposee_recuperation_ms"] = mesure["couts"][
            "unique_avec_traduction_recuperation_ms"
        ]
        mesure["couts"]["fusion_question_traduite_decomposee_ms"] = mesure["couts"][
            "unique_avec_traduction_rerank_ms"
        ]
        mesure["n_sous_questions_traduites"] = 0

    mesure["variantes"] = variantes
    return mesure


def fuse_pondere(classements: list[list[Any]], top_k: int, poids: list[float]) -> list[Any]:
    """`fuse` de `src/`, AVEC des poids inegaux, et c'est la seule difference.

    `fusionner_les_classements` du §4.78 donne des poids EGAUX, et le dit : les
    sous-questions y sont soeurs, aucune n'est la requete d'origine. Ici les
    classements ne le sont pas — une famille vient de la question, l'autre de sa
    traduction —, et la production a un poids POUR CE CAS : `translation_weight`,
    que `retrieve` applique aux classements de la traduction.

    ET CE POIDS VAUT 1,0 SUR CE POSTE, C'EST-A-DIRE L'EGALITE. `mesure` le 25
    septembre 2026 dans l'environnement du conteneur servi — `TRANSLATION_WEIGHT=1.0`
    — et c'est aussi le defaut de `settings.py`. La docstring de `retrieve` ecrit
    que « la traduction pese moins » : elle decrit ce que le reglage PERMET, pas
    ce que ce poste APPLIQUE. La fonction lit donc `settings.translation_weight`
    et n'ecrit aucune valeur en dur — un banc qui coderait 1,0 mesurerait encore
    1,0 le jour ou le service passerait a 0,5, et un banc qui coderait 0,5
    mesurerait aujourd'hui une ponderation que le service n'applique pas.
    """
    from src.agent.lexical import fuse

    non_vides = [c for c in classements if c]
    if not non_vides:
        return []
    return fuse(non_vides, top_k, poids=list(poids))


def sondes_amont(question: str, traduction: str | None, ancrages: list[str]) -> dict[str, Any]:
    """LES DEUX MOTEURS SEPAREMENT, POUR LA QUESTION ET POUR SA TRADUCTION.

    POURQUOI CETTE SONDE EXISTE. Pour les deux variantes a requete UNIQUE, ce
    que `_rangs_par_etage` appelle `par_requete` est la sortie de `retrieve` —
    c'est-a-dire une liste DEJA fondue et DEJA coupee a `retrieval_top_k`. Leur
    etage `perdu_a_la_fusion` est donc vide par construction, et leur
    `jamais_recupere` veut dire « absent des cinquante de `retrieve` », ce qui
    confond « aucun moteur ne l'a vu » et « la fusion interne l'a coupe ».

    Le §4.77 a publie cette separation pour la production SUR LE JEU DISPERSE
    (`runs/2026-09-24-recuperation-p50.json`). Les jeux de reglage et de controle
    ne l'ont jamais eue, et c'est precisement la ou vivent `G-110` et `q18` : le
    diagnostic que le §4.78 reclame serait muet sans elle. Quatre recherches de
    plus par question, et elles n'entrent dans AUCUNE variante ni dans AUCUN
    cout publie — c'est une sonde de diagnostic, pas une mesure de chaine.
    """
    from src.agent.retriever import _dense_search, _lexical_search
    from src.agent.settings import settings

    k = settings.fetch_k
    sondes: dict[str, Any] = {
        "dense_question": _dense_search(question, k),
        "lexical_question": _lexical_search(question, k) if settings.hybrid_search else [],
    }
    if traduction:
        sondes["dense_traduction"] = _dense_search(traduction, k)
        sondes["lexical_traduction"] = (
            _lexical_search(traduction, k) if settings.hybrid_search else []
        )
    return {
        eid: {nom: rang_de(eid, classement) for nom, classement in sondes.items()}
        for eid in ancrages
    }


# ─── LE DEPOUILLEMENT ────────────────────────────────────────────────────────


def depouiller(lignes: list[dict[str, Any]]) -> dict[str, Any]:
    """LES ANCRAGES ET LES QUESTIONS COMPLETES, variante par variante.

    « Questions completes » est la grandeur des §4.76 a §4.78 : le nombre de
    questions dont TOUS les ancrages entrent dans le haut. Le denominateur ne
    bouge pas d'un lot a l'autre, sans quoi les tableaux ne se compareraient pas.
    """
    resultats: dict[str, Any] = {}
    for variante in VARIANTES:
        ancrages = sum(
            1
            for ligne in lignes
            for r in ligne["variantes"][variante].values()
            if dans_le_haut(r["rerank"])
        )
        completes = [
            ligne["id"]
            for ligne in lignes
            if ligne["variantes"][variante]
            and all(dans_le_haut(r["rerank"]) for r in ligne["variantes"][variante].values())
        ]
        resultats[variante] = {
            "ancrages_dans_le_haut": ancrages,
            "questions_completes": len(completes),
            "questions_completes_ids": completes,
        }
    return resultats


def non_regression(depouille: dict[str, Any], base: str) -> dict[str, Any]:
    """LES QUESTIONS GAGNEES ET PERDUES, UNE PAR UNE, ET NOMMEES.

    Un solde net cacherait un echange : le jeu de controle du §4.78 est reste a
    **14** en perdant `q18` et en gagnant `q05`, et seules les listes nommees le
    disent. C'est ce bilan, pris CONTRE LA PRODUCTION, qui deciderait un jour
    d'un changement de production — la base appariee, elle, ne sert qu'a
    imputer : elle separe l'effet de la decomposition de celui du retrait de la
    traduction.
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


def repartir_par_etage(lignes: list[dict[str, Any]]) -> dict[str, Any]:
    """L'ECART REPARTI PAR ETAGE, EN ANCRAGES ET EN QUESTIONS.

    C'est la QUESTION OUVERTE B du §4.78, et elle demandait exactement cela :
    savoir si ce qui manque se perd a la fusion — l'ancrage n'entre pas dans les
    cinquante fondus — ou au reranking — il y entre et n'en ressort pas. Le §4.78
    ne versionnait le rang de fusion que pour la variante de production ; ce banc
    le versionne pour les SEPT, et la repartition en decoule sans hypothese.

    Les quatre etages sont EXCLUSIFS par construction (`etage_de_perte`), donc
    les comptes SOMMENT au nombre d'ancrages et au nombre de questions du jeu.
    Le banc l'assertit : une repartition qui ne somme pas decrit autre chose que
    le jeu qu'elle pretend decrire.
    """
    table: dict[str, Any] = {}
    for variante in VARIANTES:
        ancrages = dict.fromkeys(ETAGES, 0)
        questions = dict.fromkeys(ETAGES, 0)
        ids_par_etage: dict[str, list[str]] = {e: [] for e in ETAGES}
        for ligne in lignes:
            etages = [etage_de_perte(r) for r in ligne["variantes"][variante].values()]
            for etage in etages:
                ancrages[etage] += 1
            etage_q = etage_de_la_question(etages)
            questions[etage_q] += 1
            ids_par_etage[etage_q].append(ligne["id"])
        total_ancrages = sum(len(ligne["gold"]) for ligne in lignes)
        table[variante] = {
            "ancrages": ancrages,
            "somme_ancrages": sum(ancrages.values()),
            "questions": questions,
            "somme_questions": sum(questions.values()),
            "questions_par_etage": ids_par_etage,
            "somme_juste": sum(ancrages.values()) == total_ancrages
            and sum(questions.values()) == len(lignes),
        }
    return table


def ecart_a_la_borne(lignes: list[dict[str, Any]], oracle: Path | None) -> dict[str, Any]:
    """L'ECART A LA BORNE DE L'ORACLE, REPARTI PAR ETAGE — et c'est une INTERSECTION.

    LA BORNE EST CELLE DU §4.77 : l'oracle `decomposition`, **86** ancrages et
    **28** questions completes sur le jeu disperse, avec son affectation
    sous-question → ancrage prise au mieux des permutations. Le §4.78 a mesure
    **72** et **19** : l'ecart vaut **14** ancrages et **9** questions, et
    personne ne savait ou il se perdait.

    ET L'ECART N'EST PAS UNE SOUSTRACTION DE COMPTES. 86 − 72 = 14 ne dit pas
    QUELS ancrages : une variante pourrait en placer 72 dont dix que l'oracle
    rate. L'ecart est donc pris comme une DIFFERENCE D'ENSEMBLES sur les cles
    `(question, ancrage)`, et le banc publie AUSSI les ancrages que la variante
    place et que l'oracle ne place pas — un ecart a sens unique mentirait sur le
    mouvement.
    """
    if oracle is None or not oracle.exists():
        return {"disponible": False, "raison": f"oracle absent : {oracle}"}
    brut = json.loads(oracle.read_text(encoding="utf-8"))
    borne_ancrages = {
        (ligne["id"], eid)
        for ligne in brut["lignes"]
        for eid, rang in (ligne.get("oracle_decomposition_rerank") or {}).items()
        if dans_le_haut(rang)
    }
    borne_questions = {
        ligne["id"]
        for ligne in brut["lignes"]
        if (ligne.get("oracle_decomposition_rerank") or {})
        and all(
            dans_le_haut(rang) for rang in (ligne.get("oracle_decomposition_rerank") or {}).values()
        )
    }
    table: dict[str, Any] = {
        "disponible": True,
        "oracle": oracle.name,
        "borne_ancrages": len(borne_ancrages),
        "borne_questions": len(borne_questions),
        "variantes": {},
    }
    for variante in VARIANTES:
        atteints = {
            (ligne["id"], eid)
            for ligne in lignes
            for eid, r in ligne["variantes"][variante].items()
            if dans_le_haut(r["rerank"])
        }
        completes = {
            ligne["id"]
            for ligne in lignes
            if ligne["variantes"][variante]
            and all(dans_le_haut(r["rerank"]) for r in ligne["variantes"][variante].values())
        }
        manquants = borne_ancrages - atteints
        etages = dict.fromkeys(ETAGES, 0)
        for identifiant, eid in manquants:
            for ligne in lignes:
                if ligne["id"] == identifiant:
                    etages[etage_de_perte(ligne["variantes"][variante][eid])] += 1
                    break
        questions_manquantes = sorted(borne_questions - completes)
        etages_q = dict.fromkeys(ETAGES, 0)
        for identifiant in questions_manquantes:
            for ligne in lignes:
                if ligne["id"] == identifiant:
                    etages_q[
                        etage_de_la_question(
                            [etage_de_perte(r) for r in ligne["variantes"][variante].values()]
                        )
                    ] += 1
                    break
        table["variantes"][variante] = {
            "ancrages_atteints": len(atteints),
            "ancrages_de_la_borne_manques": len(manquants),
            "ancrages_hors_borne_gagnes": len(atteints - borne_ancrages),
            "ancrages_manques_par_etage": etages,
            "questions_completes": len(completes),
            "questions_de_la_borne_manquees": questions_manquantes,
            "questions_hors_borne_gagnees": sorted(completes - borne_questions),
            "questions_manquees_par_etage": etages_q,
            "somme_juste": sum(etages.values()) == len(manquants)
            and sum(etages_q.values()) == len(questions_manquantes),
        }
    return table


def diagnostiquer(lignes: list[dict[str, Any]], interessantes: set[str]) -> list[dict[str, Any]]:
    """LE DIAGNOSTIC D'UNE QUESTION, ET CE N'EST PAS UNE REPARATION.

    Pour chaque question nommee — perdue contre la production ou contre la base,
    sous n'importe quelle variante —, le banc rend : ses sous-questions dans les
    deux langues, la traduction que la production aurait emise, et, ancrage par
    ancrage, le rang A CHAQUE ETAGE de CHAQUE variante, plus les rangs des deux
    moteurs pris separement. C'est ce qui manquait au §4.78 pour lire `G-110`,
    `q18` et `D-003` autrement que comme trois lignes d'un tableau.
    """
    return [
        {
            "id": ligne["id"],
            "question": ligne["question"],
            "traduction": ligne["traduction"],
            "gold": ligne["gold"],
            "nature": ligne["nature"],
            "repli": ligne["repli"],
            "sous_questions": ligne["sous_questions"],
            "traductions_des_sous_questions": ligne["traductions_des_sous_questions"],
            "sous_questions_de_la_question_traduite": ligne["sous_questions_traduites"],
            "sondes_amont": ligne["sondes_amont"],
            "etages": {
                variante: {
                    eid: {**rangs, "etage": etage_de_perte(rangs)}
                    for eid, rangs in ligne["variantes"][variante].items()
                }
                for variante in VARIANTES
            },
        }
        for ligne in lignes
        if ligne["id"] in interessantes
    ]


# ─── LE CONTROLE POSITIF, ET IL EST ANTERIEUR A TOUTE PUBLICATION ────────────


def controle_positif(
    lignes: list[dict[str, Any]],
    depouille: dict[str, Any],
    jeu: Path,
    lot38: Path | None,
    reference: Path | None,
) -> dict[str, Any]:
    """LE BANC ETENDU REJOUE-T-IL LE §4.78 ? TROIS TERMES, ET IL REFUSE SANS EUX.

    TERME 1 — LES DOUZE COUPLES DU §4.78, A L'UNITE. Quatre variantes, trois
    jeux, ancrages ET questions. Ils sont ecrits en dur au haut de ce fichier,
    recopies du registre : c'est la confrontation au DOCUMENT, celle qui attrape
    un banc qui aurait derive avec ses propres fichiers.

    TERME 2 — LES RANGS, UN A UN, CONTRE LES BILANS VERSIONNES DU §4.78. Et
    c'est une INTERSECTION, pas un accord de comptes : la lecon du §4.77, ou
    deux bancs mesurant deux jeux pouvaient rendre 53 et 7 sans qu'un seul rang
    ne coincide. Les cles `(question, ancrage)` doivent etre les MEMES, et le
    rang de reranking de CHACUNE des quatre variantes du lot 38 doit etre
    IDENTIQUE — pas seulement celui de la production.

    TERME 3 — LES 120 RANGS DU §4.77, pour la variante de production et sur le
    seul jeu disperse : `runs/2026-09-24-recuperation-p50.json`. C'est la chaine
    de bout en bout, mesuree la veille par un autre instrument.

    UN DESACCORD SUR L'UN DES TROIS EST UN REFUS. Une mesure de la traduction
    contre une base qui a bouge ne mesure rien, et l'imprimer suffirait a ce
    qu'elle soit recopiee.
    """
    verdicts: dict[str, Any] = {}

    attendus = CONTROLE_4_78.get(jeu.name)
    if attendus is None:
        verdicts["couples_4_78"] = {"applicable": False, "raison": f"jeu inconnu : {jeu.name}"}
    else:
        desaccords = [
            {
                "variante": variante,
                "attendu": list(couple),
                "mesure": [
                    depouille[variante]["ancrages_dans_le_haut"],
                    depouille[variante]["questions_completes"],
                ],
            }
            for variante, couple in attendus.items()
            if (
                depouille[variante]["ancrages_dans_le_haut"],
                depouille[variante]["questions_completes"],
            )
            != couple
        ]
        verdicts["couples_4_78"] = {
            "applicable": True,
            "variantes_confrontees": len(attendus),
            "desaccords": desaccords,
            "accord": not desaccords,
        }

    if lot38 is None or not lot38.exists():
        verdicts["rangs_du_lot_38"] = {"applicable": False, "raison": f"bilan absent : {lot38}"}
    else:
        brut = json.loads(lot38.read_text(encoding="utf-8"))["lignes"]
        par_variante: dict[str, Any] = {}
        for variante in VARIANTES_DU_LOT_38:
            attendu = {
                (ligne["id"], eid): rang
                for ligne in brut
                for eid, rang in ligne["variantes"][variante].items()
            }
            mesure = {
                (ligne["id"], eid): r["rerank"]
                for ligne in lignes
                for eid, r in ligne["variantes"][variante].items()
            }
            communes = set(attendu) & set(mesure)
            ecarts = [
                {"cle": list(cle), "attendu": attendu[cle], "mesure": mesure[cle]}
                for cle in sorted(communes)
                if attendu[cle] != mesure[cle]
            ]
            par_variante[variante] = {
                "cles_attendues": len(attendu),
                "cles_mesurees": len(mesure),
                "cles_communes": len(communes),
                "rangs_identiques": len(communes) - len(ecarts),
                "n_desaccords": len(ecarts),
                "desaccords": ecarts[:20],
                "accord": len(communes) == len(attendu) == len(mesure) and not ecarts,
            }
        verdicts["rangs_du_lot_38"] = {
            "applicable": True,
            "bilan": lot38.name,
            "par_variante": par_variante,
            "accord": all(v["accord"] for v in par_variante.values()),
        }

    if reference is None or not reference.exists():
        verdicts["rangs_du_4_77"] = {"applicable": False, "raison": "reference absente"}
    else:
        attendu = {
            (ligne["id"], eid): r["rerank"]
            for ligne in json.loads(reference.read_text(encoding="utf-8"))["lignes"]
            for eid, r in ligne["rangs"].items()
        }
        mesure = {
            (ligne["id"], eid): r["rerank"]
            for ligne in lignes
            for eid, r in ligne["variantes"]["unique_avec_traduction"].items()
        }
        communes = set(attendu) & set(mesure)
        ecarts = [
            {"cle": list(cle), "attendu": attendu[cle], "mesure": mesure[cle]}
            for cle in sorted(communes)
            if attendu[cle] != mesure[cle]
        ]
        verdicts["rangs_du_4_77"] = {
            "applicable": True,
            "reference": reference.name,
            "cles_attendues": len(attendu),
            "cles_mesurees": len(mesure),
            "cles_communes": len(communes),
            "rangs_identiques": len(communes) - len(ecarts),
            "n_desaccords": len(ecarts),
            "desaccords": ecarts[:20],
            "accord": len(communes) == len(attendu) == len(mesure) and not ecarts,
        }

    applicables = [v for v in verdicts.values() if v.get("applicable")]
    verdicts["termes_applicables"] = len(applicables)
    verdicts["accord"] = bool(applicables) and all(v["accord"] for v in applicables)
    return verdicts


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


# ─── LES PRODUCTEURS DE CACHE, ET LE BANC NE LES APPELLE JAMAIS ──────────────


def _appels_de_traduction(
    textes: list[str], hote: str, modele: str, timeout: float
) -> dict[str, Any]:
    """Traduit une liste de textes, et releve la raison de fin de CHACUN.

    UN APPEL DE CHAUFFE EST JOUE D'ABORD ET EXCLU DES STATISTIQUES — meme raison
    qu'au §4.78 : le premier appel paie la mise en place cote serveur, et le
    compter ferait remonter la mediane sur un cout qu'aucune requete ne paie en
    production.

    LES REFUS DE LA PRODUCTION SONT COMPTES A PART DES PANNES. Une traduction
    que `translate_question` aurait jetee — vide, trop longue, identique a la
    question — n'est pas un echec du banc : c'est le comportement du service, et
    la sous-question part alors en recherche MONOLINGUE, exactement comme en
    production. Les confondre ferait passer un comportement pour une panne.
    """
    chauffe: dict[str, Any] = {}
    try:
        brut = traduire_comme_la_production(
            "What is the stated purpose of this corpus, in one sentence?", hote, modele, timeout
        )
        chauffe = {
            "ms": round(brut["ms"], 1),
            "raison_de_fin": brut["raison_de_fin"],
            "exclu_des_statistiques": True,
        }
    except Exception as panne:  # noqa: BLE001 — absorption large ASSUMEE, et DITE
        chauffe = {"panne": f"{type(panne).__name__}: {panne}", "exclu_des_statistiques": True}

    cache: dict[str, str] = {}
    refus: list[dict[str, str]] = []
    pannes: list[str] = []
    latences: list[float] = []
    jetons: list[int] = []
    raisons: list[str] = []
    for index, texte in enumerate(textes, 1):
        try:
            brut = traduire_comme_la_production(texte, hote, modele, timeout)
            latences.append(brut["ms"])
            jetons.append(brut["jetons"])
            raisons.append(brut["raison_de_fin"])
            if brut["traduction"] is None:
                refus.append({"texte": texte[:90], "brut": brut["brut"][:90]})
            else:
                cache[texte] = brut["traduction"]
        except Exception as panne:  # noqa: BLE001 — meme absorption, meme raison
            pannes.append(f"{texte[:60]}: {type(panne).__name__}: {panne}")
        if index % 20 == 0:
            print(f"  {index}/{len(textes)}", flush=True)
    return {
        "appel_de_chauffe": chauffe,
        "generations": len(textes),
        "raisons_de_fin": {r: raisons.count(r) for r in sorted(set(raisons))},
        "traduites": len(cache),
        "refusees_par_la_production": refus,
        "n_refusees": len(refus),
        "pannes": pannes,
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
            "total": sum(jetons),
            "mediane": round(statistics.median(jetons), 1) if jetons else None,
        },
        "cache": cache,
    }


def _decompositions(jeu: Path, questions: list[dict[str, Any]]) -> dict[str, list[str]]:
    """LES DECOMPOSITIONS DU §4.78, LUES ET JAMAIS REFABRIQUEES.

    C'est ce qui rend ce lot lisible. Refabriquer les sous-questions ferait
    varier la decomposition EN MEME TEMPS que la traduction — le modele n'est
    pas deterministe a temperature 0,2 — et l'ecart entre `fusion_rerank_*` et
    `fusion_traduite_rerank_*` ne serait imputable a rien. Le cache versionne du
    §4.78 est donc EXIGE, et son absence est un refus.
    """
    chemin = cache_de_decomposition(jeu)
    if not chemin.exists():
        raise SystemExit(f"ABSENT : {chemin}. C'est le cache versionne du §4.78.")
    cache: dict[str, list[str]] = json.loads(chemin.read_text(encoding="utf-8"))
    manquantes = [q["id"] for q in questions if q["id"] not in cache]
    if manquantes:
        raise SystemExit(
            f"REFUS : {len(manquantes)} question(s) sans decomposition en cache "
            f"({', '.join(manquantes[:5])}…). La fusion serait mesuree sur un autre jeu."
        )
    return cache


def _traductions_des_questions(questions: list[dict[str, Any]]) -> dict[str, str]:
    """Le cache de traductions des QUESTIONS, EXIGE et jamais fabrique.

    Meme refus qu'aux §4.76 a §4.78 : une traduction manquante deplacerait le
    rappel de la variante de production sans un mot, et c'est elle que le
    controle positif confronte aux deux references.
    """
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


def etape_traduction_des_sous_questions(
    questions: list[dict[str, Any]], jeu: Path, hote: str, modele: str, timeout: float
) -> dict[str, Any]:
    """LE PRODUCTEUR du cache de traductions des sous-questions.

    Il ne traduit QUE les sous-questions des decompositions UTILISABLES : une
    decomposition en repli retombe sur la requete unique, qui a deja sa
    traduction en cache, et traduire ce qui ne sera jamais emis gonflerait le
    cout publie d'appels que l'implementation ne ferait pas.
    """
    cache_decomposition = _decompositions(jeu, questions)
    textes: list[str] = []
    vus: set[str] = set()
    for q in questions:
        sous = cache_decomposition[q["id"]]
        utilisable, _ = decomposition_utilisable(q["question"], sous)
        if not utilisable:
            continue
        for s in sous:
            if s not in vus:
                vus.add(s)
                textes.append(s)
    print(f"{len(textes)} sous-questions distinctes a traduire", flush=True)
    bilan = _appels_de_traduction(textes, hote, modele, timeout)
    bilan["etape"] = "traduction-sous-questions"
    bilan["jeu"] = jeu.name
    bilan["modele"] = modele
    bilan["prompts_distincts"] = len(set(textes))
    return bilan


def etape_decomposition_de_la_question_traduite(
    questions: list[dict[str, Any]], jeu: Path, hote: str, modele: str, timeout: float, graine: int
) -> dict[str, Any]:
    """LE PRODUCTEUR du cache de decompositions de la question TRADUITE.

    LE PROMPT EST CELUI DU §4.78, IMPORTE ET NON RECOPIE — `prompt_de_decomposition`.
    La seule difference avec le lot 38 est le TEXTE qu'on lui donne : la
    traduction au lieu de la question. Un prompt recopie ici aurait pu deriver
    d'un caractere, et l'ecart entre les deux ordres aurait alors melange deux
    changements.
    """
    from mesurer_fusion_sous_questions import etape_decomposition

    traductions = _traductions_des_questions(questions)
    traduites = [
        {"id": q["id"], "question": traductions[q["question"]], "gold_element_ids": []}
        for q in questions
    ]
    bilan = etape_decomposition(traduites, jeu, hote, modele, timeout, graine)
    bilan["etape"] = "decomposition-de-la-question-traduite"
    bilan["texte_decompose"] = "la traduction de la question, lue de runs/.traductions.json"
    return bilan


def etape_fusion(
    questions: list[dict[str, Any]],
    jeu: Path,
    port_sante: int,
    lot38: Path | None,
    reference: Path | None,
    oracle: Path | None,
) -> dict[str, Any]:
    """LA MESURE : les sept variantes, sur chaque question du jeu."""
    from src.agent.settings import settings

    cache_decomposition = _decompositions(jeu, questions)
    traductions = _traductions_des_questions(questions)

    chemin_t = cache_de_traduction_des_sous_questions(jeu)
    if not chemin_t.exists():
        raise SystemExit(
            f"ABSENT : {chemin_t}. Joue d'abord --etape traduction-sous-questions --jeu {jeu}."
        )
    traductions_des_sous: dict[str, str] = json.loads(chemin_t.read_text(encoding="utf-8"))

    chemin_d = cache_de_decomposition_traduite(jeu)
    if not chemin_d.exists():
        raise SystemExit(
            f"ABSENT : {chemin_d}. Joue d'abord --etape decomposition-traduite --jeu {jeu}."
        )
    decompositions_traduites: dict[str, list[str]] = json.loads(
        chemin_d.read_text(encoding="utf-8")
    )

    debut = etat_des_stores(port_sante)

    # UN PASSAGE DE CHAUFFE, EXCLU DE TOUTE STATISTIQUE — meme raison qu'au
    # §4.78 : l'embedder et le cross-encoder sont charges paresseusement au
    # premier appel, et la premiere question du jeu porterait sans lui une
    # seconde de chargement qu'aucune autre ne paie.
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
    natures_traduites = {"decomposee": 0, "vide": 0, "une_seule": 0, "quasi_identique": 0}
    sans_traduction: list[str] = []
    t0 = time.perf_counter()
    for index, q in enumerate(questions, 1):
        ancrages = list(q["gold_element_ids"])
        sous = cache_decomposition[q["id"]]
        utilisable, nature = decomposition_utilisable(q["question"], sous)
        natures[nature] += 1
        traduction = traductions.get(q["question"])
        sous_traduites = decompositions_traduites.get(q["id"], [])
        traduite_utilisable, nature_t = decomposition_utilisable(traduction or "", sous_traduites)
        natures_traduites[nature_t] += 1
        paires_de_traduction = {s: traductions_des_sous.get(s) for s in sous}
        if utilisable:
            sans_traduction.extend(s for s, t in paires_de_traduction.items() if t is None)
        mesure = jouer_les_variantes(
            q["question"],
            traduction,
            ancrages,
            sous,
            utilisable,
            paires_de_traduction,
            sous_traduites,
            traduite_utilisable,
        )
        lignes.append(
            {
                "id": q["id"],
                "question": q["question"],
                "traduction": traduction,
                "gold": ancrages,
                "sous_questions": sous,
                "traductions_des_sous_questions": paires_de_traduction,
                "sous_questions_traduites": sous_traduites,
                "nature": nature,
                "nature_de_la_question_traduite": nature_t,
                "repli": not utilisable,
                "sondes_amont": sondes_amont(q["question"], traduction, ancrages),
                **mesure,
            }
        )
        if index % 10 == 0:
            print(f"  {index}/{len(questions)} — {time.perf_counter() - t0:.0f} s", flush=True)
    fin = etat_des_stores(port_sante)

    depouille = depouiller(lignes)
    vs_production = non_regression(depouille, "unique_avec_traduction")
    vs_base = non_regression(depouille, "unique_sans_traduction")
    nommees = {
        identifiant
        for tableau in (vs_production, vs_base)
        for bilan in tableau.values()
        for identifiant in bilan["perdues"] + bilan["gagnees"]
    }

    bilan: dict[str, Any] = {
        "etape": "fusion",
        "jeu": jeu.name,
        "date_utc": datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds"),
        "questions": len(questions),
        "ancrages": sum(len(ligne["gold"]) for ligne in lignes),
        "seuil_du_haut": _SEUIL_TOP,
        "max_sous_questions": _MAX_SOUS_QUESTIONS,
        "profondeurs": {
            "fetch_k": settings.fetch_k,
            "retrieval_top_k": settings.retrieval_top_k,
            "rerank_top_k": settings.rerank_top_k,
            "rrf_k": settings.rrf_k,
            "hybrid_search": settings.hybrid_search,
            "translation_weight": settings.translation_weight,
            "cross_lingual_search": settings.cross_lingual_search,
            "torch_device": settings.torch_device,
        },
        "natures_de_decomposition": natures,
        "natures_de_decomposition_de_la_traduction": natures_traduites,
        "sous_questions_sans_traduction": sorted(set(sans_traduction)),
        "n_sous_questions_sans_traduction": len(set(sans_traduction)),
        "passage_de_chauffe": chauffe,
        "stores": {"debut": debut, "fin": fin},
        "resultats": depouille,
        "non_regression_vs_production": vs_production,
        "non_regression_vs_sans_traduction": vs_base,
        "repartition_par_etage": repartir_par_etage(lignes),
        "ecart_a_la_borne": ecart_a_la_borne(lignes, oracle),
        "diagnostic": diagnostiquer(lignes, nommees),
        "couts": resumer_les_couts(lignes),
        "secondes": round(time.perf_counter() - t0, 1),
        "controle_positif": controle_positif(lignes, depouille, jeu, lot38, reference),
        "lignes": lignes,
    }
    return bilan


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--etape",
        required=True,
        choices=["traduction-sous-questions", "decomposition-traduite", "fusion"],
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
    parser.add_argument("--seed", type=int, default=39)
    parser.add_argument("--lot38", type=Path, help="Bilan du §4.78 pour ce jeu.")
    parser.add_argument("--reference", type=Path, help="Bilan du §4.77 (jeu disperse).")
    parser.add_argument("--oracle", type=Path, help="Bilan oracle du §4.77 (jeu disperse).")
    args = parser.parse_args()

    questions = charger_questions(args.jeu)
    if args.limite:
        questions = questions[: args.limite]
    print(f"{len(questions)} questions, jeu {args.jeu.name}, etape {args.etape}", flush=True)

    if args.etape == "traduction-sous-questions":
        bilan = etape_traduction_des_sous_questions(
            questions, args.jeu, args.llm_host, args.model, args.timeout
        )
    elif args.etape == "decomposition-traduite":
        bilan = etape_decomposition_de_la_question_traduite(
            questions, args.jeu, args.llm_host, args.model, args.timeout, args.seed
        )
    else:
        bilan = etape_fusion(
            questions, args.jeu, args.port_sante, args.lot38, args.reference, args.oracle
        )

    # L'ETAT DES STORES EST UN REFUS, PAS UNE NOTE — la regle du §4.78. Une
    # campagne qui a vu deux etats rend un tableau dont chaque ligne est juste
    # et dont le total ne decrit rien ; elle sort en 1 et le DIT.
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

    if args.etape == "traduction-sous-questions":
        chemin = cache_de_traduction_des_sous_questions(args.jeu)
        chemin.write_text(
            json.dumps(bilan["cache"], ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"cache : {bilan['traduites']}/{bilan['generations']} dans {chemin}")
        print(f"raisons de fin : {bilan['raisons_de_fin']}")
        print(f"refusees par la production : {bilan['n_refusees']}")
        print(f"latence ms : {bilan['latence_ms']}")
    elif args.etape == "decomposition-traduite":
        chemin = cache_de_decomposition_traduite(args.jeu)
        chemin.write_text(
            json.dumps(bilan["cache"], ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"cache : {len(bilan['cache'])}/{len(questions)} dans {chemin}")
        print(f"raisons de fin : {bilan['raisons_de_fin']}")
        print(f"natures : {bilan['natures']}")
        print(f"latence ms : {bilan['latence_ms']}")
    else:
        controle = bilan["controle_positif"]
        print(f"\ncontrole positif : {controle['termes_applicables']} terme(s) applicable(s)")
        for nom in ("couples_4_78", "rangs_du_lot_38", "rangs_du_4_77"):
            terme = controle[nom]
            if not terme.get("applicable"):
                print(f"  {nom:<18} NON APPLICABLE — {terme.get('raison')}")
            else:
                print(f"  {nom:<18} accord={terme['accord']}")
        if not controle["accord"]:
            # LE REFUS DE PUBLIER. Le bilan est ecrit — il porte la preuve du
            # desaccord — mais le banc sort en 1 et ne presente AUCUN resultat :
            # une mesure de la traduction contre une base qui a bouge ne mesure
            # rien, et l'imprimer suffirait a ce qu'elle soit recopiee.
            print("REFUS : le controle positif ne passe pas. Les variantes ne sont pas publiees.")
            return 1
        for variante in VARIANTES:
            ligne = bilan["resultats"][variante]
            print(
                f"  {variante:<40} ancrages {ligne['ancrages_dans_le_haut']:>4}"
                f"   questions completes {ligne['questions_completes']:>4}"
            )
        for variante, tableau in bilan["non_regression_vs_production"].items():
            print(
                f"  vs PRODUCTION — {variante:<40} "
                f"+{tableau['n_gagnees']} / -{tableau['n_perdues']}  "
                f"perdues : {', '.join(tableau['perdues']) or '—'}  "
                f"gagnees : {', '.join(tableau['gagnees']) or '—'}"
            )
    print(f"ecrit : {args.sortie}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
