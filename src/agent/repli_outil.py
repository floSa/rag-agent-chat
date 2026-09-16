"""Le second rideau : reconnaître un appel d'outil ÉCRIT DANS LA PROSE.

L'appel d'outil natif fait foi — il est structuré, donc sans ambiguïté. Quand il
n'arrive pas, ce module est le seul signal restant : le modèle a écrit l'appel
dans son texte, et ce texte est déjà parti à l'écran.

POURQUOI UN MODULE, ET POURQUOI UNE SEULE FONCTION
--------------------------------------------------

Avant ce lot, la reconnaissance et le nettoyage étaient DEUX expressions
régulières, à quinze lignes l'une de l'autre dans `graph.py`. Écrites identiques,
elles pouvaient diverger sans que rien ne rougisse — et une divergence n'est pas
un détail de forme : celle qui reconnaît sans nettoyer affiche la syntaxe à
l'utilisateur, celle qui nettoie sans reconnaître efface la demande sans jamais
la servir. Les deux effets sont indépendants et tombent séparément.

`lire_et_retirer` rend les deux résultats d'un seul passage sur un seul motif.
Ce n'est plus « deux motifs qu'un garde surveille » : il n'y en a plus qu'un, et
la divergence n'est plus représentable. Le garde qui reste
(`tests/unit/test_coherence_depot.py`) tient l'unicité du site, pas l'accord de
deux copies.

Ce module ne dépend ni de LangGraph, ni de `llm.py`, ni du moteur d'inférence :
`scripts/banc_vllm.py` l'importe sans tirer le graphe entier, et mesure donc
le rideau que la production sert, au lieu d'une copie recollée pour l'occasion.

LES FORMES RECONNUES, ET POURQUOI CELLES-LÀ
-------------------------------------------

Chacune a été relevée sur un des deux moteurs du poste le 15 septembre 2026,
entre 22:35 et 22:50 UTC, en lecture, une requête à la fois, sans déclarer
l'outil nativement :

    search_vectors("contrat cadre")                 positionnelle    ollama
    search_vectors(query="…")                       nommée           vllm
    search_vectors(sous_question="…")               nommée, _        vllm
    search_vectors(sous-question="…")               nommée, -        ollama

Le motif d'origine n'acceptait que la PREMIÈRE — une parenthèse immédiatement
suivie d'un guillemet — et les deux moteurs écrivent les autres. C'est le défaut
que ce module ferme.

Le nom d'argument n'est pas comparé à une liste : `query`, `sous_question` et
`sous-question` sont trois noms pour la même place, et un modèle en inventera un
quatrième. Ce qui est exigé, c'est la FORME — un identifiant, un `=`, puis une
chaîne entre guillemets — parce que c'est elle qui distingue un appel d'une
phrase.

CE QUI N'EST PAS RECONNU, ET C'EST VOULU
----------------------------------------

La parenthèse ET la chaîne entre guillemets sont toutes deux obligatoires. Sans
cette exigence, le rideau attrape ce qu'Ollama écrit quand il parle de l'outil
au lieu de l'appeler — « Je vais lancer une recherche complémentaire avec
l'outil `search_vectors`. » , mesuré deux essais sur deux — et l'agent part alors
en recherche sur une phrase qui n'a rien demandé. Un motif trop large ne rend pas
le rideau plus solide : il lui fait inventer des demandes.

Les guillemets ne sont pas appariés (`"…'` passe), et c'est le comportement
d'origine, conservé faute de l'avoir vu se produire : resserrer sur une forme
qu'aucun moteur n'a écrite serait deviner dans l'autre sens.
"""

from __future__ import annotations

import json
import re

# L'enrobage que vLLM pose autour de l'appel (mesuré). Il est OPTIONNEL des deux
# côtés et ne se retire que s'il entoure un appel reconnu : une balise seule ne
# déclenche rien, et l'appel sans balise se lit aussi bien. Le retirer avec
# l'appel évite de laisser à l'écran une ouvrante et une fermante vides, qui
# sont la même fuite en plus discret.
_ENROBAGE_OUVRANT = r"(?:<execute_tool>\s*)?"
_ENROBAGE_FERMANT = r"(?:\s*</execute_tool>)?"

# LE SITE CANONIQUE. Il n'y en a qu'un dans tout le dépôt, et
# `tests/unit/test_coherence_depot.py` rougit si un second apparaît.
APPEL_DANS_LA_PROSE = re.compile(
    _ENROBAGE_OUVRANT
    # Le nom de l'outil, puis sa parenthèse — obligatoire.
    + r"search_vectors\(\s*"
    # Le nom d'argument est optionnel : la forme positionnelle n'en a pas.
    # `[\w-]` couvre `query`, `sous_question` et `sous-question` sans les nommer.
    + r"(?:[A-Za-z_][\w-]*\s*=\s*)?"
    # La sous-question, entre guillemets — obligatoire elle aussi.
    + r"[\"'](.+?)[\"']"
    + r"\s*\)"
    + _ENROBAGE_FERMANT
)


# LA SECONDE FORME : L'APPEL QUI FUIT EN SENTINELLES.
#
# Quand l'analyseur d'outils est mal choisi CÔTÉ SERVEUR, l'appel n'est pas
# structuré du tout : il part dans le contenu, encadré de sentinelles, et il
# arrive donc à l'écran de l'utilisateur. C'est la même fuite que celle
# au-dessus, dans une autre syntaxe, et elle se ferme au même endroit — un
# second site voudrait dire deux motifs libres de diverger, ce que ce module
# existe précisément pour empêcher.
#
# CETTE FORME EST CRUE SUR PAROLE, et c'est la seule du module qui le soit :
# elle nous vient de l'équipe voisine, et la reproduire demanderait de poser un
# `--reasoning-parser` sur un serveur qui ne nous appartient pas. Les quatre
# formes du motif au-dessus, elles, ont été relevées sur les moteurs du poste.
#
# Le nom d'outil n'est pas figé dans le motif mais VÉRIFIÉ à la lecture : un
# bloc qui fuit est du bruit d'écran quel que soit l'outil qu'il nomme, donc il
# se retire toujours ; seul `search_vectors` a une place où servir la
# sous-question, donc lui seul en rend une.
_NOM_DE_L_OUTIL_SERVI = "search_vectors"
APPEL_EN_SENTINELLES = re.compile(
    r"<\|tool_call>\s*call:\s*([A-Za-z_]\w*)\s*(\{.*?\})?\s*<tool_call\|>",
    re.S,
)


def _query_des_sentinelles(trouve: re.Match[str]) -> str | None:
    """Rend la sous-question portée par un bloc de sentinelles, None sinon.

    Le bloc se retire dans tous les cas — c'est l'appelant qui s'en charge, avec
    le MÊME objet de motif. Cette fonction ne décide que de ce qu'on en tire.
    """
    if trouve.group(1) != _NOM_DE_L_OUTIL_SERVI:
        return None
    try:
        arguments = json.loads(trouve.group(2) or "{}")
    except json.JSONDecodeError:
        # `{}` vide, tronqué, ou brouillé par la fuite elle-même. Le bloc part
        # quand même de l'écran : une fuite illisible reste une fuite.
        return None
    if not isinstance(arguments, dict):
        return None
    query = arguments.get("query")
    return query.strip() if isinstance(query, str) and query.strip() else None


def lire_et_retirer(reponse: str) -> tuple[str | None, str]:
    """Rend la sous-question demandée dans la prose, et le texte sans l'appel.

    Les deux sorties viennent du MÊME motif, en un passage : c'est ce qui rend
    impossible de reconnaître une forme sans la retirer, ou l'inverse.

    - `(None, texte)` quand aucun appel n'est écrit — le texte revient intact,
      à l'espacement de bord près.
    - `(sous_question, texte_sans_appel)` sinon. Le PREMIER appel décide, comme
      avant ce lot : un modèle qui en écrit deux a déjà perdu le fil, et servir
      le second serait un choix que rien ne mesure.
    """
    trouve = APPEL_DANS_LA_PROSE.search(reponse)
    sous_question = trouve.group(1) if trouve else None
    # Le nettoyage passe même sans correspondance : `sub` rend alors le texte
    # tel quel, et le `strip` reste celui d'avant ce lot.
    reponse = APPEL_DANS_LA_PROSE.sub("", reponse)

    # La seconde forme, lue et retirée par le MÊME objet de motif — la
    # propriété qui fait ce module tient forme par forme, pas globalement.
    # La prose garde la priorité : c'est elle qui a quatre relevés derrière
    # elle, les sentinelles n'en ont aucun.
    sentinelles = APPEL_EN_SENTINELLES.search(reponse)
    if sentinelles is not None:
        if sous_question is None:
            sous_question = _query_des_sentinelles(sentinelles)
        reponse = APPEL_EN_SENTINELLES.sub("", reponse)

    return sous_question, reponse.strip()
