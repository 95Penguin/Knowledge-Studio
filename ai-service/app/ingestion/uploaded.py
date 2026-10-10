"""Extract searchable text from user-provided documents without fetching remote URLs."""

from __future__ import annotations

import io
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path

from pypdf import PdfReader
from pypdf.errors import PdfReadError

SUPPORTED_EXTENSIONS = {".md", ".txt", ".html", ".htm", ".pdf"}
MAX_PDF_PAGES = 100
MAX_OCR_PAGES = 20
PDF_SECTION_RE = re.compile(r"^\s*(\d+(?:\.\d+)*\.?)\s+([A-Z][^\n]{3,90})\s*$")
PDF_UNNUMBERED_HEADINGS = frozenset(
    {"abstract", "introduction", "conclusion", "conclusions", "references"}
)


@dataclass(frozen=True)
class ParsedUpload:
    body: str
    extraction_method: str
    page_count: int | None = None
    ocr_page_count: int = 0


class _HTMLTextExtractor(HTMLParser):
    """Keep headings and paragraphs while dropping typical page chrome."""

    SKIP_TAGS = frozenset({"head", "script", "style", "nav", "footer", "aside", "form", "svg"})
    VOID_TAGS = frozenset(
        {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source"}
    )
    BLOCK_TAGS = frozenset(
        {"p", "div", "section", "article", "main", "br", "tr", "table", "blockquote"}
    )

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self.skip_depth:
            if tag not in self.VOID_TAGS:
                self.skip_depth += 1
            return
        if tag in self.SKIP_TAGS:
            self.skip_depth = 1
        elif re.fullmatch(r"h[1-6]", tag):
            self.parts.append(f"\n\n{'#' * int(tag[1])} ")
        elif tag == "li":
            self.parts.append("\n- ")
        elif tag in {"td", "th"}:
            self.parts.append(" | ")
        elif tag in self.BLOCK_TAGS:
            self.parts.append("\n\n")

    def handle_endtag(self, tag: str) -> None:
        if self.skip_depth:
            if tag not in self.VOID_TAGS:
                self.skip_depth -= 1
        elif tag in self.BLOCK_TAGS or re.fullmatch(r"h[1-6]", tag):
            self.parts.append("\n\n")

    def handle_data(self, data: str) -> None:
        if not self.skip_depth:
            self.parts.append(data)

    def text(self) -> str:
        lines = [re.sub(r"[\t ]+", " ", line).strip() for line in "".join(self.parts).splitlines()]
        return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def parse_uploaded_document(filename: str, content: bytes) -> ParsedUpload:
    extension = Path(filename).suffix.lower()
    if extension not in SUPPORTED_EXTENSIONS:
        raise ValueError("supported document formats: .md, .txt, .html, .htm, .pdf")
    if not content or len(content) > 10 * 1024 * 1024:
        raise ValueError("document must be non-empty and at most 10 MiB")
    if extension == ".pdf":
        return _parse_pdf(content)
    try:
        raw_text = content.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise ValueError("text documents must use UTF-8 encoding") from error
    if extension in {".html", ".htm"}:
        extractor = _HTMLTextExtractor()
        extractor.feed(raw_text)
        body = extractor.text()
        method = "html"
    else:
        body = raw_text.strip()
        method = "markdown" if extension == ".md" else "text"
    if not body.strip():
        raise ValueError("document contains no extractable text")
    return ParsedUpload(body=body, extraction_method=method)


def _parse_pdf(content: bytes) -> ParsedUpload:
    try:
        reader = PdfReader(io.BytesIO(content), strict=False)
        if reader.is_encrypted and not reader.decrypt(""):
            raise ValueError("password-protected PDF is not supported")
        if len(reader.pages) > MAX_PDF_PAGES:
            raise ValueError(f"PDF exceeds the {MAX_PDF_PAGES}-page limit")
        texts: list[str] = []
        ocr_pages: list[int] = []
        for page_number, page in enumerate(reader.pages, 1):
            text = page.extract_text() or ""
            texts.append(text)
            if len(text.strip()) < 24 and bool(page.images):
                ocr_pages.append(page_number)
    except (PdfReadError, OSError, KeyError) as error:
        raise ValueError("PDF could not be parsed") from error
    if len(ocr_pages) > MAX_OCR_PAGES:
        raise ValueError(f"PDF contains more than {MAX_OCR_PAGES} image-only pages; split it first")
    if ocr_pages:
        for page_number, text in _ocr_pdf_pages(content, ocr_pages).items():
            if text.strip():
                texts[page_number - 1] = text
    sections = [
        f"## Page {index}\n{_mark_pdf_headings(text.strip())}"
        for index, text in enumerate(texts, 1)
        if text.strip()
    ]
    if not sections:
        raise ValueError("PDF contains no extractable text")
    return ParsedUpload(
        body="\n\n".join(sections),
        extraction_method="pdf+ocr" if ocr_pages else "pdf-text",
        page_count=len(reader.pages),
        ocr_page_count=len(ocr_pages),
    )


def _mark_pdf_headings(text: str) -> str:
    """Preserve recognizable paper headings beneath the page marker."""
    lines: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        match = PDF_SECTION_RE.fullmatch(stripped)
        if match and not stripped.endswith((".", ":")):
            depth = match.group(1).rstrip(".").count(".")
            lines.append(f"{'#' * min(3 + depth, 6)} {stripped}")
        elif stripped.casefold() in PDF_UNNUMBERED_HEADINGS:
            lines.append(f"### {stripped}")
        else:
            lines.append(line)
    return "\n".join(lines)


def _ocr_pdf_pages(content: bytes, page_numbers: list[int]) -> dict[int, str]:
    if not shutil.which("pdftoppm") or not shutil.which("tesseract"):
        raise ValueError("scanned PDF requires pdftoppm and Tesseract OCR")
    output: dict[int, str] = {}
    with tempfile.TemporaryDirectory(prefix="knowledge-ocr-") as directory:
        pdf_path = Path(directory) / "input.pdf"
        pdf_path.write_bytes(content)
        for page_number in page_numbers:
            png_prefix = Path(directory) / f"page-{page_number}"
            try:
                subprocess.run(
                    [
                        "pdftoppm",
                        "-f",
                        str(page_number),
                        "-l",
                        str(page_number),
                        "-r",
                        "180",
                        "-png",
                        "-singlefile",
                        str(pdf_path),
                        str(png_prefix),
                    ],
                    check=True,
                    capture_output=True,
                    timeout=45,
                )
                result = subprocess.run(
                    ["tesseract", f"{png_prefix}.png", "stdout", "-l", "eng+chi_sim"],
                    check=True,
                    capture_output=True,
                    text=True,
                    timeout=45,
                )
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
                raise ValueError(f"OCR failed on PDF page {page_number}") from error
            output[page_number] = result.stdout.strip()
    return output
