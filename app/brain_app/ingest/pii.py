"""A basic PII scan for landed content.

Not a compliance-grade detector; a cheap, deterministic backstop that flags the
obvious classes (email, credit-card-like and government-id-like numbers) before
content lands, so a demo source never quietly seeds the corpus with personal
data. A real deployment layers a proper in-tenancy DLP scan on top; the interface
here is the seam for that.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
# 13-16 digit runs allowing spaces/dashes: catches most card-like numbers.
_CARD = re.compile(r"\b(?:\d[ -]?){13,16}\b")
# US SSN-shaped and similar national-id patterns.
_SSN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")

_PATTERNS = {"email": _EMAIL, "credit-card": _CARD, "national-id": _SSN}


@dataclass(frozen=True)
class PiiFinding:
    kind: str
    sample: str


def scan_pii(text: str) -> list[PiiFinding]:
    """Return de-duplicated PII findings, ordered by kind then first match."""
    findings: list[PiiFinding] = []
    seen: set[tuple[str, str]] = set()
    for kind, pattern in _PATTERNS.items():
        for match in pattern.finditer(text):
            sample = match.group(0)
            key = (kind, sample)
            if key not in seen:
                seen.add(key)
                findings.append(PiiFinding(kind=kind, sample=sample))
    return findings
