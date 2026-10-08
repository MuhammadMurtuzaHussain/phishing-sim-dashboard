"""Checks on the statistics behind the dashboard: point estimates match plain pandas, intervals behave,
and differences are taken against the right control."""
from __future__ import annotations

import copy
import math

import pytest

from psim import config as cfg
from psim.analysis import analyse, excludes_zero

NUDGE_KEYS = [k for k in cfg.NUDGES if k != "none"]


def test_shape(analysis):
    assert set(analysis) == {"meta", "overall", "nudges", "departments", "cells", "campaigns", "individuals"}
    assert analysis["overall"]["n"] == analysis["meta"]["rows"] == 7200
    assert [x["key"] for x in analysis["nudges"]] == list(cfg.NUDGES)
    assert {d["name"] for d in analysis["departments"]} == set(cfg.DEPARTMENTS)
    assert len(analysis["cells"]) == len(cfg.DEPARTMENTS) * len(NUDGE_KEYS)
    assert len(analysis["campaigns"]) == len(cfg.CAMPAIGNS)


def test_point_estimates_match_pandas(analysis, events):
    for x in analysis["nudges"]:
        rows = events[events["nudge_type"] == x["key"]]
        assert x["n"] == len(rows)
        assert x["click"]["est"] == pytest.approx(rows["clicked"].mean(), abs=1e-4)
        assert x["report"]["est"] == pytest.approx(rows["reported"].mean(), abs=1e-4)
    for d in analysis["departments"]:
        rows = events[events["department"] == d["name"]]
        assert d["n"] == len(rows)
        assert d["employees"] == rows["employee_id"].nunique()
        assert d["click"]["est"] == pytest.approx(rows["clicked"].mean(), abs=1e-4)
    for c in analysis["campaigns"]:
        rows = events[events["campaign_id"] == c["id"]]
        assert c["n"] == len(rows)
        assert c["report"]["est"] == pytest.approx(rows["reported"].mean(), abs=1e-4)


def test_every_interval_brackets_its_estimate(analysis):
    def estimates():
        yield analysis["overall"]["click"]
        yield analysis["overall"]["report"]
        for group in ("nudges", "departments", "campaigns"):
            for row in analysis[group]:
                yield row["click"]
                yield row["report"]
        for x in analysis["nudges"]:
            if x["key"] != "none":
                yield x["d_click"]
                yield x["d_report"]
        for c in analysis["cells"]:
            yield c["d_click"]
            yield c["d_report"]

    for e in estimates():
        assert e["lo"] <= e["est"] <= e["hi"]


def test_differences_are_arm_minus_control(analysis):
    control = next(x for x in analysis["nudges"] if x["key"] == "none")
    assert "d_click" not in control
    for x in analysis["nudges"]:
        if x["key"] == "none":
            continue
        assert x["d_click"]["est"] == pytest.approx(x["click"]["est"] - control["click"]["est"], abs=2e-4)
        assert x["d_report"]["est"] == pytest.approx(x["report"]["est"] - control["report"]["est"], abs=2e-4)


def test_cells_compare_against_their_own_departments_control(analysis, events):
    for c in analysis["cells"]:
        dept = events[events["department"] == c["department"]]
        control = dept[dept["nudge_type"] == "none"]
        arm = dept[dept["nudge_type"] == c["nudge"]]
        assert c["control_n"] == len(control)
        assert c["n"] == len(arm)
        assert c["control_click"] == pytest.approx(control["clicked"].mean(), abs=1e-4)
        assert c["d_click"]["est"] == pytest.approx(arm["clicked"].mean() - control["clicked"].mean(), abs=2e-4)
        assert c["d_report"]["est"] == pytest.approx(arm["reported"].mean() - control["reported"].mean(), abs=2e-4)


def test_nudge_department_counts(analysis):
    for x in analysis["nudges"]:
        if x["key"] == "none":
            continue
        assert x["departments_total"] == len(cfg.DEPARTMENTS)
        assert 0 <= x["departments_fewer_clicks"] <= x["departments_total"]
        assert 0 <= x["departments_more_reports"] <= x["departments_total"]
        cells = [c for c in analysis["cells"] if c["nudge"] == x["key"]]
        assert x["departments_more_reports"] == sum(c["d_report"]["est"] > 0 for c in cells)


def test_resampling_employees_gives_wider_intervals_than_treating_emails_as_independent(analysis):
    """People repeat across campaigns, so an interval that ignored that would be too tight."""
    overall = analysis["overall"]
    p, n = overall["click"]["est"], overall["n"]
    naive_width = 2 * 1.96 * math.sqrt(p * (1 - p) / n)
    assert overall["click"]["hi"] - overall["click"]["lo"] > 1.15 * naive_width


def test_same_seed_same_answer_and_a_different_seed_moves_the_intervals(events):
    a = analyse(events, seed=7, draws=300)
    b = analyse(events, seed=7, draws=300)
    c = analyse(events, seed=8, draws=300)
    assert a == b
    assert a["overall"]["click"]["est"] == c["overall"]["click"]["est"]
    assert a["overall"]["click"]["lo"] != c["overall"]["click"]["lo"]


def test_analysis_does_not_modify_its_input(events):
    before = events.copy(deep=True)
    analyse(events, draws=100)
    assert events.equals(before)


def test_excludes_zero():
    assert excludes_zero({"est": 0.02, "lo": 0.01, "hi": 0.03})
    assert excludes_zero({"est": -0.02, "lo": -0.03, "hi": -0.01})
    assert not excludes_zero({"est": 0.02, "lo": -0.01, "hi": 0.05})
    assert not excludes_zero({"est": 0.0, "lo": 0.0, "hi": 0.04})


def test_individual_level_shares_are_proportions(analysis):
    ind = analysis["individuals"]
    assert ind["employees"] == analysis["meta"]["employees"]
    for key in ("never_clicked_share", "never_reported_share", "top_decile_click_share"):
        assert 0 <= ind[key] <= 1


def test_headline_effects_point_the_way_the_generator_built_them(analysis):
    """The banner is built to cut clicks, the report prompt to lift reports; the analysis has to see both."""
    by = {x["key"]: x for x in analysis["nudges"]}
    assert by["warning_banner"]["d_click"]["est"] < 0
    assert by["easy_report_prompt"]["d_report"]["est"] > 0
    assert excludes_zero(by["easy_report_prompt"]["d_report"])
    assert by["easy_report_prompt"]["median_minutes_to_report"] < by["none"]["median_minutes_to_report"]


def test_deep_copy_round_trip_is_json_safe(analysis):
    import json
    assert json.loads(json.dumps(copy.deepcopy(analysis))) == analysis
