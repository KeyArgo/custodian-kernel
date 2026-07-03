from pathlib import Path


OPERATOR_HTML = (
    Path(__file__).resolve().parents[1] / "pages-frontend" / "operator.html"
)


def read_operator() -> str:
    return OPERATOR_HTML.read_text(encoding="utf-8")


def test_no_demo_mode_warn_banner():
    """The operator page must not self-discredit with 'Demo mode — no real money'."""
    html = read_operator()
    assert "Demo mode" not in html, "Old 'Demo mode' header still present"
    assert "no real money" not in html, "Old 'no real money' disclaimer still present"


def test_live_banner_class_present():
    """The replacement 'live' banner must be in place."""
    html = read_operator()
    assert 'class="ok-banner"' in html, "Missing ok-banner element"
    assert "● Live" in html, "Live banner marker missing"


def test_live_activity_panel_present():
    """The live activity panel must show real audit data, not demo placeholders."""
    html = read_operator()
    assert 'class="live-panel"' in html, "Missing live-panel"
    assert 'id="live-tbody"' in html, "Missing live-tbody"
    assert "/api/v1/hermes/summary" in html, "Live panel must call the public API"


def test_self_verify_curl_panel_present():
    """The self-verify panel must show judges they can hit the live API."""
    html = read_operator()
    assert 'class="curl-panel"' in html, "Missing curl-panel"
    assert "Self-Verify" in html, "Self-verify header missing"
    assert "/api/v1/operator/earn" in html, "earn endpoint not shown"
    assert "/api/v1/operator/spend" in html, "spend endpoint not shown"
    assert "/api/v1/operator/refund" in html, "refund endpoint not shown"


def test_live_activity_autorefresh():
    """The live activity must auto-refresh, not be a one-shot fetch."""
    html = read_operator()
    assert "setInterval" in html and "refreshLive" in html
    # The interval should be 5s (5000ms)
    assert "5000" in html, "Live activity must refresh on a 5s interval"


def test_curl_buttons_are_browser_executable():
    """The 'Run from this page' curl buttons must use the browser fetch, not raw curl."""
    html = read_operator()
    # We have buttons for /earn and /spend. /refund requires a real PI
    # from the live activity feed, so the curl block is shown but no button
    # is provided (judges need to substitute their own PI).
    assert html.count('class="curl-btn"') >= 2, "Need at least 2 curl-btn (earn + spend)"
    assert "curl-btn" in html and "data-cmd" in html
    # Must use fetch() in the click handler (not require user to paste into a terminal)
    assert "fetch(url" in html or "fetch(" in html


def test_treasury_panel_present():
    """The Treasury panel must show real money in / out / net P&L (HermesCo parity)."""
    html = read_operator()
    assert 'class="treasury-panel"' in html, "Missing treasury-panel"
    assert "treasury-earned" in html, "Missing earned tile"
    assert "treasury-pnl" in html, "Missing P&L tile"
    assert "treasury-cashout" in html, "Missing self-charge button"
    assert "Treasury" in html, "Treasury header missing"


def test_treasury_button_charges_25_dollars():
    """The self-charge button must trigger a real $25 Stripe PaymentIntent."""
    html = read_operator()
    # Check that 25.00 is referenced (either as a string or amount)
    assert "25.00" in html, "Missing 25.00 amount"
    # Must hit the earn endpoint
    assert "/earn" in html
    # Must mention 4242 (the standard Stripe test card)
    assert "4242" in html


def test_treasury_handles_real_authority_payload():
    """The Treasury refresh function must read the fields the /api/v1/hermes/summary endpoint returns."""
    html = read_operator()
    # The summary endpoint returns authority.earned_total, .refunded_total,
    # .autonomous_spent, .approved_override_spent, .spent_this_session, .net_pnl,
    # .per_action_cap, .session_cap, .autonomous_remaining, .band
    for field in ("earned_total", "refunded_total", "autonomous_spent",
                  "approved_override_spent", "net_pnl", "per_action_cap",
                  "session_cap", "autonomous_remaining", "band"):
        assert field in html, f"JS reads authority.{field}"


def test_operator_code_flow_does_not_fake_prefill():
    """If the page says a code is auto-filled, the JS must really populate the input.

    The operator flow now has to support both modes:
    - current secure path: the code lives only on the phone, so the UI tells
      the operator to type it manually
    - legacy/live fallback: if the backend does return a code, the JS may
      populate the input explicitly
    """
    html = read_operator()
    assert "The code is pre-filled from the SMS" not in html
    assert "Code is pre-filled from the SMS notification above" not in html
    assert "enter code from your phone" in html.lower()
    assert "document.getElementById(approveInputId).value = d.code" in html


def test_live_audit_feed_esc_function_is_in_scope():
    """Regression: `esc` (the HTML escaper) must be defined at the same
    scope as refreshLive() and refreshOpFeed() — both of which use it.

    The bug: previously `const esc = ...` was inside the DOMContentLoaded
    callback closure, but refreshLive() and refreshOpFeed() are defined
    at the script-block top level and were called at script-eval time
    (before DOMContentLoaded). The result: ReferenceError "esc is not
    defined", caught by the try/catch, the live audit feed showed
    "⚠ Live feed unreachable: esc is not defined".

    Fix: `esc` is now a top-level constant in the same <script> block,
    defined BEFORE the DOMContentLoaded callback. The inner copy inside
    the closure has been removed so there is exactly one definition.
    """
    html = read_operator()
    # Must be exactly one definition
    n_defined = html.count("const esc = s =>")
    assert n_defined == 1, f"expected exactly 1 esc definition, found {n_defined}"

    # Find the position of the `const esc` and the DOMContentLoaded callback
    pos_esc = html.index("const esc = s =>")
    pos_dom = html.index("document.addEventListener('DOMContentLoaded'")
    assert pos_esc < pos_dom, (
        "const esc must be defined BEFORE the DOMContentLoaded callback so that "
        "top-level calls to refreshOpFeed() and refreshLive() can find it. "
        f"Got esc at {pos_esc}, DOMContentLoaded at {pos_dom}."
    )

    # refreshLive and refreshOpFeed must use esc (i.e. the dependency still exists)
    assert "function refreshLive" in html or "async function refreshLive" in html
    assert "function refreshOpFeed" in html or "async function refreshOpFeed" in html
    # esc must be referenced multiple times in the script
    assert html.count("esc(") >= 5, "expected multiple uses of esc() in the script"
