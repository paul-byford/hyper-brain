"""Draft-first web ingestion: fetch a URL, pull out the real article, hand back an
editable draft. Nothing here writes to the corpus; the caller reviews and edits the
draft, then creates it through the normal note/propose path.

The fetcher is hardened against SSRF: only http/https, and every hop (including
redirects) must resolve to a public address, so a user-supplied URL can never be
turned into a request for the cloud metadata server or other internal resources.
A light main-content extraction drops boilerplate (nav, scripts, footers) before the
curator cleans it up, so the model sees the article rather than the whole page.
"""

from __future__ import annotations

import ipaddress
import socket
import urllib.error
import urllib.request
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

_MAX_REDIRECTS = 4
_MAX_BYTES = 5 * 1024 * 1024
_UA = "hyper-brain-ingest/1.0 (+draft)"


class UrlFetchError(ValueError):
    """A URL could not be fetched (bad scheme, blocked address, too large, HTTP error)."""


def _http_error_message(status: int) -> str:
    """A human-friendly message for an HTTP error from a fetched page."""
    if status in (401, 403):
        return (
            "That page blocked our request (it needs a login, or it blocks automated "
            "fetching). Open it and paste the text into the 'Paste text' tab instead."
        )
    if status == 404:
        return "That page could not be found (404). Check the link and try again."
    if status == 429:
        return "That site is rate-limiting requests (429). Please try again in a moment."
    if 500 <= status < 600:
        return f"That site had a server error ({status}). Try again later."
    return f"That page could not be fetched (HTTP {status})."


def _resolves_public(host: str) -> bool:
    """True only if every address the host resolves to is a public, routable IP."""
    try:
        infos = socket.getaddrinfo(host, None)
    except (socket.gaierror, UnicodeError, OSError):
        return False
    if not infos:
        return False
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local  # blocks 169.254.169.254 (cloud metadata)
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        ):
            return False
    return True


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None  # never auto-follow; we validate each hop's address ourselves


def _open(url: str):
    opener = urllib.request.build_opener(_NoRedirect)
    request = urllib.request.Request(url, headers={"User-Agent": _UA})
    try:
        return opener.open(request, timeout=15)  # nosec B310  # noqa: S310
    except urllib.error.HTTPError as exc:
        return exc  # a 3xx/4xx still carries .status and .headers


def fetch_url(url: str, *, opener=None) -> tuple[bytes, str]:
    """Fetch a public http/https URL, re-validating every redirect hop.

    Returns ``(bytes, mime)``. ``opener`` is an injection seam for tests (it bypasses
    the network and the address check, so tests never touch DNS)."""
    current = url
    for _ in range(_MAX_REDIRECTS + 1):
        parsed = urlparse(current)
        if parsed.scheme not in ("http", "https"):
            raise UrlFetchError("Only http and https links can be fetched.")
        if not parsed.hostname:
            raise UrlFetchError("That does not look like a valid web address.")
        if opener is not None:
            return opener(current)
        if not _resolves_public(parsed.hostname):
            raise UrlFetchError("That address is private or internal and cannot be fetched.")
        response = _open(current)
        status = getattr(response, "status", None) or response.getcode()
        if status in (301, 302, 303, 307, 308):
            location = response.headers.get("Location")
            if not location:
                raise UrlFetchError("That page redirected without a destination.")
            current = urljoin(current, location)
            continue
        if status >= 400:
            raise UrlFetchError(_http_error_message(status))
        data = response.read(_MAX_BYTES + 1)
        if len(data) > _MAX_BYTES:
            raise UrlFetchError("That page is too large to ingest.")
        get_ct = getattr(response.headers, "get_content_type", None)
        mime = get_ct() if get_ct else "text/html"
        return data, (mime or "text/html")
    raise UrlFetchError("That page redirected too many times.")


_SKIP = {"script", "style", "nav", "header", "footer", "aside", "form", "noscript", "svg", "button"}
_MAIN = {"article", "main"}
_BLOCK = {"p", "div", "section", "li", "br", "tr", "article", "main"}
_BLOCK |= {f"h{n}" for n in range(1, 7)}


class _Extractor(HTMLParser):
    """Collect readable text, skipping boilerplate; prefer text inside <article>/<main>."""

    def __init__(self) -> None:
        super().__init__()
        self._skip = 0
        self._in_main = 0
        self._in_title = False
        self.title_parts: list[str] = []
        self.blocks: list[str] = []
        self.main_blocks: list[str] = []
        self._cur: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in _SKIP:
            self._skip += 1
        elif tag == "title":
            self._in_title = True
        elif tag in _MAIN:
            self._in_main += 1
        if tag in _BLOCK:
            self._flush()

    def handle_endtag(self, tag):
        if tag in _SKIP and self._skip:
            self._skip -= 1
        elif tag == "title":
            self._in_title = False
        elif tag in _MAIN and self._in_main:
            self._in_main -= 1
        if tag in _BLOCK:
            self._flush()

    def handle_data(self, data):
        if self._skip:
            return
        if self._in_title:
            self.title_parts.append(data)
            return
        text = data.strip()
        if text:
            self._cur.append(text)

    def _flush(self):
        if self._cur:
            block = " ".join(self._cur).strip()
            if block:
                self.blocks.append(block)
                if self._in_main:
                    self.main_blocks.append(block)
            self._cur = []

    def close(self):
        super().close()
        self._flush()


def extract_main_text(html_bytes: bytes) -> tuple[str, str]:
    """Return ``(title, body)``: the page title and its main readable text.

    Prefers text inside <article>/<main>; falls back to the whole body. Very short
    fragments (menu items, buttons) are dropped so the draft is the actual article."""
    html = html_bytes.decode("utf-8", errors="replace")
    extractor = _Extractor()
    extractor.feed(html)
    extractor.close()
    blocks = extractor.main_blocks or extractor.blocks
    body = "\n\n".join(b for b in blocks if len(b) > 2).strip()
    title = " ".join(extractor.title_parts).split("|")[0].split(" - ")[0].strip()
    return title, body
