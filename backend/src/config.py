from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Logoped Assistant"

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
    rerank_fallback_n: int = 2
    kb_max_upload_bytes: int = 20 * 1024 * 1024
    kb_chunk_chars: int = 1500
    kb_source_dir: str = "/kb"
    kb_session_gap_minutes: int = 30
    # Automatyczne wykrywanie nowych/zmienionych plików w katalogu (0 = wyłączone).
    kb_scan_interval_seconds: int = 300
    ocr_engine: str = "tesseract"  # domyślny silnik OCR (src.ocr.ENGINES)
    ocr_languages: str = "pol+eng"
    ocr_min_word_confidence: int = 60
    ocr_max_side_px: int = 2600
    history_window: int = 10

    llm_log_enabled: bool = True
    llm_log_retention_days: int = 90
    llm_log_max_chars: int = 100_000

    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    smtp_starttls: bool = True
    smtp_ssl: bool = False
    smtp_timeout_seconds: float = 20.0
    app_public_url: str = "http://localhost:8080"

    # Kredyty (zł): koszt = tokeny × cena modelu (USD / 1 mln tokenów) × kurs USD→PLN × marża.
    billing_default_limit_pln: float = 20.0
    billing_usd_pln_rate: float = 3.70
    billing_margin: float = 1.0
    # Nadpisanie/uzupełnienie cennika: JSON {"model": [cena_wejścia, cena_wyjścia]} w USD za 1 mln.
    billing_prices_json: str = ""
    billing_topup_amounts: str = "20,50,100"
    topup_bank_account: str = ""
    topup_recipient: str = "Webaby"
    # Płatności online (Stripe Checkout: BLIK, karta, Przelewy24); puste klucze = tylko przelew.
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""
    stripe_payment_methods: str = (
        "blik,card,p24"  # tylko opis w UI; metody włącza się w panelu Stripe
    )
    stripe_api_url: str = "https://api.stripe.com/v1"
    # Model zastępczy po wyczerpaniu kredytów (OpenAI-compatible, np. Ollama: http://gemma4:11434/v1).
    local_llm_base_url: str = ""
    local_llm_model: str = "gemma4:12b"
    local_llm_api_key: str = "local"  # dla taniego modelu w chmurze – klucz tego dostawcy
    local_llm_timeout_seconds: float = 600.0

    seed_on_startup: bool = True
    seed_max_attempts: int = 12

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]


settings = get_settings()
