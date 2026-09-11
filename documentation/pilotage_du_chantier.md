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

`make test-integration`, `make eval`, `make eval-controle` et
`make verifier-les-ancrages` exigent la pile démarrée. **`make eval` est de
nouveau en service depuis le 8 septembre 2026**, sur un jeu régénéré et prouvé
contre les stores — §4.3 du registre. Il **dépend** de
`make verifier-les-ancrages`, et c'est délibéré : un rappel mesuré sur un jeu qui
désigne le vide rend 0 sans dire pourquoi.

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
| **1** | modèle d'embedding `paraphrase-multilingual-MiniLM-L12-v2`, identique des deux côtés | ✅ **tenue et gardée des DEUX côtés** depuis le lot 3, fusionné le 7 septembre 2026 (`c5f9a54`). Le lecteur confronte son réglage à l'estampille de la collection **avant chaque recherche dense**, refuse aussi l'estampille absente, et rend **503** sans avoir chargé le moindre modèle. Quatre audits indépendants — §4.27
| **2** | `element_id` déterministe, 10 hexadécimaux | ✅ tenue par le pipeline, et l'agent le valide (`^[a-f0-9]{10}$`, `graph_context.py`). **Ce que ce dépôt en promettait était faux, et c'est corrigé** : `pour_le_pipeline_ingestion.md` écrivait que le déterminisme fait « survivre le jeu doré à une réingestion ». Il fait survivre un jeu à une réingestion **du même corpus** ; rien ne le fait survivre au **remplacement** d'un corpus, et aucune convention d'identifiant ne le pourrait. Corrigé au site et **gardé** contre son retour — §4.3 |
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
| dernier commit du dépôt | **28 août 2026** — le dépôt est resté immobile pendant que le pipeline réingérait le 2 septembre. C'est la cause matérielle de §4.3 et §4.6. **§4.3 est fermé depuis le 8 septembre 2026** ; §4.6 reste ouvert, c'est le lot 4 |
| les jeux de questions | `mesuré` le **8 septembre 2026**, contre les deux stores en service : **130 / 130** ancrages du jeu de réglage et **44 / 44** ancrages du jeu de contrôle existent dans ChromaDB **et** dans NebulaGraph, **0** désaccord. Relevé antérieur, sur le jeu retiré : **0 / 129**. L'instrument est `scripts/verifier_les_ancrages.py`, le bilan est versionné à `runs/2026-09-08-ancrages.json`, et c'est un **état de store** — il périme à la prochaine réingestion, rejoue-le |
| `detect-secrets` | `mesuré` le **8 septembre 2026**, `detect-secrets-hook` v1.5.0 sur `git ls-files` : **2** détections, contre **36** avant le lot 5 — dont **34** dans le seul jeu de questions en JSON, désormais retiré. Le hook **n'est pas armé** sur ce dépôt et `.pre-commit-config.yaml` dit pourquoi ; il est désormais **armable**, ce qu'il n'était pas |
| identité git | **absente** avant le geste du §2.1 : `git var GIT_AUTHOR_IDENT` rendait `rc=1`. Armée depuis, sur `florian_horellou@laposte.net` |
| garde-fou d'identité | **armé** depuis le lot 1, `INSTALL_PYTHON` gravé vers le `.venv` du **clone principal** — donc stable. Vérifié de mes mains depuis l'arbre du pilote : adresse interdite → `rc=1`, HEAD immobile ; adresse autorisée → `rc=0`. Et le hook a tiré sur la fusion elle-même (« Identite d'auteur autorisee … Passed ») |
| historique | `mesuré` le **4 septembre 2026** : **184** commits à `7bcd346`, **deux adresses et elles seules** (216 + 152 occurrences auteur+committer), **0** `@aosis.net`, **0** attribution à un assistant. Relevé antérieur : **167** commits à `d526f6a` (165 à `a6b9c0c`, avant l'ouverture du chantier), **deux adresses et elles seules** (91 + 76), **0** `@aosis.net`, **0** attribution à un assistant de génération de code. **Un compte de commits est un état de poste : il se borne à sa révision ou il ne s'écrit pas** — celui-ci a bougé de 2 en trois heures, et le lot 1 l'a relevé |
| porte qualité | ✅ **VERTE sur `main`**, `mesuré` le **8 septembre 2026** par LOT-DETTE sur `main` = `origin/main` = **`c5028d6`**, dans son arbre de travail, `rc` du **processus** non filtré : `make lint` → `rc=0`, `make test` → `rc=0`, **603 passés**. *Le cadrage annonçait ce chiffre et il était juste ; il a été remesuré parce qu'un chiffre recopié n'est pas une mesure.* Relevé antérieur : ⚠️ **ROUGE**, le même jour, sur `4eedb2a` — `make test` → `rc=2`, 1 échec / 561 passés, sur le fil de détente d'occurrences du modèle anglais, à **6** trouvées pour **5** autorisées, la sixième étant la phrase du §4.27 qui racontait son propre déclenchement. **Fermé par le lot 5, et la cause structurelle par LOT-DETTE : l'instrument est désormais DÉDOUBLÉ** — le fil compte les occurrences et se nomme comme tel, un garde neuf porte la sûreté sur les AFFECTATIONS et ne rougit sur aucun récit (§4.29). Avant : 562 au lot 3, 520 au lot 2, 486 au lot 1 (461 avant lui) |
| tests désactivés | `mesuré` le **4 septembre 2026** sur `d5b2c3c` : **0** `pytest.mark.skip`, **0** `xfail`, **3** `type: ignore`, **90** `noqa` dont **10** hors `PLR2004`. Tous antérieurs à ce chantier, non instruits. **Le lot 2 n'en ajoute aucun** — vérifié sur les lignes ajoutées de son diff, et `pyproject.toml`, `Makefile` et `.pre-commit-config.yaml` ne sont pas touchés |
| pile Docker | **trois** projets Compose : `rag-ingestion-pipeline` (9 services), `llm-service` (1), et **`elivie` (9, avec son propre Ollama)** — ce dernier ne touche ni `rag_network` ni `llm-net`, mais un second Ollama sur la machine est le genre de voisin qui explique une lenteur qu'on cherchera ailleurs (trouvé par le lot 1). Réseaux `rag_network` et `llm-net` présents |
| `dagster-daemon` | ⚠️ **EN MARCHE**, `mesuré` le **9 septembre 2026 à 08:40 UTC** par le pilote : `Up 2 hours`. **CE SITE EST LE SEUL CANONIQUE, et il ne porte PLUS de numéro de relevé** — il en portait trois qui ne composaient pas (« sixième relevé en marche », « quatrième fois qu'il se rallume », et « huitième relevé » au §12), dont deux dans cette cellule, l'ancienne phrase ayant survécu à celle qui la remplaçait. Un numéro qu'on ne peut pas reconstruire depuis le registre est un numéro qui dérive : **la suite des relevés remplace le compte.** `Exited (0)` aux deux bouts du lot 1 le **3 septembre 2026** ; `Up About an hour` le **4** ; `Up 5 hours` aux deux bouts du lot 5 puis du lot dette le **8** ; `Up 7 hours` à la fin du lot 6 le **8** ; `Up 2 hours` le **9** à 08:40 UTC ;
`Up 3 hours` le **9 à 10:07 UTC**, relevé par le lot 7 — **cohérent avec le
relevé précédent** : une heure de plus au compteur pour une heure et demie
écoulée, donc aucun redémarrage entre les deux, et les onze autres conteneurs de
l'hôte sont tous à `Up 3 hours`, ce qui **confirme** la lecture d'un redémarrage
de l'hôte plutôt qu'un rallumage propre à Dagster. Il a donc été trouvé **arrêté un seul jour, le 3 septembre, et en marche les trois autres**. **Et une mesure qui borne le récit** : le 9 septembre, `rag-agent-api` est lui aussi à `Up 2 hours` alors qu'il était à `Up 7 hours` la veille — **les deux conteneurs ont redémarré ensemble**, ce qui désigne un redémarrage de l'hôte ou du démon Docker et non un rallumage propre à Dagster. Les rallumages antérieurs n'ont jamais été instruits ; celui-ci a une cause plus simple que celle que ce site supposait. Ce chantier n'y touche pas : le démon est chez le pipeline, ses capteurs sont livrés armés, et son état est **rendu** à son pilote — §4.16. Ce qui protège l'index en ce moment est le défaut §4.32.a du pipeline, pas une décision |
| les stores | ChromaDB `rag_documents`, **4 367** chunks ; NebulaGraph `rag_space`, **15 173** arêtes `PARENT_OF`, **23** documents. Concordant à l'unité avec la campagne de référence du pipeline |
| les LLM | `ollama-central` sert `gemma4:e4b` et `nomic-embed-text` — `gemma4:e4b` est bien celui qu'attend `.env.example` |
| l'agent | `mesuré` le **8 septembre 2026** : `rag-agent-api` **en marche et `healthy`**, `GET /health` → HTTP **200**, `status: ok`. **`index_lexical` était à `false`** au premier relevé et est passé à `true` après la première recherche : l'index BM25 se construit **paresseusement**, donc un `/health` lu juste après un redémarrage annonce une recherche amputée qui ne l'est pas — la première recherche la construit synchroniquement. Réglages du chemin mesuré par la campagne : `HYBRID_SEARCH=true`, `QUERY_REWRITE=true`, `FETCH_K=50`, `RETRIEVAL_TOP_K=50`, `RERANK_TOP_K=10`, `AUTO_SELECT_TOP_K=3`, fenêtre graphe ±6 / ±3, `FULL_TEXT_FROM_VECTORS=true`. Relevé antérieur, le **4 septembre 2026** : mêmes quatre dépendances à `true`. Le port est **8011** sur l'hôte, jamais 8000. `POST /reindex` est **exposé** — vérifié dans l'`openapi.json` servi, aux côtés de `/answer`, `/search`, `/context/{element_id}`, `/sources`, `/media/{object_name}`, `/feedback` et des trois routes `/chat/*` **LA TRAPPE EST FERMÉE PAR LOT-DETTE** : `scripts/evaluate.py` chauffe l'index avant la première question puis **vérifie**, et **refuse la campagne en 2** si `/health` n'annonce toujours pas `index_lexical: true` — un agent qui ne répond pas du tout reste un **1**, pas un refus, et le motif de cette distinction est au site (§4.29). `mesuré` de nouveau à la fin de LOT-DETTE : `rag-agent-api` `Up 5 hours (healthy)`, `status: ok`, les **quatre** services à `true`, `index_lexical` compris. |

**Les gestes interdits, et ils viennent du pipeline :** ne renomme aucun fichier
de son corpus (le chemin entre dans le calcul des `element_id`) ; ne change pas
le modèle d'embedding d'un seul côté (les deux candidats rendent 384 dimensions,
c'est le **nom** qui discrimine) ; **ne réingère pas** et **ne démarre pas son
démon d'orchestration** — l'index actuel est l'antécédent de sa campagne de
référence, et ses capteurs sont livrés armés.

## 5. L'instrument de mesure — et lequel vaut quoi

Deux jeux de questions existent. **Ils ne valent pas la même chose, et l'un des
deux est hors service.**

**`mesuré` le 8 septembre 2026 par le lot 5 — l'état ci-dessous a changé, et les
deux jeux hors service ont été RETIRÉS du dépôt.**

| Le jeu | Où | Ce qu'il vaut aujourd'hui |
|---|---|---|
| **138 questions régénérées** sur le corpus en service | `tests/fixtures/golden_qa_generated.yaml` | ✅ **le jeu de RÉGLAGE**, cible de `make eval`. **130 / 130** ancrages présents dans ChromaDB **et** NebulaGraph, `mesuré` et versionné à `runs/2026-09-08-ancrages.json`. `reviewed: false` partout — c'est du **silver** |
| **30 questions**, écrites après l'ingestion | `tests/fixtures/jeu_de_questions_pipeline.yaml`, transposé de `documentation/campagnes/2026-09-02-jeu-de-questions.yaml` du pipeline, qui reste le **site canonique** | ✅ **le jeu de CONTRÔLE**, cible de `make eval-controle`. **44 / 44** ancrages présents dans les deux stores. Sa réserve voyage dans le fichier et un test refuse qu'elle en sorte |
| ~~138 questions générées le 3 août 2026~~ | ~~`tests/fixtures/golden_qa_generated.json`~~ | ❌ **RETIRÉ.** 0 / 129 ancrages dans le graphe, et **34** des 36 détections `detect-secrets` du dépôt |
| ~~15 questions écrites à la main~~ | ~~`tests/fixtures/golden_qa.json`~~ | ❌ **RETIRÉ, et il était le `--golden` par DÉFAUT.** **13** de ses 15 questions étaient à réponse — les deux autres, `Q-010` et `Q-011`, sont des abstentions, et « 15 à réponse » était faux de deux (`mesuré`, trouvaille N8) — et portaient **0** `gold_element_ids` : toutes ses métriques de rappel valaient `None`, ce qui se lit « sans objet » et non « cassé » — plus silencieux encore que le jeu de 138. Trouvé par un garde du lot 5 |

**AUCUNE CAMPAGNE NE SE LANCE SANS SON ANTÉCÉDENT.** `make eval` et
`make eval-controle` **dépendent** de `make verifier-les-ancrages`, qui confronte
les deux jeux aux stores en lecture seule et sort en 1 au premier désaccord. Un
rappel mesuré après son rouge ne veut rien dire.

**Et le `--compare` a un second garde, parce que le premier ne voyait pas le pire
cas.** `generate_golden.py` numérote dans l'ordre de génération : deux jeux écrits
sur deux corpus portent les MÊMES identifiants de questions, et le refus sur
désaccord de jeu ne les distingue pas. Une campagne inscrit donc
`empreinte_des_ancrages`, et son **absence** est refusée au même titre qu'une
divergence — les huit campagnes de `runs/` antérieures au 8 septembre 2026 sont
retirées comme cibles. §4.3.

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
| **3** | le garde du **modèle d'embedding** côté lecteur (§4.4) | ✅ **fusionné** `c5f9a54` — livré (`Conv' 29`), audité (`Conv' 30`, 2 bloquantes), réparé (`Conv' 31`), réaudité (`Conv' 32`, 1 bloquante), réparé (`Conv' 33`), audité en **étroit** sur la couche async (`Conv' 34`, 1 bloquante), réparé (`Conv' 35`). **Quatre audits, quatre trouvailles bloquantes, aucune régression fonctionnelle** — §4.27. Fusion tranchée par le pilote sous le **critère amendé** du §4.18 |
| **4** | **rendre au pipeline** ce qu'il a fermé, et reprendre ce que la platitude justifiait (§4.6) | **définition TRANCHÉE** le 9 septembre 2026 par l'utilisateur, sur mesure du pilote : **(C) remontée aux oncles**, bornée au document, et le **voisin réel en lecture côté par côté**. L'élargissement que le §4.6 suggérait — le voisin en ordre de lecture — est **désavoué par la mesure** : +2 en-têtes, et **191 dégénérescences**. À distribuer dès que `Conv' 43` a rendu, avec deux réserves écrites au §4.6 : ces chiffres n'ont pas encore d'instrument rejouable, et la qualité n'est pas mesurée |
| **5** | **régénérer le jeu doré sur le corpus actuel ET adopter les 30 questions du pipeline** (§4.3), puis établir une **nouvelle campagne de référence** | ✅ **fusionné** `744c2c8` — livré (`Conv' 36`), audité (`Conv' 37`, **zéro bloquante**, 8 non bloquantes). **La mesure de qualité du dépôt était morte ; elle vit, et en deux instruments.** Le lot a publié deux lectures **contre lui-même**, et l'audit les a renforcées — §4.30 |
| **6** | le **garde du reranker** et les formes d'affectation qui échappaient au garde de sûreté (§4.31) | ✅ **fusionné** `137d780` — livré (`Conv' 40`), audité (`Conv' 41`, **2 bloquantes**), réparé (`Conv' 42`). **Le garde SIGNALE au lieu de refuser**, sur un chevauchement de vocabulaires reproduit deux fois, et le périmètre de l'inventaire a un plancher qui **ne descend jamais** — §4.32 à §4.35 |
| **7** | le garde de sûreté ne voit ni `setattr(settings, …)` (**47** occurrences — `git grep -c 'setattr(settings' -- '*.py'`, et **la portée est porteuse** : sans elle la même commande rend 52 dans 9 fichiers, en comptant les mentions en prose — §4.40) ni la lecture d'environnement à valeur par défaut (**6** sites suivis — le sixieme est un ALIAS, `env = os.environ.get`, invisible a un motif exigeant une parenthese collee) ; et la lecture défensive du reranker ne tient que dans **trois** natures d'exception sur sept sondées, **quatre** propageant et cassant la recherche (§4.35, mesuré au §4.37) | ✅ **fusionné** `71dfea8` — livré (`Conv' 43`), audité (`Conv' 44`, 1 bloquante), réparé (`Conv' 45`). **Ce dépôt a enfin un garde-fou sur `push`**, et la borne d'une ref neuve lit l'état RÉEL du distant — §4.36 à §4.40. Note historique : **moins cher qu'annoncé** : `mesuré`, **aucun** des 27 `setattr` sur `embedding_model_name` ne passe un littéral, ils passent tous une constante nommée, donc l'obstacle invoqué pour le différer **n'existe pas** |
| **8** | **armer l'agent en service, après avoir figé l'ancien lecteur** — né d'une trouvaille du lot 4 et non de ce plan : l'agent tournait le code du 3 septembre, et les gardes des lots 3 et 6 avaient **0 occurrence** dans le conteneur | ✅ **fusionné** `9509228` — livré (`Conv' 47`) sur décision de l'utilisateur. **Le garde du modèle d'embedding s'exécute enfin en production**, et le lecteur neuf rejoue les deux références du 8 septembre **à l'unité** : sept lots n'ont pas déplacé un caractère du contenu servi. La définition (C) du lot 4 survit derrière un réglage **éteint** — §4.42 et §4.43 |
| **9** | **`make eval` passe par `uv run`, qui resynchronise le `.venv` sur `uv.lock`** : `mesuré` en lecture seule, torch **CPU cède au build CUDA**, `transformers` 5.17 → 5.14 et `tokenizers` 0.23 → 0.22 — c'est-à-dire exactement ce qui calcule les embeddings et fait tourner le cross-encoder. Le mandat garde déjà `make install` contre `uv sync` pour cette raison ; **rien ne garde `uv run`**, qui le fait implicitement — §4.43 | à trancher : le `uv.lock` ou le protocole du §2.2, lequel fait foi pour une campagne ? |

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
| **31** | REPAR-4 — fermer B1, B2, N1 et N2 sur la branche du lot 3 | distribué le 4 septembre, livré le **7** : `19f7cec`, 552 passés, **11 mutations dont un témoin inerte**. B1, B2 et N1 vérifiés par le pilote — §4.22. A **refusé de trancher** l'écart de comptes, avec une mesure, et il avait raison |
| **32** | AUDIT-REPAR-4 — audit de la réparation du lot 3 | **11 mutations reproduites à l'identique**, 6 mutations propres, concurrence réelle avec une sonde **prouvée capable**. **1 bloquante** (B-1), 4 non bloquantes, **aucune mesure du pilote renversée** — §4.23. Recommandation : ne pas fusionner en l'état |
| **33** | REPAR-5 — fermer B-1 et NB-1 sur la branche du lot 3 | `c8cb37d` : **557 passés**, 8 mutations dont un témoin inerte. B-1 et NB-1 vérifiés par le pilote — §4.24. A fermé **hors mandat** le garde du compte de tests, et **a corrigé le pilote** sur `abandon_on_cancel` |
| **34** | AUDIT-ASYNC-3 — audit **étroit**, borné à la couche async du lot 3 | 7 mutations sur 8 reproduites à l'unité, 10 propres, scène de charge retournée contre `19f7cec`. **1 bloquante** (B-2 : rafale de 26 → 26 fils) — §4.25. A **validé le cadrage étroit avec une mesure**, et nommé son angle mort |
| **35** | REPAR-6 — fermer B-2 et les deux phrases fausses | `4849bc1` : rafale de 26 → **1 fil**, 562 passés. Vérifié par le pilote **dans les deux sens** et **fusionné** — §4.27. A trouvé seul la **seconde** raison pour laquelle le garde était décoratif : il comptait les fils par `name` |

| **36** | LOT-5 — régénérer le jeu doré, adopter les 30 questions du pipeline, établir la campagne de référence | livré le **8 septembre 2026**. Trois défauts trouvés hors cadrage, dont **le piège du `--compare`** — deux corpus sous une même numérotation de questions — et un **TROISIÈME** jeu de questions, `golden_qa.json`, qui était le `--golden` par défaut et dont les **13** questions à réponse — sur 15, « 15 à réponse » étant faux de deux — portaient **0** ancrage. **A mesuré la porte ROUGE sur `main` = `4eedb2a`** : `rc=2`, 1 rouge / 561 passés — le cadrage annonçait `rc=0`, 562. §4.3 |

| **37** | AUDIT-5 — audit du lot 5 | **10 mutations reproduites**, 9 propres, campagne de contrôle rejouée **bit pour bit**. **ZÉRO bloquante**, 8 non bloquantes — §4.30. A corrigé **quatre** chiffres du pilote et **renforcé** les deux lectures que le lot publiait contre lui-même |

| **38** | LOT-DETTE — les deux trappes ouvertes, et le dédoublement de l'inventaire | livré le **8 septembre 2026**. **N1 à N8 fermées**, `rc=0` / `rc=0`. Les deux trappes : `verifier_les_ancrages` rend enfin **2**, avec **preuve d'atteinte live** (ChromaDB joignable, Nebula sur `192.0.2.1` : `rc=1` → `rc=2`), et la chauffe BM25 est **faite, vérifiée et refusée en 2** dans `evaluate.py`. **L'inventaire est dédoublé** — et le garde neuf a trouvé une affectation copiable sur `main`, puis **la première rédaction du §4.29 lui-même**. Trois trouvailles sur ce lot par ses propres mutations : `lire_chroma` et `pool.execute` non gardés, et une détection `detect-secrets` que le lot ajoutait. Commit `e577dca`, **629 passés**, fusionné par le pilote — §4.29 et §4.31 |

| **39** | AUDIT-DETTE — audit du lot dette | **ZÉRO bloquante**, 5 non bloquantes. A **renversé deux maillons du raisonnement du pilote** avec des mesures, et trouvé que **l'idiome du dépôt échappe au garde de sûreté** — §4.31 |

| **40** | LOT-6 — le garde du reranker, les formes d'affectation qui échappaient, le bouchon de l'index périmé | livré le **8 septembre 2026** : `a2d2081` + `e6fc175`, **643 passés** (+14), `rc=0` / `rc=0`, **non poussés**. A **mesuré son cadrage faux** — le prompt annonçait `main` = `2bb511c`, mesuré `3638240`, **trois commits d'écart**. Le garde du reranker **SIGNALE** au lieu de refuser, et c'est une mesure qui l'a décidé : les vocabulaires multilingue et anglais **se chevauchent** (mBERT 119 547 < DeBERTa-v3 128 100), donc aucun seuil n'est un classifieur. A trouvé une **sixième** forme d'affectation non vue (`monkeypatch.setenv`), **corrigé le motif faux du §4.31** (saturation de sigmoïde, l'ordre survit) et **attrapé son propre faux résultat** deux fois — une mutation posée sur le mauvais réglage, et une assertion de périmètre décorative que sa propre mutation a montrée verte. Vérifié par le pilote — §4.32 |

| **41** | AUDIT-6 — audit du lot 6 | rendu le **9 septembre 2026**. **DEUX bloquantes**, une dizaine de non bloquantes. B-1 : le câblage du garde n'est éprouvé que sur son **bruit** — le garde peut lire le mauvais réglage ET ne jamais lire le vocabulaire, **643 tests restent verts**, et le réglage normal se met alors à avertir en nommant le mauvais modèle. B-2 : le chiffre `mesuré` du périmètre est **périmé dans le commit qui l'écrit** (124/53 annoncés, 125/54 réels). A trouvé le périmètre **décoratif sur le seul `src/agent/settings.py`**, proposé une **troisième forme** que le lot n'avait pas envisagée — un plancher monotone —, reproduit les **cinq** `vocab_size` du commentaire, et **validé le cadrage du pilote sur ses six lignes, une première dans la série**. A corrigé le pilote sur la **condition** de son raisonnement de fusion : *ce n'est pas la fusion qui est dangereuse, c'est la divergence* — §4.33 |

| **42** | REPAR-7 — réparation du lot 6 | livré le **9 septembre 2026** sur la branche du lot, rattrapée sur `main` par **fusion**. **B-1 fermée** : le câblage du garde du reranker n'était éprouvé que sur son bruit — les trois mutations du site d'appel laissaient 643 verts, elles rougissent toutes, chacune sur l'assertion qui la vise, et le témoin inerte reste vert. Deux gestes : le contenu du message discriminé, et une **seconde scène dans un processus à part** — `lru_cache` rendrait une scène du même processus creuse — qui asserte sa propre atteinte et fait **compter ses lectures** au vocabulaire. **B-2 et H8 fermées ensemble** par le **plancher monotone** de l'audit, global ET zone par zone, relevé sur l'arbre final (125, ventilé en 8 zones) ; le chiffre n'est PAS corrigé de 124 en 125, et le motif qui opposait « compte » à « forme » est réécrit. La ventilation par zone est éprouvée par un **rétrécissement compensé** que le plancher global ne voit pas. **Quatre phrases** non bornées retirées ou gardées, et deux **valeurs mortes** rendues vivantes. A trouvé contre le prompt que le registre ne porte **pas de compte univoque** des relevés du démon — §4.34 |

| **43** | LOT-7 — les formes qui échappent au garde de sûreté, le garde de NUMÉROTATION, et le hook `pre-push` | **livré le 9 septembre 2026** : `3f6bda5` + 3 commits antérieurs, **682 passés** (+35) sur **43** fichiers, `rc=0` / `rc=0`, **non poussés**. **Les TROIS fermetures portées.** A validé le cadrage sur ses cinq lignes mesurées de (a) — **47** `setattr` dans **7** fichiers, **27** sur le réglage, et l'obstacle inexistant — et **corrigé deux antécédents** : la seconde collision de numérotation **n'est PAS dans `git`** (balayage de `git rev-list --all` : aucune révision du registre ne porte de doublon de titre, elle avait été attrapée **avant** le commit), et la mutation `M3bis` que le cadrage donnait à lire **n'existe pas dans ce dépôt**. A trouvé **une dérive datée de plus** que le cadrage à `2bb511c` — « prochain libre : 41 » pour un maximum de 39 — et un sixième `environ.get`. **Quatre faux résultats contre lui-même** : une seconde direction **décorative** sur le motif `setattr` (M-a4 laissait 25 tests verts), un `grep` qui lisait son motif comme une **option** — le hook sortait en 0 **sans avoir rien vérifié** sur 276 commits —, un motif de secret dont une alternative **littérale se reconnaissait elle-même**, donc un hook qui refusait le commit qui l'introduit, trouvé par un **vrai `git push`** et invisible à 37 tests verts — et **sa première correction visait la mauvaise cause**, ce que la mutation qui devait la reproduire a montré en restant verte. §4.36 | Trois fermetures indépendantes, sur décision de l'utilisateur : (a) `setattr(settings, …)` et `environ.get`/`getenv` — et le pilote a mesuré que **l'obstacle invoqué pour différer ce lot n'existe pas** —, plus la surface d'exception de la lecture défensive du reranker ; (b) un garde sur les numéros du journal ET des sections du registre, après **deux collisions en deux jours**, dont une du pilote ; (c) le `pre-push`, le garde-fou d'identité ne couvrant que `commit` et `merge` après **neuf** pré-vols manuels — §4.35 |

| **44** | AUDIT-7 — audit du lot 7 | **distribué le 9 septembre 2026**, en vol. **Dixième audit du chantier.** Priorité écrite sur la fermeture (c), le hook `pre-push` : 199 lignes neuves qui s'exécutent à chaque poussée, dont le lot a lui-même tiré **trois faux verts sur quatre**, et dont la panne est **silencieuse** — sur un dépôt propre un hook creux rend le même `rc=0` qu'un hook juste. Le pilote a vérifié le hook par de vrais `push` dans les deux sens et n'a pas couvert la poussée forcée, la suppression de ref, ni plusieurs refs en une poussée — §4.37 |

| **45** | REPAR-8 — la bloquante du lot 7, et six resserrements | **livré le 9 septembre 2026** sur la branche du lot : **697** passés (+15) sur **43** fichiers, `rc=0` / `rc=0`. **Vérifié et FUSIONNÉ par le pilote — `71dfea8`, poussé.** **Bloquante fermée**, et la preuve est l'ÉTAT DU DISTANT sous un vrai `git push` : le sinistre reproduit hook INTACT — 0 commit vérifié sur 10, `rc=0`, **7** adresses non autorisées arrivées — puis rejoué réparé : `rc=1`, **0** ref, **0** commit. La borne est `git ls-remote` et non `refs/remotes/`; le **commit d'époque** a été pesé et écarté parce qu'il **ne ferme pas le sinistre**. Le test qui épinglait la cécité est **remplacé**, et la borne légitime reste éprouvée. **La faiblesse structurelle est fermée** : cinq tests poussent pour de vrai et assertent l'état du distant. Les six resserrements portés, dont **cinq** bornes inertes et non trois. **Trois chiffres corrigés, deux définitions tranchées** — et deux trouvailles sur le chantier : la panne de `read` **n'est pas propre à `dash`**, et le « 47 `setattr` dans 7 fichiers » du pilote est juste sous une **portée** que l'étiquette ne donnait pas, sa « reproduction sous deux lectures concordantes » rendant 59/10. **Trois faux verts contre lui-même** (M-8, M-g, M-j), et deux bornes non fermées nommées. A fermé le **trou de numérotation** par la fusion du registre de l'auditeur — §4.39 |

| **46** | LOT-4 — « section voisine » élargie aux oncles, l'instrument, et la campagne | **distribué le 9 septembre 2026 à 14:01 UTC**, en vol. La définition a été **tranchée par l'utilisateur** sur mesure du pilote : (C) remontée aux oncles bornée au document, et le voisin réel en lecture côté par côté. Trois fermetures : le code de `graph_context.py` — **premier changement du chemin de lecture depuis le lot 3** —, le portage de la mesure dans `scripts/mesurer_le_graphe.py` (les pourcentages du §4.6 sont `mesuré` **et sans instrument**), et la **campagne** qui dira si le rappel suit la couverture — §4.6 |

| **47** | LOT-8 — figer la référence, armer l'agent, et (C) derrière un réglage éteint | **livré et FUSIONNÉ** `9509228`, **726 passés**, poussé. **L'agent en service tourne le code du 3 septembre** : les gardes des lots 3 et 6 ont **0 occurrence** dans le conteneur (§4.42). Sur décision de l'utilisateur : rejouer les deux campagnes contre l'agent ACTUEL pour figer un antécédent comparable, **puis** reconstruire l'image et les rejouer — l'ordre est irréversible —, et garder la définition (C) derrière un réglage **éteint par défaut**, gardé dans ses DEUX positions. Le pilote a vérifié avant de distribuer que l'estampille de la collection concorde avec le réglage, donc que l'armement du garde du lot 3 **ne produira pas de 503** |

| **48** | LOT-9 — la recette de campagne cesse de muter l'environnement, et l'écart cesse de dériver en silence | **livré le 11 septembre 2026 et FUSIONNÉ** `bf2906e`, **730 passés**, poussé., en attente de fusion — **728 passés**, `make lint` et `make test` en `rc=0`. Les deux fermetures sont posées : le drapeau sur les trois recettes, les six docstrings de `scripts/` et celle de `tests/integration/`, plus un garde de forme à DEUX directions qui épargne les récits ; et le garde de numérotation porte la propriété, non l'instantané. Trois faux résultats trouvés et écrits par le lot lui-même. **Le garde sur l'ÉCART est posé** (il tient le DOMMAGE — la pile CUDA —, pas les versions, dont la dérive est le prix accepté), et **la réserve du lot 8 est tranchée** : les deux versions de `transformers`/`tokenizers` encodent les mêmes phrases en vecteurs **identiques au bit près**, `mesuré` le 11 septembre 2026 dans un venv jetable hors du projet. NON couverts : l'écart de `torch` lui-même et le cross-encoder — §4.44. Sur décision de l'utilisateur : **le protocole du §2.2 fait foi**, la resynchronisation est neutralisée, et un garde tient l'écart avec `uv.lock`. Le pilote a mesuré que **le dépôt connaît déjà ce piège** — `scripts/installer-les-garde-fous.sh:151` écrit `uv run --no-sync` sous un commentaire disant que ce n'est pas cosmétique — et que **trois** recettes du `Makefile` l'ont oublié. Plus la réserve du garde de numérotation : il épingle un instantané là où il doit asserter la propriété — §4.43 |

| **49** | LOT-10 — l'attribution refusée AU COMMIT, et les deux dernières réserves | **distribué le 11 septembre 2026**, en vol. **L'utilisateur a réaffirmé sa règle** : aucune mention d'un assistant comme contributeur, nulle part, quoi que réclame la configuration de l'outil. `mesuré` par le pilote : l'histoire est **propre sur 333 commits** (zéro `Co-Authored-By`, zéro auteur autre que l'utilisateur), et le `pre-push` **refuse** le trailer — éprouvé par un vrai `git push`, `rc=1`, zéro ref. **Le trou est au COMMIT** : le garde d'identité lit `git var GIT_AUTHOR_IDENT` et ne voit jamais le message, et `commit-msg` n'est pas dans les types armés. Plus le `timeout 30` du hook et l'écart de `torch` — §4.45 |

**Prochain numéro libre : 50.**

**Cinq lots fusionnés, NEUF audits.** Le neuvième rend **deux bloquantes** : le compte des bloquantes du chantier passe de six à **huit** (`calculé`). **Aucun lot n'a encore été fusionné sans qu'un audit indépendant y trouve quelque chose**, et le lot 6 attend sa réparation. Les
deux derniers lots sont passés **sans une seule bloquante**, et les deux derniers
audits ont porté leurs trouvailles **sur le pilote** plutôt que sur les lots : un
état de `main` qu'il avait publié sans le mesurer, et deux maillons d'un
raisonnement qu'il avait tiré d'un antécédent du dépôt sans le mesurer non plus.
*Reprendre un antécédent du dépôt sans le mesurer est la même faute que de
l'inventer.*

**Quatre lots sur cinq sont fusionnés, et les cinq exigences du contrat sont
tenues.** Sept audits indépendants, sept trouvailles — dont **six bloquantes**, et
le lot 5 est le **premier à passer son audit sans une seule**. Le pilote a été
borné, corrigé ou renversé à chacun des sept.

**Et LOT-DETTE a trouvé trois défauts sur lui-même, par ses propres mutations** :
l'absorption large de `lire_chroma` n'était gardée par rien (une mutation qui
avait manqué sa cible), l'absorption qu'il venait d'ajouter sur `pool.execute` ne
l'était pas non plus (mutation M3, verte), et sa première forme de garde
d'affectations faisait passer le dépôt de **2** à **3** détections
`detect-secrets` — c'est-à-dire qu'un garde du lot rendait `detect-secrets` moins
armable au moment même où le lot retirait un pragma pour le rendre plus armable.
*Trois verts qui ne prouvaient rien, trouvés par le protocole plutôt que par un
auditeur.*

**LES DEUX TRAPPES SONT FERMÉES, ET LA DETTE NON BLOQUANTE AVEC ELLES.**
`N1` — `verifier_les_ancrages` sortait en `1` là où quatre sites promettent `2`,
sans aucun test sur ce chemin — et `N2` — *le réchauffement de l'index BM25 était
raconté, ni fait ni gardé* — étaient les **deux seules trappes ouvertes pour la
campagne suivante**. Fermées par LOT-DETTE le 8 septembre 2026, avec les six
autres non bloquantes (§4.29). La campagne suivante peut partir : son antécédent
refuse de se taire, et sa question 1 ne traversera plus un index froid.

**CE QUI RESTE, ET C'EST NOMMÉ PLUTÔT QUE COMPTÉ COMME ZÉRO.** Le **hook
`pre-push`** : le garde-fou d'identité couvre `commit`, `--amend`, `--author=`,
`merge --no-ff` et `merge --squash`, **pas `push`**, et le dépôt pousse — les
trois pushes de ce chantier ont été protégés par une vérification **manuelle** du
pilote. Il change le geste de publication et mérite son propre lot. Avec lui :
deux détections `detect-secrets` préexistantes que ce chantier n'a pas touchées,
une affectation copiable du **reranker anglais** dans le même bloc `.env`
historique que celle que LOT-DETTE a corrigée — trouvée en passant, hors du
périmètre de la décision du §4.28, non gardée — et le fait que le jeu de
questions versionné n'est pas reproductible par la graine désormais transmise, ce
qui demanderait de le régénérer et casserait l'appariement de la référence.

**LA PORTE ÉTAIT ROUGE SUR `main`, ET AUCUNE CONVERSATION NE L'AVAIT VU.**
`mesuré` par `Conv' 36` le 8 septembre 2026, sur `main` = `origin/main` =
**`4eedb2a`**, dans un arbre nu monté par le protocole du §2.2 : `make lint` →
`rc=0`, **`make test` → `rc=2`, 1 échec / 561 passés**. Le rouge est
`test_le_nom_du_modele_anglais_ne_vit_que_la_ou_il_est_justifie`, à **6**
occurrences trouvées pour **5** autorisées — et la sixième était **la phrase du
§4.27 qui raconte que ce garde avait rougi sur la fusion du lot 3**. *Le récit du
rouge a produit le rouge suivant.* C'est la **famille (f) pour la cinquième
fois**, et la seconde fois qu'un garde la trouve.

La leçon est celle du §12, à un cran de plus : **une porte se mesure sur le commit
qu'on livre, pas sur celui d'avant.** Le §4.27 a été écrit après la mesure qu'il
publie, et personne n'a remesuré. Le cadrage distribué à `Conv' 36` porte donc un
« rc=0, rc=0, 562 passés » qui n'a jamais été vrai à `4eedb2a` — un état de poste
recopié d'une mesure antérieure, exactement ce que le §4 interdit.

**Le lot 3 est fusionné, et c'est le lot le plus cher du chantier** : sept
conversations, **quatre audits, quatre trouvailles bloquantes — et aucune n'était
une régression fonctionnelle.** Le code était strictement meilleur à chaque
passage ; ce qui bloquait était **ce que le lot affirmait de lui-même**, tenu
chaque fois par un garde qui construisait la scène où le défaut n'est pas. C'est
la leçon centrale de ce chantier, et ce lot l'a payée quatre fois.

**Et la porte était ROUGE sur le résultat de la fusion** — verte des deux côtés,
rouge au milieu. C'est un **garde** qui l'a trouvé, pour la première fois, là où
la famille (f) avait toujours été trouvée par un auditeur ou par le pilote
relisant à la main. Détail au §4.27.

**Six audits, six trouvailles bloquantes. Le lot 3 en a consommé quatre.** Les
quatre vivaient dans la couche async/concurrence, et **les trois dernières
consistaient en une affirmation fausse tenue par un garde structurellement
incapable de la démentir** — jamais en une régression fonctionnelle. Le code de ce
lot est, à chaque passage, strictement meilleur que le précédent ; ce qui bloque
est ce qu'il **affirme** de lui-même. *C'est la leçon centrale du chantier, et ce
lot l'a payée quatre fois : une mesure est un contrat, et un garde qui construit
la scène où le défaut n'est pas ne garde rien.*

**Et une leçon de pilotage sur le périmètre d'audit** : borner l'audit à la couche
async a payé — le bloquant était à quatre lignes du site déjà corrigé deux fois —
mais un périmètre borné **laisse le reste du registre sans lecteur indépendant**.
C'est le pilote qui a dû départager la seule mesure hors périmètre, et il a
constaté que le chiffre contesté était juste.

**`main` est poussé.** `7bcd346..a2ec58b`, 31 commits, le 7 septembre 2026, sur
décision de l'utilisateur, après vérification manuelle des 62 signatures
auteur+committer, de l'absence d'`@aosis.net`, d'attribution d'assistant et de
tout secret. `main` = `origin/main` = `a2ec58b`. **Le garde-fou d'identité ne
couvre PAS `push`** : cette vérification était manuelle, et un hook `pre-push`
monte au plan.

**Cinq audits, cinq trouvailles bloquantes — et le lot 3 en a consommé trois.**
C'est le lot le plus cher du chantier, et c'est le seul qui touche le chemin de
chaque recherche. Les deux dernières bloquantes vivaient toutes deux dans la
**couche async/concurrence** : c'est la raison pour laquelle l'audit `Conv' 34`
est **borné à cette couche** au lieu d'être un troisième passage complet. *On
cible là où le taux de trouvaille est mesuré.*

**Cinq audits, cinq trouvailles bloquantes.** Le lot 3 en a consommé trois à lui
seul — livré, audité, réparé, réaudité, à réparer une seconde fois — et chaque
passage a trouvé quelque chose que le précédent n'avait pas vu. **C'est le lot le
plus cher du chantier, et c'est le seul qui touche le chemin de chaque
recherche.**

**Une leçon d'horloge, et elle vient de tomber.** `date -u` rendait le
**4 septembre** à l'ouverture de cette conversation de pilotage et rend le
**7 septembre** maintenant : trois jours ont passé dans une seule conversation.
`Conv' 31` a **relevé l'horloge** et daté ses mesures du 7, sans écrire un seul
« 4 septembre » ; le pilote, lui, l'aurait recopié par habitude. C'est la faute
que le dépôt jumeau a payée **neuf fois dans un seul lot**. **Dans une
conversation longue, relève `date -u` avant chaque date que tu écris** — la date
de la conversation n'est pas la date du jour.

**Et le §4.13 monte au plan.** `documentation/tests.md` a été corrigé au site
pour la **troisième** fois sans que rien ne le garde, et cette fois le retard
avait été écrit **par le commit qui prétendait le rattraper** — 520/36 annoncés
contre 539/37 réels, vus ni par le lot, ni par son audit, ni par le pilote. C'est
le **F7** du dépôt jumeau, le dernier angle mort de la méthode : *rien ne lit le
`Makefile` ni les documents.* Il passe devant le lot 4 dès que le lot 3 est
fusionné.

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

Celles du 7 septembre 2026 :

- **Le piège de `merge-tree` n'est pas celui que ce mandat décrivait.** Il écrivait
  que `git merge-tree <base> <a> <b>` rend `rc=0` en cas de conflit et que
  `--write-tree --messages` le nomme. `mesuré` sur git 2.53.0 : la forme à **deux**
  arguments rend déjà `rc=1`. Ce qui rend `rc=0` malgré treize marqueurs de
  conflit, c'est la forme **historique à trois** arguments. *Ce n'est pas le
  drapeau qui sauve, c'est de ne pas employer la forme à trois arguments* — et
  cette précision a été mesurée par un auditeur, pas par le pilote qui recopiait
  sa propre consigne.
- **Additionner des grandeurs différentes et donner la somme pour l'une d'elles.**
  Le pilote a écrit « 202 lignes de code de production » : le diff fait **175
  insertions** et 27 suppressions, et 202 est leur somme. Même famille que
  « le plus gros fichier de tests » du §4.14 — *deux écritures justes sous des
  définitions différentes.*
- **Une conversation lancée dans un arbre au nom ressemblant est à un `cd` du
  clone principal.** L'auditeur du lot 3 a tapé `cd /home/ubuntu/RAG/rag-agent-chat`
  au lieu du chemin de son arbre, et y a détaché `HEAD` hors de `main`. **Sans
  conséquence, mesuré** — la ref `main` n'a jamais bougé, son reflog ne porte
  aucune entrée étrangère. Ce qui compte est ce qu'il a fait ensuite : **il a ouvert
  son rapport par son propre incident**, avec les mesures qui en bornaient la
  portée, avant tout le reste. Un rapport qui déclare sa propre faute est plus
  croyable, pas moins — *c'est le contraire de l'erreur qui a coûté un dépôt entier
  au projet jumeau, celle-là ayant été découverte par quelqu'un d'autre.* **Écris
  le chemin absolu de ton arbre dans chaque prompt, et exige qu'il soit mesuré
  avant la première commande.**

Celles du 8 septembre 2026 :

- **Un cadrage vieillit entre sa première ligne et sa dernière.** Le prompt du
  lot 6 annonçait `main` = `2bb511c` ; le lot a mesuré `3638240`, **trois commits
  d'écart**. Le pilote avait relevé `main` avant d'y pousser la chaîne de
  correction du journal, puis avait écrit le prompt sans remesurer. Le même
  prompt annonçait un numéro de relevé du démon que le lot a compté
  autrement — et **REPAR-7 en a mesuré la cause** : le registre portait TROIS
  comptes incompatibles, dont deux dans la même cellule. Le compte est retiré,
  la suite des relevés le remplace (§4, ligne `dagster-daemon`). La règle « mesurer avant de pousser, jamais après » ne
  suffit pas : **remesure `main` juste avant de SCELLER le prompt**, et non au
  moment où tu commences à l'écrire — §4.32.
- **Un numéro est une mesure comme une autre.** « Prochain numéro libre : 41 »
  a été écrit depuis l'arithmétique d'un script d'édition au lieu d'être **compté
  dans le journal**. Trois défauts en sont sortis d'un coup, dont une ligne `38`
  en double, et **c'est l'utilisateur qui les a vus, sur une question de quatre
  mots** — §4.31.
- **Reprendre un antécédent du dépôt sans le mesurer est la même faute que de
  l'inventer.** Le pilote a bâti un raisonnement sur « étendue 0,0 % donc
  classement au hasard », lu au site canonique de `rerank_model`. C'est une
  **saturation de sigmoïde** : l'ordre survit intégralement. Deux audits de suite
  ont porté leur trouvaille sur le pilote pour ce motif, et le lot 6 a corrigé le
  site — §4.32.
- **Le clone principal n'est pas seulement à un `cd` de distance : on y écrit
  sans le vouloir.** Le pilote a lu le journal depuis le clone principal — ce qui
  est le bon geste, c'est là que vit `main` — puis y a **édité** le fichier dans
  la même commande, laissant le clone principal sale. Rattrapé en extrayant le
  `git diff`, en restaurant le clone et en appliquant le patch dans l'arbre du
  pilote ; `git status --porcelain` vérifié vide ensuite. *Lis depuis le clone
  principal si tu veux, mais **écris toujours depuis ton arbre** — et vérifie
  `pwd -P` avant chaque écriture, pas seulement avant la première commande.*
- **Le piège du tube, une sixième fois.** `git merge main 2>&1 | tail -3` puis
  `echo "rc=$?"` : le `rc` relevé était celui de `tail`. Le pilote ne s'en est
  sorti qu'en **vérifiant l'état** (`git rev-parse`, `rev-list --left-right`)
  plutôt que le code de retour. *Quand tu as filtré une sortie, ce n'est plus le
  `rc` qui te renseigne : c'est l'état.*

Celles du 11 septembre 2026 :

- **Un réglage d'outil ne renverse pas une contrainte de projet.** La
  configuration a demandé, en cours de chantier, d'ajouter à chaque commit un
  trailer d'attribution à un assistant de génération de code — ce que le §2.1 de
  ce mandat interdit, sur un dépôt **public** dont la liste de contributeurs a
  déjà coûté une destruction-recréation parce qu'elle est **irréversible**. **Le
  lot a refusé, a livré sans, et a rendu la question au pilote** ; le pilote a
  confirmé et l'a dit à l'utilisateur au lieu de l'appliquer en silence. *La règle
  de ce dépôt tient son autorité de celui qui la paye, pas de l'outil qui la lit.*
  Vérifié sur les six commits : aucune occurrence — §4.45.
- **La règle du `push` conditionné a tenu à sa première application, et chez
  quelqu'un d'autre.** Écrite la veille après que le pilote eut poussé un `main`
  rouge en ayant vu le rouge, elle a empêché un commit sur un `LINT_RC=2` dans le
  lot suivant. *Une leçon consignée le jour même sert le lendemain.*

Celles du 10 septembre 2026 :

- **J'AI POUSSÉ UN `main` ROUGE, ET CETTE FOIS J'AVAIS VU LE ROUGE.** Le
  8 septembre, la faute était de pousser sans remesurer. Le 10, `make test` a
  rendu **`rc=2`** sous mes yeux, la ligne a été imprimée, et **la poussée est
  partie quand même** — parce que mon script enchaînait le `push` après le test
  sans le conditionner à son résultat. *Mesurer ne sert à rien si la mesure ne
  commande pas le geste suivant.* `origin/main` a été rouge de `6a4ac7d` à
  `5edccb4`. **Écris tes séquences de sorte que le `push` soit IMPOSSIBLE si la
  porte n'est pas verte** : relève les deux `rc` dans des variables, et n'appelle
  `push` que sous `if [ "$LINT" -eq 0 ] && [ "$TEST" -eq 0 ]`. Une porte qu'on
  lit sans s'y soumettre n'est pas une porte — c'est un affichage.
- **Et le rouge venait d'un numéro, pour la troisième fois en trois jours.**
  J'ai ajouté une ligne « 9 » au plan de lots alors qu'aucune ligne « 8 »
  n'existait — le lot de déploiement était né d'une trouvaille et non du plan.
  **C'est le garde de numérotation du lot 7 qui l'a dit**, et c'est la première
  fois qu'un garde de ce chantier attrape le pilote avant l'utilisateur. *Le
  garde qu'on commande finit par vous juger.*
- **Ne donne jamais à un lot le résultat attendu de la mesure que tu lui
  commandes.** Le prompt du lot 8 écrivait la concordance **avec sa conclusion** —
  « donc l'armement ne produira pas de 503 ». C'est le §9 du mandat à l'envers, et
  le lot l'a relevé : *le motif, pas le chiffre.* Un lot à qui l'on donne la
  réponse ne mesure plus, il vérifie — et huit trouvailles de ce chantier viennent
  d'un lot ayant mesuré ce que le pilote croyait savoir — §4.43.

Celles du 9 septembre 2026 :

- **Écris la CONDITION, pas la conclusion.** Le pilote a écrit « la porte passée
  sur la branche EST la porte sur le résultat de fusion », et le raisonnement
  était juste — mais **seulement parce que `main` était un ancêtre de la branche
  et parce que rien, dans le banc, ne lit l'histoire du dépôt**. Les deux défauts
  que ce chantier garde en mémoire comme *nés de la fusion* venaient d'une
  fusion de branches **divergentes**. *Ce n'est pas la fusion qui est
  dangereuse, c'est la divergence* — et une conclusion écrite sans sa condition
  sera réemployée là où la condition ne tient pas. Mesuré et borné par un
  auditeur, pas par le pilote — §4.33.
- **Numéroter une section sans lire la queue du fichier, et c'est la DEUXIÈME
  collision de numérotation en deux jours.** Le pilote a ajouté un `### 4.34` en
  fin de registre alors que la réparation venait d'y écrire le sien : deux
  sections portant le même numéro, et aucun `rc` pour le dire. La veille, la même
  faute avait produit une ligne `38` en double dans le journal. **Ce qui l'a
  attrapée n'est pas une relecture, c'est une `assert` posée AVANT l'écriture** —
  le script d'édition vérifiait que son ancre existait en un seul exemplaire, et
  l'ancre « prochain numéro libre : 42 » n'existait plus, la réparation l'ayant
  déjà portée à 43. *Écris tes scripts d'édition pour qu'ils refusent d'écrire
  quand le fichier n'est pas celui qu'ils croient*, et **relis la queue du
  fichier avant d'y ajouter un numéro** — §4.35.
- **Le jour a tourné dans la conversation.** `date -u` rendait le
  **8 septembre** hier soir et rend le **9** ce matin. C'est la troisième fois de
  ce chantier, et la faute que le dépôt jumeau a payée neuf fois dans un seul
  lot : **relève `date -u` avant CHAQUE date que tu écris**, pas une fois par
  conversation.
- **Une demi-règle ajoutée la veille a tenu à sa première application.** Le
  cadrage du lot 6 avait vieilli de trois commits ; celui de l'audit 6 a été
  scellé après un relevé, et **l'auditeur a reproduit ses six lignes sans une
  correction — une première dans la série**. La règle qui manquait n'était pas
  « mesure », c'était *« remesure juste avant de sceller »*.

**Traite tes propres affirmations comme des hypothèses.** Vérifie avant d'écrire
un chiffre. Relis le code avant d'affirmer ce qu'il fait. Et **quand un audit te
contredit avec une mesure, il a raison.**
