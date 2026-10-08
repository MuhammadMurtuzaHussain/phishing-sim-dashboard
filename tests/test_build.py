"""Checks on the built page: every claim in the text is tied to the data, the file is self-contained and
safe to embed data in, the colours clear contrast, and the committed reading is what the code produces."""
from __future__ import annotations

import copy
import json
import re
import shutil
import subprocess
from html.parser import HTMLParser
from pathlib import Path

import pytest

from psim import build
from psim import config as cfg
from psim.analysis import excludes_zero

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "psim" / "web"


@pytest.fixture(scope="module")
def page(analysis) -> str:
    return build.render(analysis)


class _Collect(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.ids: set[str] = set()
        self.tags: list[tuple[str, dict[str, str | None]]] = []

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))
        if dict(attrs).get("id"):
            self.ids.add(dict(attrs)["id"])


def _parsed(page: str) -> _Collect:
    parser = _Collect()
    parser.feed(page)
    return parser


# --- The story is checked against the data ----------------------------------------------------

def test_story_holds_for_the_committed_data(analysis):
    s = build.story(analysis)
    assert s["best_click"]["key"] != s["best_report"]["key"]
    assert len(s["exposed"]) >= 3 and len(s["resilient"]) >= 2


def test_story_refuses_a_page_the_data_no_longer_supports(analysis):
    flipped = copy.deepcopy(analysis)
    banner = next(x for x in flipped["nudges"] if x["key"] == "warning_banner")
    banner["d_click"] = {"est": -0.001, "lo": -0.02, "hi": 0.02}  # no longer beyond chance
    with pytest.raises(build.StoryError, match="banner"):
        build.story(flipped)


def test_story_refuses_when_the_report_prompt_stops_working(analysis):
    broken = copy.deepcopy(analysis)
    for c in broken["cells"]:
        if c["nudge"] == "easy_report_prompt":
            c["d_report"]["est"] = -abs(c["d_report"]["est"])
    with pytest.raises(build.StoryError):
        build.story(broken)


# --- The page ---------------------------------------------------------------------------------

def test_every_placeholder_is_filled(page):
    assert "@@" not in page
    assert "/*@" not in page


def test_page_leads_with_the_finding_and_numbers_come_from_the_data(page, analysis):
    s = build.story(analysis)
    assert "<h1" in page and "Clicking and reporting are different behaviours" in page
    lede = build.lede(s)
    assert lede in page.replace("&#x27;", "'")
    assert f"{abs(s['best_click']['d_click']['est']) * 100:.1f}" in lede


def test_page_is_self_contained(page):
    parsed = _parsed(page)
    for tag, attrs in parsed.tags:
        assert tag != "link", "no external stylesheets"
        if tag == "script":
            assert not attrs.get("src"), "no external scripts"
        for attr in ("src", "srcset", "action"):
            assert not attrs.get(attr, "") or attrs[attr].startswith("data:"), (tag, attrs)
    assert "@import" not in page
    assert not re.search(r"url\(\s*['\"]?https?:", page)
    assert not re.search(r"\bfetch\(|XMLHttpRequest|navigator\.sendBeacon", page)


def test_every_element_the_script_looks_up_exists(page):
    ids = set(re.findall(r"getElementById\('([^']+)'\)", (WEB / "app.js").read_text()))
    ids |= set(re.findall(r"register\('([^']+)'", (WEB / "app.js").read_text()))
    assert {"data", "theme", "chart-nudge", "chart-dept", "chart-heat", "chart-campaign"} <= ids
    assert ids <= _parsed(page).ids


def test_embedded_data_round_trips_and_cannot_close_the_script_tag(page, analysis):
    match = re.search(r'<script type="application/json" id="data">(.*?)</script>', page, re.S)
    assert match, "data block missing"
    raw = match.group(1)
    assert "</" not in raw and "<!--" not in raw
    payload = json.loads(raw)
    assert payload["overall"] == analysis["overall"]
    assert payload["order"] == build.department_order(analysis)


def test_safe_json_escapes_markup_and_line_separators():
    text = build.safe_json({"x": "</script><b>&  "})
    assert "<" not in text and ">" not in text and "&" not in text
    assert " " not in text and " " not in text
    assert json.loads(text) == {"x": "</script><b>&  "}


def test_text_from_the_data_is_escaped(analysis):
    hostile = copy.deepcopy(analysis)
    name = "<img src=x onerror=alert(1)>"
    old = hostile["departments"][0]["name"]
    hostile["departments"][0]["name"] = name
    for c in hostile["cells"]:
        if c["department"] == old:
            c["department"] = name
    page = build.render(hostile)
    assert name not in page
    assert "&lt;img src=x onerror=alert(1)&gt;" in page


def test_tables_are_in_the_html_so_the_page_reads_without_scripts(page, analysis):
    tables = page.count('<table class="data">')
    assert tables == 5  # nudges, departments, two heat tables, campaigns
    for x in analysis["nudges"]:
        assert x["label"] in page
    for name in cfg.DEPARTMENTS:
        assert name.replace("&", "&amp;") in page


def test_every_figure_has_a_table_twin_and_a_toggle(page):
    toggles = [attrs for tag, attrs in _parsed(page).tags if tag == "button" and "toggle" in (attrs.get("class") or "")]
    assert len(toggles) == 2  # the heatmaps and the campaign chart each have a table twin
    assert all(attrs.get("aria-pressed") == "false" for attrs in toggles)


def test_app_script_parses():
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    result = subprocess.run([node, "--check", str(WEB / "app.js")], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


# --- Colour -----------------------------------------------------------------------------------

def _tokens(theme: str) -> dict[str, str]:
    return dict(part[2:].split(":", 1) for part in build.theme_css(theme).split(";"))


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_heat_cell_text_is_readable(theme):
    t = _tokens(theme)
    for step in ("o4", "o3", "o2", "o1", "n", "b1", "b2", "b3", "b4"):
        assert build._contrast(t[f"{step}-ink"], t[step]) >= 4.5, (theme, step)


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_text_and_marks_clear_contrast_on_the_page(theme):
    t = _tokens(theme)
    for token in ("ink", "ink-2", "ink-3"):
        assert build._contrast(t[token], t["page"]) >= 4.5, (theme, token)
    for token in ("click", "report"):
        assert build._contrast(t[token], t["page"]) >= 3.0, (theme, token)


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_diverging_scale_runs_light_to_strong_on_each_arm(theme):
    t = _tokens(theme)
    lightness = [build._oklab(t[s])[0] for s in ("n", "b1", "b2", "b3", "b4")]
    steps = [abs(b - a) for a, b in zip(lightness, lightness[1:], strict=False)]
    assert all(step > 0.01 for step in steps), "each step must differ in lightness"
    assert (lightness == sorted(lightness)) or (lightness == sorted(lightness, reverse=True))


def test_orange_and_blue_keep_one_meaning_in_both_themes():
    for theme in ("light", "dark"):
        t = _tokens(theme)
        # orange is the risky direction, blue the protective one
        r, _, b = build._rgb(t["click"])
        assert r > b
        r, _, b = build._rgb(t["report"])
        assert b > r


# --- Generated documents ----------------------------------------------------------------------

def test_committed_reading_is_what_the_code_produces(analysis):
    committed = (ROOT / "docs" / "behavioural-reading.md").read_text(encoding="utf-8")
    expected = build.reading_markdown(analysis)
    assert committed == expected, "run `python -m psim.build` and commit docs/behavioural-reading.md"


def test_reading_document_carries_the_numbers_and_the_caveats(analysis):
    text = build.reading_markdown(analysis)
    for x in analysis["nudges"]:
        assert x["label"] in text
    assert "synthetic" in text.lower()
    assert "What this reading cannot show" in text
    assert "GDPR" in text and "Annex A 6.3" in text and "Article 21(2)(g)" in text


def test_reading_flags_the_fragile_cell(analysis):
    s = build.story(analysis)
    smallest = min(s["sig_click"], key=lambda c: c["n"])
    assert smallest["n"] < 60, "the text calls the smallest conclusive cell one to distrust; it must be small"
    assert excludes_zero(smallest["d_click"])


def test_cli_writes_the_page_and_the_reading(tmp_path):
    out, reading = tmp_path / "site", tmp_path / "reading.md"
    assert build.main(["--out", str(out), "--reading", str(reading)]) == 0
    assert (out / "index.html").stat().st_size > 50_000
    assert reading.read_text(encoding="utf-8").startswith("# Behavioural reading")
