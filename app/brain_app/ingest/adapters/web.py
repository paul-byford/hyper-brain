"""Web/URL adapter, on the standard library.

Fetches a configured list of URLs. It uses ``urllib`` (no third-party HTTP
dependency in the offline core) and restricts schemes to an allowlist, so a
misconfigured source cannot be turned into a request for ``file://`` secrets or
other local resources. Tests drive it deterministically by pointing it at a
``file://`` fixture through an injected opener, so no network is touched.
"""

from __future__ import annotations

import urllib.request
from collections.abc import Callable, Iterable
from urllib.parse import urlparse

from ..models import RawItem

# Only these schemes may be fetched. ``file`` is allowed so fixtures and a local
# ``raw/`` drop can be addressed by URL; block everything else (ftp, data, ...).
_ALLOWED_SCHEMES = {"http", "https", "file"}

# An opener maps a URL to (raw bytes, content-type). Injectable for tests.
Opener = Callable[[str], tuple[bytes, str]]


def _default_opener(url: str) -> tuple[bytes, str]:
    # nosec B310: the scheme is validated against _ALLOWED_SCHEMES in fetch() before
    # any URL reaches this opener, so http/https/file only, no custom schemes.
    with urllib.request.urlopen(url, timeout=30) as response:  # nosec B310  # noqa: S310
        content_type = response.headers.get_content_type() or "text/html"
        return response.read(), content_type


class WebAdapter:
    def __init__(
        self,
        source_id: str,
        *,
        urls: list[str],
        opener: Opener | None = None,
    ) -> None:
        self.source_id = source_id
        self.urls = list(urls)
        self._opener = opener or _default_opener

    def fetch(self) -> Iterable[RawItem]:
        for url in self.urls:
            scheme = urlparse(url).scheme.lower()
            if scheme not in _ALLOWED_SCHEMES:
                raise ValueError(
                    f"web source {self.source_id!r}: scheme {scheme!r} not allowed for {url!r}"
                )
            content, mime = self._opener(url)
            yield RawItem(
                identifier=url,
                content=content,
                mime=mime,
                source_url=url,
                title=None,
            )
