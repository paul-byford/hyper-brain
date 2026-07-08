"""Pillar 1 (functional): the parser seam."""

from __future__ import annotations

import pathlib

import pytest

from brain_app.ingest.parsers import HtmlParser, MarkdownParser, get_parser
from brain_app.ingest.parsers.pdf import FakePdfParser, PdfParser

FIXTURES = pathlib.Path(__file__).resolve().parent / "fixtures"


def test_markdown_passthrough_lifts_frontmatter_and_drops_it():
    raw = b"---\ntitle: Hello\ntags: [a, b]\n---\n\n# Body\n\nText here.\n"
    parsed = MarkdownParser().parse(raw, "text/markdown")
    assert parsed.title == "Hello"
    assert parsed.tags == ["a", "b"]
    # The source frontmatter block is removed; the pipeline writes its own.
    assert "title: Hello" not in parsed.body
    assert parsed.body.startswith("# Body")


def test_html_parser_converts_and_strips_noise():
    html = (FIXTURES / "sample.html").read_bytes()
    parsed = HtmlParser().parse(html, "text/html")
    assert parsed.title == "Streaming features for fraud"
    assert "# Streaming features for fraud" in parsed.body
    assert "## Why freshness matters" in parsed.body
    assert "- transaction velocity" in parsed.body
    # script/style content must never survive into the body.
    assert "should not appear" not in parsed.body
    assert "color: red" not in parsed.body


def test_get_parser_dispatch_and_charset_suffix():
    assert isinstance(get_parser("text/markdown; charset=utf-8"), MarkdownParser)
    assert isinstance(get_parser("text/html"), HtmlParser)
    with pytest.raises(ValueError):
        get_parser("application/x-msdownload")


def test_pdf_parser_reports_a_clean_error_on_bad_input():
    # The real PDF parser (pypdf, in-tenancy) raises a clear ValueError on non-PDF
    # bytes rather than crashing; the fake still stands in for pipeline tests.
    pytest.importorskip("pypdf")
    with pytest.raises(ValueError):
        PdfParser().parse(b"not a pdf", "application/pdf")
    parsed = FakePdfParser().parse(b"plain text body", "application/pdf")
    assert parsed.body == "plain text body"
