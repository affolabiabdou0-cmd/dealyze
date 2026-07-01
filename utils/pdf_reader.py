"""Extract plain text from a PDF (bytes or file path)."""
import io
import logging
from pathlib import Path

import pypdf

logger = logging.getLogger(__name__)

MAX_CHARS = 12_000  # ~3 000 tokens — safe for llama-3.3-70b context


def extract_text(source: bytes | str | Path) -> str:
    """
    Accept PDF as raw bytes, file path (str or Path).
    Returns cleaned text, truncated to MAX_CHARS if needed.
    """
    if isinstance(source, (str, Path)):
        with open(source, "rb") as f:
            source = f.read()

    reader = pypdf.PdfReader(io.BytesIO(source))
    pages = []
    for page in reader.pages:
        text = page.extract_text() or ""
        pages.append(text.strip())

    full_text = "\n\n".join(p for p in pages if p)

    if len(full_text) > MAX_CHARS:
        logger.warning("PDF text truncated from %d to %d chars", len(full_text), MAX_CHARS)
        full_text = full_text[:MAX_CHARS] + "\n\n[...texte tronqué pour l'analyse]"

    return full_text
