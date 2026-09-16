from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class Document:
    source_path: str
    source_url: str
    title: str
    document_type: str
    front_matter: dict[str, Any]
    body: str
    source_type: str = "official"
    removed_version_blocks: int = 0
    removed_product_sections: int = 0
    removed_product_blocks: int = 0
    removed_irrelevant_sections: int = 0


@dataclass(frozen=True)
class Chunk:
    chunk_id: str
    corpus_id: str
    content: str
    title: str
    section_path: list[str]
    source_path: str
    source_url: str
    target_version: str
    document_type: str
    source_type: str
    chunk_index: int
    approx_tokens: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
