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

    # MinIO
    minio_endpoint: str = Field(default="minio:9000", alias="MINIO_ENDPOINT")
    minio_root_user: str = Field(default="minioadmin", alias="MINIO_ROOT_USER")
    minio_root_password: str = Field(default="", alias="MINIO_ROOT_PASSWORD")
    minio_bucket: str = Field(default="documents", alias="MINIO_BUCKET")
    minio_secure: bool = Field(default=False, alias="MINIO_SECURE")

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

    # Retrieval
    embedding_model_name: str = Field(
        default="all-MiniLM-L6-v2", alias="EMBEDDING_MODEL_NAME"
    )
    rerank_model: str = Field(
        default="cross-encoder/ms-marco-MiniLM-L6-v2", alias="RERANK_MODEL"
    )
    retrieval_top_k: int = Field(default=20, alias="RETRIEVAL_TOP_K")
    rerank_top_k: int = Field(default=10, alias="RERANK_TOP_K")
    max_search_iterations: int = Field(default=3, alias="MAX_SEARCH_ITERATIONS")

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

    # Prompts
    prompts_dir: str = Field(default="/app/prompts", alias="PROMPTS_DIR")

    # API
    api_host: str = Field(default="0.0.0.0", alias="API_HOST")
    api_port: int = Field(default=8000, alias="API_PORT")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")


settings = Settings()
