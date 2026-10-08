"""Generate the synthetic phishing simulation dataset.

    python -m psim.generate                       # data/phishing_sim_events.csv + data/assumptions.json
    python -m psim.generate --seed 7 --out /tmp/events.csv

One row per employee per campaign. Nudges are randomly assigned within each department every
campaign (block randomisation), so arms are balanced and a comparison between nudge types is fair
by design. Everything else the data "knows" lives in psim/config.py.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from . import config as cfg

COLUMNS = [
    "record_id", "campaign_id", "send_date", "lure_theme",
    "employee_id", "department", "tenure_band",
    "nudge_type", "prior_exposures_to_nudge",
    "clicked", "reported", "outcome",
    "minutes_to_click", "minutes_to_report",
]

DEFAULT_OUT = Path("data/phishing_sim_events.csv")


def _logit(p):
    p = np.asarray(p, dtype=float)
    return np.log(p / (1.0 - p))


def _expit(x):
    return 1.0 / (1.0 + np.exp(-x))


def _lognormal(rng: np.random.Generator, median: float, sigma: float, size: int) -> np.ndarray:
    return np.exp(rng.normal(np.log(median), sigma, size))


def build_roster(rng: np.random.Generator) -> pd.DataFrame:
    """Employees with a department, tenure band and two persistent latent propensities."""
    dept_names = list(cfg.DEPARTMENTS)
    depts = np.repeat(dept_names, [cfg.DEPARTMENTS[d]["headcount"] for d in dept_names])
    n = len(depts)
    depts = depts[rng.permutation(n)]  # employee IDs are not ordered by department
    tenure = rng.choice(cfg.TENURE_BANDS, size=n, p=cfg.TENURE_SHARES)

    # Correlated propensities: employees who click readily tend to report less.
    z1, z2 = rng.standard_normal(n), rng.standard_normal(n)
    rho = cfg.PROPENSITY_CORRELATION
    click_prop = cfg.CLICK_PROPENSITY_SD * z1
    report_prop = cfg.REPORT_PROPENSITY_SD * (rho * z1 + np.sqrt(1.0 - rho**2) * z2)

    return pd.DataFrame(
        {
            "employee_id": [f"E{i:04d}" for i in range(1, n + 1)],
            "department": depts,
            "tenure_band": tenure,
            "click_propensity": click_prop,
            "report_propensity": report_prop,
        }
    )


def assign_nudges(rng: np.random.Generator, dept_idx: np.ndarray, n_nudges: int) -> np.ndarray:
    """Block randomisation: within each department, deal nudges out in rotation from a shuffled list."""
    out = np.empty(len(dept_idx), dtype=int)
    for d in np.unique(dept_idx):
        members = rng.permutation(np.flatnonzero(dept_idx == d))
        offset = int(rng.integers(n_nudges))
        out[members] = (np.arange(len(members)) + offset) % n_nudges
    return out


def _modifier_matrix(nudge_keys: list[str], dept_names: list[str]) -> np.ndarray:
    m = np.ones((len(nudge_keys), len(dept_names)))
    for nudge, per_dept in cfg.DEPARTMENT_NUDGE_MODIFIER.items():
        for dept, mult in per_dept.items():
            m[nudge_keys.index(nudge), dept_names.index(dept)] = mult
    return m


def generate(seed: int = cfg.DEFAULT_SEED) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    roster = build_roster(rng)
    n = len(roster)

    dept_names = list(cfg.DEPARTMENTS)
    nudge_keys = list(cfg.NUDGES)
    dept_arr = roster["department"].to_numpy()
    dept_idx = pd.Series(dept_arr).map({d: i for i, d in enumerate(dept_names)}).to_numpy()

    base_click = _logit([cfg.DEPARTMENTS[d]["click"] for d in dept_names])[dept_idx]
    base_report = _logit([cfg.DEPARTMENTS[d]["report"] for d in dept_names])[dept_idx]
    tenure_click = roster["tenure_band"].map(cfg.TENURE_CLICK_SHIFT).to_numpy()
    tenure_report = roster["tenure_band"].map(cfg.TENURE_REPORT_SHIFT).to_numpy()

    click_log_or = np.log([cfg.NUDGES[k]["click_or"] for k in nudge_keys])
    report_log_or = np.log([cfg.NUDGES[k]["report_or"] for k in nudge_keys])
    decay = np.array([cfg.NUDGES[k]["decay"] for k in nudge_keys])
    nudge_speed = np.array([cfg.NUDGES[k]["report_speed"] for k in nudge_keys])
    modifier = _modifier_matrix(nudge_keys, dept_names)
    dept_speed = np.array([cfg.DEPARTMENT_REPORT_SPEED.get(d, 1.0) for d in dept_names])[dept_idx]

    exposures = np.zeros((n, len(nudge_keys)), dtype=int)
    everyone = np.arange(n)
    frames = []

    for c_idx, camp in enumerate(cfg.CAMPAIGNS):
        nudge_idx = assign_nudges(rng, dept_idx, len(nudge_keys))
        prior = exposures[everyone, nudge_idx]

        # Share of a nudge's effect left for this person: habituation by exposure, scaled by department.
        scale = decay[nudge_idx] ** prior * modifier[nudge_idx, dept_idx]
        affinity = np.isin(dept_arr, camp["affinity"]) * cfg.AFFINITY_CLICK_SHIFT

        click_logit = (
            base_click + roster["click_propensity"].to_numpy() + tenure_click
            + camp["difficulty"] + affinity
            + cfg.CLICK_TREND_PER_CAMPAIGN * c_idx
            + click_log_or[nudge_idx] * scale
        )
        clicked = rng.random(n) < _expit(click_logit)

        report_logit = (
            base_report + roster["report_propensity"].to_numpy() + tenure_report
            + cfg.REPORT_TREND_PER_CAMPAIGN * c_idx
            + report_log_or[nudge_idx] * scale
            + cfg.REPORT_AFTER_CLICK_SHIFT * clicked
        )
        reported = rng.random(n) < _expit(report_logit)

        # Timing. Every draw is made for every row, then masked, so the random stream is stable.
        t_click = _lognormal(rng, cfg.CLICK_MEDIAN_MIN, cfg.CLICK_SIGMA, n)
        t_after_click = _lognormal(rng, cfg.REPORT_AFTER_CLICK_MEDIAN_MIN, cfg.REPORT_AFTER_CLICK_SIGMA, n)
        t_direct = (
            _lognormal(rng, cfg.REPORT_MEDIAN_MIN, cfg.REPORT_SIGMA, n)
            * nudge_speed[nudge_idx] * dept_speed
        )
        t_report = np.where(clicked, t_click + t_after_click, t_direct)
        t_click = np.round(np.clip(t_click, cfg.MIN_MINUTES, cfg.WINDOW_MINUTES), 1)
        t_report = np.round(np.clip(t_report, cfg.MIN_MINUTES, cfg.WINDOW_MINUTES), 1)

        outcome = np.select(
            [clicked & reported, clicked, reported],
            ["clicked_and_reported", "clicked_only", "reported_only"],
            default="no_action",
        )

        frames.append(
            pd.DataFrame(
                {
                    "campaign_id": camp["id"],
                    "send_date": camp["date"],
                    "lure_theme": camp["lure"],
                    "employee_id": roster["employee_id"].to_numpy(),
                    "department": dept_arr,
                    "tenure_band": roster["tenure_band"].to_numpy(),
                    "nudge_type": np.array(nudge_keys)[nudge_idx],
                    "prior_exposures_to_nudge": prior,
                    "clicked": clicked.astype(int),
                    "reported": reported.astype(int),
                    "outcome": outcome,
                    "minutes_to_click": np.where(clicked, t_click, np.nan),
                    "minutes_to_report": np.where(reported, t_report, np.nan),
                }
            )
        )
        exposures[everyone, nudge_idx] += 1

    df = pd.concat(frames, ignore_index=True)
    df.insert(0, "record_id", np.arange(1, len(df) + 1))
    return df[COLUMNS]


def assumptions(seed: int, df: pd.DataFrame) -> dict:
    """The parameters behind the data, written next to it so the generator's 'truth' is auditable."""
    return {
        "generator_version": cfg.GENERATOR_VERSION,
        "seed": seed,
        "rows": int(len(df)),
        "employees": int(df["employee_id"].nunique()),
        "campaigns": cfg.CAMPAIGNS,
        "departments": cfg.DEPARTMENTS,
        "nudges": cfg.NUDGES,
        "department_nudge_modifier": cfg.DEPARTMENT_NUDGE_MODIFIER,
        "tenure": {
            "shares": dict(zip(cfg.TENURE_BANDS, cfg.TENURE_SHARES, strict=True)),
            "click_logit_shift": cfg.TENURE_CLICK_SHIFT,
            "report_logit_shift": cfg.TENURE_REPORT_SHIFT,
        },
        "affinity_click_logit_shift": cfg.AFFINITY_CLICK_SHIFT,
        "trend_per_campaign_logit": {
            "click": cfg.CLICK_TREND_PER_CAMPAIGN,
            "report": cfg.REPORT_TREND_PER_CAMPAIGN,
        },
        "individual_differences": {
            "click_propensity_sd": cfg.CLICK_PROPENSITY_SD,
            "report_propensity_sd": cfg.REPORT_PROPENSITY_SD,
            "correlation": cfg.PROPENSITY_CORRELATION,
        },
        "report_after_click_logit_shift": cfg.REPORT_AFTER_CLICK_SHIFT,
        "timing_minutes": {
            "click_median": cfg.CLICK_MEDIAN_MIN,
            "report_median": cfg.REPORT_MEDIAN_MIN,
            "report_after_click_median": cfg.REPORT_AFTER_CLICK_MEDIAN_MIN,
            "window": cfg.WINDOW_MINUTES,
        },
    }


def write(df: pd.DataFrame, seed: int, out: Path) -> tuple[Path, Path]:
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out, index=False, float_format="%.1f")
    meta = out.with_name("assumptions.json")
    meta.write_text(json.dumps(assumptions(seed, df), indent=2) + "\n", encoding="utf-8")
    return out, meta


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--seed", type=int, default=cfg.DEFAULT_SEED, help="random seed (default: %(default)s)")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="CSV path (default: %(default)s)")
    args = parser.parse_args(argv)

    df = generate(args.seed)
    csv_path, meta_path = write(df, args.seed, args.out)
    print(f"{len(df):,} rows ({df['employee_id'].nunique():,} employees x {df['campaign_id'].nunique()} campaigns)")
    print(f"  {csv_path}\n  {meta_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
