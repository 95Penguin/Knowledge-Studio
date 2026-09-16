from dataclasses import dataclass, field
from typing import Any

from app.agent.intent import QuestionIntent
from app.agent.models import AgentState, ConversationTurn, ToolEvent


@dataclass
class Conversation:
    id: str
    state: AgentState = AgentState.NEW
    token_fingerprint: str | None = None
    original_question: str | None = None
    question_intent: QuestionIntent | None = None
    device_id: str | None = None
    device: dict[str, Any] | None = None
    ticket_draft: dict[str, Any] | None = None
    step_count: int = 0
    last_sensitive_signature: str | None = None
    events: list[ToolEvent] = field(default_factory=list)
    history: list[ConversationTurn] = field(default_factory=list)
