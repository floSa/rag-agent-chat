"""Le lecteur de flux : UN site qui lit les deux dialectes sans savoir lequel.

POURQUOI CE MODULE EXISTE
-------------------------

`generate_stream` lisait une ligne de flux en trois gestes collés au corps de la
boucle : `json.loads(ligne)`, `data["message"]["content"]`, `data["done"]`. Les
trois sont du NDJSON d'Ollama, et les trois cassent sur le SSE d'un serveur
OpenAI-compatible. Le premier casse BRUYAMMENT — `json.loads` lève sur
`data: {…}` — et c'est le seul des trois défauts qui se voit.

Le second est silencieux, et c'est lui qui décide : un serveur
OpenAI-compatible FRAGMENTE l'appel d'outil sur plusieurs événements, dont
AUCUN ne porte l'appel entier. Lu ligne par ligne, chaque fragment rend `None`,
le rappel ne part jamais, et la recherche supplémentaire disparaît sans une
erreur, sans un log, avec un HTTP 200 et des tokens qui s'affichent
normalement. Réparer le premier défaut sans réparer le second livre donc une
régression INVISIBLE — c'est pourquoi les deux sont dans le même lot, et dans
le même objet.

IL N'Y A PAS DE BRANCHE PAR MOTEUR, ET C'EST LE POINT
-----------------------------------------------------

La tentation est d'écrire « si vLLM … sinon Ollama ». Deux motifs qui doivent
s'accorder finissent par diverger, et une divergence ici ne se voit pas : elle
rend le texte d'un côté et perd l'appel d'outil de l'autre.

Ce lecteur ne sait pas à quel moteur il parle. Il n'a ni réglage, ni drapeau,
ni nom de serveur. Il lit la FORME de ce qu'on lui donne :

- l'enveloppe : un `data: ` en tête est retiré s'il est là. Les lignes d'Ollama
  n'en ont jamais, donc la même ligne de code les traverse sans rien faire.
- la charge : `message` si l'objet en a un, sinon `choices[0].delta`. Une seule
  fonction, `_charge`, et tout ce qui suit travaille sur son résultat.
- une fois normalisée, la clé des appels d'outil porte LE MÊME NOM dans les
  deux dialectes — `tool_calls`. L'accumulation n'a donc pas deux versions :
  elle n'en a qu'une, et elle est exercée par les deux moteurs.

C'est ce qui rend la divergence non REPRÉSENTABLE, au lieu de la rendre
surveillée.

CE QUE LE LECTEUR NE FAIT PAS
-----------------------------

Il ne juge pas ce qu'est une sous-question valable : `extract_tool_query` reste
le seul juge, et le lecteur lui rend un `message` de la forme qu'il attend. La
règle de lecture des arguments — objet, ou chaîne JSON — n'est donc PAS
réécrite ici. Il n'y en a toujours qu'une dans le dépôt.

Il ne bascule rien : la charge utile envoyée au serveur n'est pas de son
ressort et reste le dialecte d'Ollama. Ce lecteur rend le dépôt CAPABLE de lire
l'autre dialecte, il ne l'y envoie pas.

Il ne retire rien du texte. Un appel d'outil qui a FUI dans le contenu — la
forme `<|tool_call>…<tool_call|>` d'un analyseur mal choisi côté serveur —
traverse ce lecteur comme du texte, parce qu'un flux se cède token par token et
qu'une sentinelle à cheval sur deux tokens ne peut pas être retirée sans
retenir tout le flux. Le retrait a UN site, `src/agent/repli_outil.py`, qui
travaille sur la réponse assemblée. Voir `tests/unit/test_lecteur_de_flux.py`,
section « la fuite dans le texte », qui mesure ce que ce lecteur en fait.

LES FORMES, RELEVÉES SUR LES DEUX MOTEURS DU POSTE LE 16 SEPTEMBRE 2026
-----------------------------------------------------------------------

Entre 04:00 et 04:04 UTC, en lecture, six requêtes, prompts tous distincts
(un prompt répété est servi par le cache de préfixe et ne mesure plus rien) :

    Ollama    {"message":{"content":"L"},"done":false}
              {"message":{…},"done":true,"prompt_eval_count":108,"eval_count":27}

    vLLM      data: {"choices":[{"delta":{"content":" grâce"}}]}
              (ligne vide)
              data: {"choices":[],"usage":{"prompt_tokens":34,"completion_tokens":22}}
              data: [DONE]

L'appel d'outil, lui, arrive en QUATRE événements chez vLLM et en UN chez
Ollama — et dans les deux cas l'`index` est présent, mais PAS À LA MÊME PLACE :

    vLLM      {"id":"…","type":"function","index":0,"function":{"name":"search_vectors"}}
              {"index":0,"function":{"arguments":"{\"query\": \""}}
              {"index":0,"function":{"arguments":"régime indemnitaire …"}}
              {"index":0,"function":{"arguments":"\"}"}}

    Ollama    {"id":"call_t4f68yu2","function":{"index":0,"name":"search_vectors",
               "arguments":{"query":"calcul de l'ancienneté …"}}}

L'index est donc cherché aux DEUX places, et c'est une mesure, pas une
précaution : `appel["index"]` chez vLLM, `appel["function"]["index"]` chez
Ollama. Les deux moteurs l'INCRÉMENTENT sur deux appels (0 puis 1, mesuré sur
les deux), et Ollama étale alors ses deux appels sur DEUX événements — donc
Ollama aussi a besoin de l'accumulation, ce que la lecture ligne à ligne ne
donnait pas.

LES DEUX PIÈGES QUI N'ÉTAIENT PAS DANS LE BANC
----------------------------------------------

1. L'événement d'usage de vLLM porte `"choices": []` — une liste VIDE. Un
   lecteur qui écrit `data["choices"][0]` lève `IndexError` sur le seul
   événement qui porte les décomptes. `_charge` rend `{}` sur une liste vide.

2. Chez vLLM, les décomptes n'existent en streaming QUE si la requête a
   demandé `stream_options: {"include_usage": true}` (mesuré : présents avec,
   absents sans). Ce lecteur les lit quand ils sont là et déclare leur absence
   sinon — il ne les invente pas, et il ne modifie pas la charge utile pour les
   obtenir : cela appartient au lot qui bascule.
"""

from __future__ import annotations

import json
from typing import Any, NamedTuple

# L'enveloppe SSE. Elle est OPTIONNELLE : les lignes d'Ollama ne la portent pas,
# et la même ligne de code les traverse sans effet. C'est ce qui évite d'avoir
# à savoir à quel moteur on parle.
_PREFIXE_SSE = "data: "

# La sentinelle de fin du SSE. Elle n'est pas du JSON — c'est exactement ce qui
# faisait lever `json.loads` — et elle doit donc être reconnue AVANT lui.
_SENTINELLE_FIN = "[DONE]"


class Decomptes(NamedTuple):
    """Les décomptes du serveur, ou leur absence DÉCLARÉE.

    `None` ne veut pas dire zéro : il veut dire « le serveur ne l'a pas dit ».
    La distinction compte — `mesure_prompt_exploitable` en dépend, et un zéro
    inventé ferait passer pour mesurée une fenêtre que personne n'a mesurée.
    """

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
        self._ordre: list[Any] = []
        self.decomptes = Decomptes()
        # Passe à True sur `done: true` (Ollama) ou `[DONE]` (SSE). L'appelant
        # s'en sert pour sortir de sa boucle, exactement comme le `break` d'avant.
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
            # Le SSE sépare ses événements par une ligne vide. Ollama n'en
            # produit pas, mais l'ancien code les sautait déjà : même geste.
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
            raise RuntimeError(f"Ollama : {data['error']}")

        self._lire_decomptes(data)
        charge_utile = self._charge(data)
        self._accumuler(charge_utile.get("tool_calls"))
        if data.get("done"):
            self.termine = True

        contenu = charge_utile.get("content")
        return contenu if isinstance(contenu, str) else ""

    def message_outils(self) -> dict[str, Any]:
        """Rend les appels accumulés sous la forme qu'`extract_tool_query` attend.

        C'est ici, et seulement ici, que la décision devient possible : un
        fragment d'arguments pris seul n'est pas du JSON valide — `{"query": "`
        ne l'est pas — donc le juger à chaque ligne rend `None` à chaque ligne.
        Rendu à la fin, l'objet reconstruit est celui qu'Ollama aurait émis d'un
        bloc, et le juge est le même pour les deux moteurs.
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

    @staticmethod
    def _charge(data: dict[str, Any]) -> dict[str, Any]:
        """Rend l'objet qui porte `content` et `tool_calls`, `{}` si absent.

        Le SEUL endroit du lecteur qui connaît les deux dialectes. Tout ce qui
        est en aval travaille sur son résultat et ignore d'où il vient — c'est
        ce qui empêche la branche « si vLLM … sinon … » de se répandre.
        """
        message = data.get("message")
        if isinstance(message, dict):
            return message
        choix = data.get("choices")
        # `choices: []` N'EST PAS une anomalie : c'est la forme exacte de
        # l'événement d'usage de vLLM, celui qui porte les décomptes. Écrire
        # `choices[0]` lèverait `IndexError` précisément là. (mesuré 16/09)
        if isinstance(choix, list) and choix and isinstance(choix[0], dict):
            delta = choix[0].get("delta")
            if isinstance(delta, dict):
                return delta
        return {}

    def _lire_decomptes(self, data: dict[str, Any]) -> None:
        """Deux dialectes, deux places, un seul champ de sortie."""
        if data.get("done"):
            self.decomptes = Decomptes(
                prompt_eval_count=data.get("prompt_eval_count"),
                eval_count=data.get("eval_count"),
            )
        usage = data.get("usage")
        if isinstance(usage, dict):
            self.decomptes = Decomptes(
                prompt_eval_count=usage.get("prompt_tokens"),
                eval_count=usage.get("completion_tokens"),
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

            # L'index vit au niveau de l'APPEL chez vLLM et au niveau de la
            # FONCTION chez Ollama (mesuré sur les deux, 16/09). La position
            # dans la liste ne sert que si aucun des deux n'est là : sans ce
            # dernier repli, deux appels sans index se recouvriraient sous la
            # même clé `None` et le second écraserait le premier.
            cle = appel.get("index")
            if cle is None:
                cle = fonction.get("index")
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
                fragment["name"] = nom

            arguments = fonction.get("arguments")
            if isinstance(arguments, str):
                # UNE CHAÎNE SE CONCATÈNE. C'est la règle qui fait tout ce
                # module : les morceaux de vLLM ne sont pas du JSON pris
                # séparément, et « fusionner » n'a aucun sens sur du texte
                # coupé au milieu d'une clé.
                precedent = fragment["arguments"]
                acquis = precedent if isinstance(precedent, str) else ""
                fragment["arguments"] = acquis + arguments
            elif arguments is not None:
                # UN OBJET REMPLACE. Ollama rend l'appel entier d'un coup ;
                # concaténer des dicts ne veut rien dire, et les fusionner
                # inventerait un appel que le modèle n'a pas demandé.
                fragment["arguments"] = arguments
