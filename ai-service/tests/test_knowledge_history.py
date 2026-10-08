from pathlib import Path

import pytest

from app.generation.models import AnswerResponse
from app.knowledge_history import KnowledgeConversationStore


def test_knowledge_conversation_is_persisted_and_owner_isolated(tmp_path: Path) -> None:
    store = KnowledgeConversationStore(tmp_path / "conversations.db")
    conversation = store.create("user-a", ["kb-a"])
    answer = AnswerResponse(status="answered", answer="测试回答", citations=[])

    store.append(conversation["id"], "user-a", "第一个问题", answer, ["kb-a"])

    assert store.list("user-a")[0]["title"] == "第一个问题"
    history = store.get(conversation["id"], "user-a")
    assert history["turns"][0]["answer"]["answer"] == "测试回答"
    assert store.list("user-b") == []
    with pytest.raises(PermissionError):
        store.get(conversation["id"], "user-b")
