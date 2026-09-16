import json
import sqlite3
import threading
from pathlib import Path

from app.agent.conversation import Conversation
from app.agent.intent import QuestionIntent
from app.agent.models import (
    AgentState,
    AgentTurnResponse,
    ConversationSummary,
    ConversationTurn,
    ToolEvent,
)


class ConversationStore:
    """Small durable repository for resumable controlled-agent conversations."""

    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=5)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS agent_conversation (
                    id TEXT PRIMARY KEY,
                    state TEXT NOT NULL,
                    token_fingerprint TEXT,
                    original_question TEXT,
                    question_intent TEXT,
                    device_id TEXT,
                    device_json TEXT,
                    ticket_draft_json TEXT,
                    step_count INTEGER NOT NULL,
                    last_sensitive_signature TEXT,
                    events_json TEXT NOT NULL,
                    history_json TEXT NOT NULL DEFAULT '[]',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            columns = {
                row["name"] for row in connection.execute("PRAGMA table_info(agent_conversation)")
            }
            if "question_intent" not in columns:
                connection.execute("ALTER TABLE agent_conversation ADD COLUMN question_intent TEXT")
            if "history_json" not in columns:
                connection.execute(
                    "ALTER TABLE agent_conversation ADD COLUMN history_json TEXT NOT NULL DEFAULT '[]'"
                )

    def get(self, conversation_id: str) -> Conversation | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM agent_conversation WHERE id = ?", (conversation_id,)
            ).fetchone()
        if row is None:
            return None
        return Conversation(
            id=row["id"],
            state=AgentState(row["state"]),
            token_fingerprint=row["token_fingerprint"],
            original_question=row["original_question"],
            question_intent=(
                QuestionIntent(row["question_intent"]) if row["question_intent"] else None
            ),
            device_id=row["device_id"],
            device=json.loads(row["device_json"]) if row["device_json"] else None,
            ticket_draft=(
                json.loads(row["ticket_draft_json"]) if row["ticket_draft_json"] else None
            ),
            step_count=row["step_count"],
            last_sensitive_signature=row["last_sensitive_signature"],
            events=[ToolEvent.model_validate(event) for event in json.loads(row["events_json"])],
            history=[
                ConversationTurn(
                    user_message=turn["user_message"],
                    response=AgentTurnResponse.model_validate(turn["response"]),
                )
                for turn in json.loads(row["history_json"] or "[]")
            ],
        )

    def list_for_identity(self, token_fingerprint: str, limit: int = 50) -> list[ConversationSummary]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                """
                SELECT id, state, original_question, updated_at
                FROM agent_conversation
                WHERE token_fingerprint = ? AND history_json != '[]'
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (token_fingerprint, limit),
            ).fetchall()
        return [
            ConversationSummary(
                id=row["id"],
                title=(row["original_question"] or "新对话")[:60],
                state=AgentState(row["state"]),
                updated_at=row["updated_at"],
            )
            for row in rows
        ]

    def save(self, conversation: Conversation) -> None:
        values = (
            conversation.id,
            conversation.state.value,
            conversation.token_fingerprint,
            conversation.original_question,
            conversation.question_intent.value if conversation.question_intent else None,
            conversation.device_id,
            json.dumps(conversation.device, ensure_ascii=False) if conversation.device else None,
            json.dumps(conversation.ticket_draft, ensure_ascii=False)
            if conversation.ticket_draft
            else None,
            conversation.step_count,
            conversation.last_sensitive_signature,
            json.dumps([event.model_dump(mode="json") for event in conversation.events]),
            json.dumps(
                [turn.model_dump(mode="json") for turn in conversation.history],
                ensure_ascii=False,
            ),
        )
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO agent_conversation (
                    id, state, token_fingerprint, original_question, question_intent, device_id, device_json,
                    ticket_draft_json, step_count, last_sensitive_signature, events_json, history_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    state = excluded.state,
                    token_fingerprint = excluded.token_fingerprint,
                    original_question = excluded.original_question,
                    question_intent = excluded.question_intent,
                    device_id = excluded.device_id,
                    device_json = excluded.device_json,
                    ticket_draft_json = excluded.ticket_draft_json,
                    step_count = excluded.step_count,
                    last_sensitive_signature = excluded.last_sensitive_signature,
                    events_json = excluded.events_json,
                    history_json = excluded.history_json,
                    updated_at = CURRENT_TIMESTAMP
                """,
                values,
            )
