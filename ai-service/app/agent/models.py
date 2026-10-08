from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.generation.models import Citation, RequestTrace


class AgentState(StrEnum):
    NEW = "new"
    WAITING_FEEDBACK = "waiting_feedback"
    WAITING_DEVICE_AUTHORIZATION = "waiting_device_authorization"
    WAITING_DEVICE_FEEDBACK = "waiting_device_feedback"
    WAITING_TICKET_CONFIRMATION = "waiting_ticket_confirmation"
    WAITING_GENERAL_ANSWER_CONFIRMATION = "waiting_general_answer_confirmation"
    TICKET_CREATED = "ticket_created"
    TRANSFERRED = "transferred"
    FAILED = "failed"
    COMPLETED = "completed"


class AgentTurnRequest(BaseModel):
    conversation_id: str | None = None
    action: Literal[
        "ask", "resolved", "unresolved", "authorize_device", "confirm_ticket", "transfer",
        "general_answer"
    ]
    message: str | None = Field(default=None, max_length=2000)
    backend_token: str | None = Field(default=None, max_length=500)
    device_id: str | None = None
    knowledge_base_ids: list[str] = Field(default_factory=list, max_length=5)


class ToolEvent(BaseModel):
    tool: Literal[
        "search_knowledge", "general_knowledge", "query_device", "create_ticket",
        "transfer_to_human"
    ]
    status: Literal["started", "succeeded", "failed", "denied", "skipped"]
    summary: str
    duration_ms: float = 0
    request_id: str | None = None


class AgentTurnResponse(BaseModel):
    conversation_id: str
    state: AgentState
    message: str
    required_action: str | None = None
    citations: list[Citation] = Field(default_factory=list)
    tool_events: list[ToolEvent] = Field(default_factory=list)
    device: dict[str, Any] | None = None
    ticket: dict[str, Any] | None = None
    ticket_draft: dict[str, Any] | None = None
    trace: RequestTrace | None = None


class ConversationTurn(BaseModel):
    user_message: str
    response: AgentTurnResponse


class ConversationSummary(BaseModel):
    id: str
    title: str
    state: AgentState
    updated_at: str


class ConversationHistory(BaseModel):
    id: str
    title: str
    state: AgentState
    turns: list[ConversationTurn] = Field(default_factory=list)
