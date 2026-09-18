"""Le lecteur de flux : UN site, et il lit une FORME, pas un moteur.

POURQUOI CE MODULE EXISTE
-------------------------

`generate_stream` lisait une ligne de flux en trois gestes collés au corps de la
boucle : `json.loads(ligne)`, `data["message"]["content"]`, `data["done"]`. Les
trois sont du NDJSON de l'ancien moteur, et les trois cassent sur le SSE d'un
serveur OpenAI-compatible. Le premier casse BRUYAMMENT — `json.loads` lève sur
`data: {…}` — et c'est le seul des trois défauts qui se voie.

Le second est silencieux, et c'est lui qui décide : ce serveur FRAGMENTE l'appel
d'outil sur plusieurs événements, dont AUCUN ne porte l'appel entier. Lu ligne
par ligne, chaque fragment rend `None`, le rappel ne part jamais, et la recherche
supplémentaire disparaît sans une erreur, sans un log, avec un HTTP 200 et des
tokens qui s'affichent normalement.

CE QUE LE LOT 28 RETIRE ICI, ET CE QU'IL NE RETIRE PAS
-------------------------------------------------------

Ce module savait lire DEUX dialectes. Le lot 28 retire le support de l'ancien
moteur : ce qui part est la lecture de SA forme — `message` à la racine, la fin
de flux par `done: true`, les décomptes `prompt_eval_count`/`eval_count` qu'il
portait avec elle, l'index d'appel d'outil rangé sous `function`, et les
arguments rendus comme un OBJET d'un seul bloc.

Ce qui reste, et qui n'a jamais été à lui : l'enveloppe `data: `, la sentinelle
`[DONE]`, l'événement d'usage à `"choices": []`, et l'accumulation des
`tool_calls` fragmentés. Ce sont les quatre choses qui font ce lecteur, et elles
sont toutes du dialecte servi.

IL N'Y A PAS DE BRANCHE PAR MOTEUR, ET C'EST TOUJOURS LE POINT
---------------------------------------------------------------

Ce lecteur n'a ni réglage, ni drapeau, ni nom de serveur, et il n'en avait déjà
pas avant ce lot. Il lit la FORME de ce qu'on lui donne :

- l'enveloppe : un `data: ` en tête est retiré s'il est là ;
- la charge : `choices[0].delta` en flux, `choices[0].message` hors flux. Une
  seule fonction, `charge_du_corps`, et tout ce qui suit travaille sur son
  résultat — `llm._contenu_message` compris.

C'est ce qui rend la divergence non REPRÉSENTABLE, au lieu de la rendre
surveillée.

CE QUE LE LECTEUR NE FAIT PAS
-----------------------------

Il ne juge pas ce qu'est une sous-question valable : `extract_tool_query` reste
le seul juge, et le lecteur lui rend un `message` de la forme qu'il attend. La
règle de lecture des arguments — objet, ou chaîne JSON — n'est donc PAS
réécrite ici. Il n'y en a toujours qu'une dans le dépôt.

Il ne bascule rien : la charge utile envoyée au serveur n'est pas de son
ressort. Ce ressort-là est `src/agent/dialecte_llm.py`.

Il ne retire rien du texte. Un appel d'outil qui a FUI dans le contenu — la
forme `<|tool_call>…<tool_call|>` d'un analyseur mal choisi côté serveur —
traverse ce lecteur comme du texte, parce qu'un flux se cède token par token et
qu'une sentinelle à cheval sur deux tokens ne peut pas être retirée sans
retenir tout le flux. Le retrait a UN site, `src/agent/repli_outil.py`, qui
travaille sur la réponse assemblée. Voir `tests/unit/test_lecteur_de_flux.py`,
section « la fuite dans le texte », qui mesure ce que ce lecteur en fait.

LA FORME, RELEVÉE SUR `vllm-central` LE 16 SEPTEMBRE 2026
----------------------------------------------------------

Entre 04:00 et 04:04 UTC, en lecture, six requêtes, prompts tous distincts
(un prompt répété est servi par le cache de préfixe et ne mesure plus rien) :

    data: {"choices":[{"delta":{"content":" grâce"}}]}
    (ligne vide)
    data: {"choices":[],"usage":{"prompt_tokens":34,"completion_tokens":22}}
    data: [DONE]

L'appel d'outil, lui, arrive en QUATRE événements, et son `index` est au niveau
de l'APPEL :

    {"id":"…","type":"function","index":0,"function":{"name":"search_vectors"}}
    {"index":0,"function":{"arguments":"{\"query\": \""}}
    {"index":0,"function":{"arguments":"régime indemnitaire …"}}
    {"index":0,"function":{"arguments":"\"}"}}

L'index est INCRÉMENTÉ sur deux appels (0 puis 1, mesuré), ce que la lecture
ligne à ligne ne savait pas rassembler.

LES DEUX PIÈGES QUI N'ÉTAIENT PAS DANS LE BANC
----------------------------------------------

1. L'événement d'usage porte `"choices": []` — une liste VIDE. Un lecteur qui
   écrit `data["choices"][0]` lève `IndexError` sur le seul événement qui porte
   les décomptes. `charge_du_corps` rend `{}` sur une liste vide.

2. Les décomptes n'existent en streaming QUE si la requête a demandé
   `stream_options: {"include_usage": true}` (mesuré : présents avec, absents
   sans). Ce lecteur les lit quand ils sont là et déclare leur absence sinon —
   il ne les invente pas, et il ne modifie pas la charge utile pour les obtenir :
   cela appartient à `dialecte_llm`.
"""

from __future__ import annotations

import json
from typing import Any, NamedTuple

# L'enveloppe SSE. Elle est retirée SI ELLE EST LÀ plutôt qu'exigée : ce lecteur
# décrit une forme, et une ligne qui ne la porte pas le traverse sans effet.
# C'est ce qui lui évite de savoir à qui il parle.
_PREFIXE_SSE = "data: "

# La sentinelle de fin du SSE. Elle n'est pas du JSON — c'est exactement ce qui
# faisait lever `json.loads` — et elle doit donc être reconnue AVANT lui.
_SENTINELLE_FIN = "[DONE]"


def charge_du_corps(data: dict[str, Any]) -> dict[str, Any]:
    """Rend l'objet qui porte `content` et `tool_calls`, `{}` si absent.

    LE SEUL SITE DU DÉPÔT QUI CONNAISSE LA FORME EN ENTRÉE. Tout ce qui est en
    aval travaille sur son résultat — `llm._contenu_message` compris — et son
    symétrique en SORTIE est `dialecte_llm`. Il n'y en a pas de troisième.

    DEUX PLACES, ET LA SECONDE EST UNE CORRECTION DU LOT 25. Ce module ne
    servait que le FLUX, où le serveur écrit `choices[0].delta` ; mais `llm.py`
    a aussi DEUX appels non-flux — la réécriture de question et la traduction —
    et là il écrit `choices[0].message`. Leur lecteur ne connaissait alors que
    la forme de l'ancien moteur : il rendait `""` sur une réponse PARFAITEMENT
    VALIDE, et les deux appels tombaient sur leur repli — « question d'origine
    conservée », « recherche monolingue » — en HTTP 200, sans erreur, avec un
    journal qui accuse le serveur. Une recherche dégradée dans les deux langues,
    pour une réponse que le serveur avait bien donnée. (`mesuré` le 16 septembre
    2026 à 14:12 UTC : le corps non-flux de `vllm-central` porte
    `choices[0].message.content`.)

    `delta` est cherché AVANT `message`, et les deux sont cherchés dans le MÊME
    objet `choices[0]`. En flux le serveur n'émet que `delta` (mesuré), donc
    l'ordre ne départage rien aujourd'hui ; il est écrit ainsi pour qu'un corps
    qui porterait les deux rende le FRAGMENT et non la réponse entière — céder
    la réponse assemblée au milieu d'un flux la ferait s'afficher deux fois.
    """
    choix = data.get("choices")
    # `choices: []` N'EST PAS une anomalie : c'est la forme exacte de
    # l'événement d'usage, celui qui porte les décomptes. Écrire
    # `choices[0]` lèverait `IndexError` précisément là. (mesuré 16/09)
    if isinstance(choix, list) and choix and isinstance(choix[0], dict):
        for cle in ("delta", "message"):
            charge = choix[0].get(cle)
            if isinstance(charge, dict):
                return charge
    return {}


class Decomptes(NamedTuple):
    """Les décomptes du serveur, ou leur absence DÉCLARÉE.

    `None` ne veut pas dire zéro : il veut dire « le serveur ne l'a pas dit ».
    La distinction compte — `mesure_prompt_exploitable` en dépend, et un zéro
    inventé ferait passer pour mesurée une fenêtre que personne n'a mesurée.
    """

    # LES DEUX NOMS SONT HÉRITÉS DE L'ANCIEN MOTEUR, ET ILS RESTENT — lot 28.
    # Ils ne le NOMMENT pas, et les renommer toucherait `usage.py`, `llm.py`,
    # le schéma publié et la base d'observation déjà écrite, pour un gain
    # purement esthétique sur un champ interne. Ce que ce lot retire est le
    # SUPPORT d'un moteur, pas le vocabulaire de ses compteurs.
    prompt_eval_count: int | None = None
    eval_count: int | None = None


class LecteurDeFlux:
    """Accumule un flux ligne à ligne, quel que soit le dialecte qui l'émet.

    L'objet est à usage unique : un flux, un lecteur. Il ne fait aucune entrée
    ni sortie — on lui donne des chaînes, il rend du texte — donc il se teste
    sans réseau, sans serveur et sans LangGraph, et `scripts/` peut l'importer
    pour mesurer le lecteur QUE LA PRODUCTION SERT, au lieu d'une copie.
    """

    def __init__(self) -> None:
        # index de l'appel → {"name": …, "arguments": …}. Un dict et non une
        # liste : rien ne garantit que les index arrivent en ordre, ni qu'ils
        # commencent à zéro.
        self._fragments: dict[Any, dict[str, Any]] = {}
        # L'ordre d'APPARITION des index, qui est celui dans lequel le modèle a
        # demandé ses appels. Trier sur l'index supposerait qu'ils sont
        # comparables entre eux ; la position de repli, elle, ne l'est pas
        # forcément avec un entier.
        #
        # CETTE LISTE EST DÉFENSIVE et elle est dite telle : les deux moteurs du
        # poste émettent leurs index dans l'ordre croissant (mesuré sur les
        # deux, 0 puis 1), donc un `sorted()` rendrait aujourd'hui exactement la
        # même chose. Ce qu'elle évite n'est pas une erreur visible : c'est que
        # l'agent parte chercher L'AUTRE sous-question que celle demandée en
        # premier, sans que rien ne le signale.
        # Tenue par `test_l_ordre_d_apparition_prime_sur_l_ordre_des_index`.
        self._ordre: list[Any] = []
        self.decomptes = Decomptes()
        # Passe à True sur la sentinelle `[DONE]`. L'appelant s'en sert pour
        # sortir de sa boucle, exactement comme le `break` d'avant. C'est
        # désormais le SEUL signal de fin : la fin par `done: true` était celle
        # de l'ancien moteur et part avec lui (lot 28).
        self.termine = False

    def lire(self, ligne: str) -> str:
        """Lit une ligne et rend le texte à céder, "" s'il n'y en a pas.

        Ce qui est cédé est cédé IMMÉDIATEMENT — c'est un flux, et retenir un
        token pour voir ce qui suit rendrait l'écran muet. Ce qui est ACCUMULÉ,
        à l'inverse, n'est jugé qu'à la fin : voir `message_outils`.

        `json.loads` reste SANS `try`, et c'est délibéré. Une ligne qui n'est ni
        vide, ni une sentinelle, ni du JSON est un dialecte que nous ne
        connaissons pas, et le seul service à rendre est de le dire fort. C'est
        ce bruit-là qui a permis au banc de mesurer le défaut au lieu de le
        subir ; l'absorber rendrait ce lecteur silencieux sur sa propre panne.
        """
        charge = ligne.strip()
        if not charge:
            # Le SSE sépare ses événements par une ligne vide.
            return ""
        if charge.startswith(_PREFIXE_SSE):
            charge = charge[len(_PREFIXE_SSE) :].strip()
        if charge == _SENTINELLE_FIN:
            self.termine = True
            return ""

        data = json.loads(charge)
        if not isinstance(data, dict):
            # Du JSON valide qui n'est pas un objet : `[]`, `"texte"`, `null`.
            # Nommer la forme acceptée plutôt que laisser `.get` lever, comme
            # `_contenu_message` le fait déjà pour le non-streaming.
            return ""
        if data.get("error"):
            # Le serveur dit son refus DANS le flux, et un flux qui continue sur
            # une erreur rend une réponse tronquée qu'on croirait complète.
            raise RuntimeError(f"moteur LLM : {data['error']}")

        self._lire_decomptes(data)
        charge_utile = charge_du_corps(data)
        self._accumuler(charge_utile.get("tool_calls"))

        contenu = charge_utile.get("content")
        return contenu if isinstance(contenu, str) else ""

    def message_outils(self) -> dict[str, Any]:
        """Rend les appels accumulés sous la forme qu'`extract_tool_query` attend.

        C'est ici, et seulement ici, que la décision devient possible : un
        fragment d'arguments pris seul n'est pas du JSON valide — `{"query": "`
        ne l'est pas — donc le juger à chaque ligne rend `None` à chaque ligne.
        Rendu à la fin, l'objet reconstruit porte l'appel entier, et le juge le
        reçoit sous la forme qu'il attendait déjà avant ce lecteur.
        """
        return {
            "tool_calls": [
                {
                    "function": {
                        "name": self._fragments[cle]["name"],
                        "arguments": self._fragments[cle]["arguments"],
                    }
                }
                for cle in self._ordre
            ]
        }

    # ─── ce qui suit n'est appelé que par `lire` ─────────────────────────────

    def _lire_decomptes(self, data: dict[str, Any]) -> None:
        """Les décomptes du serveur, quand l'événement qui les porte arrive.

        UNE SEULE PLACE DEPUIS LE LOT 28 : `usage`, sur l'événement à
        `"choices": []`. La branche qui lisait `prompt_eval_count` et
        `eval_count` sur un `done: true` était celle de l'ancien moteur et part
        avec son support.

        CE QUE `_renseigner` GARDE DE PRÉCIEUX, MÊME À UNE SEULE BRANCHE : il
        est appelé une fois PAR événement d'usage, et il ne remplace que ce
        qu'on lui renseigne. Un événement qui porterait `prompt_tokens` sans
        `completion_tokens` n'effacerait donc pas un compte déjà acquis.

        ET LA RÈGLE « LE DERNIER RENSEIGNÉ GAGNE » RESTE EXERCÉE, ce qui n'est
        pas une précaution : `vllm-central` accepte `stream_options:
        {"include_usage": true, "continuous_usage_stats": true}` et émet alors
        un `usage` CUMULATIF sur chaque événement (`mesuré` 16/09 07:49 UTC :
        42 événements, `completion_tokens` de 0 à 40). Garder le premier
        renseigné y figerait le compte à zéro token généré — c'est-à-dire
        précisément la mesure fausse que ce garde existe pour empêcher.
        `dialecte_llm` ne demande pas cette option (voir sa décision (c)), donc
        la production n'émet qu'un seul `usage` ; la règle tient le jour où on
        la demanderait.
        """
        usage = data.get("usage")
        if isinstance(usage, dict):
            # `isinstance` et non `usage is not None` : un `usage` qui n'est pas
            # un objet — `42`, une chaîne — ferait lever `.get` au milieu du
            # flux. Ligne DÉFENSIVE : le serveur du poste ne l'écrit pas ainsi.
            self._renseigner(usage.get("prompt_tokens"), usage.get("completion_tokens"))

    def _renseigner(self, prompt_eval_count: Any, eval_count: Any) -> None:
        """Écrit les décomptes SANS effacer ceux qu'un événement précédent a donnés.

        `None` en entrée veut dire « cet événement ne dit rien de ce champ » —
        ce qui n'est pas la même chose que « le serveur a dit qu'il ne sait
        pas », et surtout pas la même chose que zéro.
        """
        self.decomptes = Decomptes(
            prompt_eval_count=(
                self.decomptes.prompt_eval_count
                if prompt_eval_count is None
                else prompt_eval_count
            ),
            eval_count=(
                self.decomptes.eval_count if eval_count is None else eval_count
            ),
        )

    def _accumuler(self, appels: Any) -> None:
        """Range les fragments PAR index, sans rien décider."""
        if not isinstance(appels, list):
            return
        for position, appel in enumerate(appels):
            if not isinstance(appel, dict):
                continue
            fonction = appel.get("function")
            fonction = fonction if isinstance(fonction, dict) else {}

            # L'index vit au niveau de l'APPEL (mesuré le 16/09). La position
            # dans la liste ne sert que s'il manque : sans ce repli, deux appels
            # sans index se recouvriraient sous la même clé `None` et le second
            # écraserait le premier. La place sous `function` était celle de
            # l'ancien moteur et part avec son support (lot 28).
            cle = appel.get("index")
            if cle is None:
                cle = position

            fragment = self._fragments.get(cle)
            if fragment is None:
                fragment = {"name": None, "arguments": None}
                self._fragments[cle] = fragment
                self._ordre.append(cle)

            nom = fonction.get("name")
            if isinstance(nom, str) and nom:
                # Un seul événement porte le nom, et les suivants n'en ont pas :
                # ne l'écraser qu'avec un nom non vide.
                #
                # `and nom` EST DÉFENSIF, et c'est dit pour qu'un refactor ne le
                # prenne pas pour du bruit : le serveur OMET `name` dans les
                # fragments suivants (mesuré, capture `VLLM_OUTIL`), il ne le met
                # pas à `""`. Le poste n'exerce donc pas cette garde — mais
                # sans elle, un `""` reçu après le nom le ferait retomber à la
                # chaîne vide et `extract_tool_query` rendrait `None` : la
                # recherche disparaîtrait sans erreur ni log.
                # Tenu par `test_un_nom_vide_n_ecrase_pas_le_nom_acquis`.
                fragment["name"] = nom

            arguments = fonction.get("arguments")
            if isinstance(arguments, str):
                # UNE CHAÎNE SE CONCATÈNE, et c'est la règle qui fait tout ce
                # module : les morceaux ne sont pas du JSON pris séparément, et
                # « fusionner » n'a aucun sens sur du texte coupé au milieu
                # d'une clé.
                #
                # LA BRANCHE QUI SUIVAIT — un `arguments` OBJET, rendu d'un seul
                # bloc, qui REMPLAÇAIT l'acquis — était celle de l'ancien
                # moteur, et elle part avec son support (lot 28). Un objet reçu
                # ici est désormais IGNORÉ : le serveur n'en émet pas, et
                # inventer une règle de fusion pour une forme que personne
                # n'envoie serait du code que rien ne mesure.
                precedent = fragment["arguments"]
                acquis = precedent if isinstance(precedent, str) else ""
                fragment["arguments"] = acquis + arguments
