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
    debug: bool = False
    cors_origins: list[str] = ["http://localhost:5173"]

    # Scheduler
    scheduler_enabled: bool = True

    # LLM Synthesis Agent
    llm_provider: str = "ollama"
    ollama_model: str = "llama3.1:8b"
    ollama_base_url: str = "http://localhost:11434"
    anthropic_api_key: str | None = None

    # Broad Market / FRED
    fred_api_key: str | None = None


settings = Settings()
