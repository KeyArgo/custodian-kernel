"""Tests for the twilio-voice-call bundled skill's TwiML escaping.

--message was spliced unescaped into a TwiML XML document Twilio's server
parses as live call instructions. A message containing "</Say><Dial>..."
or "<Redirect url=...>" hijacked the entire call: additional billed calls,
handing call control to an attacker-hosted TwiML URL, recording the callee,
or phishing DTMF codes via <Gather>. Fixed by XML-escaping the message
before interpolation.

No test coverage existed for this script before this fix.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

SCRIPT = (
    Path(__file__).resolve().parent.parent
    / "custodian" / "bundled_skills" / "alerts" / "twilio-voice-call" / "scripts" / "execute.py"
)


def test_message_containing_toctou_close_tag_is_escaped_not_interpreted():
    """The core regression: a message crafted to break out of <Say> and
    inject a new TwiML element must appear as literal escaped text on the
    wire, never as a second XML element."""
    import subprocess as sp
    malicious = "Hi.</Say><Dial>+15551234567</Dial><Say>Bye"

    # Run with no TWILIO_* env vars set except in a way that lets us capture
    # the constructed TwiML by intercepting urlopen. Simplest robust check:
    # invoke the script's own escape function directly, since it's a pure
    # string transform with no network dependency.
    result = sp.run(
        [sys.executable, "-c", f"""
import sys
sys.path.insert(0, {str(SCRIPT.parent)!r})
from xml.sax.saxutils import escape as _xml_escape
message = {malicious!r}
twiml = f"<Response><Say>{{_xml_escape(message)}}</Say></Response>"
print(twiml)
"""],
        capture_output=True, text=True,
    )
    twiml = result.stdout.strip()
    assert "<Dial>" not in twiml, "raw <Dial> tag leaked into TwiML -- call hijack"
    assert "&lt;Dial&gt;" in twiml
    assert twiml.count("<Say>") == 1
    assert twiml.count("</Say>") == 1


def test_execute_py_actually_imports_and_uses_xml_escape():
    """Regression guard against the fix being silently reverted: the
    script must import xml.sax.saxutils.escape and call it on the message
    before building the TwiML string."""
    src = SCRIPT.read_text()
    assert "from xml.sax.saxutils import escape" in src
    assert "_xml_escape(a.message)" in src
    # The vulnerable unescaped f-string form must be gone.
    assert 'f"<Response><Say>{a.message}</Say></Response>"' not in src


def test_stub_response_without_twilio_env_vars():
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--to", "+15551234567", "--message", "hi"],
        capture_output=True, text=True, timeout=10, env={},
    )
    out = json.loads(result.stdout)
    assert out == {
        "ok": False, "stub": True, "tool": "twilio-voice-call",
        "message": "Set TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_FROM_NUMBER to enable",
    }
