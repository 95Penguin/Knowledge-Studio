from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "SupportPilot AI Service"
    app_env: str = "local"
    api_prefix: str = "/api"
    llm_api_key: str = ""
    llm_base_url: str = ""
    llm_model: str = ""
    llm_timeout_seconds: float = 60.0
    evidence_score_threshold: float = 0.10
    answer_top_k: int = 5
    backend_base_url: str = "http://127.0.0.1:8080"
    backend_timeout_seconds: float = 5.0
    agent_max_steps: int = 12
    project_root: Path = Path(__file__).resolve().parents[2]
    agent_database_path: Path = project_root / "ai-service" / "data" / "agent-conversations.db"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
