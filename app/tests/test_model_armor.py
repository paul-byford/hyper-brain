"""Model Armor guard: redact-then-allow parsing and the unconfigured no-op.

The live detection is Google's; what is ours to keep correct is (1) we redact the exact ranges
Model Armor returns, back-to-front, so a secret never survives in stored/served text, (2) other
filter hits become flags (surfaced, not silently dropped), and (3) an unconfigured deployment is
a pure pass-through that never calls out. These hermetic tests pin exactly that.
"""

from __future__ import annotations

from brain_app.safety import model_armor as ma


def _response(findings=(), pi=False, rai=None):
    filters = {
        "sdp": {
            "sdpFilterResult": {
                "inspectResult": {
                    "matchState": "MATCH_FOUND" if findings else "NO_MATCH_FOUND",
                    "findings": list(findings),
                }
            }
        },
        "pi_and_jailbreak": {
            "piAndJailbreakFilterResult": {
                "matchState": "MATCH_FOUND" if pi else "NO_MATCH_FOUND"
            }
        },
    }
    if rai:
        filters["rai"] = {
            "raiFilterResult": {
                "matchState": "MATCH_FOUND",
                "raiFilterTypeResults": {k: {"matchState": "MATCH_FOUND"} for k in rai},
            }
        }
    return {"sanitizationResult": {"filterResults": filters}}


def _finding(info_type, start, end):
    return {"infoType": info_type, "location": {"codepointRange": {"start": start, "end": end}}}


def test_redacts_each_finding_in_place():
    text = "password is hunter2 and card 4111111111111111 here"
    findings = [_finding("PASSWORD", 12, 19), _finding("CREDIT_CARD_NUMBER", 29, 45)]
    v = ma._parse(_response(findings=findings), text)
    assert v.text == "password is [redacted:password] and card [redacted:credit_card_number] here"
    assert v.changed and set(v.redactions) == {"PASSWORD", "CREDIT_CARD_NUMBER"}
    assert "redacted credit_card_number, password" in v.note()


def test_overlapping_order_is_stable_back_to_front():
    # Two findings; applying back-to-front keeps the earlier range's offsets valid.
    text = "aaaa bbbb cccc"
    v = ma._parse(_response(findings=[_finding("X", 0, 4), _finding("Y", 10, 14)]), text)
    assert v.text == "[redacted:x] bbbb [redacted:y]"


def test_flags_prompt_injection_and_rai_without_redacting():
    v = ma._parse(_response(pi=True, rai=["hate_speech"]), "some text")
    assert not v.changed and v.text == "some text"
    assert "prompt-injection" in v.flags and "hate-speech" in v.flags


def test_clean_text_has_no_note():
    v = ma._parse(_response(), "a wholesome note about fraud detection")
    assert not v.changed and v.flags == [] and v.note() == ""


def test_unconfigured_scan_is_a_passthrough_noop(monkeypatch):
    monkeypatch.delenv("BRAIN_MODEL_ARMOR_TEMPLATE", raising=False)
    assert not ma.enabled()
    v = ma.scan("password is hunter2")  # must not call out
    assert v.text == "password is hunter2" and not v.changed


def test_endpoint_is_derived_in_region():
    tmpl = "projects/p/locations/europe-west2/templates/brain-guard"
    assert ma._endpoint(tmpl) == "https://modelarmor.europe-west2.rep.googleapis.com/v1"
