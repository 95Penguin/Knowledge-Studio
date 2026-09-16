import html
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.ingestion.models import Document

FRONT_MATTER_BOUNDARY = "---"
HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
HUGO_DIRECTIVE_RE = re.compile(r"{{[<%].*?[>%]}}", re.DOTALL)
# Only remove known presentation tags. Redis command placeholders such as
# <key>, <value>, and <master-name> are meaningful text, not HTML.
HTML_TAG_RE = re.compile(
    r"</?(?:a|br|div|nobr|span|table|tbody|td|th|thead|tr)(?:\s+[^>]*)?/?>",
    re.IGNORECASE,
)
MARKDOWN_LINK_RE = re.compile(r"\[([^\]]+)]\(([^)]*)\)")
REFERENCE_LINK_RE = re.compile(r"^\[[^\]]+]:\s+\S+\s*$", re.MULTILINE)
VERSION_8_RE = re.compile(
    r"\b(?:added|available|introduced|starting|since|beginning)\s+(?:with|in|from)?\s*"
    r"(?:Redis(?:\s+Open\s+Source)?\s+)?(?:version\s+)?8(?:\.\d+){0,2}\b"
    r"|\bRedis\s+Open\s+Source\s+8\.x\b",
    re.IGNORECASE,
)
PRODUCT_HEADING_RE = re.compile(
    r"^#{1,6}\s+Redis\s+(?:Software\s+and\s+Redis\s+Cloud|Enterprise|Cloud)\b",
    re.IGNORECASE,
)
PRODUCT_BLOCK_RE = re.compile(r"\bRedis\s+(?:Software|Cloud|Enterprise)\b", re.IGNORECASE)
IRRELEVANT_HEADING_RE = re.compile(
    r"^#{1,6}\s+(?:"
    r"Appendix A:\s+CRC16 reference implementation in ANSI C"
    r"|Using hashes to abstract a very memory-efficient plain key-value store on top of Redis"
    r")\s*$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class CleaningResult:
    text: str
    removed_version_blocks: int
    removed_product_sections: int
    removed_product_blocks: int
    removed_irrelevant_sections: int


def parse_front_matter(text: str) -> tuple[dict[str, Any], str]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != FRONT_MATTER_BOUNDARY:
        return {}, text

    try:
        end = next(i for i in range(1, len(lines)) if lines[i].strip() == FRONT_MATTER_BOUNDARY)
    except StopIteration:
        return {}, text

    metadata: dict[str, Any] = {}
    current_list: str | None = None
    for line in lines[1:end]:
        if re.match(r"^\s*-\s+", line) and current_list:
            value = re.sub(r"^\s*-\s+", "", line).strip().strip('"\'')
            metadata[current_list].append(value)
            continue
        match = re.match(r"^([A-Za-z_][\w-]*):\s*(.*)$", line)
        if not match:
            current_list = None
            continue
        key, raw_value = match.groups()
        if raw_value == "":
            metadata[key] = []
            current_list = key
        else:
            metadata[key] = _parse_scalar(raw_value)
            current_list = None
    return metadata, "\n".join(lines[end + 1 :]).strip()


def _parse_scalar(value: str) -> Any:
    value = value.strip().strip('"\'')
    if value.lower() in {"true", "false"}:
        return value.lower() == "true"
    if re.fullmatch(r"-?\d+", value):
        return int(value)
    return value


def _remove_heading_sections(text: str, heading_pattern: re.Pattern[str]) -> tuple[str, int]:
    lines = text.splitlines()
    kept: list[str] = []
    skipped = 0
    skip_level: int | None = None
    in_code = False
    for line in lines:
        if line.strip().startswith("```"):
            in_code = not in_code
        heading = None if in_code else HEADING_RE.match(line)
        if skip_level is not None:
            if heading and len(heading.group(1)) <= skip_level:
                skip_level = None
            else:
                continue
        if skip_level is None and not in_code and heading_pattern.match(line):
            skip_level = len(line) - len(line.lstrip("#"))
            skipped += 1
            continue
        kept.append(line)
    return "\n".join(kept), skipped


def _remove_version_8_blocks(text: str) -> tuple[str, int]:
    blocks = re.split(r"\n\s*\n", text)
    kept: list[str] = []
    removed = 0
    for block in blocks:
        # Headings are structural. Only content blocks explicitly scoped to Redis 8+ are removed.
        if not block.lstrip().startswith("#") and VERSION_8_RE.search(block):
            removed += 1
            continue
        kept.append(block)
    return "\n\n".join(kept), removed


def _remove_product_blocks(text: str) -> tuple[str, int]:
    blocks = re.split(r"\n\s*\n", text)
    kept: list[str] = []
    removed = 0
    for block in blocks:
        if not block.lstrip().startswith("#") and PRODUCT_BLOCK_RE.search(block):
            removed += 1
            continue
        kept.append(block)
    return "\n\n".join(kept), removed


def clean_markdown(body: str) -> CleaningResult:
    body, product_sections = _remove_heading_sections(body, PRODUCT_HEADING_RE)
    body, irrelevant_sections = _remove_heading_sections(body, IRRELEVANT_HEADING_RE)
    body, version_blocks = _remove_version_8_blocks(body)
    body, product_blocks = _remove_product_blocks(body)
    body = HUGO_DIRECTIVE_RE.sub("", body)
    body = body.replace("-tab-sep-", "")
    body = REFERENCE_LINK_RE.sub("", body)
    body = MARKDOWN_LINK_RE.sub(r"\1", body)
    body = HTML_TAG_RE.sub("", body)
    body = html.unescape(body)
    body = re.sub(r"[ \t]+\n", "\n", body)
    body = re.sub(r"\n{3,}", "\n\n", body)
    body = _deduplicate_adjacent_blocks(body)
    return CleaningResult(
        body.strip(),
        version_blocks,
        product_sections,
        product_blocks,
        irrelevant_sections,
    )


def _deduplicate_adjacent_blocks(text: str) -> str:
    """Remove exact adjacent blocks left when equivalent Hugo tabs are flattened."""
    blocks = re.split(r"\n\s*\n", text)
    deduplicated: list[str] = []
    for block in blocks:
        normalized = re.sub(r"\s+", " ", block).strip()
        previous = re.sub(r"\s+", " ", deduplicated[-1]).strip() if deduplicated else None
        if normalized and normalized == previous:
            continue
        deduplicated.append(block)
    return "\n\n".join(deduplicated)


def source_url_for(source_path: str) -> str:
    relative = source_path.removeprefix("content/")
    if relative.endswith("/_index.md"):
        relative = relative[: -len("_index.md")]
    else:
        relative = relative.removesuffix(".md") + "/"
    return f"https://redis.io/docs/latest/{relative}"


def parse_document(path: Path, source_root: Path, source_path_prefix: str = "") -> Document:
    relative_path = path.relative_to(source_root).as_posix()
    source_path = f"{source_path_prefix}{relative_path}"
    metadata, body = parse_front_matter(path.read_text(encoding="utf-8"))
    cleaned = clean_markdown(body)
    title = str(metadata.get("title") or metadata.get("linkTitle") or path.stem)
    document_type = str(metadata.get("document_type") or (
        "command" if source_path.startswith("content/commands/") else "guide"
    ))
    source_type = str(metadata.get("source_type") or "official")
    source_url = str(metadata.get("source_url") or source_url_for(source_path))
    return Document(
        source_path=source_path,
        source_url=source_url,
        title=title,
        document_type=document_type,
        front_matter=metadata,
        body=cleaned.text,
        source_type=source_type,
        removed_version_blocks=cleaned.removed_version_blocks,
        removed_product_sections=cleaned.removed_product_sections,
        removed_product_blocks=cleaned.removed_product_blocks,
        removed_irrelevant_sections=cleaned.removed_irrelevant_sections,
    )
