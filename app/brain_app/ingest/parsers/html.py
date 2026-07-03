"""HTML parser built on the standard library only.

A bank's web adapter must not ship sensitive page content to a third-party
parser, and the offline core must stay dependency-light (numpy + pyyaml). So this
converts a useful subset of HTML to markdown using ``html.parser`` from the
standard library: headings, paragraphs, lists, and inline emphasis, with
``<script>``/``<style>`` dropped. It is intentionally small; richer or messier
sources are exactly what the optional Gemini curate step (in-tenancy) cleans up.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser as _StdHTMLParser

from ..models import ParsedDoc

_HEADINGS = {"h1": "#", "h2": "##", "h3": "###", "h4": "####", "h5": "#####", "h6": "######"}
_BLOCK = {"p", "div", "section", "article", "br", "tr"}
_SKIP = {"script", "style", "head", "noscript"}
_WS = re.compile(r"[ \t\r\f\v]+")


class _Converter(_StdHTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.title: str | None = None
        self._skip_depth = 0
        self._in_title = False
        self._pending_heading: str | None = None
        self._list_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _SKIP:
            self._skip_depth += 1
            return
        if tag == "title":
            self._in_title = True
        elif tag in _HEADINGS:
            self._flush_block()
            self._pending_heading = _HEADINGS[tag]
        elif tag in ("ul", "ol"):
            self._list_depth += 1
        elif tag == "li":
            self._flush_block()
            self.parts.append("- ")
        elif tag in _BLOCK:
            self._flush_block()

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP:
            self._skip_depth = max(0, self._skip_depth - 1)
            return
        if tag == "title":
            self._in_title = False
        elif tag in _HEADINGS or tag in _BLOCK or tag == "li":
            self._flush_block()
        elif tag in ("ul", "ol"):
            self._list_depth = max(0, self._list_depth - 1)
            self._flush_block()

    def handle_data(self, data: str) -> None:
        text = _WS.sub(" ", data)
        # Title lives inside <head>, which we otherwise skip, so capture it before
        # the skip check.
        if self._in_title:
            self.title = (self.title or "") + text.strip()
            return
        if self._skip_depth:
            return
        if not text.strip() and not self.parts:
            return
        if self._pending_heading and text.strip():
            self.parts.append(f"{self._pending_heading} {text.strip()}")
            self._pending_heading = None
            self._flush_block()
            return
        self.parts.append(text)

    def _flush_block(self) -> None:
        if self.parts and self.parts[-1] != "\n\n":
            self.parts.append("\n\n")

    def markdown(self) -> str:
        text = "".join(self.parts)
        # Collapse the block separators we sprinkled and tidy stray spaces.
        text = re.sub(r"\n{3,}", "\n\n", text)
        text = re.sub(r"[ \t]+\n", "\n", text)
        text = re.sub(r"\n +", "\n", text)
        return text.strip()


class HtmlParser:
    def parse(self, content: bytes, mime: str) -> ParsedDoc:
        converter = _Converter()
        converter.feed(content.decode("utf-8", errors="replace"))
        converter.close()
        title = converter.title.strip() if converter.title else None
        return ParsedDoc(body=converter.markdown(), title=title or None, tags=[])
