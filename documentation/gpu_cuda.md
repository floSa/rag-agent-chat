# Installer et activer CUDA pour l'agent

**Pour qui** : quelqu'un qui monte ce projet sur une machine neuve, qui veut
savoir si l'agent calcule sur le GPU, et qui n'a jamais vu ce chantier.

**Ce que ce document ne fait pas** : décider que le GPU vaut le coup sur ce
service. Cette question a une réponse mesurée, et elle est au §7 — lisez-la avant
d'allumer quoi que ce soit en production.

Chaque affirmation de ce document porte la commande qui la vérifie. Les chiffres
portent leur date et leur étiquette : `mesuré` (relevé ici, par la commande
indiquée), `cité` (relevé ailleurs, avec son site), `supposé` (ni l'un ni
l'autre — il n'y en a aucun ici).

---

## 1. Les trois conditions, et chacune suffit à éteindre le GPU

Ce service calcule sur le GPU **si et seulement si les trois sont vraies en même
temps**. Il n'y a aucune hiérarchie entre elles : chacune, seule, ramène tout sur
le CPU, et **aucune ne se signale**. Le service répond, les tests passent, les
réponses sont justes — simplement plus lentes.

| | la condition | où elle se règle | ce qui la lit |
|---|---|---|---|
| **(a)** | `torch` est un build **CUDA** dans l'image | `Dockerfile.agent`, `ARG TORCH_INDEX_URL` | `torch.version.cuda` |
| **(b)** | le conteneur a **accès à la carte** | `docker-compose.yml`, bloc `deploy.resources.reservations.devices` du service `agent-api`, **plus** le NVIDIA Container Toolkit installé sur l'hôte | `torch.cuda.is_available()` |
| **(c)** | le **réglage** nomme la carte | `TORCH_DEVICE` dans le `.env` (défaut : `cpu`) | `settings.torch_device` |

**(c) vaut `cpu` par défaut, et c'est délibéré.** Reconstruire l'image avec un
build CUDA et réserver la carte ne met **pas** ce service sur le GPU : ça le rend
seulement *possible*. Le motif est au §7, et il est chiffré.

Les trois sont publiées en continu par `GET /health`, champ `torch_device` :

```bash
curl -s http://localhost:8011/health | python3 -m json.tool
```

```
"torch_device": {
    "requested": "cpu",            <- condition (c)
    "torch_version": "2.14.0+cpu", <- condition (a), le suffixe
    "cuda_build": null,            <- condition (a), la version CUDA compilée
    "cuda_available": false,       <- condition (b)
    "embedding": null,             <- le modèle est-il POSÉ sur la carte
    "rerank": null
}
```

`embedding` et `rerank` valent `null` tant que le modèle concerné n'a pas été
chargé : la route de santé ne charge rien, et un `null` se lit « personne n'a
encore eu besoin de ce modèle ». Posez une question à l'agent, puis relisez.

---

## 2. Vérifier la condition (a) : le build de torch dans l'image

```bash
docker exec rag-agent-api python -c "import torch; print(torch.__version__, torch.version.cuda, torch.backends.cuda.is_built(), torch.cuda.is_available())"
```

| ce qui sort | ce que ça veut dire |
|---|---|
| `2.14.0+cpu None False False` | build **CPU**. Aucune réservation de GPU n'y changera rien : il faut **reconstruire l'image** |
| `2.14.0+cu130 13.0 True False` | build CUDA, mais **la carte n'est pas visible** → condition (b), §3 |
| `2.14.0+cu130 13.0 True True` | conditions (a) et (b) tenues. Reste (c), §4 |

`torch.backends.cuda.is_built()` est la forme canonique de la question ; le code
de ce dépôt lit `torch.version.cuda` à la place, qui dit la même chose **et en
plus quelle version** — le motif est écrit au site, dans `TorchDeviceHealth`
(`src/api/schemas.py`).

**Vérifier une image AVANT de la servir**, ce qui distingue une reconstruction
d'un pari :

```bash
docker run --rm --entrypoint sh rag-agent-chat-agent-api:latest -c 'python -c "import torch; print(torch.__version__, torch.version.cuda)"'
```

Sans carte attachée, `torch.cuda.is_available()` rendra `False` dans ce
`docker run` : c'est normal et attendu, il n'y a pas de `--gpus` ici. Ce que
cette commande vérifie est **le build**, pas l'accès.

---

## 3. Vérifier la condition (b) : le conteneur atteint la carte

### 3.1 Sur l'hôte

```bash
nvidia-smi
nvidia-ctk --version
docker info | grep -i runtime
```

`nvidia-smi` doit afficher la carte et, **en haut à droite, la version CUDA du
pilote** — c'est le chiffre du §5. `nvidia-ctk --version` doit répondre : c'est
le NVIDIA Container Toolkit, sans lequel Docker ne sait pas donner une carte à un
conteneur. `docker info` doit lister `nvidia` parmi les `Runtimes`.

Si `nvidia-ctk` n'existe pas, rien de ce qui suit ne marchera : installez le
toolkit (paquet `nvidia-container-toolkit` de NVIDIA), puis
`sudo nvidia-ctk runtime configure --runtime=docker && sudo systemctl restart docker`.
**Attention** : redémarrer le démon Docker redémarre les conteneurs ; sur une
machine qui sert, c'est une décision d'exploitation, pas un détail.

Relevé de ce poste, `mesuré` le **11 septembre 2026 à 12:23 UTC** par les trois
commandes ci-dessus :

| | valeur |
|---|---|
| pilote | **595.71.05** |
| CUDA du pilote | **13.2** |
| carte | **NVIDIA L4**, 23 034 Mio |
| NVIDIA Container Toolkit | **1.19.1** |
| runtime `nvidia` dans Docker | **présent** |

### 3.2 La réservation dans le compose

Elle vit dans `docker-compose.yml`, sur le **seul** service `agent-api` :

```yaml
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]
```

Elle ne vaut rien tant que le conteneur n'a pas été **recréé** : `docker compose
up -d` sur un conteneur déjà en place avec une réservation ajoutée le recrée,
mais vérifiez-le plutôt que de l'espérer.

### 3.3 Vérifier que la carte est bien ENTRÉE dans le conteneur

Trois lectures, de la plus extérieure à la plus intérieure :

```bash
docker inspect rag-agent-api --format '{{json .HostConfig.DeviceRequests}}'
docker exec rag-agent-api sh -c 'ls /dev/nvidia*'
docker exec rag-agent-api python -c "import torch; print(torch.cuda.is_available())"
```

- la première doit rendre autre chose que `null` — elle dit ce que **Docker a
  demandé** ;
- la deuxième doit lister des périphériques (`/dev/nvidia0`, `/dev/nvidiactl`…)
  — elle dit ce qui est **réellement entré**. Un `No such file or directory`
  avec une `DeviceRequests` non nulle désigne le toolkit de l'hôte ;
- la troisième dit que **torch** les voit. Elle peut rendre `False` alors que
  `/dev/nvidia*` existe : c'est alors la condition (a), ou une incompatibilité
  de version — §5.

---

## 4. Vérifier la condition (c) : le réglage

```bash
docker exec rag-agent-api python -c "from src.agent.settings import settings; print(settings.torch_device)"
```

Le réglage se change dans le `.env` du projet, sans reconstruire l'image :

```
TORCH_DEVICE=cuda
```

puis `docker compose up -d` (le conteneur est recréé pour prendre la nouvelle
variable ; `docker compose restart` **ne relit pas** le `.env`).

Valeurs acceptées : tout ce que torch accepte — `cpu`, `cuda`, `cuda:1`. La
valeur n'est **pas** validée au démarrage, délibérément : la liste des
périphériques que torch connaît dépend du build, et un service qui refuserait de
démarrer sur un réglage inconnu serait plus difficile à diagnostiquer qu'un
service debout qui publie son état. Le motif complet est au site du réglage,
`src/agent/settings.py`.

**Ce qui se passe si vous demandez `cuda` sans que (a) ou (b) soit tenue** :
`torch` lève au chargement du **premier modèle**, c'est-à-dire à la **première
recherche**, et non au démarrage. Le message est
`Torch not compiled with CUDA enabled` (condition (a) manquante) ou
`no CUDA-capable device is detected` / `Found no NVIDIA driver` (condition (b)).
`/health` reste à `200`, la recherche rend une erreur. **C'est pourquoi on lit
`/health` AVANT de changer ce réglage** : les trois champs y sont, et ils disent
lequel des deux cas vous attend.

---

## 5. Quelle roue de torch pour quel pilote

Les roues de PyTorch portent un suffixe de build : `+cpu`, `+cu126`, `+cu128`,
`+cu130`. Le nombre est la version du **runtime CUDA embarqué dans la roue** —
pas celle de votre pilote, et pas celle de votre carte.

**La règle** : un pilote NVIDIA sert les runtimes CUDA **antérieurs ou égaux** au
sien, jamais postérieurs. Un pilote qui annonce CUDA 13.2 sert donc `cu130`,
`cu129`, `cu128`, `cu126` ; il ne servirait pas un hypothétique `cu140`.

**Ce qui se passe si on se trompe** :

| l'erreur | le symptôme |
|---|---|
| roue trop **récente** pour le pilote | `torch.cuda.is_available()` rend `False`, ou `CUDA driver version is insufficient for CUDA runtime version` au premier calcul. Le conteneur démarre, `/health` répond, seules les recherches tombent |
| roue **CPU** installée par-dessus une roue CUDA (ou l'inverse) | `torch.__version__` et `torch.version.cuda` se contredisent. Un garde le voit : `test_le_suffixe_du_build_et_la_version_cuda_disent_la_meme_chose` |
| carte trop **ancienne** pour le build | `NVIDIA GeForce ... with CUDA capability sm_XX is not compatible with the current PyTorch installation`. CUDA 13 a retiré les architectures les plus anciennes ; la L4 de ce poste est `sm_89`, largement dans la fenêtre |

**Comment choisir, en pratique** : prenez le plus haut index que votre pilote
sert **et** qui publie la version de torch que vous voulez. Les index ne portent
pas tous les mêmes versions. `mesuré` le 11 septembre 2026, en cp312 / x86_64,
par :

```bash
curl -s https://download.pytorch.org/whl/cu130/torch/ | grep -o 'torch-[0-9][0-9.]*+[a-z0-9]*-cp312-cp312-manylinux[_0-9]*x86_64\.whl' | sed 's/torch-//;s/-cp312.*//' | sort -V -u | tail -3
```

| index | version de torch la plus haute |
|---|---|
| `cu126` | **2.14.0** |
| `cu128` | 2.11.0 |
| `cu129` | 2.13.0 |
| `cu130` | **2.14.0** |
| `cpu` | **2.14.0** |

Ce dépôt a retenu **`cu130`** : c'est le runtime le plus haut que le pilote 595
sert, et il publie `2.14.0`, **la version que l'image portait déjà en CPU**. Le
changement porte donc sur le build, pas sur la version de torch — un écart de
moins à expliquer si une campagne bouge.

Le choix se change sans éditer le `Dockerfile` :

```bash
docker build -f Dockerfile.agent --build-arg TORCH_INDEX_URL=https://download.pytorch.org/whl/cu126 -t rag-agent-chat-agent-api:latest .
```

---

## 6. Ce que ça coûte : la taille de l'image

`mesuré` le 11 septembre 2026, `docker images` :

| build | id | taille de l'image `rag-agent-chat-agent-api` |
|---|---|---|
| `+cpu` (étiquetée `2026-09-11-avant-gpu`) | `2f4f1aa93f55` | **2,92 Go** |
| `+cu130` (étiquetée `2026-09-11-gpu-cu130`) | `f4d488b447a6` | **10,5 Go** |
| | | **+7,58 Go, soit ×3,6** |

Ce coût était le motif écrit du choix CPU d'origine, et il n'a pas disparu : il
est simplement devenu le prix d'une mesure que le propriétaire a demandée.
Vérifiez la place disponible avant de reconstruire :

```bash
df -h /var/lib/docker
```

---

## 7. Ce que le GPU rapporte ici — et pourquoi le défaut reste `cpu`

**Le GPU de ce poste n'est pas libre.** Ollama y sert les LLM du projet, et il
porte l'essentiel du temps d'une réponse. Partition d'une réponse, `citée` du
relevé du pilote du 11 septembre 2026 :

| étage | p50 | où ça tourne |
|---|---|---|
| `generation` | **4 616 ms** (67 %) | GPU — Ollama |
| `translation` | 1 196 ms (17 %) | GPU — Ollama |
| `rerank` | 622 ms (9 %) | CPU — le cross-encoder |
| `dense` | 115 ms (1,7 %) | CPU — l'embedder |
| **total** | **6 846 ms** | |

Ce que `torch` fait sur CPU vaut donc **~737 ms sur 6 846, soit 11 %** : c'est le
**plafond** de ce que le GPU peut rapporter ici. Et le risque n'est pas
symétrique — mettre les deux modèles sur la même carte qu'Ollama les fait
**partager le calcul** avec l'étage qui porte 67 % du temps. La mémoire n'est pas
le sujet (4 904 Mio occupés sur 23 034) ; la **contention de calcul** l'est.

C'est pour ça que `TORCH_DEVICE` vaut `cpu` par défaut : **allumer le GPU sur ce
service est une décision qui se prend contre une mesure, pas contre une
intuition.** Le résultat de la campagne du 11 septembre 2026 est au rapport du
lot 11 et au §4.48 de `axes_amelioration.md`.

---

## 8. Le retour en arrière

Il ne demande **aucune édition de fichier**, et il est en deux temps selon ce
qu'on veut défaire.

**Éteindre le GPU sans rien reconstruire** — c'est le geste à connaître, il prend
quelques secondes :

```bash
# dans le .env du projet
TORCH_DEVICE=cpu
```
```bash
docker compose up -d agent-api
curl -s http://localhost:8011/health | python3 -m json.tool | grep -A6 torch_device
```

**Revenir à l'image CPU** — l'image d'avant est étiquetée, et c'est ce qui rend
la reconstruction réversible :

```bash
docker images | grep agent-api          # vérifier que l'étiquette existe
docker tag rag-agent-chat-agent-api:2026-09-11-avant-gpu rag-agent-chat-agent-api:latest
docker compose up -d --no-build agent-api
docker exec rag-agent-api python -c "import torch; print(torch.__version__)"
```

**Reconstruire une image CPU depuis les sources** :

```bash
docker build -f Dockerfile.agent --build-arg TORCH_INDEX_URL=https://download.pytorch.org/whl/cpu -t rag-agent-chat-agent-api:latest .
```

**Retirer la réservation** : commentez le bloc `deploy:` du service `agent-api`
dans `docker-compose.yml`, puis `docker compose up -d agent-api`. Vérifiez par
`docker inspect rag-agent-api --format '{{json .HostConfig.DeviceRequests}}'`,
qui doit rendre `null`.

---

## 9. Après un redémarrage : l'index lexical se reconstruit paresseusement

Ce n'est pas propre au GPU, mais ça mord à chaque fois qu'on recrée le conteneur,
donc c'est ici. Juste après un redémarrage, `/health` annonce
`"index_lexical": false` : l'index BM25 n'est pas encore construit, et la
recherche est **dense seule** — amputée, sans le dire. La **première** recherche
déclenche la reconstruction.

Ne mesurez donc **jamais** une campagne sur un service qui vient de démarrer sans
avoir chauffé. `scripts/evaluate.py` le fait pour vous et **refuse la campagne en
`rc=2`** si `/health` n'annonce toujours pas l'index après la chauffe. Ce refus
est un garde-fou : ne le contournez pas, servez-vous-en.

```bash
curl -s http://localhost:8011/health | python3 -c "import json,sys; print(json.load(sys.stdin)['services']['index_lexical'])"
```

---

## 10. Diagnostic : du symptôme à la condition

| ce que vous voyez | la condition en cause | la commande qui tranche |
|---|---|---|
| `/health` : `cuda_build: null` | **(a)** — l'image est en CPU | `docker exec rag-agent-api python -c "import torch; print(torch.version.cuda)"` |
| `cuda_build: "13.0"` mais `cuda_available: false` | **(b)** — la carte n'entre pas | `docker exec rag-agent-api sh -c 'ls /dev/nvidia*'` |
| `cuda_available: true` mais `embedding: "cpu"` | **(c)** — le réglage. **Ce n'est pas une panne** : c'est le défaut | `docker exec rag-agent-api python -c "from src.agent.settings import settings; print(settings.torch_device)"` |
| `embedding: null` après une requête | le modèle n'a pas été chargé : la recherche n'est pas allée jusque-là (voir les 503 de concordance) | `curl -s localhost:8011/health \| grep embedding_model` |
| une recherche rend 500, `/health` reste `200` | `TORCH_DEVICE` nomme un périphérique que le build ou la machine ne sert pas | `docker logs rag-agent-api --tail 50` |
| tout est vert, rien n'est plus rapide | la **contention** — §7 | `nvidia-smi` pendant une recherche |

---

## 11. Prouver que le GPU est ATTEINT, pas seulement présent

`/dev/nvidia*` et `cuda_available: true` disent que la carte est **là**. Ils ne
disent pas qu'on s'en sert. Trois preuves, et il en faut plus d'une :

1. **le champ publié** — `torch_device.embedding` et `.rerank` doivent nommer
   `cuda`, après qu'une question a été posée ;
2. **le journal du chargement** — deux lignes par modèle, celle qui dit le
   périphérique *demandé* et celle qui dit celui que torch a *posé* :
   ```bash
   docker logs rag-agent-api 2>&1 | grep -i "périphérique"
   ```
3. **la mémoire prise sur la carte**, qui est la seule preuve extérieure au
   programme :
   ```bash
   nvidia-smi --query-compute-apps=pid,process_name,used_memory --format=csv
   ```
   Un **second** processus doit y apparaître à côté de celui d'Ollama.

Un garde présent mais jamais atteint est la forme dominante des défauts trouvés
sur ce chantier — neuf fois. Ne vous contentez pas de la première preuve.
