#!/usr/bin/env python
"""Prouve, en LECTURE SEULE, que les ancrages d'un jeu de questions existent.

POURQUOI CE SCRIPT EXISTE, ET C'EST LA LEÇON LA PLUS CHÈRE DU CHANTIER. Un jeu
de questions qui rend 0 % de rappel ne dit pas si la recherche est cassée ou si
le jeu désigne le vide. Les deux produisent le même zéro, et le second est
arrivé : `mesuré` le 3 septembre 2026, le jeu de 138 questions alors versionné
désignait **129** `gold_element_ids` distincts dont **0** existait dans le
graphe — non par dérive d'identifiants, mais parce que le corpus avait été
remplacé (site canonique : `documentation/axes_amelioration.md`, §4.3).
`make eval` n'aurait pas rendu d'erreur : il aurait rendu un tableau faux.

Une mesure qui décide du plan doit laisser un artefact rejouable. Celui-ci est
l'antécédent de toute campagne : **il tourne AVANT, et un rappel mesuré après
son rouge ne veut rien dire.**

    # les deux jeux du dépôt, contre les stores en service
    CH=$(docker inspect -f '{{.NetworkSettings.Networks.rag_network.IPAddress}}' \
         rag-ingestion-pipeline-chromadb-1)
    NB=$(docker inspect -f '{{.NetworkSettings.Networks.rag_network.IPAddress}}' graphd)
    uv run --no-sync python scripts/verifier_les_ancrages.py \
        --chroma-host "$CH" --nebula-host "$NB" \
        tests/fixtures/golden_qa_generated.yaml \
        tests/fixtures/jeu_de_questions_pipeline.yaml

    # depuis un conteneur déjà branché à `rag_network`, les défauts suffisent
    docker exec -i rag-agent-api python - < scripts/verifier_les_ancrages.py

`graphd` et `chromadb` n'exposent aucun port sur l'hôte (`docker port graphd`
rend une sortie vide, `mesuré` le 8 septembre 2026) : les deux invocations
ci-dessus sont les seules qui les atteignent, et la première découvre les
adresses elle-même plutôt que de les figer dans un document.

CE SCRIPT EST EN LECTURE SEULE, ET CE N'EST PAS UNE PROMESSE : c'est gardé.
Les seuls appels de store qu'il fait sont `get_collection`, `count` et `get` du
côté ChromaDB, et `FETCH PROP ON *` du côté NebulaGraph.
`tests/unit/test_verification_des_ancrages.py`
(`TestLaSondeEstEnLectureSeule`) lit ce fichier par l'ARBRE SYNTAXIQUE, relève
le nom de chaque appel de méthode, et rougit si l'un d'eux est un verbe
d'écriture ChromaDB — `add`, `upsert`, `modify`, `delete`, `update` — ou si un
verbe d'écriture nGQL apparaît dans une chaîne. Le garde a été éprouvé par
mutation, dans les deux sens : voir son docstring.

Codes de sortie :

    0   tous les ancrages de tous les jeux existent, et concordent
    1   au moins un désaccord — le détail est imprimé
    2   les stores sont injoignables, ou un jeu est illisible : RIEN n'est
        prouvé, et ce code se distingue du 1 parce qu'un jeu sain derrière un
        store éteint ne doit pas passer pour un jeu périmé
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent

# Taille des lots de `FETCH PROP ON *`. Une requête nGQL trop longue est refusée
# par `graphd` ; 200 identifiants de dix caractères tiennent largement.
_LOT_NEBULA = 200
# ChromaDB pagine ses lectures. Même valeur que `retriever._LEXICAL_PAGE`, pour
# la même raison : au-delà, la mémoire du client devient le facteur limitant.
_PAGE_CHROMA = 2000

# Les deux schémas de jeu de questions que ce dépôt lit. Ils ne portent pas les
# ancrages sous la même clé, et confondre les deux est le genre de silence qui
# rend une sonde décorative : un jeu lu sous la mauvaise clé rend « 0 ancrage
# déclaré », donc VERT, sans avoir rien vérifié.
#
# Garde : `test_verification_des_ancrages.py`,
# `test_un_jeu_sous_la_mauvaise_cle_est_refuse_et_non_declare_vert`.
_CLES_ANCRAGES = ("gold_element_ids", "element_ids")

class StoreInjoignableError(RuntimeError):
    """Un store n'a pas répondu, ou un jeu n'a pas pu être lu.

    Distincte d'un désaccord : elle mène au code 2, pas au code 1. Un jeu sain
    derrière un store éteint ne doit pas passer pour un jeu périmé.
    """


# ─── Lecture des jeux ────────────────────────────────────────────────────────


def charger_jeu(chemin: Path) -> list[dict[str, Any]]:
    """Lit un jeu de questions, YAML ou JSON selon son suffixe.

    Le YAML est le format des jeux de ce dépôt et du pipeline, pour une raison
    mesurée qui vit au docstring de `scripts/generate_golden.py`. Le JSON reste
    lu : `runs/*.json` et les jeux d'avant le 8 septembre 2026 en sont.
    """
    texte = chemin.read_text(encoding="utf-8")
    en_yaml = chemin.suffix.lower() in (".yaml", ".yml")
    data = yaml.safe_load(texte) if en_yaml else json.loads(texte)
    if not isinstance(data, dict) or not isinstance(data.get("questions"), list):
        raise StoreInjoignableError(f"{chemin} ne porte pas de liste `questions`")
    return [q for q in data["questions"] if not q.get("_skip")]


def ancrages_de(question: dict[str, Any]) -> tuple[str, list[str]]:
    """Retourne la clé d'ancrage utilisée par cette question, et ses valeurs.

    Une question qui ne porte AUCUNE des clés connues n'est pas une question
    sans ancrage : c'est un schéma que cette sonde ne sait pas lire, et la
    différence décide du verdict. Rendre une liste vide la déclarerait
    conforme.
    """
    for cle in _CLES_ANCRAGES:
        if cle in question:
            return cle, list(question.get(cle) or [])
    raise StoreInjoignableError(
        f"question {question.get('id', '?')} : aucune des clés {_CLES_ANCRAGES} — "
        "schéma inconnu, la vérification n'a PAS eu lieu"
    )


def sans_reponse(question: dict[str, Any]) -> bool:
    """Vrai si la question attend une abstention.

    Les deux schémas le disent autrement : `unanswerable: true` côté agent,
    `strate: sans_reponse` côté pipeline.
    """
    return bool(question.get("unanswerable")) or question.get("strate") == "sans_reponse"


# ─── Les stores, en lecture seule ────────────────────────────────────────────


def lire_chroma(host: str, port: int, nom: str) -> tuple[dict[str, str], dict[str, Any], int]:
    """Lit l'index vectoriel entier et rend la carte `element_id -> source_path`.

    Returns:
        La carte, les métadonnées de la collection (dont l'estampille du modèle
        d'embedding), et le nombre de chunks.
    """
    import chromadb

    try:
        collection = chromadb.HttpClient(host=host, port=port).get_collection(nom)
        total = collection.count()
    except Exception as erreur:
        # Absorption LARGE et justifiée : un ChromaDB absent, un nom de
        # collection inconnu et un client incompatible produisent des erreurs de
        # transport, de schéma et de sérialisation sans ancêtre commun. Ce qui
        # compte est de sortir en 2 et non en 1 — un store éteint ne doit pas
        # faire passer un jeu sain pour un jeu périmé.
        raise StoreInjoignableError(f"ChromaDB {host}:{port} / {nom} : {erreur}") from erreur

    carte: dict[str, str] = {}
    for offset in range(0, total, _PAGE_CHROMA):
        lot = collection.get(limit=_PAGE_CHROMA, offset=offset, include=["metadatas"])
        for meta in lot.get("metadatas") or []:
            element_id = str(meta.get("element_id") or "")
            if element_id:
                carte[element_id] = str(meta.get("source_path") or "")
    return carte, dict(collection.metadata or {}), total


def lire_nebula(
    host: str, port: int, user: str, password: str, space: str, identifiants: list[str]
) -> set[str]:
    """Rend le sous-ensemble des identifiants qui existent comme sommets.

    `FETCH PROP ON *` est une lecture : il ne crée pas le sommet absent, il ne
    le rend simplement pas. C'est ce qui en fait le bon instrument — un `MATCH`
    par identifiant coûterait un aller-retour chacun.
    """
    from nebula3.Config import SessionPoolConfig
    from nebula3.gclient.net.SessionPool import SessionPool

    try:
        pool = SessionPool(user, password, space, [(host, port)])
        joignable = pool.init(SessionPoolConfig())
    except Exception as erreur:
        # ABSORPTION LARGE, ET VOICI SON MOTIF, parce qu'un `except Exception`
        # sans justification écrite est interdit dans ce dépôt.
        #
        # `SessionPool.init()` NE REND PAS `False` QUAND LE SERVEUR NE RÉPOND
        # PAS : il LÈVE un `RuntimeError` nu. Et `StoreInjoignableError` HÉRITE
        # de `RuntimeError`, donc les deux `except` de `main()` ne l'attrapaient
        # pas — un `except` ne voit jamais le PARENT de ce qu'il nomme. Le
        # script sortait en **1** avec une trace, là où ses quatre sites de
        # contrat promettent **2**. `mesuré` le 8 septembre 2026, ChromaDB
        # joignable et Nebula sur `192.0.2.1` (TEST-NET-1, non routable) :
        # `RuntimeError: The services status exception: [services:
        # ('192.0.2.1', 9669), status: BAD]`, `rc=1`. Et la différence n'est pas
        # cosmétique : 1 veut dire « ce jeu de questions est périmé », ce qui
        # enverrait réparer un jeu sain.
        #
        # LARGE plutôt que `except RuntimeError`, pour la même raison que
        # `lire_chroma` : ce chemin lève au moins trois familles sans ancêtre
        # commun autre que `Exception` — `RuntimeError` sur un service muet,
        # `InValidHostname` (qui dérive d'`Exception`) sur un nom qui ne résout
        # pas, et les erreurs de transport du client thrift. Toutes disent la
        # même chose : *le graphe n'a pas répondu, RIEN n'est prouvé.*
        #
        # Garde : `TestUnStoreInjoignableSortEnDeux`, éprouvé dans les deux
        # directions — un graphe injoignable rend 2, un désaccord réel rend
        # toujours 1.
        raise StoreInjoignableError(f"NebulaGraph {host}:{port} / {space} : {erreur}") from erreur
    if not joignable:
        # `init()` rend bien `False`, mais sur un SEUL cas : une
        # `SessionPoolConfig` invalide. Cette branche n'est donc pas morte, et
        # elle est gardée séparément.
        raise StoreInjoignableError(f"NebulaGraph {host}:{port} / {space} : connexion refusée")

    # LES NOMS LOCAUX ÉVITENT `set.add` ET `set.update`, ET CE N'EST PAS UN
    # DÉTAIL DE STYLE. Le garde de lecture seule
    # (`test_verification_des_ancrages.TestLaSondeEstEnLectureSeule`) interdit
    # tout appel nommé `add`, `upsert`, `modify`, `delete` ou `update` dans ce
    # fichier — ce sont les verbes d'écriture de ChromaDB. Un `trouves.add(...)`
    # sur un ensemble Python le ferait rougir sur un appel légitime, et un garde
    # qui rougit toujours est retiré, donc désarmé. On construit donc par
    # compréhension et on fusionne par `|=`.
    trouves: set[str] = set()
    for debut in range(0, len(identifiants), _LOT_NEBULA):
        lot = identifiants[debut : debut + _LOT_NEBULA]
        liste = ",".join(f'"{x}"' for x in lot)
        try:
            resultat = pool.execute(f"FETCH PROP ON * {liste} YIELD id(vertex) AS vid")
        except Exception as erreur:
            # MÊME MOTIF QUE CI-DESSUS, et le même défaut : un graphe qui meurt
            # EN COURS de lecture faisait sortir en 1 sur un jeu sain. Le pool
            # lève ici `NoValidSessionException` — qui dérive d'`Exception`, pas
            # de `RuntimeError` — et les erreurs de transport du client thrift.
            raise StoreInjoignableError(f"NebulaGraph {host}:{port} : {erreur}") from erreur
        if not resultat.is_succeeded():
            raise StoreInjoignableError(f"nGQL refusé : {resultat.error_msg()}")
        trouves |= {
            resultat.row_values(rang)[0].as_string()
            for rang in range(resultat.row_size())
        }
    return trouves


# ─── Le verdict ──────────────────────────────────────────────────────────────


def verifier(
    questions: list[dict[str, Any]],
    carte_chroma: dict[str, str],
    dans_le_graphe: set[str],
) -> dict[str, Any]:
    """Confronte un jeu aux deux stores et rend son bilan.

    QUATRE DÉSACCORDS SONT CHERCHÉS, et chacun ferme une façon de mesurer zéro
    sans le savoir :

    - **absent du graphe** : la reconstruction de contexte ne trouvera rien ;
    - **absent de ChromaDB** : c'est celui qui compte pour le RAPPEL, car
      `retrieved_element_ids` sort des métadonnées de l'index vectoriel. Un
      ancrage présent au graphe et absent de l'index est le pire des deux
      mondes : il a l'air bon et ne peut jamais être trouvé ;
    - **document discordant** : l'ancrage existe mais ne vit pas dans le
      document que le jeu lui prête, donc `rappel_documents` mesure autre chose
      que ce qu'il annonce ;
    - **strate incohérente** : une question à réponse sans aucun ancrage, ou
      une question d'abstention qui en porte un. La première rend `None` partout
      et disparaît des moyennes en silence — une strate vide qui se tait
      ressemble à une strate saine.
    """
    absents_graphe: list[tuple[str, str]] = []
    absents_chroma: list[tuple[str, str]] = []
    documents_discordants: list[tuple[str, str, str, str]] = []
    strates_incoherentes: list[str] = []
    ancrages_vus: set[str] = set()

    for question in questions:
        identifiant = str(question.get("id", "?"))
        _, ancrages = ancrages_de(question)
        ancrages_vus |= set(ancrages)

        if sans_reponse(question):
            if ancrages:
                strates_incoherentes.append(
                    f"{identifiant} : abstention attendue, mais "
                    f"{len(ancrages)} ancrage(s) déclaré(s)"
                )
        elif not ancrages:
            strates_incoherentes.append(
                f"{identifiant} : question à réponse sans aucun ancrage — elle ne mesure rien"
            )

        attendu = (question.get("_origine") or {}).get("source_path") or question.get("source_path")
        for ancrage in ancrages:
            if ancrage not in dans_le_graphe:
                absents_graphe.append((identifiant, ancrage))
            if ancrage not in carte_chroma:
                absents_chroma.append((identifiant, ancrage))
            elif attendu and carte_chroma[ancrage] != attendu:
                documents_discordants.append(
                    (identifiant, ancrage, str(attendu), carte_chroma[ancrage])
                )

    return {
        "questions": len(questions),
        "ancrages_distincts": len(ancrages_vus),
        "dans_le_graphe": len(ancrages_vus & dans_le_graphe),
        "dans_chromadb": len(ancrages_vus & set(carte_chroma)),
        "absents_du_graphe": absents_graphe,
        "absents_de_chromadb": absents_chroma,
        "documents_discordants": documents_discordants,
        "strates_incoherentes": strates_incoherentes,
    }


def desaccords(bilan: dict[str, Any]) -> int:
    return (
        len(bilan["absents_du_graphe"])
        + len(bilan["absents_de_chromadb"])
        + len(bilan["documents_discordants"])
        + len(bilan["strates_incoherentes"])
    )


def afficher(nom: str, bilan: dict[str, Any]) -> None:
    total = desaccords(bilan)
    marque = "OK " if total == 0 else "NON"
    print(f"\n[{marque}] {nom}")
    print(f"     questions                     {bilan['questions']}")
    print(f"     ancrages distincts            {bilan['ancrages_distincts']}")
    print(
        f"     existant dans le graphe       {bilan['dans_le_graphe']}"
        f" / {bilan['ancrages_distincts']}"
    )
    print(
        f"     existant dans ChromaDB        {bilan['dans_chromadb']}"
        f" / {bilan['ancrages_distincts']}"
    )
    for question, ancrage in bilan["absents_du_graphe"][:20]:
        print(f"     ABSENT DU GRAPHE      {question}  {ancrage}")
    for question, ancrage in bilan["absents_de_chromadb"][:20]:
        print(f"     ABSENT DE CHROMADB    {question}  {ancrage}")
    for question, ancrage, attendu, trouve in bilan["documents_discordants"][:20]:
        print(f"     DOCUMENT DISCORDANT   {question}  {ancrage}")
        print(f"                             déclaré : {attendu}")
        print(f"                             indexé  : {trouve}")
    for ligne in bilan["strates_incoherentes"][:20]:
        print(f"     STRATE INCOHÉRENTE    {ligne}")
    if total > len(bilan["absents_du_graphe"][:20]) + 60:
        print(f"     … {total} désaccords au total")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("jeux", nargs="*", type=Path, help="Jeux de questions à vérifier")
    env = os.environ.get
    parser.add_argument("--chroma-host", default=env("CHROMA_HOST", "chromadb"))
    parser.add_argument("--chroma-port", type=int, default=int(env("CHROMA_PORT", "8000")))
    parser.add_argument("--chroma-collection", default=env("CHROMA_COLLECTION", "rag_documents"))
    parser.add_argument("--nebula-host", default=env("NEBULA_HOST", "graphd"))
    parser.add_argument("--nebula-port", type=int, default=int(env("NEBULA_PORT", "9669")))
    parser.add_argument("--nebula-user", default=env("NEBULA_USER", "root"))
    parser.add_argument("--nebula-password", default=env("NEBULA_PASSWORD", "nebula"))
    parser.add_argument("--nebula-space", default=env("NEBULA_SPACE", "rag_space"))
    parser.add_argument("--json", type=Path, help="Écrit le bilan, pour qu'un rapport le cite")
    args = parser.parse_args()

    jeux = args.jeux or [
        ROOT / "tests" / "fixtures" / "golden_qa_generated.yaml",
        ROOT / "tests" / "fixtures" / "jeu_de_questions_pipeline.yaml",
    ]

    try:
        charges = {chemin: charger_jeu(chemin) for chemin in jeux}
        tous = sorted({a for qs in charges.values() for q in qs for a in ancrages_de(q)[1]})
        carte, metadonnees, chunks = lire_chroma(
            args.chroma_host, args.chroma_port, args.chroma_collection
        )
        dans_le_graphe = lire_nebula(
            args.nebula_host,
            args.nebula_port,
            args.nebula_user,
            args.nebula_password,
            args.nebula_space,
            tous,
        )
    except StoreInjoignableError as erreur:
        print(f"RIEN N'EST PROUVÉ — {erreur}", file=sys.stderr)
        return 2
    except OSError as erreur:
        print(f"RIEN N'EST PROUVÉ — {erreur}", file=sys.stderr)
        return 2

    print(f"ChromaDB  {args.chroma_host}:{args.chroma_port}/{args.chroma_collection}")
    print(f"          {chunks} chunks, {len(carte)} element_id distincts")
    print(f"          estampille du modèle : {metadonnees.get('embedding_model') or 'ABSENTE'}")
    print(f"NebulaGraph {args.nebula_host}:{args.nebula_port}/{args.nebula_space}")

    bilans = {
        str(chemin.relative_to(ROOT) if chemin.is_relative_to(ROOT) else chemin): verifier(
            questions, carte, dans_le_graphe
        )
        for chemin, questions in charges.items()
    }
    for nom, bilan in bilans.items():
        afficher(nom, bilan)

    total = sum(desaccords(bilan) for bilan in bilans.values())
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(
            json.dumps(
                {
                    "chromadb": {
                        "hote": f"{args.chroma_host}:{args.chroma_port}",
                        "collection": args.chroma_collection,
                        "chunks": chunks,
                        "element_id_distincts": len(carte),
                        "estampille_embedding": metadonnees.get("embedding_model"),
                    },
                    "nebulagraph": {
                        "hote": f"{args.nebula_host}:{args.nebula_port}",
                        "espace": args.nebula_space,
                    },
                    "jeux": bilans,
                    "desaccords": total,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    print(f"\n{total} désaccord(s).")
    return 1 if total else 0


if __name__ == "__main__":
    sys.exit(main())
