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
    # FORFAIT, mais un forfait dont la valeur exacte est SANS EFFET sur la
    # grille de mesure : de 0,25 à 0,45 le résultat est identique — même marge
    # inutilisée, mêmes configurations gagnées, même plus petit fragment. 1/3
    # est le milieu de ce plateau, donc le point le moins sensible à ±10 points.
    # Le protocole de mesure est dans documentation/llm.md.
    #
    # Ce qu'il empêche, mesuré : sans plancher, la grille retient un fragment
    # tombant à 4 % de sa source. Le modèle en voit alors assez pour la citer et
    # pas assez pour savoir ce qu'elle dit — un défaut silencieux, donc pire
    # qu'une source absente, que l'abstention rend visible.
    #
    # Il ne s'applique QUE si une autre source est déjà retenue : sans lui le
    # prompt partirait sans aucune source, et « mieux vaut une source amputée
    # que zéro source » reste l'arbitrage du budget (registre 1.14).
    truncation_floor_share: float = Field(default=1 / 3, alias="TRUNCATION_FLOOR_SHARE",
                                          ge=0.0, le=1.0)

    # Retrieval
    embedding_model_name: str = Field(
        default="paraphrase-multilingual-MiniLM-L12-v2", alias="EMBEDDING_MODEL_NAME"
    )
    # Le cross-encoder doit parler les mêmes langues que l'embedder, sinon il
    # défait son travail : mesuré sur une question française, ms-marco (anglais)
    # rendait des scores plats — étendue 0,0 % sur 20 candidats, soit un
    # classement au hasard. Son équivalent multilingue sépare à 75 %.
    rerank_model: str = Field(
        default="cross-encoder/mmarco-mMiniLMv2-L12-H384-v1", alias="RERANK_MODEL"
    )
    # Candidats conservés après fusion, soumis au reranking. Balayé sur 130
    # questions, mesuré APRÈS reranking — donc sur ce qui atteint le LLM :
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
