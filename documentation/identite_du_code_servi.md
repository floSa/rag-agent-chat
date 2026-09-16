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

---

## 4. Redéployer, et pouvoir revenir — la marche exacte

> **L'étiquetage vient AVANT tout autre geste.** C'est ce qui a sauvé le retour
> arrière du lot 18, et l'ordre n'est pas négociable : une fois `latest` repris
> par une image neuve, l'ancienne n'a plus de nom.

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

```bash
NOM="$(docker inspect -f '{{.Config.Image}}' rag-agent-api)"
ETIQUETTE="<celle que (b) a affichée, recopiée telle quelle>"

# Vérifier d'abord à quoi elle pend, et SEULEMENT ensuite la faire servir.
docker image inspect -f '{{.Id}}' "$ETIQUETTE"
docker image tag "$ETIQUETTE" "$NOM:latest"
docker compose up -d --no-build agent-api

# Et contrôler que le retour a eu lieu, par le conteneur.
docker inspect -f '{{.Image}}' rag-agent-api
```

Le dernier identifiant doit être celui relevé en (a).

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
  `8209e68` — **27 commits en arrière de `main`** — alors que la seule chose qui
  le disait était une étiquette posée à la main.
- **Il ne surveille rien.** Il publie. C'est à la campagne appariée, au pipeline
  et à l'exploitant de lire `code_servi` et de refuser de comparer deux mesures
  qui ne viennent pas du même code.
