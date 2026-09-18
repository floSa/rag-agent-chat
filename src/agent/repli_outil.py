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

ET IL LA TIENT POUR LES DEUX FORMES DE CE MODULE, ce qui n'a pas toujours été
vrai. Le garde ne cherchait que la marque de la forme en prose : une copie du
motif EN SENTINELLES posée dans un second fichier laissait les 937 tests du
dépôt au vert, et la phrase ci-dessus dépassait donc ce qu'elle promettait —
deux audits de suite l'ont relevée. Le garde cherche désormais les deux
marques, et chacune a SON contrôle positif, parce qu'une marque qui trouve
n'est pas encore une marque qui discrimine.

Ce module ne dépend ni de LangGraph, ni de `llm.py`, ni du moteur d'inférence :
un outil de mesure peut l'importer sans tirer le graphe entier, et éprouver donc
le rideau que la production sert, au lieu d'une copie recollée pour l'occasion.

LES FORMES RECONNUES, ET POURQUOI CELLES-LÀ
-------------------------------------------

Chacune a été relevée sur un moteur du poste le 15 septembre 2026, entre 22:35
et 22:50 UTC, en lecture, une requête à la fois, sans déclarer l'outil
nativement. Deux moteurs étaient alors servis, et les quatre formes sont gardées
ensemble : c'est le MODÈLE qui les écrit, pas le serveur qui le sert, et
`gemma4:e4b` est le même poids des deux côtés.

    search_vectors("contrat cadre")                 positionnelle
    search_vectors(query="…")                       nommée
    search_vectors(sous_question="…")               nommée, _
    search_vectors(sous-question="…")               nommée, -

Le motif d'origine n'acceptait que la PREMIÈRE — une parenthèse immédiatement
suivie d'un guillemet — et le modèle écrit les autres. C'est le défaut que ce
module ferme.

Le nom d'argument n'est pas comparé à une liste : `query`, `sous_question` et
`sous-question` sont trois noms pour la même place, et un modèle en inventera un
quatrième. Ce qui est exigé, c'est la FORME — un identifiant, un `=`, puis une
chaîne entre guillemets — parce que c'est elle qui distingue un appel d'une
phrase.

CE QUI N'EST PAS RECONNU, ET C'EST VOULU
----------------------------------------

La parenthèse ET la chaîne entre guillemets sont toutes deux obligatoires. Sans
cette exigence, le rideau attrape ce que le modèle écrit quand il parle de l'outil
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
#
# CE QUE CE MOTIF PEUT EFFACER, ET CE QU'IL NE PEUT PAS. La question importe
# plus ici qu'ailleurs : un rideau qui efface du texte utile est PLUS GRAVE
# qu'un rideau qui laisse fuir, parce que la fuite se voit à l'écran et
# l'effacement non. `mesuré` le 16 septembre 2026 à 07:54 UTC :
#
#     prose ordinaire ..............................  0 caractère retiré
#     accolades JSON légitimes dans la réponse .....  0
#     sentinelle OUVRANTE seule, sans fermante .....  0
#     un paragraphe entre les deux sentinelles ......  0
#     deux fuites séparées par du texte utile ......  118, LE MILIEU CONSERVÉ
#     une fuite écrite sur trois lignes ............  retirée, sa query rendue
#
# La borne est donc : ne part que ce qui est encadré par les DEUX sentinelles
# littérales et ne contient, entre le nom d'outil et la fermante, qu'un bloc
# d'accolades et des espaces. Le `.*?` est non-glouton et `re.S` le fait
# franchir les retours à la ligne : rendre le premier glouton effacerait un
# paragraphe entier, retirer le second laisserait la fuite multiligne à
# l'écran ET perdrait sa sous-question. Les deux sont tenus par des scènes de
# `tests/unit/test_lecteur_de_flux.py`, section « LA BORNE DU RIDEAU ».
#
# LE CAS ACCEPTÉ, ÉCRIT PLUTÔT QUE SUBI : une réponse qui CITE cette syntaxe
# pour l'expliquer écrit exactement les mêmes caractères qu'une fuite, et le
# rideau la traite donc comme une fuite — l'exemple part de l'écran (57
# caractères, `mesuré`) et une recherche réelle part sur la sous-question
# citée. Nous l'acceptons : le risque exige les deux sentinelles littérales
# dans la même réponse, la conséquence est une recherche SUPPLÉMENTAIRE et non
# une réponse remplacée, et le fermer demanderait de deviner à quoi ressemble
# une vraie fuite — que personne ici n'a mesurée. C'est la devinette que ce
# module refuse déjà pour les guillemets non appariés. La scène
# `test_une_reponse_qui_cite_la_syntaxe_de_fuite_est_traitee_comme_une_fuite`
# fixe ce choix pour qu'il ne change pas en silence.
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
    # elle, les sentinelles n'en ont aucun. Cette priorité était écrite ici et
    # tenue par rien — aucune scène ne faisait apparaître les DEUX formes dans
    # le même texte, et l'inverser passait les 937 tests. Elle est désormais
    # tenue par
    # `test_la_prose_garde_la_priorite_sur_les_sentinelles_dans_le_meme_texte`.
    # Les deux blocs partent de l'écran dans les deux cas : ce qui se décide
    # ici est uniquement LAQUELLE des deux sous-questions est servie.
    sentinelles = APPEL_EN_SENTINELLES.search(reponse)
    if sentinelles is not None:
        if sous_question is None:
            sous_question = _query_des_sentinelles(sentinelles)
        reponse = APPEL_EN_SENTINELLES.sub("", reponse)

    return sous_question, reponse.strip()
