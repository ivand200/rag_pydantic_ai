from __future__ import annotations

import re
from dataclasses import dataclass
from io import BytesIO

from pypdf import PdfReader


class DocumentExtractionError(Exception):
    retryable = False

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class UnsupportedExtractionTypeError(DocumentExtractionError):
    pass


class EmptyExtractedTextError(DocumentExtractionError):
    pass


class ExtractedTextTooLargeError(DocumentExtractionError):
    pass


@dataclass(frozen=True)
class ExtractedText:
    text: str
    pages: list[str] | None = None


def extract_document_text(
    *,
    content: bytes,
    file_extension: str,
    max_chars: int,
) -> ExtractedText:
    match file_extension.lower():
        case ".txt" | ".md":
            extracted = _extract_text_bytes(content)
        case ".pdf":
            extracted = _extract_pdf_text(content)
        case _:
            raise UnsupportedExtractionTypeError("Document type is not supported for ingestion.")

    text = _normalize_text(extracted.text)
    if not text:
        raise EmptyExtractedTextError("Document has no extractable text.")
    if len(text) > max_chars:
        raise ExtractedTextTooLargeError("Extracted text exceeds the configured character limit.")

    if extracted.pages is None:
        return ExtractedText(text=text)

    pages = [_normalize_text(page) for page in extracted.pages]
    return ExtractedText(text=text, pages=pages)


def _extract_text_bytes(content: bytes) -> ExtractedText:
    return ExtractedText(text=content.decode("utf-8", errors="replace"))


def _extract_pdf_text(content: bytes) -> ExtractedText:
    try:
        reader = PdfReader(BytesIO(content))
        pages = [page.extract_text() or "" for page in reader.pages]
    except Exception as exc:
        raise EmptyExtractedTextError("PDF text extraction failed.") from exc

    if not any(page.strip() for page in pages):
        raise EmptyExtractedTextError(
            "PDF has no extractable text layer. Scanned or image-only PDFs are not supported."
        )

    return ExtractedText(text="\n\n".join(pages), pages=pages)


def _normalize_text(text: str) -> str:
    normalized = text.replace("\x00", "")
    normalized = re.sub(r"[ \t\r\f\v]+", " ", normalized)
    normalized = re.sub(r"\n{3,}", "\n\n", normalized)
    return normalized.strip()
