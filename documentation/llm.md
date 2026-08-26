# Ollama — service central

Ce projet **n'embarque aucune instance Ollama**. Les modèles sont servis par le
projet [`llm-service`](https://github.com/floSa/llm-service), qui expose le
conteneur `ollama-central` sur le réseau Docker `llm-net`.

## Pourquoi

Une instance Ollama vivait dans le `docker-compose.yml` de ce projet, avec son
propre volume de modèles. Elle faisait doublon avec le service central : un
`docker compose up -d` la recréait et retéléchargeait plusieurs gigaoctets d'un
modèle déjà servi à côté. Un seul serveur d'inférence pour tous les projets
évite d'en héberger un par dépôt, et de multiplier les copies des poids.

## Configuration

| Variable | Valeur | Rôle |
|---|---|---|
| `OLLAMA_HOST` | `http://ollama-central:11434` | Endpoint du service central |
| `OLLAMA_MODEL` | `gemma4:e4b` | Modèle de génération |
| `LLM_NUM_CTX` | `8192` | Fenêtre de contexte demandée par requête |
| `LLM_MAX_TOKENS` | `4096` | Plafond de génération (`num_predict`) |
| `LLM_TEMPERATURE` | `0.1` | Température |
| `LLM_THINKING` | `false` | Raisonnement de Gemma 4, coûteux en CPU |
| `HISTORY_WINDOW_SHARE` | `0.25` | Part de la fenêtre de prompt laissée à l'historique — **forfait**, cf. plus bas |

`LLM_NUM_CTX` est passé explicitement dans chaque requête. Sans lui, la fenêtre
dépendrait de l'`OLLAMA_CONTEXT_LENGTH` du serveur, et le même prompt
produirait deux comportements selon le serveur interrogé.

Ce tableau annonçait `32768`, alors que `.env.example` et `settings.py` valent
`8192` — un facteur quatre sur la capacité annoncée, dont le budget de sources
dérive directement. La valeur retenue est **8192**, celle qui s'exécute. Monter à
32768 quadruple le cache KV et le coût de préremplissage, sur un déploiement où
la latence de génération est déjà à 12,4 s au p95 : c'est un changement qui se
mesure par une campagne, pas qui se décrète dans une table.

## Le budget de contexte

### La formule

Le budget ne se calcule pas sur la fenêtre nue. `num_ctx` est partagé entre le
prompt et la génération, et le prompt ne contient pas que des sources :

```
fenêtre utile     = (LLM_NUM_CTX − LLM_MAX_TOKENS) × 3,5 caractères/token
budget sources    = fenêtre utile − prompt système
                                  − gabarit rendu sans ses sources
                                  − historique retenu
                                  − balises de tour (une par message)
                                  − déclaration de l'outil search_vectors
coût d'une source = len(markdown) + son encadrement, mesuré dans le gabarit
```

L'encadrement est facturé **au moment où la source est retenue**, jamais pour une
candidate écartée. Le compter d'avance sur les candidates réservait la place de
sources qui ne seraient jamais rendues : dix candidates dont six retenues, et une
septième qui aurait tenu se faisait écarter — mesuré, sept candidates en
gardaient sept et dix n'en gardaient plus que six.

À `8192 / 4096`, **mesuré à l'exécution** — chaque terme est la longueur d'une
chaîne réellement construite, pas une provision :

| Terme mesuré | Caractères |
|---|---|
| Fenêtre utile | 14 336 |
| Prompt système (`prompts/system.txt`, lu) | 935 |
| Gabarit rendu sans sources | 472 |
| Déclaration de l'outil `search_vectors` (si `NATIVE_TOOL_CALLING`) | 417 |
| Encadrement d'une source, sans fil des titres | 34 |
| Encadrement d'une source, fil des titres à 2 niveaux | 134 |
| Encadrement d'une source, fil des titres à 5 niveaux | 275 |
| **Budget de sources** — premier tour | **12 444** |
| **Budget de sources** — trois tours de 600 caractères par message (dont un tour écarté) | **9 908** |

L'encadrement va de 34 caractères sans fil des titres à 275 avec cinq niveaux :
un forfait unique serait faux dans les deux sens selon le document. Il était
forfaitisé à 200, ce qui paraissait généreux sur des fixtures sans breadcrumbs —
mais en production `breadcrumbs` est **toujours** peuplé, c'est le résultat de la
remontée `PARENT_OF`, et le gabarit imprime « Chemin : » en clair. Il est
désormais mesuré source par source, par décomposition
(`rendu([source]) − rendu([]) − len(markdown)`) : le gabarit n'a aucune dépendance
entre ses sources, donc la décomposition est exacte — vérifié sur douze sources.

`tools` n'est pas un canal séparé pour le modèle : Ollama le rend **dans** le
prompt via le gabarit de chat. Ne pas le compter laissait le même trou que le
forfait, à plus petite échelle — 417 caractères, soit ~119 tokens.

Ce qui reste un **forfait** — la liste est complète, tout ce qui n'y figure pas
est mesuré à l'exécution :

| Forfait | Valeur | À mesurer |
|---|---|---|
| Ratio caractères/token | 3,5 | Le log `prompt_eval_count` donne le ratio mesuré à chaque génération |
| Balises de tour du gabarit de chat, par message | 34 | Dépend du modèle. C'est le décompte du gabarit Gemma — `<start_of_turn>user\n` 20 caractères, `<end_of_turn>\n` 14 — appliqué à tous |
| Part de la fenêtre laissée à l'historique (`HISTORY_WINDOW_SHARE`) | 25 % | Demande une mesure de la qualité multi-tour, qui n'existe pas |
| Marge sous `num_ctx` au-delà de laquelle on suspecte une troncature d'Ollama | 8 tokens | Dépend du gabarit de chat, qui ne retombe pas pile sur la borne. Se resserrerait sur des `prompt_eval_count` réels |
| Fraction de l'estimation sous laquelle une mesure est imputée au cache KV | 0,6 | Choisi assez bas pour ne pas écarter une simple erreur d'estimation, assez haut pour attraper un préfixe caché. Se réglerait sur la distribution observée |

Le budget précédent valait 12 544 caractères, **constant** : un forfait de 512
tokens tenait lieu de provision pour « le prompt système, le gabarit et
l'historique ». L'historique n'y entrait jamais. Six messages sont acceptés,
chaque réponse assistante peut atteindre `LLM_MAX_TOKENS`, et `Message.content`
n'avait aucune borne : mesuré sur six messages de 3 000 caractères et deux
sources de 12 000, le prompt faisait **31 380 caractères pour une fenêtre utile
de 14 336**, soit 2,2 fois la fenêtre.

Ce qui se passait alors est le mode de panne le plus coûteux du projet : Ollama
tronque **par le début** du prompt. Il jette donc le message système — « cite
chaque affirmation », « ne réponds jamais au-delà des sources », « dis-le si tu
ne trouves pas ». Le garde-fou disparaissait exactement quand la conversation
devenait assez longue pour en avoir besoin.

Le ratio de 3,5 caractères/token reste une estimation — le tokenizer réel dépend
du modèle. Mais il s'applique désormais à **toutes** les parties du prompt : ce
n'était pas le ratio qui trompait, c'était son application partielle.

### Ce qui est écarté, et par quel bout

| Élément | Coupe | Sens |
|---|---|---|
| Sources | Les moins bien classées | Remplissage **au mieux** : une petite source qui suit une grosse écartée est conservée |
| Source unique trop grosse | Tronquée par la **fin**, sur une frontière d'élément, avec une marque dans le markdown | Mieux vaut une source amputée que zéro source — mais pas au prix d'un prompt qu'Ollama tronque par le début. La coupe recule jusqu'à la fin du dernier `[src:ID]` complet : un identifiant amputé n'est plus résolu par le post-processing, ou correspond à un **autre** élément, et un fragment sans marqueur n'est pas attribuable alors que le prompt système exige de citer chaque affirmation |
| Historique | Les **tours** les plus anciens, entiers | C'est le dernier échange qui situe la question. La coupe porte sur des tours et non des messages : couper par message laissait passer une réponse sans la question à laquelle elle répondait, soit un prompt `['system', 'assistant', 'user']` qu'un gabarit strict sur l'alternance refuse |
| Tour trop gros à lui seul | Écarté, pas tronqué | `node_rewrite` a déjà rendu la question de suivi autonome avant l'encodage : l'historique est du confort, pas un prérequis |

`fit_prompt` est le point d'entrée unique, et il est appelé **une seule fois par
génération** : `_build_messages` construit le prompt avec, et rend le budget
appliqué. `node_generate` le récupère par le rappel `on_fit` et le publie dans
l'état du graphe, d'où `/answer` lit ses `dropped_contexts`. Recalculer le budget
côté endpoint journalisait chaque troncature deux fois et rendait le gabarit une
fois de plus par candidate — et surtout, deux calculs séparés dérivent : la
campagne d'évaluation aurait rapporté un autre nombre de sources écartées que ce
qui a réellement atteint le LLM.

Les bornes d'entrée correspondantes sont dans `src/api/schemas.py` :
`MAX_MESSAGE_CHARS` (14 336, soit le plafond de génération lui-même),
`MAX_HISTORY_MESSAGES` (6, ce qui est soumis au LLM) et `MAX_HISTORY_PAYLOAD`
(50, ce qu'une requête peut porter).

### L'instrumentation : `prompt_eval_count`

Le dernier événement du flux Ollama — celui qui porte `done: true` — contient
`prompt_eval_count` : le nombre **réel** de tokens du prompt. Personne ne le
lisait. Le ratio caractères/token restait une devinette qu'aucune mesure ne
corrigeait, et un prompt qui dépassait `num_ctx` ne laissait **aucune trace**.

Chaque génération journalise désormais :

```
INFO  Prompt : estimé 3214 tokens, réel 3480, écart -7.6 % — ratio mesuré
      3.23 caractères/token (retenu : 3.50).
```

**Exemple de forme, pas une mesure** : aucun `prompt_eval_count` réel n'a encore
été observé — cela demande la stack démarrée. Les chiffres ci-dessus illustrent la
lecture du log, ils ne mesurent rien.

Comment la lire :

- **écart négatif** : l'estimation sous-estime le prompt. Le budget est trop
  permissif, et le ratio devrait baisser vers le ratio mesuré ;
- **écart positif** : le budget est trop prudent et écarte des sources qui
  auraient tenu ;
- **ratio mesuré** : la valeur qu'il aurait fallu donner à `_CHARS_PER_TOKEN`
  pour que l'estimation soit exacte. C'est de là que viendra sa calibration —
  sur la distribution observée en campagne, pas sur une valeur posée au jugé.

Deux `WARNING` encadrent la zone dangereuse. Ils ne portent PAS sur
`prompt_eval_count > num_ctx` : Ollama tronque le prompt **avant** de l'évaluer,
donc ce décompte est majoré par `num_ctx` par construction, et une première
version guettait ainsi une condition inatteignable — le détecteur ne pouvait pas
voir ce qu'il cherchait.

| Zone | Signal |
|---|---|
| `prompt_eval_count` à moins de 8 tokens de `num_ctx` | Troncature très probable, **par le début** : le message système, donc les règles de citation et d'abstention, a pu ne pas encadrer la réponse. C'est la seule trace observable de l'événement |
| `prompt_eval_count` au-delà de la fenêtre de prompt (`num_ctx − num_predict`) | La génération n'a plus ses `num_predict` tokens et sera rognée sans le dire. Le budget a sous-estimé le prompt |

### Le cache KV fausse la mesure

Ollama ne réévalue que le préfixe **absent de son cache KV**. Au deuxième tour
d'une conversation, `prompt_eval_count` ne mesure donc plus le prompt mais son
suffixe non caché — il peut valoir quelques dizaines de tokens pour un prompt de
plusieurs milliers.

Une telle mesure est écartée de la calibration : en deçà de 60 % de l'estimation,
le log dit que la valeur est ignorée et pourquoi. **Ne recalibrez jamais
`_CHARS_PER_TOKEN` sur ces échantillons** — le ratio fondrait à chaque tour de
conversation. Pour calibrer, ne retenez que les mesures publiées avec un « ratio
mesuré », ou ne prenez que le premier appel d'une conversation.

```bash
docker compose logs -f agent-api | grep "Prompt :"
```

### La mesure ne sort plus seulement en journal

Le lot 1 a construit cette instrumentation, et **rien ne l'avait jamais
observée** : elle ne sortait qu'en `logger.info`, donc aucune campagne n'en
gardait trace. Depuis le lot 4, `/answer` publie les décomptes réels sous
`generation`, et `scripts/evaluate.py` les enregistre par question :

| Champ | Ce qu'il porte |
|---|---|
| `prompt_eval_count` | Décompte réel du prompt, tel qu'Ollama l'a rendu |
| `prompt_tokens_estimated` | Notre estimation du même prompt, avec le ratio qui a décidé de la coupe |
| `prompt_tokens_reliable` | Faux = échantillon pollué par le cache KV, à écarter de la calibration |
| `eval_count` | Tokens **générés** |
| `num_predict` | Le plafond qui s'appliquait |

La décision d'écarter un échantillon pollué reste **unique** :
`llm.mesure_prompt_exploitable` la porte, `log_prompt_measure` l'applique, la
campagne l'applique. Deux prédicats séparés dériveraient, et la campagne
publierait un ratio que le journal a refusé.

Le résumé de campagne en tire `ratio_caracteres_par_token_mesure` — calculé sur
les seuls échantillons exploitables, avec le nombre d'écartés à côté. C'est ce
chiffre qui calibrera `_CHARS_PER_TOKEN`, aujourd'hui un forfait de 3,5 posé au
jugé.

## `LLM_MAX_TOKENS` — à mesurer

`LLM_MAX_TOKENS = 4096` réserve la **moitié** de la fenêtre à la génération, et
rien ne dit que celle-ci en a besoin. Le seul indice sourcé est indirect :
`runs/final.json` donne 3,246 citations par réponse — une réponse à trois
citations est rarement longue. Mais **la longueur des réponses n'est mesurée
nulle part**, donc l'affirmation « une génération qui n'arrive jamais » reste une
présomption, pas un fait. C'est exactement ce que le protocole ci-dessous
mesure.

**La valeur n'a pas été ajustée, faute de pouvoir la mesurer** : ni
`ollama-central` ni les stores n'étaient joignables. Un chiffre inventé est pire
que pas de chiffre.

Les campagnes passées ne permettent pas de reconstituer la distribution après
coup — `runs/*.json` n'enregistrait que `generation_ms`. Depuis le lot 4, la
campagne l'enregistre, et le protocole n'est plus un script à part : c'est
`make eval`, dont le résumé porte les quatre chiffres qui tranchent.

| Chiffre du résumé | Ce qu'il décide |
|---|---|
| `generations_au_plafond` | **Le chiffre qui tranche.** Zéro sur les 138 questions = le plafond n'est jamais atteint, donc les tokens qu'il réserve sont pris aux sources pour rien. Non nul = le baisser tronquerait des réponses |
| `eval_count_p95`, `eval_count_max` | Où poser le plafond : au p95 mesuré, majoré d'une marge assumée |
| `eval_count_sur` | Sur combien de réponses les trois précédents portent — un serveur qui ne rend pas le décompte les rendrait vides |
| `reponse_caracteres_p95` | Le repli si le serveur ne rend pas `eval_count` : une longueur en caractères, à diviser par le ratio mesuré |

`eval_count` est le décompte du **serveur**, pas une estimation en caractères
divisés par 3,5 : c'est le seul qui puisse dire si la génération a buté sur son
plafond, puisque Ollama s'arrête pile à `num_predict` quand il l'atteint.

Un plafond atteint tronque la réponse, ce qui est un défaut visible ; un plafond
trop haut ne coûte « que » du budget de sources. Le `WARNING` sur
`prompt_eval_count` dira si la nouvelle valeur fait déborder la fenêtre.

Une fois la valeur posée, relancer `make eval` : le budget de sources en dérive,
donc `contextes_ecartes`, `part_utile_caracteres` et `citations_par_reponse`
bougeront — et la comparaison appariée dira lesquelles des 138 questions
basculent.

## Prérequis

```bash
cd ~/mes_projets/llm-service && make up
```

Vérifier que le modèle attendu est servi :

```bash
make models
```

## Dépannage

| Symptôme | Cause probable |
|---|---|
| `/health` renvoie `ollama: false` | `llm-service` n'est pas démarré, ou le réseau `llm-net` n'existe pas |
| `network llm-net not found` | Lancer `make up` dans `llm-service` d'abord |
| Réponse vide ou tronquée | `LLM_NUM_CTX` supérieur à l'`OLLAMA_CONTEXT_LENGTH` du serveur central |
