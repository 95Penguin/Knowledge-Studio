import json
from collections import Counter
from pathlib import Path
from typing import Any

from app.ingestion.chunking import chunk_document
from app.ingestion.markdown import parse_document


def _read_manifest_value(manifest_path: Path, key: str) -> str:
    prefix = f"{key}:"
    for line in manifest_path.read_text(encoding="utf-8").splitlines():
        if line.startswith(prefix):
            return line.split(":", 1)[1].strip().strip('"')
    raise ValueError(f"Missing {key!r} in {manifest_path}")


def build_corpus(
    raw_dir: Path,
    output_dir: Path,
    max_tokens: int = 450,
    overlap_tokens: int = 60,
    supplemental_dir: Path | None = None,
) -> dict[str, Any]:
    if overlap_tokens >= max_tokens:
        raise ValueError("overlap_tokens must be smaller than max_tokens")
    manifest_path = raw_dir / "CORPUS_MANIFEST.yaml"
    source_root = raw_dir / "source"
    corpus_id = _read_manifest_value(manifest_path, "corpus_id")
    target_version = _read_manifest_value(manifest_path, "target_version")
    expected_files = int(_read_manifest_value(manifest_path, "file_count"))
    paths = sorted(source_root.rglob("*.md"))
    if len(paths) != expected_files:
        raise ValueError(f"Manifest expects {expected_files} Markdown files, found {len(paths)}")

    output_dir.mkdir(parents=True, exist_ok=True)
    documents = [parse_document(path, source_root) for path in paths]
    supplemental_paths = (
        sorted(supplemental_dir.rglob("*.md")) if supplemental_dir and supplemental_dir.is_dir()
        else []
    )
    documents.extend(
        parse_document(path, supplemental_dir, source_path_prefix="engineering/")
        for path in supplemental_paths
    )
    rejected = [document for document in documents if not document.body.strip()]
    accepted = [document for document in documents if document.body.strip()]
    chunks = [
        chunk
        for document in accepted
        for chunk in chunk_document(
            document,
            corpus_id,
            target_version,
            max_tokens=max_tokens,
            overlap_tokens=overlap_tokens,
        )
    ]

    chunks_path = output_dir / "chunks.jsonl"
    with chunks_path.open("w", encoding="utf-8") as file:
        for chunk in chunks:
            file.write(json.dumps(chunk.to_dict(), ensure_ascii=False) + "\n")

    rejected_path = output_dir / "rejected-files.jsonl"
    with rejected_path.open("w", encoding="utf-8") as file:
        for document in rejected:
            file.write(
                json.dumps(
                    {"source_path": document.source_path, "reason": "empty_after_cleaning"},
                    ensure_ascii=False,
                )
                + "\n"
            )

    token_counts = [chunk.approx_tokens for chunk in chunks]
    stats: dict[str, Any] = {
        "corpus_id": corpus_id,
        "target_version": target_version,
        "input_documents": len(documents),
        "accepted_documents": len(accepted),
        "rejected_documents": len(rejected),
        "chunks": len(chunks),
        "max_tokens_setting": max_tokens,
        "overlap_tokens_setting": overlap_tokens,
        "approx_tokens": {
            "min": min(token_counts, default=0),
            "max": max(token_counts, default=0),
            "average": round(sum(token_counts) / len(token_counts), 2) if token_counts else 0,
        },
        "short_chunks_below_25": sum(count < 25 for count in token_counts),
        "oversized_chunks": [
            {
                "chunk_id": chunk.chunk_id,
                "source_path": chunk.source_path,
                "section_path": chunk.section_path,
                "approx_tokens": chunk.approx_tokens,
                "reason": "indivisible_code_or_example_block",
            }
            for chunk in chunks
            if chunk.approx_tokens > max_tokens
        ],
        "document_types": dict(sorted(Counter(c.document_type for c in chunks).items())),
        "source_types": dict(sorted(Counter(c.source_type for c in chunks).items())),
        "removed_version_8_blocks": sum(d.removed_version_blocks for d in documents),
        "removed_product_sections": sum(d.removed_product_sections for d in documents),
        "removed_product_blocks": sum(d.removed_product_blocks for d in documents),
        "removed_irrelevant_sections": sum(d.removed_irrelevant_sections for d in documents),
    }
    (output_dir / "corpus-stats.json").write_text(
        json.dumps(stats, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    sample = _sample_chunks(chunks, 20)
    with (output_dir / "review-sample.jsonl").open("w", encoding="utf-8") as file:
        for chunk in sample:
            preview = chunk.content[:500].replace("\n", " ")
            file.write(
                json.dumps(
                    {
                        "chunk_id": chunk.chunk_id,
                        "title": chunk.title,
                        "section_path": chunk.section_path,
                        "source_path": chunk.source_path,
                        "approx_tokens": chunk.approx_tokens,
                        "preview": preview,
                        "review_status": "pending",
                        "review_notes": "",
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
    return stats


def _sample_chunks(chunks: list[Any], size: int) -> list[Any]:
    if len(chunks) <= size:
        return chunks
    # Deterministic, evenly spaced sampling makes repeated builds comparable.
    return [chunks[round(i * (len(chunks) - 1) / (size - 1))] for i in range(size)]
