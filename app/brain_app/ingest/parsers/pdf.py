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

        client = documentai.DocumentProcessorServiceClient()
        raw = documentai.RawDocument(content=content, mime_type=mime)
        result = client.process_document(
            request=documentai.ProcessRequest(name=self.processor, raw_document=raw)
        )
        return ParsedDoc(body=result.document.text.strip(), tags=[])


class PdfParser:
    def parse(self, content: bytes, mime: str) -> ParsedDoc:
        raise NotImplementedError(
            "PDF parsing runs in-tenancy via Vertex AI Document AI and is wired in a "
            "later cloud phase (ARCHITECTURE.md section 12). Use the deterministic "
            "FakePdfParser in tests, or convert the source to markdown/HTML upstream."
        )


class FakePdfParser:
    """Deterministic offline stand-in: treats the bytes as UTF-8 text.

    Enough to exercise the pipeline's PDF branch in tests without the cloud. It is
    not a real PDF decoder and is never used in production.
    """

    def parse(self, content: bytes, mime: str) -> ParsedDoc:
        return ParsedDoc(body=content.decode("utf-8", errors="replace").strip(), tags=[])
