"""Owned knowledge bases with versioned, all-or-nothing local index snapshots."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import tempfile
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from app.ingestion.chunking import chunk_document
from app.ingestion.models import Document
from app.ingestion.uploaded import ParsedUpload, parse_uploaded_document
from app.retrieval.bm25 import BM25Index
from app.retrieval.dense import DenseIndex, EmbeddingEncoder, document_embedding_text
from app.retrieval.graph import HeadingGraphIndex
from app.retrieval.hybrid import MultiRouteRRFRetriever
from app.retrieval.models import SearchResult

logger = logging.getLogger(__name__)


class KnowledgeBaseStore:
    def __init__(
        self,
        root: Path,
        encoder: EmbeddingEncoder,
        max_revisions: int = 3,
    ) -> None:
        if max_revisions < 2:
            raise ValueError("max_revisions must retain at least the active and previous version")
        self.root = root
        self.encoder = encoder
        self.max_revisions = max_revisions
        self._lock = threading.RLock()
        self._index_cache: dict[Path, tuple[BM25Index, DenseIndex, HeadingGraphIndex]] = {}
        self.root.mkdir(parents=True, exist_ok=True)

    def create(self, name: str, owner_id: str, description: str = "") -> dict[str, Any]:
        name, description = self._validated_metadata(name, description)
        with self._lock:
            kb_id = str(uuid.uuid4())
            folder = self.root / kb_id
            folder.mkdir()
            metadata = {
                "id": kb_id,
                "name": name,
                "description": description,
                "owner_id": owner_id,
                "document_count": 0,
            }
            self._atomic_json(folder / "metadata.json", metadata)
            return metadata

    def list(self, owner_id: str) -> list[dict[str, Any]]:
        with self._lock:
            items = []
            for path in sorted(self.root.glob("*/metadata.json")):
                metadata = self._read_json(path)
                if metadata.get("owner_id") == owner_id:
                    metadata["document_count"] = len(self._documents(self._active(path.parent)))
                    items.append(metadata)
            return items

    def update(self, kb_id: str, owner_id: str, name: str, description: str = "") -> dict[str, Any]:
        name, description = self._validated_metadata(name, description)
        with self._lock:
            folder = self._owned_folder(kb_id, owner_id)
            path = folder / "metadata.json"
            metadata = self._read_json(path)
            metadata.update(
                {
                    "name": name,
                    "description": description,
                    "document_count": len(self._documents(self._active(folder))),
                }
            )
            self._atomic_json(path, metadata)
            return metadata

    def list_documents(self, kb_id: str, owner_id: str) -> list[dict[str, Any]]:
        with self._lock:
            return self._documents(self._active(self._owned_folder(kb_id, owner_id)))

    def outline(self, kb_id: str, owner_id: str) -> list[dict[str, Any]]:
        """Return the active document/section hierarchy, scoped to the owner."""
        with self._lock:
            active = self._active(self._owned_folder(kb_id, owner_id))
            chunks = self._chunks(active)
            documents = []
            for document in self._documents(active):
                sections = list(
                    dict.fromkeys(
                        " > ".join(chunk["section_path"])
                        for chunk in chunks
                        if self._is_document_chunk(chunk, kb_id, document["id"])
                    )
                )
                documents.append(
                    {
                        "document_id": document["id"],
                        "filename": document["filename"],
                        "sections": sections[:100],
                    }
                )
            return documents

    def read_section(
        self,
        kb_id: str,
        owner_id: str,
        document_id: str,
        section: str,
        limit: int = 4,
    ) -> list[SearchResult]:
        """Read existing indexed chunks; never fetch an arbitrary path or URL."""
        section = section.strip().casefold()
        if not section or not 1 <= limit <= 8:
            raise ValueError("section and limit are invalid")
        with self._lock:
            active = self._active(self._owned_folder(kb_id, owner_id))
            documents = {item["id"] for item in self._documents(active)}
            if document_id not in documents:
                raise FileNotFoundError("document not found")
            matches = [
                chunk
                for chunk in self._chunks(active)
                if self._is_document_chunk(chunk, kb_id, document_id)
                and any(section in title.casefold() for title in chunk["section_path"])
            ]
            matches.sort(key=lambda item: item["chunk_index"])
            return [
                self._as_search_result(chunk, rank) for rank, chunk in enumerate(matches[:limit], 1)
            ]

    def read_neighbors(
        self,
        kb_id: str,
        owner_id: str,
        chunk_id: str,
        radius: int = 1,
    ) -> list[SearchResult]:
        if not 0 <= radius <= 2:
            raise ValueError("radius must be between 0 and 2")
        with self._lock:
            active = self._active(self._owned_folder(kb_id, owner_id))
            chunks = self._chunks(active)
            target = next((item for item in chunks if item["chunk_id"] == chunk_id), None)
            if target is None:
                raise FileNotFoundError("chunk not found")
            same_document = sorted(
                (item for item in chunks if item["source_path"] == target["source_path"]),
                key=lambda item: item["chunk_index"],
            )
            position = next(
                index for index, item in enumerate(same_document) if item["chunk_id"] == chunk_id
            )
            neighborhood = same_document[max(0, position - radius) : position + radius + 1]
            return [
                self._as_search_result(chunk, rank) for rank, chunk in enumerate(neighborhood, 1)
            ]

    @staticmethod
    def _as_search_result(chunk: dict[str, Any], rank: int) -> SearchResult:
        return SearchResult(
            rank=rank,
            score=0.5,
            chunk_id=chunk["chunk_id"],
            title=chunk["title"],
            section_path=chunk["section_path"],
            source_path=chunk["source_path"],
            source_url=chunk["source_url"],
            content=chunk["content"],
            source_type=chunk.get("source_type", "uploaded"),
            retrieval_details={"route": "section_read"},
        )

    def assert_owned(self, kb_ids: list[str] | tuple[str, ...], owner_id: str) -> None:
        for kb_id in kb_ids:
            metadata = self._read_json(self._folder(kb_id) / "metadata.json")
            if metadata.get("owner_id") != owner_id:
                raise PermissionError("knowledge base does not belong to current user")

    def upload(
        self,
        kb_id: str,
        filename: str,
        content: bytes,
        owner_id: str,
        source_url: str | None = None,
    ) -> dict[str, Any]:
        self.assert_owned([kb_id], owner_id)
        parsed = parse_uploaded_document(filename, content)
        source_url = self._validated_source_url(source_url)
        checksum = hashlib.sha256(content).hexdigest()
        with self._lock:
            folder = self._owned_folder(kb_id, owner_id)
            active = self._active(folder)
            documents = self._documents(active)
            for existing in documents:
                if existing["filename"] == filename:
                    if existing.get("sha256") == checksum:
                        return existing
                    raise ValueError("filename already exists; replace the document instead")
            document_id = str(uuid.uuid4())
            metadata, chunks = self._prepare_document(
                kb_id,
                document_id,
                filename,
                parsed,
                checksum,
                source_url,
            )
            self._publish(
                folder,
                active,
                documents + [metadata],
                self._chunks(active) + chunks,
                {document_id: parsed.body},
            )
            return metadata

    def replace(
        self,
        kb_id: str,
        document_id: str,
        filename: str,
        content: bytes,
        owner_id: str,
        source_url: str | None = None,
    ) -> dict[str, Any]:
        document_id = str(uuid.UUID(document_id))
        self.assert_owned([kb_id], owner_id)
        parsed = parse_uploaded_document(filename, content)
        source_url = self._validated_source_url(source_url)
        checksum = hashlib.sha256(content).hexdigest()
        with self._lock:
            folder = self._owned_folder(kb_id, owner_id)
            active = self._active(folder)
            documents = self._documents(active)
            old = next((item for item in documents if item["id"] == document_id), None)
            if old is None:
                raise FileNotFoundError("document not found")
            if any(
                item["filename"] == filename and item["id"] != document_id for item in documents
            ):
                raise ValueError("another document already uses this filename")
            if source_url is None:
                source_url = old.get("origin_url")
            metadata, chunks = self._prepare_document(
                kb_id,
                document_id,
                filename,
                parsed,
                checksum,
                source_url,
                version=int(old.get("version", 1)) + 1,
                created_at=old.get("created_at"),
            )
            updated_documents = [
                metadata if item["id"] == document_id else item for item in documents
            ]
            updated_chunks = [
                chunk
                for chunk in self._chunks(active)
                if not self._is_document_chunk(chunk, kb_id, document_id)
            ] + chunks
            self._publish(
                folder, active, updated_documents, updated_chunks, {document_id: parsed.body}
            )
            return metadata

    def delete(self, kb_id: str, document_id: str, owner_id: str) -> None:
        document_id = str(uuid.UUID(document_id))
        with self._lock:
            folder = self._owned_folder(kb_id, owner_id)
            active = self._active(folder)
            documents = self._documents(active)
            if not any(item["id"] == document_id for item in documents):
                raise FileNotFoundError("document not found")
            self._publish(
                folder,
                active,
                [item for item in documents if item["id"] != document_id],
                [
                    chunk
                    for chunk in self._chunks(active)
                    if not self._is_document_chunk(chunk, kb_id, document_id)
                ],
                {},
            )

    def document_text(self, kb_id: str, document_id: str, owner_id: str) -> str:
        document_id = str(uuid.UUID(document_id))
        with self._lock:
            active = self._active(self._owned_folder(kb_id, owner_id))
            if not any(item["id"] == document_id for item in self._documents(active)):
                raise FileNotFoundError("document not found")
            path = active / "documents" / f"{document_id}.txt"
            if not path.is_file():
                raise FileNotFoundError("document content not found")
            return path.read_text(encoding="utf-8")

    def search(
        self, query: str, top_k: int = 5, knowledge_base_ids: tuple[str, ...] = ()
    ) -> list[SearchResult]:
        results: list[SearchResult] = []
        with self._lock:
            folders = [path.parent for path in self.root.glob("*/metadata.json")]
            if knowledge_base_ids:
                allowed = {self._folder(kb_id) for kb_id in knowledge_base_ids}
                folders = [folder for folder in folders if folder in allowed]
            for folder in folders:
                active = self._active(folder)
                if not (active / "bm25.json").is_file():
                    continue
                indexes = self._index_cache.get(active)
                if indexes is None:
                    bm25 = BM25Index.load(active / "bm25.json")
                    dense = DenseIndex.load(active / "dense.json", self.encoder)
                    indexes = (bm25, dense, HeadingGraphIndex(bm25.documents))
                    self._index_cache[active] = indexes
                bm25, dense, graph = indexes
                results.extend(
                    MultiRouteRRFRetriever(
                        {
                            "bm25": (bm25, 1.0),
                            "dense": (dense, 1.0),
                            "graph": (graph, 0.5),
                        }
                    ).search(query, top_k=top_k)
                )
        results.sort(key=lambda item: (-item.score, item.chunk_id))
        return [
            SearchResult(
                rank=index,
                score=item.score,
                chunk_id=item.chunk_id,
                title=item.title,
                section_path=item.section_path,
                source_path=item.source_path,
                source_url=item.source_url,
                content=item.content,
                source_type=item.source_type,
                retrieval_details=item.retrieval_details,
            )
            for index, item in enumerate(results[:top_k], 1)
        ]

    def _prepare_document(
        self,
        kb_id: str,
        document_id: str,
        filename: str,
        parsed: ParsedUpload,
        checksum: str,
        source_url: str | None,
        version: int = 1,
        created_at: str | None = None,
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        safe_name = re.sub(r"[^\w.\-]+", "_", Path(filename).name)[:100]
        source_path = f"{kb_id}/{document_id}-{safe_name}"
        citation_url = source_url or f"/api/knowledge-bases/{kb_id}/documents/{document_id}/content"
        document = Document(
            source_path=source_path,
            source_url=citation_url,
            title=Path(filename).stem[:100],
            document_type="uploaded",
            front_matter={},
            body=parsed.body,
            source_type="uploaded",
        )
        chunks = [item.to_dict() for item in chunk_document(document, kb_id, "uploaded")]
        if not chunks:
            raise ValueError("document did not produce searchable chunks")
        now = datetime.now(UTC).isoformat()
        metadata = {
            "id": document_id,
            "filename": filename,
            "chunk_count": len(chunks),
            "sha256": checksum,
            "extraction_method": parsed.extraction_method,
            "page_count": parsed.page_count,
            "ocr_page_count": parsed.ocr_page_count,
            "origin_url": source_url,
            "version": version,
            "created_at": created_at or now,
            "updated_at": now,
        }
        return metadata, chunks

    def _publish(
        self,
        folder: Path,
        active: Path,
        documents: list[dict[str, Any]],
        chunks: list[dict[str, Any]],
        new_texts: dict[str, str],
    ) -> None:
        revisions = folder / "revisions"
        revisions.mkdir(exist_ok=True)
        revision_id = str(uuid.uuid4())
        final = revisions / revision_id
        stage = Path(tempfile.mkdtemp(prefix=".pending-", dir=revisions))
        committed = False
        try:
            (stage / "documents").mkdir()
            for item in documents:
                document_id = item["id"]
                destination = stage / "documents" / f"{document_id}.txt"
                if document_id in new_texts:
                    destination.write_text(new_texts[document_id], encoding="utf-8")
                else:
                    shutil.copyfile(active / "documents" / f"{document_id}.txt", destination)
            (stage / "documents.json").write_text(
                json.dumps(documents, ensure_ascii=False), encoding="utf-8"
            )
            (stage / "chunks.json").write_text(
                json.dumps(chunks, ensure_ascii=False), encoding="utf-8"
            )
            if chunks:
                BM25Index.build(chunks).save(stage / "bm25.json")
                self._dense_with_reuse(chunks, active).save(stage / "dense.json")
            os.replace(stage, final)
            self._atomic_json(folder / "active_revision.json", {"revision": revision_id})
            committed = True
            self._index_cache.clear()
        finally:
            if stage.exists():
                shutil.rmtree(stage)
            if not committed and final.exists():
                shutil.rmtree(final)
        try:
            self._prune_revisions(revisions, final)
        except OSError:
            logger.exception("could not prune old knowledge-base revisions")

    def _prune_revisions(self, revisions: Path, active: Path) -> None:
        """Keep the active snapshot and the latest rollback candidates."""
        candidates = sorted(
            (
                path
                for path in revisions.iterdir()
                if path.is_dir() and not path.is_symlink() and self._is_revision_name(path.name)
            ),
            key=lambda path: path.stat().st_mtime_ns,
            reverse=True,
        )
        retained = {
            active,
            *[path for path in candidates if path != active][: self.max_revisions - 1],
        }
        for path in candidates:
            if path not in retained:
                shutil.rmtree(path)

    @staticmethod
    def _is_revision_name(name: str) -> bool:
        try:
            return str(uuid.UUID(name)) == name
        except ValueError:
            return False

    def _dense_with_reuse(self, chunks: list[dict[str, Any]], active: Path) -> DenseIndex:
        old_vectors: dict[str, list[float]] = {}
        if (active / "dense.json").is_file():
            try:
                old = DenseIndex.load(active / "dense.json", self.encoder)
                old_vectors = {
                    document_embedding_text(document): vector
                    for document, vector in zip(old.documents, old.embeddings, strict=True)
                }
            except ValueError:
                pass  # A model/revision change requires re-embedding every active chunk.
        texts = [document_embedding_text(chunk) for chunk in chunks]
        missing = list(dict.fromkeys(text for text in texts if text not in old_vectors))
        if missing:
            old_vectors.update(zip(missing, self.encoder.encode_documents(missing), strict=True))
        return DenseIndex(chunks, [old_vectors[text] for text in texts], self.encoder)

    @staticmethod
    def _is_document_chunk(chunk: dict[str, Any], kb_id: str, document_id: str) -> bool:
        return chunk["source_path"].startswith(f"{kb_id}/{document_id}-")

    @staticmethod
    def _documents(active: Path) -> list[dict[str, Any]]:
        path = active / "documents.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else []

    @staticmethod
    def _chunks(active: Path) -> list[dict[str, Any]]:
        path = active / "chunks.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else []

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any]:
        return json.loads(path.read_text(encoding="utf-8"))

    @staticmethod
    def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, prefix=".pending-", delete=False
        ) as handle:
            temporary = Path(handle.name)
            json.dump(payload, handle, ensure_ascii=False)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)

    @staticmethod
    def _validated_metadata(name: str, description: str) -> tuple[str, str]:
        name, description = name.strip(), description.strip()
        if not name or len(name) > 100:
            raise ValueError("knowledge base name must be 1-100 characters")
        if len(description) > 500:
            raise ValueError("knowledge base description must be at most 500 characters")
        return name, description

    @staticmethod
    def _validated_source_url(source_url: str | None) -> str | None:
        if not source_url or not source_url.strip():
            return None
        source_url = source_url.strip()
        parsed = urlsplit(source_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc or len(source_url) > 2048:
            raise ValueError("source URL must be an HTTP(S) URL of at most 2048 characters")
        return source_url

    def _active(self, folder: Path) -> Path:
        pointer = folder / "active_revision.json"
        if not pointer.is_file():
            return folder  # Existing knowledge bases retain their pre-migration layout.
        revision = str(uuid.UUID(self._read_json(pointer)["revision"]))
        active = folder / "revisions" / revision
        if not active.is_dir():
            raise RuntimeError("knowledge base active revision is missing")
        return active

    def _owned_folder(self, kb_id: str, owner_id: str) -> Path:
        folder = self._folder(kb_id)
        self.assert_owned([kb_id], owner_id)
        return folder

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
