"""Parse a chat export or a meeting transcript into a clean, speaker-attributed note.

This is the ingestion side of the Conversations (Microsoft Teams) and Voice & meetings
connectors. A live Teams connector needs an Azure AD app and Graph API consent in the
customer's own tenant, which is a configuration step (see the connector card); the part
that is the same regardless of how the export arrives is turning it into a governed note,
and that is what this does. It auto-detects the common shapes so the user can paste or
upload whatever their tool produced:

- Microsoft Teams / Graph ``chatMessages`` JSON (an array, or a ``{"value": [...]}``)
- WebVTT captions (``.vtt``) and SubRip subtitles (``.srt``) from meeting recordings
- plain text, passed through unchanged

Everything is done in-process with the standard library, so there is no new dependency
and no network call.
"""

from __future__ import annotations

import html
import json
import re

_TAG = re.compile(r"<[^>]+>")
_VTT_SPEAKER = re.compile(r"<v\s+([^>]+)>(.*?)</v>", re.IGNORECASE | re.DOTALL)
_TS_ARROW = "-->"


def _strip_html(value: str) -> str:
    return html.unescape(_TAG.sub("", value)).strip()


def parse_transcript(raw: str) -> tuple[str, str]:
    """Return ``(title, body)`` for a chat export or transcript. Falls back to passing
    plain text through unchanged. Raises ``ValueError`` on empty input."""
    text = (raw or "").strip()
    if not text:
        raise ValueError("no transcript or chat content was provided")
    if text[0] in "[{":
        teams = _try_teams_json(text)
        if teams is not None:
            return teams
    if text.upper().startswith("WEBVTT"):
        return "Meeting transcript", _parse_vtt(text)
    if _looks_like_srt(text):
        return "Meeting transcript", _parse_srt(text)
    return "", text


def _try_teams_json(text: str) -> tuple[str, str] | None:
    """Parse a Teams/Graph chatMessages export into a chronological note, or None."""
    try:
        data = json.loads(text)
    except ValueError:
        return None
    messages = data.get("value") if isinstance(data, dict) else data
    if not isinstance(messages, list) or not messages:
        return None
    lines: list[str] = []
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        frm = msg.get("from") or {}
        user = (frm.get("user") or frm.get("application") or {}) if isinstance(frm, dict) else {}
        speaker = (user.get("displayName") if isinstance(user, dict) else None) or "Unknown"
        body = msg.get("body") or {}
        content = body.get("content", "") if isinstance(body, dict) else str(body)
        message = _strip_html(content)
        if message:
            lines.append(f"**{speaker}:** {message}")
    if not lines:
        return None
    return "Teams conversation", "\n\n".join(lines)


def _parse_vtt(text: str) -> str:
    """Strip WebVTT cue numbers and timestamps, keep the spoken text (with speakers)."""
    out: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.upper().startswith(("WEBVTT", "NOTE")):
            continue
        if _TS_ARROW in stripped or stripped.isdigit():
            continue
        speaker_turn = _VTT_SPEAKER.search(stripped)
        if speaker_turn:
            out.append(f"**{speaker_turn.group(1).strip()}:** {_strip_html(speaker_turn.group(2))}")
        else:
            out.append(_strip_html(stripped))
    return "\n\n".join(p for p in out if p)


def _looks_like_srt(text: str) -> bool:
    # An SRT block is an index line, a "HH:MM:SS,mmm --> ..." line, then text.
    return bool(re.search(r"\n?\d+\s*\n\d{2}:\d{2}:\d{2},\d{3}\s*-->", text))


def _parse_srt(text: str) -> str:
    out: list[str] = []
    for block in re.split(r"\n\s*\n", text):
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        # Drop the leading index line and the timestamp line; keep the rest as text.
        kept = [line for line in lines if _TS_ARROW not in line and not line.isdigit()]
        if kept:
            out.append(" ".join(kept))
    return "\n\n".join(out)
