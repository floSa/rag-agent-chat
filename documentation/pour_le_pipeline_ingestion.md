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

### 5.1 Le graphe est plat — mesuré

Sur le graphe tel qu'il était en production : **901** `SectionHeader` enfants
d'un `Document`, **0** enfant d'un autre `SectionHeader`, **0** chemin de
longueur 3 depuis le `Document`. L'arbre fait exactement **deux** niveaux.

En cause : `elements.py` pose `reference_id = ROOT_REFERENCE` dès qu'un en-tête
est rencontré, alors que Docling expose le niveau des titres — que `TAG_MAP`
écrase.

Conséquence côté agent : le fil d'Ariane ne peut afficher qu'un seul titre,
jamais `Chapitre 3 > 3.2 > 3.2.1`. Le budget de contexte de l'agent facture
d'ailleurs le cadrage par source en fonction de la profondeur du fil : 34
caractères sans fil, 134 à deux niveaux, 275 à cinq. Un graphe réellement
hiérarchique coûtera donc un peu de fenêtre, et c'est prévu.

Correction : stocker le niveau du titre sur le tag `SectionHeader` et chaîner
les parents. **Impose une purge du space** — le schéma Nebula n'évolue pas en
place. Donc autant le faire *pendant* cette réingestion que plus tard.

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
  du projet : le graphe vaut-il son prix ? Un graphe **hiérarchique** (§5.1)
  changera cette réponse, donc l'ordre importe — mieux vaut réingérer avec le
  graphe corrigé avant de mesurer l'ablation, sinon il faudra tout rejouer ;
- **le jeu doré ne porte aucune question de suivi** : 0 des 138 questions n'a
  d'historique de conversation. C'est un chantier côté agent, mentionné ici
  parce qu'il conditionne ce qu'une campagne peut voir.

---

## 7. Ce qu'il serait utile de rapporter

- le corpus source est-il encore disponible, et lequel ;
- le modèle d'embedding effectivement utilisé par le pipeline aujourd'hui ;
- le nombre de documents et de chunks après ingestion, pour confronter à
  `collection.count()` côté agent ;
- si §5.1 est corrigé dans la même passe, puisqu'il impose de toute façon une
  purge du space ;
- la sortie de `POST /reindex` en fin de pipeline.

---

Pour le détail : [architecture.md](architecture.md) (vue d'ensemble et contrat),
[stores.md](stores.md) (ce que l'agent fait de chaque métadonnée),
[axes_amelioration.md](axes_amelioration.md) (le registre complet, dont la
section 3 « Ouvert — dépend de l'ingestion »).
