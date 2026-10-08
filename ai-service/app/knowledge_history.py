"""Durable conversation history for knowledge-base question answering."""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from pathlib import Path
from typing import Any

from app.generation.models import AnswerResponse


class KnowledgeConversationStore:
    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=5)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS knowledge_conversation (
                    id TEXT PRIMARY KEY,
                    owner_id TEXT NOT NULL,
                    title TEXT NOT NULL DEFAULT '新对话',
                    knowledge_base_ids_json TEXT NOT NULL DEFAULT '[]',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS knowledge_turn (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    conversation_id TEXT NOT NULL,
                    position INTEGER NOT NULL,
                    question TEXT NOT NULL,
                    answer_json TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(conversation_id, position),
                    FOREIGN KEY(conversation_id) REFERENCES knowledge_conversation(id)
                );
                """
            )

    def create(self, owner_id: str, knowledge_base_ids: list[str]) -> dict[str, Any]:
        conversation_id = str(uuid.uuid4())
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO knowledge_conversation (id, owner_id, knowledge_base_ids_json)
                VALUES (?, ?, ?)
                """,
                (conversation_id, owner_id, json.dumps(knowledge_base_ids)),
            )
        return {
            "id": conversation_id,
            "title": "新对话",
            "knowledge_base_ids": knowledge_base_ids,
            "updated_at": "",
            "turn_count": 0,
        }

    def list(self, owner_id: str, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                """
                SELECT c.id, c.title, c.knowledge_base_ids_json, c.updated_at,
                       COUNT(t.id) AS turn_count
                FROM knowledge_conversation c
                LEFT JOIN knowledge_turn t ON t.conversation_id = c.id
                WHERE c.owner_id = ?
                GROUP BY c.id
                HAVING COUNT(t.id) > 0
                ORDER BY c.updated_at DESC
                LIMIT ?
                """,
                (owner_id, limit),
            ).fetchall()
        return [self._summary(row) for row in rows]

    def get(self, conversation_id: str, owner_id: str) -> dict[str, Any]:
        with self._lock, self._connect() as connection:
            conversation = connection.execute(
                "SELECT * FROM knowledge_conversation WHERE id = ?",
                (conversation_id,),
            ).fetchone()
            if conversation is None:
                raise FileNotFoundError("conversation not found")
            if conversation["owner_id"] != owner_id:
                raise PermissionError("conversation does not belong to current user")
            turns = connection.execute(
                """
                SELECT question, answer_json FROM knowledge_turn
                WHERE conversation_id = ? ORDER BY position
                """,
                (conversation_id,),
            ).fetchall()
        return {
            "id": conversation["id"],
            "title": conversation["title"],
            "knowledge_base_ids": json.loads(conversation["knowledge_base_ids_json"]),
            "updated_at": conversation["updated_at"],
            "turns": [
                {"question": turn["question"], "answer": json.loads(turn["answer_json"])}
                for turn in turns
            ],
        }

    def assert_owned(self, conversation_id: str, owner_id: str) -> None:
        self.get(conversation_id, owner_id)

    def append(
        self,
        conversation_id: str,
        owner_id: str,
        question: str,
        answer: AnswerResponse,
        knowledge_base_ids: list[str],
    ) -> None:
        with self._lock, self._connect() as connection:
            conversation = connection.execute(
                "SELECT owner_id, title FROM knowledge_conversation WHERE id = ?",
                (conversation_id,),
            ).fetchone()
            if conversation is None:
                raise FileNotFoundError("conversation not found")
            if conversation["owner_id"] != owner_id:
                raise PermissionError("conversation does not belong to current user")
            position = connection.execute(
                "SELECT COUNT(*) FROM knowledge_turn WHERE conversation_id = ?",
                (conversation_id,),
            ).fetchone()[0]
            connection.execute(
                """
                INSERT INTO knowledge_turn (conversation_id, position, question, answer_json)
                VALUES (?, ?, ?, ?)
                """,
                (
                    conversation_id,
                    position,
                    question,
                    answer.model_dump_json(),
                ),
            )
            title = question.strip()[:40] if position == 0 else conversation["title"]
            connection.execute(
                """
                UPDATE knowledge_conversation
                SET title = ?, knowledge_base_ids_json = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (title or "新对话", json.dumps(knowledge_base_ids), conversation_id),
            )

    @staticmethod
    def _summary(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "title": row["title"],
            "knowledge_base_ids": json.loads(row["knowledge_base_ids_json"]),
            "updated_at": row["updated_at"],
            "turn_count": row["turn_count"],
        }
