from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "HandOff"
    database_url: str = "sqlite:///./handoff.db"
    gemini_api_key: str = ""
    ai_model: str = "gemini-flash-lite-latest"
    cors_origins: str = "http://localhost:8000,http://127.0.0.1:8000"
    log_file: str = "logs/app.log"
    log_level: str = "INFO"
    anthropic_api_key: str = ""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @property
    def allowed_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
