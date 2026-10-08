import math
from collections.abc import Sequence
from pathlib import Path

import pytest

from app.knowledge_bases import KnowledgeBaseStore


class FakeEncoder:
    model_name = "fake"
    model_revision = "test"
    dimension = 2

    def encode_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._vector(text) for text in texts]

    def encode_queries(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._vector(text) for text in texts]

    def _vector(self, text: str) -> list[float]:
        raw = [1.0, 0.0] if "向量" in text else [0.0, 1.0]
        norm = math.sqrt(sum(value * value for value in raw))
        return [value / norm for value in raw]


def test_multiple_knowledge_bases_are_isolated_by_owner_and_scope(tmp_path: Path) -> None:
    store = KnowledgeBaseStore(tmp_path, FakeEncoder())
    first = store.create("RAG", "user-a", "检索增强生成")
    second = store.create("Java", "user-a", "Spring Boot")
    hidden = store.create("Private", "user-b")
    store.upload(first["id"], "rag.md", b"# Embedding\n\n\xe5\x90\x91\xe9\x87\x8f\xe6\xa3\x80\xe7\xb4\xa2", "user-a")
    store.upload(second["id"], "java.md", b"# Spring\n\nDependency injection", "user-a")

    assert {item["id"] for item in store.list("user-a")} == {first["id"], second["id"]}
    assert hidden["id"] not in {item["id"] for item in store.list("user-a")}
    assert store.list_documents(first["id"], "user-a")[0]["chunk_count"] == 1
    assert all(
        result.source_path.startswith(f"{first['id']}/")
        for result in store.search("向量", knowledge_base_ids=(first["id"],))
    )
    with pytest.raises(PermissionError):
        store.assert_owned([hidden["id"]], "user-a")

    updated = store.update(first["id"], "user-a", "RAG 新名称", "新的描述")
    assert updated["name"] == "RAG 新名称"
    persisted = next(item for item in store.list("user-a") if item["id"] == first["id"])
    assert persisted["description"] == "新的描述"
