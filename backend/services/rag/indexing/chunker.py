"""
chunker.py — Text chunking and cleaning.

Responsibilities:
  - Split unstructured elements into text chunks (chunk_by_title)
  - Clean boilerplate from chunk text
  - Filter chunks that should be excluded
"""

from __future__ import annotations

import re
from typing import List

from unstructured.chunking.title import chunk_by_title


class Chunker:
    """
    Converts a list of unstructured elements into clean text chunks.
    """

    def __init__(
        self,
        combine_under_n_chars: int = 700,
        max_characters: int = 1000,
    ):
        """
        Args:
            combine_under_n_chars: Merge consecutive chunks smaller than this
                                   threshold (passed to chunk_by_title).
            max_characters: Hard upper limit on chunk length.
        """
        self.combine_under_n_chars = combine_under_n_chars
        self.max_characters = max_characters

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def chunk(self, elements: list) -> List[str]:
        """
        Split *elements* into cleaned text chunks.

        Processing order:
          1. chunk_by_title with the configured size parameters
          2. clean_text  — remove known boilerplate
          3. is_excluded — drop chunks that hit cutoff keywords (stop on first hit)

        Args:
            elements: Raw unstructured Element objects from PdfParser.parse().

        Returns:
            List of non-empty, cleaned text strings.
        """
        raw_chunks = chunk_by_title(
            elements,
            combine_text_under_n_chars=self.combine_under_n_chars,
            max_characters=self.max_characters,
        )

        result: List[str] = []
        for chunk in raw_chunks:
            if not chunk.text:
                continue

            text = self.clean_text(chunk.text)
            if not text:
                continue

            if self.is_excluded(text):
                break  # treat as a document-level cutoff marker

            result.append(text)

        return result

    def chunk_texts(self, texts: list[str]) -> List[str]:
        """Clean and filter already-split text snippets."""
        cleaned: List[str] = []
        for text in texts:
            normalized = self.clean_text(text)
            if normalized and not self.is_excluded(normalized):
                cleaned.append(normalized)
        return cleaned

    # ------------------------------------------------------------------
    # Text cleaning helpers
    # ------------------------------------------------------------------

    @staticmethod
    def clean_text(text: str) -> str:
        """
        Remove known boilerplate patterns from a chunk.

        Patterns removed:
          - Henkel Colombiana legal/distribution footer
          - 'for the most direct access to local sales…' trailing block

        Args:
            text: Raw chunk text.

        Returns:
            Cleaned text, stripped of leading/trailing whitespace.
        """
        text = re.sub(
            r"# In case products are delivered by Henkel Colombiana[\s\S]*$",
            "",
            text,
            flags=re.IGNORECASE,
        )
        text = re.sub(
            r"for the most direct access to local sales and technical support[\s\S]*?$",
            "",
            text,
            flags=re.IGNORECASE,
        )
        return text.strip()

    @staticmethod
    def is_excluded(text: str) -> bool:
        """
        Return True if this chunk signals the end of useful content.

        Currently flags chunks containing 'conversions' (unit-conversion tables
        that appear at the tail of many datasheets).

        Args:
            text: Cleaned chunk text.

        Returns:
            True if the chunk should be dropped and parsing stopped.
        """
        return "conversions" in text.lower()
