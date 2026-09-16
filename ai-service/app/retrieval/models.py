from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class SearchResult:
    rank: int
    score: float
    chunk_id: str
    title: str
    section_path: list[str]
    source_path: str
    source_url: str
    content: str
    source_type: str = "official"
    retrieval_details: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        result = {
            "rank": self.rank,
            "score": round(self.score, 6),
            "chunk_id": self.chunk_id,
            "title": self.title,
            "section_path": self.section_path,
            "source_path": self.source_path,
            "source_url": self.source_url,
            "source_type": self.source_type,
            "content": self.content,
        }
        if self.retrieval_details is not None:
            result["retrieval_details"] = self.retrieval_details
        return result
