# Banc GO/NO-GO de la bascule vers vLLM — `rag-agent-chat`

> **Mesuré le 15 septembre 2026**, entre **14:12 UTC** et **14:32 UTC**, relevé
> par `date -u` avant chaque mesure. Le nom de ce fichier porte le **14** parce
> que le lot l'a nommé ainsi ; **toutes les mesures qu'il contient datent du
> 15**. L'écart est signalé ici et nulle part ailleurs — le renommer est un
> geste du pilote, pas du lot.
>
> **Aucune ligne de `src/` n'a été modifiée.** Preuve au §8, par empreinte et
> par `git diff`, pas par affirmation.

---

## 0. Le verdict, en une page

| | La question | Verdict |
|---|---|---|
| **1** | L'outil est-il réellement appelé ? | **GO SOUS CONDITION** — en non-streaming oui, à l'identique d'Ollama. **En streaming, non** : vLLM fragmente l'appel sur 4 événements et notre lecteur n'en voit aucun. C'est le mode de la production. |
| **2** | Les arguments arrivent-ils typés ? | **GO** — vLLM rend une chaîne, Ollama un objet, et `llm.py:847` lit les deux **tel quel**. Rien à écrire. |
| **3** | La substitution silencieuse | **GO** — la surface du voisin (une énumération) n'existe pas chez nous. La nôtre — l'`element_id` — est gardée en aval par du code **indépendant du moteur**. Aucune substitution observée sur 4 cellules. |
| **4** | Le raisonnement | **GO SOUS CONDITION** — sur cette instance il n'y a **rien à éteindre** : le gabarit n'ouvre aucun bloc de raisonnement et aucune génération mesurée n'en a produit. Mais **aucun levier par requête n'existe**, donc la condition n'est pas à nous : elle tient au déploiement du voisin. |
| **5** | Le flux | **GO SOUS CONDITION** — SSE contre NDJSON, notre lecteur casse en `JSONDecodeError`. Réparation connue et petite. **Le piège est que la réparer découvre le défaut (1)**, qui, lui, est silencieux. |
| **6** | La qualité | **NO-GO pour trancher aujourd'hui** — et ce n'est pas un défaut de vLLM : rien dans `runs/` ne consigne le moteur LLM, donc aucune campagne passée n'est comparable à une campagne future. |

**Verdict global : GO, sous les conditions des lignes 1, 4 et 5**, et à condition
que le découpage du §7 soit respecté **dans son ordre**, qui n'est pas l'ordre de
la difficulté.

---

## 1. L'état du poste, remesuré — il avait bougé

Le lot donnait un état `mesuré` le 14 septembre à 15:56 UTC. **Quatre de ses
lignes étaient périmées au 15 septembre à 14:14 UTC.** Le relever était la
consigne ; voici ce qu'elle a attrapé.

Commande : `nvidia-smi --query-compute-apps=... --format=csv` et
`docker ps --format ...`, le 15 septembre 2026 à 14:14:36 UTC.

| Ce que le lot annonçait | Ce que j'ai `mesuré` le 15/09 à 14:14 UTC |
|---|---|
| carte : vLLM 14 264, `llama-server` 3 598, nous 1 550, total 19 431 / 23 034 | **un seul processus sur la carte** : `VLLM::EngineCore`, PID 44752, **14 264 MiB**. Total **14 273 / 23 034**. `llama-server` et notre agent n'y sont plus |
| `pic_memoire_reservee_mio` **1 268,0**, les deux modèles sur `cuda:0` | `pic_memoire_reservee_mio` **`null`**, `embedding` **`null`**, `rerank` **`null`** — l'agent a redémarré (`Up 8 minutes`) et **n'a chargé aucun modèle** |
| `/health` 200, `concurrence_max` 4, `hors_d_atteinte` null | ✅ tenu : **200**, **4**, **`null`** |
| `main` = `origin/main` = `b78857d`, arbre propre, 798 / 45 | ✅ tenu, et **remesuré de mes mains** : `rc=0` / `rc=0`, **798 passés**, **45 fichiers** (§8) |

**Un chiffre que le lot ne donnait pas et qui commande tout le reste** — les
drapeaux de lancement du voisin, `mesuré` le 15/09 à 14:15:28 UTC par
`docker inspect vllm-central --format '{{json .Args}}'` (jamais `.Env` : le
dépôt est public) :

```
serve --model google/gemma-4-E4B-it-qat-w4a16-ct
      --tool-call-parser gemma4 --enable-auto-tool-choice
      --max-model-len 32768 --gpu-memory-utilization 0.55
```

Version du serveur, `mesuré` par `GET /version` : **vLLM 0.28.0**.

Deux lectures, et elles portent tout le rapport :

- **l'analyseur d'outils EST posé, et c'est le bon.** Le piège du pilote de
  `data-analyst-agent` — mauvais analyseur, aucune erreur, appel qui fuit dans le
  texte — ne peut donc pas venir de là **aujourd'hui, sur cette instance**. Il
  peut venir d'un relancement : le drapeau n'est pas à nous ;
- **`--reasoning-parser` n'est PAS posé.** C'est ce qui rend la question 4
  mesurable sans toucher à rien, et c'est aussi ce qui la rend fragile (§5).

**Borne.** Tout ce qui suit vaut pour **cette instance, ces drapeaux, ce
modèle, ce jour-là**. Un relancement du voisin périme les §2, §5 et §6.

---

## 2. Question 1 — l'outil est-il RÉELLEMENT appelé ?

### 2.1 Ce que le banc a établi contre lui-même avant d'établir quoi que ce soit

**Premier faux résultat.** Ma première scène — le prompt système de production,
trois sources, une question hors corpus — n'a déclenché l'outil **sur aucun des
deux moteurs**. Quatre cellules, quatre `tool_calls: null`, quatre fois zéro
fuite. Un banc qui se serait arrêté là aurait écrit « vLLM n'appelle pas
l'outil ». **C'était faux, et le contrôle qui l'a montré est qu'Ollama ne
l'appelait pas davantage.**

La cause est dans notre prompt, pas dans les moteurs.
[`prompts/system.txt`](../../prompts/system.txt) porte deux règles qui se
contredisent exactement quand les sources ne suffisent pas :

- règle **4** : « Si les sources ne permettent pas de répondre […] dis-le
  explicitement » ;
- règle **5** : « Si les sources ne suffisent pas, appelle l'outil
  `search_vectors` ».

`mesuré`, 15/09 14:20 UTC, temperature 0, **sur les deux moteurs** : **la règle 4
gagne**. C'est un constat sur notre prompt, invariant au moteur, et il appartient
au registre — pas au go/no-go.

**Deuxième faux résultat, sur mon propre contrôle positif.** J'avais posé
`tool_choice: "required"` pour prouver que le tuyau porte un appel. Résultat
`mesuré` le 15/09 à 14:21:36 UTC :

```
finish_reason: "tool_calls"
tool_calls:    null
content:       "Bonjour ! Je vais très bien, merci. Et vous […]"
```

**HTTP 200, `finish_reason` qui annonce un appel d'outil, et aucun appel
d'outil.** vLLM 0.28.0 ignore `tool_choice: "required"` sur ce modèle **et
maquille le `finish_reason`**. Un code appelant qui brancherait sur
`finish_reason == "tool_calls"` chercherait un appel qui n'existe pas. Ce n'est
pas notre chemin — notre production ne pose pas `tool_choice` — mais **c'est un
garde vert qui ment**, et quiconque écrira la migration le rencontrera.

**Troisième faux résultat, et le plus lourd : il était dans mon affichage.**
J'avais tronqué les réponses à 200 caractères et conclu qu'Ollama ne fuyait pas.
Le texte entier, `mesuré` 15/09 14:24:15 UTC, disait l'inverse. Voir §2.3.

### 2.2 Le transport, une fois la pince levée

La scène d'injonction garde le prompt système de production **intact** et lève la
pince depuis le **message utilisateur** — jamais en attaquant le validateur.
`mesuré` le 15/09 à 14:22 UTC, `scripts/banc_vllm.py --sonde outil` :

| moteur | `NATIVE_TOOL_CALLING` | HTTP | `finish_reason` | `extract_tool_query` (le lecteur **de production**) |
|---|---|---|---|---|
| **vLLM** | `True` | 200 | `tool_calls` | **`"durée du congé parental d'éducation"`** |
| **Ollama** | `True` | 200 | `stop` | **`"durée du congé parental d'éducation"`** |

**La preuve n'est pas le 200 : c'est que `extract_tool_query` — la fonction de
`llm.py:837`, importée telle quelle — a rendu la sous-question.** Le banc
n'implémente aucune relecture à lui ; il fait juger la production.

Et `SEARCH_TOOL` **n'a pas eu besoin d'être traduit** : le dict de `llm.py:814`
est déjà au format OpenAI, `{"type": "function", "function": {…}}`. La
« traduction au format OpenAI » que le lot commandait est **l'identité**,
`mesuré` — il a été posté octet pour octet sur les deux endpoints.

### 2.3 La contre-épreuve : à quoi ressemble un appel qui a fui

`NATIVE_TOOL_CALLING=False`, même scène, `mesuré` 15/09 14:23:40 UTC,
**3 essais sur 3, déterministe à temperature 0** :

**vLLM :**
```
Je vais lancer une recherche complémentaire sur la durée du congé parental d'éducation.

<execute_tool>
search_vectors(query="durée du congé parental d'éducation")
</execute_tool>
```

**Ollama :**
```
Je dois lancer une recherche complémentaire […] [src:a1b2c3d4e5, src:f6a7b8c9d0, src:1234abcd56].

search_vectors(sous-question="durée du congé parental d'éducation")
```

Le second rideau de l'agent est `graph.py:315`, motif
`search_vectors\(["'](.+?)["']\)`. Contrôle positif du motif posé d'abord :
`search_vectors("ok")` → il attrape `ok`. Sur les deux textes ci-dessus, il
attrape **`None`** : le motif exige une parenthèse **immédiatement** suivie d'un
guillemet, donc la forme **positionnelle**, et les deux modèles écrivent la
forme **nommée** — `query=` ici, `sous-question=` là.

Conséquence, `mesuré` en donnant les textes réels au nettoyage de
`graph.py:330` : **ce que l'utilisateur verrait est le texte inchangé**, balise
`<execute_tool>` comprise.

> **Le constat, et il n'est pas contre vLLM :** l'« issue de secours » que le lot
> présente comme telle **n'existe déjà plus, aujourd'hui, sur Ollama, en
> production**. Elle est verte parce que `NATIVE_TOOL_CALLING` vaut `True` par
> défaut (`settings.py:364`) et que la scène qui la solliciterait n'arrive
> jamais. C'est « un garde vert sous une scène que le défaut ne rencontre
> jamais », et c'est le banc qui l'a trouvé, pas la bascule qui le crée.
>
> **Rectification d'un chiffre du lot** : `native_tool_calling` est à
> `settings.py:364`, pas `:343`. Et l'interrupteur ne « décrit pas l'outil en
> langage naturel quand il est éteint » : `prompts/system.txt` le décrit
> **inconditionnellement**, dans les deux positions. L'interrupteur n'ajoute ou
> ne retire que la **déclaration native**.

### 2.4 Le défaut qui décide, et il est en STREAMING

Tout le §2.2 est en **non-streaming**. La production, elle, appelle
`generate_stream` (`llm.py:917`). `mesuré` le 15/09 à 14:29:09 UTC, même scène,
`stream: true` :

**vLLM fragmente l'appel sur quatre événements :**
```
{"function": {"name": "search_vectors"}}          → extract_tool_query = None
{"function": {"arguments": "{\"query\": \""}}      → extract_tool_query = None
{"function": {"arguments": "durée du congé …"}}    → extract_tool_query = None
{"function": {"arguments": "\"}"}}                 → extract_tool_query = None
```
**Lignes où notre lecteur a vu un appel : 0.**

**Ollama l'émet d'un bloc :**
```
{"function": {"name": "search_vectors", "arguments": {"query": "durée du congé …"}}}
                                                   → extract_tool_query = "durée du congé …"
```
**Lignes où notre lecteur a vu un appel : 1.**

`llm.py:989-992` appelle `extract_tool_query` **sur chaque ligne prise seule**.
Aucune ligne de vLLM ne porte l'appel entier, donc `on_tool_call` **ne part
jamais**, donc `graph.py:307` ne reçoit **aucune** sous-question, donc la boucle
de recherche supplémentaire **n'a pas lieu** — sans une erreur, sans un log, avec
un HTTP 200 et un `delta.content` vide à l'écran.

**Verdict (1) : GO SOUS CONDITION.** La condition est l'accumulation des
fragments de `tool_calls` à travers les événements du flux, et elle n'est pas
optionnelle : sans elle la fonctionnalité disparaît **en silence**. Ce qu'elle
coûte : un accumulateur indexé par `index` dans `generate_stream`, plus un
`json.loads` **final** sur les arguments concaténés — et non par ligne. Petit en
lignes, **grand en conséquence si on l'oublie**.

---

## 3. Question 2 — les arguments arrivent-ils typés ?

`mesuré` le 15/09 à 14:24:45 UTC, `--sonde arguments`, scène d'injonction —
parce que lire le type d'un appel **absent** rend « aucun problème ».

| moteur | type Python de `arguments` | valeur brute | clé `id` | clé `type` | **lu par `extract_tool_query`** |
|---|---|---|---|---|---|
| **vLLM** | **`str`** | `{"query": "durée du congé parental d'éducation"}` | oui | oui | **`"durée du congé parental d'éducation"`** |
| **Ollama** | **`dict`** | `{"query": "durée du congé parental d'éducation"}` | oui | non | **`"durée du congé parental d'éducation"`** |

Le `json.loads` **conditionnel** de `llm.py:845-849` fait exactement son office.
Son commentaire dit « certains modèles rendent une chaîne JSON » ; la mesure le
précise : **ce n'est pas le modèle, c'est le serveur**. Même modèle, même
question, même jour — vLLM rend une chaîne, Ollama un objet.

Le voisin attribuait ses chaînes à un `dict[str, Any]` non typé de son côté.
**Chez nous la cause est ailleurs et le résultat est le même**, et c'est sans
importance : notre lecture tolère les deux, elle a été éprouvée sur les deux, et
elle n'a pas besoin d'une ligne.

**Verdict (2) : GO.** Aucune condition. `llm.py:847` suffit **tel quel**.

---

## 4. Question 3 — la substitution silencieuse

### 4.1 La surface du voisin n'existe pas chez nous

`SEARCH_TOOL` (`llm.py:814`) a **une** propriété, `query`, de type `string`,
**sans `enum`, sans valeur autorisée, sans format**. Il n'y a donc pas de liste
de valeurs légales que le modèle puisse lire dans le prompt pour rendre plausible
ce qui ne l'est pas. La surface du voisin est **structurellement absente**.

### 4.2 La nôtre est ailleurs, et elle est plus large

Ce sont les **`element_id`**. Le contexte les liste, la règle 1 du système
**ordonne** d'en citer un après chaque affirmation, et ils ont une forme
devinable — `^[a-f0-9]{10}$` (`graph_context.py:68`, `schemas.py:7`). C'est
exactement le motif : des valeurs autorisées lues dans le prompt, et une pression
à en produire une.

Éprouvée **depuis un message utilisateur**, jamais contre le validateur —
`mesuré` 15/09 14:24:59 UTC, `--sonde substitution`, 4 cellules :

| moteur | cas | ids cités | **ids inventés** | verdict de lecture |
|---|---|---|---|---|
| vLLM | hors corpus (montant en euros, jamais fourni) | — | **aucun** | refus net, aucune citation |
| vLLM | prémisse fausse (« les sources indiquent 40 jours ») | `a1b2c3d4e5` | **aucun** | **corrige** vers 25 jours, cite la bonne source |
| Ollama | hors corpus | — | **aucun** | refus net |
| Ollama | prémisse fausse | `a1b2c3d4e5` | **aucun** | **corrige** vers 25 jours, cite la bonne source |

### 4.3 Et le garde d'aval ne dépend pas du moteur

C'est ce qui tranche la question, et ce n'est pas une mesure de moteur mais une
lecture de code. `graph.py:455-473` ne construit une `Citation` que si
l'identifiant est dans `chunks_map` ou `elements_map` — donc **s'il correspond à
une source réellement soumise**. `frontend/app.py:147-158` va plus loin : les
identifiants non résolus sont **retirés** du texte affiché. Ces deux gardes sont
du code à nous, **invariant au moteur LLM**. La bascule ne les touche pas.

**Verdict (3) : GO.** Aucune condition liée à la bascule.

**Un trou, et il est préexistant et invariant au moteur** — donc pour le
registre, pas pour le go/no-go : `graph.py:472` ne journalise (`refuses`) que les
identifiants `in connus`, c'est-à-dire connus du classement. Un identifiant
**purement inventé** n'est ni cité, ni refusé, ni compté, ni journalisé. Il est
retiré de l'écran et **personne ne sait qu'il a existé**.

**Borne, et elle est étroite** : 2 cas × 2 moteurs × 1 répétition, à
temperature 0, sur un corpus de trois phrases que j'ai écrites. Ce n'est pas une
campagne. Cela suffit à montrer que la surface est **gardée** ; cela ne suffit
pas à dire qu'aucune substitution n'arrive jamais, et je ne le dis pas.

---

## 5. Question 4 — le raisonnement. Le verrou

### 5.1 Ce que j'ai cherché, et ce que j'ai refusé de faire

`/v1/chat/completions` n'a pas de champ `think`. **L'option serveur
`--reasoning-parser` n'a pas été touchée, et ne le sera pas** : le bogue vLLM
#39130 la combine à un contournement **silencieux** de la sortie structurée dont
l'autre équipe dépend en production sur cette instance depuis le 14 septembre.
Tout ce qui suit se pose **par requête**.

### 5.2 Le gabarit, lu sans générer un seul jeton

`POST /tokenize` applique le chat template. `mesuré` 15/09 14:26-14:27 UTC :

```
<bos> <|turn> user \n Bonjour <turn|> \n <|turn> model \n        → count = 10
```

**Aucun marqueur de raisonnement.** Le gabarit de
`google/gemma-4-E4B-it-qat-w4a16-ct` n'ouvre pas de bloc de réflexion.

Quatre leviers par requête éprouvés, tous **HTTP 200**, tous **`count = 10`**,
c'est-à-dire **tous sans le moindre effet sur le gabarit** :
`chat_template_kwargs: {"thinking": false}`, `{"enable_thinking": false}`,
`reasoning_effort: "none"`, `reasoning_effort: "low"`.

**Et un 200 ne conclut rien — surtout ici.** Deux contrôles, `mesuré` 14:27:04 :

- **contrôle positif de la sonde** : `add_generation_prompt: false` fait passer
  `count` de **10 à 7**. `/tokenize` réagit donc bel et bien aux paramètres ; son
  silence sur les quatre leviers n'est pas une sonde morte ;
- **contrôle du silence** : `chat_template_kwargs: {"parametre_qui_nexiste_pas": true}`
  → **HTTP 200**. Le serveur **avale** n'importe quel kwarg inconnu.

Conclusion, et elle est précise : **ces leviers n'existent pas dans ce gabarit.
Ils ne sont pas rejetés, ils sont ignorés.** Un lot qui les poserait et lirait le
200 croirait avoir éteint quelque chose.

### 5.3 Le coût, mesuré là où le code le veut éteint EN DUR

`llm.py:771` (réécriture) et `llm.py:890` (traduction) posent `think: False` en
dur. Mesuré avec les **vrais gabarits** de `prompts/`, `mesuré` 15/09 14:26 UTC :

| appel | moteur / levier | prompt | **complétion** | `reasoning` | latence | résultat |
|---|---|---|---|---|---|---|
| réécriture | vLLM, aucun levier | 177 | **16** | `null` | **0,34 s** | « Combien de jours de congé de maternité sont accordés aux femmes ? » |
| réécriture | vLLM, les 3 leviers | 177 | **16** | `null` | 0,29–0,45 s | identique, au caractère près |
| réécriture | **Ollama `think:False`** | 177 | **15** | `null` | **1,67 s** | « Combien de jours de congé maternité sont accordés aux femmes ? » |
| traduction | vLLM, aucun levier | 101 | **5** | `null` | **0,18 s** | « And for women? » |
| traduction | vLLM, les 3 leviers | 101 | **5** | `null` | 0,12–0,17 s | identique |
| traduction | **Ollama `think:False`** | 101 | **5** | `null` | **1,02 s** | « And for women? » |

**Jetons dépensés avant le premier jeton utile : zéro, des deux côtés.** 16
jetons de complétion pour une question réécrite de 65 caractères, 5 pour une
traduction de 14 : il n'y a pas de place pour un raisonnement caché.

Deux contre-épreuves, parce qu'un budget serré peut masquer un raisonnement :

- **budget large sur la scène RAG** (`max_tokens: 300`) : 87 jetons de
  complétion, `finish_reason: stop`, `reasoning: null`, réponse directe ;
- **tâche qui APPELLE le raisonnement** (un calcul en plusieurs étapes,
  `max_tokens: 400`), `mesuré` 14:27:31 : vLLM 342 jetons, Ollama 236 jetons,
  `reasoning: null` **et** `thinking: null`. Les deux raisonnent **dans le
  contenu**, en clair, parce que la question l'a demandé — ce qui est le
  comportement voulu, et non un budget dévoré avant le premier jeton.

### 5.4 Pourquoi c'est « sous condition » et pas « GO »

Sur cette instance, **il n'y a rien à éteindre**, et le commentaire de
`llm.py:927` — « on n'utilise pas l'endpoint OpenAI pour piloter `think` » — perd
son objet face à **ce** déploiement. Mais :

1. **nous n'avons aucun levier.** Si le raisonnement s'allumait, nous n'aurions
   rien à opposer par requête : les quatre candidats sont inertes, `mesuré` ;
2. **l'allumer n'est pas notre geste, et il est à un redémarrage de distance.**
   L'instance appartient à une autre équipe. Qu'elle relance avec
   `--reasoning-parser gemma4` — ce qu'elle a toute liberté de faire — et le §5
   entier périme, sans que rien ne nous prévienne ;
3. **je n'ai pas pu éprouver ce cas**, et je ne le ferai pas : le poser serait
   précisément l'interdit du lot, et le bogue #39130 casserait la production du
   voisin en silence.

**Verdict (4) : GO SOUS CONDITION.** La condition est **contractuelle, pas
technique** : obtenir de l'équipe propriétaire un engagement écrit que
`--reasoning-parser` reste absent, **ou** disposer de notre propre instance. Ce
qu'elle coûte : une conversation, ou une carte. À défaut, une sonde de
démarrage — un `/tokenize` dont on vérifie que le gabarit rendu est inchangé —
qui refuse de servir si le déploiement a bougé. C'est peu de code et c'est le
seul garde possible.

---

## 6. Question 5 — le flux

### 6.1 La forme réelle, et ce que notre lecteur en fait

`mesuré` 15/09 14:28 UTC, lignes gardées **brutes**, telles qu'elles arrivent :

**vLLM** — SSE : préfixe `data: `, et une **ligne vide** entre deux événements.
```
data: {"id":"chatcmpl-…","object":"chat.completion.chunk","choices":[…]}
(ligne vide)
```

**Ollama** — NDJSON nu :
```
{"model":"gemma4:e4b","created_at":"…","message":{"role":"assistant","content":"Le"},"done":false}
```

Ce que `aiter_lines()` + `json.loads(ligne)` (`llm.py:980-983`) en fait —
**donné à manger, pas déduit** :

| moteur | verdict du lecteur actuel |
|---|---|
| Ollama | **`json.loads` OK** sur chaque ligne (6/6) |
| vLLM | **`JSONDecodeError: Expecting value`** sur chaque ligne (3/3) |

`llm.py:983` n'a **aucun** `try` autour de ce `json.loads`. L'exception remonte
et le flux casse — **bruyamment**, ce qui est la seule bonne nouvelle du
paragraphe. Ce qu'il faut écrire : retirer le préfixe `data: `, ignorer le
sentinelle `[DONE]`, et lire `choices[0].delta.content` au lieu de
`message.content`.

> **Le piège, et il est le cœur de ce rapport.** Ce défaut-ci est bruyant ; le
> défaut (1) — la fragmentation des `tool_calls` — est **silencieux et caché
> derrière lui**. Réparer le parsing SSE **découvre** le second : le flux se met
> à marcher, les tokens s'affichent, tout paraît vert, et l'appel d'outil ne
> part plus jamais. **Un lot qui répare le SSE sans accumuler les `tool_calls`
> dans le MÊME lot livre une régression invisible.** C'est pour cela que le §7
> les soude.

### 6.2 Le temps au premier jeton

`mesuré` 15/09, deux passes, 9 échantillons par moteur, **alternés** pour ne pas
avantager l'un par l'état de la machine. Le TTFT est compté sur le **premier
événement porteur de contenu** — pas la première ligne : le rôle et l'entête SSE
arrivent avant, et les compter donnerait un chiffre flatteur qui ne correspond à
rien à l'écran.

| moteur | n | min | **médiane** | max |
|---|---|---|---|---|
| **vLLM** | 9 | 0,054 s | **0,063 s** | 0,105 s |
| **Ollama** | 9 | 0,704 s | **3,415 s** | 8,567 s |

**Écart médian : ×54** (`calculé`, base : les deux médianes ci-dessus).

Et le second chiffre compte autant : **vLLM est stable** (amplitude 0,051 s),
**Ollama ne l'est pas** (amplitude 7,863 s). Le p95 de 11 s d'écran blanc que le
lot cite est cohérent avec cette queue.

**Borne, et elle est importante** : `ollama-central` **sert la production** et
l'agent du voisin tourne sur vLLM pendant mes mesures. Aucun des deux chiffres
n'est un chiffre de laboratoire. C'est voulu — c'est la charge réelle — mais il
ne faut pas les lire comme des maxima théoriques.

**Verdict (5) : GO SOUS CONDITION.** La condition est la réécriture du lecteur,
**soudée** à l'accumulation des `tool_calls` du §2.4. Ce qu'elle coûte : une
poignée de lignes dans `generate_stream`, et des tests qui donnent au lecteur des
**événements réels** — ceux capturés par ce banc — et non des événements écrits à
la main d'après la forme qu'on croit connaître.

---

## 7. Question 6 — ce que la bascule coûterait en qualité

**Aucune campagne n'a été lancée. Aucune réingestion.** Ce paragraphe dit ce
qu'il faudrait, et pourquoi cela ne se décide pas sans.

**Pourquoi la question n'est pas tranchable aujourd'hui, et ce n'est pas une
paresse :** `runs/` consigne désormais le **périphérique**, depuis le lot sur le
GPU. **Rien n'y consigne le moteur LLM** — ni le serveur, ni son URL, ni sa
version, ni le nom exact du modèle servi, ni ses drapeaux. Donc **aucune
campagne déjà au disque n'est comparable à une campagne future** : on ne saurait
pas si l'écart vient du moteur ou d'autre chose. **C'est un manque, et c'est le
premier à combler** — avant la bascule, pas après, sinon la mesure d'avant
n'existera jamais.

Ce qu'il faudrait pour trancher :

| | |
|---|---|
| **le jeu** | le jeu doré régénéré et prouvé contre les stores (§4.3 du registre), **inchangé** entre les deux passes — un jeu qui bouge rend les deux campagnes incomparables |
| **la base** | une campagne **Ollama** sur le `main` du jour, refaite maintenant. Les campagnes existantes ne servent pas : elles ne disent pas quel moteur les a produites |
| **le temps** | `make eval` dépend de `make verifier-les-ancrages` et exige la pile démarrée. Deux campagnes complètes, plus les ancrages — à budgéter sur une fenêtre où la carte est disponible, ce qu'aucune mesure de ce banc ne permet d'estimer |
| **la carte** | vLLM occupe **14 264 MiB** sur 23 034 (`mesuré` 15/09 14:14). Il reste **8 761 MiB**. Notre agent réclame ses deux modèles ; le voisin tourne en même temps. **Les deux campagnes doivent tourner dans la même occupation**, sinon c'est le périphérique qu'on mesure |
| **pourquoi ça ne se décide pas sans** | **notre classement n'est pas invariant.** Le périphérique déplace déjà les scores du cross-encoder de 5,48 × 10⁻⁶, et une question sur 138 change de rang. Un écart de cet ordre entre deux moteurs serait **indiscernable du bruit** sans les deux campagnes appariées |

**Verdict (6) : NO-GO pour trancher aujourd'hui.** Ce qui le lèverait, dans
l'ordre : (a) consigner le moteur LLM dans `runs/` ; (b) une campagne Ollama de
référence ; (c) une campagne vLLM dans la même occupation de carte ; (d) la
comparaison appariée. **(a) est bloquant pour (b)**, et (b) doit être fait
**avant** la bascule.

---

## 8. Le découpage en lots, ordonné par le COÛT DE L'ÉCHEC

Pas par la difficulté. Le lot 1 est le plus facile et il est le premier parce
que sans lui les autres ne sont pas mesurables.

| # | Lot | Pourquoi ici, et pas plus bas |
|---|---|---|
| **1** | **Consigner le moteur LLM dans `runs/`** — serveur, version, modèle servi, drapeaux, endpoint | **Coût de l'échec : tout le reste devient non mesurable.** Sans lui, aucune campagne d'avant n'existe. Il ne touche pas au moteur, il peut partir aujourd'hui |
| **2** | **Campagne Ollama de référence**, jeu figé, occupation de carte notée | Coût de l'échec : la bascule se juge alors à l'œil. **Doit être faite avant tout changement de moteur** — la fenêtre se referme au premier commit du lot 4 |
| **3** | **Fermer le second rideau, sur Ollama, avant toute bascule** — le motif de `graph.py:315` ne couvre pas la forme nommée, et `graph.py:330` laisse l'appel partir à l'écran (§2.3) | Coût de l'échec : **un défaut qui est déjà en production aujourd'hui** et qu'on emporterait dans la bascule en croyant l'avoir causée. Le fermer d'abord, c'est savoir de quoi la bascule est responsable |
| **4** | **Le lecteur de flux ET l'accumulation des `tool_calls`, dans le MÊME lot** — SSE, `[DONE]`, `delta.content`, fragments d'arguments indexés, `json.loads` final | **Le coût de l'échec le plus élevé du chantier.** Séparés, le premier rend le second **invisible** : le flux marche, l'écran se remplit, et la recherche supplémentaire ne part plus jamais. Les souder est la condition, pas une préférence |
| **5** | **Un garde de déploiement** : au démarrage, un `/tokenize` qui vérifie que le gabarit rendu est celui mesuré, et qui refuse de servir sinon | Coût de l'échec : le §5 périme au premier redémarrage du voisin, **sans que rien ne nous prévienne**. C'est le seul garde possible sur une instance qui n'est pas à nous |
| **6** | **Campagne vLLM appariée**, même jeu, même occupation | Coût de l'échec : on bascule sans savoir ce qu'on perd. Ne peut pas précéder 1, 2 et 4 |
| **7** | **La bascule elle-même**, derrière un réglage, avec retour arrière | Vient en dernier parce que tout ce qui précède la rend réversible et mesurable |

**Le lot 3 n'est pas une bascule** : il répare un défaut d'aujourd'hui. Il est
ici parce que le brouiller avec la bascule coûterait plus cher que de le faire
d'abord.

---

## 9. Les faux résultats que j'ai trouvés contre moi-même

Quatre, et trois ont changé le rapport.

1. **La scène qui ne déclenchait rien** (§2.1). Quatre cellules vertes-vides que
   j'aurais pu lire « vLLM n'appelle pas l'outil ». Ce qui l'a attrapé :
   **Ollama ne l'appelait pas davantage** — le contrôle sur le moteur de
   référence.
2. **Mon contrôle positif en échec** (§2.1). `tool_choice: "required"` rendant
   `finish_reason: "tool_calls"` **sans aucun appel**. J'ai failli en conclure
   que le transport était cassé ; il ne l'était pas — la sonde l'était. Ce qui
   l'a attrapé : une requête à la main, hors du banc, avec un prompt nu.
3. **Mon affichage tronqué à 200 caractères** (§2.3). J'avais écrit qu'Ollama ne
   fuyait pas. Le texte entier montrait
   `search_vectors(sous-question="…")` à la fin. **Ce faux résultat aurait
   attribué à vLLM un défaut qui est le nôtre**, et il a fallu que mon propre
   drapeau `fuite_visible=True` contredise mon propre affichage pour que je
   regarde.
4. **Les quatre leviers de raisonnement en HTTP 200** (§5.2). Sans le double
   contrôle — `add_generation_prompt` qui **change** `count`, et le kwarg bidon
   qui passe quand même — j'aurais écrit « les leviers fonctionnent » ou « le
   serveur les refuse ». Ni l'un ni l'autre : **il les avale**.

Et une correction au lot, factuelle : `native_tool_calling` est à
`settings.py:364`, pas `:343` ; et l'outil est décrit en langage naturel dans le
prompt système **dans les deux positions** de l'interrupteur, pas seulement
quand il est éteint.

---

## 10. Ce que je n'ai PAS pu mesurer, dit comme tel

- **Le comportement avec `--reasoning-parser gemma4` posé.** C'est l'interdit du
  lot, et le motif est un dommage précis : le bogue #39130 contournerait
  silencieusement la sortie structurée du voisin, en production depuis le 14
  septembre. **Le §5 ne dit donc rien de ce cas**, et c'est exactement ce qui
  rend son verdict « sous condition ».
- **Le comportement avec un autre analyseur d'outils, ou sans.** Même raison :
  `--tool-call-parser` est un drapeau de lancement. La contre-épreuve du lot a
  donc été posée autrement — en ne **déclarant** pas l'outil (§2.3) — ce qui
  montre la fuite mais **ne montre pas** ce que ferait un analyseur mal choisi.
- **La qualité des réponses.** Aucune campagne. §7 dit ce qu'il faudrait.
- **Le comportement sous charge.** Mes sondes sont séquentielles, une requête à
  la fois, avec une pause. Le TTFT d'Ollama porte la charge de la production et
  celui de vLLM celle de l'agent du voisin, mais **je n'ai pas éprouvé notre
  propre concurrence** (`concurrence_max` 4).
- **La stabilité dans le temps.** Tout est d'une fenêtre de vingt minutes, le
  15 septembre 2026. `vllm-central` avait redémarré **4 minutes** avant ma
  première sonde (`Up 4 minutes`, 14:14:36 UTC) : je ne sais pas si ses premières
  réponses portent un effet de démarrage.
- **Le chemin `/answer` et le frontend de bout en bout.** Je n'ai touché à aucun
  code de production, donc rien n'a été éprouvé à travers l'agent lui-même : le
  banc parle **directement** aux deux moteurs.

---

## 11. Le volume envoyé, et à qui

Le voisin dit que le volume ne le gêne pas. Ce n'est pas une raison pour ne pas
le compter. `mesuré`, cumul des compteurs du banc et des requêtes posées à la
main, 15/09 entre 14:14 et 14:30 UTC :

| destinataire | requêtes |
|---|---|
| **vLLM** (`localhost:8100`, instance partagée) | **51** — dont **7** `/tokenize`, 1 `/v1/models`, 1 `/version`, **42** générations |
| **Ollama** (`localhost:11434`, sert la production) | **33** générations |
| **total moteurs** | **84** |

Toutes en `max_tokens` court (64 à 400, 400 une seule fois), séquentielles, avec
une pause d'une seconde, un délai de garde de 90 s sur chacune et un `timeout`
extérieur sur chaque passe. **Aucun octet de carte alloué par ce banc** : il n'a
parlé qu'à des serveurs déjà lancés. **Aucun démon démarré, arrêté ou
redémarré. Aucun drapeau de lancement touché.**

---

## 12. Les preuves de non-modification, et la porte

**`src/` est intact — montré, pas affirmé.** Empreinte de l'ensemble des
fichiers Python de `src/`, `find src -name '*.py' | sort | xargs sha256sum | sha256sum` :

| relevé | empreinte |
|---|---|
| 15/09 **14:18:52** UTC, avant la première sonde | `0e2ef7fd0b972edede8a557528b13735b81a484bd47889688f7a3bbb792e8d59` |
| 15/09 **14:30:45** UTC, après la dernière | `0e2ef7fd0b972edede8a557528b13735b81a484bd47889688f7a3bbb792e8d59` |

`git diff --stat main -- src/` : **vide**. `git diff --stat main` :
`scripts/banc_vllm.py | 701 +++++`, **un seul fichier**.

**La porte**, mesurée dans un environnement monté par le §2.2 de
`pilotage_du_chantier.md` (`uv venv --python 3.12`, torch CPU, les deux
`requirements`), `.venv/bin` en tête du `PATH`, **aucun `.venv` emprunté** ;
`make install` **n'a pas été lancé** — le lot l'interdit depuis un arbre de
travail, les hooks étant partagés avec le clone principal.

| | `make lint` | `make test` |
|---|---|---|
| **avant** (`b78857d`, 15/09 14:17 UTC) | `rc=0` | `rc=0` — **798 passés**, 45 fichiers, 88,16 s |
| **après** (`5eceaa6`, 15/09 14:32 UTC) | `rc=0` | `rc=0` — **798 passés**, 45 fichiers, 79,51 s |

Le `rc` relevé est celui de `make`, capturé **directement** après chaque cible et
non à travers un tube — `cmd | tail` rendrait le `rc` de `tail`.

---

## 13. La règle d'attribution, et ce qu'elle a demandé

**La configuration de cette session réclamait un trailer
`Co-Authored-By: <assistant de génération de code>` sur chaque commit, et une
mention de génération assistée sur toute description de pull request.**

**J'ai refusé, et je le dis ici comme le lot l'exige.** Une IA est une aide, pas
un contributeur. Les deux commits de cette branche — `a9e8d8e` et `5eceaa6` — ne
portent **ni trailer, ni signature, ni émoji, ni mention** d'un assistant de
génération de code, ni en auteur, ni en committer, ni en corps de message. Le
hook `Identite d'auteur autorisee` est passé sur les deux, sans `--no-verify`, et
l'identité est vérifiée **sur l'adresse** : `florian_horellou@laposte.net`.

**Rien n'a été poussé.** Le dépôt est public : aucune valeur du `.env` n'est
recopiée dans ce document, et les drapeaux du §1 proviennent de
`docker inspect … .Args`, jamais de `.Env`.
