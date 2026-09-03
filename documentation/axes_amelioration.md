# Axes d'amélioration — rag-agent-chat

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

`reconstruct_section` ne récupérait que la section de l'élément. Les en-têtes
étant frères sous le `Document` et ordonnés par la propriété `sequence` de
l'arête, `_find_sibling` atteint la section précédente et la suivante : leur
queue et leur tête entrent dans le prompt, dans des blocs explicitement
étiquetés pour que le LLM les distingue de la section trouvée.

### 1.10 Légendes des illustrations — `graph_context.py`

L'ingestion relie chaque `Caption` à l'illustration qui la précède par une arête
`DESCRIBES`. L'agent ne la traversait jamais : le LLM recevait un `[img:ID]`
muet et devait juger seul de sa pertinence. La légende est désormais rattachée
au visuel dans le markdown.

### 1.11 `CONTEXT_DEPTH` sans effet — `settings.py`

Le paramètre était lu nulle part, et ne pouvait rien faire : l'ingestion
n'imbrique pas les titres, il n'y a aucun niveau à remonter (§3.1). Supprimé et
remplacé par les bornes de fenêtrage, qui décrivent ce qui est réellement
réglable.

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
`/health`, donc redémarrer le service en boucle : précisément ce que cette route
existe pour éviter. Effet de bord acquis : un `OLLAMA_HOST` mal formé lève
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
| Tool-calling natif | `search_vectors` déclaré comme outil Ollama ; le regex sur la prose reste en second rideau. |
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

### 4.1 Le garde-fou d'identité Git n'existe pas sur ce dépôt

**Gravité : la plus haute du chantier, parce qu'elle est irréversible.**

`mesuré` le 3 septembre 2026 :

| Ce qui a été cherché | Commande | Résultat |
|---|---|---|
| une identité configurée | `git config --list --show-origin \| grep -i user` | `rc=1` — **rien**, ni local, ni global |
| ce que git utiliserait | `git var GIT_AUTHOR_IDENT` | `rc≠0`, « Author identity unknown » |
| des hooks armés | `ls .git/hooks/` | **uniquement des `*.sample`** |
| le hook versionné du dépôt jumeau | `ls scripts/git-hooks/` | **absent** |
| une cible d'installation | `grep install Makefile` | **absente** |

Autrement dit : **rien ne protège ce dépôt**, et la seule raison pour laquelle
aucun mauvais commit n'en est parti est qu'aucune identité n'était configurée du
tout — un `fail-closed` par accident, pas par construction. Le geste qui le
défait est une seule commande, et il n'y a rien derrière.

Ce que ça a coûté sur le dépôt jumeau, où le même trou existait : sept commits
partis avec une adresse **professionnelle** `@aosis.net` sur un dépôt
**personnel**, puis 165 commits réécrits, puis **le dépôt GitHub détruit et
recréé** — la liste des contributeurs, une fois constituée, ne se défait pas.

**Ce que l'historique de CE dépôt porte, et il est sain** (`mesuré` :
`git log --all --format='%ae | %ce' | sort | uniq -c`) : 165 commits, **deux
adresses et elles seules** — `florian_horellou@laposte.net` (89) et
`florian.horellou@gmail.com` (76) —, **0** occurrence de `@aosis.net`, et **0**
attribution à un assistant de génération de code. Il n'y a rien à réparer :
il y a un garde à poser avant que quelque chose soit à réparer.

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

### 4.2 L'agent ne tourne pas : il n'a pas de `.env` — et l'exemple porte une valeur fausse pour ce poste

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

### 4.3 `make eval` est hors service : son jeu doré désigne un corpus qui n'est plus là

**Gravité : c'est la seule mesure de qualité du dépôt, et elle est morte.**

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

**Ce que ce constat ne tranche pas.** Trois issues existent — retirer le jeu
doré et adopter les 30 questions du pipeline comme seul instrument, régénérer le
jeu depuis le nouveau corpus avec `scripts/generate_golden.py`, ou les deux. Le
choix engage tout ce qui suit et **il n'appartient pas à une conversation** : il
est au plan du pilote, en attente de décision.

**Et l'instrument valide existe déjà** : le jeu de 30 questions du pipeline,
`documentation/campagnes/2026-09-02-jeu-de-questions.yaml`, écrit **après**
l'ingestion, désignant 44 identifiants réels. Il porte sa propre réserve, et
elle interdit d'arbitrer un réglage avec lui — §5 de
[`pilotage_du_chantier.md`](pilotage_du_chantier.md).

### 4.4 Le modèle d'embedding n'est gardé que d'un seul côté — et le pipeline tend déjà de quoi fermer

C'est l'**exigence 1** du contrat, et la panne la plus coûteuse du système :
les deux modèles candidats rendent des vecteurs de **384 dimensions**, donc
ChromaDB accepte sans broncher, aucune sonde ne voit rien, et la recherche rend
des passages **plausibles et faux**. Vérifier la dimension ne protège de rien —
c'est le **nom** qui discrimine.

`mesuré` le 3 septembre 2026 :

- **le pipeline garde les deux bouts** : il refuse de démarrer sur un autre
  modèle, et refuse d'écrire dans une collection produite par un autre ;
- **l'agent, qui LIT, n'a aucun garde.** `embedding_model_name` est un
  `Field` de `settings.py` avec un défaut, et rien ne le confronte à quoi que
  ce soit : `grep -n "model_validator\|field_validator" src/agent/settings.py`
  ne rend **aucune ligne**. `retriever.py:30` charge ce que le réglage nomme et
  interroge la collection avec ;
- **et la comparaison est disponible en une lecture** : le pipeline **estampille
  déjà la collection**. `collection.metadata` vaut
  `{'embedding_model': 'paraphrase-multilingual-MiniLM-L12-v2'}`.

Donc le garde manquant est une confrontation entre `settings.embedding_model_name`
et `collection.metadata["embedding_model"]`, au démarrage ou dans `/health`. Le
producteur a fait sa moitié ; le lecteur n'a pas fait la sienne.

**Une correction de raisonnement, au passage.** Le §3.2 de ce registre prouvait
la concordance des modèles par un détour : « `runs/final.json` porte
`rappel_recherche = 0,985`, ce qui est impossible avec deux embedders
différents ». Le raisonnement est juste, mais **son antécédent a péri** — ce run
décrit un corpus qui n'est plus là (§4.3). Il prouve la concordance d'août sur
le corpus d'août, et rien d'aujourd'hui. La preuve directe existe désormais, et
c'est l'estampille de la collection ci-dessus.

### 4.5 Les trois réserves de lecture de `sequence` ne sont écrites nulle part — et le code n'est juste que par construction

Le pipeline garantit que `sequence` porte l'ordre et qu'elle est monotone
(exigence 4). Ce qu'il ne peut pas écrire, parce que ça décrit comment l'agent
*lit*, ce sont les trois réserves. **`grep -rn "sequence" documentation/`
n'en rend aucune** (`mesuré`, 3 septembre 2026) : les 10 occurrences décrivent
l'arête, jamais ses pièges.

**Les trois réserves, reproduites de mes mains** sur les 15 173 arêtes
`PARENT_OF` extraites du graphe en service — les trois chiffres du pipeline
tombent à l'unité :

| La réserve | `mesuré` le 3 septembre 2026 |
|---|---|
| **1. `sequence` repart à 0 dans chaque document** | tout « avant / après » doit être **borné au document** |
| **2. elle n'est pas contiguë sous un parent**, par construction | **167** parents sur **763** ont des valeurs non contiguës, et l'écart s'explique par la taille du sous-arbre du frère précédent. **Ce n'est pas une perte** |
| **3. le plus grand écart entre deux enfants d'un même parent vaut 994** (993 valeurs intercalaires) | site : `doc_htms/MLOps with Databricks/7. Foundation Models and Context Engineering`. Un agent qui implémente « la fenêtre d'éléments » comme « les enfants de P dont `sequence ∈ [s−k, s+k]` » rendrait **silencieusement moins** d'éléments que demandé |

Également `mesuré` : **0** arête à `sequence` nulle sur les 15 173.

**Ce que fait le code aujourd'hui, et c'est la partie qui compte.** Les trois
réserves sont respectées, mais **par construction, et non par un garde** :

- `_window_around` (`src/agent/graph_context.py:493`) découpe sur des
  **positions de liste** — `rows[start:stop]`, après un `index` trouvé par
  énumération — et **jamais sur des valeurs de `sequence`. `_get_children`
  (`:398`) va chercher **tous** les enfants avec `ORDER BY $-.seq ASC`, sans
  aucun filtre d'intervalle. **Le piège 3 ne mord donc pas** ;
- `_get_children` et `_find_sibling` partent tous deux d'un VID de parent, donc
  leur portée est **structurellement bornée à un document**. Le piège 1 ne mord
  pas non plus.

**Et c'est précisément ce qui rend le sujet dangereux.** Rien ne rougit si
quelqu'un « optimise » `_window_around` en poussant la fenêtre dans la requête
nGQL sous la forme d'un encadrement sur `sequence` — l'optimisation naturelle,
celle qui économise un aller-retour. Le résultat serait juste sur la plupart des
sections et **silencieusement amputé** sur les 167 parents non contigus, jusqu'à
993 éléments manquants au pire site. **Le travail n'est donc pas d'écrire trois
paragraphes : c'est d'écrire les trois réserves ET le garde qui rend le découpage
positionnel non négociable.**

### 4.6 Le graphe est imbriqué depuis le 2 septembre 2026, et ce dépôt le croit encore plat — en six sites

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
| `src/agent/graph_context.py:19-22` | « L'ingestion produit aujourd'hui un arbre à **deux niveaux** » | justifie `_MAX_DEPTH = 10`. **Sans conséquence** : 10 couvre la profondeur réelle, qui atteint 4 pour un titre et 5 pour un élément. La marge annoncée « pour une future imbrication » a effectivement absorbé le changement |
| `src/agent/graph_context.py:24-26` | « Les enfants d'un `Document` ne sont pas tous des en-têtes » | justifie `_SIBLING_CANDIDATES = 5`. **Sans conséquence non plus, et pas pour la raison écrite** — voir la mesure ci-dessous |
| `src/agent/graph_context.py:266-267` | « Les en-têtes sont **tous** enfants directs du `Document` (l'ingestion ne les imbrique pas) » | justifie toute la stratégie « la section voisine est un frère ». C'est la phrase la plus fausse des six : 78,2 % des en-têtes la contredisent |

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
en-têtes, **214** n'ont aucun frère en-tête d'un côté donné (mêmes 214 dans les
deux directions). Pour ceux-là `_find_sibling` rend `None`, alors qu'une section
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
