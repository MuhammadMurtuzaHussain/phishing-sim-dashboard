"""Build the dashboard as one self-contained HTML file.

    python -m psim.build                   # writes site/index.html
    python -m psim.build --out public      # somewhere else

The page needs no network: the font, styles, script and data are all inlined. Every statistic is
computed here (psim/analysis.py), so the script in the page only draws. The text of the reading is
generated from those statistics, and the claims it makes are checked before the file is written, so
the page cannot say something the data no longer supports.
"""
from __future__ import annotations

import argparse
import base64
import html
import json
from pathlib import Path

import pandas as pd

from . import config as cfg
from .analysis import analyse, excludes_zero
from .generate import DEFAULT_OUT

WEB = Path(__file__).parent / "web"
READING_DOC = Path("docs") / "behavioural-reading.md"
REPO_URL = "https://github.com/MuhammadMurtuzaHussain/phishing-sim-dashboard"
MINUS = "−"

SHORT = {
    "none": "Control",
    "warning_banner": "Banner",
    "social_norm": "Social norm",
    "loss_framing": "Loss framing",
    "just_in_time_tip": "Tip",
    "easy_report_prompt": "Report prompt",
}

# --- Colour ------------------------------------------------------------------------------------
# Two themes from one set of roles. Orange means the risky direction (more clicks, fewer reports) and
# blue the protective one, in every chart. Both pass the palette validator against their own surface.

BASE_LIGHT = {
    "page": "#f6f7f8", "raised": "#ffffff", "ink": "#10151b", "ink-2": "#4a525c", "ink-3": "#69727c",
    "grid": "#e3e6ea", "axis": "#c5cad1", "click": "#e6612c", "report": "#2a78d6", "focus": "#2a78d6",
    "wash-good": "rgba(42,120,214,.09)", "wash-bad": "rgba(230,97,44,.09)", "whisker": "rgba(74,82,92,.55)",
    "shadow": "0 6px 24px rgba(16,21,27,.14)",
}
BASE_DARK = {
    "page": "#14181d", "raised": "#1d232a", "ink": "#e8ecf0", "ink-2": "#b4bcc6", "ink-3": "#8d96a1",
    "grid": "#242a31", "axis": "#38404a", "click": "#d95926", "report": "#3987e5", "focus": "#6aaaf0",
    "wash-good": "rgba(57,135,229,.14)", "wash-bad": "rgba(217,89,38,.14)", "whisker": "rgba(180,188,198,.55)",
    "shadow": "0 6px 24px rgba(0,0,0,.5)",
}
DIVERGING = {  # neutral midpoint and the two end colours of the diverging scale, per theme
    "light": {"n": "#e6e9ec", "b": "#1f5fb0", "o": "#c4481a"},
    "dark": {"n": "#2a3139", "b": "#6aaaf0", "o": "#f0814d"},
}
STEPS = (0.30, 0.52, 0.76, 1.0)
DARK_INK = "#10151b"  # text on a bright fill; white is the other candidate, whichever contrasts more


def _to_linear(c: float) -> float:
    c /= 255
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _from_linear(c: float) -> float:
    c = max(0.0, min(1.0, c))
    return 255 * (12.92 * c if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055)


def _rgb(hex_: str) -> tuple[int, int, int]:
    return int(hex_[1:3], 16), int(hex_[3:5], 16), int(hex_[5:7], 16)


def _oklab(hex_: str) -> tuple[float, float, float]:
    r, g, b = (_to_linear(v) for v in _rgb(hex_))
    l_ = (0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b) ** (1 / 3)
    m_ = (0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b) ** (1 / 3)
    s_ = (0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b) ** (1 / 3)
    return (
        0.2104542553 * l_ + 0.7936177850 * m_ - 0.0040720468 * s_,
        1.9779984951 * l_ - 2.4285922050 * m_ + 0.4505937099 * s_,
        0.0259040371 * l_ + 0.7827717662 * m_ - 0.8086757660 * s_,
    )


def _hex(lab: tuple[float, float, float]) -> str:
    big_l, a, b = lab
    l_ = (big_l + 0.3963377774 * a + 0.2158037573 * b) ** 3
    m_ = (big_l - 0.1055613458 * a - 0.0638541728 * b) ** 3
    s_ = (big_l - 0.0894841775 * a - 1.2914855480 * b) ** 3
    rgb = (
        4.0767416621 * l_ - 3.3077115913 * m_ + 0.2309699292 * s_,
        -1.2684380046 * l_ + 2.6097574011 * m_ - 0.3413193965 * s_,
        -0.0041960863 * l_ - 0.7034186147 * m_ + 1.7076147010 * s_,
    )
    return "#" + "".join(f"{round(_from_linear(v)):02x}" for v in rgb)


def _mix(a: str, b: str, t: float) -> str:
    (l1, a1, b1), (l2, a2, b2) = _oklab(a), _oklab(b)
    return _hex((l1 + (l2 - l1) * t, a1 + (a2 - a1) * t, b1 + (b2 - b1) * t))


def _luminance(hex_: str) -> float:
    r, g, b = (_to_linear(v) for v in _rgb(hex_))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast(a: str, b: str) -> float:
    hi, lo = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def theme_css(theme: str) -> str:
    """Custom properties for one theme: the base roles and the diverging scale with its text colours."""
    base = BASE_LIGHT if theme == "light" else BASE_DARK
    div = DIVERGING[theme]
    props = dict(base)
    props["n"] = div["n"]
    props["n-ink"] = base["ink"]
    for arm in ("b", "o"):
        for i, t in enumerate(STEPS, start=1):
            colour = _mix(div["n"], div[arm], t)
            props[f"{arm}{i}"] = colour
            props[f"{arm}{i}-ink"] = max(("#ffffff", DARK_INK), key=lambda c: _contrast(colour, c))
    return ";".join(f"--{k}:{v}" for k, v in props.items())


# --- Formatting --------------------------------------------------------------------------------

def esc(text: object) -> str:
    return html.escape(str(text), quote=True)


def pct(x: float, digits: int = 1) -> str:
    return f"{x * 100:.{digits}f}%"


def signed(x: float, digits: int = 1) -> str:
    v = round(x * 100, digits)
    sign = "+" if v > 0 else MINUS if v < 0 else ""
    return f"{sign}{abs(v):.{digits}f}"


def interval_pct(e: dict) -> str:
    return f"{e['lo'] * 100:.1f}–{e['hi'] * 100:.1f}"


def interval_pp(e: dict) -> str:
    return f"{signed(e['lo'])} to {signed(e['hi'])}"


def join_names(names: list[str]) -> str:
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


NUMBER_WORDS = {1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six", 7: "seven", 8: "eight",
                9: "nine", 10: "ten"}


def word(n: int) -> str:
    return NUMBER_WORDS.get(n, str(n))


# --- The story, and the checks that keep it honest ---------------------------------------------

class StoryError(RuntimeError):
    """Raised when a sentence on the page would no longer match the data."""


def story(a: dict) -> dict:
    """Pick out the results the text talks about and verify every claim made about them."""
    n = {x["key"]: x for x in a["nudges"]}
    depts = {d["name"]: d for d in a["departments"]}
    ov_click, ov_report = a["overall"]["click"]["est"], a["overall"]["report"]["est"]
    treatments = [x for x in a["nudges"] if x["key"] != "none"]

    best_click = min(treatments, key=lambda x: x["d_click"]["est"])
    best_report = max(treatments, key=lambda x: x["d_report"]["est"])
    banner, norm, loss = n["warning_banner"], n["social_norm"], n["loss_framing"]
    tip, prompt = n["just_in_time_tip"], n["easy_report_prompt"]

    exposed = sorted((d for d in depts.values() if d["click"]["est"] > ov_click and d["report"]["est"] < ov_report),
                     key=lambda d: -d["click"]["est"])
    resilient = sorted((d for d in depts.values() if d["click"]["est"] < ov_click and d["report"]["est"] > ov_report),
                       key=lambda d: d["click"]["est"])
    grouped = {d["name"] for d in exposed + resilient}
    other = [d for d in depts.values() if d["name"] not in grouped]
    lowest_reporter = min(depts.values(), key=lambda d: d["report"]["est"])

    sig_click = [c for c in a["cells"] if excludes_zero(c["d_click"])]
    sig_report = [c for c in a["cells"] if excludes_zero(c["d_report"])]
    prompt_cells = [c for c in a["cells"] if c["nudge"] == "easy_report_prompt"]

    claims = {
        "the best click nudge is not the best report nudge": best_click["key"] != best_report["key"],
        "the best click nudge cut clicks beyond chance": excludes_zero(best_click["d_click"]),
        "the best report nudge lifted reports beyond chance": excludes_zero(best_report["d_report"]),
        "the best report nudge left clicks unchanged": not excludes_zero(best_report["d_click"]),
        "the banner cut clicks beyond chance": excludes_zero(banner["d_click"]) and banner["d_click"]["est"] < 0,
        "the banner did not lift reports beyond chance": not excludes_zero(banner["d_report"]),
        "social norm and tip moved both behaviours": all(
            excludes_zero(x["d_click"]) and x["d_click"]["est"] < 0
            and excludes_zero(x["d_report"]) and x["d_report"]["est"] > 0 for x in (norm, tip)),
        "loss framing moved neither behaviour beyond chance":
            not excludes_zero(loss["d_click"]) and not excludes_zero(loss["d_report"]),
        "the report prompt shortened time to report":
            prompt["median_minutes_to_report"] < n["none"]["median_minutes_to_report"],
        "the exposed and quiet group has at least three departments": len(exposed) >= 3,
        "the resilient group has at least two departments": len(resilient) >= 2,
        "one department is outside both groups and reports least":
            len(other) == 1 and other[0]["name"] == lowest_reporter["name"],
        "the cell evidence is thin":
            len(sig_click) < 0.4 * len(a["cells"]) and len(sig_report) < 0.4 * len(a["cells"]),
        "the report prompt lifted reports in every department": all(c["d_report"]["est"] > 0 for c in prompt_cells),
        "risk is concentrated": a["individuals"]["top_decile_click_share"] > 0.25,
        "departments differ more in reporting than in clicking": (
            max(d["report"]["est"] for d in depts.values()) - min(d["report"]["est"] for d in depts.values())
            > max(d["click"]["est"] for d in depts.values()) - min(d["click"]["est"] for d in depts.values())),
    }
    failed = [claim for claim, ok in claims.items() if not ok]
    if failed:
        raise StoryError("The reading no longer matches the data: " + "; ".join(failed)
                         + ". Review the text in psim/build.py before building.")

    return {
        "n": n, "best_click": best_click, "best_report": best_report,
        "banner": banner, "norm": norm, "loss": loss, "tip": tip, "prompt": prompt,
        "exposed": exposed, "resilient": resilient, "other": other[0],
        "sig_click": sig_click, "sig_report": sig_report, "prompt_cells": prompt_cells,
    }


def lede(s: dict) -> str:
    bc, br = s["best_click"], s["best_report"]
    return (f"The {bc['label'].lower()} cut clicks by {abs(bc['d_click']['est']) * 100:.1f} points. "
            f"The {br['label'].lower()} lifted reports by {br['d_report']['est'] * 100:.1f} points "
            "and did not move clicks.")


def provenance(a: dict) -> str:
    m = a["meta"]
    return (f"Synthetic data: {m['rows']:,} simulated phishing emails sent to {m['employees']:,} employees in "
            f"{len(cfg.DEPARTMENTS)} departments over {m['campaigns']} monthly campaigns, April to September 2026. "
            "Intervals are 95% and resample employees rather than emails.")


def reading_blocks(a: dict, s: dict) -> tuple[list[tuple[str, str]], list[str]]:
    """The behavioural reading as (heading, paragraph) pairs plus the list of things to test next."""
    n, ind = s["n"], a["individuals"]
    banner, norm, tip, prompt = s["banner"], s["norm"], s["tip"], s["prompt"]
    ctrl = n["none"]
    exposed, resilient, other = s["exposed"], s["resilient"], s["other"]
    ex_click = [d["click"]["est"] for d in exposed]
    ex_report = [d["report"]["est"] for d in exposed]
    smallest = min(s["sig_click"], key=lambda c: c["n"])
    smallest_label = n[smallest["nudge"]]["label"].lower()
    total = len(s["prompt_cells"])
    prompt_up = sum(c["d_report"]["est"] > 0 for c in s["prompt_cells"])
    prompt_sig = sum(excludes_zero(c["d_report"]) for c in s["prompt_cells"])

    norm_up = norm["departments_more_reports"]
    if norm_up == norm["departments_total"] == prompt_up == total:
        steady = f"the social norm and the report prompt each lifted reports in all {word(total)} departments"
    else:
        steady = (f"the social norm lifted reports in {word(norm_up)} of {word(norm['departments_total'])} and the "
                  f"report prompt in {word(prompt_up)} of {word(total)}")

    blocks = [
        ("Clicking and reporting have different levers",
         f"The banner and the tip act at the moment of the click: they cut clicks by "
         f"{abs(banner['d_click']['est']) * 100:.1f} and {abs(tip['d_click']['est']) * 100:.1f} points. "
         f"Reporting responds to effort and norms. The easy-report prompt lifted reports from "
         f"{pct(ctrl['report']['est'])} to {pct(prompt['report']['est'])} and cut the median time to report from "
         f"{ctrl['median_minutes_to_report']:.0f} to {prompt['median_minutes_to_report']:.0f} minutes, "
         f"with no detectable change in clicks. A click is a fast decision taken in the middle of a task. A report "
         f"is a deliberate act that costs time and a little standing, so making it one tap and visibly normal is "
         f"what moves it. The banner warns without making reporting any easier, and lifted reports by only "
         f"{banner['d_report']['est'] * 100:.1f} points, which is within chance."),
        ("Some nudges do both, and one does neither",
         f"The social norm cut clicks by {abs(norm['d_click']['est']) * 100:.1f} points and lifted reports by "
         f"{norm['d_report']['est'] * 100:.1f}. The tip did the same by {abs(tip['d_click']['est']) * 100:.1f} and "
         f"{tip['d_report']['est'] * 100:.1f}. Loss framing produced no change that can be told apart from zero on "
         f"either measure. The direction is steady across departments: {steady}."),
        ("Departments differ more in reporting than in clicking",
         f"{word(len(exposed)).capitalize()} departments click more than the organisation average and report less: "
         f"{join_names([d['name'] for d in exposed])}. They clicked {min(ex_click) * 100:.0f}% to "
         f"{max(ex_click) * 100:.0f}% of the time and reported {min(ex_report) * 100:.0f}% to "
         f"{max(ex_report) * 100:.0f}%. {join_names([d['name'] for d in resilient])} sit at the other end. "
         f"{other['name']} clicks less than average but reports least of all ({pct(other['report']['est'])}); with "
         f"{other['employees']} people its interval runs from {pct(other['report']['lo'])} to "
         f"{pct(other['report']['hi'])}, so it earns a closer look rather than a conclusion. The exposed and quiet "
         "group is where a reporting nudge has the most room, and where a click rate alone would understate the "
         "problem."),
        ("Risk is concentrated in a few people, and so is silence",
         f"{pct(ind['never_clicked_share'], 0)} of employees never clicked in six simulations, while the top tenth "
         f"account for {pct(ind['top_decile_click_share'], 0)} of all clicks. At the other end, "
         f"{pct(ind['never_reported_share'], 0)} never reported once. A supportive conversation with repeat clickers "
         "reaches a large share of the risk with a small share of staff, which blanket retraining does not, provided "
         "the results are never used for discipline."),
        ("Department-level effects are mostly leads, not findings",
         f"{len(s['sig_click'])} of {len(a['cells'])} department-by-nudge cells show a click change whose interval "
         f"excludes zero, and {len(s['sig_report'])} of {len(a['cells'])} show a report change. With "
         f"{2 * len(a['cells'])} comparisons (two measures in each cell), a handful would clear that bar by "
         f"chance, and the {smallest_label} result for {smallest['department']} "
         f"({signed(smallest['d_click']['est'])} points on {smallest['n']} emails) is the "
         f"kind to distrust. The report prompt is the consistent one: it lifted reports in {word(prompt_up)} of "
         f"{word(total)} departments, beyond chance in {word(prompt_sig)}. Treat the nudge-level results as the "
         "evidence and the department cells as hypotheses for the next round."),
    ]
    nxt = [
        "Run the tip and the report prompt together. They act on different behaviours, so their effects may add up; "
        "this data cannot say whether they do.",
        "Rotate or retire the banner and measure whether its effect fades with repeat exposure. Each person sees a "
        "given nudge about once in six campaigns here, too rarely to show it.",
        "Name the primary outcome before the next round: report rate and time to report, which the security team acts "
        "on, with click rate as the secondary measure.",
    ]
    return blocks, nxt


def reading(a: dict, s: dict) -> str:
    blocks, nxt = reading_blocks(a, s)
    items = "".join(f"<h3>{esc(title)}</h3><p>{esc(text)}</p>" for title, text in blocks)
    steps = "".join(f"<li>{esc(t)}</li>" for t in nxt)
    return f'{items}<h3>What to test next</h3><ul class="next">{steps}</ul>'


def reading_markdown(a: dict) -> str:
    """The same reading as a standalone document, so it can be read on GitHub without opening the page."""
    s = story(a)
    blocks, nxt = reading_blocks(a, s)
    rows = []
    for x in a["nudges"]:
        control = x["key"] == "none"
        change_c = "–" if control else f"{signed(x['d_click']['est'])} ({interval_pp(x['d_click'])})"
        change_r = "–" if control else f"{signed(x['d_report']['est'])} ({interval_pp(x['d_report'])})"
        rows.append(f"| {x['label']} | {x['n']:,} | {pct(x['click']['est'])} | {change_c} | "
                    f"{pct(x['report']['est'])} | {change_r} |")
    table = "\n".join([
        "| Nudge | Emails | Click rate | Change in clicks (points) | Report rate | Change in reports (points) |",
        "| --- | ---: | ---: | ---: | ---: | ---: |", *rows])
    parts = [
        "# Behavioural reading",
        "<!-- Generated by `python -m psim.build`. Edit the text in psim/build.py, not this file. -->",
        f"{lede(s)} {provenance(a)}",
        "This is a worked reading of synthetic results. The size of every effect is an assumption set in "
        "[`psim/config.py`](../psim/config.py), so the point is how to read this kind of result, not that any nudge "
        "works in practice.",
        "## The result in one table",
        table,
        "Changes are against the emails that carried no nudge; intervals are 95% and resample employees, not emails.",
        *[f"## {title}\n\n{text}" for title, text in blocks],
        "## What to test next",
        "\n".join(f"- {t}" for t in nxt),
        "## What this reading cannot show",
        "- **Real effects.** Nothing here measures a real workforce. A different organisation, lure style or "
        "reporting button would give different numbers.\n"
        "- **Lasting change.** Six monthly campaigns, with each person seeing a given nudge about once, say nothing "
        "about habituation or about behaviour outside the simulation.\n"
        "- **Accuracy of reports.** A report shows willingness to act, not that the email was judged correctly. A "
        "programme that rewards reporting should also track false reports and how quickly the team triages them.\n"
        "- **Compromise.** A click is a proxy for exposure. It does not say whether credentials were entered or "
        "whether other controls would have stopped the attack.",
        "## If this were real data",
        "Employee-level click and report data is personal data under GDPR, and results can feel punitive. Agree the "
        "purpose, retention and access with HR and data protection first, report at department level only above a "
        "minimum group size, and keep individual results out of disciplinary processes. A programme like this "
        "supports, but does not satisfy, the awareness and training expectations in ISO/IEC 27001:2022 Annex A 6.3 "
        "and NIS2 Article 21(2)(g).",
    ]
    return "\n\n".join(parts) + "\n"


# --- Tables (rendered as HTML so the page reads without scripts) ------------------------------

def _cell_change(e: dict) -> str:
    sig = excludes_zero(e)
    mark = '<span class="sr">, interval excludes zero</span>' if sig else ""
    return f'<td class="num{" sig" if sig else ""}">{signed(e["est"])}{mark}<small>{interval_pp(e)}</small></td>'


def nudge_table(a: dict) -> str:
    rows = []
    for x in a["nudges"]:
        control = x["key"] == "none"
        change_c = '<td class="num dash">–</td>' if control else _cell_change(x["d_click"])
        change_r = '<td class="num dash">–</td>' if control else _cell_change(x["d_report"])
        rows.append(
            f'<tr data-key="{esc(x["key"])}"><th scope="row">{esc(x["label"])}</th>'
            f'<td class="num">{x["n"]:,}</td>'
            f'<td class="num">{pct(x["click"]["est"])}<small>{interval_pct(x["click"])}</small></td>{change_c}'
            f'<td class="num">{pct(x["report"]["est"])}<small>{interval_pct(x["report"])}</small></td>{change_r}'
            f'<td class="num">{x["median_minutes_to_report"]:.0f}</td></tr>')
    return ('<table class="data"><caption>Click and report rates by nudge. Changes are in percentage points against '
            'the no-nudge emails; bold means the 95% interval excludes zero.</caption><thead><tr>'
            '<th scope="col">Nudge</th><th scope="col" class="num">Emails</th>'
            '<th scope="col" class="num">Click rate</th><th scope="col" class="num">Change in clicks</th>'
            '<th scope="col" class="num">Report rate</th><th scope="col" class="num">Change in reports</th>'
            '<th scope="col" class="num">Median minutes to report</th></tr></thead><tbody>'
            + "".join(rows) + "</tbody></table>")


def department_order(a: dict) -> list[str]:
    return [d["name"] for d in sorted(a["departments"], key=lambda d: -d["report"]["est"])]


def department_table(a: dict) -> str:
    by = {d["name"]: d for d in a["departments"]}
    rows = "".join(
        f'<tr data-key="{esc(name)}"><th scope="row">{esc(name)}</th><td class="num">{by[name]["employees"]}</td>'
        f'<td class="num">{pct(by[name]["click"]["est"])}<small>{interval_pct(by[name]["click"])}</small></td>'
        f'<td class="num">{pct(by[name]["report"]["est"])}<small>{interval_pct(by[name]["report"])}</small></td></tr>'
        for name in department_order(a))
    return ('<table class="data"><caption>Click and report rates by department, all nudges pooled, with 95% '
            'intervals.</caption><thead><tr><th scope="col">Department</th><th scope="col" class="num">Employees</th>'
            '<th scope="col" class="num">Click rate</th><th scope="col" class="num">Report rate</th></tr></thead>'
            f"<tbody>{rows}</tbody></table>")


def heat_tables(a: dict) -> str:
    cells = {(c["department"], c["nudge"]): c for c in a["cells"]}
    nudges = [k for k in cfg.NUDGES if k != "none"]
    out = []
    for metric, title in (("click", "Change in click rate"), ("report", "Change in report rate")):
        head = "".join(f'<th scope="col" class="num">{esc(cfg.NUDGES[k]["label"])}</th>' for k in nudges)
        body = []
        for name in department_order(a):
            tds = "".join(_cell_change(cells[(name, k)][f"d_{metric}"]) for k in nudges)
            body.append(f'<tr><th scope="row">{esc(name)}</th>{tds}</tr>')
        out.append(f'<div class="tbl-wrap"><table class="data"><caption>{title} against the same department’s '
                   "no-nudge emails, in percentage points, with 95% intervals; bold means the interval excludes "
                   f'zero.</caption><thead><tr><th scope="col">Department</th>{head}</tr></thead>'
                   f'<tbody>{"".join(body)}</tbody></table></div>')
    return "".join(out)


def campaign_table(a: dict) -> str:
    rows = "".join(
        f'<tr><th scope="row">{esc(c["id"])}</th><td>{esc(c["date"])}</td><td>{esc(c["lure"])}</td>'
        f'<td class="num">{pct(c["click"]["est"])}<small>{interval_pct(c["click"])}</small></td>'
        f'<td class="num">{pct(c["report"]["est"])}<small>{interval_pct(c["report"])}</small></td></tr>'
        for c in a["campaigns"])
    return ('<div class="tbl-wrap"><table class="data"><caption>Click and report rates by campaign, all nudges '
            'pooled, with 95% intervals.</caption><thead><tr><th scope="col">Campaign</th><th scope="col">Sent</th>'
            '<th scope="col">Lure</th><th scope="col" class="num">Click rate</th>'
            '<th scope="col" class="num">Report rate</th></tr></thead>'
            f"<tbody>{rows}</tbody></table></div>")


def mechanisms() -> str:
    items = "".join(f"<dt>{esc(v['label'])}</dt><dd>{esc(v['mechanism'])}</dd>"
                    for k, v in cfg.NUDGES.items() if k != "none")
    return f'<dl class="mech">{items}</dl>'


def notes(a: dict) -> str:
    m = a["meta"]
    return (
        "<h3>Method</h3>"
        f"<p>Rates are per simulated email. Intervals are 95% percentile intervals from {m['bootstrap_draws']:,} "
        "bootstrap resamples of employees, not emails, because the same person appears in several campaigns. A "
        "nudge and the control share each resample, so an interval on a difference allows for the overlap between "
        "them. Nudges were dealt out evenly within each department every campaign, so every comparison is within "
        "the same month and the same lure.</p>"
        "<h3>Synthetic data</h3>"
        "<p>No real people or messages are involved. The size of every effect is an assumption set in "
        f'<a href="{REPO_URL}/blob/main/psim/config.py">psim/config.py</a> and exported with the data, so the page '
        "can only recover what the generator put in. It shows how to read this kind of result, not that any nudge "
        "works in practice.</p>"
        "<h3>If this were real data</h3>"
        "<p>Employee-level click and report data is personal data under GDPR, and results can feel punitive. Agree "
        "the purpose, retention and access with HR and data protection first, report at department level only above a "
        "minimum group size, and keep individual results out of disciplinary processes. A programme like this "
        "supports, but does not satisfy, the awareness and training expectations in ISO/IEC 27001:2022 Annex A 6.3 and "
        "NIS2 Article 21(2)(g).</p>"
        f'<p class="links"><a href="{REPO_URL}">Source and tests</a>'
        f'<a href="{REPO_URL}/blob/main/docs/data-dictionary.md">Data dictionary</a>'
        '<a href="https://github.com/MuhammadMurtuzaHussain">Muhammad Murtuza Hussain</a></p>'
    )


# --- Assembly ----------------------------------------------------------------------------------

def safe_json(obj: object) -> str:
    text = json.dumps(obj, separators=(",", ":"), ensure_ascii=False)
    for ch, rep in (("<", "\\u003c"), (">", "\\u003e"), ("&", "\\u0026"), (" ", "\\u2028"), (" ", "\\u2029")):
        text = text.replace(ch, rep)
    return text


def font_face() -> str:
    data = (WEB / "fonts" / "schibsted-grotesk-latin-wght-normal.woff2").read_bytes()
    b64 = base64.b64encode(data).decode("ascii")
    return ('@font-face{font-family:"Schibsted Grotesk";font-style:normal;font-weight:400 900;font-display:swap;'
            f'src:url(data:font/woff2;base64,{b64}) format("woff2")}}')


def render(a: dict) -> str:
    s = story(a)
    payload = {**a, "order": department_order(a), "short": SHORT}
    css = (WEB / "style.css").read_text(encoding="utf-8")
    css = (css.replace("/*@font*/", font_face())
              .replace("/*@light*/", theme_css("light"))
              .replace("/*@dark*/", theme_css("dark")))
    page = (WEB / "template.html").read_text(encoding="utf-8")
    parts = {
        "@@CSS@@": css,
        "@@JS@@": (WEB / "app.js").read_text(encoding="utf-8"),
        "@@DATA@@": safe_json(payload),
        "@@LEDE@@": esc(lede(s)),
        "@@PROVENANCE@@": esc(provenance(a)),
        "@@MECHANISMS@@": mechanisms(),
        "@@NUDGE_TABLE@@": nudge_table(a),
        "@@DEPARTMENT_TABLE@@": department_table(a),
        "@@HEAT_TABLES@@": heat_tables(a),
        "@@CAMPAIGN_TABLE@@": campaign_table(a),
        "@@READING@@": reading(a, s),
        "@@NOTES@@": notes(a),
    }
    for key, value in parts.items():
        page = page.replace(key, value)
    return page


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--csv", type=Path, default=DEFAULT_OUT, help="events CSV (default: %(default)s)")
    parser.add_argument("--out", type=Path, default=Path("site"), help="output folder (default: %(default)s)")
    parser.add_argument("--reading", type=Path, default=READING_DOC,
                        help="where to write the reading as markdown (default: %(default)s; pass '' to skip)")
    args = parser.parse_args(argv)

    analysis = analyse(pd.read_csv(args.csv))
    try:
        page = render(analysis)
    except StoryError as err:
        print(f"error: {err}")
        return 1
    args.out.mkdir(parents=True, exist_ok=True)
    target = args.out / "index.html"
    target.write_text(page, encoding="utf-8")
    print(f"wrote {target} ({len(page) / 1024:.0f} KB)")
    if str(args.reading):
        args.reading.write_text(reading_markdown(analysis), encoding="utf-8")
        print(f"wrote {args.reading}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
