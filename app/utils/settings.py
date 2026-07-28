"""Configurações carregadas do .env via pydantic-settings."""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    openai_api_key: str = ""
    model_name: str = "gpt-4o-mini"
    model_name_pro: str = ""  # opcional — vazio usa model_name
    max_tokens: int = 16384
    embedding_model: str = "text-embedding-3-small"

    contracts_dir: str = "./contracts"
    db_path: str = "./contract_analyzer.db"
    export_dir: str = ""

    @property
    def export_path(self) -> Path | None:
        if not self.export_dir.strip():
            return None
        return Path(self.export_dir).expanduser().resolve()

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
