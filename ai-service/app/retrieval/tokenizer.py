import re

TOKEN_RE = re.compile(r"[a-z0-9]+(?:[-_:][a-z0-9]+)*|[\u4e00-\u9fff]", re.IGNORECASE)

# These words occur in almost every page and add little discriminative value.
# This is deliberately small: BM25's IDF already down-weights common terms.
STOP_WORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "in",
    "is",
    "it",
    "of",
    "on",
    "or",
    "redis",
    "that",
    "the",
    "this",
    "to",
    "with",
}


def tokenize(text: str) -> list[str]:
    """Deterministic lexical tokenizer for English docs and Redis identifiers."""
    return [token for token in TOKEN_RE.findall(text.lower()) if token not in STOP_WORDS]


def searchable_tokens(chunk: dict[str, object]) -> list[str]:
    """Give structural metadata modest weight while keeping body text dominant."""
    title = tokenize(str(chunk["title"]))
    section = tokenize(" ".join(str(value) for value in chunk["section_path"]))
    content = tokenize(str(chunk["content"]))
    return title * 3 + section * 2 + content
