import pytest

from app.ingestion import uploaded


def test_html_upload_keeps_headings_without_navigation() -> None:
    content = b"""<html><head><meta charset='utf-8'><title>Hidden</title></head>
    <body><nav>Menu</nav><main><h1>Care guide</h1><p>Daily observation.</p>
    <h2>Records</h2><p>Keep dated notes.</p></main><footer>Footer</footer></body></html>"""
    parsed = uploaded.parse_uploaded_document("guide.html", content)
    assert parsed.extraction_method == "html"
    assert "# Care guide" in parsed.body
    assert "## Records" in parsed.body
    assert "Menu" not in parsed.body
    assert "Footer" not in parsed.body


def test_pdf_uses_ocr_only_for_image_only_pages(monkeypatch: pytest.MonkeyPatch) -> None:
    class Page:
        def __init__(self, text: str, images: list[object]) -> None:
            self.text = text
            self.images = images

        def extract_text(self) -> str:
            return self.text

    class Reader:
        is_encrypted = False

        def __init__(self) -> None:
            self.pages = [Page("Readable text on page one", []), Page("", [object()])]

    monkeypatch.setattr(uploaded, "PdfReader", lambda _content, **_kwargs: Reader())
    monkeypatch.setattr(uploaded, "_ocr_pdf_pages", lambda content, pages: {2: "OCR page two"})
    parsed = uploaded.parse_uploaded_document("guide.pdf", b"mock-pdf")
    assert parsed.page_count == 2
    assert parsed.ocr_page_count == 1
    assert parsed.extraction_method == "pdf+ocr"
    assert "## Page 1\nReadable text" in parsed.body
    assert "## Page 2\nOCR page two" in parsed.body


def test_scanned_pdf_reports_missing_ocr_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(uploaded.shutil, "which", lambda _: None)
    with pytest.raises(ValueError, match="Tesseract"):
        uploaded._ocr_pdf_pages(b"pdf", [1])


def test_pdf_section_headings_are_preserved_under_page_marker() -> None:
    marked = uploaded._mark_pdf_headings(
        "3 Model Architecture\nThe model follows an encoder-decoder structure.\n"
        "3.1 Encoder and Decoder Stacks\nBoth components are stacked."
    )
    assert "### 3 Model Architecture" in marked
    assert "#### 3.1 Encoder and Decoder Stacks" in marked


def test_rejects_unsupported_or_empty_documents() -> None:
    with pytest.raises(ValueError, match="supported document formats"):
        uploaded.parse_uploaded_document("guide.docx", b"not-docx")
    with pytest.raises(ValueError, match="no extractable text"):
        uploaded.parse_uploaded_document("empty.html", b"<nav>Only navigation</nav>")
