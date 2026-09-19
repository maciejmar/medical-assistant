from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Logoped Assist"

    vllm_base_url: str
    vllm_api_key: str = "EMPTY"
    vllm_chat_model: str
    vllm_embedding_model: str
    llm_timeout_seconds: float = 120.0

    whisper_api_url: str
    whisper_api_key: str = ""
    whisper_model: str = "openai/whisper-large-v3"
    whisper_timeout_seconds: float = 180.0
    max_audio_bytes: int = 25 * 1024 * 1024

    db_url: str
    qdrant_url: str = "http://qdrant:6333"
    qdrant_collection: str = "logopedia_kb"

    jwt_secret: str = Field(min_length=32)
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 480
    admin_email: str = "admin@logoped.local"
    admin_password: str = Field(min_length=8)
    cors_origins: str = "http://localhost:8080,http://localhost:4200"

    reranker_model: str = "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1"
    retrieval_top_k: int = 12
    rerank_top_n: int = 4
    rerank_min_score: float = 0.02
    history_window: int = 10

    seed_on_startup: bool = True
    seed_max_attempts: int = 12

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]


settings = get_settings()
