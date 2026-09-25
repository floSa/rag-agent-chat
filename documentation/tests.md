# Les tests, et ce qu'ils ne disent pas

Trois niveaux, qui répondent à trois questions différentes. Aucun ne remplace
les autres, et le troisième est le seul à parler de **qualité**.

| Niveau | Commande | Question à laquelle il répond |
|---|---|---|
| Unitaire | `make test` | La logique est-elle correcte ? |
| Intégration | `make test-integration` | Le système tient-il debout avec les vrais stores ? |
| Campagne | `make eval` | Les réponses sont-elles bonnes ? |

## Unitaire — 1263 tests, aucune dépendance

> **Ce compte est `mesuré`, ET IL EST DÉSORMAIS GARDÉ.** C'était le §4.13 du
> registre, un angle mort connu : il a pris 25 tests de retard sans que le lot ni
> son audit le voient, puis il a été faux dans le commit même qui le corrigeait.
> Il se remesure ainsi, et les deux chiffres doivent concorder :
>
> ```bash
> pytest tests/unit/ --collect-only -q | awk -F': ' '/^tests\/unit\/.*: [0-9]+$/ {s+=$2} END {print s}'
> ```
>
> `mesuré` le 25 septembre 2026 à 07:47 UTC par LOT-39 : **1263** tests sur **61** fichiers,
> et les deux comptes de la recette — la somme par fichier et le total
> que `pytest` annonce — concordent.
>
> **CE COMPTE MONTE DE TRENTE-NEUF, ET `src/` N’EST PAS TOUCHÉ.**
> *(LOT-38 relevait **1224** sur **60** fichiers le 25 septembre à 03:53 UTC ; les **39** de plus
> sont **39** dans le fichier neuf `test_decomposition_traduite.py`, et rien
> d'autre. Ils gardent le banc qui mesure ce que rend une décomposition **avec**
> recherche translingue, là où le §4.78 comparait une variante qui ne traduit
> pas à une production qui traduit — et imputait au retrait de la traduction
> deux des trois questions perdues **sans le mesurer**.
>
> Le garde qui porte le plus est celui de la TRADUCTION : il ne relit pas le
> code de `translate_question`, **il le fait tourner**, sur les mêmes corps que
> le banc, et exige le même résultat sur sept formes — la traduction nominale,
> celle qui porte une explication à la ligne suivante, celle que le modèle
> entoure de guillemets, la vide, celle qui n'est que des espaces, celle qui
> recopie la question à la casse près, et celle qui dépasse trois fois sa
> longueur. Les trois dernières sont des **refus de la production**, qui
> retombe alors en recherche monolingue : un banc qui en oublierait un donnerait
> au moteur des requêtes que le service n'émet jamais. Comparer deux listes de
> règles écrites à la main aurait prouvé qu'elles se ressemblent ; les faire
> tourner côte à côte prouve qu'elles décident pareil.
>
> Le REPLI est gardé dans ses DEUX formes, et elles ne sont pas
> interchangeables : les variantes du §4.78 retombent sur la requête unique
> **sans** traduction, les variantes traduites sur **la production exacte** —
> un décomposeur qui traduit ne perd pas la recherche translingue sur les
> questions qu'il renonce à décomposer, et les 69 questions à besoin unique du
> jeu de réglage porteraient sinon une perte que l'implémentation n'aurait pas.
> La PONDÉRATION est gardée contre un poids écrit en dur : sur ce poste
> `TRANSLATION_WEIGHT` vaut **1,0**, c'est-à-dire l'égalité, et un banc qui
> coderait 1,0 rendrait aujourd'hui exactement les mêmes chiffres qu'un banc qui
> lit le réglage — le témoin déplace donc le réglage à 0,3 et exige que l'ORDRE
> du RRF change.
>
> Les QUATRE ÉTAGES — `arrive`, `perdu_au_reranking`, `perdu_a_la_fusion`,
> `jamais_recupere` — sont gardés un par un ET dans leur ORDRE, qui est ce qui
> les rend exclusifs et fait que les comptes **somment** ; une question est
> classée par son ancrage le plus **amont**, et le témoin oppose les deux
> lectures sur la même question, réparer l'aval ne sauvant pas une question dont
> l'autre ancrage n'est dans aucune liste. L'ÉCART À LA BORNE est gardé comme
> une **différence d'ensembles** : le témoin fait ACCORDER les comptes — deux
> ancrages placés de part et d'autre — et DIVERGER les ensembles, cas sur lequel
> une soustraction rendrait « écart nul ».
>
> Le CONTRÔLE POSITIF a **trois** termes et chacun est muté séparément : les
> **douze** couples du §4.78 (quatre variantes × trois jeux, ancrages et
> questions), les rangs de ses **quatre** variantes **un à un** — pas seulement
> ceux de la production —, et les **120** rangs du §4.77. Un quatrième témoin
> exige qu'un contrôle **sans aucun terme applicable** n'accorde pas, `all([])`
> valant `True`. Et le contrôle du contrôle existe : un garde qui refuserait
> TOUT serait vert sur les quatre. Les deux caches neufs sont exigés et jamais
> fabriqués, leur absence est un refus, un cache partiel **nomme** ce qui
> manque, et chacun porte le nom de son jeu. Les mesures sont au §4.79 du
> registre.)*
>
> **LE RELEVÉ ANTÉRIEUR.**
> *(LOT-37 relevait **1193** sur **59** fichiers le 24 septembre à 21:30 UTC ; les **31** de plus
> sont **31** dans le fichier neuf `test_fusion_des_sous_questions.py`, et rien
> d'autre. Ils gardent le banc qui mesure ce que rend une VRAIE fusion des
> sous-requêtes, là où le §4.77 n'avait qu'un oracle d'affectation : que la
> règle du « rien à décomposer » nomme ses **quatre** natures — `decomposee`,
> `vide`, `une_seule`, `quasi_identique` — et qu'aucune ne soit fondue dans sa
> voisine, une panne du producteur ne se lisant pas comme une question simple ;
> que le seuil de quasi-identité soit exigé de **toutes** les sous-questions et
> non d'une seule ; que la fusion fasse **remonter** le candidat que deux
> sous-questions portent au-dessus de celui qu'une seule met en tête — un témoin
> sur lequel une simple concaténation est rouge ; qu'elle reste bornée au `top_k`
> de production, sans quoi le gain mêlerait la décomposition à un élargissement
> de profondeur ; que le reranking par sous-question garde le **maximum** et non
> la moyenne, un témoin opposant le passage précis sur un besoin au passage tiède
> sur les deux ; que le seuil du haut accepte **10** et refuse **11** ; qu'une
> question sans ancrage mesurable ne soit **pas** déclarée complète, `all({})`
> étant vrai ; que la non-régression publie les questions perdues et gagnées par
> leurs **identifiants** et non un solde net, le témoin étant construit pour
> qu'un solde nul cache deux pertes ; et que le contrôle positif soit une
> **intersection** — le témoin qui compte le plus fait ACCORDER les deux comptes
> du §4.77 et DIVERGER un rang, cas sur lequel un contrôle par comptes seuls est
> vert. Le REPLI est gardé lui aussi, et il est la moitié de la
> non-régression : quand il n'y a rien à décomposer, les variantes recopient
> la requête unique **sans** traduction — la base appariée — et **pas** celle
> avec, sans quoi elles hériteraient d'un gain translingue que le §4.77
> mesure à deux signes, et sans relancer ni la récupération ni le reranking,
> ce qu'un compteur de paires assertit. Le prompt de décomposition est gardé
> lui aussi : la question en **tête**,
> pour que le cache de préfixe de `vllm-central` ne serve pas une latence, et
> **aucune** mention du nombre de besoins, que l'oracle du §4.77 affirmait et
> qu'un décomposeur réel ne connaît pas. Les mesures sont au §4.78 du registre.)*
>
> **LE RELEVÉ ANTÉRIEUR.**
> *(LOT-36 relevait **1160** sur **58** fichiers le 24 septembre à 19:20 UTC ; les **33** de plus
> sont **33** dans le fichier neuf `test_plafond_de_recuperation.py`, et rien
> d'autre. Ils gardent le banc qui cherche POURQUOI 67 ancrages sur 120
> n'atteignent pas le top-10 du reranker : que **chacune** des huit causes ait
> un témoin que le classeur sait rendre — sans quoi une cause comptée à `0` ne
> dirait pas si elle est absente ou si le détecteur est aveugle —, que l'arbre
> soit EXCLUSIF dans l'ordre où il est écrit, que « dans le haut du classement »
> reste **le top-10 aux trois profondeurs** et ne devienne pas « rendu par la
> liste » quand `RERANK_TOP_K` vaut 1000 — la faute a été commise et ce test
> l'attrape —, que la ligne « non expliqué » existe et attrape l'oracle qu'on
> n'a pas joué, que la requête oracle soit la `preuve` et **pas** le titre de
> section, qui vient du graphe et non du chunk, que l'affectation des
> sous-questions retienne la meilleure des deux permutations **et** départage à
> égalité, que deux comptes de chunks différents ou un service rouge soient un
> **refus** et non une note, et que le contrôle positif du §4.76 refuse une
> autre **profondeur** avant de comparer trois comptes qui porteraient alors le
> même nom et un autre sens. Les deux derniers relisent les bilans versionnés
> de `runs/`, **sans `skipif`** : un garde qui s'efface quand son fichier manque
> ne garde rien. Les mesures sont au §4.77 du registre.)*
>
> **LE RELEVÉ ENCORE ANTÉRIEUR.**
> *(LOT-35 relevait **1128** sur **57** fichiers le 24 septembre à 16:35 UTC ; les **32** de plus
> sont **32** dans le fichier neuf `test_jeu_ancrages_disperses.py`, et
> rien d'autre. Ils gardent le jeu à ancrages multiples et dispersés et le banc
> qui le mesure : que chaque question porte au moins **deux** ancrages, que les
> deux vivent dans des `section_id` **différents** — ceux que le GRAPHE rend, pas
> le `reference_id` du chunk —, que la limite de la méthode voyage dans le
> fichier, que les jetons de moins de trois caractères soient écartés de la
> mesure de présence du TEXTE — sans quoi elle serait toujours vraie —, que
> l'histogramme des rangs compte l'`absent` à part du lointain, que la
> condition de reconstruction tienne ses **quatre** directions — contrôle positif
> compris : une reconstruction qui ne rend RIEN satisfait la disjonction —, et
> qu'une question ne soit comptée réussie que si **TOUS** ses ancrages arrivent,
> `all` et jamais `any`, sur cinq états écrits et les deux natures de présence,
> et enfin que l'en-tête du jeu — sa méthode et sa limite — soit celui que son
> producteur écrit, deux sites ne pouvant pas diverger sans rien dire.
> Les mesures sont au §4.76 du registre.)*
>
> **LE RELEVÉ ANTÉRIEUR, ET IL MONTAIT DE DEUX SANS QU'AUCUN TEST NE SOIT RETIRÉ NI AUCUN FICHIER AJOUTÉ.**
> *(LOT-34 relevait **1126** sur **57** fichiers le 24 septembre à 13:05 UTC ; les **2** de plus
> tiennent dans deux scènes ajoutées à `test_capture_usage.py`. La première
> reproduit par retard INJECTÉ, déclenché par un ÉVÉNEMENT, la disparition du
> `usage.sqlite-wal` entre l'`exists()` et le `stat()` de `src/agent/usage.py` —
> /health publiait alors un actif de capture VIDE pendant un tick, et `failures`
> montait définitivement. La seconde tient la BORNE du rattrapage : une annexe
> illisible reste une panne qui se compte. Le constat et les mesures sont au
> §4.75 du registre.)*
>
> **UN GARDE DE CE FICHIER LISAIT LE POSTE ET NON LE CODE, et ce lot l'a fait
> rougir sans toucher au code.** `test_le_defaut_du_reglage_est_celui_que_la_campagne_a_tranche`
> lit `Settings()` neuve — mais `pydantic-settings` fait de l'environnement une
> source PRIORITAIRE sur le `.env`, et un lancement qui pose `TORCH_DEVICE=cpu`
> le faisait accuser un défaut qui n'avait pas bougé. La variable est désormais
> retirée pour la durée de la scène. Éprouvé aux deux bouts : vert avec et sans
> la variable posée, rouge quand le défaut du code passe à `cpu`.
>
> **LE RELEVÉ ANTÉRIEUR, ET IL MONTAIT DE CINQ.**
> *(à 16:18 UTC le 22 septembre, LOT-29 relevait **1104** sur **54** fichiers à 15:19 UTC ; les **5** de plus
> sont un fichier neuf et rien d'autre — `src/` n'a pas été touché par ce lot :
> les **5** dans le fichier neuf `test_fenetre_heritee.py`, qui garde
> l'invariant que le §4.63 du registre laissait ouvert — **le verdict de onze
> scènes ne dépend pas de `LLM_NUM_CTX`**. Il les relance sous trois fenêtres,
> 8192, 16384 et 32768, dans de vrais sous-processus : `settings` est construit
> à l'import, et `pydantic-settings` fait de l'environnement une source de
> priorité supérieure au fichier `.env`, de sorte que ce garde reste mordant
> dans le clone principal, seul arbre à en porter un. Il exige le même `rc` ET
> le même compte, ce compte étant le nombre de scènes gardées et non un chiffre
> écrit — un identifiant périmé fait donc rougir au lieu de rétrécir le
> périmètre en silence. Les quatre autres tiennent ce que ce garde suppose :
> aucune des trois valeurs posées par `fenetre_du_prompt.py` n'est un défaut
> déclaré de `Settings`, et chacune est encore un champ de `Settings`.)*
>
> **CE COMPTE MONTAIT DE VINGT AU RELEVÉ PRÉCÉDENT, ET AUCUN TEST N'AVAIT ÉTÉ RETIRÉ.**
> *(LOT-28 relevait **1084** sur **52** fichiers le 18 septembre à 15:28 UTC ; les **20** de plus
> sont deux fichiers neufs et rien d'autre — `src/` n'a pas été touché par ce
> lot. **9** dans le fichier neuf `test_contrat_champs_externes.py`, qui relève
> par AST les sept lectures du nom de champ média rendu par le graphe et par
> ChromaDB et les confronte à un contrat déclaré en un seul endroit ; les **11**
> restants sont portés par `test_bascule_du_nom_de_champ_media.py`, second
> fichier neuf, qui exerce le vrai code sur un producteur ayant renommé le champ
> et cloue la conséquence — aucune image, aucune exception, aucun journal. **Deux
> des neuf sont nés d'une mutation SURVIVANTE** — le contrôle positif du releveur
> ne portait aucun témoin de la nature `subscript`, et un site écrit
> `meta["minio_url"]` passait alors inaperçu. **Le
> garde de cette note ne sait vérifier par collecte que le PREMIER** — il refuse
> deux mentions de la forme « **N** dans le fichier neuf `x` » pour ne pas
> arbitrer en silence — donc la part de 11 est annoncée ici sans être gardée ;
> c'est une borne du garde, écrite plutôt que tue, et le total de 1102 la
> majore.)*
>
> **UN RELEVÉ PRÉCÉDENT, QUAND LE COMPTE A BAISSÉ POUR LA PREMIÈRE FOIS.** *(REPAR-26 relevait **1089** sur
> **51** fichiers le 16 septembre à 20:37 UTC ; les **5** de moins sont le retrait
> du support d'un moteur, et il n'y a pas d'autre cause — le témoin a été
> recollecté sur `main` dans un arbre à part pour l'établir. **Le solde est NET**,
> et le détail par fichier le dit. Ce qui PART : **−12** dans
> `test_champs_du_dialecte.py`, **−6** dans `test_lecteur_de_flux.py`, **−4** dans
> `test_dialecte_llm.py`, **−1** dans `test_jeux_de_questions.py`, **−1** dans
> `test_moteur_llm.py` — vingt-quatre scènes, chacune nommée dans le rapport du
> lot. Ce qui ARRIVE : **13** dans le fichier neuf `test_moteur_unique.py`, qui
> porte le garde du nom — **dont une scène née d'une mutation SURVIVANTE**, le
> contrôle qui confronte le motif du garde au nom tel que le dépôt l'écrit ; **+4** dans `test_absorptions.py`, d'un paramétrage qui
> ne discriminait plus — ses quatre corps mal formés étaient écrits autour d'une
> clé que le lecteur ne lit plus, donc les quatre chemins qu'ils prétendaient
> éprouver se réduisaient à un seul ; **+2** dans `test_coherence_depot.py`, qui
> éprouvent la lecture d'une BAISSE par le garde de cette note même — il ne savait
> lire qu'une hausse, et il se serait tu le jour où le chiffre bouge le plus.)*
>
> **CE QUI PART N'EST PAS CE QUI EST SUPPRIMÉ** : le solde est net. Trente scènes
> sont arrivées, dont trois **contrôles négatifs** du retrait — la forme de
> l'ancien moteur ne cède plus de texte, n'accumule plus d'appel d'outil, et aucun
> réglage ne nomme plus un moteur —, sans lesquelles sa lecture pourrait revenir
> sans que rien ne le dise. Ce qui part vraiment : les scènes qui figeaient la
> charge de l'autre dialecte « à l'octet près », celles qui lisaient ses captures
> NDJSON, celle du `Literal` d'un réglage qui n'existe plus, et le paramétrage
> « × deux dialectes », qui n'a plus qu'une valeur.
>
> **DEUX GARDES SONT TRANSPOSÉS PLUTÔT QUE RETIRÉS**, et c'est ce qui évite que ce
> lot désarme le suivant. La TABLE de `test_champs_du_dialecte.py` tenait deux
> colonnes dont le garde central exigeait qu'elles **diffèrent** ; la colonne
> disparaît, la cause reste, et chaque valeur attendue doit désormais différer du
> **défaut du code**. Et les scènes qui exerçaient leur discrimination en assertant
> « les deux versants d'un coup » **posent** maintenant un hôte et un modèle
> d'essai, distincts des défauts : une URL ou un nom écrit en dur y rougit
> toujours.
>
> *(REPAR-23 relevait **1005** sur
> **49** fichiers à 12:46 UTC ; les **30** de plus étaient le fichier
> `test_dialecte_llm.py`, qui tenait alors l'interrupteur du moteur — la charge
> inchangée à l'octet, la bascule, le retour arrière, les deux lectures
> non-flux, et les trois postes d'appel sur leur URL. **QUATRE de ces 30 scènes
> sont nées d'une mutation SURVIVANTE** : l'URL du poste de FLUX n'était exercée
> par rien — alors que c'est elle qui sert chaque réponse de l'agent —, et DEUX
> champs n'étaient mesurés que dans l'état où leur valeur par défaut les rend
> indiscernables d'une constante : le réglage de raisonnement, et le modèle que
> `/health` publie.)* *(LOT-22 avait relevé **999** sur les
> mêmes 49 fichiers à 09:14 UTC ; les **six** de plus ferment deux non bloquantes
> de l'audit du lot 22. **Trois** dans `test_identite_du_code.py` (NB-1) : la
> scène du sha illisible est paramétrée sur les **trois bornes** du motif du
> module — longueur, ancrage, casse —, chacune éprouvée par la sortie d'une
> commande `git` qu'un lecteur pressé mettrait dans la cible `image` en croyant
> l'améliorer. Les trois mutations correspondantes SURVIVAIENT à la suite
> entière, et chaque borne a son propre texte séparateur : elle tue une mutation
> et une seule. **Trois** dans `test_coherence_depot.py` (NB-2) : un chemin de
> document cité par `src/` doit désigner un fichier qui existe — le verdict avec
> sa preuve d'atteinte, son contrôle positif dans les deux sens, et l'assertion
> que le domaine balayé exclut la source du garde, pour qu'une sonde ne
> s'attrape pas elle-même.)*
>
> *(REPAR-21 avait relevé **954** sur
> **48** fichiers à 07:58 UTC ; les **quarante-cinq** de plus sont ceux du garde
> de déploiement, tous dans le fichier neuf `test_identite_du_code.py` : **treize**
> sur le contrat qui refuse qu'une image anonyme passe pour identifiée — les deux
> sens de chacun de ses trois invariants, plus les sept formes qui ressemblent à
> un sha sans en être un —, **dix** sur les trois positions de la
> lecture et les trois chemins distincts vers l'anonymat, **trois** sur la
> publication dans le corps de `/health`, **seize** sur le gabarit qui fait entrer
> l'identité dans l'image — les trois arguments du compose, leur interpolation,
> les trois `ARG` sans valeur par défaut, les trois `ENV`, les trois `LABEL` et
> la cible qui relève le sha ET la propreté de l'arbre —, et **trois** sur le
> lecteur qui lit le compose COMME DOCKER LE LIT, override compris. Aucun test
> n'a été ajouté par LOT-22 ni par REPAR-23 sans qu'une mutation l'ait fait
> rougir d'abord.)*
> *(LOT-20 avait relevé **937** sur les
> mêmes 48 fichiers à 04:45 UTC ; les **dix-sept** de plus sont les gardes de
> REPAR-21, qui ferme les huit trouvailles non bloquantes de l'audit du lot 20 —
> seize dans `test_lecteur_de_flux.py` (quatre sur les décomptes qu'une branche
> n'efface plus, dont celle qui TRANCHE la règle de conflit sur un `usage`
> cumulatif relevé le 16/09 à 07:49 UTC ; trois qui nomment les lignes
> DÉFENSIVES du lecteur ; cinq qui tiennent la borne du rideau en sentinelles
> des DEUX côtés, dont le cas tranché de la réponse qui cite la syntaxe ; une
> sur la priorité prose/sentinelles dans le même texte ; deux sur l'erreur qui
> arrive APRÈS des tokens ; une sur la ligne émise après `done: true` ; une sur
> l'événement qui porte du texte ET un appel, forme CONSTRUITE et déclarée comme
> telle), plus le contrôle positif de la seconde marque du garde du site unique
> dans `test_coherence_depot.py`, dont le balayage cherche désormais AUSSI le
> motif en sentinelles. Aucun test n'a été ajouté par REPAR-21 sans qu'une
> mutation l'ait fait rougir d'abord.)* *(LOT-19 avait relevé **910** sur **47**
> fichiers le 15/09 à 23:00 UTC ; les **vingt-sept** de plus sont ceux du lecteur
> de flux — tous dans le fichier neuf `test_lecteur_de_flux.py`, qui éprouve les
> deux dialectes sur des lignes capturées sur les deux moteurs du poste, la
> fragmentation de l'appel d'outil, le rappel qui ne part qu'une fois, et les
> trois scènes nées des trois mutations qui avaient d'abord survécu. Avant lui,
> REPAR-20 avait relevé **892** sur **46**
> fichiers à 20:57 UTC ; les **dix-huit** de plus sont ceux du second rideau — seize
> dans le fichier neuf `test_repli_dans_la_prose.py`, qui éprouve les quatre formes
> d'appel mesurées sur les deux moteurs et les six proses ordinaires qui ne
> doivent rien déclencher, plus les deux gardes du site unique du motif dans
> `test_coherence_depot.py`. Avant lui, REPAR-19 avait relevé **870** sur les
> mêmes 46 fichiers à 19:01 UTC ; les **vingt-deux** de plus sont les gardes de
> REPAR-20, qui ferme les trois non bloquantes de l'audit de REPAR-19 — onze sur
> le refus des modèles DÉRIVÉS du nôtre (quatre familles de dérivation, le
> catalogue qui sert le dérivé ET le nôtre, le témoin de l'`id` réellement servi,
> le témoin inerte, les deux bornes qui restent et qui sont mesurées, la
> non-mémorisation du dérivé), trois sur le sens de la
> relation de noms rendu exact et son coût COMPTÉ en requêtes plutôt que décrit,
> huit sur le lecteur du compose qui lit désormais `docker-compose.override.yml`
> comme docker le fusionne. Aucun test n'a été ajouté par REPAR-20 sans qu'une
> mutation l'ait fait rougir d'abord.)* *(REPAR-18 avait relevé **852** sur les
> mêmes 46 fichiers à 17:39 UTC ; les **dix-huit** de plus sont les gardes de
> REPAR-19, qui ferme les trois non bloquantes et les quatre réserves de l'audit
> de REPAR-18 — cinq sur la confrontation de l'`id` servi par vLLM au modèle que
> nous demandons, trois sur la fenêtre servie dans la signature (dont celui qui
> tient les DEUX moitiés du critère ensemble), sept sur le garde du budget qui
> lit désormais la valeur du bon service (dont la contre-épreuve qui reproduit
> ses deux faux verts et le contrôle positif sur le vrai fichier), trois sur le
> signalement du régime de re-sondage. Aucun test n'a été ajouté par REPAR-19
> sans qu'une mutation l'ait fait rougir d'abord.)* *(LOT-17 avait relevé **841** sur les
> mêmes 46 fichiers à 15:44 UTC ; les **onze** de plus sont les gardes de
> REPAR-18 — quatre sur la mémorisation d'un relevé PARTIEL de moteur, trois sur
> ce que la sonde ne relèvera jamais côté vLLM, deux sur l'horodatage du relevé,
> un qui tient cet horodatage HORS de la signature, un sur le budget de durée de
> la sonde entre deux battements du healthcheck. Aucun test n'a été ajouté par
> REPAR-18 sans qu'une mutation l'ait fait rougir.)* *(LOT-12 avait relevé **793** sur les
> mêmes 45 fichiers à 09:37 UTC ; les cinq de plus sont les gardes de REPAR-13 —
> deux sur le chargement des modèles, deux sur le réservoir de fils des sondes,
> un témoin sur `services_unknown`.)*
>
> **Les vingt-deux de plus** viennent du lot 12, et ils tiennent trois
> propriétés qui n'existaient pas. Les deux premières : **`/health` cesse de dire `ok` sur un service qui ne sert
> rien** — un périphérique demandé que torch ne sert pas dégrade le statut, dans
> les deux directions, contrôle positif et témoin de la concordance compris —
> et **une campagne consigne le périphérique sur lequel elle a tourné**, la
> comparaison appariée signalant une bascule sans jamais la refuser. Huit tests
> d'autres fichiers ont dû **épingler** le périphérique : ils assertaient un
> service `ok` sans rien dire de la carte, et mesuraient donc leur propriété sur
> un service qu'ils croyaient sain.
>
> **La troisième borne ce que cet agent prend sur la carte**, et elle existe pour
> un lecteur qui n'est pas dans ce dépôt : le voisin de carte, qui dimensionne
> son `--gpu-memory-utilization` **avant** de lancer vLLM. Un sémaphore réglable
> plafonne les deux étages torch — éprouvé dans les **deux** directions, gratuit
> sous la borne et bloquant au-dessus, et **câblé aux deux étages par leur vrai
> chemin d'appel** — et `/health` publie le cliquet de mémoire réservée, `null`
> tant que rien n'est chargé plutôt que `0.0`, qui se lirait « cet agent ne prend
> rien ».
>
> **Les quinze d'avant** tiennent le
> périphérique de torch, rendu explicite par le lot 11
> (`tests/unit/test_peripherique_torch.py`) : le défaut `cpu` qui préserve le
> service, l'alias qui rend le réglage utilisable sans reconstruire l'image, les
> **deux positions** — `cpu` et `cuda` — vérifiées sur les **deux**
> constructeurs, le journal des deux chargements, l'état publié par `/health`
> qui distingue « la carte est là » de « la carte SERT », et un témoin inerte
> dans les deux positions. Le garde du câblage de `/health` a d'abord été écrit
> **creux** — la mutation qui remplace la sonde par son repli laissait quinze
> verts — et c'est le lot qui l'a trouvé par sa propre table de mutations.
>
> Les dix-sept précédents gardent l'armement de
> `commit-msg` : le MESSAGE d'un commit n'était lu par aucun des trois types
> armés jusque-là — tous portent le contrôle d'**identité**, qui lit
> `git var GIT_AUTHOR_IDENT` et jamais le message — et un trailer d'attribution
> n'était donc attrapé qu'à la **poussée**, au prix d'une réécriture de commits.
> Ils couvrent les deux directions (la forme refusée, le récit accepté), les deux
> formes de **fusion** — c'est là que le mandat prescrit `--no-ff` — et le fait
> que le motif n'a qu'un **seul site** au runtime, prouvé par mutation du
> fragment posé. Les cinq derniers ferment la réserve « borné par écrit, pas
> gardé » du `timeout` de `pre-push` : le repli fail-closed n'était atteint
> jusque-là que par un distant qui **échoue vite**, jamais par un distant qui
> **pend** — deux chemins de code différents, et seul le second passe par la
> borne. Les trois derniers gardent **la lecture de cette note-ci** : elle se
> faisait par un motif non ancré, qui lisait donc la PREMIÈRE phrase de cette
> forme dans la page — et la page en porte plusieurs, dont le récit du §4.13.
> L'ancrage porte désormais sur le mot `mesuré`, **sur la même ligne**, et
> l'unicité est exigée. Le quatrième vient de la **table des mutations** : relâcher
> `== 1` en `>= 1` restait VERT, la seule scène qui éprouvait la clause rendant
> **zéro** note et non plusieurs.
> Relevés antérieurs : **730** sur **44** le 11 septembre 2026 à 07:32 UTC
> (LOT-9), **720** sur **44** le 9 septembre 2026 à 15:04 UTC (LOT-4 ;
> le fichier neuf est `tests/unit/test_section_voisine.py`, qui garde la
> définition (C) de « section voisine », §4.6), **718** sur **44** le même jour à
> 14:30 UTC (LOT-4, avant son garde de coût), **697** sur **43** le 9 septembre
> 2026 (REPAR-8),
> **682** sur **43** le même jour (LOT-7),
> **668** sur **43** le même jour (LOT-7, ses
> fermetures (a) et (b)), **647** sur **42** le même jour (REPAR-7),
> **643** sur **42** le 8 septembre 2026 (lot 6), **629**
> sur **41** le même jour (lot dette), **603** sur **40** le même jour (lot 5),
> **562** sur **38** le 7 septembre 2026.
>
> **Attention au piège de la commande.** `addopts = -q` est déjà dans
> `pyproject.toml` : un `-q` de plus vaut `-qq`, qui SUPPRIME la ligne de total.
> La somme par fichier ci-dessus, elle, reste imprimée.
>
> **CE CHIFFRE A ÉTÉ FAUX DANS LE COMMIT QUI LE CORRIGEAIT, et c'est la
> démonstration du §4.13.** Cette note annonçait **520** tests sur **36**
> fichiers, `mesuré` le 4 septembre ; l'état réel du dépôt à ce commit
> (`c5c38d5`) était de **539** tests sur **37** fichiers — 19 tests et un
> fichier de retard, écrits dans le commit même qui prétendait rattraper le
> retard. Le lot a corrigé le chiffre, l'audit ne l'a pas revu, et **rien ne
> pouvait le voir** : c'est exactement la trouvaille du §4.13, et elle vaut
> mieux que le chiffre.
>
> **LE GARDE EST FERMÉ, et il l'est parce qu'une troisième correction à la main
> aurait été le geste que le §4.13 sanctionne.** Cette page est confrontée à la
> collecte de `pytest` par
> `tests/unit/test_coherence_depot.py::test_le_compte_de_tests_annonce_est_celui_que_pytest_collecte`,
> qui relève le titre ET la note séparément — deux sites qui s'accordent entre
> eux peuvent être faux ensemble, et c'est exactement ce qui est arrivé. La
> mesure passe par `pytest` et non par un comptage des `def test_*` : `mesuré`,
> l'AST en rend **532** là où `pytest` en collecte **562**, huit `parametrize` en
> dépliant trente de plus. **Ce sont deux grandeurs différentes**, et ce chantier
> en a déjà payé deux confusions du même genre.

Tout est simulé : ni ChromaDB, ni NebulaGraph, ni LLM. La suite tourne en
quelques secondes sur une machine nue, et c'est ce qui tourne en intégration
continue.

Les fichiers les plus fournis disent où sont les pièges du projet :

| Fichier | Ce qu'il protège |
|---|---|
| `test_lexical.py` | Tokenisation et fusion RRF — la fusion se fait sur les **rangs**, jamais sur les scores, qui ne sont pas comparables entre moteurs. |
| `test_context_assembly.py` | Échappement des VIDs, fenêtrage, assemblage du markdown soumis au LLM. **Ce que ses cinq tests de fenêtre ne voient pas** : ils appellent `_window_around` sur une liste qu'ils fabriquent eux-mêmes, et sans clé `seq`. Une réécriture qui pousse la fenêtre dans la requête nGQL laisse cette fonction intacte et la sort du chemin — `mesuré` le 3 septembre 2026, les 486 tests d'alors restaient **tous verts** sous cette réécriture. C'est `test_lecture_sequence.py` qui garde la composition. |
| `test_lecture_sequence.py` | Les **trois réserves de lecture de `sequence`** — elle repart à 0 par document, elle n'est pas contiguë sous un parent, et l'écart entre deux enfants peut être grand. La propriété gardée n'est pas dans `_window_around` mais dans la **composition** « chercher tous les enfants sans filtre, puis découper par position » : les tests pilotent donc `reconstruct_section`, avec un bouchon posé à la frontière nGQL (`_execute`). Le graphe factice **honore les clauses `WHERE`** des requêtes qu'il reçoit — sans quoi un code qui filtre dans la requête recevrait quand même toutes les lignes, et les gardes seraient verts pour rien ; deux tests gardent cette fidélité du montage lui-même. **Onze** mutations distinctes le font rougir (`mesuré` le 4 septembre 2026 ; le tableau est au §« Ce que ces trois réserves interdisent » de [`stores.md`](stores.md), site canonique), dont l'encadrement `sequence ∈ [s−k, s+k]` — qui amputerait **7,5 %** des ancres, chiffre dont le site canonique est [`stores.md`](stores.md) — et, depuis la réparation de ce fichier, le simple retrait de son `ORDER BY` : le graphe factice triait ses enfants à l'insertion, donc il fabriquait l'ordonnancement que la composition doit éprouver, et ce retrait passait en `rc=0`, 496 passés, zéro rouge. Le bouchon rend désormais ses enfants dans un ordre **non trié**, et une fixture à en-têtes **imbriqués** couvre le cas des 583 en-têtes sur 746 qu'aucune fixture du dépôt ne construisait. Il est enfin **fail-closed** sur les clauses qu'il ne sait pas évaluer : il LÈVE au lieu de rendre toutes les lignes, parce que trois écritures d'un même encadrement — `IN` sur une liste, forme arithmétique, alias de la liste `YIELD` — passaient en `rc=0`, zéro rouge, alors que NebulaGraph les sert avec la même perte que l'écriture classique. La borne de ce qu'il évalue est **gardée par un test** et non plus seulement affirmée. Les tests de frontière portent un épinglage d'anti-vacuité : ils prouvent que le montage POURRAIT franchir la frontière du document avant d'exiger qu'il ne la franchisse pas. |
| `test_installation_des_garde_fous.py` | La cible `make install` et le garde-fou d'identité Git qu'elle arme — **le plus gros fichier de tests du dépôt en nombre d'octets** — de 21 octets, et il n'est que deuxième en lignes et cinquième en nombre de tests —, et il manquait à cette table (§4.13). Deux familles : `TestLaCibleInstallArmeVraiment`, parce que git n'exécute jamais ce qui arrive avec un clone et qu'un garde-fou qui repose sur la mémoire du suivant n'en est pas un ; et `TestLaCibleInstallNeDesarmeRien`, qui interdit que la cible arme les hooks en retirant `ruff`, `mypy` ou `pytest` de l'environnement — ce que `uv sync` faisait, en `rc=0` et sans un seul rouge. |
| `test_affichage_sources.py` | Numérotation des citations et couleurs de pertinence côté frontend. |
| `test_postprocess.py` | Extraction des `[src:…]` — y compris les crochets à identifiants multiples, qui avaient fait perdre 27 citations sur 30. |
| `test_securite.py` | Traversée de chemin, échappement nGQL, comparaison de clé à temps constant. |
| `test_resilience.py` | Un store qui redémarre doit rester invisible : cache oublié, une seule reprise. |
| `test_coherence_depot.py` | Trois endroits qui doivent s'accorder et que rien ne forçait à s'accorder : la borne d'historique dupliquée dans le frontend (son image ne contient pas les schémas), et les versions épinglées par `Dockerfile.frontend` face à `requirements.txt`. Les deux ont réellement divergé. Le troisième est la liste des étages de latence, recopiée dans `scripts/evaluate.py` — délibérément, le script interrogeant un service distant — donc exposée à la divergence qui rendrait un étage mesuré mais jamais publié. Le quatrième est une **mesure** : la marge de fenêtre reprise par le remplissage vit dans un docstring de `llm.py` et dans deux documents, et les trois copies avaient dérivé jusqu'à porter trois triplets pour une seule grille. Le rapprochement se fait à espaces normalisés — c'est la phrase qui est gardée, pas sa mise en page. |
| `test_moteur_llm.py` | **Quel moteur LLM a généré une campagne**, consigné dans `runs/` et confronté par `--compare`. Le banc go/no-go du 15 septembre 2026 a conclu NO-GO sur la seule question de la qualité (§7) parce que **rien** ne le consignait : 19 campagnes sur 19 muettes, donc aucune comparable à une campagne d'après la bascule vers vLLM. Le garde tient quatre propriétés, et chacune a été éprouvée par mutation : il **signale sans refuser** — refuser interdirait de confronter une campagne archivée à une campagne d'aujourd'hui, qui est le geste pour lequel il a été demandé ; **trois positions dont `identique`, qui est imprimé**, sans quoi un silence se lirait comme un accord ; la signature porte le **fait** (`modele_servi`, l'empreinte du poids) et non le réglage (`modele_demande`), parce qu'un nom de modèle est **mutable** et que deux poids peuvent être servis sous le même nom ; un antécédent antérieur au lot est **muet, jamais différent**. Côté sonde, le relevé exige une réponse **positive** — `GET /version` rend 200 et un `version` — sans quoi tout serveur silencieux serait rangé sous ce nom-là. Le double des tests a dû être corrigé pour cela : sa première écriture reconnaissait la route par un **suffixe**. **Depuis le lot 28, le relevé ne sait plus NOMMER un autre moteur** : il coûte deux requêtes au lieu de trois, et un serveur qui n'est pas celui-là laisse `moteur_llm` muet. |
| `test_champs_du_dialecte.py` | **LA TABLE DES CHAMPS QUI DÉPENDENT DU DIALECTE**, et la réponse de REPAR-26 à la cause que le lot 25 avait écrite lui-même : *« une campagne menée sous le défaut ne peut pas mesurer ce qui ne varie qu'à la bascule »*. Son audit a trouvé **trois champs de plus** que le lot — hôte interrogé, modèle demandé, modèle confronté — dont les mutations passaient les 1035 tests **sans un rouge**. Ce fichier ne pose pas trois scènes : il pose une TABLE qui donne, pour chaque champ de `MoteurLlmHealth` et pour chacun des deux dialectes, la valeur attendue, et **quatre gardes la tiennent** — exhaustive contre `model_fields` (un champ neuf non classé rougit), paritaire entre les deux colonnes, SÉPARANTE (un champ portant la même valeur des deux côtés est refusé : c'est le garde anti-« mesuré sous le défaut », et c'est l'erreur exacte que `num_ctx` avait payée), et JOUÉE par une seule scène paramétrée sur (champ × dialecte). **Il n'y a rien à écrire deux fois** : un garde qu'il faut penser à écrire deux fois divergera, et c'est la leçon du lot 19 appliquée à la mesure. Son double route par **(hôte, chemin)** et non par le seul chemin — deux serveurs à deux adresses, comme le poste réel — sans quoi une sonde qui interroge le mauvais hôte y resterait invisible. Il tient aussi les trois sites qui publient le modèle demandé, l'expurgation de l'endpoint **à travers le relevé** (dépôt public, `runs/*.json` versionné), le délai de lecture du flux qui n'est pas borné, et la famille des réglages qu'aucune scène ne doit éprouver à leur **valeur par défaut**. |
| `test_historique_soumis.py` | La profondeur d'historique soumise au LLM, par route. /chat/simple soumettait tout ce que le client envoyait là où les autres coupaient à six : la même conversation produisait deux prompts selon la route. |
| `test_montage_des_tests.py` | **Les garanties du montage des tests, gardées comme du code.** Une fixture `autouse` est une décision invisible : elle s'applique à tout et n'est nommée nulle part dans les tests qu'elle protège. Deux d'entre elles ont été mesurées inertes ou non gardées — retirées, la suite restait verte. Ce fichier est leur rouge. Il garde (a) la **barrière réseau** de `tests/unit/conftest.py`, qui interdit à un test unitaire d'ouvrir une vraie connexion `chromadb` : 41 tests en ouvraient une, 48 tentatives, et ils ne restaient verts et rapides que parce que l'hôte `chromadb` ne se résout pas depuis un poste de développement — *le montage tenait par absorption, pas par construction* ; (b) la fixture qui empêche un test d'**hériter du verdict de concordance** établi par un autre, au moyen de deux tests **ordonnés** dont le second exige de ne rien hériter du premier. Le témoin qui les accompagne vérifie que la barrière ne transforme pas ce cas en panne : une estampille hors réseau se publie en `unknown`, état prévu et documenté, là où un échec de résolution DNS ne l'était pas. |
| `test_ordre_des_sources.py` | L'ordre dans lequel les sources entrent dans la fenêtre. Tout l'aval du budget suppose la pertinence décroissante ; le frontend postait un `set`, donc l'ordre du hachage, et la fenêtre écartait une source au hasard. Les tests assertent depuis `node_reconstruct_context`, qui produit l'ordre. Le cinquième épingle la cause en lisant l'**arbre syntaxique** de `src/frontend/app.py` — `selected_ids` initialisé par `set()`, `selected_element_ids` posté par un `list()` nu. Sa première version construisait `list(set(...))` sur ses propres identifiants : elle n'épinglait rien — corriger le frontend laissait la suite verte — et elle rougissait sur environ une graine de hachage sur deux cents. Un test qui n'importe pas le fichier dont il parle ne garde pas ce fichier. |
| `test_llm_budget.py` | Le budget de la fenêtre de contexte : ce qui entre dans le prompt, ce qui en est écarté et par quel bout, et l'écart entre le prompt estimé et le `prompt_eval_count` réel. L'historique de conversation n'y figurait pas — c'est par là que le prompt dépassait `num_ctx`. Deux invariants y valent plus que les cas isolés : offrir plus de candidates ne doit jamais retirer une source retenue, et la troncature ne doit jamais laisser un `[src:ID]` amputé (balayé sur 1 337 budgets, depuis la première coupe possible : la borne valait 150 et la seule bande où un marqueur pouvait être amputé est 124–134). La chaîne `on_fit` → état du graphe → `/answer` y est exercée sur le vrai `node_generate`, seule la couche HTTP étant simulée : deux mutations la cassaient en gardant la suite verte. La marge de fenêtre qu'une source écartée laissait vide revient désormais à la mieux classée des écartées, tronquée sous un plancher de part : les tests sont des tests de SERRAGE — la place restée libre doit être plus petite que le plus petit fragment que le plancher aurait accepté —, pas des tests « ça tient », qui seraient verts des deux côtés. Un de ces tests portait une phrase d'EXHAUSTIVITÉ fausse — « tout fragment se termine sur un marqueur complet » — que sa fixture, faite de sources toutes marquées, ne pouvait pas contredire : une source orpheline de section n'en porte aucun. La fixture en contient désormais une, et le test compte séparément les fragments des deux espèces pour prouver qu'il a vu les deux. |
| `test_capture_usage.py` | Le module de capture : les trois états de `retenue`, l'empreinte de configuration, la concurrence, et surtout l'absorption des pannes. |
| `test_purge_sessions.py` | La purge des sessions LangGraph : ce qu'elle supprime, et ce qu'elle annonce. Le checkpointer y est **réel** — un vrai `AsyncSqliteSaver` sur un fichier temporaire — et les assertions sont lues en SQL brut dans `checkpoints`. Un faux checkpointer ne lève pas `asyncio.InvalidStateError`, donc il ne prouve rien du défaut : c'est exactement ce montage-là qui l'a laissé vivre. Cinq des six tests sont rouges sur le code d'origine, dont celui qui confronte le nombre de suppressions ANNONCÉ au nombre RÉEL — « le journal annonce [1] suppression(s) alors qu'aucune n'a eu lieu ». Le sixième est un garde-fou, vert des deux côtés et c'est ce qu'on lui demande : une session en attente de sélection doit survivre à un redémarrage. |
| `test_index_lexical.py` | L'index BM25 face à un corpus qui bouge et à des requêtes concurrentes. Deux pièges de montage y sont évités. Le premier : un test « l'index finit construit » est vert des deux côtés d'un défaut de dimensionnement — ce qui voit la panne, c'est un test de **serrage**, qui compte les lectures du corpus (`assert 8 == 1` sur le code d'origine). Le second : les corpus de test comptent au moins **trois** documents, parce que l'IDF de BM25 vaut exactement zéro pour un terme présent dans 1 document sur 2, ce qui rend la recherche lexicale intestable à deux documents. |
| `test_absorptions.py` | Les absorptions d'exceptions resserrées par le lot 3, et le garde-fou qui les empêche de s'élargir. Cinq tests tombent si un `except` resserré redevient `except Exception`, ou si un journal redescend en `debug` ; d'autres gardent les cas que les resserrements doivent continuer de couvrir — un transport mort et un corps non-JSON restent des replis, pas des 500. **Le resserrement a lui-même introduit une régression, et son garde-fou est ici** : un corps qui est du JSON valide sans avoir la forme attendue faisait rendre 500 à /chat/start et /answer. Le garde couvre les quatre formes — `message` nul, chaîne, liste, et corps qui n'est pas un objet — et le fait **au niveau HTTP en plus du niveau unitaire** : c'est l'absence de try/except dans `node_rewrite` qui rendait la panne visible à l'utilisateur, et un test unitaire seul resterait vert le jour où quelqu'un en ajoute un autour du nœud. Il asserte le comportement, pas l'absence d'exception : la question d'origine est conservée et la traduction reste `None`, parce qu'une traduction VIDE entrée dans la fusion RRF serait pire que le 500. |
| `test_mesure_generation.py` | Ce que la génération coûte, et qui n'était mesuré nulle part : `eval_count` n'était même pas LU dans le flux. Deux chaînes y sont exercées de bout en bout — `on_measure` → état → `/answer` → campagne, sur le vrai `node_generate` — et le fait que la décision « écarter un décompte pollué par un cache de préfixe » reste **unique** : le test confronte le verdict de `mesure_prompt_exploitable` au journal de `log_prompt_measure` sur la même valeur, parce que deux seuils recopiés finiraient par diverger. Le test qui fait régresser la mesure porte sur `generations_au_plafond`, le chiffre qui tranche `LLM_MAX_TOKENS`. Trois autres gardent des distinctions qu'une moyenne effacerait : « pas de mesure » n'est pas « zéro token », un ratio non mesuré n'est pas le forfait, et une strate vide doit dire son effectif. |
| `test_comparaison_appariee.py` | L'appariement, et son refus. La pièce maîtresse est `tests/fixtures/campagne_echange.json` : **exactement le même MRR moyen** que la référence alors que huit questions sur dix ont basculé — un diff de résumés s'y lit « rien n'a changé ». Le refus est prouvé sur les fichiers du dépôt : `runs/final.json` (138 lignes) contre `runs/reference.json` (117), qui était la cible de `make eval`. Le bootstrap est exercé sur son déterminisme — même intervalle sur un module rechargé, donc un `random` neuf — et le test des signes sur le fait qu'il ignore les inchangées, ce qui fait sa puissance. Quatre tests lancent le script comme une COMMANDE, en sous-processus, et assertent ses **trois codes de sortie** depuis le côté qui les produit — 0 quand la comparaison aboutit, 1 quand aucune question n'a abouti, 2 quand elle est refusée : un `make eval` rouge doit dire lequel des deux s'est produit. Le code 2 n'était **pas** asserté avant l'audit, et la phrase précédente de cette ligne affirmait le contraire : le remplacer par 0 laissait verts les 390 tests que la suite comptait alors, donc une comparaison refusée serait passée en vert. Le refus était pourtant gardé par cinq tests — mais tous du côté de la LOGIQUE, aucun ne descendant jusqu'au code rendu au shell. Un garde-fou qui ne joue que d'un côté est le défaut de l'espèce que ce dépôt corrige lot après lot. Atteindre le code de sortie sans agent demande un faux `httpx` posé sur `PYTHONPATH`, réduit à `post()` / `raise_for_status()` / `json()` — exactement la surface que le script touche. |
| `test_jeux_de_questions.py` | **La FORME des deux jeux de questions**, contre leur spécification, sans toucher aux stores. Il ne peut pas garder la VÉRITÉ de leurs ancrages — cela demande ChromaDB et NebulaGraph, et c'est `scripts/verifier_les_ancrages.py` : les deux sont nécessaires, aucun ne remplace l'autre. Ce qu'il tient : les 138 questions du jeu de réglage et leurs ancrages bien formés ; les cinq strates du jeu de contrôle à l'effectif (12 / 8 / 4 / 4 / 2) et ses 44 ancrages distincts ; les quatre questions de suivi portant leur `chat_history` ; la **réserve** du jeu de 30 vivant dans le fichier de données — une réserve qu'on peut perdre en éditant un fichier n'en est pas une ; le `# pragma: allowlist secret` sur l'empreinte de provenance, `mesuré` nécessaire (`rc=1`, une détection, sans lui) parce que `yaml.safe_dump` n'écrit pas de commentaire et que le pragma du script y reste. **Et le défaut que le lot 5 existe pour réparer, gardé sur les DEUX jeux** : aucune question à réponse ne désigne le vide, aucune abstention ne porte d'ancrage. C'est ce garde-là qui a trouvé `tests/fixtures/golden_qa.json` — un troisième jeu, `--golden` par défaut, dont les **13** questions à réponse — sur 15 ; les deux autres, `Q-010` et `Q-011`, sont des abstentions, et « 15 à réponse » était faux de deux, `mesuré` (trouvaille N8) — portaient **0** ancrage, donc des métriques de rappel à `None` qui se lisent « sans objet » et non « cassé ». |
| `test_verification_des_ancrages.py` | **La sonde qui prouve qu'un jeu désigne quelque chose**, et qu'une campagne LIT. Son garde central lit `scripts/verifier_les_ancrages.py` par l'**arbre syntaxique** et relève le nom de chaque méthode appelée : aucun verbe d'écriture ChromaDB, aucune requête nGQL d'écriture. **Sa première forme était fausse** — une recherche de la sous-chaîne `.add(` rougissait sur un `trouves.add(...)` parfaitement légitime, et un garde qui rougit sur du code sain est retiré par le suivant, donc désarmé. La sonde a été réécrite pour n'appeler aucun de ces noms, et son code dit à l'endroit où il les évite pourquoi. Éprouvé dans les deux directions : `collection.modify(...)` et `INSERT VERTEX …` le font rougir. **CE QUE CETTE LIGNE AFFIRMAIT ET QUI ÉTAIT FAUX** — « un `set.add` non ». `mesuré` le 8 septembre 2026 en plantant un `trouves.add(...)` légitime dans la sonde : **deux** tests rougissaient, l'analyse par arbre syntaxique ET une assertion de sous-chaîne `.add(` qui était revenue dans le fichier alors que le lot 5 la qualifiait de « première forme fausse ». Le fichier de test, lui, était honnête. L'assertion de sous-chaîne est **retirée** — strictement redondante avec l'arbre syntaxique, mesuré — et ce qui reste vrai est : l'arbre syntaxique **ne sait pas** distinguer `trouves.add` de `collection.add`, et c'est pourquoi la sonde n'appelle aucun `add` du tout. Il sait en revanche distinguer `parser.add_argument`, ce que la sous-chaîne ne savait pas. Le contrat des codes de sortie est désormais gardé lui aussi — `TestUnStoreInjoignableSortEnDeux`, et il ne l'était par rien. Le reste garde les quatre désaccords que la sonde cherche — absent du graphe, absent de ChromaDB (celui qui décide du rappel, et le plus traître : 15 196 sommets au graphe contre **3 750** `element_id` dans l'index), document discordant, strate incohérente — et le piège du schéma : le pipeline nomme ses ancrages `element_ids`, ce dépôt `gold_element_ids`, et une sonde qui ne lirait qu'une clé déclarerait l'autre jeu **conforme sans rien vérifier**. Elle lève. |
| `test_sens_des_metriques.py` | Ce que l'instrument AFFICHE. `comparer` posait « ▲ » sur tout écart positif : une génération passant de 9 s à 6 s portait le même « ▼ » qu'un rappel qui s'effondre, sur **vingt-six clés** dont `reconstruction_ms` — celle que l'ablation du graphe viendra lire. Les tests exigent le SENS sur les trois familles, et le plus dur d'entre eux exige que le MÊME signe d'écart porte des flèches OPPOSÉES selon la métrique : un affichage qui ne regarde que le signe ne peut pas y arriver, quelle que soit la flèche qu'il choisit. Deux garde-fous ferment le repli de `sens_de_lecture`, qui rend +1 sur une clé inconnue pour ne pas casser une campagne : toute clé du résumé doit être classée par une liste, et toute métrique appariée doit avoir un sens — sans quoi elle recevrait des colonnes ▲/▼ vides de sens et une p-value. |
| `test_precision_contexte.py` | La précision du contexte **payé**, et les trois pièges de son dénominateur. Chaque métrique y a un test qui la fait RÉGRESSER : un or noyé dans neuf sections inutiles fait chuter `taux_contexte_utile` à rapport de rappel identique, et un contexte inutile qui grossit fait chuter `part_utile_caracteres` sans que le taux bouge. Trois mutations sont vérifiées rouges — dénominateur pris sur les candidates, texte publié entier au lieu du texte tronqué, `submitted_contexts` jamais publié. Un test épingle la BORNE de `part_utile_caracteres` : elle ne bouge pas quand la fenêtre grossit à l'intérieur de la section porteuse, et c'est `caracteres_retenus` à `rappel_contexte` constant qui lit ce cas. Les deux derniers exercent la vraie chaîne `on_fit` → état → `/answer` sur le vrai `fit_prompt`. Le lot 4b y ajoute la séparation des **deux causes du prix** : deux campagnes au prix total identique — six sections de mille caractères contre trois de deux mille — que `caracteres_retenus` seul ne distingue pas, et que le quotient sépare. Le test du dénominateur nul est dimensionné pour que la médiane BOUGE — deux questions servies et trois vides — parce qu'à deux zéros sur quatre il serait vert des deux côtés du défaut. |
| `test_fenetre_heritee.py` | **LE VERDICT DE ONZE SCÈNES NE DÉPEND PAS DE `LLM_NUM_CTX`**, et c'est la dette que le §4.63 du registre laissait ouverte. Le 22 septembre 2026, le réglage est passé de 8192 à 32768 dans le `.env` du poste : onze scènes qui HÉRITAIENT du plafond au lieu de le POSER ont perdu leur sujet le jour même — un budget qui n'écarte plus rien ne mesure plus rien —, et personne ne l'a vu pendant deux jours parce que les arbres de travail n'ont pas de `.env` et que la porte y était verte à bon droit. Ce garde relance les onze **par leurs identifiants** sous trois fenêtres (8192, 16384, 32768) dans de vrais sous-processus, et exige le même `rc` ET le même compte. Le sous-processus n'est pas un confort : `settings` est construit à l'import, et deux des onze reconstruisent un `Settings` — `_env_file=None` neutralise le FICHIER, pas l'ENVIRONNEMENT, dont `pydantic-settings` fait une source de priorité supérieure, ce qui rend aussi ce garde mordant dans le clone principal. Le compte attendu est le nombre de scènes gardées et non un chiffre écrit : un identifiant périmé rougit au lieu de rétrécir le périmètre en silence. Ce qu'il ne prouve pas est écrit à son site : il balaie `LLM_NUM_CTX` et lui seul, quand le budget dépend aussi de `LLM_MAX_TOKENS` et de `HISTORY_WINDOW_SHARE` — que `fenetre_du_prompt.py` pose avec la fenêtre, affranchissant les onze sans fermer le cas général. |
| `test_chronometrie.py` | La partition du temps par étage : son arithmétique, et surtout ce qui la fait mentir. Le test qui compte fait **régresser** la mesure — il verse un agrégat dans un étage et exige que le résidu devienne NÉGATIF et que le journal le dise. Borner le résidu à zéro le rendrait vert sur un tableau faux. Un second épingle la décision elle-même : `retrieval_ms` est un agrégat, et il tombe le jour où quelqu'un l'ajoute à `ETAGES` « pour compléter le tableau ». |
| `test_partition_etages.py` | La même partition, mais branchée sur les **vrais nœuds** : chaque étape simulée dort une durée qui lui est propre, ce qui permet d'exiger le SENS de l'attribution et pas seulement la présence d'un chiffre. Un `decomposer` correct branché sur rien publierait huit zéros et un résidu égal au total. Deux tests portent l'étage qui n'avait jamais été chronométré — la reconstruction par le graphe — dans les deux sens : elle coûte son temps même quand elle échoue, et elle tombe à zéro quand rien n'est reconstruit, ce que l'ablation doit lire. |
| `test_health_parallele.py` | `/health` sous le délai que Docker lui accorde. Le test du lot compare la durée mesurée au `timeout` **lu dans `docker-compose.yml`** : 32,0 s avant, 3,0 s après, et le 32,0 ≈ 4 × 8 s de sondes muettes est la preuve de la sérialisation. Le parallélisme, lui, n'est pas prouvé par un chronomètre — « moins de 5 s » reste vert sur des sondes séquentielles rapides — mais par une **barrière à quatre parties**, qu'une implémentation séquentielle ne peut pas franchir quelle que soit la vitesse de chaque sonde. Deux tests portent le piège du lot : un plafond n'interrompt pas un fil, il le lâche, donc une sonde déjà en vol ne doit pas être relancée (compté sur les ENTRÉES de la sonde, pas sur la réponse), et un fil revenu doit rendre la sonde à nouveau interrogeable — sans quoi la panne serait remplacée par une cécité définitive. Un dernier test porte une leçon générale : il vérifie que `/health` rend 200 sur un `LLM_HOST` mal formé, et il **épingle d'abord que son host lève bien l'exception visée**. Écrit sans cet épinglage, il empruntait le chemin ordinaire — une URL sans schéma lève `UnsupportedProtocol`, qui EST une `HTTPError` et que la sonde rattrape — en prétendant vérifier l'autre. Un test qui choisit lui-même son cas doit prouver qu'il l'a atteint. |
| `test_citations_soumises.py` | Une citation ne doit pas résoudre vers un texte jamais soumis au modèle. Deux voies y sont comptées **séparément**, parce que chacune se ferme par une moitié différente du correctif : passer les sections soumises au lieu des candidates ferme `elements_map`, filtrer `chunks_map` ferme l'autre, et un test qui n'en couvre qu'une reste vert avec la moitié du travail. Le test du chemin réel — le modèle recite un marqueur d'un tour précédent, resoumis par `fit_history` — prouve ses trois maillons dans le même corps sur le vrai `_build_messages` : la section est bien écartée, le marqueur est bien dans le prompt, la citation est refusée. Sans le maillon du milieu, le lot corrigerait un défaut inatteignable. Les tailles de sections y sont **calculées depuis le budget réel** et non posées : une constante choisie à la main finit du mauvais côté de la frontière, et le test surveille alors un cas qu'il n'atteint plus. |
| `test_capture_branchement.py` | La capture vue de l'API : les deux phases jointes par `thread_id`, la sélection humaine distinguée des sections soumises, et une base en échec qui ne casse aucune requête. La colonne `dropped_contexts` y est exercée sur des sections qui dépassent réellement la fenêtre — seule la couche HTTP est simulée, le budget est celui du vrai `fit_prompt` : trois mutations la cassent, une par maillon de la chaîne `on_fit` → état → colonne. |

Trois leçons du lot 3, du même ordre que celles du lot 2 :

- **Un faux qui ne ressemble pas à la bibliothèque ne prouve rien de la
  bibliothèque.** Deux tests simulaient la panne du serveur LLM en levant un
  `ConnectionError` intégré, qu'httpx ne lève jamais — il enveloppe le transport
  dans `httpx.TransportError`. Ils restaient donc verts sur n'importe quelle
  absorption, y compris la plus large, et devenaient rouges dès qu'on resserrait
  sur la vraie panne. Le resserrement les a révélés ; sans lui, ils auraient
  gardé pour toujours un `except Exception` qu'ils ne testaient pas.
- **Une phrase d'exhaustivité dans un document est un défaut en attente.** La
  table du balayage écrivait « les deux **seules** façons dont l'appel échoue
  sans que le code soit en cause ». Il y en avait trois, et la troisième — un
  corps JSON valide de forme inattendue — a fait rendre 500 à deux routes. La
  phrase n'a pas seulement décrit le défaut : elle l'a autorisé, en clôturant
  l'énumération que personne n'a plus rouverte.
- **Ce qui doit être asserté, c'est le disque, pas le compteur du code.** La
  purge des sessions journalisait « Sessions purgées : 1 » sans supprimer une
  ligne. Tout test qui aurait cru ce compteur aurait été vert. Les tests de
  `test_purge_sessions.py` ouvrent le fichier SQLite en lecture directe, et
  confrontent le nombre annoncé au nombre réellement supprimé.

Deux leçons du lot 5, sur la forme des tests de temps :

- **Un chronomètre ne prouve pas le parallélisme.** Un test qui n'assère que
  « moins de 5 s » reste vert sur quatre sondes séquentielles rapides : il garde
  la borne, pas la simultanéité. Une **barrière** à autant de parties qu'il y a
  de sondes prouve la simultanéité structurellement — une implémentation
  séquentielle ne peut pas la franchir, quelle que soit la vitesse de chaque
  sonde — et elle ne coûte aucune attente quand elle est verte.
- **Ce qu'il faut simuler, c'est une sonde qui ne revient pas, pas une sonde qui
  dort.** Une suite qui gagne huit secondes de `sleep` par test de latence
  devient une suite qu'on n'exécute plus. Les sondes de ces tests bloquent sur un
  `threading.Event` débloqué dans un `finally` : la durée verte est celle du
  plafond, pas celle du blocage — et sans ce `finally`, les fils du threadpool
  n'étant pas des démons, ils retiendraient l'interpréteur à la sortie. Un seul
  test paie le plafond RÉEL, parce qu'un test qui règle lui-même le plafond
  resterait vert le jour où la valeur par défaut passe à 60 s.

Deux leçons du lot 6b, sur les tests qui accompagnent une restriction :

- **Un test vert peut l'être GRÂCE au défaut.** Deux tests de
  `test_postprocess.py` résolvaient une citation depuis les chunks reranqués avec
  AUCUNE section soumise dans l'état : ils décrivaient précisément le trou qu'on
  vient de fermer, et il a fallu les réécrire — pas les désactiver — sur l'état
  normal, où l'élément est à la fois dans le classement et dans une section
  soumise. Un test qu'un correctif fait rougir mérite d'être lu avant d'être cru.
- **Un faux qui ne rappelle pas ses rappels ne prouve rien de l'appelant.** Les
  faux `generate_stream` de `test_flux_interactif.py` et
  `test_capture_branchement.py` remplaçaient la fonction en entier sans jamais
  appeler `on_fit` — le dépôt le savait et l'avait écrit — donc l'état ne portait
  aucune section soumise et plus aucune citation ne se résolvait. Ils appellent
  désormais le vrai `fit_prompt`. Même famille : le test de la route non diffusée
  laisse tourner le vrai `generate` et ne neutralise que `generate_stream`, sinon
  retirer le relais de `on_fit` dans `generate` laissait la suite verte — mutation
  vérifiée dans les deux sens.

Deux leçons de la revue du lot 2, qui valent au-delà de ses fichiers :

- **Un script n'est pas testé tant qu'il n'a pas été lancé comme une commande.**
  `usage_export.py` mourait sur `ModuleNotFoundError` dès la première ligne de
  `main()` ; les tests chargeaient le module par `importlib` et n'appelaient que
  ses fonctions. Un test en processus ne l'aurait pas vu davantage — pytest
  tourne depuis la racine, donc `src` y est déjà importable. Seul un
  **sous-processus, PYTHONPATH retiré**, reproduit la vraie invocation.
- **Une ligne écrite mérite d'être comparée entière.** Sept colonnes de
  `sources_proposees` étaient écrites sans qu'aucun test ne les garde : sabotées
  une à une, la suite restait verte. Comparer le dictionnaire complet coûte
  moins qu'une assertion par colonne, et n'oublie rien.

**`--strict-markers` et `asyncio_mode = "strict"` ne sont pas décoratifs.** Sans
eux, un test asynchrone mal marqué n'échoue pas : il *passe sans rien
exécuter*. Une suite verte qui ne teste rien est pire qu'une suite rouge.

Pour vérifier que ce garde-fou tient encore, écrire un test asynchrone qui
échoue et s'assurer qu'il échoue bien. S'il passe, le greffon ne fait plus son
travail.

## Intégration — 10 tests, stack requise

Ils existent parce que **trois des défauts les plus coûteux de ce projet
étaient invisibles en unitaire**, tous parce qu'ils vivaient dans l'écart entre
ce que le code croyait et ce que les services faisaient :

- une requête nGQL écrite à l'envers — `dst(edge)` sous `REVERSELY` renvoie le
  nœud de départ — qui rendait toute la reconstruction par le graphe
  inopérante, sans une seule erreur ;
- une arête renommée côté ingestion (`DESCRIBES` → `LINKED_TO`), dont l'échec
  était avalé et privait les illustrations de leur légende ;
- un checkpointer synchrone branché sur un flux asynchrone, qui faisait tomber
  toute l'interface en 500.

Aucun test simulé ne pouvait les voir : un faux ChromaDB répond ce qu'on lui a
dit de répondre.

**Sans la stack, ils sont ignorés, pas en échec.** Un test rouge faute
d'infrastructure ne dit rien sur le code, et apprend à ignorer le rouge.

```bash
make up && make test-integration
```

## Campagne — 138 questions, la seule mesure de qualité

`make eval` rejoue le jeu doré contre l'API réelle et le compare à
`runs/final.json`, **question par question**. C'est le seul niveau qui mesure si
le système **répond bien**, par opposition à *fonctionne*.

La cible fut `runs/reference.json` jusqu'au lot 4 : ce fichier ne porte que 117
des 138 lignes, et la comparaison appariée le refuse désormais — cf. la ligne du
registre, qui dit pourquoi le compte n'est pas le vrai problème.

Les métriques et leur lecture sont dans
[rag_evaluation_strategy.md](rag_evaluation_strategy.md) ; les résultats et les
règles de comparaison dans [runs/README.md](../runs/README.md).

Trois règles apprises en se trompant :

1. Mesurer **après** le reranking — c'est ce qui atteint le LLM qui compte.
2. Vérifier ce que le `.env` impose : il surcharge les valeurs par défaut du
   code, et a déjà invalidé un balayage entier.
3. **Ne toucher à rien pendant une campagne.** Deux ont été faussées par un
   `docker compose build` lancé pendant qu'elles tournaient.

## Ce que rien ne teste

À dire franchement, parce que la couverture n'est pas la confiance :

- **La qualité des réponses n'est jugée par personne.** Le rappel mesure la
  recherche. Savoir si la reconstruction de section améliore la *réponse*
  demande un juge calibré, qui n'existe pas ici.
- **Le jeu doré n'est pas relu.** 138 questions générées, toutes
  `reviewed: false`. Aucun humain n'a confirmé qu'elles sont de vraies
  questions.
- **Le frontend n'a pas de tests de bout en bout.** Les fonctions d'affichage
  sont testées ; le parcours dans un navigateur ne l'est qu'à la main. Les deux
  derniers défauts de citation ont été trouvés à l'œil, pas par la suite.
- **Ni charge, ni concurrence.** Rien ne dit ce qui se passe à dix questions
  simultanées. Deux exceptions : les écritures de la capture d'usage sont
  testées à dix interactions concurrentes — c'est là qu'un défaut de
  transaction SQLite en faisait perdre jusqu'à six — et la construction de
  l'index lexical est testée à huit requêtes concurrentes, où elle se faisait
  huit fois. Ce sont deux points, pas une couverture de charge : aucun test ne
  fait passer une **question entière** en parallèle d'une autre.
- **Les deux boutons d'appréciation ne sont pas testés.** L'endpoint `/feedback`
  l'est ; le clic dans Streamlit ne l'est qu'à la main, comme le reste du
  frontend.
- **La reconstruction de l'index lexical est attendue, pas observée en
  situation.** `test_index_lexical.py` programme la reconstruction puis attend
  son fil (`join`). Cela prouve qu'elle a lieu et qu'elle n'a lieu qu'une fois ;
  cela ne prouve pas que les requêtes servies **pendant** qu'elle tourne
  répondent correctement. Ce point-là tient au remplacement atomique de l'état
  de l'index, relu, pas à un test.
- **L'écriture après le dernier événement SSE n'est vérifiée que de
  l'intérieur.** Le client de test tamponne la réponse : l'ordre est observé par
  un espion dans l'application, ce qui interdit d'écrire avant d'avoir répondu
  mais ne distingue pas « juste avant » de « juste après » le dernier
  événement. Cette position-là tient au point d'appel, relu, pas à un test.
