"""Le dialecte sortant : UN site qui décide de l'adresse ET de la forme.

POURQUOI CE MODULE EXISTE
-------------------------

`flux_llm.py` rend le dépôt capable de LIRE les deux dialectes, et sa docstring
dit explicitement ce qu'il ne fait pas : « il ne bascule rien ; la charge utile
envoyée au serveur n'est pas de son ressort ». Ce module est ce ressort-là, et
c'est tout ce qu'il est.

CE QUI VARIE N'EST PAS UNE ADRESSE, C'EST UN DIALECTE
-----------------------------------------------------

Quatre choses changent en même temps, et aucune ne se déduit des autres :

1. le CHEMIN — `/api/chat` contre `/v1/chat/completions` ;
2. la FORME de la charge — `options: {temperature, num_predict, num_ctx}` d'un
   côté, `temperature` et `max_tokens` à plat de l'autre ;
3. le NOM DU MODÈLE, qui n'est pas le même des deux côtés ;
4. le RAISONNEMENT — `think` chez Ollama, `chat_template_kwargs` chez vLLM.

CE QUE MESURE UNE CHARGE OLLAMA ENVOYÉE À vLLM, ET C'EST LA RAISON D'ÊTRE DE CE
MODULE : **elle ne casse pas**. `mesuré` le 16 septembre 2026 à 14:12 UTC sur
`vllm-central` (vLLM 0.28.0), quatre requêtes en lecture :

    POST /v1/chat/completions {"options":{"num_predict":5,…},"think":false}
      → HTTP 200, finish_reason=stop, completion_tokens=41 à 77

    POST /v1/chat/completions {"max_tokens":5}          (contrôle positif)
      → HTTP 200, finish_reason=length, completion_tokens=5

`options`, `num_predict`, `num_ctx` et `think` sont ACCEPTÉS et IGNORÉS, sans
erreur, sans avertissement, sans journal. Un lot qui basculerait le chemin sans
basculer la FORME générerait donc avec la température et le plafond PAR DÉFAUT
du serveur, et rien ne le dirait. C'est exactement le genre de défaut que ce
chantier passe son temps à débusquer, et c'est pourquoi l'adresse et la forme
sont décidées ICI, ensemble, au même endroit.

LE NOM DU MODÈLE EST LA SEULE PART QUI SE PLAIGNE, ET C'EST MESURÉ DANS LES DEUX
SENS le 16 septembre 2026 à 14:14 UTC : `{"model":"gemma4:e4b"}` à vLLM rend
**404** « The model `gemma4:e4b` does not exist », et le nom vLLM à Ollama rend
**404** « model … not found ». Les deux noms sont donc DISJOINTS par mesure, un
seul réglage ne peut pas les porter, et ce module en lit deux.

UN SEUL SITE DÉCIDE — C'EST LA LEÇON DU LOT 19, APPLIQUÉE À L'ENVOI
-------------------------------------------------------------------

Il n'y a PAS de `if moteur == …` dans `llm.py`, ni dans `main.py`, ni dans
`usage.py`. Les appelants demandent une charge et une URL ; ils ne savent pas à
qui ils parlent. Deux endroits qui doivent s'accorder finissent par diverger, et
ici la divergence ne se verrait pas — elle enverrait `num_predict` à un serveur
qui l'ignore.

LE RÉGLAGE EST LU À CHAQUE APPEL, ET C'EST TRANCHÉ
---------------------------------------------------

`dialecte_courant()` construit son objet à chaque appel et ne mémorise rien.
Les deux options se défendaient ; celle-ci est retenue pour trois raisons, dans
cet ordre :

- **le retour arrière est le réglage lui-même**. Un dialecte mémorisé au
  démarrage ferait de la bascule un aller simple pour la vie du processus, et
  ce chantier a déjà payé exactement cela — `_moteur_releve` dans `main.py` est
  mémorisé à vie *et sa docstring doit dire pourquoi c'est tolérable là-bas*.
  Ici ce ne le serait pas : l'interrupteur doit revenir.
- **le coût est nul** : un `Dialecte` est un tuple de quatre chaînes construit
  sans entrée-sortie, et les appelants en font au plus un par requête HTTP
  sortante — c'est-à-dire trois par réponse de l'agent, face à une génération
  qui se compte en secondes.
- **la mesure devient possible sans redémarrage** : les scènes basculent le
  réglage et relisent, ce qui est ce qui permet de GARDER le défaut plutôt que
  de l'affirmer.

CE QUE CE MODULE NE FAIT PAS
-----------------------------

Il ne LIT aucune réponse : la lecture du flux est à `flux_llm.py`, et celle du
non-flux à `llm._contenu_message`, qui délègue à `charge_du_corps` — le seul
site qui connaisse les deux formes en ENTRÉE, comme celui-ci est le seul à les
connaître en SORTIE.

Il ne fait aucune entrée-sortie : il rend une URL et un dict. Il se teste donc
sans réseau, sans serveur et sans LangGraph.

Il ne touche à RIEN côté serveur. `vllm-central` appartient à une autre équipe
et sert d'autres projets de cette machine : tout ce que ce module demande passe
PAR REQUÊTE. Le raisonnement en particulier — voir `_charge_vllm`.
"""

from __future__ import annotations

from typing import Any, Literal, NamedTuple

from .settings import settings

# Les deux valeurs que `LLM_ENGINE` accepte. Elles sont contraintes par
# `Literal` dans `Settings`, donc une troisième valeur est refusée AU DÉMARRAGE
# par pydantic et non silencieusement rabattue sur Ollama. Un réglage qui
# retomberait sur le défaut sans le dire ferait croire à une bascule qui n'a
# pas eu lieu — c'est la panne muette que tout ce lot existe pour empêcher.
MoteurLlm = Literal["ollama", "vllm"]


class Dialecte(NamedTuple):
    """Où poster, sous quel nom de modèle, et dans quelle forme.

    `nom` n'est PAS ce que `/health` publie sous `moteur_llm.serveur` : celui-ci
    est notre RÉGLAGE, celui-là est relevé DU SERVEUR. Les deux peuvent
    diverger — c'est même précisément ce qu'un exploitant a besoin de voir — et
    `documentation/moteur_llm.md` en fait le mode d'emploi.
    """

    nom: MoteurLlm
    hote: str
    modele: str

    @property
    def url_chat(self) -> str:
        """L'endpoint de génération, seul endroit où le chemin est écrit."""
        return f"{self.hote}{'/api/chat' if self.nom == 'ollama' else '/v1/chat/completions'}"

    @property
    def url_sonde(self) -> str:
        """Ce que `/health` interroge pour dire que le moteur répond.

        `/api/tags` liste ce qu'Ollama PORTE, `/v1/models` ce que vLLM SERT. Les
        deux rendent 200 sur un serveur en marche, et c'est tout ce que la sonde
        booléenne de `/health` demande. Sans ce site, basculer le moteur ferait
        passer le service `degraded` en interrogeant `/api/tags` sur un serveur
        qui n'en a pas — une panne annoncée pour un service qui fonctionne.
        """
        return f"{self.hote}{'/api/tags' if self.nom == 'ollama' else '/v1/models'}"

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
        """La charge utile POST, dans le dialecte du moteur courant.

        Les cinq premières grandeurs nommées ici sont celles qui changent le
        SENS de la réponse : elles sont donc toutes passées, jamais laissées au
        défaut du serveur. `num_ctx` n'en fait pas partie, et c'est traité dans
        `_charge_vllm`.

        `graine` ET `format_json` SONT NULS SUR LE CHEMIN QUI SERT, et c'est
        pourquoi la charge de production ne bouge pas d'un octet : ni l'un ni
        l'autre n'est inséré quand il n'est pas demandé. Ils existent pour les
        DEUX SCRIPTS D'OUTILLAGE — `scripts/generate_golden.py` et
        `scripts/sweep_retrieval.py` — qui postaient jusqu'ici `/api/chat` en
        dur, donc hors de ce site (NB-5 de l'audit du 16 septembre 2026). Les
        faire entrer ici plutôt que de les laisser dehors est la seule lecture
        cohérente de « UN SEUL SITE » : un site unique qui ne porte pas toute la
        forme n'est pas unique, il est majoritaire.

        LES DEUX N'ONT PAS LE MÊME NOM NI LA MÊME PLACE DES DEUX CÔTÉS, et c'est
        exactement la raison d'être de ce module : `seed` vit dans `options` chez
        Ollama et à plat chez vLLM ; le format contraint s'appelle
        `format: "json"` chez l'un et `response_format: {"type": "json_object"}`
        chez l'autre. Un script qui bascule le chemin sans basculer ces deux-là
        les verrait ACCEPTÉS ET IGNORÉS, sans erreur — la panne muette que ce
        module existe pour empêcher, et qui coûterait ici la reproductibilité du
        jeu doré.
        """
        if self.nom == "ollama":
            return _charge_ollama(
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
    """Le dialecte que le réglage désigne, relu à chaque appel.

    LE DÉFAUT EST OLLAMA, ET IL REPRODUIT L'OCTET PRÈS CE QUE LE DÉPÔT ENVOYAIT
    AVANT CE MODULE. Ce n'est pas une intention : c'est ce que mesure
    `tests/unit/test_dialecte_llm.py`, qui confronte les trois charges à des
    littéraux recopiés du code d'avant, et qui rougit si l'une bouge.
    """
    if settings.llm_engine == "vllm":
        return Dialecte(nom="vllm", hote=settings.vllm_host, modele=settings.vllm_model)
    return Dialecte(nom="ollama", hote=settings.ollama_host, modele=settings.ollama_model)


def _charge_ollama(
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
    """La charge d'Ollama, dans l'ORDRE D'INSERTION qu'elle avait déjà.

    L'ordre n'a aucune portée pour le serveur — c'est du JSON — mais il en a une
    pour la relecture d'un diff : une charge réordonnée se lit comme une charge
    modifiée, et c'est la dernière chose qu'on veut sur le chemin qui SERT.
    """
    charge: dict[str, Any] = {
        "model": modele,
        "messages": messages,
        "stream": stream,
        "think": thinking,
        "options": {
            "temperature": temperature,
            "num_predict": max_tokens,
            # Explicite : sans ce champ la fenêtre dépend de
            # l'OLLAMA_CONTEXT_LENGTH du serveur, qui diffère entre l'Ollama
            # embarqué (8192) et le service central (32768). Le même prompt
            # donnait deux comportements.
            "num_ctx": settings.llm_num_ctx,
        },
    }
    # AJOUTÉS SEULEMENT S'ILS SONT DEMANDÉS, et l'ordre d'insertion de la charge
    # de production est donc INTACT : `graine` et `format_json` sont nuls sur les
    # trois postes qui servent. Le garde de l'octet près le vérifie encore.
    if graine is not None:
        charge["options"]["seed"] = graine
    if format_json:
        charge["format"] = "json"
    if outils:
        charge["tools"] = outils
    return charge


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
    `mesuré` le 16 septembre 2026 à 14:11 UTC par `docker inspect`), et ce lot
    n'a pas le droit d'y toucher. Inventer un champ le ferait ignorer en
    silence, exactement comme `options` (voir la docstring du module).

    `LLM_NUM_CTX` reste donc pleinement UTILISÉ, mais côté CLIENT : c'est lui
    qui borne le budget de prompt (`llm.context_budget_chars`,
    `llm.fit_prompt`) et qui arme la suspicion de troncature
    (`llm._TRUNCATION_SUSPICION_TOKENS`). Il ne dit plus au serveur quoi faire,
    il dit toujours au client ce qu'il a le droit d'envoyer — et `/health`
    publie en regard la fenêtre RÉELLEMENT servie (`fenetre_servie`), de sorte
    qu'un écart entre les deux se voie au lieu de se deviner.

    (b) LE RAISONNEMENT PASSE PAR REQUÊTE, ET JAMAIS AUTREMENT.

    `think` est un champ d'Ollama ; vLLM ouvre le raisonnement par
    `chat_template_kwargs`, qui est un argument du GABARIT et non du serveur.
    Le poser côté serveur est INTERDIT ici, et pas par prudence : combiné à
    `--reasoning-parser gemma4`, il contourne SILENCIEUSEMENT la sortie
    structurée (bogue vLLM #39130), sur un serveur partagé avec deux autres
    équipes.

    CE QUE `enable_thinking: true` DONNE SUR LE SERVEUR DE CE POSTE, QUI N'A PAS
    DE `--reasoning-parser` (`mesuré` le 16 septembre 2026 à 14:13 et 14:14 UTC,
    trois requêtes) :

        non-flux   completion_tokens=278, finish_reason=stop,
                   `content: null` ET `reasoning: null`  → la réponse est PERDUE
        flux       completion_tokens=240, 659 caractères cédés,
                   commençant par « thought\\nThinking Process: » → le
                   raisonnement BRUT part à l'écran de l'utilisateur

    Aucune des deux n'est exploitable, et aucune ne lève. `LLM_THINKING=true`
    sous `LLM_ENGINE=vllm` est donc une configuration QUI SE TRANSMET FIDÈLEMENT
    et dont le résultat est mauvais : ce module envoie ce que le réglage dit,
    il ne le corrige pas en douce — corriger ici ferait mentir le réglage, et
    un réglage qui ment est pire qu'un réglage qui a un mauvais réglage. La
    mesure est écrite pour que le choix se fasse les yeux ouverts, et le défaut
    (`false`) est celui qui marche.

    (c) LES DÉCOMPTES N'EXISTENT EN FLUX QUE SI ON LES DEMANDE.

    `mesuré` le 16 septembre 2026 à 14:13 UTC, dans les deux sens : avec
    `stream_options: {"include_usage": true}`, un événement à `"choices": []`
    porte `usage` (1 sur 8 événements `data:`) ; sans lui, ZÉRO sur 22. Le
    lecteur les lirait donc comme une absence déclarée, et `on_measure`
    n'aurait jamais rien à rendre sous vLLM.

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
    # LES DEUX MÊMES DEMANDES, DANS L'AUTRE DIALECTE. `seed` est à plat ici et
    # dans `options` chez Ollama ; le format contraint passe par
    # `response_format`, le champ du dialecte OpenAI. Envoyer `format: "json"` à
    # vLLM le ferait ignorer en silence, exactement comme `options`.
    if graine is not None:
        charge["seed"] = graine
    if format_json:
        charge["response_format"] = {"type": "json_object"}
    if outils:
        charge["tools"] = outils
    return charge
