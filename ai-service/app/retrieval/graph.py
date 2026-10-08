"""Heading/entity graph retrieval over a document hierarchy."""

from collections import defaultdict
from typing import Any

from app.observability.trace import trace_stage
from app.retrieval.models import SearchResult
from app.retrieval.tokenizer import tokenize


class HeadingGraphIndex:
    """Connect each chunk to its title and ancestor headings for graph recall."""

    retriever_name = "heading-graph"

    def __init__(self, chunks: list[dict[str, Any]]) -> None:
        self.chunks = chunks
        self.neighbors: dict[str, set[int]] = defaultdict(set)
        self.entity_names: dict[str, str] = {}
        for index, chunk in enumerate(chunks):
            for heading in [chunk["title"], *chunk["section_path"]]:
                key = heading.strip().casefold()
                if key:
                    self.neighbors[key].add(index)
                    self.entity_names[key] = heading

    @property
    def retriever_parameters(self) -> dict[str, int]:
        return {"entity_count": len(self.neighbors), "chunk_count": len(self.chunks)}

    def search(self, query: str, top_k: int = 5) -> list[SearchResult]:
        if top_k < 1:
            raise ValueError("top_k must be positive")
        query_terms = set(tokenize(query))
        scores: dict[int, float] = defaultdict(float)
        matches: dict[int, list[str]] = defaultdict(list)
        with trace_stage("graph_search"):
            for key, indices in self.neighbors.items():
                entity_terms = set(tokenize(key))
                overlap = query_terms & entity_terms
                if not overlap or not entity_terms:
                    continue
                # Complete heading matches are stronger than a generic shared term.
                strength = len(overlap) / len(entity_terms)
                if strength < 0.5:
                    continue
                for index in indices:
                    scores[index] += strength
                    matches[index].append(self.entity_names[key])
            ranked = sorted(scores.items(), key=lambda item: (-item[1], item[0]))[:top_k]
        return [
            SearchResult(
                rank=rank, score=score, chunk_id=self.chunks[index]["chunk_id"],
                title=self.chunks[index]["title"],
                section_path=self.chunks[index]["section_path"],
                source_path=self.chunks[index]["source_path"],
                source_url=self.chunks[index]["source_url"],
                content=self.chunks[index]["content"],
                source_type=self.chunks[index].get("source_type", "official"),
                retrieval_details={"matched_entities": matches[index]},
            )
            for rank, (index, score) in enumerate(ranked, 1)
        ]
