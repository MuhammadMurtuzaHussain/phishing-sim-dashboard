"""Print click and report rates by nudge type and by department.

    python -m psim.summary [path/to/phishing_sim_events.csv]
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

from . import config as cfg
from .generate import DEFAULT_OUT


def rate_table(df: pd.DataFrame, by: str, order: list[str]) -> pd.DataFrame:
    g = df.groupby(by)
    out = pd.DataFrame(
        {
            "n": g.size(),
            "click_%": g["clicked"].mean() * 100,
            "report_%": g["reported"].mean() * 100,
            "median_min_to_report": g["minutes_to_report"].median(),
        }
    )
    return out.reindex(order)


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    path = Path(argv[0]) if argv else DEFAULT_OUT
    df = pd.read_csv(path)

    fmt = {"n": "{:,.0f}".format, "click_%": "{:.1f}".format, "report_%": "{:.1f}".format,
           "median_min_to_report": "{:.0f}".format}
    print(f"{len(df):,} simulation emails, overall click {df['clicked'].mean():.1%}, "
          f"report {df['reported'].mean():.1%}\n")
    print("By nudge type")
    print(rate_table(df, "nudge_type", list(cfg.NUDGES)).to_string(formatters=fmt))
    print("\nBy department")
    print(rate_table(df, "department", list(cfg.DEPARTMENTS)).to_string(formatters=fmt))
    print("\nBy campaign")
    print(rate_table(df, "campaign_id", [c["id"] for c in cfg.CAMPAIGNS]).to_string(formatters=fmt))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
