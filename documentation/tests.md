# Les tests, et ce qu'ils ne disent pas

Trois niveaux, qui répondent à trois questions différentes. Aucun ne remplace
les autres, et le troisième est le seul à parler de **qualité**.

| Niveau | Commande | Question à laquelle il répond |
|---|---|---|
| Unitaire | `make test` | La logique est-elle correcte ? |
| Intégration | `make test-integration` | Le système tient-il debout avec les vrais stores ? |
| Campagne | `make eval` | Les réponses sont-elles bonnes ? |

## Unitaire — 337 tests, aucune dépendance

Tout est simulé : ni ChromaDB, ni NebulaGraph, ni LLM. La suite tourne en
quelques secondes sur une machine nue, et c'est ce qui tourne en intégration
continue.

Les fichiers les plus fournis disent où sont les pièges du projet :

| Fichier | Ce qu'il protège |
|---|---|
| `test_lexical.py` | Tokenisation et fusion RRF — la fusion se fait sur les **rangs**, jamais sur les scores, qui ne sont pas comparables entre moteurs. |
| `test_context_assembly.py` | Fenêtrage, sections voisines, assemblage du markdown soumis au LLM. |
| `test_affichage_sources.py` | Numérotation des citations et couleurs de pertinence côté frontend. |
| `test_postprocess.py` | Extraction des `[src:…]` — y compris les crochets à identifiants multiples, qui avaient fait perdre 27 citations sur 30. |
| `test_securite.py` | Traversée de chemin, échappement nGQL, comparaison de clé à temps constant. |
| `test_resilience.py` | Un store qui redémarre doit rester invisible : cache oublié, une seule reprise. |
| `test_coherence_depot.py` | Deux endroits qui doivent s'accorder et que rien ne forçait à s'accorder : la borne d'historique dupliquée dans le frontend (son image ne contient pas les schémas), et les versions épinglées par `Dockerfile.frontend` face à `requirements.txt`. Les deux ont réellement divergé. |
| `test_historique_soumis.py` | La profondeur d'historique soumise au LLM, par route. /chat/simple soumettait tout ce que le client envoyait là où les autres coupaient à six : la même conversation produisait deux prompts selon la route. |
| `test_llm_budget.py` | Le budget de la fenêtre de contexte : ce qui entre dans le prompt, ce qui en est écarté et par quel bout, et l'écart entre le prompt estimé et le `prompt_eval_count` réel. L'historique de conversation n'y figurait pas — c'est par là que le prompt dépassait `num_ctx`. Deux invariants y valent plus que les cas isolés : offrir plus de candidates ne doit jamais retirer une source retenue, et la troncature ne doit jamais laisser un `[src:ID]` amputé (balayé sur 1 250 budgets). La chaîne `on_fit` → état du graphe → `/answer` y est exercée sur le vrai `node_generate`, seule la couche HTTP étant simulée : deux mutations la cassaient en gardant la suite verte. |
| `test_capture_usage.py` | Le module de capture : les trois états de `retenue`, l'empreinte de configuration, la concurrence, et surtout l'absorption des pannes. |
| `test_purge_sessions.py` | La purge des sessions LangGraph : ce qu'elle supprime, et ce qu'elle annonce. Le checkpointer y est **réel** — un vrai `AsyncSqliteSaver` sur un fichier temporaire — et les assertions sont lues en SQL brut dans `checkpoints`. Un faux checkpointer ne lève pas `asyncio.InvalidStateError`, donc il ne prouve rien du défaut : c'est exactement ce montage-là qui l'a laissé vivre. Cinq des six tests sont rouges sur le code d'origine, dont celui qui confronte le nombre de suppressions ANNONCÉ au nombre RÉEL — « le journal annonce [1] suppression(s) alors qu'aucune n'a eu lieu ». Le sixième est un garde-fou, vert des deux côtés et c'est ce qu'on lui demande : une session en attente de sélection doit survivre à un redémarrage. |
| `test_index_lexical.py` | L'index BM25 face à un corpus qui bouge et à des requêtes concurrentes. Deux pièges de montage y sont évités. Le premier : un test « l'index finit construit » est vert des deux côtés d'un défaut de dimensionnement — ce qui voit la panne, c'est un test de **serrage**, qui compte les lectures du corpus (`assert 8 == 1` sur le code d'origine). Le second : les corpus de test comptent au moins **trois** documents, parce que l'IDF de BM25 vaut exactement zéro pour un terme présent dans 1 document sur 2, ce qui rend la recherche lexicale intestable à deux documents. |
| `test_absorptions.py` | Les absorptions d'exceptions resserrées par le lot 3, et le garde-fou qui les empêche de s'élargir. Cinq tests tombent si un `except` resserré redevient `except Exception`, ou si un journal redescend en `debug` ; d'autres gardent les cas que les resserrements doivent continuer de couvrir — un transport mort et un corps non-JSON restent des replis, pas des 500. **Le resserrement a lui-même introduit une régression, et son garde-fou est ici** : un corps qui est du JSON valide sans avoir la forme attendue faisait rendre 500 à /chat/start et /answer. Le garde couvre les quatre formes — `message` nul, chaîne, liste, et corps qui n'est pas un objet — et le fait **au niveau HTTP en plus du niveau unitaire** : c'est l'absence de try/except dans `node_rewrite` qui rendait la panne visible à l'utilisateur, et un test unitaire seul resterait vert le jour où quelqu'un en ajoute un autour du nœud. Il asserte le comportement, pas l'absence d'exception : la question d'origine est conservée et la traduction reste `None`, parce qu'une traduction VIDE entrée dans la fusion RRF serait pire que le 500. |
| `test_chronometrie.py` | La partition du temps par étage : son arithmétique, et surtout ce qui la fait mentir. Le test qui compte fait **régresser** la mesure — il verse un agrégat dans un étage et exige que le résidu devienne NÉGATIF et que le journal le dise. Borner le résidu à zéro le rendrait vert sur un tableau faux. Un second épingle la décision elle-même : `retrieval_ms` est un agrégat, et il tombe le jour où quelqu'un l'ajoute à `ETAGES` « pour compléter le tableau ». |
| `test_partition_etages.py` | La même partition, mais branchée sur les **vrais nœuds** : chaque étape simulée dort une durée qui lui est propre, ce qui permet d'exiger le SENS de l'attribution et pas seulement la présence d'un chiffre. Un `decomposer` correct branché sur rien publierait huit zéros et un résidu égal au total. Deux tests portent l'étage qui n'avait jamais été chronométré — la reconstruction par le graphe — dans les deux sens : elle coûte son temps même quand elle échoue, et elle tombe à zéro quand rien n'est reconstruit, ce que l'ablation doit lire. |
| `test_capture_branchement.py` | La capture vue de l'API : les deux phases jointes par `thread_id`, la sélection humaine distinguée des sections soumises, et une base en échec qui ne casse aucune requête. La colonne `dropped_contexts` y est exercée sur des sections qui dépassent réellement la fenêtre — seule la couche HTTP est simulée, le budget est celui du vrai `fit_prompt` : trois mutations la cassent, une par maillon de la chaîne `on_fit` → état → colonne. |

Deux leçons du lot 3, du même ordre que celles du lot 2 :

- **Un faux qui ne ressemble pas à la bibliothèque ne prouve rien de la
  bibliothèque.** Deux tests simulaient la panne d'Ollama en levant un
  `ConnectionError` intégré, qu'httpx ne lève jamais — il enveloppe le transport
  dans `httpx.TransportError`. Ils restaient donc verts sur n'importe quelle
  absorption, y compris la plus large, et devenaient rouges dès qu'on resserrait
  sur la vraie panne. Le resserrement les a révélés ; sans lui, ils auraient
  gardé pour toujours un `except Exception` qu'ils ne testaient pas.
- **Une phrase d'exhaustivité dans un document est un défaut en attente.** La
  table du balayage écrivait « les deux **seules** façons dont l'appel échoue
  sans que le code soit en cause ». Il y en avait trois, et la troisième — un
  corps JSON valide de forme inattendue — a fait rendre 500 à deux routes. La
  phrase n'a pas seulement décrit le défaut : elle l'a autorisé, en clôturant
  l'énumération que personne n'a plus rouverte.
- **Ce qui doit être asserté, c'est le disque, pas le compteur du code.** La
  purge des sessions journalisait « Sessions purgées : 1 » sans supprimer une
  ligne. Tout test qui aurait cru ce compteur aurait été vert. Les tests de
  `test_purge_sessions.py` ouvrent le fichier SQLite en lecture directe, et
  confrontent le nombre annoncé au nombre réellement supprimé.

Deux leçons de la revue du lot 2, qui valent au-delà de ses fichiers :

- **Un script n'est pas testé tant qu'il n'a pas été lancé comme une commande.**
  `usage_export.py` mourait sur `ModuleNotFoundError` dès la première ligne de
  `main()` ; les tests chargeaient le module par `importlib` et n'appelaient que
  ses fonctions. Un test en processus ne l'aurait pas vu davantage — pytest
  tourne depuis la racine, donc `src` y est déjà importable. Seul un
  **sous-processus, PYTHONPATH retiré**, reproduit la vraie invocation.
- **Une ligne écrite mérite d'être comparée entière.** Sept colonnes de
  `sources_proposees` étaient écrites sans qu'aucun test ne les garde : sabotées
  une à une, la suite restait verte. Comparer le dictionnaire complet coûte
  moins qu'une assertion par colonne, et n'oublie rien.

**`--strict-markers` et `asyncio_mode = "strict"` ne sont pas décoratifs.** Sans
eux, un test asynchrone mal marqué n'échoue pas : il *passe sans rien
exécuter*. Une suite verte qui ne teste rien est pire qu'une suite rouge.

Pour vérifier que ce garde-fou tient encore, écrire un test asynchrone qui
échoue et s'assurer qu'il échoue bien. S'il passe, le greffon ne fait plus son
travail.

## Intégration — 10 tests, stack requise

Ils existent parce que **trois des défauts les plus coûteux de ce projet
étaient invisibles en unitaire**, tous parce qu'ils vivaient dans l'écart entre
ce que le code croyait et ce que les services faisaient :

- une requête nGQL écrite à l'envers — `dst(edge)` sous `REVERSELY` renvoie le
  nœud de départ — qui rendait toute la reconstruction par le graphe
  inopérante, sans une seule erreur ;
- une arête renommée côté ingestion (`DESCRIBES` → `LINKED_TO`), dont l'échec
  était avalé et privait les illustrations de leur légende ;
- un checkpointer synchrone branché sur un flux asynchrone, qui faisait tomber
  toute l'interface en 500.

Aucun test simulé ne pouvait les voir : un faux ChromaDB répond ce qu'on lui a
dit de répondre.

**Sans la stack, ils sont ignorés, pas en échec.** Un test rouge faute
d'infrastructure ne dit rien sur le code, et apprend à ignorer le rouge.

```bash
make up && make test-integration
```

## Campagne — 138 questions, la seule mesure de qualité

`make eval` rejoue le jeu doré contre l'API réelle et compare à
`runs/reference.json`. C'est le seul niveau qui mesure si le système
**répond bien**, par opposition à *fonctionne*.

Les métriques et leur lecture sont dans
[rag_evaluation_strategy.md](rag_evaluation_strategy.md) ; les résultats et les
règles de comparaison dans [runs/README.md](../runs/README.md).

Trois règles apprises en se trompant :

1. Mesurer **après** le reranking — c'est ce qui atteint le LLM qui compte.
2. Vérifier ce que le `.env` impose : il surcharge les valeurs par défaut du
   code, et a déjà invalidé un balayage entier.
3. **Ne toucher à rien pendant une campagne.** Deux ont été faussées par un
   `docker compose build` lancé pendant qu'elles tournaient.

## Ce que rien ne teste

À dire franchement, parce que la couverture n'est pas la confiance :

- **La qualité des réponses n'est jugée par personne.** Le rappel mesure la
  recherche. Savoir si la reconstruction de section améliore la *réponse*
  demande un juge calibré, qui n'existe pas ici.
- **Le jeu doré n'est pas relu.** 138 questions générées, toutes
  `reviewed: false`. Aucun humain n'a confirmé qu'elles sont de vraies
  questions.
- **Le frontend n'a pas de tests de bout en bout.** Les fonctions d'affichage
  sont testées ; le parcours dans un navigateur ne l'est qu'à la main. Les deux
  derniers défauts de citation ont été trouvés à l'œil, pas par la suite.
- **Ni charge, ni concurrence.** Rien ne dit ce qui se passe à dix questions
  simultanées. Deux exceptions : les écritures de la capture d'usage sont
  testées à dix interactions concurrentes — c'est là qu'un défaut de
  transaction SQLite en faisait perdre jusqu'à six — et la construction de
  l'index lexical est testée à huit requêtes concurrentes, où elle se faisait
  huit fois. Ce sont deux points, pas une couverture de charge : aucun test ne
  fait passer une **question entière** en parallèle d'une autre.
- **Les deux boutons d'appréciation ne sont pas testés.** L'endpoint `/feedback`
  l'est ; le clic dans Streamlit ne l'est qu'à la main, comme le reste du
  frontend.
- **La reconstruction de l'index lexical est attendue, pas observée en
  situation.** `test_index_lexical.py` programme la reconstruction puis attend
  son fil (`join`). Cela prouve qu'elle a lieu et qu'elle n'a lieu qu'une fois ;
  cela ne prouve pas que les requêtes servies **pendant** qu'elle tourne
  répondent correctement. Ce point-là tient au remplacement atomique de l'état
  de l'index, relu, pas à un test.
- **L'écriture après le dernier événement SSE n'est vérifiée que de
  l'intérieur.** Le client de test tamponne la réponse : l'ordre est observé par
  un espion dans l'application, ce qui interdit d'écrire avant d'avoir répondu
  mais ne distingue pas « juste avant » de « juste après » le dernier
  événement. Cette position-là tient au point d'appel, relu, pas à un test.
