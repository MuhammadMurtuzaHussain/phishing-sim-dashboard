"""Checks on the synthetic dataset: structure, randomisation, internal consistency and the effects
the generator is supposed to have put in. They run against a freshly generated frame, and one test
confirms the committed CSV and assumptions file are exactly what the generator produces today."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from psim import config as cfg
from psim.generate import COLUMNS, DEFAULT_OUT, generate, write

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def df() -> pd.DataFrame:
    return generate()


# --- Configuration ----------------------------------------------------------------------------

def test_config_references_are_valid():
    for nudge, per_dept in cfg.DEPARTMENT_NUDGE_MODIFIER.items():
        assert nudge in cfg.NUDGES
        assert set(per_dept) <= set(cfg.DEPARTMENTS)
    for camp in cfg.CAMPAIGNS:
        assert set(camp["affinity"]) <= set(cfg.DEPARTMENTS)
    assert list(cfg.NUDGES)[0] == "none", "the control arm must come first"
    assert abs(sum(cfg.TENURE_SHARES) - 1.0) < 1e-9
    dates = [c["date"] for c in cfg.CAMPAIGNS]
    assert dates == sorted(dates) and len(set(dates)) == len(dates)


# --- Structure --------------------------------------------------------------------------------

def test_shape_and_columns(df):
    employees = sum(d["headcount"] for d in cfg.DEPARTMENTS.values())
    assert list(df.columns) == COLUMNS
    assert len(df) == employees * len(cfg.CAMPAIGNS)
    assert df["record_id"].is_unique


def test_one_row_per_employee_per_campaign(df):
    assert not df.duplicated(["employee_id", "campaign_id"]).any()
    assert (df.groupby("employee_id").size() == len(cfg.CAMPAIGNS)).all()


def test_employee_attributes_are_stable_across_campaigns(df):
    assert (df.groupby("employee_id")["department"].nunique() == 1).all()
    assert (df.groupby("employee_id")["tenure_band"].nunique() == 1).all()


def test_department_headcounts_match_config(df):
    counts = df.drop_duplicates("employee_id")["department"].value_counts()
    for name, spec in cfg.DEPARTMENTS.items():
        assert counts[name] == spec["headcount"]


def test_categorical_values_are_known(df):
    assert set(df["nudge_type"]) == set(cfg.NUDGES)
    assert set(df["tenure_band"]) == set(cfg.TENURE_BANDS)
    assert set(df["outcome"]) == {"no_action", "clicked_only", "reported_only", "clicked_and_reported"}


# --- Randomisation ----------------------------------------------------------------------------

def test_nudge_arms_are_balanced_within_each_department_and_campaign(df):
    sizes = df.groupby(["campaign_id", "department", "nudge_type"]).size().unstack(fill_value=0)
    assert ((sizes.max(axis=1) - sizes.min(axis=1)) <= 1).all()


def test_prior_exposures_match_history(df):
    ordered = df.sort_values(["employee_id", "nudge_type", "send_date"])
    expected = ordered.groupby(["employee_id", "nudge_type"]).cumcount()
    assert (ordered["prior_exposures_to_nudge"] == expected).all()


# --- Internal consistency ---------------------------------------------------------------------

def test_outcomes_agree_with_flags(df):
    assert set(df["clicked"]) <= {0, 1} and set(df["reported"]) <= {0, 1}
    both, click, rep = (df["clicked"] == 1) & (df["reported"] == 1), df["clicked"] == 1, df["reported"] == 1
    assert (df.loc[both, "outcome"] == "clicked_and_reported").all()
    assert (df.loc[click & ~rep, "outcome"] == "clicked_only").all()
    assert (df.loc[~click & rep, "outcome"] == "reported_only").all()
    assert (df.loc[~click & ~rep, "outcome"] == "no_action").all()


def test_timing_present_only_when_the_event_happened(df):
    assert df["minutes_to_click"].notna().eq(df["clicked"] == 1).all()
    assert df["minutes_to_report"].notna().eq(df["reported"] == 1).all()


def test_timing_is_ordered_and_inside_the_window(df):
    for col in ("minutes_to_click", "minutes_to_report"):
        values = df[col].dropna()
        assert values.between(cfg.MIN_MINUTES, cfg.WINDOW_MINUTES).all()
    both = df[(df["clicked"] == 1) & (df["reported"] == 1)]
    assert (both["minutes_to_report"] >= both["minutes_to_click"]).all()


# --- Effects the generator is meant to have put in --------------------------------------------

def _rate(df, col, **where):
    mask = np.ones(len(df), dtype=bool)
    for key, value in where.items():
        mask &= (df[key] == value).to_numpy()
    return df.loc[mask, col].mean()


def test_clicks_fall_with_the_nudges_that_target_clicking(df):
    control = _rate(df, "clicked", nudge_type="none")
    for nudge in ("warning_banner", "just_in_time_tip", "social_norm"):
        assert _rate(df, "clicked", nudge_type=nudge) < control - 0.03, nudge


def test_easy_report_prompt_lifts_reporting_without_cutting_clicks(df):
    control_report = _rate(df, "reported", nudge_type="none")
    control_click = _rate(df, "clicked", nudge_type="none")
    assert _rate(df, "reported", nudge_type="easy_report_prompt") > control_report + 0.06
    assert abs(_rate(df, "clicked", nudge_type="easy_report_prompt") - control_click) < 0.03


def test_it_and_security_clicks_least_and_reports_most(df):
    clicks = df.groupby("department")["clicked"].mean()
    reports = df.groupby("department")["reported"].mean()
    assert clicks.idxmin() == "IT & Security"
    assert reports.idxmax() == "IT & Security"


def test_a_minority_of_employees_account_for_most_clicks(df):
    per_employee = df.groupby("employee_id")["clicked"].sum().sort_values(ascending=False)
    top_decile = per_employee.head(len(per_employee) // 10).sum() / per_employee.sum()
    assert 0.25 < top_decile < 0.45


# --- Reproducibility and drift ----------------------------------------------------------------

def test_same_seed_gives_identical_data_and_different_seed_does_not(df):
    pd.testing.assert_frame_equal(df, generate())
    assert not df["clicked"].equals(generate(seed=cfg.DEFAULT_SEED + 1)["clicked"])


def test_committed_files_match_the_generator(df, tmp_path):
    out, meta = write(df, cfg.DEFAULT_SEED, tmp_path / DEFAULT_OUT.name)
    assert (ROOT / DEFAULT_OUT).read_bytes() == out.read_bytes(), "run: python -m psim.generate"
    assert (ROOT / DEFAULT_OUT.with_name("assumptions.json")).read_bytes() == meta.read_bytes()


def test_data_dictionary_is_current():
    from psim.docs import DOC_PATH, render

    assert (ROOT / DOC_PATH).read_text(encoding="utf-8") == render(), "run: python -m psim.docs"
