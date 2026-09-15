# Le moteur LLM consigné dans les campagnes

> **Mesuré le 15 septembre 2026**, entre **15:25 et 15:44 UTC**, `date -u` relevé
> avant chaque mesure. Ce document est le site canonique de la clé `moteur_llm`.
> Les versions qu'il cite sont datées : elles seront fausses au prochain
> redémarrage des serveurs, et **aucun garde du dépôt ne les épingle** — ce sont
> les relations qui sont tenues, pas les valeurs.

---

## 1. Le trou que cette clé referme

Le [banc go/no-go de la bascule vers vLLM](audits/2026-09-15-banc-go-no-go-vllm.md)
a rendu **GO sous conditions** sur cinq de ses six questions. La sixième — *ce
que la bascule coûterait en qualité* — est la seule **NO-GO**, et son §7 dit
pourquoi : ce n'est pas un défaut de vLLM.

> `runs/` consigne désormais le **périphérique**, depuis le lot sur le GPU.
> **Rien n'y consigne le moteur LLM** — ni le serveur, ni son URL, ni sa version,
> ni le nom exact du modèle servi, ni ses drapeaux. Donc **aucune campagne déjà
> au disque n'est comparable à une campagne future**.

`mesuré` le 15 septembre 2026 à 15:26 UTC, sur les **19** artefacts de `runs/` :

| | Campagnes portant la clé | Recette |
|---|---|---|
| `empreinte_des_ancrages` | 10 / 19 | `python -c "import json,glob; print(sum(1 for f in glob.glob('runs/*.json') if json.load(open(f)).get('empreinte_des_ancrages')))"` |
| `peripherique` | **0 / 19** | idem, clé `peripherique` |
| `moteur_llm` | **0 / 19** | idem, clé `moteur_llm` |

Les **zéros sont doublés d'un contrôle positif** — la première ligne, non nulle,
établit que la sonde lit bien les fichiers.

**Ce que cela veut dire, et il faut le dire sans détour : aucune campagne
existante ne sert de base à la bascule.** La clé ne s'applique pas
rétroactivement ; seule une campagne **rejouée** en portera une. C'est le lot 2
du découpage, et il doit passer **avant** tout changement de moteur.

---

## 2. Ce qui est consigné, et d'où chaque champ vient

À la racine de l'artefact, sous `moteur_llm`. Relevé par l'agent à `/health`,
**après** les questions.

| Champ | Fait ou réglage | Relevé par |
|---|---|---|
| `serveur` | **fait** | déduit de la route de version qui répond |
| `endpoint` | **fait**, expurgé | l'URL réellement jointe, sans userinfo ni chemin |
| `version` | **fait** | `GET /api/version` (Ollama) ou `GET /version` (vLLM) |
| `modele_servi` | **fait** | `GET /api/tags` (Ollama) ou `GET /v1/models` (vLLM) |
| `empreinte_du_modele` | **fait** | le `digest` Ollama, tronqué à 16 caractères |
| `quantification` | **fait** | `details.quantization_level` (Ollama) |
| `fenetre_servie` | **fait** | `max_model_len` (vLLM) |
| `modele_demande` | *réglage* | `OLLAMA_MODEL` |
| `options` | *réglage* | nos cinq drapeaux d'appel |
| `releve_le` | **fait**, sur NOUS | l'horloge de l'agent à l'instant du relevé, ISO-8601 UTC |

**POURQUOI UNE DATE, ET SUR CE CHAMP SEUL.** Le relevé est **mémorisé pour la vie
du processus** de l'agent, et c'est le **seul** état de `/health` qui le soit :
toutes les autres sondes sont relancées à chaque battement, donc ce qu'elles
publient date de la réponse qu'on lit. Celui-ci peut dater d'il y a onze heures.
Le lecteur visé est **externe** — le pipeline, l'équipe voisine qui relance son
serveur vLLM quand elle change son réglage de mémoire GPU : la valeur devient
fausse sans que rien ne rougisse, et la seule défense honnête est de dater ce
qu'on publie. C'est la date du **relevé**, jamais celle de la lecture, et la
distinction est tout l'intérêt du champ — un horodatage refait à chaque lecture
rendrait un relevé de onze heures indiscernable d'un relevé neuf.

`releve_le` **n'entre pas dans la signature**, et un test le tient : deux
campagnes tournées sur le même serveur à deux heures différentes doivent signer
**pareil**, sans quoi `--compare` conclurait « MOTEUR LLM DIFFÉRENT » sur un
moteur identique.

**CE QUI EST MÉMORISÉ EST UN RELEVÉ COMPLET**, et c'était la bloquante de l'audit
du 15 septembre 2026. Le prédicat était « le serveur a dit son nom » ; il est
« le serveur a dit son nom **et** ce qu'il porte » (`modele_servi`). Entre les
deux se trouve la fenêtre de démarrage : un serveur dont le port HTTP répond
avant que son modèle soit servi rendait un relevé **partiel**, figé à vie, d'où
`/health` publiait `modele_servi: null` en permanence sur un serveur
parfaitement sain — et `signature_du_moteur` en tirait « modèle ABSENT DU
SERVEUR », une affirmation **fausse** et non un silence. Le relevé partiel est
toujours **rendu** ; il n'est plus **figé**. Il se redemande au battement
suivant, vingt secondes plus tard.

**LE FAIT, JAMAIS L'INTENTION**, et c'est la leçon de la clé `peripherique` du
lot 12 : `requested` y est le réglage, `embedding` le fait. Ici, `ollama_model`
publie depuis toujours le nom qu'on **demande** — il reste identique quand le
serveur d'en face est remplacé, mis à jour, ou sert un autre poids sous le même
tag.

**Pourquoi l'empreinte pèse.** Un tag Ollama est **mutable**. Deux campagnes
lancées toutes deux sur `gemma4:e4b` contre deux serveurs portant deux poids sous
ce nom sont incomparables, et leur `modele_demande` est identique au caractère
près. C'est `empreinte_du_modele` qui les sépare, et c'est pour cela qu'elle est
dans la signature.

**Pourquoi les options y sont quand même.** Elles sont du réglage, assumé : rien
au monde ne les relève d'un serveur. Elles sont là parce qu'elles changent le
**sens** de la réponse et non sa vitesse — deux campagnes contre le même serveur,
l'une avec le raisonnement allumé et l'autre non, ne mesurent pas la même chose.
Elles sont confrontées **à part**, sur leur propre ligne : les mêler à la
signature ferait lire « moteur différent » là où le moteur est le même.

---

## 3. Ce que les deux serveurs rendent vraiment

`mesuré` le 15 septembre 2026 à 15:31 UTC, par la sonde livrée, contre les deux
serveurs de ce poste. **Valeurs datées, non gardées.**

```jsonc
// Ollama, port hôte 11434
{"serveur": "ollama", "version": "0.30.10", "modele_servi": "gemma4:e4b",
 "empreinte_du_modele": "c6eb396dbd5992bb", "quantification": "Q4_K_M",
 "fenetre_servie": null}

// vLLM, port hôte 8100 — l'instance d'une autre équipe
{"serveur": "vllm", "version": "0.28.0",
 "modele_servi": "google/gemma-4-E4B-it-qat-w4a16-ct",
 "empreinte_du_modele": null, "quantification": null, "fenetre_servie": 32768}
```

**Deux écarts que ce relevé rend visibles et que `ollama_model` cachait :**

- le poids d'Ollama est un **GGUF `Q4_K_M` de 8,0 milliards de paramètres** ;
  celui de vLLM est une quantification **`w4a16`**. Ce ne sont pas les mêmes
  poids, et `gemma4:e4b` contre `google/gemma-4-E4B-it-qat-w4a16-ct` ne le disait
  qu'à qui sait lire un nom de dépôt ;
- vLLM sert une fenêtre de **32 768** quand nous en demandons **8 192**
  (`LLM_NUM_CTX`). `fenetre_servie` et `options.num_ctx` sont deux grandeurs
  différentes et le document les nomme séparément.

**CE QUE LE CATALOGUE vLLM PORTE D'AUTRE, ET QUI NE SERT À RIEN.** `mesuré` le
15 septembre 2026 à 17:30 UTC, la réponse complète de `/v1/models` porte aussi
`created`, `owned_by`, `root`, `parent` et un bloc `permission`. **Aucun n'est
relevé, et deux sont écartés exprès** : `created` et `permission[].id` sont
**régénérés à chaque requête** — deux lectures du même serveur à quatorze
secondes d'écart rendent deux valeurs différentes. Les consigner ferait différer
deux relevés du même moteur. Voir le §6.

---

## 4. Le discriminant, et pourquoi il exige une réponse POSITIVE

| Route | Ollama | vLLM |
|---|---|---|
| `GET /api/version` | **200** + `{"version": …}` | **404** |
| `GET /version` | 404 | **200** + `{"version": …}` |

`mesuré` le 15 septembre 2026 à 15:25 UTC sur les deux serveurs.

**Un discriminant qui saurait seulement dire « ce n'est pas Ollama » rangerait
n'importe quel serveur muet dans « vLLM ».** Celui-ci exige un `version` de type
chaîne pour conclure ; à défaut, le champ entier est **`null`**, et `null` se lit
« je n'ai pas pu lire », jamais « Ollama ».

C'est la leçon du deuxième faux résultat du banc go/no-go : un `finish_reason:
"tool_calls"` rendu en **HTTP 200 sans aucun appel d'outil**. Un code de retour
n'est pas un fait.

**Au plus trois requêtes, toutes en lecture.** Aucune génération, aucun jeton.
Le serveur vLLM de ce poste appartient à une autre équipe, et le relevé est
**mémorisé pour la vie du processus** après un premier succès : `/health` est
battu toutes les 20 s par le healthcheck, et deux requêtes de plus à chaque
battement seraient un prix permanent pour un fait qui ne change qu'au redémarrage
du serveur. **Un échec n'est pas mémorisé** — sinon un serveur qui finit de
démarrer resterait muet pour toujours.

---

## 5. Ce que `--compare` en dit : trois positions

| Position | Quand | Ce qui est imprimé |
|---|---|---|
| `IDENTIQUE` | les deux signatures coïncident | `moteur LLM : IDENTIQUE des deux côtés — …` |
| `DIFFÉRENT` | les deux sont connues et diffèrent | les **deux** signatures, et l'avertissement d'attribution |
| `MUET` | l'une au moins est inconnue | ce qu'on sait de chaque côté, et **pourquoi** |

**`IDENTIQUE` EST IMPRIMÉ, et ce n'est pas du bavardage.** Un garde qui ne parle
que lorsqu'il mord ne distingue pas « les deux campagnes ont tourné sur le même
moteur » de « ce garde n'existe pas dans la version qui a produit cette sortie ».
C'est la forme exacte du faux vert que ce chantier a trouvée neuf fois.

**« MUET » N'EST PAS « DIFFÉRENT ».** On ne peut ni affirmer ni exclure une
bascule. Les campagnes de `runs/` en sont toutes là aujourd'hui.

**ET `DIFFÉRENT` EST INATTEIGNABLE CÔTÉ vLLM SUR DEUX POIDS SERVIS SOUS LE MÊME
`id`.** C'est une borne du tableau ci-dessus, pas une note de bas de page, et
elle pèse d'autant plus que le chantier bascule **vers** vLLM : la position
n'est atteinte que par un écart de signature, et la signature côté vLLM ne porte
rien qui sépare deux poids sous un même nom. Ce qui reste visible est le nom —
qui porte la quantification sur l'instance de ce poste — et la fenêtre servie.
Le détail de ce qui a été cherché, et de ce qui n'existe pas, est au §6.

**IL SIGNALE, IL NE REFUSE PAS**, et le motif est plus fort ici que pour le
périphérique. `empreinte_des_ancrages` **refuse**, parce qu'un corpus remplacé
rend des chiffres plausibles et faux sur chaque question. Le moteur est de
l'autre famille : **confronter deux moteurs est exactement ce que cette clé a été
posée pour permettre** — le lot 6 du découpage est une campagne vLLM appariée à
une campagne Ollama. Un garde qui refuserait interdirait le seul geste pour
lequel il a été demandé.

Le moteur **s'ajoute** à la discipline de l'empreinte, il ne la remplace pas : un
corpus remplacé reste un refus, quel que soit le moteur.

---

## 6. Ce que ce lot NE ferme pas, dit comme tel

- **Aucune campagne n'a été lancée.** `make eval` est le lot 2 ; sa fenêtre se
  referme au premier commit du lot 4. Ce lot n'y a pas touché.
- **L'agent en service ne publie pas encore la clé.** Il tourne le code
  antérieur, et **ce lot n'a redémarré aucun démon** — le poste est partagé.
  Jusqu'à son redémarrage sur `main`, `moteur_de_la_campagne` rendra `null` et
  toute campagne sera écrite **muette**. Le message d'avertissement de
  `evaluate.py` nomme cette cause en premier parce qu'elle est la seule qui se
  répare d'un geste.
- **Le serveur que l'agent joint n'a pas été vérifié de l'intérieur du
  conteneur.** `OLLAMA_HOST` y désigne un nom de service docker sur le port
  standard d'Ollama — `mesuré` le 15/09 à 15:26 UTC, **sur la forme de l'URL et
  non sur sa valeur**, le dépôt étant public. Que ce nom résolve vers
  `ollama-central` plutôt qu'un autre est **plausible et non mesuré** : l'établir
  demanderait un `docker exec` dans un conteneur de production.
- **Le comportement sous un serveur relancé pendant une campagne.** Le relevé
  étant mémorisé, il décrirait l'état d'avant. Ce n'est pas le cas que cette clé
  existe pour attraper — mais depuis le 15 septembre 2026 le relevé **porte sa
  date**, donc un lecteur peut voir qu'il décrit un instant antérieur.
  *(L'analogie autrefois invoquée ici avec `peripherique_de_la_campagne` a été
  **retirée** : celui-ci vit dans un processus de campagne qui se **termine** au
  bout de quelques minutes, celui-là dans un **démon** battu toutes les 20 s
  pendant des jours. La borne du premier ne justifie pas celle du second.)*

- **AUCUN DISCRIMINANT DE POIDS N'EXISTE CÔTÉ vLLM, et c'est mesuré.** `mesuré`
  le 15 septembre 2026 à 17:30–17:31 UTC, en **lecture seule**, contre
  l'instance de ce poste et sur les **sept** routes GET qu'elle déclare à
  `/openapi.json` (`/health`, `/load`, `/metrics`, `/ping`, `/v1/models`,
  `/v1/responses/{id}`, `/version`) :

  | Ce qu'on espérait | Ce qui a été mesuré |
  |---|---|
  | un digest de poids dans `/v1/models` | **absent** — `id`, `root`, `max_model_len` et rien d'autre d'utile |
  | `created` = l'instant de DÉMARRAGE du serveur | **faux** : il vaut l'instant de **chaque requête** (deux lectures du même serveur à 14 s d'écart rendent deux valeurs) |
  | `permission[].id` comme identifiant stable | **faux** : régénéré à chaque requête lui aussi |
  | une empreinte dans `/metrics` | **absente** — on y trouve la configuration du moteur, dont son utilisation mémoire GPU, et la lire coûterait une **quatrième** requête par battement sur un serveur partagé |

  Les deux faux amis ne sont pas seulement inutiles, ils sont **nuisibles** : les
  relever ferait différer deux relevés du **même** moteur. Un test l'interdit
  désormais. Ce qui reste donc non couvert est le cas exact du **poids remplacé
  sous un `id` inchangé**, côté vLLM — invisible, et dit ici plutôt que
  supposé fermé.

- **Le premier modèle du catalogue vLLM n'est pas confronté au modèle demandé**,
  là où la branche Ollama cherche explicitement le tag demandé et rend `null`
  s'il est absent. Ce n'est **pas** réparable par une égalité : les deux noms ne
  vivent pas dans le même espace de nommage — un tag Ollama court d'un côté, un
  identifiant de dépôt Hugging Face de l'autre —, et les confronter rendrait
  `modele_servi: null` en **permanence** sur un serveur parfaitement sain. Le
  garde « modèle ABSENT DU SERVEUR » ne peut donc pas se déclencher côté vLLM.
  `mesuré` le 15 septembre 2026 : l'instance voisine ne sert **qu'une** entrée,
  donc la réserve est inerte en pratique — elle cessera de l'être le jour où un
  serveur vLLM en servira plusieurs.

- **La clé n'a jamais été relevée à travers le `/health` d'un agent réellement
  en service.** L'audit l'a vérifié plutôt que supposé : le conteneur en service
  tourne du code antérieur au lot, et `moteur_llm` est absente de sa réponse.
  L'atteindre exigerait de **redémarrer ce démon**, ce que le poste partagé
  interdit. Aucune mesure de bout en bout à travers un vrai serveur ASGI
  n'existe donc à ce jour — ni de la part du lot, ni de son audit, ni de cette
  réparation. Ce que la sonde in-process ne peut pas voir reste non vu, en
  particulier le comportement du cache sous **plusieurs workers**, chacun ayant
  son propre `_moteur_releve` : deux battements consécutifs de `/health`
  derrière un répartiteur pourraient publier deux relevés d'âges différents —
  ce que `releve_le` rend au moins **visible**, sans le résoudre.

---

## 7. Recettes

```bash
# Ce que l'agent publie
curl -s localhost:8011/health | python3 -c "import json,sys; print(json.dumps(json.load(sys.stdin).get('moteur_llm'), indent=2, ensure_ascii=False))"

# Ce qu'une campagne a consigné
python3 -c "import json,sys; print(json.load(open(sys.argv[1])).get('moteur_llm'))" runs/une-campagne.json

# L'AGE du relevé publié : « pris il y a dix secondes » ou « il y a onze heures » ?
curl -s localhost:8011/health | python3 -c "
import datetime, json, sys
d = json.load(sys.stdin).get('moteur_llm') or {}
pris = d.get('releve_le')
print('relevé le', pris, '— il y a',
      datetime.datetime.now(datetime.UTC) - datetime.datetime.fromisoformat(pris)
      if pris else 'DATE ABSENTE (agent antérieur au 15 septembre 2026)')"

# Combien de campagnes du disque sont muettes
python3 -c "import json,glob; f=glob.glob('runs/*.json'); print(sum(1 for x in f if json.load(open(x)).get('moteur_llm') is None), 'muettes sur', len(f))"
```
