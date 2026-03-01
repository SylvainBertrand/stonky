from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # Database
    database_url: str = "postgresql+asyncpg://stonky:changeme@localhost:5432/stonky"

    # FastAPI
    debug: bool = False
    cors_origins: list[str] = ["http://localhost:5173"]

    # Scheduler
    scheduler_enabled: bool = True


settings = Settings()
