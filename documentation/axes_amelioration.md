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
threadpool FastAPI pendant ~9 secondes, et les endpoints de recherche partagent
ce threadpool. Trouvé en relisant l'endpoint, mesuré par le test (`assert 7 ==
2` sur les lectures du corpus avant correctif).

La reconstruction déclenchée par le filet tourne dans un fil démon : ses
~9 secondes ne doivent pas être payées par la requête qui découvre la dérive, qui
n'a pas participé à l'ingestion. L'index périmé continue de servir pendant ce
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
~9 secondes ; deux utilisateurs qui ouvrent l'interface après un redéploiement
n'est pas un cas exotique.

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

Répartition : **5 resserrées**, **4 dont le journal a changé de niveau ou de
message**, **14 conservées** avec justification écrite au site, et **1
supprimée** — `main.py:461`, l'absorption du §1.20, remplacée par la gestion
d'échec de `sessions.purger`. L'arbre courant en compte 24 aussi : les six
resserrements sont compensés par les cinq de `sessions.py` — qui passent par
`_echec`, la forme de référence — et par `retriever._taille_collection`,
nouvelle et documentée comme muette au site.

**Resserrées** — le repli ne couvre plus qu'une panne d'infrastructure :

| Site | Type retenu | Ce que `Exception` masquait |
|---|---|---|
| `llm.py:516` `rewrite_question`, gabarit | `(TemplateError, OSError)` | Une faute dans le bloc journalisait « Gabarit introuvable » : le message accusait le gabarit, la réécriture était désactivée à chaque question, et rien ne pointait vers la cause. |
| `llm.py:537` `rewrite_question`, appel Ollama | `(httpx.HTTPError, ValueError)` | Les deux seules façons dont l'appel échoue sans que le code soit en cause : transport, et corps qui n'est pas du JSON. |
| `llm.py:628` `translate_question`, gabarit | `(TemplateError, OSError)` | Idem §516. |
| `llm.py:647` `translate_question`, appel Ollama | `(httpx.HTTPError, ValueError)` | Idem §537. |
| `graph.py:173` `node_generate`, `get_stream_writer` | `RuntimeError` | Toute autre panne de LangGraph faisait `writer = None` : la génération continuait, **muette**, et le frontend ne recevait aucun token sans qu'une ligne existe pour le dire. |

**Niveau de journal remonté :**

| Site | Avant → après | Pourquoi |
|---|---|---|
| `graph.py:485` `close_checkpointers` | `debug` → `WARNING` | Une fermeture en échec laisse une connexion SQLite ouverte sur le fichier des sessions, donc un WAL non replié et un verrou possible au démarrage suivant. `debug` est invisible à `LOG_LEVEL=INFO` : c'est le motif même du §1.20. |
| `api/main.py:255` `/context` | muet → `ERROR` avec trace | FastAPI ne journalise pas une `HTTPException` : cette route rendait des 500 dont la cause n'était tracée nulle part. |
| `graph.py:145` et `api/main.py:309`, reconstruction par élément | message recalé | « Erreur reconstruction section » laissait croire à un incident sans suite, alors que la source **disparaît de la réponse**. Le message le dit, et compte celles qui restent. |

**Conservées, avec au site ce qu'elles protègent et pourquoi elles sont
larges :**

| Site | Fonction | Décision |
|---|---|---|
| `retriever.py:378` | `_dense_search` | Reprise de connexion. Un client Chroma mort produit transport, sérialisation et schéma sans ancêtre commun. WARNING, un second échec remonte. |
| `retriever.py:246` | `full_texts` | Dégradation bornée : le texte tronqué du graphe reste, le LLM reçoit un tableau amputé plutôt que rien. WARNING. |
| `retriever.py:301` | `ping` | Une sonde ne doit jamais lever. Le faux est publié par `/health`, et le cache est oublié pour que la requête suivante rouvre. |
| `retriever.py:103` | `_taille_collection` | Large et **muette**, délibérément : Chroma injoignable est déjà rapporté par `services.chromadb` dans la même réponse. Rend `None` — « je ne sais pas » — jamais confondu avec « rien n'a changé ». |
| `retriever.py:187` | `_lexical_search` | La recherche dense suffit à servir la requête. Tracée avec sa pile, publiée en `index_lexical: false`. |
| `graph_context.py:140` | `_execute_raw` | Reprise de connexion. nebula3 mêle transport, authentification et session sans ancêtre commun. WARNING puis nouvel essai ; un second échec remonte. |
| `graph_context.py:197` | `props_of` | Large et **muette** : un nœud sans propriétés pour ce tag est le cas NORMAL — le tag `Document` n'a ni `label` ni `text`. Appelée plusieurs fois par élément : y journaliser inonderait le journal en régime nominal. |
| `graph_context.py:394` | `ping` | Une sonde ne doit jamais lever. `_execute` a déjà journalisé la panne en WARNING. |
| `minio_client.py:98` | `get_object_bytes` | Reprise de connexion. Le SDK minio mêle ses `S3Error` aux erreurs urllib3 d'un socket mort. WARNING au premier essai, pile complète au second. |
| `graph.py:145` | `node_reconstruct_context` | Une source illisible ne doit pas emporter la réponse entière. Message recalé (ci-dessus). |
| `graph.py:469` | `build_checkpointer` | Volume non monté, disque en lecture seule, aiosqlite en défaut : mieux vaut un service dégradé qu'un service mort. ERROR avec trace — le repli change le comportement du service. |
| `api/main.py:255` | `/context` | La reconstruction traverse Nebula, Chroma et le parsing de leurs réponses. Journal ajouté (ci-dessus). |
| `api/main.py:309` | `chat_simple` | Idem `node_reconstruct_context`. Message recalé. |
| `sessions.py` ×5 | `initialiser`, `enregistrer`, `purger` ×3 | Une purge en échec ne doit pas casser la requête qui l'a déclenchée. Passe par `_echec` : WARNING au premier, rappels tous les 20, compteur dans `/health`. La ligne de registre est **conservée** en cas d'échec, sinon la session deviendrait inatteignable. |
| `usage.py` ×5 | `initialiser`, `record_start`, `record_completion`, `record_feedback`, `stats` | Inchangées : elles passent déjà par `_echec`, la forme de référence posée au lot 2. La capture est de l'observation, pas une fonctionnalité. |

**Supprimée :** `main.py:461`, le `except Exception: logger.debug("Purge du
thread %s impossible")` du §1.20. C'est l'absorption qui a motivé le lot ; elle
n'a pas été resserrée mais remplacée, par une gestion d'échec qui compte, trace
et publie (`sessions._echec`).

**Nouvelle, et assumée :** `retriever.py:103` `_taille_collection`. Le filet
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

---

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
| P1 | Marge résiduelle du remplissage des sources | Seule la **première** source retenue peut être tronquée, jamais la dernière : quand une source est écartée, la place qu'elle aurait presque remplie reste vide. Mesuré sur les 43 configurations où le budget corrigé écarte une source : **2 308 caractères de fenêtre inutilisés en moyenne, 6 169 au maximum**. Tronquer la dernière retenue au lieu de l'écarter les récupérerait. C'est un changement de l'algorithme de remplissage, pas un réglage — il touche l'ordre de préférence entre « une source de plus, amputée » et « une source de moins, entière », qui demande à être arbitré. **Reporté au lot 1**, débloqué par : rien, c'est prêt à être fait dans un lot dédié. |
| P1 | Le pari central n'est pas vérifié | Personne n'a montré que la reconstruction de section améliore les **réponses**. Le rappel mesure le retrieval, pas ce que le LLM en fait. Trancher demande un juge calibré — donc RAG-Eval-Bench. |
| P1 | Jeu doré non relu | 138 questions générées, toutes `reviewed: false`. L'approche est fiable pour régler un retriever, moins pour arbitrer entre générateurs. Une relecture humaine les promeut — et depuis la capture d'usage, les questions réellement posées et les sources validées par un humain s'accumulent pour la remplacer progressivement. Encore faut-il des utilisateurs : il n'y en a aucun à ce jour. |
| P1 | « Tout décoché » est irreprésentable, et le signal de sélection est aveugle avec lui | Un utilisateur qui rejette **toutes** les sources ne peut pas le dire : `SourceSelectionRequest.selected_element_ids` porte `min_length=1`, et le bouton « Générer » est désactivé à zéro coché. Son rejet total tombe donc dans le même seau `retenue IS NULL` que l'abandon d'onglet, alors que c'est le jugement le plus tranché qu'il puisse rendre — et le plus informatif pour la recherche. Deux défauts de la même famille l'accompagnent : **aucun seuil de pertinence** n'écarte les sources faibles (`rerank` rend les `RERANK_TOP_K` premières quel que soit leur score), et le **badge de pertinence est relatif au meilleur score de la question**, donc la meilleure source s'affiche toujours en vert — même quand la recherche n'a rien trouvé de bon. Les trois portent sur la même chose : ce que l'interface demande à l'humain, et ce qu'elle sait de la qualité absolue du classement. À traiter **ensemble, dans un lot dédié**, pas au fil de la capture. `agent_architecture.md` documentait le seuil comme un réglage existant (`RERANK_MIN_SCORE=0.0`) : l'affirmation est retirée (§1.25) et le réglage n'a pas été créé, pour que ce lot-ci reste entier. Débloqué par : rien, mais l'arbitrage à rendre — que veut dire « aucune source ne vaut » pour le graphe, faut-il générer, s'abstenir, ou relancer une recherche — est un choix produit, pas une correction. |
| P1 | Les données d'usage ne sont pas exploitées | **Ce que la capture ne fait pas, et c'est délibéré.** Le lot pose le robinet — les deux tables, les requêtes des trois usages, l'export JSON — pas la décision. Promouvoir une question en jeu doré, choisir son annotation, arbitrer ce qu'un décochage prouve : chantier d'un lot ultérieur. Débloqué par le premier corpus d'enregistrements réels, donc par les premiers utilisateurs. |
| P2 | Les trois classes de questions non couvertes | « Résume ce document », l'agrégation (« combien de documents parlent de X »), le multi-saut réel : l'architecture ne les sert pas, et personne ne sait si c'est un manque coûteux ou une inquiétude théorique. La question est désormais stockée telle qu'elle a été posée, et la requête de classement est écrite dans [capture_usage.md](capture_usage.md) : il ne manque que l'usage. |
| P3 | La capture n'a pas de garde-fou de taille | Aucune purge, par conception. La taille est journalisée au démarrage et exposée par `/health`, mais rien n'alerte : un poste laissé tourner des mois avec une campagne quotidienne (138 interactions, environ 4,6 ko chacune) écrit de l'ordre de 240 Mo par an. Trancher demande de savoir ce que l'exploitation garde. |
| P2 | Branchement sur RAG-Eval-Bench | Le banc apporte juges calibrés, comparaison appariée et intervalles de confiance. Il lui manque un `ExternalPipeline` qui poste sur `/answer`. |
| P1 | `LLM_MAX_TOKENS` non mesuré | 4096 tokens sur 8192 confisquent la **moitié** de la fenêtre à la génération, et rien ne dit qu'elle en a besoin. Le seul indice sourcé est indirect : 3,246 citations par réponse (`runs/final.json`). La longueur des réponses n'est mesurée nulle part — `runs/*.json` n'enregistre que `generation_ms` — donc « une génération qui n'arrive jamais » est une présomption, pas un fait. C'est le plus gros levier du budget de sources : à un plafond de 1024 tokens — **hypothèse de calcul, pas une mesure** — le budget de sources passerait de 12 444 à 23 196 caractères, soit **+86 %**. Protocole de mesure dans [llm.md](llm.md). **Reporté au lot 1**, débloqué par : la stack démarrée (§ ci-dessous). |
| P1 | Rien n'a jamais tourné contre le service d'inférence réel | `prompt_eval_count` n'a **jamais** été observé : l'instrumentation existe, elle n'a produit aucune mesure. Donc `_CHARS_PER_TOKEN = 3,5` reste un forfait, et aucune campagne n'a tourné depuis la correction du budget. La première peut démentir le ratio — c'est précisément pour cela que le log a été écrit, et pour cela que l'écart mesuré y est journalisé à chaque génération. **Reporté au lot 1**, débloqué par : réseau `llm-net` absent, conteneur `ollama-central` absent, stores arrêtés — les deux stacks prérequises doivent tourner. |
| P2 | La campagne n'enregistre pas la longueur des réponses | `scripts/evaluate.py` publie les citations, les temps et les contextes, mais pas le nombre de caractères ou de tokens générés. C'est exactement la grandeur dont dépend le réglage de `LLM_MAX_TOKENS` ci-dessus, et aucun fichier de `runs/` ne la porte — les campagnes passées ne permettent donc pas de reconstituer la distribution après coup. Elle ne coûte qu'un champ. **Reporté au lot 1**, débloqué par : rien, c'est une ligne dans `resumer()`. |
| P2 | Le jeu doré ne contient aucun historique de conversation | **0 des 138 questions** de `golden_qa_generated.json` porte un `chat_history` (l'ancien jeu de 15 en a 3, mais `make eval` ne l'utilise pas). Or le bénéfice principal du budget corrigé est la survie du message système **au troisième tour** d'une conversation : la campagne mesurera le coût de la correction sans jamais mesurer son gain. C'est un manque du **jeu**, pas du protocole de lecture — celui-ci est déjà prévenu dans [runs/README.md](../runs/README.md). **Reporté au lot 1**, débloqué par : quelques questions de suivi ajoutées au jeu, et une relecture humaine pour les valider (cf. « Jeu doré non relu »). |
| P2 | Ratio caractères/token posé au jugé | `_CHARS_PER_TOKEN = 3,5` gouverne tout le budget. Le log `prompt_eval_count` donne maintenant de quoi le calibrer, mais aucune campagne ne l'a encore fait (§ ci-dessus). |
| P2 | Le garde-fou de `_MARKER_RE` ne joue que dans un sens | `test_la_notion_de_marqueur_complet_est_celle_du_post_processing` compare `llm._MARKER_RE` à `graph._BLOC_SRC` sur trois formes. Il attrape un `_MARKER_RE` plus **étroit** que le post-processing, mais pas un plus **large** : vérifié, en l'élargissant à `\[[^\]]*\]` — qui accepterait `[Tableau]` comme frontière de coupe, donc laisserait un `[src:` amputé derrière lui — la suite reste entièrement verte. Le test doit exiger l'équivalence dans les deux sens, sur des formes qui ne sont **pas** des marqueurs. **Reporté au lot 1**, débloqué par : rien, c'est un durcissement de test. |
| P2 | `HISTORY_WINDOW_SHARE` posé au jugé | 25 % de la fenêtre de prompt pour l'historique, 75 % pour les sources. Forfait assumé : arbitrer demande de mesurer la qualité des réponses **multi-tour**, ce que `make eval` ne fait pas — le jeu doré ne pose que des questions isolées. Le réglage est exposé pour qu'un balayage soit possible le jour où la mesure existe. |
| P3 | Balises de tour du gabarit de chat | 34 caractères par message, le décompte du gabarit Gemma appliqué à tous les modèles. Le log `prompt_eval_count` permettrait de le déduire par différence. |
| P3 | `test_les_balises_de_tour_valent_le_gabarit_qu_elles_citent` ne valide rien d'externe | Le test recalcule `len("<start_of_turn>user\n") + len("<end_of_turn>\n")`, soit les mêmes littéraux que le commentaire de la constante : c'est un épinglage contre la dérive — utile — mais sa docstring laisse entendre une validation contre le gabarit réel de Gemma, qui n'a pas lieu. Le vrai gabarit vit dans le modèle Ollama, pas dans ce dépôt. **Reporté au lot 1**, débloqué par : reformuler la docstring en « épinglage », ou lire le gabarit du modèle servi — ce qui demande la stack. |
| P2 | Latence de génération | ~3 à 10 s contre 0,5 s de recherche. Le levier est le LLM — quantisation, `num_predict`, modèle plus petit — pas la recherche. |
| P2 | Coût de la traduction | Un appel LLM par question s'ajoute à la recherche. Un cache des traductions, ou un modèle plus petit dédié, l'amortirait. |
| P2 | Index BM25 en mémoire | Construit au premier appel : la **première** requête après un démarrage paie ~9 s, et cela n'a pas changé — c'est la seule construction encore payée par une requête utilisateur. Les reconstructions ultérieures, elles, tournent en tâche de fond (§1.21), et N requêtes concurrentes n'en déclenchent plus qu'une (§1.22). Un corpus nettement plus gros demanderait un moteur dédié. Déplacer la première construction au démarrage retarderait la mise en service d'autant : l'arbitrage n'a pas été rendu. |
| P3 | Multi-workers | Les sessions sont persistées — et leur purge l'est aussi désormais (§1.20), donc un worker purge ce qu'un autre a créé. Mais l'index BM25 et les modèles restent chargés par processus : N workers = N copies en mémoire, et surtout **`POST /reindex` ne reconstruit que l'index du worker qui reçoit la requête** — les autres restent périmés jusqu'à ce que leur filet de comparaison des comptes les rattrape. Non traité : le contrat de réindexation suppose aujourd'hui un worker unique. |
| P2 | Entretien des dépendances | Le projet a démarré sur des versions déjà vieilles d'onze mois, jamais montées ensuite. Il n'existe aucun garde-fou : `make audit` ne tourne pas en CI, rien ne signale une version qui vieillit. |
| P3 | Observabilité | Logs console uniquement, pas de tracing distribué ni de métriques exportées. |

---

## 3. Ouvert — dépend de l'ingestion

À transmettre à `rag-ingestion-pipeline` ; rien n'est faisable côté agent.

### 3.1 Le graphe est plat

Mesuré sur le graphe en production : **901** `SectionHeader` enfants d'un
`Document`, **0** enfant d'un autre `SectionHeader`, et **0** chemin de
longueur 3 depuis le `Document`. L'arbre fait exactement deux niveaux.

En cause, `elements.py` : `reference_id = ROOT_REFERENCE` dès qu'un en-tête est
rencontré. Docling expose pourtant le niveau des titres, que `TAG_MAP` écrase.

Conséquence : le breadcrumb ne peut afficher qu'un seul titre — pas de
`Chapitre 3 > 3.2 > 3.2.1`. Le « avant / après » n'en dépend pas (§1.9).

Correction : stocker le niveau du titre sur le tag `SectionHeader` et chaîner
les parents. **Impose une purge du space** — le schéma Nebula n'évolue pas en
place.

### 3.2 Modèle d'embedding monolingue

`all-MiniLM-L6-v2` est un modèle anglais, tronqué à 256 tokens, utilisé sur un
corpus et des questions en partie francophones. C'est l'écart le plus coûteux à
l'état de l'art. Le modèle est décidé à l'ingestion et doit coïncider des deux
côtés : en changer (`bge-m3`, `multilingual-e5-large`) **impose une réingestion
complète**.

### 3.3 Illustrations sans légende

L'arête `DESCRIBES` couvre les visuels légendés dans le document d'origine. Une
figure sans légende reste muette : introuvable par la recherche sémantique, et
impossible à juger pertinente par le LLM. Une description générée par VLM à
l'ingestion, indexée dans ChromaDB, comblerait ce trou.
