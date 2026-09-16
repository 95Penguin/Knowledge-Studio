from functools import lru_cache

from app.agent.backend import JavaBackendClient
from app.agent.service import ControlledAgentService
from app.agent.store import ConversationStore
from app.config import get_settings
from app.generation.runtime import get_answer_service


@lru_cache
def get_agent_service() -> ControlledAgentService:
    settings = get_settings()
    return ControlledAgentService(
        get_answer_service(),
        JavaBackendClient(settings.backend_base_url, settings.backend_timeout_seconds),
        max_steps=settings.agent_max_steps,
        store=ConversationStore(settings.agent_database_path),
    )
