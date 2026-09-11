# Le GPU sur les étages torch — ce qu'il rapporte, et ce qui n'a pas pu être mesuré

`mesuré` le **11 septembre 2026**, entre **14:25 et 14:30 UTC**, par le lot 11,
sur l'agent en service (image `f4d488b447a6`, `torch 2.14.0+cu130`, carte
**NVIDIA L4**, pilote 595.71.05 / CUDA 13.2).

---

## 1. Ce que cette campagne mesure, et pourquoi elle ne ressemble pas aux autres

**Elle ne passe pas par le LLM, et c'est une décision forcée par le poste.**

Le plan d'origine était de rejouer `make eval` (138 questions) et
`make eval-controle` (30 questions) sous les deux périphériques. La première a
été lancée à 12:54 UTC et **interrompue à 14:24 UTC après 82 questions sur 138**,
pour la raison mesurée au §5 : un autre projet du poste dispute le service
Ollama, et le temps par question est passé de **6 846 ms** (antécédent du
10 septembre) à **~55 s**. Deux campagnes complètes auraient coûté quatre heures
pour rendre un `generation_ms` dominé par un tiers.

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

## 6. Ce qui n'a PAS été mesuré, et qui décide pourtant

**LA CONTENTION DE CALCUL ENTRE TORCH ET OLLAMA SUR LA MÊME CARTE.** C'est le
risque que le propriétaire a nommé en distribuant ce lot, et **cette campagne ne
le tranche pas.**

Ce qu'on sait : la mémoire n'est pas le sujet (§4). Ce qu'on ne sait pas : si
faire calculer l'embedder et le cross-encoder sur la L4 ralentit la génération
d'Ollama, qui porte **67 %** du temps d'une réponse. La seule mesure qui le
dirait est une campagne complète comparée à un antécédent, et elle exige un poste
où Ollama n'est pas déjà disputé par un tiers.

**Ce que l'arithmétique permet quand même de poser**, et c'est `calculé`, pas
`mesuré` : sur la partition du 10 septembre, le GPU retire **650,7 ms** des
6 846 ms d'une réponse, soit **9,5 %**. Pour que l'opération soit neutre, il
faudrait que la contention ajoute autant à la génération, c'est-à-dire **+14 %**
sur `generation_ms`. *C'est le seuil à mesurer* — et il n'est pas
invraisemblable, ce qui est exactement pourquoi il faut le mesurer plutôt que de
le supposer dans un sens ou dans l'autre.

**C'est pour cela que `TORCH_DEVICE` reste à `cpu` par défaut.** Le gain sur
l'étage torch est net, reproduit et hors de portée du bruit ; le prix sur l'étage
dominant est inconnu. Le §P1 du registre tranche sur un rapport prix/apport
connu — ici le prix ne l'est pas encore.

---

## 7. Ce qu'il faudrait pour conclure

1. **un poste où seul cet agent parle à Ollama** — ou une fenêtre où le projet
   `data-analyst-agent` ne tourne pas ;
2. `make eval` sous `TORCH_DEVICE=cpu` puis sous `cuda`, comparés à
   `runs/2026-09-10-lecteur-neuf-reglage.json` ;
3. la lecture des **trois** colonnes, et pas d'une seule : `rerank_ms` et
   `dense_ms` (ce que le GPU rapporte), **`generation_ms`** (ce que la contention
   coûte), `total_ms` (ce que l'utilisateur ressent) ;
4. et la vérification que les métriques de rappel ne bougent pas — le lot 10 a
   mesuré que le périphérique ne change les scores qu'à **5,48 × 10⁻⁶ avec
   classement inchangé**, donc tout mouvement serait une trouvaille.

Coût estimé : **~40 min par campagne** sur un poste libre, contre 2 h 07 observées
sous contention.
