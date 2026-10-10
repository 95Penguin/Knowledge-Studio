import json
import math
import uuid
from collections.abc import Sequence
from pathlib import Path

import pytest

from app.ingestion.uploaded import parse_uploaded_document
from app.knowledge_bases import KnowledgeBaseStore
from app.retrieval.bm25 import BM25Index
from app.retrieval.dense import DenseIndex


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
    store.upload(
        first["id"],
        "rag.md",
        b"# Embedding\n\n\xe5\x90\x91\xe9\x87\x8f\xe6\xa3\x80\xe7\xb4\xa2",
        "user-a",
    )
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


def test_agent_can_read_owned_outline_sections_and_neighbors(tmp_path: Path) -> None:
    store = KnowledgeBaseStore(tmp_path, FakeEncoder())
    kb_id = store.create("Papers", "user-a")["id"]
    document = store.upload(
        kb_id,
        "paper.md",
        b"# Transformer\n\n## Encoder\n\nEncoder layers.\n\n## Decoder\n\nDecoder layers.",
        "user-a",
    )
    outline = store.outline(kb_id, "user-a")
    assert outline[0]["document_id"] == document["id"]
    assert "Transformer > Encoder" in outline[0]["sections"]
    encoder = store.read_section(kb_id, "user-a", document["id"], "Encoder")
    assert encoder[0].content == "Encoder layers."
    neighbors = store.read_neighbors(kb_id, "user-a", encoder[0].chunk_id)
    assert {item.content for item in neighbors} == {"Encoder layers.", "Decoder layers."}
    with pytest.raises(PermissionError):
        store.outline(kb_id, "user-b")
    with pytest.raises(FileNotFoundError):
        store.read_section(kb_id, "user-a", "missing", "Encoder")


def test_replace_and_delete_document_update_active_index(tmp_path: Path) -> None:
    store = KnowledgeBaseStore(tmp_path, FakeEncoder())
    kb_id = store.create("Pets", "user-a")["id"]
    original = store.upload(kb_id, "guide.md", b"# Old\n\nOld content", "user-a")
    assert (
        store.upload(kb_id, "guide.md", b"# Old\n\nOld content", "user-a")["id"] == original["id"]
    )

    updated = store.replace(
        kb_id,
        original["id"],
        "guide.md",
        b"# New\n\nNew content",
        "user-a",
        "https://example.org/guide",
    )
    assert updated["id"] == original["id"]
    assert updated["version"] == 2
    assert updated["origin_url"] == "https://example.org/guide"
    assert store.document_text(kb_id, original["id"], "user-a") == "# New\n\nNew content"
    assert all(
        "Old content" not in item.content
        for item in store.search("New", knowledge_base_ids=(kb_id,))
    )
    assert all(
        item.source_url == "https://example.org/guide"
        for item in store.search("New", knowledge_base_ids=(kb_id,))
    )

    store.delete(kb_id, original["id"], "user-a")
    assert store.list_documents(kb_id, "user-a") == []
    assert store.list("user-a")[0]["document_count"] == 0
    assert store.search("New", knowledge_base_ids=(kb_id,)) == []
    with pytest.raises(FileNotFoundError):
        store.document_text(kb_id, original["id"], "user-a")


def test_revision_retention_keeps_active_snapshot_and_two_rollback_versions(
    tmp_path: Path,
) -> None:
    store = KnowledgeBaseStore(tmp_path, FakeEncoder(), max_revisions=3)
    kb_id = store.create("Docs", "user-a")["id"]
    document = store.upload(kb_id, "guide.md", b"# Version 0\n\nInitial", "user-a")
    manual = tmp_path / kb_id / "revisions" / "manual-backup"
    manual.mkdir()
    for version in range(1, 6):
        store.replace(
            kb_id,
            document["id"],
            "guide.md",
            f"# Version {version}\n\nContent {version}".encode(),
            "user-a",
        )
    folder = tmp_path / kb_id
    active_id = json.loads((folder / "active_revision.json").read_text())["revision"]
    revisions = [
        path for path in (folder / "revisions").iterdir()
        if path.is_dir() and store._is_revision_name(path.name)
    ]
    assert len(revisions) == 3
    assert manual.is_dir()
    assert (folder / "revisions" / active_id).is_dir()
    assert "Content 5" in store.document_text(kb_id, document["id"], "user-a")


def test_failed_reindex_preserves_previous_active_revision(tmp_path: Path) -> None:
    class FailingEncoder(FakeEncoder):
        fail = False

        def encode_documents(self, texts: Sequence[str]) -> list[list[float]]:
            if self.fail:
                raise RuntimeError("embedding unavailable")
            return super().encode_documents(texts)

    encoder = FailingEncoder()
    store = KnowledgeBaseStore(tmp_path, encoder)
    kb_id = store.create("Pets", "user-a")["id"]
    original = store.upload(kb_id, "guide.md", b"# Original\n\nUseful content", "user-a")
    pointer = (tmp_path / kb_id / "active_revision.json").read_text(encoding="utf-8")
    encoder.fail = True
    with pytest.raises(RuntimeError, match="embedding unavailable"):
        store.replace(kb_id, original["id"], "guide.md", b"# Changed\n\nDifferent text", "user-a")
    assert (tmp_path / kb_id / "active_revision.json").read_text(encoding="utf-8") == pointer
    assert store.document_text(kb_id, original["id"], "user-a") == "# Original\n\nUseful content"
    assert store.list_documents(kb_id, "user-a")[0]["version"] == 1


def test_document_mutations_enforce_owner_and_source_url(tmp_path: Path) -> None:
    store = KnowledgeBaseStore(tmp_path, FakeEncoder())
    kb_id = store.create("Pets", "user-a")["id"]
    document = store.upload(kb_id, "guide.md", b"# Guide\n\nText", "user-a")
    with pytest.raises(PermissionError):
        store.delete(kb_id, document["id"], "user-b")
    with pytest.raises(PermissionError):
        store.replace(kb_id, document["id"], "guide.md", b"New text", "user-b")
    with pytest.raises(ValueError, match="source URL"):
        store.upload(kb_id, "bad.md", b"Text", "user-a", "file:///private/data")


def test_legacy_document_is_migrated_on_first_replacement(tmp_path: Path) -> None:
    encoder = FakeEncoder()
    store = KnowledgeBaseStore(tmp_path, encoder)
    kb_id = store.create("Legacy", "user-a")["id"]
    document_id = str(uuid.uuid4())
    folder = tmp_path / kb_id
    original = "# Old\n\nLegacy content"
    metadata, chunks = store._prepare_document(
        kb_id,
        document_id,
        "guide.md",
        parse_uploaded_document("guide.md", original.encode()),
        "old-checksum",
        None,
    )
    (folder / "documents").mkdir()
    (folder / "documents" / f"{document_id}.txt").write_text(original, encoding="utf-8")
    (folder / "documents.json").write_text(json.dumps([metadata]), encoding="utf-8")
    (folder / "chunks.json").write_text(json.dumps(chunks), encoding="utf-8")
    BM25Index.build(chunks).save(folder / "bm25.json")
    DenseIndex.build(chunks, encoder).save(folder / "dense.json")

    store.replace(kb_id, document_id, "guide.md", b"# New\n\nMigrated content", "user-a")
    assert (folder / "active_revision.json").exists()
    assert store.document_text(kb_id, document_id, "user-a") == "# New\n\nMigrated content"
    assert store.list_documents(kb_id, "user-a")[0]["version"] == 2


def test_unchanged_chunks_reuse_existing_embeddings(tmp_path: Path) -> None:
    class CountingEncoder(FakeEncoder):
        def __init__(self) -> None:
            self.calls: list[list[str]] = []

        def encode_documents(self, texts: Sequence[str]) -> list[list[float]]:
            self.calls.append(list(texts))
            return super().encode_documents(texts)

    encoder = CountingEncoder()
    store = KnowledgeBaseStore(tmp_path, encoder)
    kb_id = store.create("Reuse", "user-a")["id"]
    first = store.upload(kb_id, "first.md", b"# First\n\nFirst content", "user-a")
    second = store.upload(kb_id, "second.md", b"# Second\n\nSecond content", "user-a")
    assert len(encoder.calls) == 2
    assert len(encoder.calls[1]) == second["chunk_count"]
    store.delete(kb_id, second["id"], "user-a")
    assert len(encoder.calls) == 2
    assert store.document_text(kb_id, first["id"], "user-a")
