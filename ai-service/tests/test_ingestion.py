import json
from pathlib import Path

from app.ingestion.chunking import approximate_token_count, chunk_document, split_blocks
from app.ingestion.markdown import clean_markdown, parse_document, parse_front_matter


def test_parse_front_matter() -> None:
    metadata, body = parse_front_matter("---\ntitle: Redis persistence\ncategories:\n- docs\n---\nBody")
    assert metadata == {"title": "Redis persistence", "categories": ["docs"]}
    assert body == "Body"


def test_cleaning_removes_product_section_and_redis_8_block() -> None:
    source = """Intro for Redis 7.4.

Added in Redis 8.10, this field is new.

Starting with version 8.0, this other behavior is new.

## Redis Software and Redis Cloud compatibility

Cloud-only table.

## Return information

Useful response.
"""
    result = clean_markdown(source)
    assert "Intro for Redis 7.4" in result.text
    assert "Redis 8.10" not in result.text
    assert "Cloud-only" not in result.text
    assert "Return information" in result.text
    assert "version 8.0" not in result.text
    assert result.removed_version_blocks == 2
    assert result.removed_product_sections == 1


def test_split_blocks_keeps_fenced_code_together() -> None:
    blocks = split_blocks("Before\n\n```\nline one\n\nline two\n```\n\nAfter")
    assert len(blocks) == 3
    assert "line one\n\nline two" in blocks[1]


def test_cleaning_preserves_command_placeholders_and_removes_duplicate_tabs() -> None:
    source = "Set <key> to <value>. See [`SET`]({{< relref \"/commands/set\" >}}).\n\nSame.\n\nSame."
    result = clean_markdown(source)
    assert "<key>" in result.text
    assert "<value>" in result.text
    assert "[`SET`]()" not in result.text
    assert "`SET`" in result.text
    assert result.text.count("Same.") == 1


def test_cleaning_removes_product_promotion_and_irrelevant_crc_appendix() -> None:
    source = """Useful Redis Open Source text.

Consider Redis Software's persistence options instead.

## Appendix

Useful appendix introduction.

### Appendix A: CRC16 reference implementation in ANSI C

uint16_t crc16(void) {}

## Operations

Useful operations.
"""
    result = clean_markdown(source)
    assert "Useful Redis Open Source text" in result.text
    assert "Redis Software" not in result.text
    assert "crc16" not in result.text
    assert "Useful operations" in result.text
    assert result.removed_product_blocks == 1
    assert result.removed_irrelevant_sections == 1


def test_cleaning_removes_obsolete_redis_22_hash_storage_section() -> None:
    source = """## Use hashes when possible

Small hashes use compact encodings.

## Using hashes to abstract a very memory-efficient plain key-value store on top of Redis

This Redis 2.2 example requires hash-max-zipmap-entries.

## Memory allocation

Current guidance.
"""
    result = clean_markdown(source)
    assert "Small hashes use compact encodings" in result.text
    assert "Redis 2.2" not in result.text
    assert "hash-max-zipmap" not in result.text
    assert "Current guidance" in result.text
    assert result.removed_irrelevant_sections == 1


def test_chunk_has_traceable_metadata(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    path = source_root / "content/commands/info.md"
    path.parent.mkdir(parents=True)
    path.write_text(
        "---\ntitle: INFO\n---\nIntroduction.\n\n## Server section\n\nServer details.",
        encoding="utf-8",
    )
    document = parse_document(path, source_root)
    chunks = chunk_document(document, "redis-test", "7.4", max_tokens=30, overlap_tokens=5)
    assert chunks
    assert chunks[-1].section_path == ["Server section"]
    assert chunks[-1].source_path == "content/commands/info.md"
    assert chunks[-1].source_url.endswith("/commands/info/")
    assert chunks[-1].approx_tokens == approximate_token_count(chunks[-1].content)


def test_generated_chunk_is_json_serializable(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    path = source_root / "content/example.md"
    path.parent.mkdir(parents=True)
    path.write_text("---\ntitle: Example\n---\nText", encoding="utf-8")
    chunk = chunk_document(parse_document(path, source_root), "test", "7.4")[0]
    assert json.loads(json.dumps(chunk.to_dict()))["title"] == "Example"
