from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # ChromaDB
    chroma_host: str = Field(default="chromadb", alias="CHROMA_HOST")
    chroma_port: int = Field(default=8000, alias="CHROMA_PORT")
    chroma_collection: str = Field(default="rag_documents", alias="CHROMA_COLLECTION")

    # NebulaGraph
    nebula_host: str = Field(default="graphd", alias="NEBULA_HOST")
    nebula_port: int = Field(default=9669, alias="NEBULA_PORT")
    nebula_user: str = Field(default="root", alias="NEBULA_USER")
    nebula_password: str = Field(default="nebula", alias="NEBULA_PASSWORD")
    nebula_space: str = Field(default="rag_space", alias="NEBULA_SPACE")
    # Délai d'expiration d'une requête nGQL. Sans lui, une requête lente du
    # graphd fige la requête FastAPI qui l'attend.
    nebula_timeout_ms: int = Field(default=15_000, alias="NEBULA_TIMEOUT_MS")

    # MinIO
    minio_endpoint: str = Field(default="minio:9000", alias="MINIO_ENDPOINT")
    minio_root_user: str = Field(default="minioadmin", alias="MINIO_ROOT_USER")
    minio_root_password: str = Field(default="", alias="MINIO_ROOT_PASSWORD")
    minio_bucket: str = Field(default="documents", alias="MINIO_BUCKET")
    minio_secure: bool = Field(default=False, alias="MINIO_SECURE")
    # Le proxy /media ne sert que les objets référencés par le graphe. Sans
    # cette borne, il sert n'importe quel objet du bucket à qui devine son
    # chemin — le garde-fou anti-traversal empêche de sortir du bucket, pas
    # d'y fouiller.
    restrict_media_to_graph: bool = Field(default=True, alias="RESTRICT_MEDIA_TO_GRAPH")

    # Ollama / LLM
    ollama_host: str = Field(default="http://ollama:11434", alias="OLLAMA_HOST")
    ollama_model: str = Field(default="gemma4:e4b", alias="OLLAMA_MODEL")
    llm_temperature: float = Field(default=0.1, alias="LLM_TEMPERATURE")
    llm_max_tokens: int = Field(default=4096, alias="LLM_MAX_TOKENS")
    # Fenêtre de contexte demandée à Ollama. Doit être passée explicitement :
    # sinon elle dépend de l'OLLAMA_CONTEXT_LENGTH du serveur, qui diffère
    # entre l'Ollama embarqué (8192) et le service central (32768) — le même
    # prompt produisait donc deux comportements selon le mode de déploiement.
    llm_num_ctx: int = Field(default=8192, alias="LLM_NUM_CTX")
    # Gemma 4 = modèle à raisonnement ; thinking désactivé par défaut (en CPU,
    # la réflexion peut consommer tout le budget avant le 1er token de réponse)
    llm_thinking: bool = Field(default=False, alias="LLM_THINKING")
    # Part de la fenêtre de prompt que l'historique de conversation peut occuper.
    # FORFAIT, pas une mesure : arbitrer entre historique et sources demanderait
    # une mesure de la qualité multi-tour, qui n'existe pas ici. Sans plafond,
    # une conversation longue affame les sources ; à 1.0, six messages à la borne
    # de Message.content dépassent à eux seuls num_ctx, et c'est Ollama qui
    # tranche — par le DÉBUT, donc en jetant le message système.
    history_window_share: float = Field(default=0.25, alias="HISTORY_WINDOW_SHARE",
                                        ge=0.0, le=1.0)
    # Part de sa source qu'un fragment tronqué doit atteindre pour valoir la
    # place qu'il prend. En dessous, la source est écartée entière.
    #
    # FORFAIT, au sens plein : aucune mesure ne désigne cette valeur-ci. Une
    # version antérieure annonçait un plateau d'insensibilité de 0,25 à 0,45 ;
    # c'était un ARTEFACT du montage, dont les sources avaient toutes la même
    # taille dans une configuration donnée — le plancher mordait alors pour
    # toutes ou pour aucune. Tailles tirées par source, il n'y a aucun palier :
    # chaque pas déplace la marge, le nombre de configurations gagnées et la plus
    # petite part retenue (protocole et sortie dans documentation/llm.md).
    #
    # Ce que la mesure établit vraiment, et qui suffit à trancher :
    #   - sans plancher, la grille retient un fragment tombant à 1 % de sa
    #     source. Le modèle en voit alors assez pour la citer et pas assez pour
    #     savoir ce qu'elle dit — un défaut silencieux, donc pire qu'une source
    #     absente, que l'abstention rend visible ;
    #   - la plus petite part retenue suit le réglage de près (34 % à 1/3, 25 % à
    #     0,25, 51 % à 0,50) : le réglage veut bien dire ce qu'il dit ;
    #   - son prix est continu : à 1/3, 408 caractères de marge laissés et 38
    #     configurations gagnées, contre 76 et 70 sans plancher.
    #
    # 1/3 est donc un arbitrage entre lisibilité du fragment et remplissage de la
    # fenêtre, pas un optimum mesuré. Ce qui le trancherait est une mesure de la
    # QUALITÉ des réponses, qui demande une campagne.
    #
    # Il ne s'applique QUE si une autre source est déjà retenue : sans lui le
    # prompt partirait sans aucune source, et « mieux vaut une source amputée
    # que zéro source » reste l'arbitrage du budget (registre 1.14).
    truncation_floor_share: float = Field(default=1 / 3, alias="TRUNCATION_FLOOR_SHARE",
                                          ge=0.0, le=1.0)

    # Retrieval
    # ---------
    # LE PÉRIPHÉRIQUE DE TORCH, ET IL EST EXPLICITE DEPUIS LE 11 SEPTEMBRE 2026.
    #
    # CE QUI ÉTAIT LÀ AVANT, ET POURQUOI CE N'ÉTAIT PAS TENABLE. `retriever`
    # construisait ses deux modèles SANS argument `device` :
    # `SentenceTransformer(nom)` et `CrossEncoder(nom)`. Or les deux portent
    # `device: str | None = None` (`mesuré` le 11 septembre 2026,
    # `inspect.signature` sur sentence-transformers 5.6.1), et `None` ne veut pas
    # dire « CPU » — il veut dire « décide pour moi ». Le service prenait donc ce
    # que l'image lui donnait, sans jamais le dire ni permettre d'en décider.
    # Tant que l'image ne portait qu'un torch CPU, la distinction n'avait aucun
    # effet observable ; elle en a un dès que l'image porte un build CUDA, et
    # c'est exactement là qu'on ne peut plus distinguer « le GPU est utilisé » de
    # « le GPU est là et on ne s'en sert pas ».
    #
    # LE DÉFAUT EST `cpu`, ET C'EST UNE DÉCISION, PAS UNE COMMODITÉ. Il préserve
    # le comportement mesuré du service le 11 septembre 2026 — `rerank` et
    # `dense` sur CPU — Y COMPRIS une fois l'image passée à un build CUDA et le
    # GPU réservé au conteneur. Sans cette valeur-ci, la seule reconstruction de
    # l'image basculerait la production sur la carte AVANT qu'une campagne ait
    # dit si ça vaut le coup, et le GPU de ce poste n'est pas libre : Ollama y
    # tient déjà 4 904 Mio et porte 84 % du temps d'une réponse.
    #
    # CE QUI EST ACCEPTÉ : une chaîne libre, transmise telle quelle à torch —
    # `cpu`, `cuda`, `cuda:1`. Elle n'est pas validée ici, et c'est délibéré :
    # la liste des périphériques que torch connaît dépend du build, donc un
    # littéral posé ici périmerait, et un réglage refusé par pydantic empêcherait
    # le service de DÉMARRER là où torch, lui, lève une erreur nommée au
    # chargement du premier modèle. Ce qui remplace la validation est
    # l'OBSERVABILITÉ : `/health` publie `torch_device`, qui dit ce qui est
    # demandé, ce que le build sait faire, et sur quoi chaque modèle est
    # réellement posé — voir `retriever.etat_du_peripherique`.
    #
    # Gardé dans les DEUX positions : `tests/unit/test_peripherique_torch.py`.
    torch_device: str = Field(default="cpu", alias="TORCH_DEVICE")
    embedding_model_name: str = Field(
        default="paraphrase-multilingual-MiniLM-L12-v2", alias="EMBEDDING_MODEL_NAME"
    )
    # Le cross-encoder doit parler les mêmes langues que l'embedder, sinon il
    # défait son travail. Le réglage multilingue est le BON — **97,6 % contre
    # 95,1 % de rappel@10** — mais pour une raison PLUS FAIBLE que celle qui
    # était écrite ici, et le motif est corrigé le 8 septembre 2026.
    #
    # CES DEUX CHIFFRES SONT CITÉS, PAS REMESURÉS ICI. Ils viennent de l'audit
    # du 8 septembre 2026 ; site canonique
    # `documentation/axes_amelioration.md` §4.31. Les rejouer demande la pile
    # démarrée et une campagne complète, ce que ce lot n'a pas fait — et la
    # distinction est écrite parce que reprendre un antécédent du dépôt sans le
    # mesurer est la même faute que de l'inventer. Ce que ce lot a bien mesuré
    # lui-même, c'est le MÉCANISME décrit juste en dessous.
    #
    # CE QUE CE SITE A AFFIRMÉ, ET QUI ÉTAIT UNE INFÉRENCE FAUSSE. Il portait
    # qu'un cross-encoder anglais sur une question française rendait « des
    # scores plats — étendue 0,0 % sur 20 candidats, **soit un classement au
    # hasard** ». La conclusion ne suit pas de la prémisse. `mesuré` : la ligne
    # `chunk.relevance = _sigmoid(score)` applique une sigmoïde au logit du
    # cross-encoder, et une sigmoïde SATURE — des logits de −6,8 à −11,35
    # s'écrasent dans 0,11 % d'étendue **en préservant STRICTEMENT l'ordre**
    # (sonde sans chargement de modèle, par le seul mécanisme). Une étendue
    # quasi nulle est donc entièrement expliquée par la saturation, et ne dit
    # RIEN sur le classement. L'audit l'a confirmé contre un témoin de hasard
    # pur : le modèle anglais est **5× meilleur en rang et 14× meilleur en
    # perte** qu'un tirage au sort. Un reranker anglais classe — il classe
    # simplement MOINS BIEN.
    #
    # LE COÛT RÉEL, ET C'EST LUI QUI JUSTIFIE LE RÉGLAGE : **−2,5 points de
    # rappel@10**, concentrés sur les **41 questions translingues sur 138** du
    # jeu de référence, soit 30 %. Un mal silencieux et modéré, pas une panne.
    # C'est pourquoi son garde SIGNALE au lieu de refuser — le motif complet est
    # au site du garde, `retriever.verdict_langue_du_reranker`.
    #
    # Ne pas relire « étendue quasi nulle » comme « le modèle ne classe plus » :
    # c'est l'inférence que ce lot est venu retirer, et le pilote du chantier
    # s'était appuyé dessus sans la mesurer.
    rerank_model: str = Field(
        default="cross-encoder/mmarco-mMiniLMv2-L12-H384-v1", alias="RERANK_MODEL"
    )
    # Candidats conservés après fusion, soumis au reranking. Balayé sur 130
    # questions, mesuré APRÈS reranking — donc sur ce qui atteint le LLM.
    #
    # **CE BALAYAGE EST DU 3 AOÛT 2026, ET IL EST ANTÉRIEUR AU CORPUS EN
    # SERVICE.** `mesuré` le 8 septembre 2026 par `git log -S "0.962" --
    # src/agent/settings.py` : ces chiffres sont entrés au dépôt le 3 août 2026,
    # soit un MOIS avant le remplacement du corpus du 2 septembre 2026
    # (site canonique : `documentation/axes_amelioration.md` §4.3). Ils ont
    # décidé d'un réglage et n'ont pas été rejoués depuis. Ce n'est pas une
    # raison de les retirer — un réglage sans motif écrit est pire — mais c'en
    # est une de ne pas les lire comme le rappel du corpus actuel : celui-là est
    # à `documentation/campagnes/2026-09-08-campagne-de-reference.md`. Le
    # `README.md` recopiait deux de ces chiffres sans date ; il renvoie
    # désormais ici (trouvaille N8 de l'audit du lot 5).
    #
    #   top_k   rappel   transling.   même langue
    #      20    0.900       0.889         0.904
    #      30    0.915       0.889         0.926
    #      50    0.962       0.889         0.989   <- retenu
    #
    # (mesuré à TRANSLATION_WEIGHT=0.5 ; à 1.0 le rappel monte à 0.985)
    #
    # La recherche translingue diluait la fusion et chassait du top-20 des
    # passages que la question d'origine avait bien trouvés. Élargir le vivier
    # règle cela sans rien céder : le cross-encoder, lui, sait trier.
    retrieval_top_k: int = Field(default=50, alias="RETRIEVAL_TOP_K")
    # Recherche hybride : BM25 en plus du dense, fusionnés par Reciprocal Rank
    # Fusion. Le dense rate ce qui ne se paraphrase pas — acronymes, noms
    # propres, références, chiffres. BM25 les retrouve à la lettre.
    hybrid_search: bool = Field(default=True, alias="HYBRID_SEARCH")
    # Candidats demandés à CHAQUE moteur avant fusion — quatre au maximum :
    # dense et lexical, pour la question et pour sa traduction. Jusqu'à 200
    # candidats distincts entrent donc dans la fusion, qui n'en garde que
    # RETRIEVAL_TOP_K. La fusion n'a d'intérêt que si les listes se recouvrent
    # peu, d'où un vivier large en amont.
    fetch_k: int = Field(default=50, alias="FETCH_K")
    # Amortissement RRF. 60 = valeur de l'article d'origine.
    rrf_k: int = Field(default=60, alias="RRF_K")
    rerank_top_k: int = Field(default=10, alias="RERANK_TOP_K")
    max_search_iterations: int = Field(default=3, alias="MAX_SEARCH_ITERATIONS")
    # Déclare search_vectors comme outil natif Ollama. Le repli — repérer
    # `search_vectors("…")` dans la prose du modèle — reste actif en second
    # rideau, pour les modèles sans tool-calling.
    native_tool_calling: bool = Field(default=True, alias="NATIVE_TOOL_CALLING")
    # Sources reconstruites d'office quand personne ne les choisit : endpoint
    # /answer, et repli si la sélection humaine revient vide.
    auto_select_top_k: int = Field(default=3, alias="AUTO_SELECT_TOP_K")
    # Reformule une question de suivi en question autonome avant l'encodage.
    # « Et pour les femmes ? » embarqué tel quel ne retrouve rien.
    query_rewrite: bool = Field(default=True, alias="QUERY_REWRITE")
    # Traduit la question dans l'autre langue du corpus et cherche avec les
    # deux. Mesuré : le rappel tombe de 0,99 à 0,74 quand la question et le
    # document ne sont pas dans la même langue, et la recherche lexicale ne
    # trouve alors rien du tout — deux langues ne partagent pas leurs mots.
    cross_lingual_search: bool = Field(default=True, alias="CROSS_LINGUAL_SEARCH")
    # Poids des résultats issus de la question traduite dans la fusion RRF.
    # Balayé sur 130 questions (36 translinguistiques, 94 en même langue),
    # mesuré APRÈS reranking, avec RETRIEVAL_TOP_K=50 :
    #
    #   poids   rappel   transling.   même langue
    #   0.00     0.938       0.806         0.989
    #   0.25     0.962       0.889         0.989
    #   0.50     0.962       0.889         0.989
    #   1.00     0.985       1.000         0.979   <- retenu
    #
    # À pleine puissance, le rappel translinguistique atteint 1,000 pour un
    # point cédé en même langue. Le réglage reste exposé, mais le compromis
    # qu'il servait à arbitrer a disparu : à RETRIEVAL_TOP_K=20 il fallait
    # brider la traduction à 0,25 pour ne pas chasser du top-20 ce que la
    # question d'origine avait trouvé. Ce n'était pas un défaut de la
    # traduction, c'était une coupe trop précoce.
    translation_weight: float = Field(default=1.0, alias="TRANSLATION_WEIGHT")

    # Reconstruction du contexte via le graphe
    # ---------------------------------------
    # Fenêtre d'éléments retenus autour de l'élément trouvé, à l'intérieur de
    # sa section. Sans borne, un document sans SectionHeader rattache tous ses
    # éléments au nœud Document : la « section » reconstruite est alors le
    # document entier, et Ollama tronque le prompt en silence.
    context_window_before: int = Field(default=6, alias="CONTEXT_WINDOW_BEFORE")
    context_window_after: int = Field(default=6, alias="CONTEXT_WINDOW_AFTER")
    # Éléments repris de la section précédente (queue) et de la suivante
    # (tête). 0 désactive la traversée vers les sections voisines.
    adjacent_section_elements: int = Field(default=3, alias="ADJACENT_SECTION_ELEMENTS")
    # LA REMONTÉE AUX ONCLES — définition (C) de « section voisine » —, ÉTEINTE
    # PAR DÉFAUT, ET VOICI CE QU'ELLE COÛTE. Quand une section n'a pas de frère
    # en-tête sous son parent (définition (A), `graph_context._find_sibling`),
    # allumer ce réglage fait remonter `_neighbour_section` aux oncles, borné au
    # document, au lieu de servir un bloc d'encadrement vide de ce côté. Couverture
    # `mesuré` le 9 septembre 2026 sur le graphe en service : 532 / 746 en-têtes
    # servis sous (A), 721 / 722 sous (C) — `scripts/mesurer_le_graphe.py`.
    #
    # ET LA COUVERTURE NE RAPPORTE RIEN QUI SE MESURE. `make eval` sur les 138
    # questions, comparaison appariée à `runs/2026-09-08-reference.json`, `mesuré`
    # le 10 septembre 2026 par le lot 4 (§4.41 de
    # `documentation/axes_amelioration.md`, le site canonique de ces chiffres) :
    #
    #   les six métriques de rappel      identiques à la 4e décimale, 130/130 ex æquo
    #   caracteres_retenus_p50            9 529  →  10 633   (+11,6 %)
    #   prompt_eval_count_p50             3 131  →   3 291   (+5,1 %)
    #   contextes_ecartes_total              26  →      32   (six contextes ÉVINCÉS)
    #   reconstruction_ms_p50               114  →     197   (+73 %)
    #   reconstruction_ms_p95               181  →     571   (+215 %)
    #
    # Ces chiffres ont été REJOUÉS par le lot 8 le 10 septembre 2026 (14:39 →
    # 14:58 UTC) sur un lecteur hors service, (C) allumée, et versionnés :
    # `runs/2026-09-10-definition-c-allumee-reglage.json` — 10 633, 3 291 et 32
    # à l'unité, reconstruction 191 / 550 ms. La colonne « après » a un site.
    #
    # Le §P1 du registre tranche : un rapport prix/apport défavorable tranche sans
    # juge. Décision de l'utilisateur, 10 septembre 2026 : le comportement de
    # production reste (A), le code de (C) survit derrière ce réglage. Ce que la
    # mesure NE dit pas : aucun des deux jeux ne note la réponse GÉNÉRÉE, donc
    # l'absence de gain mesuré n'est pas une preuve d'absence de gain — c'est la
    # seule raison pour laquelle ce réglage existe au lieu d'un revert.
    #
    # Éteint, le chemin est celui de `main` à la requête nGQL près, et c'est
    # gardé dans les DEUX positions : `tests/unit/test_section_voisine.py`,
    # `TestLeReglageEteintRendLeComportementDeMain`.
    neighbour_section_uncles: bool = Field(default=False, alias="NEIGHBOUR_SECTION_UNCLES")
    # Illustrations affichées au maximum dans une réponse. Elles proviennent
    # des sections d'où viennent les citations : au-delà de cette borne, on
    # remplirait l'écran de figures décoratives.
    max_images: int = Field(default=4, alias="MAX_IMAGES")
    # Le graphe ne porte qu'un aperçu du texte (tronqué à l'ingestion) ; le
    # corpus complet vit dans l'index vectoriel. Un tableau Docling dépasse
    # souvent la limite et arrivait amputé au LLM.
    full_text_from_vectors: bool = Field(default=True, alias="FULL_TEXT_FROM_VECTORS")
    # Doit correspondre à GRAPH_TEXT_MAX_CHARS côté ingestion.
    graph_text_truncation: int = Field(default=2000, alias="GRAPH_TEXT_TRUNCATION")

    # Prompts
    prompts_dir: str = Field(default="/app/prompts", alias="PROMPTS_DIR")

    # API
    # Sessions LangGraph (checkpointer en mémoire) : bornes de purge. Sans
    # elles, chaque question laisse son état en mémoire indéfiniment.
    # Fichier SQLite des sessions LangGraph. Vide = checkpointer en mémoire
    # (sessions perdues au redémarrage, incompatible multi-workers).
    checkpoint_db_path: str = Field(default="/app/data/checkpoints.sqlite",
                                    alias="CHECKPOINT_DB_PATH")
    max_live_sessions: int = Field(default=200, alias="MAX_LIVE_SESSIONS")
    session_ttl_seconds: int = Field(default=3600, alias="SESSION_TTL_SECONDS")

    # Capture d'usage : questions posées, sources proposées, sources retenues,
    # réponses, appréciations. VRAI par défaut — un drapeau à faux annulerait
    # le dispositif, puisque personne ne le basculera avant les premiers
    # utilisateurs, et que les premières semaines d'usage ne se rattrapent pas.
    # L'exposition n'est pas nouvelle : le checkpointer persiste DÉJÀ l'état
    # complet du graphe dans le même volume, sans purge. Cf. SECURITY.md.
    usage_capture: bool = Field(default=True, alias="USAGE_CAPTURE")
    # Même volume que le checkpointer : ce qui est monté est déjà durable.
    # Vide désactive la capture aussi sûrement que USAGE_CAPTURE=false.
    usage_db_path: str = Field(default="/app/data/usage.sqlite", alias="USAGE_DB_PATH")

    # Origines autorisées par CORS, séparées par des virgules. « * » ouvre
    # l'API à n'importe quelle page web du navigateur de l'utilisateur.
    cors_origins: str = Field(
        default="http://localhost:8506,http://localhost:8501", alias="CORS_ORIGINS"
    )
    # Clé exigée dans l'en-tête X-API-Key. Vide = aucune authentification,
    # ce qui convient à un déploiement local mais pas à une exposition.
    api_key: str = Field(default="", alias="API_KEY")

    # Pas d'API_HOST / API_PORT : le Dockerfile fixe l'écoute et compose fait
    # la correspondance de ports. Les exposer laissait croire qu'on pouvait les
    # changer par le .env, ce qui n'avait aucun effet.
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")


    @property
    def cors_origin_list(self) -> list[str]:
        """Origines CORS sous forme de liste, vides écartées."""
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


settings = Settings()
