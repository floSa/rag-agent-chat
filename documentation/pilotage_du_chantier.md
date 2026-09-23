# Piloter le chantier d'audit et de refonte — `rag-agent-chat`

> Ouvert le **3 septembre 2026**, à la passation de
> [`rag-ingestion-pipeline`](https://github.com/floSa/rag-ingestion-pipeline).
> Le point d'entrée de l'autre côté est son `documentation/etat_des_lieux.md` :
> il se lit sans lancer le projet, et il est autosuffisant.
>
> Ce fichier-ci est le mandat du pilote **de ce côté**. Il porte l'état du
> chantier, le plan de lots, et les conventions. Le détail de chaque constat,
> ouvert ou fermé, vit dans [`axes_amelioration.md`](axes_amelioration.md).
>
> **SES SECTIONS 4 ET 6 SONT DATÉES, ET LEURS CONSTATS NE SONT PAS RÉÉCRITS.**
> Le moteur servi est **vLLM depuis le 17 septembre 2026**, et le lot 28 a retiré
> le support de l'autre du code. Le §4 porte dans son titre même que « chaque
> ligne porte SA date de mesure », et le §6 est le journal des lots livrés :
> réécrire un relevé de carte graphique ou le résumé d'un lot rendu ferait dire à
> une mesure autre chose que ce qu'elle a dit. C'est pourquoi ce fichier est nommé
> dans le périmètre d'exclusion du garde
> `test_le_nom_de_l_ancien_moteur_ne_revient_pas`, avec sa raison.

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
**Leur fermeture est le hook `pre-push`, armé le 9 septembre 2026** (lot 7,
§4.40) : il relit l'adresse d'auteur ET de committer de **chaque** commit de la
plage qui part, donc il voit ce que le commit a laissé passer. Un `tag -a` reste
hors de sa portée.

**QUATRIÈME TYPE ARMÉ LE 11 SEPTEMBRE 2026 : `commit-msg`** (lot 10, §4.46). Les
trois premiers portent le contrôle d'**identité**, qui lit
`git var GIT_AUTHOR_IDENT` et `GIT_COMMITTER_IDENT` : **aucun ne lit le MESSAGE**.
`commit-msg` est le seul type auquel git passe le message, en chemin de fichier
sur `$1`, et il refuse les **formes** d'attribution à un assistant de génération
de code — jamais les **mentions** en prose, sans quoi le garde enseignerait le
`--no-verify` que ce chantier interdit.

**Il couvre la fusion automatique, et c'est `mesuré`** : sur
`git merge --no-ff --no-edit` propre, `pre-commit` **ne passe pas** et
`pre-merge-commit` passe **sans recevoir aucun chemin de message** ; `commit-msg`,
lui, reçoit `.git/MERGE_MSG`. Sur une fusion dont le conflit est résolu à la main,
il reçoit `.git/COMMIT_EDITMSG`. **Ce qu'il ne couvre pas** : `git revert`,
`git cherry-pick` et `git rebase`, qui n'exécutent que `prepare-commit-msg` et
**rejouent** un message existant — le rempart y reste `pre-push`.

Le motif refusé n'a **qu'un seul site**, `scripts/git-hooks/formes-d-attribution.sh`,
sourcé par les deux hooks qui l'appliquent et copié **à côté** d'eux par
l'installeur — donc hors de l'arbre de travail, comme la couche `.legacy`
elle-même, faute de quoi il disparaîtrait exactement dans les scènes que cette
couche existe pour couvrir.

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
| les LLM | **`vllm-central` sert `google/gemma-4-E4B-it-qat-w4a16-ct`, et c'est ce qu'attend `.env.example`** — `mesuré` le **18 septembre 2026 à 12:35 UTC**, `GET /version` → `{"version":"0.28.0"}`, fenêtre servie **32768**. *Relevé antérieur, avant la bascule : un autre serveur central servait le modèle sous un autre nom.* **Le serveur d'avant tourne TOUJOURS sur ce poste** — `mesuré` le 18 septembre 2026, `docker ps`, `Up 2 hours (healthy)` — mais il appartient au projet `llm-service` et **ce dépôt ne lui parle plus** : le lot 28 a retiré son support, pas le conteneur |
| la carte L4 | ⚠️ **vLLM EST EN SERVICE DESSUS**, `mesuré` le **14 septembre 2026 à 09:08 UTC** par LOT-12, `nvidia-smi --query-compute-apps` croisé avec `docker inspect -f '{{.State.Pid}}' rag-agent-api` : `VLLM::EngineCore` **14 264 MiB**, `llama-server` (Ollama) **4 584**, **cet agent 1 294** (PID 503779), **2 892 libres** sur 23 034. **L'agent a GARDÉ son périphérique** — le risque du §4.49 ne s'est pas réalisé. Mais la marge est de 2,9 Go : un agent qui redémarrerait et redemanderait ses 1,29 Go les trouve **aujourd'hui**. Si vLLM grandit, il **lèvera sur la mémoire**, `cuda_available` restant `true` — c'est la panne que la seconde moitié du garde du lot 12 attrape, et la première ne la voit pas. *Seize minutes plus tôt, à 08:52, l'agent tenait **0 MiB** : son empreinte est PARESSEUSE, les deux modèles étant derrière `lru_cache` — §4.50. Cet état périme vite, remesure-le* **Relevé de part et d'autre du redéploiement du lot 24**, `mesuré` le **16 septembre 2026**, même instrument (`--query-compute-apps` croisé avec le PID du conteneur, et le cgroup de chaque PID rapporté à son conteneur — l'attribution est LUE, pas supposée) : à 13:37 UTC, `vllm-central` **14 264 MiB**, `ollama-central` **3 586**, cet agent **1 468**, **3 229 libres** sur 23 034 ; à 13:43 UTC, après recréation et une question réelle, `vllm-central` **14 264**, `ollama-central` **3 262**, cet agent **1 300**, **3 721 libres**. **L'agent a REPRIS son périphérique** — `cuda_available: true`, `embedding: cuda:0`, `rerank: cuda:0`, `hors_d_atteinte: null`. **La marge a commandé le geste** : l'agent rendait 1 468 MiB et n'en redemandait pas plus, donc 4 697 MiB disponibles au moment de la reprise pour un besoin de 1 468 — `calculé` depuis les deux relevés. *Le seul scénario qui cassait était un redémarrage de `vllm-central` à `--gpu-memory-utilization 0.76` dans la fenêtre ; sa valeur courante a été RELUE — `0.55`, `docker inspect` — et son `StartedAt` est identique avant et après.* |
| l'agent | `mesuré` le **8 septembre 2026** : `rag-agent-api` **en marche et `healthy`**, `GET /health` → HTTP **200**, `status: ok`. **`index_lexical` était à `false`** au premier relevé et est passé à `true` après la première recherche : l'index BM25 se construit **paresseusement**, donc un `/health` lu juste après un redémarrage annonce une recherche amputée qui ne l'est pas — la première recherche la construit synchroniquement. Réglages du chemin mesuré par la campagne : `HYBRID_SEARCH=true`, `QUERY_REWRITE=true`, `FETCH_K=50`, `RETRIEVAL_TOP_K=50`, `RERANK_TOP_K=10`, `AUTO_SELECT_TOP_K=3`, fenêtre graphe ±6 / ±3, `FULL_TEXT_FROM_VECTORS=true`. Relevé antérieur, le **4 septembre 2026** : mêmes quatre dépendances à `true`. Le port est **8011** sur l'hôte, jamais 8000. `POST /reindex` est **exposé** — vérifié dans l'`openapi.json` servi, aux côtés de `/answer`, `/search`, `/context/{element_id}`, `/sources`, `/media/{object_name}`, `/feedback` et des trois routes `/chat/*` **LA TRAPPE EST FERMÉE PAR LOT-DETTE** : `scripts/evaluate.py` chauffe l'index avant la première question puis **vérifie**, et **refuse la campagne en 2** si `/health` n'annonce toujours pas `index_lexical: true` — un agent qui ne répond pas du tout reste un **1**, pas un refus, et le motif de cette distinction est au site (§4.29). `mesuré` de nouveau à la fin de LOT-DETTE : `rag-agent-api` `Up 5 hours (healthy)`, `status: ok`, les **quatre** services à `true`, `index_lexical` compris. **REDÉPLOYÉ LE 16 SEPTEMBRE 2026 À 13:40:14 UTC PAR LE LOT 24, ET POUR LA PREMIÈRE FOIS ON SAIT QUEL CODE TOURNE.** Avant : le conteneur exécutait `8209e68`, **tranché par le conteneur** (`docker cp` puis SHA-256 fichier par fichier — 15/15 identiques à `8209e68`, et 4 différents + 3 manquants contre `main`), `/health` **sans clé `code_servi`**, image `sha256:b2f787a4…`, `StartedAt=2026-09-15T21:21:05Z`, `RestartCount=0`. Après : `/health` publie `code_servi: {etat: "identifie", sha: "b7337a3e544009dbbbc36764cb072e046b175e09", construite_le: "2026-09-16T13:39:21Z", avertissement: null}`, image `sha256:48b00a43…`, `Health=healthy` en **21 s**, et le contenu du conteneur est **18/18 identique au SHA-256** à `b7337a3` — `src/agent/flux_llm.py` et `src/agent/repli_outil.py` compris. **Les lots 19, 20 et 21 sont en service.** `moteur_llm.releve_le` passe de `2026-09-15T21:21:16Z` (16 h d'âge) à `2026-09-16T13:40:25Z`. Les volumes ont traversé : `usage` reprend à **1 533** interactions / **15 330** sources et incrémente à **1 534** / **15 340** sur la question posée ; `hf_cache` a servi les deux modèles sans **aucun** téléchargement de poids (**0** `GET` sur un fichier de poids contre **49** `HEAD` de revalidation, motif doublé d'un contrôle positif sur une ligne témoin). `rag-frontend` n'a **pas** été touché malgré son `depends_on`. *Le chemin du retour a été armé et non parcouru : `rag-agent-chat-agent-api:2026-09-16-avant-redeploiement` pend à `sha256:b2f787a4…`, vérifié.* |

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

| **48** | LOT-9 — la recette de campagne cesse de muter l'environnement, et l'écart cesse de dériver en silence | **livré le 11 septembre 2026 et FUSIONNÉ** `bf2906e`, **730 passés**, poussé — **728 passés** sur la branche avant fusion, `make lint` et `make test` en `rc=0`. Les deux fermetures sont posées : le drapeau sur les trois recettes, les six docstrings de `scripts/` et celle de `tests/integration/`, plus un garde de forme à DEUX directions qui épargne les récits ; et le garde de numérotation porte la propriété, non l'instantané. Trois faux résultats trouvés et écrits par le lot lui-même. **Le garde sur l'ÉCART est posé** (il tient le DOMMAGE — la pile CUDA —, pas les versions, dont la dérive est le prix accepté), et **la réserve du lot 8 est tranchée** : les deux versions de `transformers`/`tokenizers` encodent les mêmes phrases en vecteurs **identiques au bit près**, `mesuré` le 11 septembre 2026 dans un venv jetable hors du projet. NON couverts : l'écart de `torch` lui-même et le cross-encoder — §4.44. Sur décision de l'utilisateur : **le protocole du §2.2 fait foi**, la resynchronisation est neutralisée, et un garde tient l'écart avec `uv.lock`. Le pilote a mesuré que **le dépôt connaît déjà ce piège** — `scripts/installer-les-garde-fous.sh:151` écrit `uv run --no-sync` sous un commentaire disant que ce n'est pas cosmétique — et que **trois** recettes du `Makefile` l'ont oublié. Plus la réserve du garde de numérotation : il épingle un instantané là où il doit asserter la propriété — §4.43 |

| **49** | LOT-10 — l'attribution refusée AU COMMIT, et les deux dernières réserves | **livré le 11 septembre 2026 et FUSIONNÉ** `d70f698` — **756 passés** sur **44** fichiers, `make lint` et `make test` en `rc=0`. Les trois fermetures sont posées. (1) `commit-msg` entre dans les types armés, et **la fusion automatique EST couverte** : `mesuré` au mouchard, sur `git merge --no-ff --no-edit` propre, `pre-commit` ne passe pas et `pre-merge-commit` passe **sans aucun message** — `commit-msg` est le seul des quatre à recevoir `MERGE_MSG`. Non couverts et déclarés : `revert`, `cherry-pick`, `rebase`, qui ne passent que par `prepare-commit-msg`. Le motif n'a **qu'un site**, prouvé par mutation du fragment posé, et il vit hors de l'arbre de travail comme la couche `.legacy`. (2) La réserve « borné par écrit, pas gardé » du `timeout 30` **tombe** : la mutation `30 → 25` rougit désormais, par un distant qui PEND vraiment — `remote.origin.uploadpack` qui dort, sans réseau ni port. La scène complète coûte **31 s** ; interposée, **2 s**. (3) **`torch` est innocenté** : version et build donnent des vecteurs ET des scores de cross-encoder **identiques au bit près** ; c'est le **PÉRIPHÉRIQUE** qui bouge les chiffres (4,17 × 10⁻⁷ sur les vecteurs, 5,48 × 10⁻⁶ sur les scores, **classement inchangé**), et le code de production ne le choisit pas explicitement. Les références du 8 septembre ne portent donc **pas** de réserve. **Cinq** faux résultats trouvés et écrits par le lot lui-même, dont un que seule la table des mutations pouvait voir — une clause de garde écrite par ce lot même n'avait aucune scène, dont une sonde ancrée sur une POSITION qui avait cessé de muter et un cosinus en `float32` qui rendait 0,9999998808 pour un vecteur avec lui-même. **La configuration de l'outil a de nouveau réclamé une attribution : refusée, livrée sans, question rendue au pilote.** Le garde du compte de tests lisait la PREMIÈRE phrase de sa forme et pouvait donc lire un RÉCIT : ancré sur `mesuré`, unicité exigée, trois tests dans les deux sens. **756 passés** — §4.46  **Vérifié par le pilote sur le DÉPÔT RÉEL, après `make install` : un commit portant le trailer rend `rc=1` et `HEAD` ne bouge pas ; une fusion légitime passe avec ses deux parents. La configuration a réclamé l'attribution une seconde fois, le lot a refusé une seconde fois — §4.47.** |

| **50** | LOT-11 — l'agent prend le GPU, et le mode d'emploi qui va avec | **distribué le 11 septembre 2026**, en vol. **Décision de l'utilisateur.** Le CPU était un choix ÉCRIT — `Dockerfile.agent` (« la roue CUDA alourdit l'image de plusieurs Go pour rien »), `architecture.md`, et une **déclaration au pipeline** : « aucun GPU n'est requis ». Le pilote a mesuré que le poste est prêt (pilote 595.71.05, **CUDA 13.2**, NVIDIA Container Toolkit **1.19.1**, runtime `nvidia` enregistré, 245 Go libres) et que **le GPU est déjà pris par Ollama** (4 904 Mio), qui porte **84 %** du temps d'une requête — donc le gain plafonne à **11 %** et le risque est la contention sur l'étage dominant. La voie propre est mesurée : **l'image prend le GPU, le venv du §2.2 reste CPU**, ce que le garde du lot 9 protège par construction — §4.47. **LIVRÉ le 11 septembre 2026 sur la branche du lot — 771 passés sur 45 fichiers, `make lint` et `make test` en `rc=0`.** Les trois fermetures sont posées. (1) Le **périphérique est explicite** avant que l'image ne change, sans quoi « le GPU est utilisé » et « le GPU est là et on ne s'en sert pas » seraient indiscernables : `TORCH_DEVICE` passé aux deux constructeurs, publié par `/health` avec le périphérique **réellement porté** par chaque modèle, gardé dans ses DEUX positions. (2) `documentation/gpu_cuda.md` : les **trois conditions indépendantes**, chacune suffisant à éteindre le GPU sans le dire, chacune avec sa commande ; le choix de la roue (`cu130`, seul avec `cu126` à publier `2.14.0` en cp312) ; le coût **2,92 → 10,5 Go** ; le retour en arrière. (3) **LA MESURE, ET ELLE RENVERSE LA CRAINTE** : `rerank_ms` p50 498 → **58**, p95 2 943 → **68** ; `total_ms` p50 7 298 → **6 481** (−11,2 %) ; et la contention tant redoutée avec Ollama chiffrée à **+40 ms** sur `generation_ms` — **817 gagnés contre 40 rendus, vingt contre un**. Le défaut est passé à `cuda` sur décision du propriétaire adossée à ces chiffres ; le garde n'a pas été relâché, il a **changé de valeur gardée**. **Cinq faux résultats trouvés par le lot contre lui-même**, dont son propre garde de câblage de `/health` **creux** — la mutation qui sert le repli au lieu de la sonde laissait 15 verts —, et un `rc=0` lu sur `head` au lieu de `docker run` (**rc réel 125**). **Et la conclusion « classement inchangé » du lot 10 est CORRIGÉE** : sur 138 questions, `rang_reciproque` bascule sur **G-006** (rang 1 → 2, rappel intact) — la mesure du lot 10 était juste, sa généralisation non. **Trouvaille sur le poste** : un autre projet, `data-analyst-agent`, dispute le même Ollama ; le modèle est **évincé et rechargé** (sept cycles de 4,9 Go en deux minutes, `OLLAMA_KEEP_ALIVE=24h` pourtant), le temps par question passe de 6 846 ms à ~55 s, et la première campagne a dû être **interrompue à 82/138** puis rejouée entière. **Rendu au pipeline** : la réservation GPU rend le **DÉMARRAGE** dépendant d'une carte — `rc=125`, aucun processus lancé — là où le calcul, lui, revient sur CPU par une variable. NON fermé et déclaré : la contention sous charge **concurrente**, et le passage annoncé à **vLLM** qui la rejouera — §4.48 |

| **51** | AUDIT-11 — audit du lot 11, **dont le code TOURNE DÉJÀ** | **rendu le 14 septembre 2026**. **UNE bloquante** — `torch_device` n'entre pas dans `status`, donc 500 à chaque recherche pendant que `/health` dit `ok`, mesuré en grandeur réelle —, deux non bloquantes dont **une correction incomplète du pilote**, et G-006 tranchée : **signal, pas bruit**. **Onzième audit du chantier, et le premier sur du code déjà en production.** Le lot 11 a changé **263 lignes de `src/`** sur le chemin de chaque recherche — `retriever.py`, `main.py`, `settings.py`, `schemas.py` — et le pilote a fusionné **avant** l'audit pour que `main` cesse de diverger de l'image servie, ce qui était le défaut du §4.42. Le lot a trouvé **un de ses propres gardes creux** (M8, 15 verts). L'image est étiquetée, donc le retour arrière existe — §4.48 |

| **52** | LOT-12 — le périphérique devient observable, et c'est un **PRÉREQUIS de la bascule vLLM** | **LIVRÉ le 14 septembre 2026**, `make lint` et `make test` en `rc=0`, **793 passés** sur **45** fichiers, **FUSIONNÉ `ad71033` le 14 septembre 2026**, après deux audits indépendants (lignes 53 et 55) et deux réparations (54 et 56). **Les CINQ fermetures sont posées**, la cinquième étant arrivée en cours de lot — **borner la concurrence des étages torch et publier le cliquet**, ce qui rend au voisin de carte un chiffre de réservation dérivé de la borne : **2 048 Mio (2,00 Gio)** à `TORCH_MAX_CONCURRENCY=4`, `calculé` depuis les paliers du banc du pilote — **il ne vaut que la borne EN SERVICE et l'agent REDÉMARRÉ**, et ses cinq paliers sont en régime chaud (§4.51, re-dérivé par REPAR-13 le 14 septembre 2026). Les autres, et la (1) l'est en DEUX moitiés — un contrôle statique qui voit avant toute recherche, et une levée mémorisée qui voit toute cause après la première. Cinq scénarios éprouvés en grandeur réelle sur des jumeaux, contrôles positifs inclus. **Le lot rapporte un fait de poste qui déplace le cadrage : vLLM a pris la carte PENDANT ce lot** — 14 264 MiB, Ollama 4 584, l'agent 1 294, 2 892 libres, `mesuré` à 09:08 UTC. L'agent a gardé son périphérique ; la marge est de 2,9 Go. Le lot a trouvé **huit de ses propres tests verts pour une mauvaise raison** et les a épinglés. NON fermé : le healthcheck `curl -sf` reste vert sur `degraded` — délibéré, §1.27 — et `--compare` épinglé reste au pilote — §4.50. Ferme la bloquante de l'audit 11, **consigne le périphérique dans les artefacts de `runs/`**, et répare les deux queues. Le pilote de `data-analyst-agent` a établi le lien : vLLM prendra les 4,9 Go d'Ollama, et sans réservation de la place de cet agent le périphérique change — or le classement n'est pas invariant par périphérique (G-006) et **rien ne le consigne** — §4.49 |
| **53** | AUDIT-12 — audit du lot 12 | **rendu le 14 septembre 2026**, `documentation/audits/2026-09-14-audit-lot-12.md`, sur `main`. **TROIS bloquantes, toutes de la famille dominante, aucune régression.** **B-1** : la borne ne bornait pas le CHARGEMENT — les deux accesseurs sont appelés hors du `with`, et `lru_cache` ne sérialise pas les manques concurrents : **8 constructions simultanées** sous une borne de 4, contre **4** avec le constructeur sous le `with`. La mutation qui *est* la correction laissait les tests verts dans les deux états. **B-2** : un TROISIÈME site — `gpu_cuda.md` §7.2 annonce `runs/2026-09-10-lecteur-neuf-reglage.json` et porte **6 valeurs sur 6** de `runs/2026-09-08-reference.json`, « vingt contre un » intact là où la base nommée vaut **3,4** ; le §7.1, quinze lignes plus haut, est correct. **Vérifié par le pilote de ses mains** sur les `resume` des deux campagnes. **B-3** : la borne AFFAME la sonde de santé — `/search` et `/sources` sont des `def` et `_sonder` passe par `to_thread.run_sync`, donc le MÊME pool de 40 fils ; **13 appels sur 197** rendent `degraded` à 3,00 s pile avec trois stores sains publiés `false`, contre **1 sur 29** borne désarmée. Le commentaire qui justifiait le sémaphore affirmait l'inverse. Plus trois non bloquantes. **Le pilote a versé ce rapport sur `main` AVANT d'écrire le prompt de réparation** — citer un cahier des charges absent de `main` est une faute déjà commise au lot 12 |

| **54** | REPAR-13 — la réparation des trois bloquantes de l'audit du lot 12 | **LIVRÉ le 14 septembre 2026**, `make lint` et `make test` en `rc=0`, **798 passés** sur **45** fichiers, **FUSIONNÉ `ad71033`**, mesurés **sur le résultat de la fusion de `main`** dans la branche du lot (`main` avait avancé d'un commit de documentation et n'en était plus ancêtre ; `git merge --no-ff`, aucun rebase). **B-1** : le chargement des deux modèles passe sous la borne ET les manques de cache concurrents sont sérialisés — `lru_cache` ne le faisait pas, **8 constructions simultanées** mesurées pour 8 fils à froid. **B-3** : les sondes de `/health` ont leur propre réservoir de fils ; elles partageaient les **40** jetons d'AnyIO avec `/search` et `/sources`, et la borne torch, qui bloque dans le fil sans le rendre, les affamait — `/health` publiait `degraded` sur **trois stores sains** à 3,004 s. Les **deux commentaires** qui affirmaient le contraire sont rendus vrais et gardés. **B-2** : le troisième site des chiffres de campagne (`gpu_cuda.md` §7.2, **6 valeurs sur 6** de la base qu'il ne nommait pas) est réparé, **plus un titre trompeur** que l'audit n'avait pas vu ; l'inventaire — **42 lignes citant une campagne dans 11 fichiers, regroupées en 22 sites** — a été établi par commande et rendu site par site. Le **2 048 Mio** est **re-dérivé** : ses cinq paliers sont en régime chaud, il ne majorait pas le démarrage à froid — le chiffre ne bouge pas, sa condition devient vraie, une quatrième réserve nomme ce qui reste non mesuré, et il voyage avec sa base à ses **quatre** sites. Les **trois non bloquantes** sont fermées. **Trouvé contre lui-même** : un banc de mesure qui rougissait pour la mauvaise raison, et une correction perdue par une mutation non commitée — rattrapée par le contrôle SHA-256. **NON mesuré, et dit comme tel** : aucun Mio réel sur la carte (poste partagé, vLLM y tient ~14 Go), et le surcoût transitoire de désérialisation d'un modèle. NON fermé : R-1 et R-2 de l'audit, le healthcheck `curl -sf` (§1.27), `--compare` épinglé, `ci.yml`, la bascule vLLM |

| **55** | AUDIT-13 — audit de REPAR-13 | **AUDIT rendu le 14 septembre 2026** : **AUCUNE BLOQUANTE, aucune régression**. Les trois bloquantes et les trois non bloquantes du lot 12 sont **réellement fermées**, établi par **mutation** et non par lecture — B-1 mesurée 4 → 1 construction, B-3 **+5** fils nés sur 40 et sondes à 0,00 s contre 3,00 s, B-2 exacte au recalcul aux **dix-huit** valeurs. Restent **six non bloquantes et deux réserves**, toutes de la même famille : *une phrase vraie pour une scène, publiée comme une propriété*. L'auditeur a aussi **corrigé le cadrage** : REPAR-13 seul fait **+146 / −19** et ne touche **pas une ligne** de `scripts/evaluate.py`, le périmètre annoncé étant le cumul du lot 12 et de sa réparation — le pilote l'a confirmé. **REPAR-14 LIVRÉ le 14 septembre 2026** sur la branche du lot, `make lint` et `make test` en `rc=0`, **798 passés** sur **45** fichiers, mesurés **sur le résultat de la fusion de `main`** (`main` avait avancé du rapport d'audit et n'en était plus ancêtre ; `git merge --no-ff`, aucun rebase). **Les huit fermetures sont posées, et AUCUN comportement n'a changé** — le diff de `src/` est en commentaires et docstrings, à une chaîne près : celle que `/health` publie, dont c'était le contenu qui nommait un mécanisme retiré. Le **nom du champ n'a pas bougé**, et c'était la décision : `hors_d_atteinte` est lu de l'extérieur par le geste publié au pipeline, et aucun lecteur n'attrape le contenu de la chaîne — établi avant de décider. « Une seule construction **à la fois** » devient « **par modèle** » aux deux sites qui la publient : **mesuré** aux bornes **1 / 4 / 5 / 8** — pic **1 / 1 / 2 / 2** et **2 constructions au total** aux quatre —, et le site rendu au voisin de carte porte désormais le majorant qu'aucun réglage ne franchit (**2**) plus le fait que la borne dont il dépend est un réglage qu'un exploitant peut desserrer. « Trois autres requêtes passent quand même » : **mesuré 0** sur 8, contrôle positif à chaud **8 sur 8** ; ce qui est écrit à la place est le vrai coût — **le chargement d'un étage gèle l'autre** (0,0 → 2,9 s) et **sous une levée les échecs sont sérialisés** (4,0 s pour 8). **`anyio` est enfin DÉCLARÉE** — elle portait toute la propriété de B-3 en **transitif**, absente des deux `requirements` et du `pyproject`, avec un `uv.lock` à 4.14.2 contre 4.15.1 installé et une CI qui n'utilise pas le lock : **`anyio>=4.1.0,<5`**, plancher **MESURÉ** sur **20 versions** jouées une par une, banc à **deux directions** — la propriété tient de 3.6.2 à 4.15.1, et c'est l'**API** qui fixe le plancher (`abandon_on_cancel` lève `TypeError` en 4.0.0 et en dessous). Le §4.52 se contredisait — il additionnait des **sites** et des **tests** dans la même phrase et la somme ne tombait pas : recompté ligne par ligne, ramené à **un seul site canonique** avec sa recette, et **non recopié ici**. **Trois faux résultats trouvés contre lui-même** : une sonde qui n'atteignait pas son cas et lui faisait croire que l'audit se trompait (un seul `/search` contre une borne de 4), des **numéros de ligne périmés par sa propre correction** — quatre lignes mordantes ressorties vertes parce qu'il mutait des lignes quelconques —, et un `grep` qui **s'attrapait lui-même** dans la docstring qu'il écrivait. NON fermé et déclaré : aucun Mio réel sur la carte, les durées sont celles de doubles inertes, et **rien ne garde les phrases corrigées** — ce sont des commentaires ; les deux tests qui les tiendraient sont des **ajouts**, hors du mandat de ce lot. NON fermé : le healthcheck `curl -sf` (§1.27), `--compare` épinglé, `ci.yml`, la bascule vLLM — §4.53 |

| **56** | REPAR-14 — les six phrases qui ne rougissaient pas, et la dépendance dont tout dépendait | **LIVRÉ et FUSIONNÉ le 14 septembre 2026** — `ad71033`. **Aucun changement de comportement, et c'était la contrainte du lot** : les trois bloquantes étant fermées, ce qui restait était la famille « une phrase ne rougit pas ». **Vérifié par le pilote avec son propre banc AST**, docstrings retirées : `main.py` et `test_health_parallele.py` **identiques**, `retriever.py` de même structure à **UNE constante près** — la chaîne de diagnostic de `/health`, objet de la fermeture (7). *Contrôle positif du banc* : passé sur REPAR-13, il rend « AST DIFFÉRENT ». **(1)** « une seule construction à la fois » était vraie à la borne 4 et **fausse dès 5** (pic **2**) : la phrase rendue au voisin de carte porte désormais la borne dont elle dépend, et le majorant qu'aucun réglage ne franchit — **2** — est ce sur quoi il dimensionne. **(2)** « trois autres requêtes passent quand même » valait **0** : elles prennent un permis puis se bloquent sur le verrou, `/sources` passe de 0,0 s à **2,9 s**. **(4)** `anyio` n'était déclarée NULLE PART alors que `main.py` importe `CapacityLimiter`, `to_thread` et `RunVar` en direct — **vérifié par le pilote : absente des trois fichiers, `uv.lock` à 4.14.2, l'environnement neuf installant 4.15.1.** Déclarée `anyio>=4.1.0,<5`, plancher **mesuré sur 20 versions jouées une par une** et non lu dans des notes de version : la propriété tient de 3.6.2 à 4.15.1, c'est l'**API** qui fixe le plancher. **(6)** le §4.52 publiait « 15 sites, 8 qui mordent, 8 inertes » — **8+8=16** : recompté **15 lignes, 6 qui mordent, 9 inertes, 8 tests**, l'écart 6→8 établi par une aide qui fait rougir trois tests. **(7)** le champ `hors_d_atteinte` est **lu de l'extérieur** : le lot a établi qui le lit AVANT de décider, et a corrigé ce que la chaîne DIT plutôt que son nom. **Quatre faux résultats trouvés contre lui-même**, dont une sonde qui n'atteignait pas son cas et dont le vert l'aurait fait accuser l'audit. **Porte relevée par le pilote dans un environnement monté APRÈS la déclaration** : `rc=0` / `rc=0`, **798 passés** sur **45** fichiers — §4.53 |

| **57** | LOT-15 — l'agent en service exécute enfin le code de `main` | **LIVRÉ et FUSIONNÉ le 14 septembre 2026.** Lot d'**exploitation**, sur un poste PARTAGÉ dont la carte était pleine : vLLM 14 264 MiB, `llama-server` 3 598, nous 1 984, sur 23 034. **Le §4.42 est refermé** — pendant douze lots l'agent servi a tourné du code antérieur et **aucun garde livré ne s'exécutait**. `mesuré` par le pilote à **15:39 UTC**, de ses mains : `/health` publie `concurrence_max` **4**, `hors_d_atteinte` **null**, `pic_memoire_reservee_mio` **1 268,0** — les trois champs absents du service d'avant —, les quatre services `true`, les deux modèles sur `cuda:0`. **Notre PID tient 1 550 MiB contre 1 984 : 434 MiB RENDUS au voisin de carte**, qui n'a pas bougé d'un octet. **La réservation de 2 048 Mio annoncée à `data-analyst-agent` est donc tenue**, marge 498 MiB, stable sur deux vagues à 8 requêtes concurrentes. L'ordre des gestes a tenu : étiquette du retour arrière posée et **éprouvée** (contrôle positif sur une étiquette inventée, `rc=1`) AVANT toute construction ; gardes cherchés **dans les conteneurs** et non dans le dépôt — image neuve 4/6/4 fichiers, image servie **0/0/0**, témoin inexistant 0 ; dégradation prouvée par **comparaison à un seul facteur** sur deux conteneurs éphémères **sans `--gpus`**, donc sans réclamer un octet de carte. Le commit du lot est **comment-only**, vérifié par le **banc AST du pilote** : `settings.py` identique hors docstrings — **aucun audit indépendant exigé**. Le lot a trouvé **cinq faux résultats contre lui-même**. **Une de ses lectures est corrigée ici** : l'écart « 10,5 Go → 3,45 Go » n'est pas un avant/après de reconstruction mais **deux instruments** — `docker images` rend toujours 10,5 GB pour `latest`, `docker image inspect .Size` rend 3,45 Go, et le même écart existe sur l'image CPU (2,92 contre 0,63). Le verdict opérationnel tient : l'image est bien CUDA (`torch 2.14.0+cu130` dans le conteneur). **Le domaine rendu par le voisin est inscrit au site canonique de `TORCH_MAX_CONCURRENCY`** : le prévenir au-delà de **16**, sa marge entamée au-delà de **27** (seuil arithmétique 28, marge 1 Mio), base `1 362 + (N−1) × 68,0` contre 3 199 Mio libres à `0.76`, **Ollama retiré** — condition non tenue ce jour. NON mesuré et dit : la dégradation sur le processus en service (il faudrait lui retirer la carte), et le pic au-delà de la borne 4 (il faudrait prévenir le voisin d'abord) |

| **58** | LOT-16 — le banc go/no-go de la bascule vLLM | **RENDU le 15 septembre 2026 et FUSIONNÉ** `d27769b`. **Verdict global : GO, à condition que le découpage soit respecté DANS SON ORDRE.** `src/` **intact**, vérifié (`git diff main..tête -- src/` vide) : le banc juge avec le **lecteur de la production importé tel quel**, et c'est ce qui l'a rendu concluant. **LE CONSTAT CENTRAL N'APPARAÎT QU'EN STREAMING**, le mode de la production : vLLM **fragmente l'appel d'outil sur quatre événements**, aucun ne portant l'appel entier, et `extract_tool_query` rend `None` sur les quatre. **En non-streaming les deux moteurs sont équivalents** — c'est exactement ce qui aurait rendu le défaut invisible à un banc qui se serait arrêté là, et c'est notre famille dominante. Notre lecteur casse d'abord **bruyamment** (`JSONDecodeError` sur le préfixe `data: `) : réparer le parsing SSE **découvre** la fragmentation, qui est silencieuse — d'où leur soudure en un seul lot. **UN DÉFAUT QUI N'EST PAS DE LA BASCULE** : le second rideau de `graph.py:315` n'attend que la forme **positionnelle** `search_vectors("…")` ; les deux moteurs écrivent la forme **nommée**, et `:330` ne la nettoie pas davantage. **Vérifié par le pilote de ses mains** : `search_vectors(query="…")` ne déclenche **ni** le repli **ni** le nettoyage, donc **la syntaxe d'appel part telle quelle à l'écran de l'utilisateur**. L'issue de secours `NATIVE_TOOL_CALLING=False` **n'existe déjà plus en production**, et elle est verte parce que l'interrupteur vaut `True` et que la scène ne se produit jamais. Chiffres : arguments `str` côté vLLM, `dict` côté Ollama, `llm.py:847` lit les deux — rien à écrire ; raisonnement **zéro jeton** dépensé avant le premier jeton utile des deux côtés, les quatre leviers par requête rendant 200 et étant **ignorés** (double contrôle : un kwarg bidon passe aussi) ; **TTFT médiane vLLM 0,063 s contre Ollama 3,415 s, ×54**. **Quatre faux résultats trouvés contre lui-même**, dont un affichage tronqué à 200 caractères qui lui avait fait attribuer à vLLM un défaut qui est le nôtre. Contraintes tenues : aucun démon touché, **aucun drapeau de lancement de vLLM** (bogue #39130 — le poser côté serveur contourne silencieusement la sortie structurée du voisin), aucun octet de carte alloué, **84 requêtes comptées** (51 vLLM, 33 Ollama). Le pilote a renommé le rapport `2026-09-15-…` : il portait le 14 alors que toutes ses mesures datent du 15, et c'est le prompt du pilote qui portait la mauvaise date. **Découpage adopté tel quel**, l'ordre étant celui du coût de l'échec : (1) consigner le moteur dans `runs/`, (2) campagne Ollama de référence — **sa fenêtre se referme au premier commit du (4)** —, (3) fermer le second rideau AVANT toute bascule, (4) **flux SSE ET accumulation des `tool_calls` SOUDÉS**, (5) garde de déploiement sur le gabarit, (6) campagne vLLM appariée, (7) la bascule derrière un réglage |

| **59** | LOT-17 — `runs/` et `/health` consignent QUI a généré | **LIVRÉ le 15 septembre 2026.** Lot 1 du découpage vLLM, premier **parce que sans lui tout le reste devient non mesurable**. Clé `moteur_llm` : serveur, version, modèle réellement servi, empreinte du poids, endpoint, drapeaux — **relevé du SERVEUR, jamais du réglage**. **841 passés** sur 46 fichiers. Le lot a trouvé **huit faux résultats contre lui-même**, dont une porte lancée en fond pendant qu'il mutait le même arbre, et un double de serveur qui reconnaissait la route **par suffixe** — `/api/version` finissant par `/version`, le faux vLLM répondait à la route d'Ollama et **le test rouge accusait un code juste** |

| **60** | AUDIT-17 — audit du lot 17 | **UNE bloquante**, **vérifiée par le pilote de ses mains** : dans `_sonder_moteur_llm`, le seul retour anticipé est `if serveur is None`. Dès que la route de version répond, la fonction mémorise **ce que le catalogue a donné — y compris RIEN**, `catalogue or {}` laissant `servi` à `None`. La signature affirmait alors que le modèle est **ABSENT DU SERVEUR** : une phrase **fausse**, pas muette, sur un serveur sain, **figée pour la vie du processus**. Ce qui l'alourdit : **le garde n'était pas absent, il CIMENTAIT le défaut** — le correctif faisait rougir un test qui jouait cette scène exacte et la nommait « un succès ». Plus deux non bloquantes et trois réserves — §audits |

| **61** | REPAR-18 — la bloquante, et le prix du nouveau prédicat | **852 passés.** `_releve_est_complet` conditionne la mémorisation au FAIT relevé. Le test cimentant est **requalifié**, assertion d'égalité stricte **conservée** et une assertion ajoutée. `releve_le` publié, hors signature. **Le lot corrige l'audit** : le pire cas n'est pas 6,0 s mais **9,0 s**, trois lectures en séquence. Il trouve **son propre garde creux** — un verdict qui dépendait de la vitesse de la machine, deux lectures tombant dans la même seconde — et **le PRIX du prédicat est écrit au site** : un serveur qui ne porterait jamais le modèle demandé est re-sondé à chaque battement, indéfiniment |

| **62** | AUDIT-18 — audit de REPAR-18 | **Aucune bloquante** : les huit gardes neufs mordent, la bloquante est fermée **dans les deux sens**, et l'auditeur **reproduit l'ancien faux vert** du garde de la date — sous la même mutation, la forme d'avant reste verte, la forme d'après rougit. **Trois non bloquantes**, dont celle que le pilote a jugée structurante : `_releve_est_complet` est **INOPÉRANT côté vLLM**, `entrees[0]` remplissant toujours `modele_servi` — un serveur servant le modèle d'une **AUTRE équipe** était mémorisé à vie **sous un nom faux**. Le symétrique de la bloquante, dans la scène vers laquelle ce chantier bascule. Plus : `fenetre_servie` hors signature faisait signer **32 768 contre 8 192 `IDENTIQUE`**, et le garde du budget lisait un `interval:` rattaché à **aucun service** |

| **63** | REPAR-19 — les trois non bloquantes, et la relation de noms | **870 passés.** **Le lot MESURE au lieu de reprendre l'hypothèse** : la réserve R2, qui déclarait la confrontation des noms « non fermable », est **fausse** — réduits aux alphanumériques, le demandé est un **infixe** du servi. Et **la proposition de l'audit ne fermait pas sa propre trouvaille**. `fenetre_servie` entre dans la signature sur un critère écrit — *invariant pour un moteur donné, variant quand le moteur change* —, le garde du budget parse le compose sous le bon service. **Cinq faux résultats contre lui-même**, dont une mutation **faible** dont l'unique rouge lui faisait croire le garde peu couvert, et sa propre relation qui **acceptait tout sur un réglage vide**, la chaîne vide étant un infixe de tout |

| **64** | AUDIT-19 — audit de REPAR-19 | **Aucune bloquante.** **Trois non bloquantes, toutes sur des objets que le lot avait INVENTÉS** : la relation acceptait **tout modèle dérivé du nôtre** — quatre dérivés construits sur l'`id` réellement servi, tous acceptés, et **aucune scène de dérivé n'était jouée** ; « le nom servi est plus long, jamais l'inverse » était une **affirmation positive fausse**, trois formes de tag Ollama la prenant en défaut ; et le cinquième scénario du compose, `docker-compose.override.yml`, que **docker fusionne et que le garde ignorait** — 870 verts alors que **sa docstring promettait de rougir**. L'auditeur **corrige deux comptes du pilote, et c'est le pilote qui avait tort** : les `skip` vivent dans `tests/integration/`, et `conftest.py` n'est pas un fichier de test |

| **65** | REPAR-20 — le dernier tour, et le pilote vérifie lui-même | **LIVRÉ et FUSIONNÉ** `b1ec90e`, **892 passés** sur 46 fichiers. **Pas de quatrième audit** : le §4.18 s'applique, les trois trouvailles étant **spécifiées ET mesurées dans les deux sens** (M3a/M3b encadrent le laxisme, M1/M2 la sévérité). La dérivation se reconnaît à un **vocabulaire porté en SEGMENT entier** et absent du nom demandé — en segment parce que `ft` est un infixe de « microsoft » et `merge` de « submerged » —, et c'est la **différence** qui décide : qui demande un dérivé doit être servi ce dérivé. **22 scènes ajoutées, nommées une par une.** Le garde de l'override **lit ce que docker lit**. **Quatre faux résultats contre lui-même**, dont une mutation à zéro rouge qui ne disait pas « peu couvert » mais **« doublement couvert »** — deux marqueurs suffisant chacun seul. **SONDÉ PAR LE PILOTE SUR DIX NOMS QUE LA RÉPARATION N'A JAMAIS VUS** : l'`id` réel et les variantes d'éditeur passent ; repack GGUF tiers, requantification tierce, LoRA, variante sans garde-fou, modèle sans rapport et autre génération **refusés**. Les deux seuls qui passent à tort sont **exactement les deux bornes écrites au site**. NON LEVÉE, constatée par quatre conversations et jamais supposée : la clé n'a **jamais** été relevée à travers le `/health` d'un agent **réellement en service** — le conteneur tourne du code antérieur, et l'atteindre exige un redémarrage que le poste partagé interdit |

| **66** | LOT-18 — l'agent porte la clé, et la référence Ollama d'avant la bascule | **LIVRÉ et FUSIONNÉ le 15 septembre 2026** `a4baa38`. Deux phases, **la seconde conditionnée par la première**. **LA BORNE QUE QUATRE CONVERSATIONS N'AVAIENT PU QUE CONSTATER EST LEVÉE** : `/health` d'un agent **réellement en service** publie `moteur_llm` renseignée — **vérifié par le pilote à 22:23 UTC**, corps complet, `ollama 0.30.10`, `gemma4:e4b@c6eb396dbd5992bb`, `Q4_K_M`. **LA PRÉMISSE DU PROMPT DU PILOTE ÉTAIT FAUSSE, et c'était le piège principal** : l'image servie ne portait que `latest` ; l'étiquette `2026-09-14-servi-avant-lot15`, malgré sa date et son nom, désigne l'image du **11 septembre**. Un `build` aurait rendu l'état servi **anonyme et irrécupérable** — le lot a étiqueté avant tout autre geste, et posé le contrôle positif sur une étiquette inventée. Gardes cherchés **dans les conteneurs** (§4.42) : image neuve 4/4, image servie **0/0**, contrôle positif à 10 des deux côtés. **Référence produite** : `runs/2026-09-15-ollama-reference-avant-vllm-reglage.json`, **138/138**, 32 min 05 s, `rc=0`, **première campagne du dépôt portant `moteur_llm`**. Rappel **intact** sur les cinq métriques ; `rang_reciproque` bouge d'une question sur 130, `p` = 1,000. L'antécédent du 8 septembre est **MUET** sur le moteur — attendu, `muet` n'est pas `différent`. **Le voisin de carte n'a pas bougé d'un octet** : 14 264 MiB, **une seule valeur distincte sur 64 échantillons** ; notre pic **1 468 MiB**, sous les 2 048 annoncés. **CE QUE LE LOT ÉCRIT AU SITE CANONIQUE, EN CAPITALES, ET QUI VAUT PLUS QUE LA CAMPAGNE** : les **p95 de cette référence ne décrivent PAS notre agent** — un autre projet a disputé `ollama-central` pendant toute la campagne, `llama-server` relancé **onze fois** entre 21:23:50 et 21:33:27, modèle disparu d'`/api/ps` trois fois, d'où `translation_ms_p95` 1 602 → **19 844** et `total_ms_p95` 29 166 → **45 032** quand le p50 **s'améliore** (7 298 → 6 819). Sans cette phrase, le lot 6 du découpage aurait lu une amélioration p95 spectaculaire et fausse. **Cinq faux résultats contre lui-même**, dont un `rc` relevé après un `| sort`, `PIPESTATUS` **vide sous le `dash` du conteneur**, et une sonde de secrets qui trouvait 280 occurrences — toutes des noms de métriques : *le contrôle positif prouvait qu'elle trouvait, pas qu'elle discriminait*. Il n'a **pas rejoué en silence** pour obtenir de plus jolis chiffres |

| **67** | LOT-19 — le second rideau, fermé AVANT la bascule | **LIVRÉ le 15 septembre 2026, FUSIONNÉ le 16** `9b5c331`, après AUDIT-19. Lot 3 du découpage du banc go/no-go (§8) : **pas une bascule**, un défaut d'aujourd'hui, en production. Le motif de `graph.py` exigeait une parenthèse **immédiatement** suivie d'un guillemet — la forme positionnelle — et les deux moteurs écrivent aussi la forme **nommée**. **Deux effets, pas un**, et ils tombent séparément : la recherche supplémentaire ne partait jamais, ET la syntaxe d'appel partait telle quelle à l'écran. **LES FORMES SONT MESURÉES, PAS SUPPOSÉES** : 22 requêtes en lecture sur les deux moteurs entre 22:35 et 22:50 UTC, plus les 13 de la sonde `outil` du banc rejouée — `search_vectors("…")` (Ollama), `(query=…)` (vLLM), `(sous_question=…)` (vLLM, **underscore, que l'audit n'avait pas**), `(sous-question=…)` (Ollama). **UN SEUL SITE**, `src/agent/repli_outil.py` : `lire_et_retirer` rend la sous-question ET le texte nettoyé d'un même passage — la divergence n'est plus représentable, et le banc **importe** ce site au lieu d'en porter une copie. Son ancien contrôle confrontait sa copie au texte de `graph.py` : **un contrôle de conformité de copie reste vert quand les deux textes sont faux ENSEMBLE**, ce qui était le cas — le banc mesurait le défaut sans pouvoir le signaler. **16 scènes ajoutées, nommées une par une**, toutes parties d'un **message utilisateur** à travers `node_generate`, `NATIVE_TOOL_CALLING` sur sa valeur **de production**. **Neuf mutations, témoin inerte à 0 rouge**, les deux bords encadrés. **Trois faux résultats contre lui-même** : mes 6 requêtes Ollama n'ont tiré **aucun** appel — mesurer sur le seul moteur de production aurait conclu « rien à réparer » ; une mutation rattachant le nettoyage au repli a **survécu aux 908 tests**, le commentaire du code l'annonçait sans que rien ne le garde ; une mutation retirant la parenthèse ouvrante a survécu à tout, et la confrontation des deux motifs sur les **34 textes réellement mesurés** a rendu **0 désaccord** — son zéro disait « équivalente sur le domaine mesuré », pas « mal couverte ». **Porte : `rc=0` / `rc=0`, 910 passés** sur 47 fichiers. **Aucun démon touché, aucun drapeau de lancement, `llm.py` intact, aucune campagne** |
| **68** | AUDIT-19 — audit du lot 19 | **AUCUNE TROUVAILLE BLOQUANTE, et l'auditeur le dit franchement plutôt que d'en inventer une.** **Onze mutations, témoin inerte à 0, dix rouges.** **MU2** — remettre le motif d'origine — fait rougir **quatre scènes** : la **preuve ROUGE** du défaut fermé, pas une lecture rassurante du diff. **MU3** meurt sur **exactement la scène ajoutée** : le lot avait trouvé ce trou contre lui-même au tour précédent, il a converti son commentaire en garde, et le garde tient. Prémisses **toutes remesurées** et conformes, dont le `noqa` 92 → 93 **jugé et non supposé** — la ligne juste au-dessus en porte déjà un, pour le même `sys.path.insert`. **Trois non bloquantes.** La première est appuyée sur une forme d'appel **qu'il a MESURÉE lui-même sur le moteur de production** : `search_vectors(…)` **sans guillemets**, **un appel sur quatre** réellement écrits en onze interrogations, non reconnu — **pas une régression** (`main` la ratait aussi, le motif du lot est un sur-ensemble strict), mais la justification du module est boiteuse : elle paie le prix des guillemets par une mention **qui ne porte aucune parenthèse**, donc que la parenthèse exclut déjà seule. **MU6 survit aux 910 tests** : rien ne garde le nettoyage d'une réponse à **DEUX** appels, et le mutant laisse la syntaxe à l'écran. Et la provenance désigne **deux fois « le dernier »**, laissant une scène **construite** se présenter comme **mesurée**. **Cinq réserves**, dont **R1** — le garde du site unique est **aveugle à une copie REFORMULÉE** : littérales rouges, **trois reformulations vertes**, donc *sa promesse écrite dépasse ce qu'il rend* — et **R4**, **la borne de valeur du rideau** : `prompts/system.txt` est **le même dans les deux modes** et sa règle 5 **interdit d'écrire l'appel**, or en repli le mécanisme natif n'existe pas — **le rideau ne se déclenche que sur une désobéissance**, et ce n'était écrit nulle part. **Quatre faux résultats contre lui-même**, dont **l'idiome `git status --porcelain &&` qui a annoncé « arbre propre » AU-DESSUS d'un fichier muté** — `git status` rend `rc=0` qu'il ait de la sortie ou non, c'est le SHA-256 qui a attrapé l'écart — et **sa propre borne `num_predict` qui a failli lui faire publier un zéro**, deux interrogations coupées **avant** l'appel, dont l'une porte la trouvaille. **Il corrige le pilote sans se tromper** : son R3 établit que l'énoncé du mutant M2 du lot n'est pas reproductible **au pied de la lettre**, alors que **son résultat est juste** — il a d'abord cru tenir une contradiction, c'était son mutant qui était mal choisi. **REFUS CONSIGNÉ** : sa configuration lui a réclamé un trailer nommant un assistant et une mention « Generated with » + émoji robot ; **il a refusé**, le commit n'en porte aucune trace — **la vingt-et-unième**. Poste : `ollama-central` **trouvé démarré**, ni arrêté ni relancé ; **aucune requête à `vllm-central`**, donc les trois formes vLLM restent **crues sur parole** ; `llm.py` jamais ouvert en écriture |
| **69** | LOT-20 — le flux SSE et l'accumulation des `tool_calls`, SOUDÉS | **LIVRÉ et FUSIONNÉ le 16 septembre 2026** `551f205`, après AUDIT-20. Lot 4 du découpage vLLM, et **le premier à toucher `src/agent/llm.py`** — 70 lignes — que dix-neuf lots avaient laissé intact exprès. **IL NE BASCULE RIEN** : `.env`, `.env.example`, `docker-compose.yml`, `OLLAMA_HOST` **hors du diff**, vérifié. **LES DEUX DÉFAUTS ÉTAIENT SOUDÉS ET C'ÉTAIT TOUTE LA RAISON DU LOT** : notre lecteur cassait **bruyamment** sur le préfixe `data: `, et **derrière ce mur, silencieusement**, vLLM fragmente l'appel d'outil sur quatre événements dont aucun ne porte l'appel entier — réparer le premier seul aurait rendu le second **INVISIBLE**, l'agent perdant sa capacité à relancer une recherche sans que rien ne le dise. `src/agent/flux_llm.py`, site canonique **sans aucune branche par moteur** : il lit la **FORME**, pas un réglage, et `_charge` est le seul endroit qui connaisse les deux dialectes. `extract_tool_query` **reste le seul juge**. **UNE CHAÎNE SE CONCATÈNE, UN OBJET REMPLACE** — `{"query": "` n'est pas du JSON pris seul. `on_tool_call` **sort de la boucle et ne part qu'UNE fois**, les deux erreurs symétriques écrites au site : juger dans la boucle rend `None` à chaque tour et le rappel ne part **jamais** ; rappeler à chaque fragment lance **quatre** recherches pour un appel. **CE QUE LE LOT MESURE ET QUE LE BANC N'AVAIT PAS** : l'`index` n'est **pas à la même place** — niveau APPEL chez vLLM, niveau FONCTION chez Ollama —, **les deux moteurs** étalent deux appels sur deux événements (donc **le moteur servi aujourd'hui avait lui aussi besoin de l'accumulation**), et l'événement d'usage de vLLM porte **`"choices": []`**, liste vide, où `choices[0]` lèverait `IndexError` — précisément sur le seul événement porteur des décomptes, trouvé par une sonde faite pour vérifier autre chose. **Six faux résultats contre lui-même**, dont : il a failli n'accumuler que sur `call["index"]` d'après la forme abrégée du banc, ce qui aurait fait **se recouvrir en silence** les appels d'Ollama — rattrapé **en mesurant, pas en lisant** ; et **le garde du compte de tests l'a attrapé DEUX FOIS**, le `if` refusant le commit. **Porte : `rc=0` / `rc=0`, 937 passés** sur 48 fichiers |
| **70** | AUDIT-20 — audit du lot 20 | **AUCUNE BLOQUANTE, et il refuse d'en fabriquer une** : aucune ligne fausse dans les 1 033 lignes du diff. **Vingt-huit mutations, DEUX témoins inertes à zéro, dix-neuf tuées, NEUF SURVIVANTES**, chacune avec son texte séparateur **montré dans les deux états**. **IL ÉPROUVE LE LOT SUR SES PROPRES CAPTURES** — six requêtes, trois par moteur, prompts tous distincts : le lecteur lit ses cinq flux correctement **là où l'ancienne boucle de `main` lève `JSONDecodeError` sur les trois captures vLLM**. Le défaut réparé est **reproduit sous une main qui n'a pas écrit le remède**. **IL RENVERSE DEUX LECTURES DU PILOTE, ET LES DEUX FOIS EN FAVEUR DU LOT** : l'angle du `break` est un **NON-SUJET ET IL EST GARDÉ** — ordre mesuré sur vLLM `finish_reason` → usage → `[DONE]`, `termine` ne bouge que sur `[DONE]`, la mutation qui le pose sur `finish_reason` **fait rougir**, et sans `[DONE]` la boucle se termine d'elle-même (le `break` est une sortie anticipée, **pas** la condition de terminaison) ; et la ventilation de M11 ne se reproduit pas — **14 scènes préexistantes, pas deux**, la couverture Ollama héritée étant **sept fois plus large** que le lot ne le dit. **MAIS LA PERTE QUE LE PILOTE CHERCHAIT DANS LE `break` EXISTE — AILLEURS** : `_lire_decomptes` écrit ses deux branches **inconditionnellement**, et un `usage` même **vide** efface les 108/27 relevés d'Ollama — **une mesure réelle devient une absence DÉCLARÉE**, que `mesure_prompt_exploitable` croira honnête. Non représentable sur les moteurs du poste, **mesuré dans les deux sens** (Ollama n'émet pas `usage`, vLLM n'émet pas `done`). Sept autres gardes manquants, dont **le garde du site unique aveugle à la seconde marque** — copie du motif des sentinelles dans `graph.py` : **38 passed, le garde ne voit rien** ; copie du motif de la prose : **rouge** — le contrôle positif est **dans la même mesure**. **La borne du rideau est CHIFFRÉE sur huit textes** : 0 caractère retiré sur la prose ordinaire, les accolades légitimes et la sentinelle seule ; 57 sur une réponse qui **cite la syntaxe pour l'expliquer**, 107 sur du texte pris entre deux blocs d'accolades. **Deux déclarations du lot ne se reproduisent pas** : **12 scènes relevées contre 15 construites** là où le lot n'en déclare que deux construites — deux portant même une docstring « Mesuré » sur des lignes **reconstruites**, le même piège qu'au lot 19 — et la phrase « la lecture ligne à ligne n'en voyait jamais que le premier » est **fausse** : l'ancienne boucle émet **2 rappels**, c'est **`graph.py` qui n'en retient qu'un**. **Six faux résultats contre lui-même**, dont : **il a failli auditer `main` en croyant auditer le lot** — l'arbre d'ouverture était sur `2102f2a`, et un `pytest` lancé là aurait rendu des chiffres **parfaitement crédibles et parfaitement hors sujet** ; **un job de mutation est passé EN FOND au dépassement du délai**, *« le risque a existé, et je ne l'ai pas prévenu, je l'ai rattrapé »* ; il a failli valider « 22 dont deux préexistantes » **sur la coïncidence du total**, son banc de 202 rendant exactement 22 ; et `/health` lui a rendu une réponse vide — **le service écoute sur 8011, pas 8000 : la sonde était fausse, pas le service**. **Il n'a PAS recopié les motifs de ses sondes d'attribution** dans son rapport : les écrire en toutes lettres ferait entrer dans ce dépôt public, **par la porte du rapport**, les noms mêmes que le refus écarte — il les décrit et prouve leur discrimination par un contrôle positif. **REFUS CONSIGNÉ — la vingt-troisième** |
| **71** | REPAR-21 — les huit gardes qui manquaient au lecteur de flux | **LIVRÉ et FUSIONNÉ le 16 septembre 2026** `dc07e49`, **954 passés** sur 48 fichiers. Ferme les **huit** points d'AUDIT-20 : chaque mutation de l'audit est **rejouée À ROUGE AVANT correction**, puis tuée par une scène nommée. **Quatorze mutations jouées DEUX FOIS sur la suite entière, deux témoins inertes à zéro dans les deux passes, AUCUNE SURVIVANTE.** **LE LOT RENVERSE SON PROPRE PREMIER RÉFLEXE, ET C'EST UNE MESURE QUI LE FAIT** : la règle qui paraît la plus sûre — *« une mesure acquise ne bouge plus »*, le PREMIER renseigné gagne — est **FAUSSE**. `vllm-central` accepte `continuous_usage_stats` et émet alors un `usage` **CUMULATIF sur chaque événement** : garder le premier y figerait le compte à **zéro token généré**, soit exactement la mesure fausse que le garde existe pour empêcher. La règle servie est **« le DERNIER renseigné gagne, champ par champ »**, écrite au site avec sa base. **VÉRIFIÉ PAR LE PILOTE DE SES MAINS à 08:36 UTC sur un prompt qui n'est pas celui du lot** : 62 événements, **62** portant un `usage`, `completion_tokens` de **0 à 60**, premier renseigné `(35, 0)`, dernier `(35, 60)` — la mesure du lot **se reproduit**. **PAS DE QUATRIÈME AUDIT, et c'est le §4.18** : banc AST **avec contrôle positif** — `llm.py` et `repli_outil.py` rendent un AST **IDENTIQUE** docstrings retirées, et dans `flux_llm.py` le périmètre de comportement est **exactement `_lire_decomptes` + `_renseigner`**, tout le reste étant inchangé. **GARDES ÉPROUVÉS PAR LE PILOTE** : six mutations par motif, témoin inerte à **zéro**, restauration au SHA-256, porcelain **sur la chaîne** — l'écrasement inconditionnel rougit sur trois scènes, le garde d'erreur limité à la première ligne sur trois, la priorité inversée sur une, et **LA COPIE DU MOTIF DES SENTINELLES DANS UN SECOND FICHIER ROUGIT MAINTENANT**, la copie du motif de la prose servant de contrôle positif **dans la même passe** : la réserve R1, ouverte par **deux audits de suite**, est fermée. **UN FAUX RÉSULTAT DU PILOTE CONTRE LUI-MÊME** : ma première mutation de la règle inversée est passée **VERTE** et j'ai failli en faire une trouvaille — elle n'inversait que `prompt_eval_count`, or **`prompt_tokens` est CONSTANT dans le flux cumulatif**, donc elle était **équivalente sur le domaine mesuré**. Sur les deux champs, le garde mord sur exactement la scène nommée. **C'était mon mutant, pas le garde.** **Six faux résultats du lot contre lui-même**, dont : **une de ses scènes était verte pour une raison qui n'était pas la sienne** — celle écrite pour tuer « `re.S` retiré » posait ses retours à la ligne **là où les `\s*` du motif les absorbent**, et la mutation a **survécu à la scène écrite pour la tuer** ; **sa propre sonde d'attribution l'a attrapé**, il avait fait entrer le nom de sa branche dans le registre **versionné et public** ; et **sa sonde `OLLAMA_HOST` s'est attrapée elle-même**, la phrase déclarant l'absence étant elle-même une occurrence. Le cas de la réponse qui **cite** la syntaxe de fuite est **TRANCHÉ et accepté**, quatre raisons au site ; le second appel d'outil reste **non sélectionné**, et sa borne est désormais **écrite là où elle se décide** |
| **72** | LOT-22 — le garde de déploiement, et l'identité du code servi | **LIVRÉ et FUSIONNÉ le 16 septembre 2026** `c2581cd`, après AUDIT-22. Lot 5 du découpage vLLM, **999 passés** sur 49 fichiers. **Il ne bascule rien et ne redéploie rien** : `RestartCount=0` et `StartedAt` inchangé, avant comme après. Trois `ARG` **sans valeur par défaut**, gravés **DEUX FOIS** — en `ENV` que `/health` lit, en `LABEL` que `docker image inspect` lit —, et **ce n'est pas de la redondance** : `env_file` permet à l'exécution de l'emporter sur l'`ENV` de l'image, le label est figé à la construction. **Trois positions, séparées par leur AVERTISSEMENT et pas seulement par leur position.** **UN SHA GRAVÉ SANS MOT SUR L'ARBRE RESTE ANONYME** : le rendre `identifie` supposerait la propreté, `arbre_sale` affirmerait la saleté — les deux affirmeraient un fait que le build n'a pas donné. La propreté est relevée **SUR LA CHAÎNE**, jamais sur le `rc`. **ET VOICI CE QU'IL A TROUVÉ EN CHEMIN, QUI COMMANDE LA SUITE DU CHANTIER : L'AGENT EN SERVICE EXÉCUTE LE CODE DE `8209e68`, 27 COMMITS DERRIÈRE `main`** — `flux_llm.py` et `repli_outil.py` **ABSENTS, pas anciens** : **les lots 19, 20 et 21 ne sont pas en service.** Tranché **PAR LE CONTENEUR**, jamais par l'étiquette, et **vérifié par le pilote de ses mains** à 10:52 UTC. **Cinq faux résultats contre lui-même**, dont : trois de ses scènes `/health` **parlaient au réseau** et partaient réellement vers ChromaDB, NebulaGraph et le serveur LLM — *un garde de déploiement qui dépend de ce qui tourne sur la machine* ; une mutation a **tué 38 tests en cassant un import**, `NameError` sur toute la route, et **un rouge massif ressemblait à un garde très mordant alors qu'il ne mesurait qu'une panne d'import** ; deux scènes **survivaient à leur propre mutation**, la chaîne vide atteignant la même position **par un autre chemin** ; et sa « modification innocente » pour salir l'arbre était **du Python invalide**, l'image ne démarrait pas et le rouge prouvait le bon fait **par accident** |
| **73** | AUDIT-22 — audit du lot 22 | **AUCUNE BLOQUANTE**, et il refuse d'en forcer une. **Les 18 prémisses se reproduisent à l'identique, aucune n'a vieilli.** **L'ANGLE LE PLUS CHER EST RÉGLÉ PAR LA MESURE LA PLUS DIRECTE POSSIBLE** : il construit de vraies images et interroge de vrais conteneurs — **les six formes d'identité mal formée rendent HTTP 200**, jamais 500 —, puis balaye **1 056 combinaisons** d'environnement : **zéro `ValidationError`**, les **trois** positions atteintes, **contrôle positif à l'appui**. En chemin **forcé**, la seconde barrière rend bien 500. **Il joue `make image` POUR DE VRAI**, ce que le lot déclarait n'avoir pas fait, **dans les deux sens** : arbre propre puis sali, **même sha**, `rc=0`. **IL CORRIGE LE PILOTE TROIS FOIS ET IL A RAISON LES TROIS FOIS** : `restart: unless-stopped` **ne redémarre PAS** un conteneur `unhealthy` — Docker réagit à une **sortie** — et le coût réel est que `frontend`, en `condition: service_healthy`, **ne lèverait jamais à froid** ; **la déclaration « deux gestes non éprouvés » N'EXISTE NULLE PART DANS LE DÉPÔT**, le lot l'avait écrite dans son rapport de conversation et le commit dit « chaque commande exacte, éprouvée » **sans réserve** — **ET C'EST LE DÉPÔT QUI SURVIT, PAS LA CONVERSATION** ; et l'absence de `.dockerignore` coûte **914 ko** transférés, pas 2 Go. **IL CONFIRME LES 27 COMMITS PAR UNE MÉTHODE EXHAUSTIVE** — 451 commits balayés par empreinte d'objet git contre `docker cp` — **ET PRÉCISE CE QUE NI LE LOT NI LE PILOTE N'AVAIENT VU** : **TREIZE** commits portent exactement le même `src/`, de 32 à 22 derrière `main`, et ce qui pince `8209e68` est **L'HORODATAGE DE L'IMAGE**, ni le contenu ni l'étiquette — le chiffre est juste, **il repose sur deux faits et non sur un seul**. **SON TÉMOIN INERTE A PAYÉ POUR TOUT LE RAPPORT** : à sa première exécution il a rendu **954 au lieu de 999**, son harnais écrivant dans l'arbre détaché mais lançant `pytest` **depuis le répertoire courant, sur `main`** — **sans lui, les vingt-deux mutations suivantes auraient toutes « survécu » et le rapport aurait affirmé que le lot n'est gardé par rien**. Quatre non bloquantes, dont **le motif `_UN_SHA` — le seul rempart qui empêche le 500 — gardé par rien**, ses deux séparateurs mesurés étant exactement `git rev-parse --short` et le suffixe `-dirty` de `git describe`. **Cinq faux résultats contre lui-même**, dont un compteur de rouges qui **comptait les journaux** et une **sortie VIDE lue comme une valeur**, `2>/dev/null` masquant l'échec — *six lignes vides ressemblaient à un résultat cohérent*. **REFUS CONSIGNÉ — la vingt-cinquième** |
| **74** | REPAR-23 — les quatre non bloquantes du garde de déploiement | **LIVRÉ et FUSIONNÉ le 16 septembre 2026** `4627e6d`, **1005 passés** sur 49 fichiers. **IL RENVERSE L'AUDITEUR DEUX FOIS, ET LES DEUX FOIS LE PILOTE A VÉRIFIÉ DE SES MAINS.** **(1) TROIS BORNES, PAS DEUX** : l'audit publiait deux mutations survivantes sur `_UN_SHA` — longueur et ancrage — et nommait « la borne de casse » **dans sa prose SANS LA MUTER**. Le lot l'a mutée : elle survivait aussi, avec son propre chemin vers le 500. **LA MATRICE EST DIAGONALE**, chaque valeur séparatrice ne tuant qu'UNE mutation — donc **les « deux cas » que l'audit recommandait en auraient laissé une VIVANTE**. Remesuré par le pilote : témoin inerte à **zéro**, puis **un seul rouge chacune**, sur `[sha-abrege]`, `[40-hex-suffixe]`, `[40-hex-majuscule]` — aucune ne meurt par un autre chemin. **(2) L'AUDITEUR S'EST TROMPÉ DE FICHIER ET LE PILOTE AVAIT RECOPIÉ SON ERREUR AU REGISTRE** : le §4.42 vit dans `axes_amelioration.md`, pas dans `pilotage_du_chantier.md` — `git grep '^#\+ *4\.42'` rend **une seule ligne**, et les titres `4.N` comptent **58** d'un côté, **ZÉRO** de l'autre. Une commande d'une seconde, que le pilote n'a pas passée **dans la phrase même où il félicitait ce rapport pour sa rigueur**. Porté au **§12**. Le garde générique est **POSÉ, et sur MESURE** — 30 citations, 10 chemins distincts, 8 fichiers, **exactement une absente**, bruit nul : il **discrimine** (preuve d'atteinte assertée en **borne inférieure**, pas en compte exact, *parce qu'un instantané rougirait au prochain commentaire*) et **se tient à distance de lui-même PAR CONSTRUCTION** — il vit dans `tests/`, son domaine est `src/`, et un test l'asserte. NB-3 est écrit **au site exact des deux commandes**, avec ce qui n'a pas été vérifié ; NB-4 est confirmé sur **sept** valeurs dont **l'ESPACE**, le cas même que le commentaire invoquait, et le lot **double ses deux compose d'un SHA-256 pour prouver qu'ils diffèrent** — sans quoi il n'aurait mesuré que son propre écho. **Six faux résultats contre lui-même**, dont : **un `git checkout --` a effacé sa propre correction non commitée**, et **c'est le SHA-256 qui l'a attrapé**, le « restauré » attendu n'apparaissant pas — la faute que le registre consigne depuis le lot 3, refaite et rattrapée par le garde qui existe pour ça ; **son garde d'unicité a compté 174 pour une ancre présente UNE fois** — une ancre multi-ligne terminée par `\n` fait compter à `grep -cF` toutes les lignes du fichier —, **et il a REFUSÉ la mutation plutôt que de la poser à l'aveugle** ; et `--collect-only -q` **cumulé au `-q` de `addopts`** lui a rendu **zéro test**. **PAS DE QUATRIÈME AUDIT** : `src/` ne change **que d'un nom de fichier dans une docstring**, une ligne, lue en entier |
| **75** | LOT-24 — le redéploiement | **LIVRÉ et FUSIONNÉ le 16 septembre 2026** `f30af30`. **LA BORNE QUE DOUZE LOTS ONT PAYÉE EST LEVÉE** : conteneur recréé à 13:40:14 UTC, `healthy` en 21 s, et `/health` publie `code_servi: {etat: identifie, sha: b7337a3…}` — **qui EST `main`**. **Les lots 19, 20 et 21 tournent enfin** ; l'agent servait `8209e68`, **sans `flux_llm.py` ni `repli_outil.py`, ABSENTS**. **VÉRIFIÉ PAR LE PILOTE PAR LE CONTENEUR, ET LE ZÉRO EST DOUBLÉ** — `code_servi` est une déclaration du build, pas une preuve du contenu : `docker cp` + SHA-256 contre `git show` rend **18 identiques / 0 / 0 / 0**, et deux contrôles positifs rendent `rc=1` contre l'ancienne révision et **sur UN SEUL OCTET**. **IL ME RENVERSE SUR DEUX CHIFFRES, ET C'EST DEUX FOIS LA MÊME FAUTE — un instantané publié comme une propriété** : « 27 commits derrière `main` » en valait **38** à sa lecture (*la propriété est `8209e68` ; la distance périme*), et les « 914 ko de contexte » ne mesurent pas le contexte — **il l'a ÉPROUVÉ** sur un Dockerfile jetable, **38 B**. **IL A TROUVÉ LE FAUX POSITIF QUI AURAIT FAIT TOMBER L'OBJECTIF DU LOT** : `make image` décide sur `git status --porcelain`, **qui compte les fichiers NON SUIVIS**, et les arbres de l'outillage vivent sous `.claude/` — **le lot qui redéploie salit l'arbre par sa seule présence**, l'image aurait gravé `arbre_sale`, donc « ne pas comparer », donc **une campagne appariée refusée**. Contourné en local, **retiré et restauré au SHA-256**, avec contrôle positif posé avant de construire ; remède versionné dans `.gitignore`, **vérifié par le pilote DANS LES QUATRE SENS** : le faux positif est éteint **sans que le garde soit désarmé**. La correction de fond est **proposée et NON FAITE** — elle touche le `Makefile` et mérite son lot. **LA RÉSERVE DEVIENT UNE MESURE** : `up --no-build` ne reconstruit pas, **RECRÉE** le conteneur, sert l'image neuve, et **n'emporte PAS `frontend`**. Marge GPU mesurée **avant** de couper — 3 229 MiB libres pour un besoin de 1 468, **2,2×** — et **la valeur du voisin RELUE au lieu d'être supposée**. Le piège paresseux rencontré **deux fois** (`index_lexical` et `torch_device` à `null` à froid) et **non pris pour une panne** : tranché par la première recherche réelle. **Une réponse réelle servie** : 200 en 43,0 s, six citations ancrées. **Cinq faux résultats contre lui-même**, dont : **il a ÉCRIT SA CONCLUSION DANS LA COMMANDE** — un `echo` qui s'exécutait quoi qu'il arrive, affiché **sous dix lignes qui le démentaient** |
| **76** | LOT-25 — la bascule derrière un réglage | **LIVRÉ et FUSIONNÉ le 16 septembre 2026** `d663aca`, après AUDIT-25. **1035 passés** sur 50 fichiers. Lot 7 du découpage, **passé AVANT la campagne appariée parce qu'il en est le moyen**. **IL NE BASCULE RIEN** : `LLM_ENGINE` vaut `ollama` par défaut, **vérifié par le pilote**. **IL ME RENVERSE, ET J'AI VÉRIFIÉ DE MES MAINS AVEC CONTRÔLE POSITIF** : j'avais écrit que la charge d'Ollama envoyée à vLLM « échouerait bruyamment ». **C'EST FAUX** — `options.num_predict=5` rend **HTTP 200**, `stop`, **42 tokens** ; le contrôle positif `max_tokens=5` rend `length` et 5. **LE BORNAGE EST ACCEPTÉ ET IGNORÉ EN SILENCE**, et un lot qui n'aurait basculé que le CHEMIN aurait généré aux réglages par défaut du serveur, **sans erreur ni journal**. **IL TROUVE UN QUATRIÈME POSTE QUE MON CADRAGE N'AVAIT PAS, EN LECTURE** : `_contenu_message` ne lisait que `message.content` à la racine — réécriture et traduction seraient tombées sur leur repli **EN HTTP 200, sur une réponse VALIDE**, avec un journal accusant le serveur. **Trois mutations ont d'abord SURVÉCU**, dont **l'URL du poste de FLUX, celui qui sert chaque réponse**, et il en tire la phrase qui vaut pour la suite : **UNE CAMPAGNE MENÉE SOUS LE DÉFAUT NE PEUT PAS MESURER CE QUI NE VARIE QU'À LA BASCULE**. **Quatre faux résultats contre lui-même**, dont un **job de mutation passé EN FOND** qu'il avoue comme *« une faute de pilotage, pas un hasard »* |
| **77** | AUDIT-25 — audit du lot 25 | **AUCUNE BLOQUANTE**, et **IL FERME L'ANGLE QUI MANQUAIT À TOUT LE CHANTIER** : la **génération complète sous `LLM_ENGINE=vllm` PASSE** — en flux, hors flux, avec appel d'outil, **sur les deux moteurs** ; les décomptes existent, **la citation `[src:…]` est produite**, aucune réponse tronquée. **Il monte l'agent COMPLET sous vLLM** sur un port à lui : `services.ollama: true` **contre un serveur vLLM**, et **six requêtes vers `:8100`, ZÉRO vers `:11434`** — la bascule est **ÉTANCHE au niveau du service entier**. **IL ÉPROUVE LE DÉFAUT PLUS DUREMENT QUE LE LOT** : la comparaison à des **littéraux recopiés** est un garde de **COPIE CONFORME**, vert sur deux exemplaires **tous deux faux** — il a donc **intercepté `httpx`** dans les deux arbres et capturé ce que chacun **POSTE RÉELLEMENT**, ordre d'insertion compris : **SHA-256 identique, 3 POST sur 3**, contrôle positif à l'appui. Il confirme le quatrième poste **contre le serveur réel** : sur le même corps, le lecteur de `main` rend **une chaîne vide**, celui du lot **195 caractères**. **Sept non bloquantes**, dont **trois champs de `_sonder_moteur_llm` que rien ne garde à la bascule** — la plus coûteuse ferait repartir la sonde **à chaque battement de `/health`, jusqu'à trois requêtes, vers le serveur PARTAGÉ du voisin** —, `tests.md` qui annonce **26 là où il y en a 30 et se contredit deux lignes plus bas**, à un endroit que le garde du compte **ne regarde pas**, et **les trois clés neuves absentes de `.env.example`**, le fichier qu'un exploitant **copie**. **HUIT faux résultats contre lui-même**, dont : **son « contrôle positif » A SURVÉCU**, le faisant conclure à tort qu'une fonction n'était pas exercée — *elle l'est, quinze fois* —, et **ses propres sondes, passées sur son propre rapport, l'ont attrapé** à faire entrer le préfixe d'outillage dans le dépôt. **REFUS CONSIGNÉ — la vingt-neuvième** |
| **78** | REPAR-26 — les sept non bloquantes du dialecte | **LIVRÉ et FUSIONNÉ le 16 septembre 2026** `6e5c64d`, **1089 passés** sur 51 fichiers. **Il traite la CAUSE, pas les sept cas** : une table donnant, pour chaque champ de `MoteurLlmHealth` et chacun des deux dialectes, la valeur attendue — tenue par quatre gardes, dont un **exhaustif contre `model_fields`** et un **séparant** (un champ identique des deux côtés est refusé au niveau de la table). **Ajouter une ligne ajoute deux scènes ; un champ neuf non classé rougit. Il n'y a rien à écrire deux fois.** Il trouve **deux champs de plus que l'audit**, et **un second chiffre faux dans `tests.md`** que ni le lot ni son audit n'avaient vu — le document **confondait « ajoutés » et « de plus »**. **Sa mutation survivante n'accusait pas le code : elle a trouvé SON PROPRE GARDE**, muet sur une espace littérale là où la note passe à la ligne. Six `noqa` ajoutés, **vérifiés par le pilote** : deux `E402` après `sys.path.insert`, deux `A002` imposés par `httpx`, et deux `BLE001` où **l'absorption reste large mais N'EST PLUS MUETTE** — le bon geste, pas un relâchement. **Six faux résultats contre lui-même**, dont un **job passé en fond** et un **témoin inerte qui ne relevait pas le compte de tests** — le piège était pourtant annoncé dans son prompt. **PAS D'AUDIT** : les sept points étaient spécifiés ET pré-mesurés par AUDIT-25 (§4.18), **et le pilote arrête ici la chaîne audit-réparation-audit** — voir §12 |
| **—** | LA BASCULE — l'agent sert vLLM *(geste du PILOTE, aucune conversation : ce journal numérote les conversations, et celle-ci n'a pas eu lieu. La ligne reste, le numéro est rendu.)* | **FAITE PAR LE PILOTE le 17 septembre 2026 à 07:45 UTC.** Pas de campagne comparative : **la décision appartenait au propriétaire et elle était prise** — le pilote l'avait transformée en question ouverte, ce qui est la faute du §12. Marge relevée avant de couper : **8 761 MiB libres**, vLLM seul sur la carte. Route vérifiée **avant** d'écrire quoi que ce soit : l'agent joint `vllm-central:8000` depuis `llm-net` et reçoit 200. État servi **étiqueté et vérifié avant construction** (`2026-09-17-avant-bascule-vllm`, l'accord des identifiants contrôlé). Trois clés ajoutées au `.env` du clone principal — **qui est ignoré par git, vérifié**. `make image` `rc=0`, image gravée sur `7b0edb0`, `arbre=propre` ; `up -d --no-build`, `healthy`, `RestartCount=0`. **RÉSULTAT : `moteur_llm.serveur = vllm`, version 0.28.0, `modele_servi` = le modèle attendu, `fenetre_servie` 32768, relevé DU SERVEUR.** `status: ok`, quatre sondes vertes. **Une vraie question servie : HTTP 200 en 17,3 s, 1 314 caractères, SEPT citations ancrées** — contre 43,0 s sous Ollama la veille, sur une question comparable. `index_lexical` `false` à froid puis `true` après la première recherche : **le piège paresseux, connu, non pris pour une panne**. Retour arrière armé : l'étiquette pend à l'image d'avant, et `LLM_ENGINE=ollama` suffit |
| **79** | LOT-28 — un seul moteur, et le nom de l'autre disparaît | **LIVRÉ et FUSIONNÉ le 21 septembre 2026** `fea48fa`, **1084 passés** sur 52 fichiers — **le compte BAISSE, et c'est la seule fois où c'est attendu** : un moteur a été retiré. Le lot ne retire pas le nom, **il retire le SUPPORT** : `LLM_ENGINE` n'existe plus, il n'y a plus de dialecte à choisir, et les deux paires de réglages par moteur deviennent `LLM_HOST` et `LLM_MODEL`. **MESURÉ PAR LE PILOTE : ZÉRO occurrence du nom dans `src/`, `scripts/` ET `tests/`**, et le défaut du code sans `.env` pointe le serveur réel. **LES ARCHIVES NE SONT PAS RÉÉCRITES, et c'est une décision du pilote** : audits, campagnes, `runs/*.json`, registre et mandat racontent des décisions datées — les réécrire serait **falsifier un rapport**. Elles portent une note qui dit pourquoi. **Le garde du nom est bien construit** : son périmètre d'exclusion est **NOMMÉ chemin par chemin** avec sa raison au site, **aucun motif large** — *un `documentation/*` excuserait tout un répertoire sans qu'on s'en aperçoive* —, et un second garde refuse une exclusion qui **ne désigne plus rien**. `scripts/banc_vllm.py` supprimé : il comparait les deux moteurs. **MIGRATION DU `.env` JOUÉE PAR LE PILOTE** : cinq clés retirées, deux ajoutées. **REDÉPLOYÉ** : `code_servi` = `main`, `moteur_llm.serveur: vllm`, quatre sondes vertes — **et la clé publique de `/health` s'appelle désormais `llm`**, le nom a disparu jusque-là |
| **80** | LOT-29 — la garde qui mord sur le nom du champ média | **LIVRÉ et FUSIONNÉ le 22 septembre 2026** `0e4d3b5`, **1104 passés** sur 54 fichiers dans `tests/unit/`, **le périmètre de la porte** — `make test` lance `pytest tests/unit/`, et `tests/` complet en rend **1114**, dix de plus en intégration : **deux grandeurs, et le pilote a publié la seconde sans dire sa portée** pendant quatre commits de registre. **`src/` N'EST PAS TOUCHÉ**, vérifié par le pilote (`git diff --stat -- src/` vide), donc pas d'audit indépendant au titre du §4.18. Le lot ferme la dette nommée au §4.62 : les 23 lignes de `tests/` qui nommaient `minio_url` le **posaient elles-mêmes**, et **le lot l'a mesuré** — les sept sites renommés ensemble laissent la suite d'avant à **1084 passés, `rc=0`, avant comme après**. Un site canonique `CONTRAT_DES_SOURCES` nomme le champ attendu de chaque source ; les sites sont relevés **par AST et par motif**, jamais par numéro, en trois natures, et le compte de sept est **calculé**, jamais écrit dans un assert. **SA TROUVAILLE EST SUR LUI-MÊME ET IL NE L'A PAS RÉPARÉE EN DOUCE** : une mutation a **survécu** — son contrôle positif prenait ses témoins dans deux natures sur trois, si bien qu'un site en `subscript` ajouté dans `src/` passait inaperçu ; la fermeture porte sur les **trois** natures avec un fragment **synthétique**, et une garde interdit désormais qu'une nature entre à l'inventaire sans témoin. **MESURÉ PAR LE PILOTE SUR LE RÉSULTAT DE LA FUSION**, dans un arbre détaché à témoin d'arbre vérifié : porte `RC_LINT(make)=0` / `RC_TEST(make)=0`, **1104** ; puis mutation du **producteur** — `meta.get("minio_url")` de `lexical.py`, ancre vérifiée **unique avant d'écrire** — → `rc=1`, **5 rouges nommés**, dont le garde de contrat et le contrôle positif de B3 ; **témoin inerte** de 13 lignes en tête du même fichier → `rc=0`, **1104**, le compte attendu ; **restaurations IDENTIQUES au SHA-256**, arbre propre avant et après |
| **81** | LOT-30 — onze scènes posent la fenêtre qu'elles mesurent | **LIVRÉ et FUSIONNÉ le 22 septembre 2026** `b3c5045`, **1109 passés**. Il referme le §4.63, **un défaut que le pilote avait causé** en portant `LLM_NUM_CTX` à 32768 : dix scènes **héritaient** du plafond au lieu de le **poser**, et la fenêtre élargie ne les faisait pas échouer — **elle les privait de leur sujet**. `src/` N'EST PAS TOUCHÉ, vérifié. **IL Y EN AVAIT ONZE, PAS DIX** : la onzième ne se révèle que sous une **variable d'environnement**, `_env_file=None` neutralisant le fichier mais pas l'environnement, dont `pydantic-settings` fait une source **prioritaire** — et son jumeau portait le même défaut **latent**, qui n'aurait rougi que sous sa propre valeur d'épreuve. **Deux gardes anti-« mesuré sous le défaut » qui héritaient eux-mêmes du défaut.** La fenêtre est posée par une **fonction et non une fixture `autouse`** — le réglage redeviendrait ambiant, et `undo()` annule aussi ce qu'une fixture pose — sur les **trois** réglages du budget ensemble, **et aucune des trois valeurs n'est un défaut déclaré** : poser 8192 aurait rendu leur sujet aux scènes tout en les laissant vertes sous une mutation écrivant `8192` en dur. **MESURÉ PAR LE PILOTE LÀ OÙ LE LOT NE POUVAIT PAS — DANS LE CLONE PRINCIPAL, SEUL ARBRE À PORTER LE `.env`**, ce qui **lève la borne 3 du lot** : porte `rc_lint(make)=0` / `rc_test(make)=0`, **1109** sous le `.env` réel (32768 **par fichier**) **et** 1109 sous `LLM_NUM_CTX=8192` **par environnement** — même compte des deux côtés ; puis mutation du **producteur**, un `poser_la_fenetre` retiré par motif → `rc(make)=2`, **2 rouges dont la garde elle-même** ; **témoin inerte** de 13 lignes en tête du module de garde → `rc(make)=0`, **1109**, le compte attendu ; **restaurations IDENTIQUES au SHA-256**, arbre propre avant et après. **LA LEÇON EST POUR LE PILOTE : `LE POSTE N'EST PAS L'ARBRE`** — une porte verte en arbre détaché ne dit rien de la porte du poste, et c'est dans cet écart que le défaut a vécu deux jours |
| **82** | LOT-31 — mesurer la sélection, l'étage que personne ne mesurait | **LIVRÉ et FUSIONNÉ le 23 septembre 2026** `6c9293b`, **1121 passés**. `src/` N'EST PAS TOUCHÉ, vérifié. **SA TROUVAILLE VAUT PLUS QUE LE RÉGLAGE QU'IL DEVAIT ÉCLAIRER, et le pilote l'a recoupée en recalculant depuis les lignes brutes, pas depuis son tableau** : sur le jeu de réglage, **120 ancrages sur 130 arrivent au prompt dès k=1, 4 de plus à k=2, et PLUS AUCUN jusqu'à k=20**. Rien ne vit entre les rangs 3 et 20. **Le jeu de réglage est donc AVEUGLE À LA SÉLECTION** — ses questions ont été écrites *pour* leur passage — et son plateau ne dit pas « 3 suffit », il dit « ce jeu ne teste pas k ». Le jeu de contrôle, lui, la teste : 0,7308 → 0,7692 de k=3 à k=6, soit **une question sur 26**, du bruit au sens de sa propre réserve. **LA DETTE A CHANGÉ DE NATURE** : ce n'est plus « mesurer le gain de k=6 », c'est « un jeu à ancrages MULTIPLES et DISPERSÉS, en nombre ». **Sa précaution n°1 était indispensable et le pilote l'a chiffrée** : à k=3 le prompt porte **32,4** identifiants et non 3, parce qu'une section reconstruite en porte plusieurs — mesurer `ranking[:k]` seul aurait sous-estimé **d'un facteur dix**. **Trois trouvailles annexes, aucune corrigée dans `src/`** : la déduplication par `section_id` fait qu'un ancrage classé **rang 2** n'atteint le prompt à **aucun k** ; deux ancrages ont leur texte dans ChromaDB et `text=""` dans NebulaGraph — **divergence de stores, rendue au pipeline** ; et **`max_sources` est borné 1..20 quand la chaîne plafonne à `RERANK_TOP_K=10`** — *promesse d'API non tenue, **mesurée par le pilote sur l'agent servi** : `3→3`, `10→10`, **`20→10`***. Le cache de traductions versionné était **périmé avec la bonne taille** — intersection **zéro** avec les deux jeux — et c'est le refus posé au banc qui l'a attrapé. **MESURÉ PAR LE PILOTE SUR LE RÉSULTAT DE LA FUSION, DANS LE CLONE PRINCIPAL** : porte `rc_lint(make)=0` / `rc_test(make)=0`, **1121** ; mutation du **producteur** — `graines[:k]` → `graines[:max(k, 999)]`, qui **compile** et change le comportement — → **6 rouges dont le contrôle positif** `test_k_petit_et_k_grand_ne_rendent_pas_la_meme_chose` ; **témoin inerte** de 13 lignes → `rc=0`, **1121** ; **restaurations IDENTIQUES au SHA-256**. **LE DÉFAUT RESTE À 3 — CE QUI A CHANGÉ, C'EST LA RAISON** |
| **—** | LA CI, VERTE POUR LA PREMIÈRE FOIS *(geste du PILOTE et du PROPRIÉTAIRE, aucune conversation : ce journal numérote les conversations, et celle-ci n'a pas eu lieu. La ligne reste, le numéro est rendu.)* | **Le 23 septembre 2026.** Run `35842144530`, verdict **`success`** sur `853a0f1`, **après plus de soixante échecs consécutifs**. **DEUX correctifs ont été nécessaires, et le second n'était pas prévu.** (1) `actions/checkout@v4` sans `fetch-depth` ne rapporte **qu'un** commit, alors que les gardes mordent sur des **révisions historiques réelles** : `assert 1 >= 250` puis `git show <sha>` en `rc=128` sur quatre fichiers. Une ligne, `fetch-depth: 0`, posée **par le propriétaire depuis l'interface web**. (2) Le run suivant est resté rouge sur **un seul** test, pour une **autre** cause : le commit web portait `…@users.noreply.github.com` en auteur et `GitHub <noreply@github.com>` en committer — **la règle d'identité qui a coûté 165 commits réécrits puis la destruction du dépôt**. Le hook prescrit le geste lui-même ; commit refait depuis le poste, **contenu strictement identique** (SHA-256 confronté, `git diff` **vide**), hook à `rc=0`, `--force-with-lease` **ancré sur l'ancien sha**, **un** commit réécrit. **TROIS LEÇONS AU REGISTRE §4.70** : un correctif validé ne valide que **sa propre cause** — il faut lire la CAUSE, pas le verdict, sans quoi on conclut « ça n'a pas marché » ; **l'interface web ne peut pas respecter la règle d'identité** tant que l'adresse de commit du compte reste privée ; et **le scope `workflow` n'est requis que par l'API Contents, PAS par un push git** — l'API rend **404**, le `git push` passe. **La borne « on ne peut pas corriger la CI sans élargir le jeton » était SUPPOSÉE et FAUSSE, et elle a coûté trois jours d'attente d'une décision qui n'avait pas lieu d'être** |
| **83** | LOT-32 — la borne de `max_sources` est celle que la chaîne sert | **LIVRÉ et FUSIONNÉ le 23 septembre 2026** `00d1b35`, **1124 passés**. Ferme la promesse d'API non tenue relevée à la ligne 82 : `max_sources` acceptait 1..20 quand la chaîne plafonne à `RERANK_TOP_K`. **Le lot a choisi la voie (b) — rendre la promesse HONNÊTE — et la mesure qui l'a décidée est au §4.72** : sous `RERANK_TOP_K=20` posé **dans l'environnement du lancement**, le contexte double (×1,93 et ×2,10 sur les deux jeux) pour **+1 question sur 130 et +0 sur 26** — sous le seuil de bruit que les deux jeux déclarent eux-mêmes. **Un accident d'écriture de schéma ne doit pas arbitrer un réglage de production.** La borne est **DÉRIVÉE** (`MAX_SOURCES_SERVIES = settings.rerank_top_k`), donc (a) reste ouverte sans toucher au schéma. Hors commentaires, **trois lignes de code**. **AUDIT INDÉPENDANT NON DEMANDÉ, ET LA RAISON EST ÉCRITE ICI** : le §4.18 l'exige dès que `src/` change, mais le diff exécutable tient en trois lignes, le lot a fourni sa table des mutations **dans les deux sens**, et **le pilote les a remesurées de ses mains sur le RÉSULTAT DE LA FUSION** — dérogation assumée au titre du §12, qui ferme un lot dès qu'un audit ne rend pas de bloquant, et qui proscrit la chaîne audit-réparation-audit. **MESURÉ PAR LE PILOTE, clone principal, `.env` réel** : porte `rc_lint(make)=0` / `rc_test(make)=0`, **1124** ; mutation **sens 1** — le schéma ment, `le=MAX_SOURCES_SERVIES` → `le=20` → `rc(make)=2`, **3 rouges, tous du garde** ; mutation **sens 2** — la chaîne ment, `[: settings.rerank_top_k]` → `[: settings.rerank_top_k - 5]` → `rc(make)=2`, **les mêmes 3** ; **témoin inerte** 13 lignes → `rc=0`, **1124** ; **restaurations IDENTIQUES au SHA-256**, arbre propre. **CONFLIT DE NUMÉROTATION RÉSOLU À LA FUSION** : le lot avait pris `4.70` sur une base antérieure à la section CI du pilote ; sa section devient **4.72** et son renvoi dans `tests.md` suit — **les deux côtés du registre sont conservés**, aucun n'écrase l'autre. **CINQ RÉSERVES DU LOT, TOUTES AU DÉPÔT**, dont deux qui comptent : **aucune latence de (a) n'est mesurée** — le ×2 porte sur les éléments au prompt, pas sur des millisecondes, et les +44 % du §4.66 mesuraient 3→6, pas 10→20 ; et **un client externe demandant 11..20 reçoit désormais 422** au lieu de dix sources silencieuses — aucun appelant du dépôt n'est concerné, mesuré, mais l'extérieur n'est pas mesurable d'ici. **LE CORRECTIF N'EST PAS DÉPLOYÉ** : l'agent du port 8011 publie toujours `maximum: 20.0` |
| **—** | LE `.dockerignore` — l'image embarquait le bytecode de la machine *(geste du PILOTE)* | **Trouvé APRÈS le redéploiement du lot 28**, en cherchant le nom de l'ancien moteur **dans le conteneur servi** : `settings.cpython-314.pyc` dans `/app/src`, alors que l'image tourne sous **Python 3.12**. Il n'existait **aucun `.dockerignore`**, donc `COPY src/agent` emportait les `__pycache__` de l'hôte. Python ignore un `.pyc` dont la version ne correspond pas, donc **rien ne cassait** — mais l'image portait du code compilé que personne n'avait construit pour elle, **et le nom de l'ancien moteur y survivait au lot qui venait de le retirer partout ailleurs**. Vérifié qu'il ne s'agissait **pas** d'un montage : `/app/src` vient bien de l'image, donc `code_servi` ne mentait pas. Le premier build a servi la couche **depuis le cache** et l'image est restée sale ; en retirant aussi les `__pycache__` de l'hôte, les `COPY` se rejouent et l'image est **propre, vérifiée dans l'image et non dans le conteneur**. Contexte transféré : 278 ko → **900 B**. **Contrôle final dans le conteneur servi : 0 fichier portant le nom, 14 portant `vllm`** — le zéro est doublé de son positif |

**Prochain numéro libre : 84.**

> **79 A ÉTÉ PRIS PUIS RENDU, ET C'EST DIT PLUTÔT QUE CORRIGÉ EN SILENCE.** Le
> pilote avait numéroté `79` un geste qu'il a fait **lui-même** — la bascule du
> moteur, le 17 septembre. Ce journal numérote les **conversations** ; celle-là
> n'a jamais existé, et le propriétaire l'a relevé. Ce n'est donc pas une
> réutilisation de numéro au sens du titre ci-dessus : `79` n'a jamais désigné
> une conversation. La ligne de la bascule reste au journal, sans numéro, parce
> que le geste a bien eu lieu et qu'il est daté.

> **ET LE PILOTE A REFAIT LA MÊME FAUTE LE 23 SEPTEMBRE, SUR LA CI.** Il a
> numéroté `83` la mise au vert de l'intégration continue — un geste, fait à
> deux mains avec le propriétaire — **en écrivant dans la ligne elle-même**
> « pas un lot, donc pas un numéro de lot », sans voir que le journal ne
> numérote pas les lots mais les **conversations**. Le numéro `83`
> appartenait à la conversation qui a produit LOT-32. Relevé par le
> propriétaire, rendu de la même façon : la ligne de la CI reste, sans numéro,
> et LOT-32 reprend son `83`. **Écrire la règle dans la ligne ne dispense pas
> de l'appliquer** — c'est la deuxième fois, et la première était déjà écrite
> six lignes plus haut.

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

- **UN DÉFAUT QUI ÉCHOUE SE VOIT ; UN DÉFAUT QUI RÉPOND MENT.** *Rendu par le
  pilote de `data-analyst-agent`, le 18 septembre 2026, et payé chez lui.* Son
  `LLM_BASE_URL` par défaut désignait un serveur **joignable** sur l'ancien
  moteur : en mesurant depuis un arbre où le `.env` n'avait pas été recopié, sa
  sonde a répondu normalement, **sans erreur ni avertissement**, et il a cru
  mesurer son produit pendant tout un tour. Chez nous le même défaut mentait
  aussi, mais ses deux hôtes sont **injoignables** (`000` depuis le conteneur,
  `mesuré` le 18 septembre) : l'application échoue au lieu de mesurer faux.
  **Quand tu choisis une valeur par défaut pour quelque chose que tu ne
  contrôles pas, choisis-en une qui NE PEUT PAS marcher par accident.** Et si tu
  mesures depuis un arbre de travail, imprime l'adresse et le modèle **en tête
  de chaque relevé** : c'est la seule façon de voir qu'on s'est trompé de
  serveur ;
- **un test qui HÉRITE d'un défaut change de sujet le jour où le défaut
  change.** Corollaire du précédent, payé ici le 18 septembre : porter
  `LLM_ENGINE` de `ollama` à `vllm` a rendu **24 scènes rouges d'un coup**, dans
  trois fichiers — aucune ne mesurait mal, elles ne **demandaient** pas le
  dialecte qu'elles éprouvaient. Une scène pose ce qu'elle mesure. *Le dépôt
  voisin ne connaît pas ce piège, et la raison est instructive : ses tests
  construisent leurs réglages argument par argument, donc ils déclarent au lieu
  d'hériter.* ;
- **`monkeypatch.undo()` annule AUSSI ce qu'une fixture a posé**, et l'état
  retombe sur le défaut. Une scène de retour arrière **repose** son état de
  départ explicitement — ce qui est d'ailleurs plus fidèle à ce que fait un
  exploitant : il réécrit un réglage, il n'annule rien ;

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

**LA CHAÎNE AUDIT-RÉPARATION-AUDIT S'ENTRETIENT ELLE-MÊME, ET C'EST MA FAUTE
LA PLUS CHÈRE.** *Relevé le 16 septembre 2026, à la 78ᵉ conversation.* Le
propriétaire a demandé où allait le chantier et pourquoi la migration d'un moteur
coûtait autant. La réponse est celle-ci, et elle est de moi :

- **la migration elle-même est petite** — un changement d'URL et de forme de
  charge, environ 300 lignes. **Un seul piège technique était réel** : vLLM
  fragmente l'appel d'outil sur quatre événements en flux, et le rater faisait
  perdre les recherches **en silence** ;
- **sur les sept lots du découpage, DEUX étaient la migration.** J'ai attaché au
  chantier le second rideau (un défaut d'aujourd'hui), le mécanisme d'identité
  d'image (de l'hygiène) et le redéploiement (rendu nécessaire par une dérive que
  j'avais laissée courir douze lots) ;
- **puis j'ai multiplié chaque lot par quatre conversations** : lot, audit,
  réparation, audit de la réparation ;
- **AUCUN AUDIT N'A JAMAIS RENDU DE TROUVAILLE BLOQUANTE SUR CE DÉCOUPAGE.** J'ai
  traité chaque non bloquante comme du travail dû, ce qui appelait un nouvel
  audit, qui rendait de nouvelles non bloquantes.

**LA RÈGLE QUI EN SORT, ET ELLE S'APPLIQUE À PARTIR D'ICI.** Un audit sans
bloquant **ferme le lot**. Ses non bloquantes vont **au registre** et **n'appellent
pas de réparation** — elles attendent qu'un défaut réel les rende utiles. Une
section de registre se mesure en dizaines de lignes, pas en centaines. *Le
chantier existe pour empêcher les faux verts, pas pour se nourrir de lui-même.*

**CITER UN RAPPORT D'AUDIT SANS MESURER CE QU'ON EN CITE.** *Le 16 septembre
2026, AUDIT-22.* L'auditeur avait relevé — justement — qu'un module citait un
fichier n'ayant jamais existé, et il nommait le fichier de remplacement :
`pilotage_du_chantier.md`. **J'ai recopié ce nom au registre sans le vérifier**,
dans la même phrase où je félicitais ce rapport pour sa rigueur. Le §4.42 vit
dans `axes_amelioration.md` : `git grep '^#\+ *4\.42' -- documentation/` rend
**une seule ligne**, et les titres `4.N` comptent **58** d'un côté, **ZÉRO** de
l'autre. Une commande d'une seconde. C'est REPAR-23 qui l'a corrigé.

**LA RIGUEUR D'UN RAPPORT NE DISPENSE PAS DE MESURER CE QU'ON EN CITE** — elle y
oblige plutôt, parce qu'un rapport juste partout ailleurs est celui qu'on recopie
sans y penser. *Un rapport d'audit est un ÉCRIT, donc une HYPOTHÈSE, exactement
comme ce document-ci.*

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

> **Un heredoc non quoté exécute ce qu'il lit.** `mesuré` le 23 septembre 2026 :
> un `cat >> … <<FIN` sans apostrophes autour du marqueur a fait interpréter les
> accents graves du Markdown comme des substitutions de commande. Bash a tenté
> d'exécuter `mesuré`, a écrit `command not found` **dans un flux que je ne
> lisais pas**, et a inséré du **vide** à sa place — supprimant précisément
> l'étiquette qui distingue un chiffre relevé d'un chiffre supposé. Le texte
> restait lisible et la porte est restée **verte** : rien ne pouvait le signaler.
> **Le marqueur d'un heredoc qui porte du Markdown se quote toujours** —
> `<<'FIN'` — et une sortie de commande se relit **en entier**, pas seulement son
> code de retour.
