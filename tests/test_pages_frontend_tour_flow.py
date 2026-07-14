from pathlib import Path


PAGES = Path(__file__).resolve().parents[1] / "pages-frontend"


def read_page(name: str) -> str:
    return (PAGES / name).read_text(encoding="utf-8")


def test_console_operator_and_triage_load_shared_tour_script():
    assert 'src="/site-tour.js"' in read_page("console.html")
    assert 'src="/site-tour.js"' in read_page("operator.html")
    assert 'src="/site-tour.js"' in read_page("triage.html")


def test_tools_and_docs_expose_judge_facing_guide_cards():
    tools = read_page("tools.html")
    docs = read_page("docs.html")

    assert 'id="tools-guide-card"' in tools
    assert 'id="tools-guide-copy"' in tools
    assert 'id="docs-guide-copy"' in docs
