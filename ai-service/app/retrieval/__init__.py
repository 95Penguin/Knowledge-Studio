"""Retrieval baselines for the SupportPilot knowledge base."""

from app.retrieval.bm25 import BM25Index
from app.retrieval.models import SearchResult

__all__ = ["BM25Index", "SearchResult"]
