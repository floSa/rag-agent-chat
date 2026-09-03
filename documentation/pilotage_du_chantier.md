# Piloter le chantier d'audit et de refonte — `rag-agent-chat`

> Ouvert le **3 septembre 2026**, à la passation de
> [`rag-ingestion-pipeline`](https://github.com/floSa/rag-ingestion-pipeline).
> Le point d'entrée de l'autre côté est son `documentation/etat_des_lieux.md` :
> il se lit sans lancer le projet, et il est autosuffisant.
>
> Ce fichier-ci est le mandat du pilote **de ce côté**. Il porte l'état du
> chantier, le plan de lots, et les conventions. Le détail de chaque constat,
> ouvert ou fermé, vit dans [`axes_amelioration.md`](axes_amelioration.md).

---

## 1. Ce que le pilote est, et ce qu'il ne fait pas

Il **pilote**. Il n'écrit pas de code de production.

- il audite, il **mesure de ses mains**, il tranche les fusions, il tient le
  registre ;
- il écrit les prompts que l'utilisateur colle dans d'autres conversations. **Un
  prompt à la fois**, et il **nomme ET numérote** la conversation destinataire :
  `Conv' <n> <RÔLE-LOT>`. Le numéro ne se réutilise **jamais** ;
- il **ne fusionne jamais un lot avant son audit indépendant** — par une
  conversation qui n'en a écrit aucune ligne. Sur le dépôt jumeau : quinze
  passages, **quinze trouvailles matérielles**, y compris sur un lot qui n'avait
  produit aucun commit et sur un lot dont tous les chiffres étaient justes ;
- il **ne touche pas au pipeline d'ingestion.** Un défaut trouvé chez lui
  s'écrit et se rend : son registre est le site canonique et son pilote tranche.

## 2. Reprendre sur ce poste

### 2.1 Le garde-fou d'identité Git — et il n'existe pas encore ici

**Le distant est un dépôt personnel** : `floSa/rag-agent-chat`. Deux adresses
sont autorisées et elles seules :

- `florian.horellou@gmail.com`
- `florian_horellou@laposte.net`

**Vérifie toujours une identité sur l'ADRESSE, jamais sur le nom** : deux
identités portent le même nom, « Florian Horellou ». **Sur CE dépôt-ci**, sept
commits sont partis avec une adresse **professionnelle** `@aosis.net` ; il a
fallu réécrire les 165 commits de l'époque **puis détruire et recréer** le dépôt
GitHub, la liste des contributeurs ne se défaisant pas. Les trois mesures qui
établissent que c'est bien ici, et non sur le dépôt jumeau, sont au §4.1 du
registre. **Jamais de `--no-verify`.**

**Ce dépôt n'a AUCUN garde-fou armé**, et c'est le premier constat du chantier —
§4.1 du registre. Ce qui a été mesuré le 3 septembre 2026 est là-bas ; ce qui
suit est le geste.

L'identité a été posée par le pilote le 3 septembre 2026, sur l'adresse en
usage dans les 12 derniers commits :

```bash
git config user.name "Florian Horellou" && git config user.email "florian_horellou@laposte.net"
```

`extensions.worktreeConfig` n'est pas positionné (`mesuré`, 3 septembre 2026) :
`git config` écrit donc dans `.git/config`, **partagé par le dépôt et tous ses
arbres de travail**. Rien à refaire par arbre de travail.

**Mais l'identité seule ne garde rien** : elle se change d'une commande et rien
ne rougit. Le hook manque, et le porter est le premier travail du chantier
(§4.1). Tant qu'il n'est pas armé, **tout commit doit être précédé d'un
`git var GIT_AUTHOR_IDENT`** — sur l'adresse, jamais sur le nom.

### 2.2 La porte qualité

Il n'y a **pas de cible `make all`** sur ce dépôt (`mesuré`, 3 septembre 2026).
La porte est en deux gestes, et c'est ce que la CI appelle
(`.github/workflows/`) :

```bash
make lint && make test
```

`make lint` dépend de `typecheck` — les deux sont de l'analyse statique, et le
rattachement est délibéré : modifier le workflow exige un jeton avec le scope
`workflow`, que le jeton de push n'a pas, donc `make typecheck` ne tournerait
jamais en intégration continue sans lui.

`make test-integration` et `make eval` exigent la pile démarrée. **`make eval`
est hors service** — §4.3 du registre.

**La porte ne tourne PAS sur un arbre de travail neuf**, et c'est une trouvaille
du lot 1 : `which ruff mypy pytest` rend `rc=1` sur ce poste, aucun n'étant au
`PATH`. Un `make lint` depuis un arbre neuf échoue donc sur
`ruff: command not found`, et non sur une faute de code. Les outils sont épinglés
dans `requirements-dev.txt`. Sur un arbre neuf comme sur un poste nu :

```bash
uv venv --python 3.12 && uv pip install torch --index-url https://download.pytorch.org/whl/cpu && uv pip install -r requirements.txt -r requirements-dev.txt
```

### 2.3 Le `.env`

**Il n'y en a pas** (`mesuré`, 3 septembre 2026), et c'est ce qui empêche
l'agent de démarrer. `.env.example` est versionné et complet. Deux valeurs ne
peuvent pas se deviner depuis lui, et une d'elles y est **fausse pour ce
poste** — §4.2 du registre.

## 3. Le contrat avec le pipeline d'ingestion

Les cinq exigences dures, leur site canonique étant le §0 du registre du
pipeline. Ce tableau dit l'état **vu de ce côté**, et il ne recopie aucun
chiffre : chaque constat renvoie à son entrée.

| | L'exigence | État vu d'ici |
|---|---|---|
| **1** | modèle d'embedding `paraphrase-multilingual-MiniLM-L12-v2`, identique des deux côtés | ⚠️ **gardée d'un seul côté.** Le pipeline refuse de démarrer hors contrat ; **l'agent, qui LIT, n'a aucun garde** — et le pipeline lui tend déjà de quoi le construire. §4.4 |
| **2** | `element_id` déterministe, 10 hexadécimaux | ✅ tenue par le pipeline, et l'agent le valide (`^[a-f0-9]{10}$`, `graph_context.py`) |
| **3** | `source_path` est l'identité d'un document | ✅ tenue |
| **4** | `sequence` porte l'ordre, monotone | ✅ tenue — et **reproduite de mes mains** : §4.5 |
| **5** | `POST /reindex` en fin de pipeline | ⚠️ **non éprouvée.** Les deux moitiés s'accordent à la lecture ; rien ne l'a jamais prouvé en marche, l'agent ne tournant pas. C'est le lot 1 |

**Ce que mes mesures ont changé au contrat.** Le pipeline a **fermé** un point
que ce dépôt porte encore comme ouvert et qu'il lui redemande : la platitude du
graphe. Le graphe est désormais imbriqué, et l'agent ne le sait pas — c'est le
constat le plus large du chantier, §4.6.

## 4. L'état du poste — `mesuré` le 3 septembre 2026

**Tout ce qui suit est un ÉTAT DE POSTE : il périme. Mesure-le, ne le lis pas.**
Sur le dépôt jumeau, cette consigne a attrapé un poste qu'on croyait être le
poste d'origine, une colonne apparue dans le graphe pendant qu'un lot
travaillait, un démon rallumé trois fois tout seul, et un arbre de travail que
le pilote croyait avoir supprimé.

| | `mesuré` le 3 septembre 2026 |
|---|---|
| branches | **deux** hors `main` : `claude/audit-rag-agent-chat-e8de9d` (l'arbre du pilote) et `claude/conv21-lot1-identite-exigence5-3de29d` (lot 1, en vol). `main` = `origin/main` = `d526f6a`, arbre propre, seul `.claude/` non suivi |
| dernier commit du dépôt | **28 août 2026** — le dépôt est resté immobile pendant que le pipeline réingérait le 2 septembre. C'est la cause matérielle de §4.3 et §4.6 |
| identité git | **absente** avant le geste du §2.1 : `git var GIT_AUTHOR_IDENT` rendait `rc=1`. Armée depuis, sur `florian_horellou@laposte.net` |
| garde-fou d'identité | **absent** — §4.1 |
| historique | **167** commits à `d526f6a` (165 à `a6b9c0c`, avant l'ouverture du chantier), **deux adresses et elles seules** (91 + 76), **0** `@aosis.net`, **0** attribution à un assistant de génération de code. **Un compte de commits est un état de poste : il se borne à sa révision ou il ne s'écrit pas** — celui-ci a bougé de 2 en trois heures, et le lot 1 l'a relevé |
| porte qualité | à `d526f6a` : `ruff check src/ tests/ scripts/` → `rc=0` ; `mypy src/` → `rc=0`, 18 fichiers ; `pytest tests/unit/` → `rc=0`, **461 passés**, concordant avec `tests.md`. À `ff000f7` (lot 1, non fusionné) : `rc=0`, **479 passés** |
| tests désactivés | **0** `pytest.mark.skip`, **0** `xfail`. 3 `type: ignore` (frontière ChromaDB, `retriever.py`), 90 `noqa` presque tous `PLR2004` — antérieurs à ce chantier, non instruits |
| pile Docker | **trois** projets Compose : `rag-ingestion-pipeline` (9 services), `llm-service` (1), et **`elivie` (9, avec son propre Ollama)** — ce dernier ne touche ni `rag_network` ni `llm-net`, mais un second Ollama sur la machine est le genre de voisin qui explique une lenteur qu'on cherchera ailleurs (trouvé par le lot 1). Réseaux `rag_network` et `llm-net` présents |
| `dagster-daemon` | **arrêté** (`Exited (0)`), et il l'est resté pendant tout le lot 1, relevé à ses deux bouts. Mais « arrêté » n'est PAS une propriété stable : il a démarré **trois fois** sur le dépôt jumeau sans qu'aucune conversation le décide, cause jamais cherchée |
| les stores | ChromaDB `rag_documents`, **4 367** chunks ; NebulaGraph `rag_space`, **15 173** arêtes `PARENT_OF`, **23** documents. Concordant à l'unité avec la campagne de référence du pipeline |
| les LLM | `ollama-central` sert `gemma4:e4b` et `nomic-embed-text` — `gemma4:e4b` est bien celui qu'attend `.env.example` |

**Les gestes interdits, et ils viennent du pipeline :** ne renomme aucun fichier
de son corpus (le chemin entre dans le calcul des `element_id`) ; ne change pas
le modèle d'embedding d'un seul côté (les deux candidats rendent 384 dimensions,
c'est le **nom** qui discrimine) ; **ne réingère pas** et **ne démarre pas son
démon d'orchestration** — l'index actuel est l'antécédent de sa campagne de
référence, et ses capteurs sont livrés armés.

## 5. L'instrument de mesure — et lequel vaut quoi

Deux jeux de questions existent. **Ils ne valent pas la même chose, et l'un des
deux est hors service.**

| Le jeu | Où | Ce qu'il vaut aujourd'hui |
|---|---|---|
| **138 questions**, générées depuis le corpus | `tests/fixtures/golden_qa_generated.json` | **hors service** — il désigne un corpus qui n'est plus dans l'index. §4.3 |
| **30 questions**, écrites après l'ingestion | `documentation/campagnes/2026-09-02-jeu-de-questions.yaml` du pipeline | **le seul valide**, et il porte sa réserve : lis-la avant d'arbitrer quoi que ce soit |

**La réserve du jeu de 30, et elle n'est pas négociable.** Trente questions
prouvent que la chaîne fonctionne et montrent un défaut grossier. Elles **ne
suffisent pas à arbitrer un réglage** : un écart de deux points est du bruit.
Première mesure = contrôle de bon fonctionnement, jamais décision
d'architecture. Deux bornes sont mesurées de l'autre côté : la strate « de
suivi » rend 20 % **parce que la question est encodée sans son historique**
(60 % avec), et le corpus est **entièrement anglais**, donc l'axe « question
anglaise → document français » a disparu.

## 6. Le plan de lots

| | Le lot | État |
|---|---|---|
| **1** | armer le garde-fou d'identité (§4.1), puis démarrer l'agent et **prouver l'exigence 5** (§4.2) | distribué — `Conv' 21` |
| **2** | les **trois réserves de lecture de `sequence`** (§4.5), et le garde qui les tient | à distribuer |
| **3** | le garde du **modèle d'embedding** côté lecteur (§4.4) | à distribuer — peut rejoindre le lot 1 si son diff reste lisible |
| **4** | **rendre au pipeline** ce qu'il a fermé, et reprendre ce que la platitude justifiait (§4.6) | à distribuer |
| **5** | **trancher le sort du jeu doré** (§4.3) — décision de l'utilisateur avant tout lot | en attente de décision |

**Le rang 1 est un prérequis, pas un choix** : sans garde-fou, aucun commit de
ce chantier n'est protégé, et l'agent qui ne tourne pas bloque toute mesure.

## 7. L'ordre invariable d'un lot

1. lire le rapport ;
2. **faire auditer par une conversation qui n'en a écrit aucune ligne** ;
3. lire le diff soi-même et faire tourner la porte qualité **de ses mains, y
   compris sur le résultat de la fusion** — et **résoudre soi-même tout
   conflit** : sur le dernier lot du dépôt jumeau, la résolution naïve
   réintroduisait une date fausse que le lot venait de trouver ;
4. **alors seulement**, trancher la fusion ;
5. si fusion : `--no-ff`, **jamais `--ff-only`, jamais de rebase**. Puis
   vérifier qu'aucun projet Compose ni bind mount n'ancre l'arbre de travail
   avant de supprimer quoi que ce soit, supprimer la branche local **et**
   distant, retirer l'arbre — et **réarmer les garde-fous APRÈS ce retrait** ;
6. mettre le registre à jour ;
7. écrire le prompt du lot suivant, et **le relire contre `git`**, pas contre sa
   mémoire. Un prompt prêt à distribuer périme.

## 8. Comment on juge un lot

**Un garde ne se juge jamais à sa lecture, seulement à la mutation qui doit le
faire rougir.** On casse volontairement le code livré ; si le test reste vert,
le garde est décoratif. **Treize gardes décoratifs** ont été trouvés ainsi sur
le dépôt jumeau, dont trois par le lot qui venait de les écrire. Exige donc,
dans chaque rapport : **la mutation, le site, le `rc`, le nombre de rouges.** Et
**rouge d'abord** — le test échoue avant la correction, et les deux états sont
montrés.

**Une phrase ne rougit pas.** Une documentation fausse survit indéfiniment,
contrairement à un bug. D'où : chaque chiffre porte sa commande et sa date, avec
son étiquette `mesuré`, `calculé` ou `supposé` ; un chiffre n'a **qu'un site
canonique** ; et toute phrase du genre « le seul », « aucun », « les trois »,
« il n'y a plus » est soit **bornée**, soit **gardée par un test**.

**Aucun test désactivé.** Pas de `skip`, `xfail`, `type: ignore`, `noqa`, aucune
règle de linter relâchée, aucun `except` élargi sans justification écrite **au
site**. Si tu en as besoin, c'est la forme du code qu'il faut changer — et **une
règle relâchée pour satisfaire l'autre n'est pas une correction**.

**Aucune attribution à un assistant de génération de code.** Ni auteur, ni
committer, ni trailer `Co-Authored-By`, ni signature, ni en-tête — dans le code,
la documentation et les messages de commit. La règle vise l'**attribution du
travail** : un nom de branche créé par l'outillage n'en est pas une.

## 9. Comment on pilote

- **Un seul prompt à la fois, séquentiel.** Ne distribue jamais un prompt dont
  l'entrée dépend d'un rapport que tu n'as pas encore reçu.
- **Nomme ET NUMÉROTE la conversation destinataire en tête du message**, sous la
  forme `Conv' <n> <RÔLE-LOT>`. Le numéro est obligatoire et ne se réutilise
  **jamais**, même pour le même lot. Le routage a déraillé plusieurs fois sur le
  dépôt jumeau ; des prompts sont arrivés au mauvais endroit. Sois brutalement
  explicite.
- **Chaque prompt se termine par l'obligation d'écrire `TÂCHE TERMINÉE` en
  dernière ligne**, ou `TÂCHE BLOQUÉE — <raison>`. Sans ça, l'utilisateur ne
  sait pas si le message lui est destiné ou est destiné au pilote.
- **Une branche par lot en vol, jamais plus.** Une conversation qui répond à une
  question ne crée pas de branche. Un commit auquel il faut pouvoir revenir
  devient un **tag**, pas une branche.
- **Quand une conversation grossit, demande-lui un `/compact`** avant de lui
  envoyer la suite, en disant ce qu'elle doit **garder** — sa méthode et sa
  connaissance du dépôt — et ce qu'elle doit **jeter** : ses rapports, les
  diffs, les sorties de commandes. Les preuves sont dans le dépôt.
- **Encourage le désaccord argumenté dans chaque prompt**, noir sur blanc. Le
  pilote du dépôt jumeau a été renversé à chaque lot, chaque fois à juste titre.
- **N'annonce jamais le résultat attendu d'une mesure que tu commandes** — donne
  le mécanisme, pas le chiffre. Le pilote de l'autre dépôt l'a fait deux fois et
  s'est trompé une fois : un développeur moins rigoureux aurait cherché à
  satisfaire son attente.

## 10. Les pièges de mesure, payés par le dépôt jumeau

- **mesure `rc` du processus, jamais derrière un tube ni un `grep`** :
  `cmd 2>&1 | tail` rend le code de `tail`. Ce piège a produit la pire faute de
  l'autre chantier — un commit qui annonçait cinq corrections et n'en avait
  appliqué aucune ;
- **ne filtre pas la sortie d'une porte qualité** : un `grep` sur sa sortie a
  déjà masqué un échec ;
- **vérifie que le texte a changé avant de croire un « 0 rouge »**, et que
  l'arbre est propre avant de croire un rouge. Un `sed` qui ne matche rien
  ressemble à un garde qui ne voit rien ;
- **un code de retour peut répondre à une autre question que la tienne.**
  `git merge-tree <base> <a> <b>` rend `rc=0` et n'émet aucun marqueur même en
  cas de conflit ; c'est `git merge-tree --write-tree --messages` qui rend
  `rc=1` et le nomme ;
- **ne boucle jamais sur une liste de fichiers non protégée** — les noms du
  corpus portent des espaces, et deux développeurs s'y sont fabriqué un faux
  vert ;
- **fais tourner un balayage de graines dans un arbre DÉDIÉ**, jamais basculé
  pendant qu'il tourne : un harnais de mesure peut muter ce qu'il observe ;
- **`git checkout <branche> -- .` dans un arbre portant des commits écrase sans
  avertir.** Pour lire un fichier d'une autre révision :
  `git show <rev>:<fichier>`.

## 11. Les leçons qui ont trouvé les défauts

Elles viennent du dépôt jumeau, où elles ont tout trouvé. **Mets-les dans tes
prompts, pas seulement dans ta tête.**

- Un test « ça marche » est vert **des deux côtés** du défaut. Il faut un test
  qui fait **régresser** ce qu'on prétend garder. Un test « ça tient » est vert
  des deux côtés d'un défaut de dimensionnement ; seul un test de **serrage** le
  voit.
- **Asserte depuis le côté qui PRODUIT le comportement**, pas depuis celui qui
  le consomme. Un code de sortie documenté et justifié n'était asserté nulle
  part : le remplacer par 0 laissait 390 tests verts.
- Une **phrase d'exhaustivité** dans un document ou un docstring est un défaut
  en attente : elle clôt une énumération que personne ne rouvre.
- **Un test qui choisit lui-même son cas doit prouver qu'il l'a atteint.**
- **Un montage de test qui bouchonne trop haut rend intestable ce qu'il prétend
  vérifier. Mute le producteur, pas le consommateur.**
- **Deux erreurs qui se compensent se cachent mutuellement.**
- Tester le point d'entrée d'un script demande un **sous-processus**, pas un
  import. **Ce qu'un test n'importe pas, il ne teste pas.**
- **Un raisonnement juste sur un antécédent faux produit une conclusion fausse,
  et il se relit comme une preuve. Cherche l'antécédent avant d'auditer le
  raisonnement.** C'est exactement ce qui s'est passé ici : §4.6 est une famille
  entière de conclusions justes posées sur un antécédent devenu faux.
- **Une conclusion tirée d'un échantillon doit porter son périmètre**, ou elle
  sera lue comme universelle.
- **Une règle survit à son motif.** Quand du code — ou un store — change, rouvre
  les règles dont le seul motif était l'ancien état. §4.6 en porte deux.
- **Une mesure qui décide du plan doit laisser un artefact rejouable.**
- **La question la plus productive des deux dépôts : qu'est-ce que la
  documentation affirme que le code ne fait pas ?** Et sa sœur, qui a tout
  trouvé de ce côté-ci : **qu'est-ce que la documentation affirme que les STORES
  ne font plus ?**

## 12. Les erreurs de pilotage à ne pas refaire

Motif unique, et il vaut pour le pilote de ce côté aussi : **affirmer un
comportement de code depuis sa mémoire au lieu de relire.**

Celles que le dépôt jumeau a payées, et qui se transposent telles quelles :

- **Vérifier une identité d'auteur sur le nom et non sur l'adresse** — l'erreur
  qui a coûté un dépôt entier.
- **Fusionner un lot avant son audit indépendant.**
- **Renvoyer à un fichier qu'on n'a pas écrit.** Un artefact qu'on cite doit
  exister avant qu'on le cite.
- **Distribuer un prompt sans le relire contre l'état réel du dépôt.** Un prompt
  prêt à distribuer périme : relis-le contre `git`, pas contre ta mémoire.
- **Écrire une date sans la mesurer.** Neuf dates fausses ont été écrites d'un
  coup de l'autre côté. **Une date est une mesure comme une autre** — `date -u`
  ou `git log --date=short`.
- **Corriger une erreur sur la forme qu'on a cherchée, et la laisser vivre sous
  une autre.** Une correction bornée au motif qu'on a tapé n'est pas une
  correction : c'est un échantillon. Le geste juste est de mesurer le reste
  après avoir corrigé.
- **Affirmer dans un prompt un état de poste qu'on n'a pas mesuré.** Le mandat
  prescrit vingt fois « mesure l'état du poste au lieu de le lire » : **cette
  règle vaut aussi pour la main qui l'écrit**, et un prompt est le dernier
  endroit où placer une affirmation non mesurée, parce qu'il est lu par
  quelqu'un qui n'a pas de raison d'en douter.
- **Annoncer dans un prompt le résultat attendu d'une mesure, et se tromper.**
- **Accepter le verdict d'un auditeur sur sa sévérité.** Un rapport excellent
  peut sous-appeler sa propre trouvaille : lis ses faits, refais son
  raisonnement, et cote toi-même.
- **Livrer autre chose que la forme demandée.** Quand l'utilisateur nomme la
  forme du livrable, produis cette forme.

Celle que le pilote de ce côté a commise **au premier jour**, et qu'il consigne
parce qu'elle illustre la règle mieux qu'un principe :

- **Poser une hypothèse de défaut, et la commander comme un fait.** Le pilote a
  lu `_SIBLING_CANDIDATES = 5` sous un commentaire dont la prémisse est fausse,
  et en a conclu que la limite devait faire manquer des sections voisines. **La
  mesure l'a démenti** : simulée sur les 15 173 arêtes, la limite ne fait rien
  manquer, le premier frère en-tête étant toujours immédiatement adjacent
  (§4.6). Le commentaire est faux, la constante est saine. Si cette attente
  était partie dans un prompt, un développeur l'aurait « corrigée ».

**Traite tes propres affirmations comme des hypothèses.** Vérifie avant d'écrire
un chiffre. Relis le code avant d'affirmer ce qu'il fait. Et **quand un audit te
contredit avec une mesure, il a raison.**
