from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Repo root .env — works regardless of which directory uvicorn is launched from
_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Database
    database_url: str = "postgresql+asyncpg://stonky:changeme@localhost:5432/stonky"

    # FastAPI
    port: int = 8080
    debug: bool = False
    cors_origins: list[str] = ["http://localhost:5173"]

    # Scheduler
    scheduler_enabled: bool = True

    # LLM Synthesis Agent
    llm_provider: str = "ollama"
    ollama_model: str = "llama3.1:8b"
    ollama_base_url: str = "http://localhost:11434"
    anthropic_api_key: str | None = None

    # Pipeline concurrency (tune based on hardware)
    pipeline_yolo_concurrency: int = 4  # reduce to 2 if using GPU for YOLO
    pipeline_chronos_concurrency: int = 4
    pipeline_synthesis_concurrency: int = 1  # do not change — Ollama is single-threaded

    # Broad Market / FRED
    fred_api_key: str | None = None

    # Real-time price service
    price_cache_ttl_seconds: int = 60

    # Notion integration (paper trader + execution log)
    notion_api_key: str | None = None

    # Discord (Trading Company webhook)
    discord_webhook_url: str | None = None

    # Paper Trader parameters
    paper_trader_portfolio_value: float = 30_000.0
    paper_trader_risk_pct: float = 0.01
    paper_trader_min_rr: float = 1.5


settings = Settings()
