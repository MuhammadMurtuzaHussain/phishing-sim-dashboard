"""Rates, intervals and differences from control for the dashboard.

Intervals come from a bootstrap that resamples employees, not emails. The same person appears in up
to six campaigns, so emails are not independent, and resampling whole employees keeps that structure.
Because every employee meets several nudges, the same resample is used for a nudge and the control, so
the interval on a difference accounts for the overlap between them.

All rates are fractions between 0 and 1. A difference is nudge minus control, in the same units.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import config as cfg

BOOTSTRAP_DRAWS = 4000
LOWER, UPPER = 2.5, 97.5  # a 95% percentile interval


# --- Building blocks ---------------------------------------------------------------------------

def employee_tensors(df: pd.DataFrame, by: str, order: list[str]):
    """Per-employee counts of emails, clicks and reports for each category of `by`.

    Returns (employee_ids, n, c, r), where each of n, c and r has one row per employee and one column
    per category in `order`.
    """
    ids = np.sort(df["employee_id"].unique())
    grouped = df.groupby(["employee_id", by])

    def pivot(series: pd.Series) -> np.ndarray:
        return series.unstack(fill_value=0).reindex(index=ids, columns=order, fill_value=0).to_numpy()

    return ids, pivot(grouped.size()), pivot(grouped["clicked"].sum()), pivot(grouped["reported"].sum())


def resample_totals(rng: np.random.Generator, n, c, r, members: np.ndarray, draws: int):
    """Column totals when the employees in `members` are resampled with replacement, `draws` times."""
    m = len(members)
    weights = rng.multinomial(m, np.full(m, 1.0 / m), size=draws)  # how often each employee is drawn
    return weights @ n[members], weights @ c[members], weights @ r[members]


def _estimate(point: float, draws: np.ndarray) -> dict:
    lo, hi = np.nanpercentile(draws, [LOWER, UPPER])
    return {"est": round(float(point), 5), "lo": round(float(lo), 5), "hi": round(float(hi), 5)}


def summarise(rng, n, c, r, members, control: int | None = None, draws: int = BOOTSTRAP_DRAWS) -> list[dict]:
    """Rate, interval and (optionally) difference from the control column, for every category."""
    totals_n, totals_c, totals_r = n[members].sum(0), c[members].sum(0), r[members].sum(0)
    boot_n, boot_c, boot_r = resample_totals(rng, n, c, r, members, draws)
    with np.errstate(divide="ignore", invalid="ignore"):
        click, report = totals_c / totals_n, totals_r / totals_n
        click_b, report_b = boot_c / boot_n, boot_r / boot_n

    rows = []
    for k in range(n.shape[1]):
        row = {
            "n": int(totals_n[k]),
            "click": _estimate(click[k], click_b[:, k]),
            "report": _estimate(report[k], report_b[:, k]),
        }
        if control is not None and k != control:
            row["d_click"] = _estimate(click[k] - click[control], click_b[:, k] - click_b[:, control])
            row["d_report"] = _estimate(report[k] - report[control], report_b[:, k] - report_b[:, control])
        rows.append(row)
    return rows


def excludes_zero(estimate: dict) -> bool:
    return estimate["lo"] > 0 or estimate["hi"] < 0


# --- The analysis the dashboard shows ----------------------------------------------------------

def analyse(df: pd.DataFrame, seed: int = cfg.DEFAULT_SEED, draws: int = BOOTSTRAP_DRAWS) -> dict:
    rng = np.random.default_rng([seed, 2026])
    nudge_keys = list(cfg.NUDGES)
    dept_names = list(cfg.DEPARTMENTS)
    campaign_ids = [c["id"] for c in cfg.CAMPAIGNS]

    ids, n, c, r = employee_tensors(df, "nudge_type", nudge_keys)
    everyone = np.arange(len(ids))
    dept_of = df.drop_duplicates("employee_id").set_index("employee_id").loc[ids, "department"].to_numpy()

    # Nudge types, all employees pooled.
    by_nudge = summarise(rng, n, c, r, everyone, control=0, draws=draws)
    timing = df.groupby("nudge_type")["minutes_to_report"].agg(["median", "count"])
    nudges = []
    for k, key in enumerate(nudge_keys):
        spec = cfg.NUDGES[key]
        nudges.append({
            "key": key, "label": spec["label"], "mechanism": spec["mechanism"],
            **by_nudge[k],
            "median_minutes_to_report": round(float(timing.loc[key, "median"]), 1),
        })

    # Departments, all nudges pooled.
    all_n, all_c, all_r = n.sum(1, keepdims=True), c.sum(1, keepdims=True), r.sum(1, keepdims=True)
    dept_timing = df.groupby("department")["minutes_to_report"].median()
    departments = []
    for name in dept_names:
        members = np.flatnonzero(dept_of == name)
        stats = summarise(rng, all_n, all_c, all_r, members, draws=draws)[0]
        departments.append({
            "name": name, "employees": int(len(members)), **stats,
            "median_minutes_to_report": round(float(dept_timing[name]), 1),
        })

    # Each nudge within each department, against that department's own control.
    cells = []
    for name in dept_names:
        members = np.flatnonzero(dept_of == name)
        stats = summarise(rng, n, c, r, members, control=0, draws=draws)
        for k, key in enumerate(nudge_keys):
            if k == 0:
                continue
            cells.append({"department": name, "nudge": key, "control_n": stats[0]["n"],
                          "control_click": stats[0]["click"]["est"], "control_report": stats[0]["report"]["est"],
                          **stats[k]})

    # How many departments point the same way as the pooled result (a cheap replication check).
    for nudge in nudges:
        if nudge["key"] == "none":
            continue
        own = [x for x in cells if x["nudge"] == nudge["key"]]
        nudge["departments_fewer_clicks"] = sum(x["d_click"]["est"] < 0 for x in own)
        nudge["departments_more_reports"] = sum(x["d_report"]["est"] > 0 for x in own)
        nudge["departments_total"] = len(own)

    # Campaigns, all employees and nudges pooled.
    _, cn, cc, cr = employee_tensors(df, "campaign_id", campaign_ids)
    by_campaign = summarise(rng, cn, cc, cr, everyone, draws=draws)
    campaigns = [
        {"id": camp["id"], "date": camp["date"], "lure": camp["lure"], **by_campaign[i]}
        for i, camp in enumerate(cfg.CAMPAIGNS)
    ]

    # Organisation-wide reference lines.
    overall = summarise(rng, all_n, all_c, all_r, everyone, draws=draws)[0]

    # Individuals.
    per_employee = df.groupby("employee_id")[["clicked", "reported"]].sum()
    clicks_sorted = per_employee["clicked"].sort_values(ascending=False)
    top_decile = clicks_sorted.head(len(clicks_sorted) // 10).sum() / clicks_sorted.sum()
    individuals = {
        "employees": int(len(per_employee)),
        "never_clicked_share": round(float((per_employee["clicked"] == 0).mean()), 4),
        "never_reported_share": round(float((per_employee["reported"] == 0).mean()), 4),
        "top_decile_click_share": round(float(top_decile), 4),
    }

    return {
        "meta": {
            "rows": int(len(df)), "employees": int(len(ids)), "campaigns": len(campaign_ids),
            "seed": seed, "bootstrap_draws": draws, "interval": "95%",
            "first_send": cfg.CAMPAIGNS[0]["date"], "last_send": cfg.CAMPAIGNS[-1]["date"],
        },
        "overall": overall,
        "nudges": nudges,
        "departments": departments,
        "cells": cells,
        "campaigns": campaigns,
        "individuals": individuals,
    }
