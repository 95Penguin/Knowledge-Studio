import hashlib
import re
from dataclasses import dataclass

from app.ingestion.markdown import HEADING_RE
from app.ingestion.models import Chunk, Document

TOKEN_RE = re.compile(r"[A-Za-z0-9_]+|[^\sA-Za-z0-9_]", re.UNICODE)


@dataclass(frozen=True)
class Section:
    path: list[str]
    body: str


def approximate_token_count(text: str) -> int:
    """Stable pre-tokenizer estimate; model-specific token counts come in P0-2."""
    return len(TOKEN_RE.findall(text))


def split_sections(text: str, document_title: str) -> list[Section]:
    sections: list[Section] = []
    heading_stack: list[tuple[int, str]] = []
    body_lines: list[str] = []
    in_code = False

    def flush() -> None:
        body = "\n".join(body_lines).strip()
        if body:
            path = [title for _, title in heading_stack] or [document_title]
            sections.append(Section(path=path, body=body))
        body_lines.clear()

    for line in text.splitlines():
        if line.strip().startswith("```"):
            in_code = not in_code
            body_lines.append(line)
            continue
        heading = None if in_code else HEADING_RE.match(line)
        if heading:
            flush()
            level = len(heading.group(1))
            title = re.sub(r"[*_`]", "", heading.group(2)).strip()
            while heading_stack and heading_stack[-1][0] >= level:
                heading_stack.pop()
            heading_stack.append((level, title))
        else:
            body_lines.append(line)
    flush()
    return sections


def split_blocks(text: str) -> list[str]:
    """Split at blank lines while keeping fenced code blocks intact."""
    blocks: list[str] = []
    current: list[str] = []
    in_code = False
    for line in text.splitlines():
        if line.strip().startswith("```"):
            in_code = not in_code
        if not line.strip() and not in_code:
            if current:
                blocks.append("\n".join(current).strip())
                current = []
        else:
            current.append(line)
    if current:
        blocks.append("\n".join(current).strip())
    return [block for block in blocks if block]


def _split_oversized_block(block: str, max_tokens: int) -> list[str]:
    if approximate_token_count(block) <= max_tokens or block.lstrip().startswith("```"):
        return [block]
    sentences = re.split(r"(?<=[.!?。！？])\s+|\n(?=[-*]\s)", block)
    pieces: list[str] = []
    current: list[str] = []
    for sentence in sentences:
        if not sentence.strip():
            continue
        candidate = " ".join(current + [sentence]).strip()
        if current and approximate_token_count(candidate) > max_tokens:
            pieces.append(" ".join(current).strip())
            current = [sentence]
        else:
            current.append(sentence)
    if current:
        pieces.append(" ".join(current).strip())
    return pieces


def _overlap_tail(blocks: list[str], overlap_tokens: int) -> list[str]:
    tail: list[str] = []
    total = 0
    for block in reversed(blocks):
        count = approximate_token_count(block)
        if tail and total + count > overlap_tokens:
            break
        tail.insert(0, block)
        total += count
        if total >= overlap_tokens:
            break
    return tail


def chunk_document(
    document: Document,
    corpus_id: str,
    target_version: str,
    max_tokens: int = 450,
    overlap_tokens: int = 60,
) -> list[Chunk]:
    chunks: list[Chunk] = []
    chunk_index = 0
    for section in split_sections(document.body, document.title):
        raw_blocks = split_blocks(section.body)
        blocks = [
            piece
            for block in raw_blocks
            for piece in _split_oversized_block(block, max_tokens)
        ]
        current: list[str] = []
        for block in blocks:
            candidate = "\n\n".join(current + [block])
            if current and approximate_token_count(candidate) > max_tokens:
                chunks.append(
                    _make_chunk(document, section, current, corpus_id, target_version, chunk_index)
                )
                chunk_index += 1
                current = _overlap_tail(current, overlap_tokens)
                if current and approximate_token_count("\n\n".join(current + [block])) > max_tokens:
                    current = []
            current.append(block)
        if current:
            chunks.append(
                _make_chunk(document, section, current, corpus_id, target_version, chunk_index)
            )
            chunk_index += 1
    return chunks


def _make_chunk(
    document: Document,
    section: Section,
    blocks: list[str],
    corpus_id: str,
    target_version: str,
    chunk_index: int,
) -> Chunk:
    content = "\n\n".join(blocks).strip()
    identity = f"{corpus_id}|{document.source_path}|{' > '.join(section.path)}|{chunk_index}"
    chunk_id = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:20]
    return Chunk(
        chunk_id=chunk_id,
        corpus_id=corpus_id,
        content=content,
        title=document.title,
        section_path=section.path,
        source_path=document.source_path,
        source_url=document.source_url,
        target_version=target_version,
        document_type=document.document_type,
        source_type=document.source_type,
        chunk_index=chunk_index,
        approx_tokens=approximate_token_count(content),
    )
