"""Model Armor content guard (in-region): redact-then-allow for PII/secrets.

Before content is written into a shared space, or an answer is returned (especially on the
guest read path), it passes through Google **Model Armor**. Detected PII / secrets (Sensitive
Data Protection) are **redacted in place** from the exact code-point ranges Model Armor returns
-- redact then allow, so a leaked password or card never lands in the commons yet the useful
content still does. Prompt-injection / jailbreak and responsible-AI hits are surfaced as
**flags** (the agents' tool-only guardrails already bound what an injected instruction could
actually do), not blocks.

Enabled only when ``BRAIN_MODEL_ARMOR_TEMPLATE`` names a template (a full resource name,
``projects/<p>/locations/<loc>/templates/<id>``); otherwise every call is a pass-through no-op,
so a memory/guard-off deployment and the offline tests never call out. The endpoint region is
derived from the template name, keeping the call in-region. Best-effort: any Model Armor error
returns the text unchanged -- content safety must never hard-fail a write or an answer on an
availability blip.
"""

from __future__ import annotations

import contextlib
import os
from dataclasses import dataclass, field

_ENV = "BRAIN_MODEL_ARMOR_TEMPLATE"

# Responsible-AI subtype -> a short, user-facing flag label.
_RAI_LABEL = {
    "hate_speech": "hate-speech",
    "dangerous": "dangerous-content",
    "harassment": "harassment",
    "sexually_explicit": "sexual-content",
}


@dataclass
class Verdict:
    """The outcome of one scan: the (possibly redacted) text plus what was found."""

    text: str
    redactions: list[str] = field(default_factory=list)  # infoTypes redacted, e.g. ["PASSWORD"]
    flags: list[str] = field(default_factory=list)  # e.g. ["prompt-injection", "hate-speech"]

    @property
    def changed(self) -> bool:
        return bool(self.redactions)

    def note(self) -> str:
        """A short human note for the UI, or '' when nothing was found."""
        parts = []
        if self.redactions:
            parts.append("redacted " + ", ".join(sorted({r.lower() for r in self.redactions})))
        if self.flags:
            parts.append("flagged " + ", ".join(sorted(set(self.flags))))
        return "Model Armor " + "; ".join(parts) if parts else ""


def _template() -> str | None:
    return os.environ.get(_ENV, "").strip() or None


def enabled() -> bool:
    return _template() is not None


def _endpoint(template: str) -> str:
    """The regional Model Armor endpoint for a template resource name (keeps the call
    in-region: ``.../locations/europe-west2/...`` -> ``modelarmor.europe-west2.rep...``)."""
    location = template.split("/locations/", 1)[1].split("/", 1)[0]
    return f"https://modelarmor.{location}.rep.googleapis.com/v1"


def _redact(text: str, findings: list[dict]) -> tuple[str, list[str]]:
    """Replace each SDP finding's code-point range with ``[redacted:<infotype>]``.

    Applied back-to-front so earlier replacements don't shift later ranges. Uses codepoint
    (not byte) offsets, which match Python string indexing."""
    spans = []
    for f in findings:
        cr = (f.get("location") or {}).get("codepointRange") or {}
        if "start" in cr and "end" in cr:
            spans.append((int(cr["start"]), int(cr["end"]), f.get("infoType", "INFO")))
    redacted: list[str] = []
    for start, end, info_type in sorted(spans, key=lambda s: s[0], reverse=True):
        text = f"{text[:start]}[redacted:{info_type.lower()}]{text[end:]}"
        redacted.append(info_type)
    return text, redacted


def _parse(result: dict, text: str) -> Verdict:
    filters = ((result or {}).get("sanitizationResult") or {}).get("filterResults") or {}

    sdp = ((filters.get("sdp") or {}).get("sdpFilterResult") or {}).get("inspectResult") or {}
    redactions: list[str] = []
    if sdp.get("matchState") == "MATCH_FOUND":
        text, redactions = _redact(text, sdp.get("findings") or [])

    flags: list[str] = []
    pj = (filters.get("pi_and_jailbreak") or {}).get("piAndJailbreakFilterResult") or {}
    if pj.get("matchState") == "MATCH_FOUND":
        flags.append("prompt-injection")

    rai = (filters.get("rai") or {}).get("raiFilterResult") or {}
    if rai.get("matchState") == "MATCH_FOUND":
        subtypes = rai.get("raiFilterTypeResults") or {}
        hit = [
            _RAI_LABEL.get(k, k)
            for k, v in subtypes.items()
            if (v or {}).get("matchState") == "MATCH_FOUND"
        ]
        flags.extend(hit or ["unsafe-content"])

    return Verdict(text=text, redactions=redactions, flags=flags)


def scan(text: str, *, kind: str = "response") -> Verdict:
    """Scan ``text`` through Model Armor and return a (possibly redacted) :class:`Verdict`.

    ``kind='prompt'`` uses ``sanitizeUserPrompt`` (for agent input; catches prompt injection),
    otherwise ``sanitizeModelResponse`` (for written content and answers). A no-op pass-through
    when unconfigured, empty, or on any error."""
    template = _template()
    if not template or not text or not text.strip():
        return Verdict(text=text)
    with contextlib.suppress(Exception):  # best-effort: never block on a Model Armor error
        import google.auth
        import google.auth.transport.requests

        method = "sanitizeUserPrompt" if kind == "prompt" else "sanitizeModelResponse"
        payload = (
            {"userPromptData": {"text": text}}
            if kind == "prompt"
            else {"modelResponseData": {"text": text}}
        )
        creds, _ = google.auth.default()
        session = google.auth.transport.requests.AuthorizedSession(creds)
        resp = session.post(f"{_endpoint(template)}/{template}:{method}", json=payload, timeout=10)
        resp.raise_for_status()
        return _parse(resp.json(), text)
    return Verdict(text=text)
