"""Configurações carregadas do .env via pydantic-settings."""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    google_api_key: str = ""
    model_name: str = "gemini-2.5-flash"
    max_tokens: int = 8192
    contracts_dir: str = "./contracts"
    db_path: str = "./contract_analyzer.db"

    @property
    def contracts_path(self) -> Path:
        return Path(self.contracts_dir).resolve()


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def reload_settings() -> Settings:
    """Recarrega .env (útil após alterar MODEL_NAME sem reiniciar o processo)."""
    global _settings
    _settings = Settings()
    return _settings
