"""Small local knowledge-base store with upload, chunking and searchable indexes."""

from __future__ import annotations

import io
import json
import re
import threading
import uuid
from pathlib import Path
from typing import Any

from app.ingestion.chunking import chunk_document
from app.ingestion.models import Document
from app.retrieval.bm25 import BM25Index
from app.retrieval.dense import DenseIndex, EmbeddingEncoder
from app.retrieval.graph import HeadingGraphIndex
from app.retrieval.hybrid import MultiRouteRRFRetriever
from app.retrieval.models import SearchResult


class KnowledgeBaseStore:
    def __init__(self, root: Path, encoder: EmbeddingEncoder) -> None:
        self.root = root
        self.encoder = encoder
        self._lock = threading.RLock()
        self.root.mkdir(parents=True, exist_ok=True)

    def create(self, name: str, owner_id: str, description: str = "") -> dict[str, Any]:
        name = name.strip()
        if not name or len(name) > 100:
            raise ValueError("knowledge base name must be 1-100 characters")
        description = description.strip()
        if len(description) > 500:
            raise ValueError("knowledge base description must be at most 500 characters")
        with self._lock:
            kb_id = str(uuid.uuid4())
            folder = self.root / kb_id
            folder.mkdir()
            metadata = {
                "id": kb_id, "name": name, "description": description,
                "owner_id": owner_id, "document_count": 0,
            }
            (folder / "metadata.json").write_text(json.dumps(metadata, ensure_ascii=False), encoding="utf-8")
            return metadata

    def list(self, owner_id: str) -> list[dict[str, Any]]:
        items = []
        for path in sorted(self.root.glob("*/metadata.json")):
            metadata = json.loads(path.read_text(encoding="utf-8"))
            if metadata.get("owner_id") == owner_id:
                items.append(metadata)
        return items

    def update(
        self, kb_id: str, owner_id: str, name: str, description: str = ""
    ) -> dict[str, Any]:
        name = name.strip()
        description = description.strip()
        if not name or len(name) > 100:
            raise ValueError("knowledge base name must be 1-100 characters")
        if len(description) > 500:
            raise ValueError("knowledge base description must be at most 500 characters")
        self.assert_owned([kb_id], owner_id)
        with self._lock:
            metadata_path = self._folder(kb_id) / "metadata.json"
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            metadata.update({"name": name, "description": description})
            metadata_path.write_text(
                json.dumps(metadata, ensure_ascii=False), encoding="utf-8"
            )
        return metadata

    def list_documents(self, kb_id: str, owner_id: str) -> list[dict[str, Any]]:
        self.assert_owned([kb_id], owner_id)
        path = self._folder(kb_id) / "documents.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else []

    def assert_owned(self, kb_ids: list[str] | tuple[str, ...], owner_id: str) -> None:
        for kb_id in kb_ids:
            metadata = json.loads((self._folder(kb_id) / "metadata.json").read_text(encoding="utf-8"))
            if metadata.get("owner_id") != owner_id:
                raise PermissionError("knowledge base does not belong to current user")

    def upload(
        self, kb_id: str, filename: str, content: bytes, owner_id: str
    ) -> dict[str, Any]:
        self.assert_owned([kb_id], owner_id)
        folder = self._folder(kb_id)
        extension = Path(filename).suffix.lower()
        if extension not in {".md", ".txt", ".pdf"}:
            raise ValueError("supported document formats: .md, .txt, .pdf")
        if not content or len(content) > 10 * 1024 * 1024:
            raise ValueError("document must be non-empty and at most 10 MiB")
        if extension == ".pdf":
            try:
                from pypdf import PdfReader
            except ImportError as error:
                raise RuntimeError("PDF parsing requires pypdf") from error
            pages = [page.extract_text() or "" for page in PdfReader(io.BytesIO(content)).pages]
            body = "\n\n".join(f"## Page {index}\n{text}" for index, text in enumerate(pages, 1))
        else:
            body = content.decode("utf-8-sig")
        if not body.strip():
            raise ValueError("document contains no extractable text")
        safe_name = re.sub(r"[^\w.\-]+", "_", Path(filename).name)[:100]
        document_id = str(uuid.uuid4())
        source_path = f"{kb_id}/{document_id}-{safe_name}"
        document = Document(
            source_path=source_path,
            source_url=f"/api/knowledge-bases/{kb_id}/documents/{document_id}/content",
            title=Path(filename).stem[:100], document_type="uploaded",
            front_matter={}, body=body, source_type="uploaded",
        )
        chunks = [item.to_dict() for item in chunk_document(document, kb_id, "uploaded")]
        if not chunks:
            raise ValueError("document did not produce searchable chunks")
        with self._lock:
            documents_dir = folder / "documents"
            documents_dir.mkdir(exist_ok=True)
            (documents_dir / f"{document_id}.txt").write_text(body, encoding="utf-8")
            chunks_path = folder / "chunks.json"
            existing = json.loads(chunks_path.read_text(encoding="utf-8")) if chunks_path.exists() else []
            all_chunks = existing + chunks
            BM25Index.build(all_chunks).save(folder / "bm25.json")
            DenseIndex.build(all_chunks, self.encoder).save(folder / "dense.json")
            chunks_path.write_text(json.dumps(all_chunks, ensure_ascii=False), encoding="utf-8")
            documents_path = folder / "documents.json"
            documents = (
                json.loads(documents_path.read_text(encoding="utf-8"))
                if documents_path.exists() else []
            )
            document_metadata = {
                "id": document_id, "filename": filename, "chunk_count": len(chunks)
            }
            documents.append(document_metadata)
            documents_path.write_text(
                json.dumps(documents, ensure_ascii=False), encoding="utf-8"
            )
            metadata_path = folder / "metadata.json"
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            metadata["document_count"] = len(documents)
            metadata_path.write_text(json.dumps(metadata, ensure_ascii=False), encoding="utf-8")
        return document_metadata

    def document_text(self, kb_id: str, document_id: str, owner_id: str) -> str:
        self.assert_owned([kb_id], owner_id)
        folder = self._folder(kb_id)
        path = folder / "documents" / f"{uuid.UUID(document_id)}.txt"
        if not path.is_file():
            raise FileNotFoundError("document not found")
        return path.read_text(encoding="utf-8")

    def search(
        self, query: str, top_k: int = 5, knowledge_base_ids: tuple[str, ...] = ()
    ) -> list[SearchResult]:
        results: list[SearchResult] = []
        with self._lock:
            folders = [path.parent for path in self.root.glob("*/chunks.json")]
            if knowledge_base_ids:
                allowed = {self._folder(kb_id) for kb_id in knowledge_base_ids}
                folders = [folder for folder in folders if folder in allowed]
            for folder in folders:
                bm25 = BM25Index.load(folder / "bm25.json")
                dense = DenseIndex.load(folder / "dense.json", self.encoder)
                graph = HeadingGraphIndex(bm25.documents)
                results.extend(MultiRouteRRFRetriever({
                    "bm25": (bm25, 1.0), "dense": (dense, 1.0), "graph": (graph, 0.5),
                }).search(query, top_k=top_k))
        results.sort(key=lambda item: (-item.score, item.chunk_id))
        return [
            SearchResult(
                rank=index, score=item.score, chunk_id=item.chunk_id, title=item.title,
                section_path=item.section_path, source_path=item.source_path,
                source_url=item.source_url, content=item.content, source_type=item.source_type,
                retrieval_details=item.retrieval_details,
            )
            for index, item in enumerate(results[:top_k], 1)
        ]

    def _folder(self, kb_id: str) -> Path:
        try:
            safe_id = str(uuid.UUID(kb_id))
        except ValueError as error:
            raise ValueError("invalid knowledge base ID") from error
        folder = self.root / safe_id
        if not (folder / "metadata.json").is_file():
            raise FileNotFoundError("knowledge base not found")
        return folder


class KnowledgeCorpusRetriever:
    """Fuse the built-in demonstration corpus with uploaded knowledge bases."""

    retriever_name = "built-in-and-uploaded"

    def __init__(self, built_in: Any, uploaded: KnowledgeBaseStore) -> None:
        self.built_in = built_in
        self.uploaded = uploaded

    @property
    def retriever_parameters(self) -> dict[str, str]:
        return {"built_in": getattr(self.built_in, "retriever_name", "unknown")}

    def search(self, query: str, top_k: int = 5) -> list[SearchResult]:
        return self.built_in.search(query, top_k)

    def search_scoped(
        self, query: str, top_k: int, knowledge_base_ids: tuple[str, ...]
    ) -> list[SearchResult]:
        if knowledge_base_ids:
            return self.uploaded.search(query, top_k, knowledge_base_ids)
        return self.search(query, top_k)
