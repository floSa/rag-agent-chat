# Quel code tourne, et comment revenir en arrière

Ce document répond à une seule question, et ce chantier a payé deux fois de ne
pas savoir y répondre :

> **Le conteneur `rag-agent-api` qui tourne en ce moment exécute-t-il le code que
> je crois ?**

**Ce qu'a coûté l'absence de réponse.** Pendant douze lots, l'agent en service a
exécuté du code antérieur et aucun garde livré ne tournait — personne ne s'en est
aperçu, parce que rien ne permettait de poser la question (§4.42 du registre).
Puis le lot 18 s'est vu donner une étiquette de retour arrière comme existante :
`2026-09-14-servi-avant-lot15`, malgré sa date et son nom, **désignait l'image du
11 septembre**, et l'image réellement servie ne portait que `latest`. Un
`docker build` aurait rendu l'état servi anonyme et irrécupérable.

**La leçon, et elle gouverne tout ce document : une étiquette ment sur ce qu'elle
désigne tant que personne n'a vérifié à quoi elle pend.** Une étiquette, une
image et un conteneur sont trois choses différentes. On tranche par le
**conteneur**, jamais par une étiquette.

---

## 1. Ce que l'image porte désormais, et par quels deux chemins

Depuis le 16 septembre 2026, `Dockerfile.agent` grave l'identité du code **deux
fois**, et ce n'est pas une redondance :

| Chemin | Lu par | Ce qu'il vaut |
|---|---|---|
| `ENV RAG_AGENT_CODE_*` | `src/api/identite_du_code.py`, publié par `GET /health` | S'obtient **sans accès au démon Docker** — depuis le pipeline, une campagne, un poste distant |
| `LABEL org.opencontainers.image.revision` et voisins | `docker image inspect` | **L'exécution ne peut pas le contredire** |

**Pourquoi les deux.** `env_file: .env` charge le `.env` au démarrage, et Docker
laisse l'exécution l'emporter sur l'`ENV` gravé dans l'image : une variable
`RAG_AGENT_CODE_SHA` posée dans le `.env` ferait publier à `/health` une identité
que le build n'a jamais gravée. Le `LABEL`, lui, est figé à la construction.
**Un désaccord entre les deux nomme exactement ce cas** — §5 ci-dessous donne le
geste qui les croise.

`/health` publie sous `code_servi` :

```json
{"etat": "identifie", "sha": "<40 hexadécimaux>", "construite_le": "<ISO-8601 UTC>", "avertissement": null}
```

**Trois positions, et elles répondent à une seule question — *puis-je me fier à ce
sha ?*** :

| `etat` | Ce que ça veut dire | Ce qu'on en fait |
|---|---|---|
| `identifie` | Sha gravé au build, arbre de construction propre. | On peut comparer une campagne à ce commit. |
| `arbre_sale` | Le sha est là, mais l'arbre portait des modifications non commitées : **le commit nommé ne contient pas ce qui tourne**. | **Ne pas comparer.** Reconstruire depuis un arbre propre. |
| `anonyme` | Rien de fiable. `sha` est `null`, et `avertissement` dit lequel des trois chemins y a mené. | On ne sait pas quel code tourne. C'est l'état d'avant ce lot, et il se dit maintenant. |

**Une image construite sans ces arguments se déclare anonyme et ne peut pas
passer pour identifiée.** Les `ARG` de `Dockerfile.agent` n'ont **aucune valeur
par défaut** : sans `--build-arg`, les trois variables arrivent vides dans
l'image. Le contrat `CodeServiHealth` refuse par ailleurs, à la construction
comme à la lecture d'un corps venu d'un autre agent, qu'un `etat: "anonyme"`
porte un sha ou qu'un `etat: "identifie"` en manque.
Gardes : `tests/unit/test_identite_du_code.py`.

---

## 2. Savoir ce qui tourne — trois commandes, dans cet ordre

**`mesuré` le 16 septembre 2026 à 09:16 UTC : les trois rendent ce qui suit sur
le service en place, et `rc=0`.**

```bash
docker inspect -f '{{.Image}}' rag-agent-api
```
→ l'identifiant de l'image que le conteneur exécute **réellement**. C'est le seul
fait ; tout le reste en dérive.

```bash
docker image inspect -f '{{range .RepoTags}}{{println .}}{{end}}' "$(docker inspect -f '{{.Image}}' rag-agent-api)"
```
→ **toutes** les étiquettes de cette image. Zéro ligne signifie que l'image n'est
désignée par aucun nom : un `docker build` qui reprend `latest` la rendrait
irrécupérable. C'est l'état dans lequel le lot 18 a trouvé le service.

```bash
curl -s http://localhost:8011/health | python3 -m json.tool
```
→ le port est **8011**, pas 8000 : `docker-compose.yml` publie `8011:8000`, et un
auditeur a failli écrire que l'API ne répondait pas parce que sa sonde visait le
port interne. Lire `code_servi`.

---

## 3. Construire une image identifiée — un seul geste

```bash
make image
```

Depuis le **clone principal** — `docker-compose.yml` monte `./prompts` et lit
`.env`, qui n'existent que là. Cette cible relève le sha **et** la propreté de
l'arbre, puis appelle `docker compose build agent-api`.

Elle **ne démarre rien** : construire et déployer sont deux gestes, et les
confondre est ce qui rend un retour arrière impossible.

Tout autre chemin — `docker compose build` nu, `docker build` à la main — reste
licite et produit une image **anonyme**, qui le déclare dans `/health`.

**CE QUE LE CHIFFRE « transferring context » MESURE — ET CE QU'IL NE MESURE
PAS.** Le build affiche une ligne `#N [internal] load build context /
transferring context: …`. **Ce n'est pas la taille du contexte de ce dépôt.**
`mesuré` le 16 septembre 2026 à 13:39 UTC par le lot 24 : `make image` annonce
**278,38 kB**, alors que le clone principal pèse **2,0 Go hors `.git`**
(`du -sb --exclude=.git --exclude=<répertoire de l'outillage>` → 1 999 480 836 o, dont `.venv`
1,84 Go, `.mypy_cache` 145 Mo) **et qu'il n'existe aucun `.dockerignore`**
(`transferring context: 2B` à l'étape `load .dockerignore` : la liste est vide).

Deux réductions se composent, et il faut les distinguer :

1. **BuildKit ne transfère que les chemins que les `COPY` réclament.**
   *Éprouvé* le 16 septembre 2026 à 13:45 UTC sur un nom d'image jetable, à
   risque nul pour l'état servi : même contexte — le clone principal —, un
   Dockerfile ne portant qu'un `COPY requirements.txt`, résultat
   **`transferring context: 38B`**. Deux gigaoctets de `.venv` dans le contexte
   ne coûtent rien tant qu'aucun `COPY` ne les réclame.
2. **Le transfert est incrémental** contre le cliché que BuildKit garde du build
   précédent. Les chemins que ce Dockerfile réclame — `requirements.txt`,
   `src/agent`, `src/api` — pèsent **874,92 kB** avec leurs `__pycache__` et
   **504,56 kB** sans (`du -sb`, 16 septembre 2026). Le **914 ko** relevé par
   l'audit du lot 22 concorde avec le premier chiffre ; les **278,38 kB** du
   lot 24 sont un delta contre ce même cliché.

**La conséquence pratique :** ne lis pas ce chiffre comme un budget de contexte,
et n'en déduis pas qu'un `.dockerignore` est inutile ici — il l'est *pour le
coût de transfert*, il ne l'est pas pour qui ajouterait un jour un `COPY . .`.

---

## 4. Redéployer, et pouvoir revenir — la marche exacte

> **L'étiquetage vient AVANT tout autre geste.** C'est ce qui a sauvé le retour
> arrière du lot 18, et l'ordre n'est pas négociable : une fois `latest` repris
> par une image neuve, l'ancienne n'a plus de nom.

> **CE QUI A ÉTÉ ÉPROUVÉ, ET CE QUI NE L'A PAS ÉTÉ. LA DISTINCTION EST ÉCRITE
> ICI PARCE QU'ELLE DOIT SURVIVRE À LA CONVERSATION QUI L'A ÉTABLIE.**
> Les gestes (a), (b), (c), (d) et (f) sont **éprouvés**. Et **(e) l'est
> désormais aussi** : la réserve qui occupait ce site — *« ces deux lignes sont
> ÉCRITES et non ÉPROUVÉES »* — a été levée le **16 septembre 2026 à 13:40 UTC**
> par le lot 24, qui a recréé le conteneur en service pour la première fois
> depuis le 15 septembre 21:21 UTC.
>
> **CE QUE `docker compose up -d --no-build agent-api` A RÉELLEMENT FAIT**,
> `mesuré` le 16 septembre 2026 à 13:40:12–13:40:15 UTC, depuis le clone
> principal, `rc(docker compose)=0`, durée **3 s** :
>
> ```
> Container rag-agent-api Recreate / Recreated / Starting / Started
> ```
>
> | la question que la réserve posait | la réponse, mesurée |
> |---|---|
> | `--no-build` empêche-t-il `up` de reconstruire ? | **OUI.** Aucune étape de build dans la sortie, et `rag-agent-chat-agent-api:latest` désigne le **même** identifiant avant et après le `up` — `sha256:48b00a43…`, `Created=2026-09-16T13:39:21Z`, celui que (d) venait de produire |
> | `up` recrée-t-il bien le conteneur ? | **OUI**, il le RECRÉE et n'en redémarre pas l'ancien : identifiant de conteneur neuf (`52472b83…` contre `fc727600…`), PID neuf, `RestartCount` **remis à 0** |
> | le conteneur sert-il l'image neuve ? | **OUI.** `docker inspect -f '{{.Image}}'` rend `sha256:48b00a43…` |
> | `frontend` est-il emporté par son `depends_on` ? | **NON.** `rag-frontend` garde le **même identifiant de conteneur**, le même `StartedAt=2026-09-15T14:06:07Z` et `RestartCount=0` de part et d'autre du `up`. Un `up` nommant `agent-api` ne touche pas ses dépendants |
> | combien de temps avant `healthy` ? | **21 s** — `Started` à 13:40:14, `Health=healthy` à 13:40:35, `FailingStreak=0`. Le `start_period` de 30 s n'a pas été consommé en entier |
>
> **CE QUI RESTE NON ÉPROUVÉ, ET IL FAUT LE DIRE EXACTEMENT.** Le lot 24 n'a pas
> eu besoin de revenir en arrière — le déploiement a tenu —, donc **la section
> *Revenir* n'a PAS été jouée de bout en bout**. Sa réserve est *réduite*, pas
> *levée* : son ingrédient risqué, `up --no-build`, est maintenant mesuré
> ci-dessus, et le `docker image tag` qui le précède l'était déjà. Ce qui reste
> cru sur la documentation, c'est **leur composition** — que reposer `latest` sur
> l'ancienne image PUIS `up --no-build` rende effectivement le conteneur à
> l'image relevée en (a). Le chemin du retour a été **armé** ce jour-là et
> vérifié à sa source (l'étiquette pend bien à l'image servie, §4 (c)) ; il n'a
> pas été parcouru.

```bash
# (a) Ce qui sert MAINTENANT. On tranche par le conteneur.
SERVI="$(docker inspect -f '{{.Image}}' rag-agent-api)"
NOM="$(docker inspect -f '{{.Config.Image}}' rag-agent-api)"
echo "$NOM sert $SERVI"
```

```bash
# (b) L'ÉTIQUETER, avant de construire quoi que ce soit.
#     L'étiquette est CAPTURÉE, jamais recalculée : deux `$(date -u ...)` posés à
#     quelques secondes d'intervalle peuvent tomber de part et d'autre de minuit,
#     et (c) vérifierait alors une étiquette qui n'existe pas.
ETIQUETTE="$NOM:$(date -u +%Y-%m-%d)-avant-redeploiement"
docker image tag "$SERVI" "$ETIQUETTE"
echo "$ETIQUETTE"   # à recopier dans le journal du lot : c'est le chemin du retour
```

```bash
# (c) VÉRIFIER À QUOI L'ÉTIQUETTE PEND. Ne pas sauter cette ligne :
#     c'est celle qui manquait au lot 18.
docker image inspect -f '{{.Id}}' "$ETIQUETTE"
```
La sortie doit être **identique** à `$SERVI`. Si elle diffère, l'étiquette
désigne autre chose : s'arrêter là.

```bash
# (d) Construire. Le sha et la propreté de l'arbre entrent dans l'image ici.
make image
```

```bash
# (e) Déployer. `--no-build` est une ceinture : il interdit à `up` de
#     reconstruire par surprise l'image que (d) vient de produire.
#
#     OK CETTE LIGNE EST ÉPROUVÉE SUR CE POSTE, le 16 septembre 2026 à
#     13:40 UTC par le lot 24 : `rc=0`, 3 s, le conteneur est RECRÉÉ, RIEN n'est
#     reconstruit, `latest` ne bouge pas, `frontend` n'est pas touché, et la
#     santé revient en 21 s. Le détail est dans l'encadré du §4.
docker compose up -d --no-build agent-api
```

```bash
# (f) VÉRIFIER CE QUI TOURNE MAINTENANT, par le conteneur et non par l'étiquette.
curl -s http://localhost:8011/health | python3 -c 'import json,sys; print(json.load(sys.stdin).get("code_servi", "CLÉ ABSENTE : cet agent est ANTÉRIEUR au lot du 16 septembre 2026"))'
```
`.get` ET NON UNE INDEXATION : un agent antérieur à ce lot ne publie pas la clé
du tout, et une `KeyError` ferait croire à une commande cassée là où le message
dit le fait — *cet agent ne sait pas répondre à la question*. C'est d'ailleurs ce
qu'a rendu le service en place le 16 septembre 2026 à 09:22 UTC.

Attendu : `etat: "identifie"` et le sha du commit déployé. Un `anonyme` ici
signifie que le build n'est pas passé par `make image` — **et le déploiement est
à refaire**, sans quoi le lot suivant retrouvera la question ouverte.

### Revenir

> **ATTENTION DEPUIS LE LOT 28, REVENIR SUR LE MOTEUR PASSE PAR ICI — ET PAR RIEN
> D'AUTRE.** Jusqu'au 18 septembre 2026, changer de moteur était une ligne de
> `.env` : le code portait les deux dialectes, et repasser le réglage suffisait,
> **sans reconstruire ni redéployer**. Le lot 28 a retiré le support du second
> moteur. Ce chemin-là n'existe plus, et il ne reste que celui-ci.
>
> **CE QUE ÇA COÛTE, DIT FRANCHEMENT.** Revenir exigeait une édition de fichier et
> un redémarrage de processus ; il exige désormais de **réétiqueter une image et
> de redéployer**. C'est plus long, cela demande le démon Docker et la main du
> pilote, et surtout : **cela ramène tout le code d'avant**, pas seulement le
> moteur. Les correctifs livrés depuis repartent avec.
>
> **L'ÉTIQUETTE DU RETOUR SUR LE MOTEUR**, vérifiée le 18 septembre 2026 à
> 13:37 UTC :
>
> ```
> rag-agent-chat-agent-api:2026-09-17-avant-bascule-vllm
> ```
>
> Elle pend à `sha256:48b00a43…`, construite le **2026-09-16T13:39:21Z**, qui
> porte `RAG_AGENT_CODE_SHA=b7337a3e544009dbbbc36764cb072e046b175e09` — le code
> du lot 24, antérieur à la bascule. L'image servie ce jour-là porte, elle,
> `7b0edb0`, construite le **2026-09-17T07:45:03Z**. Les deux sont donc bien
> distinctes, et **l'étiquette ne ment pas sur ce qu'elle désigne** : ce dépôt a
> déjà vu une étiquette datée pendre à l'image d'un autre jour, et la vérifier
> coûte une commande. C'est en outre sa **seule** étiquette : sans elle, cette
> image n'est plus retrouvable que par son identifiant.
>
<!-- migration-du-lot-28:début — ce paragraphe nomme les trois clés que le
     retour arrière doit RESTAURER dans le `.env`. Sans leurs noms exacts, le
     geste est injouable. Le garde `test_le_nom_de_l_ancien_moteur_ne_revient_pas`
     borne cette exemption à ce bloc et mord partout ailleurs dans ce fichier. -->

> **ET LE `.env` DOIT REVENIR AVEC ELLE.** C'est le piège de ce retour-ci, et il
> est silencieux. L'image d'avant lit `LLM_ENGINE`, `OLLAMA_HOST` et
> `OLLAMA_MODEL` ; la migration du lot 28 les retire du `.env`
> (`documentation/moteur_llm.md`, « la migration du `.env` »). Sous un `.env`
> migré, cette image ne trouverait aucune de ces trois clés et **retomberait sur
> ses défauts SANS UN MOT** — `extra="ignore"` d'un côté, des défauts de champ de
> l'autre. Elle repartirait alors sur un hôte qui n'est pas celui du poste. **Le
> retour arrière du moteur est donc un geste en DEUX temps** : restaurer les
> trois clés dans le `.env` du clone principal, *puis* réétiqueter et redéployer.
> Garder une copie du `.env` d'avant la migration est ce qui rend le premier
> temps possible.

<!-- migration-du-lot-28:fin -->

```bash
NOM="$(docker inspect -f '{{.Config.Image}}' rag-agent-api)"
ETIQUETTE="<celle que (b) a affichée, recopiée telle quelle>"

# Vérifier d'abord à quoi elle pend, et SEULEMENT ensuite la faire servir.
docker image inspect -f '{{.Id}}' "$ETIQUETTE"
docker image tag "$ETIQUETTE" "$NOM:latest"

# ATTENTION RÉSERVE RÉDUITE, PAS LEVÉE, et c'est plus gênant ici qu'au (e) : c'est la
#   ligne d'un RETOUR ARRIÈRE, donc celle qu'on joue sous pression. Ce que fait
#   `up --no-build` est désormais MESURÉ (encadré du §4, 16 septembre 2026) : il
#   recrée le conteneur sur l'image que `latest` désigne, sans rien
#   reconstruire. Ce qui reste NON ÉPROUVÉ est la COMPOSITION de ce `up` avec le
#   `docker tag` qui le précède — aucun lot n'a eu à revenir en arrière. Les deux
#   lignes qui l'encadrent, elles, sont éprouvées : vérifier à quoi l'étiquette
#   pend AVANT, et relever l'image du conteneur APRÈS. Si le `up` ne fait pas ce
#   qu'on attend, c'est la dernière ligne de ce bloc qui le dira.
docker compose up -d --no-build agent-api

# Et contrôler que le retour a eu lieu, par le conteneur.
docker inspect -f '{{.Image}}' rag-agent-api
```

Le dernier identifiant doit être celui relevé en (a).

---

## 4 bis. LE GARDE DE PROPRETÉ COMPTE DES FICHIERS QUI N'ENTRENT JAMAIS DANS L'IMAGE

**Ceci a failli coûter au lot 24 son objectif principal, et ce n'est pas un cas
limite : c'est l'état par défaut de ce poste dès qu'une session d'outillage y
travaille.**

`make image` décide de `code.arbre` ainsi :

```make
S="$(git -C . status --porcelain)"
RAG_AGENT_CODE_ARBRE="$([ -z "$S" ] && echo propre || echo sale)"
```

`git status --porcelain` liste **aussi les fichiers NON SUIVIS**. Or
`Dockerfile.agent` ne copie que `requirements.txt`, `src/agent` et `src/api` :
**un fichier non suivi hors de ces trois chemins ne peut pas changer l'image**,
et pourtant il fait graver `arbre=sale` — donc `/health` rend
`etat: "arbre_sale"`, donc le §1 de ce document ordonne *« Ne pas comparer »*, et
la campagne appariée refuse un agent parfaitement identifiable.

**L'état trouvé le 16 septembre 2026 à 13:33 UTC**, `mesuré` sur le clone
principal :

```
$ git status --porcelain -uall
?? <arbre de travail>/
?? <arbre de travail>/

$ git status --porcelain --untracked-files=no
(vide — AUCUN fichier suivi ne s'écarte de HEAD)
```

Les deux seules saletés étaient les **arbres de travail de l'outillage de
session**, `.<branche de session>/` n'étant couvert par aucun `.gitignore` du dépôt.
Le lot qui redéploie salit donc l'arbre **par sa seule présence**.

**CE QUE LE LOT 24 A FAIT, ET IL LE DIT PLUTÔT QUE DE LE TAIRE.** Il a ajouté
`/.<branche de session>/` à `.git/info/exclude` — **local, non versionné, et retiré
juste après le déploiement**, le fichier étant restauré à son SHA-256 d'origine
(`6671fe83…`, vérifié). Motif volontairement **ÉTROIT** : toute AUTRE saleté doit
continuer à faire graver `sale`. *Contrôle positif posé avant de construire* : un
fichier témoin créé à la racine fait bien ressortir `?? ZZ_temoin…` — le garde
mordait encore.

**Ce que cette manœuvre ne prouve pas, et ce qui le prouve.** Écrire
`arbre=propre` ne garantit pas que l'image contienne le code de ce commit ; c'est
le §6 qui le tranche, en comparant le contenu du conteneur au dépôt. C'est ce
qui a été fait, et `18/18` fichiers concordent au SHA-256.

**LA CORRECTION DURABLE N'EST PAS CELLE-LÀ.** Deux chemins, et le second est le
bon :

- ajouter `<répertoire de l'outillage>/` au `.gitignore` **versionné** — le lot 24 le propose sur sa
  branche ; il ferme le cas précis, pas la classe ;
- faire porter la sonde de propreté **sur les chemins que le `COPY` réclame**,
  par exemple `git status --porcelain -- requirements.txt src/agent src/api`.
  C'est la sonde qui répond à la question posée — *le commit nommé décrit-il ce
  qui tourne ?* — plutôt qu'à une question plus large. **Ce changement touche le
  `Makefile` et mérite son lot, avec son garde et son audit** : il n'a pas été
  fait sous un redéploiement.

---

## 5. Quand `/health` et l'étiquette ne disent pas la même chose

```bash
SERVI="$(docker inspect -f '{{.Image}}' rag-agent-api)"
docker image inspect -f 'label={{index .Config.Labels "org.opencontainers.image.revision"}}' "$SERVI"
curl -s http://localhost:8011/health | python3 -c 'import json,sys; print("env  =", (json.load(sys.stdin).get("code_servi") or {}).get("sha"))'
```

Les deux doivent concorder. **S'ils diffèrent, c'est l'`ENV` qui a été surchargé
à l'exécution** — presque toujours par une variable `RAG_AGENT_CODE_*` posée dans
le `.env`. Le label est celui qui dit la vérité sur ce que le build a gravé ;
retirer la variable du `.env` et recréer le conteneur.

---

## 6. Ce que ce mécanisme ne dit pas

- **Il ne dit rien des dépendances.** Deux images construites du même sha à deux
  mois d'écart n'embarquent pas les mêmes roues. `construite_le` les sépare ; il
  ne remplace pas un verrou.
- **Il ne prouve pas que l'image contient le code de ce commit** — il rapporte ce
  que le build a déclaré. La seule preuve indépendante est de comparer le contenu
  du conteneur au dépôt, et elle coûte une lecture complète :
  ```bash
  docker cp rag-agent-api:/app/src /tmp/servi
  ```
  puis un rapprochement fichier par fichier. C'est ce geste qui a établi, le
  16 septembre 2026 à 09:02 UTC, que le service exécutait alors le code de
  `8209e68`, alors que la seule chose qui le disait était une étiquette posée à
  la main. **La propriété est `8209e68` ; le retard en commits est un
  instantané et il périme.** Ce site a d'abord écrit « 27 commits en arrière de
  `main` » ; le lot 24 a remesuré le 16 septembre 2026 à 13:33 UTC, sur
  `main` = `b7337a3` : `git rev-list --count 8209e68..b7337a3` rend **38**. Le
  27 n'était pas faux, il avait **vieilli de onze commits de registre** entre sa
  mesure et sa relecture. *Nomme la révision, pas la distance.*

  Le même geste, rejoué par le lot 24 le 16 septembre 2026 à 13:41 UTC APRÈS le
  redéploiement, rend **18 fichiers sur 18 identiques au SHA-256**, `0`
  différent, `0` manquant, `0` en trop, contre `b7337a3`. **Et ce zéro est
  doublé d'un contrôle positif** — la même méthode rend `rc=1` sur chacun des
  quatre modes de défaut : référence différente (`8209e68`), un seul octet
  ajouté à un fichier, un fichier retiré, un fichier ajouté. Un « tout est
  identique » qu'on n'a pas su faire rougir ne dit rien.
- **Il ne surveille rien.** Il publie. C'est à la campagne appariée, au pipeline
  et à l'exploitant de lire `code_servi` et de refuser de comparer deux mesures
  qui ne viennent pas du même code.
