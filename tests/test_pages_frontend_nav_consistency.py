"""Cross-page nav consistency for the console-area pages.

Bug report 2026-07-19: /guardrails and /paladin were missing entirely from
some pages' top nav, /lie-catch and /triage were used interchangeably as
labels for the SAME link (a link to /triage was labeled "Lie-Catch" on
guardrails.html and paladin.html instead of the real /lie-catch page), and
docs.html had a broken CSS layout that collapsed its main content column
to one word per line. Each page's nav had drifted independently because
the nav markup is duplicated per-file with no shared source of truth and
nothing compared them -- the same failure mode as test_skill_trees_in_sync.py
covers for skills/ vs custodian/bundled_skills/, applied here to HTML.

If this fails: work out whether the new page belongs in the canonical set
(and add it to CANONICAL_LINKS + CONSOLE_AREA_PAGES here, in ACTIVE_HREF,
and in every page's nav), not just silence the assertion.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

PAGES_DIR = Path(__file__).resolve().parents[1] / "pages-frontend"

CONSOLE_AREA_PAGES = [
    "console.html", "docs.html", "guardrails.html", "lie-catch.html",
    "operator.html", "paladin.html", "tools.html", "triage.html",
]

CANONICAL_LINKS = [
    ("/", "Home"),
    ("/console", "Console"),
    ("/operator", "Operator"),
    ("/triage", "Triage"),
    ("/lie-catch", "Lie-Catch"),
    ("/guardrails", "Guardrails"),
    ("/paladin", "Paladin"),
    ("/tools", "Tools"),
    ("/docs", "Docs"),
]

ACTIVE_HREF = {
    "console.html": "/console",
    "docs.html": "/docs",
    "guardrails.html": "/guardrails",
    "lie-catch.html": "/lie-catch",
    "operator.html": "/operator",
    "paladin.html": "/paladin",
    "tools.html": "/tools",
    "triage.html": "/triage",
}

_LINK_RE = re.compile(r'<a href="([^"]+)"(\s+class="active")?>([^<]+)</a>')


def _read(page: str) -> str:
    return (PAGES_DIR / page).read_text(encoding="utf-8")


def _extract_k_links(html: str) -> list[tuple[str, str, bool]]:
    """Return [(href, text, is_active), ...] from the <div class="k-links"> block."""
    m = re.search(r'<div class="k-links">(.*?)</div>', html, re.DOTALL)
    assert m, "no <div class=\"k-links\"> nav block found"
    block = m.group(1)
    return [(href, text, bool(active)) for href, active, text in _LINK_RE.findall(block)]


@pytest.mark.parametrize("page", CONSOLE_AREA_PAGES)
def test_nav_has_canonical_link_set(page):
    """Every console-area page must expose the exact same nav links, in the
    same order, with the same labels."""
    links = _extract_k_links(_read(page))
    got = [(href, text) for href, text, _active in links]
    assert got == CANONICAL_LINKS, (
        f"{page}: nav link set/order doesn't match the canonical set.\n"
        f"Expected: {CANONICAL_LINKS}\nGot: {got}"
    )


@pytest.mark.parametrize("page", CONSOLE_AREA_PAGES)
def test_nav_marks_only_the_current_page_active(page):
    links = _extract_k_links(_read(page))
    active = [href for href, _text, is_active in links if is_active]
    assert active == [ACTIVE_HREF[page]], (
        f"{page}: expected only {ACTIVE_HREF[page]!r} marked active, got {active}"
    )


def test_no_page_mislabels_triage_link_as_lie_catch():
    """Regression: guardrails.html and paladin.html both linked to /triage
    but labeled it "Lie-Catch" -- the identity of the separate /lie-catch
    page. /triage must always read as Triage; only /lie-catch may use the
    Lie-Catch name."""
    offenders = []
    for f in PAGES_DIR.glob("*.html"):
        html = f.read_text(encoding="utf-8")
        for m in re.finditer(r'<a href="/triage"[^>]*>([^<]+)</a>', html):
            if "lie-catch" in m.group(1).lower():
                offenders.append(f"{f.name}: {m.group(0)!r}")
    assert not offenders, "links to /triage mislabeled as Lie-Catch:\n" + "\n".join(offenders)


def test_triage_page_identifies_itself_as_triage_not_lie_catch():
    """Regression: triage.html's own <h1> and Nemotron-guide copy claimed to
    BE the Lie-Catch page ("Lie-Catch: the AI reads it...", "lie-catch demo")
    while its <title> said "Refund Triage Walkthrough" -- internally
    inconsistent about its own identity, on top of colliding with the
    separate lie-catch.html page."""
    html = _read("triage.html")
    assert "<title>Custodian — Refund Triage Walkthrough</title>" in html
    assert "<h1>Lie-Catch:" not in html
    assert "the lie-catch demo" not in html.lower()


def test_docs_guide_card_is_inside_content_not_a_layout_sibling():
    """Regression: the Judge's Guide card sat directly inside
    <div class="layout"> (a flex row also containing the sidebar), making
    it an unintended third flex item that squeezed .content down to a
    sliver -- every line of body text wrapped to one word per line. It
    must be the first thing inside <main class="content">, not a sibling
    of <aside class="sidebar">."""
    html = _read("docs.html")
    layout_start = html.index('<div class="layout">')
    sidebar_start = html.index('<!-- SIDEBAR -->')
    content_start = html.index('<main class="content">')
    guide_card_start = html.index('id="docs-guide-card"')
    assert layout_start < sidebar_start < content_start < guide_card_start, (
        'expected order: <div class="layout"> ... <!-- SIDEBAR --> ... '
        '<main class="content"> ... docs-guide-card, got a different order '
        '-- docs-guide-card may have drifted back out into .layout'
    )


def test_docs_defines_every_css_variable_it_uses():
    """Regression: docs.html's Judge's Guide card used var(--violet) for
    its label/button color, but --violet was never defined in :root --
    an invalid custom property reference that silently fell back to the
    inherited text color instead of the intended accent."""
    html = _read("docs.html")
    root_match = re.search(r':root\s*\{(.*?)\}', html, re.DOTALL)
    assert root_match, "no :root block found in docs.html"
    defined = set(re.findall(r'(--[\w-]+)\s*:', root_match.group(1)))
    used = set(re.findall(r'var\((--[\w-]+)[,)]', html))
    missing = used - defined
    assert not missing, f"docs.html uses undefined CSS variables: {missing}"


def test_docs_sidebar_links_all_have_matching_section_ids():
    """Every #anchor the docs sidebar links to must have a matching
    id="anchor" section somewhere on the page -- otherwise the sidebar
    link silently does nothing."""
    html = _read("docs.html")
    sidebar_match = re.search(r'<aside class="sidebar".*?</aside>', html, re.DOTALL)
    assert sidebar_match, "no docs sidebar found"
    anchors = re.findall(r'href="#([\w-]+)"', sidebar_match.group(0))
    assert anchors, "no sidebar anchors found"
    for anchor in anchors:
        assert re.search(rf'id="{re.escape(anchor)}"', html), (
            f'sidebar links to #{anchor} but no element with id="{anchor}" exists'
        )


def test_docs_documents_guardrails_and_paladin():
    """Regression: docs.html linked to /guardrails and /paladin in its nav
    but never explained what either feature is anywhere in the page body."""
    html = _read("docs.html")
    assert 'id="guardrails"' in html, "docs.html has no Guardrails content section"
    assert 'id="paladin"' in html, "docs.html has no Paladin content section"
