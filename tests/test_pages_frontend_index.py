from pathlib import Path


INDEX_HTML = (
    Path(__file__).resolve().parents[1] / "pages-frontend" / "index.html"
)


def read_index() -> str:
    return INDEX_HTML.read_text(encoding="utf-8")


def test_hero_kernel_ticker_uses_fixed_badge_and_message_slots():
    html = read_index()

    assert 'id="kt-status"' in html
    assert 'id="kt-message"' in html
    assert "class=\"kernel-ticker\"" in html
    assert "class=\"kernel-status\"" in html
    assert "class=\"kernel-message\"" in html


def test_hero_terminal_and_visual_stack_have_stable_shell_classes():
    html = read_index()

    assert "class=\"hero-chip-row\"" in html
    assert "class=\"hero-proof-strip\"" in html
    assert "class=\"vkit-shell\"" in html
    assert "class=\"vkit-window\"" in html
