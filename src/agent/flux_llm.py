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
- la charge : `message` si l'objet en a un, sinon `choices[0].delta` en flux ou
  `choices[0].message` hors flux. Une seule fonction, `charge_du_corps`, et tout
  ce qui suit travaille sur son résultat — `llm._contenu_message` compris.
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
ressort. Ce lecteur rend le dépôt CAPABLE de lire l'autre dialecte, il ne l'y
envoie pas — ce ressort-là est `src/agent/dialecte_llm.py` depuis le lot 25, et
le défaut qu'il sert reste Ollama.

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
   événement qui porte les décomptes. `charge_du_corps` rend `{}` sur une liste vide.

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


def charge_du_corps(data: dict[str, Any]) -> dict[str, Any]:
    """Rend l'objet qui porte `content` et `tool_calls`, `{}` si absent.

    LE SEUL SITE DU DÉPÔT QUI CONNAISSE LES DEUX DIALECTES EN ENTRÉE. Tout ce
    qui est en aval travaille sur son résultat et ignore d'où il vient — c'est
    ce qui empêche la branche « si vLLM … sinon … » de se répandre. Son
    symétrique en SORTIE est `dialecte_llm`, et il n'y en a pas de troisième.

    TROIS FORMES, ET LA TROISIÈME EST UNE CORRECTION DU LOT 25. Ce module ne
    servait que le FLUX, où vLLM écrit `choices[0].delta` ; mais `llm.py` a
    aussi DEUX appels non-flux — la réécriture de question et la traduction —
    et là vLLM écrit `choices[0].message`. Leur lecteur, `llm._contenu_message`,
    ne connaissait que `message` à la racine : sous vLLM il aurait rendu `""`
    sur une réponse PARFAITEMENT VALIDE, et les deux appels seraient tombés sur
    leur repli — « question d'origine conservée », « recherche monolingue » —
    en HTTP 200, sans erreur, avec un journal qui accuse le serveur. Une
    recherche dégradée dans les deux langues, pour une réponse que le serveur
    avait bien donnée. (`mesuré` le 16 septembre 2026 à 14:12 UTC : le corps
    non-flux de `vllm-central` porte `choices[0].message.content` et aucune clé
    `message` à la racine.)

    `delta` est cherché AVANT `message` : en flux, les deux moteurs du poste
    n'émettent que `delta` (mesuré), et l'ordre inverse ne changerait donc rien
    aujourd'hui. Il est écrit ainsi pour qu'un corps qui porterait les deux —
    un proxy qui mêle les dialectes, le même chemin que `_lire_decomptes`
    traite déjà — rende le FRAGMENT et non la réponse entière : céder la
    réponse assemblée au milieu d'un flux la ferait s'afficher deux fois.
    """
    message = data.get("message")
    if isinstance(message, dict):
        return message
    choix = data.get("choices")
    # `choices: []` N'EST PAS une anomalie : c'est la forme exacte de
    # l'événement d'usage de vLLM, celui qui porte les décomptes. Écrire
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
        charge_utile = charge_du_corps(data)
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

    def _lire_decomptes(self, data: dict[str, Any]) -> None:
        """Deux dialectes, deux places, un seul champ de sortie.

        CHAQUE BRANCHE NE REMPLACE QUE CE QU'ELLE RENSEIGNE, et c'est tout ce
        que cette fonction a de délicat. Les deux branches s'exécutaient
        auparavant l'une après l'autre sans condition, chacune écrivant un
        `Decomptes` NEUF : un événement portant `done: true`, ses compteurs, ET
        un `usage` — même vide — rendait alors `(None, None)`. Une mesure
        RÉELLE devenait une absence DÉCLARÉE, et `mesure_prompt_exploitable` la
        croyait honnête, alors que `None` est censé vouloir dire « le serveur ne
        l'a pas dit » et rien d'autre.

        AUCUN MOTEUR DU POSTE N'ÉCRIT LES DEUX DIALECTES, et c'est mesuré dans
        les deux sens le 16 septembre 2026 à 07:26 UTC : `ollama-central` n'émet
        aucun `usage` (61 événements, 0 occurrence), `vllm-central` n'émet aucun
        `done` (62 événements JSON, 0 occurrence). Le chemin réparé ici est donc
        celui d'un PROXY qui mêle les deux, pas celui d'un serveur du poste — ce
        module se présentant comme lisant « la FORME, pas un réglage », il doit
        tenir devant la forme mêlée au lieu d'y perdre ses décomptes en silence.

        CE QUE LA RÈGLE DÉCIDE QUAND LES DEUX DIALECTES RENSEIGNENT LE MÊME
        CHAMP AVEC DES VALEURS DIFFÉRENTES : le DERNIER lu gagne. Ce n'est pas
        l'arbitraire qu'il paraît, et le premier réflexe — « une mesure acquise
        ne bouge plus » — est FAUX, mesuré : `vllm-central` accepte
        `stream_options: {"include_usage": true, "continuous_usage_stats":
        true}` et émet alors un `usage` CUMULATIF sur chaque événement (`mesuré`
        16/09 07:49 UTC : 42 événements, `completion_tokens` de 0 à 40). Garder
        le premier renseigné y figerait le compte à zéro token généré —
        c'est-à-dire précisément la mesure fausse que ce garde existe pour
        empêcher. Le dernier lu est le seul qui soit le compte FINAL sur le seul
        conflit que le poste sait produire.
        """
        if data.get("done"):
            self._renseigner(data.get("prompt_eval_count"), data.get("eval_count"))
        usage = data.get("usage")
        if isinstance(usage, dict):
            # `isinstance` et non `usage is not None` : un `usage` qui n'est pas
            # un objet — `42`, une chaîne — ferait lever `.get` au milieu du
            # flux. Ligne DÉFENSIVE : aucun moteur du poste ne l'écrit ainsi.
            self._renseigner(usage.get("prompt_tokens"), usage.get("completion_tokens"))

    def _renseigner(self, prompt_eval_count: Any, eval_count: Any) -> None:
        """Écrit les décomptes SANS effacer ceux qu'un autre dialecte a donnés.

        `None` en entrée veut dire « cette branche ne dit rien de ce champ » —
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
                #
                # `and nom` EST DÉFENSIF, et c'est dit pour qu'un refactor ne le
                # prenne pas pour du bruit : vLLM OMET `name` dans les fragments
                # suivants (mesuré, capture `VLLM_OUTIL`), il ne le met pas à
                # `""`. Aucun moteur du poste n'exerce donc cette garde — mais
                # sans elle, un `""` reçu après le nom le ferait retomber à la
                # chaîne vide et `extract_tool_query` rendrait `None` : la
                # recherche disparaîtrait sans erreur ni log.
                # Tenu par `test_un_nom_vide_n_ecrase_pas_le_nom_acquis`.
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
