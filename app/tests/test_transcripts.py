"""Chat/transcript parsing for the Conversations and Voice & meetings connectors.

Pins the auto-detection: Teams/Graph JSON becomes a speaker-attributed thread, WebVTT
and SubRip lose their timestamps but keep the words, and anything else passes through.
"""

from __future__ import annotations

import json

import pytest

from brain_app.serving.transcripts import parse_transcript


def _msg(name, content):
    return {"from": {"user": {"displayName": name}}, "body": {"content": content}}


def test_teams_graph_json_becomes_a_thread():
    export = json.dumps(
        [_msg("Ada", "<p>Shipping today.</p>"), _msg("Grace", "Nice, I'll review.")]
    )
    title, body = parse_transcript(export)
    assert title == "Teams conversation"
    assert "**Ada:** Shipping today." in body
    assert "**Grace:** Nice, I'll review." in body
    assert "<p>" not in body  # HTML stripped


def test_teams_graph_value_wrapper_is_supported():
    export = json.dumps({"value": [_msg("Ada", "hi")]})
    title, body = parse_transcript(export)
    assert title == "Teams conversation"
    assert "**Ada:** hi" in body


def test_vtt_strips_timestamps_keeps_speakers():
    vtt = (
        "WEBVTT\n\n"
        "1\n00:00:01.000 --> 00:00:04.000\n<v Ada>Let's start.</v>\n\n"
        "2\n00:00:04.000 --> 00:00:06.000\n<v Grace>Agreed.</v>\n"
    )
    title, body = parse_transcript(vtt)
    assert title == "Meeting transcript"
    assert "**Ada:** Let's start." in body
    assert "**Grace:** Agreed." in body
    assert "-->" not in body and "00:00" not in body


def test_srt_strips_indices_and_timestamps():
    srt = (
        "1\n00:00:01,000 --> 00:00:03,000\nHello everyone\n\n"
        "2\n00:00:03,000 --> 00:00:05,000\nwelcome to the call\n"
    )
    title, body = parse_transcript(srt)
    assert title == "Meeting transcript"
    assert "Hello everyone" in body and "welcome to the call" in body
    assert "-->" not in body


def test_plain_text_passes_through():
    title, body = parse_transcript("Just some notes I typed.")
    assert title == ""
    assert body == "Just some notes I typed."


def test_empty_input_is_a_clean_error():
    with pytest.raises(ValueError):
        parse_transcript("   ")
