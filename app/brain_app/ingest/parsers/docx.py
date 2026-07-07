"""Word (.docx) text extraction, offline and dependency-free.

A .docx is a zip whose ``word/document.xml`` holds the body. We pull the visible
text run by run and break on paragraph boundaries, which is all retrieval needs
(it embeds text, not layout). Done with the standard library and plain string
scanning (no XML parser, so no external-entity surface on an uploaded file), so it
runs in the offline core and in tests with nothing to install.
"""

from __future__ import annotations

import html
import io
import re
import zipfile

from ..models import ParsedDoc

_RUN = re.compile(r"<w:t[^>]*>(.*?)</w:t>", re.DOTALL)


class DocxParser:
    def parse(self, content: bytes, mime: str) -> ParsedDoc:
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as archive:
                document = archive.read("word/document.xml").decode("utf-8", errors="replace")
        except (zipfile.BadZipFile, KeyError) as exc:
            raise ValueError("not a readable .docx (no word/document.xml)") from exc

        lines: list[str] = []
        for paragraph in document.split("</w:p>"):
            text = html.unescape("".join(_RUN.findall(paragraph))).strip()
            if text:
                lines.append(text)
        return ParsedDoc(body="\n\n".join(lines).strip(), tags=[])
