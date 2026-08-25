# Les tests, et ce qu'ils ne disent pas

Trois niveaux, qui répondent à trois questions différentes. Aucun ne remplace
les autres, et le troisième est le seul à parler de **qualité**.

| Niveau | Commande | Question à laquelle il répond |
|---|---|---|
| Unitaire | `make test` | La logique est-elle correcte ? |
| Intégration | `make test-integration` | Le système tient-il debout avec les vrais stores ? |
| Campagne | `make eval` | Les réponses sont-elles bonnes ? |

## Unitaire — 261 tests, aucune dépendance

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
| `test_capture_branchement.py` | La capture vue de l'API : les deux phases jointes par `thread_id`, la sélection humaine distinguée des sections soumises, et une base en échec qui ne casse aucune requête. |

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
  simultanées. Seule exception : les écritures de la capture d'usage sont
  testées à dix interactions concurrentes — c'est là qu'un défaut de
  transaction SQLite en faisait perdre jusqu'à six.
- **Les deux boutons d'appréciation ne sont pas testés.** L'endpoint `/feedback`
  l'est ; le clic dans Streamlit ne l'est qu'à la main, comme le reste du
  frontend.
- **L'écriture après le dernier événement SSE n'est vérifiée que de
  l'intérieur.** Le client de test tamponne la réponse : l'ordre est observé par
  un espion dans l'application, ce qui interdit d'écrire avant d'avoir répondu
  mais ne distingue pas « juste avant » de « juste après » le dernier
  événement. Cette position-là tient au point d'appel, relu, pas à un test.
