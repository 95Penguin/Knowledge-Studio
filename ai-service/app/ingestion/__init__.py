"""Document ingestion for the SupportPilot knowledge base."""

from app.ingestion.models import Chunk, Document
from app.ingestion.pipeline import build_corpus

__all__ = ["Chunk", "Document", "build_corpus"]
