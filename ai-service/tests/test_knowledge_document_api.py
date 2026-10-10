from collections.abc import Sequence
from pathlib import Path

from fastapi.testclient import TestClient

from app.generation.runtime import get_knowledge_base_store
from app.knowledge_bases import KnowledgeBaseStore
from app.main import app


class Encoder:
    model_name = "test"
    model_revision = "v1"
    dimension = 2

    def encode_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return [[1.0, 0.0] for _ in texts]

    def encode_queries(self, texts: Sequence[str]) -> list[list[float]]:
        return [[1.0, 0.0] for _ in texts]


def test_document_upload_replace_delete_routes(tmp_path: Path, monkeypatch) -> None:
    store = KnowledgeBaseStore(tmp_path, Encoder())
    kb_id = store.create("Docs", "user-a")["id"]
    monkeypatch.setattr("app.main._current_user_id", lambda _authorization: "user-a")
    app.dependency_overrides[get_knowledge_base_store] = lambda: store
    try:
        client = TestClient(app)
        base = f"/api/knowledge-bases/{kb_id}/documents"
        uploaded = client.post(
            base,
            data={"source_url": "https://example.org/guide"},
            files={"file": ("guide.html", b"<h1>Guide</h1><p>First version</p>", "text/html")},
        )
        assert uploaded.status_code == 200
        document_id = uploaded.json()["id"]
        assert uploaded.json()["origin_url"] == "https://example.org/guide"
        assert client.get(base).json()[0]["id"] == document_id

        replaced = client.put(
            f"{base}/{document_id}",
            files={"file": ("guide.html", b"<h1>Guide</h1><p>Second version</p>", "text/html")},
        )
        assert replaced.status_code == 200
        assert replaced.json()["version"] == 2
        assert replaced.json()["origin_url"] == "https://example.org/guide"
        assert client.get(f"{base}/{document_id}/content").text.find("Second version") > -1

        assert client.delete(f"{base}/{document_id}").json() == {"status": "deleted"}
        assert client.get(base).json() == []
        assert client.get(f"{base}/{document_id}/content").status_code == 404
        assert client.get("/api/knowledge-bases/not-a-uuid/documents").status_code == 400
    finally:
        app.dependency_overrides.clear()
