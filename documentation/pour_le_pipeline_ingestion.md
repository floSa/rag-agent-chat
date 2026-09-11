# Pour les conversations qui travaillent sur `rag-ingestion-pipeline`

Ce document est écrit **depuis** `rag-agent-chat`, à l'intention de qui travaille
sur le pipeline d'ingestion. Il dit ce que l'agent attend, ce qui casse en
silence si l'attente n'est pas tenue, et dans quel ordre remettre la chaîne en
route. Il est autosuffisant : rien n'oblige à avoir ce dépôt sous les yeux.

L'agent ne lit jamais les documents sources. Il lit **trois stores que ce
pipeline remplit**. Tout ce qui suit découle de là.

---

## 1. La règle qui ne souffre aucune exception

**Le modèle d'embedding doit être `paraphrase-multilingual-MiniLM-L12-v2`
(384 dimensions), le même des deux côtés.**

C'est le défaut de `settings.py` côté agent, sous `EMBEDDING_MODEL_NAME`.

Un désaccord entre les deux côtés est **la panne la plus coûteuse de tout le
système**, et elle est parfaitement silencieuse : pas d'exception, pas de ligne
de journal, aucune sonde de `/health` qui la voie. La recherche rend simplement
des passages plausibles et faux, et personne ne s'en aperçoit avant d'avoir lu
les réponses une par une.

Deux pièges connus, tous deux rencontrés :

- **la documentation a longtemps annoncé `all-MiniLM-L6-v2`**, un modèle
  anglais. C'était vrai avant une réingestion multilingue, ce ne l'est plus.
  Une version antérieure de cette page affirmait ici que « toutes les mentions
  ont été corrigées » : **c'était faux**, et sept d'entre elles vivaient dans
  `llm_integration_plan.md`, dont une ligne de `.env` d'apparence exécutable.
  Elles sont désormais couvertes par le bandeau en tête de ce document-là, et
  **l'inventaire complet est gardé par un test** —
  `tests/unit/test_coherence_depot.py`, qui est son site canonique et le seul
  chiffre à jour. Une affirmation de cette forme ne se recopie plus ici : elle
  rougit quand elle devient fausse. Si vous tombez sur ce nom, c'est un
  vestige — pas une instruction ;
- **le cross-encoder de reranking doit parler les mêmes langues que
  l'embedder.** Mesuré côté agent : sur une question française, un reranker
  anglais rendait des scores plats — étendue 0,0 % sur 20 candidats, soit un
  classement au hasard. Ce réglage-là est côté agent
  (`cross-encoder/mmarco-mMiniLMv2-L12-H384-v1`) ; c'est mentionné ici pour que
  personne ne conclue qu'un modèle anglais « suffit » quelque part dans la
  chaîne.

Changer d'embedding pour l'état de l'art (`bge-m3`, `multilingual-e5-large`,
`Qwen3-Embedding`) est prévu, mais **impose une réingestion complète** et ne se
décide pas sans campagne comparative appariée. Ce n'est pas le moment.

### Ce qui a changé côté agent le 4 septembre 2026, et ce que vous devez tenir

**L'estampille de la collection est devenue obligatoire.** Vous l'écriviez déjà
— `mesuré` en lecture seule le 4 septembre 2026, la collection `rag_documents`
porte `metadata = {'embedding_model': 'paraphrase-multilingual-MiniLM-L12-v2'}`
— et c'est désormais un **contrat**, pas une commodité : l'agent confronte son
réglage à cette valeur avant chaque recherche dense.

Trois conséquences, et elles sont franches :

- **estampille absente → l'agent refuse de chercher.** Toute recherche rend
  `503`, `/health` passe en `degraded` et nomme la cause. C'est délibéré : une
  collection sans estampille est une collection dont personne ne sait ce qui l'a
  produite, et un garde qui ne comparerait qu'en présence de l'estampille serait
  décoratif sur exactement ce cas-là. Une collection produite par une version
  plus ancienne du pipeline tombe donc sous cette règle ;
- **estampille différente du réglage de l'agent → même refus.** Aucun des deux
  côtés ne « gagne » : les deux noms sont publiés, à vous de dire lequel est le
  bon ;
- **rien à changer si vous estampillez déjà.** Ce paragraphe décrit ce que
  l'agent fait de ce que vous écrivez, pas une exigence nouvelle sur ce que vous
  écrivez.

**Ce que l'agent NE voit pas, et c'est une réserve.** Il lit l'estampille à
l'ouverture de la collection. Une réingestion qui changerait de modèle **pendant
que l'agent tourne** ne serait pas vue tant que la connexion n'est pas rouverte
— redémarrage de l'agent, ou coupure de ChromaDB. Si vous réingérez avec un
autre modèle, **redémarrez l'agent** : un `POST /reindex` ne suffit pas, il ne
touche que l'index lexical.

Site canonique du raisonnement complet, des deux décisions et de leur prix :
[`axes_amelioration.md`](axes_amelioration.md), §4.4.

---

## 2. Où en est la machine, concrètement

Constaté, pas supposé :

- **aucun volume Docker ne contient de données ChromaDB, NebulaGraph ou MinIO.**
  Les 15 volumes de la machine ont été listés ; les stores sont vides ou absents.
  **Une réingestion complète du corpus est donc nécessaire**, pas un simple
  redémarrage ;
- `rag_hf_cache` et `rag_models_cache` existent : les modèles d'embedding et de
  reranking n'auront pas à être retéléchargés ;
- **⚠ CECI A CHANGÉ LE 11 SEPTEMBRE 2026, ET C'EST CE QUE NOUS VOUS RENDONS.**
  Ce document déclarait : *« aucun GPU n'est requis. L'image de l'agent embarque
  Torch CPU-only et le projet est conçu pour tourner sur processeur. »* La
  première phrase est **devenue fausse**, la deuxième aussi, la troisième reste
  vraie. Le détail, parce que la nuance décide de ce que vous avez à faire :

  | | avant | depuis le 11 septembre 2026 |
  |---|---|---|
  | `torch` dans l'image de l'agent | build **CPU** (`2.14.0+cpu`) | build **CUDA** (`2.14.0+cu130`) |
  | taille de l'image | 2,92 Go | **10,5 Go** |
  | le CALCUL a-t-il besoin d'un GPU | non | **oui par défaut** — `TORCH_DEVICE` vaut `cuda` depuis la campagne du 11 septembre. `TORCH_DEVICE=cpu` le ramène sur processeur, sans rien reconstruire |
  | le DÉMARRAGE a-t-il besoin d'un GPU | non | **OUI**, et c'est le point qui vous concerne |

  **Ce qui vous concerne vraiment** : `docker-compose.yml` réserve désormais une
  carte au service `agent-api`. Sur une machine **sans** carte, sans pilote ou
  sans NVIDIA Container Toolkit, **le conteneur ne démarre pas** — il ne démarre
  pas *lentement*, il ne démarre **pas** : `mesuré` le 11 septembre 2026,
  `docker run` rend **`rc=125`** et `nvidia-container-cli: device error`, aucun
  processus lancé. C'est une panne sèche, pas une dégradation.

  **Ce que ça ne change pas** : le contrat entre nos deux projets. L'agent lit
  les mêmes stores, avec le même modèle d'embedding, et il trouve **les mêmes
  passages** — la campagne du 11 septembre l'a vérifié question par question sur
  les 138 du jeu de référence : neuf métriques de rappel identiques, 130/130 ex
  æquo. Rien de ce que vous produisez n'a besoin d'être différent, et **vous
  n'avez pas besoin d'un GPU pour le pipeline**.

  **Le geste, si votre machine n'a pas de carte** : commenter le bloc `deploy:`
  du service `agent-api` dans `docker-compose.yml`, puis
  `docker compose up -d agent-api`. Le service repart à l'identique. Le mode
  d'emploi complet — les trois conditions qui décident du GPU, comment vérifier
  chacune, le coût et le retour en arrière — est à
  [`gpu_cuda.md`](gpu_cuda.md).

  **Ce que nous ne tranchons pas** : si votre registre porte une exigence de
  portabilité sur cette pile, c'est votre pilote qui cote. Nous rendons le fait,
  pas la décision.

  Les « heures de GPU » que la documentation mentionne concernent toujours
  `RAG-Eval-Bench`, un outil d'évaluation séparé qui n'est pas dans cette boucle ;
- le réseau Docker `rag_network` est **créé par ce pipeline** — l'agent s'y
  raccroche en `external: true` et ne démarrera pas sans lui ;
- le réseau `llm-net` est créé par un troisième dépôt, `llm-service`, qui porte
  l'Ollama central. Il n'est pas sur la machine. À défaut, `OLLAMA_HOST` peut
  pointer vers un Ollama local.

---

## 3. Le contrat : ce que l'agent lit

### ChromaDB, collection `rag_documents`

Métadonnées attendues par chunk :

`element_id`, `graph_node_id`, `filename`, `collection`, `source_path`,
`section_title`, `language`, `depth`, `label`, `page_no`, `minio_url`,
`chunk_index`, `chunk_count`.

Trois exigences qui ne se devinent pas :

- **`element_id` doit être déterministe**, dérivé du contenu (sha256 tronqué à
  10 caractères hexadécimaux, validé par l'agent contre `^[a-f0-9]{10}$`). Ce
  qu'il garantit, exactement : **réingérer LE MÊME corpus rend LES MÊMES
  identifiants**, donc un jeu de questions qui les désigne reste valide à travers
  une réingestion à corpus constant. C'est ce dont un jeu d'évaluation a besoin,
  et le pipeline le tient ;

  > **CETTE PHRASE PROMETTAIT AUTRE CHOSE, ET LA MESURE L'A DÉMENTIE.** Elle
  > disait : « c'est ce qui permet au jeu doré de survivre à une réingestion ».
  > `mesuré` le 3 septembre 2026, puis reproduit le 8 septembre 2026 par le
  > lot 5 : le jeu de 138 questions alors versionné désignait **129**
  > `element_id` distincts dont **0** existait dans le graphe. **Le déterminisme
  > n'était pas en cause** — le pipeline le tient, et l'exigence 2 est tenue. Ce
  > qui a changé le 2 septembre 2026 est le **CORPUS** : les 23 documents en
  > service n'ont aucun ouvrage en commun avec ceux que le jeu nommait. Un
  > identifiant dérivé du contenu et du chemin change par construction quand le
  > contenu et le chemin changent — c'est la propriété qu'on lui demande, pas un
  > défaut.
  >
  > **La phrase attribuait donc au déterminisme une garantie qu'il n'a jamais
  > donnée** : survivre au REMPLACEMENT d'un corpus. Rien ne peut la donner, et
  > aucune convention d'identifiant n'y suffirait — un passage qui n'existe plus
  > n'a pas d'identifiant valide. La conséquence appartient à ce dépôt, pas au
  > pipeline : **un jeu de questions est un état de corpus**, il périme avec lui,
  > et il doit prouver ses ancrages contre les stores AVANT toute mesure. Le lot 5
  > a régénéré le jeu, adopté les trente questions du pipeline, et posé
  > l'instrument qui refuse de mesurer sur un jeu périmé —
  > `scripts/verifier_les_ancrages.py`. Site canonique du constat et de la
  > décision : §4.3 de [`axes_amelioration.md`](axes_amelioration.md).

- **`source_path` est l'identité d'un document, jamais `filename` seul.** Deux
  ouvrages peuvent contenir une « Préface » ;
- **un élément long réparti sur plusieurs chunks** doit voir ses chunks partager
  le même `element_id`, avec `chunk_index` / `chunk_count` pour les ordonner. La
  déduplication de l'agent en dépend.

### NebulaGraph, space `rag_space`

`Document → SectionHeader → SectionHeader → …` via `PARENT_OF(sequence)`, plus
une arête `DESCRIBES` de chaque légende vers son illustration.

VIDs : sha256[:10] pour les éléments, `doc_{chemin}` pour les documents.

La propriété `sequence` de `PARENT_OF` porte l'ordre, et l'agent s'en sert pour
la fenêtre d'éléments et pour le « avant / après » entre sections voisines. Un
`sequence` absent ou non monotone casse cette reconstruction sans erreur
visible.

**Ce que l'agent en a fait de son côté, et vous n'avez rien à changer pour ça.**
`sequence` porte trois réserves qui décrivent comment on la LIT — elle repart à
0 par document, elle n'est pas contiguë sous un parent, et l'écart entre deux
enfants peut être grand. C'était le dernier point ouvert du contrat, et il est
désormais écrit et **gardé par un test** de ce côté-ci. Site canonique :
[stores.md](stores.md#les-trois-réserves-de-lecture-de-sequence). Les trois
chiffres que le pipeline avait transmis ont été reproduits ici à l'unité.

### MinIO, bucket `documents`

Crops PNG sous `images/{stem}/{id}_{type}.png`, référencés par `minio_url` dans
les métadonnées ChromaDB.

L'agent ne sert que les objets **référencés par le graphe**
(`RESTRICT_MEDIA_TO_GRAPH=true`) : un objet présent dans le bucket mais absent
du graphe est inaccessible, délibérément.

### `POST /reindex` — la seule chose que le pipeline doit APPELER

L'agent tient un index BM25 **en mémoire**, construit au premier appel. La
recherche dense suit ChromaDB sans effort ; la recherche lexicale, non.

**À appeler en fin de pipeline, une fois l'ingestion terminée.** Sans cet appel,
un document ingéré après le démarrage de l'agent reste invisible en recherche
lexicale jusqu'au prochain redémarrage.

Un filet existe côté agent — il compare `collection.count()` au nombre de chunks
indexés — mais il ne voit **pas** un corpus dont on a retiré autant de chunks
qu'on en a ajouté. C'est pourquoi l'appel est un contrat et non une option.

---

## 4. Dans quel ordre remettre la chaîne en route

1. Démarrer `rag-ingestion-pipeline`, qui crée le réseau `rag_network` et les
   trois stores.
2. Vérifier le modèle d'embedding **avant** d'ingérer quoi que ce soit (§1).
3. Ingérer le corpus.
4. Rendre Ollama joignable : `llm-service` et son réseau `llm-net`, ou un Ollama
   local via `OLLAMA_HOST`.
5. Démarrer `rag-agent-chat` et vérifier que `GET /health` répond `ok`. Les
   quatre sondes y sont désormais parallèles sous un plafond de 3 s : le
   conteneur ne peut plus rester `unhealthy` à cause d'un store lent, et le
   frontend n'est plus bloqué au démarrage.
6. Appeler `POST /reindex`.
7. Lancer `make eval` une fois, pour obtenir la première campagne de référence.

L'étape 3 est celle qui peut bloquer : **si le corpus source lui-même n'est plus
sur la machine, rien de ce qui suit n'est possible.** C'est la première chose à
vérifier.

---

## 5. Ce qui vous appartient, et que l'agent ne peut pas régler

Trois points relevés côté agent, dont aucun n'est corrigeable sans toucher à
l'ingestion.

### 5.1 → RENDU. Le graphe n'est plus plat, et vous l'avez livré

**Cette demande est close, et elle n'attend plus rien de vous.** Elle a survécu
à sa livraison parce que ce dépôt est resté immobile pendant que le pipeline
réingérait : la page redemandait donc un travail déjà fait, et faisait perdre
son temps à qui la lisait.

Ce qui était demandé : chaîner les parents des titres au lieu de les rattacher
tous au `Document`. Ce que la réingestion du **2 septembre 2026** a livré,
`mesuré` de ce côté-ci le 3 septembre 2026 sur le graphe en service :

L'ordre de grandeur, et une seule valeur pour le fixer : **78,2 %** des
`SectionHeader` ont pour parent un autre `SectionHeader`.

`Chapitre 3 > 3.2 > 3.2.1` est donc possible, et le fil d'Ariane de l'agent le
construit correctement **sans rien changer** : `_climb_to_section` collecte la
chaîne entière jusqu'au tag racine.

Le compte exact, la distribution des profondeurs et les commandes qui les
rejouent sont au **§4.6** de
[`axes_amelioration.md`](axes_amelioration.md), leur site canonique — cette page
y renvoie plutôt que de les recopier. La version précédente recopiait la table
entière trois lignes au-dessus d'écrire qu'elle ne la recopiait pas.

**Ce qui reste vrai du coût annoncé ici**, et c'est la seule chose à retenir de
l'ancienne version : le budget de contexte de l'agent facture l'encadrement
source par source selon la profondeur du fil, donc des titres imbriqués
coûtent réellement plus de fenêtre. C'est absorbé par construction et gardé par
un test, mais **ce coût n'a jamais été payé en campagne** : aucune mesure ne
dit encore ce qu'il déplace.

### 5.2 Illustrations sans légende

L'arête `DESCRIBES` ne couvre que les visuels légendés dans le document
d'origine. Une figure sans légende est muette : introuvable par la recherche
sémantique, et impossible à juger pertinente par le modèle, qui n'en voit qu'un
marqueur `[img:ID]`.

Une description générée par un VLM à l'ingestion, indexée dans ChromaDB,
comblerait ce trou.

### 5.3 Le nombre de chunks, et le coût qu'il impose à l'agent

L'agent appelle `collection.count()` à chaque recherche lexicale et à chaque
sonde `/health`, pour détecter un index périmé. C'est un aller-retour ChromaDB
par appel, non mesuré. Ce n'est pas une demande — c'est une information : si le
pipeline honore fidèlement `POST /reindex`, ce filet devient superflu et pourra
être allégé côté agent.

---

## 6. Ce que l'agent mesure désormais, et pourquoi ça vous concerne

Six lots de travail ont porté sur l'agent pendant que les stores étaient
éteints. Ce qui change pour vous :

- **la première campagne servira de référence, et rien d'antérieur n'est
  comparable.** Le budget de contexte a été corrigé, l'algorithme de
  remplissage des sources a changé, et la résolution des citations a été
  restreinte à ce qui a réellement été soumis au modèle. Les avertissements et
  les sens attendus par métrique sont écrits dans `runs/README.md` ;
- **le rappel se mesure à l'`element_id`**, ce qui rend le déterminisme des
  identifiants (§3) non négociable ;
- **la reconstruction par le graphe est désormais chronométrée**
  (`reconstruction_ms`), et son bénéfice mesurable — l'écart entre
  `rappel_contexte` et `rappel_elements` isole ce que la fenêtre du graphe
  apporte par elle-même. C'est ce qui permettra enfin d'arbitrer le pari central
  du projet : le graphe vaut-il son prix ? Le graphe **est** désormais
  hiérarchique (§5.1), et aucune campagne n'a encore été jouée dessus — la
  précaution que ce point demandait (« réingérer avant de mesurer l'ablation »)
  est donc satisfaite d'office, mais la mesure reste entièrement à faire ;
- **le jeu doré ne porte aucune question de suivi** : 0 des 138 questions n'a
  d'historique de conversation. C'est un chantier côté agent, mentionné ici
  parce qu'il conditionne ce qu'une campagne peut voir.

---

## 7. Ce qu'il serait utile de rapporter

- le corpus source est-il encore disponible, et lequel ;
- le modèle d'embedding effectivement utilisé par le pipeline aujourd'hui ;
- le nombre de documents et de chunks après ingestion, pour confronter à
  `collection.count()` côté agent ;
- ~~si §5.1 est corrigé dans la même passe~~ — **rendu** : il l'est depuis la
  réingestion du 2 septembre 2026 (§5.1) ;
- la sortie de `POST /reindex` en fin de pipeline.

---

Pour le détail : [architecture.md](architecture.md) (vue d'ensemble et contrat),
[stores.md](stores.md) (ce que l'agent fait de chaque métadonnée),
[axes_amelioration.md](axes_amelioration.md) (le registre complet, dont la
section 3 « Ouvert — dépend de l'ingestion »).

---

## 8. Trois constats que ce dépôt vous rend, le 4 septembre 2026

**Votre registre est le site canonique de ces trois points, et votre pilote les
cote.** Ce dépôt les a mesurés et les rend ; il n'en tranche aucun. Le détail,
avec les commandes, est au §4.16 de
[`axes_amelioration.md`](axes_amelioration.md) de ce dépôt.

### 8.1 Votre `etat_des_lieux.md` est périmé sur l'exigence 5 — la seule que vous donniez ouverte

Votre page dit, au 3 septembre : *« ⚠️ non éprouvée — l'appel part, mais l'agent
ne tourne pas sur ce poste »*, et votre §8 range « prouver l'exigence 5 » au
**rang 2** de ce qui reste.

**C'est fait.** Le lot 1 de ce dépôt l'a prouvée en marche, son audit
indépendant l'a reproduite **sur l'agent vivant**, et un test la garde — dont
l'audit a mesuré qu'il est seul garde de deux mutations du producteur. `mesuré`
le 4 septembre 2026 : `rag-agent-api` est `healthy`, `GET /health` rend
HTTP **200** et `status: ok` avec ses quatre dépendances à `true`, et
`POST /reindex` est exposé dans l'`openapi.json` servi.

**Le port de l'hôte est `8011`, pas `8000`.** C'est `8000` dans le conteneur.

**Les cinq exigences du contrat sont donc tenues.** Votre tableau du §4 et votre
§8 sont à amender, et votre rang 2 à retirer.

### 8.2 La cause matérielle que vous donniez a disparu

Votre page explique que l'agent ne tourne pas parce qu'il est *« sans `.env` »*.
Ce fichier existe depuis le 3 septembre 2026, écrit dans le **clone principal** —
jamais dans un arbre de travail, parce que `docker-compose.yml` monte
`./prompts` et qu'un `up` lancé depuis un arbre l'y ancrerait. `mesuré` le
4 septembre 2026 : présent, en `0600`.

### 8.3 Votre démon d'orchestration s'est rallumé, et c'est la quatrième fois

`mesuré` le 4 septembre 2026 : `rag-ingestion-pipeline-dagster-daemon-1` est
`Up`, là où votre relevé du 3 septembre le donnait `Exited (0)` aux deux bouts du
lot 1. Votre dépôt en compte **trois** occurrences, cause jamais cherchée ; en
voici une **quatrième**, sur un poste où aucune conversation ne l'a décidée.

**Ce dépôt n'y a pas touché** — ni démarré, ni arrêté. Il vous le signale parce
que la conséquence est chez vous, et qu'elle a une ironie que votre propre §6
nomme : **ce qui protège l'index de votre campagne de référence en ce moment
n'est pas l'arrêt du démon**, c'est le défaut de la clé de run déjà consommée —
le §4.32.a, celui que votre plan met au **rang 1**. *Le jour où vous le corrigez,
l'état des capteurs cesse d'être sans conséquence.*

### 8.4 Et ce que ce dépôt vous rend en positif : le rang 3 est livré

Votre rang 3 — *« écrire les trois réserves de `sequence` côté agent »* — est
**fusionné ici** le 4 septembre 2026. Elles sont écrites dans
[`stores.md`](stores.md), au § « Ce que ces trois réserves interdisent », et
elles ne sont plus seulement écrites : **onze mutations les font rougir**, et un
instrument rejouable — `scripts/mesurer_le_graphe.py`, en lecture seule —
imprime chacun des chiffres publiés.

Deux de vos chiffres se sont précisés au passage, et ce sont des **corrections de
dénominateur, pas de mesure** :

- la non-contiguïté se rapporte aux **692 parents qui ont au moins deux
  enfants**, et non aux 763 parents du graphe : un parent à enfant unique est
  contigu par définition et ne peut pas entrer au dénominateur. Le numérateur est
  inchangé — **167** ;
- l'écart de **994** est un **trou de numérotation**, pas un nombre d'éléments
  manquants. La perte réelle se borne à `before + after` : `mesuré`, **1 141**
  ancres sur 15 173 — **7,5 %** — rendraient moins d'éléments, chez **162**
  parents, et la perte maximale est de **12 éléments sur 13**, l'ancre revenant
  seule. Votre §5.3 gagnerait à porter cette borne : telle quelle, « 994 » se lit
  comme 993 éléments perdus.

Votre §5.3 dit que ces trois réserves *« ne peuvent pas être fermées depuis ce
dépôt »*. C'est exact, et c'est fait de ce côté-ci.
