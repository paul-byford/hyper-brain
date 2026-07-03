"""PDF parser stub, behind the Vertex AI Document AI seam.

Parsing rich formats in-tenancy is load-bearing for the data boundary
(ARCHITECTURE.md section 12): a bank's PDFs must be parsed by a Google-managed
model inside the tenancy, never shipped to a third-party SaaS parser. The real
adapter is wired in a cloud phase. Until then this raises a clear, honest error
rather than silently degrading, and a deterministic fake stands in for tests.
"""

from __future__ import annotations

from ..models import ParsedDoc


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
