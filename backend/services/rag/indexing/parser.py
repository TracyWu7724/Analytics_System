"""
parser.py — PDF parsing and product metadata extraction.

Responsibilities:
  - Partition a PDF into unstructured elements (hi-res strategy)
  - Extract a stable product ID and UUID from a filename
"""

from __future__ import annotations

import hashlib
import os
import re
from typing import List

from unstructured.partition.pdf import partition_pdf


class PdfParser:
    """Parses a single PDF into raw unstructured elements."""

    def __init__(self, strategy: str = "hi_res", infer_table_structure: bool = True):
        """
        Args:
            strategy: Unstructured partition strategy ('hi_res' or 'fast').
            infer_table_structure: Whether to extract table structure from PDFs.
        """
        self.strategy = strategy
        self.infer_table_structure = infer_table_structure

    def parse(self, path: str) -> list:
        """
        Partition a PDF file into unstructured elements.

        Args:
            path: Absolute path to the PDF file.

        Returns:
            List of unstructured Element objects.
        """
        return partition_pdf(
            filename=path,
            strategy=self.strategy,
            infer_table_structure=self.infer_table_structure,
            extract_images_in_pdf=False,
        )

    # ------------------------------------------------------------------
    # Product ID / UUID helpers
    # ------------------------------------------------------------------

    @staticmethod
    def extract_product_id(filename: str) -> str:
        """
        Derive a human-readable product ID from a PDF filename.

        Example:
            'LOCTITE-AA-332-en_GL.pdf'  ->  'LOCTITE-AA-332'

        Args:
            filename: Bare filename (no directory component needed).

        Returns:
            Product ID string.
        """
        base = os.path.splitext(filename)[0]
        match = re.match(r"([A-Z0-9\-]+?)(?:-[a-z]{2}_[A-Z]{2})?$", base)
        return match.group(1) if match else base

    @staticmethod
    def product_uuid(product_id: str, length: int = 10) -> str:
        """
        Generate a short, stable hash that acts as a product UUID.

        Example:
            'LOCTITE-454'  ->  'ad4f91c2fe'

        Args:
            product_id: The human-readable product identifier.
            length: Number of hex characters to return (max 40).

        Returns:
            Hex string of the requested length.
        """
        return hashlib.sha1(product_id.encode("utf-8")).hexdigest()[:length]

    def pdf_files(self, directory: str) -> List[str]:
        """
        Return all PDF filenames (bare names, not full paths) in *directory*.

        Args:
            directory: Directory to scan.

        Returns:
            Sorted list of PDF filenames.
        """
        if not os.path.isdir(directory):
            raise FileNotFoundError(f"Input directory not found: {directory}")
        return sorted(f for f in os.listdir(directory) if f.lower().endswith(".pdf"))

    def parse_directory(self, directory: str) -> dict[str, list]:
        """Parse every PDF in *directory* and return a filename→elements mapping."""
        return {filename: self.parse(os.path.join(directory, filename)) for filename in self.pdf_files(directory)}
