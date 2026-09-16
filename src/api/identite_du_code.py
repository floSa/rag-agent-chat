"""QUEL CODE TOURNE : l'identité que le BUILD a gravée dans l'image, ou rien.

POURQUOI CE MODULE EXISTE, ET CE QU'IL A DÉJÀ COÛTÉ. Pendant douze lots, l'agent
en service a exécuté du code antérieur et aucun garde livré ne tournait ; personne
ne s'en est aperçu parce que rien ne permettait de répondre à « quel code
tourne ? ». Site canonique : `documentation/registre_du_chantier.md` §4.42. La
borne que ce module pose est une PROPRIÉTÉ : *l'image porte l'identité du code
qu'elle contient, et `/health` la publie ou déclare qu'elle ne l'a pas.*

L'IDENTITÉ VIENT DU BUILD, JAMAIS D'UNE CONSTANTE DANS LE CODE. Une
`VERSION = "1.2.3"` écrite à la main est un chiffre qui dérive — ce dépôt en a
corrigé trois, dont un qui a été écrit FAUX par le commit qui prétendait le
rattraper. Le sha est donc relevé au moment où l'image se construit
(`ARG CODE_SHA` dans `Dockerfile.agent`, posé par la cible `image` du
`Makefile`), gravé en `ENV` — que ce module lit — et en `LABEL` — que
`docker image inspect` lit.

CE QUE CE MODULE NE DIT PAS, et c'est écrit ici plutôt que découvert plus tard :

- Il lit l'ENVIRONNEMENT du processus, pas le contenu de l'image. `env_file:`
  charge le `.env` à l'exécution et Docker laisse l'exécution l'emporter sur
  l'`ENV` de l'image : une variable `RAG_AGENT_CODE_SHA` posée dans le `.env`
  ferait publier une identité que le build n'a pas gravée. C'est pourquoi le
  `LABEL` existe EN PLUS de l'`ENV` — un label est figé au build et l'exécution
  ne peut pas le toucher. La procédure de retour arrière
  (`documentation/identite_du_code_servi.md`) fait croiser les deux, et un
  désaccord entre eux nomme précisément ce cas. Un garde tient l'exigence des
  deux dans `Dockerfile.agent`.
- Il ne dit rien des DÉPENDANCES de l'image. Deux images construites du même sha
  à deux mois d'écart n'ont pas les mêmes roues ; `construite_le` est là pour
  ça, et il ne remplace pas un verrou.

`None` VEUT DIRE « ON NE ME L'A PAS DIT », JAMAIS « C'EST À JOUR ». C'est la
forme de défaut que ce chantier a rencontrée trois fois — une absence rendue en
zéro, un catalogue vide mémorisé en « modèle absent », un `usage` vide effaçant
une mesure réelle. Une image construite sans ces arguments se déclare donc
ANONYME, et le contrat de `CodeServiHealth` REFUSE qu'elle passe pour
identifiée : l'invariant est tenu par pydantic, pas par la politesse des
appelants.
"""

import os
import re

from src.api.schemas import CodeServiHealth

# Le sha, et rien qui lui ressemble. TROISIÈME PIÈGE FERMÉ ICI : un mécanisme
# d'identité qui échoue à la construction ne doit pas produire une chaîne vide,
# un `HEAD` non résolu, un `unknown`, ni un sha abrégé — tous passeraient pour
# une identité auprès d'un lecteur pressé. Quarante hexadécimaux minuscules, ou
# l'image est anonyme.
_UN_SHA = re.compile(r"^[0-9a-f]{40}$")

# Les deux seuls mots que la déclaration d'arbre peut porter. Tout autre — vide,
# absent, `true`, un mot mal orthographié — laisse l'image ANONYME plutôt que de
# faire un pari : voir `_lire` pour le motif.
_ARBRE_PROPRE = "propre"
_ARBRE_SALE = "sale"

# Les trois variables d'environnement que `Dockerfile.agent` grave. Nommées ici
# et nulle part ailleurs dans le code : le garde
# `tests/unit/test_identite_du_code.py` les relit d'ici pour vérifier que le
# Dockerfile les porte, ce qui empêche le module et l'image de diverger.
VAR_SHA = "RAG_AGENT_CODE_SHA"
VAR_ARBRE = "RAG_AGENT_CODE_ARBRE"
VAR_CONSTRUITE_LE = "RAG_AGENT_CODE_CONSTRUITE_LE"

_ANONYME_SANS_SHA = (
    "aucune identité de code gravée dans cette image : elle a été construite sans "
    "`--build-arg CODE_SHA=...`, ou par un `docker build` qui ne passe pas par la "
    "cible `image` du Makefile. Rien ici ne dit quel code tourne."
)

_ANONYME_SHA_ILLISIBLE = (
    "une identité de code a été gravée mais elle n'est pas un sha de commit "
    "(attendu 40 caractères hexadécimaux minuscules) : le relevé a échoué à la "
    "construction, et publier ce qu'il a rendu nommerait un code qui n'existe pas."
)

_ANONYME_ARBRE_MUET = (
    "un sha de commit a été gravé, mais rien ne dit si l'arbre de construction "
    "était propre : le sha ne peut donc pas être confronté au dépôt. Le build "
    "doit graver `CODE_SHA` ET `CODE_ARBRE`, ou aucun des deux."
)

_ARBRE_SALE_AVERTISSEMENT = (
    "ce sha NE DÉCRIT PAS le code de cette image : l'arbre de construction "
    "portait des modifications non commitées. Le commit nommé ne contient pas ce "
    "qui tourne — ne pas comparer une campagne à ce sha."
)


def _lire(nom: str) -> str | None:
    """La variable, dépouillée, ou `None` si elle est absente ou vide.

    La chaîne vide est ramenée à `None` À DESSEIN : `ARG CODE_SHA=` sans valeur
    par défaut produit une variable PRÉSENTE et VIDE dans l'image — un
    `os.environ.get` nu la rendrait `""`, et une chaîne vide qui se propage
    jusqu'au contrat est exactement le « zéro pour une absence » que ce module
    existe pour interdire.
    """
    valeur = os.environ.get(nom, "").strip()
    return valeur or None


def identite_du_code() -> CodeServiHealth:
    """Ce que le build a gravé, relu À CHAQUE APPEL.

    RELU, ET NON MÉMORISÉ AU CHARGEMENT DU MODULE : une constante de module
    figerait la valeur à l'import, ce qui rendrait la lecture INÉPROUVABLE — un
    test ne pourrait plus poser les trois cas sans recharger l'interpréteur. Le
    coût est de trois lectures de `os.environ` par battement du healthcheck, soit
    aucune entrée-sortie : c'est pourquoi cet appel est HORS du plafond des
    sondes de `/health`, au même titre que `sessions.stats()`.

    TROIS POSITIONS, ET ELLES RÉPONDENT À UNE SEULE QUESTION — *puis-je me fier à
    `sha` pour dire quel code tourne ?*

    - `identifie` : oui. Un sha de commit, gravé au build, dans un arbre propre.
    - `arbre_sale` : non, et on sait pourquoi. Le sha est là, mais l'arbre de
      construction portait des modifications non commitées : **le commit nommé ne
      contient pas ce qui tourne**. Publier ce sha sans le dire serait pire que
      l'anonymat, parce qu'il serait CRU.
    - `anonyme` : non, et rien n'est publié. Trois chemins y mènent, et ils sont
      distingués par l'avertissement : rien de gravé, un sha illisible, ou un sha
      dont on ne sait pas s'il décrit l'arbre.

    Le troisième chemin — `CODE_SHA` sans `CODE_ARBRE` — est le seul qui pourrait
    surprendre, et il est délibéré : un sha dont la fiabilité est INCONNUE n'est
    pas une identité, c'est une supposition. Le rendre `identifie` supposerait la
    propreté ; le rendre `arbre_sale` affirmerait la saleté. Les deux
    affirmeraient un fait que le build n'a pas donné.
    """
    sha = _lire(VAR_SHA)
    arbre = _lire(VAR_ARBRE)
    construite_le = _lire(VAR_CONSTRUITE_LE)

    if sha is None:
        return CodeServiHealth(
            etat="anonyme", construite_le=construite_le, avertissement=_ANONYME_SANS_SHA
        )
    if not _UN_SHA.match(sha):
        return CodeServiHealth(
            etat="anonyme", construite_le=construite_le, avertissement=_ANONYME_SHA_ILLISIBLE
        )
    if arbre == _ARBRE_PROPRE:
        return CodeServiHealth(etat="identifie", sha=sha, construite_le=construite_le)
    if arbre == _ARBRE_SALE:
        return CodeServiHealth(
            etat="arbre_sale",
            sha=sha,
            construite_le=construite_le,
            avertissement=_ARBRE_SALE_AVERTISSEMENT,
        )
    return CodeServiHealth(
        etat="anonyme", construite_le=construite_le, avertissement=_ANONYME_ARBRE_MUET
    )
