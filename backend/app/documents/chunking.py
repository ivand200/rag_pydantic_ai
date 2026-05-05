from __future__ import annotations

import re
from dataclasses import dataclass

_TOKEN_PATTERN = re.compile(r"\w+|[^\w\s]", re.UNICODE)
_HEADING_PATTERN = re.compile(r"^\s{0,3}#{1,6}\s+(.+?)\s*$")


@dataclass(frozen=True)
class TextChunk:
    chunk_index: int
    text: str
    token_count: int
    section_title: str | None = None


def split_text_into_chunks(
    *,
    text: str,
    target_tokens: int,
    overlap_tokens: int,
) -> list[TextChunk]:
    if target_tokens <= 0:
        raise ValueError("target_tokens must be positive")
    if overlap_tokens < 0 or overlap_tokens >= target_tokens:
        raise ValueError("overlap_tokens must be non-negative and less than target_tokens")

    units = _recursive_units(text)
    chunks: list[TextChunk] = []
    current_tokens: list[str] = []
    current_text_parts: list[str] = []
    current_section: str | None = None

    for unit_text, section_title in units:
        unit_tokens = tokenize(unit_text)
        if not unit_tokens:
            continue

        if len(unit_tokens) > target_tokens:
            chunks.extend(
                _flush_chunk(
                    current_tokens=current_tokens,
                    current_text_parts=current_text_parts,
                    section_title=current_section,
                    chunk_index_offset=len(chunks),
                )
            )
            current_tokens = []
            current_text_parts = []
            current_section = None
            chunks.extend(
                _split_large_unit(
                    unit_text=unit_text,
                    target_tokens=target_tokens,
                    overlap_tokens=overlap_tokens,
                    section_title=section_title,
                    chunk_index_offset=len(chunks),
                )
            )
            continue

        would_exceed = current_tokens and len(current_tokens) + len(unit_tokens) > target_tokens
        if would_exceed:
            chunks.extend(
                _flush_chunk(
                    current_tokens=current_tokens,
                    current_text_parts=current_text_parts,
                    section_title=current_section,
                    chunk_index_offset=len(chunks),
                )
            )
            available_overlap_tokens = max(target_tokens - len(unit_tokens), 0)
            overlap_text = _overlap_text(
                current_tokens,
                min(overlap_tokens, available_overlap_tokens),
            )
            current_tokens = tokenize(overlap_text)
            current_text_parts = [overlap_text] if overlap_text else []

        current_text_parts.append(unit_text)
        current_tokens.extend(unit_tokens)
        current_section = current_section or section_title

    chunks.extend(
        _flush_chunk(
            current_tokens=current_tokens,
            current_text_parts=current_text_parts,
            section_title=current_section,
            chunk_index_offset=len(chunks),
        )
    )
    return chunks


def tokenize(text: str) -> list[str]:
    return _TOKEN_PATTERN.findall(text)


def _recursive_units(text: str) -> list[tuple[str, str | None]]:
    units: list[tuple[str, str | None]] = []
    current_section: str | None = None
    for paragraph in re.split(r"\n\s*\n", text):
        paragraph = paragraph.strip()
        if not paragraph:
            continue

        heading = _HEADING_PATTERN.match(paragraph)
        if heading:
            current_section = heading.group(1).strip()

        sentences = _split_sentences(paragraph)
        if len(sentences) == 1:
            units.append((paragraph, current_section))
        else:
            units.extend((sentence, current_section) for sentence in sentences)
    return units


def _split_sentences(text: str) -> list[str]:
    parts = [part.strip() for part in re.split(r"(?<=[.!?])\s+", text) if part.strip()]
    return parts or [text]


def _split_large_unit(
    *,
    unit_text: str,
    target_tokens: int,
    overlap_tokens: int,
    section_title: str | None,
    chunk_index_offset: int,
) -> list[TextChunk]:
    tokens = tokenize(unit_text)
    chunks: list[TextChunk] = []
    start = 0
    while start < len(tokens):
        window = tokens[start : start + target_tokens]
        chunks.append(
            TextChunk(
                chunk_index=chunk_index_offset + len(chunks),
                text=_tokens_to_text(window),
                token_count=len(window),
                section_title=section_title,
            )
        )
        if start + target_tokens >= len(tokens):
            break
        start += target_tokens - overlap_tokens
    return chunks


def _flush_chunk(
    *,
    current_tokens: list[str],
    current_text_parts: list[str],
    section_title: str | None,
    chunk_index_offset: int,
) -> list[TextChunk]:
    text = "\n\n".join(part for part in current_text_parts if part).strip()
    if not text:
        return []
    return [
        TextChunk(
            chunk_index=chunk_index_offset,
            text=text,
            token_count=len(current_tokens),
            section_title=section_title,
        )
    ]


def _overlap_text(tokens: list[str], overlap_tokens: int) -> str:
    if overlap_tokens == 0:
        return ""
    return _tokens_to_text(tokens[-overlap_tokens:])


def _tokens_to_text(tokens: list[str]) -> str:
    text = " ".join(tokens)
    return re.sub(r"\s+([,.;:!?])", r"\1", text)
