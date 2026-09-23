"""Sliding-window chunking of a new page's flat block list — `page.created` path only
(see decisions-log.md's 2026-09-23 entry). Pure function, independently unit-testable, no
I/O. Defaults are adjustable via settings, not fixed requirements — see the Feature 1.7
planning notes for the sizing rationale."""

from ..config import settings
from .client import NotionBlock


def chunk_blocks(
    blocks: list[NotionBlock],
    chunk_size: int | None = None,
    overlap: int | None = None,
) -> list[list[NotionBlock]]:
    chunk_size = chunk_size or settings.NOTION_CHUNK_SIZE_BLOCKS
    overlap = overlap if overlap is not None else settings.NOTION_CHUNK_OVERLAP_BLOCKS

    if not blocks:
        return []
    if chunk_size <= overlap:
        raise ValueError("chunk_size must be greater than overlap")

    step = chunk_size - overlap
    chunks: list[list[NotionBlock]] = []
    start = 0
    while start < len(blocks):
        chunks.append(blocks[start : start + chunk_size])
        start += step
    return chunks
