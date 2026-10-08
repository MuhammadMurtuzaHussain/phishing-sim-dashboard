# phishing-sim-dashboard

Click and report rates from phishing simulations, by nudge type and department, using synthetic data, with a short behavioural reading of the results.

**Status:** step 1 of 3, the dataset. The dashboard and the behavioural reading follow.

A phishing simulation asks two different questions. The click rate says how exposed individuals are. The report rate says whether the organisation is acting as a sensor. A nudge can move one without the other, so this project reads the two together, by nudge type and by department.

## Start here

The loop is: generate the data, look at the rates, run the checks.

```bash
git clone https://github.com/MuhammadMurtuzaHussain/phishing-sim-dashboard.git
cd phishing-sim-dashboard
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt

python -m psim.generate    # writes data/phishing_sim_events.csv and data/assumptions.json
python -m psim.summary     # click and report rates by nudge, department and campaign
python -m pytest -q        # structure, randomisation, consistency, effects, drift
```

```
7,200 simulation emails, overall click 21.0%, report 18.7%

By nudge type
                       n click_% report_% median_min_to_report
none               1,196    24.3     14.7                   16
warning_banner     1,198    18.8     16.4                   18
social_norm        1,204    19.7     20.8                   16
loss_framing       1,202    21.0     16.1                   16
just_in_time_tip   1,201    17.5     19.0                   18
easy_report_prompt 1,199    24.7     25.2                   10
```

## The data

One row per employee per monthly campaign: 1,200 employees in ten departments, six campaigns from April to September 2026, 7,200 rows. Each email carries one of six nudge types (no nudge as the control, warning banner, social norm, loss framing, just-in-time tip, easy-report prompt), and the outcome is whether the employee clicked, reported, both or neither, with the time taken.

Three design choices:

- **Randomised and balanced.** Within each department, every campaign deals the nudges out evenly to a shuffled list of employees, so a comparison between nudge types is fair by design.
- **Click and report are modelled separately.** The warning banner is built to cut clicks more than it lifts reports, and the easy-report prompt the other way round. Whether the dashboard makes that visible is part of the test.
- **Every assumption is written down.** Baselines, effect sizes and department differences live in [`psim/config.py`](psim/config.py) and are exported to `data/assumptions.json`. Column definitions and how to compute the rates are in the [data dictionary](docs/data-dictionary.md).

## Limits to keep in mind

- **The data is synthetic.** Effect sizes are assumptions with plausible direction, not findings. A dashboard can only recover what the generator put in, so nothing here shows that any nudge works in practice.
- **Small cells.** A department-by-nudge cell holds about 35 to 220 rows. In the generated data the Finance banner cell shows more clicks than the Finance control, although the generator gives the banner lower click odds. That is sampling noise, and the reason the dashboard will show row counts and intervals.
- **Habituation is built in but faint.** Each person sees a given nudge about once across six campaigns, so the fade-out of repeated nudges is too small to see at this sample size.

## If you point this at real data

Employee-level click and report data is personal data under GDPR, and simulation results can feel punitive. Agree the purpose, retention and who sees what with HR and data protection before using it, report at department level only above a minimum group size (ten, for example), and keep individual results out of disciplinary processes. A programme like this supports, but does not satisfy, the awareness and training expectations in ISO/IEC 27001:2022 Annex A 6.3 and NIS2 Article 21(2)(g).

## Layout

```
psim/config.py        every assumption behind the data
psim/generate.py      seeded generator and CSV writer
psim/summary.py       rates by nudge, department and campaign
psim/docs.py          renders the data dictionary from the code
data/                 phishing_sim_events.csv and assumptions.json (seed 2026)
docs/                 data-dictionary.md (generated)
tests/                structure, balance, effects, reproducibility and drift checks
```

## Roadmap

1. Dataset: done.
2. Dashboard: click and report rates by nudge type and department, with row counts and intervals.
3. Behavioural reading: what the pattern suggests, what it cannot show, and the next experiment worth running.
# phishing-sim-dashboard
