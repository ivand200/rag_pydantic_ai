from io import BytesIO

import pytest
from pypdf import PdfWriter

from app.documents.chunking import split_text_into_chunks
from app.documents.extraction import (
    EmptyExtractedTextError,
    ExtractedTextTooLargeError,
    extract_document_text,
)


def test_extracts_text_and_markdown_as_plain_text() -> None:
    extracted = extract_document_text(
        content=b"# Heading\n\nHello markdown.",
        file_extension=".md",
        max_chars=100,
    )

    assert extracted.text == "# Heading\n\nHello markdown."


def test_rejects_extracted_text_over_configured_limit() -> None:
    with pytest.raises(ExtractedTextTooLargeError):
        extract_document_text(content=b"12345", file_extension=".txt", max_chars=4)


def test_rejects_empty_or_scanned_pdf_without_text_layer() -> None:
    with pytest.raises(EmptyExtractedTextError, match="no extractable text layer"):
        extract_document_text(
            content=blank_pdf_bytes(),
            file_extension=".pdf",
            max_chars=100,
        )


def test_splits_text_with_token_target_and_overlap() -> None:
    chunks = split_text_into_chunks(
        text=(
            "# Intro\n\n"
            "Alpha beta gamma.\n\n"
            "Delta epsilon zeta eta.\n\n"
            "Theta iota kappa lambda.\n\n"
            "Mu nu xi omicron."
        ),
        target_tokens=5,
        overlap_tokens=2,
    )

    assert [chunk.chunk_index for chunk in chunks] == list(range(len(chunks)))
    assert all(chunk.token_count <= 5 for chunk in chunks)


def blank_pdf_bytes() -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    buffer = BytesIO()
    writer.write(buffer)
    return buffer.getvalue()
