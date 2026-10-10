from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Knowledge Studio AI Service"
    app_env: str = "local"
    api_prefix: str = "/api"
    llm_api_key: str = ""
    llm_base_url: str = ""
    llm_model: str = ""
    llm_timeout_seconds: float = 60.0
    evidence_score_threshold: float = 0.10
    answer_top_k: int = 5
    knowledge_agent_max_steps: int = 3
    knowledge_agent_deadline_seconds: float = 90.0
    knowledge_max_revisions: int = 3
    backend_base_url: str = "http://127.0.0.1:8080"
    backend_timeout_seconds: float = 5.0
    backend_tool_transport: str = "mcp"
    agent_max_steps: int = 12
    project_root: Path = Path(__file__).resolve().parents[2]
    agent_database_path: Path = project_root / "ai-service" / "data" / "agent-conversations.db"
    knowledge_base_path: Path = project_root / "ai-service" / "data" / "knowledge-bases"
    retrieval_mode: str = "local"
    elasticsearch_url: str = ""
    elasticsearch_index: str = "supportpilot_chunks"
    elasticsearch_api_key: str = ""
    milvus_url: str = ""
    milvus_collection: str = "supportpilot_chunks"
    milvus_token: str = ""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
