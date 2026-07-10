"""PDF parser stub, behind the Vertex AI Document AI seam.

Parsing rich formats in-tenancy is load-bearing for the data boundary
(ARCHITECTURE.md section 12): a bank's PDFs must be parsed by a Google-managed
model inside the tenancy, never shipped to a third-party SaaS parser. The real
adapter is wired in a cloud phase. Until then this raises a clear, honest error
rather than silently degrading, and a deterministic fake stands in for tests.
"""

from __future__ import annotations

import os

from ..models import ParsedDoc


def _docai_message(exc: Exception) -> str:
    """A friendly message for a Document AI failure (esp. the 30-page online limit)."""
    text = str(exc)
    if "PAGE_LIMIT_EXCEEDED" in text or "pages exceed" in text:
        return (
            "This scanned PDF is too long for in-tenancy OCR, which reads up to 30 pages "
            "per document. Split it into smaller PDFs, or upload a text-based PDF (those "
            "are read directly, with no page limit)."
        )
    first = text.splitlines()[0] if text else "unknown error"
    return f"in-tenancy OCR could not read this PDF: {first[:200]}"


def _endpoint_for(processor: str) -> str | None:
    """The regional Document AI endpoint for a processor name, or None for the default.

    The client defaults to the ``us`` deployment, so a processor in ``eu`` (or any
    other region) must target ``{location}-documentai.googleapis.com`` or the call is
    rejected with an invalid-location error.
    """
    parts = processor.split("/")
    if "locations" in parts:
        location = parts[parts.index("locations") + 1]
        if location and location != "us":
            return f"{location}-documentai.googleapis.com"
    return None


class DocumentAiParser:
    """In-tenancy PDF parsing via Vertex AI Document AI (ARCHITECTURE.md section 12).

    Sensitive PDFs are parsed by a Google-managed processor inside the tenancy, never
    shipped to a third-party parser. Lazy import; needs a processor resource name in
    ``BRAIN_DOCAI_PROCESSOR`` (``projects/P/locations/L/processors/ID``). The process
    call is injectable so the branch is testable with no cloud.
    """

    def __init__(self, processor: str | None = None, *, process=None) -> None:
        self.processor = processor or os.environ.get("BRAIN_DOCAI_PROCESSOR")
        self._process = process

    def parse(self, content: bytes, mime: str) -> ParsedDoc:
        if self._process is not None:
            return ParsedDoc(body=self._process(content, mime).strip(), tags=[])
        if not self.processor:
            raise ValueError("BRAIN_DOCAI_PROCESSOR (the Document AI processor name) is not set")
        from google.cloud import documentai

        endpoint = _endpoint_for(self.processor)
        client = documentai.DocumentProcessorServiceClient(
            client_options={"api_endpoint": endpoint} if endpoint else None
        )
        raw = documentai.RawDocument(content=content, mime_type=mime)
        try:
            result = client.process_document(
                request=documentai.ProcessRequest(name=self.processor, raw_document=raw)
            )
        except Exception as exc:  # turn a raw API error into a clean, specific message
            raise ValueError(_docai_message(exc)) from exc
        return ParsedDoc(body=result.document.text.strip(), tags=[])


class PdfParser:
    """Text-first PDF extraction. pypdf reads the text layer in-tenancy (free, no page
    limit, the bytes never leave the container). Only an image-only PDF that yields no
    text falls back to Document AI OCR, and only when a processor is configured. So a
    normal text PDF never incurs a paid OCR call or Document AI's 30-page online limit."""

    def parse(self, content: bytes, mime: str) -> ParsedDoc:
        import io

        from pypdf import PdfReader
        from pypdf.errors import PyPdfError

        try:
            reader = PdfReader(io.BytesIO(content))
            parts = [(page.extract_text() or "").strip() for page in reader.pages]
        except (PyPdfError, ValueError, OSError) as exc:
            raise ValueError(f"could not read the PDF: {exc}") from exc
        body = "\n\n".join(p for p in parts if p).strip()
        if body:
            return ParsedDoc(body=body, tags=[])
        # No text layer: a scanned/image PDF. OCR with Document AI when configured.
        if os.environ.get("BRAIN_DOCAI_PROCESSOR"):
            return DocumentAiParser().parse(content, mime)
        return ParsedDoc(body="", tags=[])


class FakePdfParser:
    """Deterministic offline stand-in: treats the bytes as UTF-8 text.

    Enough to exercise the pipeline's PDF branch in tests without the cloud. It is
    not a real PDF decoder and is never used in production.
    """

    def parse(self, content: bytes, mime: str) -> ParsedDoc:
        return ParsedDoc(body=content.decode("utf-8", errors="replace").strip(), tags=[])
