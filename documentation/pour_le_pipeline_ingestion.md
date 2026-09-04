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
  Toutes les mentions ont été corrigées, mais si vous tombez sur une trace de ce
  nom quelque part, c'est un vestige — pas une instruction ;
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

---

## 2. Où en est la machine, concrètement

Constaté, pas supposé :

- **aucun volume Docker ne contient de données ChromaDB, NebulaGraph ou MinIO.**
  Les 15 volumes de la machine ont été listés ; les stores sont vides ou absents.
  **Une réingestion complète du corpus est donc nécessaire**, pas un simple
  redémarrage ;
- `rag_hf_cache` et `rag_models_cache` existent : les modèles d'embedding et de
  reranking n'auront pas à être retéléchargés ;
- **aucun GPU n'est requis.** L'image de l'agent embarque Torch **CPU-only** et
  le projet est conçu pour tourner sur processeur. Les « heures de GPU » que la
  documentation mentionne concernent `RAG-Eval-Bench`, un outil d'évaluation
  séparé qui n'est pas dans cette boucle ;
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
  10 caractères hexadécimaux, validé par l'agent contre `^[a-f0-9]{10}$`). C'est
  ce qui permet au jeu doré de survivre à une réingestion : les 138 questions
  d'évaluation désignent des `element_id`, et un identifiant qui change rend
  toute la mesure historique incomparable ;
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
