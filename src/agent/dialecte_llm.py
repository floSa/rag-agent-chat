"""Le dialecte sortant : UN site qui décide de l'adresse ET de la forme.

POURQUOI CE MODULE EXISTE ENCORE, ALORS QU'IL N'Y A PLUS QU'UN DIALECTE
-----------------------------------------------------------------------

Il est né (lot 25) pour tenir DEUX dialectes sans les éparpiller. Le lot 28 en
retire un : le service tourne sous vLLM depuis le 17 septembre 2026, l'autre
moteur n'est plus servi, et son support est retiré du code — pas seulement son
nom.

Ce module reste, et ce n'est pas par sentiment. Ce qu'il tenait n'était pas la
BRANCHE, c'était le fait que quatre choses voyagent ensemble et qu'aucune ne se
déduit des autres :

1. le CHEMIN — `/v1/chat/completions` ;
2. la FORME de la charge — `temperature` et `max_tokens` à plat ;
3. le NOM DU MODÈLE, qui est celui que le serveur SERT ;
4. le RAISONNEMENT — `chat_template_kwargs`, un argument du GABARIT.

Les éparpiller chez les appelants était le défaut d'avant le lot 25, et le
retrait d'un moteur ne le rend pas moins vrai : `llm.py`, `main.py` et `usage.py`
demandent toujours une charge et une URL sans écrire eux-mêmes un chemin ni un
nom de champ. Ce qui a disparu, c'est le `if` — pas le site.

CE QUE LE RETRAIT COÛTE, ET IL FAUT LE SAVOIR AVANT DE LE REGRETTER
--------------------------------------------------------------------

Le retour arrière n'est plus un réglage. Avant ce lot, repasser `LLM_ENGINE` à
l'autre valeur suffisait, sans reconstruction. Désormais il faut réétiqueter
l'image d'avant la bascule et redéployer — la procédure est écrite, avec son
étiquette exacte, dans `documentation/identite_du_code_servi.md`.

LA PANNE MUETTE QUI JUSTIFIAIT CE SITE N'A PAS DISPARU AVEC LA BRANCHE, et c'est
la raison pour laquelle sa mesure reste écrite ici. `mesuré` le 16 septembre
2026 à 14:12 UTC sur `vllm-central` (vLLM 0.28.0), quatre requêtes en lecture :

    POST /v1/chat/completions {"options":{"num_predict":5,…},"think":false}
      → HTTP 200, finish_reason=stop, completion_tokens=41 à 77

    POST /v1/chat/completions {"max_tokens":5}          (contrôle positif)
      → HTTP 200, finish_reason=length, completion_tokens=5

Un champ du dialecte de l'ancien moteur est ACCEPTÉ et IGNORÉ par celui-ci, sans
erreur, sans avertissement, sans journal. Un appelant qui en réintroduirait un —
`options`, `num_predict`, `num_ctx`, `think` — générerait donc avec la
température et le plafond PAR DÉFAUT du serveur, et rien ne le dirait. C'est
pourquoi la forme est décidée ICI, en un seul endroit, plutôt que surveillée.

CE QUE CE MODULE NE FAIT PAS
-----------------------------

Il ne LIT aucune réponse : la lecture du flux est à `flux_llm.py`, et celle du
non-flux à `llm._contenu_message`, qui délègue à `charge_du_corps` — le seul
site qui connaisse la forme en ENTRÉE, comme celui-ci est le seul à la
connaître en SORTIE.

Il ne fait aucune entrée-sortie : il rend une URL et un dict. Il se teste donc
sans réseau, sans serveur et sans LangGraph.

Il ne touche à RIEN côté serveur. `vllm-central` appartient à une autre équipe
et sert d'autres projets de cette machine : tout ce que ce module demande passe
PAR REQUÊTE. Le raisonnement en particulier — voir `_charge_vllm`.
"""

from __future__ import annotations

from typing import Any, NamedTuple

from .settings import settings


class Dialecte(NamedTuple):
    """Où poster, sous quel nom de modèle, et dans quelle forme.

    Le NOM du moteur n'est plus un champ de cet objet, et c'est le lot 28 :
    un champ à une seule valeur possible n'est pas une donnée, c'est une
    affirmation que rien ne peut plus contredire. Ce que `/health` publie sous
    `moteur_llm.serveur` reste, lui, relevé DU SERVEUR — il peut donc démentir
    ce que ce dépôt croit, et `documentation/moteur_llm.md` en fait le mode
    d'emploi.
    """

    hote: str
    modele: str

    @property
    def url_chat(self) -> str:
        """L'endpoint de génération, seul endroit où le chemin est écrit."""
        return f"{self.hote}/v1/chat/completions"

    @property
    def url_sonde(self) -> str:
        """Ce que `/health` interroge pour dire que le moteur répond.

        `/v1/models` liste ce que le serveur SERT. Il rend 200 sur un serveur en
        marche, et c'est tout ce que la sonde booléenne de `/health` demande.
        """
        return f"{self.hote}/v1/models"

    def charge(
        self,
        messages: list[dict[str, Any]],
        *,
        stream: bool,
        temperature: float,
        max_tokens: int,
        thinking: bool,
        outils: list[dict[str, Any]] | None = None,
        graine: int | None = None,
        format_json: bool = False,
    ) -> dict[str, Any]:
        """La charge utile POST, dans le dialecte du moteur.

        Les cinq premières grandeurs nommées ici sont celles qui changent le
        SENS de la réponse : elles sont donc toutes passées, jamais laissées au
        défaut du serveur. `num_ctx` n'en fait pas partie, et c'est traité dans
        `_charge_vllm`.

        `graine` ET `format_json` SONT NULS SUR LE CHEMIN QUI SERT, et c'est
        pourquoi la charge de production ne bouge pas d'un octet : ni l'un ni
        l'autre n'est inséré quand il n'est pas demandé. Ils existent pour les
        DEUX SCRIPTS D'OUTILLAGE — `scripts/generate_golden.py` et
        `scripts/sweep_retrieval.py` — qui postaient jusqu'ici leur chemin en
        dur, donc hors de ce site (NB-5 de l'audit du 16 septembre 2026). Les
        faire entrer ici plutôt que de les laisser dehors est la seule lecture
        cohérente de « UN SEUL SITE » : un site unique qui ne porte pas toute la
        forme n'est pas unique, il est majoritaire.
        """
        return _charge_vllm(
            self.modele,
            messages,
            stream=stream,
            temperature=temperature,
            max_tokens=max_tokens,
            thinking=thinking,
            outils=outils,
            graine=graine,
            format_json=format_json,
        )


def dialecte_courant() -> Dialecte:
    """Le dialecte du moteur servi, construit à chaque appel.

    RIEN N'EST MÉMORISÉ, et c'est tenu alors même que le réglage ne bascule
    plus. Un `Dialecte` est un tuple de deux chaînes construit sans
    entrée-sortie, et les appelants en font au plus un par requête HTTP
    sortante — trois par réponse de l'agent, face à une génération qui se compte
    en secondes. Le mémoriser au démarrage échangerait ce coût nul contre un
    état figé à vie de plus, et rendrait les scènes incapables de poser un hôte
    et de relire sans redémarrer le processus.
    """
    return Dialecte(hote=settings.llm_host, modele=settings.llm_model)


def _charge_vllm(
    modele: str,
    messages: list[dict[str, Any]],
    *,
    stream: bool,
    temperature: float,
    max_tokens: int,
    thinking: bool,
    outils: list[dict[str, Any]] | None,
    graine: int | None = None,
    format_json: bool = False,
) -> dict[str, Any]:
    """La charge OpenAI-compatible, et les TROIS décisions qu'elle porte.

    (a) `num_ctx` N'EST PAS ENVOYÉ, ET IL N'EST PAS PERDU POUR AUTANT.

    Le dialecte OpenAI n'a aucun champ de fenêtre de contexte : celle-ci est
    fixée au LANCEMENT du serveur (`--max-model-len 32768` sur `vllm-central`,
    `mesuré` le 16 septembre 2026 à 14:11 UTC par `docker inspect`), et ce dépôt
    n'a pas le droit d'y toucher. Inventer un champ le ferait ignorer en
    silence, exactement comme les champs de l'ancien dialecte (voir la docstring
    du module).

    `LLM_NUM_CTX` reste donc pleinement UTILISÉ, mais côté CLIENT : c'est lui
    qui borne le budget de prompt (`llm.context_budget_chars`,
    `llm.fit_prompt`) et qui arme la suspicion de troncature
    (`llm._TRUNCATION_SUSPICION_TOKENS`). Il ne dit plus au serveur quoi faire,
    il dit toujours au client ce qu'il a le droit d'envoyer — et `/health`
    publie en regard la fenêtre RÉELLEMENT servie (`fenetre_servie`), de sorte
    qu'un écart entre les deux se voie au lieu de se deviner.

    (b) LE RAISONNEMENT PASSE PAR REQUÊTE, ET JAMAIS AUTREMENT.

    vLLM ouvre le raisonnement par `chat_template_kwargs`, qui est un argument du
    GABARIT et non du serveur. Le poser côté serveur est INTERDIT ici, et pas par
    prudence : combiné à `--reasoning-parser gemma4`, il contourne SILENCIEUSEMENT
    la sortie structurée (bogue vLLM #39130), sur un serveur partagé avec deux
    autres équipes.

    CE QUE `enable_thinking: true` DONNE SUR LE SERVEUR DE CE POSTE, QUI N'A PAS
    DE `--reasoning-parser` (`mesuré` le 16 septembre 2026 à 14:13 et 14:14 UTC,
    trois requêtes) :

        non-flux   completion_tokens=278, finish_reason=stop,
                   `content: null` ET `reasoning: null`  → la réponse est PERDUE
        flux       completion_tokens=240, 659 caractères cédés,
                   commençant par « thought\\nThinking Process: » → le
                   raisonnement BRUT part à l'écran de l'utilisateur

    Aucune des deux n'est exploitable, et aucune ne lève. `LLM_THINKING=true` est
    donc une configuration QUI SE TRANSMET FIDÈLEMENT et dont le résultat est
    mauvais : ce module envoie ce que le réglage dit, il ne le corrige pas en
    douce — corriger ici ferait mentir le réglage, et un réglage qui ment est
    pire qu'un mauvais réglage. La mesure est écrite pour que le choix se fasse
    les yeux ouverts, et le défaut (`false`) est celui qui marche.

    (c) LES DÉCOMPTES N'EXISTENT EN FLUX QUE SI ON LES DEMANDE.

    `mesuré` le 16 septembre 2026 à 14:13 UTC, dans les deux sens : avec
    `stream_options: {"include_usage": true}`, un événement à `"choices": []`
    porte `usage` (1 sur 8 événements `data:`) ; sans lui, ZÉRO sur 22. Le
    lecteur les lirait donc comme une absence déclarée, et `on_measure`
    n'aurait jamais rien à rendre.

    `continuous_usage_stats` n'est PAS demandé. Il ferait émettre un `usage`
    cumulatif sur CHAQUE événement, ce que `flux_llm._lire_decomptes` sait
    traiter — sa règle « le dernier renseigné gagne » est écrite pour lui — mais
    qui multiplie le volume du flux sans rien ajouter : le dernier événement dit
    déjà le total. Ne pas le demander ne casse pas cette règle, il ne l'exerce
    pas.

    Hors flux, `stream_options` est refusé par le serveur et n'a pas de sens :
    le corps porte alors `usage` sans qu'on ait à le demander.
    """
    charge: dict[str, Any] = {
        "model": modele,
        "messages": messages,
        "stream": stream,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "chat_template_kwargs": {"enable_thinking": thinking},
    }
    if stream:
        charge["stream_options"] = {"include_usage": True}
    # `seed` est à plat dans ce dialecte, et le format contraint passe par
    # `response_format`. Les deux ne sont insérés que s'ils sont demandés :
    # l'ordre d'insertion de la charge de production est donc INTACT, et le garde
    # de l'octet près le vérifie encore.
    if graine is not None:
        charge["seed"] = graine
    if format_json:
        charge["response_format"] = {"type": "json_object"}
    if outils:
        charge["tools"] = outils
    return charge
