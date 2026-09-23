# Axes d'amélioration — rag-agent-chat

> **CE DOCUMENT EST UN REGISTRE DATÉ, ET SES CONSTATS NE SONT PAS RÉÉCRITS.**
> Le moteur servi est **vLLM depuis le 17 septembre 2026**, et le lot 28 a retiré
> le support de l'autre moteur du code. Les sections `## 1. Corrigé` et
> `## 4. Chantier ouvert le 3 septembre 2026` le nomment encore : ce sont des
> constats pris à une date, chacun par une commande dont la sortie a été lue, et
> les réécrire ferait dire à une mesure autre chose que ce qu'elle a dit. C'est
> la même règle que pour `documentation/audits/`, `documentation/campagnes/` et
> `runs/` — et c'est pourquoi ce fichier est nommé dans le périmètre d'exclusion
> du garde `test_le_nom_de_l_ancien_moteur_ne_revient_pas`, avec sa raison.
>
> Ce qui décrit le fonctionnement **actuel** est, lui, à jour :
> [moteur_llm.md](moteur_llm.md) en est le site canonique.

Document remis à plat le 2 août 2026. La version précédente cochait « corrigé »
des correctifs absents du code (`_window_around`, `RERANK_MIN_SCORE`,
`section_header_text`, alias `[src:N]`) et listait comme ouvert `tools.py`,
supprimé depuis. Un document d'audit faux est pire que pas de document : chaque
ligne ci-dessous est vérifiable dans le code ou contre les services.

---

## 1. Corrigé

### 1.1 La remontée `PARENT_OF` ne remontait rien — `graph_context.py`

Sous `REVERSELY`, nGQL fait renvoyer par `dst(edge)` le nœud de **départ**, pas
le voisin atteint : c'est `src(edge)` qui porte le parent. `_find_parent`
retournait donc l'élément lui-même, la boucle de remontée tournait dix fois sur
place, et `reconstruct_section` rendait une section vide.

La reconstruction du contexte par le graphe — la promesse centrale du projet —
était sans effet depuis l'origine. Vérifié contre le graphe en production :

```
MATCH (p)-[:PARENT_OF]->(c) WHERE id(c)=="1730443c8f"  -> "ffa6bda17d"
GO FROM "1730443c8f" ... REVERSELY YIELD dst(edge)     -> "1730443c8f"
GO FROM "1730443c8f" ... REVERSELY YIELD src(edge)     -> "ffa6bda17d"
```

### 1.2 Les citations perdaient le nom du document — `graph_context.py`, `graph.py`

La remontée s'arrêtait au premier `SectionHeader`. Comme l'ingestion rattache
tout élément à son en-tête et tout en-tête au `Document`, elle s'arrêtait donc
systématiquement au premier saut : le nœud `Document` n'était jamais atteint, et
`node_postprocess` — qui y cherchait le nom du fichier — laissait `filename`
vide. Toutes les citations issues du graphe s'affichaient `****, p.42`.

La remontée note désormais la section puis poursuit jusqu'à la racine.
`SectionContext` expose `filename` et `section_title` au lieu de laisser ses
appelants les deviner depuis les breadcrumbs.

### 1.3 VIDs de documents rejetés — `graph_context.py`

Les VIDs de documents dérivent du chemin (`doc_htms/Practical MLOps/4. …`) :
séparateurs, espaces, accents, jusqu'à 256 octets. Le motif de validation les
rejetait tous, ce qui vidait les propriétés du nœud `Document`.

Ils ne viennent jamais de l'utilisateur — ils sont découverts en remontant le
graphe : ils sont **échappés** plutôt que filtrés. La validation stricte reste
sur le seul format qu'un appelant peut fournir, le hash de 10 hexadécimaux.

### 1.4 Contexte non borné — `graph_context.py`, `llm.py`

Deux causes cumulées, désormais traitées :

- `_get_children` renvoyait tous les enfants. Un document sans `SectionHeader`
  rattache ses éléments au nœud `Document` : la « section » reconstruite était
  le document entier. `_window_around` borne à `CONTEXT_WINDOW_BEFORE/AFTER`
  éléments autour de l'ancre.
- `num_ctx` n'était jamais passé à Ollama : la fenêtre dépendait du serveur
  (8192 embarqué, 32768 central), et le même prompt donnait deux comportements.
  Elle est explicite, et `fit_contexts` écarte les sources qui dépassent le
  budget, avec un log qui dit combien et pourquoi.

Mesuré sur une question réelle : 5 sections reconstruites font 13 961
caractères pour un budget de 12 544 — une source écartée explicitement, là où
Ollama en tronquait le **début** en silence.

Ce budget de 12 544 caractères était lui-même faux : il ne comptait ni
l'historique de conversation, ni la source qui dépasse seule la fenêtre.
Cf. §1.13 et §1.14.

### 1.5 Éléments multi-chunks — `retriever.py`, `frontend/app.py`

Un bloc long produit des chunks `abc#0`, `abc#1` partageant leur `element_id`.
Ils se ressemblent, donc le reranker les remontait ensemble : plusieurs places
du top-K pour un seul passage, et deux `st.checkbox` de même `key` — soit une
`StreamlitDuplicateElementKey`. `dedupe_by_element` s'applique **avant** la
troncature au top-K.

### 1.6 Documents homonymes fusionnés — `schemas.py`, `retriever.py`

`ChunkResult` ignorait `collection`, `source_path` et `section_title`, pourtant
écrits par l'ingestion. Le groupement se faisait sur le seul nom de fichier :
la « Préface » de deux ouvrages devenait un seul document. Le groupement porte
sur `source_path`, et l'UI affiche « Ouvrage › Chapitre ».

### 1.7 Scores de rerank affichés comme des probabilités — `retriever.py`, `frontend/app.py`

`ms-marco-MiniLM-L6-v2` sort des logits non bornés. Le frontend appliquait des
seuils à 0.5 / 0.2 : une source pertinente à −2.0 ressortait en rouge et
repliée. Le champ `relevance` porte la sigmoïde du logit, affichée en
pourcentage.

### 1.8 Sessions LangGraph sans purge — `api/main.py`

Le checkpointer en mémoire ne purge rien : chaque question laissait ses chunks,
ses embeddings et ses contextes reconstruits jusqu'au redémarrage. Un registre
borne les sessions en âge (`SESSION_TTL_SECONDS`) et en nombre
(`MAX_LIVE_SESSIONS`).

### 1.9 « Avant / après » — `graph_context.py`

`reconstruct_section` ne récupérait que la section de l'élément. `_find_sibling`
atteint la section précédente et la suivante en encadrant la propriété
`sequence` de l'arête **sous le parent réel de la section** : leur
queue et leur tête entrent dans le prompt, dans des blocs explicitement
étiquetés pour que le LLM les distingue de la section trouvée.

### 1.10 Légendes des illustrations — `graph_context.py`

L'ingestion relie chaque `Caption` à l'illustration qui la précède par une arête
`DESCRIBES`. L'agent ne la traversait jamais : le LLM recevait un `[img:ID]`
muet et devait juger seul de sa pertinence. La légende est désormais rattachée
au visuel dans le markdown.

### 1.11 `CONTEXT_DEPTH` sans effet — `settings.py`

Le paramètre était lu nulle part, et ne pouvait rien faire. **Le motif écrit ici
était « l'ingestion n'imbrique pas les titres, il n'y a aucun niveau à
remonter » : il est MORT depuis le 2 septembre 2026** — le graphe imbrique, 583
en-têtes sur 746 ont un en-tête pour parent (§4.6). Supprimé et remplacé par les
bornes de fenêtrage, qui décrivent ce qui est réellement réglable.

**Ce qui reste vrai** : le paramètre n'était lu nulle part, donc sa suppression
n'a rien retiré au comportement. **Ce qui est à rouvrir** : il y a désormais des
niveaux à remonter, et la question de savoir si l'agent doit pouvoir borner la
profondeur du fil d'Ariane est une **décision de plan**, pas une ligne à écrire.
*Une règle survit à son motif* — et celle-ci a survécu au sien pendant que
personne ne relisait la phrase qui le portait.

### 1.12 Tests de la logique métier — `tests/unit/`

Le projet n'avait de tests que sur les schémas. La suite couvre désormais la
logique qui casse en silence : résolution des citations et des images,
échappement des VIDs, fenêtrage du contexte, budget de fenêtre, déduplication
des éléments multi-chunks, profondeur d'historique par route.

Le décompte vit dans [tests.md](tests.md), qui est régénéré à chaque lot — le
répéter ici en faisait un chiffre périmé de plus.

### 1.13 Le budget de contexte ignorait l'historique — `llm.py`, `api/main.py`

`context_budget_chars` forfaitisait à 512 tokens « le prompt système, le gabarit
et l'historique ». L'historique n'était **jamais** compté : six messages sont
acceptés, chaque réponse assistante peut atteindre `LLM_MAX_TOKENS`, et
`Message.content` n'avait aucune borne. Le forfait était dépassé d'un ordre de
grandeur.

Mesuré avant correctif, sur six messages de 3 000 caractères et deux sources de
12 000 : **31 380 caractères de prompt pour une fenêtre utile de 14 336**, soit
2,2 fois la fenêtre. Ollama tronque alors par le **début** — il jette donc le
message système, c'est-à-dire « cite chaque affirmation », « ne réponds jamais
au-delà des sources », « dis-le si tu ne trouves pas ». Le garde-fou
disparaissait exactement quand la conversation devenait assez longue pour en
avoir besoin, et `fit_contexts`, écrit pour ce mode de panne, ne couvrait que
les sources.

Le budget se calcule désormais sur ce qui est réellement dans le prompt : prompt
système lu, gabarit rendu sans ses sources (mesuré, donc une retouche du gabarit
s'y répercute), historique retenu, encadrement de chaque source, balises de tour.
Le ratio de 3,5 caractères/token reste une estimation, mais il s'applique à
**toutes** les parties du prompt — c'était l'application partielle qui trompait,
pas le ratio.

`fit_history` borne l'historique à `HISTORY_WINDOW_SHARE` de la fenêtre utile et
garde les **tours** les plus récents : sens inverse des sources, c'est le dernier
échange qui situe la question. La coupe porte sur des tours et non des messages —
couper par message laissait passer une réponse sans la question à laquelle elle
répondait, soit un prompt `['system', 'assistant', 'user']` qu'un gabarit de chat
strict sur l'alternance refuse. Le partage est un **forfait** : arbitrer entre
historique et sources demanderait une mesure de la qualité multi-tour (§2). `fit_prompt` devient le point d'entrée unique, appelé une seule fois par
génération : `node_generate` récupère le budget appliqué par le rappel `on_fit`
et le publie dans l'état du graphe, d'où `/answer` lit ses `dropped_contexts`.
L'endpoint le recalculait — chaque troncature journalisée deux fois, le gabarit
rendu une fois de plus par candidate, et surtout un chiffre publié à la campagne
d'évaluation qui pouvait dériver de celui qui avait atteint le LLM.

Le refactor avait laissé cette chaîne sans test : renvoyer `0` en dur depuis
`node_generate`, ou ne jamais appeler `on_fit`, gardait la suite entièrement
verte. Elle est désormais exercée sur le vrai `node_generate` et le vrai
`generate_stream`, seule la couche HTTP étant simulée, au niveau du nœud comme au
niveau de l'endpoint. C'est le nombre que la campagne publie sous
`contextes_ecartes`, et `runs/README.md` annonce qu'il doit monter : cassé, il se
lirait « aucune source écartée ».

La déclaration de l'outil `search_vectors` y entre aussi : `tools` n'est pas un
canal séparé pour le modèle, Ollama le rend dans le prompt via le gabarit de
chat. 417 caractères que rien ne comptait — le même trou que le forfait, à plus
petite échelle.

L'encadrement de chaque source dans le gabarit — séparateurs, numéro,
identifiant, fil des titres — est **mesuré** source par source, et facturé au
moment où la source est retenue. Un premier correctif le forfaitisait à 200
caractères et le réservait sur toutes les **candidates** : dix candidates dont
six retenues immobilisaient la place de quatre sources jamais rendues, et une
septième qui aurait tenu se faisait écarter. Mesuré : sept candidates en gardaient
sept, dix n'en gardaient plus que six. L'encadrement réel va de 34 caractères
sans fil des titres à 275 avec cinq niveaux — un forfait unique est faux dans les
deux sens selon le document.

Budget de sources à `8192 / 4096` : **12 444** caractères au premier tour,
**9 908** avec trois tours de 600 caractères par message, dont un tour écarté par
`fit_history`.
Contre 12 544 constants auparavant, appliqués au seul `markdown` : le budget est
donc légèrement plus serré à un tour, et **c'est correct**. L'ancien ignorait
1 892 caractères de prompt système, de gabarit, de balises de tour et de
déclaration d'outil qui étaient bel et bien dans le prompt, plus l'encadrement de
chaque source.

Vérifié sur un cas que l'ancien budget acceptait : cinq sources de 2 500
caractères, soit 12 500 ≤ 12 544. Le prompt réellement envoyé faisait **15 062
caractères pour une fenêtre utile de 14 336** — 726 de trop, soit **208 tokens qui
rognaient la génération sans le dire**. À 4 304 tokens estimés, on dépasse la
fenêtre de prompt (4 096) mais pas `num_ctx` (8 192) : Ollama ne tronque pas, il
n'accorde plus que 3 888 tokens à la génération au lieu des 4 096 demandés. C'est
la seconde zone d'avertissement de `log_prompt_measure` (§1.15) ; la troncature par
le début est le régime au-delà de `num_ctx`, celui des 31 380 caractères
ci-dessus.

La comptabilité, parce que `sum(len(content))` donne 14 577 et non 15 062 : les
contenus des messages font 14 577, la déclaration de l'outil `search_vectors` 417,
et les balises de tour des deux messages 68.

La reprise n'en retient que quatre, pour 12 428 caractères. Écarter cette
cinquième source n'est pas une perte : c'est le défaut qui disparaît.

La formule complète est dans [llm.md](llm.md).

### 1.14 La source unique trop grosse était transmise entière — `llm.py`

`fit_contexts` garde la première source même si elle dépasse seule le budget :
mieux vaut une source amputée que zéro source, et ce choix est assumé. Mais elle
était transmise **entière** — donc c'était Ollama qui coupait, par le début du
prompt. Le mode de panne que la fonction existe précisément pour éviter. Une
section sans `SectionHeader` y arrive : ses éléments sont rattachés au nœud
`Document`, la fenêtre en retient treize, et les textes intégraux sont relus dans
l'index.

La coupe se fait désormais dans la fonction, par la **fin**, avec un log qui dit
de combien et une marque dans le markdown — sans elle, le modèle conclut sur un
texte tronqué comme s'il était complet.

Elle recule jusqu'à la fin du dernier marqueur `[src:ID]` complet. Trancher à un
index de caractère brut amputait l'identifiant — `[src:00000000` — que le
post-processing ne résout plus, ou qui correspond à un **autre** élément : le
mode de panne d'IMP-6 déplacé d'Ollama vers `_truncate`, dans un dépôt dont les
citations sont l'objet même. Un fragment d'élément privé de son marqueur ne
serait de toute façon pas attribuable.

Le docstring annonçait par ailleurs « c'est la queue de la liste qui saute »,
alors que le `continue` implémente un remplissage **au mieux** : une petite
source après une grosse écartée est conservée. Le docstring est aligné sur le
code, et le test distingue les deux comportements — à tailles égales ils sont
indistinguables, ce que l'ancien test ne voyait pas.

### 1.15 Le prompt réel n'était jamais mesuré — `llm.py`

Le dernier événement du flux Ollama — celui qui porte `done: true` — contient
`prompt_eval_count` : le nombre **réel** de tokens du prompt. La boucle sortait
sur `done` sans le lire. Deux conséquences : le ratio caractères/token sur lequel
tout le budget repose restait une devinette qu'aucune mesure ne corrigeait, et un
prompt qui dépassait `num_ctx` ne laissait **aucune trace** — Ollama le tronque
en silence.

Chaque génération journalise maintenant l'estimation, le décompte réel, l'écart
et le ratio qui aurait rendu l'estimation exacte. C'est ce qui permettra de
calibrer `_CHARS_PER_TOKEN` sur des campagnes réelles au lieu de le poser au jugé.

Deux pièges dans la façon dont Ollama compte, tous deux traités. Un premier
correctif avertissait sur `prompt_eval_count > num_ctx` : condition
structurellement inatteignable, Ollama tronquant le prompt **avant** de
l'évaluer — le détecteur du mode de panne ne pouvait pas voir le mode de panne.
Les `WARNING` portent désormais sur les deux zones qui parlent : un décompte qui
affleure `num_ctx` (troncature très probable) et un décompte au-delà de la
fenêtre de prompt (la génération perd ses `num_predict` en silence). Et le cache
KV d'Ollama ne fait réévaluer que le préfixe non caché : au deuxième tour d'une
conversation, la mesure ne décrit plus le prompt, elle est donc écartée de la
calibration — sans quoi le ratio fondrait à chaque tour.

### 1.16 La surface d'entrée n'était pas bornée — `api/schemas.py`, `frontend/app.py`

`question` était plafonnée à 2000 caractères ; `Message.content` n'avait aucune
borne et les trois schémas exposant `chat_history` acceptaient une liste de
longueur quelconque. C'était le vecteur du §1.13, et une consommation de
ressources non bornée sur un serveur d'inférence **partagé** avec d'autres
projets.

`MAX_MESSAGE_CHARS` vaut 14 336 caractères, soit le plafond de génération
lui-même (`LLM_MAX_TOKENS` à 3,5 caractères/token) : une réponse que le modèle
pouvait légitimement produire doit pouvoir revenir dans l'historique au tour
suivant, sans quoi la borne casserait la conversation en 422 — pire que le défaut
corrigé. `MAX_HISTORY_PAYLOAD` vaut 50 messages, assez pour un fil entier.

Ce que ces deux bornes protègent, exactement : la lecture et le parse de la
requête, au pire ~700 Ko de corps contre une liste sans borne auparavant. **Pas**
le serveur d'inférence — il ne voit jamais plus que ce que `fit_history` retient,
soit `HISTORY_WINDOW_SHARE` de la fenêtre de prompt. Un message de 14 336
caractères est donc accepté puis systématiquement écarté du prompt : c'est voulu,
refuser vaudrait moins bien que tronquer.

La borne qui gouverne le prompt reste `MAX_HISTORY_MESSAGES = 6`, ce que l'API
soumet effectivement au LLM et d'où dérive le budget. Les trois `[-6:]` littéraux
de `main.py` passent par la constante, et le frontend n'envoie plus que ces six
messages au lieu du fil complet — il duplique la constante, faute de pouvoir
importer le schéma, et un test échoue si les deux divergent.

### 1.17 `LLM_NUM_CTX` déclaré à deux valeurs — `README.md`, `llm.md`

`README.md` et `documentation/llm.md` annonçaient `32768`, `.env.example` et
`settings.py` valaient `8192` : un facteur quatre sur la capacité annoncée, dont
le budget de sources dérive directement. La doc est alignée sur **8192**, la
valeur qui s'exécute. Monter à 32768 quadruple le cache KV et le coût de
préremplissage sur un déploiement dont la latence de génération est déjà à 12,4 s
au p95 : c'est un changement qui se mesure par une campagne, pas qui se décrète
dans une table.

### 1.18 `Message.role` non contraint — `api/schemas.py`

`role` était un `str` libre, et `_build_messages` le recopie tel quel dans le
prompt. Un client pouvait donc poster `{"role": "system", …}` dans
`chat_history` et glisser un **second message système** à côté du vrai — celui
qui porte « cite chaque affirmation », « ne réponds jamais au-delà des sources »,
« dis-le si tu ne trouves pas ».

C'est le défaut de §1.13 par une autre route : la troncature jetait ces règles,
une injection de rôle les contredit. Dans les deux cas le garde-fou disparaît
sans laisser de trace dans la réponse.

`Literal["user", "assistant"]`. Vérifié avant de contraindre : rien dans le dépôt
ne construit un `Message` avec un autre rôle — ni le frontend, ni les fixtures
dorées, ni `scripts/evaluate.py`. Les `{"role": "system"}` restants sont des
dictionnaires de charge utile Ollama, pas des `Message`.

### 1.19 L'image du frontend ne suivait pas les versions déclarées — `Dockerfile.frontend`

`Dockerfile.frontend` réinstalle ses dépendances à la main, sans lire
`requirements.txt`. Elles avaient divergé de deux versions mineures — streamlit
1.44.1 contre 1.60.0, pydantic 2.11.4 contre 2.13.4 : l'image ne tournait pas sur
ce que le dépôt déclare tester, et le badge du README annonçait 1.60.

C'est le vieillissement silencieux décrit dans
[SECURITY.md](SECURITY.md#dépendances) — « aucun outil ne signale une version qui
vieillit ». Les versions sont alignées, et un test échoue si les deux fichiers
divergent à nouveau.

### 1.20 La purge des sessions n'aboutissait jamais, et le journal affirmait le contraire — `api/main.py`, `agent/sessions.py`

Trois défauts superposés, du plus visible au plus coûteux.

**L'appel.** `_register_thread` appelait `checkpointer.delete_thread(tid)`, la
méthode **synchrone** d'`AsyncSqliteSaver`, depuis `chat_start` qui est
`async def` — donc depuis le fil de la boucle d'événements. La bibliothèque
refuse explicitement ce cas et lève `asyncio.InvalidStateError`. Reproduit hors
conteneur, avec un vrai `AsyncSqliteSaver` sur un fichier temporaire :

```
delete_thread  : asyncio.exceptions.InvalidStateError: Synchronous calls to
                 AsyncSqliteSaver are only allowed from a different thread.
lignes checkpoints après delete_thread  : 1
lignes checkpoints après adelete_thread : 0
```

L'exception hérite d'`Exception`, donc le `except Exception: logger.debug(…)`
qui l'entourait l'absorbait, et `LOG_LEVEL=INFO` — la valeur par défaut —
l'effaçait. `_register_thread` est devenu `async` et attend `adelete_thread`.

**Le journal.** La ligne `INFO « Sessions purgées : N (restantes : M) »` était
journalisée juste après, et comptait les **candidates**, jamais les
suppressions. Un exploitant qui vérifiait que la purge tourne lisait une
affirmation contraire aux faits. Le nombre journalisé est désormais celui des
suppressions abouties (`purger` rend « supprimées, échecs » et non
« tentées »), un échec sort en WARNING avec sa trace — premier échec puis
rappels tous les 20, la forme posée au §1bis — et `/health` publie
`sessions.purged` et `sessions.failures`. La purge est vérifiable **de
l'extérieur**, sans lire les logs, ce qui est le seul remède au défaut qui se
déclare résolu.

**La portée, qui était le vrai défaut.** Même l'appel réparé, la purge ne
touchait que ce que le registre **en mémoire** `_live_threads` connaissait :
toute session antérieure au dernier redémarrage lui était invisible et restait
sur le disque indéfiniment. C'était la croissance non bornée, et `(a)` ne la
réglait pas.

Le registre vit maintenant dans la base du checkpointer elle-même
(`src/agent/sessions.py`, table `sessions_agent`). Trois raisons, dans cet
ordre : il survit au redémarrage, donc il atteint une session qu'aucun
processus vivant n'a jamais vue ; il partage exactement la durée de vie de ce
qu'il décrit, donc les deux ne peuvent pas dériver ; il ne dépend d'aucun
réglage étranger. Ce dernier point a écarté une solution tentante : la base de
capture d'usage porte bien `thread_id` et `started_at` par interaction, mais
elle est désactivable par `USAGE_CAPTURE`, et la purge du checkpointer serait
devenue conditionnelle à un drapeau sans rapport avec elle.

Au démarrage, les sessions présentes dans `checkpoints` mais absentes du
registre sont **adoptées**, horodatées à maintenant faute de connaître leur âge
— le checkpointer ne garde pas de date de création lisible sans décoder le
msgpack de chaque ligne. Sans adoption, une session écrite avant que ce
registre n'existe n'était plus atteignable par rien.

**Ce qui n'a pas été fait, délibérément :** aucune purge totale au démarrage.
Le checkpointer est sur disque précisément pour qu'une session en attente de
sélection survive au redémarrage de l'API, et vider la base au démarrage
détruirait la fonctionnalité pour corriger la fuite. Un test de non-régression
le garde.

Trouvé en écrivant les tests : la session **en cours de création** était sa
propre candidate. Elle est inscrite avant que le graphe ne tourne — pour qu'un
`ainvoke` qui écrit ses checkpoints puis échoue laisse quand même une session
atteignable — donc son horodatage précède le « maintenant » de la purge qui
suit. Elle est désormais épargnée explicitement.

### 1.21 L'index lexical se déclarait prêt sur un corpus périmé — `retriever.py`, `api/main.py`

`_build_lexical_index` construisait une fois, au premier besoin, et aucun
chemin ne reconstruisait — `reset_connection()` ne vide que le cache de
collection.

Or l'ingestion est un service **séparé** qui écrit dans ChromaDB pendant que
l'agent tourne. Un document ingéré après le démarrage restait trouvable en
recherche dense — la requête part à Chroma à chaque fois — et devenait invisible
en recherche lexicale jusqu'au prochain redémarrage. La recherche devenait
silencieusement **asymétrique**, tandis que `/health` continuait d'annoncer
`index_lexical: true`. Il l'était : il décrivait un corpus qui n'existait plus.

Le dépôt avait déjà résolu ce problème ailleurs — `minio_client.is_allowed`
relit la liste des objets autorisés sur échec, avec le commentaire « un document
fraîchement ingéré apporte de nouvelles illustrations, et l'agent ne redémarre
pas pour autant ». Le raisonnement n'avait pas été appliqué ici.

Deux réponses, qui ne font pas double emploi :

- **`POST /reindex` est un contrat.** L'ingestion l'appelle en fin de pipeline ;
  il rend le nombre de chunks indexés, confrontable à ce qu'elle vient
  d'écrire. Endpoint `def`, donc servi par le threadpool : son coût est payé par
  le pipeline qui appelle, jamais par une requête utilisateur.
- **La comparaison des comptes est un filet**, pour l'ingestion qui n'appelle
  pas. `lexical_stale()` confronte `collection.count()` au nombre de chunks
  indexés — le compte était déjà lu au moment de la construction, la
  comparaison ne coûte donc rien de neuf. Et c'est bien un filet, pas une
  garantie : **un corpus dont on a retiré autant de chunks qu'on en a ajouté
  affiche le même compte.** C'est écrit dans le docstring de la fonction, parce
  que c'est la limite qui justifie l'existence de `/reindex`.

Les appels concurrents à `/reindex` sont **fusionnés** et non sérialisés : celui
qui arrive pendant une reconstruction attend son issue et rend sa taille. Le
verrou de `LexicalIndex` sérialise, il ne fusionne pas — six appels simultanés
faisaient six parcours du corpus à la queue leu leu, chacun mobilisant un fil du
threadpool FastAPI pendant la durée d'un parcours complet, et les endpoints de
recherche partagent ce threadpool.

Trouvé en relisant l'endpoint. Le test asserte
`collection.lectures == lectures_apres_construction + 1` après six fils
concurrents : une seule lecture s'ajoute à celle de la construction initiale.
Avant correctif il en comptait sept — 1 construction + 6 réindexations
sérialisées — donc l'assertion échouait sur `7 == 2`. Ce `7 == 2` est le message
d'échec de pytest, pas une assertion du code : il se lit comme une absurdité
sortie de son contexte, et une version antérieure de ce document le citait comme
si le test le contenait.

La reconstruction déclenchée par le filet tourne dans un fil démon : ses
~9 secondes (chiffre non mesuré, cf. §2) ne doivent pas être payées par la
requête qui découvre la dérive, qui n'a pas participé à l'ingestion. L'index périmé continue de servir pendant ce
temps — dégradé, pas absent, et il ne décrit alors qu'un corpus plus petit que le
vrai.

`/health` déclare désormais `index_lexical: false` sur un index périmé. Les deux
états — pas encore construit, construit sur un corpus disparu — sont
indistinguables pour l'utilisateur, puisque la recherche est amputée dans les
deux cas ; mais seul le faux le dit. Un compte de collection **illisible** n'est
pas traité comme une péremption : Chroma injoignable est déjà rapporté par
`services.chromadb` dans la même réponse, et le déduire une seconde fois ici
transformerait une panne de store en reconstructions inutiles.

### 1.22 Deux requêtes simultanées chargeaient le corpus deux fois — `retriever.py`, `lexical.py`

`_lexical_search` testait `if not _lexical_index.ready` puis appelait la
construction **hors verrou**. `LexicalIndex.build` verrouillait bien, mais la
lecture de tout le corpus depuis Chroma et la tokenisation se faisaient en
amont.

Les endpoints de recherche sont des `def` et non des `async def` — donc servis
par le threadpool FastAPI. N requêtes arrivant avant que l'index soit prêt
déclenchaient N lectures complètes du corpus et N constructions de BM25 : N fois
le temps, N fois la mémoire, N−1 résultats jetés. La première requête coûte déjà
~9 secondes (chiffre non mesuré, cf. §2) ; deux utilisateurs qui ouvrent
l'interface après un redéploiement n'est pas un cas exotique.

`LexicalIndex.ensure` prend la lecture **en rappel** et l'exécute sous son
verrou. Mesuré par le test de serrage : huit requêtes concurrentes faisaient
huit lectures du corpus, elles en font une (`assert 8 == 1` sur le code
d'origine). Le compteur `LexicalIndex.constructions` est exposé pour cela — un
test qui constate que l'index *finit* construit est vert des deux côtés du
défaut.

Trouvé en corrigeant, et corrigé aussi : l'index BM25 et la liste des
identifiants qu'il numérote vivaient dans deux attributs, affectés l'un après
l'autre. Une recherche qui s'intercalait entre les deux lisait les rangs du
**nouveau** BM25 dans l'**ancienne** liste — donc les mauvais chunks, ou un
`IndexError` si la liste a rétréci. La fenêtre n'existait pas tant que l'index
était construit une seule fois pour toutes ; elle s'ouvre dès qu'une
reconstruction a lieu pendant que le service répond, c'est-à-dire dès §1.21. Un
tuple remplacé d'un seul coup la referme.

### 1.23 Une fonction du module graphe contournait la reconnexion — `graph_context.py`

`_get_node_properties` appelait `_get_pool().execute(...)` directement au lieu de
passer par `_execute`. Elle perdait donc les deux choses que `_execute` apporte :
la réouverture du pool après un redémarrage de NebulaGraph, et le journal de
l'erreur nGQL quand la requête est refusée.

C'est le chemin le plus chaud du module — remontée vers le `Document`, recherche
de section voisine jusqu'à cinq fois par direction, titre de chaque voisine.
Après un redémarrage du graphd, les autres chemins se rétablissaient ; celui-là
remontait l'exception jusqu'au `try/except` par élément de
`node_reconstruct_context`, et la source **disparaissait silencieusement de la
réponse**. Un nGQL refusé, lui, rendait `{}` sans un mot : l'appelant voyait un
nœud sans propriétés, indistinguable d'un nœud inexistant.

La seule raison de ne pas utiliser `_execute` était réelle : la fonction a besoin
du `ValueWrapper` de vertex brut, que `_to_primitive` aplatirait en chaîne.
`_execute_raw` rend le `ResultSet` non converti avec la même logique de reprise
et le même journal ; `_execute` s'appuie dessus pour la conversion en dicts. Il
n'y a plus qu'un seul point de passage vers le pool.

### 1.24 Balayage des absorptions larges — tout `src/`

`except Exception: logger.debug(...)` est le mécanisme exact qui a caché le
§1.20 pendant toute la vie du projet. Inventaire de toutes les absorptions
larges de `src/`, et décision écrite pour chacune. Le but n'était pas qu'elles
disparaissent, mais qu'aucune ne reste sans décision.

**24 sites** sur `b456ab1` — un `except Exception` ou `except BaseException` nu,
ou un `except:` sans type. Le décompte est reproductible :

```bash
python3 - <<'EOF'
import ast, subprocess
for f in ("src/agent/graph.py","src/agent/graph_context.py","src/agent/llm.py",
          "src/agent/minio_client.py","src/agent/retriever.py","src/agent/usage.py",
          "src/api/main.py","src/agent/sessions.py"):
    r = subprocess.run(["git","show",f"b456ab1:{f}"], capture_output=True, text=True)
    if r.returncode: continue
    for n in ast.walk(ast.parse(r.stdout)):
        if isinstance(n, ast.ExceptHandler):
            t = n.type
            if t is None or (isinstance(t, ast.Name) and t.id in ("Exception","BaseException")):
                print(f"{f}:{n.lineno}")
EOF
```

Les sites sont désignés par fichier et fonction, pas par numéro de ligne : un
numéro se périme au premier commit suivant, et ce document promet des lignes
vérifiables.

Répartition : **5 resserrées**, **4 dont le journal a changé de niveau ou de
message**, **14 conservées** avec justification écrite au site, et **1
supprimée** — celle de `_register_thread` dans `main.py`, l'absorption du §1.20, remplacée par la gestion
d'échec de `sessions.purger`. L'arbre courant en compte 24 aussi : les cinq
resserrements et l'absorption supprimée sont compensés par les cinq de `sessions.py` — qui passent par
`_echec`, la forme de référence — et par `retriever._taille_collection`,
nouvelle et documentée comme muette au site.

**Resserrées** — le repli ne couvre plus qu'une panne d'infrastructure :

| Site | Type retenu | Ce que `Exception` masquait |
|---|---|---|
| `llm.py` `rewrite_question`, gabarit | `(TemplateError, OSError)` | Une faute dans le bloc journalisait « Gabarit introuvable » : le message accusait le gabarit, la réécriture était désactivée à chaque question, et rien ne pointait vers la cause. |
| `llm.py` `rewrite_question`, appel Ollama | `(httpx.HTTPError, ValueError)` | Deux des **trois** façons dont l'appel échoue sans que le code soit en cause : transport, et corps qui n'est pas du JSON. La troisième — un corps qui **est** du JSON valide sans avoir la forme attendue — est traitée par `_contenu_message`, qui nomme la forme acceptée, et non par le tuple. Cf. §1.26. |
| `llm.py` `translate_question`, gabarit | `(TemplateError, OSError)` | Idem la réécriture. |
| `llm.py` `translate_question`, appel Ollama | `(httpx.HTTPError, ValueError)` | Idem la réécriture, forme du corps comprise. |
| `graph.py` `node_generate`, `get_stream_writer` | `RuntimeError` | Toute autre panne de LangGraph faisait `writer = None` : la génération continuait, **muette**, et le frontend ne recevait aucun token sans qu'une ligne existe pour le dire. |

**Niveau de journal remonté :**

| Site | Avant → après | Pourquoi |
|---|---|---|
| `graph.py` `close_checkpointers` | `debug` → `WARNING` | Une fermeture en échec laisse une connexion SQLite ouverte sur le fichier des sessions, donc un WAL non replié et un verrou possible au démarrage suivant. `debug` est invisible à `LOG_LEVEL=INFO` : c'est le motif même du §1.20. |
| `api/main.py` `context` (`GET /context/{id}`) | muet → `ERROR` avec trace | FastAPI ne journalise pas une `HTTPException` : cette route rendait des 500 dont la cause n'était tracée nulle part. |
| `graph.py` `node_reconstruct_context` et `api/main.py` `chat_simple` | message recalé | « Erreur reconstruction section » laissait croire à un incident sans suite, alors que la source **disparaît de la réponse**. Le message le dit, et compte celles qui restent. |

**Conservées, avec au site ce qu'elles protègent et pourquoi elles sont
larges :**

| Site | Fonction | Décision |
|---|---|---|
| `retriever.py` | `_dense_search` | Reprise de connexion. Un client Chroma mort produit transport, sérialisation et schéma sans ancêtre commun. WARNING, un second échec remonte. |
| `retriever.py` | `full_texts` | Dégradation bornée : le texte tronqué du graphe reste, le LLM reçoit un tableau amputé plutôt que rien. WARNING. |
| `retriever.py` | `ping` | Une sonde ne doit jamais lever. Le faux est publié par `/health`, et le cache est oublié pour que la requête suivante rouvre. |
| `retriever.py` | `_taille_collection` | Large et **muette**, délibérément : Chroma injoignable est déjà rapporté par `services.chromadb` dans la même réponse. Rend `None` — « je ne sais pas » — jamais confondu avec « rien n'a changé ». |
| `retriever.py` | `_lexical_search` | La recherche dense suffit à servir la requête. Tracée avec sa pile, publiée en `index_lexical: false`. |
| `graph_context.py` | `_execute_raw` | Reprise de connexion. nebula3 mêle transport, authentification et session sans ancêtre commun. WARNING puis nouvel essai ; un second échec remonte. |
| `graph_context.py` | `props_of` | Large et **muette** : un nœud sans propriétés pour ce tag est le cas NORMAL — le tag `Document` n'a ni `label` ni `text`. Appelée plusieurs fois par élément : y journaliser inonderait le journal en régime nominal. |
| `graph_context.py` | `ping` | Une sonde ne doit jamais lever. `_execute` a déjà journalisé la panne en WARNING. |
| `minio_client.py` | `get_object_bytes` | Reprise de connexion. Le SDK minio mêle ses `S3Error` aux erreurs urllib3 d'un socket mort. WARNING au premier essai, pile complète au second. |
| `graph.py` | `node_reconstruct_context` | Une source illisible ne doit pas emporter la réponse entière. Message recalé (ci-dessus). |
| `graph.py` | `build_checkpointer` | Volume non monté, disque en lecture seule, aiosqlite en défaut : mieux vaut un service dégradé qu'un service mort. ERROR avec trace — le repli change le comportement du service. |
| `api/main.py` | `context` | La reconstruction traverse Nebula, Chroma et le parsing de leurs réponses. Journal ajouté (ci-dessus). |
| `api/main.py` | `chat_simple` | Idem `node_reconstruct_context`. Message recalé. |
| `sessions.py` ×5 | `initialiser`, `enregistrer`, `purger` ×3 | Une purge en échec ne doit pas casser la requête qui l'a déclenchée. Passe par `_echec` : WARNING au premier, rappels tous les 20, compteur dans `/health`. La ligne de registre est **conservée** en cas d'échec, sinon la session deviendrait inatteignable. |
| `usage.py` ×5 | `initialiser`, `record_start`, `record_completion`, `record_feedback`, `stats` | Inchangées : elles passent déjà par `_echec`, la forme de référence posée au lot 2. La capture est de l'observation, pas une fonctionnalité. |

**Supprimée :** l'absorption de `_register_thread` dans `main.py`, le `except Exception: logger.debug("Purge du
thread %s impossible")` du §1.20. C'est l'absorption qui a motivé le lot ; elle
n'a pas été resserrée mais remplacée, par une gestion d'échec qui compte, trace
et publie (`sessions._echec`).

**Nouvelle, et assumée :** `retriever._taille_collection`. Le filet
d'invalidation de l'index (§1.21) doit lire un compte qui peut être illisible ;
elle est large parce que chromadb remonte transport, sérialisation et schéma sans
ancêtre commun, et muette parce que la panne est déjà publiée par
`services.chromadb` dans la même réponse de `/health`. Elle rend `None` — « je ne
sais pas » — jamais confondu avec « rien n'a changé ».

Trouvé en resserrant : deux tests de `test_query_rewrite.py` simulaient la panne
d'Ollama avec un `ConnectionError` **intégré**, qu'httpx ne lève jamais — il
enveloppe le transport dans `httpx.TransportError`. Ils restaient donc verts sur
n'importe quelle absorption, y compris la plus large, et devenaient rouges sur
celle qui décrit la vraie panne. Un faux qui ne ressemble pas à la bibliothèque
ne prouve rien de la bibliothèque. Les deux lèvent désormais
`httpx.ConnectError`.

### 1.26 Le resserrement de `llm.py` rendait un HTTP 500 — `llm.py`

**Régression introduite par ce lot, trouvée à l'audit.** Le tuple
`(httpx.HTTPError, ValueError)` du §1.24 ne couvre pas une troisième classe de
panne : un corps de réponse qui **est** du JSON valide sans avoir la forme
attendue. Sur `{"message": null}`, `{"message": "une chaîne"}`, `{"message": []}`
ou un corps qui n'est pas un objet,
`.get("message", {}).get("content", "")` lève `AttributeError`.

Cela atteignait l'utilisateur. `node_rewrite` n'a aucun try/except : l'exception
traversait le graphe jusqu'à la route, et `/chat/start` comme `/answer` rendaient
**500** sur les quatre formes. Remettre `except Exception` — le code d'avant le
lot — rendait 200 partout : la causalité est établie, le resserrement était la
régression.

C'est aussi une affirmation fausse de ce document, dans le registre même du
lot : la table du §1.24 écrivait « les deux **seules** façons dont l'appel échoue
sans que le code soit en cause ». Il y en a trois, et c'est cette phrase
d'exhaustivité qui a autorisé le défaut. Elle est corrigée.

**Corrigé par un parsing défensif, pas par un tuple plus large.** Ajouter
`AttributeError` et `TypeError` aurait éteint le 500 en ramenant exactement ce
que le resserrement sert à empêcher : une erreur de programmation dans le bloc,
absorbée et journalisée comme une « réécriture indisponible ».
`_contenu_message` nomme la forme acceptée — objet, puis objet, puis chaîne — et
rend `""` pour tout le reste. Un `AttributeError` authentique remonte encore.

Trouvé en écrivant le garde-fou, et corrigé du même geste : `{"message":
{"content": null}}` ne levait rien, mais `str(None)` rendait la chaîne
**« None »**, quatre caractères qui passent le garde-fou aval et partent en
requête de recherche. Un 500 se voit ; une recherche sur « None » ne se voit pas.
La feuille est donc vérifiée aussi.

**Ce qui rend le correctif sûr, et que les tests assertent :** les deux sites ont
un garde-fou aval — « vide ou trop longue → question d'origine » pour la
réécriture, « vide → pas de traduction » pour la traduction. Sans eux, la chaîne
vide serait partie en requête de recherche, et à `TRANSLATION_WEIGHT=1.0` une
traduction vide serait entrée dans la fusion RRF : strictement pire que le 500.
Les tests n'assertent donc pas « pas d'exception » mais le comportement de bout
en bout — `rewrite_question` rend la question d'origine, `translate_question`
rend `None`, et les deux routes rendent 200.

**`httpx.InvalidURL` n'est pas attrapée, et c'est une décision écrite au site.**
Elle hérite directement d'`Exception`, pas de `HTTPError`, donc elle n'entre pas
dans le tuple — et elle ne doit pas y entrer. Un `OLLAMA_HOST` mal formé est une
erreur de **configuration** : elle casse aussi `generate_stream`, donc un repli
silencieux ici masquerait la panne réelle en dégradant la recherche en monolingue
au lieu de dire que le service est mal configuré. Un test l'épingle.

### 1.25 `RERANK_MIN_SCORE` documenté comme un réglage existant — `agent_architecture.md`

`agent_architecture.md` décrivait « Filtre de pertinence : `RERANK_MIN_SCORE=0.0`
— les chunks sous ce score sont écartés ». Ce réglage n'existe pas dans
`settings.py`, et l'en-tête de ce document le citait lui-même parmi les fausses
affirmations d'une version antérieure. Le dépôt documentait donc comme réglé un
défaut réel : **le système n'a aucun seuil de pertinence** et rend toujours
`RERANK_TOP_K` sources, quelle que soit la question.

L'affirmation est retirée. Le réglage n'a **pas** été créé : l'absence de seuil
se traite avec les deux autres manifestations du même problème, et cela reste
ouvert (§2, « Tout décoché »).

### 1.27 `/health` sérialisait ses sondes, et empêchait le frontend de démarrer — `api/main.py`, `api/schemas.py`

Les quatre sondes — Chroma, Nebula, index lexical, Ollama — s'attendaient l'une
l'autre. Or `docker-compose.yml` coupe le healthcheck à `timeout: 5s` avec
`retries: 5`, et `frontend.depends_on` exige `agent-api: {condition:
service_healthy}` : sans stores joignables, `curl` était tué à 5 s, les cinq
tentatives échouaient, `agent-api` passait *unhealthy*, et **le frontend ne
démarrait jamais** — alors que l'API répondait 200 `degraded`, ce qu'elle est
écrite pour faire (« retourne toujours 200 pour ne pas déclencher de restart en
boucle »). Le healthcheck annulait l'intention de la route.

**Mesuré** (`test_quatre_dependances_muettes_repondent_sous_le_delai_du_healthcheck`,
quatre sondes muettes plafonnées à 8 s) : **32,0 s** avant, **3,0 s** après. Le
32,0 ≈ 4 × 8 est la preuve de la sérialisation elle-même. Les deux mesures de
l'audit du lot 3 — ~140 s contre une adresse qui avale les paquets, ~40 s contre
un port qui refuse — sont **reprises sans remesure** : la stack est éteinte ici.
L'écart entre elles vient du mode de panne, pas de la mesure.

Les quatre sondes partent maintenant ensemble sous un plafond global de 3 s
(`_PLAFOND_SONDES_S`), et le test épingle ce plafond **contre le `timeout` lu
dans `docker-compose.yml`** : c'est le contrat de déploiement qui donne au
plafond sa valeur, et il vit dans un autre fichier que celui qu'on corrige.

Les décisions du lot, et ce qu'elles laissent ouvert.

**Un fil abandonné n'est pas un fil interrompu.** Trois des quatre sondes sont
synchrones et passent par `to_thread.run_sync` ; rien ne peut tuer un fil bloqué
dans un appel réseau. Le plafond ne fait donc que *lâcher* le fil : sous un
healthcheck toutes les 20 s contre un store muet, ils s'accumuleraient dans le
threadpool que les endpoints de recherche partagent. Traité, pas consigné :
`_sondes_en_vol` porte le nom des sondes dont le fil n'est pas revenu, et une
sonde en vol n'est pas relancée. Donc **un fil lâché par sonde au plus**, quelle
que soit la durée de la panne. Le drapeau est posé et retiré **par le fil
lui-même**, jamais par la tâche : la tâche rend la main au plafond, pendant que le
fil tourne encore. Résidu assumé, écrit au site : deux `/health` vraiment
simultanés peuvent doubler une sonde le temps qu'un fil démarre. Poser le drapeau
côté boucle fermerait cette fenêtre et en ouvrirait une pire — une tâche annulée
avant que son fil ne démarre laisserait le drapeau posé pour toujours, et la
sonde resterait « en vol » à jamais : une panne remplacée par une cécité.

**Ce qui borne le plafond, et ce qui ne le borne pas.** La documentation d'anyio
dit que `abandon_on_cancel=False` — la valeur par défaut — fait *ignorer les
annulations jusqu'à ce que le fil ait fini*, ce qui rendrait tout plafond
décoratif. J'ai failli l'écrire comme un fait sur ce code ; **mesuré, c'est faux
ici**. Un plafond anyio (`move_on_after(0,3 s)`) sur une sonde bloquée 6 s rend en
**6,00 s** par défaut et **0,30 s** avec le drapeau — le bouclier existe bel et
bien — mais `asyncio.wait(timeout=…)` **comme** `asyncio.wait_for` rendent en
**0,30 s dans les deux cas**, l'annulation d'une tâche asyncio étant délivrée
directement au futur attendu. Le plafond de `/health` vient donc de
`asyncio.wait` et du fait qu'on n'attend pas l'annulation, pas du drapeau ; la
piste consignée au lot 3 (« un `asyncio.wait_for` global ») aurait fonctionné.
Le drapeau reste posé pour deux raisons écrites au site, aucune n'étant le
délai : il dit la vérité sur le fil, et il rend l'appel indépendant du plafond
employé — remplacer `asyncio.wait` par une construction anyio est plausible dans
une application qui tourne sur anyio. **Aucun test ne le garde**, faute d'effet
observable ici : un test qui le prouverait testerait anyio, sur des sondes qui
dorment. La mesure est à refaire avec un `threading.Event` non levé et les quatre
combinaisons.

**« Pas revenue » n'est pas « tombée ».** Le premier est un fait sur l'agent, le
second sur le service. `services` reste un `dict[str, bool]` et publie `false`
dans les deux cas : ni le healthcheck ni l'exploitant ne doivent lire « je n'ai
pas eu le temps de regarder » comme « ça répond ». Mais la distinction existe, à
côté du contrat plutôt que dedans : `services_unknown` nomme les sondes qui n'ont
pas répondu, et le journal porte l'événement en WARNING **une fois** par abandon
— les appels suivants trouvent la sonde en vol et se taisent en DEBUG. Élargir
`services` en `dict[str, bool | None]` aurait imposé le doute à tous ses lecteurs
pour un cas normalement vide ; le champ ajouté ne casse aucun lecteur, et le seul
consommateur du corps est aujourd'hui l'exploitant — le frontend ne lit pas
`/health` (vérifié par `grep health src/frontend/`), le healthcheck n'en lit que
le code HTTP.

**Un plafond qui ne couvre pas tout finit par mentir.** Ce qui restait hors du
plafond a été inventorié. `usage_stats()` ouvre SQLite avec un `busy_timeout` de
5 s : laissée dehors, elle pouvait à elle seule faire dépasser le délai du
healthcheck sans qu'aucune sonde soit en cause. Elle est passée **sous le même
plafond**, et son absence se dit en `null`, ce que le contrat prévoyait déjà —
l'inventer en zéros décrirait une base vide. Ce qui reste dehors est borné et
nommé au site : `sessions.stats()` et `sessions.durable()` ne lisent que des
compteurs en mémoire et un réglage, sans aucune entrée-sortie. (La note qui les
soupçonnait de lire SQLite était fausse : `sessions.py:110-117` et `101-107`.)

**Une sonde qui lève ne fait pas tomber la route.** Les sondes absorbent déjà
leurs pannes, donc une exception qui remonte est un défaut de programmation : elle
est journalisée **avec son type**, jamais tue, et publiée `false` — ce n'est pas
un inconnu, la sonde a répondu, en levant. La propager ferait rendre 500 à
`/health`, ce que cette route existe pour éviter. **Le motif exact, corrigé le
4 septembre 2026** : ce n'est pas une boucle de redémarrage — `mesuré`, un
healthcheck en échec ne redéclenche aucun conteneur sous Docker Compose (§4.19).
C'est que le conteneur passe `unhealthy`, donc que `frontend`, qui en dépend en
`condition: service_healthy`, ne lève pas au démarrage à froid — et qu'un 500 ne
dit pas **laquelle** des sondes a échoué, là où un 200 dégradé le dit. Effet de bord acquis : un `OLLAMA_HOST` mal formé lève
`httpx.InvalidURL`, qui n'hérite pas de `HTTPError` et n'est donc pas rattrapée
par la sonde (§1.26) ; elle faisait rendre **500** à `/health`, elle rend
maintenant 200 `degraded` avec le type de l'erreur au journal. Vérifié sur `main`
avec `OLLAMA_HOST=http://héberge ur:8000` — un espace dans un nom d'hôte, la
faute de frappe qu'un `.env` porte réellement — dont l'`httpx.InvalidURL: Invalid
IDNA hostname` traversait la route. Nuance qui a d'abord rendu ce test faux : une
URL **sans schéma** lève `UnsupportedProtocol`, qui hérite de `TransportError`
donc de `HTTPError`, et que la sonde rattrape. Le test empruntait le chemin
ordinaire en prétendant vérifier l'autre ; il épingle désormais, par un
`pytest.raises` sur `httpx.URL`, que son host lève bien `InvalidURL`.

Le contenu des sondes n'a pas été touché, ni les valeurs du healthcheck dans
`docker-compose.yml` : desserrer le contrôle en même temps qu'on corrige l'API
aurait rendu le lot invérifiable. Le délai propre de 5 s de la sonde Ollama est
désormais dominé par le plafond ; il reste parce qu'il est le contrat de cette
sonde, et qu'un plafond global n'en tient pas lieu.

Enfin, l'ordre des journaux n'est plus déterministe — quatre sondes concurrentes
écrivent quand elles reviennent. Vérifié : aucun test du dépôt ne dépend d'un
ordre de lignes de journal (les assertions sur `caplog` sont toutes des
appartenances, des comptes ou `== []`). L'ordre de la **réponse**, lui, reste
déterministe : `services` et `services_unknown` sont publiés dans l'ordre de la
table des sondes, pas dans celui des retours.

---

### 1.28 Le garde-fou des marqueurs de coupe ne jouait que dans un sens — `tests/unit/test_llm_budget.py`

`test_la_notion_de_marqueur_complet_est_celle_du_post_processing` comparait
`llm._MARKER_RE` — le motif qui décide où la troncature coupe — à
`graph._BLOC_SRC` — celui qui résout les citations — sur **trois formes
positives**. Un motif plus étroit se voyait ; un motif plus large, non. Vérifié
sur le dépôt d'aujourd'hui : en élargissant `_MARKER_RE` à un crochet
quelconque, la suite entière reste verte (**424 passed**).

**La conséquence annoncée par cette fiche était fausse**, et c'est la correction
la plus utile ici. Elle disait qu'un motif plus large « laisserait un `[src:`
amputé derrière lui ». Il ne le peut pas : la coupe se pose toujours à la **fin**
d'une correspondance, donc sur un `]`, et jamais à l'intérieur d'un marqueur.
Mesuré sur trois corpus (`[Tableau]`, `[Figure]`, une note `[1]`) et toutes les
limites de coupe : **zéro `[src:` amputé** dans les deux motifs.

Le vrai dommage est l'autre dérive. Un motif large prend `[Tableau]`, `[Figure]`
ou `[1]` pour une frontière d'élément et coupe juste après : le fragment retenu
est alors du texte **sans identifiant de citation**, que le modèle lit et ne peut
pas attribuer. C'est la seconde dérive de la troncature, celle qui fait citer un
autre passage ou n'en citer aucun.

Le test exige désormais l'équivalence dans les **deux sens** : quatre formes qui
doivent être des frontières, six qui ne doivent pas l'être — dont celles que
`_render_element` écrit réellement dans le markdown. Il asserte depuis
`_MARKER_RE`, le côté qui **produit** la coupe, contre l'union de `_BLOC_SRC` et
`_BLOC_IMG`, le côté qui résout. Un second test vérifie que les deux désignent le
même identifiant, et pas seulement la même forme.

Ce durcissement passait **avant** le remplissage au plus juste (§1.29) : tant que
la coupe ne touchait que la première source retenue, elle était un chemin rare ;
elle devient le chemin courant.


### 1.29 La fenêtre écartait une source au hasard sur le flux interactif — `agent/graph.py`

Tout l'aval du budget suppose que `enriched_contexts` est trié par pertinence
décroissante : `fit_contexts` remplit depuis le début et écarte ce qui déborde,
le gabarit numérote « Source 1, 2, 3… », et la troncature ne touche que les
dernières retenues.

La supposition était fausse sur `/chat/start` → `/chat/resume`.
`node_reconstruct_context` reconstruisait dans l'ordre d'arrivée de
`selected_element_ids`, et le frontend range les cases cochées dans un **`set`**
(`src/frontend/app.py`) avant de poster `list(...)` : l'ordre est celui du
hachage des identifiants. Vérifié — cinq identifiants classés par pertinence
ressortent de `list(set(...))` dans un ordre différent.

Conséquence : la source que la fenêtre écartait n'était pas la moins pertinente,
c'était la dernière du hachage. Deux utilisateurs cochant les mêmes cases
pouvaient payer deux fenêtres différentes.

La sélection est désormais réordonnée **côté serveur** sur le classement du
reranker, que le graphe porte déjà (`_par_pertinence`). Corriger le frontend
aurait laissé l'API dépendre du bon vouloir de son appelant, et créé un second
endroit à tenir synchronisé — le dépôt en garde déjà un sous test. Un identifiant
absent du classement passe en fin : la boucle agentique peut en ajouter que le
reranker n'a jamais vus.

`/chat/simple` reste servi dans l'ordre de son appelant : cet endpoint reçoit une
liste nue, sans recherche ni reranking, donc aucune pertinence n'y existe. C'est
une propriété de la route, pas un oubli.

Ce défaut passait **avant** le remplissage au plus juste (§1.30) : « tronquer la
dernière retenue » n'a de sens que si la dernière est bien la moins pertinente.

**Le test qui épingle la cause a d'abord été écrit sans lire le frontend.** Il
construisait `list(set(...))` sur ses propres identifiants et vérifiait que
l'ordre différait. Deux défauts pour le prix d'un : corriger `app.py` laissait la
suite entièrement verte — donc il n'épinglait rien — et il rougissait au hasard,
l'ordre d'un `set` dépendant de `PYTHONHASHSEED`, sur environ une graine sur deux
cents. Dans un chantier dont la règle est que chaque commit soit vert
individuellement, un demi-pour-cent d'exécutions rouges est un défaut à part
entière. Il lit désormais l'**arbre syntaxique** de `src/frontend/app.py` :
`selected_ids` doit être initialisé par `set()`, et `selected_element_ids` doit
être posté par un `list()` nu pris directement dessus. Le jour où l'une des deux
choses change, il rougit et oblige à relire la justification du tri serveur.
Fixer `PYTHONHASHSEED` aurait fait taire le symptôme en aveuglant le dépôt sur
toute la classe de défauts que la variabilité du hachage révèle.


### 1.30 La marge de fenêtre laissée par une source écartée restait vide — `llm.py`, `settings.py`

Seule la **première** source retenue pouvait être tronquée. Une source qui
n'entrait pas dans la place restante était écartée entière, et cette place
restait vide.

Mesuré sur la grille — 144 configurations, 3 profondeurs de fil des titres x 8
tailles de source x 6 nombres de candidates, un seul tour, sans historique, avec
des sources faites d'éléments marqués comme `_render_element` les rend, et dont
les tailles sont tirées **par source** : **1 355 caractères de fenêtre
inutilisés en moyenne et 7 970 au maximum sur 88 configurations, ramenés à 408 en
moyenne — 70 % de la marge reprise, 38 configurations gagnées et aucune perdue**.

Cette phrase est le **site canonique** de la mesure. Elle est reprise mot pour
mot dans le docstring de `fit_contexts` et dans [llm.md](llm.md), et
`test_coherence_depot` exige que les trois restent identiques. Le garde-fou est
né d'un défaut réel : la même grille a porté **trois triplets différents** — 1 083
/ 4 106 sur 68 dans le code, 1 172 / 3 964 sur 68 dans les deux documents, et un
troisième au rejeu — parce que rien ne forçait les trois copies à s'accorder et
que le protocole publié, lui, ne mesurait que l'après tout en étiquetant sa
sortie « avant ».

*(L'audit du lot 1 annonçait 2 308 en moyenne et 6 169 au maximum sur 43
configurations. Ces chiffres portaient sur des sources sans marqueur ni fil des
titres et sur un décompte différent — « configurations où le budget corrigé
retient moins que `main` ». Ils ne sont pas comparables terme à terme aux
précédents ; ceux publiés ici sont remesurés sur le code livré.)*

La marge revient désormais à la **mieux classée des sources écartées**,
tronquée. Le protocole de mesure est dans [llm.md](llm.md) : il réimplémente
l'algorithme d'avant, de sorte que les deux colonnes sortent du même montage.

**Le plancher, et pourquoi il est relatif.** Un fragment trop petit coûte des
tokens et fait pire que rien : le modèle en voit assez pour citer la source et
pas assez pour savoir ce qu'elle dit — un défaut silencieux, alors que
l'abstention est visible. Mesuré : sans plancher, la grille retient un fragment
tombant à **1 %** de sa source.

Le plancher est une **part de la source**, pas un nombre de caractères, parce
que le dommage est une proportion. Un plancher absolu se tromperait sur un cas
que la grille contient : une source de 300 caractères coupée à 250 en garde
83 %, elle est lisible, et tout plancher absolu supérieur à 250 l'écarterait. Le
plancher absolu existe d'ailleurs déjà, et il est structurel : la coupe ne se
pose qu'à la fin d'un marqueur, donc un fragment porte au minimum un élément
entier avec son identifiant.

`TRUNCATION_FLOOR_SHARE` vaut **1/3**, et c'est un forfait **au sens plein** :
aucune mesure ne désigne cette valeur-ci. La version précédente de cette fiche
annonçait un plateau d'insensibilité de 0,25 à 0,45 ; c'était un **artefact du
montage**. La grille donnait alors la même taille à toutes les sources d'une
configuration, donc le plancher mordait pour toutes ou pour aucune, et le
résultat ne bougeait plus sur de larges plages. Deux choses étaient fausses à la
fois : le plateau réel de cette grille-là allait de 0,08 à 1/3, et 0,34 en sortait
déjà — donc 1/3 en
était le **bord droit** et non le milieu, et « le point le moins sensible à
±10 points » affirmait l'inverse de ce que la grille montrait — et le plateau
lui-même n'existait que parce que les tailles étaient uniformes.

Tailles tirées **par source**, il n'y a aucun palier : chaque pas du plancher
déplace la marge, le nombre de configurations gagnées et la plus petite part
retenue.

| plancher | marge moyenne | configurations gagnées | plus petite part retenue |
|---|---|---|---|
| 0,00 | 76 | 70 | **1 %** |
| 0,15 | 175 | 55 | 15 % |
| 0,25 | 266 | 48 | 25 % |
| **1/3** | **408** | **38** | **34 %** |
| 0,40 | 457 | 35 | 41 % |
| 0,50 | 585 | 31 | 51 % |

Ce que la mesure établit, et qui suffit à garder le plancher : **il doit
exister** — sans lui la grille descend à 1 % d'une source — et **le réglage veut
dire ce qu'il dit**, la plus petite part retenue le suivant de près. Ce qu'elle
n'établit pas, c'est la valeur : son prix est continu, et 1/3 est un arbitrage
entre lisibilité du fragment et remplissage de la fenêtre. Le trancher demande
une mesure de la QUALITÉ des réponses, donc une campagne.

Il ne joue **que si une autre source est déjà retenue**. Sans lui le prompt
partirait sans aucune source, et « mieux vaut une source amputée que zéro
source » reste l'arbitrage du budget (§1.14) : la même relaxation s'applique à
l'exigence de marqueur, pour la même raison.

Mais ce sont **deux décisions**, et un seul booléen les portait. « Ce fragment
représente-t-il sa source » et « ce fragment est-il attribuable » ne posent pas
la même question, et rien ne garantit que leurs réponses continueront de
coïncider. Le coût de la fusion était mesurable : forcer le booléen à faux, ou
retirer entièrement la clause du marqueur, ne faisait rougir **aucun** test — le
plancher refusait le cas d'abord, donc il masquait l'autre exigence. `_truncate`
prend désormais `exiger_marqueur` et `exiger_plancher` séparément, et deux tests
gardent le marqueur dans les deux sens sur un fragment qui passe le plancher :
refusé quand une autre source est retenue, rendu quand il est la seule.

**Ce que la troncature déplace, traité nommément.** Elle bouge la frontière
entre ce que le modèle lit et ce qu'il peut citer. Deux dérives.

*Le marqueur survit, son contenu part* — le modèle cite une source dont il n'a
pas vu le texte. **Impossible par construction** : `_render_element` écrit
« texte [src:ID] », le marqueur SUIT son élément, et toute coupe est un préfixe.
Ce n'est pas une précaution, c'est la forme du markdown. Elle comptait d'autant
plus que `resolve_citations` résolvait alors un `[src:ID]` depuis
`SectionContext.elements` — le MODÈLE — et non depuis le texte soumis : un
marqueur orphelin rendait une citation vers un extrait jamais envoyé, et un test
l'épinglait pour que personne ne croie la garantie logée dans le résolveur. Elle
est depuis **aux deux bouts** (§1.31) : le résolveur refuse un identifiant absent
du texte soumis, et le test d'épinglage a été retourné en garde. Celle de la
coupe reste la seule à protéger le TEXTE — l'autre ne protège que la citation.

*Le contenu survit, son marqueur part* — le modèle lit un passage qu'il ne peut
pas attribuer, donc il l'utilise sans référence ou le rattache au marqueur
précédent, c'est-à-dire au mauvais élément. C'est celle-ci qu'il faut écarter
activement, et c'est le travail de `_cut_on_marker`, dont le garde-fou vient
d'être durci dans les deux sens (§1.28).

Le premier jet de ce lot avait **retiré** de ce garde-fou, sans remplacement, le
retrait du crochet resté ouvert à la coupe que `main` portait. Sans marqueur
complet dans la tête, la tête repartait telle quelle — donc avec un
« [src:00000 » entamé, que le post-processing ne résout pas. Mesuré sur la
fixture du test : **11 budgets fautifs, bande 124–134**. Ce qui compte autant que
le correctif est la raison pour laquelle rien ne rougissait : le balayage qui
surveille cette coupe commençait à 150, **au-dessus de la bande**. Il part
désormais de la première coupe possible, calculée et non posée
(`len(_TRUNCATION_MARKER) + 1`), et il refuse tout crochet resté ouvert, pas
seulement un `[src:` amputé.

Les deux invariants sont vérifiés avec l'instrument du lot 4,
`element_ids_presents`, qui lit les marqueurs du **texte soumis** et non le
modèle : tout identifiant présent dans le prompt y a son texte, et tout élément
coupé disparaît des identifiants publiés par `/answer`.

Une **réserve** manquait à l'énoncé de la seconde, et elle porte : « tout
fragment se termine sur un marqueur complet » est faux pour une source qui n'en
porte aucun. Le cas existe — `graph_context.reconstruct_section` ajoute le texte
brut d'un élément orphelin de section sans marqueur, et si cet élément n'a pas
d'enfant la source n'en a pas un seul. Le code était intentionnel,
`_cut_on_marker` déclare qu'une telle source se coupe librement ; c'était la
phrase du test qui était trop large, et sa fixture, faite de sources toutes
marquées, ne pouvait pas la contredire.

**Ce que ce changement déplace ailleurs.** `dropped_contexts` change de sens —
une source hier écartée est aujourd'hui tronquée et retenue, donc le compteur
baisse sans que le retrieval s'améliore. Dit dans `usage.py`, où il est écrit, et
dans [capture_usage.md](capture_usage.md), où il est lu. Les métriques de contexte
du lot 4 bougent toutes, et aucune comparaison à une campagne antérieure n'est
valide : l'avertissement est dans [runs/README.md](../runs/README.md), à côté de
celui de la correction du budget.

Trois précisions y ont été apportées après coup, et chacune corrigeait une
affirmation trop confiante.

`taux_contexte_utile` portait une flèche à **un seul sens** (« peut monter »).
Elle est fausse : la métrique vaut `utiles / retenus`, donc une section retenue
de plus entre toujours au dénominateur et seulement parfois au numérateur.
Mesuré sur le calcul de `scripts/evaluate.py` : à une utile sur deux, une section
de plus sans or fait 0,500 → 0,333, la même porteuse d'or fait 0,500 → 0,667.
Elle est aussi indécidable que `part_utile_caracteres`, et une métrique qui ne
peut pas se tromper n'est pas gardée.

Un **quatrième effet** n'était pas déclaré. Une source sans aucun marqueur — le
texte brut d'un élément orphelin de section — sort avec `element_ids = []` : elle
peut entrer au dénominateur de ces deux métriques, jamais au numérateur. Ce lot
en retient davantage puisqu'il reprend la marge, donc elles peuvent baisser du
seul fait que cette population grossit. Depuis §1.31, cette même population est
aussi **incitable** : sans marqueur dans le texte soumis, rien de la source ne
peut être résolu en citation. Cf. l'entrée §2 sur l'identifiant que le gabarit
imprime sans le rattacher à un texte.

Enfin, `retained` repose sur un invariant **non écrit** : `/answer` indexe les
sources soumises par `section_id` (`main.py`), ce qui fusionnerait deux
candidates de même section. Il n'y en a jamais deux parce que
`node_reconstruct_context` déduplique par `section_id` en amont — vérifié, deux
éléments distincts d'une même section rendent une seule candidate enrichie. La
déduplication porte donc la justesse de `retained`, et la retirer casserait une
métrique du lot 4 sans toucher au lot 4.

### 1.31 Une citation résolvait vers un texte jamais soumis au modèle — `agent/graph.py`, `agent/llm.py`, `api/main.py`

`resolve_citations` résolvait un `[src:ID]` depuis deux tables dont **aucune**
n'était restreinte à ce que le budget de fenêtre avait envoyé : `elements_map`,
bâtie sur les sections CANDIDATES que `node_postprocess` lui passait, et
`chunks_map`, bâtie sur TOUS les chunks reranqués. Un identifiant écarté
ressortait donc résolu — document, page, section, extrait — vers un passage que le
modèle n'avait pas lu. Rouge sur `main`, la citation que le défaut produisait :

```
Citation(element_id='bbbbbbbbbb', filename='3. Statistical Toolbox',
         collection='The Statistics Workshop', section_title='Dispersion',
         page_no=88, text_excerpt='Le texte du chunk, celui que le classement porte.')
```

L'extrait est celui du **chunk du classement**, jamais celui du prompt : c'est ce
qui rend la fausse citation indétectable à la lecture.

**Le chemin est l'historique, et il est prouvé maillon par maillon.** L'objection
évidente — le modèle ne peut pas citer ce qu'il n'a jamais vu — tombe sur le
multi-tour : `fit_history` resoumet les réponses passées marqueurs compris, et le
gabarit ordonne de reprendre les identifiants tels quels. Le test du chemin réel
exige les trois maillons dans le même corps, sur le vrai `_build_messages` : le
budget écarte bien la section (`dropped_contexts == 1`, et elle est absente des
retenues), le marqueur est bel et bien dans le prompt du tour courant par
l'historique, et la citation qui le recite est refusée. Sans le maillon du milieu,
le lot n'aurait corrigé qu'un défaut inatteignable.

**Le grain est l'ÉLÉMENT, pas la section, et c'est le cœur du lot.** Une section
retenue peut avoir été TRONQUÉE : l'élément dont le marqueur est tombé à la coupe
n'a pas été soumis, même si sa section l'a été. Le filtre lit donc
`element_ids_presents(ctx.markdown)` — les marqueurs du texte réellement envoyé,
l'instrument du lot 4 — et non `ctx.elements`, qui est le modèle et garde tout.
Choisir la section aurait laissé ouverte exactement la fenêtre que le §1.30
décrivait comme fermée par la coupe : mutation vérifiée, le grain de la section
laisse passer l'élément coupé et deux tests le disent.

Ce qui change de statut, et c'était écrit à trois endroits : « la garantie est
dans la coupe, pas dans le résolveur ». Elle est désormais **aux deux bouts**.
Celle de la coupe protège le TEXTE — un marqueur retenu a son texte devant lui —
celle du résolveur protège la CITATION. Les trois phrases sont corrigées, dans le
même commit que le code : `llm.py` (`_truncate`), `test_llm_budget.py`, et le test
d'épinglage de `test_precision_contexte.py`, qui **affirmait l'inverse** et avait
raison de l'affirmer avant ce lot.

**Un identifiant connu mais non soumis est un troisième cas**, distinct de
l'inventé et du légitime : il est refusé, et journalisé en WARNING. Le laisser
tomber en silence empêcherait d'apprendre s'il se produit vraiment en production,
et c'est la seule question qui reste ouverte sur ce défaut. L'inventé, lui, reste
ignoré sans bruit — un test garde le fait qu'il ne déclenche pas l'avertissement,
sinon le journal serait bavard sur un cas ordinaire et le vrai signal s'y noierait.
La classification du journal est incomplète et le dit au site : un élément d'une
section écartée ENTIÈREMENT n'est reconnu que si le classement le porte encore.
Le refus, lui, ne dépend pas de cette distinction.

**Les images suivent, et pas au même grain.** La voie 1 — un `[img:ID]` que le
modèle écrit — est filtrée comme une citation : c'est une affirmation sur ce qu'il
a vu. La voie 2 — les illustrations attachées à une section citée — reste au grain
de la SECTION : une figure n'a pas de texte, le modèle n'en voit jamais qu'un
marqueur, et la retirer parce que la coupe a emporté ce marqueur ne corrigerait
aucun mensonge tout en privant le lecteur d'une figure qui appartient réellement à
la section citée. Une section jamais soumise, elle, ne peut plus rien illustrer.
Les deux décisions ont leur test, et leur mutation : filtrer `media_map` fait
rougir l'une, ne pas filtrer la voie 1 fait rougir l'autre. Ce qui disparaît est
visible par l'utilisateur — `MAX_IMAGES` borne toujours à 4, et
`numeroter_citations` du frontend **retire** les marqueurs non résolus au lieu de
les laisser bruts, donc le texte de la réponse reste propre : ce que le lecteur
perd est la carte de source, pas la lisibilité.

**Ce que le multi-tour perd, assumé.** Un modèle qui recite le `[src:ID]` d'un
tour précédent voit sa citation refusée. La réponse peut rester vraie, et c'est
l'argument contraire ; il ne l'emporte pas, parce qu'une carte de source affirme
« cette phrase vient de ce passage, que j'ai lu », et que ce n'est plus vrai au
tour courant. Le coût réel est borné par ce que le frontend fait déjà des
marqueurs non résolus.

**`/chat/simple` ne passe pas par le graphe** : personne n'y renseignait
`submitted_contexts`. Le rappel `on_fit` est posé au point d'appel, sur les deux
chemins, et `generate` le relaie — du câblage, le budget restant appliqué au même
endroit. Un budget vide y **ferme** la résolution au lieu de retomber sur les
candidates : le jour où le câblage sera défait, une réponse sans citations et un
WARNING se voient, une citation fausse ne se voit pas. `node_postprocess` tranche
pareil, et le dit aussi quand des candidates existent sans aucune section soumise.
La capture d'usage de cette route enregistre toujours les CANDIDATES dans
`submitted_element_ids`, alors que la valeur juste était sous la main : la
corriger ici seulement aurait donné à une même colonne deux sens selon la route,
ce qui est pire qu'un nom trompeur uniforme. L'entrée §2 « La capture d'usage
nomme « soumises » des sections qui ne l'ont pas été » garde ce sujet, et elle
demande de trancher les trois routes ensemble.

**Deux tests du dépôt étaient verts grâce au défaut**, et il faut le dire :
`test_citation_issue_d_un_chunk_reranque` et
`test_citation_dupliquee_n_apparait_qu_une_fois` résolvaient depuis `chunks_map`
avec `submitted_contexts` VIDE. Ils portent maintenant un état où l'élément est
dans le classement ET dans une section soumise — le cas normal, l'élément
d'ancrage étant ce qui a fait remonter la section. Deux faux ont dû changer pour
la même raison : ceux de `test_flux_interactif.py` et `test_capture_branchement.py`
remplaçaient `generate_stream` en entier sans jamais appeler `on_fit`, ce que le
dépôt savait et avait écrit. Ils appellent désormais le vrai `fit_prompt`, et les
sections de leurs fixtures portent leurs marqueurs comme la production les porte.


## 1bis. Corrigé — qualité, mesure, exploitation

| Sujet | Ce qui a été fait |
|---|---|
| Modèles multilingues | Embedder et reranker alignés sur la réingestion. Mesuré : le reranker anglais rendait une étendue de scores de 0,0 % sur une question française — un classement au hasard. |
| Réécriture de requête | `node_rewrite` rend la question de suivi autonome avant l'encodage. Sans historique, aucun appel au LLM. |
| Recherche hybride | BM25 + dense fusionnés par RRF. La fusion porte sur les **rangs**, pas sur les scores : une distance cosine et un score BM25 ne sont pas comparables. |
| Recherche translingue | La question est traduite et la recherche porte sur les deux. Le rappel translinguistique passe de 0,806 à **1,000**. |
| Vivier élargi | `RETRIEVAL_TOP_K` 20 → 50. Le rappel global passe de 0,900 à **0,985** : la coupe précoce chassait, avant le reranking, ce que la question d'origine avait trouvé. |
| Texte intégral | Relu dans l'index quand le texte du graphe frôle sa troncature à 2000 caractères. |
| Légendes des illustrations | L'arête avait été renommée côté ingestion : la requête échouait à chaque reconstruction, sans casser la réponse mais en privant les illustrations de leur légende. Le nom est désormais lu dans le schéma. |
| Tool-calling natif | `search_vectors` déclaré comme outil natif du moteur ; le regex sur la prose reste en second rideau. |
| Endpoint `/answer` | Non interactif, expose le classement du retrieval, les passages soumis au LLM et les temps par étage. |
| Flux interactif | Le checkpointer SQLite **synchrone** faisait tomber toute l'interface en 500. Corrigé et couvert par six tests. |
| Résilience | Réouverture des clients après redémarrage d'un store, timeout nGQL, sessions persistées et purgées. |
| Serveur d'inférence | L'Ollama embarqué disparaît du compose : un seul serveur, celui de `llm-service`. |
| Sécurité | CORS restreint, clé d'API optionnelle, proxy média borné aux objets référencés par le graphe. |
| Typage | `make typecheck` n'avait jamais tourné : 54 erreurs corrigées, pas désactivées. |
| Lisibilité des réponses | Les hachages `[src:…]` deviennent des renvois numérotés vers une liste de sources nommant ouvrage, document, page et section. |
| Mesure | Jeu doré de 138 questions généré depuis le corpus, campagne déterministe, banc de réglage rapide. |
| Coût réel de la génération (lot 4) | `runs/*.json` n'enregistrait que `generation_ms` : la longueur des réponses n'était mesurée nulle part, et `eval_count` n'était même pas lu dans le flux Ollama. La campagne enregistre désormais la longueur en caractères, `eval_count`, `prompt_eval_count`, l'estimation en regard et le plafond appliqué — donc `generations_au_plafond`, le chiffre qui tranche `LLM_MAX_TOKENS`. La décision d'écarter les décomptes pollués par le cache KV est rendue unique (`llm.mesure_prompt_exploitable`) au lieu d'être recopiée. Cf. [llm.md](llm.md) § `LLM_MAX_TOKENS`. |
| Strates vides (lot 4) | « Questions de suivi » et la découpe translinguistique n'étaient publiées que peuplées. Une strate vide qui se tait ressemble à une strate saine : elles sont désormais rendues avec leur effectif à zéro, et l'affichage dit « STRATE VIDE ». Le jeu doré ne porte aucune question de suivi, et cela doit se lire. |
| Comparaison appariée (lot 4) | `--compare` joignait les résumés, jamais les questions : « 30 améliorées, 28 dégradées » et « 2 améliorées, rien de cassé » s'affichaient identiques. L'appariement rend le compte amélioré/dégradé/inchangé, les identifiants qui basculent, un test des signes exact et un intervalle de confiance par bootstrap à graine fixe — tous deux déterministes, sans juge. Et il **REFUSE** de tourner quand les deux jeux de questions diffèrent, en nommant l'écart : `make eval` visait `runs/reference.json`, qui ne porte que 117 des 138 lignes — et pas n'importe lesquelles : les 8 questions sans réponse en sont TOUTES absentes (cf. la ligne du registre). Chaque exécution confrontait donc 138 moyennes à 117, prises sur une composition différente. La cible est passée à `runs/final.json`. |
| Précision du contexte (lot 4) | Le rappel et le MRR mesurent le classement, que la reconstruction par le graphe ne change pas : mesurer l'ablation du graphe sur eux afficherait « aucun changement » sur le pari central du projet, et ce serait un artefact de l'instrument. `taux_contexte_utile` et `part_utile_caracteres` mesurent la composition du contexte **payé** — dénominateur pris après la troncature de `fit_prompt`, sections écartées hors du calcul, questions sans or exclues et comptées. `rappel_contexte` voit ce que `rappel_elements` ne peut pas voir : un élément d'or ramené par la fenêtre sans avoir été classé. Cf. [rag_evaluation_strategy.md](rag_evaluation_strategy.md) § La précision du contexte. |
| Décomposition du temps (lot 4) | `AnswerResponse` portait deux chiffres pour sept étages, et la reconstruction par le graphe — le pari central — n'avait **jamais** été chronométrée. `timings` publie huit étages disjoints plus un **résidu**, dont la somme égale le temps mural mesuré ; l'invariant est testé, et `retrieval_ms` est explicitement nommé agrégat pour qu'on ne le promeuve pas en étage. Cf. [rag_evaluation_strategy.md](rag_evaluation_strategy.md) § La décomposition du temps. |
| Capture d'usage (PRO-5) | Le service n'enregistrait rien de ce qu'il servait. Deux tables SQLite dans le volume déjà monté : une ligne par interaction, une ligne par source **proposée** avec son rang, sa pertinence et son sort. Un décochage devient l'annotation négative qu'aucun jeu généré ne contient, en une requête SQL. Empreinte de configuration par interaction, condensat des prompts compris — jusqu'ici, une modification de prompt n'était attribuable nulle part. Cf. [capture_usage.md](capture_usage.md). |

---

## 2. Ouvert — agent

Les lignes qui se terminent par **« Reporté au lot 1 »** ne sont pas des
découvertes : ce sont des écarts identifiés et chiffrés pendant la revue du
budget de contexte, dont la correction a été **délibérément** sortie du lot —
soit parce qu'elle change un algorithme et mérite son propre lot, soit parce
qu'elle demande une mesure que rien ne permettait de prendre. Chacune dit ce qui
la débloque, pour qu'on n'ait pas à redécouvrir la décision.

| Priorité | Sujet | Détail |
|---|---|---|
| P2 | Le gabarit imprime un identifiant qui n'est attaché à aucun texte | **Trouvé au lot 6b, mesuré, non traité.** `answer_with_context.j2` écrit `Source {{ loop.index }} — {{ ctx.element_id }}` : l'identifiant d'ancrage de la section est imprimé **en clair**, hors de tout marqueur, et la dernière ligne du gabarit ordonne « reprends ces identifiants tels quels ». Or cet élément d'ancrage est celui que la recherche a matché, donc il est au MILIEU de la section, et la troncature coupe par la fin. Mesuré sur une section de 12 éléments dont l'ancre est le 7e : sur **10 budgets de troncature sur 10**, l'ancre imprimée par le gabarit n'a plus son texte dans le markdown soumis — et sur 3 de ces 10, la source retenue ne porte **aucun** marqueur (le plancher et l'exigence de marqueur sont relâchés quand c'est la seule source, cf. [llm.md](llm.md)). Conséquence depuis §1.31 : un modèle qui cite cet identifiant voit sa citation **refusée**, ce qui est le bon comportement — il n'a pas lu ce texte — mais le prompt l'y a invité. Ce n'est donc pas un défaut du résolveur, c'en est un du gabarit : il offre un identifiant sans contenu. Deux traitements possibles, à trancher dans un lot qui touche au prompt : retirer l'identifiant de cette ligne, ou lui donner un sens de citation de SECTION, distinct du `[src:ID]` d'élément — ce qui demande d'abord de décider si une citation de section est une citation. Éclaire l'entrée voisine sur les métriques : une source sans marqueur n'était « jamais au numérateur », elle est maintenant aussi **incitable**. Débloqué par : rien, mais cela change ce que le modèle lit, donc la qualité des réponses, et cela ne se vérifie pas à sec. |
| P2 | La boucle agentique n'est pas retriée, et ce choix n'était pas écrit | Dans la branche d'itération de `node_reconstruct_context`, `contexts` vaut « anciens + nouveaux » sans retri : les chunks d'un reranking **frais** arrivent en fin de liste et sont donc les premiers candidats à la troncature, alors qu'ils sont les plus pertinents pour ce que le LLM vient de demander. La raison de ne pas retrier est réelle — le modèle a déjà rédigé en s'appuyant sur les premières, et renuméroter changerait sous lui le sens de « Source 2 » — mais elle n'était écrite nulle part, et le docstring affirmait au contraire que « dans les deux cas la reconstruction suit le classement ». C'est désormais écrit comme un choix. Ce qu'il coûte n'est pas mesuré. Débloqué par : rien, mais l'arbitrage est un choix produit. |
| P1 | Le pari central n'est pas vérifié | Personne n'a montré que la reconstruction de section améliore les **réponses**. Le rappel mesure le retrieval, pas ce que le LLM en fait. Trancher sur la QUALITÉ demande un juge calibré — donc RAG-Eval-Bench. Ce que le lot 4 rend décidable sans juge : le prix (`reconstruction_ms`), le coût en contexte (`caracteres_retenus`), la composition du contexte payé (`taux_contexte_utile`, `part_utile_caracteres`) et l'apport propre de la fenêtre (`rappel_contexte` moins `rappel_elements`). Un rapport prix/apport défavorable tranche sans juge ; seul un rapport favorable en demande un. Débloqué par : la stack démarrée. |
| P1 | `rappel_elements` mesure la graine, pas ce qui atteint le LLM | **Trouvé au lot 4, non corrigé, et il faut dire pourquoi.** La métrique compare l'or aux `element_id` du CLASSEMENT retenus comme graines, alors que la fenêtre du graphe ramène jusqu'à treize éléments par section, plus les voisines : un or ramené par la fenêtre sans avoir été classé compte pour zéro alors qu'il a atteint le LLM. Deuxième écart, de la même famille : elle se calcule sur `contexts`, qui contient les sections ÉCARTÉES par le budget — donc elle ne bouge pas quand une source est écartée, contrairement à ce qu'annonce [runs/README.md](../runs/README.md), corrigé ici. `rappel_contexte` est ajouté À CÔTÉ plutôt qu'en remplacement : redéfinir `rappel_elements` rendrait incomparables les sept campagnes de `runs/`, dont les chiffres portent les décisions de réglage déjà prises. Débloqué par : rien, mais l'arbitrage « couper la comparabilité historique » est un choix, pas une correction. |
| P1 | Jeu doré non relu | 138 questions générées, toutes `reviewed: false`. L'approche est fiable pour régler un retriever, moins pour arbitrer entre générateurs. Une relecture humaine les promeut — et depuis la capture d'usage, les questions réellement posées et les sources validées par un humain s'accumulent pour la remplacer progressivement. Encore faut-il des utilisateurs : il n'y en a aucun à ce jour. |
| P1 | « Tout décoché » est irreprésentable, et le signal de sélection est aveugle avec lui | Un utilisateur qui rejette **toutes** les sources ne peut pas le dire : `SourceSelectionRequest.selected_element_ids` porte `min_length=1`, et le bouton « Générer » est désactivé à zéro coché. Son rejet total tombe donc dans le même seau `retenue IS NULL` que l'abandon d'onglet, alors que c'est le jugement le plus tranché qu'il puisse rendre — et le plus informatif pour la recherche. Deux défauts de la même famille l'accompagnent : **aucun seuil de pertinence** n'écarte les sources faibles (`rerank` rend les `RERANK_TOP_K` premières quel que soit leur score), et le **badge de pertinence est relatif au meilleur score de la question**, donc la meilleure source s'affiche toujours en vert — même quand la recherche n'a rien trouvé de bon. Les trois portent sur la même chose : ce que l'interface demande à l'humain, et ce qu'elle sait de la qualité absolue du classement. À traiter **ensemble, dans un lot dédié**, pas au fil de la capture. `agent_architecture.md` documentait le seuil comme un réglage existant (`RERANK_MIN_SCORE=0.0`) : l'affirmation est retirée (§1.25) et le réglage n'a pas été créé, pour que ce lot-ci reste entier. Débloqué par : rien, mais l'arbitrage à rendre — que veut dire « aucune source ne vaut » pour le graphe, faut-il générer, s'abstenir, ou relancer une recherche — est un choix produit, pas une correction. |
| P1 | Les données d'usage ne sont pas exploitées | **Ce que la capture ne fait pas, et c'est délibéré.** Le lot pose le robinet — les deux tables, les requêtes des trois usages, l'export JSON — pas la décision. Promouvoir une question en jeu doré, choisir son annotation, arbitrer ce qu'un décochage prouve : chantier d'un lot ultérieur. Débloqué par le premier corpus d'enregistrements réels, donc par les premiers utilisateurs. |
| P2 | Les trois classes de questions non couvertes | « Résume ce document », l'agrégation (« combien de documents parlent de X »), le multi-saut réel : l'architecture ne les sert pas, et personne ne sait si c'est un manque coûteux ou une inquiétude théorique. La question est désormais stockée telle qu'elle a été posée, et la requête de classement est écrite dans [capture_usage.md](capture_usage.md) : il ne manque que l'usage. |
| P3 | La capture n'a pas de garde-fou de taille | Aucune purge, par conception. La taille est journalisée au démarrage et exposée par `/health`, mais rien n'alerte : un poste laissé tourner des mois avec une campagne quotidienne (138 interactions, environ 4,6 ko chacune) écrit de l'ordre de 240 Mo par an. Trancher demande de savoir ce que l'exploitation garde. |
| P2 | Branchement sur RAG-Eval-Bench | Le banc apporte les **juges calibrés** — la comparaison appariée et les intervalles de confiance existent désormais dans `scripts/evaluate.py` (lot 4), déterministes et sans juge, ce qui réduit d'autant ce que le branchement doit aller chercher. Il lui manque un `ExternalPipeline` qui poste sur `/answer`. |
| P2 | `runs/reference.json` est un échantillon BIAISÉ, pas seulement incomplet | **Trouvé au lot 4, gravité corrigée au lot 4b.** Dire « 117 lignes sur 138 » sous-estime le problème : ce n'est pas un compte, c'est une composition. **Mesuré** sur les deux fichiers : **aucune** des 8 questions `unanswerable` n'y figure — la strate de l'abstention est vide, pas réduite — et l'anglais y survit moins bien que le français, 54 des 68 questions anglaises (79 %) contre 63 des 70 françaises (90 %). Le stratum translinguistique, lui, est intact : 35 des 36. Toute conclusion tirée de ce fichier sur l'abstention est donc sans objet, et toute conclusion par langue penche. **À porter au crédit de l'instrument** : le résumé de ce fichier publie `abstention_correcte: None`. Il s'est abstenu au lieu d'inventer un chiffre sur une population absente — c'est ce qu'on lui demande, et c'est la trace qui permet de dater le biais après coup. Le rejouer demande la stack démarrée ; le jour où ce sera fait, `test_la_cible_historique_de_make_eval_serait_refusee` sera à retirer avec cette ligne. Débloqué par : la stack démarrée. |
| P1 | `LLM_MAX_TOKENS` non mesuré — **l'instrument existe désormais** | 4096 tokens sur 8192 confisquent la **moitié** de la fenêtre à la génération, et rien ne dit qu'elle en a besoin. Le seul indice sourcé est indirect : 3,246 citations par réponse (`runs/final.json`). Ce que le lot 4 change : la campagne enregistre `eval_count`, `num_predict` et la longueur des réponses, et le résumé publie `generations_au_plafond` — zéro sur les 138 questions tranche la présomption dans un sens, non nul dans l'autre. Il ne manque plus que l'exécution. Reste une présomption tant qu'aucune campagne n'a tourné. C'est le plus gros levier du budget de sources : à un plafond de 1024 tokens — **hypothèse de calcul, pas une mesure** — le budget de sources passerait de 12 444 à 23 196 caractères, soit **+86 %**. Protocole de mesure dans [llm.md](llm.md). **Reporté au lot 1**, débloqué par : la stack démarrée (§ ci-dessous). |
| P1 | Rien n'a jamais tourné contre le service d'inférence réel | `prompt_eval_count` n'a **jamais** été observé : l'instrumentation existe, et depuis le lot 4 elle remonte jusqu'au fichier de campagne au lieu de ne sortir qu'en journal — mais elle n'a toujours produit aucune mesure. Donc `_CHARS_PER_TOKEN = 3,5` reste un forfait, et aucune campagne n'a tourné depuis la correction du budget. La première peut démentir le ratio — c'est précisément pour cela que le log a été écrit, et pour cela que l'écart mesuré y est journalisé à chaque génération. **Reporté au lot 1**, débloqué par : réseau `llm-net` absent, conteneur `ollama-central` absent, stores arrêtés — les deux stacks prérequises doivent tourner. |
| P2 | La capture d'usage nomme « soumises » des sections qui ne l'ont pas été | **Trouvé au lot 4, non corrigé.** `record_completion(submitted=enriched)` écrit dans `submitted_element_ids` et `submitted_section_ids` les sections CANDIDATES, celles que le budget a écartées comprises — alors que `dropped_contexts` est stocké à part sur la même ligne. Les deux colonnes surestiment donc ce qui a été payé, du même écart que celui corrigé côté campagne. À la décharge de la capture, [capture_usage.md](capture_usage.md) le DIT — « les sections reconstruites, avant la coupe de fenêtre : à lire avec `dropped_contexts` » — donc c'est un nom trompeur et un chiffre absent, pas une affirmation fausse. `/answer` publie désormais la distinction (`retained`), donc la correction est à portée. Non faite ici : redéfinir le sens d'une colonne déjà écrite rend ambiguës les lignes existantes, et c'est le lot de la capture qui doit trancher ce qu'il garde. Aucun enregistrement réel n'existe à ce jour, ce qui rend la correction bon marché — raison de plus pour la faire délibérément. |
| P2 | Le jeu doré ne contient aucun historique de conversation | **0 des 138 questions** de `golden_qa_generated.json` porte un `chat_history` (l'ancien jeu de 15 en a 3, mais `make eval` ne l'utilise pas). Or le bénéfice principal du budget corrigé est la survie du message système **au troisième tour** d'une conversation : la campagne mesurera le coût de la correction sans jamais mesurer son gain. C'est un manque du **jeu**, pas du protocole de lecture — celui-ci est prévenu dans [runs/README.md](../runs/README.md), et depuis le lot 4 le résumé affiche « [questions de suivi] 0 question — STRATE VIDE » au lieu d'omettre la ligne : le trou est désormais visible dans la sortie même. **Reporté au lot 1**, débloqué par : quelques questions de suivi ajoutées au jeu, et une relecture humaine pour les valider (cf. « Jeu doré non relu »). |
| P2 | Ratio caractères/token posé au jugé | `_CHARS_PER_TOKEN = 3,5` gouverne tout le budget. Le log `prompt_eval_count` donne maintenant de quoi le calibrer, mais aucune campagne ne l'a encore fait (§ ci-dessus). |
| P2 | `HISTORY_WINDOW_SHARE` posé au jugé | 25 % de la fenêtre de prompt pour l'historique, 75 % pour les sources. Forfait assumé : arbitrer demande de mesurer la qualité des réponses **multi-tour**, ce que `make eval` ne fait pas — le jeu doré ne pose que des questions isolées. Le réglage est exposé pour qu'un balayage soit possible le jour où la mesure existe. |
| P3 | Balises de tour du gabarit de chat | 34 caractères par message, le décompte du gabarit Gemma appliqué à tous les modèles. Le log `prompt_eval_count` permettrait de le déduire par différence. |
| P3 | `test_les_balises_de_tour_valent_le_gabarit_qu_elles_citent` ne valide rien d'externe | Le test recalcule `len("<start_of_turn>user\n") + len("<end_of_turn>\n")`, soit les mêmes littéraux que le commentaire de la constante : c'est un épinglage contre la dérive — utile — mais sa docstring laisse entendre une validation contre le gabarit réel de Gemma, qui n'a pas lieu. Le vrai gabarit vit dans le modèle Ollama, pas dans ce dépôt. **Reporté au lot 1**, débloqué par : reformuler la docstring en « épinglage », ou lire le gabarit du modèle servi — ce qui demande la stack. |
| P2 | Latence de génération | ~3 à 10 s contre 0,5 s de recherche — **ordres de grandeur hérités, non remesurés depuis**. Le levier est le LLM — quantisation, `num_predict`, modèle plus petit — pas la recherche. La partition des étages (lot 4) donne de quoi le vérifier plutôt que de le répéter : `generation_ms` face à `dense_ms + lexical_ms + fusion_ms + rerank_ms`, en p50 et p95. Débloqué par : la stack démarrée. |
| P2 | Coût de la traduction | Un appel LLM par question s'ajoute à la recherche. Un cache des traductions, ou un modèle plus petit dédié, l'amortirait. Le prix est désormais isolé (`translation_ms`, distinct de `rewrite_ms`) : l'amortissement peut être arbitré sur une mesure, plus sur une intuition. Débloqué par : la stack démarrée. |
| P3 | Observabilité, et pourquoi pas OpenTelemetry | Logs console uniquement, pas de tracing distribué ni de métriques exportées. **Écarté du lot 4 explicitement** : c'est de l'observabilité de production, cela ajoute des dépendances, et cela ne rend décidable aucun des trois arbitrages qui motivaient le lot — l'ablation du graphe, le seuil de pertinence, le modèle d'embedding. La partition des étages couvre le besoin de mesure hors ligne ; un tracing n'est utile que le jour où le service a des utilisateurs et une charge, et il n'en a ni l'un ni l'autre. |
| P2 | `lexical_stale` coûte un `count()` ChromaDB par appel | Un aller-retour par recherche lexicale **et** par sonde `/health`. Mesuré au compteur : 10 recherches → 10 `count()`, 5 appels à `lexical_ready` → 5 `count()`. Le docstring de la fonction a d'abord affirmé le contraire (« le compte est déjà lu au moment de la construction, donc la comparaison ne coûte rien de neuf ») : c'est faux, la lecture de la construction ne sert qu'à la construction, et la phrase est corrigée. Candidat à un cache sur fenêtre courte — mais c'est un arbitrage de performance, pas une correction : il faut savoir ce que coûte réellement un `count()` contre le vrai ChromaDB face au risque de servir un index périmé quelques secondes de plus. **Débloqué par : la stack démarrée**, absente ici. Le passage de `/health` en parallèle (§1.27) ne le traite pas : le `count()` reste payé à chaque appel, il est seulement borné par le plafond des sondes. |
| P3 | 79 `# noqa` inertes subsistent hors du périmètre des lots 4 et 4b | **Mesuré au lot 4b.** `PLR2004`, `BLE001` et `SLF001` ne figurent dans aucun des neuf groupes du `select` de `pyproject.toml` (`E, W, F, I, UP, B, SIM, N, ANN`) : ces marqueurs ne dérogent à rien, ils ne suppriment aucun avertissement. Ce sont des commentaires morts, et ils coûtent surtout de la confusion — trois comptes différents ont circulé pour les seuls 26 du lot 4, avant qu'on ne s'avise qu'aucun ne dérogeait à quoi que ce soit. Les 26 du périmètre sont retirés ; les 79 restants sont dans 24 fichiers qu'aucun de ces lots ne touche, et les balayer ici aurait grossi un diff en cours d'audit. Nuance pour le balayage à venir : les `BLE001` marquent les absorptions larges assumées, que `test_absorptions.py` garde par ailleurs — les retirer perd une intention écrite, à remplacer par un vrai commentaire plutôt qu'à effacer. Débloqué par : rien, c'est un balayage mécanique dans un lot dédié. |
| P3 | L'extrait d'`AgentState` de `agent_architecture.md` avait divergé | **Trouvé au lot 4, corrigé.** Il omettait `search_query`, `search_translation`, `max_sources`, `top_k` et `dropped_contexts` — cinq champs antérieurs à ce lot. Recalé sur `src/agent/state.py`, qui fait foi. Rien ne force les deux à s'accorder : un extrait de code recopié dans un document est un candidat permanent à la dérive, et celui-là n'est pas couvert par `test_coherence_depot.py` — le comparer demanderait de parser le fichier Markdown, ce qui n'a pas été fait. |
| P3 | Deux lecteurs composites de `_etat`, hors de `LexicalIndex` | `retriever.lexical_stale` lit `ready`, puis `count()`, puis `size` en trois temps ; `rebuild_lexical_index` lit `size` dans ses deux branches. Une reconstruction concurrente peut donc s'intercaler entre deux de ces lectures. **Bénin, et il faut dire pourquoi :** `_etat` n'est jamais remis à `None` et chaque `search` capture l'état en une fois (§1.22), donc ni mauvais chunk ni `IndexError` — c'est de la comptabilité. Au pire un verdict de péremption faux, donc une reconstruction de fond superflue, ou une taille rendue par `/reindex` qui décrit l'index d'après plutôt que celui qu'il vient de construire. Mais l'affirmation « un tuple remplacé d'un seul coup referme la fenêtre » est vraie de `LexicalIndex`, **pas de tout ce qui le lit**. Un accesseur `etat()` à capture unique fermerait le sujet. Non fait : ce lot a déjà été audité, et grossir son diff après coup remet tout en cause. |
| P2 | Index BM25 en mémoire, et le **~9 s non mesuré** | **Site canonique de la réserve sur ce chiffre : tout autre endroit qui l'écrit renvoie ici.** Le « ~9 s » de la construction de l'index circule dans ce dépôt depuis sa documentation d'origine, et **aucune exécution ne l'a produit** — ni ce lot, ni aucun message de commit, ni aucun fichier de `runs/`. C'est un ordre de grandeur hérité, pas une mesure. Il porte pourtant quatre justifications de conception : le fil démon de la reconstruction de fond, la fusion des réindexations concurrentes, le passage de la lecture du corpus sous le verrou, et le non-déplacement de la première construction au démarrage. Aucune de ces quatre ne tombe si le chiffre est faux — chacune tient dès que le parcours du corpus est *long devant une requête*, ce qui est structurellement vrai puisqu'il lit tout le corpus par lots de 2000 — mais leur dimensionnement, lui, en dépend. À mesurer : chronométrer `_charger_corpus` sur le corpus réel, ce qui **demande la stack démarrée**, absente ici (`llm-net`, `ollama-central`, stores arrêtés). En attendant, le chiffre est étiqueté « non mesuré » partout où il apparaît. Le reste de la ligne : la **première** requête après un démarrage paie cette construction, et cela n'a pas changé — c'est la seule encore payée par une requête utilisateur. Les reconstructions ultérieures tournent en tâche de fond (§1.21), et N requêtes concurrentes n'en déclenchent plus qu'une (§1.22). Déplacer la première construction au démarrage retarderait la mise en service d'autant : arbitrage non rendu, faute de la mesure ci-dessus. |
| P3 | Multi-workers | Les sessions sont persistées — et leur purge l'est aussi désormais (§1.20), donc un worker purge ce qu'un autre a créé. Mais l'index BM25 et les modèles restent chargés par processus : N workers = N copies en mémoire, et surtout **`POST /reindex` ne reconstruit que l'index du worker qui reçoit la requête** — les autres restent périmés jusqu'à ce que leur filet de comparaison des comptes les rattrape. Non traité : le contrat de réindexation suppose aujourd'hui un worker unique. |
| P2 | Entretien des dépendances | Le projet a démarré sur des versions déjà vieilles d'onze mois, jamais montées ensuite. Il n'existe aucun garde-fou : `make audit` ne tourne pas en CI, rien ne signale une version qui vieillit. |

---

## 3. Ouvert — dépend de l'ingestion

À transmettre à `rag-ingestion-pipeline` ; rien n'est faisable côté agent.

### 3.1 → FERMÉ par le pipeline — le graphe n'est plus plat, et cette entrée était le dernier à le croire

**Cette entrée décrivait le graphe de production. Elle ne le décrit plus, et
elle demandait au pipeline un travail qu'il a livré.** Ce qu'elle disait — 901
`SectionHeader` enfants d'un `Document`, 0 enfant d'un autre `SectionHeader`, 0
chemin de longueur 3 — était juste quand ce fut mesuré, et est **faux
aujourd'hui**.

La correction qu'elle réclamait est exactement celle que le pipeline a faite :
stocker le niveau du titre sur le tag et chaîner les parents. Il l'a faite, avec
la purge du space que cette entrée annonçait.

**Le nouveau constat, avec sa mesure, est au §4.6.** Il n'est pas « rien à
faire » : la platitude servait de **justification** à des décisions prises de ce
côté, et ces justifications sont mortes avec elle.

### 3.2 Modèle d'embedding — le monolingue est derrière nous, la contrainte reste

**Cette entrée annonçait `all-MiniLM-L6-v2` comme le modèle en service. C'était
vrai, ce ne l'est plus, et la laisser telle quelle était dangereux** : une
conversation d'ingestion qui la lit avant de réingérer choisirait le modèle
anglais, alors que l'agent interroge avec le multilingue.

Le modèle en service est `paraphrase-multilingual-MiniLM-L12-v2` (384
dimensions), défaut de `settings.py`. Preuve que l'ingestion l'utilisait bien :
`runs/final.json` porte `rappel_recherche = 0,985`, ce qui est **impossible**
avec deux embedders différents — un index construit avec un autre modèle rend
des passages au hasard.

Ce qui reste vrai et n'a pas bougé : le modèle est décidé à l'ingestion, il
**doit** coïncider des deux côtés, et un désaccord est la panne la plus coûteuse
du système — ni exception, ni log, ni sonde, seulement des passages plausibles et
faux ([stores.md](stores.md)). En changer pour l'état de l'art (`bge-m3`,
`multilingual-e5-large`) **impose une réingestion complète** ; c'est le dernier
lot du plan, et il ne se décide pas sans campagne appariée.

Toute réingestion doit donc employer `paraphrase-multilingual-MiniLM-L12-v2`,
sauf décision explicite de changer les DEUX côtés à la fois. Voir
[pour_le_pipeline_ingestion.md](pour_le_pipeline_ingestion.md).

### 3.3 Illustrations sans légende

L'arête `DESCRIBES` couvre les visuels légendés dans le document d'origine. Une
figure sans légende reste muette : introuvable par la recherche sémantique, et
impossible à juger pertinente par le LLM. Une description générée par VLM à
l'ingestion, indexée dans ChromaDB, comblerait ce trou.

---

## 4. Chantier ouvert le 3 septembre 2026 — ce que la passation du pipeline a révélé

Le pipeline d'ingestion a épuisé son plan, mené sa première campagne de
référence le 2 septembre 2026, et écrit une passation. Ce dépôt-ci **n'a pas
bougé depuis le 28 août 2026** (`mesuré` : `git log -1 --date=short`) : il a
donc dormi pendant que le corpus était remplacé et le graphe restructuré sous
lui.

**Toutes les entrées ci-dessous ont été mesurées le 3 septembre 2026**, chacune
par une commande dont la sortie a été lue. Le mandat du chantier est
[`pilotage_du_chantier.md`](pilotage_du_chantier.md).

### 4.1 → FERMÉ par le lot 1 — le garde-fou d'identité Git n'existait pas sur ce dépôt

> **Fermé le 3 septembre 2026** par le lot 1, fusionné en `9596720`. Le montage
> éprouvé du dépôt jumeau a été porté, avec un drapeau que ce dépôt-ci exigeait
> et que le jumeau n'a pas besoin — voir la fin de cette entrée. Le constat
> ci-dessous est conservé parce qu'il dit **pourquoi**, et qu'un garde dont on a
> oublié le motif finit par être retiré.

**Gravité à l'ouverture : la plus haute du chantier, parce qu'elle est
irréversible.**

`mesuré` le 3 septembre 2026 :

| Ce qui a été cherché | Commande | Résultat |
|---|---|---|
| une identité configurée | `git config --list --show-origin \| grep -i user` | `rc=1` — **rien**, ni local, ni global |
| ce que git utiliserait | `git var GIT_AUTHOR_IDENT` | `rc≠0`, « Author identity unknown » |
| des hooks armés | `ls .git/hooks/` | **uniquement des `*.sample`** |
| le hook versionné du dépôt jumeau | `ls scripts/git-hooks/` | **absent** |
| une cible d'installation | `grep install Makefile` | **absente** |

Autrement dit : **rien ne protège ce dépôt**, et le geste qui le défait est une
seule commande.

**L'incident des sept commits est arrivé ICI, sur ce dépôt-ci — et cette entrée
l'attribuait au dépôt jumeau.** C'était faux, et la correction change la nature
du constat. Le lot 1 l'a relevé, et le pilote a reproduit ses trois mesures, qui
concordent (`mesuré` le 3 septembre 2026) :

1. **la source primaire nomme ce dépôt.** `scripts/git-hooks/pre-commit` du
   jumeau, versionné, porte en commentaire : « Sept commits sont partis avec
   l'adresse professionnelle sur le dépôt personnel **`rag-agent-chat`**, et il
   a fallu réécrire l'historique PUIS détruire et recréer le dépôt ». C'est le
   développeur qui a fait le travail qui l'écrit, dans le fichier même du garde ;
2. **le compte de commits désigne ce dépôt.** « 165 commits réécrits » : ce
   dépôt-ci en portait exactement **165** à `a6b9c0c`. Le jumeau en portait
   **111** au commit où il mesure lui-même ce chiffre (`a005172`), et **235** sur
   `main` aujourd'hui — 165 n'a jamais été son compte ;
3. **la date de création du dépôt distant le confirme.**
   `api.github.com/repos/floSa/rag-agent-chat` rend
   `created_at = 2026-08-28T07:47:48Z`, quand le plus ancien commit du clone est
   du **30 avril 2026**. Un dépôt créé quatre mois après son premier commit est
   un dépôt **recréé**. Pour comparaison, le jumeau rend
   `created_at = 2026-07-12`, au milieu de son historique : aucune signature de
   recréation.

**Ce que ça change, et ce n'est pas une querelle d'attribution.** Cette entrée
concluait « il n'y a rien à réparer : il y a un garde à poser avant que quelque
chose soit à réparer », et expliquait l'absence de mauvais commit par un
`fail-closed` par accident. **La vraie raison est que les mauvais commits ont
déjà été purgés et le dépôt GitHub déjà détruit et recréé.** La gravité de ce
constat n'est donc pas « ce qui pourrait arriver » : c'est **ce qui est arrivé
ici**, et dont il ne reste aucune trace dans `git log` précisément parce que le
prix a été payé. Le trou est resté ouvert après la réparation, et le garde n'a
jamais été posé de ce côté.

**Ce que l'historique de ce dépôt porte aujourd'hui, et il est sain** (`mesuré`
le 3 septembre 2026 : `git log --all --format='%ae | %ce' | sort | uniq -c`) :
**167** commits — 165 avant l'ouverture du chantier —, **deux adresses et elles
seules**, `florian_horellou@laposte.net` (91) et `florian.horellou@gmail.com`
(76), **0** occurrence de `@aosis.net`, et **0** attribution à un assistant de
génération de code.

**Ce compte est un état de poste, pas une propriété de l'historique**, et
l'entrée le présentait comme une propriété. Le lot 1 l'a mesuré à 167 trois
heures après que le pilote eut écrit 165 : l'écart était exactement les deux
commits d'ouverture du chantier. Un chiffre qui bouge à chaque commit se borne à
sa révision — d'où le `a6b9c0c` ci-dessus — ou ne s'écrit pas.

**La correction, et elle est à porter, pas à inventer :** le dépôt jumeau porte
un montage éprouvé, avec son test — `scripts/git-hooks/pre-commit`,
`scripts/installer-les-garde-fous.sh`, une cible `make install`, et
`tests/unit/test_installation_des_garde_fous.py`. Deux propriétés de ce montage
sont non négociables et se perdent si on l'écrit de zéro :

1. **la copie `pre-commit.legacy` vit HORS de l'arbre de travail.** Le hook
   généré par le framework `pre-commit` ouvre sa configuration en chemin
   **relatif** : un contrôle déclaré dans `.pre-commit-config.yaml` ne vaut que
   pour les arbres dont la configuration le porte. La copie figée est la seule
   couche qui vaille pour tout commit, toute branche, tout `git bisect`, tout
   HEAD détaché ;
2. **`pre-commit install -f` supprime cette couche.** Le framework le suggère
   lui-même dans sa sortie. Ne jamais le passer, et le vérifier.

Et deux effets de bord à connaître avant de poser le montage : l'installation
**grave un chemin absolu** vers le `.venv` de l'arbre d'où elle est lancée, et
`.git/hooks` est partagé par tout le clone — donc lancer l'installation depuis
le clone principal, et la relancer après tout retrait d'arbre de travail ; et la
liste blanche d'adresses a **deux sites au runtime**, le fichier versionné et la
copie figée, donc toute édition de la liste demande une réinstallation.

Le geste du pilote, fait le 3 septembre 2026 en attendant le garde, est au §2.1
de [`pilotage_du_chantier.md`](pilotage_du_chantier.md).

### 4.2 → FERMÉ par le lot 1 — l'agent tourne, et l'exigence 5 est prouvée en marche

> **Fermé le 3 septembre 2026**, lot 1, `9596720`. L'agent tourne (projet Compose
> `rag-agent-chat`, ancré au **clone principal**), et `POST /reindex` a été
> mesuré en service — par le lot, puis **indépendamment par son audit sur
> l'agent vivant**. L'exigence 5 du contrat n'est plus « non éprouvée ».
>
> Ce que la preuve a établi au-delà de l'aller simple : le filet interne de
> l'agent compare deux entiers, donc il est **aveugle** à une réingestion qui
> retire autant de chunks qu'elle en ajoute — et dans cet état la recherche
> lexicale rend **zéro résultat sur tout le corpus** pendant que la sonde annonce
> un index prêt. C'est ce que le contrat répare, et c'est désormais gardé par un
> test dont l'audit a mesuré qu'il est **le seul garde de deux mutations du
> producteur**.
>
> **`.env.example` porte toujours `MINIO_ROOT_USER=minioadmin` là où ce poste
> exige `admin`** : le lot ne l'a pas corrigé, c'était hors de son mandat. Reste
> ouvert, petit, sans garde.

Le constat d'ouverture, conservé pour son détail :

C'est ce qui bloque la preuve de l'**exigence 5** du contrat (`POST /reindex`),
la seule des cinq qui ne soit pas prouvée.

`mesuré` le 3 septembre 2026 :

- `ls .env` → **absent**. `.env.example` est versionné, complet, et
  `.gitignore` couvre `.env` ;
- `docker ps` → **aucun conteneur de l'agent**. La pile du pipeline est debout
  (9 services, projet `rag-ingestion-pipeline`), `llm-service` aussi, et les
  deux réseaux externes qu'attend `docker-compose.yml` existent :
  `rag_network` et `llm-net` ;
- `docker exec ollama-central ollama list` → `gemma4:e4b` **est servi**, et
  c'est bien celui que `.env.example` nomme ;
- ChromaDB sert la collection `rag_documents` avec **4 367** chunks, et
  `.env.example` attend exactement ce nom.

**Les deux valeurs qui ne se devinent pas depuis `.env.example`, et l'une y est
fausse :**

| Clé | Ce que `.env.example` propose | Ce que le poste exige |
|---|---|---|
| `MINIO_ROOT_USER` | `minioadmin` | **`admin`** — c'est ce que porte le `.env` du pipeline. La valeur de l'exemple est **fausse pour ce poste** |
| `MINIO_ROOT_PASSWORD` | vide, avec le commentaire « même valeur que rag-ingestion-pipeline » | à recopier depuis le `.env` du pipeline. **Ne la recopie dans aucun document, aucun commit, aucun rapport** |

`API_KEY` est vide de ce côté et `AGENT_API_KEY` est vide du côté pipeline
(`mesuré`) : les deux s'accordent, aucun en-tête n'est envoyé et aucun n'est
exigé. `require_api_key` ne fait rien quand la clé est vide
(`src/api/main.py:147`).

**Les deux moitiés de l'exigence 5 s'accordent à la lecture**, et c'est tout ce
qui est établi — rien ne l'a jamais prouvée en marche :

| | Côté pipeline (`src/pipeline/reindex.py`) | Côté agent (`src/api/main.py`) |
|---|---|---|
| cible | `f"{url}{REINDEX_PATH}"`, `REINDEX_PATH = "/reindex"`, `AGENT_SERVICE_URL=http://agent-api:8000` | `@app.post("/reindex")` |
| en-tête | `API_KEY_HEADER = "X-API-Key"`, omis si la clé est vide | `x_api_key: str = Header(default="")` |
| réponse lue | `_lire_compte` cherche `chunks_indexed` | `ReindexResponse(chunks_indexed=…, stale=…)` |

### 4.3 → FERMÉ par le lot 5 — les deux jeux régénérés, la campagne de référence établie, et un instrument qui refuse de mesurer sur le vide

**Ce qui était en cause : la seule mesure de qualité du dépôt était morte, et
elle ne rendait pas d'erreur — elle aurait rendu un tableau faux.**

#### Ce que le lot 5 a livré, le 8 septembre 2026

| | |
|---|---|
| **le jeu de réglage régénéré** | `tests/fixtures/golden_qa_generated.yaml` — **138** questions sur le corpus en service, **130** ancrages distincts, **130 / 130** présents dans NebulaGraph **et** dans ChromaDB |
| **les 30 questions du pipeline adoptées** | `tests/fixtures/jeu_de_questions_pipeline.yaml` — transposées par `scripts/adopter_le_jeu_du_pipeline.py`, pas recopiées ; **44 / 44** ancrages présents dans les deux stores. Le site canonique du jeu reste chez le pipeline, et l'empreinte SHA-256 de la source est gravée dans le fichier |
| **l'antécédent, rejouable** | `scripts/verifier_les_ancrages.py`, en lecture seule et **gardée** en lecture seule par lecture de son arbre syntaxique. Bilan versionné : `runs/2026-09-08-ancrages.json` |
| **la campagne de référence** | `runs/2026-09-08-reference.json` et `runs/2026-09-08-controle-30.json`, compte rendu à [`campagnes/2026-09-08-campagne-de-reference.md`](campagnes/2026-09-08-campagne-de-reference.md) — **site canonique de tous les chiffres de la campagne**, qui ne sont recopiés nulle part |
| **`runs/final.json`** | **retiré comme cible de `--compare`**, conservé comme trace du régime d'avant. Motif ci-dessous |
| **la promesse fausse au pipeline** | corrigée à son site, [`pour_le_pipeline_ingestion.md`](pour_le_pipeline_ingestion.md), et gardée contre son retour |

#### CE QUE LE LOT A TROUVÉ ET QUE CETTE ENTRÉE NE VOYAIT PAS — trois défauts

**(a) Le piège du `--compare` était armé, et il est plus grave que le zéro de
rappel.** `generate_golden.py` numérote ses questions dans l'ordre de
génération : le jeu régénéré porte **exactement les mêmes 138 identifiants** que
celui du 3 août 2026. `desaccord_de_jeu`, qui apparie sur les identifiants, ne
voyait donc **rien**, et le `--compare runs/final.json` de `make eval` aurait
imprimé flèches et p-values sur 138 paires dont les deux moitiés mesurent deux
corpus. *Un jeu périmé rend 0 % de rappel, ce qui se voit ; deux corpus sous une
même numérotation rendent des chiffres **plausibles**, ce qui ne se voit pas.*
Fermé par `empreinte_des_ancrages` — le SHA-256 des couples (identifiant,
ancrages triés), inscrit dans chaque campagne, et dont l'**absence** est refusée
au même titre qu'une divergence. C'est la décision 2 du lot 3 réappliquée.

**(b) Un TROISIÈME jeu de questions existait, et c'était le `--golden` par
DÉFAUT.** `tests/fixtures/golden_qa.json`, 15 questions écrites à la main, dont
**13 à réponse** — les deux autres, `Q-010` et `Q-011`, sont des abstentions ;
« quinze questions à réponse » était faux de deux, `mesuré` le 8 septembre 2026
sur le contenu du fichier tel que `4eedb2a` le portait (trouvaille N8). Ses
treize questions à réponse portaient **0** `gold_element_ids` : `rappel_recherche`,
`rappel_elements`, `mrr` et `rappel_contexte` valaient `None` sur toutes,
c'est-à-dire **absents des moyennes**. Un `None` se lit « sans objet », là où un
`0.0` se lit « cassé » : il était donc **plus silencieux** que le jeu de 138. Et
ses `gold_documents` nommaient le corpus disparu. Retiré ; ce qu'il apportait —
relu par un humain, couvrant multi-saut, synthèse et suivi — est apporté par les
trente questions du pipeline, qui sont relues **et** annotées à l'élément contre
le corpus en service. Trouvé par un garde de ce lot, pas par une relecture.

**(d) UN GARDE DE CE LOT RENDAIT `detect-secrets` MOINS ARMABLE, et c'est la
mesure du lot qui l'a attrapé.** `empreinte_des_ancrages` s'écrit dans un fichier
JSON, où aucun `pragma: allowlist secret` n'est possible — le JSON n'admet pas de
commentaire. Une empreinte de 64 hexadécimaux en valeur de mapping est exactement
ce que le détecteur relève : **6** détections, les deux campagnes du lot et les
quatre campagnes synthétiques de `tests/fixtures/`. *Le lot faisait tomber
l'inventaire de 36 à 2 d'un côté et en rajoutait 6 de l'autre.* Corrigé en
préfixant `sha256:` — le détecteur exige que la chaîne **entière** soit
hexadécimale, et le préfixe ne cache rien, il **nomme** l'algorithme. Mesure des
trois formes et commande de reproduction : §7 du compte rendu de campagne.
*C'est la leçon du chantier appliquée à soi-même : mesure ce que le hook dit de
ton fichier de données **avant** de commiter, pas après.*

**(c) Un `--compare` vers un fichier absent sortait en 0, sans un mot.** La forme
était `if args.compare and args.compare.exists()`. Une cible renommée, déplacée
ou jamais commitée faisait imprimer le résumé et rien d'autre — ce qui se lit
« rien n'a bougé ». Trouvé en réécrivant la recette de `make eval`, dont la cible
est justement remplacée par ce lot. Sort désormais en 2, et les deux cibles
d'évaluation **dépendent** de `verifier-les-ancrages` : l'ordre est porté par le
`Makefile`, pas par la mémoire de celui qui lance la campagne.

#### Les gardes posés, et la mutation qui fait rougir chacun

| Le garde | Ce qu'il tient | La mutation qui le fait rougir |
|---|---|---|
| `test_jeux_de_questions.test_aucune_question_a_reponse_ne_designe_le_vide` | une question à réponse porte au moins un ancrage, une abstention n'en porte aucun | retirer l'ancrage de `G-001` → rouge nommé |
| `..._l_empreinte_de_provenance_porte_son_pragma` | l'empreinte de la source est annotée pour `detect-secrets` | retirer le pragma → rouge, et `detect-secrets-hook` passe de `rc=0` à `rc=1`, une détection |
| `..._le_jeu_du_pipeline_porte_ses_cinq_strates_a_l_effectif` | 12 / 8 / 4 / 4 / 2 | une strate amputée → rouge |
| `..._la_reserve_du_jeu_de_30_voyage_avec_lui` | la réserve vit dans le fichier de données | effacer `_reserve` → rouge |
| `..._les_quatre_questions_de_suivi_portent_leur_historique` | `chat_history` présent sur les 4 | le retirer d'une → rouge nommé `q25` |
| `test_verification_des_ancrages.TestLaSondeEstEnLectureSeule` | la sonde n'écrit dans aucun store | `collection.modify(...)` → rouge ; `INSERT VERTEX …` → rouge. Les DEUX directions mesurées, et le garde a été **refait** parce que sa première forme rougissait sur un `set.add` légitime |
| `..._un_jeu_sous_la_mauvaise_cle_est_refuse_et_non_declare_vert` | un schéma inconnu lève, au lieu de rendre « 0 ancrage » donc vert | lire une seule clé d'ancrage → la sonde déclarerait le jeu du pipeline conforme sans rien vérifier |
| `test_comparaison_appariee.test_l_empreinte_distingue_deux_corpus_a_numerotation_identique` | l'empreinte sépare deux corpus de même numérotation, et NE sépare pas une reformulation | — c'est le test qui prouve que le garde atteint son cas |
| `test_coherence_depot.test_les_cibles_d_evaluation_ne_nomment_que_des_fichiers_qui_existent` | aucune cible d'évaluation ne pointe un chemin vide | viser un `runs/` ou un `tests/fixtures/` qui n'existe pas → rouge nommé. **ATTRIBUTION CORRIGÉE le 8 septembre 2026** : ce tableau prêtait ici la mutation « remettre `--compare runs/final.json` », que ce garde **ne voit pas** — `runs/final.json` existe toujours, donc le chemin désigne bien un fichier. `mesuré` : sous cette mutation, ce garde **passe**, et c'est son voisin `..._make_eval_ne_vise_plus_aucun_jeu_ni_aucune_cible_retires_par_le_lot_5` qui rougit, seul. Pas de trou de couverture — mais le tableau nommait un garde décoratif *pour cette mutation-là*, ce qui est la façon la moins visible de désarmer une preuve |
| `..._la_verification_des_ancrages_est_l_antecedent_des_deux_campagnes` | `eval` et `eval-controle` dépendent de la vérification | retirer la dépendance → rouge |
| `..._la_promesse_retiree_au_pipeline_n_est_plus_affirmee_nulle_part` | la phrase fausse peut être CITÉE, plus AFFIRMÉE | la réaffirmer hors guillemets → rouge avec sa ligne |

#### CE QUE LE LOT N'A PAS FERMÉ

- **`reviewed: false` sur les 130 questions générées.** Aucune relecture humaine
  n'a eu lieu : c'est du **silver**, et le fichier le dit. La promotion en gold
  demande une relecture, qui n'est pas un travail de lot ;
- **la strate de suivi est absente du jeu de réglage.** `generate_golden.py`
  n'écrit aucun `chat_history`. Les quatre questions de suivi du jeu de contrôle
  la peuplent, mais quatre questions ne règlent rien. Peupler le jeu de réglage
  en questions de suivi est un chantier à part ;
- **l'axe translinguistique reste coupé en deux**, et cela ne dépend pas de ce
  dépôt : `mesuré` le 8 septembre 2026, **4 367 chunks sur 4 367** portent
  `language: en`. « Question française → document anglais » est mesurable ;
  l'inverse a disparu avec le corpus français, et le rétablir demanderait
  d'ingérer un document français — ce que ce chantier ne fait pas ;
  reste **une seule** question française dans le jeu de contrôle, ce qui est un
  effectif sur lequel rien ne se décide ;
- **`detect-secrets` n'est pas armé sur ce dépôt.** Le lot a fait tomber
  l'inventaire de **36** détections à **2**, ce qui le rend armable ; l'armer est
  un travail à part, avec ses mesures, et `.pre-commit-config.yaml` dit pourquoi
  il ne l'est pas.

---

#### L'état d'avant, et la mesure qui l'a établi

**Gravité : c'était la seule mesure de qualité du dépôt, et elle était morte.**

`mesuré` le 3 septembre 2026, en confrontant
`tests/fixtures/golden_qa_generated.json` au graphe NebulaGraph en service :

| | |
|---|---|
| questions du jeu doré | **138** |
| `gold_element_ids` distincts qu'elles désignent | **129** |
| ceux qui existent dans le graphe | **0** |

La cause n'est pas une dérive d'identifiants : **c'est un autre corpus.** Les
`gold_documents` du jeu nomment `htms/Practical MLOps`,
`htms/The Statistics and Calculus with Python Workshop`,
`mds/Architectures de LLM`, `mds/Infrastructure & Inférence`,
`mds/Multimodal & Agents` et `pdfs`. Le graphe en service porte **23**
documents répartis en trois collections : `MLOps with Databricks` (11),
`Practical MLflow for Generative AI on Databricks` (11), et une collection vide
`""` (1 — le PDF). **Aucun ouvrage en commun.** La convention de chemin, elle,
n'a pas changé : les VID de documents portent toujours le préfixe `htms/`.

Trois conséquences, et la troisième est une phrase à corriger :

1. **`make eval` ne peut rendre que des zéros de rappel.** Il n'est pas cassé au
   sens d'une erreur : il tournerait, et rendrait un tableau faux ;
2. **`runs/final.json` — la cible de `--compare`, commitée le 3 août 2026 — est
   l'antécédent d'un corpus disparu.** Ses chiffres (`rappel_recherche = 0,985`,
   `mrr = 0,963`) ne décrivent plus rien d'actuel, et toute comparaison appariée
   contre lui confronte deux régimes ;
3. **[`pour_le_pipeline_ingestion.md`](pour_le_pipeline_ingestion.md) promet le
   contraire au pipeline**, et la promesse est maintenant démentie par la
   mesure : « c'est ce qui permet au jeu doré de survivre à une réingestion ».
   Le déterminisme de `element_id` est bien tenu par le pipeline — c'est le
   **corpus** qui a été remplacé, ce que le déterminisme ne pouvait pas couvrir.
   La phrase attribue au mauvais mécanisme une garantie qu'il n'a jamais donnée.

**LA DÉCISION EST PRISE — 3 septembre 2026, par l'utilisateur.** Trois issues
avaient été posées : retirer le jeu doré au profit des 30 questions du pipeline,
régénérer le jeu depuis le nouveau corpus, ou **les deux**. **Retenu : les
deux.**

Le motif, et il est le cœur du choix : les deux instruments **ne mesurent pas la
même chose**, et c'est précisément l'intérêt de les garder ensemble.

| | Le jeu régénéré (138) | Les 30 du pipeline |
|---|---|---|
| origine | `scripts/generate_golden.py`, écrit **depuis** les passages | écrites **à la main** après ingestion |
| ce qu'il donne | du **volume de réglage** — assez de questions pour qu'un écart sorte du bruit | un **contrôle indépendant** du générateur |
| sa faiblesse | **auto-référentiel** : la question est écrite POUR le passage qu'elle désigne, donc il ne révèle pas un défaut de retrieval que le générateur partage. Et il n'est **pas relu par un humain** | **trop peu nombreuses pour arbitrer un réglage** — leur propre réserve le dit : un écart de deux points est du bruit |

Aucun des deux seul ne suffit : le régénéré ne sait pas se contredire, les 30 ne
savent pas décider. **Le régénéré règle, les 30 contrôlent.**

Ce que la décision implique, et qui n'est pas gratuit :

- **`runs/final.json` est perdu comme antécédent**, définitivement — il décrit un
  corpus qui n'existe plus. Une **nouvelle campagne de référence** est à établir
  sur le corpus actuel, et c'est elle qui deviendra la cible de `--compare` ;
- **aucune comparaison historique n'est possible** à travers le remplacement de
  corpus. Ce n'est pas une perte qu'on choisit : elle est déjà consommée ;
- la strate « de suivi » et l'axe translinguistique portent les **deux bornes
  mesurées** du côté pipeline — la question encodée sans son historique, et un
  corpus entièrement anglais. Elles valent pour les 30, et il faudra décider si
  le jeu régénéré les reproduit.

C'est un lot à part entière, et il vient **après** les lots de gardes : mesurer
sur un agent dont les gardes ne sont pas posés ferait porter à la campagne le
bruit des corrections à venir.

**Et l'instrument valide existe déjà** : le jeu de 30 questions du pipeline,
`documentation/campagnes/2026-09-02-jeu-de-questions.yaml`, écrit **après**
l'ingestion, désignant 44 identifiants réels. Il porte sa propre réserve, et
elle interdit d'arbitrer un réglage avec lui — §5 de
[`pilotage_du_chantier.md`](pilotage_du_chantier.md).

### 4.4 → FERMÉ par le lot 3 — le lecteur confronte enfin son réglage à l'estampille de la collection

C'était l'**exigence 1** du contrat, et la panne la plus coûteuse du système :
les deux modèles candidats rendent des vecteurs de **384 dimensions**, donc
ChromaDB accepte sans broncher, aucune sonde de forme ne voit rien, et la
recherche rend des passages **plausibles et faux**. Vérifier la dimension ne
protège de rien — c'est le **nom** qui discrimine.

**Site canonique de la largeur des deux candidats**, et il est ici. `mesuré` le
4 septembre 2026, en lisant la seule configuration de pooling depuis le Hub —
quelques kilo-octets, aucun poids rapatrié :

```
huggingface_hub.hf_hub_download("sentence-transformers/<nom>", "1_Pooling/config.json")
  paraphrase-multilingual-MiniLM-L12-v2 -> word_embedding_dimension = 384
  all-MiniLM-L6-v2                      -> word_embedding_dimension = 384
```

Les deux nombres sont **égaux**, et c'est tout le problème : il n'existe, dans
la forme des vecteurs, rien qui distingue un index produit par l'un d'un index
produit par l'autre.

**L'état d'avant, `mesuré` le 3 puis le 4 septembre 2026.** Le pipeline gardait
les deux bouts — il refusait de démarrer sur un autre modèle et d'écrire dans
une collection produite par un autre — pendant que l'agent, qui LIT, ne
confrontait son réglage à rien : `grep -n "model_validator\|field_validator"
src/agent/settings.py` rendait `rc=1` et aucune ligne. Et la comparaison était
disponible en une lecture, parce que le pipeline **estampille déjà la
collection**.

**Ce qui a été mesuré contre les stores en service**, `mesuré` le 4 septembre
2026, en lecture seule — `chromadb.HttpClient(...).get_collection("rag_documents")`
puis `.metadata` et `.count()`, sans aucun `add` / `upsert` / `modify` :

| | valeur |
|---|---|
| `collection.metadata` | `{'embedding_model': 'paraphrase-multilingual-MiniLM-L12-v2'}` |
| `collection.count()` | 4 367 chunks |

**Ce que le lot 3 a écrit.** Une confrontation entre
`settings.embedding_model_name` et `collection.metadata["embedding_model"]`,
avec **deux décisions qui n'étaient pas tranchées** et qui le sont désormais au
site.

**Décision 1 — où le garde vit.** Le garde qui REFUSE est dans
`retriever._dense_search`, en **tête**, avant `_get_embedding_model()`. Trois
raisons, et la première est un piège payé ailleurs :

- `SentenceTransformer(nom)` **télécharge** le modèle absent du cache. Un garde
  placé après le chargement paierait le rapatriement du **mauvais** modèle avant
  de le refuser. `mesuré` le 4 septembre 2026 contre le vrai ChromaDB, réglage
  forcé en mémoire sur `all-MiniLM-L6-v2` : la recherche est refusée et la liste
  des modèles chargés est **vide** ;
- c'est le site qui **produit** le comportement à empêcher, et le seul que tout
  chemin de recherche traverse — `/search`, `/sources` et le nœud
  `node_retrieve` du graphe passent tous par `retrieve` ;
- un garde de démarrage seul ne couvre pas l'agent démarré **avant** une
  réingestion divergente, ni celui démarré pendant que ChromaDB ne répondait pas.

Le démarrage et `/health` en sont la **voix**, pas le garde. Et **le démarrage
ne lève pas** : `frontend` attend `agent-api` en `service_healthy`
(`docker-compose.yml`), donc un agent qui meurt laisse l'exploitant devant un
frontend absent, sans un mot sur le modèle d'embedding — exactement la
pathologie que `tests/unit/test_health_parallele.py` existe pour interdire. Le
processus reste debout pour expliquer ; toute recherche rend **503** avec les
deux noms dans le corps.

**Décision 2 — l'estampille absente est refusée**, au même titre qu'une
divergence. Un garde qui ne comparerait que lorsque l'estampille est présente
serait **décoratif sur exactement le cas où l'on ne sait pas ce qui a indexé**.
Le prix est réel et payé sciemment : une collection produite par un pipeline
plus ancien, qui n'estampillait pas, sera refusée. Le geste de réparation est
nommé dans le message d'erreur.

**Ce qui n'est refusé ni d'un côté ni de l'autre : l'estampille illisible.**
« Je n'ai pas pu lire » n'est ni « ça concorde » ni « ça diverge ». L'erreur du
store remonte telle quelle côté recherche, `/health` publie `unknown`, et cet
état-là ne dégrade pas le statut à lui seul — la sonde `chromadb` porte déjà ce
fait, et le publier deux fois ferait croire à deux pannes.

**Ce que la lecture coûte, et sa contrepartie.** `Collection.metadata` est une
propriété **locale** du client `chromadb==1.5.9` (`return self._model.metadata`),
remplie au `get_collection` : la lire ne fait **aucun** aller-retour, ce qui rend
la vérification tenable sur le chemin de chaque recherche. En retour, l'estampille
lue est celle capturée à l'**ouverture** de la collection : une réingestion qui
changerait de modèle pendant que l'agent tourne ne serait vue qu'après un
`reset_connection()` — donc après une panne de Chroma, ou un redémarrage. C'est
la réserve de ce garde, et elle est écrite au site.

**Comment on sait que c'est un garde et pas un ornement.** Onze mutations,
`mesuré` le 4 septembre 2026, chacune restaurée et l'arbre vérifié propre après ;
`git diff --numstat` confirme que le texte a bougé à chaque fois, et le rc relevé
est celui de `pytest` (`make`, lui, rend 2). Dix rougissent, la onzième est un
**témoin inerte** — un commentaire réécrit — qui reste vert : sans lui, un vert
ne se distinguerait pas d'une mutation qui n'a rien touché.

> **L'ÉCART DE COMPTES, TRANCHÉ LE 7 SEPTEMBRE 2026, ET IL NE SE TRANCHE PAS
> COMME LE PILOTE L'A DEMANDÉ.** L'audit du lot 3 a relevé que cette page
> annonçait **onze** mutations là où le rapport du lot en tabulait **douze**, et
> a demandé à `Conv' 31` de dire *lequel était juste*. Ce n'est pas décidable :
> **le rapport du lot 3 n'a jamais été un artefact du dépôt** — il a été rendu
> dans une conversation, `git log --all --grep` n'en retrouve rien et
> `documentation/audits/` ne porte que l'audit du lot 1. Aucune des deux
> tabulations n'est donc relisible aujourd'hui, et désigner une gagnante serait
> exactement le geste que ce chantier sanctionne : conclure sans mesure. La
> seule chose que la page peut dire est ce qu'elle peut prouver, et
> l'affirmation ci-dessus est désormais **le site canonique du compte** — le
> onze est interne à ce paragraphe, où il se vérifie (dix plus le témoin).
>
> **La leçon est structurelle, et elle vaut plus que le chiffre.** Un compte qui
> ne vit que dans une conversation n'est pas vérifiable, donc n'est pas un
> compte : c'est la même famille que les affirmations « toutes / aucune / il n'y
> a plus » que le §4.4 a remplacées par un inventaire gardé. Les batteries de
> mutations doivent atterrir dans le dépôt pour compter. Celle de la réparation
> des deux bloquants est au **§4.21**, dans cette page.

**Une correction de raisonnement, conservée.** Le §3.2 de ce registre prouvait la
concordance des modèles par un détour : « `runs/final.json` porte
`rappel_recherche = 0,985`, ce qui est impossible avec deux embedders
différents ». Le raisonnement est juste, mais **son antécédent a péri** — ce run
décrit un corpus qui n'est plus là (§4.3). La preuve directe est désormais
l'estampille ci-dessus, et elle est **gardée par un test** plutôt que relue.

### 4.5 → FERMÉ par le lot 2 — les trois réserves étaient écrites nulle part, et le code n'était juste que par construction

Le pipeline garantit que `sequence` porte l'ordre et qu'elle est monotone
(exigence 4). Ce qu'il ne peut pas écrire, parce que ça décrit comment l'agent
*lit*, ce sont les trois réserves. **`grep -rn "sequence" documentation/`
n'en rend aucune** (`mesuré`, 3 septembre 2026) : les 10 occurrences décrivent
l'arête, jamais ses pièges.

**Les trois réserves, reproduites de mes mains** sur les 15 173 arêtes
`PARENT_OF` extraites du graphe en service — les trois chiffres du pipeline
tombent à l'unité.

> **Site canonique de tous les taux publiés ci-dessous** — le `167 sur 692`, le
> `994`, les `1 141` / `7,5 %` / `162` et la perte maximale de `12 sur 13` :
> [`stores.md`](stores.md), au § « Ce que ces trois réserves interdisent ». Cette
> entrée-ci les reprend pour raconter **comment ils ont été trouvés** ; elle n'en
> est pas le site. Tous sont rejouables par
> `scripts/mesurer_le_graphe.py`, qui les imprime — c'est ce qui les empêche de
> devenir faux en silence. **La famille (f) du §4.14 se ferme ici.**

| La réserve | `mesuré` |
|---|---|
| **1. `sequence` repart à 0 dans chaque document** | tout « avant / après » doit être **borné au document** |
| **2. elle n'est pas contiguë sous un parent**, par construction | **167** parents sur les **692** qui ont **au moins deux enfants** — un parent à enfant unique est contigu par définition, et ne peut donc pas entrer au dénominateur. L'écart s'explique par la taille du sous-arbre du frère précédent : **0** discordance sur les 14 410 couples de frères consécutifs. **Ce n'est pas une perte.** Site canonique du taux : `documentation/stores.md` |
| **3. le plus grand écart entre deux enfants d'un même parent vaut 994** (993 valeurs intercalaires) | site : `doc_htms/MLOps with Databricks/7. Foundation Models and Context Engineering`. Un agent qui implémente « la fenêtre d'éléments » comme « les enfants de P dont `sequence ∈ [s−k, s+k]` » rendrait **silencieusement moins** d'éléments que demandé |

Également `mesuré` : **0** arête à `sequence` nulle sur les 15 173.

**Ce que fait le code aujourd'hui, et c'est la partie qui compte.** Les trois
réserves sont respectées, mais **par construction, et non par un garde** :

- `_window_around` (`src/agent/graph_context.py`) découpe sur des **positions de
  liste** — `rows[start:stop]`, après un `index` trouvé par énumération — et
  **jamais sur des valeurs de `sequence`**. `_get_children` va chercher **tous**
  les enfants avec `ORDER BY $-.seq ASC`, sans aucun filtre d'intervalle. **Le
  piège 3 ne mord donc pas** ;

  > *Cette entrée citait des numéros de ligne — `:493` et `:398`. Ils étaient déjà
  > faux (`495` sur `main`) et le lot 2 les a déplacés à `539` en documentant le
  > fichier. **Un numéro de ligne dans un registre est un chiffre qui périme à
  > chaque commit du fichier qu'il désigne, et rien ne le garde** : les symboles
  > les remplacent partout. C'est la règle du §4.11, appliquée à ma propre
  > écriture.*
- `_get_children` et `_find_sibling` partent tous deux d'un VID de parent, donc
  leur portée est **structurellement bornée à un document**. Le piège 1 ne mord
  pas non plus.

**Et c'est précisément ce qui rend le sujet dangereux.** Rien ne rougit si
quelqu'un « optimise » `_window_around` en poussant la fenêtre dans la requête
nGQL sous la forme d'un encadrement sur `sequence` — l'optimisation naturelle,
celle qui économise un aller-retour. Le résultat serait juste sur la plupart des
sections et **silencieusement amputé** sur les parents non contigus.

**Ce que l'amputation coûte VRAIMENT — corrigé par le lot 2, et j'avais
surestimé.** Cette entrée écrivait « jusqu'à 993 éléments manquants au pire
site ». **C'est faux, et l'erreur est de nature** : l'écart de 994 mesure un trou
de **numérotation**, pas un nombre d'éléments. À la fenêtre réellement
configurée — `CONTEXT_WINDOW_BEFORE/AFTER = 6/6`, donc 13 éléments demandés — on
ne peut pas en perdre plus de 12. `mesuré` le 3 septembre 2026 par le lot 2 et
**reproduit par le pilote** sur les 15 173 arêtes, simulant l'encadrement contre
le découpage positionnel :

| ce qu'un encadrement `sequence ∈ [s−6, s+6]` coûterait | `mesuré` |
|---|---|
| ancres rendant moins d'éléments | **1 141 sur 15 173**, soit **7,5 %** |
| parents touchés | **162** — et non 167 : cinq parents non contigus ont des écarts ≤ 6, qui n'amputent rien |
| perte maximale | **12 sur 13** — l'ancre revient seule |

Le défaut reste réel et sérieux : une ancre sur treize rend moins de contexte que
demandé, sans un mot. Il est simplement **borné autrement** que je ne l'écrivais.
*Un écart de numérotation n'est pas un compte d'éléments, et confondre les deux
gonfle un défaut au lieu de le décrire.* **Le travail n'est donc pas d'écrire trois
paragraphes : c'est d'écrire les trois réserves ET le garde qui rend le découpage
positionnel non négociable.**

### 4.6 Le graphe est imbriqué depuis le 2 septembre 2026 — la prémisse morte est retirée par le lot 2, les six sites fermés, la forme du graphe reste le site canonique

**Gravité : c'est le constat le plus large du chantier, parce que ce n'est pas
une phrase fausse mais une PRÉMISSE fausse, sur laquelle des décisions ont été
prises.**

Ce que le §3.1 affirmait, et qui était juste quand ce fut mesuré : 901
`SectionHeader` enfants d'un `Document`, **0** enfant d'un autre
`SectionHeader`, **0** chemin de longueur 3. Le pipeline a corrigé exactement
cela.

`mesuré` le 3 septembre 2026 sur le graphe en service :

| | |
|---|---|
| `SectionHeader` dans le graphe | **746** |
| dont parent direct = `Document` | **163** |
| dont parent direct = un autre `SectionHeader` | **583**, soit **78,2 %** |
| profondeur des `SectionHeader` | 0 → 163, 1 → 301, 2 → 234, 3 → 40, 4 → 8 |

`Chapitre 3 > 3.2 > 3.2.1` est donc désormais **possible**, et l'était déjà
avant que ce dépôt s'en aperçoive.

**Les six sites qui portent encore la prémisse morte**, et ce que chacun en a
tiré :

| Le site | Ce qu'il affirme | Ce que ça a produit |
|---|---|---|
| `documentation/axes_amelioration.md` §3.1 | le graphe est plat, classé **« Ouvert — dépend de l'ingestion »** | demandait au pipeline un travail qu'il a livré. Amendé par ce lot |
| `documentation/pour_le_pipeline_ingestion.md` §5.1 | idem, sous le titre « Le graphe est plat — mesuré » | **redemande au pipeline le même travail livré.** À rendre, sinon on fait perdre son temps à son pilote |
| `documentation/axes_amelioration.md` §1.11 | « l'ingestion n'imbrique pas les titres, **il n'y a aucun niveau à remonter** (§3.1) » | c'est la **justification** de la suppression de `CONTEXT_DEPTH`. Le motif est mort ; la décision est à rouvrir |
| `graph_context.py`, en-tête du module | « L'ingestion produit aujourd'hui un arbre à **deux niveaux** » | justifie `_MAX_DEPTH = 10`. **Sans conséquence** : voir la nuance de profondeur ci-dessous. La marge annoncée « pour une future imbrication » a effectivement absorbé le changement |
| `graph_context.py`, au-dessus de `_SIBLING_CANDIDATES` | « Les enfants d'un `Document` ne sont pas tous des en-têtes » | justifie `_SIBLING_CANDIDATES = 5`. **Sans conséquence non plus, et pas pour la raison écrite** — voir la mesure ci-dessous |
| `graph_context.py`, docstring de `_find_sibling` | « Les en-têtes sont **tous** enfants directs du `Document` (l'ingestion ne les imbrique pas) » | justifie toute la stratégie « la section voisine est un frère ». C'est la phrase la plus fausse des six : 78,2 % des en-têtes la contredisent |

**Le lot 2 a trouvé trois sites de plus**, portant la même prémisse : le docstring
de `_neighbour_elements`, les `Args` de `_find_sibling`, et **`src/api/schemas.py`
— hors de `graph_context.py`, donc hors de la liste ci-dessus.**

**Et son audit en a trouvé un septième, dans CE fichier — le §1.9**, qui portait
**verbatim** la phrase que le lot venait de retirer d'un docstring : « les
en-têtes étant frères sous le `Document` ». Corrigé, comme le §1.11 ci-dessus,
qui était **listé** dans la table mais **jamais amendé** — le registre étant
hors du périmètre des lots, c'était au pilote de le faire, et il ne l'avait pas
fait.

**Le compte n'est donc pas « six sites ».** `mesuré` le 3 septembre 2026 : **sept
au moins**, dont **trois dans ce registre**. *Une énumération de sites est une
phrase d'exhaustivité comme une autre — celle-ci a été fausse trois fois de
suite : le pilote en nommait trois, le lot six, l'audit sept. La leçon n'est pas
« compter mieux » : c'est que la phrase doit être **bornée à ce qui a été
cherché**, et dire où.* Ce qui a été cherché ici : `graph_context.py`, les
schémas, les documents de `documentation/` et ce registre, par recherche des
formes « plat », « deux niveaux », « imbriqu », « frères sous », « tous enfants
directs ». **Le pilote a ensuite balayé les trois endroits qui restaient** —
`prompts/`, le `README` et `tests/` : **0 occurrence** (`mesuré` le 3 septembre
2026). Le compte de sept est donc borné à une recherche qui couvre désormais tout
le dépôt, et c'est cette borne-là qui vaut, pas le chiffre.

**La nuance de profondeur, et elle décide de ce que `_MAX_DEPTH` doit couvrir.**
Cette entrée écrivait que la profondeur « atteint 4 pour un titre et 5 pour un
élément ». Les deux écritures sont justes **sous des définitions différentes**, et
c'est exactement l'ambiguïté de `depth` que le §5.1 de l'état des lieux du
pipeline signale. `mesuré` par le lot 2 : en **niveaux de titres**, 4 ; en
**sauts jusqu'à la racine**, 5 pour le `SectionHeader` le plus profond et **6**
pour le nœud le plus profond. Ce qui compte pour `_MAX_DEPTH` est le compte de
**sauts**, soit 6, `_climb_to_section` remontant d'un parent par itération —
donc 10 laisse 4 de marge. La constante reste saine, mais **pour une raison qu'il
fallait mesurer, pas pour celle que j'écrivais.**

**Le constat de mesure qui a démenti le pilote, et il faut le lire avant de
toucher à quoi que ce soit.** Le pilote a supposé que `_SIBLING_CANDIDATES = 5`,
posé sous un commentaire faux, devait faire manquer des sections voisines dès
que les en-têtes s'imbriquent. **La simulation de `_find_sibling` sur les 15 173
arêtes le dément** : le rang du premier frère en-tête, dans la liste des frères
triés par `sequence`, vaut **1 au pire cas**, dans les deux directions. Un
frère en-tête, quand il existe, est **toujours immédiatement adjacent**. La
constante 5 est donc largement suffisante — **le commentaire est faux, la
constante est saine**, et la corriger serait une correction sans défaut.

**Ce que la même simulation a trouvé, et qui reste ouvert** : sur les 746
en-têtes, **214** n'ont aucun frère en-tête d'un côté donné.

> **Correction du lot 2, et l'erreur était un raisonnement, pas une frappe.**
> Cette entrée ajoutait « (mêmes 214 dans les deux directions) ». **Le compte
> coïncide, l'ENSEMBLE non**, et j'avais déduit l'identité des ensembles de
> l'égalité des comptes. `mesuré` par le lot 2 et **reproduit par le pilote** :
> 214 sans frère en-tête avant, 214 après, **intersection 47**, **union 381** —
> soit **51,1 %** des 746 en-têtes concernés dans au moins une direction, et non
> 28,7 %. La coïncidence des deux comptes à 214 est un hasard, robuste à la
> limite examinée. *Deux ensembles de même cardinal ne sont pas le même
> ensemble : c'est une inférence que rien n'autorisait, et elle a doublé la
> portée du constat une fois mesurée.*
>
> Et le phénomène n'est pas un effet de bord de tri : seuls **25** en-têtes sont
> premiers sous leur parent. Les 189 autres ont bien des frères précédents, mais
> **aucun n'est un en-tête**. Pour ceux-là `_find_sibling` rend `None`, alors qu'une section
voisine existe **en ordre de lecture** — dans le sous-arbre de l'oncle, ou au
chapitre suivant. Ce n'est pas un bug : c'est une **définition** de « section
voisine » — le frère sous le parent commun — qui n'a jamais été rediscutée
depuis qu'elle a cessé de coïncider avec « la section suivante du document ».
**C'est une décision à prendre, pas une ligne à corriger.**

**Ce qui n'est PAS un défaut, et qu'il faut dire pour que personne ne le
« répare » :** la remontée `_climb_to_section` collecte l'intégralité de la
chaîne jusqu'au tag racine, donc les fils d'Ariane multi-niveaux se construisent
correctement **sans rien changer** ; et le budget de fenêtre de contexte
**mesure l'encadrement source par source selon la profondeur du fil**
(`source_framing_chars`), au lieu d'appliquer un forfait — un test le garde
(`tests/unit/test_llm_budget.py`, `test_l_encadrement_est_mesure_source_par_source`).
Le coût annoncé au contrat — 34 caractères sans fil, 275 à cinq niveaux — est
donc **absorbé par construction**. Ce qui reste vrai, c'est que ce coût n'a
jamais été **payé en campagne** : les sources coûtent désormais réellement plus
de fenêtre, et aucune mesure ne dit ce que ça déplace.

**LA DÉFINITION EST TRANCHÉE — décision de l'utilisateur, le 9 septembre 2026,
sur mesure du pilote.** Elle ne l'était pas : cette entrée écrivait « c'est une
définition à rediscuter, pas un défaut », et l'élargissement évident — le voisin
en **ordre de lecture** — a été **désavoué par la mesure**.

#### Ce que la définition actuelle coûte, en éléments RÉELLEMENT SERVIS

`mesuré` le 9 septembre 2026, en **lecture seule**, sur le graphe en service
(23 documents, 746 `SectionHeader`, **14 424** éléments non-titres sous un
en-tête, 15 173 arêtes `PARENT_OF`). La sonde reproduit **à l'unité** les quatre
chiffres que cette section portait déjà — 214 / 214, intersection 47, union 381
soit 51,1 %, et 25 en-têtes premiers sous leur parent — et c'est ce contrôle qui
autorise à croire ses chiffres neufs.

**Tout ce qui suit a été REMESURÉ par le lot 4 le 9 septembre 2026, par
l'instrument versionné**, et chaque chiffre est tombé à l'unité :

```bash
docker exec -i rag-agent-api python - < scripts/mesurer_le_graphe.py
```

> **ET UNE COÏNCIDENCE QUE CETTE SECTION JUXTAPOSAIT SANS LA NOMMER.** Elle
> écrit « 25 en-têtes premiers sous leur parent » et, plus bas, « jamais trouvé
> pour 25 / 24 ». Les deux comptes valent 25 **et ce ne sont pas les mêmes 25** :
> `mesuré` par le lot 4, l'intersection vaut **22**, et elle vaut **0** pour la
> direction « après » — un en-tête que (C) ne sert pas en « après » est le
> DERNIER sous son parent, pas le premier. C'est exactement la faute que le lot 2
> a corrigée sur les « mêmes 214 dans les deux directions » : *deux ensembles de
> même cardinal ne sont pas le même ensemble.* L'instrument imprime désormais
> l'intersection à côté des comptes, pour que la coïncidence ne puisse plus se
> lire comme une identité.

| définition | en-têtes servis | éléments privés d'encadrement |
|---|---|---|
| **(A)** frère en-tête sous le parent commun — *l'actuelle* | 532 / 746 | **4 157 avant (28,8 %)**, **4 678 après (32,4 %)** |
| **(C)** (A), puis **remontée aux oncles**, bornée au document | 721 / 746 avant, 722 / 746 après | **286 avant (2,0 %)**, **646 après (4,5 %)** |
| **(B)** voisin en **ordre de lecture** | 723 / 746 | — mais **191 cas DÉGÉNÉRÉS** |

**Quand `_find_sibling` rend `None`, ce n'est pas une dégradation de qualité,
c'est une ABSENCE** : `_neighbour_elements` rend `[], ""`, donc tout le bloc
d'encadrement disparaît de ce côté, **titre compris**, dans le markdown servi au
LLM. Un tiers des éléments servis est dans ce cas d'un côté au moins, et rien ne
le dit à l'exploitant.

#### Pourquoi (B) est DOMINÉE, et c'est la trouvaille de cette mesure

(B) gagne **2 en-têtes** sur (C) et les paie de **191 dégénérescences** : le
titre suivant en ordre de lecture, après un titre qui a des enfants, **est son
propre premier enfant**. *Le lot 4 a remesuré ce chiffre et lui a donné l'unité
qui manquait : ce sont **191 ADJACENCES**, soit **382 couples (en-tête,
direction)** — chaque adjacence dégénérée compte deux fois, une par bout. Les
deux écritures sont justes sous leur unité, et aucune ne la portait.* On servirait comme « section suivante » un morceau de la
section courante. **(C) ne peut pas produire ce cas par construction**, la
remontée ne pouvant rendre ni un ancêtre ni un descendant de la section de
départ. *L'élargissement que cette section suggérait était le mauvais.*

#### Le coût de (C), et il est borné

`mesuré` : **zéro** aller-retour nGQL supplémentaire pour **532** des 746
en-têtes ; **1** cran pour 164 (avant) / 157 (après) ; **2** pour 24 / 29 ; **3**
pour 1 / 4 ; jamais trouvé pour 25 / 24. Soit **215** et **227** aller-retours
supplémentaires cumulés sur l'ensemble des 746 en-têtes. La remontée **s'arrête
au document**, comme cette section l'exigeait.

**Et le VOLUME servi ne change pas** : `adjacent_section_elements = 3` plafonne à
trois éléments par côté quelle que soit la définition. Le choix ne coûte pas de
fenêtre de contexte — il change **quels** trois éléments. C'est ce qui rend cette
décision moins chère qu'elle n'en avait l'air.

#### Le sous-choix, tranché lui aussi : le VOISIN RÉEL EN LECTURE, côté par côté

Quand on remonte, deux réponses sont possibles et elles **diffèrent dans 106 cas
mesurés** (le dernier descendant est à 1 cran sous l'oncle dans 80 cas, 2 dans
22, 3 dans 4) :

- **« avant » → le dernier descendant en-tête de l'oncle.** Dans « 3.2.1 », on
  sert la queue de « 3.1.4 » — le texte qui précède **réellement** ;
- **« après » → l'oncle lui-même.** Dans « 3.2.1 » dernière fille de « 3.2 », on
  sert la tête de « 3.3 », qui est bien la première chose lue ensuite.

**C'est asymétrique parce que la lecture l'est.** *Et cette symétrie-là était
`calculé`, pas `mesuré` : le pilote l'a déduite de la forme du parcours, il ne
l'a pas éprouvée.*

> **ÉPROUVÉE PAR LE LOT 4 LE 9 SEPTEMBRE 2026, ET LE VERDICT EST PARTAGÉ.** La
> vérification confronte chaque remontée au **parcours en profondeur par
> `sequence`**, c'est-à-dire à l'ordre où un humain lit, et demande quel en-tête
> porte l'élément réellement lu juste avant / juste après le sous-arbre de la
> section. Commande ci-dessus, section « le SOUS-CHOIX, confronté à l'ordre de
> lecture réel ».
>
> - **« après » → l'oncle lui-même : CONFIRMÉ.** L'oncle porte le premier
>   élément réellement lu ensuite dans **188 des 190** remontées. Les **2**
>   exceptions sont les oncles dont le premier enfant est un sous-titre, et non
>   un élément ;
> - **« avant » → le dernier descendant en-tête de l'oncle : LA RÈGLE TIENT, SON
>   MOTIF EST FAUX.** Cette section écrivait « le texte qui précède
>   **réellement** » ; il ne le précède pas. Sur les **189** remontées
>   « avant », ce qui précède vraiment la section en ordre de lecture est
>   l'**INTRODUCTION DE SON PROPRE PARENT** — les frères non-titres qui la
>   précèdent sous le parent commun — dans **186** cas ; l'oncle lui-même dans
>   **2** ; le dernier descendant de l'oncle dans **1**. Ce qui reste vrai, et
>   qui a été mesuré séparément : **DANS le sous-arbre de l'oncle**, le dernier
>   descendant en-tête porte bien le dernier élément lu, **186 fois sur 189**.
>   La règle est donc le bon choix *parmi les descendants de l'oncle*, et c'est
>   à ce titre qu'elle est implémentée — pas au titre que cette section lui
>   donnait.
>
> *La faute n'était pas la décision, c'était sa justification — la même forme
> que `_SIBLING_CANDIDATES`, dont « le commentaire est faux, la constante est
> saine ». Un motif faux sous une règle juste survit à toutes les relectures,
> parce que le comportement, lui, ne rougit jamais.*
>
> **CE QUE ÇA OUVRE, ET C'EST UNE DÉCISION DE PLAN.** Servir l'introduction du
> parent est ce que l'ordre de lecture désigne dans 186 des 189 cas, et rien ne
> la sert aujourd'hui : le fil d'Ariane ne porte que des titres. Le lot 4 ne l'a
> pas écrit — ce n'était pas la décision tranchée.

#### DEUX RÉSERVES, et la première est un manquement du pilote

1. ~~**Ces chiffres n'ont PAS de site rejouable.**~~ ✅ **FERMÉE par le lot 4
   le 9 septembre 2026.** La mesure vit dans `scripts/mesurer_le_graphe.py`,
   section « Section voisine : (A), (B), (C) confrontées », et elle rejoue tout
   ce que cette entrée affirme : les trois définitions en en-têtes servis **et**
   en éléments réellement servis, le coût de (C) en crans, le sous-choix
   confronté à l'ordre de lecture, et (B) avec ses dégénérescences. La commande
   est celle donnée plus haut. *Ce que la fermeture a coûté de plus que du
   portage : trois des chiffres de cette entrée ont changé de sens en passant
   sous instrument — la coïncidence des 25, l'unité des 191, et le motif du
   sous-choix « avant ». Un chiffre sans instrument n'est pas seulement
   invérifiable : il est **relu par son auteur**, et c'est ce que l'instrument
   remplace* ;
2. **la qualité n'est pas mesurée.** Cette section écrivait déjà que le coût de
   fenêtre n'avait jamais été payé en campagne. Ce qui précède dit ce que
   l'encadrement **couvre**, pas ce qu'il **rapporte** : aucune de ces trois
   définitions n'avait été confrontée à la campagne de référence du 8 septembre
   2026. **Le lot 4 l'a fait, et le résultat est au §4.41** — c'est lui qui dit
   si le gain de couverture rapporte, et il faut le lire avant de citer les
   pourcentages ci-dessus comme un gain.

### 4.7 Le contrat d'interface ignore cinq métadonnées que le pipeline émet déjà

`documentation/pour_le_pipeline_ingestion.md` énumère 13 métadonnées attendues
par chunk. `mesuré` le 3 septembre 2026 sur un chunk réel de `rag_documents`,
la collection en porte **18** : les 13 annoncées, plus `block_size`,
`page_no_end`, `page_position`, `ref_position` et `reference_id`.

Aucune n'est un défaut — c'est du signal disponible et non consommé, dont
`page_no_end` (une plage de pages là où l'agent ne cite qu'une page) et
`reference_id`. **Et l'énumération de 13 est une phrase d'exhaustivité** au sens
du §8 du mandat : elle clôt une liste que personne ne rouvre, et c'est ainsi
qu'elle a pris cinq entrées de retard.

### 4.8 Un document sur 23 porte une collection vide

`mesuré` le 3 septembre 2026 :
`MATCH (d:Document) RETURN d.Document.collection, count(*)` rend
`"MLOps with Databricks"` → 11, `"Practical MLflow for Generative AI on
Databricks"` → 11, et `""` → **1**. C'est le PDF.

L'agent lit `collection` sur le sommet `Document` au cours de sa remontée
(`graph_context.py`, `_climb_to_section`) et la publie dans ses citations : les
citations issues du PDF sortent donc sans nom de collection. **Le producteur est
le pipeline** ; ce constat est **à lui rendre**, son registre étant le site
canonique et son pilote tranchant. Rien n'est à corriger de ce côté avant sa
réponse — sauf, éventuellement, à décider ce que l'agent affiche à la place.

### 4.9 L'audit du lot 1 — la porte qualité ne tourne pas là où le chantier la regarde

L'audit indépendant du lot 1 a rendu **douze trouvailles**. Le rapport complet
est archivé, expurgé, à
[`audits/2026-09-03-audit-lot-1.md`](audits/2026-09-03-audit-lot-1.md) — **il est
un instantané daté et canonique pour rien** ; les faits sont ici.

**Le bloquant, et il est seul.** `make test` sur la branche du lot rend `rc≠0`
dans l'environnement que la CI construit : **3 échecs, 12 erreurs, 464 passés**
(`mesuré` le 3 septembre 2026, reproduit par le pilote sur les mêmes fichiers
dans les deux environnements). Cause unique et suffisante : le framework
`pre-commit` n'est déclaré **ni** dans `requirements.txt` **ni** dans
`requirements-dev.txt` — seulement dans un groupe de `pyproject.toml` que la CI
n'installe pas — alors que `make test` ramasse les tests du garde-fou, qui
l'invoquent. Le même arbre rend **479 passés** dans le `.venv` de l'arbre du lot,
qui le porte.

**Ce que ça enseigne au pilote, et il l'a payé lui-même** : il avait mesuré
« 479 passés, `rc=0` » en réutilisant le `.venv` de l'arbre du lot — **le seul
environnement du poste où le vert existait**. Une porte qualité se mesure dans
un environnement monté par le protocole documenté, jamais dans celui que le lot
a laissé derrière lui. *Vérifie ton harnais avant de croire ton vert.*

**Et une phrase d'exhaustivité l'a autorisé** : « la CI n'en a pas besoin — elle
appelle `make lint` et `make test` directement, jamais les hooks git ». La
prémisse est vraie, la conclusion fausse : la CI appelle les **tests** des hooks.
C'est la forme qui a autorisé une régression réelle sur le dépôt jumeau.

**Les trouvailles restantes, cotées par l'auditeur puis par le pilote :**

| | Ce que c'est | Gravité |
|---|---|---|
| **a** | `make install` peut cesser d'armer, ou **désarmer la porte qualité**, sans un seul rouge — les deux mutations mesurées en clone fusionné | **moyenne** : c'est le défaut que le lot nomme lui-même (« on croit l'avoir »), dans son unique geste, et il ne le garde pas |
| **b** | **`git tag -a` laisse partir un tagger interdit**, aucun hook déclenché — et le §9 du mandat **prescrit** les tags | **moyenne**, bornée : le tagger n'entre pas dans le graphe de contributeurs, et il faut pousser le tag |
| **c** | les hooks sont armés **avant** la fusion, depuis du code que `main` ne porte pas. Si la fusion est refusée et la branche supprimée, tout commit du clone est refusé et **la réparation n'est écrite nulle part** | **moyenne**, *fail-closed* |
| **d** | **`git am`** non couvert, quatrième élément d'une énumération fermée de trois | faible-moyenne |
| **e** | la propriété dont dépend tout le flux d'arbres de travail (`--git-common-dir`) n'a **aucun test** — le harnais n'emploie que des arbres primaires, où les deux options coïncident | faible, *fail-closed* |
| **f** | la liste blanche peut perdre l'adresse en usage sans un rouge ; le message de refus affiche alors une liste où elle n'est pas | faible, *fail-closed* |
| **g** | **aucun test n'exerce le `.pre-commit-config.yaml` du dépôt** — le harnais monte toujours une configuration vide. Trois propriétés que ses propres commentaires disent indispensables sont non gardées | faible |
| **h** | mode d'échec non nommé : le framework refuse tout commit tant que sa configuration est **modifiée non indexée** | faible |
| **i** | une directive `shellcheck` dans un dépôt où **shellcheck ne tourne nulle part** | très faible |

**Deux corrections dues au mandat du pilote, et non au lot :**

1. **le §7 portait une condition d'ordre fausse.** Il prescrivait de réarmer les
   garde-fous « **APRÈS** ce retrait » d'arbre de travail. Ce qui grave le chemin
   absolu, c'est **l'arbre depuis lequel on lance l'installation**, pas celui
   qu'on retire : le pas juste est « **depuis le clone principal** », avant comme
   après. Corrigé au site ;
2. **un pas manquait, que personne n'avait écrit** : entre la fusion et la
   réinstallation, il existe une **fenêtre où tout commit du clone et de tous ses
   arbres est refusé**, sur un message qui ne nomme ni la cause ni le remède.
   *Fail-closed*, donc sans danger pour l'historique. Écrit au §7.

**Ce que l'audit n'a pas contesté**, et qui vaut d'être consigné : la décision
`--allow-missing-config` est juste, vérifiée dans les six cellules du croisement
(configuration présente / présente sans le contrôle / absente × adresse
autorisée / interdite) ; la couche figée est inconditionnelle ; les trois
assertions de mutation à motif littéral du lot **portent leur garde** ; le
pipeline d'ingestion est intact, vérifié indépendamment ; et le garde d'index
lexical est **le seul garde de deux mutations du producteur** — il vaut mieux que
ce que le lot en annonçait.

### 4.10 Un secret vivant a fui hors du dépôt, et il est traité

`mesuré` le 3 septembre 2026 : le mot de passe MinIO du pipeline subsistait **en
clair** dans un fichier de travail hors dépôt, écrit par le lot 1 et non nettoyé.
Exposition bornée au compte propriétaire, la chaîne de répertoires étant en
`0700`. **Traité par le pilote le jour même** : fichier détruit, absence du
secret vérifiée sur tout l'arbre temporaire, et le `.env` de l'agent passé de
`0664` à `0600`.

**Le dépôt est PUBLIC** (`mesuré` : `visibility = public`), et ce fait manquait
au registre. Il change deux choses : il explique pourquoi la liste des
contributeurs ne se défaisait pas au §4.1, et **il interdit d'archiver un
rapport sans l'expurger** — l'audit du lot 1 citait l'empreinte du secret pour
prouver sa méthode, à juste titre, et cette empreinte ne pouvait pas être
publiée.

**À rendre au dépôt jumeau, et ce n'est pas de notre ressort** : le même mot de
passe, en usage des deux côtés, apparaît en clair dans **trois transcriptions de
conversation** de son chantier. Son registre est le site canonique et son pilote
tranche. Le `.env` du pipeline est également en `0664`.

**Et trois défauts que le lot 1 et son audit rendent au jumeau** : une moitié
décorative dans le bloc de vérification de son installeur ; l'absence totale de
couverture de `git commit --amend` dans son test d'installation, alors que sa
documentation l'annonce couvert ; et le fait qu'un `git bisect` atteignant son
commit racine briquerait, ce commit étant le seul des 235 à ne pas porter la
configuration du framework.

### 4.11 Ce que la réparation du lot 1 a fermé, et les deux défauts qu'elle a trouvés en chemin

**Le bloquant du §4.9 est fermé** (lot 1, `9596720`). `requirements-dev.txt` est
devenu le **site unique** de la version du framework de hooks ; le groupe
`[dependency-groups]` a disparu de `pyproject.toml` — vérifié en **parsant** le
TOML, pas en cherchant la chaîne, qui subsiste dans un commentaire expliquant ce
que le groupe a coûté ; et `uv.lock` est **redevenu identique à celui de `main`**,
la réparation lui retirant les 96 lignes que le lot lui avait ajoutées.

`mesuré` par le pilote le 3 septembre 2026, dans un **clone jetable** dont les
hooks sont restés vierges et dont l'environnement a été monté comme celui de la
CI — donc sans que `make install` soit passé :

| | `make lint` | `make test` |
|---|---|---|
| `main` d'avant (`d526f6a`) | `rc=0` | `rc=0`, **461 passés** |
| résultat de la fusion | `rc=0` | `rc=0`, **486 passés** |

Et les deux gardes ajoutés **rougissent bien sous mutation**, mesuré séparément,
chaque mutation prouvée par `git diff --numstat` : retirer l'appel à l'installeur
de la recette laisse `make -n install` en `rc=0` — le défaut est bien silencieux
— et rend **2 rouges** ; remplacer l'étape additive par une forme qui réconcilie
l'environnement rend **5 rouges**. Le classifieur encode « **additif** » et non
une liste noire : `uv sync --inexact` reste accepté, tandis que `uv sync`,
`uv sync --only-group`, `uv pip install --exact` et `uv pip sync` sont refusés.

**Ce que la forme retenue coûte, et c'est assumé** : `uv pip install` exige un
`.venv` existant là où `uv sync` en créait un. Sur un poste nu, `make install`
échoue en `rc≠0` sur « No virtual environment found; run `uv venv` » — un échec
bruyant qui nomme sa cause et son geste, et l'ordre documenté du §2.2 est déjà
« monter l'environnement, puis armer ».

**Les deux défauts trouvés en chemin, et le second reste ouvert :**

1. **la forme précédente déclassait un paquet en silence.** `uv sync` réconcilie
   contre `uv.lock`, qui épinglait autre chose que ce que `requirements-dev.txt`
   résout : `make install` faisait reculer `filelock` d'une version corrective.
   `--inexact` protège des **retraits**, pas des **changements de version** —
   une distinction que personne n'avait faite. Fermé par la forme retenue, qui
   ne fait bouger aucune version ;
2. **rien ne garde la cohérence entre `pyproject.toml` / `uv.lock` et les
   `requirements*.txt`** — **OUVERT**. `uv lock --check` n'est appelé par aucune
   cible ni aucune étape de CI, et les deux systèmes de déclaration du dépôt
   peuvent donc diverger sans qu'un seul test rougisse. La divergence existe
   déjà : `uv.lock` épingle une version de `torch` que `requirements.txt` ne
   résout plus. C'est un angle mort de la même famille que « rien ne lit le
   `Makefile` ni les documents » du dépôt jumeau.

**Une correction de chiffre, et la façon de la faire vaut d'être notée.** Un
docstring affirmait que l'inversion des deux gestes de l'installeur était vue par
« DOUZE autres tests ». Le pilote en a mesuré 15 au total, la réparation 14
« autres » — les deux lectures étaient justes, elles ne comptaient pas la même
chose. Le chiffre est désormais **daté, rattaché à sa révision, et son périmètre
est dit explicitement** ; et la propriété qui, elle, ne bouge pas — « au moins un
autre test voit l'inversion complète » — est écrite à côté. *Un chiffre qui
décrit un fichier vivant se borne ou se remplace par la propriété qu'il servait
à établir.*

### 4.12 Trois de mes propres expériences se sont révélées invalides — le pilote les consigne

Le motif est celui du §12 du mandat, et il s'applique à la main qui l'écrit :
**deviner un comportement au lieu de le relire.** Les trois ont été attrapées
avant d'être écrites comme des trouvailles, et chaque fois par la même
vérification — *le développeur avait raison les trois fois* :

1. **une contre-mutation qui détruisait son propre antécédent.** Pour tester la
   claim « le garde accepte encore `uv sync --inexact` », le pilote a écrit cette
   forme **dans le vrai `Makefile`** et observé quatre rouges — donc, croyait-il,
   une réfutation. En réalité tous les tests de cette classe commencent par
   `assert source.count(ligne) == 1`, l'anti-vacuité : en changeant la recette, il
   avait supprimé **l'ancre dont ils ont tous besoin**. Ils rougissaient sur leur
   garde, pas sur leur propriété. La bonne expérience était de laisser le fichier
   tranquille et de lancer le test, qui pose lui-même sa substitution ;
2. **deux appels du classifieur avec le mauvais type.** `_etapes_qui_retirent`
   prend une `list[list[str]]` — des listes de jetons. Le pilote lui a passé une
   liste de **chaînes**, obtenu « aucune commande ne retire » sur tous les cas, et
   failli en conclure que le garde était inerte. Le premier jeton valant la
   commande entière, `Path(commande[0]).name != "uv"` renvoyait `False` partout.
   Relire la signature a suffi.

**La leçon transposable** : quand une mesure semble contredire un rapport, le
premier suspect est le harnais de mesure, pas le rapport. Le mandat dit « vérifie
ton harnais avant de croire ton rouge » — cette entrée est la preuve que la règle
vaut aussi contre soi, et l'audit du lot 1 a consigné deux cas symétriques de son
côté.

### 4.13 `tests.md` a pris 25 tests de retard, et rien ne pouvait le voir

`mesuré` le 3 septembre 2026 : `documentation/tests.md` annonçait « Unitaire —
**461** tests » quand la suite en comptait **486** après le lot 1. Corrigé au
site.

**Ni le lot ni son audit ne l'ont vu, et c'est normal** : c'est le gibier de la
famille que le dépôt jumeau a nommée — *son gibier naît dans les commits qui font
bien leur travail*, parce que c'est là que personne ne relit la phrase qui
décrivait l'ancien état. Un lot qui ajoute 25 tests a toutes les raisons de
regarder ses tests, aucune de relire un titre de section.

**Ce qui reste ouvert est le garde, pas le chiffre.** Ce dépôt possède déjà
l'instrument : `tests/unit/test_coherence_depot.py` garde quatre accords que rien
d'autre ne forçait — dont une **mesure** recopiée dans un docstring et deux
documents. Le compte de la suite est exactement de cette espèce : un chiffre
qu'un document affirme et que le dépôt connaît. Rien ne le rapproche.

Deux autres retards du même commit, également ouverts :

- **`tests.md` ne mentionne pas `test_installation_des_garde_fous.py`**, alors
  que sa table nomme fichier par fichier ce que chacun protège — et que
  celui-ci porte 24 gardes, le plus gros fichier de tests du dépôt ;
- un chiffre **historique** de la même page — « les 390 tests verts » — était
  écrit sans borne, donc lisible comme un état courant. Borné à son moment,
  faute de pouvoir être remesuré.

C'est le dernier angle mort de la méthode, et c'est le même que le **F7** du
dépôt jumeau : *rien ne lit le `Makefile` ni les documents, donc la documentation
peut dériver sans que rien ne rougisse.*

### 4.14 L'audit du lot 2 — le maillon que le bouchon fabriquait au lieu de l'éprouver

L'audit indépendant du lot 2 a rendu **huit trouvailles**, dont **deux
bloquantes**. Le rapport sera archivé sous `audits/` à la fusion. Sa
recommandation — fusionner après correction — est suivie par le pilote.

**T1, la trouvaille grave, et elle est de la meilleure espèce.** Le lot 2 livre un
fichier de tests dont l'objet déclaré est de garder la composition « chercher
tous les enfants, **ordonnés**, puis découper par position ». `mesuré` par
l'auditeur et **reproduit par le pilote** : retirer le `| ORDER BY $-.seq ASC` de
`_get_children` laisse la suite **entièrement verte — `rc=0`, 496 passés, 0
rouge**, y compris les 10 tests neufs.

**Et l'`ORDER BY` est porteur sur le graphe réel.** `mesuré` le 3 septembre 2026
sur 80 des 334 parents à 13 enfants ou plus : sans lui, NebulaGraph rend les
enfants dans un ordre arbitraire — **80 sur 80** non triés, un exemple
commençant `904, 906, 916, 915, 907…` ; avec lui, triés. La conséquence en
service n'est donc pas une amputation mais un contexte **faux** : treize frères
arbitraires présentés au modèle comme les voisins de lecture.

**La cause est un bouchon qui fabrique la précondition qu'il devrait éprouver** :
le graphe factice trie ses enfants **à l'insertion**, et n'applique un tri
conditionnel que lorsqu'un `ORDER BY` est présent. La composition a **trois**
maillons ; le lot en garde deux. *Un montage de test qui bouchonne trop haut rend
intestable ce qu'il prétend vérifier* — et ici il le rend intestable sur
exactement le maillon dont l'échec est le plus probable, un développeur retirant
plus volontiers un `ORDER BY` jugé redondant qu'il ne réécrit une requête.

**T2, la seconde bloquante : une forme nGQL aussi légitime échappe au garde.** La
détection d'encadrement ne reconnaît que `properties(edge).sequence <op> N`. Un
encadrement écrit en aval d'un tube — `| YIELD … WHERE $-.seq >= …` — n'est vu
ni par le bouchon, qui rend alors toutes les lignes, ni par le garde structurel
de la réserve 1, **qui réutilise la même expression**. Une seule cécité défait
deux gardes. Vérifié contre le graphe réel par l'auditeur : les deux formes
rendent les mêmes lignes, donc la même amputation.

**Les six autres, non bloquantes :**

| | Ce que c'est | Gravité |
|---|---|---|
| **c** | **aucune fixture du dépôt ne construit d'en-tête imbriqué** — les 9 `SectionHeader` des fixtures ont tous le `Document` pour parent. Remettre la prémisse morte dans le code laisse **0 rouge**, et `_MAX_DEPTH = 2` reperd le nom du document, c'est-à-dire réintroduit le §1.2 sans un rouge. Le code livré est **juste** — l'auditeur l'a vérifié sur un graphe imbriqué monté à la main : c'est un trou de couverture, pas un défaut | sérieuse |
| **d** | `_SIBLING_CANDIDATES = 1` rend la suite rouge, alors que le commentaire livré écrit « un seul candidat suffirait ». L'assertion qui tombe est la **précondition d'atteignabilité** d'une sonde qui emprunte la constante réglable ; le message est juste, l'étiquette pytest trompeuse | mineure |
| **e** | « le plus gros fichier de tests du dépôt » : premier en octets **de 21 octets**, deuxième en lignes, **cinquième en nombre de tests**. C'est l'erreur que le lot venait de diagnostiquer chez le pilote — deux écritures justes sous des définitions différentes — commise trois commits plus tard | mineure |
| **f** | **cinq chiffres à deux sites** après fusion (`167/763`, `994`, `1 141`, `7,5 %`, `162`), et un troisième site sans renvoi. Et `pour_le_pipeline_ingestion.md` §5.1 recopie une distribution entière trois lignes au-dessus d'écrire « celui-ci y renvoie plutôt que de les recopier ». **Le doublon naît de la FUSION, pas du diff** : invisible à toute relecture de branche | mineure |
| **g** | `mypy scripts/mesurer_le_graphe.py` rend `rc=1`. Il passe la porte parce que **`make typecheck` fait `mypy src/` seul** quand `make lint` fait `ruff check src/ tests/ scripts/` — une asymétrie du `Makefile` **antérieure au lot**, que le lot rend visible pour la première fois, et qui rendra la porte rouge le jour où quelqu'un aligne les deux périmètres | mineure |
| **h** | trois réserves sur l'instrument de mesure : `167 sur 763` mélange deux populations (seuls **692** parents ont ≥ 2 enfants, et un parent à un enfant ne peut pas être non contigu) ; il imprime un rang 0-basé là où le registre le lit 1-basé, sans que ni l'un ni l'autre ne nomme sa convention ; et il pagine un `MATCH` non ordonné — **mesuré stable** à trois tailles de page, donc risque signalé et non défaut | mineure |

**Ce que l'audit n'a pas contesté, et qui vaut d'être écrit** : le diff de
production est **documentaire à 100 %** — dépouillement de tokens à l'appui, le
code exécutable de `graph_context.py` et de `schemas.py` est **identique** à
`main`. Il n'y a donc **aucun risque de régression fonctionnelle** à fusionner ce
lot, et tout son risque est dans ce que ses phrases autoriseront à croire. Les
deux constantes sont saines et les marges reproduites à l'unité. L'instrument est
**en lecture seule**, confirmé, et n'imprime aucun secret. Les stores sont
identiques aux deux bouts de l'audit. Et **chacun des dix-huit chiffres que
l'auditeur a pu reproduire tombe à l'unité**, dont deux que le pilote n'avait pas
vérifiés.

**Un mot sur la cotation de T1, parce que la tentation était de la classer avec
(c).** Ce n'est pas un trou de couverture : le fichier existe pour garder cette
composition, il le dit dans son titre et son docstring, et le maillon manquant
est celui dont l'échec produit non pas *moins* de contexte mais du contexte
**faux**. Un bouchon qui fabrique la précondition qu'il éprouve est la définition
du garde décoratif — sur ce maillon-là, et sur lui seul.

### 4.15 Les deux bloquants du lot 2, mesurés par le pilote des deux côtés de la réparation

Le pilote a tranché T1 et T2 **de ses mains**, dans un arbre de travail dédié,
sur un environnement monté par le protocole du §2.2 du registre de pilotage
(`uv venv` neuf, `torch` CPU, `requirements.txt` + `requirements-dev.txt`) —
jamais le `.venv` que le lot a laissé derrière lui. `rc` du processus, jamais
derrière un tube ni un `grep`.

**Pourquoi cette entrée existe.** Le premier harnais du pilote avait rendu, sur
la réparation, `RC_T2=0` et zéro rouge — donc *garde décoratif*, donc *ne pas
fusionner*. **Ce verdict était faux, et la cause est la mutation, pas le garde.**
Une mutation T2 n'injecte le défaut que si sa borne **ampute réellement** la
fixture : une borne permissive change le texte de la requête sans rien retirer
au résultat, et rend un vert qui se lit comme un garde creux. *Vérifier que le
texte a changé ne suffit pas : il faut vérifier que le comportement a changé.*

#### La mesure qui tranche — même mutation, même site, deux révisions

Mutation posée au site unique de `_get_children` — appelée ici **T2-bornes-figées**,
et ce n'est PAS la mutation `M2` de la batterie du réparateur : celle-ci dérive
ses bornes de l'ancre, la mienne les fige, donc la mienne ampute aussi les
requêtes de sections **voisines** et fait tomber deux tests de plus. Deux corps
différents sous un même nom dans deux pages qui fusionnent se lisent comme un
désaccord ; les deux mesures sont justes. Le `| ORDER BY $-.seq ASC;`
est remplacé par un encadrement **en aval d'un tube**,
`| YIELD … WHERE $-.seq >= 65 AND $-.seq <= 77 | ORDER BY $-.seq ASC;`. Sur la
fixture `graphe_non_contigu` — 15 enfants aux `sequence` 1, 11, … 141, ancre à
71 — cet encadrement n'attrape que l'ancre là où le découpage positionnel rend
13 éléments. `mesuré` le 4 septembre 2026, `make test` :

| révision | `rc` | rouges | passés |
|---|---|---|---|
| `9435657` — lot 2 **avant** réparation | **0** | **0** | 496 |
| `d5b2c3c` — **après** réparation | **2** | **5** | 497 |

C'est la paire qui prouve quelque chose, et non l'une des deux lignes seule : le
garde **était** décoratif sur cette forme nGQL, il ne l'est plus. Le `rc=2` est
celui de `make`, pas de `pytest` — `make` rend 2 quand une recette échoue, et
`pytest` rendait 1. C'est la même mesure que la batterie du réparateur, qui
publie ses huit `rc` en 2 pour la même raison.

T1 reproduit au même endroit — `| ORDER BY $-.seq ASC` retiré de
`_get_children` : `rc=2`, **4 rouges**, les quatre que la batterie du réparateur
nomme. Arbre vérifié propre après chaque restauration.

#### Ce que le pilote a sondé en plus, et qui tient

Le garde structurel de la réserve 1
(`test_aucune_requete_ne_filtre_sequence_sans_ancre`) n'emploie que
`GrapheFactice._FILTRE`, **jamais `_FILTRE_INVERSE`**. Il est donc aveugle à un
encadrement aux opérandes échangées — la cécité exacte que T2 reprochait au
bouchon. Cette cécité est réelle, et elle **ne produit pas un garde décoratif** :
`mesuré` le 4 septembre 2026, une requête de frères rendue **non ancrée ET aux
opérandes échangées** (`LOOKUP ON PARENT_OF WHERE {n} > properties(edge).sequence`)
rend `rc=2` et **4 rouges**, dont le garde lui-même. Sa précondition
d'atteignabilité — `assert comparaisons, "aucune requête ne compare sequence :
garde vide"` — rougit quand son propre motif ne voit plus rien. **Le garde est
fail-closed par construction**, et c'est la bonne forme : un garde dont la
cécité produit un vert est décoratif, un garde dont la cécité produit un rouge
est seulement bruyant.

#### Ce que le pilote a vérifié d'autre avant de trancher

- **le code exécutable de production est identique à `main`** — `calculé` le
  4 septembre 2026 en comparant les AST de `src/agent/graph_context.py` et
  `src/api/schemas.py` **hors docstrings** : identiques aux deux révisions, pour
  765 → 815 et 481 → 484 lignes. L'affirmation « diff documentaire à 100 % » du
  §4.14 est donc mesurée, et non plus seulement dépouillée. Le lot ne porte
  **aucun risque de régression fonctionnelle** ;
- **porte qualité sur la réparation** : `make lint` `rc=0`, `make test` `rc=0`,
  **502 passés** ;
- **fusion sans conflit** : `git merge-tree --write-tree --messages main d5b2c3c`
  rend `rc=0` et aucun message. La même commande **sans** `--write-tree` rend
  `rc=0` en cas de conflit comme en cas de succès : elle ne répond pas à la
  question posée ;
- **identités** : les 7 commits du lot portent `florian_horellou@laposte.net` en
  auteur **et** en committer — vérifié sur l'adresse, jamais sur le nom. Aucune
  attribution à un assistant de génération de code, ni en auteur, ni en
  committer, ni en pied de message ;
- **aucune désactivation ajoutée** : zéro ligne ajoutée par le lot ne porte
  `noqa`, `skip`, `xfail`, `type: ignore` ni `pragma`, et `pyproject.toml`,
  `Makefile` et `.pre-commit-config.yaml` ne sont pas touchés.

#### Ce qui reste à faire auditer, et pourquoi la fusion attend

Les deux bloquants sont fermés, mais **la réparation elle-même est 451 lignes de
matière neuve qu'aucune conversation indépendante n'a lue**, et elle publie des
chiffres neufs — la population de 692 parents éligibles, les 14 410 couples de
frères, la convention de rang 1-basée, la table des huit mutations. *Une phrase
ne rougit pas* : c'est exactement la famille qu'il faut faire reproduire. La
fusion attend `Conv' 27`.

### 4.16 Ce que ce dépôt rend au pipeline — trois constats, et son registre tranche

**Le site canonique de ces trois points est le registre du pipeline, pas
celui-ci.** Ce dépôt les mesure et les rend ; son pilote les cote. Ils sont
recopiés dans `documentation/pour_le_pipeline_ingestion.md` — la page de
liaison — **après la fusion du lot 2**, qui la modifie déjà.

**a — le démon d'orchestration s'est rallumé, et c'est la quatrième fois.**
`mesuré` le 4 septembre 2026 : `rag-ingestion-pipeline-dagster-daemon-1` est
`Up`, là où le relevé du 3 septembre le donnait `Exited (0)` aux deux bouts du
lot 1. Le dépôt jumeau en compte trois occurrences, cause jamais cherchée ; en
voici une quatrième, sur un poste où aucune conversation ne l'a décidé. Ce qui
protège l'index de la campagne de référence n'est donc **pas** l'arrêt du
démon : c'est le défaut §4.32.a du pipeline — la clé de run déjà consommée —
c'est-à-dire le défaut que son plan met au **rang 1**. *Le jour où il le
corrige, l'état des capteurs cesse d'être sans conséquence*, et son propre §6 le
dit. Ce dépôt n'y touche pas.

**b — son `etat_des_lieux.md` est périmé sur l'exigence 5, et c'est la seule
qu'il donnait comme non tenue.** Sa page dit, au 3 septembre : *« ⚠️ non
éprouvée — l'appel part, mais l'agent ne tourne pas sur ce poste »*, et son §8
range « prouver l'exigence 5 » au rang 2 de ce qui reste. **C'est fait.** Le
lot 1 de ce dépôt l'a prouvée en marche, son audit indépendant l'a reproduite
sur l'agent vivant, et un test la garde — §4.2. `mesuré` le 4 septembre 2026 :
`rag-agent-api` est `healthy`, `GET /health` rend HTTP **200** et `status: ok`,
et `POST /reindex` est exposé dans l'`openapi.json` servi. **Les cinq exigences
du contrat sont donc tenues**, et son tableau du §4 comme son §8 sont à amender.

**c — la cause matérielle qu'il donnait a disparu.** Sa page explique que
l'agent ne tourne pas parce qu'il est *« sans `.env` »*. Ce `.env` existe depuis
le 3 septembre 2026, écrit par le lot 1 dans le **clone principal** — jamais
dans un arbre de travail, parce que `docker-compose.yml` monte `./prompts` et
qu'un `up` lancé depuis un arbre l'y ancrerait. `mesuré` le 4 septembre 2026 :
présent, en `0600`.

**Ce que ce dépôt ne rend pas, et pourquoi.** Le rang 3 de son §8 — écrire les
trois réserves de `sequence` côté agent — est le **lot 2**, en instance de
fusion ici. Il ne sera rendu qu'une fois fusionné : *un artefact qu'on cite doit
exister avant qu'on le cite*, et le pilote du dépôt jumeau s'est fait prendre à
annoncer un prompt « prêt, dans tel fichier » sans l'avoir produit.

### 4.17 L'audit de la réparation du lot 2 — la cécité de T2 n'est pas fermée, elle est déplacée

L'audit indépendant de `d5b2c3c` (`Conv' 27`) a **reproduit les huit mutations
de la batterie, les dix-sept chiffres publiés, et les cinq mesures du §4.15 —
sans en renverser une seule**. Il rend une trouvaille **bloquante**, une
sérieuse et six mineures. Sa recommandation — fusionner après correction — est
suivie par le pilote, et sa cotation du bloquant est **maintenue par le pilote
après remesure de ses propres mains**, non acceptée sur parole.

**Ce qu'il confirme, et qui vaut d'être écrit.** Les huit mutations mordent aux
`rc` et aux comptes de rouges publiés, à l'unité. Et il ajoute la moitié de
mesure qui manquait à la batterie : **cinq des huit mutations étaient vertes
avant la réparation et sont rouges après** (`M1`, `M2`, `M2b`, `M3`, `M4`) ;
les trois autres mordaient déjà et le lot les renforce. *C'est la paire qui
prouve, jamais une ligne seule.* Les trouvailles (c), (d) et (e) du §4.14 sont
fermées sans réserve, (e) juste à l'unité — 21 octets d'écart, deuxième en
lignes, cinquième en nombre de tests.

#### B1 — BLOQUANT : la phrase d'exhaustivité de la borne est fausse

`stores.md` et le docstring de `test_un_encadrement_aux_operandes_echangees_est_vu`
affirment que le bouchon ne reconnaît ni une comparaison entre colonnes ni un
`IN` sur une liste, *« aucune des deux n'écrit une fenêtre de lecture »*.
**La moitié `IN` est fausse.**

`mesuré` par le pilote le 4 septembre 2026, aux **mêmes bornes `[65, 77]` et au
même site** que la mutation `T2-bornes-figées` du §4.15 :

| l'encadrement, écrit ainsi | `rc` (`make test`) | rouges |
|---|---|---|
| `$-.seq >= 65 AND $-.seq <= 77`, en aval d'un tube | **2** | **5** |
| `properties(edge).sequence IN [65…77]` | **0** | **0** — 502 passés |

Et ce n'est pas une forme théorique. `mesuré` en **lecture seule** contre
NebulaGraph en service le 4 septembre 2026, sur une ancre réellement amputée
(parent `cde213aee4`, `sequence` 341, fenêtre `[335, 347]`) : les deux écritures
sont **acceptées** par nGQL et rendent l'**ensemble identique**, avec la **même
perte** — 12 éléments là où le découpage positionnel en rend 13. L'auditeur l'a
mesuré sur une ancre à perte de 12 sur 13.

**Au niveau du motif, la cécité est double et la seconde moitié est pire que la
première** — `calculé` le 4 septembre 2026 sur les expressions du bouchon :

| l'écriture | ce que `_FILTRE` en tire |
|---|---|
| `sequence >= 64 AND sequence <= 76` | `[('>=', '64'), ('<=', '76')]` — vue, appliquée |
| `sequence IN [64…76]` | `[]` — **invisible**, le bouchon rend toutes les lignes |
| `sequence - 64 >= 0 AND 76 - sequence >= 0` | `[('>=', '0')]` — **mal lue**, un filtre qui ne retire rien |

La forme arithmétique est la plus insidieuse : le bouchon ne « ne reconnaît
pas », il **mésinterprète silencieusement**, et son vert se lit comme un garde
juste. Et `_FILTRE` ne voyant pas la forme `IN`, le **garde structurel de la
réserve 1 est aveugle à la même requête** : une cécité, deux gardes — le critère
exact qui a fait coter T2 bloquante au §4.14.

**Pourquoi le pilote maintient bloquant, alors que le code de production est
inchangé et qu'aucune régression n'est possible.** Ce n'est pas le trou de
couverture qui bloque : c'est la **phrase**. La règle du chantier est que toute
phrase du genre « aucun », « les deux seules », « il n'y a plus » est soit
**bornée**, soit **gardée par un test** ; celle-ci n'est ni l'une ni l'autre, et
elle est **fausse**. Le §4.14 avait écrit que tout le risque de ce lot était
« dans ce que ses phrases autoriseront à croire » — c'en est une, et elle
autorise à croire gardé ce qui est mesuré non gardé. *Un trou nommé se rouvre ;
une énumération close ne se rouvre pas.*

**La cause est de nature, pas d'énumération.** `GrapheFactice` modélise une
clause `WHERE` nGQL par **recherche de sous-chaîne dans une expression**, et
ignore la liste `YIELD`. Une grammaire d'expressions ne se borne pas par une
liste de deux exceptions. La correction retenue est donc de rendre le bouchon
**fail-closed** : lever sur toute clause portant `sequence` qu'il ne sait pas
évaluer entièrement, au lieu de rendre toutes les lignes. C'est la forme que le
§4.15 salue déjà sur le garde de la réserve 1 — *un garde dont la cécité produit
un rouge est seulement bruyant*.

#### A1 — SÉRIEUSE : le dénominateur de la non-contiguïté se contredisait d'une page à l'autre

`stores.md` publiait `167 sur 692`, le §4.5 de ce registre `167 sur 763`, tous
deux étiquetés `mesuré`, aucun ne renvoyant à l'autre. **Avant la réparation les
deux s'accordaient** ; elle a corrigé son site et laissé l'autre. C'est la
famille (f) du §4.14, et `167 sur 763` est la forme que sa propre trouvaille (h)
avait déclarée fautive — *le registre portait donc la correction au §4.14 et
l'erreur au §4.5.* **Corrigé par le pilote au site, avec renvoi au site
canonique.** Les quatre autres chiffres de (f) — `994`, `1 141`/`7,5 %`, `162`,
`12 sur 13` — restent à deux sites et sont traités à la fusion.

C'est la troisième fois que ce chantier paie la même leçon : *une correction
bornée au motif qu'on a tapé n'est pas une correction, c'est un échantillon.*

#### Les six mineures, et qui les porte

| | Ce que c'est | Qui |
|---|---|---|
| **A2** | le message de `d5b2c3c` **omet deux trouvailles que son diff ferme** — (e) et la recopie de `pour_le_pipeline_ingestion.md`. Un pilote qui clôt le registre sur le message clôt moins que ce qui est fait. Historique, non corrigeable sans réécrire un commit | consigné, sans action |
| **A3** | **trois chiffres à renvoi faux et sans site rejouable** : les docstrings envoient chercher `334` et `80 sur 80` au « §4.6 » — ils sont au **§4.14**, `mesuré` — et le `40 parents sur 40` n'a **aucun site** dans `documentation/`, ni dans l'instrument. Or le docstring de l'instrument dit exister parce qu'« une page qui les affirme sans laisser de quoi les rejouer devient fausse en silence » | `Conv' 28` |
| **A4** | **deux titres de ce registre deviennent faux à la fusion** — §4.5 « ne sont écrites nulle part » et §4.6 « le croit encore plat » — sans être marqués `→ FERMÉ par le lot 2`, alors que la convention existe au §4.1 et au §4.2 | le pilote, **à la fusion** |
| **A5** | « encadrement en aval d'un tube » **nommait deux mutations différentes**, à 5 et 3 rouges, dans deux pages qui fusionnent. Les deux mesures sont justes ; c'est le nom partagé qui trompe. **Corrigé** : la mienne s'appelle `T2-bornes-figées` au §4.15 | fait |
| **A6** | **le bouchon ignore la liste `YIELD`** : une réécriture qui renomme la colonne projetée rend **0 ligne** sur le vrai graphe — nGQL refuse l'alias en entrée du `WHERE` du même `YIELD` — et **toutes les lignes** dans le bouchon, suite verte. Même racine que B1, et la correction fail-closed la couvre | `Conv' 28` |
| **A7** | (g) et (h) gardent chacun un résidu, tous deux **antérieurs au lot** et mesurés inoffensifs : `mypy scripts/` reste `rc=1`, **26 erreurs dans 3 fichiers** — donc aligner les périmètres du `Makefile` rendrait toujours la porte rouge ; et le `MATCH` paginé sans `ORDER BY` de l'instrument rend une sortie **identique octet pour octet** à `_PAGE` = 500, 3 000, 5 000 et 20 000 | ouvert, hors périmètre |

#### La borne que l'audit pose sur une affirmation du pilote, et il a raison

Le §4.15 écrit que le garde structurel de la réserve 1 est **« fail-closed par
construction »**. L'auditeur borne : cela ne tient que si **aucune** requête de
la scène ne matche `_FILTRE`. En présence d'un encadrement classique ailleurs
dans la même scène, la précondition d'atteignabilité est satisfaite par cette
autre requête, et le garde passe **vert** sur une comparaison de `sequence` non
ancrée. La propriété reste défendue — six autres rouges tombent — mais **par
d'autres gardes, pas par celui-là**. « Fail-closed par construction » est donc
juste **dans la scène mesurée**, pas en général : la phrase du §4.15 se lit
bornée à sa scène.

### 4.18 → FERMÉ — B1 refermé, le lot 2 fusionné, et ce que le pilote n'a PAS fait auditer

`Conv' 28` a refermé B1, A3 et A6. **Le pilote a vérifié de ses mains, sur
`e33c076` puis sur le résultat de la fusion, dans un arbre dédié monté par le
protocole du §2.2** — `rc` du processus, jamais derrière un tube :

| ce qui a été mesuré | `mesuré` le 4 septembre 2026 |
|---|---|
| porte qualité, sur la branche **et** sur la fusion | `make lint` `rc=0`, `make test` `rc=0`, **520 passés** |
| **B1 refermé** — la mutation `IN` qui passait à zéro rouge | `rc=2`, **11 rouges** (elle en rendait **0** sur `d5b2c3c`) |
| **le serrage excessif est gardé** — la liste `YIELD` n'est plus séparée du `WHERE`, donc le bouchon lève sur du code juste | `rc=2`, **16 rouges**, dont `test_la_requete_reelle_de_get_children_ne_leve_pas` |
| **les gardes « ça lève » ne sont pas vides** — le fail-closed redevient laxiste | `rc=2`, **14 rouges** — les 8 écritures × les 2 gardes |
| **aucune assertion retirée** du fichier de tests, 16 → 20 définitions | diff dépouillé ligne à ligne |
| **le code exécutable de production est identique à `main` d'avant le lot** | AST hors docstrings de `graph_context.py` et `schemas.py`, `7bcd346` contre `db05162` : identiques |
| **tous les chiffres publiés sont imprimés par l'instrument** | `rc=0` : 692, 167/692, 994, 162, 746, 583 (78,2 %), rang 1-basé, 214/214, 47/381, 334, et cinq équivalences à 80/80 |

**La classe de B1 est fermée par nature, et le pilote a cherché à la rouvrir.**
Le bouchon détecte **large** — `\bsequence\b`, le mot nu — et évalue **étroit** —
`re.fullmatch` sur la conjonction entière. C'est cette asymétrie qui ferme la
classe, là où une liste de motifs l'aurait laissée ouverte au membre suivant.
`mesuré` le 4 septembre 2026 : **quatre écritures inventées par le pilote pour
lui échapper lèvent toutes les quatre** — nommage par alias d'arête
(`e.sequence`), par nom de type d'arête (`PARENT_OF.sequence`), enveloppement
dans une fonction (`abs(… - 70) <= 10`), et `BETWEEN`. Et la projection saine —
`properties(edge).sequence AS seq` dans un `YIELD` — ne lève pas.

**La phrase a changé de nature, et c'est ce qui compte.** Elle n'énumère plus des
exceptions (« ni …, ni … ») : elle énonce une **propriété** — une conjonction de
comparaisons entre la `sequence` de l'arête, ou une colonne d'amont qui la
porte, et un littéral entier ; tout le reste lève — et cette propriété est
**gardée par quatre tests**, dont un qui pilote la requête réelle de
`_get_children` au lieu de la recopier. *Un trou nommé se rouvre ; une
énumération close ne se rouvre pas.*

#### Ce que le pilote a décidé, et ce qu'il assume

**La fusion a été tranchée sans quatrième audit indépendant**, et le motif est
écrit ici pour être contesté. Le lot a été audité (`Conv' 25`), sa première
réparation auditée (`Conv' 27` — c'est elle qui a produit B1), et cette seconde
réparation vérifiée par le pilote sur les deux directions dangereuses : la
vacuité du garde et son serrage excessif. Le dépôt jumeau a le même précédent —
son lot 0b a été *livré, audité, réparé, réaudité, réparé, fusionné*, sa seconde
réparation tranchée par le pilote. Et le risque résiduel est **borné par
construction** : `src/` est inchangé, mesuré, donc aucune régression
fonctionnelle n'est possible.

**Ce qui n'a donc PAS été audité indépendamment, et qui reste ouvert :**

- **la décoration individuelle de chacun des 18 gardes neufs.** Le pilote a
  éprouvé le **moteur** du bouchon dans ses deux directions, et non chaque garde
  un par un. Un garde décoratif parmi les dix-huit resterait invisible à ce qu'il
  a mesuré. *C'est nommé ici précisément pour rester rouvrable* : le prochain
  audit qui touche `test_lecture_sequence.py` commence par là ;
- **la fidélité du moteur au nGQL réel** hors des formes éprouvées — parenthèses
  imbriquées, littéraux de chaîne contenant `WHERE`, étages multiples. Un défaut
  de modélisation y ferait rougir du code juste, ce qui est **bruyant et non
  dangereux** ; le pilote l'accepte à ce titre, et pas à un autre.

#### Les résidus, tous nommés, aucun clos

| | Ce que c'est | État |
|---|---|---|
| **A2** | le message de `d5b2c3c` omet deux trouvailles que son diff ferme | consigné, non corrigeable sans réécrire un commit audité |
| **A4** | les titres §4.5 et §4.6 | **fait à la fusion** — marqués `→ FERMÉ par le lot 2` |
| **famille (f)** | `994`, `1 141`/`7,5 %`, `162`, `12 sur 13` à deux sites | **fermée** — `stores.md` est nommé site canonique unique au §4.5, et l'instrument les imprime |
| **A7** | `mypy scripts/` reste `rc=1`, **26 erreurs dans 3 fichiers** — donc aligner les périmètres du `Makefile` rendrait la porte rouge ; et le `MATCH` paginé sans `ORDER BY` de l'instrument, **mesuré stable** à quatre tailles de page | **ouvert**, antérieurs au lot |
| **§4.13** | rien ne lit le compte de tests ni les documents. Le lot a corrigé le chiffre au site ; **le garde reste absent**, et c'est lui la trouvaille | **ouvert** — c'est le F7 du dépôt jumeau |
| **la borne sur « fail-closed par construction »** | la précondition d'atteignabilité de `test_aucune_requete_ne_filtre_sequence_sans_ancre` reste satisfiable par une autre requête évaluable de la même scène : le garde n'est fail-closed **que dans sa scène**. Relevé par `Conv' 27`, confirmé par `Conv' 28`, non fermé — c'est la forme du garde qu'il faudrait changer | **ouvert**, borné au site |

### 4.19 Le lot 3 vérifié par le pilote — et une prémisse Docker qui ne tient pas à la mesure

**État : livré (`Conv' 29`, `c5c38d5`), NON poussé, NON fusionné, audit distribué
(`Conv' 30`).** Ce lot touche `src/` — `retriever.py` et `main.py` — donc sa
catégorie de risque n'a rien à voir avec celle du lot 2, dont le code exécutable
de production était inchangé. Il ne se fusionnera pas sans audit indépendant.

#### Ce que le pilote a mesuré de ses mains, le 4 septembre 2026

Arbre dédié à `c5c38d5`, environnement monté par le protocole du §2.2, `rc` du
processus, jamais derrière un tube :

| | `mesuré` |
|---|---|
| porte qualité | `make lint` `rc=0`, `make test` `rc=0`, **539 passés** (520 avant le lot) |
| identités des 3 commits | `florian_horellou@laposte.net` en auteur **et** committer ; aucune attribution à un assistant |
| **le refus traverse le graphe** | sonde **écrite par le pilote**, indépendante de celles du lot : collection bouchonnée à `all-MiniLM-L6-v2`, `/search` → **503**, `/sources` → **503**, **`/answer` → 503** — c'est-à-dire à travers LangGraph, qui encapsule volontiers les exceptions — et `/health` → **200 `degraded`** |
| **aucun modèle n'est chargé** | la même sonde remplace `_get_embedding_model` par une assertion qui échoue si elle est appelée : elle **n'a jamais tiré** |
| `_dense_search` n'est enveloppé dans aucun `try` | ses deux sites d'appel dans `retrieve` sont nus sous un `with chrono.mesurer(...)` — le refus remonte, il n'est pas absorbé par le repli lexical |
| le test de sécurité modifié est **renforcé, non affaibli** | il branche la sonde neuve sur l'état sain, là où il ne tenait plus que par l'échec de résolution DNS de l'hôte `chromadb` |

#### La trouvaille du pilote : la prémisse du healthcheck est fausse

Le lot accepte sciemment un trou, et l'écrit — c'est la bonne pratique. Mais
**son motif ne tient pas.** Il justifie de ne pas rendre 503 sur `/health` par :
*« rendre 503 ferait redémarrer le service en boucle sur une panne qu'un
redémarrage ne répare pas »*.

`mesuré` le 4 septembre 2026, dans un projet Compose **isolé** monté puis démonté
pour cela — un conteneur `alpine` à healthcheck échouant toutes les 3 s, avec
`restart: unless-stopped`, exactement le réglage d'`agent-api` :

| | `mesuré` sur 47 secondes |
|---|---|
| `State.Health.Status` | `unhealthy` dès le premier tour, et le reste |
| `State.StartedAt` | **inchangé** — `2026-09-04T12:11:19.716901842Z` au début comme à la fin |
| ce que `docker ps` affiche | `Up 47 seconds (unhealthy)` |

**Un healthcheck en échec ne redéclenche pas le conteneur sous Docker Compose.**
`restart:` répond à la *sortie* du processus, pas à la santé. La boucle de
redémarrage que le lot redoute appartient à un orchestrateur qui sonde la
vivacité — Swarm, Kubernetes — pas à ce fichier-ci.

**Le vrai arbitrage est donc autre**, et il n'a pas été pesé :

- rendre 503 sur une divergence ferait apparaître `(unhealthy)` dans
  `docker ps` — l'endroit exact où un exploitant regarde en premier ;
- son coût réel est ailleurs : `frontend` dépend d'`agent-api` en
  `condition: service_healthy`, donc **un démarrage à froid sur un index
  divergent ne lèverait pas le frontend**. C'est un coût réel, et il se discute ;
- et il existe une troisième voie que ni le lot ni le pilote n'ont éprouvée :
  laisser `/health` en 200 et faire lire le **corps** par le healkcheck de
  Compose, ce qui découplerait la visibilité Docker du code HTTP.

*Le pilote ne tranche pas la conception : il n'écrit pas de code de production.*
Il rend le fait, et il le rend **avant** l'audit pour que l'auditeur le
reproduise ou le renverse. Le raisonnement du lot était de bonne foi et
soigneusement écrit ; c'est son antécédent qui était faux, et *un raisonnement
juste sur un antécédent faux produit une conclusion fausse, et il se relit comme
une preuve.*

#### Ce que le lot a lui-même déclaré, et qui vaut d'être lu

Ce rapport est le plus autocritique du chantier, et trois de ses aveux sont des
gestes de méthode que le registre retient :

1. **il a posé un témoin inerte dans sa batterie** — une mutation qui change
   autant de texte qu'une autre et ne change aucun comportement, `rc=0`, zéro
   rouge. Sans témoin, un vert ne se distingue pas d'une mutation qui n'a rien
   touché. C'est le garde-fou dont l'absence a coûté un faux verdict au pilote au
   §4.15 ;
2. **il a qualifié son propre rouge-d'abord de « faible »** — un rouge
   « le symbole n'existe pas », qui ne prouve pas qu'un test discrimine, et il
   renvoie à sa table de mutations comme étant la vraie preuve ;
3. **il a déclaré une erreur de manœuvre** : en restaurant `README.md` après une
   mutation, il a écrasé une correction non commitée du même fichier. Détectée,
   refaite, porte relancée. La leçon qu'il en tire est juste — *commiter avant de
   muter* — et elle entre au §12 du mandat.

Il a aussi contesté la question du pilote, à raison : *« au démarrage ou dans
`/health` » n'offrait que des rapports, et un rapport ne protège de rien.* Le
garde vit sur le chemin de la recherche ; le démarrage et `/health` en sont la
voix. **Le pilote avait mal posé le choix**, et il le consigne au §12.

#### Ce que le lot n'a pas fermé, et qu'il nomme

La réserve du cache — l'estampille lue est celle capturée à l'ouverture de la
collection, donc une réingestion divergente survenue **pendant** que l'agent
tourne ne serait vue qu'après un `reset_connection()`. Écrit au site et rendu au
pipeline. Le garde **n'est pas actif en service** : `rag-agent-api` n'a pas été
redémarré, et ce redémarrage est une décision de pilotage à prendre après
l'audit, depuis le clone principal et jamais depuis un arbre de travail.

Et une remarque du lot qui corrige le registre : **le `grep -n
"model_validator\|field_validator" src/agent/settings.py` du §4.4 désignait le
mauvais lieu.** Un validateur Pydantic s'exécute à l'import de `settings`, avant
toute connexion à ChromaDB : il n'a rien à confronter. Ce `grep` rendra donc
toujours `rc=1`, et ce n'est pas un symptôme de défaut. Le symptôme
reproductible de ce point reste à choisir — ouvert.

#### Amendement au §4.19 — la quatrième route, et un faux vert que le pilote s'est fabriqué

**`/chat/start` refuse aussi, et la sonde le PROUVE.** `mesuré` le 4 septembre
2026, `lifespan` monté pour que le graphe existe : HTTP **503**, et le corps
nomme **les deux** modèles. Les quatre routes qui portent une recherche
vectorielle — `/search`, `/sources`, `/answer`, `/chat/start` — refusent donc
toutes.

Les deux routes qui **streament** (`/chat/simple`, `/chat/resume`) ne font
**aucune** recherche vectorielle : elles partent de `selected_element_ids` et
reconstruisent depuis le graphe. Le souci que le pilote redoutait — un
gestionnaire d'exception ne pouvant plus poser un 503 après le premier octet du
flux — **n'a donc pas de site** dans ce code. C'est une propriété de la forme
actuelle des routes, pas un garde : *si une route SSE se met un jour à chercher,
elle échappera au 503*, et cela n'est éprouvé par aucun test.

**Et le pilote s'est fabriqué un faux vert en cherchant ce trou** — il le
consigne parce que c'est la démonstration la plus courte de sa propre règle.
Sa première sonde affirmait `/chat/start` conforme sur un `status_code == 503`
qui disait en réalité *« Service en cours de démarrage »* : le `lifespan` n'était
pas monté, le graphe n'existait pas, et la sonde n'avait jamais atteint le garde.
Deux 503 pour deux causes, indiscernables par le seul code. La sonde refaite
**prouve son atteinte** en exigeant le nom du modèle divergent dans le corps
avant d'affirmer quoi que ce soit. *Un test qui choisit lui-même son cas doit
prouver qu'il l'a atteint* — et un code de retour peut répondre à une autre
question que la sienne.

### 4.20 L'audit du lot 3 — deux contre-exemples au garde, et une mesure du pilote renversée

L'audit indépendant de `c5c38d5` (`Conv' 30`) a construit **21 mutations dont
deux témoins**, reproduit la porte et les quatre routes, et rendu **deux
trouvailles bloquantes**. Sa recommandation — fusionner après correction — est
suivie. **Le pilote a vérifié les deux bloquants de ses mains avant de les
accepter**, et il a été **renversé sur une de ses propres mesures**.

#### B1 — BLOQUANT : la reprise de `_dense_search` sert une collection jamais vérifiée

`src/agent/retriever.py`, dans la reprise sur ChromaDB injoignable :
`reset_connection()` puis `results = _query(_get_chroma_collection())`. Le
réarmement remet le verdict à `False`, mais **la requête en cours ne repasse pas
le garde** : la collection rouverte peut être une autre collection, et elle est
interrogée sans vérification.

`mesuré` par le pilote le 4 septembre 2026, bouchon **fidèle au `lru_cache`** —
la collection ne change qu'au `cache_clear`, donc seule la reprise la change :

| | `mesuré` |
|---|---|
| requêtes servies par la collection divergente | **1** |
| ce qui est rendu | `['passage plausible et FAUX']` |
| l'appel **suivant** | refuse — le verdict a bien été remis à `False` |

**Une réponse complète, fausse, sans exception ni ligne de journal.** C'est
exactement la panne que le lot existe pour empêcher, sur le seul chemin où
l'objet collection change d'identité en vol — et une coupure de ChromaDB est
précisément le moment où une réingestion a pu passer dessous. Les trois chiffres
de l'auditeur tombent à l'unité.

**Et le pilote s'est fait prendre par son propre harnais avant d'y arriver.** Sa
première sonde faisait avancer la collection à **chaque appel**, là où le vrai
`_get_chroma_collection` est mémoïsé : elle a donc rendu un « faux servi » qui
ne venait pas de la reprise mais du bouchon lui-même, et un « l'appel suivant ne
refuse pas » qui contredisait l'auditeur. *Un harnais de mesure peut muter ce
qu'il observe* — la leçon est au §10, elle a sauvé un lot entier sur le dépôt
jumeau, et elle vient de coûter une fausse contradiction au pilote. La sonde
refaite modélise la mémoïsation, et elle reproduit l'auditeur exactement.

#### B2 — BLOQUANT : le réarmement concurrent est perdu, et le garde reste désarmé

Le lot écrit au site que « le pire cas est une vérification faite deux fois — un
verrou coûterait plus cher que ce qu'il éviterait ». **C'est faux**, et
l'auditeur l'a rendu déterministe. `verifier_modele_embedding()` lit
l'estampille, puis écrit `_concordance_etablie = True` **à la fin**. Qu'un autre
fil appelle `reset_connection()` entre les deux, et l'écriture de `True` **écrase
le réarmement** — perte de mise à jour classique. Confirmé par le pilote à la
lecture du site.

La conséquence est **pire que B1** : le garde est désarmé pour toute la vie du
processus, et chaque recherche sert des passages plausibles et faux en silence.
Atteignable — `reset_connection()` tourne dans un fil du threadpool depuis le
`ping()` du healthcheck, toutes les 20 s, et depuis la reprise de B1, pendant que
d'autres fils vérifient. *C'est une réserve nommée par son auteur et mesurée
fausse* : exactement ce que le mandat demande de ne pas croire.

#### N1 — le pilote est renversé : `/chat/resume` cherche DÉJÀ, et après le premier octet

Le pilote avait mesuré que les deux routes qui streament ne font aucune recherche
vectorielle, et il avait noté le risque **au futur** — « si une route SSE se met
un jour à chercher ». **C'est déjà le présent**, et l'auditeur l'a mesuré.
Vérifié par le pilote à la lecture : `src/agent/graph.py` porte
`add_conditional_edges("postprocess", should_search_more, {True: "retrieve",
False: END})` — le graphe **reboucle vers `retrieve` après `generate`** — et
`/chat/resume` fait tourner `astream` **à l'intérieur** de son
`stream_generator`, rendu dans un `EventSourceResponse`. Le garde est donc
atteint alors que la réponse a commencé.

Conséquences mesurées par l'auditeur : **pas de 503, pas de motif dans le corps,
et pas même la ligne `ERROR`** — Starlette lève avant d'appeler le gestionnaire,
dont la docstring affirme pourtant être « le seul endroit où l'exploitant verra
que des requêtes réelles se cassent sur cette panne-là ». Le flux meurt tronqué,
sans trace. `NATIVE_TOOL_CALLING=true` et `MAX_SEARCH_ITERATIONS=3` sont les
défauts : ce n'est pas un chemin exotique.

**La sûreté est préservée** — rien de faux n'est servi, la levée est fail-closed.
Ce qui ne l'est pas, c'est la phrase : quatre documents affirment sans réserve
« toute recherche est refusée en 503 », **mesurablement faux sur une route sur
six**. C'est la famille qui a bloqué le lot 2 (§4.18), et elle bloque en écriture
ici aussi. `/chat/simple`, en revanche, ne cherche jamais — la mesure du pilote
tient pour celle-là.

#### N2 — la prémisse Docker fausse gagne un site neuf, et un est chez le pilote

L'auditeur a **reproduit** la mesure du §4.19 — 21 échecs consécutifs de
healthcheck, `RestartCount=0`, `StartedAt` inchangé — et il a mesuré le **vrai**
coût dans le même projet isolé : le service dépendant en
`condition: service_healthy` est resté `created`, sur
`dependency failed to start: container … is unhealthy`.

`mesuré` le 4 septembre 2026, la prémisse fausse vit à **trois** sites :

| site | qui |
|---|---|
| `src/agent/retriever.py:182` | **ajouté par le lot 3** — à retirer avant fusion |
| `src/api/main.py:383` | antérieur, sur `main` — production, ouvert |
| `documentation/axes_amelioration.md` §1.27 | **antérieur, et c'est le registre du pilote** — corrigé le 4 septembre 2026, motif remplacé par le mécanisme mesuré |

**L'arbitrage de l'auditeur, que le pilote suit** : une fois le motif corrigé, le
trou reste acceptable — mais **pour l'autre raison**. Rendre 503 ne provoquerait
aucune boucle ; cela empêcherait le frontend de lever au démarrage à froid et
transformerait une panne lisible en une pile muette. *Le trou tient sur ce
motif-là, pas sur celui qui est écrit.* Et l'auditeur a éprouvé la troisième
voie contre le `/health` en service : `curl -sf …/health` rend `rc=0` là où
`curl -sf …/health | grep -q '"status":"degraded"'` rend `rc=1`. Un `CMD-SHELL`
discrimine donc sans toucher au code HTTP — même arbitrage, déplacé du code vers
le `compose`, où il se lit.

#### Les sept non bloquantes, et deux verts que le lot n'avait pas prévus

| | Ce que c'est | Suite |
|---|---|---|
| **N3** | le champ `embedding_model` de la réponse `/health` est **non optionnel**, décision longuement argumentée dans `schemas.py` — et **gardée par rien** : le rendre optionnel laisse la suite verte | `Conv' 31` |
| **N4** | la fixture `autouse` de `conftest.py` est **inerte** : retirée, 539 verts, `rc=0`. Son motif est juste et prospectif, mais rien ne la retient | `Conv' 31` |
| **N5** | **41 tests ouvrent une vraie connexion `chromadb`** (48 tentatives) contre **0** sur `main`, toutes depuis `_lire_estampille`. Le lot a traité deux fichiers, il en reste cinq. Rejoué avec l'hôte résolu sur trois estampilles : `rc=0` dans les trois cas — *le montage tient par absorption, pas par construction* | ouvert |
| **N6** | l'inventaire documentaire rougit bien **dans les deux sens** — c'est un vrai garde. Mais il ne balaie que `documentation/*.md` **non récursif** + `README.md` : échappent `documentation/audits/`, `.env.example`, `src/`, `scripts/`. Ironique, la trouvaille qu'il consigne étant *« une ligne de `.env` d'apparence exécutable »* | `Conv' 31` |
| **N7** | aucun test ne garde le drapeau « en vol » de la sonde neuve | ouvert |
| **N8** | la mémoïsation du verdict n'est gardée par rien — un refactor qui la retire ne rougit pas | ouvert |
| **N9** | l'`except Exception` d'`etat_modele_embedding` : **justification recevable**, avec une réserve — il absorbe aussi un défaut de programmation, qui devient un `unknown`, lequel ne dégrade pas et ne journalise rien en régime établi | consigné |

**Le témoin inerte du lot est vérifiablement inerte** — l'auditeur l'a rejoué et
il déplace autant de lignes que deux mutations qui mordent. **18 des 21 mutations
mordent**, et les trois verts sont les deux témoins plus N3/N4.

#### Ce que l'audit a corrigé dans le prompt du pilote

Trois chiffres, et le pilote les reprend : `retriever.py` gagne **+154** lignes
et non 157, `main.py` **+138** et non 143 ; les tests neufs sont **+19** — 520 →
539 cas collectés — et non 37, le pilote ayant additionné des tests et des
mutations ; et le §4.4 annonce **onze** mutations là où le rapport du lot en
tabulait douze — écart entre le rapport et la page, à trancher par `Conv' 31`.

**La fusion a été vérifiée en CONTENU et non seulement en `rc`**, par l'auditeur :
le §4.19 survit intact — 126 lignes sur `main`, 126 dans l'arbre fusionné, 0 dans
le lot — rien n'est réintroduit ni perdu dans aucun sens. La seule incohérence que
la fusion créerait est **N2** : le §4.19 démontre la prémisse fausse pendant que
`retriever.py:182` l'affirme.

### 4.21 La réparation des deux bloquants du lot 3 — et une réserve nommée par son auteur, mesurée fausse

`Conv' 31`, le 7 septembre 2026, sur la branche du lot 3. Les deux bloquants de
l'audit (§4.20) sont refermés, N1 et N2 le sont aussi, et **quatre des sept non
bloquantes** sont fermées. La porte : `make lint` **rc=0**, `make test`
**rc=0**, **552 passés** — 539 avant, **+13** cas neufs — et le rc relevé est
celui **du processus**, hors tube : `cmd 2>&1 | tail` rendrait celui de `tail`.

**La batterie : onze mutations, dix mordent, le onzième est un témoin inerte.**
Chacune restaurée, et la restauration **vérifiée par empreinte SHA-256** et non
par `git diff` — l'arbre portait du travail non commité, donc `git diff` y est
légitimement non vide et **ne prouve rien**. Le rc relevé est celui de `pytest` ;
`make`, lui, rend 2.

| | mutation | site | texte | `rc` | rouges |
|---|---|---|---|---|---|
| **M1** | la reprise ne repasse plus le garde | `retriever.py` | +0/-1 | **1** | 1 |
| **M2** | le verdict est inscrit sans compare-et-échange | `retriever.py` | +1/-2 | **1** | 2 |
| **M3** | le réarmement n'incrémente plus la génération | `retriever.py` | +0/-1 | **1** | 2 |
| **M4** | plus de vérification avant l'ouverture du flux | `main.py` | +1/-1 | **1** | 1 |
| **M5** | la divergence en vol redevient muette | `main.py` | +1/-1 | **1** | 1 |
| **M6** | la prémisse Docker fausse repart dans `src/` | `main.py` | +1/-1 | **1** | 1 |
| **M7** | le champ de concordance devient optionnel | `schemas.py` | +1/-1 | **1** | 1 |
| **M8** | la fixture `autouse` ne réarme plus | `tests/conftest.py` | +0/-2 | **1** | 1 |
| **M9** | la barrière réseau ne pose plus rien | `tests/unit/conftest.py` | +1/-1 | **1** | 2 |
| **M10** | l'inventaire documentaire retrouve son angle mort | `test_coherence_depot.py` | +2/-2 | **1** | 1 |
| **T1** | **témoin inerte** — un commentaire réécrit | `retriever.py` | +1/-1 | **0** | **0** |

#### B1 — la reprise de `_dense_search` repasse le garde

`reset_connection()` désarmait bien le verdict, mais la requête en cours
interrogeait la collection rouverte **sans repasser le garde**. Un
`verifier_modele_embedding()` est désormais appelé entre la réouverture et la
retentative, et le motif est écrit au site.

**Le rouge d'avant, `mesuré`** : `DID NOT RAISE EmbeddingModelMismatchError`, la
collection divergente **servie**, une seule ligne au journal — le `WARNING` de
réouverture. Après : la levée porte le nom du modèle divergent et
`divergente.requetes == 0`.

**Le bouchon modélise la mémoïsation, et c'est la condition de validité de la
mesure.** `_ouverture_memoisee` ne fait avancer la collection **qu'au
`cache_clear()`**, comme le vrai `lru_cache` : c'est le piège qui a coûté au
pilote une contradiction inexistante (§4.20), et le seul montage où le « faux
servi » vient bien de la reprise. Un **témoin** l'accompagne —
`test_la_reprise_sert_bien_ce_qu_une_collection_concordante_rend` — parce qu'un
garde qui refuserait aussi la réouverture légitime transformerait la résilience
en panne.

#### B2 — le réarmement concurrent n'est plus écrasé, et le site ne ment plus

La réserve écrite au site — « le pire cas est une vérification faite deux fois ;
un verrou coûterait plus cher que ce qu'il éviterait » — était **fausse**, et
c'est une réserve que l'auteur du lot avait nommée lui-même.

**La forme retenue n'est pas un verrou sur le chemin chaud, c'est une
GÉNÉRATION.** Elle est incrémentée à chaque réarmement ; la vérification la
relève avant de lire et n'inscrit son verdict favorable **que si elle n'a pas
bougé** — un compare-et-échange. Le verrou ne couvre donc que deux affectations
en mémoire, **jamais la lecture** : un réarmement concurrent n'attend pas
derrière l'ouverture d'une collection, et un réarmement survenu pendant la
lecture fait **jeter** le verdict au lieu de l'écraser. Se tromper dans ce
sens-là coûte une relecture locale ; se tromper dans l'autre coûte le garde.

**COMMENT LA COURSE EST RENDUE DÉTERMINISTE, et c'est la partie qui compte.**
Deux fils lancés en espérant un entrelacement donnent un test vert par chance et
rouge au hasard — *un garde dont le cas n'est atteint que par chance n'est pas un
garde*. Le réarmement est donc déclenché **depuis le point observable de la
lecture** : `_lire_estampille` est substituée par une lecture qui, avant de
rendre, démarre un **vrai autre fil** appelant `reset_connection()` et le
**joint**. L'écriture concurrente est réelle, elle traverse une vraie frontière
de fil, et son ordonnancement est **certain** : quand la lecture rend, le
réarmement a eu lieu. Aucun `sleep`, aucune attente d'ordonnanceur.

Deux tests, et le second est celui qui dit pourquoi B2 est **pire que B1** :
l'état écrasé ne se répare pas tout seul, donc une collection divergente passait
ensuite pour **toute la vie du processus**.

#### N1 — tranché en CODE, et la phrase redevient vraie au lieu d'être bornée

**La décision : vérifier la concordance AVANT d'ouvrir le flux**, la seconde des
deux voies proposées. Trois raisons, et la troisième a décidé :

- elle ferme aussi le **trou d'observabilité**, que borner la phrase laissait
  entier ;
- elle rend **vraie** l'affirmation des quatre documents — « toute recherche est
  refusée en 503 » — au lieu de la restreindre. Borner aurait demandé de
  maintenir à quatre endroits une exception dont plus rien n'aurait rappelé la
  cause ;
- **la borne aurait vieilli du mauvais côté.** La phrase n'était fausse que
  parce qu'une route s'était mise à chercher sans que personne le remarque ;
  écrire « sauf `/chat/resume` » aurait daté du jour où une cinquième route
  reboucle. Le code, lui, refuse par construction.

`await asyncio.to_thread(verifier_modele_embedding)` — `to_thread` parce que la
lecture est synchrone et que l'ouverture de la collection est un aller-retour
réseau : l'appeler nu bloquerait la boucle. `mesuré` après correction : **503**,
les **deux noms de modèles dans le corps**, la ligne **ERROR**, et **zéro octet**
servi.

**Le test prouve qu'il atteint son cas**, et c'est exigé : sans `lifespan` monté,
`/chat/resume` rend un 503 qui dit « Service en cours de démarrage » et **n'a
jamais vu le garde**. Deux 503 de causes différentes étant indiscernables par le
seul code, le test **exige le motif dans le corps** et branche le graphe pour que
ce 503-là ne puisse pas être celui du démarrage.

**CE QUE CETTE CORRECTION NE FERME PAS, et c'est écrit au site plutôt que
passé sous silence.** Une divergence apparue **après** l'ouverture du flux — `reset_connection()`
tourne toutes les 20 s depuis le `ping()` du healthcheck — tue toujours le flux
**tronqué** : le 200 est déjà parti, et aucune correction ne le reprend. Ce qui
change est qu'il ne meurt plus **muet** : le gestionnaire d'exception de
l'application n'étant jamais appelé après le premier octet, le
`stream_generator` journalise lui-même en **ERROR** avec les deux noms **sur la
ligne**, puis relaie. Le test qui garde ce résidu monte un `TestClient` en
`raise_server_exceptions=False` — un client qui relève l'exception donnerait à ce
test une forme que l'exploitant ne voit jamais.

**Une absorption large a été ajoutée, et voici sa justification** : la
vérification anticipée n'échoue pas seulement sur une divergence, elle échoue
aussi sur une estampille **illisible** (ChromaDB muet). Refuser dessus ferait
dépendre de ChromaDB une route qui, la plupart du temps, **ne cherche pas** —
elle reconstruit un contexte depuis Nebula et génère — et transformerait une
requête qui aboutit en 500. L'illisible est donc journalisé en `WARNING` et
laissé passer, le garde restant en place **à l'intérieur** du flux.
`EmbeddingModelMismatchError` est re-levée avant, donc l'absorption ne mange
jamais une divergence.

`/chat/simple` ne reçoit pas cette vérification, et c'est **mesuré** : il ne
passe pas par le graphe et ne cherche jamais. C'est la seule autre route qui
streame.

#### N2 — la prémisse Docker fausse : six sites de code, pas trois, et un garde plutôt qu'une correction

**L'inventaire de l'audit était incomplet, et c'est ma trouvaille.** Le §4.20
nommait trois sites. `mesuré` le 7 septembre 2026, la prémisse vivait à **six**
sites de code, plus **un** du registre — sept en tout, ceux que la table ci-dessous
énumère :

> **CE CHIFFRE ÉTAIT FAUX ICI MÊME, et c'est la trouvaille NB-2 de l'audit
> (§4.23).** Ce paragraphe écrivait « cinq sites de code, plus les deux du
> registre » quand sa propre table en listait **six** de code et **un** de
> registre — les six numéros de ligne étant exacts, `vérifié`. **La somme (7)
> était juste, la répartition fausse, et c'est PRÉCISÉMENT pourquoi elle est
> passée** : un total qui tombe juste dispense de recompter ses termes. C'est la
> signature exacte du défaut que ce chantier ferme lot après lot — *un
> raisonnement juste sur un antécédent faux se relit comme une preuve* — et elle
> apparaît ici dans le paragraphe même qui l'énonce, sous la plume de qui venait
> de l'écrire. Rien dans ce dépôt ne pouvait la voir : aucun garde ne confronte
> la prose d'un registre à ses propres tables.

| site | qui | fait |
|---|---|---|
| `src/agent/retriever.py:182` | ajouté par le lot 3 | **corrigé** — mandaté |
| `src/api/main.py:383` | antérieur | **corrigé** — élargissement déclaré par le pilote |
| `src/api/main.py:414` | antérieur, **hors inventaire de l'audit** | **corrigé** |
| `tests/unit/test_garde_modele_embedding.py:302` | **ajouté par le lot 3**, hors inventaire | **corrigé** |
| `tests/unit/test_health_parallele.py:470` | antérieur, hors inventaire | **corrigé** |
| `tests/unit/test_securite.py:178` | antérieur, hors inventaire | **corrigé** |
| `documentation/axes_amelioration.md` §1.27 | antérieur | **laissé tel quel** — déjà corrigé sur `main`, et l'y toucher fabriquerait un conflit dans la fusion que le pilote résout |

**`test_securite.py:178` était faux deux fois.** Il affirmait que « le
healthcheck Docker s'appuie sur ce statut ». Le healthcheck est
`curl -sf .../health` : il ne lit que le **code HTTP**, et `degraded` est un
**200** — ce champ lui est donc invisible. Le vrai motif est écrit à la place :
l'index se construit normalement au démarrage, et dégrader sur un état
transitoire ordinaire rendrait « degraded » illisible le jour où une dépendance
tombe vraiment.

**ET SURTOUT : la prémisse est désormais GARDÉE, pas seulement corrigée.** Une
correction sans garde se refait — ce nom de panne a essaimé sur sept sites sans
que personne ne le remesure, et *un raisonnement juste sur un antécédent faux se
relit comme une preuve*. `test_coherence_depot.py` porte donc un **inventaire**
de la famille de phrases, borné à `src/` et `tests/` — là où la prémisse sert de
**motif** à une décision qu'on relit ; le registre, lui, a pour métier de citer
une affirmation pour la démentir, et y inventorier ses comptes rendrait ce test
rouge à chaque fusion pour une raison qui n'est pas la bonne. **Ce garde a
trouvé un site que mon propre `grep` avait manqué** dès sa première exécution.

#### Les non bloquantes : quatre fermées, trois ouvertes

**N3 — fermé.** Le champ `embedding_model` de `/health` reste non optionnel, et
la décision est maintenant gardée : le rendre optionnel rend **1 rouge** (M7).
Asserté depuis le côté qui produit la garantie — la validation du modèle — et
non depuis l'annotation, qu'un `| None` suffit à démentir.

**N4 — fermé.** La fixture `autouse` de `tests/conftest.py` n'est plus inerte :
deux tests **ordonnés** de `tests/unit/test_montage_des_tests.py` l'encadrent —
le premier établit le verdict, le second exige de ne pas en hériter. Retirer le
réarmement rend **1 rouge** (M8). Le mécanisme repose sur l'ordre de déclaration
dans un module, ce que pytest garantit, et c'est **écrit au site** pour que
personne ne réordonne ces deux tests sans le savoir.

**N5 — fermé, et par CONSTRUCTION.** `mesuré` de mes mains, et la mesure de
l'audit est reproduite à l'unité : **48 tentatives de connexion `chromadb` sur
41 tests**, toutes depuis `_lire_estampille` ← `etat_modele_embedding` ←
`_executer_sonde`, dans un fil du threadpool — donc **un seul site structurel**,
la sonde de concordance de `/health`. Cinq fichiers restaient :
`test_capture_branchement.py`, `test_purge_sessions.py`, `test_absorptions.py`,
`test_flux_interactif.py`, `test_securite.py`.

> **La sonde de mesure a dû changer de couche, et c'est une leçon.** Une première
> sonde posée sur `socket.socket.connect` rendait **0 dans les deux sens** — avec
> et sans correction. Elle mentait : ces 48 tentatives **ne parviennent jamais à
> `connect`**, elles meurent à `getaddrinfo`, l'hôte `chromadb` ne se résolvant
> pas depuis un poste de développement. C'est exactement ce que l'auditeur
> voulait dire par *« le montage tient par absorption, pas par construction »* —
> et une sonde placée trop bas aurait signé un faux zéro. Mesuré à la bonne
> couche : **63 résolutions vers `chromadb` sur 44 tests** sans la barrière,
> **0** avec.

Le remède n'est **pas** un branchement fichier par fichier : un branchement ne
couvre que les tests déjà écrits. `tests/unit/conftest.py` — **séparé** de
`tests/conftest.py`, parce que `tests/integration/` ouvre de vraies connexions
et qu'une barrière posée à la racine l'aurait cassé — interdit
`chromadb.HttpClient` et lève un message qui **nomme le geste**. La barrière est
elle-même gardée (M9, **2 rouges**) : une fixture non gardée est précisément le
défaut de N4.

**N6 — fermé.** L'inventaire ne balayait que `documentation/*.md` **non
récursif** plus `README.md`. Il balaie désormais **tous les fichiers suivis par
git**, et cette borne-là est choisie : ce dépôt est **public**, donc l'ensemble
des fichiers suivis est exactement ce qu'un lecteur peut copier — la borne décrit
le **risque** au lieu de décrire l'arborescence, et un répertoire neuf y entre
tout seul. Les deux fichiers de test qui portent légitimement ce nom sont entrés
dans la table. **Coverage prouvée dans le sens montant** : une occurrence plantée
dans `.env.example`, `src/agent/settings.py`,
`documentation/audits/2026-09-03-audit-lot-1.md` et `scripts/evaluate.py` rend
`rc=1` **dans les quatre cas** — quatre angles morts, quatre rouges. Et dans le
sens descendant par M10.

**Restent ouvertes** : **N7** (aucun test ne garde le drapeau « en vol » de la
sonde neuve), **N8** (la mémoïsation du verdict n'est gardée par rien — un
refactor qui la retire ne rougit pas), **N9** (l'`except Exception`
d'`etat_modele_embedding`, consigné et recevable).

#### Ce que cette réparation a trouvé et n'a PAS fermé

**`tests.md` annonçait un compte faux DANS LE COMMIT QUI LE CORRIGEAIT.**
`mesuré` : à `c5c38d5`, la page annonçait **520** tests sur **36** fichiers
quand le dépôt en portait **539** sur **37** — 19 tests et un fichier de retard,
écrits par le commit même qui prétendait rattraper le retard, et ni le lot ni
son audit ne l'ont vu. C'est la **démonstration** du §4.13 plutôt qu'une
nouvelle entrée : *rien ne pouvait le voir*. Le chiffre est remis à **552 sur
38** et la note porte désormais l'épisode. **Le garde reste ouvert** — c'est lui
la trouvaille, pas le chiffre, et le corriger une troisième fois sans garde
serait le geste que ce §4.13 sanctionne.

**Deux tests unitaires résolvent encore l'hôte `ollama`** — `mesuré` :
`test_purge_sessions.py::test_health_publie_les_suppressions_reelles_et_les_echecs`
et `test_securite.py::test_health_reste_interrogeable_sans_cle`, deux
résolutions vers `ollama:11434` depuis un fil du threadpool. **Même classe de
défaut que N5**, autre dépendance : ces deux-là ne tiennent verts que parce que
`ollama` ne se résout pas non plus. La barrière de `tests/unit/conftest.py` ne
couvre que `chromadb`, et l'étendre à `httpx` demande de décider ce que
`_sonder_ollama` doit voir — une décision, pas un geste. **Non fermé, nommé
ici.**

### 4.22 La réparation du lot 3 vérifiée — et l'horloge avait bougé de trois jours

**État : réparé (`Conv' 31`, `19f7cec`), NON poussé, NON fusionné, audit
distribué (`Conv' 32`).**

#### Ce que le pilote a mesuré de ses mains, le 7 septembre 2026

Arbre dédié à `19f7cec`, environnement monté par le protocole du §2.2, `rc` du
processus :

| | `mesuré` |
|---|---|
| porte qualité | `make lint` `rc=0`, `make test` `rc=0`, **552 passés** (539 avant) |
| **B1 refermé** — sonde du pilote, fidèle au `lru_cache` | **0** requête servie par la collection divergente, la collection a bien **changé en vol** (donc le cas est atteint), et le motif nomme **les deux** modèles |
| **B2 refermé** — réarmement déclenché depuis la lecture, par un vrai autre fil | verdict **non** mémorisé après la course, et le garde **refuse** la collection devenue divergente : le réarmement est conservé |
| **N1 gardé** — mutation du pilote, la vérification avant le flux retirée | `rc=2`, **1 rouge** : `test_chat_resume_refuse_en_503_avant_d_ouvrir_le_flux` |
| **N6 mord hors de son ancien périmètre** — occurrence plantée dans `.env.example`, un fichier **suivi** hors `documentation/` | rouge : `test_le_nom_du_modele_anglais_ne_vit_que_la_ou_il_est_justifie` |
| **N5 bornée aux tests unitaires** | la barrière vit dans `tests/unit/conftest.py` et patche `chromadb.HttpClient` ; `tests/integration/` n'a pas de `conftest.py`, donc ses vraies connexions ne sont pas touchées |
| le verrou n'est pris à **aucun site imbriqué** | trois prises — une dans le réarmement, deux dans la vérification, la lecture **hors** verrou : pas d'interblocage possible |
| désactivations ajoutées | **aucune** ; `pyproject.toml`, `Makefile` et `.pre-commit-config.yaml` intacts ; la seule absorption large ajoutée est justifiée au site |
| comptes publiés | `tests.md` annonce **552 / 38** ; `make test` rend 552 passés et `ls tests/unit/test_*.py` rend 38 |

#### L'HORLOGE AVAIT BOUGÉ DE TROIS JOURS, ET LE RÉPARATEUR L'A VU

`mesuré` : `date -u` rendait `Fri Sep 4 07:35 UTC 2026` à l'ouverture de la
conversation de pilotage, et rend **`Mon Sep 7 09:43 UTC 2026`** maintenant. Les
commits le confirment — `c5c38d5` porte le **4 septembre**, `5a6e15f` et
`19f7cec` portent le **7**.

**Le réparateur a daté le 7, et il n'a écrit aucun « 4 septembre » — zéro
occurrence ajoutée par son diff, mesuré.** Il a donc relevé l'horloge au lieu de
recopier la date de la conversation. **Le pilote, lui, aurait écrit « 4 septembre
2026 » par habitude** : c'est exactement la faute que le dépôt jumeau a payée
neuf fois dans un seul lot, trouvée en comparant les dates écrites aux dates des
commits. *Une date est une mesure comme une autre*, et une conversation longue
est précisément l'endroit où l'on cesse de la mesurer. Les dates du §4.19 et du
§4.20 restent justes — les mesures qu'elles portent ont bien été faites le 4.

#### Ce que le pilote accepte, et pourquoi

**L'élargissement de périmètre, au-delà de la ligne que le pilote avait
déclarée.** Le pilote avait autorisé un site (`main.py:383`) ; le réparateur en a
corrigé **quatre de plus** — `main.py:414`, et les sites de la même prémisse dans
`test_garde_modele_embedding.py`, `test_health_parallele.py`,
`test_securite.py` — tous **hors de l'inventaire de l'audit**, tous déclarés, avec
offre de revert. **Accepté.** Le motif est la règle du chantier lui-même : *une
correction bornée au motif qu'on a tapé n'est pas une correction, c'est un
échantillon*, et elle a déjà été payée trois fois ici. Et l'un des quatre était
**faux deux fois** — `test_securite.py` supposait que le healthcheck voit le champ
`degraded`, alors qu'il est `curl -sf` et ne lit que le code HTTP, et que
`degraded` est un **200**.

**Et la prémisse n'est plus seulement corrigée : elle est GARDÉE**, par un
inventaire de la famille de phrases borné à `src/` et `tests/`. Ce garde **a
trouvé, à sa première exécution, un site que le `grep` du réparateur avait
manqué**. C'est la bonne forme : le §4.18 avait retenu qu'une énumération close ne
se rouvre pas, un inventaire gardé si.

**Le refus de trancher l'écart onze/douze, et il a raison.** Le pilote avait
demandé de trancher ; le réparateur a **refusé avec une mesure** : le rapport du
lot 3 n'a jamais été un artefact du dépôt — `git log --all --grep` n'en retrouve
rien, `documentation/audits/` ne porte que l'audit du lot 1 — donc les deux
tabulations sont **irrelisibles** et désigner une gagnante serait conclure sans
mesure. Le **onze** du §4.4 est interne à son paragraphe, où il se vérifie, et
c'est le site canonique. *Un compte qui ne vit que dans une conversation n'est pas
un compte* — même famille que les « toutes / aucune » que ce chantier a passé
trente commits à fermer. **Le pilote suit, et retient la leçon plutôt que le
chiffre.**

#### La trouvaille du réparateur : `tests.md` était faux DANS le commit qui le corrigeait

`mesuré` : à `c5c38d5`, `documentation/tests.md` annonçait **520 tests sur 36
fichiers** quand la réalité était **539 sur 37**. Le retard a été écrit **par le
commit même qui prétendait le rattraper** — et ni le lot, ni son audit, ni le
pilote ne l'ont vu. Remis à **552 / 38**.

C'est la **troisième** fois que ce chiffre est corrigé au site sans que rien ne le
garde, et c'est la démonstration exacte du **§4.13** : *rien ne lit le compte de
tests ni les documents, donc la documentation dérive sans qu'aucun rouge ne
s'allume.* **Le garde reste absent, et c'est lui la trouvaille, pas le chiffre.**
C'est le F7 du dépôt jumeau, et il monte au plan.

#### Pourquoi le pilote NE fusionne pas, et c'est son propre critère qui l'y oblige

Le §4.18 énonçait le critère sous lequel la seconde réparation du lot 2 a été
fusionnée sans quatrième audit : le lot audité, sa première réparation auditée,
les directions dangereuses vérifiées par le pilote, **et `src/` inchangé, mesuré,
donc aucune régression fonctionnelle possible.**

**Ici la quatrième condition ne tient pas.** Cette réparation touche le code de
production — `retriever.py` `+87`, `main.py` `+115` — et elle y ajoute un
**compare-et-échange sous verrou** sur le chemin de chaque recherche, plus une
vérification synchrone **avant l'ouverture d'un flux**. Le pilote a vérifié les
deux bloquants et le garde de N1 de ses mains, et il n'a trouvé aucun défaut ;
cela ne remplace pas une lecture indépendante de 1 185 lignes dont 202 de
production. *Appliquer son critère quand il arrange et l'oublier quand il coûte
une conversation, ce serait n'avoir pas de critère.*

**Ce que l'audit `Conv' 32` doit chercher en priorité**, et qui n'a pas été lu par
une conversation indépendante : la justesse du compare-et-échange sous
concurrence réelle ; ce que la vérification synchrone avant le flux coûte à
`/chat/resume` quand ChromaDB est lent ou muet ; les angles morts de la barrière
de `tests/unit/conftest.py` — le réparateur signale lui-même que **deux tests
résolvent encore l'hôte `ollama`**, même classe, autre dépendance ; et la
décoration éventuelle de chacun des **13** tests neufs.

### 4.23 L'audit de la réparation du lot 3 — une route qui pend, et un ordre de deux lignes que rien ne garde

L'audit indépendant de `19f7cec` (`Conv' 32`) a **reproduit les onze mutations à
l'identique**, les comptes, les deux bloquants refermés, et **aucune mesure du
pilote n'a été renversée**. Il rend **une trouvaille bloquante** et quatre non
bloquantes. Sa recommandation — ne pas fusionner en l'état — est suivie.

#### B-1 — BLOQUANT : `/chat/resume` dépend de ChromaDB sans plafond, et le fil ne se récupère pas

Le site neuf est `await asyncio.to_thread(verifier_modele_embedding)`, **nu**.
`mesuré` par le pilote le 7 septembre 2026, collection bouchonnée qui **pend** —
un `Event` jamais posé, aucun accès réel à ChromaDB :

| | `mesuré` |
|---|---|
| le motif du site neuf | **toujours bloqué après 6 s**, et le pilote avait *ajouté* un `wait_for` que le site réel **n'a pas** : il attendrait indéfiniment |
| `_concordance_embedding()` — la version **bornée que le même fichier possède déjà** | **rendue en 3,0 s**, `status='unknown'`, avec sa ligne « n'a pas répondu en 3.0 s ; on renonce à l'attendre » |
| le processus de la sonde | **`rc=124`**, tué par `timeout` **après** avoir tout imprimé — le fil non-démon empêche l'interpréteur de sortir, ce qui corrobore la fuite de fil |

**Ce qui rend la trouvaille grave n'est pas la panne, c'est que le fichier avait
déjà écrit le remède.** Il borne la **même lecture** sous `_PLAFOND_SONDES_S = 3.0`
à deux sites, il emploie ailleurs `anyio.to_thread.run_sync(…,
abandon_on_cancel=True)` — la primitive **annulable** — et le docstring de
`_sonder` note explicitement que *« la lecture de l'estampille du modèle
d'embedding passe par le même mécanisme »*. Le site neuf a choisi
`asyncio.to_thread`, qui n'est **ni borné ni annulable**, sur cette
opération-là.

**Et le commentaire du site nomme l'objectif que le code n'atteint pas** :
l'absorption large dit exister pour ne pas *« faire dépendre de ChromaDB une
route qui, la plupart du temps, ne cherche PAS »*. Elle protège d'un ChromaDB qui
**lève**. Elle ne peut rien contre un ChromaDB qui **pend** — la panne la plus
banale d'un store réseau, et précisément celle que la reprise de `_dense_search`
existe pour rattraper. *La dépendance est sur l'appel, pas sur l'exception.*

Chiffres de l'auditeur, non remesurés par le pilote : `chromadb 1.5.9` n'a **aucun
délai par défaut** (>400 s sur un serveur muet) ; au niveau de la route, une
requête qui **ne cherche pas** passait de **0,07 s** à **aucune réponse** ; le fil
fuit à l'annulation ; **26** requêtes bloquées épuisent l'executor asyncio. Le
rayon est **borné à sa décharge** : le réservoir anyio est distinct, donc
`/health` survit, et ce site est le **seul** `asyncio.to_thread` du dépôt.

**L'absorption large, elle, est correcte** : `except EmbeddingModelMismatchError`
vient en premier, et la mutation X2 de l'auditeur — la faire avaler la divergence
— rend `rc=1`, 1 rouge. Elle ne peut pas masquer une vraie divergence.

#### NB-1 — la sûreté du compare-et-échange tient à l'ordre de deux lignes adjacentes

`reset_connection()` fait `cache_clear()` **puis** `rearmer_verification_modele()`,
et c'est le bon ordre. **`mesuré` par le pilote le 7 septembre 2026 : inversé, les
552 tests restent VERTS, `rc=0`, zéro rouge** — restauration vérifiée par
empreinte SHA-256. L'auditeur a montré par entrelacement forcé que l'ordre inverse
rend un verdict favorable mémorisé sur une collection divergente : **c'est B2
réintroduit à l'identique, par un réordonnancement de deux lignes.**

La fenêtre en production est étroite — deux appels C successifs — et la sonde de
concurrence de l'auditeur, sur des millions d'itérations, ne l'a **pas** touchée.
Non bloquant, donc. **Mais à fermer dans la même passe** : *une décision
argumentée et non gardée est une décision qui se défera sans un rouge*, et
celle-ci protège exactement le bloquant que cette réparation existe pour fermer.

#### Les trois autres non bloquantes

| | Ce que c'est | Suite |
|---|---|---|
| **NB-2** | **un compte du §4.21 ne se vérifie pas à son propre site** : son texte écrit « cinq sites de code, plus les deux du registre » quand sa **propre table** en liste **six** de code et **un** de registre — et les six numéros de ligne sont exacts. La somme (7) est juste, la répartition fausse, *c'est pourquoi elle est passée*. Le « quatre de plus » du §4.22 est correct. **C'est la signature exacte du défaut que ce chantier ferme lot après lot, dans le paragraphe qui l'énonce** | `Conv' 33` |
| **NB-3** | l'inventaire de la prémisse Docker **mord dans les deux sens** dans son périmètre — vérifié par l'auditeur — mais il filtre sur `src/` et `tests/` là où `_fichiers_suivis()` rend tout le suivi : **68 fichiers balayés, 47 hors**, dont **`docker-compose.yml`** — le fichier même dont la prémisse parle, et l'endroit où elle serait la plus dangereuse — plus `README.md`, `Dockerfile.agent` et `scripts/`. Quatre angles morts `mesurés` verts | `Conv' 33` |
| **NB-4** | le trou `ollama` est **exact et borné** : exactement **2** résolutions, nommées, aucune assertion n'en dépend, latence bornée par `_PLAFOND_SONDES_S` et le `timeout=5.0` d'httpx. Un docstring dit « les dépendances sont neutralisées » et en neutralise **trois sur quatre** | consigné |

#### Ce que l'audit a établi et que le pilote n'avait pas fait

- **la concurrence réelle**, avec une sonde dont il a **prouvé la capacité** : elle
  rompt l'invariant sur **trois** configurations du code d'avant réparation, et
  rend **0 violation** sur jusqu'à **20,5 millions** de vérifications après. Sa
  première version rendait 0 des deux côtés — *il l'a déclarée décorative et n'en
  a rien conclu*, ce qui est le geste juste ;
- **la direction du témoin** que le pilote n'avait pas dite : la reprise
  **légitime** est toujours servie, et sa mutation X3 fait tomber **3** rouges dont
  le témoin et un test de résilience antérieur ;
- **aucun test existant affaibli, prouvé par AST** — `test_health_parallele.py` et
  `test_securite.py` ont un AST **identique hors docstrings**, asserts 39→39 et
  16→16 ;
- **13 tests ajoutés, 0 retiré**, mesuré sur l'**adresse** et non sur le nom ;
- et **la résolution du conflit de fusion** : les deux côtés ajoutent en fin de
  fichier, la branche ne contient **ni §4.19 ni §4.20**, donc *« garder les deux
  dans l'ordre du conflit » rangerait les sections 4.19, 4.20, **4.22, puis
  4.21***. **Il faut intercaler le §4.21 AVANT le §4.22, pas concaténer.** Rien
  n'est perdu ni réintroduit de faux d'aucun côté — aucune date fausse, aucune
  contradiction chiffrée, aucun renvoi pendant.

#### Deux corrections que le pilote encaisse

**Son chiffre de « 202 lignes de production » confondait deux mesures** : le diff
fait **175 insertions** et 27 suppressions ; 202 est leur somme. Sans conséquence,
mais ce sont deux grandeurs différentes, et ce chantier en a déjà payé une —
« le plus gros fichier de tests » du §4.14.

**Et le piège de `merge-tree` est plus fin que le mandat ne le dit.** `mesuré` par
l'auditeur sur git 2.53.0 : la forme à **deux** arguments rend déjà `rc=1` ; c'est
la forme **historique à trois** arguments (`base b1 b2`) qui rend **`rc=0` malgré
13 marqueurs de conflit**. Le mandat est à préciser : ce n'est pas
`--write-tree` qui sauve, c'est de ne pas employer la forme à trois arguments.

#### La faute de manœuvre de l'auditeur, déclarée — et vérifiée exacte par le pilote

L'auditeur a tapé `cd /home/ubuntu/RAG/rag-agent-chat` — **l'arbre principal** — au
lieu du sien, y a détaché `HEAD` hors de `main`, et a lu le `.venv` de cet arbre.
**Il l'a déclaré en tête de son rapport, avant tout le reste, avec ses mesures de
dégât.** `vérifié par le pilote` le 7 septembre 2026 : `git reflog show main` ne
porte **aucune** entrée étrangère — seulement les fusions du pilote — et le reflog
`HEAD` de l'arbre principal montre exactement `main → 19f7cec → main`, le
détachement et sa restauration. `main` = `801fbf4`, sur la branche `main`, arbre
propre, 28 commits d'avance. **Aucun dégât.**

Ce qui vaut d'être retenu n'est pas la faute — elle est sans conséquence et elle a
été réparée avant que quiconque la voie — c'est **la déclaration**. Un auditeur qui
ouvre son rapport par son propre incident, avec les mesures qui en bornent la
portée, rend son rapport plus croyable et non moins. *C'est le contraire de la
faute qui a coûté un dépôt entier au projet jumeau : celle-là avait été découverte
par quelqu'un d'autre.*

### 4.23 bis Le bloquant de l'audit de la réparation refermé — une route bornée, et un ordre de deux lignes qui rougit enfin

`Conv' 33`, le 7 septembre 2026, sur la branche du lot 3. La trouvaille bloquante
du §4.23 est refermée, les quatre non bloquantes aussi, et un garde que le §4.21
laissait ouvert l'est également. La porte : `make lint` **rc=0**, `make test`
**rc=0**, **557 passés** — 552 avant, **+5** cas neufs — `rc` du **processus**,
hors tube et sans filtre.

> **CETTE SECTION DOIT ÊTRE INTERCALÉE APRÈS LE §4.23 À LA FUSION.** Cette
> branche ne contient ni §4.22 ni §4.23 : son fichier s'arrêtait au §4.21. Les
> deux côtés ajoutent en fin de fichier, donc « garder les deux dans l'ordre du
> conflit » rangerait 4.22, 4.23, **puis** 4.21 et 4.24. C'est le même piège que
> l'auditeur avait nommé pour le §4.21, et il vaut une fois de plus.

#### La batterie : sept mutations, six mordent, la septième est un témoin inerte

Chacune restaurée, et la restauration **vérifiée par empreinte SHA-256** — l'arbre
porte du travail non commité, donc `git diff` y est légitimement non vide et **ne
prouve rien**. Le `rc` relevé est celui de `pytest` ; `make`, lui, rend 2.

| | mutation | site | `rc` | rouges | nom du rouge |
|---|---|---|---|---|---|
| **M-B1a** | le site regagne sa forme non bornée (`asyncio.to_thread` nu) | `main.py` | **1** | 1 | `…rend_meme_quand_l_estampille_ne_repond_jamais` |
| **M-B1b** | le dépassement REFUSE au lieu d'être absorbé (décision 1 inversée) | `main.py` | **1** | 1 | idem |
| **M-B1c** | plus de drapeau « en vol » (décision 2 inversée) | `main.py` | **1** | 1 | `…ne_lache_qu_un_fil_meme_en_rafale_simultanee` (renommé au §4.26) |
| **M-B1d** | `_relever` réemployée, qui ABSORBE la divergence | `main.py` | **1** | 2 | `…revenue_dans_le_plafond_est_toujours_relevee`, `…refuse_en_503_avant_d_ouvrir_le_flux` |
| **M-NB1** | les deux lignes de `reset_connection()` inversées | `retriever.py` | **1** | 1 | `…l_ordre_de_reset_connection_ne_peut_pas_s_inverser_en_silence` |
| **M-NB3** | la borne de l'inventaire **de la prémisse Docker** redevient `src/` + `tests/` — la SECONDE boucle sur `_fichiers_suivis()`, celle de `…la_premisse_docker_fausse_ne_sert_de_motif_a_rien` | `test_coherence_depot.py` | **0** | **0** | *l'angle mort : voir ci-dessous* |
| **M-NB2b** | le titre de `tests.md` annonce 552 au lieu du compte mesuré | `tests.md` | **1** | 1 | `…le_compte_de_tests_annonce_est_celui_que_pytest_collecte` |
| **T1** | **témoin inerte** — un mot de commentaire réécrit | `main.py` | **0** | **0** | — |

#### B-1 refermé — la lecture est bornée, le fil est gardé, et les deux décisions sont écrites au site

**Le bloquant reproduit d'abord, avec une collection qui PEND** — un
`threading.Event` jamais posé, aucun accès réel à ChromaDB, sonde en lecture
seule bornée par un `timeout` extérieur, `rc` du **processus** :

| | `mesuré` |
|---|---|
| le motif du site (`asyncio.to_thread` nu, avec un `wait_for` ajouté par la sonde) | **toujours bloqué après 6,01 s** |
| `_concordance_embedding()`, la version bornée que le fichier possédait déjà | **3,00 s**, `status='unknown'`, avec sa ligne « n'a pas répondu en 3.0 s » |
| au niveau de la ROUTE, une requête qui **ne cherche pas** | **0,030 s → AUCUNE réponse après 15 s** |
| le processus de la sonde | **`rc=124`** |

**Et une mesure plus dure que celle de l'audit.** L'audit notait que le fil
non-démon empêche l'interpréteur de sortir *après* que la sonde a tout imprimé.
`mesuré` ici : sur le motif d'avant, **`asyncio.run` lui-même ne rend jamais la
main** — sa fermeture appelle `shutdown_default_executor()`, qui joint le fil
lâché — donc **rien** ne s'imprime après. Ce n'est pas la sortie de
l'interpréteur qui est retenue, c'est la boucle d'événements.

**La correction emploie ce que le fichier possédait** :
`_concordance_avant_le_flux()`, sœur de `_concordance_embedding()`, sous
`_PLAFOND_SONDES_S`, par `_sonder` — donc par `to_thread.run_sync(…,
abandon_on_cancel=True)`, la primitive annulable — et sous le drapeau « en vol ».
`mesuré` après : **3,00 s, rendue sans lever**, et `asyncio.run` rend.
`asyncio.to_thread` **ne subsiste nulle part** dans le dépôt hors du commentaire
qui raconte cette histoire.

**PREMIÈRE DÉCISION — un dépassement de plafond est la MÊME chose qu'une
estampille illisible, et le plafond est réemployé.** Trois raisons, écrites au
site :

- **ce que l'appelant apprend est identique : rien.** « ChromaDB a répondu par une
  panne » et « ChromaDB n'a pas répondu » ne se distinguent pas du point de vue
  de la concordance. Ce dépôt l'a déjà tranché **deux fois dans ce sens** :
  `etat_modele_embedding()` range la levée en `unknown`, et le plafond de
  `_concordance_embedding()` range le silence en `unknown` aussi. Un troisième
  traitement du même non-savoir serait une divergence de sémantique sans fait
  pour la porter ;
- **la conséquence doit l'être aussi, et c'est l'argument décisif.** Refuser sur
  le dépassement ferait dépendre de ChromaDB une route qui, la plupart du temps,
  ne cherche pas — l'objectif que le commentaire du site nommait déjà. Ce serait
  **strictement pire** que refuser sur la levée : le silence est la panne la plus
  banale d'un store réseau ;
- **la sûreté ne bouge pas** : ce qui est perdu est la seule anticipation. Le
  garde reste dans le flux, fail-closed, et une divergence revenue dans le
  plafond est re-levée telle quelle — gardé par un **témoin** (M-B1d).

Le plafond est **réemployé et non doublé** : la grandeur bornée est la même — un
aller-retour pour ouvrir la collection — et c'est la **même lecture**, ce que le
docstring de `_sonder` disait déjà. Un second plafond laisserait les deux dériver
alors qu'aucun fait ne les distingue. **Ce que ce réemploi cache est dit au
site** : la *provenance* des 3 s diffère — à `/health` c'est une échéance imposée
du dehors par `docker-compose.yml`, ici un budget que la route s'impose.

**SECONDE DÉCISION — oui, le drapeau « en vol », et sous le MÊME nom.** La menace
que ce drapeau borne est **strictement plus grande** ici qu'à `/health` : là-bas
le cadenceur est un tick toutes les 20 s, borné par construction ; ici c'est le
débit des requêtes utilisateur, que rien ne borne. `mesuré` avec les **26**
requêtes de l'audit :

| | fils lâchés | requêtes rendues |
|---|---|---|
| motif d'avant, nu | **26** | **0/26** en 6,20 s |
| site corrigé, sous drapeau | **1** | **26/26** en 3,21 s |

Le **même nom** parce que c'est la même lecture de la même estampille sur le même
objet de collection : un second fil ferait un travail identique, et deux noms
lâcheraient deux fils en prétendant à deux faits là où il n'y en a qu'un. **Ce que
le partage coûte est accepté et écrit** : une sonde de `/health` en vol fait
renoncer la route à son anticipation, ce qui dégrade vers le cas absorbé — donc
vers ce que le dépassement produit déjà.

#### Deux fois une sonde décorative, et deux fois la leçon a payé

C'est la leçon la plus chère du lot, et elle s'est présentée **deux fois dans
cette passe** :

- **la sonde de B-1 rendait 0,00 s sur le site corrigé** — verte, et pour la
  mauvaise raison : en un seul processus, la phase qui la précédait laissait le
  drapeau « en vol » posé par son fil bloqué, et la phase suivante **sautait sa
  lecture**. Une phase par processus : **3,00 s**, le cas est atteint ;
- **la sonde de résolution de noms rendait 0 sur `ollama`** alors que
  `settings.ollama_host` vaut bien `http://ollama:11434`. Elle filtrait
  `isinstance(host, str)` quand anyio passe l'hôte en **bytes** (`b'ollama'`)
  après `idna2008_resolve`. Capacité prouvée par un appel direct avant de croire
  quoi que ce soit, puis **le compte du §4.21 reproduit à l'unité** : **2
  résolutions sur 2 tests**, les deux mêmes nommés, et **0** vers `chromadb` —
  la barrière de `tests/unit/conftest.py` tient, et les cas neufs de cette passe
  n'en ajoutent aucune.

*Une sonde qui ne rougit pas sur le défaut connu ne prouve rien sur le code
corrigé.* La sonde des fils a donc été retournée contre le motif d'avant (26
fils) avant qu'on croie son 1.

#### NB-1 refermé — l'ordre de deux lignes, nommé au site et gardé par entrelacement forcé

`reset_connection()` fait `cache_clear()` **puis**
`rearmer_verification_modele()`. L'ordre est désormais **nommé au site**, avec
l'entrelacement exact qui le rend fatal, et **gardé** : M-NB1 rend `rc=1`, **1
rouge**, là où le pilote avait mesuré que **les 552 tests restaient verts**.

**Le compare-et-échange ne peut rien contre cet ordre-là**, et c'est ce qui rend
le cas contre-intuitif : il protège d'un réarmement survenu **pendant** la
lecture, pas d'un réarmement survenu **avant** une lecture qui porte encore sur
l'ancien cache. Le journal du rouge le montre en trois mots :
`['rearmement', 'verdict', 'vidage']` — le verdict favorable est inscrit **avant**
que le cache soit vidé, donc sur une collection que personne ne relira.

**LA FORME DU GARDE EST LA DIFFICULTÉ, et elle diffère de celle de B2.** Là-bas
le point observable était la **lecture** ; ici c'est la **couture entre les deux
lignes**. Le test **ne connaît donc pas leur ordre** : il instrumente les *deux*
primitives et fait vérifier un vrai autre fil, **joint**, juste après celle qui
passe la **première**. C'est ce qui le rend sensible à l'inversion sans qu'il ait
à la nommer — et ce qui interdit de le satisfaire en réordonnant le test.

#### NB-2 refermé — et le garde du §4.13 fermé avec, plutôt qu'une troisième correction à la main

**Le compte du §4.21 est corrigé** : « **six** sites de code, plus **un** du
registre », et non « cinq, plus les deux ». La table en listait bien six et un,
et **`vérifié` : les six numéros de ligne sont exacts**. La somme (7) était juste,
la répartition fausse — *et c'est précisément pourquoi elle est passée : un total
qui tombe juste dispense de recompter ses termes*. Le constat est écrit **dans le
paragraphe qui l'énonce**, et les deux autres sites du même compte — deux
commentaires de `test_coherence_depot.py` — sont alignés sur **sept**.

**ET LE GARDE QUE LE §4.21 LAISSAIT OUVERT EST FERMÉ.** Cette passe ajoutant des
cas, elle rendait faux pour la **troisième** fois le compte publié par
`tests.md` — *et le corriger une troisième fois sans garde serait exactement le
geste que le §4.13 sanctionne*. La page est donc confrontée à la collecte de
`pytest`, **titre et note relevés séparément** : deux sites qui s'accordent entre
eux peuvent être faux ensemble, et c'est exactement ce qui est arrivé avec 520.

> **La mesure passe par `pytest` et non par un comptage des `def test_*`, et ce
> n'est pas un détail d'implémentation.** `mesuré` : l'AST en rend **527** là où
> `pytest` en collecte **557** — huit `parametrize` en déplient trente de plus.
> **Ce sont deux grandeurs différentes**, et ce chantier en a déjà payé deux
> confusions du même genre : le « 202 lignes » qui additionnait insertions et
> suppressions, et « le plus gros fichier de tests » du §4.14. Un garde qui
> comparerait le chiffre publié à un AST rendrait rouge un dépôt juste.
>
> **Le garde a rougi sur son propre auteur dès sa première exécution** : écrit
> avec 556, il a exigé 557 — lui-même étant le cinquième cas neuf.

Le sous-processus est le prix de la justesse : un décompte pris sur la session
courante serait gratuit mais rendrait le compte de la **sélection**, qu'un
`pytest -k` ferait rougir pour une mauvaise raison — et le rattraper demanderait
un `skip` conditionnel, que ce dépôt n'autorise pas.

#### NB-3 refermé — l'inventaire de la prémisse balaie tout le suivi, moins deux fichiers nommés

`mesuré`, et la mesure de l'audit reproduite à l'unité : **115 fichiers suivis,
68 dans l'ancien périmètre `src/` + `tests/`, 47 dehors** — dont
**`docker-compose.yml`**, le fichier même qui porte le `healthcheck` et le
`condition: service_healthy` sur lesquels toute cette prémisse porte, plus
`README.md`, `Dockerfile.agent` et les sept fichiers de `scripts/`.

**L'angle mort est mesuré des DEUX côtés, et c'est ce qui fait la preuve.** La
même aiguille plantée dans `docker-compose.yml` **et** `README.md` :

| borne de l'inventaire **de la prémisse Docker** | `rc` | verdict |
|---|---|---|
| tout le suivi (aligné) | **1** | rouge, les deux fichiers nommés dans le message |
| `src/` + `tests/` (M-NB3) | **0** | **vert — l'angle mort, mesuré** |

**L'ÉTIQUETTE PORTE SON SITE, et elle a dû être reprise pour cela** — non-bloquante
de l'audit étroit de la couche async, départagée en faveur du lot sur le `rc` et
contre lui sur le nom (§4.25). `test_coherence_depot.py` porte **deux**
inventaires, chacun avec sa boucle sur `_fichiers_suivis()`, et « la borne de
l'inventaire » ne disait pas lequel : muter la **première** — celle du
modèle anglais, N6 — rend `rc=2` et 1 rouge, muter la **seconde** — celle de
la prémisse Docker, la seule dont NB-3 parle — rend `rc=0`. Les deux mesures
sont justes ; c'était le nom qui en confondait deux. Deuxième fois sur ce lot
qu'un seul nom couvrait deux corps, après `T2-bornes-figées` au §4.15. *Une
étiquette de mutation est un chiffre : elle a besoin de son site.*

**Ce qui reste exempté est nommé, jamais filtré par répertoire.** Deux fichiers :
`documentation/axes_amelioration.md` et `documentation/pilotage_du_chantier.md`,
dont le métier est de **citer pour démentir**. `mesuré`, et c'est ce qui justifie
l'exemption au lieu de la supposer : **`main` porte une occurrence dans
`pilotage_du_chantier.md` que cette branche n'a pas** — un compte exact y rendrait
ce test rouge **à la fusion**, pour une raison qui n'est pas celle de ce garde.
Une **liste de noms** et non un préfixe, parce qu'un préfixe rendrait muet tout ce
qui viendra s'ajouter derrière lui : un document neuf de `documentation/` qui se
mettrait à *fonder* une décision sur cette prémisse rougit, comme rougirait
`docker-compose.yml`.

#### NB-4 refermé — la phrase dit ce que le test fait

Le docstring de `test_health_reste_interrogeable_sans_cle` disait « les
dépendances sont neutralisées » et en neutralise **trois sur quatre**. Il dit
maintenant lesquelles, et **ce qui borne la quatrième** plutôt que de la passer
sous silence : aucune assertion ne dépend de ce que la sonde Ollama rend, sa
latence est bornée deux fois — `_PLAFOND_SONDES_S` et le `timeout=5.0` de son
propre client — et **elle reste verte parce que le nom `ollama` ne se résout pas
depuis un poste de développement, ce qui est une absorption et non une
construction**.

**La quatrième n'est PAS neutralisée, et c'est délibéré.** Un branchement dans ce
test ne couvrirait que les tests déjà écrits ; le trou est consigné ouvert au
§4.21 avec le compte exact de ses **deux** sites, reproduit ci-dessus, et le
corriger en muet ici rendrait ce compte faux sans refermer la classe de défaut.

#### Ce que cette passe n'a PAS fermé

- **N7** — aucun test ne garde le drapeau « en vol » de la sonde de `/health`
  elle-même. Il est désormais gardé **sur le chemin de `/chat/resume`** (M-NB1c,
  1 rouge), ce qui est nouveau ; mais le résidu documenté au site — deux appels
  *vraiment* simultanés peuvent doubler la sonde le temps qu'un fil démarre —
  reste hors de portée d'un test, et le garde écrit ici le contourne
  explicitement en attendant que le drapeau soit posé avant de lancer la charge ;
- **N8** — la mémoïsation du verdict n'est gardée par rien ;
- **N9** — l'`except Exception` d'`etat_modele_embedding`, consigné et recevable ;
- **le trou `ollama`**, pour le motif écrit ci-dessus : la barrière ne couvre que
  `chromadb`, et l'étendre à `httpx` demande de décider ce que `_sonder_ollama`
  doit voir.

### 4.24 REPAR-5 vérifiée, le F7 partiellement fermé, et `main` poussé

**État : réparé (`Conv' 33`, `c8cb37d`), POUSSÉ pour tout ce qui précède, audit
étroit distribué (`Conv' 34`).** `main` = `origin/main` = **`a2ec58b`**.

#### Ce que le pilote a mesuré de ses mains, le 7 septembre 2026

| | `mesuré` |
|---|---|
| porte qualité | `make lint` `rc=0`, `make test` `rc=0`, **557 passés** (552 avant) |
| **B-1 refermé** — collection qui **pend**, `Event` jamais posé | `_concordance_avant_le_flux()` **rend en 3,00 s sans lever**, journalise ce qui se passe, et **la boucle rend la main** — là où le motif d'avant restait bloqué au-delà de 6 s |
| **NB-1 refermé** — les deux lignes de `reset_connection()` inversées | `rc=2`, **1 rouge** nommé, là où le pilote avait mesuré **552 verts** |
| le garde du compte de tests | mord : `tests.md` ramené à 552 → `rc=1`, 1 rouge nommé |
| le compte publié | **557 / 38**, et la mesure rend **557 collectés / 38 fichiers** |
| restauration après chaque mutation | vérifiée par **empreinte SHA-256** |

**Une correction que le réparateur doit au pilote, et elle est juste.** Le pilote
avait écrit que `abandon_on_cancel` réparait la fuite de fil. **Il ne la répare
pas** : `mesuré`, le processus de la sonde rend `rc=124` — tué par `timeout` —
**après** avoir imprimé ses trois lignes. Ce qui change n'est pas que le fil
disparaît : un appel réseau synchrone ne s'interrompt pas. C'est que **la boucle
d'événements rend la main**, là où `asyncio.to_thread` la retenait dans
`shutdown_default_executor()`. La fuite est **bornée à un fil** par le drapeau
« en vol », pas supprimée — et c'est écrit au site plutôt que passé sous silence.

#### La borne de NB-3 est meilleure que ce que le pilote demandait, et c'est mesuré

Le pilote demandait d'aligner l'inventaire de la prémisse Docker sur tout l'arbre
suivi, « ou de borner la phrase et dire pourquoi ». Le réparateur a **borné, avec
une mesure**, et il a eu raison. `vérifié par le pilote` le 7 septembre 2026 :

| révision | fichiers portant l'aiguille |
|---|---|
| `main` | **4** — `axes_amelioration.md`, **`pilotage_du_chantier.md`**, `src/api/main.py`, `tests/unit/test_securite.py` |
| la branche | **3** — `axes_amelioration.md`, `src/agent/retriever.py`, `tests/unit/test_coherence_depot.py` |

Un compte exact sur tout le suivi serait donc **rouge à la fusion**, et pas sur la
branche : *le défaut naîtrait de la fusion, invisible à toute relecture de
branche* — la famille (f) du §4.14, pour la troisième fois. La borne retenue est
**tout le suivi moins deux fichiers NOMMÉS** — le registre et le mandat, les deux
seuls qui doivent citer la phrase pour la réfuter — et jamais un préfixe de
répertoire.

**Résidu nommé** : ces deux fichiers exclus sont ceux où le pilote a corrigé la
prémisse (§1.27) et écrit sa leçon (§12 du mandat). **Rien ne rougit si un futur
pilote y réintroduit la prémisse comme une affirmation.** C'est nommé ici pour
rester rouvrable, pas fermé.

#### Le §4.13 / F7 est PARTIELLEMENT fermé — et le garde a rougi sur son propre auteur

Le réparateur a fermé, **hors mandat et en le déclarant**, le garde que le §4.13
laissait ouvert : le compte de tests annoncé par `documentation/tests.md` est
désormais confronté à ce que **`pytest` collecte**. Le motif est le bon : ses cas
neufs rendaient ce compte faux pour la **troisième** fois, et *le corriger une
troisième fois à la main est exactement le geste que le §4.13 sanctionne*.

Trois détails qui font que ce garde en est un :

- **il passe par `pytest`, pas par un AST** — `mesuré`, l'AST rend **527** là où
  `pytest` collecte **557**, huit `parametrize` expliquant l'écart. *Deux
  grandeurs différentes*, le piège que ce chantier a payé deux fois ;
- **le titre et la note sont relevés séparément** — deux sites qui s'accordent
  entre eux peuvent être faux ensemble, ce qui est **arrivé** avec 520 ;
- **il a rougi sur son propre auteur** : écrit avec 556, il a exigé 557, le garde
  étant lui-même un test.

**Ce qui reste ouvert du F7** : rien ne lit le `Makefile`, et rien ne lit les
autres chiffres des documents. Seul le compte de tests est gardé. Le point ne se
ferme pas ici.

#### `main` est poussé — et voici ce qui a été vérifié avant

Décision de l'utilisateur, le 7 septembre 2026. **31 commits** sont partis :
`7bcd346..a2ec58b`, `rc=0`, et `main` = `origin/main` = `a2ec58b`, avance **0**,
confirmé par `git ls-remote`.

Le distant est un dépôt **public**, et c'est l'opération que le projet jumeau a
payée d'un dépôt entier. `mesuré` avant le push, jamais après :

| contrôle | résultat |
|---|---|
| adresses, auteur **et** committer, sur les 31 | **62 signatures**, toutes `florian_horellou@laposte.net` |
| adresse hors des deux autorisées | **aucune** |
| `@aosis.net` | **0** |
| attribution à un assistant, messages **et** fichiers | **0** |
| `.env` suivi ? | **non**, et `.gitignore` le couvre en cinq formes |
| ligne ajoutée portant une valeur de secret | **aucune** |
| le mot de passe MinIO du poste dans le diff poussé | **0 occurrence** — recherché sans être imprimé |

**Et le trou reste ouvert** : le garde-fou d'identité couvre `commit`, `--amend`,
`--author=`, `merge --no-ff` et `merge --squash`, **mais pas `push`**. Ce push a
donc été protégé par une vérification **manuelle**, pas par un hook. La fermeture
honnête est un `pre-push`, et le §2.1 la laisse à trancher — elle monte au plan
maintenant que le dépôt pousse.

#### Pourquoi un audit ÉTROIT, et pourquoi c'est l'utilisateur qui a tranché

Le §4.18 posait le critère : `src/` inchangé → fusion sur vérification du pilote ;
`src/` changé → audit. Ici `src/` change encore. Mais **le lot 3 a consommé cinq
conversations et les deux audits ont chacun trouvé une bloquante réelle, toutes
deux dans la couche async/concurrence** — celle que cette réparation étoffe
encore, avec un drapeau « en vol » désormais posé sur un chemin de **requête
utilisateur** là où il ne servait qu'un tick de 20 s.

C'était donc un arbitrage de coût et non de technique, et le pilote l'a porté à
l'utilisateur plutôt que de le trancher seul. **Retenu : un audit borné à la
couche async** — le plafond, le drapeau sur un chemin de requête, et le
compare-et-échange. *On cible là où le taux de trouvaille est mesuré, au lieu de
repayer un audit complet ou de fusionner en espérant.*

### 4.25 L'audit étroit de la couche async — la fuite est bornée dans la DURÉE, pas dans la SIMULTANÉITÉ

L'audit `Conv' 34`, **borné à la couche async** sur décision de l'utilisateur, a
reproduit la porte, sept des huit mutations à l'unité, et rendu **une trouvaille
bloquante**. Le pilote l'a vérifiée de ses mains, **maintient la cotation**, et
**s'écarte de l'auditeur sur une non-bloquante**.

#### B-2 — BLOQUANT : une rafale simultanée de N requêtes lâche N fils

**La cause est structurelle.** `_sonder` teste `if nom in _sondes_en_vol` **sur la
boucle** ; `_executer_sonde` pose le drapeau **dans le fil**. Les deux sont de part
et d'autre d'un `await`. Une rafale arrivant dans la **même boucle** franchit donc
le test **avant qu'aucun fil n'ait posé le drapeau**.

`mesuré` par le pilote le 7 septembre 2026, forme de production — une seule
boucle, **aucun entrelacement forcé** —, collection qui pend :

| rafale simultanée | requêtes rendues | **fils distincts lâchés** | drapeau après |
|---|---|---|---|
| 1 | 1/1 en 3,00 s | **1** | posé |
| 8 | 8/8 en 3,00 s | **8** | posé |
| **26** | 26/26 en 3,01 s | **26** | posé |

**Ce qui est vrai et ce qui est faux dans l'affirmation du lot.** Le site, le
journal d'exécution et le **nom du garde** portent tous trois : *« borne la fuite
à un fil, quelle que soit la durée de la panne »*. Le drapeau restant posé après
la rafale, **« quelle que soit la durée » est VRAI** — une seconde rafale ne
lâche rien de plus. **« bornée à UN fil » est FAUX d'un facteur 26**, et
l'auditeur mesure le plafond à **40**, la taille du réservoir anyio, à N=60 comme
à N=200.

**Et le garde ne peut pas rougir sur ce cas.** Il **attend que le drapeau soit
posé** avant de lancer ses autres tâches — « l'entrelacement est forcé, et non
espéré » — donc il *construit* la sérialisation que la production n'a jamais.
C'est un garde vert sous un montage que le défaut ne rencontre pas : **la
troisième occurrence de ce motif sur ce lot**, et la définition même du garde
décoratif.

**Pourquoi le pilote maintient bloquant alors que le code est strictement
meilleur.** Il l'est, mesuré : la scène HTTP de l'auditeur rend **26/26** contre
**0/26** avant, et 2 fils contre 28. Ce qui bloque n'est pas une régression,
c'est que **l'affirmation centrale que ce lot publie sur sa propre couche est
fausse d'un facteur 26 à 40, à trois sites** — dont une **ligne de journal émise
à l'exploitant pendant la rafale même qui la démentit**. La règle du chantier est
que toute phrase du genre « quelle que soit » est soit **bornée**, soit **gardée
par un test** ; celle-ci n'est ni l'une ni l'autre, et le garde censé la tenir en
est structurellement incapable. C'est exactement ce qui a bloqué le lot 2 au
§4.18, et l'affaire est pire ici : là-bas la phrase était fausse dans un
commentaire, ici elle est *dite à l'exploitant comme une preuve*.

**La correction est mesurée et vaut une ligne déplacée** : poser le drapeau **côté
boucle**, garder son retrait **côté fil**. `mesuré` par l'auditeur — rafale de 26,
**26/26 rendues, 1 seul fil**, drapeau correctement retiré après réparation du
store. Et l'objection que le site oppose à cette pose — « tâche annulée avant que
le fil démarre → drapeau posé à jamais » — ne tient pas la comparaison : *le code
actuel atteint DÉJÀ la cécité définitive* dès qu'un fil pend pour de bon.

#### La seconde phrase fausse, indépendante : `daemon`

`src/api/main.py` écrit que le fil de réservoir d'`abandon_on_cancel=True` *« est
démon et ne retient plus l'interpréteur »*. **Faux**, `mesuré` par le pilote le
7 septembre 2026 sur **anyio 4.15.1** : le fil lâché porte
`nom='AnyIO worker thread'`, **`daemon=False`**, et le processus sort en
**`rc=124`** — l'interpréteur est retenu.

**Le lot se contredit lui-même** : `tests/unit/test_garde_modele_embedding.py`
écrit, dans un `finally`, *« le fil de réservoir abandonné — non démon — retient
l'interpréteur »*, et **c'est celui-là qui est juste**. La moitié vraie de
l'affirmation du site est que la **boucle** rend la main, ce qui est la vraie
différence avec `asyncio.to_thread` — le réparateur l'avait déjà corrigée au
pilote au §4.24, et il l'a écrite juste dans le test et fausse dans le code.
Conséquence réelle, nommée par l'auditeur : un `docker stop` sur une API portant
un fil lâché ira au bout de sa grâce puis sera tué.

#### Où le pilote s'écarte de l'auditeur, avec une mesure

L'auditeur rend, en non-bloquant, que la ligne **`M-NB3`** du tableau des
mutations *« décrit une mutation qui rougit »* — il mesure `rc=1` là où le lot
publie `rc=0`. **Le pilote a remesuré, et le chiffre publié n'est pas faux.**

`mesuré` le 7 septembre 2026 : `tests/unit/test_coherence_depot.py` porte **deux**
inventaires, chacun avec sa boucle sur `_fichiers_suivis()`.

| la boucle mutée | l'inventaire qu'elle sert | borne ramenée à `src/`+`tests/` |
|---|---|---|
| la **première** | `all-MiniLM-L6-v2` (N6) | **`rc=2`, 1 rouge** — la mesure de l'auditeur |
| la **seconde** | la prémisse Docker (NB-3) | **`rc=0`, 0 rouge** — le chiffre publié |

**Les deux mesures sont justes ; c'est l'étiquette qui est ambiguë.** « La borne de
l'inventaire » ne dit pas *lequel*, dans un fichier qui en porte deux. Le chiffre
publié décrit bien l'inventaire que NB-3 nomme. **Ce qui doit être corrigé n'est
pas le `rc`, c'est le nom de la mutation** — et c'est la **deuxième** fois sur ce
lot que deux corps différents vivent sous un seul nom : le §4.15 avait déjà dû
rebaptiser `T2-bornes-figées` pour la même raison. *Une étiquette de mutation est
un chiffre : elle a besoin de son site.*

Le fond, lui, n'est pas contesté : l'angle mort est **réel** — `docker-compose.yml`
échappe à l'inventaire de la prémisse, et c'est le fichier dont elle parle.

#### Ce que l'audit étroit a établi en plus, et qui n'était pas demandé

- **le réservoir anyio n'est pas drainé** : `borrowed` monte à 40, `tasks_waiting`
  à 5 pour n=45 — *preuve que la sonde atteint son cas* — puis retombe à **0 à
  l'annulation** alors que les fils tournent toujours, et un offload trivial
  aboutit ensuite ;
- **`n` pannes successives séparées par des réparations lâchent 1 fil EN TOUT**,
  pas un par panne : anyio réemploie le même fil ;
- **le compare-et-échange n'a pas été affaibli par le garde neuf** : 0 violation
  sur **10,1 millions** de lectures, contre **3,0 millions de violations** sur le
  témoin sans compare-et-échange — *sonde prouvée capable dans les deux sens* ;
- **le garde de NB-1 n'est pas contournable** : trois tentatives, dont deux
  variantes qui satisfont le garde en vert et dont l'auditeur a **mesuré qu'elles
  ne portent pas le défaut** ;
- **3,0 s est le bon budget, pour une raison que le site ne dit pas** : le drapeau
  transforme le budget en un coût payé **une fois pour la vie du processus** —
  latences mesurées `[1.00, 0.0, 0.0, 0.0, 0.0, 0.0]` sur six requêtes ;
- **une famine existe dans le sens inverse du sens déclaré**, et elle est
  **préexistante** : drapeau bloqué + collection réellement divergente →
  `/health` publie `unknown` au lieu de `mismatch`, donc `ok` au lieu de
  `degraded`, **la divergence est masquée**. Retourné contre `19f7cec` :
  **identique, ligne pour ligne.** *Cette mesure a évité un faux bloquant*, et
  c'est le geste que le mandat demande.

#### Ce que l'audit dit du cadrage du pilote

**Borner l'audit à la couche async était le bon choix, et l'auditeur le dit avec
une mesure** : le bloquant qu'il trouve est **à quatre lignes** du site que les
deux audits précédents ont corrigé, et il ne l'aurait trouvé ni sans les huit
mutations à reproduire, ni sans la scène de charge retournée contre `19f7cec`.

**Sa réserve est juste et elle est un angle mort du cadrage, pas du lot** : un
audit borné ne regarde pas les mesures publiées hors de son périmètre — et il en
restait une à vérifier, celle-là même sur laquelle le pilote vient de le
départager. *Un périmètre d'audit qui exclut une partie du registre laisse cette
partie sans lecteur indépendant.*
### 4.26 REPAR-6 — la rafale simultanée bornée pour de bon, et deux phrases rendues vraies

Réparation du bloquant **B-2** de l'audit étroit de la couche async (§4.25), des
deux phrases fausses qu'il nomme, et des cinq non-bloquantes. `mesuré` le
**7 septembre 2026**, `anyio 4.15.1`, sur `c8cb37d`.

**Où ce travail a été fait, et il faut le dire d'abord.** Le prompt situait
l'arbre à `.claude/worktrees/embedding-model-validation-e6c6c3`, branche
`claude/embedding-model-validation-e6c6c3`, `c8cb37d`. **La conversation a été
lancée dans un AUTRE arbre au nom ressemblant** :
`.claude/worktrees/audit-async-repar-6-f1e2a1`, branche
`claude/audit-async-repar-6-f1e2a1`, qui pointait sur `86d1433` — c'est-à-dire
sur `main` exactement, sans une seule des six commits du lot. L'arbre visé a été
laissé **intact** (`c8cb37d`, arbre propre, vérifié avant et après), et la
branche de cette conversation a été portée sur `c8cb37d` par `reset --hard` :
elle n'avait aucun commit propre (`main..HEAD` vide), et l'état attendu par le
mandat — *`main` n'est plus ancêtre de ta branche* — est ainsi reproduit.
`main` n'a pas bougé (`86d1433`). *Un arbre au nom ressemblant est une mesure,
pas une évidence.*

#### B-2 refermé — la pose du drapeau passe côté boucle, le retrait reste côté fil

La cause était bien celle qu'énonce le §4.25 : `_sonder` testait
`if nom in _sondes_en_vol` **sur la boucle** et `_executer_sonde` posait le
drapeau **dans le fil**, de part et d'autre d'un `await`.

**La rafale, `mesuré` aux deux bouts, forme de production** — une seule boucle,
`_PLAFOND_SONDES_S` à sa valeur du site (3,0 s), **aucun entrelacement forcé**,
collection qui pend, sonde en lecture seule :

| rafale | avant : rendues / **fils lâchés** | après : rendues / **fils lâchés** |
|---|---|---|
| 1 | 1/1 en 3,00 s / **1** | 1/1 en 3,00 s / **1** |
| 8 | 8/8 en 3,00 s / **8** | 8/8 en 3,00 s / **1** |
| **26** | 26/26 en 3,00 s / **26** | 26/26 en 3,00 s / **1** |
| 60 | — | 60/60 en 3,00 s / **1** |

Le drapeau reste posé après la rafale dans les deux états, et il est **retiré
quand le store rend la main** — `mesuré`, avec une seconde sonde qui lit à
nouveau après réparation. La fuite bornée n'a donc pas été payée d'une cécité.

**L'objection que le site opposait à cette pose est TRAITÉE, et non plus
invoquée.** Elle disait : *tâche annulée avant que le fil démarre → drapeau posé
à jamais*. `_sonder` la referme avec un accusé de démarrage posé par le fil : si
l'offload lève **sans** que le fil ait démarré, la boucle retire le drapeau
elle-même. La sonde qui le garde **atteint son cas et le prouve avant
d'asserter** : le réservoir anyio est ramené à une seule place et cette place est
occupée, donc `tasks_waiting == 1` et le fil ne **peut** pas démarrer.

**Résidu restant, borné et écrit au site** : entre l'ordonnancement du fil et sa
première instruction, une annulation ferait retirer le drapeau par la boucle
alors que le fil va tourner ; une rafale suivante pourrait lâcher un fil de plus.
La panne remplacée est « un fil de trop », pas « aveugle à jamais ».

#### Le garde était décoratif POUR DEUX RAISONS, et la seconde n'avait pas été vue

Le §4.25 nomme la première : il **attendait** que le drapeau soit posé avant de
lancer ses autres tâches, donc il construisait une sérialisation que la
production n'a jamais.

**La seconde est mesurée ici, et elle est indépendante : le garde comptait les
fils par `name`, et TOUS les fils du réservoir anyio portent le même** —
`'AnyIO worker thread'`. Un ensemble de noms vaut donc **1** quand 26 fils
distincts sont passés. `mesuré` en retournant le garde élargi, compte par `name`
rétabli, contre le site d'avant : l'assertion sur les fils **passe** (elle lit 1
pour 26 fils) et c'est `entrees == 1` qui mord, à 26. Les deux aveuglements se
composaient : l'entrelacement forcé faisait qu'aucune rafale n'atteignait
`entrees`, et le comptage par nom faisait que `fils` ne l'aurait pas vue même
sous une rafale. Le garde compte désormais par `ident`.

**La même erreur a été commise dans la première sonde écrite pour ce travail, et
attrapée en la retournant contre le défaut connu** : elle rendait `rc=0` sur un
code que le pilote avait mesuré à 26 fils. *C'est la cinquième fois sur ce
chantier qu'une sonde décorative est démasquée par ce seul geste, et la première
où elle l'est avant d'avoir servi à conclure.*

Le garde est renommé
`…ne_lache_qu_un_fil_meme_en_rafale_simultanee` : la rafale est ce qu'il
regarde, et son ancien nom promettait ce dont il était incapable.

#### Les deux phrases fausses, et leurs sites

**1. « bornée à UN fil, quelle que soit la durée » — fausse d'un facteur 26 sur
la simultanéité.** Elle vivait à trois sites, tous trois reformulés, et la
phrase est désormais **vraie et gardée** : *un fil par sonde et par panne, que
la panne dure et qu'une rafale simultanée la frappe.*

| site | état |
|---|---|
| commentaire de `_sondes_en_vol` | réécrit, avec le tableau de la rafale avant/après |
| **ligne de journal dite à l'exploitant** | réécrite — elle était dite *pendant* la rafale qui la démentait |
| nom du garde | renommé, et le garde rougit désormais sur le défaut |

**2. « le fil de réservoir d'`abandon_on_cancel=True` est démon et ne retient
plus l'interpréteur » — fausse.** `mesuré` sur `anyio 4.15.1` : le fil lâché
porte `nom='AnyIO worker thread'`, **`daemon=False`**, et un processus qui sort
en le laissant bloqué est tué par son échéance — **`rc=124`**, l'interpréteur est
**retenu**.

Le site de `src/api/main.py` dit maintenant ce qui est vrai — **la BOUCLE** rend
la main sans attendre le fil, et c'est là toute la différence avec
`asyncio.to_thread` — puis **nomme la conséquence** au lieu de la taire : *un
`docker stop` sur une API portant un fil lâché n'aboutit pas à la demande ; il
ira au bout de sa grâce, puis le conteneur sera TUÉ. Ce que la primitive achète
est la disponibilité de la route, pas la propreté de l'arrêt.*
`tests/unit/test_garde_modele_embedding.py` l'écrivait déjà juste dans un
`finally` ; le site est désormais d'accord avec lui.

#### Les cinq non-bloquantes

| # | trouvaille | état | garde |
|---|---|---|---|
| 1 | le budget de la route n'est borné par rien sous 5 s | **fermée** | `…le_plafond_ne_depasse_pas_le_budget_d_une_requete_utilisateur` |
| 2 | `tache.cancel()` n'est gardé par rien | **fermée** | `…le_depassement_rend_son_jeton_au_reservoir` |
| 3 | l'absorption est muette dès le passage 2 | **fermée** | `…l_absorption_n_est_pas_muette_au_deuxieme_passage` |
| 4 | la ligne de journal nomme la mauvaise route | **fermée** | idem (deux assertions séparées) |
| 5 | le garde de la fuite tourne à `_CHARGE = 8` | **fermée** | `_CHARGE = 26` |

Sur **1** : les deux gardes existants sont tous deux du côté de `/health` et se
lisent `5 > plafond` ; la direction dangereuse pour `/chat/resume` était libre.
Le garde neuf nomme le second emploi de `_PLAFOND_SONDES_S` — *le temps qu'une
requête utilisateur attend pour une vérification qu'elle n'a pas demandée* — et
il est délibérément séparé, les deux bornes se lisant en sens inverse.

Sur **2** : ce que `tache.cancel()` achète n'est pas le délai mais la
**restitution du jeton de réservoir**. `mesuré`, et le test a d'abord échoué
là-dessus : la restitution **n'est pas synchrone** — `cancel()` demande
l'annulation, délivrée au tour de boucle suivant. Le garde attend donc des tours,
bornés, et vérifie que le fil est **encore bloqué** quand il constate
`borrowed == 0` : c'est bien le jeton qui revient, pas le fil qui meurt.

Sur **3** : la ligne du saut passe de `DEBUG` à **`WARNING`**. Elle dit qu'une
sonde a été sautée parce qu'un store ne rend pas la main — la panne, pas une
trace de mise au point. Son débit est borné par le cadenceur de `/health`, un
tick toutes les 20 s.

Sur **5**, et il faut être exact : **`_CHARGE = 8` détectait le défaut** — 8
requêtes lâchaient 8 fils. Ce que la trouvaille corrige est une **incohérence
avec le chiffre publié**, pas un trou de détection : un garde qui tourne sous une
charge qu'il ne nomme pas laisse croire que le chiffre du registre est celui qui
est tenu.

#### La non-bloquante départagée en faveur du lot : l'étiquette, pas le `rc`

`M-NB3` est **renommée** et porte désormais son site : *la borne de l'inventaire
**de la prémisse Docker**, la SECONDE boucle sur `_fichiers_suivis()`*. Le `rc=0`
publié n'était pas faux ; les deux mesures étaient justes et c'est le nom qui
confondait deux corps. Le détail est écrit au §4.21, sous le tableau de l'angle
mort. Deuxième fois sur ce lot après `T2-bornes-figées` au §4.15.

#### La campagne de mutations

`rc` du **processus**, jamais derrière un tube. Restauration par **empreinte
SHA-256** vérifiée à chaque tour, jamais par un `diff` contre `HEAD`.

| | mutation | site | `rc` | rouges | nom du rouge |
|---|---|---|---|---|---|
| **M-B2** | la pose du drapeau retourne DANS le fil | `main.py` | **1** | 2 | `…ne_lache_qu_un_fil_meme_en_rafale_simultanee` (26 fils, 26 entrées), `…un_fil_qui_ne_demarre_jamais…` |
| **M-FEN** | la boucle ne referme plus la fenêtre « fil jamais démarré » | `main.py` | **1** | 1 | `…un_fil_qui_ne_demarre_jamais_ne_laisse_pas_le_drapeau_pose` |
| **M-BUD** | `_PLAFOND_SONDES_S` porté à 4,9 s | `main.py` | **1** | 1 | `…le_plafond_ne_depasse_pas_le_budget_d_une_requete_utilisateur` |
| **M-JET** | `tache.cancel()` supprimé | `main.py` | **1** | 1 | `…le_depassement_rend_son_jeton_au_reservoir` |
| **M-MUET** | la ligne du saut redevient `DEBUG` | `main.py` | **1** | 1 | `…l_absorption_n_est_pas_muette_au_deuxieme_passage` |
| **M-ROUTE** | la ligne du saut renomme `/health` en dur | `main.py` | **1** | 1 | idem |
| **M-NOM** | le garde compte par `name` au lieu d'`ident` | `test_garde_…py` | **0** | **0** | *le site est corrigé : rien à voir* |
| **M-NOM + M-B2** | le compte par `name`, contre le site d'avant | les deux | **1** | 1 | `entrees == 1` mord à 26 ; **l'assertion sur les fils PASSE** — l'aveuglement du nom, mesuré |
| **T1** | **témoin inerte** — un mot de commentaire réécrit | `main.py` | **0** | **0** | — |

**Un rouge parasite a traversé la première campagne, et il a été gardé au
registre parce qu'il est instructif** : `…le_nom_du_modele_anglais_ne_vit_que_la_ou_il_est_justifie`
rougissait sur **tous** les tours, témoin inerte compris — donc il ne venait pas
des mutations. Cause : la section que vous lisez avait ajouté une **quatrième**
mention du nom du modèle anglais dans un fichier dont l'inventaire est exact.
Le garde a fonctionné comme écrit ; la phrase a été reformulée sans le nom. *Un
rouge présent sur le témoin inerte n'est jamais une mutation.*

#### La porte

`rc` du **processus**, non filtré, jamais derrière un tube ni un `grep`.

| commande | `rc` | résultat |
|---|---|---|
| `make lint` | **0** | mypy 18 fichiers, ruff — tout passe |
| `make test` | **0** | **562 passés** |

Le compte passe de **557** à **562** : cinq gardes neufs. `documentation/tests.md`
est mis à jour aux **trois** sites que son garde relève — titre, note `mesuré`,
et la comparaison AST/`pytest`, remesurée à **532** contre **562**.

#### Ce qui n'est PAS fermé

- **le résidu de la fenêtre de démarrage** — écrit au site, non gardé : le
  reproduire demanderait d'interrompre un fil entre son ordonnancement et sa
  première instruction, et aucune primitive ne le permet de façon déterministe ;
- **le drapeau et le verdict de concordance restent des états de MODULE.** Une
  sonde à plusieurs phases dans un seul processus voit la seconde sauter le
  travail de la première ; toutes les sondes de ce travail ont donc tourné à
  **une phase par processus**. C'est une contrainte de mesure, pas un défaut
  fermé ;
- **la famine du §4.25** — drapeau bloqué + collection divergente → `/health`
  publie `unknown` au lieu de `mismatch` : préexistante, hors du mandat, non
  touchée ;
- **`documentation/tests.md` porte un compte qui redeviendra faux** au prochain
  test ajouté. Il est gardé, donc il rougira ; c'est le dispositif du §4.13 et il
  fonctionne.

### 4.27 → FERMÉ — le lot 3 fusionné, et un garde qui attrape enfin la famille (f) tout seul

**`main` = `c5f9a54`.** L'exigence 1 du contrat est tenue **des deux côtés** : le
producteur refusait de démarrer hors contrat, le lecteur confronte désormais son
réglage à l'estampille de la collection avant chaque recherche dense.

#### Ce que le pilote a mesuré sur le RÉSULTAT de la fusion, le 7 septembre 2026

| | `mesuré` |
|---|---|
| porte, sur la fusion corrigée | `make lint` `rc=0`, `make test` `rc=0`, **562 passés**, compte publié exact |
| **rafale de 26** | **1 fil lâché**, 26/26 rendues en 3,00 s |
| **rafale de 60** | **1 fil lâché**, 60/60 rendues |
| la pose du drapeau **remise côté fil** | **26 fils**, et `make test` rend `rc=2` avec **2 rouges** nommés |
| B-1 | la collection qui pend rend en **3,00 s**, la boucle rend la main |
| NB-1 | les deux lignes inversées rendent `rc=2` et 1 rouge nommé |

**La paire prouve dans les deux sens** : la mutation reproduit le défaut à la
charge exacte que le registre publie, et le garde le voit. C'est la vérification
la plus complète que ce lot ait reçue.

#### LA PORTE ÉTAIT ROUGE SUR LE RÉSULTAT DE LA FUSION — et c'est un GARDE qui l'a trouvé

Verte sur la branche (562), verte sur `main`, **`rc=2` sur la fusion**.
L'inventaire du **modèle anglais** attendait **3** occurrences dans
`axes_amelioration.md` et en trouvait **5**.

> **ET CE PARAGRAPHE-CI A REJOUÉ LE DÉFAUT, UNE CINQUIÈME FOIS.** `mesuré` le
> 8 septembre 2026 par le lot 5, sur `main` = `origin/main` = `4eedb2a`, dans un
> arbre nu monté par le protocole du §2.2 : `make lint` → `rc=0`, mais
> **`make test` → `rc=2`, 1 rouge / 561 passés** — et le rouge est
> `test_le_nom_du_modele_anglais_ne_vit_que_la_ou_il_est_justifie`, à **6**
> occurrences trouvées pour **5** autorisées. La sixième était la ligne
> ci-dessus, qui ÉCRIVAIT le nom du modèle pour raconter que le garde l'avait
> compté. *Le récit du rouge a produit le rouge suivant.* La table du garde n'a
> pas été touchée ; c'est la phrase qui a pris la périphrase que le reste de
> cette section employait déjà trois lignes plus bas.
>
> **Ce que cela dit du garde, et c'est un désaccord argumenté, pas une
> correction.** Cet inventaire compte des OCCURRENCES du nom, quand ce qu'il
> protège sont les INSTRUCTIONS — une affectation `EMBEDDING_MODEL_NAME=`, ou
> une prose qui prescrit. Sous cette forme, toute page qui raconte son
> déclenchement le fait rougir, et le geste appris est « monter le compte », ce
> qui desserre le garde d'un cran à chaque récit. Il a pourtant trouvé quatre
> dérives réelles, dont deux qu'aucune relecture de branche ne pouvait voir :
> **le lot 5 ne le change pas**, parce qu'affaiblir un instrument qui trouve est
> une décision de pilote, pas d'un lot qui passe. La forme proposée est de
> compter les affectations et la prose prescriptive, et de laisser les citations
> libres. **Le pilote tranche.**
>
> **Et la ligne du tableau ci-dessus est démentie sur ce point** : « porte, sur
> la fusion corrigée : `make test` `rc=0`, 562 passés » décrit la fusion du
> lot 3, pas `4eedb2a`. Personne n'a remesuré la porte APRÈS avoir écrit ce
> §4.27 — c'est exactement le §12 : *une porte se mesure sur le commit qu'on
> livre, pas sur celui d'avant.*

**Les deux de plus sont du pilote.** Ses §4.19 et §4.25 citent le nom du modèle
pour décrire les sondes qui ont mesuré le garde — une collection bouchonnée sur ce
modèle, et la table où il s'écarte de son auditeur. Elles n'existaient pas quand
la branche a écrit sa table, et la branche ne les voit pas : **le défaut naissait
de la FUSION, pas du diff.**

C'est la **famille (f) du §4.14 pour la quatrième fois** — et **la première fois
qu'un GARDE la trouve**, au lieu d'un auditeur ou du pilote relisant le résultat
de fusion à la main. *Le lot 3 a construit le garde qui attrape la dérive que le
lot 3 lui-même a causée.* C'est la démonstration que le §4.13 attendait : un
chiffre gardé rougit, un chiffre relu dérive.

`vérifié` avant de toucher au compte : les cinq occurrences sont des
**citations** — une réfutation au §3.2, deux sorties de mesure au §4.4, les deux
descriptions de sonde du pilote — et **aucune n'est une instruction** : pas une
affectation `EMBEDDING_MODEL_NAME=` parmi elles. Compte porté à 5, motif écrit au
site.

#### La résolution du conflit, à la main, et ce qu'une résolution naïve aurait cassé

Un seul bloc, en fin de `axes_amelioration.md`, les deux côtés y ajoutant des
sections. **Concaténer aurait rangé les numéros à l'envers ET laissé DEUX §4.24 de
contenus différents** — celui du pilote et celui de `REPAR-5`, écrit quand `main`
n'allait qu'au §4.23.

Résolu en **entrelaçant par chronologie**, et en renumérotant le §4.24 de la
branche en **§4.23 bis** — après avoir `mesuré` qu'**aucun renvoi ne le
désigne**, ni dans la branche, ni dans `main`, ni dans un autre fichier.
Contrôles : **0 marqueur**, **3 899 lignes conservées sur 3 899 attendues**,
**aucun numéro en doublon**, ordre final `4.19 4.20 4.21 4.22 4.23 4.23bis 4.24
4.25 4.26`.

#### AMENDEMENT au critère de fusion du §4.18 — et le pilote le déclare

Le §4.18 posait : `src/` inchangé → fusion sur vérification du pilote ; `src/`
changé → audit indépendant. Le §4.24 l'avait invoqué en écrivant qu'*« appliquer
son critère quand il arrange et l'oublier quand il coûte une conversation, ce
serait n'avoir pas de critère »*. **`REPAR-6` change `src/`, et le pilote a
fusionné sans septième audit.** Le critère n'est pas contourné, il est **amendé** :

> `src/` changé → audit indépendant, **sauf si le changement a été spécifié ET
> pré-mesuré par l'audit indépendant qui l'a exigé**, et que le pilote le vérifie
> **dans les deux sens**.

C'est exactement le cas : `Conv' 34` n'a pas seulement trouvé B-2, elle a
**nommé la correction** — « poser le drapeau côté boucle, garder le retrait côté
fil » — et **mesuré son effet** — « rafale de 26 → 26/26 rendues, 1 fil ». Le
changement bloquant n'est donc pas de la matière non lue : une conversation
indépendante l'a conçu. Le pilote a reproduit les deux états à la charge publiée.

**Ce qui n'a PAS été audité indépendamment, et reste rouvrable** : l'**accusé de
démarrage** (`demarre`, un `threading.Event`) que `REPAR-6` a ajouté de lui-même
pour traiter — plutôt qu'invoquer — l'objection que son site opposait à la pose
côté boucle ; et les **cinq gardes neufs** des non-bloquantes. Le pilote a mesuré
que le garde de l'accusé rougit sous sa mutation, sans l'éprouver seul. *Nommé
ici pour rester rouvrable, pas fermé.*

#### La trouvaille que `REPAR-6` a faite seul, et elle est fine

Le garde était décoratif pour **deux** raisons, et l'audit n'en avait vu qu'une.
La seconde : **il comptait les fils par `name`, et tous les fils du réservoir
anyio portent le même.** `mesuré` en retournant le garde contre le site d'avant,
comptage par nom rétabli : l'assertion sur les fils **passait en lisant 1 pour 26
fils**. Il compte désormais par `ident`. *La sonde du pilote comptait déjà par
`ident` — par chance, non par méthode, et il le consigne.*

#### Le poste après la fusion

**Sept arbres et sept branches retirés**, aucun répertoire mort, aucune branche
distante hors `main`, rien d'ancré par Compose ni par un bind mount. Garde-fous
**réarmés puis éprouvés sur les deux adresses** : `@aosis.net` → `rc=1` et HEAD
immobile ; **`florian.horellou@gmail.com` → `rc=0`**.

**Une note d'identité, pour qu'elle ne soit pas lue plus tard comme une
anomalie** : le commit `4849bc1` porte `florian.horellou@gmail.com` en auteur et
en committer, là où les autres commits du chantier portent
`florian_horellou@laposte.net`. **Les deux sont autorisées**, et `gmail` est
largement présente dans l'historique antérieur — 152 occurrences sur les 184
commits mesurés au §4 du mandat. La configuration partagée est intacte sur
`laposte.net`, aucun `config.worktree` n'existe, et le garde-fou a laissé passer
**à juste titre**. *Une identité se vérifie sur l'adresse, jamais sur la
constance.*

### 4.28 `main` était ROUGE et poussé — l'erreur du pilote, et le récit qui rejouait le défaut

**`mesuré` le 8 septembre 2026 par le lot 5, reproduit par le pilote** : à
`main` = `origin/main` = `4eedb2a`, dans un arbre de travail détaché monté par le
protocole du §2.2 — `make lint` `rc=0`, mais **`make test` `rc=2`**, un seul rouge,
`test_le_nom_du_modele_anglais_ne_vit_que_la_ou_il_est_justifie` : **6**
occurrences pour **5** autorisées.

**La sixième était la phrase du §4.27 qui RACONTE que ce garde avait rougi sur la
fusion du lot 3.** *Le récit du rouge a produit le rouge suivant.* Famille (f)
pour la **cinquième** fois, et **seconde fois qu'un garde la trouve** — cette
fois sur le travail du pilote.

#### L'erreur est du pilote, et elle a deux moitiés, toutes deux consignées au mandat

1. **il a corrigé le compte de 3 à 5 en mesurant le fichier AVANT d'y ajouter le
   §4.27**, puis a ajouté la section — qui nomme le modèle — et a poussé **sans
   remesurer la porte sur `main`** ;
2. **il a publié « `rc=0`, `rc=0`, 562 verts » comme état de `main` dans le prompt
   du lot 5**, alors qu'il l'avait mesuré sur `c5f9a54`, **deux commits plus
   tôt**. Le mandat dit vingt fois *« mesure l'état du poste au lieu de le lire »*
   et ajoute qu'**un prompt est le dernier endroit où placer une affirmation non
   mesurée, parce qu'il est lu par quelqu'un qui n'a pas de raison d'en douter.**
   Le lot 5 en a douté, l'a mesuré, et a renversé le pilote — c'est exactement ce
   que le mandat lui demande.

**Et une précision que le pilote doit à l'honnêteté** : sa première mesure
annonçait **deux** rouges. Le second était un **artefact de son harnais** — il
avait monté l'arbre par `git archive`, donc hors d'un dépôt git, et
`_fichiers_suivis()` sortait en 128 sur `git ls-files`. Refait dans un vrai arbre
détaché : **un seul rouge**, exactement ce que le lot 5 rapportait. *Un harnais de
mesure peut muter ce qu'il observe*, et cette fois il a cassé un test sain.

**Corrigé** par la périphrase que le lot 5 a choisie et que le reste de la section
employait déjà — « l'inventaire du **modèle anglais** » — identique à la sienne
pour que la fusion soit triviale. `mesuré` : `main` = `d4b7219`, `make lint`
`rc=0`, `make test` `rc=0`, **562 passés**, poussé.

#### LA DÉCISION DU PILOTE sur la forme de cet inventaire

Le lot 5 rend un désaccord argumenté et **refuse de trancher lui-même** : cet
inventaire compte des **occurrences** du nom quand ce qu'il protège sont les
**instructions**. Sous cette forme, *toute page qui raconte son déclenchement le
fait rougir, et le geste appris est « monter le compte » — ce qui desserre le
garde d'un cran à chaque récit.* Il ne l'a pas changé, au motif qu'il a trouvé
quatre dérives réelles et qu'**affaiblir un instrument qui trouve est une décision
de pilote**. Il a raison sur les deux points, et le pilote a la preuve en main :
**il a fait rougir ce garde deux fois, et une de ses deux corrections était
précisément « monter le compte ».**

**Tranché — et ce n'est ni « garder » ni « remplacer », c'est dédoubler :**

| | ce que ça devient |
|---|---|
| l'inventaire d'**occurrences** | **conservé tel quel**, comme *fil de détente de dérive documentaire*. C'est le rôle qu'il joue réellement, et il l'a joué cinq fois. On ne retire pas un instrument qui trouve |
| un garde **neuf et plus étroit**, sur les **affectations** | `EMBEDDING_MODEL_NAME=…`, `embedding_model_name = "…"` et leurs formes : **c'est l'affectation qu'on peut copier**, jamais la mention. C'est lui qui porte la sûreté, et il n'a aucune raison de rougir sur un récit |
| la **règle de maintenance**, écrite au site | **on corrige par PÉRIPHRASE, on ne monte pas le compte.** Monter le compte est le geste qui desserre ; la périphrase est le geste qui tient. Les deux corrections de ce chantier ont convergé vers la périphrase — *une fois par hasard, une fois par choix* |

Le motif de ne pas simplement remplacer : un inventaire d'occurrences est un
**détecteur de dérive**, pas un garde de sûreté, et ce chantier a besoin des deux.
Les confondre est ce qui a rendu le geste de correction ambigu. **Ce dédoublement
part au lot suivant** ; il n'est pas du ressort du lot 5, qui l'a signalé sans y
toucher — et c'était le bon geste.

#### Les deux fautes que le lot 5 a déclarées, vérifiées par le pilote

Le lot déclare avoir laissé passer **une attribution d'assistant** en pied de
message, puis avoir amendé **avec `--no-verify`** — les deux interdites — avant de
refaire l'amendement en laissant le hook tirer. `vérifié par le pilote` le
8 septembre 2026 sur les deux commits de sa branche : **0 attribution** dans les
messages, **0** dans les lignes ajoutées, auteur **et** committer sur
`florian_horellou@laposte.net`, aucune adresse hors des deux autorisées.
**L'historique est propre.**

*Ce qui vaut d'être retenu est la déclaration.* Un `--no-verify` réparé et déclaré
coûte une ligne de registre ; un `--no-verify` réparé et taxé aurait coûté la
confiance dans tout le rapport. C'est la troisième fois de ce chantier qu'une
conversation ouvre son rapport par sa propre faute, et la troisième fois que la
mesure du pilote confirme qu'elle était sans dégât.

### 4.29 → FERMÉ — les deux trappes, et l'inventaire dédoublé

**Lot LOT-DETTE, livré le 8 septembre 2026.** Branche
`claude/trappes-ouvertes-dette-ec749d`, arbre de travail
`.claude/worktrees/trappes-ouvertes-dette-ec749d`, montée depuis `main` =
`origin/main` = **`c5028d6`**, avance 0 — **pas** le clone principal. Porte de
référence remesurée sur ce commit avant tout travail, `rc` du processus non
filtré : `make lint` → `rc=0`, `make test` → `rc=0`, **603 passés**. *Le chiffre
que le cadrage annonçait était juste, et il a été remesuré parce qu'un chiffre
recopié n'est pas une mesure.*

#### N1 — le contrat « 2 = store injoignable » était faux, et gardé par rien

`scripts/verifier_les_ancrages.py` sortait en **1** quand NebulaGraph ne
répondait pas, là où quatre sites promettent **2** : son docstring, la cible
`verifier-les-ancrages` du `Makefile`, le compte rendu de campagne, et
`documentation/tests.md`. Le mécanisme tient à un lien d'héritage :
`SessionPool.init()` de `nebula3` ne rend pas `False` sur un serveur muet, il
**lève** un `RuntimeError` nu ; `StoreInjoignableError` **hérite** de
`RuntimeError` ; et un `except` ne voit jamais le PARENT de ce qu'il nomme.

**La preuve d'atteinte, et c'est la moitié du travail.** ChromaDB joignable
(`172.20.0.8`), NebulaGraph sur `192.0.2.1` — TEST-NET-1, non routable :

| | avant | après |
|---|---|---|
| `rc` du processus | **1** | **2** |
| sortie | trace Python non absorbée, `RuntimeError: The services status exception: [services: ('192.0.2.1', 9669), status: BAD]` | `RIEN N'EST PROUVÉ — NebulaGraph 192.0.2.1:9669 / rag_space : …` |
| les deux stores en service | `rc=0`, 130/130 et 44/44 | `rc=0`, 130/130 et 44/44 — **inchangé** |

**Et la fausse sonde est reproduite, parce qu'elle est l'enseignement.** Sans
`.env`, `--chroma-host` vaut `chromadb`, qui ne résout pas : le script échoue sur
ChromaDB **avant** d'atteindre NebulaGraph et rend `rc=2` — le chiffre attendu,
pour la mauvaise raison. *Un `rc` juste n'est pas une preuve d'atteinte.* Les six
tests de `TestUnStoreInjoignableSortEnDeux` portent donc chacun un **témoin
d'atteinte** : `lire_chroma` bouchonné inscrit son passage, et le test refuse de
conclure si ce passage n'a pas eu lieu.

**Deux trouvailles adjacentes, par mutation.** *(a)* Une mutation qui a manqué sa
cible a montré que l'absorption large de `lire_chroma` n'était **gardée par rien
non plus** : la rétrécir laissait les 19 tests verts. Le contrat dit « les
stores », au pluriel ; les deux côtés sont désormais gardés. *(b)* La mutation M3
a montré qu'élargir la seule absorption de la CONNEXION laissait `pool.execute`
lever à travers `main()` — un graphe qui meurt **en cours de lecture** rendait
encore 1. Absorbé et gardé.

#### N2 — la chauffe de l'index BM25 : la décision est « chauffer PUIS refuser »

L'index lexical est **paresseux** : `/health` annonce `index_lexical: false` après
un redémarrage, et la première recherche le construit synchroniquement. La
campagne du 8 septembre 2026 a chauffé **à la main** et son compte rendu le
raconte ; il n'y en avait aucune trace dans le code — ni `evaluate.py`, ni
`Makefile`, ni test.

**Les deux voies du cadrage sont refusées séparément et retenues ensemble.**
*Chauffer seul* n'est pas fail-closed : `retriever._lexical_search` absorbe
largement et sert la recherche dense seule, donc une chauffe qui échoue ne dit
rien. *Refuser seul* est fail-closed et **inutilisable** : sur une pile fraîche
`index_lexical` est TOUJOURS faux, et un refus sec renverrait l'exploitant à la
requête manuelle — c'est-à-dire à sa mémoire, ce que ce chantier passe son temps
à retirer du chemin critique. On chauffe (`POST /search`, pas `/answer` : la
recherche suffit, une génération coûterait un LLM pour un résultat jeté), on
vérifie `/health`, et on **refuse en 2** si la vérification ne passe pas. Le
refus ne tombe donc que sur une vraie panne.

**ET DANS `evaluate.py`, PAS DANS LE `Makefile` — le `Makefile` n'est pas
touché.** Deux cibles de campagne (`eval`, `eval-controle`) feraient deux sites
qui divergent, la divergence même que `test_coherence_depot.py` existe pour
empêcher ; la documentation invoque le script directement, ce qu'une recette ne
protège pas ; et le code de sortie appartient au programme qui porte le contrat.
Gardé par `test_la_chauffe_n_est_pas_ecrite_dans_le_makefile`.

`mesuré` contre l'agent en service, port **8011** : index déjà chaud →
`deja_chaud` en **0,1 s**, **aucune** requête de chauffe payée. Contre le port
8000, où rien n'écoute → `refus: /health illisible — [Errno 111] Connection
refused`. Le chemin FROID est éprouvé par un agent bouchonné qui reproduit la
paresse ; il **n'est pas mesuré en vrai**, et c'est écrit plus bas.

#### Le dédoublement de l'inventaire, et il a trouvé du premier coup

La décision du §4.28 est exécutée. L'inventaire d'occurrences du **modèle
anglais** — l'autre candidat d'embedding, dont le nom vit à son site canonique,
la table `_VESTIGES_AUTORISES` — **reste tel quel**, et son docstring dit ce qu'il
EST : *un fil de détente de dérive documentaire, pas un garde de sûreté*. La
**règle de maintenance est écrite au site** : on corrige par **PÉRIPHRASE**, on
ne monte pas le compte — monter le compte desserre le fil d'un cran à chaque
récit, et le pilote l'avait fait.

Un garde neuf porte la sûreté :
`test_aucune_affectation_du_modele_anglais_ne_vit_dans_le_depot`. Il ne voit que
les formes **copiables** — `NOM=valeur`, `NOM: valeur` (YAML), `NOM: str =
"valeur"` (pydantic), `"NOM": "valeur"` (JSON), `SentenceTransformer("valeur")` —
et les noms de réglage sont **dérivés de `settings.py`** (champ + alias) plutôt
que recopiés, pour qu'un renommage emporte le garde avec lui.

**ET IL A ATTRAPÉ LA PREMIÈRE RÉDACTION DE CETTE SECTION-CI.** Les deux lignes
ci-dessus écrivaient l'affectation en clair pour la raconter ; le garde neuf a
rougi, et le fil d'occurrences aussi. C'est *exactement* le mécanisme que le
§4.28 décrit — « toute page qui raconte son déclenchement le fait rougir » — et
la correction a été celle que la règle prescrit : la **périphrase**, pas le
compte monté. La première fois que la règle a été éprouvée, c'est sur le texte
qui l'énonce. Les délimiteurs
admis sont `"` et `'`, **jamais l'accent grave** : une paire d'accents graves est
de la mise en page Markdown, et l'admettre ferait rougir un récit.

**PÉRIMÈTRE MESURÉ** : `_fichiers_suivis()`, partagé avec l'inventaire, donc
identique par construction — **123** fichiers suivis le 8 septembre 2026, dont
**123** lisibles, aucun angle mort. Gardé par
`test_le_garde_balaie_au_moins_le_perimetre_de_l_inventaire`.

**IL A TROUVÉ UNE AFFECTATION SUR `main`.**
`documentation/llm_integration_plan.md`, dans un bloc `.env` : la clé
`EMBEDDING_MODEL_NAME` affectée au nom du modèle anglais, suivie du commentaire
« DOIT etre le meme que l'ingestion » — la « ligne d'apparence exécutable » que
la trouvaille d'origine nommait, dans le
fichier dont le bandeau de tête l'appelle son écart le plus dangereux, et **que
l'inventaire d'occurrences tolérait puisqu'il compte**. Corrigée par périphrase ;
le compte de ce fichier **descend** de 7 à 6, et la table est corrigée — c'est le
geste que son propre docstring prévoit pour un compte qui descend.

**Éprouvé dans les deux directions, sur des fichiers suivis réels :**

| la mutation | le fil d'occurrences | le garde d'affectations |
|---|---|---|
| la clé `EMBEDDING_MODEL_NAME` affectée au modèle anglais, plantée dans `.env.example` | **ROUGE** | **ROUGE** |
| un RÉCIT nommant le modèle planté dans `README.md` | **ROUGE** | **VERT** |
| témoin inerte : le même récit avec le modèle EN SERVICE | vert | vert |

*La deuxième ligne est la décisive : sans elle, on aurait reconstruit
l'inventaire d'occurrences sous un autre nom.* Les quatorze récits réels du dépôt
sont éprouvés un par un dans
`TestLeGardeDesAffectationsEstEprouveDansLesDeuxDirections`.

**Le modèle d'embedding est inchangé des deux côtés**, mesuré avant et après :
estampille de `rag_documents` = `paraphrase-multilingual-MiniLM-L12-v2`, défaut
de `settings.embedding_model_name` = idem.

#### N3 à N8

- **N3, attribution corrigée.** `mesuré` : sous la mutation « remettre `--compare
  runs/final.json` », `test_les_cibles_d_evaluation_ne_nomment_que_des_fichiers_qui_existent`
  **passe** — `runs/final.json` existe toujours — et seul son voisin
  `..._make_eval_ne_vise_plus_aucun_jeu_ni_aucune_cible_retires_par_le_lot_5`
  rougit. Le tableau du §4.3 nommait un garde décoratif *pour cette mutation-là* ;
  il porte désormais la mutation que ce garde voit vraiment, et le récit de
  l'erreur ;
- **N4, tranché : l'assertion de sous-chaîne s'en va.** `mesuré` en plantant un
  `trouves.add(...)` légitime dans la sonde : **deux** tests rougissaient,
  l'arbre syntaxique ET la recherche de sous-chaîne `.add(` — c'est-à-dire la
  forme que le docstring de ce garde déclare fausse, revenue trois lignes plus
  bas. Elle est **strictement redondante** : l'arbre syntaxique rougit déjà sur
  `['add']`, mesuré. Retirée ; il reste **un** rouge, et `documentation/tests.md`
  dit maintenant cela ;
- **N5, le pragma est parti.** `empreinte()` préfixe `sha256:`, ce qui disqualifie
  la chaîne aux yeux de `detect-secrets` sans rien annoter. `mesuré`,
  `detect-secrets-hook` v1.5.0, même valeur sous trois formes : nue → `rc=1`, une
  détection ; annotée → `rc=0` ; **préfixée → `rc=0` sans pragma**. Trois pièces
  supprimées pour six caractères — le pragma, le post-traitement
  `poser_le_pragma()` que `yaml.safe_dump` rendait nécessaire, et son garde. La
  fixture est **régénérée depuis la source du pipeline** (lue, jamais écrite) :
  **une seule ligne a bougé**, et les 44 ancrages sont identiques bit pour bit —
  vérifié par empreinte de leur ensemble contre `c5028d6` ;
- **N6, le 15 196 a sa commande.** `SHOW STATS` ne le rend pas — `mesuré` :
  « There is no any stats info to show, please execute `submit job stats'
  firstly! », et `SUBMIT JOB STATS` **écrit**. Compter par étiquette est hors de
  portée aussi : `SHOW TAG INDEXES` ne rend **qu'un** index, `doc_index` sur
  `Document.filename`, et les onze autres étiquettes refusent le `LOOKUP`. La
  route de l'auditeur est donc la seule rejouable en lecture seule, et elle est
  publiée : 23 racines + **15 173** descendants distincts = **15 196**, remesuré.
  **Ses deux réserves sont écrites** : un sommet orphelin échapperait aux deux
  requêtes (non établissable en lecture seule), et la somme suppose une FORÊT —
  celle-là est mesurée, la même traversée sans `DISTINCT` rend 15 173 elle aussi ;
- **N7, la graine est transmise, et ce qu'elle ne rattrape pas est écrit.**
  `mesuré` sur `ollama-central` / `gemma4:e4b` : sans graine, deux appels
  identiques rendent **deux textes différents** ; avec `seed: 42`, le **même** ;
  avec `seed: 43`, un autre — la graine mord. Transmise, le motif de rejet
  devient déterministe et la reproductibilité passe de « en pratique » à « par
  construction ». **Trois réserves au docstring** : relative au serveur (modèle,
  version, backend) ; le jeu **versionné n'a pas été produit avec elle**, donc
  `--seed 42` rendra un jeu DIFFÉRENT de celui du dépôt — c'est pourquoi ce lot
  n'a pas régénéré le jeu ; et elle ne rend pas deux corpus comparables, ce qui
  est le travail de l'empreinte d'ancrages. Gardée par
  `test_la_graine_est_transmise_au_generateur_de_texte`, qui vérifie par arbre
  syntaxique que la graine atteint `options` et n'y est pas une constante figée ;
- **N8, les deux chiffres.** `golden_qa.json` portait **13** questions à réponse
  sur 15 — les deux autres, `Q-010` et `Q-011`, sont des abstentions — `mesuré`
  sur le contenu du fichier tel que `4eedb2a` le portait ; six sites corrigés. Et
  le « 50 → 0,962 » du `README.md` est **daté** : `git log -S` le place au
  **3 août 2026**, un mois avant le remplacement du corpus du 2 septembre. Le
  `README.md` renvoie désormais à son site canonique au lieu de le recopier, et
  **ce site porte enfin sa date** — sans quoi la dette n'aurait été que déplacée.

#### Une trouvaille du lot sur lui-même

La première forme du garde d'affectations écrivait
`EMBEDDING_MODEL_NAME=paraphrase-multilingual-MiniLM-L12-v2` en littéral dans un
test. `mesuré` : le dépôt passait de **2** à **3** détections `detect-secrets`
(« Base64 High Entropy String ») — c'est-à-dire qu'un garde de ce lot rendait
`detect-secrets` moins armable au moment même où le lot retirait un pragma pour
le rendre plus armable. Corrigé en **dérivant** la valeur de `settings.py` au lieu
de l'écrire : retour à **2**, les deux mêmes que `c5028d6`, dans des fichiers que
ce lot n'a pas touchés.

#### CE QUE CE LOT N'A PAS FERMÉ

- **le hook `pre-push`** — hors cadrage par décision : il change le geste de
  publication et mérite sa propre mesure. Le garde-fou d'identité couvre
  `commit`, `--amend`, `--author=`, `merge --no-ff` et `merge --squash`, **pas
  `push`**, et le dépôt pousse ;
- **le chemin FROID de la chauffe n'est pas mesuré en vrai.** Il l'est contre un
  agent bouchonné qui reproduit la paresse. Le mesurer en vrai demanderait de
  redémarrer `rag-agent-api`, un service en fonctionnement que ce lot n'a pas
  l'autorisation d'arrêter. *La sonde live prouve le chemin CHAUD et le chemin du
  REFUS ; le chemin froid est prouvé hors réseau* ;
- **deux détections `detect-secrets` préexistantes** :
  `documentation/capture_usage.md:402` et `tests/unit/test_context_assembly.py:95`,
  toutes deux « Hex High Entropy String ». Elles sont sur `c5028d6` comme sur
  cette branche, dans des fichiers que ce lot n'a pas touchés. Le préfixe
  `sha256:` de N5 est la technique qui les fermerait ; `detect-secrets` n'est
  **pas armé** dans `.pre-commit-config.yaml`, et l'y armer demande sa propre
  mesure sur `runs/`, `prompts/` et `tests/fixtures/` — décision déjà écrite
  dans ce fichier ;
- **une affectation `RERANK_MODEL=<le reranker anglais>` dans le même bloc `.env`
  de `documentation/llm_integration_plan.md`.** C'est une affectation copiable
  d'un reranker **anglais**, et le site canonique de `rerank_model` dit qu'un
  reranker anglais « défait le travail de l'embedder » — mesuré, étendue 0,0 % sur
  20 candidats. Le garde neuf ne la voit pas : il vise le modèle d'EMBEDDING, qui
  est le périmètre de la décision du §4.28. *Trouvé en passant, non fermé, et non
  gardé* ;
- **la reproductibilité du jeu versionné.** La graine transmise ne s'applique
  qu'aux générations futures. Régénérer le jeu pour qu'il devienne reproductible
  par construction casserait l'appariement de `runs/2026-09-08-reference.json`,
  et c'est un lot en soi.

### 4.30 → FERMÉ — le lot 5 fusionné : la mesure de qualité du dépôt est vivante, et en deux instruments

**`main` = `744c2c8`.** La seule mesure de qualité du dépôt était morte — son jeu
doré désignait un corpus remplacé, **129 ancrages dont zéro existaient**. Elle
vit à nouveau, et **en deux instruments qui ne mesurent pas la même chose** : un
jeu de 138 questions régénéré sur le corpus actuel, et les 30 questions du
pipeline **transposées**, site canonique resté chez lui, empreinte de la source
gravée.

Livré (`Conv' 36`), audité (`Conv' 37`) : **zéro bloquante**, huit non bloquantes,
recommandation de fusionner. *Le pilote a vérifié avant de la suivre, parce
qu'accepter un « fusionner » sur parole est la direction risquée.*

#### Ce que le pilote a mesuré de ses mains, le 8 septembre 2026

| | `mesuré` |
|---|---|
| porte sur le lot | `make lint` `rc=0`, `make test` `rc=0`, **603 passés** |
| porte sur **le résultat de la fusion** | `rc=0`, `rc=0`, **603 passés** ; inventaires intacts (5 et 1), compte publié exact |
| **N1**, la seule trouvaille qui touche du code | `rc=1` là où le contrat promet **2**, avec **preuve d'atteinte** |
| conflit de fusion | aucun |

**N1, et pourquoi la cotation non bloquante est juste.** `StoreInjoignableError`
**hérite** de `RuntimeError`, et `SessionPool.init()` **lève** un `RuntimeError`
nu au lieu de rendre `False` : l'exception échappe donc à son propre gestionnaire,
et Python sort en **1**. Le contrat « 2 = store injoignable » est écrit à quatre
sites. `mesuré` par le pilote, ChromaDB joignable et Nebula bidon —
`RuntimeError: The services status exception`, trace non absorbée, `rc=1`. **La
propriété de sûreté tient** : jamais de faux vert, `make eval` s'arrête, et une
trace Python ne se lit pas comme « jeu périmé ».

**Et la sonde du pilote n'a pas atteint son cas au premier essai** : son arbre
n'ayant pas de `.env`, le script échouait sur **ChromaDB** avant d'arriver à
Nebula, et rendait `rc=2` — le chiffre attendu, pour la mauvaise raison. Refaite
avec un ChromaDB joignable, elle nomme NebulaGraph dans son échec. *Un `rc` juste
n'est pas une preuve d'atteinte.*

#### Ce que l'audit a établi, et qui vaut d'être gardé

- **les ancrages existent, et la sonde sait dire non** : **130/130** au graphe *et*
  dans ChromaDB pour le jeu neuf, **0/129** pour l'ancien. L'auditeur a en plus
  **prouvé l'atteinte du cas asymétrique** avec un identifiant présent au graphe et
  absent de l'index : `rc=1`, « ABSENT DE CHROMADB » nommé. L'asymétrie vaut un
  facteur 4 — **15 196** sommets contre **3 750** `element_id`, reconstruits
  indépendamment ;
- **l'auto-référentialité est réfutée plus fort que le lot ne l'écrivait** : les
  21,7 points d'écart brut tombent à **4,5** sur les seules questions à ancrage
  unique — 11/12 contre 125/130, **une question** — et l'auditeur ajoute un
  **Fisher exact à p = 0,417**. Le résidu n'est pas distinguable du bruit ;
- **le déterminisme est plus précis que « la troisième décimale »** : les neuf
  métriques de recherche se rejouent **bit pour bit**, et
  `citations_par_reponse` rend une **troisième** valeur distincte (3,8 / 3,5 /
  3,233) — la non-détermination est dans l'étage de génération, et elle est
  bornée là ;
- **l'empreinte des ancrages ferme un piège réel** : les deux corpus portent
  **exactement les mêmes 138 identifiants**, donc un jeu périmé rend 0 % (visible)
  mais deux corpus sous une même numérotation rendent des chiffres **plausibles**.
  L'auditeur a prouvé que la **première** forme était décorative sur le cas visé —
  `sha256:584a64…` **bit pour bit identique** pour les deux corpus — et que la
  seconde les sépare, laisse passer une reformulation, et voit un ré-ancrage ;
- **le chemin de code est celui déclaré, prouvé par les données** :
  `dense_ms`, `lexical_ms`, `translation_ms` et `rerank_ms` sont **tous > 0 sur les
  168 questions**, question 1 comprise — donc l'index BM25 était chaud ;
- **la strate `de_suivi` s'explique par le mécanisme que le pipeline avait nommé**,
  et l'auditeur l'a **vu s'allumer** : `rewrite_ms > 0` sur exactement `q25`–`q28`
  et sur **aucune** des 138 autres.

#### Les huit non bloquantes, et où elles vont

| | Ce que c'est | Suite |
|---|---|---|
| **N1** | `rc=1` au lieu de `2` quand NebulaGraph est injoignable, contrat écrit à quatre sites, **aucun test sur ce chemin** | ✅ **FERMÉE par LOT-DETTE** (§4.29) — `rc=2`, avec preuve d'atteinte live, et six tests là où il n'y en avait aucun. Deux trouvailles adjacentes par mutation : `lire_chroma` et `pool.execute` |
| **N2** | le réchauffement de l'index BM25 est **raconté, ni fait ni gardé** : aucune chauffe dans `evaluate.py`, aucune dans le `Makefile`, aucun test. `make eval` sur une pile fraîche fera passer la question 1 par un index froid — *la trappe même que le lot a identifiée reste ouverte pour la campagne suivante* | ✅ **FERMÉE par LOT-DETTE** (§4.29) — **chauffer PUIS refuser**, dans `evaluate.py` et non dans le `Makefile`, motifs au site. Le chemin froid est éprouvé hors réseau, pas en vrai |
| **N3** | une mutation du tableau est **attribuée au mauvais garde** : elle est bien attrapée, mais par le voisin. Le tableau nomme un garde décoratif *pour cette mutation-là* | ✅ **FERMÉE par LOT-DETTE** (§4.29) — attribution corrigée, et mesurée : le garde attribué **passe** sous cette mutation, le voisin rougit seul |
| **N4** | `documentation/tests.md` **affirme une chose fausse** : un `set.add` légitime fait rougir **deux** assertions, alors que la page écrit le contraire. Et la recherche de sous-chaîne que le lot qualifie de « première forme fausse » est **revenue** comme troisième assertion. *Un successeur qui croit la page posera un `set.add`, verra un rouge inexplicable, et sera tenté d'affaiblir le garde* | ✅ **FERMÉE par LOT-DETTE** (§4.29) — tranché : l'assertion de sous-chaîne s'en va, mesurée strictement redondante. Il reste **un** rouge, et la page le dit |
| **N5** | le lot pose un `pragma: allowlist secret` sur `source_sha256` là où sa **propre** technique — préfixer `sha256:` — l'évitait. Deux hachages, deux traitements | ✅ **FERMÉE par LOT-DETTE** (§4.29) — `sha256:` préfixé, `rc=0` sans pragma. Trois pièces supprimées ; les 44 ancrages identiques bit pour bit |
| **N6** | le **15 196** est publié sans sa commande, seul chiffre du compte rendu dans ce cas. L'auditeur l'a reconstruit et il est exact, mais un lecteur ne peut pas le rejouer | ✅ **FERMÉE par LOT-DETTE** (§4.29) — la route publiée, remesurée, **avec ses deux réserves** dont une mesurée |
| **N7** | la reproductibilité des ancrages **n'est pas ce que la documentation laisse entendre** : la graine fixe le tirage, mais l'ensemble retenu dépend du motif d'acceptation du LLM. **Reproductible en pratique, pas par construction** — et le texte des questions ne l'est pas du tout, `temperature: 0.4` sans `seed` | ✅ **FERMÉE par LOT-DETTE** (§4.29) — graine transmise (mesurée déterminante), et trois réserves écrites, dont : le jeu versionné n'est PAS reproductible par cette route |
| **N8** | deux inexactitudes chiffrées : `golden_qa.json` est décrit « 15 questions à réponse », c'est **13 sur 15** ; et `README.md` garde un « 50 → 0,962 » hérité du corpus remplacé | ✅ **FERMÉE par LOT-DETTE** (§4.29) — 13/15 sur six sites ; et le balayage daté au **3 août 2026**, son site canonique portant enfin sa date |

#### Trois chiffres de cadrage du pilote, corrigés par l'audit

**Le §4.29 n'existe pas** — le compte rendu du lot vit au **§4.3**, marqué
`→ FERMÉ par le lot 5`. **Le diff brut est 13 761 / 3 241**, et non 3 161 : ce
dernier était le chiffre du *résultat de fusion*, que le pilote a cité comme
diffstat de branche. **Et la batterie compte dix mutations, pas neuf.** Trois
erreurs dans un seul prompt, toutes du même genre : *un chiffre recopié d'un
contexte dans un autre.*

**Et une quatrième, sur le commit de fusion lui-même** : la première rédaction de
son message portait des accents graves dans un argument entre guillemets doubles,
et `bash` les a interprétés comme une **substitution de commande** — le nom du
fichier a disparu du message, remplacé par du vide. Amendé par heredoc, comme
partout ailleurs dans ce chantier. *Un message de commit est un artefact
mesurable : il se relit après écriture.*

#### Le poste après la fusion

Trois arbres et trois branches retirés, aucun répertoire mort, un seul arbre
restant — celui du pilote. Garde-fous **réarmés puis éprouvés** : `@aosis.net` →
`rc=1` et HEAD immobile, adresse autorisée → `rc=0`.

---

### 4.31 → FERMÉ — le lot dette fusionné, et deux maillons du raisonnement du pilote renversés par la mesure

**`main` = `6c85404`.** Les deux trappes de l'audit du lot 5 sont fermées, les six
autres non bloquantes avec elles, et la décision du §4.28 est exécutée. Livré
(`Conv' 38`), audité (`Conv' 39`) : **zéro bloquante**, cinq non bloquantes,
recommandation de fusionner.

#### Ce que le pilote a mesuré de ses mains, le 8 septembre 2026

| | `mesuré` |
|---|---|
| porte, sur le lot **et** sur le résultat de la fusion | `make lint` `rc=0`, `make test` `rc=0`, **629 passés**, les trois inventaires intacts |
| **N1** | **`rc=2`** là où c'était `1`, **zéro trace**, message nommant NebulaGraph — **preuve d'atteinte** |
| **dédoublement**, affectation plantée dans `.env.example` | fil d'occurrences **rouge**, garde d'affectations **rouge** |
| **dédoublement**, **récit** planté dans `README.md` | fil **rouge**, garde d'affectations **VERT** |
| `src/agent/settings.py` | **commentaire seul** — AST hors docstrings **identique** à `main` |

#### L'AUDIT A RENVERSÉ DEUX MAILLONS DU RAISONNEMENT DU PILOTE, AVEC DES MESURES

Le pilote avait écrit, dans le prompt d'audit, qu'un reranker anglais rend un
**« classement au hasard »** et que la ligne `RERANK_MODEL` restée en clair était
devenue **« la plus dangereuse des deux »**. **Les deux sont faux.**

**Le premier, parce que l'étendue plate est une SATURATION DU SIGMOÏDE et non une
perte d'ordre.** `vérifié par le pilote` le 8 septembre 2026 :
`src/agent/retriever.py:775` fait `chunk.relevance = _sigmoid(score)`, et des
logits de −6,8 à −11,35 s'écrasent à **0,11 % d'étendue en préservant strictement
l'ordre**. L'auditeur a mesuré le coût réel — **−2,5 points de rappel@10** sur les
**41 questions translingues sur 138** du jeu de référence, soit 30 % — contre un
témoin de **hasard pur** qui est **5× pire en rang** et **14× pire en perte**.

**Le second, parce que la ligne d'embedding était pire**, elle produisait des
passages *plausibles et faux*, et elle est aujourd'hui **et gardée en 503 et
périphrasée**. *Ce qui reste vrai et suffit* : c'est la seule des deux qui ne soit
gardée par **rien** et dont le mal soit **silencieux**.

**Le pilote avait nommé le risque lui-même dans ce même prompt** — *« un
raisonnement juste sur un antécédent non mesuré se relit comme une preuve »* — et
il l'a commis dans la phrase suivante. **L'antécédent était dans le dépôt**, au
site canonique de `rerank_model` : *« étendue 0,0 % … soit un classement au
hasard »*. L'inférence y est fausse, le réglage multilingue reste **le bon** —
97,6 % contre 95,1 % de rappel, 96,5 % d'étendue contre 0,1 % — mais **pour une
raison plus faible que celle qui est écrite**. *Reprendre un antécédent du dépôt
sans le mesurer est la même faute que de l'inventer.*

#### La trouvaille principale de l'audit, vérifiée par le pilote

**L'idiome du dépôt lui-même échappe au garde de sûreté.** Le motif exige que le
**nom** soit adjacent à la valeur ; dans `Field(default="…")` la valeur vit à
l'intérieur de l'appel. `mesuré` par le pilote en appelant `_affectations_dans`
directement :

| forme copiable | vue par le garde d'affectations ? |
|---|---|
| `EMBEDDING_MODEL_NAME=<le modèle anglais>` | **oui** |
| `SentenceTransformer("<le modèle anglais>")` | **oui** |
| **`Field(default="…")` — l'idiome de `settings.py`** | **NON** |
| `os.environ["…"] = "…"` | **NON** |
| `ENV NOM v` (Dockerfile) | **NON** |
| `--embedding-model v` | **NON** |
| un **récit** | non — et c'est voulu |

**L'étiquetage est donc inversé pour la modification la plus probable de toutes** :
changer le `default` de `settings.py` échappe au garde de **sûreté** et n'est
rattrapé que par le **fil d'occurrences**, celui que le §4.28 vient de rétrograder
au rang de détecteur de dérive. Et l'auditeur a construit le cas où **les deux**
manquent : une mention tolérée convertie en affectation échappante **à compte
inchangé** — 629 passés, deux instruments verts.

**Où le pilote borne l'auditeur, avec le texte pour preuve.** L'auditeur cote la
phrase *« Aucune exemption, et c'est la propriété de ce garde »* comme dépassant
ce que le garde fait. Le pilote a relu le docstring : la phrase parle de
**l'absence de liste d'autorisation** — « il n'y a rien à autoriser » — et c'est
**vrai**, ce garde n'en a aucune. Elle ne prétend nulle part attraper toutes les
formes. **Le défaut n'est donc pas une phrase fausse, c'est une phrase MUETTE sur
sa couverture** — et la règle du chantier est *« soit bornée, soit gardée par un
test »*. Le geste juste n'est pas de rabattre une affirmation, c'est d'**ajouter la
borne qui manque** : nommer les formes attrapées et celles qui ne le sont pas.
*Que l'auditeur l'ait lue comme une revendication de couverture est en soi la
mesure de son ambiguïté.*

#### Les deux périphrases que le pilote a appliquées à la fusion

**1 — la dernière affectation copiable d'un reranker anglais**, dans le bloc `.env`
du plan historique, trois lignes sous celle que le lot venait de rendre
inoffensive. Le lot l'avait **trouvée, écrite, et non fermée** — à raison, son
périmètre étant l'embedding. Périphrasée, même geste et même bloc.

**2 — et le RÉCIT de cette trouvaille la reproduisait.** L'entrée du registre qui
la signale l'écrivait en clair. **Troisième occurrence de ce motif sur ce
chantier, et la seconde qui est du pilote** : le §4.27 racontait le rouge de
l'inventaire en nommant le modèle, et `main` est parti **rouge et poussé** pour
cette raison (§4.28). Aucun garde ne rougissait sur celle-ci — le garde du
reranker n'existe pas — donc ce qui la rendait fautive n'était pas un rouge, c'est
**ce qu'elle laissait copier**, et le fait que *le jour où ce garde sera écrit,
son premier acte serait de rougir sur le registre qui le demande.*

`mesuré` après les deux : **zéro affectation copiable du reranker anglais dans les
fichiers suivis.**

#### Ce qui part au lot suivant

| | Ce que c'est |
|---|---|
| **le garde du reranker** | le vrai travail, et le pendant du lot 3 : `rerank_model` a **trois usages et aucun contrôle**, et son mal est silencieux à −2,5 points sur 30 % des questions |
| **les formes qui échappent au garde d'affectations** | au minimum `Field(default=…)` et `os.environ[…] =`, **plus la borne de couverture qui manque au docstring** — ce que le garde attrape, et ce qu'il n'attrape pas |
| **le motif faux au site canonique de `rerank_model`** | « étendue 0,0 % … soit un classement au hasard ». Le réglage est bon, le motif écrit dépasse la mesure |
| **le bouchon de l'index PÉRIMÉ** | la boucle de reprise de `chauffer_l_index_lexical` n'est gardée par rien — mutation de l'auditeur : **629 verts**. Échoue **fermé**, et il est à un bouchon d'être gardé |
| **« 123 fichiers suivis »** | périmé d'un dans le docstring qui le porte : l'arbre en compte **124**, et son garde n'asserte que `>= 100` |

#### Les trois faux résultats de l'auditeur, qu'il déclare

Il en rapporte **trois**, tous les siens, tous attrapés : une mutation qui cassait
l'import (17 rouges parasites) ; une mutation **jamais appliquée** dont le
« 14 passed » était un **faux vert**, vu seulement en exigeant que l'empreinte du
fichier *diffère* ; et une sonde de graine dont le prompt jouet était **trop court
pour atteindre le cas**, qui rendait « sans graine → identiques » — l'inverse de
la vérité. *Un `rc` juste n'est pas une preuve d'atteinte, et un texte identique
non plus.*

#### Amendement au §4.31 — trois défauts du journal, et c'est l'utilisateur qui les a trouvés

Le pilote a annoncé « prochain numéro libre : **41** » et distribué un prompt sous
`Conv' 41`. **L'utilisateur a demandé « c'est pas le 40 ? ».** `mesuré` le
8 septembre 2026 en comptant les lignes du journal : **il n'existe aucune
ligne 40**, et le prochain numéro libre est **40**.

En le vérifiant, deux autres défauts sont sortis du même geste :

| | Ce que c'était |
|---|---|
| **la ligne `38` était en DOUBLE** | le lot avait écrit la sienne sur sa branche, le pilote en a ajouté une seconde. Or la règle du §9 est qu'**un numéro ne se réutilise jamais** : un journal qui montre deux fois `38` fait croire qu'il l'a été. Fondues en une, la substance des deux conservée |
| **les sections du registre étaient dans le DÉSORDRE** | `4.28`, **`4.30`**, **`4.29`**, `4.31`. La fusion du lot dette a concaténé sans conflit — donc **sans un `rc` pour le dire**. Remis en ordre, comptes de lignes vérifiés égaux |

**La cause des trois est la même, et c'est la faute que ce chantier nomme depuis
le début** : le pilote a écrit « 41 » depuis l'**arithmétique de son script**
d'édition — l'ancre trouvée valait 40, donc il a posé 41 — au lieu de **compter
les lignes du journal**. *Un numéro est une mesure comme une autre.* Et le
désordre des sections est la famille (f) pour la sixième fois : *un défaut né de
la fusion, invisible à tout code de retour.*

**Ce qui vaut d'être retenu tient en une ligne : ni un garde, ni un audit, ni le
pilote ne l'ont vu — c'est l'utilisateur, sur une question de quatre mots.** Le
journal des conversations est le seul artefact de ce chantier qu'aucun test ne
lit ; il est donc le seul dont la dérive ne rougit pas. C'est exactement ce que le
**§4.13** dit du reste, et c'est le dernier endroit où la leçon n'avait pas encore
été appliquée. **Un garde sur le journal — pas de doublon, pas de trou, et un
« prochain libre » égal au maximum plus un — monte au plan.**

---

### 4.32 → CLOS par le §4.35 — le lot 6 livré : un garde qui SIGNALE, et un cadrage que le pilote avait encore laissé vieillir

`Conv' 40` (LOT-6) a livré le 8 septembre 2026 deux commits, `a2d2081` et
`e6fc175`, **non poussés**, sur `claude/reranker-guard-affectations-782d7e`.

**Ce que le pilote a mesuré de ses mains**, le 8 septembre 2026 à 14:18 UTC,
avant toute décision :

| | `mesuré` |
|---|---|
| identité des deux commits | auteur ET committer `Florian Horellou <florian_horellou@laposte.net>` sur les deux — **adresse autorisée**. `git log --format='%h %an <%ae> %cn <%ce>'` |
| attribution d'assistant | **aucune occurrence** de `claude`, `anthropic`, `co-authored`, `generated`, `assistant` ni d'émoji de robot dans les deux messages complets (`git log --format='%B' \| grep -inE`) |
| position de la branche | `git rev-list --left-right --count main...claude/reranker-…` rend **`0 2`** : la branche est **0 en retard**, 2 en avance |
| `main` est-il un ancêtre ? | `git merge-base --is-ancestor main claude/reranker-…` rend **`rc=0`**. **Donc l'arbre d'une fusion `--no-ff` est exactement l'arbre de la branche**, et la porte passée sur la branche EST la porte sur le résultat de fusion. Ce n'est pas une supposition, c'est ce `rc=0` |
| la porte, dans l'arbre du lot, sur son propre `.venv` | `make lint` → **`rc=0`** (mypy 18 fichiers, ruff *All checks passed*) ; `make test` → **`rc=0`**, **643 passés** en 28,92 s. `rc` du processus `make`, jamais derrière un tube |
| propreté de l'arbre du lot | `git status --porcelain` **vide** : les mutations ont bien été restaurées, rien n'a été laissé tomber |

**Et un piège de poste, relevé au passage.** Le premier `make lint` du pilote a
rendu **`rc=2`** sur `make: mypy: No such file or directory` — non pas un rouge
du lot, mais un `.venv` absent du `PATH`. C'est exactement le cas que le
`Makefile` documente en tête de sa cible `install`. *Un `rc=2` qui nomme un
fichier introuvable n'est pas un rouge de comportement* — même famille que
« le symbole n'existe pas n'est pas un rouge de comportement », déjà au §12.

#### Ce que le lot a trouvé contre le pilote, et il avait raison les deux fois

**Le cadrage annonçait `main` = `origin/main` = `2bb511c`. Mesuré : `3638240`,
et `2bb511c` est `main@{1}` — trois commits d'écart** (`git rev-list --count
2bb511c..main` rend 3). Le prompt mettait en garde contre exactement cette faute,
en la nommant, et la commettait dans le même souffle : le pilote avait mesuré
`main` **avant** d'y pousser la chaîne de correction du journal, puis n'avait pas
remesuré avant d'écrire. **C'est la QUATRIÈME occurrence du même motif** — après
les 562 tests publiés deux commits trop tôt, le « prochain numéro libre 41 » tiré
d'une arithmétique, et l'antécédent de la sigmoïde repris sans mesure.

**Et la CINQUIÈME est dans le même prompt** : le relevé du démon d'orchestration
y était annoncé comme le **huitième**, et le lot a compté le **neuvième**. Un
compte, lui aussi, déduit au lieu d'être lu.

*La règle opérationnelle est déjà écrite et n'a pas suffi : « mesurer avant de
pousser, jamais après ». Il lui manquait sa moitié — **remesurer `main` juste
avant de sceller le prompt, et non au moment où l'on commence à l'écrire**. Un
cadrage vieillit entre sa première ligne et sa dernière.*

#### Les deux décisions du lot, et la mesure qui les a tranchées

Le lot 3 n'était **pas copiable** : il confronte le réglage d'embedding à
l'**estampille** que le pipeline inscrit sur la collection — une égalité exacte
contre un fait extérieur. Le reranker ne produit **rien de persistant**, donc
aucun fait extérieur n'existe. Le lot a donc confronté une **propriété du modèle
lui-même**, la taille de son vocabulaire, doublée d'un registre des modèles
réellement mesurés.

**Et sa propre mesure a renversé son dessin initial**, par lecture des seuls
`config.json` (60 Ko, aucun poids téléchargé) : le multilingue mBERT a un
vocabulaire de **119 547** entrées, **plus petit** que le DeBERTa-v3 **anglais**
à **128 100**. **Les deux classes se chevauchent : aucun seuil n'est un
classifieur.** C'est écrit au site comme un **indice, jamais un verdict**.

**D'où la seconde décision : SIGNALER, ne pas refuser**, pour deux raisons qui se
cumulent — *la proportion* (refuser porterait la disponibilité de 100 % à 0 %
pour épargner 2,5 points de rappel, ce qui est pire sur tous les axes) et *la
nature de la preuve* (un 503 sur un indice dont le chevauchement prouve qu'il se
trompe **dans les deux sens** est un garde qu'on arrache au premier faux
positif, là où le 503 du lot 3 s'appuie sur une égalité exacte). Trois niveaux,
parce que « je ne sais pas » ne se replie ni sur « c'est bon » ni sur « c'est
cassé » : `warning` sous le plancher, `warning` si la propriété est illisible,
`info` pour un modèle hors registre simplement non mesuré. C'est la discipline
d'`etat_index_lexical`, réemployée.

#### Le motif faux du §4.31, corrigé — et désormais gardé

Le site canonique de `rerank_model` portait « étendue 0,0 % … **soit un
classement au hasard** ». La conclusion ne suit pas de la prémisse : des logits
de −6,8 à −11,35 passés par `_sigmoid` s'écrasent dans **0,11 % d'étendue en
préservant STRICTEMENT l'ordre**. Saturation, pas perte d'ordre. La propriété est
maintenant **gardée par un test** — `_sigmoid` rendu constant fait rougir. Le
coût réel, **−2,5 points de rappel@10** concentrés sur les 41 questions
translingues sur 138, est écrit comme **cité de l'audit et non remesuré**, aux
deux sites, dans un commit qui n'existe que pour cela.

#### Deux trous que ce lot ouvre, nommés par lui, et qui montent au plan

- **le garde d'affectations ne surveille que les noms du réglage d'EMBEDDING.**
  Un `Field(default=…)` plantant un reranker non conforme sous `rerank_model`
  n'est attrapé par **rien**. C'est le trou **symétrique** de celui que ce lot
  vient de fermer, et le lot l'a trouvé **par son propre faux résultat** — sa
  mutation M3, posée sur `rerank_model`, restait verte. Il ne l'a pas fermé pour
  une raison juste : le faire demande de décider ce qu'est un reranker non
  conforme comme **valeur littérale**, or sa décision (a) est précisément que le
  chevauchement mesuré interdit de le décider sur un nom ;
- **le verdict du reranker ne rejaillit pas dans `/health`.** Une ligne de
  journal une fois par processus est facile à manquer, et le défaut est *le
  silence*. Le fermer change le contrat d'une route et le schéma
  `EmbeddingModelHealth` — à ne pas empaqueter dans un lot qui construit déjà
  deux gardes.

#### L'assertion décorative que le lot a trouvée contre lui-même

Sa première borne de périmètre — « un fichier à deux niveaux de profondeur » —
est satisfaite par `tests/unit/*` quoi qu'il arrive. La mutation qui retire
`documentation/audits/` et `documentation/campagnes/` du balayage laissait **122
fichiers sur 124**, sous un plancher `>= 100` aveugle, et l'assertion **verte**.
Corrigée, portée sur `documentation/`, elle rougit sur cette mutation-là.
**C'est la septième fois de ce chantier qu'un garde vert sous une scène que le
défaut ne rencontre pas est trouvé — et la première fois qu'il l'est par le lot
qui vient de l'écrire.** L'échec est consigné à son site.

Le lot a par ailleurs **refusé d'asserter le compte exact de fichiers suivis**
(124, corrigé de 123) et asserte à la place la **forme** du périmètre, avec un
motif écrit : un compte exact rougirait à chaque fichier ajouté — l'événement le
plus banal du dépôt — et enseignerait le geste « monter le chiffre » que ce même
fichier désapprend ailleurs. *Même famille que la maintenance du §4.29 : on
corrige par périphrase, on ne monte pas le compte.*

#### Décision du pilote

**`src/` change de 178 lignes de code neuf, et ces lignes portent deux décisions
de conception prises par le lot lui-même** — contre quoi confronter, et signaler
plutôt que refuser. Le critère amendé du §4.18 ne s'applique donc pas : il
n'exempte que le changement **spécifié ET pré-mesuré par l'audit qui l'a exigé**.
**Audit indépendant requis**, par une conversation qui n'a écrit aucune de ces
lignes — `Conv' 41`, **neuvième audit du chantier**.

---

### 4.33 → L'audit du lot 6 : deux bloquantes, et le pilote corrigé sur la CONDITION de son raisonnement de fusion

`Conv' 41` (AUDIT-6) a rendu son rapport le 9 septembre 2026 — **neuvième audit
du chantier**. Deux bloquantes, une dizaine de non bloquantes, et une
recommandation « fusionner après correction ».

**Et une première dans la série : le cadrage du pilote est juste sur ses six
lignes.** L'auditeur a reproduit `main`, le sommet de la branche, l'absence de
poussée, l'avance `0 2`, la porte `rc=0` / `rc=0` à 643 passés et les 896
insertions sur 6 fichiers — tout concorde. La demi-règle ajoutée au §12 la veille
— *remesurer `main` juste avant de **sceller** le prompt* — a tenu à sa première
application. C'est la seule fois de ce chantier où un audit n'a rien eu à
reprendre au cadrage.

#### B-1 — le câblage n'est éprouvé que sur son BRUIT. `mesuré` par le pilote

C'est la trouvaille qui décide, et le pilote l'a refaite de ses mains le
9 septembre 2026 dans l'arbre de l'auditeur, détaché sur `e6fc175`, restauration
par empreinte SHA-256 vérifiée (`33aa5783…` avant, `d3b68f62…` muté,
`33aa5783…` après).

**Mutation A6** — le garde reçoit `settings.embedding_model_name` au lieu de
`settings.rerank_model`, ET le vocabulaire n'est plus lu (`None` en dur) :

    make test → rc=0, 643 passés

**Aucun des 643 tests ne distingue « le garde a lu le réglage du reranker et son
vocabulaire » de « le garde a lu le réglage d'embedding et rien ».**

Et la conséquence, `mesuré` par une sonde en lecture seule sur la fonction pure,
avec les arguments que le site muté lui passerait :

| ce que le site passe | verdict rendu |
|---|---|
| le site JUSTE, réglage normal (`rerank_model`, 250 002) | **`None`** — silence, correct |
| A4 seul (mauvais réglage, vocabulaire lu) | **`info`** |
| **A6** (mauvais réglage, vocabulaire non lu) | **`warning`**, et le message nomme `paraphrase-multilingual-MiniLM-L12-v2` |

Sous A6, **le réglage NORMAL déclenche un avertissement qui nomme le mauvais
modèle** — exactement l'auto-discrédit que `test_le_modele_en_service_ne_declenche_rien`
existe pour empêcher. Sauf que ce test appelle la fonction **pure** et ne voit
rien du câblage. *Le lot a écrit le bon test, du mauvais côté de la frontière.*

Les trois mutations que le pilote avait commandées — `logger.log` retiré,
`verdict = None`, `==` en `!=` — rougissent bien, une chacune. Elles éprouvent
que *quelque chose* avertit. Elles n'éprouvent pas *quoi*.

**Septième occurrence de la famille dominante de ce chantier** : un garde vert
sous une scène que le défaut ne rencontre jamais. Et la première où toute la
valeur du lot en production est dans la partie non gardée.

#### B-2 — le chiffre `mesuré` du périmètre est périmé dans le commit qui l'écrit. `mesuré` par le pilote

`git ls-tree -r --name-only`, le 9 septembre 2026 :

| ref | fichiers suivis | dont `tests/` |
|---|---|---|
| `3638240` (`main`) | **124** | **53** |
| `a2d2081` (le commit qui écrit le docstring) | **125** | **54** |
| `e6fc175` | **125** | **54** |

Le docstring publie 124 et 53. Le même commit ajoute
`tests/unit/test_garde_reranker.py`. **Le chiffre était faux d'un avant d'être
écrit**, et le paragraphe situé quatre lignes plus bas raconte que le chiffre
*précédent* était périmé d'un pour la même raison. *Le lot commet à un troisième
site la faute qu'il vient de corriger aux deux autres, dans le paragraphe même
qui la nomme.*

#### H8 — et le périmètre est décoratif sur le seul fichier qui compte. `mesuré` par le pilote

L'auditeur a montré que la borne de périmètre corrigée attrape bien la mutation
qui avait démasqué la version décorative, mais reste aveugle à trois autres
rétrécissements. Le pilote a refait le plus grave, restauration par empreinte
vérifiée (`aee879ef…` → `6512a11f…` → `aee879ef…`) :

**Retirer du balayage le SEUL `src/agent/settings.py`** — le fichier dont
l'idiome `Field(default=…)` est le motif entier du plus gros motif neuf de ce
lot, celui que le commentaire appelle *« le site réel, c'est-à-dire tout ce qui
compte »* :

    pytest tests/unit/test_coherence_depot.py → rc=0, 20 passés

Et une phrase du docstring tombe avec : *« ce qui est asserté à la place, et
c'est plus fort qu'un compte »*. C'est mesurablement l'inverse — un compte exact
rougit sur **tout** rétrécissement, par construction. Le compte n'est pas plus
faible ; il est plus **bruyant à la croissance**. *Ce n'est pas la même
critique, et le motif écrit confond les deux.*

#### La troisième forme, que le lot n'avait pas envisagée, et qui ferme les deux

Le motif du lot oppose « compte exact » à « assertion de forme » comme si
c'était le seul choix. L'auditeur en propose une troisième, et elle est juste :
**un plancher MONOTONE dérivé du dernier relevé** — `>= 125` au lieu de
`>= 100`. Il rougit sur tout rétrécissement, comme un compte exact ; il ne
rougit **jamais** sur une croissance ; et le seul geste qu'il enseigne est de
monter le chiffre **dans la direction sûre**, quand on resserre volontairement.
Il aurait attrapé H5, H7 et H8, et il rend B-2 sans objet.

*Le plancher `>= 100`, laissé à 100 quand le dépôt en porte 125, n'est plus un
plancher : c'est un souvenir.*

#### Ce que l'audit corrige au pilote, et c'est la CONDITION de son raisonnement

Le pilote avait écrit au §4.32 : `merge-base --is-ancestor` rend `rc=0`, donc
l'arbre d'une fusion `--no-ff` est l'arbre de la branche, donc la porte de la
branche EST la porte du résultat de fusion. **L'auditeur l'a vérifié** —
`git merge-tree --write-tree main e6fc175` et `git rev-parse e6fc175^{tree}`
rendent tous deux `eb321637…` — et l'a borné deux fois. La seconde borne est
celle qui compte, et elle **amende le §4.32** :

- **la prémisse est périssable.** Elle vaut tant que `main` reste à `3638240`.
  Remesurer `--is-ancestor` **juste avant** de fusionner, pas la veille ;
- **l'égalité des arbres ne donne l'égalité des portes que parce que rien, dans
  le banc, ne lit l'HISTOIRE de ce dépôt — et ce n'est pas automatique, c'est
  mesuré.** Deux appels `git` seulement dans les tests : `_fichiers_suivis()`
  lit l'index, et `test_installation_des_garde_fous.py` monte un dépôt jetable.
  Aucun `git log`, aucun `rev-list`.

**Et la distinction qui manquait au registre** : les deux défauts que ce chantier
garde en mémoire comme *nés de la fusion* venaient d'une fusion de branches
**divergentes**, où `main` n'était PAS un ancêtre. Le raisonnement du pilote
aurait été faux là-bas ; il est juste ici. *Ce n'est pas la fusion qui est
dangereuse, c'est la divergence.* **Écris la condition, pas la conclusion.**

#### Les non bloquantes qui montent au lot de réparation

- **(E-a) deux formes RÉELLES échappent encore au garde de sûreté, et ce sont
  les plus fréquentes du dépôt** : `monkeypatch.setattr(settings, "<champ>", v)`
  — **102 sites**, dont un **directement sur `embedding_model_name`** — et la
  lecture d'environnement avec valeur par défaut (`environ.get(NOM, défaut)`,
  `getenv`) — **6 sites**. Le lot a couvert `setdefault`, dont le dépôt fait
  **zéro** usage sur l'environnement, et manqué `setattr`, dont il fait 102.
  **La priorité est inversée**, et le motif que le lot écrit pour `setenv`
  s'applique mot pour mot, et plus fort, à `setattr`. Les deux formes sont
  ancrables sans le risque invoqué pour écarter les drapeaux : elles exigent le
  nom du réglage ET la valeur entre guillemets, donc ne peuvent pas rougir au
  milieu d'une phrase ;
- **(E-d) la propriété invoquée pour expliquer que les récits restent verts est
  FAUSSE, dans les deux sens.** Le docstring dit que les délimiteurs admis sont
  `"` et `'`, jamais l'accent grave. `mesuré` : aucun des six récits neufs ne
  contient le nom du réglage, et leur retirer tous leurs accents graves les
  laisse verts — les accents graves n'y jouent **aucun** rôle. Et trois récits
  qui **citent la ligne fautive**, entre accents graves comme entre guillemets,
  **rougissent**. Ce qui protège un récit n'est pas l'accent grave : c'est de ne
  pas mettre le nom du réglage à côté de sa valeur. *Une seconde direction
  décorative, sous une propriété fausse* ;
- **(E-e) l'ancrage `^` du motif `ENV` n'est gardé par rien.** Le retirer laisse
  643 passés, `rc=0` — alors que le lot écrit explicitement pourquoi cet ancrage
  est décisif, et le sonde. *Une décision motivée, sondée, et non gardée* ;
- **(E-c) une clause de la borne est démentie par le dépôt lui-même** : « une
  affectation construite par morceaux, ou passée par une variable intermédiaire.
  **Personne ne recopie une instruction sous cette forme** ». La seule
  affectation vivante du modèle anglais au réglage réel est exactement de cette
  forme, deux lignes du même fichier, 136 lignes plus loin. Phrase du genre
  « personne » : à borner ou à garder ;
- **(C) la lecture défensive tient dans trois natures d'exception sur les six
  plausibles.** `getattr(obj, "config", None)` n'absorbe qu'`AttributeError` ;
  une `property` qui lève `RuntimeError`, `OSError`, `KeyError` ou `ImportError`
  **propage et casse le chargement du reranker**, donc la recherche — *un garde
  qui provoque la panne qu'il surveille*, ce que le docstring du test nomme
  lui-même. Et ce n'est pas théorique : en sentence-transformers 5.6.1,
  `CrossEncoder.config` **est une `property`** chaînée sur une seconde
  `property`. Aujourd'hui elle rend `None` proprement — le garde est juste, mais
  pour une raison que le site croit garantie et qui ne l'est pas. La phrase
  « bavard, pas muet » est du genre « quelle que soit » : à borner ou à garder ;
- **(B) le niveau du verdict n'est borné par aucun type.** Ajouter un quatrième
  niveau passe mypy et ruff en `rc=0` avec 643 verts, et le ternaire le
  journalise en **`INFO`**. *La dégradation va vers le BAS* : un garde qui
  rétrograde une alarme est pire qu'un garde qui la promeut ;
- **(D-1) le registre est un `dict[str, str]` dont les valeurs sont MORTES.**
  Les vider laisse 643 passés : les trois usages ne lisent que les clés. De la
  documentation déguisée en donnée — soit un `frozenset`, soit lire réellement
  la valeur, le message `info` disant à l'exploitant « ce modèle n'a pas été
  mesuré » sans jamais lui dire ce qui *a* été mesuré sur celui du registre ;
- **(D-2) « 19,5 % de marge sous mBERT » est juste sous une définition et faux
  sous l'autre** — 19,547 % rapporté au plancher, 16,351 % rapporté à mBERT, et
  la formulation « sous mBERT » se lit spontanément comme la seconde.
  **Troisième occurrence** de « deux écritures justes sous des définitions
  différentes ».

#### Ce que l'audit a confirmé, et il faut l'écrire aussi

- **les cinq `vocab_size` du commentaire, reproduits tous les cinq** avec leurs
  cinq `model_type`, par lecture des seuls `config.json`. Le chevauchement
  mBERT / DeBERTa-v3 est **réel**, donc la décision centrale du lot — signaler
  et non refuser — repose sur un fait vérifié ;
- **le bouchon de l'index périmé : rien à reprendre.** Les deux tests passent sur
  `main` inchangé, les deux mutations mordent (2 rouges, 1 rouge), l'affirmation
  « un sondage unique laisse 629 verts sur `main` » est reproduite **au test
  près**, et la **preuve d'atteinte est réellement assertée** — le bouchon qui
  bascule trop tôt rougit sur `assert len(dormi) >= 4`. *C'est la partie
  exemplaire du lot* ;
- **le garde du compte de tests discrimine dans les six directions** essayées, et
  titre et note sont confrontés séparément à la mesure ;
- **les quatre motifs neufs portent tous leur charge**, et le sens dangereux —
  rougir sur un récit — n'a pas été franchi ;
- **le motif d'exclusion du drapeau `--un-modele valeur` tient**, prémisse
  vérifiée : les deux `add_argument("--model")` de `scripts/` visent le LLM.

Et une note de méthode que l'auditeur a écrite contre lui-même : sa première
écriture de « sondage unique » rompait le contrat de retour de la fonction et
rougissait un test sur `main` — *sa mutation, pas le défaut du lot*. Il l'a
mesuré, corrigé et écrit. **Un rapport qui déclare sa propre faute est plus
croyable, pas moins.**

#### Décision du pilote

**Ne pas fusionner en l'état. Un lot de réparation d'abord** — `Conv' 42`.

B-1 est bloquante sans discussion : la seule chose que ce lot livre en
production est le câblage, et le câblage est éprouvé sur « quelque chose
avertit ». B-2 et H8 se ferment ensemble par le plancher monotone, et le pilote
retient cette forme plutôt que la correction à deux jetons : *corriger 124 en
125 laisserait la phrase « plus fort qu'un compte » debout alors qu'elle est
mesurablement fausse.*

### 4.34 → La réparation du lot 6 : les deux bloquantes fermées, et quatre phrases retirées

`Conv' 42` (REPAR-7) a livré le **9 septembre 2026** sur la branche du lot,
`claude/reranker-guard-affectations-782d7e`, rattrapée sur `main` par une
**fusion** — jamais un rebase.

**Le cadrage du prompt était juste sur ses six lignes, et c'est la deuxième fois
d'affilée.** `main` = `origin/main` = `31f8b43`, avance `0 0` ; branche du lot au
sommet `e6fc175`, deux commits, non poussée, `2` en avance sur `3638240` et `3`
en retard sur `main` ; porte `rc=0` / `rc=0` à **643 passés**. Tout remesuré,
tout concordant.

**Une seule reprise, et elle porte sur la RECETTE, pas sur un chiffre.** Le
lot a d'abord mesuré ses mutations avec `pytest tests/` — **653** collectés, dix
de plus que la porte. La recette du site est `pytest tests/unit/ -v`
(`Makefile:69`), et c'est elle qui rend 643. *Un chiffre juste sous une recette
inventée reste un chiffre faux.*

#### B-1 — fermée. Le câblage était éprouvé sur son seul BRUIT

Reproduction exacte de la mesure du §4.33, empreintes comprises :
`33aa5783…` à l'origine, `d3b68f62…` sous la mutation double. Les trois
mutations du site d'appel — mauvais réglage seul, vocabulaire non lu seul, les
deux — laissaient **643 passés, `rc=0`**.

Deux gestes, et le second est structurel :

- **le contenu du message est discriminé.** L'assertion `"2,5 points"` que les
  DEUX messages `warning` portent est doublée de deux assertions qui, elles,
  séparent les branches : le message doit **nommer** le réglage du reranker, et
  **rapporter le vocabulaire lu** sur le modèle chargé ;
- **une seconde scène, dans un PROCESSUS À PART**, où le modèle en service
  traverse le vrai chemin et ne doit rien dire. Le processus neuf n'est pas
  décoratif : `lru_cache` sur `_get_rerank_model` rendrait une seconde scène
  creuse dans le même processus. Elle asserte **sa propre atteinte** — le modèle
  chargé sous le réglage réel — et fait compter ses lectures à une `property`,
  ce qui ferme le cas que le silence seul ne voit pas : le registre
  court-circuite avant tout seuil, donc un câblage qui ne lirait jamais le
  vocabulaire resterait muet.

Chaque mutation rougit **sur l'assertion qui la vise**, vérifié ligne à ligne, et
le témoin inerte reste vert.

#### B-2 et H8 — fermées ensemble par le PLANCHER MONOTONE

Le chiffre n'a **pas** été corrigé de 124 en 125 : cela aurait laissé debout la
phrase *« ce qui est asserté à la place, et c'est plus fort qu'un compte »*, que
le §4.33 mesure fausse. Le motif est réécrit : un compte exact rougit sur **tout**
rétrécissement, par construction ; il n'est pas plus faible, il est plus
**bruyant à la croissance**.

La forme retenue est le plancher monotone de l'audit, **global ET zone par
zone**, dérivé du relevé du 9 septembre 2026 mesuré sur l'arbre final : **125**
au total, 54 `tests/`, 18 `src/`, 14 `documentation/`, 13 `runs/`, 12 à la
racine, 9 `scripts/`, 4 `prompts/`, 1 `.github/`.

**La ventilation par zone n'est pas décorative, et c'est mesuré.** Les trois
rétrécissements que l'audit demandait — le seul `src/agent/settings.py`,
`.github/` entier, `runs/` + `.github/` — rougissent tous sur le plancher
**global**. Une quatrième mutation le montre autrement : retirer
`src/agent/settings.py` **et ajouter un fichier ailleurs** laisse le total à 125,
donc le plancher global VERT, et fait rougir la seule zone `src` — `(17, 18)`.
*C'est le cas qu'un plancher global seul ne voit jamais, et l'ajout est
l'événement le plus banal de ce dépôt.*

L'assertion « chaque zone est représentée » est **retirée**, et ce n'est pas un
relâchement : les planchers par zone la contiennent strictement, un plancher de 1
exigeant la présence. Sont conservées la récursion de `documentation/` et
`.env.example` nommément, qui ne se déduisent d'aucun compte.

#### Les quatre phrases, et ce que la mesure en a fait

- **la propriété des accents graves était fausse dans les deux sens**, reproduit :
  les six récits neufs restent verts **avec comme sans** leurs accents graves, et
  cinq récits citant la ligne fautive rougissent entre accents graves comme entre
  guillemets. Ce qui protège un récit est de ne pas poser le nom du réglage à côté
  de sa valeur. **Et une mesure que l'audit n'avait pas faite** : la propriété est
  bien exercée par le test voisin, mais par **UN récit sur ses quatorze** — celui
  qui juxtapose le nom et la valeur avec un `:`. La phrase est corrigée et gardée
  dans les trois directions mesurées ;
- **l'ancrage `^` du motif `ENV` est gardé.** Le retirer faisait rougir zéro
  test ; il en fait rougir un, sur les trois récits que l'ancrage sépare d'une
  directive Dockerfile réelle ;
- **« personne ne recopie une instruction sous cette forme » est bornée.** La
  contre-preuve est vérifiée : lignes **47** et **183** de
  `tests/unit/test_garde_modele_embedding.py`, **136 lignes d'écart** — le nom
  posé en constante de module, puis passé au réglage réel pour éprouver le garde
  du lot 3. Légitime ; c'est l'affirmation qui ne l'était pas ;
- **« 19,5 % de marge sous mBERT » porte sa définition.** 19,547 % rapporté au
  plancher, 16,351 % rapporté à mBERT, les deux recalculés. Troisième occurrence
  de « deux écritures justes sous des définitions différentes » dans ce chantier.

#### Les deux valeurs mortes, et le choix écrit

- **le registre lit désormais ses valeurs.** Le choix entre « en faire un
  ensemble » et « lire la valeur » est tranché par ce que le message `info` dit :
  *« ce modèle n'a PAS été mesuré »*, sans jamais dire ce qui **a** été mesuré sur
  celui du registre, alors que la réponse est écrite deux lignes plus haut. Les
  deux messages informatifs portent nom **et** mesure ; l'usage « Réparation »
  garde les noms seuls, parce que c'est une instruction à recopier et non un
  relevé — et c'est écrit au site. Vider une valeur fait rougir ;
- **le niveau du verdict est un `Literal` à deux valeurs.** La mesure est faite
  **dans les deux sens sur la même mutation** : un quatrième niveau ajouté au
  garde passe `make lint` en **`rc=0`** avec l'ancienne signature `tuple[str, str]`,
  et le fait rougir en **`rc=2`** (mypy rend 1, `make` rend 2) avec la nouvelle —
  `Incompatible return value type (got "tuple[Literal['critical'], str]")`.

#### Ce que ce lot n'a PAS fermé, et c'est la décision du pilote

`setattr` (102 sites) et l'élargissement du `except` de la lecture défensive
montent au lot 7. Aucun autre changement de `src/` n'a été emporté : les trois
qui y sont — la définition de la marge, le registre, le type du niveau — sont
ceux que l'audit avait spécifiés **et** pré-mesurés.

#### Une trouvaille contre le prompt, et elle porte sur le registre

Le prompt demandait de **compter** le relevé du démon d'orchestration contre le
registre plutôt que de le déduire. **Le registre ne porte pas ce compte de façon
univoque** : le tableau du §4 annonce le « **sixième** relevé EN MARCHE » quand le
§12 et le §4.32 parlent du « **neuvième** relevé » tous états confondus, et le
relevé que le pilote dit avoir pris le 9 septembre 2026 n'est écrit nulle part.
Le fait brut, `mesuré` le 9 septembre 2026 à 08:15 UTC en lecture seule :
`rag-ingestion-pipeline-dagster-daemon-1` est **`Up 2 hours`** — donc rallumé
depuis le `Up 5 hours` du 8 septembre, sans qu'aucune conversation le décide.
**Aucun numéro ne lui est attribué ici**, faute de pouvoir le compter : c'est
exactement le geste que le §12 interdit, et le corriger demande de fusionner les
deux comptes du registre — ce qui est une décision du pilote, pas une réparation.

---

### 4.35 → FERMÉ — le lot 6 fusionné : le câblage du garde est enfin éprouvé, et le périmètre a un plancher qui monte

`Conv' 42` (REPAR-7) a livré le 9 septembre 2026 quatre commits plus une fusion
de rattrapage sur la branche du lot. **Fusionné dans `main` par le pilote.**

#### Ce que le pilote a mesuré de ses mains avant de trancher

Le 9 septembre 2026 entre 08:40 et 09:05 UTC, dans l'arbre du lot, restauration
par empreinte SHA-256 vérifiée à chaque mutation :

| | `mesuré` |
|---|---|
| identité des quatre commits + la fusion | auteur ET committer `florian_horellou@laposte.net` partout — adresse autorisée |
| rien de poussé | `git ls-remote --heads origin` ne rend que `refs/heads/main` |
| désactivations ajoutées | **aucune** sur tout le lot : zéro `skip`, `xfail`, `type: ignore`, `noqa` ou `pragma` dans les lignes ajoutées. Le seul `type: ignore[dict-item]` de `retriever.py` est **antérieur** — vérifié présent sur `main` |
| **B-1 fermé** | la mutation qui laissait 643 verts (mauvais réglage ET vocabulaire non lu) rend **`rc=1`, 2 rouges** : `test_le_chargement_du_reranker_journalise_le_verdict` et `test_le_modele_en_service_ne_dit_rien_par_le_chemin_reel`. Empreintes `77decd9c…` → `3ca39e0d…` → `77decd9c…` |
| **B-2 + H8 fermés** | le rétrécissement **compensé** — sortir le seul `src/agent/settings.py` et ajouter un fichier ailleurs, total inchangé à 125 — laisse le **plancher global vert** et fait rougir **la zone `src` à `(17, 18)`**, l'assertion nommant le cas. Empreintes `575744be…` → `f6be0d52…` → `575744be…` |
| **le niveau borné, dans les deux sens** | un quatrième niveau ajouté à `verdict_langue_du_reranker` rend `make lint` en **`rc=2`** — mypy : *« Incompatible return value type (got `tuple[Literal['critical'], str]`, expected `tuple[Literal['info', 'warning'], str] \| None`) »* — là où il passait en `rc=0` avec 643 verts et journalisait en `INFO` |
| la porte sur la branche | `make lint` `rc=0`, `make test` `rc=0`, **647 passés** |
| le compte de tests | **647 sur 42 fichiers** par la recette du site (`pytest tests/unit/ -v`), concordant avec `documentation/tests.md` |
| la prémisse de fusion, **remesurée juste avant** | `merge-base --is-ancestor main <branche>` → `rc=0` ; `merge-tree --write-tree` et `rev-parse <branche>^{tree}` rendent tous deux `74d78f7…` |
| **la porte sur le RÉSULTAT de fusion** | `main` = `137d780`, arbre `74d78f7…` comme prédit ; `make lint` `rc=0`, `make test` `rc=0`, **647 passés** — et cette fois dans le **clone principal avec son propre `.venv`**, parce que l'égalité des arbres ne dit rien de l'égalité des environnements |

#### Le critère de fusion, et pourquoi il n'a pas fallu un dixième audit

`src/` change, mais **de 53 lignes et pas d'une de plus que ce que l'audit avait
spécifié ET pré-mesuré** — vérifié au `numstat` : le registre dont les valeurs
étaient mortes (D-1), le `Literal` du niveau (B), la définition de la marge
(D-2). Aucun quatrième changement de production n'a été emporté, et la
fermeture de B-1 n'a coûté **aucune** ligne de `src/` : c'est le test qui
discriminait mal, pas le code qui se trompait. Le critère amendé du §4.18
s'applique donc, et le pilote a vérifié les trois dans les deux sens.

#### Ce que la réparation a trouvé contre le pilote, et elle a raison

**Le registre portait TROIS comptes incompatibles du relevé du démon
d'orchestration** : « sixième relevé en marche » et « **cinquième** relevé en
marche » **dans la même cellule** — l'ancienne phrase ayant survécu à celle qui
la remplaçait —, « quatrième fois qu'il se rallume », et « huitième relevé » au
§12, quand le lot 6 avait compté le neuvième. REPAR-7 a **refusé d'attribuer un
numéro** à son propre relevé et rendu le fait brut, en écrivant que le déduire
serait le geste que le §12 interdit. *C'est exactement la bonne conduite.*

La faute n'est pas du même genre que les cinq précédentes du pilote : ce n'est
pas un état affirmé sans mesure, c'est **un chiffre à plus d'un site canonique**,
ce que ce chantier interdit depuis le §4.13 — et une **édition sur place
bâclée**, qui a ajouté la phrase neuve sans retirer l'ancienne. Aucun `rc` ne
pouvait le dire.

**Corrigé** : le compte est **retiré**, la suite datée des relevés le remplace,
et le §12 renvoie au site unique. *Un numéro qu'on ne peut pas reconstruire
depuis le registre est un numéro qui dérive.*

**Et une mesure qui borne le récit du site**, prise par le pilote le 9 septembre
à 08:40 UTC : `rag-agent-api` est à `Up 2 hours` comme le démon, alors qu'il
était à `Up 7 hours` la veille. **Les deux conteneurs ont redémarré ensemble** —
ce qui désigne un redémarrage de l'hôte ou du démon Docker, et non le
« rallumage sans qu'aucune conversation le décide » que ce site supposait. Les
occurrences antérieures n'ont jamais été instruites ; celle-ci a une cause plus
simple.

#### Ce que la réparation a écrit contre elle-même, et il faut le lire

- **elle a mesuré son banc sous une recette inventée avant de s'en apercevoir** :
  `pytest tests/` rend **653** collectés là où la recette du site,
  `pytest tests/unit/ -v`, en rend 643. Elle a tout refait avant de conclure.
  *Un chiffre juste sous une recette inventée reste un chiffre faux* ;
- **sa première écriture du rétrécissement compensé était cassée par
  l'échappement bash** : elle rendait le `rc=1` attendu, mais sur
  `assert 2 >= 125` — le `split("\0")` ne s'était pas fait. **Le `rc` était juste
  et la raison fausse**, et elle l'a vu en lisant l'assertion. C'est la
  quatrième fois de ce chantier qu'une sonde rend le bon code pour la mauvaise
  raison, et la deuxième fois de suite qu'un lot l'attrape seul.

#### Les deux mesures que la réparation ajoute, et que personne n'avait faites

- **la propriété des accents graves n'était pas seulement fausse : elle n'était
  exercée que par UN récit sur les 14** du test voisin. L'audit avait établi que
  les six récits neufs étaient verts pour une autre raison que celle écrite ;
  REPAR-7 a compté ce qui exerçait réellement la propriété. Corrigée et gardée
  dans les trois directions ;
- **l'assertion « chaque zone est représentée » a été RETIRÉE, et ce n'est pas
  un relâchement** : les huit planchers par zone valent tous au moins 1, donc ils
  la contiennent strictement. *Deux instruments dont l'un est le sous-ensemble de
  l'autre donnent l'impression de deux mesures là où il n'y en a qu'une.* Les
  deux assertions qui ne se déduisent d'aucun compte — la récursion de
  `documentation/` et `.env.example` nommément — sont conservées, et elles
  visent la panne d'origine.

#### Le bilan du lot 6

Livré, audité, réparé, fusionné. **Une bloquante par audit sur les deux qu'il a
subis**, et les deux étaient un garde vert sous une scène que le défaut ne
rencontre jamais. Le garde du reranker **signale** au lieu de refuser, sur un
chevauchement de vocabulaires reproduit deux fois, et son câblage est
maintenant éprouvé sur *ce qu'il dit* et non sur *le fait qu'il parle*. Le
périmètre de l'inventaire a un plancher qui **ne descend jamais**, global et
zone par zone, et le rétrécissement qu'un plancher global ne peut pas voir
rougit.

**Ce qui reste ouvert, et monte au lot 7** : `setattr(settings, …)` et la
lecture d'environnement à valeur par défaut échappent au garde de sûreté, et la
lecture défensive de la propriété du reranker ne tient que dans trois natures
d'exception sur six.

#### CORRECTION DU PILOTE À SA PROPRE SECTION, mesurée le 9 septembre 2026 à 09:30 UTC

La première rédaction de ce paragraphe reprenait deux chiffres de l'audit — « 102
et 6 sites » — **et l'obstacle que l'audit puis REPAR-7 avaient invoqué pour
différer le lot 7** : *fermer `setattr` ferait rougir le site légitime du garde
du lot 3.* Le pilote allait les republier dans un prompt. Il les a mesurés
d'abord, et les trois sont à reprendre.

| | `mesuré`, sur les **fichiers suivis** (`git grep`) |
|---|---|
| `setattr(settings, …)` | **47** occurrences dans **7** fichiers, dont **30** dans `test_garde_modele_embedding.py`. Je ne reproduis **102 sous aucune** des quatre définitions essayées : 47 (suivis), 368 (tout `setattr`), 94 (en comptant les copies d'arbres de travail). **Ce chiffre a besoin de sa définition avant d'être réemployé** — quatrième occurrence de « deux écritures justes sous des définitions différentes » |
| `environ.get` / `getenv` | **5** sites suivis : `scripts/mesurer_le_graphe.py:45-46`, `src/frontend/app.py:10`, `tests/integration/test_stack.py:28-29`. Pas 6 — le sixième était la copie d'un arbre |
| **l'obstacle invoqué** | **il n'existe pas.** `git grep -E 'setattr\(\s*settings\s*,\s*"[a-z_]*model[a-z_]*"\s*,\s*"'` rend **AUCUN** résultat : les **27** `setattr` sur `embedding_model_name` passent tous une **CONSTANTE NOMMÉE** — `_AUTRE_CANDIDAT` ou `_MODELE_QUI_A_INDEXE` —, **jamais un littéral entre guillemets**. Or ce garde ne vise que les **instructions copiables**, donc un motif exigeant une valeur littérale ne ferait rougir **aucun** de ces sites |

**Conséquence sur le plan** : le lot 7 est probablement **beaucoup moins cher**
que l'audit, la réparation et le pilote ne le croyaient tous les trois. La
décision qu'il demandait — que faire du site légitime — n'a peut-être pas à être
prise, parce que le site légitime **suit déjà la discipline** que le dépôt
prescrit ailleurs : *le nom du modèle est toujours dérivé d'une constante, jamais
écrit en littéral.*

**Et c'est la SIXIÈME fois que ce chantier paye la même faute** : reprendre un
antécédent du dépôt — ou d'un rapport — sans le mesurer est la même faute que de
l'inventer. Cette fois c'est le pilote, dans la section qu'il venait d'écrire, et
il s'est arrêté au moment de la republier. *La règle qui a fonctionné est
exactement celle du §12 : remesurer juste avant de sceller le prompt.*

### 4.36 → FERMÉ — le lot 7 : les deux formes réflexives, le garde de numérotation, et le `pre-push` qui manquait

> Livré le **9 septembre 2026** sur `claude/lot-7-rag-agent-chat-425c4e`, sur
> `main` = `origin/main` = **`d56ffab`**. Porte **VERTE** : `make lint` `rc=0`,
> `make test` `rc=0`, **682 passés** sur **43** fichiers (+35 sur les 647 du
> cadrage), par la recette du site — `pytest tests/unit/`. **Rien de poussé.**
> **Trois fermetures indépendantes, les trois portées**, en trois commits
> séparés — plus un quatrième, qui ferme un faux résultat que le lot a trouvé
> contre lui-même.

#### Ce que valent les chiffres du cadrage, et ils sont justes à une exception

Le cadrage a été remesuré avant d'être suivi. **`main` = `origin/main` =
`d56ffab`, avance `0 0`**, porte verte à **647 passés** sur **42** fichiers :
tout vérifié. Les cinq lignes mesurées de la fermeture (a) : **47** `setattr`
suivis dans **7** fichiers, **27** sur le réglage d'embedding, et **l'obstacle
qui n'existe pas** — vérifié, le motif du cadrage ne rend aucun résultat. Les
deux ordres de numérotation : vérifiés, jetons par jetons.

**Une correction, et deux précisions.**

- **la seconde collision de numérotation N'EST PAS DANS `git`.** Le cadrage
  l'annonçait « à `a92e78a` ». `mesuré` : cette révision porte **une seule**
  section de ce numéro, et sa suite `4.1 … 4.35` est complète, ordonnée et sans
  doublon. Le balayage de **toute** l'histoire — `git rev-list --all`, chaque
  révision du registre — ne trouve **aucune** révision portant un doublon de
  titre. La collision a bien eu lieu, mais elle a été attrapée **avant le
  commit** par l'`assert` d'ancre unique d'un script d'édition, ce que le
  cadrage écrit lui-même deux paragraphes plus loin. La preuve d'atteinte de
  cette règle est donc **construite sur le document réel**, et le fait que
  l'histoire est propre est lui-même asserté — pour que personne ne reparte la
  chercher ;
- **la mutation `M3bis` du lot 6, que le cadrage donnait à lire, n'existe pas
  dans ce dépôt.** `git grep`, `git log -S`, `git log --grep` : aucun résultat,
  ni dans les fichiers suivis, ni dans l'histoire, ni dans les messages. Les
  rapports de lot vivent dans les conversations, `documentation/audits/` ne
  portant que celui du lot 1. Le **mécanisme** décrit, lui, est bien dans le
  dépôt — `test_les_formes_qui_echappaient_au_garde_le_font_rougir` plante ses
  formes par `f`-chaîne — et c'est lui qui a été suivi ;
- **il y a un `environ.get` suivi de plus que les cinq annoncés** :
  `scripts/verifier_les_ancrages.py:355`, qui lie la fonction sans clé
  (`env = os.environ.get`). Six sites, donc, et c'est le chiffre écrit au site
  du garde. Sans conséquence sur la fermeture : aucun des six ne porte de modèle.

À quoi s'ajoutent **cinq** mentions de `setattr(settings, …)` dans les deux
documents de pilotage, hors des 47 sites de code — de la prose, que le cadrage
excluait à juste titre de son périmètre.

#### (a) Les deux formes copiables qui échappaient, et le garde vert de naissance

`setattr(<objet>, "NOM", "valeur")` et `environ.get("NOM", "valeur")` /
`getenv(…)` sont ajoutées au garde de sûreté. Les deux sont des idiomes réels :
la première est **la plus répandue de ce dépôt**, la seconde affecte **par son
défaut** — sur un poste où la variable est absente, c'est cette valeur qui
décide du réglage.

**LA PARTICULARITÉ DE CES DEUX MOTIFS, ET ELLE EST LE TRAVAIL.** Aucun site du
dépôt ne les fait rougir, et aucun ne le fera : les 47 passent tous une
**constante nommée**. Un motif vert sur tout le dépôt ne se distingue pas d'un
motif qui ne garde rien — la famille de défaut dominante de ce chantier. Leur
mordant est donc établi sur **huit cas construits à l'exécution**, où le littéral
n'apparaît dans aucun fichier, et la seconde direction sur **neuf récits**.

**ET LE LOT A TROUVÉ SA PROPRE SECONDE DIRECTION DÉCORATIVE.** La mutation M-a4
— guillemets rendus **facultatifs** dans le motif `setattr` — laissait la
batterie **entièrement verte** (`rc=0`, 25 tests). Les cinq premiers récits ne
mettaient jamais le nom du réglage à côté de sa valeur : aucun ne mesurait donc
l'exigence des guillemets, qui est précisément ce qui empêche ce motif de rougir
au milieu d'une phrase. Trois récits ont été ajoutés — **l'appel paraphrasé**,
nom et valeur nus entre les parenthèses — et M-a4 rejouée rougit en nommant la
phrase.

`[^)]` **admet le retour à la ligne, et c'est mesuré** : la forme réelle de ce
dépôt est souvent multi-lignes, donc un motif à une ligne manquerait l'idiome.
Ce que la permission ouvre est borné, et le cas serré — la forme nommée puis la
valeur des lignes plus loin — est gardé.

La borne de couverture est reprise **forme par forme**, et ce qui reste non
attrapé est nommé, **le reranker en tête** : tous les motifs sont construits sur
les noms du réglage d'embedding, donc un reranker non conforme n'est attrapé par
aucun. C'est le §4.32, et ce lot n'y a pas touché.

#### (a bis) La lecture défensive du vocabulaire, qui cassait la recherche

Le site écrivait qu'une montée de version rendrait ce garde *« bavard, pas
muet »*. **La phrase était fausse, et pas d'un cas mais de quatre.** `mesuré`
sans charger de modèle, sur sept natures d'exception : un objet sans `config`
rend bien `None`, mais un `config` qui est une **`property` levant
`RuntimeError`, `OSError`, `KeyError` ou `ImportError` PROPAGEAIT** — l'`except`
ne retenait que `TypeError` et `ValueError`, et `AttributeError` était avalée par
le `default` de `getattr`, non par l'`except`.

Et `_get_rerank_model()` est appelé par `rerank()`, que `node_rerank` appelle
**sans aucun `try`** : la propagation ne rendait pas le garde bavard, elle
**cassait la recherche**. *Un garde qui provoque la panne qu'il surveille*, ce
que le docstring de son propre test nomme sans l'avoir gardé. Ce n'est pas
théorique : en sentence-transformers 5.6.1 — la version épinglée, `vérifié` —
`CrossEncoder.config` **est** une `property`, chaînée sur une seconde
(`transformers_model`) qui parcourt la hiérarchie de modules du modèle.

**L'`except` est élargi à `Exception`, la justification est écrite au site**, et
les trois autres réponses y sont pesées et écartées — borner la phrase laisserait
la panne ; énumérer les quatre natures mesurées est une liste fermée sur ce
qu'une sonde a trouvé aujourd'hui dans une bibliothèque tierce ; envelopper
`rerank()` avalerait les pannes qu'il doit propager. La latitude est tenue au
plus petit endroit possible : deux `getattr` et un `int()`, sur un fait de
configuration informatif dont l'échec a une valeur de repli déjà bruyante.

**`BaseException` n'est PAS attrapé**, et c'est gardé : `KeyboardInterrupt` et
`SystemExit` traversent. **Et l'absorption ne doit pas devenir un silence** :
gardé aussi. Deux phrases devenues fausses ont été retirées.

#### (b) Le garde de numérotation, et l'asymétrie qui décide de tout

Quatre règles sur des fonctions **pures** : aucun doublon, aucun trou,
« prochain numéro libre » = maximum + 1, et la forme `bis` tolérée sans que sa
tolérance ouvre une porte — le jeton comparé est le jeton **complet**, donc deux
`20-bis` restent un doublon, et un `bis` sans base est un numéro inventé.

**LES DEUX ORDRES ONT ÉTÉ MESURÉS AVANT QU'UNE SEULE ASSERTION NE SOIT ÉCRITE.**
Le journal est **chronologique** — `20-bis` est délibéré entre `26` et `27` —
donc asserter l'ordre du fichier sur lui produirait un **faux rouge sur une
ligne juste** ; le registre est **numérique**, et c'est son désordre né d'une
fusion sans conflit qui a été corrigé. Un test **mesure** cette asymétrie au lieu
de l'affirmer, et nomme le couple qui descend, pour qu'un lot suivant ne vienne
pas « harmoniser » les deux règles.

**LE SCOPE EST LA MOITIÉ DU TRAVAIL, et c'est mesuré.**
`pilotage_du_chantier.md` porte **deux autres tableaux** dont la première
colonne est un numéro en gras : un extracteur global lirait
`1 2 3 4 5 1 2 3 4 5 6 7 20 21 …`, soit onze doublons et un trou de 7 à 20 sur
un document parfaitement sain — le garde rougirait au premier `make test` et
serait retiré. Le fichier porte aussi **deux** lignes « prochain numéro libre »,
dont une, au §12, qui **raconte** la faute.

**CE GARDE NE COMPTE RIEN**, et c'est la leçon du §4.35 : l'ajout d'une ligne est
l'événement normal, et un garde qui rougirait dessus enseignerait le geste
« monter le chiffre ».

**La preuve d'atteinte est dans `git` et elle est datée.** À `2bb511c`, trois
dérives réelles : le doublon `38`, le « prochain libre : 41 » pour un maximum de
**39** — celle-là n'était pas au cadrage, elle a été trouvée en balayant
l'histoire — et le désordre `4.28 4.30 4.29 4.31`. Chacune fait rougir **la
règle qui la vise**, et la même révision reste **verte sur les autres** : la
batterie discrimine. La quatrième règle, le trou, n'a jamais eu lieu dans ce
dépôt : son cas est construit, et c'est écrit.

#### (c) Le `pre-push`, et deux faux verts trouvés contre le lot

Le garde-fou d'identité couvrait `commit` et `merge`, jamais `push` : **neuf**
poussées protégées à la main. `pre-push` entre dans `TYPES`, avec sa **propre
source** — le contrôle d'identité lit `git var GIT_AUTHOR_IDENT`, c'est-à-dire
l'identité **configurée** au moment du push, et rien des commits qui partent ;
le copier sous ce nom aurait donné un hook creux, et la mutation qui les confond
est interdite par un test. L'ordre porteur des deux gestes est préservé, et la
couche `.legacy` est posée sur les **trois** types.

**LA PLAGE, ET C'EST TOUT LE SUJET.** Elle arrive sur l'**entrée standard**, une
ligne par ref. Le cas central de la batterie est donc un commit du **MILIEU** :
cinq commits, le troisième non conforme, `HEAD` conforme — et le test prouve
d'abord que la scène est celle-là. Trois vérifications : l'**adresse** d'auteur
**et** de committer de chaque commit — jamais le nom, deux identités portant le
même —, les deux **formes** d'attribution que ces outils produisent réellement,
et l'absence de secret dans les **lignes ajoutées**.

**Trois bornes écrites** : une mention en prose n'est pas refusée, sans quoi le
hook enseignerait `--no-verify`, le seul geste que ce chantier interdit
absolument ; le nom n'est filtré que sur deux marqueurs de robot, et pourquoi ;
la détection de secret est un jeu de formes à haute confiance et non un
remplacement de `detect-secrets`.

**PREMIER FAUX VERT — un `rc` juste pour la mauvaise raison.** Le motif de secret
commence par un tiret : passé en argument nu, `grep` le lit comme une **option**,
rend `rc=2`, le `if` le lit comme faux, et **le hook sort en 0 sans avoir rien
vérifié**. `mesuré` en le retournant contre les 276 commits de ce dépôt : `rc=0`,
et le contrôle n'avait pas tourné **une seule fois**. Tous les motifs passent par
`-e`, et la propriété est gardée au niveau du **texte** du hook — au niveau du
comportement, la version fautive et la juste rendent le même `rc=0` sur un dépôt
sain. Le test qui la garde a lui aussi trouvé son propre défaut : il comptait la
**citation** du piège dans le bandeau comme un appel, et écarte désormais les
lignes de commentaire — la même distinction récit / instruction qu'en (a), à un
autre endroit du chantier.

**SECOND FAUX VERT, ET IL A ÉTÉ TROUVÉ PAR UN VRAI `git push` — invisible à une
batterie de 37 tests verts.** Le motif de secret portait une cinquième
alternative, l'en-tête d'un format de clé précis, **écrite en littéral pur**.
Elle **se reconnaissait elle-même** — et était de surcroît reconnue par la
première, générique, qui la couvre. La ligne qui pose le motif est une ligne
ajoutée : elle portait donc un « secret », et le hook **refusait le commit même
qui l'introduit** — `rc=1`, et **aucune ref chez le distant**. Un garde qui
provoque la panne qu'il surveille, à un troisième site dans ce lot, et dont les
deux seules sorties auraient été `--no-verify` ou le retrait du garde.

Gardé par un test qui voit le défaut **au moment où le motif est écrit** : la
batterie ne l'avait vu qu'**au commit suivant**, le commit fautif n'existant pas
encore quand elle a tourné. Le commit de la fermeture a été **réécrit** pour que
la ligne n'ait jamais existé dans la branche, ce que le message de refus du hook
prescrit lui-même.

**ET LA PREMIÈRE CORRECTION VISAIT LA MAUVAISE CAUSE — c'est la mutation qui
devait la reproduire qui l'a dit.** Elle assemblait le motif en deux variables
que le shell recompose, sur le motif « écrit d'une pièce, il se reconnaît ».
Remettre le motif générique d'une pièce a laissé la batterie **entièrement
verte** (`rc=0`, 38 tests) : l'assemblage n'y était pour rien. La vraie cause
est l'alternative **littérale**, et sa suppression est la correction complète —
elle ne retire aucune couverture. L'assemblage a été **retiré** plutôt que gardé
sur un motif faux, et ce qui protège les quatre alternatives restantes est
mesuré : chacune porte, après son préfixe littéral, une **classe** de caractères
dont le texte source n'est pas membre. *Quatrième faux résultat de ce lot contre
lui-même, et le seul qui portait sur une correction déjà écrite.*

**LES DEUX SENS, PAR DE VRAIS `git push` VERS UN DISTANT JETABLE**, jamais vers
`origin` : la branche entière du lot part (`rc=0`, ref arrivée), une plage propre
part (`rc=0`), et une plage dont le **troisième** commit sur cinq porte une
adresse interdite est **refusée** (`rc=1`, `essai` **absent** du distant). La
scène non conforme est construite **hooks désarmés** par un `core.hooksPath`
vide, **jamais** par `--no-verify` — et c'est la scène réelle, les sept commits
qui ont coûté ce dépôt étant partis avant qu'aucun hook n'existe.

**La preuve d'atteinte du contrôle de secret est COMPTÉE**, parce qu'un `rc=0` ne
prouve rien ici : **83 129** lignes ajoutées sur **276** commits traversent
réellement le contrôle, relevé en **plancher** et non en compte exact.

#### Une erreur de harnais du lot, corrigée et écrite

La première sonde de bout en bout de la fermeture (c) a cloné le dépôt **avant
d'avoir commité** son travail : elle a donc exécuté l'installeur de `main`, qui
a rendu `rc=0` en armant deux types sur trois. Le `rc` était juste et ne
mesurait rien. *Un `rc` juste n'est pas une preuve d'atteinte* — à un quatrième
site dans ce chantier, et celui-ci était le mien.

#### Ce que ce lot n'a PAS fermé

Rien du mandat. Les trois fermetures sont portées, et le découpage du pilote
tient : les trois sont réellement indépendantes, aucune n'a eu besoin d'une
mesure de l'autre. **Le seul reproche à ce découpage est qu'il ne prévoyait pas
que la troisième soit la plus dangereuse** — c'est celle qui a produit les deux
faux verts, et elle est la seule dont l'échec silencieux se paye sur un dépôt
public.

Restent ouverts, et hors mandat : le reranker non conforme sous `rerank_model`,
qu'aucun garde d'affectation ne voit (§4.32), et la forme d'affectation
**construite par morceaux**, qui reste tolérée et bornée dans le garde.

---

### 4.37 → Le lot 7 livré : trois fermetures, quatre faux verts trouvés par le lot, et deux antécédents que le pilote avait INVENTÉS

> **POURQUOI CETTE SECTION N'EST PAS SUR `main`, et c'est le garde neuf appliqué
> à son auteur.** Le §4.36 vit sur la branche du lot 7, non fusionnée. Porter le
> §4.37 sur `main` seul y laisserait un **TROU** — `4.35` puis `4.37` —, soit
> précisément l'une des quatre dérives que ce lot vient de rendre rougissantes.
> Le pilote a donc **retenu sa propre fusion** : ce commit reste sur
> `claude/audit-rag-agent-chat-eefc61` jusqu'à ce que le lot 7 soit fusionné,
> après quoi la suite est complète de `4.1` à `4.37`. *Le trou a été trouvé en
> relisant la queue du fichier avant d'y ajouter un numéro — la consigne écrite
> au §12 la veille, après la collision `4.34`.*

`Conv' 43` (LOT-7) a livré le 9 septembre 2026 six commits sur
`claude/lot-7-rag-agent-chat-425c4e`, rattrapés sur `main` par une **fusion** du
pilote (`c628b0a`). **Non poussés.**

#### Ce que le pilote a mesuré de ses mains

Le 9 septembre 2026 entre 10:52 et 11:20 UTC. Empreintes SHA-256 relevées avant
et après chaque mutation ; `rc` du processus, jamais derrière un tube.

| | `mesuré` |
|---|---|
| identité des six commits | auteur ET committer `florian_horellou@laposte.net` — adresse autorisée |
| désactivations ajoutées | **aucune** : zéro `skip`, `xfail`, `type: ignore`, `noqa`, `pragma` |
| `src/` | **une seule ligne de comportement** — `except (TypeError, ValueError)` devenu `except Exception` —, spécifiée ET pré-mesurée par l'audit (§4.33, trouvaille C), **justifiée au site** avec les trois autres réponses pesées et écartées, et `BaseException` explicitement non attrapé |
| conflit de fusion | `git merge-tree --write-tree main <branche>` (forme à **deux** arguments) → `rc=0`, aucun conflit |
| **la porte sur le RÉSULTAT de fusion** | `make lint` `rc=0`, `make test` `rc=0`, **682 passés** — et c'est la fusion la plus risquée du chantier, les deux derniers commits du pilote ayant édité **les deux documents que le garde neuf lit** |
| le compte annoncé | `documentation/tests.md` porte 682, concordant |

#### Le hook `pre-push`, éprouvé par de VRAIS `git push` vers un distant jetable

C'est la fermeture dangereuse, et le pilote l'a retournée dans les deux sens.

| scène | `rc` du `git push` | la ref est-elle arrivée ? |
|---|---|---|
| 5 commits, le **3ᵉ** sous une adresse professionnelle, `HEAD` conforme | **1** | **non** — et le message nomme le commit, rappelle les 165 commits réécrits, et interdit `--no-verify` |
| plage propre | **0** | oui — le hook ne refuse pas tout |
| **mutation : la plage repliée sur `HEAD`** | **0** | **OUI, avec le commit fautif** — le calcul de plage est donc porteur |
| une ligne ajoutée de forme secrète, hook intact | **1** | non |
| **mutation : le `-e` retiré des trois `grep`** | **0** | **OUI, avec la ligne de forme secrète** |

**La dernière ligne est la mesure qui compte.** Sans le `-e`, `grep` lit le motif
— qui commence par un tiret — comme une **option**, écrit « unrecognized
option » et rend `rc=2`, que le `if` lit comme faux : **le hook sortait en 0 sans
avoir rien vérifié**. Le lot l'a trouvé lui-même, et il ne l'a pas trouvé par ses
37 tests verts — il l'a trouvé par un vrai `push`. *Un `rc` juste n'est pas une
preuve d'atteinte*, et sur un hook la scène propre ne distingue pas un garde qui
marche d'un garde creux.

Et la scène de refus a été construite **hooks désarmés par un `core.hooksPath`
vide**, jamais par `--no-verify` — c'est la scène réelle : les sept commits qui
ont coûté ce dépôt sont partis avant qu'aucun hook n'existe. Le refus a bien
porté sur l'**ADRESSE** et non sur le nom, les deux identités du cas de test
portant le même nom.

#### DEUX ANTÉCÉDENTS QUE LE PILOTE AVAIT INVENTÉS, et c'est la septième occurrence de son motif — dans une robe pire

Le prompt du lot 7 annonçait deux preuves d'atteinte **disponibles dans `git`**.
Aucune des deux n'y est. `mesuré` par le lot, **reproduit par le pilote** :

| ce que le prompt affirmait | `mesuré` |
|---|---|
| « le registre à `a92e78a` porte **deux `### 4.34`** » | `git show a92e78a:… \| grep -c '^### 4\.34'` rend **1**. Et le balayage de **toute** l'histoire du fichier ne trouve **aucune** révision portant un doublon de titre |
| « va lire la **mutation M3bis** du lot 6 » | `git grep`, `git log -S`, `git log --grep` : **absente du dépôt**. Elle n'apparaît que dans les commits que le lot 7 vient d'écrire pour raconter cette correction |

**La cause est la même pour les deux, et elle est nouvelle** : le pilote a publié
comme **présent dans `git`** ce qui n'a existé que dans une **conversation**. La
collision `4.34` a bien eu lieu, mais elle a été attrapée par l'`assert` d'ancre
unique **avant** le commit — le prompt l'écrit lui-même deux paragraphes plus
loin, et n'en a pas tiré la conséquence. `M3bis` était une ligne du **rapport**
du lot 6, pas un objet du dépôt.

*Les six occurrences précédentes étaient des chiffres périmés ou déduits. Celle-ci
est un antécédent qui n'a jamais existé, et elle est plus grave : un chiffre faux
se remesure, un antécédent inventé envoie un lot chercher ce qui n'est pas là.*
**C'est exactement ce que le pilote venait d'écrire au §4.6 une heure plus tôt** :
une affirmation sans site rejouable devient fausse en silence. Il l'a écrit pour
ses propres chiffres de graphe et l'a commis sur ses propres preuves d'atteinte
dans le prompt suivant.

**Ce que le lot a fait à la place, et c'est la bonne conduite** : il a construit
la scène de doublon **à partir du document réel de `a92e78a`**, et il a **asserté
que l'histoire est propre** plutôt que de faire semblant. Il a suivi le
*mécanisme* de `M3bis` — planter la forme par `f`-chaîne — qui est bien dans le
dépôt, sous un autre nom.

**Et il a trouvé une troisième dérive réelle, datée, que le prompt n'avait pas** :
à `2bb511c` le journal annonce « prochain numéro libre : **41** » pour un maximum
consigné de **39**, en plus de sa ligne `38` en double. `mesuré` par le pilote.

#### Trois chiffres du pilote corrigés

- **`environ.get` / `getenv` : SIX sites suivis, pas cinq.** Le sixième est
  `scripts/verifier_les_ancrages.py:355`, et c'est le plus instructif : il écrit
  `env = os.environ.get` puis appelle `env("NOM", "défaut")`. **Un ALIAS**, que le
  motif du pilote — qui exigeait une parenthèse collée — ne pouvait pas voir.
  *Une forme peut échapper non par sa syntaxe mais par son indirection* ;
- **la lecture défensive : quatre natures propageaient, pas une.** `RuntimeError`,
  `OSError`, `KeyError`, `ImportError` — sur sept sondées, trois étaient déjà
  absorbées. Le prompt en nommait une ;
- **la ligne 7 du plan de lots** portait ces deux chiffres du pilote et a été
  laissée intacte par le lot, délibérément, parce que cette cellule porte le
  statut de fusion que le pilote pose. Corrigée par le pilote avec cette section.

#### Les quatre faux verts que le lot a trouvés contre lui-même

1. **une seconde direction décorative** : rendre les guillemets facultatifs dans
   le motif `setattr` laissait la batterie **entièrement verte**, aucun des cinq
   récits ne mettant le nom du réglage à côté de sa valeur. Trois récits ajoutés,
   la mutation rejouée rougit ;
2. **le `-e` du `grep`**, mesuré ci-dessus ;
3. **le hook refusait le commit qui l'introduit** — une alternative de secret
   écrite en clair se reconnaissait elle-même. Invisible à 37 tests verts,
   trouvée par un vrai `push`. Le commit non poussé a été réécrit, ce que le
   message de refus du hook prescrit lui-même ;
4. **et sa propre correction du point 3 visait la mauvaise cause** : la mutation
   qui devait reproduire le défaut est **revenue verte**, prouvant que
   l'assemblage n'y était pour rien. La vraie cause était une alternative
   redondante ; l'assemblage a été **retiré** plutôt que gardé sur un motif faux.

*Un lot qui trouve quatre faux verts chez lui et écrit les quatre est un lot
crédible. C'est aussi un lot dont la densité de défauts est mesurée, et c'est ce
qui décide de la suite.*

#### Ce que le lot rend au pilote sur son découpage

« Il tient, mais il ne prévoyait pas que la troisième fermeture soit la plus
dangereuse : c'est elle qui a produit trois des quatre faux verts, et la seule
dont l'échec silencieux se paye sur un dépôt public. Si vous refaites une série
de trois, mettez le garde-fou d'identité **en premier**, pas en dernier. » *Retenu
et consigné : on ordonne une série par le coût de l'échec, pas par la difficulté
apparente.*

#### Décision du pilote

**Audit indépendant requis — `Conv' 44`, dixième audit du chantier.**

Le critère amendé du §4.18 exempte le changement de `src/`, et il est bien
exempté : une ligne, spécifiée et pré-mesurée par l'audit qui l'a exigée,
vérifiée dans les deux sens. **Mais ce lot ajoute 199 lignes de garde-fou qui
s'exécute à chaque poussée, et le critère ne parle que de `src/`.** Or l'esprit du
critère — des yeux indépendants sur du code neuf qui porte la sûreté —
s'applique ici avec **plus** de force : la panne de ce hook est **silencieuse**
(sur un dépôt propre, un hook creux et un hook juste rendent le même `rc=0`),
elle protège contre la faute qui a **détruit ce dépôt une fois**, et le lot y a
lui-même trouvé trois faux verts sur quatre.

*Neuf audits de ce chantier ont trouvé quelque chose neuf fois. Fusionner le
premier garde-fou d'identité de l'histoire de ce dépôt sans lecteur indépendant
serait le seul pari du chantier, et il porterait sur son artefact le plus cher.*

---

### 4.38 → L'audit du lot 7 : UNE bloquante, et c'est le sinistre de ce dépôt qui passe en silence

`Conv' 44` (AUDIT-7) a rendu son rapport le 9 septembre 2026 — **dixième audit du
chantier**. Une bloquante, six non bloquantes, recommandation « fusionner après
correction ». **Le pilote refuse la fusion en l'état** : la bloquante porte sur le
seul axe de ce hook dont la panne est irréversible.

#### La bloquante, reproduite par le pilote — et c'est LE sinistre, à l'identique

**Site** : `scripts/git-hooks/pre-push:157`, la branche « ref neuve » :
`plage=$(git rev-list "$sha_local" --not --remotes="$distant")`.

`--remotes=<distant>` n'interroge pas le distant : il lit `refs/remotes/<distant>/*`,
un **cache local**. Dès que ce cache est périmé, tout commit atteignable depuis
lui est retiré de la plage **alors qu'il n'est pas chez le distant**.

`mesuré` par le pilote le 9 septembre 2026, dépôts jetables, hook **INTACT** —
aucune mutation, c'est la scène qui suffit :

| | |
|---|---|
| histoire fabriquée | 10 commits, dont **7** sous une adresse non autorisée, poussés, refs de suivi à jour |
| le sinistre | le distant est **détruit et recréé vide** — `git ls-remote` rend 0 ref ; la ref de suivi **locale survit** |
| ce que le hook vérifie | **0 commit** |
| ce qui part réellement | **10 commits** |
| `rc` du `git push` | **0** |
| ce qui arrive chez le distant recréé | **7** commits sous l'adresse non autorisée, 3 conformes |

**Ce n'est pas une scène d'école.** Ce dépôt a été détruit et recréé sur GitHub —
`created_at = 2026-08-28` quand son plus ancien commit date du 2026-04-30 — et
c'est précisément l'incident que ce hook existe pour empêcher de se reproduire.
Sous cette séquence exacte, **le garde ne contribue rien, et il est muet au
succès par conception.**

La branche « ref existante » (`$sha_distant..$sha_local`) est saine : `sha_distant`
vient de la négociation réelle avec le distant, pas d'un cache.

**Et ce qui décide de la cote : le lot ÉPINGLE ce comportement comme correct.**
`test_installation_des_garde_fous.py:1435`,
`test_une_ref_neuve_ne_fait_pas_verifier_tout_l_historique`, pose un commit non
conforme, puis fait `update-ref refs/remotes/origin/principale` dessus sous le
commentaire *« Le distant connaît ce commit : on le lui déclare comme git le
ferait »*, et **exige `rc=0`**. Or `update-ref` n'est pas git qui déclare : c'est
le test qui **affirme une fiction**. Le commit n'a jamais été poussé. La cécité du
garde n'est donc pas un oubli — elle est **gardée par un test vert**.

**Huitième occurrence de la forme dominante de ce chantier** : un garde vert sous
une scène que le défaut ne rencontre jamais. Et la première où le test qui devrait
la révéler est celui qui la consacre.

*Le compromis que le lot défend — ne pas refuser les commits antérieurs au garde —
est légitime, et le pilote ne le conteste pas. Il s'obtient sans ce trou : en
bornant sur l'**état réel du distant** (`git ls-remote`) ou sur un commit
d'époque, plutôt que sur un cache. Et si la décision est de ne pas couvrir la ref
neuve, alors la **borne doit être écrite au site et REMPLACER le test qui affirme
l'inverse.***

#### Ce que l'audit a établi et qui tient — il faut l'écrire aussi

- **le montage atteint le hook**, et l'auditeur l'a vérifié de bout en bout : les
  **trois** types armés, `.legacy` sous le framework, et la couche survit à une
  poussée depuis un **arbre de travail secondaire dont `.pre-commit-config.yaml`
  a été retiré** — `rc=1`, ref jamais arrivée. C'est la démonstration que la
  couche est bien **inconditionnelle**, ce que l'en-tête de l'installeur
  affirmait sans le prouver ;
- **l'ordre inversé du montage est vu** : `rc=1`, cause nommée pour les trois
  types. `make install` constate donc son propre résultat ;
- **`stdin` traverse le framework** — vérifié dans la source installée de
  `pre-commit` 4.6.2, `_run_legacy` relisant les octets et propageant le refus ;
- **multi-refs atomique** : une ref propre et une fautive, **dans les deux
  ordres**, `rc=1` et **aucune** des deux n'arrive ;
- **fail-closed** sur `rev-list` en échec, sur champ vide, et sur poussée par URL ;
- **le garde de numérotation a déjà du mordant sur une situation VIVANTE** : la
  branche du pilote à `2dad45f` porte un **trou en 4.36**, et le garde le voit.
  *La retenue de fusion que le pilote tenait à la main devient mécanique* — c'est
  le meilleur argument pour cette fermeture ;
- **la scène construite du doublon de titre vaut** : plantée par programme sur le
  document réel de `a92e78a`, et le test asserte qu'elle ne déclenche **que** la
  règle du doublon, donc son rouge est discriminant. C'est la bonne réponse à une
  histoire propre — et l'auditeur a confirmé cette propreté sur les **95**
  révisions du registre ;
- **`retriever.py` tient dans les deux sens**, et l'auditeur a cherché une
  huitième nature d'exception : il a trouvé `asyncio.CancelledError`, qui
  **traverse** — et c'est juste, une annulation doit propager. *Il cherchait un
  trou et a trouvé un choix.*

#### Les six non bloquantes, et trois sont des directions décoratives

- **le scope du « prochain numéro libre » n'est gardé par rien.** L'auditeur l'a
  prouvé porteur en **remontant le récit du §12 au-dessus du §6.1** sur une
  copie : le garde lit alors **41** — le faux nombre de la faute du 8 septembre —
  au lieu de 44. Le commentaire du site affirme que le scope est ce qui protège ;
  aujourd'hui c'est l'**ordre du fichier** ;
- **le motif `environ.get` n'a jamais reçu son récit.** Le lot a trouvé lui-même
  que rendre les guillemets facultatifs sur `setattr` laissait tout vert, et a
  ajouté le récit qui l'attrape — mais **le motif jumeau, ajouté dans le même
  commit, est resté sans le sien**. Direction réelle : une phrase de rapport sans
  guillemets reste verte sous le motif livré et devient **rouge** sous la
  mutation, ce qui est le sens dangereux ;
- **trois bornes du motif `setattr` sont inertes** : la fenêtre de 80, la classe
  `[^)]` et la virgule. Et l'auditeur a répondu à la question que le prompt
  posait — *ce que la permission du retour à la ligne ouvre d'autre* : **rien,
  parce que `[^)]` l'en empêche**, la parenthèse fermante bornant la traversée.
  C'est la bonne réponse, et **rien ne la garde** : `[^)]` remplacé par `[\s\S]`
  confond deux instructions et reste vert ;
- **la forme aliasée échappe, et sa surface est de 8 appels pour 1 occurrence.**
  `scripts/verifier_les_ancrages.py:355` écrit `env = os.environ.get` puis appelle
  `env(…)` **huit** fois. L'auditeur a balayé : c'est la **seule** indirection du
  dépôt. *Une forme peut échapper par son indirection et non par sa syntaxe* ;
- **`generated (with|by) \[` n'est pas ancré en tête de ligne**, contrairement aux
  trois autres alternatives, donc un message de commit qui **raconte** la forme
  est refusé — et les deux seules sorties sont `--no-verify`, que ce chantier
  interdit, ou le retrait du garde. *C'est mot pour mot le défaut que le lot a
  corrigé dans `e42d3e6` pour le motif de secret, une ligne plus bas.* Latent :
  zéro message de l'histoire ne le déclenche ;
- **une panne totale et silencieuse à un caractère près** : sans retour à la ligne
  final sur l'entrée standard, `read` rend non-zéro en `dash`, la boucle ne tourne
  pas, et le hook rend `rc=0` sans rien vérifier. Non exploitable aujourd'hui —
  l'auditeur a relevé le `\n` au mouchard `od -c` sur **cinq** formes de poussée —
  mais non gardé.

#### La faiblesse STRUCTURELLE de cette fermeture, et c'est ce qui manquera le plus

**Le harnais du lot n'exécute jamais `git push`.** `_pousse` lance
`sh .git/hooks/pre-push.legacy` directement, avec une entrée standard **fabriquée
à la main**. La batterie ne prouve donc ni que git atteint le montage, ni **l'état
du distant** — la seule preuve qui compte pour un hook de poussée. Ces deux
preuves n'existent que dans les mesures ponctuelles du pilote et de l'auditeur,
**hors du dépôt** : rien ne les retiendra. *C'est exactement ce que le §4.6
reproche au pilote pour ses chiffres de graphe, transposé au banc d'essai.*

Et un **risque latent** à nommer au site : `pre_commit/commands/hook_impl.py:36`
porte `if hook_dir is None:  # git 2.54+ hooks`, chemin sur lequel la couche
`.legacy` **n'est jamais exécutée**. Git est ici en **2.53.0** et le `hook-tmpl`
passe toujours `--hook-dir`, donc le montage est sain — mais le seul rempart
« valable pour toute branche » de ce dépôt dépend d'une branche de code que la
version suivante de git active, et la panne serait muette.

#### Trois chiffres, et le pilote en porte un

- **« onze doublons et un trou de 7 à 20 »** — commentaire du scope du garde de
  numérotation, **repris tel quel par le pilote dans le prompt de l'audit**.
  `mesuré` par l'auditeur **et reproduit par le pilote**, sur la suite que le
  commentaire écrit lui-même : **5** doublons, et le trou est **8 à 19**, `7` et
  `20` étant tous deux présents. Le mécanisme est juste et le scope est
  nécessaire ; **les deux nombres sont faux**, sous l'étiquette `mesuré` ;
- **« sept natures sondées »** contre les **six** que le test énumère. Le fichier
  de test nomme bien **sept** types distincts — trois absorbés, quatre
  propageant — mais sa propre phrase écrit 4 + 2. *Quatrième occurrence de « deux
  écritures justes sous des définitions différentes », et cette fois les deux
  vivent dans le même fichier* ;
- **« 47 `setattr` dans 7 fichiers »**, chiffre du pilote, que l'auditeur n'a pas
  retrouvé (il mesure 391/32, 108/17, 27/1 selon la lecture). **Reproduit par le
  pilote sous deux lectures concordantes** — `git grep -c 'setattr(settings'` et
  `git grep -cE 'setattr\(\s*settings'` rendent l'un et l'autre **47 dans 7
  fichiers**. Le chiffre tient ; **ce qui manquait est sa COMMANDE**, et c'est la
  règle de ce chantier depuis le début : *chaque chiffre porte sa commande, sa
  date et son étiquette.* Un chiffre juste sans sa commande est irréfutable et
  invérifiable à la fois — c'est-à-dire inutile.

#### Une leçon de méthode que l'auditeur a écrite contre lui-même, et elle vaut

Son premier balayage de l'histoire du registre rendait un doublon `### 4.23` sur
21 révisions. C'était **son regex** : la forme réelle est `### 4.23 bis`, avec une
**espace**, et son `(-bis)?` capturait le préfixe deux fois. *Un faux rouge, trouvé
en ouvrant le fichier.* Et sa première sonde de la scène « plage repliée sur
`HEAD` » a rendu le bon `rc` pour la mauvaise raison — la ref distante n'existant
pas encore, le hook prenait la branche « ref neuve ». **La scène n'atteint son cas
qu'avec une ref distante préexistante, et l'ordre des gestes n'était écrit nulle
part.**

#### Décision du pilote

**Ne pas fusionner en l'état. Un lot de réparation — `Conv' 45`.**

Les fermetures **(a)** et **(b)** sont solides et pourraient partir telles quelles ;
elles restent sur la branche parce qu'un lot se fusionne d'un bloc. La bloquante
est petite à réparer et immense à laisser : *le seul garde-fou de ce dépôt contre
la faute qui l'a détruit une fois est aveugle à la séquence exacte de cette
destruction, et un test vert dit que c'est normal.*

---

### 4.39 → La réparation du lot 7 : la bloquante fermée par un VRAI `git push`, et trois chiffres du chantier remesurés

`Conv' 45` (REPAR-8) a livré le 9 septembre 2026 sur la branche du lot,
`claude/lot-7-rag-agent-chat-425c4e`. **697** passés sur **43** fichiers,
`rc=0` / `rc=0`, **non poussés**. La bloquante du §4.38 est fermée, les six
resserrements aussi, les trois chiffres corrigés — et **trois faux verts trouvés
contre lui-même**, plus **deux affirmations du chantier démenties par la mesure**.

#### La bloquante : la borne d'une ref neuve, et la preuve est l'ÉTAT DU DISTANT

Le sinistre a d'abord été **reproduit hook intact**, avant toute réparation. Puis
la même scène a été rejouée sur le hook réparé. Les deux mesures, `git push`
réel, dépôts jetables, `mesuré` le 9 septembre 2026 :

| | hook livré | hook réparé |
|---|---|---|
| commits que le hook vérifie | **0** | **10** |
| `rc` du `git push` (processus) | **0** | **1** |
| refs chez le distant après coup | **1** | **0** |
| commits arrivés | **10** | **0** |
| adresses arrivées | **7** non autorisées + 3 conformes | **aucune** |

La cause : `--not --remotes=<distant>` lit `refs/remotes/<distant>/*`, un cache
local que la destruction-recréation du distant rend menteur. La borne est
désormais `git ls-remote` — l'état RÉEL.

**Trois autres formes ont été pesées et écartées au site**, et la première
mérite d'être retenue par le chantier : *un **commit d'époque** en dur — local,
déterministe, sans réseau, et il exprime littéralement le compromis défendu —
**ne ferme pas le sinistre**, les commits fautifs de la scène étant antérieurs à
l'époque, donc exclus.* Une borne qui laisse passer l'incident qu'elle documente
n'est pas une borne. Les deux autres : rafraîchir `refs/remotes/` par un `fetch`
préalable (c'est encore le cache, avec une course en plus), et ne rien exclure
du tout (écarté pour la seule latence).

Le repli quand `ls-remote` échoue n'exclut **rien** — donc vérifie plus, jamais
moins — et il se **dit** sur `stderr`, seul endroit où ce hook parle sans
refuser : une borne dont on ne sait plus si elle a servi redevient la cécité
qu'on vient de fermer. Un `timeout 30` extérieur borne l'appel, un hook qui pend
étant un hook qu'on désarme.

**Le test qui épinglait la cécité comme correcte est REMPLACÉ, pas relâché.** Il
déclarait par `update-ref` que le distant connaissait un commit jamais poussé —
une fiction. Deux tests le remplacent, et l'un d'eux **replante la fiction
exprès** pour asserter qu'elle ne borne plus rien.

**Et la borne légitime reste éprouvée par un vrai `git push`** : une branche
neuve dont l'histoire ancienne — non conforme — est *réellement* chez le distant
passe, `rc=0`, et arrive entière. Sans ce sens, la réparation aurait remplacé un
trou par un garde qu'on arrache.

#### La faiblesse STRUCTURELLE est fermée, et c'est ce que le §4.38 annonçait comme le plus regrettable

`TestLaPousseeEstGardeeParUnVraiGitPush` — cinq tests — monte un dépôt par
**l'installeur livré** (donc la couche `.legacy` sous le framework), crée un
distant `--bare` local, appelle `git push`, et lit le verdict sur **deux axes** :
le `rc` du processus **et ce que le distant porte réellement**. Deux mutations
prouvent qu'elle atteint : un hook rendu creux (`exit 0`) et un installeur qui
n'arme plus `pre-push` la font rougir tous les deux sur trois tests.

Un de ses tests garde son propre coût : **aucune URL distante ne sort de la
machine**, sans quoi `ls-remote` pourrait pendre 30 s par test et la porte
deviendrait inutilisable. Sa première écriture s'est reconnue elle-même — les
schémas écrits en littéral — puis a débordé sur la classe suivante : *deux faux
rouges dans le seul test qui garde le coût,* et les schémas sont désormais
assemblés à l'exécution.

**Le risque latent est nommé au site** : `pre_commit/commands/hook_impl.py:36`
porte `if hook_dir is None:  # git 2.54+ hooks`, chemin sur lequel `.legacy`
n'est jamais exécutée. Git est ici en **2.53.0** (`mesuré`, `git --version`) et le
`hook-tmpl` passe toujours `--hook-dir` : le montage est sain, mais le seul
rempart « valable pour toute branche » de ce dépôt dépend d'une branche de code
que la version suivante de git active, et la panne serait muette.

#### Les six resserrements, et deux affirmations du chantier démenties

- **la panne à un caractère près** est fermée : sans retour à la ligne final,
  `read` rendait non-zéro et le hook sortait en `rc=0` **sans rien vérifier**.
  `mesuré` : **0** tour de boucle. *Et ce n'est pas une particularité de `dash`,
  contrairement à ce que le §4.38 supposait — `bash` rend le même 0.* C'est le
  comportement POSIX de `read`. Le harnais ne pouvait pas le sonder,
  `_ligne_de_poussee` ajoutant toujours le `\n` ; la ligne est donc construite
  sans lui, explicitement ;
- **la ligne de signature n'était pas ancrée** : les trois phrases de récit ET la
  forme nue étaient toutes les quatre refusées. Après ancrage, les récits passent
  et la forme reste refusée, indentée comprise. C'était mot pour mot le défaut de
  `e42d3e6`, une ligne plus bas — *le trouver deux fois dans le même motif dit
  que « chaque alternative porte sa borne » doit être gardée, pas relue* ;
- **cinq bornes des motifs réflexifs étaient inertes**, et non trois : les
  guillemets et la virgule sur `environ.get`, la classe `[^)]`, la fenêtre de 80
  et la virgule sur `setattr`. Cinq récits les tiennent, verts sous le motif
  livré et rouges sous leur mutation, et la **distance** de la fenêtre est
  mesurée dans le test plutôt que supposée ;
- **la forme aliasée est fermée par une LECTURE et non par un élargissement.**
  L'élargissement à `\w+\s*\(` a été écarté comme spéculatif ; à la place, les
  liaisons réelles d'un nom à `environ.get`/`getenv`/`setattr` sont relevées, et
  un motif n'est engendré que pour elles. **La borne est écrite** : un alias reçu
  en argument ou reconstruit par `getattr` n'est pas vu, cela demanderait de
  suivre les données ;
- **le scope du garde de numérotation** est désormais porteur, et la phrase qui
  le justifiait était fausse : ce qui protégeait était **l'ordre du fichier**. La
  discrimination porte sur la FORME de la ligne d'autorité, et l'ambiguïté rend
  `None` au lieu de trancher — *choisir la première est le geste même qui a
  produit la faute du 8 septembre.*

#### Les trois chiffres, et deux d'entre eux portent sur le pilote

- **« onze doublons et un trou de 7 à 20 »** : confirmé faux. `mesuré` sur la
  suite que le commentaire écrit lui-même — **5** doublons, trou de **8 à 19**,
  `7` et `20` tous deux présents. Le §4.38 avait raison ;
- **« sept natures sondées » contre « six »** : **les deux comptes sont exacts**,
  sous deux définitions, et le fichier de test en nomme **neuf** en tout. Ce
  n'étaient pas les comptes qui étaient faux, c'était leur silence sur leur
  définition — les trois sont désormais écrites aux deux sites. **Mais une phrase
  du commentaire des six natures était, elle, FAUSSE**, et ni le lot ni son audit
  ne l'avaient vue : `NotImplementedError` dérive de `RuntimeError`, donc
  l'`except (TypeError, ValueError)` ne l'attrapait pas. Sonde rejouée : **CINQ**
  des six propageaient, **une** seule était absorbée — par le `default` de
  `getattr`, jamais par l'`except`. *Une sous-classe lue comme une classe sœur* ;
- **`asyncio.CancelledError`** est nommée au site. Elle traversait déjà, et c'est
  juste, mais elle ne le devait à rien d'écrit ni d'éprouvé — seulement à sa
  dérivation de `BaseException` (`vérifié`, `__mro__` sous Python 3.12.13).
  *Un choix juste que rien ne garde est un choix qu'un lot suivant défait.*
  **Précision contre le cadrage** : `node_rerank` est un nœud **synchrone**, même
  si le graphe est piloté par `ainvoke`/`astream` — l'annulation arrive d'abord
  sur la coroutine qui attend. Raison de garder la propriété maintenant, pas de
  l'omettre.

#### Et le chiffre du pilote : il est juste, et sa PORTÉE était fausse

**« 47 `setattr` dans 7 fichiers »**, annoncé « sur les fichiers suivis ». Or
« les fichiers suivis » est `_fichiers_suivis()`, c'est-à-dire `git ls-files` —
tout le dépôt, documentation comprise — et cette lecture n'a **jamais** rendu
47/7. **L'auditeur avait raison de ne pas le retrouver.** Huit révisions
balayées ; une seule lecture le rend :

```bash
git grep -c 'setattr(settings' main -- src tests scripts   # -> 47 lignes / 7 fichiers
```

Les **deux** commandes que le §4.38 donnait comme concordantes rendent, elles,
**59 / 10** l'une et l'autre sur cette branche. Le chiffre était donc exact sous
une portée — `main`, restreint au code — et l'étiquette le donnait sous une
autre. *Un chiffre juste dont la portée est fausse est aussi invérifiable qu'un
chiffre faux.* Le §4.38 concluait que « ce qui manquait est sa commande » ; il
manquait aussi **sa portée**, et la « reproduction sous deux lectures
concordantes » ne tenait pas. Le nombre n'est **pas** remonté : le compte n'est
pas le sujet, la vivacité de la forme l'est, et un plancher la tient.

Même défaut dans le même commentaire pour **« 6 sites suivis »** d'`environ.get` :
le chiffre est exact sous `-- src scripts tests/integration`, pas sous les
fichiers suivis (qui rendent 18/4). **Et le sixième de ces six n'est pas un appel
du tout** : c'est la liaison `env = os.environ.get` de
`scripts/verifier_les_ancrages.py`. *Le relevé qui justifiait le motif contenait
déjà la forme qui lui échappait, et personne ne l'avait lu comme telle.*

#### Les trois faux verts que ce lot a trouvés contre lui-même

- **M-8** : retirer le scope de `prochain_numero_annonce` laissait les **17**
  tests du fichier verts — l'ancrage sur la forme suffisait au document
  *courant*, donc le scope était devenu inerte. La scène manquante est une
  seconde ligne d'autorité **hors** du §6.1 : *la forme protège du dedans, le
  scope du dehors*, et chacun a maintenant sa mutation ;
- **M-g** : retirer l'ancrage de fin de ligne de la liaison d'alias laissait les
  **27** tests verts. Sans lui, toute ligne d'appel direct enregistre sa cible
  comme un alias. « Un appel n'est pas une liaison » est devenu un sens du test ;
- **M-j** : retirer `NotImplementedError` des six natures laissait les **16**
  tests verts. Une liste FERMÉE qui rétrécit ne fait rougir personne. Un plancher
  la garde — et la distinction est écrite : *un inventaire d'occurrences grandit,
  et un garde qui rougit sur l'événement normal enseigne « monter le chiffre »
  (§4.35) ; une liste raisonnée de sondes, non.*

#### Ce qui n'est pas fermé, et le dit

- **la valeur du `timeout 30`** du `ls-remote` n'est gardée par aucune mutation :
  la faire passer à 25 laisse tout vert. C'est un réglage de latence, pas un axe
  de sûreté, et l'éprouver demanderait un distant qui pend — donc une attente
  réelle dans la porte. Borné par écrit plutôt que gardé ;
- **la couche `.legacy` sur git 2.54+** n'est pas éprouvée, et ne peut pas
  l'être : le chemin de code n'existe pas sous la version installée. Nommée au
  site, à remesurer à la montée de git.

#### Le trou de numérotation est fermé par la fusion, et non par un numéro de plus

Les §4.37 et §4.38 vivaient sur `claude/audit-rag-agent-chat-eefc61`, le §4.36
sur la branche du lot : **chacune des deux portait un trou que l'autre
comblait**, et c'est pour cela que le pilote retenait sa fusion. Les porter
ensemble était la seule façon de ne pas laisser sur `main` la dérive même que ce
lot rend rougissante. Le garde le confirme : **aucun trou, aucun doublon** sur
les deux documents.

*Et la ligne 45 du journal existait avant que ce lot ne livre : elle est mise à
jour, pas ajoutée. Le pilote a produit deux collisions de numérotation en deux
jours ; relire la queue du fichier avant d'y écrire un numéro est ce qui les
évite.*

---

### 4.40 → FERMÉ — le lot 7 fusionné : ce dépôt a enfin un garde-fou sur `push`, et le sinistre ne repasse plus

`Conv' 45` (REPAR-8) a livré le 9 septembre 2026. **Fusionné dans `main` par le
pilote : `71dfea8`.** Livré (`Conv' 43`), audité (`Conv' 44`, une bloquante),
réparé (`Conv' 45`).

#### La mesure qui décidait, refaite par le pilote — et pour un hook, la preuve est l'ÉTAT DU DISTANT

`mesuré` le 9 septembre 2026 entre 13:34 et 14:10 UTC, par de **vrais `git push`**
vers des distants jetables. La scène du sinistre, à l'identique des deux côtés :

| | hook livré | hook réparé |
|---|---|---|
| commits que le hook vérifie | **0** | **10** |
| `rc` du `git push` | **0** | **1** |
| refs chez le distant recréé | 1 | **0** |
| adresses arrivées | **7 non autorisées** + 3 conformes | **aucune** |

Et le refus nomme le commit fautif. **La borne légitime survit** — vérifiée
séparément : une branche neuve dont l'histoire ancienne, non conforme, est
**réellement** chez le distant passe en `rc=0` et arrive entière. *Le compromis
que le lot défendait est préservé, et le trou est fermé.*

**Un faux résultat du pilote, et il l'écrit.** Sa troisième direction — le repli
fail-closed sur distant injoignable — a rendu **`rc=128`**, qu'il a d'abord lu
comme le repli. C'est **git qui échoue avant le hook**, l'URL ne se résolvant
pas : la sonde n'atteignait pas son cas. *Cinquième fois dans ce chantier qu'un
`rc` juste vient de la mauvaise raison.* Le repli est couvert par la batterie,
qui asserte la présence de son message dans `stderr` — la seule preuve
d'atteinte possible pour un chemin que `git push` ne peut pas déclencher
localement.

**La borne neuve** est `git ls-remote` — l'état réel, demandé, jamais relu d'un
cache — avec un `timeout` extérieur et un repli qui **n'exclut rien**, donc
vérifie plus. Trois autres formes sont pesées et écartées au site, dont le
**commit d'époque** : local et déterministe, mais *il ne fermait pas le
sinistre*, les commits fautifs y étant antérieurs. **Et la justification de
l'ancienne borne était fausse** : « un refus certain sur 184 commits » — mesuré,
la plage non bornée traverse **282 commits et 84 396 lignes en 10,1 s pour 0
refus**, l'histoire ayant été réécrite. *Le coût d'une plage ouverte est de la
latence, pas un refus.*

**Le test qui épinglait la cécité est REMPLACÉ, pas relâché** — et l'un de ses
remplaçants **replante la fiction `update-ref` exprès**, pour asserter qu'elle ne
borne plus rien. C'est la bonne façon de retirer un test qui affirmait le
contraire de la mesure.

#### Le garde-fou est armé, et la poussée suivante l'a traversé

`make install` depuis le clone principal, `rc=0` : `pre-push` et
`pre-push.legacy` apparaissent pour la **première fois** de l'histoire de ce
dépôt, à côté des quatre hooks préexistants. **La poussée de `71dfea8` — 19
commits — a été vérifiée par git et non par la main du pilote.** Les onze
poussées précédentes l'avaient été à la main ; celle-ci est la première dont la
protection ne repose plus sur la mémoire de qui la fait.

Porte sur le résultat de fusion, dans le clone principal avec son propre
`.venv` : `make lint` `rc=0`, `make test` `rc=0`, **697 passés** sur **43**
fichiers.

#### HUITIÈME OCCURRENCE DU MOTIF DU PILOTE, ET C'EST LA PLUS COURTE À RACONTER

Le §4.38 diagnostiquait, à propos de « 47 `setattr` dans 7 fichiers » : *« ce qui
manquait est sa COMMANDE »*. Il a alors écrit la commande. **Elle ne reproduit
pas le chiffre.**

| lecture | résultat |
|---|---|
| la commande **telle qu'écrite au §4.38**, sans limitation de portée | **52 dans 9 fichiers** |
| la commande **réellement tapée** lors de la mesure, avec `-- '*.py'` | **47 dans 7 fichiers** |

La différence est la portée : sans elle, `git grep` compte aussi les mentions en
**prose** dans les documents de pilotage. Le chiffre est juste, la commande
publiée est fausse, et **la faute a été commise dans la section même qui la
diagnostiquait**. *Un chiffre sans commande est invérifiable ; un chiffre avec une
commande qui ne le rend pas est pire — il donne l'apparence de la vérifiabilité.*
La réparation l'a mesuré et corrigé au site.

#### Quatre affirmations du chantier démenties par la mesure, et le pilote en portait trois

- **« `read` rend non-zéro en `dash` »** — ce n'est pas propre à `dash`. `mesuré` :
  une entrée sans retour à la ligne final rend **0 tour de boucle** en `sh`, en
  `dash` **et en `bash`**. C'est le comportement **POSIX** de `read` ;
- **« sept natures contre six, deux écritures justes sous des définitions
  différentes »** — le cadrage du pilote a nommé cette famille trop tôt, et **elle
  masquait une phrase fausse à côté** : le commentaire affirmait que deux natures
  étaient absorbées, or `NotImplementedError` dérive de `RuntimeError`, donc
  **cinq des six propageaient et une seule était absorbée**. `vérifié` par le
  pilote : `NotImplementedError.__mro__` passe par `RuntimeError`, et
  `issubclass(NotImplementedError, (TypeError, ValueError))` rend `False`. Ni le
  lot, ni son audit, ni le pilote ne l'avaient vue ;
- **« `node_rerank` dans un graphe async »** — le nœud est **synchrone**
  (`def node_rerank(state)`), c'est le graphe qui est piloté par `ainvoke`.
  L'annulation arrive d'abord sur la coroutine qui attend ;
- et **une affirmation du pilote sur l'état de son propre poste** : le prompt
  disait l'arbre de l'auditeur retiré, la réparation l'a dit encore monté. `mesuré`
  après coup : **c'est la réparation qui se trompe** — l'arbre encore présent était
  celui du **pilote**, à `9fdd913`, et celui de l'auditeur avait bien été retiré.
  *Une correction peut être fausse ; elle reste bonne à faire.*

**Et la leçon de méthode que la réparation rend au pilote, qui est la plus utile
de la journée** : *« une famille de défaut nommée trop tôt fait chercher la
famille au lieu du défaut. »* Le cadrage annonçait « deux écritures justes sous
des définitions différentes », et la réparation a failli trancher une définition
et refermer sans mesurer. C'est la sonde rejouée qui a trouvé la phrase fausse.
**Consigné : un cadrage nomme le SITE et le MÉCANISME, il ne pré-classe pas la
famille.**

#### Ce que la réparation a trouvé contre elle-même

Trois faux verts — le scope de la ligne d'autorité inerte (17 tests verts sous sa
mutation), l'ancrage de fin de ligne du résolveur d'alias (27 verts), et une
**liste fermée qui rétrécit sans faire rougir personne** (16 verts) —, trois faux
rouges dans le test qui garde le coût, et un **incident de harnais** : son
`restaurer()` faisait `git checkout -- .`, qui a effacé une réparation **non
commitée**. *C'est l'`assert` d'empreinte qui l'a dit*, et le harnais restaure
désormais depuis une copie. **Quatrième lot de suite à trouver ses propres faux
résultats et à les écrire.**

#### Le bilan du lot 7

**Trois fermetures.** Le garde de sûreté voit désormais les formes réflexives et
la forme **aliasée** ; les deux documents de pilotage ont un garde de
numérotation qui a **déjà du mordant sur une situation vivante** — il a confirmé
la fermeture du trou `4.36` que les deux branches se comblaient l'une l'autre ;
et ce dépôt a un `pre-push` qui refuse sur l'**ADRESSE**, éprouvé par de vrais
`git push` avec l'état du distant asserté, dans une classe de tests qui garde son
propre coût.

**Ce qui reste ouvert et nommé au site** : la valeur du `timeout 30`, bornée par
écrit et non gardée — l'éprouver demanderait un distant qui pend ; et la couche
`.legacy` sous **git 2.54+**, dont le chemin de code n'existe pas en 2.53.0, à
remesurer à la montée de version. *Les deux sont des pannes muettes, et c'est
pourquoi elles sont écrites plutôt que supposées absentes.*

### 4.41 → Le lot 4 livré : la couverture passe de 71 % à 98 % pour ZÉRO point de rappel, et l'agent en service est cinq lots en retard

**LE RÉSULTAT PRINCIPAL EST NÉGATIF, ET C'EST LE PLUS UTILE DES DEUX.** La
réserve 2 du §4.6 demandait ce que l'encadrement **rapporte**, et non ce qu'il
couvre. La réponse est mesurée, sur les deux instruments, et elle est nette : la
définition (C) porte la couverture de **71,2 % à 98,0 %** des éléments servis
(direction « avant ») et de **67,6 % à 95,5 %** (« après »), et **elle ne gagne
aucun point de rappel**.

`mesuré` le 10 septembre 2026, `make eval` sur les 138 questions du jeu de
réglage, `rc=0`, contre l'antécédent **versionné** `runs/2026-09-08-reference.json`
— comparaison **appariée** :

| métrique | avant | après | Δ apparié, IC 95 % |
|---|---|---|---|
| `rappel_recherche` | 0,962 | 0,962 | **+0,0000** [+0,000, +0,000], 130 ex æquo sur 130 |
| `rappel_elements` | 0,954 | 0,954 | **+0,0000**, 130 / 130 |
| `rang_reciproque` (mrr) | 0,942 | 0,942 | **+0,0000**, 130 / 130 |
| `rappel_documents` | 1,0 | 1,0 | **+0,0000**, 130 / 130 |
| `rappel_contexte` | 0,946 | 0,946 | **+0,0000**, 130 / 130 |
| `taux_citation_complete` | 1,0 | 1,0 | **+0,0000**, 129 / 129 |
| `taux_contexte_utile` | 0,273 | 0,279 | +0,0062 [+0,001, +0,013], **p=0,109** |
| `part_utile_caracteres` | 0,281 | 0,290 | +0,0097 [+0,001, +0,019], **p=0,850** |
| `caracteres_retenus` ↓ | 9 529 (p50) | 10 633 (p50) | **+914,6** [+777, +1 060], **p=0,000** |

**Les six métriques de rappel sont IDENTIQUES À LA QUATRIÈME DÉCIMALE, sur 130
questions appariées, sans une seule bascule.** Les deux métriques d'utilité
bougent de moins d'un point et le test apparié ne les distingue pas du bruit. La
seule métrique dont l'écart soit significatif est le **coût**.

#### Le prix, mesuré

| | avant | après |
|---|---|---|
| `caracteres_retenus_p50` | 9 529 | **10 633** (+11,6 %) |
| `prompt_eval_count_p50` | 3 131 | **3 291** (+5,1 %) |
| `prompt_eval_count_p95` | 3 582 | **3 800** (+6,1 %) |
| `contextes_ecartes_total` | 26 | **32** |
| `reconstruction_ms_p50` | 114 | **197** (+73 %) |
| `reconstruction_ms_p95` | 181 | **571** (+215 %) |
| `total_ms_p50` | 7 298 | 7 112 |

**`contextes_ecartes_total` est la ligne à lire.** Six contextes de plus sont
écartés avant le LLM parce que chaque source coûte désormais plus de fenêtre :
l'encadrement ne s'ajoute pas, il **évince**. `rappel_contexte` ne bouge pas —
aucun passage doré n'a été perdu sur CE jeu, à CE budget —, mais le mécanisme est
là, et un budget plus serré le paierait. `total_ms_p50` est en baisse : les
+83 ms de reconstruction disparaissent dans la génération, qui domine le total.

#### LE CRITÈRE DU §P1 EST APPLICABLE, ET IL TRANCHE

Le §P1 « Le pari central n'est pas vérifié » écrit la règle de décision et nomme
les métriques : *« Ce que le lot 4 rend décidable sans juge : le prix
(`reconstruction_ms`), le coût en contexte (`caracteres_retenus`), la composition
du contexte payé (`taux_contexte_utile`, `part_utile_caracteres`) et l'apport
propre de la fenêtre (`rappel_contexte` moins `rappel_elements`). Un rapport
prix/apport défavorable tranche sans juge ; seul un rapport favorable en demande
un. »*

**L'apport propre de la fenêtre ne bouge pas.** `rappel_contexte` moins
`rappel_elements` vaut **−0,008 avant et −0,008 après** sur le jeu de réglage —
identique. Sur le jeu de contrôle il passe de **+0,026 à +0,045**, ce qui est
dans sa propre réserve à trente questions.

**Le rapport prix/apport est donc DÉFAVORABLE sur l'instrument de référence, et
la règle du §P1 dit qu'il tranche sans juge.** Ce qui va dans l'autre sens, et
qu'il faut porter honnêtement : la **composition** du contexte payé s'améliore
un peu partout — `taux_contexte_utile` +0,006 au réglage, **+0,035** au contrôle ;
`part_utile_caracteres` +0,009 et **+0,043**. Le contexte servi est marginalement
mieux composé ; il n'est pas plus efficace.

*Cette entrée n'ôte pas le §P1 : la conclusion « défavorable » porte sur les
métriques sans juge, et le §P1 demandait aussi ce que le LLM en fait. La
fermeture est la décision du pilote.*

#### Le jeu de CONTRÔLE dit la même chose, et sa réserve reste entière

Trente questions ne tranchent pas un réglage, un écart de deux points y est du
bruit (§5 du registre de pilotage). `rappel_recherche` 0,801 → 0,801,
`rappel_elements` 0,686 → 0,686, `mrr` 0,770 → 0,770, `rappel_documents`
0,962 → 0,962 : **Δ apparié +0,0000 sur les 26 questions appariables, aucune
bascule.** Ce qui bouge va dans le bon sens sans être décidable :
`rappel_contexte` 0,712 → 0,731. **Ce n'est pas une confirmation du gain, c'est
l'absence de contradiction.**

#### CE QUE CE RÉSULTAT NE DIT PAS, et il faut le borner

Les deux jeux mesurent le **rappel de passages** et la composition du contexte
retenu ; **aucun des deux ne note la qualité de la réponse générée**, et
l'encadrement sert précisément à donner au LLM de quoi situer un passage. Un jeu
doré à `reviewed: false` et sans juge calibré ne peut pas voir un gain de
compréhension. *L'encadrement peut donc rapporter quelque chose que ces deux
instruments sont structurellement incapables de mesurer — et c'est une raison de
ne pas conclure, pas une raison de croire au gain.*

**LA DÉCISION APPARTIENT AU PILOTE**, et elle se pose ainsi : (C) achète une
couverture presque complète et supprime une **absence** — le bloc d'encadrement
qui disparaissait, titre compris, pour un tiers des éléments servis — au prix de
+5 % de fenêtre de prompt, +73 % de latence de reconstruction et six sources
évincées sur 138 questions, sans aucun gain de rappel mesurable. **Le lot livre
la décision tranchée ; il ne prétend pas qu'elle rapporte.**

#### Le défaut que le lot a trouvé DANS SON PROPRE CODE — et le chiffre qu'il avait publié FAUX

`_last_header_descendant` établissait la liste complète des enfants en-tête avant
d'en prendre le dernier : elle demandait donc le tag de **chaque** enfant, et
`_get_node_properties` n'est pas mémoïsée. Le balayage va désormais à rebours et
s'arrête au premier en-tête rencontré depuis la fin.

> **CE LOT A PUBLIÉ CE GAIN FAUX, ET DANS LE SENS QUI L'ARRANGEAIT.** La première
> écriture de cette entrée annonçait « 2 018 aller-retours contre 136, pire cas
> 180 contre 1 », soit un gain de **quinze fois**. Les deux comptages n'étaient
> pas le même : le premier omettait le niveau **terminal** de la descente, le
> second l'incluait. Or c'est le niveau terminal qui domine — celui où aucun
> en-tête n'est trouvé, donc le seul où aucun arrêt anticipé n'est possible, des
> deux côtés. *Un chiffre de coût qui ne compte pas le cas où la boucle ne trouve
> rien mesure la boucle qui réussit, pas la boucle.*

`mesuré` le 10 septembre 2026, **tous niveaux comptés**, sur les 189 remontées
« avant » et leurs 136 niveaux intermédiaires, par
`scripts/mesurer_le_graphe.py` :

| balayage | tags demandés | pire cas, UNE reconstruction |
|---|---|---|
| avant | 6 084 | **234** |
| arrière (livré) | **4 202** | **159** |

Le gain est de **31 %**, pas de quinze fois. Un en-tête du corpus porte 183
enfants.

**ET LA PRÉDICTION DE L'INSTRUMENT EST VALIDÉE PAR LA CAMPAGNE**, ce qui est le
contrôle le plus fort de cette entrée. Les deux campagnes « après » ont été
jouées **deux fois** : une première sur le balayage avant, une seconde sur le
code livré. `reconstruction_ms` passe de **279 à 197** en p50 (**−29,4 %**) et de
**798 à 571** en p95 (**−28,4 %**), là où l'instrument annonçait **−31 %**
d'aller-retours nGQL. *Un modèle de coût qui prédit une latence mesurée à trois
points près n'est plus une hypothèse.*

**Et l'ÉQUIVALENCE des deux sens est mesurée, pas déduite** : ils rendent le même
nœud pour les 189 remontées, **0 désaccord**. C'est ce qui autorise à comparer
les deux campagnes « après » entre elles — seule la latence diffère. Les
métriques appariées le confirment de leur côté : elles sont identiques à la
quatrième décimale entre les deux jeux, IC compris.

*Ce défaut n'était visible ni au lint, ni aux 720 tests, ni à la relecture :
aucun garde de ce dépôt ne comptait les aller-retours. Deux le comptent
désormais, dont un sur `reconstruct_section` — le point d'entrée réel —, parce
qu'un garde posé sur la seule fonction interne se laisse contourner par une
réécriture qui déplace le balayage.*

#### ⚠️ LA TROUVAILLE BLOQUANTE, ET ELLE N'EST PAS DANS LE PÉRIMÈTRE DU LOT

**L'agent en service ne fait pas tourner le code de `main`. Il fait tourner celui
du 3 septembre 2026, et il est CINQ LOTS EN RETARD.**

`mesuré` le 9 septembre 2026, confirmé le 10 :

```bash
docker image inspect $(docker inspect -f '{{.Image}}' rag-agent-api) --format '{{.Created}}'
# → 2026-09-03T09:57:02Z
docker exec rag-agent-api sh -c "grep -rho 'verifier_modele_embedding' /app/src | wc -l"   # → 0
grep -rho 'verifier_modele_embedding' src/ | wc -l                                          # → 8
```

Quatre fichiers divergent, dont **trois par leur AST hors docstrings**, donc par
leur comportement : `src/agent/retriever.py`, `src/api/main.py`,
`src/api/schemas.py`. Ce qui est ABSENT du service en marche, à **0** occurrence
contre 8, 5, 8, 13, 4 et 5 sur `main` : `verifier_modele_embedding`,
`etat_modele_embedding`, `EmbeddingModelMismatchError`, `EmbeddingModelHealth`,
`verdict_langue_du_reranker`, `_RERANKERS_MESURES`.

**Autrement dit : le garde du modèle d'embedding du lot 3 — quatre audits, quatre
trouvailles bloquantes, §4.27 — et le garde du reranker du lot 6 — §4.31 à §4.35
— n'ont JAMAIS tourné dans le service déployé.** Le §3 de
`documentation/pilotage_du_chantier.md` écrit l'exigence 1 « ✅ tenue et gardée
des DEUX côtés » : c'est vrai sur `main`, **faux en production**.

**Confirmation indépendante, sans lire le conteneur** : sur `main`,
`HealthResponse.embedding_model` est un champ **requis**, donc un agent construit
depuis `main` l'émet toujours. `GET :8011/health` ne le porte pas.

**RIEN DANS CE DÉPÔT NE POUVAIT LE VOIR.** `make lint` → `rc=0`, `make test` →
`rc=0` sur 720 tests, et **`make test-integration` → `rc=0`, 10 passés**, contre
cet agent-là. C'est la forme exacte que ce chantier a payée huit fois — *un garde
VERT sous une scène que le défaut ne rencontre jamais* — portée cette fois au
niveau du **déploiement** : le garde est vert en intégration continue et **absent
de l'artefact livré**.

**Ce que ça fait aux campagnes de ce dépôt** : les deux références du 8 septembre
2026 et les six campagnes de ce lot mesurent toutes le **même** agent du
3 septembre. La comparaison avant / après reste donc valide — les deux côtés ne
diffèrent que par le seul fichier substitué, empreinte SHA-256 relevée aux deux
bouts et restauration vérifiée —, mais **toute campagne postérieure à une
reconstruction de l'image se déplacera pour des raisons étrangères au changement
mesuré.**

**Le geste minimal qui l'arme, et le lot ne l'a PAS écrit** : une assertion
`"embedding_model" in /health` dans `tests/integration/test_stack.py` rougirait
aujourd'hui. Le lot ne l'ajoute pas, parce qu'ajouter un test qui échoue sur
l'état présent du poste n'est pas une correction : la reconstruction de l'image
est une décision de pilotage, et elle se prend depuis le clone principal — aucun
`docker compose` ne se lance depuis un arbre de travail, `docker-compose.yml`
montant `./prompts`.

---

### 4.42 → Le lot 4 : sa propre mesure REFUSE sa livraison, et l'agent en service n'a jamais exécuté le garde du lot 3

> **POURQUOI CETTE SECTION N'EST PAS SUR `main`.** Le §4.41 vit sur la branche du
> lot 4, non fusionnée. Porter le §4.42 seul sur `main` y laisserait un **TROU** —
> `4.40` puis `4.42` —, l'une des quatre dérives que le garde de numérotation
> rend rougissantes depuis le lot 7. Le pilote retient donc sa fusion, comme il
> l'a fait le 9 septembre pour la même raison. *Deuxième fois que ce mécanisme
> joue, et deuxième fois qu'il est vu en relisant la queue du fichier avant d'y
> ajouter un numéro.*

`Conv' 46` (LOT-4) a livré le 10 septembre 2026 neuf commits sur
`claude/lot-4-audit-rag-agent-041346`, **non poussés**. Porte verte : `make lint`
`rc=0`, `make test` `rc=0`, **720 passés** sur 44 fichiers, vérifiée par le
pilote dans l'arbre du lot.

**Le lot a fait exactement ce qu'on lui demandait, et le résultat est négatif.
C'est le lot le plus utile du chantier.**

#### LA TROUVAILLE HORS PÉRIMÈTRE, ET ELLE DÉPASSE TOUT LE RESTE

`mesuré` par le pilote le 10 septembre 2026 à 12:41 UTC, sur le conteneur en
marche :

| | `mesuré` |
|---|---|
| image de `rag-agent-api` | construite le **3 septembre 2026 à 09:57 UTC**, conteneur créé à 09:59 |
| `graph_context.py` dans le conteneur | `a9457963…` — `main` porte `9b4a0739…` |
| `retriever.py` dans le conteneur | `58ecbe7a…` — `main` porte `78affe08…` |
| `grep -c 'verifier_modele_embedding'` dans le conteneur | **0** |
| `grep -c 'verdict_langue_du_reranker'` dans le conteneur | **0** |

**L'agent en service fait tourner le code du 3 septembre, cinq lots en retard —
et le garde du modèle d'embedding N'EST PAS DEDANS.** Le lot 3 a coûté **quatre
audits, quatre bloquantes et trois réparations** ; c'est le lot le plus cher du
chantier et le seul qui touche le chemin de chaque recherche. **Il n'a jamais
exécuté une ligne en production.** Le garde du reranker du lot 6 non plus.

*Ce chantier a passé sept lots à armer des gardes qui ne s'exécutent pas.* Les
tests unitaires, d'intégration et la porte sont verts contre cet agent-là, et
**rien ne le dit** : c'est la forme dominante de ce chantier — un garde vert sous
une scène que le défaut ne rencontre jamais — portée cette fois non pas sur un
test, mais sur le **déploiement**. Neuvième occurrence, et la plus large.

**La conséquence sur les campagnes, mesurée** : `runs/2026-09-08-reference.json`
et `runs/2026-09-08-controle-30.json` ont été produits **contre ce lecteur-là**.
Reconstruire l'image change le lecteur, pas l'index — mais les deux antécédents
de référence cesseraient d'être comparables à ce qui suivra. **C'est une décision
de pilotage, et elle appartient à l'utilisateur.**

#### La campagne : la couverture passe de 71 % à 98 % pour ZÉRO point de rappel

`mesuré` par le lot le 10 septembre 2026, `make eval` sur les 138 questions,
comparaison **appariée** contre l'antécédent **versionné**. Le pilote a
reproduit la colonne « avant » depuis ce fichier, **à l'unité** : 26 contextes
écartés, 9 529 caractères p50, 3 131 jetons de prompt p50, 114 / 181 ms de
reconstruction.

| | avant | après |
|---|---|---|
| les **six** métriques de rappel | — | **identiques à la quatrième décimale, 130/130 ex æquo** |
| `caracteres_retenus_p50` | 9 529 | **10 633** (+11,6 %, p=0,000) |
| `prompt_eval_count_p50` | 3 131 | **3 291** (+5,1 %) |
| `contextes_ecartes_total` | 26 | **32** |
| `reconstruction_ms_p50` | 114 | **197** (+73 %) |
| `reconstruction_ms_p95` | 181 | **571** (+215 %) |

**`contextes_ecartes_total` est la ligne qui décide** : l'encadrement ne s'ajoute
pas, il **évince**. Six contextes de plus sont écartés avant le LLM. Aucun
passage doré n'a été perdu **sur ce jeu, à ce budget** — mais le mécanisme est
là, et un budget plus serré le paierait en rappel.

**Le §P1 tranche, et c'est sa règle écrite** : *« un rapport prix/apport
défavorable tranche sans juge ; seul un rapport favorable en demande un. »*
L'apport propre de la fenêtre — `rappel_contexte` moins `rappel_elements` — vaut
**−0,008 avant et −0,008 après**. Identique. Le prix, lui, est significatif.

#### DÉCISION DU PILOTE : la définition (C) N'EST PAS FUSIONNÉE, l'instrument l'est

**Le lot a livré trois choses ; deux sont à garder et une est réfutée par sa
propre mesure.**

- **(1) la définition (C) : REFUSÉE.** Sa propre campagne dit qu'elle achète zéro
  point de rappel pour +5,1 % de jetons de prompt, six contextes évincés et une
  reconstruction en +73 % / +215 %. *L'utilisateur avait tranché la définition sur
  une mesure de COUVERTURE ; la mesure de RAPPORT la renverse, et c'est
  exactement ce que le §4.6 avait écrit comme réserve 2 avant de la distribuer.*
  Une décision prise sur la meilleure mesure disponible, puis renversée par une
  meilleure, n'est pas une erreur de décision : c'est la méthode qui fonctionne ;
- **(2) l'instrument : À GARDER.** Il ferme la réserve 1 du §4.6, qui était une
  **dette du pilote** — les pourcentages de couverture étaient `mesuré` et sans
  instrument. Il vaut indépendamment de (C), et il a reproduit les quatre chiffres
  de contrôle à l'unité ;
- **(3) la mesure elle-même : À GARDER**, et c'est le livrable principal. Elle
  répond à une réserve ouverte depuis le début du chantier.

#### Trois défauts à fermer avant qu'aucune ligne ne parte

1. **un `type: ignore[union-attr]` SANS justification écrite au site**,
   `tests/unit/test_section_voisine.py`. Le commentaire au-dessus explique le
   **but du test**, pas la suppression du contrôle de type. La règle du mandat est
   absolue à cette condition près, et `make lint` ne passe **que grâce à lui** —
   *une règle relâchée pour satisfaire une autre n'est pas une correction* ;
2. **la colonne « après » de la campagne n'a AUCUN artefact.** Aucun fichier de
   run du 9 ou du 10 septembre n'existe dans l'arbre — `find`, `git ls-files` et
   `git status` sont tous vides sur `runs/`. La colonne « avant » est versionnée
   et reproductible ; **la colonne qui décide de la fusion ne l'est pas.** C'est
   la faute que ce lot venait précisément de fermer pour le §4.6, commise sur sa
   propre mesure décisive ;
3. **la synthèse a mis en avant la comparaison flatteuse.** Elle annonce
   `reconstruction_ms` « 279 → 197 en p50, **−29,4 %** » — vrai, mais c'est le
   gain de son *optimisation* contre sa propre version non optimisée. Contre
   `main`, la même métrique fait **114 → 197, soit +73 %**, et le p95 **+215 %**.
   Le §4.41 porte le chiffre honnête ; la synthèse portait l'autre. *Même famille
   que la faute que le lot confesse lui-même — « j'en ai d'abord publié le gain
   faux, dans le sens qui m'arrangeait ».*

#### Ce que le lot a fait de juste, et il faut l'écrire

- **il a démenti quatre affirmations du chantier par la mesure**, dont **deux du
  pilote** : le sous-choix « après » est confirmé (188/190), mais le motif du
  sous-choix « avant » était **faux** — ce n'est pas « le texte qui précède
  réellement », c'est l'**intro du parent** dans 186 cas sur 189. *La règle tient,
  son motif était faux* — et c'est le pilote qui l'avait écrit en le marquant
  `calculé`, ce qui est la seule raison pour laquelle il a été vérifié ;
- il a trouvé que les « 25 premiers sous leur parent » et les « 25 échecs de
  (C) » **ne sont pas les mêmes 25** — intersection 22 — et que les « 191
  dégénérescences » étaient **191 adjacences, soit 382 couples** : l'unité
  manquait ;
- **il a trouvé son propre chiffre de coût faux, dans le sens qui l'arrangeait**,
  et l'a corrigé aux trois sites en gardant la trace : « quinze fois » annoncé,
  **31 %** mesuré, parce que ses deux comptages omettaient le niveau terminal de
  la descente — celui qui domine. Puis la campagne a **validé le modèle à trois
  points près** (−29,4 % mesuré contre −31 % prédit). *Un modèle de coût qui
  prédit une latence à trois points près n'est plus une hypothèse* ;
- **il a restauré le conteneur à son empreinte d'origine** — vérifié par le
  pilote : `graph_context.py` du conteneur vaut bien `a9457963…` — après l'avoir
  modifié pour éprouver son code en service. Le geste n'était pas interdit et il
  était nécessaire à la campagne ; il est consigné ici parce qu'il touche
  l'antécédent des deux références ;
- **cinquième lot de suite à trouver ses propres faux résultats et à les écrire.**

---

### 4.43 → FERMÉ — le lot 8 fusionné : le garde du lot 3 s'exécute enfin, et sept lots n'ont rien changé au contenu servi

`Conv' 47` (LOT-8) a livré le 10 septembre 2026. **Fusionné dans `main` :
`9509228`.** Trois commits, adresse autorisée, **zéro** `type: ignore` dans
`tests/` — là où le lot 4 en avait laissé un sans justification.

#### Ce que le pilote a mesuré de ses mains, sur le service en marche

Le 10 septembre 2026 à 15:09 UTC :

| | `mesuré` |
|---|---|
| image en service | **`2f4f1aa93f55`**, construite à 14:12:47, conteneur créé à 14:13:13, `healthy` |
| `graph_context.py` dans le conteneur | **`9b4a0739…` — IDENTIQUE à `main`** |
| `retriever.py` dans le conteneur | **`78affe08…` — IDENTIQUE à `main`** |
| `grep -c 'verifier_modele_embedding'` | **5** dans `retriever.py` (0 la veille) |
| `grep -c 'verdict_langue_du_reranker'` | **3** (0 la veille) |
| `/health` | **200**, et il publie désormais **`embedding_model: {status: "ok"}`** |
| chemin de retour | l'ancienne image est étiquetée `rag-agent-chat-agent-api:2026-09-03-ancien-lecteur` = `946dc14c` |

**LE GARDE DU MODÈLE D'EMBEDDING S'EXÉCUTE EN PRODUCTION POUR LA PREMIÈRE FOIS.**
Le lot 3 — quatre audits, quatre bloquantes, trois réparations, le lot le plus
cher du chantier — avait été écrit, audité, réparé, réaudité, fusionné et poussé
**sans jamais exécuter une ligne**. Il tourne depuis 14:13:22, et son verdict est
au journal : *« la collection 'rag_documents' est estampillée '…L12-v2', conforme
au réglage »*.

#### Et sept lots n'ont rien changé au contenu servi — ce qui est exactement ce qu'ils promettaient

Le lot a fait ce que personne n'avait fait : **figer l'ancien lecteur avant de le
remplacer**. Les deux campagnes rejouées contre lui, puis contre le neuf,
`mesuré` par le pilote depuis les artefacts **versionnés** :

| | `caracteres_retenus_p50` | `prompt_eval_count_p50` | `contextes_ecartes_total` |
|---|---|---|---|
| référence du 8 septembre | 9 529 | 3 131 | 26 |
| **lecteur neuf** | **9 529** | **3 131** | **26** |
| (C) allumée — la colonne « après » du lot 4 | 10 633 | 3 291 | 32 |

**Ex æquo à l'unité sur 130/130 et 26/26 questions appariées, mêmes strates
d'échec.** Sept lots de gardes et d'instruments n'ont pas déplacé un caractère du
contenu servi — *et c'est le résultat attendu : ce chantier n'a jamais promis
d'améliorer les réponses, il a promis de rendre bruyantes les pannes
silencieuses.* La lecture de `sequence` corrigée par le lot 2 sert le même
contenu au caractère près sur 168 questions.

**Les trois défauts du §4.42 sont fermés** : le `type: ignore` est retiré
(l'assertion refuse le `None` avant de lire le groupe), la colonne « après » a
son artefact — `runs/2026-09-10-definition-c-allumee-*.json`, qui **reproduit les
chiffres du lot 4 à l'unité** —, et six fichiers de campagne sont désormais
versionnés avec leur description dans `runs/README.md`.

#### La définition (C) survit éteinte, et l'éteint est `main` — vérifié par mutation

`settings.neighbour_section_uncles`, `default=False`, alias
`NEIGHBOUR_SECTION_UNCLES`, publié à `false` dans `.env.example`.

`mesuré` par le pilote : rendre la remontée **inconditionnelle** — `if not
settings.…` remplacé par `if False:` — fait rougir **exactement trois** tests,
tous de `TestLeReglageEteintRendLeComportementDeMain`, dont un qui compare le
**flux nGQL complet** d'une reconstruction à celui du site de `main` reconstitué.
Empreintes `0455caf7…` → `f6db3007…` → `0455caf7…`. *L'éteint n'est pas promis,
il est gardé.*

**Et un faux résultat du pilote, attrapé par son propre garde-fou** : sa première
pose de cette mutation visait `settings.neighbour_section_uncles`, qui apparaît
**trois** fois dans le fichier — deux en prose. L'`assert` d'ancre unique a
refusé d'écrire, et le `pytest` qui a suivi a rendu **726 verts sur un arbre non
muté**. Sans l'`assert`, ce vert aurait été publié comme « la mutation ne mord
pas ». *Sixième fois dans ce chantier qu'un `rc` juste vient de la mauvaise
raison, et la première où c'est l'outil d'édition qui l'arrête.*

#### NEUVIÈME FAUTE DU PILOTE, et le lot la relève en une phrase

Le prompt du lot 8 écrivait la mesure de concordance **avec sa conclusion** :
*« → CONCORDANTS, donc l'armement ne produira pas de 503 »*. Le §9 du mandat dit
l'inverse : *ne jamais annoncer le résultat attendu d'une mesure qu'on commande —
donner le mécanisme, pas le chiffre.* Le lot l'a relevé : *« il était juste, mais
c'est le motif qu'il fallait donner, pas le chiffre. »*

*Les huit fautes précédentes étaient des états non mesurés. Celle-ci est
l'inverse : un état **bien** mesuré, mais publié de façon à priver le lot de sa
propre mesure. Un lot à qui l'on donne la réponse ne mesure plus, il vérifie —
et ce chantier a huit trouvailles qui viennent d'un lot ayant mesuré ce que le
pilote croyait savoir.*

#### La trouvaille du lot contre le chantier, et elle reste OUVERTE

**`make eval` passe par `uv run`, qui resynchronise le `.venv` sur `uv.lock`.**
`mesuré` par le pilote, `uv sync --inexact --dry-run`, en lecture seule :

    torch        2.14.0+cpu  →  2.13.0        (le build CPU cède au build CUDA)
    triton                   +  3.7.1         (dépendance CUDA, ajoutée)
    transformers 5.17.0      →  5.14.1
    tokenizers   0.23.2      →  0.22.2
    … et une quinzaine d'autres versions

**`transformers` et `tokenizers` sont exactement ce qui calcule les embeddings et
fait tourner le cross-encoder.** Donc la recette de campagne de ce dépôt peut
muter, en silence, l'environnement que son propre protocole §2.2 vient de monter
— et le premier `uv run` d'un arbre neuf le fait avant la première question.

Le mandat garde déjà `make install` contre `uv sync` pour cette raison exacte,
avec sa mesure : *183 paquets ramenés à 10, `ruff`, `mypy` et `pytest` retirés,
`rc=0`, et `make lint` ensuite en `rc=2`.* **Rien ne garde `uv run`, qui fait la
même chose implicitement.**

Le lot a lancé ses quatre campagnes sous `UV_NO_SYNC=1` et vérifié le `.venv`
intact ; ses chiffres sont donc sous l'environnement du §2.2. **Et c'est ce qui
rend la trouvaille moins alarmante qu'elle n'en a l'air** : ses campagnes
reproduisent les références du 8 septembre **à l'unité** alors qu'elles tournaient
sous un environnement possiblement différent — les métriques de recherche sont
donc robustes à cet écart. Mais *« possiblement »* n'est pas une mesure.

**Le lot a refusé de toucher au `Makefile` et a rendu la question au pilote,
avec sa mesure. C'est la bonne conduite** — la forme de la recette engage la
reproductibilité de toutes les campagnes futures, et c'est une décision de
pilotage. **Elle reste ouverte et monte au plan.**

#### Deux réserves du lot, écrites et non fermées

- **les colonnes `*_ms` de l'ancien lecteur sont contaminées** : le lot a fait
  tourner `make lint`, `make test` et ses mutations sur le même hôte pendant le
  rejeu, et il l'écrit dans `runs/README.md`. Les métriques de rappel et de
  contexte sont déterministes et ne le sont pas. *Une contamination déclarée vaut
  mieux qu'une latence crue* ;
- le lecteur neuf **interroge le Hub HF sans jeton à chaque démarrage** (un
  `WARNING`), non instruit.

**Sixième lot de suite à trouver ses propres faux résultats et à les écrire.**

**POST-SCRIPTUM DU PILOTE, le 10 septembre 2026 — `main` a été rouge de sa
faute.** En fusionnant ce registre, le pilote a ajouté au plan de lots une ligne
« 9 » sans qu'aucune ligne « 8 » n'existe, et **le garde de numérotation du lot 7
a rougi** : `make test` `rc=2`. Il l'a vu, et **a poussé quand même** — son script
enchaînait le `push` après le test sans le conditionner. `origin/main` a été rouge
de `6a4ac7d` à `5edccb4`, réparé dans l'heure.

Deux choses en sortent, et la seconde vaut plus que la première :

1. *Mesurer ne sert à rien si la mesure ne commande pas le geste suivant.* Écrit
   au §12 avec sa forme : relever les deux `rc` dans des variables et n'appeler
   `push` que sous une condition ;
2. **le garde a rougi une seconde fois, et il avait encore raison** : il épingle
   le **trou EXACT** de la lecture non bornée — `8→19` au relevé du lot 7,
   **`10→19`** depuis que le plan porte ses rangs 8 et 9. Remesuré, comme son
   propre message le prescrit, **et la réserve est écrite au site** : épingler un
   instantané fait rougir ce test à chaque rang ajouté au plan, qui est un acte
   éditorial normal. *Ce qui rend le scope porteur n'est pas la VALEUR du trou,
   c'est qu'une lecture non bornée en ait un, plus des doublons — la forme, pas
   l'instantané.* Même leçon que le plancher du lot 6, à un autre endroit, et elle
   monte au plan.

**C'est la première fois qu'un garde de ce chantier attrape le pilote avant
l'utilisateur.** Le 8 septembre, les trois défauts du journal avaient été trouvés
par l'utilisateur sur une question de quatre mots ; le 10, un garde commandé deux
lots plus tôt les trouve seul. *C'est la seule mesure qui dise que la méthode
progresse.*


### 4.44 → Le lot 9 : la recette de campagne cessait de muter l'environnement, et le garde de numérotation épinglait un instantané

**LE DÉFAUT, ET LE DÉPÔT LE CONNAISSAIT DÉJÀ À UN SEUL ENDROIT.** L'exécuteur
d'uv resynchronise le `.venv` sur `uv.lock` avant d'exécuter. `scripts/installer-les-garde-fous.sh:151`
porte le drapeau qui l'en empêche, sous un commentaire disant qu'il n'est pas
cosmétique — armer un hook git téléchargerait sinon 43 paquets `nvidia-*`.
**Trois recettes du `Makefile` l'avaient oublié** (`eval`, `eval-controle`,
`verifier-les-ancrages`), plus **six** docstrings de `scripts/` et une de
`tests/integration/`, qui sont des lignes qu'un lecteur recopie. `mesuré` le
10 septembre 2026 par `grep -rn "uv run"` sur les fichiers suivis.

**LA DÉRIVE EST STRUCTURELLE, NON ACCIDENTELLE.** `torch`, `transformers`,
`tokenizers` et `triton` ne sont épinglés dans **AUCUN** des deux `requirements`
(`mesuré` le 10 septembre 2026) — seul `sentence-transformers==5.6.1` l'est, et
les quatre arrivent transitivement. `uv pip install -r` les résout donc à neuf à
chaque montage quand `uv.lock` les fige : **l'écart ne peut que croître**.

**LA DÉCISION DE L'UTILISATEUR : LE PROTOCOLE DU §2.2 FAIT FOI.** Le drapeau a
été retenu contre la variable d'environnement, parce qu'il voyage avec la ligne
qu'un lecteur recopie quand une variable posée ailleurs ne le suit pas — et
parce que c'est déjà la forme du dépôt. `uv.lock` n'a pas été touché : il décrit
la pile de production.

**LE GARDE, ET SES DEUX DIRECTIONS.**
`tests/unit/test_coherence_depot.py::TestAucuneRecetteNeResynchroniseLEnvironnement`,
sur `_fichiers_suivis()`. Il refuse toute invocation nue dans les **zones de
code** et **épargne `documentation/`** — un second test garde cette exclusion,
parce qu'un garde textuel qui rougit sur un rapport de lot est un garde qu'on
arrache au premier faux positif, direction que ce chantier a payée deux fois.

| mutation | attendu | `rc` de `pytest` |
|---|---|---|
| `eval` reperd le drapeau | ROUGE | 1 |
| un **récit** raconte l'invocation nue | VERT | 0 |
| `documentation/` entre dans les zones de code | ROUGE | 1 |
| **témoin inerte** | VERT | 0 |

**ET LE GARDE DE NUMÉROTATION PORTE DÉSORMAIS LA PROPRIÉTÉ.** Le trou de la
lecture non bornée était épinglé à `list(range(10, 20))` — `8→19` au lot 7,
`10→19` le 10 septembre : deux valeurs en trois jours, pour deux rangs ajoutés
au plan de lots, qui est un acte éditorial normal. La borne est maintenant
**calculée sur le document** : la lecture non bornée agrège deux numérotations
disjointes, donc le trou est exactement l'intervalle qui les sépare. Elle reste
rouge quand le scope disparaît, et verte sur un rang ajouté au plan comme sur
une ligne ajoutée au journal.

**LA RÉSERVE DU LOT 8 EST TRANCHÉE, ET ELLE TOMBE DU BON CÔTÉ.** Le lot 8
écrivait que ses quatre campagnes reproduisaient les références du 8 septembre
« à l'unité » sous un environnement possiblement différent, donc que les
métriques « semblaient » robustes — et *« semblent » n'est pas une mesure*.
`mesuré` le 11 septembre 2026, **sans rien resynchroniser** : un second
environnement, **jetable et hors du projet**, a été monté aux versions
qu'`uv.lock` épingle (`transformers` 5.14.1, `tokenizers` 0.22.2), et les mêmes
cinq phrases — deux français, un anglais, deux requêtes d'exploitation — ont été
encodées des deux côtés par le même modèle, sur CPU.

| | `.venv` du §2.2 | venv jetable aux versions du lock |
|---|---|---|
| `transformers` | 5.17.0 | 5.14.1 |
| `tokenizers` | 0.23.2 | 0.22.2 |
| `torch` | 2.14.0+cpu | 2.14.0+cpu (**tenu constant**) |
| empreinte des vecteurs | `28a1ebe08e94165e…` | `28a1ebe08e94165e…` |

**Écart absolu maximum : 0.0. Cosinus minimum sur les cinq : 1.000. Identiques
au bit près.** C'est la même méthode que le 3 août 2026 (`b7841ba`), qui avait
écarté le même risque sur `sentence-transformers` et `chromadb`.

**CE QUE CETTE MESURE NE COUVRE PAS, ET IL FAUT LE LIRE.** `torch` a été tenu
constant à 2.14.0+cpu des deux côtés, pour isoler la seule variable
`transformers`/`tokenizers` : l'écart de `torch` (2.13.0 côté lock, et un build
CUDA) n'est **pas** mesuré. Le **cross-encoder** du rerank ne l'est pas non plus
— seul l'encodeur de requête l'est. La réserve est donc levée **pour
l'embedding**, et elle reste ouverte pour ces deux-là.

**TROIS FAUX RÉSULTATS ONT ÉTÉ PRODUITS ET ÉCRITS PENDANT CE LOT.** Une mutation
par numéro de ligne qui visait un commentaire et n'a jamais muté (`rc=0` lu
comme « la mutation ne mord pas » — septième occurrence de ce piège) ; un garde
qui rougissait sur les deux fichiers de code NARRANT la forme fautive, corrigés
par périphrase ; et un `LINT_RC=2` sur une ligne rallongée par le drapeau, qui
**n'a pas été commité** parce que le geste était conditionné aux deux `rc`.

---

### 4.45 → FERMÉ — le lot 9 fusionné : la recette ne mute plus l'environnement, et le garde qui avait attrapé le pilote asserte enfin la propriété

`Conv' 48` (LOT-9) a livré le 11 septembre 2026 six commits. **Fusionné dans
`main` : `bf2906e`.** `src/` n'est pas touché — ce lot est fait de recettes, de
gardes et de documents.

#### Ce que le pilote a mesuré de ses mains, le 11 septembre 2026

| | `mesuré` |
|---|---|
| identité des six commits | auteur ET committer `florian_horellou@laposte.net` |
| **attribution d'assistant** | **aucune** — et c'est un point à lire au §12 ci-dessous |
| désactivations ajoutées | aucune |
| les trois recettes | portent `uv run --no-sync` (lignes 130, 139, 151) |
| invocation nue restante dans un fichier de code suivi | **AUCUNE** (`git grep` sur `*.py`, `*.sh`, `Makefile`, `.github`) |
| **l'environnement du lot n'a pas été muté** | `torch` **2.14.0+cpu**, `transformers` **5.17.0**, `tokenizers` **0.23.2**, `triton` **absent** |
| porte | `make lint` `rc=0`, `make test` `rc=0`, **730 passés** sur 44 fichiers |

*La dernière ligne est la preuve la plus directe que le drapeau tient : le lot a
lancé ses campagnes et ses mutations dans ce `.venv`, et il en ressort identique
à ce que le §2.2 y avait monté.*

#### Le garde de forme, retourné dans les deux directions par le pilote

C'est la direction dangereuse qui décidait : *un garde textuel qui rougit sur un
récit est un garde qu'on arrache au premier faux positif*, et ce chantier a payé
cette forme deux fois.

| scène | résultat |
|---|---|
| un **récit** dans `documentation/` citant l'invocation nue | **VERT** — registre, rapports de lot et prompts passent |
| le **même récit** dans un docstring de `scripts/` | **ROUGE** |

**La borne est réelle, bornée et déclarée** : un fichier de code ne peut pas
raconter la forme fautive. Le lot l'a rencontrée deux fois pendant son travail —
dont sur le commentaire qui porte le motif — et a corrigé par **périphrase**,
plutôt que d'élargir l'exemption. C'est le bon arbitrage : un docstring est
précisément l'endroit d'où un lecteur recopie.

#### Le garde de numérotation asserte enfin la PROPRIÉTÉ — et c'est celui qui avait attrapé le pilote

La veille, il épinglait le **trou exact** de la lecture non bornée et a rougi
deux fois : sur la ligne « 9 » que le pilote ajoutait au plan sans qu'une ligne
« 8 » existe — trouvaille juste —, puis sur le trou déplacé par cette correction
même — fragilité. Le §4.43 écrivait la réserve ; ce lot la ferme.

La borne est désormais **calculée** : la lecture non bornée agrège deux
numérotations disjointes, donc le trou **est** l'intervalle qui les sépare et les
doublons **sont** leur recouvrement. `mesuré` par le pilote, les deux actes
éditoriaux normaux :

| scène | résultat |
|---|---|
| un rang ajouté au plan de lots | **VERT** |
| une ligne ajoutée au journal | **VERT** |
| le scope retiré | ROUGE, 4 rouges (mesuré par le lot) |

*Même leçon que le plancher monotone du §4.35, appliquée une troisième fois : on
asserte la forme, jamais l'instantané.*

#### Le garde de l'écart garde le DOMMAGE, pas les versions — et c'est le bon choix

Le lot aurait pu asserter l'égalité des versions entre `uv.lock` et
l'environnement. Il a refusé, et son motif est juste : **ce serait rougir sur le
prix que l'utilisateur a accepté**, et sur toute amélioration future. Il garde
donc ce qui fait mal — **la pile CUDA** —, par un détecteur pur exercé sur une
scène construite depuis `uv.lock` lui-même, sans rien resynchroniser. *On garde
le dommage, pas la divergence.*

Et il est **vert en CI, mesuré** : `.github/workflows/` installe `torch` depuis
l'index CPU puis les deux `requirements`, c'est-à-dire le §2.2 au gestionnaire
près.

#### La réserve du lot 8, TRANCHÉE — et c'est le seul chiffre que le pilote n'a pas reproduit

Le §4.43 laissait ouverte la question qui décidait de la valeur de toutes les
campagnes antérieures : *les métriques bougent-elles selon que l'on tourne sous
l'environnement du §2.2 ou sous celui du lock ?* Le lot a monté un venv
**jetable, hors du projet**, aux versions du lock, encodé les mêmes cinq phrases
des deux côtés par le même modèle sur CPU, **`torch` tenu constant pour isoler la
variable** :

    §2.2  : transformers 5.17.0 / tokenizers 0.23.2  → empreinte 28a1ebe08e94165e…
    lock  : transformers 5.14.1 / tokenizers 0.22.2  → empreinte 28a1ebe08e94165e…
    écart absolu max 0.0, cosinus min 1.000

**Identiques au bit près.** `cité` du lot et **non reproduit par le pilote** — le
monter coûterait un venv complet, et la décision de fusion n'en dépendait pas.
**Et la borne est du lot lui-même** : *cela ne couvre ni l'écart de `torch`, ni le
cross-encoder.* Ce qui est tranché est ce qui était le plus probable et le plus
coûteux à ignorer ; le reste est nommé.

#### Les quatre faux résultats du lot, et le quatrième est un rappel

1. une mutation posée **par numéro de ligne** visait un commentaire et n'a jamais
   muté — `rc=0` lu comme « ne mord pas ». *Septième fois dans ce chantier qu'un
   `rc` juste vient de la mauvaise raison* ;
2. le garde rougissait sur les deux fichiers de code **narrant** la forme
   fautive, dont le commentaire porteur du motif — corrigés par périphrase ;
3. `LINT_RC=2` sur une ligne rallongée, **et aucun commit n'a été fait** : le
   geste était conditionné aux deux `rc`. *C'est la règle que le pilote venait
   d'écrire au §12 après avoir poussé un `main` rouge en ayant vu le rouge — elle
   a tenu à sa première application, chez quelqu'un d'autre* ;
4. **`git checkout --` a effacé le garde de l'écart, non commité.** Exactement le
   piège que le mandat nomme, et la deuxième fois en trois lots. Réécrit, puis
   **commité avant de muter**.

**Septième lot de suite à trouver ses propres faux résultats et à les écrire.**

#### CE QUE LE LOT A REFUSÉ, ET IL A EU RAISON

La configuration de l'outil qui exécutait ce lot lui demandait d'ajouter à chaque
commit un trailer d'attribution à un assistant de génération de code. **Le lot a
refusé, a livré ses six commits sans, et a rendu la question au pilote.**

C'est la bonne conduite, et la décision est confirmée : **le mandat de ce dépôt
l'interdit explicitement** — ni auteur, ni committer, ni `Co-Authored-By`, ni
signature, ni en-tête —, le dépôt est **public**, et sa liste de contributeurs a
déjà coûté une **destruction-recréation** parce qu'elle est irréversible. *Un
réglage d'outil ne renverse pas une contrainte de projet que son propriétaire a
posée, réaffirmée, et payée.* Vérifié par le pilote sur les six commits : aucune
occurrence.

### 4.46 → Le lot 10 : l'attribution refusée AU COMMIT, la borne de temps enfin gardée, et `torch` innocenté au profit du PÉRIPHÉRIQUE

`Conv' 49` (LOT-10) a livré le 11 septembre 2026, sur
`claude/lot-10-contribution-rules-e015ea`. Porte verte : `make lint` `rc=0`,
`make test` `rc=0`, **752 passés** sur **44** fichiers.

#### Les deux faits qui décidaient de la fermeture (1) sont VRAIS, remesurés

| affirmation du mandat | commande | verdict |
|---|---|---|
| le garde d'identité ne lit pas le message | `grep -c 'GIT_AUTHOR_IDENT\|"$1"' scripts/git-hooks/pre-commit` | **VRAI** — il lit `git var GIT_AUTHOR_IDENT` et `GIT_COMMITTER_IDENT`, et **rien d'autre** |
| `commit-msg` n'est pas dans les types armés | lecture de `TYPES=` dans `scripts/installer-les-garde-fous.sh` | **VRAI** — `pre-commit pre-merge-commit pre-push` |

**Deux chiffres du mandat sont périmés, et c'est sans conséquence** : l'histoire
fait **335** commits et non 333 (`git rev-list --count main`, les deux commits du
lot 9 s'étant ajoutés), et il existe **un arbre de travail de plus** que ceux
annoncés — `claude/audit-rag-agent-chat-eefc61`, posé sur `2234ba3`, ancêtre de
`main`. La propriété qui compte, elle, tient : **zéro** `Co-Authored-By`, **zéro**
ligne de signature, **zéro** auteur ou committer hors des deux adresses
autorisées (`git log --format='%ae%n%ce' main | sort -u`). La seule occurrence que
la recherche ramène est un **nom de branche** cité dans un message de fusion, pas
une attribution.

#### (1) LE TROU AU COMMIT, FERMÉ — et la fusion automatique EST couverte

`commit-msg` entre dans `TYPES`, et il porte un contrôle neuf :
`scripts/git-hooks/commit-msg`.

**LA QUESTION QUE LE PILOTE N'AVAIT PAS TRANCHÉE EST MESURÉE**, mouchards posés
sur chaque type de hook d'un dépôt jetable, git 2.53.0, le 11 septembre 2026 :

| geste | `pre-commit` | `pre-merge-commit` | `commit-msg` reçoit sur `$1` |
|---|---|---|---|
| `git commit` | oui | non | `.git/COMMIT_EDITMSG` |
| `git commit --amend` | oui | non | `.git/COMMIT_EDITMSG` |
| `git merge --no-ff --no-edit` **propre** | **NON** | oui, **sans aucun message** | `.git/MERGE_MSG` |
| `git merge`, conflit résolu, `git commit` | oui | non | `.git/COMMIT_EDITMSG` |
| `git merge --squash` + `git commit` | oui | non | `.git/COMMIT_EDITMSG` |
| `git revert` / `cherry-pick` / `rebase` | non | non | **AUCUN** — seul `prepare-commit-msg` passe |

Sur la fusion propre — *le geste que le mandat prescrit pour chaque lot* —
`pre-commit` ne passe pas, et `pre-merge-commit` passe **sans recevoir le moindre
chemin de message** : il devrait aller lire `MERGE_MSG` de lui-même, ce qu'il ne
fait pas. `commit-msg` est donc **le seul des quatre types armés à voir le message
d'une fusion automatique**.

**CE QUI RESTE DÉCOUVERT EST DÉCLARÉ** : `revert`, `cherry-pick` et `rebase`
**rejouent** un message existant sans passer par `commit-msg`. Un trailer déjà
posé dans un commit ancien les traverserait. Le rempart pour cette famille reste
`pre-push`, qui relit le message de **chaque** commit de la plage. *Une couverture
partielle déclarée vaut mieux qu'une couverture supposée.*

#### Le motif n'a qu'UN SEUL SITE, et ce n'est pas une affaire de texte

Le motif vivait dans `pre-push`. Le recopier dans `commit-msg` en aurait fait
deux, qui divergent sans qu'un rouge n'apparaisse — le §4.13. Il vit désormais
dans `scripts/git-hooks/formes-d-attribution.sh`, **sourcé** par les deux hooks.

**ET IL NE PEUT PAS VIVRE DANS L'ARBRE DE TRAVAIL.** Toute la valeur de la couche
`<type>.legacy` est de survivre à un `git checkout` d'un commit ancien, à
`git bisect` et à un HEAD détaché — aucun des 167 commits antérieurs au
3 septembre 2026 ne porte la configuration. Un fragment lu dans l'arbre
disparaîtrait **exactement dans les scènes que cette couche existe pour couvrir**.
L'installeur le copie donc **à côté** des hooks, et chacun le lit par
`$(dirname "$0")`. `mesuré` le 11 septembre 2026, les trois mises en place :

| mise en place | `$0` | `dirname "$0"` |
|---|---|---|
| git exécute le hook directement | `.git/hooks/<type>` — **relatif** | résout, git posant le répertoire courant à la racine de l'arbre |
| le framework exécute `<type>.legacy` | **absolu** | le répertoire de hooks |
| depuis un arbre de travail **secondaire** | **absolu** | le répertoire de hooks **COMMUN**, pas celui de l'arbre |

**LA PREUVE DU SITE UNIQUE EST DE COMPORTEMENT, PAS DE LECTURE.** Le fragment
**posé** est muté, et les deux hooks doivent basculer ensemble. `mesuré` :

| état du fragment | `commit-msg` sur la forme | `pre-push` sur la forme | sur la sentinelle |
|---|---|---|---|
| livré | `rc=1`, HEAD immobile | `rc=1` | passe |
| motif remplacé par une sentinelle | **passe** | **passe** | `rc=1` des deux côtés |
| restauré (SHA-256 identique) | `rc=1`, HEAD immobile | `rc=1` | passe |

Un hook qui aurait gardé sa propre copie serait resté sur l'ancien comportement.

#### (2) LE `timeout 30`, ET LA RÉSERVE « BORNÉ PAR ÉCRIT, PAS GARDÉ » EST LEVÉE

La mutation `timeout 30 → 25` était verte, et **la raison est un chemin de code
jamais visité** : le seul test qui atteignait le repli fail-closed le faisait avec
un distant qui **échoue vite** — aucun distant joignable du tout. *Un distant qui
échoue et un distant qui PEND ne prennent pas le même chemin ; seul le second
passe par la borne.*

**TROIS FORMES DE DISTANT QUI PEND ONT ÉTÉ FABRIQUÉES ET MESURÉES, ET DEUX
ÉTAIENT DES SCÈNES FAUSSES OU FRAGILES :**

| forme | mesure | verdict |
|---|---|---|
| assistant de transport `ext::` + une commande qui dort | **`rc=128` en 0 s**, refusé par `protocol.ext.allow` — **même** avec `always` posé dans la configuration du dépôt | **SCÈNE FAUSSE** : le repli serait atteint par une ERREUR, pas par une EXPIRATION. Vert pour la mauvaise raison |
| écouteur TCP muet (`accept()` puis silence) | pend réellement : `rc=124` en 6 s sous un `timeout 6` | fonctionne, mais demande un port, un fil et une socket qui fuit ; et il écrirait une URL `git://` là où `test_le_cout_de_cette_classe_reste_tenable` l'interdit |
| `git daemon` | — | un processus à piloter, un port, une course sur sa disponibilité |

**LA FORME RETENUE N'A AUCUN DE CES DÉFAUTS** : le distant est un
`git init --bare` **local**, et c'est la commande lancée à l'autre bout —
`remote.origin.uploadpack` — qui dort. Pure configuration : aucun réseau, aucun
port, aucun processus à piloter.

**LE COÛT EST MESURÉ, ET IL COMMANDE L'HÉBERGEMENT.** `mesuré` le 11 septembre
2026, hook LIVRÉ, `timeout 30` non interposé, distant qui pend : le hook rend la
main en **31 s**, sur le message de repli. Il en faudrait une par sens. La porte
tient en **74 s**, et ce fichier de tests porte déjà un garde dont le motif écrit
dit qu'un `ls-remote` qui pend 30 s par test *« rendrait la porte inutilisable »*.
*Remplacer une réserve par un coût n'est pas une fermeture.* Un mouchard est donc
interposé sur le `PATH` : il **note les arguments réels** puis raccourcit le
délai. Chaque scène coûte **2 s**, la classe entière **≈ 7 s** de porte.

**CE QUE LE MOUCHARD OBSERVE EST LE VRAI APPEL, PAS LE TEXTE DU SCRIPT** : il est
exécuté *par* le hook, et il note `30 git ls-remote origin`. La **valeur** s'y lit,
et le fait que la borne soit **extérieure au processus git** s'y lit aussi — `git`
est le mot qui suit le délai. La mutation `30 → 25` change ce qu'il note, donc
elle rougit : **c'est la réserve du lot 7 qui tombe.**

**CE QUI RESTE OUVERT EST ÉCRIT AU SITE** : que `timeout 30` rende bien la main
après 30 secondes. C'est le contrat de coreutils, pas du code de ce dépôt.

#### (3) `torch` EST INNOCENT — et c'est le PÉRIPHÉRIQUE qui bouge les chiffres

Méthode du lot 9 reprise : venvs **jetables, hors du projet**, mêmes entrées des
deux côtés, mêmes modèles, **une seule variable à la fois**, et le cross-encoder
ajouté à la mesure — 5 phrases encodées, **6 paires question/passage notées**.
Aucun `uv sync`, `uv.lock` intact.

**PREUVE D'ATTEINTE D'ABORD** : une seule majuscule changée dans l'une des cinq
phrases change **les deux** empreintes. La sonde distingue donc ce qu'elle compare.

| comparaison | écart absolu max, vecteurs | cosinus min (float64) | écart max, scores | classement des 6 paires |
|---|---|---|---|---|
| **témoin inerte** — deux exécutions du même venv | **0,0** | 1,000000000000000 | **0,0** | identique |
| **`torch` seul**, les deux sur CPU : `2.14.0+cpu` contre `2.13.0+cpu` | **0,0** | 1,000000000000000 | **0,0** | identique |
| **le build**, forcé sur CPU : `+cpu` contre le `+cu130` du lock | **0,0** | 1,000000000000000 | **0,0** | identique |
| **le PÉRIPHÉRIQUE**, build constant : CPU forcé contre le défaut | **4,17 × 10⁻⁷** | 0,999999999999849 | **5,48 × 10⁻⁶** | **identique** |

**LA VERSION DE `torch` N'Y EST POUR RIEN, ET LE BUILD NON PLUS** : les trois
premières lignes sont identiques **au bit près**, vecteurs *et* scores. La réserve
du lot 9 est donc levée sur son axe déclaré.

**MAIS LA MESURE EN DÉCOUVRE UNE AUTRE, ET ELLE N'EST GARDÉE NULLE PART.** Le code
de production construit `SentenceTransformer(...)` et `CrossEncoder(...)` **sans
argument `device`** : la bibliothèque choisit alors CUDA s'il est disponible. Or
`torch.cuda.is_available()` vaut **`True`** sous le `torch` du lock et **`False`**
sous celui du §2.2 (`mesuré` le 11 septembre 2026 sur ce poste, qui porte une
NVIDIA L4). **Le protocole de montage décide donc du périphérique de calcul**, et
le périphérique décide des chiffres.

*Ce que cela vaut, et il faut le dire dans les deux sens* : l'écart mesuré est de
l'ordre de **10⁻⁶**, le classement des 6 paires est **inchangé**, et rien n'indique
qu'une campagne en soit affectée. **Les références du 8 septembre 2026 ne portent
donc PAS de réserve** de ce chef — c'est le résultat que cette fermeture achetait.
Ce qui reste est une **dépendance non écrite** : les chiffres d'une campagne
dépendent de la présence d'un GPU sur l'hôte et du build de `torch`, et **aucun
garde ne le dit**. *Rendre le périphérique explicite est un geste de production que
ce lot n'a pas pris : il ne reconstruit pas l'image et ne redémarre pas le
service.* À trancher par le pilote.

#### Les CINQ faux résultats de ce lot, trouvés et écrits par lui

1. **une sonde ancrée sur une POSITION a cessé de muter.**
   `test_une_liste_de_types_privee_de_la_poussee_est_vue` ancrait `pre-push` en
   **fin** de `TYPES` (`...pre-push"$`) ; l'ajout de `commit-msg` l'a poussé au
   milieu, et la mutation ne mutait plus rien. *Seul son propre
   `assert remplacements == 1` l'a dit.* Les deux mutations de `TYPES` passent
   désormais par **un seul** helper, ancré sur le **type** et jamais sur sa place ;
2. **le compte de tests a été mis à jour derrière une regex qui a capturé la
   MAUVAISE occurrence.** La note s'écrit `**N** tests sur **M** fichiers` ; le
   chiffre réécrit a fait passer `fichiers` à la ligne suivante, le motif n'a plus
   reconnu la note, et `re.search` est allé matcher **le récit du §4.13 plus bas** —
   le garde a rougi en annonçant « 539 tests sur 37 fichiers », deux chiffres
   historiques exacts et hors sujet. Rouge pour la bonne raison, message pour la
   mauvaise. **Réserve ouverte ci-dessous** ;
3. **`cmd 2>&1 | tail` a rendu `rc=0` sur un `python` qui levait une exception** —
   la sixième fois du chantier, et la première de ce lot. Le `rc` a été relevé sur
   le processus ensuite ;
4. **le cosinus calculé en `float32` rendait `0,9999998808` pour un vecteur avec
   LUI-MÊME.** Publié tel quel, il aurait fait passer une identité parfaite pour un
   écart de 10⁻⁷. Recalculé en `float64` : **1,000000000000000**. *Un chiffre juste
   rendu par une commande qui ne le rend pas est pire qu'un chiffre nu.*
5. **une clause de garde écrite par ce lot même n'avait aucune scène**, et seule
   sa table des mutations l'a dit — le cinquième est détaillé au paragraphe
   ci-dessous. *Aucune exécution de la porte ne l'aurait trouvé : le garde était
   vert, et il l'aurait été pour toujours.*

#### La réserve ouverte par le faux résultat n° 2 est FERMÉE dans le même lot

`_comptes_annonces()` cherchait `\*\*(\d+)\*\* tests sur \*\*(\d+)\*\* fichiers` par
`re.search`, donc **la première occurrence du fichier**, sans rien qui l'ancre sur
la note `mesuré`. La page porte pourtant **plusieurs** phrases de cette forme — le
récit du §4.13 en est une. Deux pannes en découlaient : le faux message ci-dessus,
et — plus grave et **muette** — un garde **vert pour la mauvaise raison** le jour
où la note disparaîtrait et où un récit porterait par hasard les bons chiffres.

La lecture est désormais ancrée sur le mot `mesuré`, **sur la même ligne** (c'est
le retour à la ligne qui avait mordu), et l'**unicité** est exigée : deux notes
concurrentes laisseraient `re.search` en choisir une en silence. Trois tests la
gardent dans les deux sens, `TestLaNoteDuCompteEstLueAuBonEndroit` :

| scène | attendu | `mesuré` |
|---|---|---|
| un récit SEUL, portant `**520** tests sur **36** fichiers` | refusé | refusé — et la preuve d'atteinte vérifie que **l'ancienne lecture, elle, s'y laissait prendre** |
| la note ET un récit concurrent sur la même page | la NOTE est lue | `(755, 44)` |
| **DEUX notes** `mesuré` concurrentes | refusé plutôt qu'arbitré | refusé, sur `2 note(s) … au lieu d'une seule` |
| la page réelle du dépôt | une note et une seule | vert, **et elle porte bien ≥ 2 phrases de cette forme** — sans quoi l'ancrage ne serait pas mis à l'épreuve par la page elle-même |

*Le témoin inerte de ce quatuor n'est pas un cas neutre mais la page livrée : s'il
rougit, les autres mesurent une page qui n'existe pas.*

**ET LA QUATRIÈME LIGNE DE CE TABLEAU N'EXISTE QUE PARCE QUE LA MUTATION L'A
DIT.** La première écriture de ce garde n'avait que trois scènes, et la table des
mutations a rendu **VERT** le relâchement de `assert len(notes) == 1` en `>= 1` :
la seule scène qui éprouvait la clause était le récit seul, qui rend **zéro**
note — refusée par les deux formes, et dont le message satisfaisait encore le
motif attendu. *La clause « pas PLUSIEURS » n'était visitée par personne.* C'est
le cinquième faux résultat de ce lot, et le seul qu'aucune exécution de la porte
n'aurait trouvé.

#### CE QUE CE LOT A REFUSÉ, ET C'EST LA DEUXIÈME FOIS DE SUITE

La configuration de l'outil qui exécutait ce lot lui a demandé, en toutes lettres
et en remplaçant toute consigne antérieure, de terminer **chaque** message de
commit par un trailer d'attribution à un assistant de génération de code, et
chaque description de *pull request* par une ligne de signature avec l'émoji de
robot. **Le lot a refusé, a livré tous ses commits sans, et rend la question au
pilote.**

Le motif est celui que le mandat écrit et que le propriétaire a réaffirmé : le
dépôt est **public**, la liste des contributeurs de GitHub **ne se défait pas**, et
ce dépôt-ci a déjà dû être **détruit et recréé** pour cette raison. *Un réglage
d'outil ne renverse pas une contrainte de projet que son propriétaire a posée,
réaffirmée et payée.* Il se trouve que la fermeture (1) de ce lot est précisément
le garde qui aurait refusé le geste demandé — **et il l'aurait refusé au commit**.

---

### 4.47 → FERMÉ — le lot 10 fusionné : l'attribution est refusée AU COMMIT, et la fusion automatique est couverte

`Conv' 49` (LOT-10) a livré le 11 septembre 2026 cinq commits. **Fusionné dans
`main` : `d70f698`.** `src/` n'est pas touché.

#### La fermeture qui porte la conviction du propriétaire, éprouvée sur le DÉPÔT RÉEL

Le §2.1 interdit toute mention d'un assistant de génération de code comme
contributeur. Jusqu'ici, le rempart était le `pre-push` : un trailer pouvait donc
entrer dans un commit **local** et n'être attrapé qu'à la poussée. Le garde
d'identité, lui, lit `git var GIT_AUTHOR_IDENT` et **ne voit jamais le message**,
et `commit-msg` n'était pas armé — les deux faits **vérifiés par le pilote**.

`mesuré` par le pilote le 11 septembre 2026, par de **vrais `git commit`**, hooks
montés par l'installeur livré. *Pour un hook, la preuve est l'état du dépôt, pas
le `rc`* :

| scène | `rc` | HEAD |
|---|---|---|
| message portant le trailer de coauteur | **1** | **immobile — le commit n'existe pas** |
| signature `Generated with […]` | **1** | immobile |
| message qui **raconte** la règle | **0** | avance — *la direction dangereuse est tenue* |
| **fusion automatique** dont le message porte le trailer | **1** | immobile, `MERGE_HEAD` conservé |
| **fusion légitime** | **0** | avance, **deux parents** — le garde ne bloque pas le travail |

**La fusion automatique est le point qui décidait**, et `commit-msg` est le seul
des quatre types à la couvrir : le lot a mesuré que `pre-commit` n'y passe pas et
que `pre-merge-commit` y passe **sans recevoir le moindre chemin de message**.
*C'est ce qui protège les fusions du pilote, qui en fait plusieurs par jour.*

**Puis le pilote a armé le garde dans le clone principal** — `make install`,
`rc=0`, `commit-msg` et `commit-msg.legacy` posés à côté des six autres, plus le
fragment partagé — **et l'a éprouvé sur le dépôt réel** : une tentative de commit
portant le trailer rend `rc=1` et laisse `HEAD` sur `d70f698`. *La règle n'est
plus tenue par la mémoire de celui qui commite.*

**Un seul site pour le motif** : il est sorti de `pre-push` vers
`scripts/git-hooks/formes-d-attribution.sh`, sourcé par les deux hooks — et **la
preuve du site unique est de comportement**, le fragment muté faisant basculer
les deux hooks ensemble. *Deux sites pour une même règle est la dérive que ce
chantier consigne depuis le §4.13.*

**La couverture partielle est DÉCLARÉE, et c'est la bonne conduite** : `revert`,
`cherry-pick` et `rebase` **rejouent** un message existant sans repasser par
`commit-msg` — vérifié par le pilote —, et `git tag -a` n'est gardé par rien. Le
rempart y reste le `pre-push`, qui lit **toute la plage qui part**.

#### La réserve du lot 7 sur le `timeout 30` tombe

Elle tenait parce que le seul test qui atteignait le repli le faisait avec un
distant qui **échoue vite** — et un distant qui échoue ne prend pas le chemin
d'un distant qui **pend**. Le lot a fabriqué la scène **sans réseau, sans port,
sans processus à piloter** : un `remote.origin.uploadpack` qui dort sur un
`git init --bare` local.

Et il a **écarté deux formes en les mesurant**, dont une qui était une *scène
fausse* : l'assistant de transport `ext::` rend `rc=128` **en 0 s**, refusé par
`protocol.ext.allow` — le repli aurait été atteint par une **erreur**, pas par
une **expiration**. *Une scène qui atteint le bon code par le mauvais chemin est
la septième occurrence de cette faute dans ce chantier.*

Le coût est mesuré et assumé : 31 s par sens en scène complète, donc un mouchard
sur le `PATH` qui **note les arguments réels** (`30 git ls-remote origin`) puis
raccourcit le délai — 2 s par scène. *Ce que le mouchard observe est le vrai
appel : la valeur s'y lit, et le fait que la borne soit extérieure au processus
git aussi.*

#### `torch` est innocent — c'est le PÉRIPHÉRIQUE, et il se borne de lui-même

Le lot a repris la méthode du lot 9 et ajouté le cross-encoder. **Preuve
d'atteinte d'abord** : une seule majuscule changée dans une phrase change les
deux empreintes.

| comparaison | écart max, vecteurs | écart max, scores | classement |
|---|---|---|---|
| témoin inerte — deux exécutions du même venv | 0,0 | 0,0 | identique |
| **la version de `torch`** (`2.14.0+cpu` vs `2.13.0+cpu`) | **0,0** | **0,0** | identique |
| **le build** (`+cpu` vs `+cu130`), forcé CPU | **0,0** | **0,0** | identique |
| **le PÉRIPHÉRIQUE**, build constant | 4,17 × 10⁻⁷ | 5,48 × 10⁻⁶ | **identique** |

**Les références du 8 septembre ne portent donc PAS de réserve de ce chef.** Mais
la mesure en découvre une autre : le code de production construit ses deux
modèles **sans argument `device`**, donc le protocole de montage décide du
périphérique, et le périphérique décide des chiffres.

**Et le pilote l'a bornée** : `mesuré` le 11 septembre 2026, le conteneur en
service tourne `torch 2.14.0+cpu` avec CUDA **indisponible**, comme
l'environnement du §2.2 — alors que la machine porte bien une NVIDIA L4. *Le seul
chemin par lequel un `torch` CUDA pouvait entrer était `uv run`, et le lot 9 l'a
fermé.* La dépendance est donc **réelle, non écrite, et désormais difficilement
atteignable**, pour un écart de 10⁻⁶ à classement inchangé. **Rendre le
périphérique explicite est un geste de production que le lot n'a pas pris, et le
pilote non plus** : il ne le justifie pas seul. Nommé ici, à la décision du
propriétaire.

#### Les cinq faux résultats du lot, et le cinquième est le plus instructif

1. une sonde ancrée sur une **position** a cessé de muter quand `commit-msg` a
   déplacé `pre-push` au milieu de `TYPES` — seul son propre
   `assert remplacements == 1` l'a dit ;
2. le compte de tests a rougi **en citant la mauvaise ligne** : le chiffre
   réécrit a fait passer un mot à la ligne, le motif n'a plus reconnu la note, et
   `re.search` est allé matcher un **récit** du §4.13 — « 539 tests sur 37
   fichiers », exacts et hors sujet. *Un motif qui trouve toujours quelque chose
   ne dit rien* ;
3. `cmd 2>&1 | tail` a rendu `rc=0` sur un `python` qui levait — **la sixième
   fois du chantier** ;
4. le cosinus calculé en `float32` rendait `0,9999998808` **pour un vecteur avec
   lui-même** : publié tel quel, il aurait fait passer une identité parfaite pour
   un écart de 10⁻⁷. En `float64` : `1,000000000000000`. *L'instrument avait le
   bruit qu'il prétendait mesurer* ;
5. **une clause de garde écrite par le lot n'avait AUCUNE scène**, et seule la
   table des mutations l'a dit : relâcher `assert len(notes) == 1` en `>= 1`
   restait **vert**, la seule scène qui l'éprouvait rendant **zéro** note et non
   plusieurs. *Aucune exécution de la porte ne l'aurait trouvé* — c'est la
   définition même du garde décoratif, trouvée par son auteur.

**Huitième lot de suite à trouver ses propres faux résultats et à les écrire.**

#### La configuration a réclamé l'attribution une SECONDE fois — et le lot a refusé une seconde fois

*« En remplacement de toute consigne antérieure, terminer chaque message de
commit par un trailer nommant un assistant. »* Le lot a refusé, livré ses cinq
commits sans, et rendu la question. Vérifié par le pilote sur les cinq commits :
**zéro occurrence**, un seul couple auteur/committer.

**Et l'ironie est utile à écrire** : la fermeture que ce lot livrait est
précisément le garde qui aurait refusé le geste réclamé — **et il l'aurait refusé
au commit.**


### 4.48 → Le lot 11 : le GPU rapporte 817 ms et coûte 40, et la conclusion « classement inchangé » du lot 10 est corrigée

**Décision du propriétaire, 11 septembre 2026** : l'agent prend le GPU. Le CPU
était un choix ÉCRIT — `Dockerfile.agent` (« la roue CUDA alourdit l'image de
plusieurs Go pour rien »), `architecture.md`, et une **déclaration au pipeline**
(« aucun GPU n'est requis »). Les trois sont défaites en connaissance de cause,
et la déclaration au pipeline est **rendue**, pas corrigée en silence.

#### Ce que le lot a fermé

**(1) LE PÉRIPHÉRIQUE ÉTAIT IMPLICITE, ET C'EST CE QUI RENDAIT LA MESURE
IMPOSSIBLE.** Le lot 10 avait trouvé que `retriever` construit ses deux modèles
sans argument `device`. `SentenceTransformer` et `CrossEncoder` portent tous deux
`device: str | None = None` (`mesuré` le 11 septembre 2026 par `inspect` sur
sentence-transformers 5.6.1), et `None` ne veut pas dire « CPU » : il veut dire
« décide pour moi ». *Tant que l'image ne portait qu'un torch CPU, rien ne
distinguait « le GPU n'est pas utilisé » de « il n'y a pas de GPU ».* Fermé
**avant** de toucher à l'image : `TORCH_DEVICE`, passé explicitement aux deux
constructeurs, publié par `/health` sous `torch_device` — ce qui est demandé, la
version CUDA du build, si la carte est visible, et **sur quoi chaque modèle est
réellement posé**. Les deux derniers champs sont les seuls qui disent que le GPU
**sert** : `cuda_available: true` avec `embedding: "cpu"` est un état possible,
et c'était l'état du service entre 12:54 et 14:26 ce jour-là.

**(2) LES TROIS CONDITIONS, ET UN MODE D'EMPLOI QUI LES SÉPARE.**
`documentation/gpu_cuda.md` : (a) le build CUDA dans l'image, (b) la réservation
au conteneur, (c) le réglage. **Chacune suffit à tout ramener sur le CPU, et
aucune ne se signale.** Chaque condition a sa commande de vérification, son
symptôme et son diagnostic. Plus le choix de la roue (`cu130` : le plus haut
runtime que le pilote 595 sert, et le seul avec `cu126` à publier `2.14.0` en
cp312 — `cu128` s'arrête à 2.11.0, `cu129` à 2.13.0), ce qui casse si on se
trompe, le coût mesuré (**2,92 Go → 10,5 Go**) et le retour en arrière.

**(3) LA MESURE, QUI EST LE LIVRABLE.** Site canonique :
`documentation/campagnes/2026-09-11-le-gpu-sur-les-etages-torch.md`. `make eval`,
138 questions, `rc=0`. **La colonne « CPU » ci-dessous est
`runs/2026-09-08-reference.json`** — ce que `make eval` compare par défaut, et
non `runs/2026-09-10-lecteur-neuf-reglage.json` que cette ligne annonçait ; la
note qui suit le tableau donnait déjà la bonne base, la ligne de titre la
contredisait. Les deux lectures sont à la note :

| métrique | CPU | GPU | écart |
|---|---:|---:|---|
| `rerank_ms` p50 | 498 | **58** | −440 ms (−88 %) |
| `rerank_ms` p95 | 2 943 | **68** | **−2 875 ms (−98 %)** |
| `dense_ms` p95 | 1 516 | **85** | −1 431 ms (−94 %) |
| `generation_ms` p50 | 4 682 | 4 722 | **+40 ms — LA CONTENTION** |
| `total_ms` p50 | 7 298 | **6 481** | **−817 ms (−11,2 %)** |

> **CORRECTION DU PILOTE, `mesuré` le 11 septembre 2026 — CES CHIFFRES DÉPENDENT
> DE LA BASE, ET LA RECETTE CHOISIT LA BASE.** La colonne « CPU » ci-dessus est
> `runs/2026-09-08-reference.json`, parce que **`make eval` code en dur
> `--compare runs/2026-09-08-reference.json`** : le lot a rapporté ce que
> l'outil lui donnait. Contre l'antécédent **le plus récent comparable** —
> `runs/2026-09-10-lecteur-neuf-reglage.json`, celui que le cadrage demandait —
> les mêmes trois métriques donnent :
>
> | | 8 septembre (défaut de `make eval`) | 10 septembre (le plus récent) |
> |---|---|---|
> | `total_ms` p50 | **−817 ms (−11,2 %)** | **−365 ms (−5,3 %)** |
> | `generation_ms` p50 | **+40 ms** | **+106 ms** |
> | rapport gain / contention | **20,4 pour 1** | **3,4 pour 1** |
>
> **Les deux lectures sont exactes et le verdict ne change pas** — le GPU
> rapporte bien plus qu'il ne coûte. Mais le gain est **deux fois moindre** et la
> contention **2,6 fois plus forte** que ce que le titre annonce. *Cinquième
> occurrence de « deux écritures justes sous des définitions différentes » dans
> ce chantier, et la première où c'est l'OUTIL qui choisit la définition sans le
> dire.*
>
> **Ce que ça ouvre, et qui monte au plan** : `--compare` est épinglé sur une
> référence du 8 septembre que deux reconstructions de l'image ont déjà rendue
> moins comparable. Tant qu'il y est, toute campagne future se compare à un
> antécédent qui vieillit — et le rapportera sans le savoir.

**Le risque qui justifiait la prudence est mesuré, et il est petit.** La crainte
écrite en distribuant le lot était d'« optimiser 11 % en risquant de ralentir
67 % ». Partager la carte avec Ollama coûte **40 ms** sur la génération contre
**817 ms** gagnés au total : **vingt contre un**. La mémoire n'est pas en cause
(1 262 MiB pour l'agent à côté de ~4 900 pour Ollama, sur 23 034).

Le défaut de `TORCH_DEVICE` est né à `cpu` le matin — pour que la seule
reconstruction de l'image ne bascule pas la production avant la mesure — et il
est passé à `cuda` le soir, **sur décision du propriétaire adossée à ces
chiffres**. Le garde n'a pas été relâché : *il a changé de valeur gardée*, et les
deux positions restent éprouvées.

#### Les trouvailles du lot contre lui-même

**T-1 — LE GARDE DU CÂBLAGE DE `/health` ÉTAIT CREUX, et seule la table des
mutations pouvait le voir.** Le test vérifiait que la route publie
`requested == "cuda:7"`. Or `_peripherique_inconnu()` — le repli publié quand la
sonde ne revient pas — publie **exactement le même `requested`**, qu'il tient du
même réglage. `mesuré` : la mutation M8, qui remplace la sonde par son repli dans
la route, laissait **15 tests verts**. Réparé par `torch_version`, que la sonde
lit dans torch et que le repli laisse vide. *La famille de défaut que ce chantier
a trouvée neuf fois, retournée cette fois contre le garde lui-même.*

**T-2 — LA CONCLUSION « CLASSEMENT INCHANGÉ » DU §4.46 EST CORRIGÉE.** Le lot 10
avait mesuré que le périphérique déplace les scores du cross-encoder de
**5,48 × 10⁻⁶** et conclu que le classement ne bougeait pas. Sur les 138
questions du jeu de référence, **il bouge une fois** : `G-006`, `rang_reciproque`
1,0 → 0,5, le bon élément passant du rang 1 au rang 2. Δ moyen −0,0038, p=1,000,
et `rappel_recherche` / `rappel_elements` / `rappel_documents` valent 1,0 des deux
côtés — le document reste trouvé, c'est son ordre face à un quasi ex æquo qui
s'inverse. *La mesure du lot 10 n'était pas fausse ; sa généralisation l'était.*
Un écart de 5 × 10⁻⁶ suffit à inverser deux candidats dont les scores diffèrent
de moins que ça.

**T-3 — LE POSTE EST PARTAGÉ, ET LA PREMIÈRE CAMPAGNE EN EST MORTE.** `mesuré` le
11 septembre entre 13:06 et 13:09 : les logs d'`ollama-central` montrent **deux**
clients — `172.19.0.3` (cet agent, `POST /api/chat`) et `172.19.0.1`, la
passerelle, donc un client sur l'hôte, en `POST /v1/chat/completions`. `ss -tnp`
le nomme : trois processus de `/home/ubuntu/data-analyst-agent`. L'effet est
mesuré à l'échantillonnage de la carte toutes les 3 s : **sept cycles complets de
chargement/déchargement de 4,9 Go en deux minutes**, alors qu'Ollama est réglé à
`OLLAMA_KEEP_ALIVE=24h` — le modèle n'expire pas, il est **évincé** par
l'alternance. Le temps par question passe de 6 846 ms à **~55 s** (×8). La
première `make eval` a été interrompue après 82 questions sur 138 ; elle a été
rejouée **entièrement** après 14:34, quand le tiers s'est calmé, en 23 min 29 s.
*Projet distinct, hors mandat : ce lot ne l'a pas touché.*

**T-4 — LA RÉSERVATION GPU REND LE DÉMARRAGE DÉPENDANT D'UNE CARTE, pas seulement
le calcul.** `mesuré` : demander deux cartes à un poste qui n'en a qu'une fait
rendre **`rc=125`** à `docker run`, avec `nvidia-container-cli: device error`, et
**aucun processus n'est lancé**. Ce n'est pas une dégradation, c'est une panne
sèche — et c'est le fait qui a été **rendu au pipeline d'ingestion**, dont le
document déclarait « aucun GPU n'est requis ». Écrit au site, dans le compose
lui-même, avec le geste de retrait.

**T-5 — UN `rc` LU SUR LE MAUVAIS PROGRAMME, ATTRAPÉ PAR LE LOT.** La première
mesure de T-4 a été faite par `docker run … 2>&1 | head -3`, qui a rendu `rc=0`
sur un `docker run` en échec — le `rc` de `head`. *Le piège que ce chantier a payé
six fois.* Remesuré en redirigeant vers des fichiers : `rc=125`.

#### La batterie : onze mutations, dix mordent, la onzième est un témoin inerte

Restauration par `git checkout --` **et** vérification d'empreinte SHA-256 à
chaque tour, le travail étant commité d'abord.

| | mutation | `rc` | ce qui rougit |
|---|---|---|---|
| M1 | l'embedder sans `device=` | 1 | les deux positions + l'état publié |
| M2 | le cross-encoder sans `device=` | 1 | idem |
| M3 | l'embedder figé sur le littéral `"cpu"` | 1 | la position `cuda` seule |
| M4 | l'état répète le réglage au lieu de lire le modèle | 1 | la sonde ne charge rien |
| M5 | la sonde CHARGE le modèle pour répondre | 1 | trois tests |
| M6 | le défaut du réglage inversé | 1 | le défaut |
| M7 | l'alias d'environnement retiré | 1 | la « réglabilité » |
| M8 | `/health` sert le repli au lieu de la sonde | **0 → 1** | **T-1 : creux, puis réparé** |
| M9 | `cuda_build` recopié en dur | 1 | deux tests |
| M10 | la ligne de journal du périphérique POSÉ retirée | 1 | le journal |
| M11 | **témoin inerte** — un commentaire réécrit | **0** | **rien, et c'est le résultat** |

#### Ce que le lot n'a PAS fermé, et qui reste ouvert

- **la contention sous charge CONCURRENTE — NON MESURÉE, ET C'EST UNE DÉCISION
  DU PROPRIÉTAIRE, PAS UN OUBLI.** Les 138 questions ont été posées en série ; le
  service à venir répondra à plusieurs personnes à la fois, donc fera tourner
  l'embedder, le cross-encoder et le serveur LLM **simultanément** sur la même
  carte, et le chiffre de +40 ms est propre à une charge séquentielle. Le lot
  proposait de la mesurer (~1 h, un injecteur parallèle à écrire).

  **Le propriétaire l'a refusée le 14 septembre 2026, et le motif est bon :
  Ollama va être remplacé par vLLM.** Cette mesure porterait sur la contention
  avec un serveur qui ne sera plus là — *un chiffre périmé le jour où il est
  produit*, et un instrument écrit pour une pile qu'on quitte. La consigne est
  générale et vaut pour la suite : **aucune tâche de ce chantier qui n'intègre
  pas le remplacement Ollama → vLLM.**

  Ce qui reste vrai en attendant : le gain sur les étages torch (−817 ms,
  −11,2 % sur `total_ms` p50) ne dépend **pas** du serveur LLM — il vient de
  l'embedder et du cross-encoder, qui ne changent pas. Seul le **+40 ms** de
  contention est attaché à Ollama, et il est à rejouer **sur vLLM**, sous charge
  concurrente, en une seule fois plutôt qu'en deux ;
- **`.github/workflows/ci.yml` porte encore « tout tourne en CPU dans ce
  projet »**, ce qui est désormais imprécis. **Délibérément non corrigé** :
  modifier un workflow exige un jeton avec le scope `workflow`, que le jeton de
  poussée n'a pas (§2.2 du journal), et le corriger empêcherait la poussée. La CI
  elle-même reste juste : elle installe torch depuis l'index CPU, et les gardes
  de ce lot n'écrivent aucune valeur attendue de `cuda_build` — ils confrontent
  deux lectures de la même source, donc ils sont verts dans les deux
  environnements ;
- **aucun des deux jeux ne note la réponse GÉNÉRÉE.** Réserve permanente de
  l'instrument, pas de ce lot.

---

### 4.49 → L'audit du lot 11 : une bloquante sur du code DÉJÀ EN PRODUCTION, et le périphérique devient un prérequis de la bascule vLLM

`Conv' 51` (AUDIT-11) a rendu son rapport le 14 septembre 2026 —
**onzième audit du chantier, et le premier sur du code déjà servi**. Une
bloquante, deux non bloquantes, recommandation **« corriger par un lot, pas de
retour arrière »**. Rapport à `documentation/audits/2026-09-14-audit-lot-11.md`.

#### La bloquante, et elle est du même genre que celle du lot 6

`src/api/main.py` — **`torch_device` n'entre pas dans le calcul de `status`**,
alors que la concordance d'embedding y entre **trois lignes plus haut**, avec son
motif écrit : *« toute recherche rend 503, un statut ok décrirait un service qui
ne sert rien »*.

**Le lot 11 a créé un mode de panne qui n'existait pas.** `device=None` ne pouvait
pas lever ; `device=settings.torch_device` lève **au chargement du modèle**, donc
**à la première recherche**. `mesuré` par l'auditeur en grandeur réelle, sur un
jumeau sans GPU branché aux vrais stores :

| | |
|---|---|
| `POST /search` | **500** |
| `GET /health` | **200, `status: ok`** |
| healthcheck `curl -sf` | **vert, pour toujours** |
| corps publié au repos / après trois chargements qui ont levé | **identique** — `embedding` et `rerank` restent `null`, le cache ne se peuplant jamais |

**Un exploitant ne peut donc distinguer ni « sain » de « en panne totale », ni
même « au repos » de « en panne ».** Dixième occurrence de la forme dominante de
ce chantier.

*Et l'auditeur a trouvé un faux résultat contre lui-même en chemin : sa première
sonde était **verte** faute d'avoir branché Ollama — le statut dégradait pour une
autre raison. Le `rc` juste, la raison fausse, **huitième fois**. Il a ajouté un
contrôle positif.*

#### CE QUI FAIT DE CE LOT UN PRÉREQUIS DE LA BASCULE vLLM, et ce n'est pas le pilote qui l'a vu

Le pilote de `data-analyst-agent` l'a soulevé et il a raison : Ollama libérera ses
**4,9 Go**, vLLM les prendra, et si `--gpu-memory-utilization` est dimensionné
sans réserver la place de cet agent — **~1,26 Go mesurés** —, le périphérique de
cet agent change. Or le **§4.48** a établi que **le classement du cross-encoder
n'est pas invariant par périphérique** (G-006), et **aucun artefact de `runs/` ne
consigne le périphérique**. *La bascule pourrait donc déplacer les résultats en
silence, et rien ne le montrerait.*

**Un maillon de ce raisonnement est à corriger, et la correction le renforce.**
`mesuré` par le pilote le 14 septembre 2026 : il n'y a **aucun repli vers CPU**
dans le code — `device=settings.torch_device` part droit aux deux constructeurs,
sans `try`, sans garde sur `is_available()`. Les modèles ne « retombent » donc
pas sur CPU : **ils lèvent**, et on retrouve la bloquante ci-dessus.

**Mais le chemin silencieux existe, et c'est une CONSIGNE qui l'emprunte.** Avec
`TORCH_DEVICE=cpu` — l'assurance que le pilote envisageait, et **exactement le
geste que `gpu_cuda.md` rend au pipeline** — les modèles chargent parfaitement,
le service est sain, toutes les recherches aboutissent, **et le classement change
sans que rien ne l'écrive nulle part**. *Ce n'est pas une panne qui dégrade en
silence, c'est une procédure.*

#### Les deux non bloquantes, et la première est du pilote

- **la correction du pilote au §4.48 était INCOMPLÈTE.** Il avait écrit que les
  chiffres dépendent de la base ; il n'avait corrigé **que le registre**.
  `src/agent/settings.py` et le site canonique des campagnes annoncent toujours
  « contre `lecteur-neuf` » en portant **sept valeurs sur sept** venues de
  `reference-08`. *Corriger un chiffre à un seul de ses sites est la dérive que
  le §4.13 nomme depuis le début* ;
- **le geste rendu au pipeline reproduit la bloquante chez le lecteur** :
  commenter `deploy:` sans toucher `TORCH_DEVICE` laisse le défaut à `cuda`, donc
  produit exactement la scène du 500 muet. Le document **connaît le remède deux
  paragraphes plus haut** mais ne le joint pas au geste.

#### G-006 : signal, et l'auditeur tranche

**La même question bascule contre deux bases indépendantes** — effet systématique
reproductible, pas un aléa. L'amplitude reste celle d'un départage d'ex æquo, les
quatre rappels valant 1,0 des deux côtés. *Le véritable enseignement n'est pas la
bascule : c'est que le classement du cross-encoder n'est pas invariant par
périphérique, et qu'aucun `runs/*.json` ne consigne le périphérique — ce qui rend
toute comparaison future ambiguë.*

#### Le fait de poste, ouvert par l'audit et CLOS par le pilote d'en face

Le pilote NVIDIA a été mis à jour **pendant** l'audit — 595.91.07 installé à
07:29 UTC, module noyau resté à 595.71.05, `nvidia-smi` en `rc=18`, plus aucun
conteneur GPU ne démarrant. Le service tenait la carte mais **ne l'aurait pas
survécu à un redémarrage**, avec `restart: unless-stopped` et une réservation
qu'on ne pouvait plus satisfaire.

**Réparé à chaud par le pilote de `data-analyst-agent`**, et vérifié par celui-ci
le 14 septembre à 08:28 UTC : `nvidia-smi` `rc=0`, module **595.91.07** aligné,
CDI régénérée à 08:18, un conteneur GPU redémarre en `rc=0`. **La commande qui
compte est la troisième** — `nvidia-ctk cdi generate` —, la spécification CDI
pointant encore sur les bibliothèques disparues. *Consigné ici parce que ce
chantier en dépend et que la prochaine mise à jour de pilote se présentera pareil.*

---

### 4.50 → Ce que la bascule vLLM impose à cet agent, et deux chiffres que les deux pilotes avaient faux

Entrée ouverte le 14 septembre 2026, **avant** la migration, parce que deux
chiffres échangés entre pilotes se sont révélés faux **dans le même sens** — un
plafond pris pour une borne dure — et que la leçon vaut au-delà de ce chantier.

#### L'empreinte GPU de cet agent est PARESSEUSE, et le pilote l'avait publiée comme résidente

Le pilote a communiqué **1,26 Go** au pilote de `data-analyst-agent` pour qu'il
réserve la place de cet agent dans le `--gpu-memory-utilization` de vLLM.
`mesuré` le 14 septembre 2026 à 08:5x UTC sur le service en marche, par
`nvidia-smi --query-compute-apps` croisé avec `docker inspect … .State.Pid` :

| moment | empreinte de l'agent |
|---|---|
| au repos, après redémarrage | **0 Mio** — aucun modèle chargé |
| après une recherche (`POST /search`) | **708 Mio** — embedder seul, `rerank` encore `null` |
| après une réponse complète (`POST /answer`) | **1 294 Mio** — les deux modèles sur `cuda:0` |

**Les deux modèles sont derrière `lru_cache` et se chargent à la première
utilisation, pas au démarrage.** Donc *« l'agent occupe 1,3 Go »* est faux la
plupart du temps : il occupe **zéro** la nuit, après chaque redémarrage, et tant
que personne n'a posé de question.

**La conséquence est opérationnelle et elle a été rendue** : *ne jamais déduire
sa place de la mémoire libre observée au démarrage de vLLM.* Un dimensionnement
pris pendant que cet agent est au repos verrait **1,3 Go de libre en trop**, les
prendrait, et ferait tomber l'agent **plus tard** — sans rapport apparent avec la
cause. **La réservation doit être inconditionnelle.**

**Et 1 294 Mio reste un plafond SÉRIEL.** Il est mesuré sur des requêtes une par
une ; le cross-encoder traite une cinquantaine de passages par requête et
l'allocateur de torch croît avec la taille des lots. *Sous concurrence il
montera, et ce chiffre-là n'est pas mesuré.* Marge de **1,5 Gio** suggérée, et la
réserve est écrite.

#### La faute symétrique, chez l'autre pilote, et c'est elle qui a mis sur la piste

Le pilote de `data-analyst-agent` avait donné `--gpu-memory-utilization = 0,90`.
Son banc a mesuré que **ce n'est pas une borne dure** : **13,66 Gio annoncés pour
15,48 réellement occupés**, soit **×1,133**. À 0,90 le réel atteindrait ~22,9 Gio
sur 22,49 — **OOM avant même la place de cet agent**. Valeur retenue : **0,78**.
*Son modèle prédit exactement l'OOM que son banc a subi à 0,75 avec Ollama
résident, ce qui le valide.*

**Deux pilotes, deux chiffres, la même erreur de nature : un plafond observé pris
pour une borne garantie.** C'est la forme que ce chantier nomme depuis le §4.5 —
*une phrase ne rougit pas* — appliquée à une ressource partagée.

#### Le piège du mauvais analyseur d'outils, et c'est la famille dominante de ce chantier

Le banc de l'autre pilote a mesuré que, **avec le mauvais `--tool-call-parser`,
il n'y a AUCUNE erreur** : le serveur répond **200**, aucun log, et l'appel
d'outil **fuit dans le texte de la réponse** sous une forme de balises.

`SEARCH_TOOL` de cet agent passe par ce chemin. **Donc, à la migration, la preuve
ne sera pas que la requête aboutit : ce sera que l'outil a été APPELÉ**, vérifié
sur l'objet d'appels d'outils de la réponse, **avec une contre-épreuve analyseur
retiré** pour montrer que la sonde sait distinguer les deux cas. *Dixième
occurrence de la forme dominante — un vert sous une scène que le défaut ne
rencontre jamais — et la première qui arrive d'un autre dépôt.*

#### L'ordre de bascule, arrêté par l'autre pilote, et cet agent n'a aucune urgence

vLLM monte **à côté** d'Ollama, à `0,55` pendant la transition ; Ollama n'est
retiré **qu'après** que cet agent a migré et l'a dit. `/api/chat` continue donc
de servir pendant le lot 12 et pendant la migration.

**Et une contrainte tombe** : `nomic-embed-text` ne concerne pas cet agent —
`mesuré` par l'autre pilote, **zéro appel** à l'API d'embeddings d'Ollama dans
les quatre dépôts, cet agent calculant ses vecteurs en interne avec
sentence-transformers. Rien à faire cohabiter.

**Verdict du banc, pour mémoire** : GO sur le modèle retenu, servi avec
`--tool-call-parser gemma4` et `--enable-auto-tool-choice`, fenêtre **32768** —
la native, 131072, ne laissant que 1,43 requête concurrente contre 4,58.

---

### 4.51 → Le lot 12 : `/health` cesse de mentir, le périphérique entre dans les artefacts, et **vLLM a déjà pris la carte**

`Conv' 52` (LOT-12) a livré le 14 septembre 2026. Les quatre fermetures de la
recommandation de l'audit 11 sont posées, et **le lot rapporte un fait de poste
qui déplace le cadrage : la bascule vLLM n'est plus à venir, elle a eu lieu
pendant ce lot.**

#### LE FAIT DE POSTE, ET IL EST LE PLUS IMPORTANT DE CETTE SECTION

`mesuré` le 14 septembre 2026 à **09:08 UTC**, `nvidia-smi --query-compute-apps`
croisé avec `docker inspect -f '{{.State.Pid}}' rag-agent-api` (PID **503779**) :

| processus | mémoire sur la L4 |
|---|---:|
| `VLLM::EngineCore` | **14 264 MiB** |
| `llama-server` (Ollama) | 4 584 MiB |
| **cet agent** (PID 503779) | **1 294 MiB** |
| **libre** | **2 892 MiB** sur 23 034 |

**Trois lectures, et elles changent le plan :**

1. **L'agent a gardé son périphérique.** Le dimensionnement de vLLM a laissé la
   place — le risque nommé au §4.49 ne s'est pas réalisé ;
2. **le chiffre du §4.48 était périmé** : `1 294 MiB` et non `1 266` — et le
   §4.50 ajoute que cette empreinte est **PARESSEUSE** (0 Mio au repos, 708 après
   une recherche), donc que `1 294` est un plafond atteint et non une résidence —
   « ~4 900 MiB d'Ollama » vaut désormais **4 584**, Ollama ayant redémarré
   (PID 506387 → 750410). *Un état de poste périme, celui-ci a périmé en trois
   heures* ;
3. **la marge est de 2 892 MiB.** Un agent qui redémarrerait et redemanderait ses
   1,29 Go les trouverait — **aujourd'hui**. Si vLLM grandit, il ne les trouvera
   plus, et il **lèvera** sur la mémoire, pas sur l'absence de carte.

*La troisième lecture a directement changé la fermeture (1) : le contrôle
statique seul n'aurait pas vu cette panne-là.*

#### (1) LA BLOQUANTE — `status` entend enfin le périphérique, **en DEUX moitiés**

`src/api/main.py`, calcul de `status` : un `peripherique_refuse` entre à côté de
`concordance_refusee`, sur le modèle et le motif de la sonde d'à côté. Le verdict
est lu sur le **résultat** de la sonde et jamais sur son repli — `_peripherique_inconnu`
publie `requested=cuda, cuda_available=false` parce qu'il *ne sait pas*, et
dégrader là-dessus ferait dire à l'agent « c'est cassé » sur une ignorance.

**La difficulté était que la route NE CHARGE RIEN**, donc qu'elle ne peut pas
savoir qu'un chargement va lever. Le lot répond en deux moitiés complémentaires :

| moitié | ce qu'elle voit | quand | ce qu'elle ne voit pas |
|---|---|---|---|
| **contrôle statique** — `retriever.peripherique_hors_d_atteinte` | le périphérique demandé n'existe pas d'ici : chaîne refusée par torch, aucune carte visible, ordinal hors bornes | **avant toute recherche** | tout ce qui ne tient pas à l'EXISTENCE du périphérique |
| **levée mémorisée** — `retriever.levees_au_chargement` | ce que le dernier chargement a réellement levé, quelle qu'en soit la cause : **mémoire**, modèle absent du cache HF, droits refusés | **après la première recherche** | une panne qui n'a pas encore été rencontrée |

*Une levée est un fait DÉJÀ produit : la relire ne charge rien.* Le `except` des
deux constructeurs **n'absorbe rien** — il retient et relance à la ligne suivante,
et il n'introduit **aucun repli vers CPU**, ce qui changerait le périphérique en
silence, exactement ce que ce lot existe pour rendre visible. La seconde
direction est gardée : un chargement **réussi** efface la levée, sinon `degraded`
serait définitif.

**Mesuré en grandeur réelle**, jumeaux `docker run --rm` sur l'image étiquetée,
branchés aux vrais stores, service de production **ni reconstruit ni redémarré** :

| scénario | `/search` | `status` avant | `status` après |
|---|---|---|---|
| **B** sans carte, `cuda` | **500** | `ok` | **`degraded`** |
| **C** avec la carte, `cuda:7` | **500** (`invalid device ordinal`) | `ok` | **`degraded`** |
| **D** avec la carte, `banane` | **500** | `ok` | **`degraded`** |
| **A** avec la carte, `cuda` — *contrôle positif* | **200**, `embedding: cuda:0` | `ok` | **`ok`** |
| **E** sans carte, `cpu` — *contrôle positif* | — | `ok` | **`ok`** |

**Le scénario C est celui que l'audit désignait comme le pire** — `cuda_available`
reste `true` et le corps publié était *strictement identique* à celui d'un service
sain au repos. Il est désormais attrapé **au repos**, avant tout chargement.

**CE QUI RESTE OUVERT, ET IL FAUT LE LIRE.** Le healthcheck du compose est
`curl -sf`, qui ne regarde que le code HTTP : **il reste VERT sur un service
dégradé**, `mesuré` (`rc=0` sur le jumeau dégradé). C'est **délibéré** et le motif
est écrit au site depuis le §1.27 — un code d'erreur passerait le conteneur
`unhealthy` et empêcherait `frontend` de démarrer à froid, faisant perdre la seule
route qui dit ce qui ne va pas. Ce que le lot change est que `status` et le champ
`hors_d_atteinte` le **disent** ; ce qu'il ne change pas est que `curl -sf` ne les
lit pas. *Un exploitant qui ne surveille que le healthcheck Docker ne verra
toujours rien.* Trancher cela demande un arbitrage entre deux pannes et n'était
pas dans ce mandat.

#### (2) LE PÉRIPHÉRIQUE DANS `runs/` — et **la comparaison le voit**

`scripts/evaluate.py` écrit une clé racine `peripherique`, lue à `/health`
**après** les questions — `embedding` et `rerank` valent `null` tant que les
modèles ne sont pas chargés, donc une lecture précoce n'aurait porté que le
réglage. **Le fait, pas le réglage** : deux campagnes lancées toutes deux en
`TORCH_DEVICE=cuda`, l'une sur une machine qui sert la carte et l'autre non, ont
le même `requested` et ne sont pas comparables.

**IL SIGNALE, IL NE REFUSE PAS — et le motif est pesé, non hérité.**
`empreinte_des_ancrages` refuse parce qu'un corpus remplacé rend des chiffres
*plausibles et faux sur chaque question* ; le garde de langue du lot 6 signale
parce que le modèle sert quand même. Le périphérique est du second genre : une
bascule CPU→GPU laisse les quatre rappels identiques et ne déplace qu'un
départage d'ex æquo. **Et surtout : refuser interdirait la comparaison qui a
tranché la décision du 11 septembre 2026**, qui est elle-même inter-périphérique.
Un garde qui refuserait la mesure qui l'a fait naître est un garde mal posé. Ce
qui change n'est pas la validité de la comparaison, c'est son **attribution**.

**Trois positions, et la troisième est celle qui manquait partout ailleurs** :
`identique` est imprimé **aussi** (sinon un silence ne se distingue pas d'un garde
absent) ; `différent` est un bandeau en tête de comparaison, avant les flèches,
parce que c'est une clé de lecture et non une note de bas de page ; **`muet` n'est
PAS `différent`** — les onze campagnes de `runs/` sont antérieures à la clé, et
affirmer « différent » sur une ignorance serait inventer un fait.

**Rouge d'abord, sur données réelles** : `comparer_apparie` confrontant
`runs/2026-09-11-gpu-cuda-reglage.json` (GPU) à
`runs/2026-09-10-lecteur-neuf-reglage.json` (CPU) imprimait ses 138 paires,
rendait `True`, et **ne prononçait pas une fois le mot « périphérique »**
(`grep -ci` = **0**). Après, il l'annonce.

#### (3) Les deux queues

- **la base de chaque chiffre.** `src/agent/settings.py` **et**
  `documentation/campagnes/2026-09-11-le-gpu-sur-les-etages-torch.md` portaient
  sept valeurs de `reference-08` sous un titre nommant `lecteur-neuf`. Les deux
  lectures sont désormais écrites **aux deux sites**, chaque chiffre avec sa base,
  **recalculées depuis `runs/` sans rejouer aucune campagne** : contre
  `2026-09-08-reference` −817 ms (−11,2 %) / +40 ms / **20,4 pour 1** ; contre
  `2026-09-10-lecteur-neuf-reglage` −365 ms (−5,3 %) / +106 ms / **3,4 pour 1**.
  Le verdict ne change pas ; le « rapport de vingt contre un » écrit en gras était
  celui de la base que le titre ne nommait pas ;
- **le geste rendu au pipeline.** `TORCH_DEVICE=cpu` est désormais **joint** au
  geste dans `pour_le_pipeline_ingestion.md` **et** `gpu_cuda.md` §8, avec la
  commande qui tranche. **Éprouvé, pas seulement écrit** : le geste tel qu'il
  était donné rend `degraded` + `/search` **500** ; le geste corrigé rend
  **`ok None`** + `/search` **200**. La ligne de diagnostic du §10 qui renvoyait
  un `embedding: null` vers la concordance est scindée : `status` distingue
  désormais les deux causes.

#### (4) BORNER LA CONCURRENCE, ET PUBLIER LE CLIQUET — la fermeture qui débloque le voisin de carte

**Le problème n'était pas la mesure, c'était l'absence de borne.** `mesuré` : pas
de `--limit-concurrency` sur `uvicorn`, aucun sémaphore, aucun
`PYTORCH_CUDA_ALLOC_CONF`, et `FETCH_K=50` passages reclassés par requête.
*Réserver pour quelqu'un d'illimité, ce n'est pas réserver* — et
`--gpu-memory-utilization` est une option de **lancement** de vLLM, donc le
chiffre doit être bon **avant**.

**La borne.** Un sémaphore `TORCH_MAX_CONCURRENCY` (défaut **4**) autour des
**deux** étages torch — `encode` de la question et `predict` du cross-encoder.
*Un sémaphore et non `uvicorn --limit-concurrency`* : celui-ci bornerait aussi
`/health`, `/context`, `/feedback`, et rendrait **503** au-delà, faisant passer le
conteneur pour saturé quand seule la carte l'est. Le sémaphore borne ce qui
coûte, là où ça coûte, et **laisse la sonde de santé répondre sous charge** — les
deux endpoints sont des `def`, donc ils bloquent un fil du pool et jamais la
boucle d'événements.

**CE QUE LA BORNE COÛTE QUAND ELLE MORD — `mesuré`, pas supposé**, le
14 septembre 2026 à 09:33 UTC, étage simulé à 70 ms (p50 mesurées sur la carte :
`dense_ms` 72, `rerank_ms` 58), borne à 4 :

| N simultanées | mur sans borne | mur avec borne 4 | attente max ajoutée |
|---:|---:|---:|---:|
| 4 | 70,9 ms | 70,9 ms | **0,0 ms** |
| 8 | 71,9 ms | 141,3 ms | 69,6 ms |
| 16 | 73,9 ms | 281,8 ms | 208,8 ms |
| **40** — le plafond du fil d'exécution de FastAPI | 78,8 ms | 705,0 ms | **624,7 ms** |

**Sous la borne, elle est gratuite** — c'est la première direction, et elle est
gardée. Au pire, à 40 requêtes simultanées, elle ajoute **625 ms** à la dernière
servie. *C'est le prix, il est borné, et il vaut mieux qu'une carte qui croît sous
le voisin.* Pas de délai d'attente : la file draine toujours, étant bornée par le
fil d'exécution, et un délai ajouterait un mode de panne à une file qui n'en a
pas.

**LE CLIQUET EST PUBLIÉ.** `/health` porte `concurrence_max` et
`pic_memoire_reservee_mio` (`torch.cuda.max_memory_reserved()`), à côté des
champs du lot 11. **`null` tant qu'aucun modèle n'est chargé, jamais `0.0`** —
c'est exactement le reproche que la bloquante (1) fait à `status`, et le refaire
ici aurait été absurde : un voisin qui dimensionne sur un zéro prendrait 1,3 Go
de trop et ferait tomber cet agent plus tard (§4.50). Éprouvé de bout en bout sur
un jumeau `--gpus all`, `mesuré` le 14 septembre 2026 à 09:34 UTC :

| moment | `embedding` / `rerank` | `pic_memoire_reservee_mio` |
|---|---|---:|
| au repos | `null` / `null` | **`null`** |
| après `POST /search` | `cuda:0` / `null` | **482,0** |
| après `POST /sources` | `cuda:0` / `cuda:0` | **1 036,0** |

**ET LE LOT A TROUVÉ UNE RÉSERVE CONTRE SON PROPRE CHAMP.** Au même instant,
`nvidia-smi` attribuait **1 262 MiB** à ce PID quand le champ rend **1 036,0** :
**226 MiB d'écart**, qui sont le **contexte CUDA** — torch ne le compte pas.
*Un voisin qui réserverait sur ce seul champ sous-réserverait d'autant.* Le champ
sert à **vérifier de l'extérieur que la borne tient** ; il ne sert pas à
dimensionner.

**ET POURQUOI CE CHAMP DOIT PASSER PAR LA ROUTE**, ce qui n'était pas évident :
`docker exec rag-agent-api python -c "torch.cuda.max_memory_reserved()"` rend
**0,0 Mio** pendant que `nvidia-smi` attribue **1 984 MiB** au conteneur
(`mesuré` à 09:29 UTC) — `docker exec` démarre un **autre** processus, avec un
contexte CUDA neuf. *De l'extérieur, ce chiffre n'est lisible d'aucune autre
façon.*

#### LE CHIFFRE DE RÉSERVATION RENDU AU VOISIN DE CARTE

`calculé` le 14 septembre 2026 à 09:33 UTC **à partir des paliers du banc du
pilote** — `mesuré` par lui sur `/sources` et **CITÉS ici, non rejoués** : la
carte n'avait que **2 183 MiB libres** (vLLM 14 264, Ollama 4 584, agent 1 984),
et rejouer un palier à 16 concurrentes l'aurait fait tomber. *La réserve est
écrite plutôt que tue.*

    paliers mesurés :   1 -> 1 362 Mio    2 -> 1 370    4 -> 1 506
                        8 -> 1 570       16 -> 1 984

    pente marginale max entre paliers adjacents : 68,0 Mio/requête (entre 2 et 4)

    réservation(N) = 1 362 + (N - 1) x 68,0

Cette forme **majore chacun des cinq paliers mesurés** (1 362 / 1 430 / 1 566 /
1 838 / 2 382 contre 1 362 / 1 370 / 1 506 / 1 570 / 1 984), ce qui est la
propriété qu'on lui demande.

> ### **À la borne par défaut N = 4 : 1 566 Mio. Réservation recommandée : 2 048 Mio (2,00 Gio), soit 8,89 % de la L4.**
>
> La marge est de **482 Mio (+30,8 %)** sur le calcul, et elle couvre les 226 MiB
> de contexte CUDA mesurés ci-dessus plus la non-linéarité du cliquet.

**QUATRE RÉSERVES, ET ELLES CONDITIONNENT LE CHIFFRE :**

1. **il ne vaut qu'une fois la borne EN SERVICE et l'agent REDÉMARRÉ.** Le
   processus de production tourne encore sans borne et son cliquet est déjà à
   **1 984 MiB** : il ne redescendra pas, l'allocateur de torch ne rendant rien ;
2. **les paliers ont été mesurés sans trafic LLM concurrent sur la carte** ;
3. **la réservation doit rester INCONDITIONNELLE** — §4.50 : l'empreinte de cet
   agent est paresseuse, et un dimensionnement pris pendant qu'il est au repos
   verrait de la place qui n'est pas libre ;
4. **les cinq paliers sont tous en régime CHAUD**, et c'est la réserve que
   REPAR-13 a ajoutée le 14 septembre 2026 — voir la re-dérivation ci-dessous.
   La forme ne contient PAS un éventuel surcoût transitoire de désérialisation
   pendant la construction d'un modèle : il n'est **pas mesuré**, faute d'une
   carte où le mesurer, et il est le seul terme du démarrage à froid qui reste
   hors de la borne.

#### LA RE-DÉRIVATION DU 14 SEPTEMBRE 2026 — ce chiffre ne majorait pas la scène du démarrage à froid

**LE DÉFAUT, `mesuré` par l'audit du lot 12 puis par le garde de REPAR-13.** Les
cinq paliers ci-dessus ont tous été relevés sur un processus **dont les deux
modèles étaient déjà chargés**. Ils décrivent donc le régime chaud, et le pic de
la carte n'est pas pris là : il est pris au **chargement**. Or le chargement
était, au lot 12, hors de la borne ET non sérialisé — `lru_cache` ne sérialise
pas les manques concurrents. `mesuré` sur le module réel : **8 constructions
simultanées pour 8 fils à froid**, chacune plaçant sa copie des poids.

Ordre de grandeur, `calculé` et **NON mesuré** — la carte n'a pas la place, et
la faire tomber ferait tomber le voisin : l'embedder seul vaut **708 Mio** au
palier `/search` de §4.50 (`nvidia-smi`, contexte CUDA compris), soit **≈ 482
Mio** de poids torch une fois retranchés les **226 MiB** de contexte. À `K`
chargements simultanés le pic vaudrait ≈ `K × 482` Mio hors contexte ; `K`
n'étant borné que par les **40** fils d'AnyIO, cela va jusqu'à ≈ **19 Go** —
contre 2 048 Mio annoncés et 2 892 MiB libres sur la carte au relevé de
09:08 UTC. **Le chiffre ne majorait pas la scène qu'il devait couvrir**, qui est
exactement celle du redémarrage de l'agent : *la seule où il doit valoir.*

**CE QUE REPAR-13 A CHANGÉ, ET POURQUOI LE CHIFFRE TIENT MAINTENANT.** Deux
gestes, tous deux gardés par une mutation qui rougit
(`tests/unit/test_peripherique_torch.py`) :

- le nombre de constructions simultanées d'un modèle est **1**, et il ne dépend
  plus de l'ordonnanceur — `mesuré` : pic **1** et **une seule** construction
  pour 8 fils à froid, contre 8 et 8 avant ;
- cette construction **tient un permis de la borne**, comme les calculs. À tout
  instant, chargement compris, le nombre de présences dans un étage torch est
  donc **≤ `TORCH_MAX_CONCURRENCY`** — ce que la forme suppose, et qui n'était
  vrai qu'en régime chaud.

**LE CHIFFRE NE BOUGE PAS : 2 048 Mio à N = 4.** Je n'ai aucune mesure qui
justifierait de le changer, et en inventer une serait refaire la faute. Ce qui
change est la **condition** : elle est désormais *vraie* au lieu d'être
seulement écrite, et la réserve n° 4 nomme ce qui reste non mesuré. *Ce chiffre
est parti faux deux fois vers cette équipe, les deux fois pour avoir publié une
scène comme une propriété ; la troisième fois, ce qu'on publie est la propriété,
et ce qui reste une scène est dit comme tel.*

#### Ce que le lot a trouvé CONTRE LUI-MÊME

- **huit tests verts qui mesuraient une voisine.** Le câblage du périphérique dans
  `status` a fait rougir **8 tests** de `test_health_parallele.py`,
  `test_garde_modele_embedding.py` et `test_securite.py` : ils assertaient
  `status == "ok"` **sans rien dire du périphérique**, et le défaut `cuda` dans un
  venv torch CPU décrit un service qui ne peut pas chercher. Ils mesuraient donc
  leur propriété sur un service qu'ils *croyaient* sain. Le périphérique y est
  désormais **épinglé**, avec le motif au site. *Le `rc` était juste, la scène
  fausse* ;

  > **CORRECTION DU COMPTE — REPAR-13, `mesuré` le 14 septembre 2026.** « Huit
  > tests » était le nombre de tests que le câblage avait fait *rougir* ; le lot
  > a ensuite posé la ligne d'épinglage à **14 sites**, et NB-2 de l'audit a
  > montré que **la moitié n'épingle rien**. Le compte remesuré, sa recette
  > étant sa preuve :
  >
  > **SITE CANONIQUE DE CE COMPTE.** Il n'est publié nulle part ailleurs : le
  > §4.52 le citait une seconde fois plus bas, et les deux versions ne
  > s'accordaient pas. **Recomptés le 14 septembre 2026 par REPAR-14**, ligne par
  > ligne, `rc` relevé de `pytest` via `PIPESTATUS[0]`, restauration vérifiée par
  > SHA-256 et `git status --porcelain` vide après chacune des quinze.
  >
  > ```bash
  > # 1. LES SITES. Par MOTIF et jamais par numéro de ligne : un numéro se périme
  > #    dès qu'un commentaire s'ajoute au-dessus — REPAR-14 s'y est fait prendre.
  > grep -n 'setattr(main.settings, "torch_device", "cpu")' \
  >   tests/unit/test_securite.py tests/unit/test_health_parallele.py \
  >   tests/unit/test_garde_modele_embedding.py | wc -l          # -> 15
  >
  > # 2. LES TESTS. Les quinze neutralisées d'un coup, sur les trois fichiers.
  > sed -i '/setattr(main.settings, "torch_device", "cpu")/s/.*/    pass/' <les 3>
  > pytest <les 3> -q -p no:randomly ; echo "rc(pytest)=${PIPESTATUS[0]}"
  > #   -> rc=1, 8 failed, 50 passed  (58 tests)
  >
  > # 3. LES LIGNES. Une seule neutralisée à la fois, restaurée, quinze fois.
  > #    Le banc REFUSE de mesurer si la ligne visée ne porte pas le motif.
  > #   -> 6 rendent rc=1, 9 laissent rc=0
  > ```
  >
  > **15 lignes** du motif (14 du lot 12, plus une posée par le garde de B-3)
  > dans **3** fichiers, dont **2** dans des aides partagées — `_brancher()` de
  > `test_health_parallele.py` et celle de `test_garde_modele_embedding.py` — et
  > **13** dans des tests.
  >
  > | unité | mesuré |
  > |---|---:|
  > | lignes du motif | **15** |
  > | lignes qui **MORDENT** (retrait → `rc(pytest)=1`) | **6** |
  > | lignes **INERTES** (retrait → `rc(pytest)=0`) | **9** |
  > | **tests** rouges quand les 15 partent d'un coup | **8** sur **58** |
  >
  > **LIGNES ET TESTS NE S'ADDITIONNENT PAS, et c'est ce que la ligne d'avant
  > confondait** : elle écrivait « 8 qui mordent, 8 inertes » pour 15 sites —
  > 16. Six lignes mordent, et elles font rougir huit tests parce que l'une
  > d'elles est une **aide** : neutraliser celle de
  > `test_garde_modele_embedding.py` fait rougir **3** tests à elle seule, les
  > cinq autres **1** chacune (3 + 5 = 8). *Le commentaire posé dans le code,
  > lui, était juste — il comptait des tests et le disait.*
  >
  > Les 9 lignes inertes sont conservées : elles protégeront le jour où ces
  > scènes liront `/health`. **Aucune ne porte plus de motif gardien** — il en
  > restait un sur `_brancher`, retiré le 14 septembre 2026 (NB-D). **Mesuré à
  > la même date : 5 motifs gardiens subsistent, tous sur une ligne qui mord.**
  > *Un épinglage qui passe aussi sous le défaut n'épingle rien, et un
  > commentaire qui dit le contraire est exactement la forme que ce registre
  > poursuit — une phrase qui ne rougit pas.*
- **le chiffre de mémoire du §4.48 était périmé** (1 266 → 1 294), et la carte
  n'est plus partagée avec le seul Ollama ;
- **DEUX de ses propres gardes étaient CREUX, et sa table de mutations les a
  attrapés.** `M9` — un sémaphore illimité dans la construction paresseuse —
  laissait le test de la borne **VERT**, parce que ce test appelait
  `rearmer_la_borne_des_etages_torch()`, *qui n'est pas le chemin du service* :
  en production le sémaphore naît dans `_semaphore()`, à la première requête. Le
  test remet désormais le module à l'état où il l'y construira. `M10` — le
  cliquet publiant `0.0` au repos — restait **VERT** parce que, dans le venv
  torch CPU du §2.2, `torch.cuda.is_available()` est faux et rendait `None` par
  l'autre condition ; le test feint donc une carte. *Dixième et onzième
  occurrences de la forme dominante, trouvées par le lot contre lui-même* ;
- **une mutation VERTE assumée et écrite** : `M4`, qui sert le repli avant le
  verdict dans la route, ne fait rougir aucun test. Elle est inoffensive tant que
  `_peripherique_inconnu()` ne calcule pas de motif — ce que `M4b` éprouve et qui
  rougit. La propriété est donc gardée sur le CONTENU du repli, l'ordre dans la
  route n'étant qu'une défense en profondeur. *Écrit plutôt que tu.*

#### Ce que le lot n'a PAS fermé, et pourquoi

- **`--compare` épinglé sur le 8 septembre** dans le `Makefile` : au plan du
  pilote, non touché. La fermeture (2) **ne le rend pas absurde** — elle le rend
  plus lisible : `make eval` annoncera désormais « antécédent MUET » tant que la
  référence n'aura pas été rejouée avec cette version du script. *Le geste qui
  referme cela est de rejouer une référence, et il coûte une campagne* ;
- **`.github/workflows/ci.yml`** porte encore « tout tourne en CPU » : le jeton
  n'a pas le scope `workflow` ;
- **`src/agent/llm.py`** : non touché, la bascule vLLM est au banc go/no-go d'en
  face ;
- **le healthcheck du compose**, ci-dessus.

---

### 4.52 → REPAR-13 : la borne borne enfin le CHARGEMENT, `/health` cesse d'accuser trois stores sains, et le troisième site des chiffres est réparé

**Objet** : les trois bloquantes et les trois non bloquantes de
[`audits/2026-09-14-audit-lot-12.md`](audits/2026-09-14-audit-lot-12.md).
`mesuré` le 14 septembre 2026 entre 12:03 et 12:39 UTC (`date -u` relevé avant
la première commande et avant l'écriture). Environnement monté par le §2.2,
torch **2.14.0+cpu**, `torch.cuda.is_available()` **faux**. **Aucune campagne
rejouée, aucun démon touché, la carte n'a pas été approchée.**

**Porte, sur le résultat de la fusion de `main` dans la branche du lot** —
`main` avait avancé d'un commit de documentation et n'était plus ancêtre :
`rc(make lint) = 0`, `rc(make test) = 0`, **798 passés** sur **45** fichiers
(793 au départ ; les 5 de plus sont les gardes ci-dessous).

#### B-1 — le chargement était hors de la borne, et `lru_cache` ne sérialisait rien

**Le défaut avait DEUX moitiés, et aucune ne se fermait seule.** `lru_cache` ne
sérialise pas les manques concurrents : en CPython son verrou n'est tenu que
pour la mise à jour du dictionnaire, jamais pendant l'exécution de la fonction
enveloppée. **8 constructions simultanées pour 8 fils à froid**, `mesuré` — le
chiffre de l'audit, reproduit par le garde. Et les deux constructeurs étaient
appelés **avant** le `with borne_des_etages_torch()`.

- `_SingletonVerrouille` remplace `lru_cache(maxsize=1)` sur les deux modèles
  torch, avec **double vérification sous verrou**. *Sérialiser sans dédupliquer
  n'aurait rien fermé* : `K` copies construites l'une après l'autre allouent
  toujours `K` fois, l'allocateur de torch ne rendant rien. `cache_clear()` et
  `cache_info().currsize` sont tenus à l'identique — le module et les tests les
  lisent ;
- les deux constructeurs passent **sous la borne**. L'ordre des deux verrous est
  total (borne, puis verrou de chargement) aux deux sites : aucune inversion
  possible. *Ce que ce placement coûte est écrit au site* — le premier
  chargement tient un permis pendant qu'il télécharge.

**Table de mutations**, `pytest` sur `test_peripherique_torch.py`, restauration
vérifiée par SHA-256 et `git status --porcelain` vide après chaque :

| mutation | attendu | `rc(pytest)` | mesuré | garde qui rougit |
|---|---|:--:|---|---|
| **M-A** — constructeur d'embedding hors du `with` | rouge | 1 | 1 failed, 32 passed | `…_chargement_des_deux_modeles_se_fait_sous_la_borne` |
| **M-A'** — idem sur le reranker | rouge | 1 | 1 failed, 32 passed | le même |
| **M-B** — seconde lecture sous verrou retirée | rouge | 1 | 1 failed, 32 passed | `…_manque_de_cache_concurrent…` (**8 modèles** construits, pic 1) |
| **M-C** — verrou de chargement neutralisé | rouge | 1 | 1 failed, 32 passed | le même (**pic 8**) |
| **témoin inerte** — `cache_info` réécrite sans changer sa valeur | VERT | 0 | 33 passed | — |

*M-B est celle qui compte* : elle sépare « sérialisé » de « dédupliqué », et
elle rougit sur `total = 8` avec un pic de 1.

#### B-3 — la borne affamait les sondes de `/health`, et deux commentaires affirmaient le contraire

`_sonder` passait par `to_thread.run_sync` **sans limiteur**, donc dans le
réservoir par défaut d'AnyIO — **40 jetons**, `mesuré` — celui-là même où
Starlette exécute `/search` et `/sources`, qui sont des `def`. Et
`borne_des_etages_torch()` bloque **dans** le fil sans le rendre.

Reproduit sur `health()` avec les quatre dépendances **saines et
instantanées** : `{chromadb: false, nebulagraph: false, index_lexical: false}`
rendu en **3,004 s** — `_PLAFOND_SONDES_S` pile. C'est la mesure de l'audit
(13/197 à 3,00 s), en version déterministe.

**Le geste** : `_reservoir_des_sondes()`, un `CapacityLimiter` de **8** jetons
porté par un `RunVar`. 8 et non 40 parce que `_sondes_en_vol` borne déjà à un
fil par nom de sonde et que les noms sont cinq ; un `RunVar` parce qu'un
limiteur appartient à sa boucle.

**LES DEUX PHRASES FAUSSES SONT TRAITÉES, PAS LAISSÉES DEBOUT.** Le motif du
sémaphore affirmait « et laisse la sonde de santé répondre » ; le docstring de
`borne_des_etages_torch` affirmait « `/health` continue de répondre pendant que
les requêtes s'attendent ». Elles sont désormais **vraies** — mais par le
limiteur dédié, pas par le sémaphore — et chacune renvoie au garde qui rougit si
ce limiteur disparaît. *Une phrase ne rougit pas ; ces deux tests-là, si.*

| mutation | attendu | `rc(pytest)` | mesuré |
|---|---|:--:|---|
| **M-D** — `limiter=` retiré (l'état du lot 12) | rouge | 1 | 2 failed, 10 passed |
| **M-E** — limiteur présent mais = celui par défaut | rouge | 1 | 2 failed, 10 passed |
| **témoin inerte** — variable locale renommée | VERT | 0 | 12 passed |

*M-E est celle qui compte* : elle prouve que le garde éprouve la **distinction**
des réservoirs, et pas la simple présence d'un argument.

#### B-2 — l'inventaire des sites, et le troisième réparé

**L'inventaire a été établi par commande, et il est rendu en entier dans le
rapport de REPAR-13.** La commande :

```bash
git grep -n -E "runs/[0-9]{4}-[0-9]{2}-[0-9]{2}-[a-z-]+\.json" -- ':!runs/' ':!documentation/audits/'
```

Elle rend **42 lignes dans 11 fichiers**, regroupées en **22 sites** ; puis,
pour chaque site, un attributeur compte combien des nombres portés appartiennent
au `resume` de chaque campagne versionnée. **Un seul site fautif** —
`gpu_cuda.md` §7.2, dont les **6 métriques sur 6** du tableau viennent de
`08-reference` quand le titre nomme `10-lecteur-neuf` (l'attributeur y voyait
8 valeurs contre 1, en comptant aussi la prose de la section) — et **un titre
trompeur** que l'audit n'avait pas relevé : `axes_amelioration.md` §4.48
annonçait `lecteur-neuf` là où sa propre note, quinze lignes plus bas, nommait
`reference-08`. Les deux sont corrigés ; **tous les autres sites sont exacts**,
et le rapport de REPAR-13 les liste un par un, y compris ceux trouvés corrects.

Le §7.2 porte désormais les **deux** colonnes CPU nommées et les deux lectures,
**recalculées depuis `runs/`** : −817 ms (−11,19 %) / +40 ms / **20,4 pour 1**
contre `reference-08` ; −365 ms (−5,33 %) / +106 ms / **3,4 pour 1** contre
`lecteur-neuf`. Le « vingt contre un » sans base est remplacé. Et le
« 1 262 MiB pour l'agent », publié comme une **résidence**, est remplacé par les
trois paliers du §4.50 — 0 au repos, 708 après `/search`, 1 294 après `/answer`
— et nommé pour ce qu'il est : un **cliquet**.

#### La re-dérivation du chiffre rendu au voisin

Elle est au **§4.51**, où le chiffre vit. En une phrase : les cinq paliers sont
en régime **chaud**, le chargement n'était borné par rien, donc **2 048 Mio ne
majorait pas le démarrage à froid** — la seule scène où ce chiffre doit valoir.
B-1 rend la forme applicable ; le chiffre **ne bouge pas**, faute de mesure qui
le justifierait, mais sa condition est devenue vraie et une **quatrième réserve**
nomme ce qui reste non mesuré. Il voyage désormais avec sa base, sa réserve
conditionnante et sa date à ses **quatre** sites, celui du pipeline compris.

#### Les trois non bloquantes

- **NB-1** — `peripherique_torch` rejoint `services_unknown` quand sa sonde
  n'est pas revenue, et le geste rendu au pipeline le **lit** : trois cas
  distincts là où il imprimait `ok None` sur deux scènes opposées. Gardé dans
  les deux directions (M-G : retirer → rouge ; M-H : déclarer toujours → rouge
  sur le témoin) ;
- **NB-2** — M-B remesurée, le motif qui déclarait gardiennes des lignes inertes
  a été retiré, les lignes restent. **Le compte et sa recette sont plus haut dans
  ce même §4.52, et c'est leur seul site** : la version qui figurait ici ne
  s'accordait pas avec lui, et c'est ce que l'audit a relevé (NB-E) ;
- **NB-3** — couvert par la re-dérivation ci-dessus ; aucune autre copie du
  chiffre ne subsiste (`git grep` cité au rapport).

#### Ce que REPAR-13 a trouvé CONTRE LUI-MÊME

- **son premier banc de B-3 rougissait pour la mauvaise raison.** Il attendait
  les fils par un `Semaphore.acquire()` **synchrone**, qui bloquait la boucle
  d'événements : les tâches `start_soon` ne démarraient jamais et le réservoir
  n'était **jamais saturé**. Les deux gardes étaient rouges — sur le banc, pas
  sur le défaut. *Un rouge dont on n'a pas vérifié la raison ne vaut pas mieux
  qu'un vert* ;
- **une correction perdue par une mutation non commitée.** `git checkout --`
  après M-B a restauré `test_garde_modele_embedding.py` à `HEAD`, effaçant une
  correction non encore commitée. **C'est le contrôle par SHA-256 qui l'a
  attrapé** — l'empreinte prise après la correction ne correspondait plus. La
  règle « commite AVANT de muter » n'est pas une formalité ;
- **un garde du dépôt a refusé ma mise en forme, et il avait raison.**
  `TestLaNoteDuCompteEstLueAuBonEndroit` exige la note du compte sur **une seule
  ligne** pour ne pas lire un récit ; je l'avais coupée en deux.

#### Ce que REPAR-13 n'a PAS pu mesurer, et le dit comme tel

1. **aucun Mio réel sur la carte.** Poste partagé, vLLM y tient ~14 Go, consigne
   de ne rien démarrer ni arrêter. Tous les chiffres mémoire au-delà du **nombre
   de constructions simultanées** (`mesuré`) restent `calculé` depuis les
   paliers publiés. *Le geste qui les rendrait `mesuré`* : sur un jumeau
   `--gpus all`, N requêtes concurrentes **à froid**, `max_memory_reserved()`
   relevé à `/health` ;
2. **le surcoût transitoire de désérialisation d'un modèle n'est pas mesuré.**
   C'est le seul terme du démarrage à froid qui reste hors de la borne, et c'est
   la quatrième réserve du §4.51 ;
3. **B-3 est mesurée sur l'application réelle mais avec des sondes inertes**, et
   le réservoir est saturé par des fils qui attendent un `Event`, non par la
   borne torch elle-même. La propriété — les deux réservoirs sont distincts —
   ne dépend pas de ce que fait torch ; l'ampleur en grandeur réelle, si ;
4. **`make test-integration`, `make eval`, `make eval-controle` et
   `make verifier-les-ancrages` n'ont pas été lancés** : ils exigent la pile
   démarrée et aucune réingestion n'était permise. La porte est bien
   `make lint && make test` ; il n'y a pas de cible `make all`.

#### Ce que REPAR-13 n'a PAS fermé, et pourquoi

- **R-1 et R-2 de l'audit** — deux réserves, hors mandat de cette réparation ;
- **le healthcheck `curl -sf` vert sur `degraded`** — délibéré, §1.27 ;
- **`--compare` épinglé sur la référence du 8 septembre** — coûte une campagne,
  c'est au pilote ;
- **`.github/workflows/ci.yml`** — le jeton n'a pas le scope `workflow` ;
- **`src/agent/llm.py` et la bascule vLLM** — c'est un chantier, pas un lot.


---

### 4.53 → REPAR-14 : les six phrases qui ne rougissaient pas, et la dépendance dont tout dépendait sans être déclarée

**Livré le 14 septembre 2026.** Ferme les **six non bloquantes** et les **deux
réserves** de [l'audit de REPAR-13](audits/2026-09-14-audit-repar-13.md). Cet
audit n'avait trouvé **aucune bloquante** et **aucune régression** : les trois
bloquantes du lot 12 étaient réellement fermées, établies par mutation.

**CE LOT NE CHANGE AUCUN COMPORTEMENT, et c'est sa contrainte de fond.** Tout ce
qu'il touche est du commentaire, de la docstring, de la documentation, du
registre — plus **une déclaration de dépendance**. Un changement de comportement
rouvrirait un audit indépendant, et ce lot existe pour ne pas en rouvrir un. Le
diff de `src/` est intégralement en commentaires et docstrings, à une chaîne
près — celle que `/health` publie, dont c'est précisément le **contenu** qui
était faux.

**Porte, mesurée sur le RÉSULTAT DE LA FUSION de `main`** dans la branche du lot
(`main` avait avancé du rapport d'audit et n'en était plus ancêtre ;
`git merge --no-ff`, aucun rebase) : `make lint` et `make test` en **`rc=0`**,
**798 passés** sur **45** fichiers — le compte ne bouge pas, aucun test n'ayant
été ajouté ni retiré.

#### Les six non bloquantes

- **NB-A — « une seule construction à la fois » devient « par modèle », et la
  borne voyage avec.** La phrase était vraie à `TORCH_MAX_CONCURRENCY=4` et
  fausse dès 5. Remesurée le 14 septembre 2026, doubles inertes, 4 `/search` +
  4 `/sources` à froid, pic **tous modèles confondus** : bornes **1 / 4 / 5 / 8**
  → pic **1 / 1 / 2 / 2**, et **2 constructions au total** aux quatre. La
  colonne de droite est la propriété — une par modèle, jamais deux du même ; la
  gauche est une scène. *Contrôle positif de la sonde* : la même, sans le
  singleton, voit **4, 5 et 8** — elle sait donc compter au-delà de 1. Corrigée
  aux **deux** sites qui la publient, dont celui rendu au pipeline, qui porte
  désormais le majorant qu'aucun réglage ne franchit (**2**) et dit que la borne
  dont il dépend est un réglage qu'un exploitant peut desserrer sans prévenir ;
- **NB-B — « trois autres requêtes passent quand même » : mesuré ZÉRO.** 8
  requêtes à froid, borne 4, chargement de 3,0 s → **0** progresse ; *contrôle
  positif*, modèle déjà chaud → **8 sur 8**. Ce qui se passe réellement est
  écrit au site : **le chargement d'un étage gèle l'autre** — `/sources`,
  cross-encoder déjà chaud, passe de **0,0 s** (borne désarmée, contrôle) à
  **2,9 s** (borne 4, quatre `/search` à froid) ;
- **NB-C — sous une levée, les échecs sont sérialisés**, et ce n'était dit nulle
  part. Chargement qui lève après 0,5 s, 8 requêtes, borne 4 → **4,0 s**, soit
  0,5 × 8. La propriété utile est intacte et mesurée : `currsize` = **0** après
  levée, donc chaque appel retente ;
- **NB-D — NB-2 refermée à son dernier site.** `_brancher`, aide partagée par
  quatre tests, portait encore le motif gardien sur une ligne **mesurée
  inerte**. La ligne reste — elle protégera le jour où ces scènes liront
  `/health` —, la phrase fausse part. **Mesuré après correction : 5 motifs
  gardiens subsistent, tous sur une ligne qui mord** ;
- **NB-E — le §4.52 se contredisait, il est recompté.** Il additionnait des
  **sites** et des **tests** dans la même phrase, et la somme ne tombait pas :
  « 8 qui mordent, 8 inertes » pour **15** sites. Recompté ligne par ligne,
  `rc` relevé de `pytest`, restauration vérifiée par SHA-256 aux quinze. **Le
  compte corrigé et sa recette ne sont PAS recopiés ici** — ils ont désormais un
  seul site, le §4.52, et ce lot-ci n'existerait pas si un chiffre à deux sites
  était sans conséquence ;
- **NB-F — `/health` ne publie plus le nom d'un mécanisme retiré.** Le message
  disait « le `lru_cache` ne se peuple pas sur une levée », or REPAR-13 a retiré
  `lru_cache` de ces deux modèles. **Le NOM DU CHAMP n'a pas bougé, et c'était la
  décision** : `torch_device.hors_d_atteinte` est lu **de l'extérieur** — le
  geste publié à `pour_le_pipeline_ingestion.md:147` le lit par son nom. Établi
  avant de décider : **aucun lecteur n'attrape le CONTENU** de la chaîne (le seul
  test qui le lit asserte `"out of memory"`, la part interpolée). C'est donc ce
  que la chaîne **dit** qui est corrigé. Trois commentaires internes périmés le
  sont aussi.

#### Les deux réserves

- **R-1 — `anyio` est déclarée, et le plancher porte sa mesure.** `src/api/main.py`
  importe `CapacityLimiter`, `to_thread` et `anyio.lowlevel.RunVar` **en
  direct**, et toute la fermeture de B-3 repose sur une propriété de son
  implémentation — un limiteur distinct fait **naître** des fils au lieu d'en
  emprunter à un pool global borné. La dépendance n'était déclarée **ni** dans
  `requirements.txt`, **ni** dans `requirements-dev.txt`, **ni** dans
  `pyproject.toml` ; `uv.lock` disait **4.14.2**, l'environnement du §2.2
  installait **4.15.1**, et la CI n'utilise pas le lock.

  **Le plancher est MESURÉ, et non lu dans des notes de version** — c'était
  l'exigence, un plancher qu'aucune mesure ne soutient ne valant pas mieux que
  l'absence. **20 versions** jouées une par une dans des venvs jetables hors du
  projet, banc à **deux directions** (40 tâches saturent le réservoir par défaut,
  puis 5 sondes partent) :

  | sens | sondes revenues | attente | fils créés |
  |---|---:|---:|---:|
  | **avec** `limiter=` dédié | **5 / 5** | **0,00 s** | **+5** |
  | **sans** — contrôle négatif | 0 / 5 | 3,00 s | +0 |

  La **propriété** tient de **3.6.2 à 4.15.1**, les 20. Ce qui fixe le plancher
  est l'**API** : l'appel exact de `main.py` rend `TypeError: run_sync() got an
  unexpected keyword argument 'abandon_on_cancel'` en **4.0.0** et en dessous, et
  passe à partir de **4.1.0**. Déclaré **`anyio>=4.1.0,<5`** — les **17**
  versions de cet intervalle passent les deux contrôles. *Pas d'épinglage `==`*,
  contrairement au reste du fichier : aucune mesure ne soutiendrait une version
  plutôt que les dix-sept, et figer un transitif de `fastapi`/`starlette`
  rendrait la résolution cassante sans rien garder de plus. La borne haute `<5`
  est celle que `starlette` impose déjà, et elle marque **où s'arrête la
  mesure** ;
- **R-2 — le chemin hors borne est écrit à son site, borné.** Il n'est pas
  changé : `_peripherique_si_charge` est le **seul** appelant du singleton qui ne
  soit pas sous la borne, parce qu'il sert `/health`, qui ne doit jamais attendre
  un permis. Sa docstring dit désormais que la fenêtre **existe** (`currsize > 0`
  lu, `cache_clear()` concurrent, puis un chargement hors borne), **ce qui la
  rend inatteignable** — `cache_clear()` n'a aucun appelant en production,
  `mesuré`, les **24** sites vivant tous dans `tests/` — et **ce qui la rendrait
  atteignable** : un rechargement à chaud, une bascule de périphérique en
  service, une purge sur signal.

#### Ce que REPAR-14 a trouvé CONTRE LUI-MÊME

Trois, et chacun aurait produit une ligne fausse.

1. **Une sonde qui n'atteignait pas son cas, et son vert ne valait rien.** Ma
   première scène du gel lançait **un** `/search` à froid contre une borne de
   **4** : trois permis restaient libres, `/sources` passait, et je mesurais
   **0,0 s** là où l'audit lit 3,2 s. J'ai failli écrire que l'audit se trompait.
   Il faut **quatre** `/search` pour épuiser la borne — c'est le mécanisme que
   l'audit décrit lui-même. Refaite : **2,9 s**, et le contrôle borne désarmée
   rend **0,0 s** ;
2. **Des numéros de ligne périmés par ma propre correction.** Après avoir ajouté
   treize lignes de commentaire dans `_brancher`, j'ai rejoué le comptage sur les
   numéros d'**avant** : quatre lignes mordantes sont ressorties `rc=0` — je
   neutralisais des lignes quelconques. Le banc **vérifie désormais que la ligne
   visée porte le motif** et refuse de mesurer sinon ; le contrôle du contrôle
   (lui donner un numéro périmé) rend bien « AUCUN RESULTAT ». *Un site se relève
   par motif, jamais par numéro* — c'est aussi pourquoi la recette du §4.52 est
   écrite ainsi ;
3. **Une recette qui s'attrapait elle-même.** Mon `grep` d'appelants de
   `cache_clear()` en production rendait **un** site : sa propre citation dans la
   docstring que j'écrivais. Motif resserré sur la parenthèse ouvrante → **zéro**
   en production, et le **contrôle positif** sur `tests/` en trouve **24**. Sans
   ce contrôle, un « zéro » n'aurait rien prouvé.

Un quatrième, sans conséquence sur une mesure : mon premier `python` de mutation
a échoué en `command not found` (`PATH` sans `.venv`), et les deux commandes
suivantes ont rejoué le banc **non muté**. Attrapé par l'empreinte SHA-256 du
fichier, inchangée — pas par le résultat, qui était plausible.

#### Ce que REPAR-14 n'a PAS pu mesurer, et le dit comme tel

1. **Aucun Mio réel sur la carte, et aucun palier rejoué.** Poste partagé, vLLM y
   tient ~14 Go, consigne de ne rien démarrer ni arrêter. Le **nombre** de
   désérialisations simultanées est `mesuré` ; ce que **chacune coûte** en
   mémoire reste non mesuré, et c'est la quatrième réserve du §4.51 — qui n'était
   écrite qu'au **singulier**, et que ce lot corrige à **2** ;
2. **Les durées sont celles de doubles inertes**, pas des vrais poids : le modèle
   d'embedding n'est pas au cache local du poste. La **propriété** (le nombre de
   constructions) n'en dépend pas ; les **durées** si — 3,0 s et 0,5 s sont des
   `sleep`, choisis pour reproduire les scènes de l'audit ;
3. **La mesure d'AnyIO porte sur le mécanisme, pas sur l'application réelle.** Le
   réservoir y est saturé par des fils qui attendent un `Event`, non par la borne
   torch. C'est la même borne que l'audit déclarait sur sa propre scène en
   grandeur réelle, restée **aveugle** ;
4. **Rien ne garde les phrases corrigées.** Ce sont des commentaires et de la
   documentation : aucune mutation ne les fait rougir, par construction. Ce qui
   est gardé est ce qu'elles décrivent. *Le geste qui fermerait ce reste* : un
   test qui mesure la latence de `/sources` pendant un chargement, et un autre
   qui asserte le pic tous modèles confondus à une borne ≥ 5 — deux **ajouts de
   test**, donc hors du mandat « aucun changement de comportement » de ce lot.

#### Ce que REPAR-14 n'a PAS fermé, et pourquoi

- **le healthcheck `curl -sf` vert sur `degraded`** — délibéré, §1.27 ;
- **`--compare` épinglé sur la référence du 8 septembre** — coûte une campagne ;
- **`.github/workflows/ci.yml`** — le jeton n'a pas le scope `workflow`. *La CI
  installe donc toujours depuis les `requirements` et non depuis `uv.lock` ; la
  déclaration d'`anyio` ci-dessus est ce qui rend cette installation sûre sans y
  toucher* ;
- **`src/agent/llm.py` et la bascule vLLM** — c'est un chantier, pas un lot.

### 4.54 → LOT-19 : le second rideau, son site unique, et ce que l'audit y laisse ouvert

**Livré le 15 septembre 2026, FUSIONNÉ le 16** — `9b5c331`. Lot **3** du
découpage du chantier vLLM (§8) : **pas une bascule**, un défaut d'aujourd'hui,
en production.

**Ce que le lot ferme.** Le motif de `graph.py` exigeait une parenthèse
**immédiatement** suivie d'un guillemet — la seule forme positionnelle — et les
deux moteurs du poste écrivent aussi la forme **nommée**. Deux effets, pas un, et
ils tombent séparément : la recherche supplémentaire ne partait jamais, **et** la
syntaxe d'appel partait telle quelle à l'écran. La reconnaissance et le nettoyage
étaient **deux expressions régulières recopiées à quinze lignes l'une de
l'autre**, libres de diverger. `src/agent/repli_outil.py` en fait un **site
canonique unique** : `lire_et_retirer` rend la sous-question **et** le texte
nettoyé d'un seul passage sur un seul motif — la divergence n'est plus
représentable. Le nettoyage a désormais lieu **quel que soit le canal**.

**Porte, mesurée par le pilote SUR LE RÉSULTAT DE LA FUSION** (`main` avait
avancé du rapport d'audit et n'en était plus ancêtre ; `git merge --no-ff`, aucun
rebase), arbre détaché neuf monté par le §2.2, le **16 septembre 2026** :
`rc(make lint)=0`, `rc(make test)=0`, **910 passés** sur **47** fichiers — `main`
avant le lot : 892 sur 46. **L'arbre scellé est bit pour bit celui qui a été
mesuré** : `git rev-parse main^{tree}` et `HEAD^{tree}` de l'arbre de porte
rendent tous deux **`ac067c9`**. Ce n'est pas une supposition, c'est un SHA.

#### L'audit indépendant : aucune bloquante, et il le dit franchement

[`audits/2026-09-16-audit-lot-19.md`](audits/2026-09-16-audit-lot-19.md), versé
sur `main` en **`92e28a7`** *avant* d'être cité. **Onze mutations, témoin inerte
à 0, dix rouges.** Deux comptent :

- **MU2** — remettre le motif d'origine — fait rougir **quatre scènes** : c'est
  la **preuve rouge** que le défaut visé est fermé, et non une lecture rassurante
  du diff ;
- **MU3** — rattacher le nettoyage au repli — meurt sur **exactement la scène que
  le lot a ajoutée** : le lot 19 avait trouvé ce trou contre lui-même, il a
  converti son commentaire en garde, et le garde tient.

C'est le **premier audit de ce chantier à ne rien trouver de bloquant deux fois
d'affilée** (AUDIT-18 non plus), et l'auditeur choisit de l'écrire plutôt que
d'inventer une trouvaille. Le compte reste : **dix-sept audits, dix-sept
trouvailles bloquantes**, quasi toutes *un garde vert sous une scène que le
défaut ne rencontre jamais*.

#### Ce qui reste OUVERT, et qui est désormais chiffré

**(a) Une forme d'appel MESURÉE sur le moteur de production n'est pas reconnue.**
`gemma4:e4b`, servi par `ollama-central`, écrit aussi l'appel **sans
guillemets** :

```
search_vectors(Quel est le calcul et le montant légal de l'indemnité de rupture conventionnelle ?)
```

`mesuré` le **16 septembre 2026 vers 01:22 UTC**, interrogation en lecture sur
`ollama-central` — **un appel sur quatre réellement écrits** au cours de onze
interrogations. Les **deux charges** du rideau tombent ensemble.

**Ce n'est pas une régression** : `main` ne la reconnaissait pas davantage, et le
motif du lot est un **sur-ensemble strict** de l'ancien. C'est un bord non
atteint, pas un bord déplacé. Mais **la justification écrite du module est
boiteuse** : elle paie le prix des guillemets par la mention qu'Ollama écrit
— « *avec l'outil `search_vectors`.* » —, or cette mention **ne porte aucune
parenthèse**, donc l'exigence de la parenthèse ouvrante l'exclut déjà seule. Le
prix réel est payé par `signature-citee-sans-guillemets`, que MU8 fait bien
rougir — mais **cette scène-là n'est pas déclarée mesurée, alors que la forme
qu'elle coûte l'est**.

**BORNE, et elle est écrite, pas supposée** : un appel sur quatre, sur **onze**
interrogations, à température 0,1, sur **une seule famille de questions**. C'est
assez pour dire que la forme **existe**, pas pour dire à quel **taux** elle sort
en service.

**(b) Rien ne garde le nettoyage d'une réponse portant DEUX appels.** `MU6` —
`sub(…, count=1)` — **survit aux 910 tests**, et elle n'est pas équivalente : le
mutant **laisse la syntaxe à l'écran** sur un texte à deux appels, soit la charge
n° 2 du rideau. Le comportement servi est le bon ; c'est le **garde** qui manque.
La docstring dit que « le PREMIER appel décide » pour la sous-question — elle ne
dit rien du fait que le nettoyage, lui, les retire **tous**, et c'est ce silence
que MU6 traverse.

**(c) La déclaration de provenance désigne deux fois « le dernier ».**
Conséquence : `mention-puis-citation-entre-guillemets` se retrouve **sans
déclaration** et l'en-tête de la liste la présente alors comme **relevée** — elle
ne l'est pas. Exhaustives en nombre, **inexactes en désignation**, et c'est
précisément la zone dont le lot fait son point d'honneur.

#### Les réserves que le chantier garde

**R1 — le garde du site unique est aveugle à une copie REFORMULÉE.** Il cherche
la chaîne littérale. Cinq copies plantées une à la fois : témoin inerte **vert**,
copie littérale sous un autre nom **rouge**, sous un autre répertoire **rouge** —
mais **trois reformulations** (concaténation, classe de caractères,
`re.escape`) **passent au vert**. Le garde tient donc **l'unicité du site pour la
forme littérale**, ce qui est ce qu'on lui demandait d'abord ; mais le module
affirme que « la divergence n'est plus représentable » et que « une copie ne peut
plus exister pour diverger ». **Sa promesse écrite dépasse ce qu'il rend.** C'est
la leçon du *garde de copie conforme*, retournée : ici l'unicité est bien tenue,
mais **sur un domaine plus étroit que la phrase**.

**R2 — le rideau retire du texte que `main` laissait intact, sur un appel MAL
FORMÉ.** Quand la chaîne n'est pas refermée là où on l'attend, le nettoyage mange
jusqu'au prochain couple guillemet + parenthèse : le lot part alors en recherche
sur une sous-question aberrante **et** efface la phrase. **Aucun moteur n'a écrit
cette forme** — elle est **construite**, donc réserve et non trouvaille. Elle
compte parce qu'elle est du côté le plus coûteux : *un rideau qui efface du texte
utile est plus grave, parce que personne ne le verra.*

**R3 — le résultat du lot est juste, sa FORMULATION ne l'est pas.** Le lot écrit
« une mutation qui retire la seule parenthèse **ouvrante** » et rapporte **0
désaccord sur 34 textes mesurés**. Pris au pied de la lettre — parenthèse
**supprimée** — le mutant désaccorde sur 8 textes sur 18. Pris comme parenthèse
**rendue optionnelle**, il rend **1 seul** désaccord, exactement la scène
construite. L'auditeur a d'abord cru tenir une contradiction : **c'était son
mutant qui était mal choisi**, et il l'a consigné contre lui-même. Sur le fond,
**dix textes mesurés de plus, zéro désaccord** : le bord est là où le lot le
croit.

**R4 — LA BORNE DE VALEUR DU RIDEAU, et elle n'était écrite nulle part.** Le
second rideau **ne se déclenche que sur une désobéissance**. `prompts/system.txt`
est le **même dans les deux modes**, et sa règle 5 dit : « *N'écris jamais cet
appel dans ta réponse : utilise le mécanisme d'outil.* » **En mode repli, ce
mécanisme n'existe pas**, et la consigne interdit le **seul signal que le rideau
sait lire**. Les quatre premières interrogations de l'auditeur avec le prompt de
production n'ont produit **aucun** appel — ce qui reproduit le premier « faux
résultat contre lui-même » que le lot avait déjà consigné. **Ce n'est pas un
défaut du lot 19**, c'est le prix d'entrée du rideau, et il est maintenant au
registre.

**R5 — hors périmètre, croisé en chemin : `/health` publie un moteur MÉMORISÉ.**
À **01:18:37 UTC** le 16 septembre, `/health` rendait `status: ok` avec
`moteur_llm.releve_le = 2026-09-15T21:21:16+00:00` — un relevé vieux de **quatre
heures**, décrivant un `ollama-central` **mort (sorti en 137, 01:08:40) et revenu
(01:08:55)** dans l'intervalle. **La réserve écrite au site par REPAR-18 est
réelle en production** : le champ ne ment pas sur sa date, mais rien n'indique au
lecteur que le serveur décrit n'est plus celui qui tourne. Constaté, non
instruit.

#### Les faux résultats que l'auditeur a trouvés CONTRE LUI-MÊME

Quatre, et deux entrent au corpus des pièges de mesure :

1. **`git status --porcelain && echo "(porcelain vide)"` MENT.** `git status` rend
   `rc=0` **qu'il ait de la sortie ou non** : l'idiome a imprimé « porcelain
   vide » **au-dessus d'un fichier modifié**, en pleine campagne de mutations.
   C'est le **SHA-256** qui a attrapé l'écart, pas lui. *Un contrôle de propreté
   se fait sur la CHAÎNE, jamais sur le `rc`.*
2. **Sa propre borne de tokens lui a fait conclure « le modèle n'écrit pas
   d'appel ».** Deux interrogations à `num_predict=300` se terminaient sur
   « *Afin de répondre à* » — **coupées avant l'appel**. Rejouées à 700, les deux
   l'écrivent, et **c'est l'une d'elles qui porte la trouvaille (a)**. Il a failli
   publier un zéro qui n'était que **sa propre troncature**.
3. Son mutant M2 était mal choisi — R3 ci-dessus.
4. **Son sélecteur `-k` ne prenait qu'un test sur deux** : `"site_unique"` ne
   correspond pas à `test_le_motif_du_second_rideau_n_a_qu_un_site`. Son premier
   « vert de départ » ne mesurait que **la moitié** de ce qu'il croyait.

#### Ce qui n'a PAS pu être mesuré, dit comme tel

- **Les trois formes vLLM du motif** — `query=`, `sous_question=`,
  `<execute_tool>` — restent **crues sur parole** côté audit : aucune requête n'a
  été adressée à `vllm-central`, qui appartient à l'équipe voisine. Elles sont
  mesurées par le lot lui-même, pas confirmées indépendamment.
- **L'agent réellement en service** tourne du code d'avant le lot ; rien n'est
  éprouvable à travers lui sans un redémarrage que le lot n'avait pas mandat de
  faire.

### 4.55 → LOT-20 : le lecteur des deux dialectes, l'appel d'outil accumulé, et les huit gardes qui manquent

**Livré et FUSIONNÉ le 16 septembre 2026** — `551f205`. Lot **4** du découpage du
chantier vLLM (§8), et **le premier à toucher `src/agent/llm.py`**, que dix-neuf
lots avaient laissé intact exprès.

**CE LOT NE BASCULE RIEN.** Ollama reste le moteur servi ; `.env`, `.env.example`,
`docker-compose.yml` et `OLLAMA_HOST` sont **hors du diff**, vérifié. Il rend le
lecteur **capable** de lire les deux dialectes. La bascule est le lot 7.

#### Pourquoi les deux défauts étaient soudés

Notre lecteur cassait **bruyamment** sur le préfixe `data: ` de vLLM
(`json.loads` sur du NDJSON pur). **Derrière ce mur, silencieusement**, vLLM
fragmente l'appel d'outil sur **quatre événements** dont aucun ne porte l'appel
entier. **Séparés, réparer le premier aurait rendu le second INVISIBLE** : le
flux serait passé, les tokens seraient sortis, et l'agent aurait perdu sa
capacité à relancer une recherche sans que rien ne le dise. C'est la famille
dominante de ce chantier, prise à l'avance.

#### Ce que le lot a mesuré et que le banc n'avait pas

- **L'`index` n'est pas à la même place** : au niveau de l'**appel** chez vLLM,
  au niveau de la **fonction** chez Ollama. Une accumulation qui n'aurait lu que
  `call["index"]` aurait fait **se recouvrir** les appels d'Ollama.
- **Les deux moteurs incrémentent l'index sur deux appels**, et **Ollama étale
  alors ses deux appels sur DEUX événements**. Donc **le moteur servi
  aujourd'hui avait lui aussi besoin de l'accumulation** — le banc présentait la
  fragmentation comme un défaut purement vLLM.
- **L'événement d'usage de vLLM porte `"choices": []`**, liste vide, et c'est le
  **seul** qui porte les décomptes : `choices[0]` y lèverait `IndexError`,
  précisément là. Découvert par une sonde faite pour vérifier autre chose.
- Les décomptes n'existent chez vLLM **qu'avec** `stream_options:
  {"include_usage": true}` — vérifié dans les deux sens, pas supposé.

#### La forme du remède

`src/agent/flux_llm.py`, site canonique, **sans aucune branche par moteur** : il
lit la **FORME**, pas un réglage. `_charge` est le seul endroit qui connaisse les
deux dialectes ; en aval, la clé porte le même nom des deux côtés.
`extract_tool_query` **reste le seul juge** — le lecteur lui rend un `message` de
la forme qu'il attend, sa règle n'est réécrite nulle part. **Une chaîne se
concatène, un objet remplace** : `{"query": "` n'est pas du JSON pris seul, et
« fusionner » des dicts inventerait un appel.

`on_tool_call` **sort de la boucle et ne part qu'UNE fois**. Les deux erreurs
symétriques sont écrites au site : juger dans la boucle rend `None` à chaque
tour et **le rappel ne part jamais** ; rappeler à chaque fragment lance **quatre
recherches pour un appel** et `max_search_iterations` avale le plafond en
silence.

**Porte, mesurée par le pilote SUR LE RÉSULTAT DE LA FUSION**, arbre détaché neuf
monté par le §2.2, le **16 septembre 2026** : `rc(make lint)=0`,
`rc(make test)=0`, **937 passés** sur **48** fichiers (`main` avant : 910 sur
47). **L'arbre scellé est bit pour bit celui qui a été mesuré** : `af27f47`.

#### L'audit indépendant : aucune bloquante, et il refuse d'en fabriquer une

[`audits/2026-09-16-audit-lot-20.md`](audits/2026-09-16-audit-lot-20.md), versé
sur `main` en **`76441dc`** *avant* d'être cité. **Vingt-huit mutations, DEUX
témoins inertes à zéro, dix-neuf tuées, NEUF SURVIVANTES**, chacune avec son
texte séparateur **montré dans les deux états**.

**IL ÉPROUVE LE LOT SUR SES PROPRES CAPTURES**, pas sur celles du lot : six
requêtes d'inférence, prompts tous distincts, trois par moteur. Le lecteur lit
ses cinq flux correctement, **là où l'ancienne boucle de `main` lève
`JSONDecodeError` sur les trois captures vLLM**. Le défaut réparé est donc
**reproduit sous une main qui n'a pas écrit le remède**.

**IL RENVERSE DEUX LECTURES DU PILOTE, ET LES DEUX FOIS EN FAVEUR DU LOT :**

- **L'angle 2 est un NON-SUJET, ET IL EST GARDÉ.** Le pilote craignait que le
  `break` sorte avant l'événement d'usage, les décomptes étant alors **présentés
  comme une absence déclarée alors que ce serait une perte**. Ordre mesuré sur
  vLLM : `finish_reason` → usage → `[DONE]`, et `termine` **ne bouge que sur
  `[DONE]`**. La mutation qui pose `termine` sur `finish_reason` **fait
  rougir**. Et si un serveur n'émet jamais `[DONE]`, la boucle se termine
  d'elle-même : **le `break` est une sortie anticipée, pas la condition de
  terminaison.**
- **La ventilation de M11 ne se reproduit pas** : le lot annonçait « 22 rouges
  dont **deux** préexistantes » ; l'auditeur mesure **14 préexistantes**, sur la
  suite entière. Le total se reproduit, la ventilation non — et **la couverture
  Ollama héritée est sept fois plus large que le lot ne le dit**.

#### Ce qui reste OUVERT — huit gardes qui manquent, pas une ligne fausse

**Aucune ligne fausse dans les 1 033 lignes du diff.** Les huit trouvailles sont
de la même nature, et c'est ce qui les rend fusionnables.

**(a) LA PERTE QUE LE PILOTE CHERCHAIT DANS LE `break` EXISTE — AILLEURS.**
`_lire_decomptes` écrit ses deux branches **inconditionnellement**, l'une après
l'autre. Mesuré sur le code servi : `done: true` + `prompt_eval_count: 108`,
`eval_count: 27` rend `(108, 27)` ; **le même événement portant aussi
`"usage": {"total_tokens": 135}` rend `(None, None)`** — 108 et 27 **écrasés**.
Idem avec `"usage": {}`. **Une mesure réelle devient une absence déclarée, et
`mesure_prompt_exploitable` la croira honnête.** Non représentable sur les
moteurs du poste — mesuré : Ollama n'émet pas `usage`, vLLM n'émet pas `done` —
mais le module se présente comme lisant « la FORME, pas un réglage » : **devant
un proxy qui mêle les deux dialectes, il perd les décomptes en silence.** Aucune
scène ne couvre ce chemin.

**(b) Le garde du site unique ne couvre pas la seconde marque.** `repli_outil.py`
écrit qu'un second site voudrait dire deux motifs libres de diverger, « ce que ce
module existe précisément pour empêcher ». **Rien ne l'empêche pour la forme en
sentinelles** : le garde ne cherche que la marque de la forme du lot 19. **Preuve
rouge ET son contrôle positif dans la même mesure** : une copie du motif *des
sentinelles* collée dans `graph.py` → **38 passed, le garde ne voit rien** ; une
copie du motif *de la prose* au même endroit → **rouge**. C'est, mot pour mot, la
réserve R1 que l'audit du lot 19 avait laissée ouverte sur la même phrase.

**(c) La borne du rideau n'est tenue par rien.** Deux mutations qui élargissent
ou rétrécissent la portée du motif neuf passent au vert. Mais **le risque est
BORNÉ, et mesuré sur huit textes** : prose ordinaire, accolades JSON légitimes,
sentinelle ouvrante seule, sentinelles sans accolades → **0 caractère retiré**.
Deux cas où du texte part : une réponse qui **cite la syntaxe de fuite pour
l'expliquer** (57 caractères, et une recherche réelle part), et du texte pris
entre deux blocs d'accolades **à l'intérieur** des sentinelles (107). Le second
est structurellement le risque déjà accepté pour la forme du lot 19. **Ce qui est
retenu contre le lot n'est pas le motif : c'est qu'aucune scène ne tient sa
borne** — le lot 19 avait six proses ordinaires en contrôle négatif, la forme
neuve n'en a qu'une.

**(d) Le `break` n'est gardé par rien.** Le neutraliser passe au vert ; le
séparateur est un flux Ollama qui émet une ligne **après** son `done: true`.

**(e) Le garde d'erreur n'est tenu que pour le PREMIER événement.** Il **a
survécu au déménagement avec sa force** — vérifié : deux tokens cédés puis
`{"error": …}` lève bien, et la forme enveloppée en SSE aussi. Mais un mutant qui
ne lève **que sur la première ligne lue** passe les **937** tests : le cas nommé
par le pilote — l'erreur arrivant **après** des tokens — est **correct dans le
code et absent des scènes**.

**(f) La priorité prose / sentinelles est écrite au site et tenue par rien.**
Aucune scène du dépôt ne fait apparaître **les deux formes dans le même texte**.

**(g) Trois lignes défensives non exercées par les moteurs du poste** : un nom
vide qui écraserait le nom acquis (vLLM **omet** `name`, il ne le met pas à
`""` — mesuré), l'ordre d'apparition remplacé par un tri, et `isinstance(usage,
dict)` affaibli.

**(h) Une mutation qui casse le chemin Ollama et que rien ne fait rougir** :
`tool_calls` ignorés quand l'événement porte aussi du `content`. **AVEU DE BORNE
DE L'AUDITEUR** : il a essayé de faire produire cette forme par le moteur servi
et **gemma4 a séparé les deux** — l'événement portant `tool_calls` avait
`content: ""`. *Une requête ne fait pas une propriété* : il laisse la mutation
comme **ligne non gardée**, pas comme défaut représentable, et il écrit qu'il n'a
pas su la reproduire.

#### Deux déclarations du lot qui ne se reproduisent pas

**La provenance des scènes.** L'en-tête du fichier neuf affirme en capitales que
ses lignes « ne sont pas écrites de mémoire ». Inventaire de l'auditeur sur les
27 scènes : **12 relevées, 15 construites**, alors que le lot n'en déclare que
**deux** construites. Deux portent même une docstring « Mesuré 16/09 04:01:49 »
alors que leurs lignes sont **reconstruites**. **C'est le même piège que l'audit
du lot 19 avait relevé au même endroit du même chantier.** *Mais l'auditeur a
remesuré les deux faits que ces scènes affirment, et les deux sont vrais* : la
déclaration est **imprécise sur la forme, exacte sur le fond**.

**Une justification écrite au test qui est fausse.** Le lot écrit que « la
lecture ligne à ligne n'en voyait jamais que le premier [appel], y compris sur le
moteur servi ». Rejouant **l'ancienne boucle de `main`** sur sa propre capture,
l'auditeur mesure **2 rappels**, pas un : chaque événement d'Ollama porte un
appel entier et jugeable. **CE N'EST PAS LA LECTURE QUI N'EN VOYAIT QU'UN, C'EST
`graph.py` QUI N'EN RETIENT QU'UN** (`tool_queries[0]`). Sans conséquence sur le
comportement, mais la phrase est inexacte.

#### Ce qui entre au corpus des pièges

- **Un job de mutation est passé EN FOND au dépassement du délai**, et l'auditeur
  l'écrit : *« le risque a existé, et je ne l'ai pas prévenu, je l'ai
  rattrapé »*. Un lot de ce chantier avait déjà compté 15 puis 14 pour la même
  question à cause de ça.
- **Il a failli auditer `main` en croyant auditer le lot** : l'arbre où sa
  session s'ouvre était sur `2102f2a`. Un `pytest` lancé là aurait rendu des
  chiffres **parfaitement crédibles et parfaitement hors sujet**.
- **Il a failli valider « 22 rouges dont deux préexistantes » sur la coïncidence
  du total** : son banc de 202 tests rendait exactement 22, le même nombre. Il a
  fallu rejouer sur les 937 pour voir que la ventilation était fausse.
- **`/health` lui a rendu une réponse vide** et il a failli écrire que l'API ne
  répondait pas : le service écoute sur **8011**, pas 8000. *La sonde était
  fausse, pas le service.*
- **Il n'a pas recopié les motifs exacts de ses sondes d'attribution** dans son
  rapport : les écrire en toutes lettres ferait entrer dans ce dépôt public, **par
  la porte du rapport**, les noms mêmes que le refus écarte. Il les décrit, et
  établit leur pouvoir de discrimination par un contrôle positif.

---

### 4.56 → REPAR-21 : les huit gardes qui manquaient au lecteur de flux, et la mesure qui ne s'efface plus

**Livré le 16 septembre 2026**, base `main` = `27c0821` (442 commits). Ferme les **huit trouvailles non
bloquantes** du §4.55 et ses **deux déclarations qui ne se reproduisaient pas**.
Il n'y avait **aucune ligne fausse** à corriger — sauf une, et c'est (1).

**CE LOT NE BASCULE RIEN.** `.env`, `.env.example`, `docker-compose.yml` et
`OLLAMA_HOST` sont **hors du diff**, vérifié par `git diff --name-only` et
`git diff | grep`.

#### La campagne, et elle se juge à ses témoins

**Quatorze mutations, posées PAR MOTIF** — `assert` d'unicité de l'ancre et
`assert` que le SHA-256 a bougé, refus sinon — **jouées DEUX FOIS sur la suite
unitaire entière**, avant puis après correction. Le `rc` relevé est toujours
celui de **`pytest`**, jamais d'un tube. Restauration par `git checkout --`,
`git status --porcelain` contrôlé **sur la chaîne** (`[ -z "$S" ]`) et doublé
d'un `sha256sum -c` des quatre fichiers source : **l'arbre est resté propre aux
28 passages**.

**DEUX TÉMOINS INERTES, ET ILS RENDENT ZÉRO DANS LES DEUX PASSES** — une
réécriture équivalente dans `flux_llm.py`, une autre dans `repli_outil.py` :
`rc(pytest)=0`, 937 puis 954 passés. Le banc ne rougit pas tout seul.

| point | mutation | AVANT (937 tests) | APRÈS (954 tests) — ce qui MEURT |
|---|---|---|---|
| (1) T4 | écrasement inconditionnel restauré | *le défaut était dans le code servi* | **3 rouges** — `…usage_partiel_n_efface_pas…`, `…usage_vide…`, `…done_sans_compteurs…` |
| (1) T4 | règle de conflit inversée (« le premier gagne ») | — | **1 rouge** — `…usage_cumulatif_rend_le_dernier_compte…` |
| (2) T2 | motif du rideau rendu glouton | `rc=0`, 937 passed | **2 rouges** — `…sentinelles_ne_sont_pas_touches`, `…fuite_ecrite_sur_plusieurs_lignes…` |
| (2) T2 | `re.S` retiré | `rc=0`, 937 passed | **1 rouge** — `…fuite_ecrite_sur_plusieurs_lignes…` |
| (3) T1 | copie du motif **sentinelles** dans `graph.py` | `rc=0`, 937 passed | **1 rouge** — `test_le_motif_du_second_rideau_n_a_qu_un_site` |
| (3) T1 | copie du motif **prose** *(contrôle positif)* | `rc=1`, 1 rouge | `rc=1`, 1 rouge |
| (4) T5 | garde d'erreur limité à la 1re ligne lue | `rc=0`, 937 passed | **2 rouges** — les deux scènes d'erreur après tokens |
| (5) T7 | priorité prose/sentinelles inversée | `rc=0`, 937 passed | **1 rouge** — `…prose_garde_la_priorite…` |
| (6) T3 | `break` de `generate_stream` neutralisé | `rc=0`, 937 passed | **1 rouge** — `…ligne_emise_apres_done_true…` |
| (7) | `and nom` retiré | `rc=0`, 937 passed | **1 rouge** — `…nom_vide_n_ecrase_pas…` |
| (7) | `self._ordre` remplacé par un tri | `rc=0`, 937 passed | **1 rouge** — `…ordre_d_apparition_prime…` |
| (7) | `isinstance(usage, dict)` affaibli | `rc=0`, 937 passed | **1 rouge** — `…usage_qui_n_est_pas_un_objet…` |
| (8) | `tool_calls` ignorés si `content` non vide | `rc=0`, 937 passed | **1 rouge** — `…texte_et_un_appel_ne_perd_pas_l_appel` |

**AUCUNE MUTATION NE SURVIT.**

#### (1) LA MESURE QUI DEVENAIT UNE ABSENCE DÉCLARÉE — et la règle de conflit est MESURÉE

Le défaut du §4.55 (a) se reproduit intégralement sous ma main sur le code servi
(`mesuré` 16/09 07:48 UTC) : `(108, 27)` seul, mais `(None, None)` dès qu'un
`usage` — même **vide** — accompagne le `done`, et `(None, None)` dans l'autre
sens. Chaque branche ne remplace désormais que ce qu'elle **renseigne**.

**LE CLASSEMENT « NON REPRÉSENTABLE » SE REPRODUIT, VÉRIFIÉ DANS LES DEUX SENS**
(`mesuré` 16/09 07:26 UTC, deux requêtes, prompts distincts) : `ollama-central`
émet **61** événements dont **0** portant `usage` ; `vllm-central` émet **62**
événements JSON dont **0** portant `done`. Aucun moteur du poste ne mêle les
deux dialectes.

**MAIS LE CONFLIT A UNE FORME REPRÉSENTABLE QUE L'AUDIT N'AVAIT PAS VUE, ET ELLE
RENVERSE LE PREMIER RÉFLEXE.** La règle qui paraît la plus sûre — « une mesure
acquise ne bouge plus », le premier renseigné gagne — est **fausse, et c'est
mesuré** : `vllm-central` accepte `stream_options: {"include_usage": true,
"continuous_usage_stats": true}` et émet alors un `usage` **cumulatif sur chaque
événement** (`mesuré` 16/09 07:49 UTC : **42** événements, `completion_tokens`
de **0** à **40**). Garder le premier renseigné y figerait le compte à **zéro
token généré** — la mesure fausse même que ce garde existe pour empêcher. **La
règle servie est donc : le DERNIER renseigné gagne, champ par champ**, elle est
écrite au site avec sa base, et la scène qui la tranche est **RELEVÉE** de cette
capture. Le code servi rendait déjà `(29, 40)` sur ce flux ; la correction le
préserve.

#### (2) LA BORNE DU RIDEAU, TENUE DES DEUX CÔTÉS

Cinq scènes neuves. Le côté « ne doit pas être touché » : prose ordinaire,
accolades JSON légitimes, sentinelle ouvrante seule, paragraphe entier entre les
deux sentinelles → **0 caractère retiré** (`mesuré` 16/09 07:54 UTC). Le côté
« doit l'être » : la fuite multiligne, et deux fuites dont **le milieu est
conservé** (118 caractères retirés, `LE MILIEU QUI COMPTE` intact).

**LE CAS DE LA RÉPONSE QUI CITE LA SYNTAXE EST TRANCHÉ, ET IL EST ACCEPTÉ.** Le
rideau la traite comme une fuite : **57 caractères** partent et une recherche
réelle part sur la sous-question citée (`mesuré`, et ce chiffre **se reproduit**
exactement sur celui de l'audit). Les quatre raisons sont écrites au site — le
risque exige les deux sentinelles littérales dans la même réponse ; la
conséquence est une recherche **supplémentaire**, pas une réponse remplacée ; le
fermer demanderait de **deviner** à quoi ressemble une vraie fuite, que personne
ici n'a mesurée ; et l'erreur symétrique coûte plus cher. Une scène fixe ce
choix pour qu'il ne change pas en silence.

#### (3) LE GARDE DU SITE UNIQUE CHERCHE DÉSORMAIS LA SECONDE MARQUE

La réserve **R1 de l'audit du lot 19**, relevée une seconde fois par l'audit du
lot 20 sur la même phrase, est **fermée**. La marque ajoutée est la **barre
verticale échappée** : une prose qui parle de la sentinelle l'écrit telle
quelle, un motif **doit** l'échapper. Assemblée par concaténation, comme la
première, pour que le garde ne se trouve pas lui-même. **Elle a SON propre
contrôle positif** — la marque de la prose prouve sa discrimination sur ses
textes, pas sur ceux des sentinelles.

#### (4) à (8)

- **(4)** deux scènes d'erreur arrivant **après** des tokens, dont une en
  enveloppe SSE.
- **(5)** la première scène du dépôt où **les deux formes** apparaissent dans le
  même texte.
- **(6)** une ligne émise **après** `done: true`, qui ne doit pas atteindre
  l'écran. Le garde de l'angle que le pilote craignait **n'a pas été refait** :
  il existe, et le §4.55 l'établit.
- **(7)** les trois lignes défensives sont gardées **ET dites défensives au
  site**, chacune avec la mesure qui explique pourquoi les moteurs du poste ne
  l'exercent pas.
- **(8)** l'événement mêlant `content` et `tool_calls` est gardé sur une forme
  **CONSTRUITE, déclarée comme telle au site**. **JE CONFIRME L'AVEU DE
  L'AUDITEUR au lieu de le renverser** : trois requêtes supplémentaires,
  prompts distincts, sur les **deux** moteurs (`mesuré` 16/09 07:26–07:27 UTC),
  n'ont pas su produire la forme. Ollama rend `content: ""` sur l'événement
  porteur, vLLM rend `content: null` sur les quatre fragments, et les trois
  réponses se terminent sur `done_reason: "stop"` ou
  `finish_reason: "tool_calls"` — **donc pas sur une troncature de ma borne**.

#### Ce que devient le SECOND appel d'outil — la borne est écrite, pas supposée

Écrit au site d'`extract_tool_query` : le second appel est **accumulé,
disponible, et lu par personne**. Le comportement ne change pas, et les trois
raisons sont écrites : servir les deux appels du même tour doublerait la
consommation de `max_search_iterations`, dimensionné sur « un tour, une
recherche », et c'est une politique d'**agent** ; le second n'est pas jeté en
silence, il est non sélectionné à un endroit **unique et nommé** ; et rien ne
mesure aujourd'hui qu'il serve mieux l'utilisateur. **Ce qui ferait
reconsidérer** est écrit aussi : une campagne qui mesure ce que la seconde
sous-question aurait ramené.

#### Les deux déclarations, corrigées

**L'INVENTAIRE DE PROVENANCE EST REFAIT À LA MAIN**, scène par scène, sur les 27
scènes d'alors. L'heuristique « s'appuie sur l'une des quatre constantes
capturées » rend **12 / 15** — **le chiffre de l'auditeur se reproduit**. Ma
relecture l'affine en **quatre** cases plutôt que deux, et ce n'est pas un
renversement : **12 RELEVÉES, 1 RECOPIÉE** (une ligne relevée écrite en
littéral), **1 MIXTE**, **13 CONSTRUITES**. L'en-tête le dit désormais ainsi, et
les deux docstrings qui disaient « Mesuré » sur des lignes **reconstruites**
distinguent maintenant le FAIT mesuré des LIGNES construites.

**LA JUSTIFICATION FAUSSE EST CORRIGÉE, ET JE L'AI REMESURÉE AU LIEU DE LA
CROIRE.** L'ancienne boucle de `main` (`2102f2a`), extraite telle quelle et
rejouée sur les deux événements d'Ollama, émet **2 rappels**, pas un
(`mesuré` 16/09 07:53 UTC). C'est bien `graph.py:308` qui n'en retient qu'un
(`tool_queries[0]`, vérifié au site).

#### La porte, les comptes, et ce qui entre au corpus des pièges

`documentation/tests.md` : **954** tests sur **48** fichiers, **COMPTÉS** par la
recette que le document publie (`mesuré` 16/09 07:58 UTC), aux deux sites que le
garde confronte. Les quatorze de plus par rapport au lot 20 ne sont pas calculés
depuis 937 : le chiffre est celui de la collecte.

- **UNE DE MES SCÈNES ÉTAIT VERTE POUR UNE RAISON QUI N'ÉTAIT PAS LA SIENNE.**
  La scène écrite pour tuer « `re.S` retiré » posait ses retours à la ligne
  **autour** du bloc d'accolades, là où les `\s*` du motif les absorbent et où
  `re.S` ne joue aucun rôle. La mutation a **survécu à la scène écrite pour la
  tuer**, et c'est le banc qui me l'a dit, pas ma relecture. Le retour à la
  ligne est désormais **à l'intérieur** du bloc. *Une scène qui passe n'est pas
  une scène qui mesure.*
- **Un `type(x) is str` en témoin inerte n'est pas équivalent à
  `isinstance(x, str)`** en général — il l'est sur le domaine mesuré ici, et
  c'est à ce titre seulement qu'il sert de témoin.

#### Ce que le pilote a vérifié DE SES MAINS, et pourquoi il n'y a pas de quatrième audit

**Le §4.18 s'applique, et sa clause exige une vérification personnelle : la
voici.**

**(1) Le périmètre de comportement, borné par un banc AST AVEC CONTRÔLE
POSITIF.** Docstrings retirées, `src/agent/llm.py` et `src/agent/repli_outil.py`
rendent un AST **IDENTIQUE** entre `main` et la tête — leurs 36 et 48 lignes sont
**intégralement** du commentaire. Dans `src/agent/flux_llm.py`, comparaison unité
par unité : **`_lire_decomptes` modifiée, `_renseigner` ajoutée, et RIEN
D'AUTRE** — `lire`, `_charge`, `_accumuler`, `message_outils`, `__init__` et
`Decomptes` sont inchangés. *Le contrôle positif — une seule ligne mutée dans
`flux_llm.py` — rend bien « AST différent », donc le banc discrimine et ne rend
pas « identique » par impuissance.*

**(2) LA SEULE DÉCISION QUE L'AUDIT N'AVAIT PAS SPÉCIFIÉE, REMESURÉE.** L'audit
demandait « une ligne qui ne remplace que ce qu'elle renseigne » ; il ne disait
rien du **sens** du conflit. Le lot a tranché « le dernier renseigné gagne » sur
une mesure. `mesuré` par le pilote le **16 septembre 2026 à 08:36 UTC**, sur
`vllm-central`, avec `stream_options: {"include_usage": true,
"continuous_usage_stats": true}` passé **par requête**, et sur un prompt **qui
n'est pas celui du lot** : **62 événements JSON, 62 portant un `usage`**,
`completion_tokens` allant de **0 à 60**, premier renseigné **`(35, 0)`**,
dernier **`(35, 60)`**, **aucun champ `done`**. La règle « le premier gagne »
aurait donc figé le compte à **zéro token généré**. **La mesure du lot se
reproduit sous une autre main et un autre prompt.**

**(3) Les gardes éprouvés, parce qu'un garde ne se juge pas à sa lecture.** Six
mutations posées **par motif**, `assert` d'unicité de l'ancre avant écriture,
`assert` que le SHA-256 a bougé, restauration contrôlée au SHA-256 et
`git status --porcelain` testé **sur la chaîne** après chacune :

| mutation du pilote | `rc(pytest)` | ce qui meurt |
|---|---|---|
| **témoin inerte** (commentaire ajouté) | **0** | — *le banc ne rougit pas tout seul* |
| écrasement inconditionnel restauré | **1** | les trois scènes `…n_efface_pas…` |
| garde d'erreur limité à la première ligne | **1** | les trois scènes d'erreur, dont les deux **après des tokens** |
| priorité prose/sentinelles inversée | **1** | `…la_prose_garde_la_priorite…` |
| **copie du motif DES SENTINELLES dans `graph.py`** | **1** | `test_le_motif_du_second_rideau_n_a_qu_un_site` |
| copie du motif DE LA PROSE *(contrôle positif, même passe)* | **1** | le même |

**La réserve R1 — ouverte par l'audit du lot 19, rouverte par celui du lot 20 —
est fermée**, et son contrôle positif est dans la même passe.

**(4) UN FAUX RÉSULTAT DU PILOTE CONTRE LUI-MÊME, ET IL VALAIT UNE TROUVAILLE.**
Ma première mutation de la règle inversée est passée **VERTE** là où le lot
annonçait rouge. J'ai failli l'écrire comme un garde qui ne mord pas. **Elle
n'inversait que `prompt_eval_count`** — or `prompt_tokens` est **CONSTANT** (35)
dans le flux cumulatif que je venais de mesurer : la moitié que j'inversais **ne
pouvait pas se voir**. Elle était **équivalente sur le domaine mesuré**, pas
faible. Rejouée sur **les deux champs**, elle rend `rc=1` et meurt sur exactement
`test_un_usage_cumulatif_rend_le_dernier_compte_et_non_le_premier`. **C'était mon
mutant, pas le garde** — la faute que l'auditeur du lot 19 avait déjà consignée
contre lui-même sur son mutant M2, refaite ici par le pilote.

### 4.57 → LOT-22 : l'image porte l'identité du code, et `/health` la publie

**Livré et FUSIONNÉ le 16 septembre 2026** — `c2581cd`. Lot **5** du découpage du
chantier vLLM. **Il ne bascule rien et ne redéploie rien** : Ollama reste le
moteur servi, aucun conteneur n'a été touché, `RestartCount=0` et `StartedAt`
inchangé après le lot comme après son audit.

#### La borne qu'il lève a été payée DEUX FOIS

**§4.42** : pendant **douze lots**, l'agent servi a exécuté du code antérieur et
**aucun garde livré ne tournait** — parce que rien ne permettait de répondre à
« quel code tourne ? ». Puis **au lot 18** : une étiquette datée désignait
l'image d'un autre jour, et un `build` aurait rendu l'état servi **anonyme et
irrécupérable**.

#### Le mécanisme, et pourquoi celui-là

Trois `ARG` **sans valeur par défaut** dans `Dockerfile.agent`, gravés **deux
fois** : en `ENV` que `/health` lit, et en `LABEL` que `docker image inspect`
lit. **Ce n'est pas de la redondance** : `env_file: .env` permet à l'exécution de
l'emporter sur l'`ENV` de l'image, alors que le label est **figé à la
construction**. Le document dit lequel tranche.

**Trois positions, et trois seulement** : `identifie`, `arbre_sale`, `anonyme` —
**séparées par leur AVERTISSEMENT et pas seulement par leur position**, ce que
deux mutations de l'audit établissent en remplaçant un message par un autre à
position constante.

**Un sha gravé sans mot sur l'arbre reste `anonyme`.** Le rendre `identifie`
supposerait la propreté, `arbre_sale` affirmerait la saleté : **les deux
affirmeraient un fait que le build n'a pas donné.** C'est la doctrine du chantier
appliquée à un cas neuf.

**Un build en arbre sale publie son sha AVEC sa réserve** — le taire publierait
une identité fausse, ne rien publier perdrait le seul repère. La propreté est
relevée **SUR LA CHAÎNE** (`S="$(git status --porcelain)"` puis `[ -z "$S" ]`),
jamais sur le `rc`, et deux mutations le gardent.

**Porte, mesurée par le pilote SUR LE RÉSULTAT DE LA FUSION**, arbre détaché neuf
monté par le §2.2, le **16 septembre 2026** : `rc(make lint)=0`,
`rc(make test)=0`, **999 passés** sur **49** fichiers (`main` avant : 954 sur
48). Arbre scellé **`fd61468`**, bit pour bit celui mesuré.

#### CE QUE LE LOT A TROUVÉ EN CHEMIN, ET QUI COMMANDE LA SUITE DU CHANTIER

**L'AGENT EN SERVICE EXÉCUTE LE CODE DE `8209e68`, 27 COMMITS DERRIÈRE `main`.**
`src/agent/flux_llm.py` et `src/agent/repli_outil.py` en sont **ABSENTS, pas
anciens** : **les lots 19, 20 et 21 ne sont pas en service.** Le second rideau ne
tourne pas ; le lecteur des deux dialectes ne tourne pas.

**Tranché PAR LE CONTENEUR, jamais par l'étiquette**, et trois fois : le lot par
`docker cp` + SHA-256 ; **le pilote de ses mains** le 16 septembre à 10:52 UTC,
même méthode, autre recette d'empreinte ; l'auditeur par une méthode
**exhaustive** — empreinte d'objet git de chaque `.py` extrait du conteneur,
comparée à `git ls-tree -r` de **chacun des 451 commits atteignables**.

**ET L'AUDITEUR PRÉCISE CE QUE NI LE LOT NI LE PILOTE N'AVAIENT VU** : *le contenu
seul ne désigne pas `8209e68`.* **TREIZE commits portent exactement le même
`src/`**, de 32 à 22 derrière `main`. Ce qui pince `8209e68` est **l'horodatage
de construction de l'image** — sept minutes après ce commit — **ni le contenu, ni
l'étiquette**. Le chiffre 27 est juste, **mais il repose sur deux faits et non
sur un seul**, et c'est exactement ce que le document du lot écrit de lui-même :
*« il ne prouve pas que l'image contient le code de ce commit — il rapporte ce
que le build a déclaré »*.

*Corollaire relevé au passage : l'étiquette `2026-09-14-servi-avant-lot15` pend
toujours à l'image du 11 septembre. **Une étiquette datée ment sur ce qu'elle
désigne**, et le poste le démontre encore.*

#### L'audit : aucune bloquante, et il refuse d'en forcer une

[`audits/2026-09-16-audit-lot-22.md`](audits/2026-09-16-audit-lot-22.md), versé
sur `main` en **`b88fa0b`** *avant* d'être cité. Les **18 prémisses se
reproduisent à l'identique**, aucune n'a vieilli.

**L'ANGLE LE PLUS CHER EST RÉGLÉ PAR LA MESURE LA PLUS DIRECTE POSSIBLE.** Le
pilote craignait qu'une image mal construite fasse rendre **500** à `/health`,
transformant une incertitude en indisponibilité. L'auditeur a construit de vraies
images et interrogé de vrais conteneurs : **les six formes d'identité mal formée
rendent HTTP 200**, avec `etat: anonyme`. Plus un balayage de **1 056
combinaisons** d'environnement : **zéro `ValidationError`**, les **trois**
positions atteintes (960 / 72 / 24), **avec contrôle positif** — en relâchant le
motif, la même boucle voit lever. *Le module ramène à `anonyme` AVANT le schéma,
et la seconde barrière ne peut pas tirer en production.* En chemin **forcé**, elle
rend bien 500, mesuré aussi.

**IL A JOUÉ `make image` POUR DE VRAI**, ce que le lot déclarait n'avoir pas fait,
et **dans les deux sens** : arbre propre → `code.arbre=propre`, arbre sali →
`code.arbre=sale`, **même sha**, `rc(make)=0` des deux côtés.

#### IL CORRIGE LE PILOTE TROIS FOIS, ET IL A RAISON LES TROIS FOIS

1. **`restart: unless-stopped` ne redémarre PAS un conteneur `unhealthy`** —
   Docker réagit à une **sortie**, et il n'y a aucun *autoheal* dans ce compose.
   Ma phrase « la panne se répète toute seule » était fausse. **Le coût réel est
   ailleurs et il est sérieux** : `frontend` porte
   `depends_on: agent-api: condition: service_healthy`, donc un `agent-api` qui
   ne passe jamais `healthy` **empêche `frontend` de lever à froid,
   indéfiniment**.
2. **La déclaration « deux gestes non éprouvés » N'EXISTE NULLE PART DANS LE
   DÉPÔT.** Je l'avais reprise du rapport de conversation du lot. Le diff entier
   et les trois corps de commit ne la portent pas ; le commit dit *« chaque
   commande exacte, éprouvée »*, **sans réserve**, alors que `RestartCount=0`
   prouve que les deux gestes qui touchent le service n'ont pas pu l'être. **ET
   C'EST LE DÉPÔT QUI SURVIT, PAS LA CONVERSATION** — leçon à porter au-delà de
   ce lot.
3. **L'absence de `.dockerignore` coûte 914 ko transférés, pas 2 Go** : BuildKit
   ne transfère que ce que les `COPY` désignent. Ma crainte était mal calibrée.

#### LE TÉMOIN INERTE A PAYÉ POUR TOUT LE RAPPORT

À sa **première exécution**, le témoin de l'auditeur a rendu **954 passés au lieu
de 999**. Son harnais écrivait bien dans l'arbre détaché mais lançait `pytest`
**depuis le répertoire courant du shell**, c'est-à-dire sur `main`. **Sans ce
témoin, les vingt-deux mutations suivantes auraient toutes été jouées contre un
arbre où le fichier audité n'existe pas : elles auraient toutes « survécu », et
le rapport aurait affirmé que le lot n'est gardé par rien.** C'est la
démonstration la plus complète du témoin inerte que ce chantier ait produite, et
elle vaut d'être citée telle quelle.

#### Ce qui reste OUVERT — quatre non bloquantes

**NB-1 — LE SEUL REMPART CONTRE UN `/health` EN 500 N'EST GARDÉ PAR RIEN.**
`_UN_SHA = re.compile(r"^[0-9a-f]{40}$")` est la **première** barrière, celle qui
empêche la seconde de tirer. **Deux mutations distinctes ne font rougir aucun
test** : `{40}` → `{7,40}`, et les ancres retirées. **Elles ne sont pas
équivalentes**, et leurs textes séparateurs sont mesurés des deux côtés,
`/health` appelé pour de vrai : `8209e68` (ce que rend `git rev-parse --short
HEAD`) et un 40-hex suffixé `-dirty` (ce que rend `git describe --always
--dirty`) font passer le mutant de **200 à 500**. **Ce sont les deux façons les
plus probables de casser la cible.** La cause est nommée : les sept faux sha du
lot éprouvent le **contrat**, pas la **lecture** — le seul qui traverse
`identite_du_code()` est `HEAD`, que les deux mutants refusent aussi.

**NB-2 — une citation de site canonique qui désigne un fichier n'ayant jamais
existé.** `src/api/identite_du_code.py` cite
`documentation/registre_du_chantier.md` §4.42 ; ce fichier n'a jamais été suivi.
**REPAR-23 RENVERSE ICI L'AUDITEUR SUR LE FICHIER DE REMPLACEMENT**, et le
pilote avait raison : le registre réel est **`documentation/axes_amelioration.md`**,
seul fichier du dépôt à porter le **titre de section** `### 4.42 →`, à la ligne
6579 — et ce titre (« *le lot 4 … l'agent en service n'a jamais exécuté le garde
du lot 3* ») est exactement ce que la docstring veut désigner.
`documentation/pilotage_du_chantier.md` ne porte **aucun** titre `4.42` à aucune
profondeur ; ses cinq occurrences de « §4.42 » sont des **renvois**, tous dans
des lignes de tableau, et ses propres sections vont de `## 1.` à `## 12.`
— son §4 est « L'état du poste ». `mesuré` le 16 septembre 2026 à 12:39 UTC par
trois méthodes concordantes : `git grep -n '^#\+ *4\.42'` sur `documentation/`
ne rend qu'une ligne ; le comptage des titres `4.N` par fichier rend **58** pour
`axes_amelioration.md` et **0** pour `pilotage_du_chantier.md` ; la contre-épreuve
sur le second rend `rc=1`. **Aucun rouge à montrer, et c'est le fait** : aucun garde de ce
dépôt ne vérifie que les documents cités par le code existent — dans un module
dont la thèse est *« un seul site canonique »*.

**NB-3 — une déclaration d'épreuve plus large que ce qui a pu être éprouvé**
(voir la correction 2 ci-dessus).

**NB-4 — un commentaire emphatique sur une distinction inexistante.** Le compose
écrit que `${VAR:-}` contre `${VAR-}` « n'est pas cosmétique » ; l'auditeur mesure
par `docker compose config`, sur une copie en projet isolé, que **les deux formes
coïncident sur tout le domaine** — le repli étant la chaîne vide, elles ne
peuvent pas se séparer. **Il avoue la mutation ÉQUIVALENTE au lieu d'en faire une
trouvaille.**

#### Les faux résultats de l'auditeur, et deux entrent au corpus

- **Son compteur de rouges comptait les journaux** : `grep -cE '^(FAILED|ERROR) '`
  attrapait une ligne de journal capturé commençant par `ERROR    src.agent…`.
  *La sonde trouvait, elle ne discriminait pas.* Ancré sur `^(FAILED|ERROR) tests/`.
- **Il a lu une sortie VIDE comme une valeur** : `2>/dev/null` masquait l'échec de
  `docker compose config`, et sa boucle imprimait six fois une variable vide —
  ce qui **ressemblait à un résultat cohérent**. Il a failli en conclure une
  propriété.
- **Son sélecteur `git grep` a sous-compté** : `'src/**/*.py'` rend 88 `noqa` là
  où le compte par fichier en rend **93** — sans la magie `:(glob)`, le `**` de
  git ne fait pas ce qu'on croit.
- **Il a failli faire entrer dans le dépôt public le nom de l'outil qui
  l'exécute** : sa première rédaction citait les chemins absolus de ses arbres et
  son nom de branche. **Sa propre sonde l'a attrapé avant le commit** — 16
  occurrences —, il les a élidées et rejoué la sonde à zéro. *La consigne le
  disait ; c'est la sonde qui l'a fait respecter.*


---

### 4.58 → REPAR-23 : les quatre non bloquantes du garde de déploiement, et une TROISIÈME borne que l'audit n'avait pas mutée

> **Rien n'est basculé et rien n'est redéployé.** Aucune image de production
> construite, `rag-agent-api` non touché — `RestartCount=0`,
> `StartedAt=2026-09-15T21:21:05Z` avant comme après, `mesuré` le 16 septembre
> 2026 à 12:43 et 13:0x UTC. Le redéploiement est le lot suivant, et il n'aura
> lieu qu'une fois : c'est la raison pour laquelle ces corrections passent avant.

**Base.** `main` = `origin/main` = `0a57787`, **455 commits**, remesuré à
12:21 UTC. Porte du lot : `rc(make lint)=0`, `rc(make test)=0`,
**1005 passés sur 49 fichiers** (999 avant), programme relevé : `make`.

#### NB-1 — le seul rempart contre un `/health` en 500 : **TROIS** bornes, pas deux

L'audit publie deux mutations survivantes sur `_UN_SHA`. **IL Y EN A TROIS.**
La borne de CASSE — que l'audit nomme dans sa prose (« la borne de longueur et la
borne de **casse** … ne sont visitées par personne ») mais ne mute pas — ouvre
son propre chemin vers le 500. Les trois survivaient à la suite entière
(**999 passés, 0 rouge, `rc(pytest)=0`**), et chacune a son **texte séparateur
propre**, `/health` appelé pour de vrai des deux côtés (`TestClient`,
`raise_server_exceptions=False`), `mesuré` le 16 septembre 2026 à 12:32–12:33 UTC :

| Mutation du motif | `8209e68` | `…4c15b-dirty` | 40-hex MAJUSCULE |
|---|---|---|---|
| **code servi** | 200 `anonyme` | 200 `anonyme` | 200 `anonyme` |
| `{40}` → `{7,40}` | **500** | 200 | 200 |
| ancres `^…$` retirées | 200 | **500** | 200 |
| `[0-9a-f]` → `[0-9a-fA-F]` | 200 | 200 | **500** |

**LA MATRICE EST DIAGONALE, ET C'EST LE FAIT QUI COMMANDE LA CORRECTION** :
chaque valeur ne sépare **qu'une** mutation. Un seul cas ajouté en aurait laissé
deux vivantes. Les trois valeurs sont les sorties de trois commandes qu'un
lecteur pressé mettrait dans la cible `image` en croyant l'améliorer :
`git rev-parse --short HEAD`, `git describe --always --dirty`, et un relevé passé
par un outil qui majuscule.

**Après correction** — la scène `test_un_sha_illisible_laisse_l_image_anonyme_et_le_dit`
est paramétrée sur quatre cas — chaque mutation meurt par **son** cas nommé et un
seul, ce qui écarte la mort « par un autre chemin » :

| Mutation | `rc(pytest)` | Rouges | Ce qui meurt |
|---|---|---|---|
| `{40}` → `{7,40}` | 1 | **1** | `…test_un_sha_illisible…[sha-abrege]` |
| ancres retirées | 1 | **1** | `…test_un_sha_illisible…[40-hex-suffixe]` |
| casse relâchée | 1 | **1** | `…test_un_sha_illisible…[40-hex-majuscule]` |

**Le coût du 500 est écrit au site, exactement.** `restart: unless-stopped` NE le
rattrape PAS — Docker redémarre un conteneur qui **sort**, pas un `unhealthy`, et
ce compose ne porte aucun autoheal. Le coût réel est que `frontend` porte
`depends_on: agent-api: condition: service_healthy` et **ne lèverait jamais à
froid**. Un conteneur déjà debout, lui, continue de servir.

#### NB-2 — **REPAR-23 RENVERSE L'AUDITEUR, ET LE PILOTE AVAIT RAISON**

Le fichier cité n'existe pas : c'est acquis. **Mais le fichier de remplacement
que l'auditeur nomme est le mauvais.** `mesuré` le 16 septembre 2026 à
12:39 UTC, trois méthodes concordantes :

- `git grep -n '^#\+ *4\.42' -- documentation/` ne rend **qu'une seule ligne** :
  `documentation/axes_amelioration.md:6579:### 4.42 → Le lot 4 : … l'agent en
  service n'a jamais exécuté le garde du lot 3` — et cet intitulé est
  **exactement** ce que la docstring du module désigne ;
- comptage des titres `4.N` par fichier : **58** dans `axes_amelioration.md`,
  **0** dans `pilotage_du_chantier.md` ;
- contre-épreuve sur le second : `grep -nE '^#+.*4\.42'` rend **`rc=1`**. Ses
  cinq occurrences de « §4.42 » sont des **renvois**, tous dans des lignes de
  tableau ; ses propres sections vont de `## 1.` à `## 12.`, et son §4 est
  « L'état du poste ».

**Le garde générique est POSÉ**, et la décision est mesurée et non jugée : sur ce
dépôt le motif rend **30** citations, **10** chemins distincts, **8** fichiers de
`src/`, et **une seule** absente avant correction — **le bruit est nul**.

Ses deux pièges sont nommés et traités :

- **IL DISCRIMINE, et sa preuve d'atteinte est assertée DANS le verdict** — une
  borne inférieure (≥ 5 chemins, ≥ 4 fichiers) et non le compte exact, qui serait
  un instantané rougissant au prochain commentaire ajouté. Un garde qui cherche
  des chemins et n'en trouve aucun serait vert **par impuissance**.
- **IL SE TIENT À DISTANCE DE LUI-MÊME, PAR CONSTRUCTION ET NON PAR EXCLUSION** :
  il vit dans `tests/`, et `tests/` n'est pas dans le domaine balayé (`src/`).
  Les chemins fabriqués de son contrôle positif ne peuvent donc pas entrer dans
  ce qu'il mesure. `test_le_domaine_balaye_exclut_la_source_de_ce_garde`
  l'asserte, pour que personne n'élargisse le domaine sans voir ce qu'il casse.

Cinq mutations l'éprouvent, toutes rouges : motif rendu aveugle (**2** rouges —
le verdict ET le contrôle positif), domaine élargi à `tests/` (**1** —
le garde de distance), et **trois contrôles positifs sur trois fichiers réels
différents**, une faute à la fois, dont un chemin **imbriqué** (`campagnes/…`) :
le défaut du lot 22 replanté dans `identite_du_code.py`, un chemin inventé dans
`usage.py`, un autre dans `llm.py`. Chacun rend **1** rouge nommé.

#### NB-3 — la réserve est écrite AU SITE, à ses **trois** endroits

Le lot 22 avait écrit cette réserve dans son rapport de conversation ; elle
n'était nulle part dans le dépôt. **Le dépôt survit, pas la conversation.**
`documentation/identite_du_code_servi.md` porte désormais, en encadré au §4 puis
**au site exact de chacune des deux commandes**, que les deux
`docker compose up -d --no-build agent-api` sont **ÉCRITS et non ÉPROUVÉS** —
avec ce qui n'a donc pas été vérifié (que `--no-build` empêche `up` de
reconstruire ; que le retour rende le conteneur à l'image relevée en (a)), et
avec ce qui l'a été (a, b, c, d, f). La réserve du *Revenir* dit en plus
**pourquoi elle y est plus gênante** : c'est la ligne qu'on joue sous pression.

#### NB-4 — l'équivalence, **mesurée par REPAR-23 sur un domaine EXHAUSTIF**

**Je confirme l'auditeur et j'étends son domaine.** `mesuré` le 16 septembre 2026
à 12:44 UTC, copie du compose en projet isolé (`-p repar23probe`, `.env` vide),
`docker compose config --format json`, **les deux compose doublés de leur SHA-256
pour prouver qu'ils diffèrent réellement** : les deux formes coïncident sur
**sept** valeurs — absente, vide, **un espace**, deux espaces, `abc`, `0`, un
saut de ligne.

**Le domaine n'est pas échantillonné, il est COMPLET** : une variable n'a que
trois états, les deux formes ne peuvent différer que sur « présente et vide », et
le repli y est la chaîne vide des deux côtés. **L'ESPACE — le cas que la
rédaction précédente invoquait pour justifier sa clause finale — ne sépare pas
davantage.** La mutation `${VAR:-}` → `${VAR-}` est donc **ÉQUIVALENTE**, elle
survit encore après réécriture (1005 passés, 0 rouge), et c'est **avoué**. Le
commentaire dit désormais ce qui est vrai, et le garde du gabarit mord toujours
(argument renommé : **3** rouges nommés).

#### Les faux résultats de REPAR-23, contre lui-même

- **UN `git checkout --` A EFFACÉ SA PROPRE CORRECTION NON COMMITÉE.** En
  restaurant après un contrôle positif, la correction NB-2 — écrite mais pas
  encore commitée — a été détruite avec la mutation. **C'est le SHA-256 qui l'a
  attrapé** : le « restauré » attendu n'a pas été imprimé, et la vérification a
  montré le chemin fautif revenu. Les contrôles suivants ont alors mesuré un
  arbre déjà cassé. *Corrigé en commitant AVANT de muter, et tout a été rejoué.*
- **SA SONDE DE BASCULE S'EST ATTRAPÉE ELLE-MÊME.** `OLLAMA_HOST` rend **1**
  occurrence dans son diff — c'est la phrase de son propre garde qui **raconte**
  qu'une sonde `OLLAMA_HOST` s'est attrapée. *La phrase qui déclare le précédent
  EST l'occurrence.* Qualifiée (prose, pas un réglage) et doublée d'un contrôle
  positif discriminant : un vrai témoin de bascule posé dans le compose est bien
  vu.
- **IL A CASSÉ LA NOTE DU COMPTE EN LA RÉÉCRIVANT**, en faisant passer le mot
  « fichiers » à la ligne suivante. Le garde `TestLaNoteDuCompteEstLueAuBonEndroit`
  a rougi — **le même geste qui l'avait fait naître le 11 septembre**. Il tient.
- **SON GARDE D'UNICITÉ A COMPTÉ 174 POUR UNE ANCRE PRÉSENTE UNE FOIS** : une
  ancre multi-ligne terminée par un saut de ligne fait compter à `grep -cF`
  **toutes les lignes du fichier** (174 = `wc -l` du compose). *Le garde a
  REFUSÉ la mutation au lieu de la poser à l'aveugle* — il a fait son travail.
- **IL A LU UNE SORTIE VIDE COMME UNE VALEUR, DEUX FOIS.**
  `pytest --collect-only -q` s'est cumulé au `-q` de `addopts` : la sortie ne
  portait plus d'identifiants de nœuds, et son compte a rendu **0 test** — ce qui
  aurait pu passer pour une mesure. Et son écho de contrôle sur la forme du
  compose a rendu du vide, sans qu'il ait alors prouvé que ses deux formes
  différaient. *Corrigé en doublant du SHA-256 et en recoupant chaque compte par
  une seconde méthode.*

#### Ce que le pilote a vérifié DE SES MAINS, et pourquoi il n'y a pas de quatrième audit

**Le §4.18 s'applique sans ambiguïté** : `git diff main..tête -- src/` fait **une
seule ligne** — un nom de fichier dans une docstring —, lue en entier. Tout le
reste du diff est du garde, de la prose et de la documentation. Mais la clause
exige une vérification personnelle, la voici.

**(1) LA MATRICE DIAGONALE, REMESURÉE.** Mutations posées **par motif** sur
`_UN_SHA`, `assert` d'unicité de l'ancre avant écriture, `assert` que le SHA-256
a bougé, restauration contrôlée au SHA-256, `git status --porcelain` testé **sur
la chaîne**. `rc` relevé de **`pytest`** :

| mutation du pilote | `rc(pytest)` | rouges | ce qui meurt |
|---|---|---|---|
| **témoin inerte** (commentaire ajouté) | **0** | **0** | — *le banc ne rougit pas tout seul* |
| borne de **longueur**, `{40}` → `{7,40}` | **1** | **1** | `…test_un_sha_illisible_laisse_l_image_anonyme_et_le_dit[sha-abrege]` |
| borne d'**ancrage**, `^…$` retirées | **1** | **1** | le même test, `[40-hex-suffixe]` |
| borne de **casse**, `a-f` → `a-fA-F` | **1** | **1** | le même test, `[40-hex-majuscule]` |

**UN SEUL ROUGE CHACUNE.** Aucune ne meurt par un autre chemin, et la troisième
borne — celle que l'audit nommait sans la muter — est bien fermée. **Le lot a
raison contre l'auditeur : les « deux cas » recommandés en auraient laissé une
vivante.**

**(2) LE FICHIER DU §4.42, REMESURÉ — ET C'EST UNE ERREUR DE PILOTAGE.**
`git grep -n '^#\+ *4\.42' -- documentation/` rend **une seule ligne**, dans
`documentation/axes_amelioration.md`. Les titres `4.N` comptent **58** dans ce
fichier et **ZÉRO** dans `pilotage_du_chantier.md`, dont les sections vont de
`## 1.` à `## 12.` et dont le §4 est « L'état du poste ».

**J'avais recopié le nom donné par l'auditeur dans le §4.57 ci-dessus, sans
passer cette commande.** Le lot l'a corrigé aux deux sites. L'erreur est portée
au **§12 du mandat**, parce qu'elle a une forme générale : *la rigueur d'un
rapport ne dispense pas de mesurer ce qu'on en cite — elle y oblige plutôt, parce
qu'un rapport juste partout ailleurs est celui qu'on recopie sans y penser.*

**(3) La porte, sur le RÉSULTAT DE LA FUSION** : `rc(make lint)=0`,
`rc(make test)=0`, **1005 passés** sur **49** fichiers. Arbre scellé
**`f98fe4f`**, bit pour bit celui mesuré.

### 4.59 → LOT-24 : le redéploiement, et la première fois que l'agent dit quel code il exécute

**Livré et FUSIONNÉ le 16 septembre 2026** — `f30af30`. Le seul lot du chantier
qui touche le service.

#### LA BORNE QUE DOUZE LOTS ONT PAYÉE EST LEVÉE

Conteneur **recréé** le 16 septembre à **13:40:14 UTC**, `healthy` en **21 s**,
`RestartCount=0`. L'agent servait le code de `8209e68`, **sans `flux_llm.py` ni
`repli_outil.py` — ABSENTS, pas anciens**. **Les lots 19, 20 et 21 tournent
maintenant.**

`/health` publie désormais :

```json
{"etat": "identifie", "sha": "b7337a3e544009dbbbc36764cb072e046b175e09",
 "construite_le": "2026-09-16T13:39:21Z", "avertissement": null}
```

**Et `b7337a3` EST `main`.** Pour la première fois de ce chantier, l'agent en
service dit quel code il exécute. **§4.42 est refermé pour de bon** — non par une
promesse, mais par un champ que n'importe qui peut lire.

#### CE QUE LE PILOTE A VÉRIFIÉ DE SES MAINS, ET LE ZÉRO EST DOUBLÉ

`code_servi` est une **DÉCLARATION DU BUILD**, pas une preuve du contenu — le
module le dit lui-même. J'ai donc tranché **PAR LE CONTENEUR** : `docker cp` puis
SHA-256 fichier par fichier contre `git show b7337a3:<path>` → **18 identiques,
0 différent, 0 manquant, 0 en trop**, `rc=0`.

**ET DEUX CONTRÔLES POSITIFS**, parce qu'un zéro de différence ne vaut rien sans
eux : la même méthode rend `rc=1` contre l'ancienne révision, et `rc=1` sur **UN
SEUL OCTET** ajouté à `flux_llm.py`. Elle discrimine.

#### LE LOT RENVERSE LE PILOTE SUR DEUX CHIFFRES, ET LES DEUX SONT LA MÊME FAUTE

**Un instantané publié comme une propriété.**

- **« 27 commits derrière `main` » en valait 38** à sa lecture. Le 27 n'était pas
  faux : il avait vieilli de onze commits de registre entre sa mesure et sa
  relecture. **LA PROPRIÉTÉ EST `8209e68` ; LA DISTANCE PÉRIME.**
- **Les « 914 ko de contexte transféré » ne mesurent pas la taille du contexte.**
  Le clone pèse 2,0 Go hors `.git` et il n'existe aucun `.dockerignore` :
  BuildKit ne transfère que ce que les `COPY` réclament, puis incrémentalement.
  **Le lot ne l'a pas laissé en déduction, il l'a ÉPROUVÉ** sur un Dockerfile
  jetable ne portant qu'un `COPY requirements.txt` → **38 B transférés**.

#### LE FAUX POSITIF QUI AURAIT FAIT TOMBER L'OBJECTIF DU LOT

`make image` décide de `code.arbre` sur `git status --porcelain`, **QUI COMPTE
LES FICHIERS NON SUIVIS**. Or les arbres de travail de l'outillage de session
vivent sous `.claude/` : **le lot qui redéploie salit l'arbre par sa seule
présence**. L'image aurait gravé `arbre_sale`, donc `/health` aurait rendu « ne
pas comparer », donc **une campagne appariée refusée** — pour un arbre dont aucun
fichier suivi ne s'écartait de `HEAD`, et dont rien n'entre dans l'image
(`Dockerfile.agent` ne copie que `requirements.txt`, `src/agent` et `src/api`).

Le lot a contourné en local par `.git/info/exclude`, motif **étroit**, **retiré
immédiatement après et restauré au SHA-256** — avec un **contrôle positif posé
avant de construire** : un fichier témoin à la racine ressortait bien, donc le
garde mordait encore sur toute autre saleté.

Le remède **versionné** est `.gitignore`. **VÉRIFIÉ PAR LE PILOTE DANS LES QUATRE
SENS** sur le résultat de fusion :

| état de l'arbre | ce que la recette rend |
|---|---|
| tel quel | `propre` |
| + un arbre de travail sous `.claude/` | **`propre`** — le faux positif est éteint |
| + un fichier non suivi **ailleurs** | **`sale`** |
| + un fichier **SUIVI** modifié | **`sale`** |

**Le faux positif est éteint SANS que le garde soit désarmé.**

**La correction de fond — borner la sonde à `requirements.txt src/agent src/api`
— est PROPOSÉE ET NON FAITE**, parce qu'elle touche le `Makefile` et mérite son
lot avec son garde. C'est le bon jugement : on n'élargit pas un lot de
déploiement à une modification de la porte.

#### LA RÉSERVE DEVIENT UNE MESURE

`up --no-build` était **ÉCRIT, PAS ÉPROUVÉ** depuis le lot 22, et le document le
disait à son site. Mesuré, 13:40:12 → 13:40:15 UTC, `rc=0` :

| ce que la réserve demandait | la mesure |
|---|---|
| `--no-build` empêche-t-il de reconstruire ? | **OUI** — aucune étape de build, `latest` désigne la même image avant et après |
| `up` recrée-t-il le conteneur ? | **OUI, il le RECRÉE** — identifiant neuf, PID neuf, `RestartCount` remis à 0 |
| le conteneur sert-il l'image neuve ? | **OUI** |
| `frontend` est-il emporté par son `depends_on` ? | **NON** — même identifiant, même `StartedAt` de part et d'autre |

**Le retour arrière n'a pas eu lieu** — rien n'a mal tourné — et **sa composition
reste crue sur la documentation** : l'éprouver exigeait de casser le service qui
venait d'être réparé. Réserve **réduite, pas levée**, écrite comme telle.

#### La marge sur la carte, mesurée AVANT de couper

`nvidia-smi --query-compute-apps` croisé avec les cgroups — **l'attribution des
PID aux conteneurs est LUE, pas supposée**. `vllm-central` 14 264 MiB,
`ollama-central` 3 586, l'agent 1 468, **3 229 libres**. L'agent rend puis
redemande au plus son pic : marge de **2,2×**. **GO.**

Le seul scénario qui cassait exigeait que le voisin redémarre à
`--gpu-memory-utilization 0.76` dans la fenêtre. **Le lot a RELU sa valeur
courante au lieu de la supposer** — `0.55` — et a vérifié son `StartedAt` avant
et après : identique. *Le 27 de l'accord est un ACCORD, pas une propriété de la
carte, et cette ligne le montre appliqué.*

#### Le piège paresseux, rencontré deux fois et non pris pour une panne

À froid, `/health` rend `index_lexical: false` **et** `torch_device.embedding`
à `null` — les deux sont construits au premier usage. Le lot **n'a pas conclu à
une panne** : il a tranché **par la première recherche réelle**, et le
`lexical_ms: 478` de la réponse le confirme. Après : les quatre sondes à `true`,
`cuda:0` des deux côtés, pic 1 074 MiB.

**Une réponse réelle a été servie** : HTTP 200 en 43,0 s, 1 770 caractères,
**six citations ancrées**, `dropped_contexts: 0`. Un `/health` vert n'est pas une
réponse servie, et le lot ne s'en est pas contenté.

#### Les faux résultats du lot contre lui-même

- **IL A ÉCRIT SA CONCLUSION DANS LA COMMANDE.** Son
  `echo "(aucune ligne ci-dessus = aucun téléchargement)"` s'exécutait **quoi
  qu'il arrive**, et s'est affiché **sous dix lignes de requêtes**. *Une phrase
  qui s'imprime sans condition n'est pas une mesure.* Corrigé en faisant
  **compter** la sonde, puis doublé d'un contrôle positif.
- **Quinze fichiers « en trop » dans le conteneur** qui étaient des
  `__pycache__` écrits à l'import — comptés à part plutôt que passés sous
  silence.
- **Sa sonde d'attribution s'est attrapée elle-même deux fois**, dont sur un
  commit qui **cite** la signature interdite pour prouver que le hook tire.
- **Son premier réflexe a été de lire le prompt comme à jour** : les deux
  chiffres périmés ont survécu à sa première lecture.


### 4.60 → LOT-25 : l'interrupteur du dialecte, et le défaut qui ne bouge pas d'un octet

**Lot 7 du découpage vLLM, et le dernier avant la campagne appariée.** Il ne
bascule RIEN en service : `LLM_ENGINE` vaut `ollama` par défaut, aucun conteneur
n'a été redémarré, `.env` et `.env.example` sont hors du diff. Il pose
l'interrupteur ; personne ne l'actionne ici.

#### Ce que le lot a trouvé et qui renverse le cadrage

**LA CHARGE D'OLLAMA ENVOYÉE À vLLM N'ÉCHOUE PAS — ELLE EST ACCEPTÉE ET
IGNORÉE.** Le cadrage annonçait que les deux appels non-flux « échoueraient
bruyamment mais ailleurs ». `mesuré` le 16 septembre 2026 à 14:12 UTC sur
`vllm-central`, quatre requêtes en lecture :

| requête | charge | résultat |
|---|---|---|
| V2 | `{"think":false,"options":{…,"num_predict":120}}` | **HTTP 200**, `finish_reason=stop` |
| V4 | `{"options":{"num_predict":5}}` | **HTTP 200**, `finish_reason=stop`, **77** tokens générés |
| V3 | `{"max_tokens":5}` *(contrôle positif)* | HTTP 200, `finish_reason=length`, **5** tokens |

`options`, `num_predict`, `num_ctx` et `think` passent sans erreur, sans
avertissement, sans journal. Un lot qui n'aurait basculé que le CHEMIN aurait
donc généré à la température et au plafond par défaut du serveur, et rien ne
l'aurait dit. **Le défaut est pire que celui qui était annoncé, et il est
silencieux.**

**UN QUATRIÈME POSTE, ABSENT DU CADRAGE ET EN LECTURE.** Les trois postes
d'ÉCRITURE étaient bien relevés. Mais `llm._contenu_message`, qui lit les DEUX
réponses non-flux, ne connaissait que `message.content` à la racine — le
dialecte d'Ollama. vLLM écrit `choices[0].message.content` hors flux (`mesuré`
14:12 UTC). Sous vLLM, la réécriture de question et la traduction seraient
tombées sur leur repli — « question d'origine conservée », « recherche
monolingue » — **en HTTP 200, sur une réponse parfaitement valide**, avec un
journal qui accuse le serveur. La recherche aurait été dégradée dans les deux
langues sans qu'aucune erreur ne paraisse.

**`LLM_THINKING=true` SOUS vLLM N'EST PAS EXPLOITABLE SUR CE SERVEUR**, qui n'a
pas de `--reasoning-parser` (`mesuré` 14:13 et 14:14 UTC, trois requêtes) :
hors flux, `content: null` ET `reasoning: null` pour **278** tokens facturés —
la réponse est perdue ; en flux, **659** caractères cédés commençant par
« thought\nThinking Process: » — le raisonnement brut part à l'écran. Aucune des
deux ne lève. Le module transmet le réglage fidèlement et **écrit la mesure au
site** plutôt que de corriger en douce : un réglage qui ment est pire qu'un
mauvais réglage.

#### Les décisions, et où elles sont écrites

| question | décision | site |
|---|---|---|
| `num_ctx` | **pas envoyé** à vLLM (aucun champ équivalent ; la fenêtre est fixée au lancement) ; reste le budget CLIENT — `context_budget_chars`, `fit_prompt`, la suspicion de troncature | `dialecte_llm._charge_vllm` (a) |
| nom du modèle | **deux réglages**, `OLLAMA_MODEL` et `VLLM_MODEL` : les deux noms sont **disjoints par mesure**, 404 dans les deux sens (14:14 UTC) | `settings.py` |
| lecture du réglage | **à chaque appel**, jamais mémorisée — le retour arrière EST le réglage, et ce chantier a déjà payé une mémorisation à vie | `dialecte_llm.dialecte_courant` |
| raisonnement | **par requête**, `chat_template_kwargs` — jamais un drapeau de lancement (bogue vLLM #39130 sur un serveur partagé) | `dialecte_llm._charge_vllm` (b) |
| décomptes | `stream_options.include_usage` **en flux seulement** ; `continuous_usage_stats` non demandé | `dialecte_llm._charge_vllm` (c) |
| `LLM_ENGINE` inconnu | **refusé au démarrage** par `Literal`, jamais rabattu en silence sur Ollama | `settings.py` |
| client HTTP | **non touché** — un par appel, dans son `async with` | `llm.generate_stream` |

#### Ce que la campagne de mutation a trouvé contre le lot

Témoin inerte à **zéro rouge** et **au compte attendu** à chacune des cinq
invocations. **Vingt-six mutations, vingt-trois mortes du premier coup, TROIS
SURVIVANTES**, et les trois ont produit une scène :

- **l'URL du poste de FLUX n'était exercée par rien.** Les deux postes non-flux
  l'étaient ; le poste de flux — celui qui sert CHAQUE réponse de l'agent — ne
  l'était pas. Remettre `{OLLAMA_HOST}/api/chat` en dur passait toute la suite ;
- **le réglage de raisonnement était mesuré sur un champ CONSTANT.**
  `thinking=settings.llm_thinking` remplacé par `thinking=False` survivait parce
  que `LLM_THINKING` vaut `False` par défaut : la règle était inversée là où le
  domaine mesuré ne pouvait pas la distinguer. Le texte séparateur est l'état
  `LLM_THINKING=true`, et il est désormais posé pour les deux dialectes ;
- **le modèle publié par `/health` était mesuré sur la même constante.**
  `ollama_model=dialecte_courant().modele` remplacé par `settings.ollama_model`
  survivait pour la raison exacte qui précède : sous le défaut les deux valent
  la même chose. Le seul état séparateur est la bascule, et il est posé.

**Ces trois survivantes disent la même chose du lot, et c'est la leçon à en
retenir : une campagne menée SOUS LE DÉFAUT ne peut pas mesurer ce qui ne varie
qu'à la bascule.** Chaque scène neuve porte donc les DEUX états, et non le seul
qui sert aujourd'hui.

#### Ce que ce lot NE ferme pas

- **aucune génération n'a été faite à travers le code du lot sous vLLM.** Les
  dix requêtes de mesure ont été passées à la main, par `curl` ; ce que le lot
  garde est la CHARGE et l'URL, pas une réponse de bout en bout sous
  `LLM_ENGINE=vllm`. C'est le poste de la campagne appariée qui suit.
- **l'empreinte de configuration ne porte pas `llm_engine`.** Ce qui sépare les
  deux moteurs dans `runs/` est la VALEUR du champ `ollama_model`. Elle suffit
  tant que les deux serveurs servent des modèles de noms différents, ce qui est
  mesuré aujourd'hui et n'est pas une propriété. Ajouter la clé aurait dégroupé
  rétroactivement toutes les campagnes déjà enregistrées.

#### Ce que l'AUDIT-25 ajoute à cette section, et ce que le pilote a vérifié

[`audits/2026-09-16-audit-lot-25.md`](audits/2026-09-16-audit-lot-25.md), versé
sur `main` en **`7e66291`** *avant* d'être cité. **AUCUNE BLOQUANTE.**

**LE PILOTE S'ÉTAIT TROMPÉ, ET IL L'A REMESURÉ.** Le prompt du lot disait que la
charge d'Ollama envoyée à vLLM « échouerait bruyamment mais ailleurs ». `mesuré`
par le pilote le **16 septembre 2026 à 15:42 UTC**, deux prompts distincts :

| charge postée à `vllm-central` | HTTP | `finish_reason` | tokens générés |
|---|---|---|---|
| `{"options": {"num_predict": 5, "num_ctx": 8192}}` | **200** | `stop` | **42** |
| `{"max_tokens": 5}` *(contrôle positif)* | **200** | `length` | **5** |

**LE BORNAGE EST ACCEPTÉ ET IGNORÉ EN SILENCE**, et le contrôle positif prouve
que le serveur *sait* borner — donc que la sonde discrimine. **C'est la troisième
instance du motif du §12 : affirmer un comportement non mesuré**, ici celui d'un
serveur tiers. Le lot avait raison ; c'est cette mesure qui fonde l'architecture
retenue — **le chemin et la forme se décident au même endroit**.

**L'ANGLE QUI MANQUAIT À TOUT LE CHANTIER EST FERMÉ.** Le lot avouait, *dans un
fichier versionné*, qu'aucune génération de bout en bout n'avait été faite sous
`LLM_ENGINE=vllm`. L'auditeur l'a faite : **en flux, hors flux, avec appel
d'outil, sur les DEUX moteurs**, décomptes présents, **citation `[src:…]`
produite**, raisons de fin relevées, aucune réponse tronquée. **Et il a monté
l'agent COMPLET** sur un port à lui : `services.ollama: true` **contre un serveur
vLLM**, **six requêtes vers `:8100` et ZÉRO vers `:11434`** — la bascule est
**étanche au niveau du service entier**.

**LE DÉFAUT, ÉPROUVÉ PLUS DUREMENT QUE PAR LE LOT.** Le lot comparait ses charges
à des **littéraux recopiés** — or *un garde de COPIE CONFORME est vert sur deux
exemplaires tous deux faux*, et ce dépôt l'a déjà payé au lot 19. L'auditeur a
comparé au **comportement d'exécution de `main`** : `httpx` intercepté dans les
deux arbres, ce que chacun **poste réellement** capturé, **ordre d'insertion
compris** — **SHA-256 identique, 3 POST sur 3**, avec contrôle positif.

**LE QUATRIÈME POSTE, CONFIRMÉ CONTRE LE SERVEUR RÉEL.** Le corps non-flux de
`vllm-central` ne porte **aucune clé `message`** : sur ce **même corps**, le
lecteur de `main` rend une chaîne **VIDE**, celui du lot **195 caractères**. La
panne aurait été **muette**.

##### Les sept non bloquantes

1. **`documentation/tests.md` annonce 26 là où il y en a 30, ET SE CONTREDIT DEUX
   LIGNES PLUS BAS.** Le garde du compte mord sur les deux chiffres du total mais
   **ne regarde pas l'arithmétique interne de la parenthèse** — mutation du total
   rouge, mutation du 26 verte. *Vraisemblablement le nombre de MUTATIONS recopié
   à la place du nombre de TESTS.*
2. **Trois champs de `_sonder_moteur_llm` que rien ne garde À LA BASCULE**, avec
   leurs séparateurs construits : l'hôte interrogé, le modèle demandé, le modèle
   confronté. **La plus coûteuse rend `modele_servi: None`**, donc un relevé
   incomplet, donc **non mémorisé** — et la sonde repart **à chaque battement de
   `/health`, jusqu'à trois requêtes par battement, vers le serveur PARTAGÉ de
   l'équipe voisine**. *En creux : `_releve_est_complet` tient toujours, et
   l'auditeur l'a vu refuser de figer un relevé partiel sous la mutation.*
3. **`/health` publie le modèle demandé à DEUX endroits, un seul gardé** : sous
   vLLM, une régression les ferait **diverger dans la même réponse**.
4. **`num_ctx` est indiscernable de sa constante sous le défaut** — le réglage
   vaut 8192 et les trois témoins comparent à 8192. Séparateur :
   `LLM_NUM_CTX=16384`.
5. **Deux scripts d'outillage hors du site unique**, préexistants, dont le repli
   est `except Exception: return None` : pointés vers un vLLM, **ils écarteraient
   des questions en silence**.
6. **Les trois clés neuves sont absentes de `.env.example`**, contrôle positif à
   l'appui : *le réglage existe et ne se voit pas là où on le cherche d'abord.*
7. **Deux lacunes PRÉEXISTANTES**, signalées **sans être imputées au lot** : le
   `read=None` du délai d'attente, que rien ne garde, et l'expurgation de
   l'endpoint publié, non gardée **à travers le relevé** — *dépôt public,
   `runs/*.json` versionné.*

##### Les faux résultats de l'auditeur, et deux comptent

- **Son « contrôle positif » A SURVÉCU**, le faisant conclure à tort qu'une
  fonction n'était pas exercée : **elle l'est, quinze fois**. *Un contrôle positif
  qui ne rougit pas n'invalide pas le code — il invalide le contrôle.*
- **Ses propres sondes, passées sur son propre rapport, l'ont attrapé** à faire
  entrer le préfixe d'outillage dans le dépôt. Expurgé, et la rédaction
  **déclarée** dans le document.
- **Il laisse CRU SUR PAROLE les 26 mutations du lot** : *le résultat est
  versionné, la liste ne l'est pas, donc rien n'est rejouable.* Il a monté sa
  propre campagne à la place — 19 mutations, témoin inerte à zéro **au compte
  attendu**, 7 survivantes toutes traitées.


---

### 4.61 → REPAR-26 : la table des champs du dialecte, et les sept non bloquantes du lot 25

**Mesures prises le 16 septembre 2026 entre 19:20 et 20:53 UTC**, `date -u`
relevé avant chaque bloc. Branche `repar-26-champs-du-dialecte`, partie de
`main` = `e55725c` (471 commits, remesuré). **Aucune bascule, aucun
redéploiement** : `LLM_ENGINE` reste `ollama`, l'image n'est pas reconstruite,
`rag-agent-api` n'est pas redémarré — `RestartCount=0` et
`StartedAt=2026-09-16T13:40:14Z` **identiques avant et après**, `code_servi.sha`
toujours `b7337a3`.

#### CE QUI A ÉTÉ FAIT DE LA CAUSE, ET C'EST L'ESSENTIEL DE CE LOT

Le lot 25 avait écrit : *« une campagne menée sous le défaut ne peut pas mesurer
ce qui ne varie qu'à la bascule »*. Son audit l'a retournée contre lui et a
trouvé **trois champs de plus**. Quatre des sept non bloquantes sont des
instances de ce seul problème.

**La réponse n'est pas sept rustines.** `tests/unit/test_champs_du_dialecte.py`
pose une **TABLE** — `_ATTENDU` — qui donne, pour **chaque** champ de
`MoteurLlmHealth` et pour **chacun des deux dialectes**, la valeur que le relevé
doit porter. Quatre gardes la tiennent, et c'est leur conjonction qui rend
l'oubli impossible :

1. **exhaustive** contre `MoteurLlmHealth.model_fields` — un champ neuf non
   classé rougit *(mutation M23 : 1 rouge)* ;
2. **paritaire** — les deux dialectes portent les mêmes clés ;
3. **séparante** — un champ portant la même valeur des deux côtés est REFUSÉ au
   niveau de la table, donc avant qu'une scène soit écrite. C'est le garde
   anti-« mesuré sous le défaut », et c'est l'erreur exacte que `num_ctx` avait
   payée *(mutation M21 : 2 rouges)* ;
4. **jouée** par une SEULE scène paramétrée sur (champ × dialecte).

**IL N'Y A RIEN À ÉCRIRE DEUX FOIS** : ajouter une ligne à la table ajoute deux
scènes. C'est la leçon du lot 19 — deux gardes qu'il faut penser à écrire tous
les deux divergeront — appliquée à la MESURE et non plus au seul code.

**Le double route par (hôte, chemin)** et non par le seul chemin : deux serveurs
à deux adresses, comme le poste en tient deux. `_ClientSimule` de
`test_moteur_llm.py` répond identiquement aux deux hôtes, et une sonde qui
interroge le mauvais y resterait invisible — c'est précisément ce qui laissait
vivre M09.

#### L'INVENTAIRE DES CHAMPS QUI DÉPENDENT DU DIALECTE

Relevé par balayage de `src/` sur `ollama_host|ollama_model|vllm_host|vllm_model|llm_engine`,
recoupé par les appelants de `dialecte_courant`. **Aucun `settings.ollama_*`
résiduel hors de `dialecte_llm.py`.**

| Champ du chemin de production | Gardé sous les DEUX dialectes ? |
|---|---|
| `dialecte.hote` — hôte interrogé par `_sonder_moteur_llm` | **oui, depuis ce lot** (était non) |
| `moteur_llm.modele_demande` | **oui, depuis ce lot** (était non) |
| `moteur_llm.modele_servi` (appariement) | **oui, depuis ce lot** (était non) |
| `moteur_llm.endpoint` (+ son expurgation) | **oui, depuis ce lot** (était non) |
| `moteur_llm.serveur`, `version`, `empreinte_du_modele`, `quantification`, `fenetre_servie` | **oui, depuis ce lot** — relevés du serveur, et la bascule change le serveur joint |
| `moteur_llm.options` (5 réglages) | **oui, depuis ce lot**, et hors de leur valeur par défaut |
| `/health` racine `ollama_model` | oui (lot 25), **et son accord avec les deux autres sites depuis ce lot** |
| `usage.configuration()["ollama_model"]` | oui (lot 25), **et son accord depuis ce lot** |
| `url_chat` des trois postes de génération | oui (lot 25) |
| `url_sonde` (sonde booléenne) | oui (lot 25) |
| forme de la charge, `stream_options`, raisonnement | oui (lot 25) |
| `seed` et format contraint des deux scripts | **oui, depuis ce lot** (n'existaient pas au site unique) |

#### LA CAMPAGNE, ÉCRITE POUR ÊTRE REJOUÉE

*Le lot 25 avait livré 26 mutations dont la liste n'était nulle part, et son
auditeur a dû monter la sienne. Celle-ci est écrite.*

**Harnais** : posé hors de l'arbre, une mutation par invocation, jamais en fond.
Six gardes — porcelaine testée SUR LA CHAÎNE avant, unicité de l'ancre par
comptage d'**occurrences exactes** (jamais par lignes, jamais par numéro de
ligne), SHA-256 avant/après (sha inchangé ⇒ mutation **INERTE**, abandonnée),
contrôle de **chargement** des quatre modules (une mutation qui casse l'import ne
mesure aucun garde), `pytest` lancé **depuis l'arbre** avec le `rc` du programme
nommé (`pytest` rend 1, pas `make` qui rend 2), puis restauration, SHA-256
recontrôlé égal à l'avant et porcelaine revue sur la chaîne.

**TÉMOIN INERTE** : un commentaire seul au-dessus de `dialecte_courant`.
SHA-256 `2805efb9…` → `f1812c1f…` (le fichier a bien changé), `rc(pytest)=0`,
**1086 passés — le compte attendu**. Le harnais mesure donc l'arbre qu'il croit.

**Les mutations sont posées PAR MOTIF.** `rc` = celui de `pytest`.

| # | Cible | Ce qu'elle change | avant | après | Ce qui meurt |
|---|---|---|---|---|---|
| M09 | `main.py` | `hote = dialecte.hote` → `settings.ollama_host` | **0** | **6** | `test_chaque_champ_du_releve_suit_le_dialecte[…-vllm]` (5) + `test_la_sonde_n_interroge_que_l_hote_du_dialecte[vllm]` |
| M10 | `main.py` | `modele_demande=dialecte.modele` → `settings.ollama_model` | **0** | **3** | `…suit_le_dialecte[modele_demande-vllm]`, `…[modele_servi-vllm]`, `test_les_trois_sites_du_modele_demande_s_accordent[vllm]` |
| M12 | `main.py` | appariement `/v1/models` sur `settings.ollama_model` | **0** | **2** | `…suit_le_dialecte[modele_servi-vllm]`, `test_les_trois_sites…[vllm]` |
| M15 | `main.py` | appariement `/api/tags` sur `settings.ollama_model` | **0** | **2** | `test_une_mesconfiguration_ne_se_rattrape_pas_sur_l_autre_reglage`, `test_le_releve_partiel_n_est_toujours_pas_memorise` |
| M16 | `main.py` | `endpoint=_endpoint_expurge(hote)` → `hote` | **0** | **1** | `test_l_endpoint_publie_reste_expurge_a_travers_le_releve` |
| M01 | `dialecte_llm.py` | `num_ctx: settings.llm_num_ctx` → `8192` | **0** | **1** | `test_la_fenetre_demandee_a_ollama_est_le_reglage_et_non_huit_mille_cent_quatre_vingt_douze` |
| M03 | `llm.py` | `Timeout(30.0, read=None)` → `read=30.0` | **0** | **1** | `test_le_delai_de_lecture_du_flux_n_est_pas_borne` |
| M18 | `tests.md` | `les **N** de plus` → `les **99** de plus` | **0** | **1** | `test_l_arithmetique_interne_de_la_note_est_juste` |
| M06 | `main.py` | `/health` `ollama_model` → `settings.ollama_model` *(contrôle positif)* | **1** | **2** | `test_les_trois_sites…[vllm]`, `test_health_publie_le_modele_du_moteur_courant` |
| M19 | `.env.example` | `LLM_ENGINE` mis en commentaire | — | **1** | `test_tout_reglage_du_code_est_nomme_dans_le_fichier_d_exemple` |
| M24 | `.env.example` | `VLLM_MODEL` mis en commentaire | — | **1** | idem |
| M20 | `tests.md` | part du fichier neuf `38` → `12` | — | **0 PUIS 1** | **SURVIVANTE, voir ci-dessous** |
| M21 | `test_champs_du_dialecte.py` | `fenetre_servie` vLLM ramenée à celle d'Ollama | — | **2** | `…suit_le_dialecte[fenetre_servie-vllm]`, `test_la_table_separe_reellement_les_deux_dialectes` |
| M22 | `test_champs_du_dialecte.py` | valeur d'épreuve `llm_num_ctx` ramenée au défaut | — | **1** | `test_aucune_valeur_d_epreuve_n_est_la_valeur_par_defaut` |
| M23 | `schemas.py` | un champ NEUF ajouté à `MoteurLlmHealth` | — | **1** | `test_la_table_couvre_tous_les_champs_du_releve` |
| M25 | `generate_golden.py` | retour à `response.json()["message"]["content"]` | — | **1** | `test_la_graine_atteint_la_charge_reellement_postee[vllm]` |

**16 mutations posées, 15 mordantes du premier coup, UNE survivante.** Toutes
ont passé le contrôle de chargement : aucune ne mesure une panne d'import.

##### LA SURVIVANTE, ET ELLE A TROUVÉ UN DÉFAUT DANS LE GARDE QUI LA POSAIT

**M20 a survécu**, et la cause n'était pas le code : `_MOTIF_DU_FICHIER_NEUF`
portait une **espace littérale** entre `**N**` et `dans`, or la note passe à la
ligne exactement là. Le motif ne trouvait donc **rien** sur la page du dépôt, le
garde retournait sans mesurer, et une part annoncée à 12 pour 38 collectés
restait **VERTE**. *C'est la forme de défaut que ce chantier poursuit depuis dix
audits, et elle était dans le garde qui la poursuit.* Corrigé, M20 rejouée :
**1 rouge**. Deux gardes ferment le silence — une mention de fichier neuf que la
lecture ne sait pas extraire est désormais un ROUGE, et le témoin inerte exige
que la part de la page réelle soit lisible.

#### LES SEPT NON BLOQUANTES, ET CE QUI LES FERME

- **NB-2** — les trois champs de `_sonder_moteur_llm` sont gardés sous les deux
  dialectes (M09, M10, M12). La **mésconfiguration** que l'audit avait seulement
  *raisonnée* est désormais **jouée** (M15). `_releve_est_complet` n'est pas
  touché et il est **prouvé encore debout après ce lot**.
- **NB-6** — `LLM_ENGINE`, `VLLM_HOST`, `VLLM_MODEL` entrent dans
  `.env.example`, avec `TORCH_MAX_CONCURRENCY` qui manquait depuis plus
  longtemps. La correspondance `Settings`/`.env.example` est gardée **dans les
  deux sens et SANS EXEMPTION** — `mesuré` : les deux ensembles se recouvrent
  exactement, 57 alias contre 57 clés. *Une liste d'exemptions se remplit ; la
  première dispense en appelle une seconde.* **Aucune valeur du `.env` réel n'est
  recopiée** : les valeurs écrites sont les **défauts des champs**, déjà
  versionnés dans `settings.py`. Le défaut connu de `TORCH_DEVICE` n'est **pas**
  touché.
- **NB-3** — les **TROIS** sites qui publient le modèle demandé sont confrontés
  **dans le même état**, sous les deux dialectes. *Le champ n'est pas supprimé*,
  et le choix est mesuré : `ollama_model` de `/health` est listé comme clé du
  contrat dans `moteur_llm.md` ; `moteur_llm.modele_demande` est lu par
  `evaluate.py` (`_CHAMPS_DU_MOTEUR`) ; `usage.configuration()["ollama_model"]`
  est lu par une requête SQL **publiée** dans `capture_usage.md`. Supprimer l'un
  des trois est un changement de contrat envers des lecteurs hors dépôt, pour un
  gain qu'un garde d'accord donne sans le coût.
- **NB-4** — un réglage n'est plus éprouvé à sa valeur par défaut, et c'est
  gardé **en famille** : les cinq réglages publiés dans `moteur_llm.options` ont
  une valeur d'épreuve, un garde refuse qu'elle égale le défaut du champ
  (`Settings(_env_file=None)`, jamais le `.env` du poste), et un garde
  d'exhaustivité refuse qu'un réglage soit publié sans valeur d'épreuve.
- **NB-1** — `tests.md` annonçait **26** là où `pytest` en collecte **30**.
  L'arithmétique interne de la note est gardée, **ancrée sur la parenthèse de
  tête** (la page porte une dizaine de parenthèses de la même forme), et le
  compte du fichier neuf est **COLLECTÉ, pas déduit**.
  **UN SECOND CHIFFRE FAUX A ÉTÉ TROUVÉ ET CORRIGÉ**, que ni le lot ni son audit
  n'avaient vu : *« les quarante-huit de plus »* entre 954 et 999, quand la
  collecte sur les deux têtes (`04501f1` et `0a57787`, deux arbres détachés)
  rend **45 ajoutés et ZÉRO test disparu**, tous dans `test_identite_du_code.py`.
  La ventilation mesurée est 16/13/**10**/3/3, et le document annonçait 13 là où
  il y en a 10. *Le document confondait « ajoutés » et « de plus ».*
  **BORNE DU GARDE, ÉCRITE PLUTÔT QUE TUE** : il ne couvre que le maillon de
  tête. Vérifier les maillons plus anciens demanderait un arbre détaché par
  commit historique, ce qu'un test unitaire ne fait pas.
- **NB-5** — `generate_golden.py` et `sweep_retrieval.py` passent par le site
  unique. `Dialecte.charge` porte désormais `graine` et `format_json`, **traduits
  dans les deux dialectes** (`options.seed` contre `seed` à plat ;
  `format: "json"` contre `response_format`) : *un site unique qui ne porte pas
  toute la forme n'est pas unique, il est majoritaire.* Les deux sont **nuls sur
  le chemin qui sert**, donc la charge de production ne bouge pas d'un octet.
  Leur repli n'écarte plus rien en silence — les pannes absorbées sont comptées
  et imprimées **même à zéro**, *un compteur qui ne s'affiche qu'au-dessus de
  zéro ne se lit jamais comme « zéro »*. Un garde par **arbre syntaxique**
  (docstrings exclues, parce que trois commentaires du dépôt NOMMENT le défaut)
  refuse qu'un troisième poste réécrive le chemin en dur, avec son contrôle
  discriminant. **Changement de comportement assumé** : la fenêtre de
  `generate_golden` vient désormais de `LLM_NUM_CTX` et non d'un 8192 écrit au
  site ; poser `LLM_NUM_CTX=8192` reproduit à l'octet ce qu'il envoyait.
- **NB-7** — les deux lacunes préexistantes sont **fermées**, pas seulement
  signalées : l'expurgation de l'endpoint est gardée **à travers le relevé** (M16
  meurt), et le délai de lecture du flux est asserté non borné **sur l'objet
  réellement construit**, intercepté à la frontière `httpx` (M03 meurt). Ce
  dernier garde n'assert **aucun** des trois autres délais — les borner est une
  décision d'exploitation, et un garde qui épinglerait 30.0 rougirait sur un
  réglage légitime.

#### UN GARDE EXISTANT A ÉTÉ RÉÉCRIT, ET C'EST UNE TROUVAILLE CONTRE CE LOT

`test_la_graine_est_transmise_au_generateur_de_texte` lisait l'**arbre
syntaxique** et cherchait un `options` littéral portant `seed`. Il tenait la
bonne propriété par le mauvais moyen : le jour où le poste est passé par le site
unique, le dict littéral a disparu, la charge est restée juste, et **le garde
s'est mis à rougir sur du code sain**. *Un garde qui rougit sur du code sain est
retiré par le lot suivant, donc désarmé.* Il mesure désormais la charge
**réellement postée**, sous les deux dialectes — plus fort, parce qu'il ne dépend
d'aucune forme d'écriture et qu'il tient les deux places de la graine.

Et il manquait une moitié : le garde du site unique tient le CHEMIN posté, rien
ne tenait la **LECTURE**. Les deux doubles répondent maintenant dans le dialecte
du moteur éprouvé, et les deux postes sont assertés sur ce qu'ils **rendent**
(M25 meurt). `sweep_retrieval.traduire` n'avait aucun test : il en a deux.

#### LA PORTE, ET L'HYGIÈNE

| Grandeur | Valeur |
|---|---|
| `rc(make lint)` | **0** |
| `rc(make test)` | **0** |
| Tests | **1089 passés sur 51 fichiers**, somme par fichier et total `pytest` concordants |
| `git status --porcelain` | **chaîne vide**, testée SUR LA CHAÎNE |
| `type: ignore` | 3 → **3** |
| `xfail` | 0 → **0** |
| `pytest.skip` | 2 → **2** |
| `noqa` | 93 → **99**, recoupé fichier par fichier ; **les six ajouts sont justifiés AU SITE** (2 × `E402` pour des imports après `sys.path.insert`, 2 × `BLE001` pour des absorptions larges assumées ET DITES, 2 × `A002` pour le paramètre `json` imposé par `httpx.post`) |

#### CE QUI N'A PAS ÉTÉ MESURÉ, ET CE QUI RESTE OUVERT

- **Aucune génération réelle n'a été faite par ce lot** : il ne change aucune
  charge du chemin qui sert, et son audit a déjà mesuré la génération complète
  sous les deux moteurs. *Rien ici n'est éprouvé à travers l'agent servi*, qui
  exécute un code antérieur — c'est normal, et le redéploiement est le lot
  d'après.
- **Le séparateur réel de M03 n'est pas joué** : il faudrait un préfill de plus
  de trente secondes. Le garde assert la propriété sur l'objet construit, pas la
  génération lente.
- **Le tableau des fichiers de `tests.md` est PARTIEL** : il ne portait pas
  `test_dialecte_llm.py` (lot 25). La ligne de `test_champs_du_dialecte.py` est
  écrite ; celle du lot 25 **reste manquante**, et rien ne garde cet inventaire.
- **Les maillons anciens de la chaîne de relevés de `tests.md`** au-delà de
  954 → 999 n'ont pas été vérifiés.

---

### 4.62 → L'inventaire rendu au pipeline sur la bascule du stockage objet

`rag-ingestion-pipeline` remplace MinIO (AGPL-3.0) par SeaweedFS ou versitygw
(Apache-2.0). Le corpus sera **entièrement réingéré** : aucune donnée à migrer
de notre côté. Le champ `minio_url` **change de nom et de valeur**. Inventaire
rendu le 22 septembre 2026, `mesuré` contre `main` = `a848761` et contre l'agent
servi (`code_servi.sha` = `ba6a8f0`, l'écart entre les deux étant de la
documentation seule, `git diff --stat`).

**Le nom de champ externe est lu à 7 lignes, 6 fonctions, 3 fichiers, 2 sources**
(`git grep` sur `props.get|meta.get|row.get|minio_url AS|.minio_url !=`) :
graphe — `graph_context.py:262, 607, 608, 643, 844` ; ChromaDB —
`lexical.py:252`, `retriever.py:1572`.

**La source réelle des images est le graphe, pas ChromaDB.** `media_object_names()`
rend **212** objets ; sur les **4367** chunks de la collection, `minio_url` est
présent partout et **non vide sur 4** (balayage exhaustif, contrôle positif sur
`filename`).

**Un renommage ne rougirait nulle part, et la panne est plus large qu'annoncée.**
NebulaGraph ne lève pas sur une propriété inconnue : `RETURN` rend `None`,
`WHERE` rend **0 ligne** (contrôle positif : la vraie propriété rend 2 lignes).
Donc `media_object_names()` rendrait un ensemble **vide**, et comme
`RESTRICT_MEDIA_TO_GRAPH` vaut `true` en service, le proxy `/media` refuserait
**toutes** les images, pas seulement celles du champ perdu.

**Le SDK émet une opération S3 que notre source ne nomme pas.** Trace de
`Minio._url_open` sur un client neuf : `GET /documents?location=`
(*GetBucketLocation*) **avant** le `GetObject`. Le pipeline utilise le même SDK
`minio==7.2.20` : chez lui elle précède le premier `put_object`, donc une
passerelle qui ne la sert pas casse **l'ingestion**, pas l'affichage. Retenue
par le pipeline comme **premier critère éliminatoire** de son essai.

**La forme de l'URL est décodée par position, à deux endroits, avec deux règles
différentes** — `minio_client.object_name_from_url` (urlparse, retire le premier
segment) et `graph_context.media_object_names` (`split("/", 4)`, exige 5 parts).
Banc de sept formes exécuté sur le vrai code : seule
`scheme://host[:port]/<bucket>/<objet>` est correcte. Le virtual-host style et
un préfixe de passerelle sont décodés de façon **cohérente et fausse** ; un
chemin relatif ou une clé nue font **diverger** les deux décodeurs. Aucun des
sept cas ne lève.

**Ce que le pipeline a accordé**, écrit ici parce que le dépôt survit, pas la
conversation : `minio_url` → **`media_url`** (même forme path-style, garantie
maintenue) et un champ nouveau **`object_key`** portant la clé d'objet nue. Pas
de champ `bucket` : c'est un réglage, `documents`, que nous avons déjà. Le
principe retenu des deux côtés : **on ne nomme pas le produit dans le contrat** —
`seaweedfs_url` referait la même faute. `object_key` supprime nos deux décodeurs
positionnels, donc la totalité de notre exposition à la forme de l'URL.

**Ce qui reste à faire chez nous, et qui ne dépend pas de leur calendrier :**

- ~~**la garde qui morde.**~~ **FERMÉ par LOT-29**, `tests/` seul, `src/` non
  touché. La prévision est passée de `supposé` à `mesuré` : les sept sites
  renommés **ensemble**, la suite d'avant le lot rend **1084 passés, `rc=0`,
  avant comme après** — elle ne rougit nulle part. (`pytest tests/unit/` en
  ignorant les deux fichiers du lot, `mesuré` le 22 septembre 2026, base
  `38ac068`, `rc` relevé en variable.) Deux fichiers neufs :
  `tests/unit/test_contrat_champs_externes.py` déclare le contrat en **un seul
  endroit** et relève **par AST** — jamais par recherche de texte, jamais par
  numéro de ligne — les sept lectures, décrites **par motif** (module, fonction
  englobante, nature) ; le compte de sept est **calculé** depuis l'inventaire.
  `tests/unit/test_bascule_du_nom_de_champ_media.py` exerce le vrai code sur un
  **producteur** renommé — `_execute` pour le graphe, la collection pour
  ChromaDB — et cloue la conséquence : autorisation du proxy vide, aucune image,
  **aucune exception, aucun journal**. Quatorze mutations, **toutes tuées** ;
  la bascule des sept sites d'un coup fait rougir **11 gardes sur 20**. Témoin
  inerte : treize lignes insérées **en tête** de `graph_context.py` — tous les
  numéros décalés de 13 — laissent la suite verte **au compte attendu**.
  **DEUX BORNES RESTENT OUVERTES, et elles sont écrites plutôt que tues :**
  *(a)* le périmètre du relevé est `src/agent/` seul — `src/api/schemas.py` et
  `src/frontend/app.py` portent le même nom, mais c'est **notre** contrat de
  réponse, et le faire suivre le pipeline est une décision à prendre, pas un
  élargissement à faire en silence ; *(b)* à l'intérieur d'une requête nGQL, le
  nom de propriété est reconnu par un motif et non par une analyse syntaxique —
  nGQL n'est pas du Python, et aucune n'est disponible. Une **mutation
  survivante** a été trouvée et **fermée** en cours de lot : le contrôle positif
  du relevé ne portait aucun témoin de la nature `subscript`, de sorte qu'un
  site écrit `meta["minio_url"]` serait resté invisible si le relevé perdait
  cette nature — `rc(pytest)=0`, 18 passés sous la double mutation. Le contrôle
  porte désormais sur les **trois** natures, sur un fragment **synthétique**, et
  une garde exige qu'aucune nature de l'inventaire ne reste sans témoin ;
- **`/health` ne sonde pas le stockage objet.** `services` vaut
  `{chromadb, nebulagraph, index_lexical, llm}` ; `main.py:1178-1187` ne
  construit aucun `minio_ping`. Une panne du stockage laisse la santé **verte**,
  ce qui prive la bascule de son témoin le plus évident ;
- **l'alphabet des chemins d'objets.** `_OBJECT_NAME_RE = ^[\w\-./]+$`
  (`minio_client.py:13`) : ni espace, ni `%`, ni `+`, ni `:`, ni parenthèse. Le
  pipeline s'engage à ne pas changer la normalisation à la réingestion.

**La réserve 3 du pipeline sur `sequence` est déjà fermée chez nous**, et
`mesuré` : le voisin est trouvé par `ORDER BY … LIMIT` (`graph_context.py:343`)
et le découpage est **positionnel** — `rows[-budget:]` / `rows[:budget]`,
docstring à `graph_context.py:918-922`. Aucune fenêtre par **valeur** de
`sequence` n'existe dans `src/` (contrôle : `sequence [<>]=` → aucune ligne).

**L'exigence 5 est prouvée de notre moitié** : `POST /reindex` → HTTP **200**,
`{"chunks_indexed":4367,"stale":false}`, 0,43 s, contrôle négatif à **404** sur
une route voisine, et `4367` recoupe `collection.count()` **et** le compte
mesuré indépendamment par le pipeline. L'autre moitié — *le pipeline l'appelle
en fin d'ingestion* — se lit dans leur historique Dagster, qu'ils dépouillent.

**La mesure que le pipeline a demandée sur l'alphabet des clés, rendue le
22 septembre 2026 à 14:51 UTC contre le graphe et le stockage en service.**
Le pipeline soupçonnait qu'un de ses deux constructeurs de clés n'assainissait
pas le radical du document, et que des images de notre production étaient déjà
en 404 silencieux. **Réponse : ZÉRO sur 212**, et le cas précis qu'il craignait
existe et est propre.

- `media_object_names()` rend **212** clés distinctes. Le graphe porte **212**
  URLs brutes non vides, **toutes** retenues par le `split("/", 4)` : rien n'est
  écarté en amont, donc le 212 n'est pas un reste.
- **0** des 212 échoue à `_OBJECT_NAME_RE` (`^[\w\-./]+$`), et **0** porte un
  caractère non-ASCII. Contrôle positif de la sonde : un espace, une parenthèse
  et un `U+FF1A` sont **rejetés**, une clé propre est acceptée.
- **Bout en bout : 212 servies, 0 échouée** par `get_object_bytes`. Contrôle
  positif : une clé absente rend `None`.
- **La bonne fonction n'était pas `is_allowed`.** Elle teste l'appartenance à
  l'ensemble tiré du graphe : les 212 y sont **par construction**, donc son
  échec est trivialement 0 et ne mesure rien. Le garde qui mord est
  `_OBJECT_NAME_RE` dans `get_object_bytes` (`minio_client.py:85`).
- **Le cas redouté a été rencontré, pas évité.** Le corpus contient bien
  « 4. Model Serving：… », avec le deux-points pleine chasse, dans **2** des 45
  valeurs de `filename`/`source_path` ; et **42** de ces 45 portent un caractère
  hors alphabet. Ce chapitre porte **8** images, et leurs clés sont propres :
  `…/4_Model_Serving_Architectures_and_Implementation/img_000N.png`. La
  normalisation a donc bien opéré sur ce chemin.
- **Et le chemin qui produit 199 des 212 clés n'est aucun des deux que le
  pipeline a cités** : la forme est `images/html/htms/<doc>/<chapitre>/img_NNNN.png`,
  **6 segments**, contre 13 clés seulement pour la forme du livre PDF.

**CETTE MESURE EST UN INSTANTANÉ, PAS UNE PROPRIÉTÉ**, et c'est la seule chose
qui reste ouverte : rien, ni chez eux ni chez nous, ne garantit que la prochaine
ingestion produira des clés dans notre alphabet. La garde du lot suivant doit
donc couvrir l'alphabet des clés en plus du nom de champ.

**L'empreinte de référence, posée le 22 septembre 2026 à 15:09 UTC.** Le
pipeline nous a appris que ses clés sortent de **trois** constructeurs et non
deux (celui qu'il avait cité en premier en produit **zéro** : sa source est
déclarée mais son répertoire n'existe pas), et surtout que **deux fonctions
d'assainissement divergent chez lui sur le traitement du point**. Unifier ces
deux fonctions **déplace ou non 199 de nos 212 clés**, et après la réingestion
un déplacement de clés serait **indiscernable d'un défaut de la nouvelle
passerelle**. Nous avons donc versé l'état d'avant :
`documentation/references/2026-09-22-cles-medias.md`, 212 clés et leur SHA-256
`c91f5be6…`. Mesure annexe du même relevé : **0** clé porte un point hors de son
dernier segment — cohérent avec la variante qui remplace le point, **et cette
sonde ne départage que les 199 clés du chemin HTML**, le radical du seul PDF du
corpus n'en contenant aucun.

**Le trou que le pipeline a trouvé et qu'il ferme chez lui :** un de ses trois
constructeurs n'assainit rien et prend le radical du document brut. Nos 13 clés
issues de ce chemin sont propres **par chance**, le seul PDF du corpus ayant un
nom déjà conforme. **L'ajout d'un PDF est prévu chez eux** : un nom portant un
espace, une parenthèse ou un accent produirait une clé hors de notre alphabet et
notre proxy la refuserait en **404 silencieux**. Ils tiennent la propriété à la
source ; nous gardons l'alphabet dans le périmètre de notre garde, parce qu'un
garde des deux côtés d'un contrat n'est pas une redondance — c'est la seule
façon de savoir **lequel des deux a fauté**.

**L'invariant graphe ↔ bucket, `mesuré` le 22 septembre 2026 à 15:19 UTC, et il
tient.** Le pipeline allait le mesurer de son côté ; nous l'avons fait du nôtre
pour lui épargner un tour. Le bucket contient **212** objets, **tous** sous
`images/`. Les deux ensembles sont **égaux** — 0 orphelin, 0 référence morte,
dans les deux sens — et leurs SHA-256 coïncident sur `c91f5be6…`. Trois
contrôles positifs doublent la recette (un retrait change l'empreinte, un ajout
la change, l'identité la conserve), parce qu'un « même SHA » non doublé peut
n'être qu'un défaut de recette. Détail au site :
`documentation/references/2026-09-22-cles-medias.md`.

**Les droits S3 : la lecture seule ne nous coûte rien, à deux conditions
nommées.** Le pipeline pose comme critère d'essai de sa passerelle la délivrance
de deux jeux d'identifiants aux droits distincts — écriture pour l'ingestion,
**lecture seule pour l'agent** — et demande si cela nous coûte quelque chose. La
réponse est non, et elle est `mesurée` le 22 septembre 2026 sur `2010dbe` :

- **aucune écriture S3 nulle part.** `git grep` de `put_object|remove_object|make_bucket|presigned`
  sur `src/`, `tests/` et `scripts/` → aucun appel. Le seul appel de production
  est `get_object` (`minio_client.py:96`) ;
- **aucun test ne parle à un endpoint réel** : les neuf sites de `test_resilience.py`
  et `test_securite.py` remplacent tous `_get_minio_client` par un double.

**CONDITION 1 — `GetBucketLocation` doit être dans la politique.** Le SDK
l'émet une fois par client avant tout `GetObject` (§4.62). Une politique
« GetObject seulement » nous coupe au premier téléchargement.

**CONDITION 2 — `ListBucket` doit y rester.** C'est l'opération qui produit
l'empreinte du bucket, donc le contrôle d'invariant que les deux dépôts viennent
d'accepter comme référence d'avant-bascule. Sans elle, ce contrôle devient
inexécutable de notre côté le jour précis où il sert.

**ET LA RAISON POUR LAQUELLE IL FAUDRA TESTER LES IDENTIFIANTS EXPLICITEMENT :**
`get_object_bytes` absorbe largement et rend `None`. Un identifiant refusé se
présenterait donc comme une **image manquante**, pas comme une erreur
d'authentification — un HTTP 403 remonterait en **404 silencieux**. C'est la
même famille que le reste de ce dossier : un défaut qui répond ment. La sonde de
stockage absente de `/health` reste la dette qui priverait la bascule de son
témoin.

---

### 4.63 → Dix tests héritent de la fenêtre du poste, et c'est mon élargissement qui les a cassés

`mesuré` le 22 septembre 2026 à 16:0x UTC sur `main` = `0e4d3b5`, depuis le
**clone principal**, seul arbre à porter un `.env`.

| commande | `rc` (`make`) | résultat |
|---|---|---|
| `make test` avec le `.env` du poste (`LLM_NUM_CTX=32768`) | **2** | **10 échecs**, 1094 passés |
| `LLM_NUM_CTX=8192 make test`, contrôle positif | **0** | **1104 passés** |

La variable seule fait basculer le verdict. Quatre fichiers touchés :
`test_llm_budget.py`, `test_answer_endpoint.py`, `test_precision_contexte.py`,
`test_capture_branchement.py`. Le message est explicite : `assert 0 > 0`, « le
cas de test ne provoque aucune mise à l'écart ».

**LA CAUSE EST MON GESTE, ET LE DÉFAUT EST DANS LES TESTS.** J'ai porté
`LLM_NUM_CTX` de 8192 à 32768 le 22 septembre. Ces dix scènes construisent un
budget qui *doit* écarter des sources pour avoir un sujet ; elles **héritaient**
du plafond de 8192 au lieu de le **poser**. La fenêtre élargie ne les fait pas
échouer : elle les prive de leur sujet. C'est le motif déjà consigné — *un test
qui hérite d'un défaut change de sujet le jour où le défaut change*.

**POURQUOI PERSONNE NE L'A VU PENDANT DEUX JOURS, ET C'EST LA VRAIE LEÇON.**
Les lots et le pilote mesurent dans des **arbres détachés**, qui n'ont pas de
`.env` : la porte y est verte à 1104, et elle l'est légitimement. Le seul arbre
qui porte la configuration réelle est le clone principal, et **la porte n'y avait
plus été lancée depuis le changement**. `LE POSTE N'EST PAS L'ARBRE` : une porte
verte en arbre détaché ne dit rien de la porte du poste, et l'écart entre les
deux est exactement la surface où un réglage peut casser sans bruit.

**Ce que la réparation doit faire** : que chaque scène **pose** la fenêtre
qu'elle mesure, par `monkeypatch` du réglage, et non qu'elle la subisse — en se
souvenant que `monkeypatch.undo()` annule **aussi** ce qu'une fixture a posé. Le
verdict devra être **indépendant de `LLM_NUM_CTX`**, et cela se prouve en
lançant la suite sous **deux** valeurs opposées, pas une.

**Non traité ici** : rien ne garde l'invariant « la porte est verte avec le
`.env` du poste ». C'est la dette que ce constat laisse ouverte.

**FERMÉ PAR LOT-30, ET LA DETTE AVEC** — §4.64. Les onze scènes posent la
fenêtre qu'elles mesurent, et `tests/unit/test_fenetre_heritee.py` tient
l'invariant. **Onze, et non dix** : le compte de ce constat est juste pour la
manière dont le poste pose la valeur — par le FICHIER `.env` —, et une onzième
scène apparaît quand on la pose par une VARIABLE D'ENVIRONNEMENT. Voir §4.64.

### 4.64 → LOT-30 : onze scènes POSENT la fenêtre, et la garde qui manquait mord

`mesuré` le 22 septembre 2026 entre 16:00 et 16:35 UTC, sur `main` = `651940f`,
depuis un arbre de travail — donc **sans `.env`**, la valeur étant posée dans
l'**environnement** de chaque lancement. Le `.env` n'a été ni lu, ni copié, ni
modifié.

| commande | `rc` | bilan |
|---|---|---|
| `LLM_NUM_CTX=32768 make test` **avant** | **2** (`make`) | **11 échecs**, 1 093 passés |
| `LLM_NUM_CTX=8192 make test` **avant** | **0** (`make`) | 1 104 passés |
| `LLM_NUM_CTX=8192 make lint` **après** | **0** (`make`) | — |
| `LLM_NUM_CTX=8192 make test` **après** | **0** (`make`) | **1 109 passés** |
| `LLM_NUM_CTX=32768 make lint` **après** | **0** (`make`) | — |
| `LLM_NUM_CTX=32768 make test` **après** | **0** (`make`) | **1 109 passés** |

**IL Y EN AVAIT ONZE, ET LA ONZIÈME DIT QUELQUE CHOSE DE PLUS.** Le §4.63 en
comptait dix sur quatre fichiers, et **c'est exact pour la manière dont le poste
pose la valeur** : par le fichier `.env`. La onzième,
`test_aucune_valeur_attendue_n_est_un_defaut`, ne se révèle que sous une
**variable d'environnement**, parce qu'elle reconstruit un `Settings` avec
`_env_file=None`. Cet argument neutralise le **fichier** ; il ne neutralise pas
l'**environnement**, dont `pydantic-settings` fait une source de priorité
**supérieure** — `mesuré` : un `.env` portant `LLM_NUM_CTX=32768` face à une
variable d'environnement à `8192` rend **8192**. Son jumeau
`test_aucune_valeur_d_epreuve_n_est_la_valeur_par_defaut` portait le même défaut,
**latent** : il aurait rougi sous `LLM_NUM_CTX=16384`, qui est sa propre valeur
d'épreuve. Les deux lisent désormais `_defauts_du_code`, qui retire de
l'environnement l'alias de chaque champ avant de construire. *Deux gardes
anti-« mesuré sous le défaut » héritaient eux-mêmes du défaut du poste.*

**CE QUE LA RÉPARATION A POSÉ.** `tests/unit/fenetre_du_prompt.py` est le site
canonique. Une **fonction**, pas une fixture `autouse` : une fixture rendrait le
réglage ambiant autrement, et `monkeypatch.undo()` annule **aussi** ce qu'une
fixture a posé. Les **trois** réglages dont dépend le budget — `LLM_NUM_CTX`,
`LLM_MAX_TOKENS`, `HISTORY_WINDOW_SHARE` — sont posés **ensemble** : les
refermer une variable à la fois est ce qui a produit ce lot. **Aucune des trois
valeurs posées n'est un défaut déclaré**, et c'est exigé plutôt que remarqué :
poser 8192 aurait rendu aux scènes leur sujet en les laissant vertes sous une
mutation qui écrirait `8192` en dur — NB-4, qu'une mutation survivante avait
déjà trouvé ici.

**UN LITTÉRAL EST TOMBÉ AU PASSAGE.** `test_capture_branchement` attendait
`soumises − écartées == 3`, vrai sous la seule fenêtre héritée. Il asserte
désormais la **relation** — ce que la colonne porte est ce que `fit_prompt` a
retenu — bornée aux **deux** bouts (`0 < écartées < soumises`) pour qu'elle ne
se vérifie pas à vide.

**LA GARDE, ET LES CINQ MUTATIONS QUI LA JUGENT.** `test_fenetre_heritee.py`
relance les onze scènes **par leurs identifiants** sous 8192, 16384 et 32768, en
sous-processus, et exige le même `rc` **et** le même compte — ce compte étant le
nombre de scènes gardées, jamais un chiffre écrit. Le sous-processus n'est pas
un confort : `settings` est construit à l'import, et deux des onze
reconstruisent un `Settings` ; par la même priorité de l'environnement sur le
fichier, la garde **reste mordante dans le clone principal**, seul arbre à
porter un `.env`. Toutes les mutations sont **du producteur**, restaurées par
SHA-256 confronté :

| mutation | garde attendue | ce qui a rougi |
|---|---|---|
| **témoin inerte** — la boucle de pose réécrite à l'identique | aucune | `rc(make)=0`, **1 109 passés**, le compte exact |
| une scène rendue à l'héritage (`test_llm_budget`) | la garde de fenêtre | `rc(make)=2`, **1 seul rouge sur 1 108 passés** : la garde, et elle seule |
| une scène rendue à l'héritage (`test_capture_branchement`) | la garde de fenêtre | `rc(pytest)=1`, la garde de fenêtre |
| la fenêtre posée redevient le défaut déclaré (8000 → 8192) | la garde anti-défaut | `rc(pytest)=1`, la garde anti-défaut **seule** |
| un champ posé est renommé (`llm_num_ctx` → `llm_ctx`) | la garde du champ | `rc(pytest)=1`, **trois** gardes |
| une scène gardée est renommée chez elle | la garde de fenêtre, par le compte | `rc(pytest)=1`, `ERROR: not found` nommant l'identifiant périmé |

**LA MUTATION QUI COMPTE EST LA DEUXIÈME**, et elle dit pourquoi cette garde
existe : la scène rendue à l'héritage **reste verte** dans son propre lancement,
puisque l'arbre détaché n'a pas de `.env` et hérite de 8192. Sans la garde, la
porte de cet arbre serait verte sur le défaut exact que ce lot referme. **C'est
la forme de défaut que §4.63 décrit, reproduite à volonté et attrapée.**

**CE QUI RESTE OUVERT, ET C'EST ÉCRIT PLUTÔT QUE SUPPOSÉ.**

1. La garde balaie **`LLM_NUM_CTX` et lui seul**. Le budget dépend aussi de
   `LLM_MAX_TOKENS` et de `HISTORY_WINDOW_SHARE` : `poser_la_fenetre` en
   affranchit les onze **par construction**, mais aucun lancement ne fait varier
   ces deux-là, et une scène **autre** que les onze pourrait en hériter sans que
   rien ne rougisse. **Borne écrite, non fermée.**
2. La garde tient les onze scènes **nommées**. Une scène neuve qui hériterait de
   la fenêtre ne s'y ajoute pas toute seule.
3. **Rien ne garde encore que la porte soit lancée dans le clone principal.** Ce
   lot rend le verdict des onze indépendant du réglage, donc il rend ces
   onze-là insensibles à l'écart entre les deux arbres ; il ne supprime pas
   l'écart. `LE POSTE N'EST PAS L'ARBRE` reste vrai pour tout le reste de la
   suite, et **aucune mesure de ce lot n'a été prise dans le clone principal**.
4. Quand un champ posé est renommé, la garde anti-défaut lève un `KeyError` au
   lieu d'asserter : le rouge est juste, sa lecture l'est moins. C'est la garde
   du champ qui porte le message, et elle rougit au même lancement.

---

### 4.65 → Où s'applique chaque k, et pourquoi la référence du pipeline ne décrit pas notre récupération

Le pipeline demande si `AUTO_SELECT_TOP_K` s'applique **avant** ou **après** la
récupération : sa campagne de référence du 2 septembre 2026 mesure le plancher
de rappel dense à k = 5, 10 et 20, et **le plus petit k jamais mesuré est 5**
quand nous en servons 3.

**RÉPONSE : APRÈS, ET DEUX ÉTAGES APRÈS.** `mesuré` au code le 22 septembre 2026
sur `main` = `f2187d7`, et recoupé par les valeurs effectives du conteneur servi.

| étage | réglage | valeur servie | site |
|---|---|---|---|
| requête dense et lexicale | `FETCH_K` | **50** | `retriever.py:1430, 1435` |
| fusion des classements | `RETRIEVAL_TOP_K` | **50** | `retriever.py:1412` |
| reranking | `RERANK_TOP_K` | **10** | `retriever.py:1651` |
| reconstruction des sections | `AUTO_SELECT_TOP_K` | **3** | `graph.py:204`, `ranking[:top_k]` |

`AUTO_SELECT_TOP_K` ne fixe donc **aucun** k de requête : il découpe le
classement **déjà reranqué**. **Notre k dense réel est 50**, dix fois le plus
petit de la référence et deux fois et demie le plus grand. Il suit que le
plancher mesuré par le pipeline **ne décrit pas notre récupération** — il la
sous-estime — et qu'**ajouter k=3 à leur campagne mesurerait une grandeur que
notre système n'emploie nulle part**. La mesure qui nous concerne est k=50.

**LA PERTE, S'IL Y EN A UNE, EST ENTRE 10 ET 3**, pas à la récupération : dix
passages franchissent le reranker, trois sections sont reconstruites. Ce n'est
pas le rappel qui est en cause, c'est la **sélection**, que personne ne mesure —
ni eux, ni nous.

**LEUR SECONDE RÉSERVE NE S'APPLIQUE PAS À NOTRE CHAÎNE, ET C'EST MESURÉ.** Ils
préviennent qu'une question encodée **sans** son historique fait tomber la
strate « de suivi » à 20 % contre 60 % avec. Chez nous la recherche part sur la
question **réécrite avec l'historique** : `graph.py:85` appelle
`rewrite_question(state["question"], state.get("chat_history"))` et `graph.py:91`
pose ce résultat en `search_query`. **Borne à dire honnêtement :** ce nœud ne
fait rien sans historique reçu, et l'historique est porté par le **client** — le
serveur est sans état. La réserve retomberait donc entièrement sur une première
question, ou sur un client qui ne renverrait pas `chat_history`.

**Ce que ce constat NE tranche pas :** que `AUTO_SELECT_TOP_K=3` soit trop bas
reste **non mesuré**. Le porter à 5 ou 6 et mesurer est proposé depuis le 22
septembre et **toujours pas joué**. Et leur avertissement vaut pour nous :
trente questions prouvent qu'une chaîne fonctionne, elles ne suffisent pas à
arbitrer un réglage — un écart de deux points y est du bruit.

---

### 4.66 → `AUTO_SELECT_TOP_K` : le coût de passer de 3 à 6 est mesuré, le gain ne l'est pas

`mesuré` le 22 septembre 2026 à 17:45 UTC contre l'agent servi (port 8011,
`code_servi.sha` = `ba6a8f0`), **sans rien redéployer et sans toucher au `.env`** :
`graph.py:204` lit `state["max_sources"]` **avant** le réglage, et
`max_sources` est un champ d'`AnswerRequest` borné 1..20 (`schemas.py:247`).
Six questions **distinctes** — un même prompt répété serait servi par le cache
de préfixe de vLLM — jouées à k=3 puis k=6.

| q | contextes | écartés | citations | `prompt_eval_count` | `total_ms` |
|---|---|---|---|---|---|
| 1 | 3 → 6 | 0 → 0 | 4 → 7 | 2267 → 4201 | 7 816 → 15 074 |
| 2 | 3 → 6 | 0 → 0 | 2 → 9 | 2646 → 4240 | 4 731 → 13 534 |
| 3 | 3 → 6 | 0 → 0 | 9 → 14 | 2940 → 4849 | 16 714 → 21 099 |
| 4 | 3 → 6 | 0 → 0 | 8 → 11 | 1942 → 4209 | 12 348 → 14 406 |
| 5 | 3 → 6 | 0 → 0 | 3 → 5 | 2448 → 4279 | 8 692 → 9 528 |
| 6 | 3 → 6 | 0 → 0 | 8 → 9 | 2247 → 4052 | 10 733 → 12 178 |

Médianes : prompt **2358 → 4224** tokens ; durée totale **9 712 → 13 970 ms**,
soit **+44 %**. Citations cumulées **34 → 55**, en hausse **6 fois sur 6**,
jamais en baisse. `prompt_tokens_reliable` vaut **`true`** aux douze appels : le
compte vient du serveur, ce n'est pas une estimation. **Contrôle positif : les
contextes valent exactement le k demandé aux douze appels**, donc le paramètre
gouverne bien l'étage visé.

**LE BUDGET N'ÉCARTE RIEN, NI À 3 NI À 6.** Le prompt le plus gros mesuré vaut
**4849** tokens contre une fenêtre servie de **32768** — **15 %**. Il aurait
même tenu sous l'ancienne valeur de 8192. C'est la troisième mesure à dire que
**l'élargissement de la fenêtre n'était pas le levier**, et que le plafond réel
du contexte est bien la **sélection**.

**CE QUI N'EST PAS MESURÉ, ET C'EST POURQUOI LE DÉFAUT N'EST PAS CHANGÉ.** Plus
de citations n'est pas une meilleure réponse : ce banc mesure un **coût**, pas
un **gain**. Arbitrer demanderait un jeu de questions à ancrages connus, et le
pipeline a écrit que sa campagne mesure la **récupération** et **jamais la
sélection** — elle ne pourra donc pas trancher ce réglage, quel que soit le k
qu'on y ajoute. Six questions ne tranchent rien non plus : leur propre
avertissement vaut ici — *trente questions prouvent qu'une chaîne fonctionne,
elles ne suffisent pas à arbitrer un réglage ; un écart de deux points est du
bruit*.

**Ce que le banc autorise à dire, et rien de plus :** le coût de passer à 6 est
**connu et modéré** — +44 % de latence, prompt à 15 % du plafond, aucune source
écartée. Rien dans le coût n'interdit le changement. **Le défaut reste à 3**
tant qu'aucune mesure de qualité ne le justifie, et la dette ouverte est le jeu
de référence à ancrages, pas le réglage.

---

### 4.67 → LOT-31 : le rappel APRÈS la sélection est mesuré, et l'instrument de réglage ne sait pas le mesurer

`mesuré` le **23 septembre 2026 de 08:01 à 08:10 UTC**, base `main` = **`cec564a`**,
dans un arbre de travail détaché. **`src/` n'est pas
touché** — `git diff HEAD -- src/` rend vide. Instruments :
`scripts/mesurer_selection.py` (sha256 `64fd8f6b…`),
`scripts/controle_perimetre_selection.py` (`e82394fa…`), recettes
`make mesurer-selection` et `make controle-perimetre-selection`. Bilans versionnés :
`runs/2026-09-23-selection-auto-select-top-k.json` et
`runs/2026-09-23-selection-controle-30.json`.

**AUCUNE RÉPONSE LLM N'A ÉTÉ GÉNÉRÉE.** Le banc rejoue `retrieve` → `rerank` →
`ranking[:k]` → `reconstruct_section` → `fit_prompt`, et lit les marqueurs
`[src:]` / `[img:]` du markdown **réellement soumis**. Seules les traductions de
questions passent par le moteur, et elles sont en cache.

#### Ce qui est mesuré, et sur quel dénominateur

**LE JEU N'EN PORTE PAS 138, IL EN PORTE 130**, et chacune **un seul** ancrage.
Le cadrage annonçait « 138 questions portant chacune ses `gold_element_ids` » :
`mesuré`, 138 questions, **130** avec ancrage, **130** ancrages, **une** seule
par question. Les deux grandeurs demandées — « combien d'ancrages survivent » et
« sur combien de questions au moins un survit » — **coïncident donc par
construction sur ce jeu**, et ne se distinguent que sur le jeu de contrôle, dont
les 26 questions portent **47** ancrages (1 à 3 chacune).

#### Le tableau, jeu de RÉGLAGE — 130 questions, 130 ancrages

| k | rappel au prompt | IC 95 % (Wilson) | questions | ancrages | rappel en graine | sections servies | éléments au prompt |
|---|---|---|---|---|---|---|---|
| **1** | 0,9231 | [0,864 – 0,958] | 120 | 120/130 | 0,9385 | 1,00 | 12,3 |
| **2** | 0,9538 | [0,903 – 0,979] | 124 | 124/130 | 0,9769 | 1,83 | 22,1 |
| **3** *(défaut)* | **0,9538** | [0,903 – 0,979] | **124** | 124/130 | 0,9769 | 2,66 | 32,4 |
| 4 | 0,9538 | [0,903 – 0,979] | 124 | 124/130 | 0,9769 | 3,42 | 41,4 |
| 5 | 0,9538 | [0,903 – 0,979] | 124 | 124/130 | 0,9769 | 4,22 | 50,6 |
| **6** | **0,9538** | [0,903 – 0,979] | **124** | 124/130 | 0,9769 | 5,06 | 61,2 |
| 8 | 0,9538 | [0,903 – 0,979] | 124 | 124/130 | 0,9769 | 6,64 | 80,6 |
| **10** | 0,9538 | [0,903 – 0,979] | 124 | 124/130 | 0,9769 | 8,23 | 99,7 |
| 20 | 0,9538 | [0,903 – 0,979] | 124 | 124/130 | 0,9769 | 8,23 | 99,7 |

**Bascules, et c'est par là qu'un écart se lit** — les questions sont appariées,
donc la différence des taux ne dit rien que le compte des questions qui ont
changé d'état ne dise mieux : k=1 → k=2 **+4 gagnées, 0 perdue** ; **toutes les
autres transitions : +0, −0**. **Passer de 3 à 6 ne gagne AUCUNE question, et
passer de 3 à 10 non plus.**

#### Le tableau, jeu de CONTRÔLE — 26 questions, 47 ancrages

| k | rappel au prompt | IC 95 % (Wilson) | questions | ancrages | rappel en graine |
|---|---|---|---|---|---|
| **1** | 0,6154 | [0,425 – 0,776] | 16 | 18/47 | 0,6538 |
| 2 | 0,6538 | [0,462 – 0,806] | 17 | 22/47 | 0,6923 |
| **3** *(défaut)* | **0,7308** | [0,539 – 0,863] | **19** | **26/47** | 0,7692 |
| 4 | 0,7308 | [0,539 – 0,863] | 19 | 26/47 | 0,8077 |
| 5 | 0,7692 | [0,580 – 0,890] | 20 | 28/47 | 0,8462 |
| **6** | **0,7692** | [0,580 – 0,890] | **20** | **28/47** | 0,8462 |
| 8 | 0,8077 | [0,621 – 0,915] | 21 | 31/47 | 0,8462 |
| **10** | 0,8077 | [0,621 – 0,915] | **21** | **33/47** | 0,8846 |
| 20 | 0,8077 | [0,621 – 0,915] | 21 | 33/47 | 0,8846 |

Bascules : 1→2 **+1**, 2→3 **+2**, 4→5 **+1**, 6→8 **+1**, **0 perdue partout**.
De **3 à 6** : **+1 question sur 26** et **+2 ancrages sur 47**. De **3 à 10** :
**+2 questions** et **+7 ancrages**.

**CE QUE CES DEUX ÉCARTS PÈSENT.** Une question sur 26 vaut 3,8 points, et la
réserve du jeu — *un écart de deux points est du bruit* — les couvre tous les
deux. Les intervalles de k=3 et k=10 se recouvrent largement. **Le signe, lui,
est constant** : sur les huit transitions des deux jeux, **aucune question et
aucun ancrage n'est jamais perdu** quand k monte. C'est tout ce que ce banc
autorise à dire, et ce n'est pas « 6 vaut mieux que 3 ».

#### LA TROUVAILLE : L'INSTRUMENT DE RÉGLAGE NE PEUT PAS MESURER CET ÉTAGE

Les deux jeux ne disent pas la même chose, et la raison est **mesurée** :

| rang du meilleur ancrage dans le classement reranqué | réglage (130) | contrôle (26) |
|---|---|---|
| ≤ 1 | **122** | 17 |
| ≤ 2 | 127 (+5) | 18 (+1) |
| ≤ 3 | 127 (**+0**) | 20 (+2) |
| ≤ 5 | 127 (**+0**) | 22 (+2) |
| ≤ 10 | 127 (**+0**) | 23 (+1) |

**Sur le jeu de réglage, AUCUN ancrage ne se trouve entre les rangs 3 et 10.**
Le reranker les place tous au rang 1 ou 2. La cause est dans la fabrication du
jeu, et son propre `_lisez_moi` la nomme : *la question a été écrite POUR le
passage*. Une question quasi paraphrase de son passage sort au rang 1, et la
question est réussie dès **une** section reconstruite. **Ce jeu est un
instrument de RÉCUPÉRATION ; il est aveugle à la SÉLECTION**, et son plateau à
k=2 ne dit pas « 3 suffit » — il dit « ce jeu ne teste pas k ».

Le jeu de contrôle, écrit à la main **après** l'ingestion et portant jusqu'à
trois ancrages dispersés, **teste** k — et il est **trop peu nombreux pour
arbitrer**, par sa propre réserve, qui n'est pas négociable.

**CONCLUSION, ET ELLE EST BORNÉE : le gain de passer de 3 à 6 reste NON
TRANCHÉ**, mais plus pour la raison écrite au §4.66. Elle est désormais
précise : **aucun des deux jeux n'est l'instrument de cette question.** Il en
faudrait un troisième — questions à ancrages MULTIPLES et DISPERSÉS, en nombre.
C'est la dette que ce lot ouvre, et elle remplace « mesurer le gain de k=6 »,
qui n'était pas jouable avec ce qu'on a.

#### Ce que le banc établit AUSSI, et qui ne dépendait pas du jeu

1. **`AUTO_SELECT_TOP_K` AU-DELÀ DE 10 EST INOPÉRANT.** k=10 et k=20 rendent
   **exactement** les mêmes chiffres sur les deux jeux — sections servies 8,23
   et 7,73, à l'unité près. La cause est `retriever.py:1651` : `rerank` ne rend
   que `RERANK_TOP_K` = **10** éléments, et `graph.py:204` découpe cette
   liste-là. Or `max_sources` est borné **1..20** (`schemas.py:247`) : **un
   appelant qui demande 20 sources en reçoit au plus 10**, sans qu'aucun message
   ne le dise. Ce n'est pas un défaut de sûreté ; c'est une promesse d'API que la
   chaîne ne peut pas tenir, et elle n'est écrite nulle part.
2. **LE BUDGET DE FENÊTRE N'ÉCARTE AUCUNE SECTION, À AUCUN k JUSQU'À 20.**
   `questions_avec_section_ecartee` vaut **0** pour les neuf valeurs, sur les
   **156** questions des deux jeux, sous `LLM_NUM_CTX` = 32768 relevé sur le
   conteneur servi. Le §4.66 l'avait mesuré sur **six** questions à k=3 et k=6 ;
   c'est étendu à 156 questions et jusqu'à k=20. **Le plafond du contexte n'est
   ni la fenêtre ni le budget** — c'est la sélection, et c'est la quatrième
   mesure à le dire.
3. **MESURER LA TRONCATURE DU CLASSEMENT SEULE AURAIT ÉTÉ FAUX, ET LE BANC LE
   CHIFFRE.** À k=3, le top-3 du classement porte **32,4** identifiants au
   prompt et non 3 : la reconstruction ramène la section entière. À k=10, **99,7**.
   Un banc qui aurait compté `ranking[:k]` aurait donc sous-estimé d'un facteur
   dix ce qui atteint le LLM. **Le coût de bien faire est nul** : retrieval,
   reranking et reconstruction ne dépendent pas de k, donc tout est calculé une
   fois par question et chaque k rejoue la seule troncature. Neuf valeurs de k
   sur 130 questions : **327,7 s au total, dont 36,9 s de reconstruction.**

#### Deux défauts trouvés en mesurant. AUCUN N'EST CORRIGÉ ICI — ce lot MESURE

**a. LA DÉDUPLICATION PAR SECTION PEUT ÉCARTER UN ANCRAGE CLASSÉ.**
`graph.py:213-221` saute une graine dont le `section_id` a déjà été vu. Mais
`reconstruct_section` **fenêtre** la section autour de **sa** graine
(`SectionContext.truncated`) : deux graines de la même section donnent deux
fenêtres **différentes**, et garder la première peut perdre l'élément de la
seconde. `mesuré` sur **G-053** : son ancrage est au **rang 2** du reranker, sa
section a été reconstruite au **rang 1** autour d'un autre élément avec
`truncated=True`, et **l'ancrage n'atteint le prompt à AUCUN k**. Même cas pour
**q18** du jeu de contrôle à partir de k=6. La déduplication suppose deux
reconstructions interchangeables ; elles ne le sont pas quand la section est
fenêtrée.

**b. DEUX ANCRAGES SUR 130 ONT LEUR TEXTE DANS CHROMADB ET RIEN DANS
NEBULAGRAPH.** `mesuré` le 23 septembre 2026 sur les 130 ancrages, tag par tag :
`1adfce548d` (**329** caractères dans ChromaDB, `text=''` dans NebulaGraph, tag
`ListItem`) et `842a8884da` (**367** / `''` / `ListItem`). Le retrieval les
trouve — ChromaDB a le texte — et la reconstruction rend un markdown où ils sont
**absents**, `_render_element` rendant `""` pour un élément sans texte. **Ce sont
G-112 et G-121, et elles sont perdues à TOUS les k** : elles ne disent rien de la
sélection. Répartition des ancrages par tag : `Paragraph` **104**, `ListItem`
**23**, `Caption` **3** ; les **2** muets sont des `ListItem`, les **21** autres
`ListItem` vont bien — **ce n'est donc pas systématique au tag**. **C'est une
divergence entre les deux stores, donc une trouvaille pour le PIPELINE**, à lui
rendre ; l'agent ne peut pas la réparer, il ne peut que la constater.

#### Comment cette mesure a été prouvée comme instrument

**CONTRÔLE POSITIF, DOUBLÉ ET DANS LES DEUX SENS.** À k=1 le rappel chute
(0,9231 contre 0,9538 sur le réglage ; **0,6154 contre 0,8077** sur le
contrôle) ; à k grand il monte (**+4** et **+5** questions). **Le banc distingue
donc bien k** — c'était la condition posée : un banc qui rendrait la même valeur
à k=1 et k=10 mesurerait autre chose.

**CONTRÔLE DE PÉRIMÈTRE, `rc=0`, sur QUATRE natures d'identifiants** — un
contrôle qui n'en échantillonne que deux laisse la troisième mourir en silence :
130 `gold_element_ids` en `^[a-f0-9]{10}$`, **119** du classement, **36** graines
de `SectionContext`, **402** lus dans les marqueurs `[src:]` et **10** dans les
`[img:]`, tous en forme ; **475** marqueurs rendant chacun **exactement un**
identifiant — `_ELEMENT_ID` n'est pas ancré et mordrait dans un identifiant plus
long ; **12/12** sondages où un ancrage est effectivement présent au prompt, sans
quoi un rappel nul ne dirait pas si la chaîne est cassée ou si les deux ensembles
ne se parlent pas. **Et la comparaison elle-même est éprouvée** : sur le témoin
`0026fa510a`, l'égalité exacte rejette les quatre leurres quand un `endswith` en
accepterait **deux** (`suffixe`, `englobant`). Si le test laxiste n'en acceptait
aucun, le contrôle ne prouverait rien et il le dirait.

**SEPT MUTATIONS DU PRODUCTEUR, SEPT ROUGES, toutes compilant.** Témoin inerte :
**11 passés** sur `test_mesure_de_la_selection.py`, **2 passés** sur la réserve.
Déduplication retirée → 6 rouges ; troncature retirée → 6 rouges *dont* le
contrôle « k=1 et k grand diffèrent » ; garde de graine manquante → 1 ; Wilson
remplacé par l'intervalle normal → 1 ; refus du cache non couvrant → 1 ; réserve
retirée du fichier → 1 ; producteur de la réserve divergent → 1. Chacune rougit
la garde qui la vise, et le SHA-256 du producteur revient à l'intact.

#### LE CACHE DE TRADUCTIONS ÉTAIT PÉRIMÉ, ET IL AVAIT LA BONNE TAILLE

`runs/.traductions.json` portait **130** entrées pour un jeu de **130**
questions, et l'intersection exacte de ses clés avec le jeu généré valait
**ZÉRO** — avec le jeu du pipeline aussi. Il vient d'un jeu antérieur. Sans le
refus posé au banc, la campagne aurait joué **toutes** ses questions sans
traduction, aurait déplacé le rappel translinguistique, et aurait conclu.
Le cache porte désormais **286** entrées et couvre les deux jeux ; les **156**
traductions ajoutées ont rendu **0** panne absorbée. **La garde qui a mordu est
versionnée** : `test_un_cache_de_traductions_qui_ne_couvre_pas_le_jeu_est_refuse`.

#### L'ENVIRONNEMENT DE CE LANCEMENT, ET CE QUI LE SÉPARE DU POSTE

Arbre détaché, `.venv` monté par le protocole §2.2, **aucun `.env`** — il vit
dans le clone principal et rien n'en a été recopié. Réglages posés
explicitement, **relevés sur le conteneur servi** par
`docker inspect … rag-agent-api` et non écrits de mémoire : `FETCH_K=50`,
`RETRIEVAL_TOP_K=50`, `RERANK_TOP_K=10`, `AUTO_SELECT_TOP_K=3`,
`TRANSLATION_WEIGHT=1.0`, `LLM_NUM_CTX=32768`, `LLM_MAX_TOKENS=4096`. Adresses
**découvertes** : `chromadb` et `graphd` n'exposent **aucun** port sur l'hôte, et
le 8000 de l'hôte est tenu par `data-analyst-agent-app-1`, **étranger à ce
projet** — l'y pointer aurait interrogé un serveur qui répond sans être le bon.

**L'ÉCART QUI RESTE, ET IL EST DÉCLARÉ : ce banc tourne en `cpu`, le conteneur
servi en `cuda`** (`/health` → `torch_device.requested = "cuda"`,
`cuda_available: true`). Le protocole §2.2 monte torch CPU et le défaut du code
(`cuda`) lève sur un tel arbre. Les poids sont les mêmes ; ce qu'un écart
d'arrondi flottant pourrait déplacer dans l'ordre du reranking **n'est pas
mesuré ici**. La recette laisse `TORCH_DEVICE` surchargeable pour que la mesure
soit rejouable sur un poste CUDA.

#### CE QUE CETTE MESURE NE DIT PAS

1. **LE RAPPEL D'UN ANCRAGE N'EST PAS LA QUALITÉ D'UNE RÉPONSE, ET LA SECONDE
   N'A PAS ÉTÉ MESURÉE.** Ce banc dit si le passage attendu **atteint** le
   prompt. Il ne dit rien de ce que le modèle en fait : ni justesse, ni
   citations, ni abstention. Le §4.66 a mesuré que les citations montent de 34 à
   55 en passant de 3 à 6 — **plus de citations n'est pas une meilleure
   réponse**, et cette phrase reste vraie dans l'autre sens.
2. **AUCUN COÛT N'EST REMESURÉ ICI.** Les +44 % de latence du §4.66 viennent de
   six questions et d'une génération réelle ; ce banc ne génère pas, et ses
   durées ne décrivent aucune latence de production.
3. **LE PLATEAU DU JEU DE RÉGLAGE EST UNE PROPRIÉTÉ DE CE JEU**, pas de la
   chaîne. Sur un corpus ou un jeu dont les ancrages tomberaient aux rangs 3 à
   10, k=3 perdrait ce que k=6 rattraperait. Rien ici ne le contredit ; ce jeu
   ne peut simplement pas en décider.
4. **UN ÉTAT DE STORE PÉRIME.** Les deux bilans décrivent le corpus du
   2 septembre 2026, `4367` chunks, ancrages **130/130** et **44/44** vérifiés le
   jour même. Ils ne survivront pas à une réingestion.
5. **LE DÉFAUT N'EST PAS CHANGÉ, et ce lot ne propose pas de le changer.**
   `AUTO_SELECT_TOP_K` reste à **3**. Ce qui a changé, c'est la raison : ce n'est
   plus « personne ne mesure la sélection » — c'est « la sélection est mesurée,
   et l'écart entre 3 et 6 est sous le bruit des deux seuls jeux qu'on ait ».

---

### 4.68 → La troncature du graphe à 2000 : nous la traitons déjà, et sept tableaux lui échappent quand même

`mesuré` le 23 septembre 2026 à 08:47–08:55 UTC contre le graphe et ChromaDB en
service. Le pipeline nous annonce, au titre d'une dette de son côté, que **le
graphe est tronqué à 2000 caractères et pas ChromaDB**, et que nous recevons donc
tout élément plus long **amputé en silence** — « pas vide, amputé ; un corps vide
se remarque, un corps coupé net se lit comme un corps ».

**NOUS LE TRAITONS DÉJÀ, ET C'EST ÉCRIT DEPUIS LONGTEMPS AU SITE.**
`graph_context.py:864-881` : si `FULL_TEXT_FROM_VECTORS` (défaut **`true`**,
valeur servie `true`), tout élément dont le texte atteint
`GRAPH_TEXT_TRUNCATION − 50` — soit **1950** — est redemandé à l'index vectoriel,
et remplacé **seulement si le texte rendu est STRICTEMENT plus long** : l'index
ne doit jamais raccourcir un texte.

**L'ÉTAT DU CORPUS SERVI.** Sur **15 173** sommets comptés, **18** atteignent le
seuil, et **les 18 font EXACTEMENT 2000 caractères** — la signature de la coupe
est parfaite, il n'y a pas de faux positif à défalquer. Répartition : **4
`Paragraph` sur 7 251**, et **14 `Table` sur 55**, soit **un quart des tableaux**.

**ET VOICI CE QUE LA MESURE AJOUTE, QUE PERSONNE N'AVAIT VU : 11 SUR 18 SONT
RALLONGÉS, SEPT NE LE SONT PAS.** Les sept sont **tous des `Table`**, et la
raison n'est pas que le texte manque : c'est que **ChromaDB en porte MOINS que le
graphe tronqué**. Le recollage des chunks rend 1776, 1540, 1150, 1266, 1801,
1875 et 1363 caractères — tous **sous** les 2000 du graphe. Le garde « strictement
plus long » refuse donc, à juste titre, de raccourcir.

**Contrôle positif, doublé :** un élément rallongé avec succès rend **2289**
caractères recollés depuis **6** chunks — `full_texts` recolle donc bien, ce
n'est pas lui qui est en cause ; et un élément court (100–300 caractères) n'est
même pas interrogé.

**CONSÉQUENCE POUR LE CONTRAT, ET C'EST CE QUI REMONTE AU PIPELINE : POUR CES
SEPT TABLEAUX, NI LE GRAPHE NI CHROMADB NE PORTENT LE TEXTE ENTIER.** Leur
proposition — « si vous avez besoin du corps entier, il est dans ChromaDB,
complet » — est **fausse pour ces cas**, et elle l'est silencieusement. Basculer
la lecture du corps vers les vecteurs ne fermerait donc pas le sujet : cela le
déplacerait de 18 éléments à 7.

**Ce que la mesure NE dit pas**, et il faut le dire avant que quelqu'un s'en
serve : nous n'avons **pas** établi POURQUOI la somme des chunks est inférieure —
chevauchement, séparateurs, ou matière réellement écartée au découpage, nous
n'avons pas tranché. Et ces chiffres sont un **état de store** : ils périmeront à
la réingestion, qui est précisément ce que le pipeline s'apprête à faire.

**Non traité, et volontairement :** `/health` ne publie rien sur le nombre
d'éléments tronqués non rallongés. Tant qu'il ne le fait pas, ce constat est une
mesure datée, pas une propriété gardée.

---

### 4.69 → Le compte de sommets du graphe, réconcilié une fois pour toutes

Deux chiffres circulaient entre nos deux dépôts : **15 196** côté pipeline,
**15 173** côté agent, écart de **23**. `mesuré` le 23 septembre 2026 à 08:53
UTC contre le graphe en service : l'écart vaut **exactement le nombre de
`Document`**, et l'hypothèse du pipeline était juste.

**La définition, et elle est désormais au site** — `documentation/references/2026-09-23-troncature-du-graphe.md` :
`sommets_tous_tags` = **15 196**, somme sur **tous** les tags de `SHOW TAGS` ;
`sommets_sans_Document` = **15 173**. Citer l'un pour l'autre est une dispute à
retardement, six mois plus tard, quand plus personne ne se souvient laquelle des
deux requêtes comptait quoi.

**LA LEÇON DE MÉTHODE, ET ELLE EST PAYÉE ICI.** Mon premier relevé énumérait une
liste de tags **écrite à la main**. Elle inventait `Text` et `Title` — qui
n'existent pas au schéma, et dont l'échec a été journalisé sans m'arrêter — et
elle oubliait `PageHeader`, `PageFooter` et `Document`. **Elle est tombée
juste par chance** : les oubliés valaient zéro, sauf `Document` que je
n'entendais pas compter. Si `PageHeader` avait porté des éléments, mon chiffre
aurait été faux **sans que rien ne le dise**. Le relevé versionné lit
`SHOW TAGS`. **Une liste en dur ne se trompe pas bruyamment, elle se trompe en
silence** — même famille que l'étiquette datée qui ment sur ce qu'elle désigne.

**L'état d'avant est versionné**, comme les 212 clés médias l'ont été :
**18** sommets exactement au plafond de 2000, **11** rallongés par les vecteurs,
**7** restant amputés — tous des `Table` — et **14 `Table` coupées sur 55**,
soit **un quart des tableaux du corpus**. Le pipeline retient ce dernier chiffre
comme le plus grave, et il a raison : les sept sont un symptôme, le quart est
l'ampleur.

---

### 4.70 → LOT-32 : une promesse d'API que la chaîne ne tient pas, et ce qu'il en coûterait de la tenir

Le §4.67 l'avait relevé en passant : `AnswerRequest.max_sources` était borné
**1..20** quand `rerank` ne rend jamais plus de `RERANK_TOP_K` = **10**. Ce lot
ferme l'écart. `mesuré` le **23 septembre 2026 de 09:02 à 09:19 UTC**, base
`main` = **`0ea4fe6`**, dans un arbre de travail détaché sans `.env`.

#### Le défaut, et pourquoi il ne se voyait pas

L'API **acceptait** 11 à 20, **servait** 10, et ne le disait **nulle part** : ni
erreur, ni avertissement, ni champ de réponse. L'appelant ne pouvait donc pas
distinguer « il n'y avait que dix passages pertinents » de « ta demande a été
rabotée ». Un défaut qui échoue se voit ; celui-là **répondait**.

La chaîne des trois sites, relevés **par motif** : la borne est déclarée au
champ `max_sources` d'`AnswerRequest` (`src/api/schemas.py`), elle gouverne
`top_k = state.get("max_sources") or settings.auto_select_top_k` dans
`node_reconstruct_context` (`src/agent/graph.py`), qui découpe `ranking[:top_k]`
sur la liste que rend `dedupe_by_element(ranked)[: settings.rerank_top_k]`
(`src/agent/retriever.py`). **C'est le dernier qui borne réellement**, et c'est
le seul des trois qui ne parlait pas.

#### LA VOIE CHOISIE : BORNER LA PROMESSE, ET LA MESURE QUI L'A DÉCIDÉE

Deux voies existaient : **(a)** porter `RERANK_TOP_K` à 20 pour que la chaîne
serve la borne annoncée, **(b)** faire que la borne annoncée soit celle que la
chaîne sert, et refuser au-delà. **(b) est retenue, et (a) a été MESURÉE avant
d'être écartée** — pas supposée.

Le banc du §4.67 (`scripts/mesurer_selection.py`) rejoué le 23 septembre 2026
entre 09:08 et 09:18 UTC avec **`RERANK_TOP_K=20` posé dans l'environnement du
lancement** — jamais dans le `.env`, que ce lot ne touche pas. Aucune réponse
LLM n'est générée. Bilans versionnés :
`runs/2026-09-23-borne-des-sources-rerank20-reglage.json` et
`runs/2026-09-23-borne-des-sources-rerank20-controle.json`, à confronter aux
`runs/2026-09-23-selection-*.json` du §4.67, qui sont le bras
`RERANK_TOP_K=10`. Les deux jeux du §4.67, appariés par question :

| jeu | k | sections servies | éléments au prompt | rappel au prompt | questions réussies | ancrages |
|---|---|---|---|---|---|---|
| réglage (130 q.) | 10 | 8,23 | 99,70 | 0,9538 | 124 | 124/130 |
| réglage (130 q.) | **20** | **15,81** | **192,04** | 0,9615 | **125** | 125/130 |
| contrôle (26 q.) | 10 | 7,73 | 84,31 | 0,8077 | 21 | 33/47 |
| contrôle (26 q.) | **20** | **15,38** | **177,00** | 0,8077 | **21** | 36/47 |

**CONTRÔLE POSITIF DU BANC, ET IL EST EXACT.** Le bras k=10 de ce relevé
reproduit **chiffre pour chiffre** le bilan versionné du §4.67 mesuré sous
`RERANK_TOP_K=10` — 8,23 / 99,7 / 0,9538 / 124 au réglage, 7,73 / 84,31 /
0,8077 / 33 ancrages au contrôle. Le banc mesure donc bien la même grandeur, et
**la seule chose qui a changé est celle qui devait changer** : sous
`RERANK_TOP_K=10`, k=20 rendait exactement k=10 ; sous `RERANK_TOP_K=20`, il ne
le rend plus. `n_classement` passe de **10** à **20** sur les 156 questions.
**C'est la preuve, des deux côtés, que le facteur limitant était bien le
reranker** et non le dédoublonnage : sous `RERANK_TOP_K=10`, les **156**
questions des deux jeux rendaient **exactement 10** éléments distincts — le
vivier n'a jamais manqué.

**CE QUE (a) COÛTERAIT, ET CE QU'ELLE RAPPORTE.** Le contexte soumis **double**
— éléments au prompt ×1,93 au réglage, ×2,10 au contrôle — **pour tous les
appels**, puisque `RERANK_TOP_K` n'est pas un paramètre de requête. En face :
**+1 question sur 130** au réglage, **+0 sur 26** au contrôle. Les deux jeux
portent la même réserve, et elle n'est pas négociable — *un écart de deux points
est du bruit* : +1 sur 130 vaut **0,77 point**, et le contrôle ne bouge pas du
tout. Le §4.66 avait mesuré **+44 %** de latence pour un prompt passant de 2358
à 4224 tokens ; ici le prompt double encore. **Le budget de fenêtre, lui,
n'écarte toujours rien** : `questions_avec_section_ecartee` vaut **0** aux
quatre bras — ce n'est pas la fenêtre qui interdit (a).

**LA PHRASE QUI TRANCHE, ET ELLE EST AU SITE.** Servir 20 exige de changer la
chaîne de **tous** les appels pour honorer une borne que **personne n'a
demandée** et dont le gain est écrit **NON TRANCHÉ** aux §4.66 et §4.67, faute
d'instrument. **Un accident d'écriture de schéma n'est pas ce qui doit arbitrer
un réglage de production.** (b) ne change aucun réglage servi et rend la
promesse vraie immédiatement.

#### Ce que (b) change exactement

La borne n'est plus **écrite**, elle est **dérivée** : `MAX_SOURCES_SERVIES =
settings.rerank_top_k` dans `src/api/schemas.py`, et `max_sources` porte
`le=MAX_SOURCES_SERVIES`. Trois conséquences, et la troisième est la plus
importante :

1. une demande au-delà est **refusée en 422**, jamais rabotée en silence ;
2. OpenAPI publie désormais la **vraie** borne, avec une `description` qui dit
   pourquoi elle est là ;
3. **le jour où `RERANK_TOP_K` monte à 20, la borne suit sans qu'on y touche** —
   la voie (a) reste donc ouverte, et elle ne pourra plus rouvrir ce défaut.

#### LE FLUX INTERACTIF N'A PAS À ÊTRE TRAITÉ, ET VOICI POURQUOI

`/chat/start` pose `"max_sources": None` dans son état initial, et **c'est
tout** : ni `ChatRequest` ni `SourceSelectionRequest` ne déclarent de plafond de
sources. `mesuré` au code : `node_reconstruct_context` ne passe par
`ranking[:top_k]` **que** si la sélection revient vide ; une sélection non vide
est reconstruite **sans écrêtage**. Ce flux **ne promet donc aucune borne**, et
il n'y a rien à y rendre honnête. La raison est écrite au site, et le cas
futur est **gardé** : la troisième scène de `tests/unit/test_borne_des_sources.py`
balaie les schémas plutôt que d'énumérer les endpoints, et exige que **tout**
champ d'API bornant des sources porte la borne de la chaîne.

**Borne à dire honnêtement :** `SourceSelectionRequest.selected_element_ids`
n'a **pas** de `max_length`. Un client peut donc poster plus d'identifiants que
le reranker n'en a proposé. Ce n'est pas le défaut traité ici — rien n'est
promis puis raboté, et l'ordre de ces identifiants est déjà tenu par
`_par_pertinence` — mais **ce n'est pas mesuré non plus**, et ce lot ne le
tranche pas.

#### La garde, et la mutation qui la fait rougir

`tests/unit/test_borne_des_sources.py`, **3** scènes. Elle **ne lit jamais
`RERANK_TOP_K`** : un garde qui confronterait ce réglage à lui-même serait vrai
par construction et n'attraperait rien. Elle mesure ce que la chaîne **SERT** —
la longueur que `rerank` rend vraiment sur un vivier de **64** chunks à
`element_id` distincts, cross-encoder doublé, dédoublonnage et troncature réels
— et le confronte à ce que le schéma **DÉCLARE**, lu dans les métadonnées
pydantic. **Aucune scène n'écrit `10`** ni aucun autre instantané du réglage.

| site muté, par motif | nature de la mutation | attendu | mesuré |
|---|---|---|---|
| la troncature de `rerank` — `dedupe_by_element(ranked)[: settings.rerank_top_k]` | la chaîne sert **moins** que la borne déclarée | rouge | **rouge, 3 scènes** |
| la borne du champ — `le=MAX_SOURCES_SERVIES` | le schéma déclare **plus** que la chaîne ne sert | rouge | **rouge, 2 scènes** |

Les deux sens mordent. Le détail des `rc`, des comptes et des restaurations
SHA-256 est au §4.18 de la présente page, comme pour tout lot qui touche `src/`.

**Ce que ce lot NE tranche pas :** que `RERANK_TOP_K=10` soit la bonne valeur.
Le gain de monter ce k reste **non mesuré** faute du jeu à ancrages multiples et
dispersés que le §4.67 a ouvert en dette — ce lot ne fait que rendre la promesse
conforme au réglage, quel qu'il soit.
