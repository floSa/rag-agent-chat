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

### 2.1 Le garde-fou d'identité Git — armé depuis le 3 septembre 2026

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

**Le garde-fou est armé depuis le 3 septembre 2026** (lot 1, `9596720`) : c'était
le premier constat du chantier, §4.1 du registre. **Un seul geste l'arme, et il
se lance DEPUIS LE CLONE PRINCIPAL :**

```bash
make install
```

Il installe les outils de la porte, puis arme les hooks **et vérifie qu'ils le
sont**, en sortant en erreur sinon. Il exige un `.venv` déjà monté — l'ordre est
celui du §2.2 : monter l'environnement, puis armer.

**Ce que le montage couvre**, `mesuré` : `git commit`, `git commit --amend` (y
compris un auteur interdit **hérité**, git exportant l'auteur du commit amendé
dans l'environnement du hook), `git commit --author=`, `git merge --no-ff` et
`git merge --squash`. **Ce qu'il ne couvre PAS**, `mesuré` et ouvert au registre :
`git revert`, `git cherry-pick`, `git rebase`, `git am` et **`git tag -a`** — ce
dernier laissant partir un *tagger* interdit alors que le §9 prescrit les tags.
Leur fermeture honnête est un hook `pre-push`, qui reste à trancher.

**Et il porte un drapeau que le dépôt jumeau n'a pas besoin** : sans
`--allow-missing-config`, le montage **briquerait ce dépôt**. La couche du
framework ouvre sa configuration en chemin **relatif**, et `.pre-commit-config.yaml`
n'existe sur **aucun** des 167 commits antérieurs à ce lot — contre 234 sur 235
chez le jumeau. Tout `git bisect`, tout HEAD détaché, tout arbre sorti à un
commit ancien serait refusé. Le drapeau rend muets les hooks du framework quand
leur configuration manque ; **il ne touche jamais la couche qui protège**, et
c'est vérifié dans les six cellules du croisement (§4.9).

Ce qui suit est le geste d'identité, qui reste manuel : le script n'y touche pas.

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

**MESURE LA PORTE DANS UN ENVIRONNEMENT MONTÉ PAR LE PROTOCOLE CI-DESSOUS,
jamais dans le `.venv` qu'un lot a laissé derrière lui.** Le pilote s'y est fait
prendre au lot 1 : il a mesuré « `rc=0`, 479 passés » en réutilisant le `.venv`
de l'arbre du lot — **le seul environnement du poste où ce vert existait**. Dans
l'environnement que la CI construit, le même arbre rendait `rc≠0` (§4.9). Un
`.venv` de lot porte ce que le lot y a installé, et c'est précisément ce que la
CI n'aura pas.

**La porte ne tourne PAS non plus sur un arbre de travail neuf**, et c'est une
trouvaille du lot 1 : `which ruff mypy pytest` rend `rc=1` sur ce poste, aucun n'étant au
`PATH`. Un `make lint` depuis un arbre neuf échoue donc sur
`ruff: command not found`, et non sur une faute de code. Les outils sont épinglés
dans `requirements-dev.txt`. Sur un arbre neuf comme sur un poste nu :

```bash
uv venv --python 3.12 && uv pip install torch --index-url https://download.pytorch.org/whl/cpu && uv pip install -r requirements.txt -r requirements-dev.txt
```

### 2.3 Le `.env`

**Il existe depuis le 3 septembre 2026**, écrit par le lot 1 dans le **clone
principal** — jamais dans un arbre de travail, parce que `docker-compose.yml`
monte `./prompts` et qu'un `up` lancé depuis un arbre l'ancrerait. Passé en
**`0600`** par le pilote (§4.10). `.env.example` est versionné et complet, mais
**il porte encore `MINIO_ROOT_USER=minioadmin` là où ce poste exige `admin`** :
ouvert, petit, sans garde — §4.2 du registre.

**Ne recopie le mot de passe MinIO dans aucun document, aucun commit, aucun
rapport.** Ce dépôt est **public**, et un secret a déjà fui une fois dans un
fichier de travail non nettoyé (§4.10).

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
| **5** | `POST /reindex` en fin de pipeline | ✅ **tenue et prouvée en marche** par le lot 1 — mesurée par le lot, puis **indépendamment par son audit sur l'agent vivant**, et gardée par un test que l'audit a mesuré seul garde de deux mutations du producteur. §4.2 |

**Ce que mes mesures ont changé au contrat.** Le pipeline a **fermé** un point
que ce dépôt porte encore comme ouvert et qu'il lui redemande : la platitude du
graphe. Le graphe est désormais imbriqué, et l'agent ne le sait pas — c'est le
constat le plus large du chantier, §4.6.

## 4. L'état du poste — chaque ligne porte SA date de mesure

**Tout ce qui suit est un ÉTAT DE POSTE : il périme. Mesure-le, ne le lis pas.**
Sur le dépôt jumeau, cette consigne a attrapé un poste qu'on croyait être le
poste d'origine, une colonne apparue dans le graphe pendant qu'un lot
travaillait, un démon rallumé trois fois tout seul, et un arbre de travail que
le pilote croyait avoir supprimé.

| | l'état, et la date à laquelle il a été relevé |
|---|---|
| branches | `mesuré` le **4 septembre 2026, après la fusion du lot 2** : `main` = **`db05162`**, **14 commits d'avance sur `origin/main`** — non poussé. **Une seule** branche hors `main` : `claude/audit-rag-agent-chat-eefc61`, l'arbre du pilote. Les **six** autres et leurs arbres ont été supprimés à la fusion, `.claude/worktrees/` ne porte plus aucun répertoire mort, et les garde-fous ont été **réarmés puis éprouvés** — adresse interdite → `rc=1` et HEAD immobile, adresse autorisée au même nom → `rc=0`. Aucune branche distante autre que `main`. *Relevé antérieur, avant fusion : cinq branches hors `main`, deux errantes* — `claude/connexion-coupee-551a87` et `claude/quirky-williamson-8fda89`, issues de sessions abandonnées, leurs arbres propres et sans travail à sauver. Les deux branches en vol du lot 2 : `claude/agent-graph-reading-140a97` (`9435657`) et `claude/conv26-repar2-blocants-0b3707` (`d5b2c3c`). Plus l'arbre du pilote, `claude/audit-rag-agent-chat-eefc61`. **La règle « une branche par lot en vol » est en dette de nettoyage, et elle se paie à la fusion du lot 2** |
| dernier commit du dépôt | **28 août 2026** — le dépôt est resté immobile pendant que le pipeline réingérait le 2 septembre. C'est la cause matérielle de §4.3 et §4.6 |
| identité git | **absente** avant le geste du §2.1 : `git var GIT_AUTHOR_IDENT` rendait `rc=1`. Armée depuis, sur `florian_horellou@laposte.net` |
| garde-fou d'identité | **armé** depuis le lot 1, `INSTALL_PYTHON` gravé vers le `.venv` du **clone principal** — donc stable. Vérifié de mes mains depuis l'arbre du pilote : adresse interdite → `rc=1`, HEAD immobile ; adresse autorisée → `rc=0`. Et le hook a tiré sur la fusion elle-même (« Identite d'auteur autorisee … Passed ») |
| historique | `mesuré` le **4 septembre 2026** : **184** commits à `7bcd346`, **deux adresses et elles seules** (216 + 152 occurrences auteur+committer), **0** `@aosis.net`, **0** attribution à un assistant. Relevé antérieur : **167** commits à `d526f6a` (165 à `a6b9c0c`, avant l'ouverture du chantier), **deux adresses et elles seules** (91 + 76), **0** `@aosis.net`, **0** attribution à un assistant de génération de code. **Un compte de commits est un état de poste : il se borne à sa révision ou il ne s'écrit pas** — celui-ci a bougé de 2 en trois heures, et le lot 1 l'a relevé |
| porte qualité | `mesuré` le **4 septembre 2026** sur `db05162` — le **résultat de la fusion**, pas seulement la branche — dans un arbre dédié monté par le protocole du §2.2 : `make lint` → `rc=0`, `make test` → `rc=0`, **520 passés**. Relevé du lot 1, à `9596720` : **486 passés** (461 avant lui). Le retard de `documentation/tests.md` est traité par le lot 2 — §4.13 |
| tests désactivés | `mesuré` le **4 septembre 2026** sur `d5b2c3c` : **0** `pytest.mark.skip`, **0** `xfail`, **3** `type: ignore`, **90** `noqa` dont **10** hors `PLR2004`. Tous antérieurs à ce chantier, non instruits. **Le lot 2 n'en ajoute aucun** — vérifié sur les lignes ajoutées de son diff, et `pyproject.toml`, `Makefile` et `.pre-commit-config.yaml` ne sont pas touchés |
| pile Docker | **trois** projets Compose : `rag-ingestion-pipeline` (9 services), `llm-service` (1), et **`elivie` (9, avec son propre Ollama)** — ce dernier ne touche ni `rag_network` ni `llm-net`, mais un second Ollama sur la machine est le genre de voisin qui explique une lenteur qu'on cherchera ailleurs (trouvé par le lot 1). Réseaux `rag_network` et `llm-net` présents |
| `dagster-daemon` | ⚠️ **EN MARCHE**, `mesuré` le **4 septembre 2026** (`Up About an hour`) — là où le relevé du 3 septembre le donnait `Exited (0)` aux deux bouts du lot 1. **C'est la quatrième fois que ce démon se rallume sans qu'aucune conversation le décide**, et la cause n'a jamais été cherchée. Ce chantier n'y touche pas : le démon est chez le pipeline, ses capteurs sont livrés armés, et son état est **rendu** à son pilote — §4.16. Ce qui protège l'index en ce moment est le défaut §4.32.a du pipeline, pas une décision |
| les stores | ChromaDB `rag_documents`, **4 367** chunks ; NebulaGraph `rag_space`, **15 173** arêtes `PARENT_OF`, **23** documents. Concordant à l'unité avec la campagne de référence du pipeline |
| les LLM | `ollama-central` sert `gemma4:e4b` et `nomic-embed-text` — `gemma4:e4b` est bien celui qu'attend `.env.example` |
| l'agent | `mesuré` le **4 septembre 2026** : `rag-agent-api` **en marche et `healthy`**, `GET /health` → HTTP **200**, `status: ok`, les quatre dépendances à `true`. Le port est **8011** sur l'hôte, jamais 8000. `POST /reindex` est **exposé** — vérifié dans l'`openapi.json` servi, aux côtés de `/answer`, `/search`, `/context/{element_id}`, `/sources`, `/media/{object_name}`, `/feedback` et des trois routes `/chat/*` |

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
| **1** | armer le garde-fou d'identité (§4.1), puis démarrer l'agent et **prouver l'exigence 5** (§4.2) | ✅ **fusionné** `9596720` — livré (`Conv' 21`), audité (`Conv' 22`), réparé (`Conv' 23`), fusion tranchée par le pilote après vérification de ses deux gardes par mutation |
| **2** | les **trois réserves de lecture de `sequence`** (§4.5), et le garde qui les tient | ✅ **fusionné** `db05162` — livré (`Conv' 24`), audité (`Conv' 25`, 8 trouvailles dont 2 bloquantes), réparé (`Conv' 26`), **sa réparation auditée à son tour** (`Conv' 27`, 1 bloquante), réparée une seconde fois (`Conv' 28`). Fusion tranchée par le pilote après vérification des deux directions dangereuses du garde — §4.18. **Trois audits, trois trouvailles matérielles** |
| **3** | le garde du **modèle d'embedding** côté lecteur (§4.4) | **à distribuer — c'est l'action suivante**, et **le risque vivant du chantier** : une panne silencieuse qui rend des passages plausibles et faux. Les deux candidats rendent 384 dimensions, donc aucune sonde de forme ne la voit ; c'est le **nom** qui discrimine |
| **4** | **rendre au pipeline** ce qu'il a fermé, et reprendre ce que la platitude justifiait (§4.6) | à distribuer |
| **5** | **régénérer le jeu doré sur le corpus actuel ET adopter les 30 questions du pipeline** (§4.3), puis établir une **nouvelle campagne de référence** | ✅ **décidé** le 3 septembre 2026 par l'utilisateur. À distribuer **après** les lots de gardes : mesurer sur un agent dont les gardes ne sont pas posés ferait porter à la campagne le bruit des corrections à venir |

**Le rang 1 est un prérequis, pas un choix** : sans garde-fou, aucun commit de
ce chantier n'est protégé, et l'agent qui ne tourne pas bloque toute mesure.

### 6.1 Le journal des conversations — un numéro ne se réutilise JAMAIS

**Ce journal est le seul état du chantier qui ne vive pas dans `git`, donc le
seul qui puisse être perdu — et il l'a été.** `Conv' 20`, la conversation de
pilotage ouverte le 3 septembre 2026 à 09:08 UTC, a été **supprimée par erreur**
le 4 septembre vers 07:20 UTC ; son transcript a été récupéré et son état de
sortie reversé ici. La leçon est écrite au §12 : *tiens le journal dans le
dépôt, pas dans la conversation.*

| `Conv'` | Rôle | Sortie |
|---|---|---|
| **20** | AGENT-1 — pilote | perdue le 4 septembre 2026, reprise par `Conv' 20-bis` |
| **21** | LOT-1 — garde-fou d'identité + exigence 5 | 2 commits, `e80969a` + `ff000f7` |
| **22** | AUDIT-1 — audit du lot 1 | rapport rendu. Réserve consignée : le rapport du lot ne lui est pas parvenu |
| **23** | REPAR-1 — le bloquant du lot 1 | rapport rendu, porte verte à 486 passés |
| **24** | LOT-2 — lecture du graphe par l'agent | 5 commits, `9435657`, 496 passés |
| **25** | AUDIT-2 — audit du lot 2 | 18 chiffres reproduits, 8 trouvailles, 2 bloquantes — §4.14 |
| **26** | REPAR-2 — fermer T1, T2 et le maillon | `d5b2c3c`, porte verte à 502 passés, rien poussé |
| **20-bis** | AGENT-1 (reprise) — pilote | tranche T2 de ses mains — §4.15 — et distribue `Conv' 27` |
| **27** | AUDIT-REPAR-2 — audit de la réparation du lot 2 | 8 mutations + 17 chiffres reproduits, **aucune mesure du pilote renversée** ; 1 bloquante (B1), 1 sérieuse (A1), 6 mineures — §4.17. Recommandation : fusionner après correction |
| **28** | REPAR-3 — fermer B1, A3 et A6 sur la branche du lot 2 | `e33c076` : bouchon **fail-closed**, 11 mutations / 11 rouges, 520 passés, **zéro ligne de production touchée**. Vérifié par le pilote, fusionné — §4.18 |

| **29** | LOT-3 — le garde du modèle d'embedding côté lecteur | `c5c38d5`, 3 commits, **non poussés**. 539 passés (+19), un **témoin inerte** dans sa batterie, zéro désactivation. Son rapport tabule **douze** mutations là où son §4.4 en annonce **onze** — écart relevé par l'audit, à trancher par `Conv' 31`. Vérifié par le pilote — §4.19 |

| **30** | AUDIT-3 — audit du lot 3 | **21 mutations dont 2 témoins**, 18 mordent. **2 bloquantes** (B1, B2), 1 mesure du pilote **renversée** (N1), 9 non bloquantes — §4.20. Recommandation : fusionner après correction |
| **31** | REPAR-4 — fermer B1, B2, N1 et N2 sur la branche du lot 3 | distribué le 4 septembre 2026 |

**Prochain numéro libre : 32.**

**Le compte des audits, au bout de onze conversations : quatre audits
indépendants, quatre trouvailles matérielles bloquantes.** Aucun lot de ce
chantier n'a été fusionné sans qu'un audit y trouve quelque chose, et le pilote a
été borné, corrigé ou **renversé** à chacun d'eux.

**Ce que ce journal apprend sur la méthode, au bout de neuf conversations.**
Trois audits indépendants, **trois trouvailles matérielles**, dont deux sur du
code que le lot précédent venait de réparer en croyant fermer le sujet. Le
compte du dépôt jumeau était de quinze sur quinze ; celui-ci est de trois sur
trois. **Aucun lot de ce chantier n'a encore été fusionné sans qu'un audit
indépendant y trouve quelque chose**, et le pilote a été borné ou corrigé à
chacun d'eux — la dernière fois sur sa propre phrase « fail-closed par
construction » (§4.17).

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
   distant, retirer l'arbre — et **relancer `make install` DEPUIS LE CLONE
   PRINCIPAL**. Ce point a porté une condition fausse jusqu'au 3 septembre 2026 :
   il disait « réarmer **après** ce retrait ». Ce qui grave le chemin absolu du
   `.venv` dans `.git/hooks`, c'est **l'arbre depuis lequel on lance
   l'installation**, pas celui qu'on retire — l'audit du lot 1 l'a mesuré
   (§4.9). Et sache qu'entre le retrait et la réinstallation s'ouvre une
   **fenêtre où tout commit du clone et de tous ses arbres est refusé**, sur un
   message qui ne nomme ni la cause ni le remède. C'est *fail-closed*, donc sans
   danger pour l'historique ;
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

Celles que la reprise du 4 septembre 2026 a ajoutées, et chacune a coûté
quelque chose :

- **Une mutation mal posée rend un faux verdict de garde décoratif — et le
  garde-fou contre le faux zéro ne l'attrape pas.** Le harnais du pilote avait
  rendu, sur la réparation du lot 2, `RC_T2=0` et zéro rouge, avec la mutation
  **bien** posée au sens du dépôt : `git diff --numstat` montrait 4 lignes
  ajoutées, donc le texte avait changé. Le verdict — *garde décoratif, ne pas
  fusionner* — était **faux** : remesuré à la main, la même famille de mutation
  rend `rc=2` et 5 rouges (§4.15). *Vérifier que le texte a changé n'est que la
  moitié du garde-fou : il faut vérifier que le **comportement** a changé.* Une
  mutation dont la borne n'ampute rien — un encadrement permissif, un
  `WHERE seq >= 0` — réécrit la requête sans rien retirer au résultat, et son
  vert se lit exactement comme un garde creux. **Le geste juste : mesurer la
  mutation des DEUX côtés de la correction.** Un vert avant et un rouge après
  prouvent quelque chose ; un vert seul ne distingue pas un garde creux d'une
  mutation inerte.
- **Un `rc` peut appartenir à un autre programme que celui qu'on croit
  interroger.** `make test` rend **2** quand une recette échoue, là où `pytest`
  rend **1**. Deux mesures justes du même échec se lisent donc comme un
  désaccord, et le pilote a d'abord lu la batterie du réparateur — huit `rc=2` —
  comme suspecte. *Nomme le programme dont tu relèves le code de retour.*
- **Le journal des conversations est le seul état du chantier qui ne vive pas
  dans `git`.** `Conv' 20` a été supprimée par erreur, et avec elle la seule
  trace des numéros consommés, des rapports reçus et des mesures non encore
  reversées. Le dépôt a survécu sans une égratignure ; le pilotage, non. **Le
  journal vit désormais au §6.1 de cette page**, et toute mesure reçue d'un lot
  se reverse au registre **avant** d'écrire le prompt suivant, pas après.

Celles que le lot 3 a ajoutées, et la première est une erreur du pilote dans
son propre prompt :

- **Poser un choix dont toutes les branches sont fausses.** Le pilote demandait
  au lot 3 où son garde devait vivre : « au démarrage, dans `/health`, ou aux
  deux ». **Le lot a contesté la question, et il avait raison : aucune des trois
  n'est un garde — les trois sont des rapports.** Un rapport ne protège de rien
  entre le moment où la divergence devient lisible et celui où quelqu'un la lit.
  Le garde devait vivre sur le chemin qui PRODUIT le comportement — la recherche
  dense — et le démarrage comme `/health` n'en sont que la voix. *Un choix bien
  posé nomme le critère, pas les options* : la question juste était « quel site
  produit le comportement à empêcher ? », et elle avait une seule réponse.
- **Commiter avant de muter.** Le lot a écrasé une correction non commitée de
  `README.md` en restaurant ce fichier après une mutation. Détectée et refaite,
  sans dégât — et la leçon est générale : une batterie de mutations restaure par
  `git checkout --`, qui ne distingue pas ce qu'on voulait garder de ce qu'on
  voulait défaire. **Le travail se commite d'abord, on mute ensuite.**
- **Un rouge « le symbole n'existe pas » n'est pas un rouge de comportement.**
  Le lot a qualifié son propre rouge-d'abord de faible et renvoyé à sa table de
  mutations comme preuve réelle. C'est la bonne lecture : un `AttributeError` sur
  une fonction pas encore écrite prouve que le test appelle quelque chose, pas
  qu'il discrimine quoi que ce soit.
- **Vérifier une affirmation de comportement d'OUTIL comme on vérifie le code.**
  Le lot justifiait un trou accepté par « rendre 503 sur `/health` ferait
  redémarrer le service en boucle ». **Mesuré faux** : un healthcheck en échec ne
  redéclenche pas un conteneur sous Docker Compose, `restart:` répondant à la
  sortie du processus et non à la santé (§4.19). Le raisonnement était de bonne
  foi et bien écrit ; son antécédent était faux. *La règle « cherche l'antécédent
  avant d'auditer le raisonnement » ne vaut pas que pour le code du dépôt : elle
  vaut pour ce qu'on croit savoir de Docker, de pytest et de git.*

**Traite tes propres affirmations comme des hypothèses.** Vérifie avant d'écrire
un chiffre. Relis le code avant d'affirmer ce qu'il fait. Et **quand un audit te
contredit avec une mesure, il a raison.**
