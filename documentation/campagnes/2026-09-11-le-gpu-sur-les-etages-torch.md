# Le GPU sur les étages torch — ce qu'il rapporte, et ce qui n'a pas pu être mesuré

`mesuré` le **11 septembre 2026**, entre **14:25 et 14:30 UTC**, par le lot 11,
sur l'agent en service (image `f4d488b447a6`, `torch 2.14.0+cu130`, carte
**NVIDIA L4**, pilote 595.71.05 / CUDA 13.2).

---

## 1. Ce que cette campagne mesure, et pourquoi elle ne ressemble pas aux autres

**Elle a DEUX instruments, et le second n'était pas prévu.**

Le plan d'origine était de rejouer `make eval` (138 questions) et
`make eval-controle` (30) sous les deux périphériques. Une première tentative a
été lancée à 12:54 UTC et **interrompue à 14:24 après 82 questions sur 138** :
un autre projet du poste disputait le service Ollama, et le temps par question
était passé de **6 846 ms** (antécédent du 10 septembre) à **~55 s** — quatre
heures pour rendre un `generation_ms` dominé par un tiers. Le §5 le mesure.

L'instrument de repli est **`POST /sources`** (§2 et §3), qui fait exactement le
travail de torch — l'embedder puis le cross-encoder — et **rien d'autre** : ni
génération, ni traduction, ni reconstruction par le graphe. Son temps mural
mesure l'étage que le périphérique change, sans la variance de celui qu'il ne
change pas.

**Puis le poste s'est libéré**, et les deux campagnes ont pu tourner pour de
bon : le contrôle à 14:29 (4 min 21 s) et les 138 questions à 14:34 (23 min 29 s),
les deux en `rc=0`. **C'est le §4bis qui porte le résultat décisif** — celui que
`/sources` ne pouvait pas donner : le coût de la **contention** sur la
génération.

**L'instrument retenu est `POST /sources`**, qui fait exactement le travail de
torch — l'embedder (`dense`), puis le cross-encoder (`rerank`) — et **rien
d'autre** : ni génération, ni traduction, ni reconstruction par le graphe. Son
temps mural mesure donc l'étage que le périphérique change, sans la variance de
l'étage qu'il ne change pas.

Ce que cet instrument NE dit pas, et le §6 y revient : il ne dit rien de la
**contention** entre torch et Ollama sur la même carte, puisqu'il ne fait pas
tourner Ollama.

---

## 2. Le protocole : A / B / A / B, et pourquoi cette forme

Quatre blocs de **60 mesures** chacun — les 30 questions du jeu du pipeline,
deux passes — en **alternant** le périphérique :

| ordre | bloc | `TORCH_DEVICE` |
|---|---|---|
| 1 | `A1-cpu` | `cpu` |
| 2 | `B-cuda` | `cuda` |
| 3 | `A2-cpu` | `cpu` |
| 4 | `B2-cuda` | `cuda` |

**L'alternance n'est pas décorative.** La charge de ce poste dérive — c'est le
§5 — et deux blocs mesurés l'un après l'autre ne distinguent pas « le GPU est
plus rapide » de « la machine était moins chargée ». Encadrer chaque bloc GPU par
deux blocs CPU rend la dérive visible **dans la mesure elle-même**.

Chaque bloc jette une **passe de chauffe** : la première requête après une
recréation du conteneur paie le chargement des modèles, et `index_lexical` est
vérifié à `true` avant de mesurer — sans quoi la recherche serait dense seule, et
le bloc mesurerait un chemin plus court, pas un périphérique plus rapide.

---

## 3. Le résultat

`mesuré` — temps mural de `POST /sources`, en millisecondes :

| bloc | n | p50 | moyenne | p95 | min | max |
|---|---:|---:|---:|---:|---:|---:|
| `A1-cpu` | 60 | **815,3** | 837,5 | 1 098,2 | 548,3 | 1 166,4 |
| `B-cuda` | 60 | **164,7** | 154,9 | 174,3 | 107,1 | 188,2 |
| `A2-cpu` | 60 | **640,0** | 1 010,4 | 3 827,9 | 430,5 | 3 922,2 |
| `B2-cuda` | 60 | **119,3** | 119,7 | 133,6 | 106,0 | 143,8 |

Groupés, 120 mesures par périphérique :

| | p50 | moyenne |
|---|---:|---:|
| CPU (`A1` + `A2`) | **777,6 ms** | 923,9 ms |
| GPU (`B` + `B2`) | **126,9 ms** | 137,3 ms |
| **écart** | **−650,7 ms, soit −83,7 %** | **facteur ×6,13** |

**ET LES DEUX POPULATIONS SONT DISJOINTES.** Le **pire** cas GPU vaut
**188,2 ms** ; le **meilleur** cas CPU vaut **430,5 ms**. Aucune mesure GPU ne
chevauche aucune mesure CPU, sur 240 mesures. *C'est ce qui met le résultat hors
de portée de la dérive de charge* : la dérive entre `A1` et `A2` est de 175 ms
sur le p50, quand l'écart mesuré est de 651 ms.

**Le gain est cohérent avec le plafond prévu.** L'antécédent du 10 septembre
donne `dense_ms` 115 + `rerank_ms` 622 = **737 ms** de travail torch par réponse.
La mesure en récupère **650,7 ms**, soit **88 %** de ce plafond. Le reste —
`lexical_ms` (BM25, 60 ms) et `fusion_ms` — ne touche pas torch et ne pouvait pas
bouger.

**Le GPU est aussi beaucoup plus RÉGULIER**, et ce n'est pas un détail
d'exploitation : p95 à **133,6 ms** contre **3 827,9 ms** en CPU sur le même
bloc. Un cross-encoder sur CPU est en concurrence avec tout ce qui tourne sur la
machine ; sur la carte, il ne l'est qu'avec Ollama.

---

## 3bis. LES DEUX CAMPAGNES, ET LE CHIFFRE QUI DÉCIDE

`mesuré` le 11 septembre 2026, agent en `TORCH_DEVICE=cuda`, `make eval` de
14:34 à 14:58 UTC (**23 min 29 s**, `rc=0`) et `make eval-controle` de 14:29 à
14:33 (**4 min 21 s**, `rc=0`).

### Les 138 questions, contre `runs/2026-09-10-lecteur-neuf-reglage.json`

| métrique | CPU (antécédent) | GPU | écart |
|---|---:|---:|---|
| `rerank_ms` p50 | 498 | **58** | **−440 ms (−88 %)** |
| `rerank_ms` p95 | 2 943 | **68** | **−2 875 ms (−98 %)** |
| `dense_ms` p50 | 120 | **72** | −48 ms (−40 %) |
| `dense_ms` p95 | 1 516 | **85** | −1 431 ms (−94 %) |
| `retrieval_ms` p50 | 700 | **218** | −482 ms |
| **`generation_ms` p50** | **4 682** | **4 722** | **+40 ms (+0,85 %)** |
| **`total_ms` p50** | **7 298** | **6 481** | **−817 ms (−11,2 %)** |

**LA CONTENTION EST MESURÉE, ET ELLE EST PETITE : +40 ms.** C'est le chiffre que
ce lot existait pour produire, et il renverse la crainte qui avait présidé au
lot : partager la carte avec Ollama — qui porte 67 % du temps — coûte **40 ms**
là où le GPU en fait gagner **817**. Rapport de **vingt contre un**.

**Les p95 sont l'information la plus utile pour un service multi-utilisateurs** :
`rerank_ms` passe de 2 943 à **68 ms**. Sur CPU, le cross-encoder est en
concurrence avec tout ce qui tourne sur la machine ; sur la carte, seulement avec
Ollama. C'est la queue de distribution qui décide du ressenti, pas la médiane.

### Le rappel — et LA question qui bascule

Neuf métriques de rappel sur dix sont **identiques question par question**,
130/130 ex æquo, contre les **deux** antécédents (`2026-09-08-reference.json` par
la recette, et `2026-09-10-lecteur-neuf-reglage.json` par comparaison croisée).

La dixième bouge sur **une seule question**, et elle est écrite plutôt que tue :

| | `G-006` |
|---|---|
| `rang_reciproque` | 1,0 → **0,5** (le bon élément passe du rang 1 au rang 2) |
| `rappel_recherche` | 1,0 → 1,0 |
| `rappel_elements` | 1,0 → 1,0 |
| `rappel_documents` | 1,0 → 1,0 |
| Δ moyen sur 130 | **−0,0038**, IC 95 % [−0,011, +0,000], p=1,000 |

Le document reste trouvé ; c'est son **ordre** face à un candidat quasi ex æquo
qui s'inverse.

**ET CELA CORRIGE UNE CONCLUSION DU LOT 10.** Celui-ci avait mesuré que le
périphérique déplace les scores du cross-encoder de **5,48 × 10⁻⁶** et conclu
« **classement inchangé** ». Sur 138 questions réelles, le classement change —
une fois. La mesure du lot 10 n'était pas fausse ; sa **généralisation** l'était,
et c'est exactement la classe d'erreur que ce chantier traque : un résultat vrai
sur son échantillon, lu comme vrai partout. *Un écart de 5 × 10⁻⁶ suffit à
inverser deux candidats dont les scores diffèrent de moins que ça.*

### Le contrôle, 30 questions

`rc=0`. Rappel **identique** contre les deux antécédents (26/26 et 30/30 ex
æquo), aucune question ne bascule. `retrieval_ms` p50 879 → 237, `rerank_ms` p95
2 817 → 72, `total_ms` p50 8 296 → 7 403 (−10,8 %). `generation_ms` p50 5 165 →
5 633 (+468 ms) — **et cette valeur-là n'est pas exploitable** : le contrôle a
tourné pendant que le tiers du §5 était encore actif, sur 30 questions seulement.
C'est la campagne à 138 qui porte le chiffre de contention.

---

## 4. La preuve que le GPU est ATTEINT, et non seulement présent

Trois preuves indépendantes, `mesuré` le 11 septembre 2026 à 14:26 UTC. Aucune
ne suffit seule — un garde présent mais jamais atteint est la forme dominante des
défauts de ce chantier.

1. **Un second processus sur la carte**, et c'est la seule preuve extérieure au
   programme :
   ```
   pid, process_name, used_gpu_memory [MiB]
   2487976, /usr/lib/ollama/llama-server, 4900 MiB
   2494733, /usr/local/bin/python3.12,    1266 MiB
   ```
   `docker inspect rag-agent-api --format '{{.State.Pid}}'` rend **2494733** :
   le second processus **est** l'agent.
2. **`/health`** publie `embedding: "cuda:0"` et `rerank: "cuda:0"` — les modèles
   sont posés sur la carte, et non seulement capables de l'être.
3. **Le journal** porte les deux lignes de chaque chargement, celle du
   périphérique *demandé* et celle du périphérique *posé* :
   ```
   Chargement du modèle d'embedding : … périphérique demandé « cuda »
   Modèle d'embedding chargé sur le périphérique « cuda:0 »
   ```

**La mémoire n'est pas une contrainte** : 1 266 à 1 396 MiB pour l'agent, à côté
des 4 900 MiB d'Ollama, sur **23 034 MiB** de carte. Les deux cohabitent à 27 %
d'occupation.

---

## 5. LA TROUVAILLE QUI A CHANGÉ LE PLAN : le poste est partagé

**Un autre projet de la machine dispute le service Ollama pendant les mesures.**
`mesuré` le 11 septembre 2026 entre 13:06 et 13:09 UTC.

Les logs d'`ollama-central` montrent **deux** clients qui alternent :

| adresse | route | qui |
|---|---|---|
| `172.19.0.3` | `POST /api/chat` | **cet agent** (`rag-agent-api`) |
| `172.19.0.1` | `POST /v1/chat/completions` | la passerelle du réseau, donc un client **sur l'hôte** |

`ss -tnp` nomme le client de l'hôte : trois processus de
`/home/ubuntu/data-analyst-agent` — deux serveurs `uvicorn` (ports 8078 et 8079)
et un script `mesure_surface_conversationnelle.py`. **Projet distinct, hors du
mandat de ce lot, qui n'y a pas touché.**

**L'effet est mesuré, pas déduit.** Échantillonnage de la mémoire de la carte
toutes les 3 s pendant que la campagne tournait :

```
13:06:26  4909 MiB, 66 %      13:06:29     3 MiB,  3 %
13:06:38  4593 MiB, 92 %      13:06:44     3 MiB,  0 %
13:06:51  4909 MiB, 91 %      13:06:57     3 MiB,  0 %
```

Sept cycles de chargement complet du modèle en deux minutes. Ollama est pourtant
réglé à `OLLAMA_KEEP_ALIVE=24h` : le modèle n'est pas déchargé par expiration,
il est **évincé** par l'alternance entre deux clients. Chaque appel LLM paie donc
un rechargement de ~4,9 Go.

**Conséquence chiffrée** : `POST /api/chat` met **24 à 39 s** par appel, contre
un `generation_ms` p50 de **4 616 ms** à l'antécédent du 10 septembre. Le temps
par question de la campagne passe de **6 846 ms** à **~55 s**, soit **×8**.

**Ce que ça invalide** : toute comparaison de `generation_ms`, `translation_ms`
et `total_ms` avec les antécédents versionnés, tant que ce tiers tourne. Ce que
ça n'invalide pas : les métriques de **rappel**, qui sont déterministes, et la
mesure du §3, qui ne passe pas par Ollama.

---

## 6. Ce que cette campagne NE dit pas

**La contention, elle, a fini par être mesurée** — c'est le §3bis, et c'était la
réserve centrale de ce lot. Restent trois choses qu'aucun de ces chiffres ne
couvre, et qu'il faut savoir avant de s'en servir.

1. **La contention a été mesurée SOUS UN SEUL UTILISATEUR.** Les 138 questions
   ont été posées en série, une à la fois. Un service qui répond à plusieurs
   personnes simultanément fait tourner l'embedder, le cross-encoder ET Ollama
   **en même temps** sur la même carte, ce que cette campagne ne reproduit pas.
   Le sens du résultat ne devrait pas s'inverser — les p95 s'améliorent
   massivement, ce qui est le contraire d'un signe de saturation — mais le
   chiffre de +40 ms, lui, est propre à une charge séquentielle.

2. **Le tiers du §5 tournait par intermittence.** Il était actif pendant le
   contrôle à 30 questions (dont le `generation_ms` est donc écarté) et absent ou
   faible pendant les 138. C'est la raison pour laquelle le `+40 ms` vient de la
   campagne longue et non du contrôle.

3. **Aucun des deux jeux ne note la réponse GÉNÉRÉE.** Ils mesurent le rappel,
   la précision du contexte, la complétude des citations et la latence — jamais
   la qualité de la réponse. L'absence de mouvement sur le rappel n'est donc pas
   une preuve d'absence d'effet sur la réponse ; c'est une réserve permanente de
   l'instrument, pas de ce lot.

**Ce que le résultat permet malgré tout d'affirmer** : sur cet usage et cette
charge, le GPU retire 817 ms des 7 298 d'une réponse et en rend 40 à la
génération. C'est le rapport prix/apport que le §P1 du registre demande, et il
est favorable d'un facteur vingt.

---

## 7. Ce qu'il faudrait pour aller plus loin

1. **une mesure sous charge concurrente** — plusieurs requêtes simultanées, qui
   est le régime du service à venir. C'est la seule réserve qui pourrait encore
   renverser la décision ;
2. **une mesure sur un poste où seul cet agent parle au service LLM** — ou une
   fenêtre où le projet `data-analyst-agent` ne tourne pas — pour resserrer
   l'intervalle sur `generation_ms` ;
3. **une reprise après le passage à vLLM**, annoncé par le propriétaire : il
   change le serveur qui partage la carte, donc il change la contention, donc ce
   chiffre de +40 ms devra être rejoué.
