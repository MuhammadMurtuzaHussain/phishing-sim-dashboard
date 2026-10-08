"""Assumptions behind the synthetic phishing simulation data.

Everything the dataset "knows" is defined in this file. A dashboard built on the data can only
recover what is put in here, so the values are explicit, named and exported next to the data
(data/assumptions.json). They are plausible rather than measured: the direction of each effect
follows common behavioural-science reasoning, the sizes are illustrative.

Conventions
- Probabilities are per delivered simulation email.
- Nudge effects are odds ratios (OR) applied on the logit scale. OR < 1 lowers the odds of the
  outcome, OR > 1 raises them.
- Departments can scale a nudge's effect (a multiplier on the log-OR), which is what makes the
  nudge-by-department view worth drawing.
"""

GENERATOR_VERSION = "1.0.0"
DEFAULT_SEED = 2026

# --- Organisation -----------------------------------------------------------------------------
# A fictional mid-sized organisation. Baselines are the control-arm rates for an average employee
# in the first campaign, before lure, tenure and learning effects.
DEPARTMENTS = {
    #                         headcount  click  report
    "Finance":                {"headcount": 110, "click": 0.22, "report": 0.10},
    "HR":                     {"headcount": 70,  "click": 0.26, "report": 0.08},
    "IT & Security":          {"headcount": 100, "click": 0.07, "report": 0.38},
    "Engineering":            {"headcount": 220, "click": 0.12, "report": 0.16},
    "Sales":                  {"headcount": 190, "click": 0.28, "report": 0.05},
    "Marketing":              {"headcount": 90,  "click": 0.24, "report": 0.07},
    "Operations":             {"headcount": 200, "click": 0.20, "report": 0.08},
    "Customer Support":       {"headcount": 140, "click": 0.27, "report": 0.06},
    "Legal & Compliance":     {"headcount": 45,  "click": 0.11, "report": 0.20},
    "Executive Office":       {"headcount": 35,  "click": 0.21, "report": 0.04},
}

TENURE_BANDS = ["under_1y", "1_to_3y", "over_3y"]
TENURE_SHARES = [0.22, 0.38, 0.40]
# Logit shifts. New starters are less familiar with what a genuine request looks like and with how
# to report, long-serving staff slightly more so.
TENURE_CLICK_SHIFT = {"under_1y": 0.35, "1_to_3y": 0.0, "over_3y": -0.10}
TENURE_REPORT_SHIFT = {"under_1y": -0.25, "1_to_3y": 0.0, "over_3y": 0.10}

# --- Nudges -----------------------------------------------------------------------------------
# click_or / report_or: odds ratio versus no nudge, on a first exposure.
# decay: share of the effect that survives each earlier exposure to the same nudge for that
#        employee (effect = log_or * decay ** prior_exposures). 1.0 would mean no habituation.
# report_speed: multiplier on the typical time to report (below 1 means faster).
NUDGES = {
    "none": {
        "label": "No nudge (control)",
        "mechanism": "Baseline",
        "click_or": 1.00, "report_or": 1.00, "decay": 1.00, "report_speed": 1.0,
    },
    "warning_banner": {
        "label": "Warning banner",
        "mechanism": "Salience and friction: an 'external sender, be careful' banner at the top",
        "click_or": 0.62, "report_or": 1.15, "decay": 0.70, "report_speed": 1.0,
    },
    "social_norm": {
        "label": "Social norm",
        "mechanism": "Descriptive norm: 'most of your colleagues report emails like this'",
        "click_or": 0.80, "report_or": 1.45, "decay": 0.90, "report_speed": 0.9,
    },
    "loss_framing": {
        "label": "Loss framing",
        "mechanism": "Loss aversion: what the organisation and its clients lose if this is real",
        "click_or": 0.78, "report_or": 1.20, "decay": 0.80, "report_speed": 1.0,
    },
    "just_in_time_tip": {
        "label": "Just-in-time tip",
        "mechanism": "Implementation intention: 'check the sender and hover over the link first'",
        "click_or": 0.60, "report_or": 1.50, "decay": 0.85, "report_speed": 1.0,
    },
    "easy_report_prompt": {
        "label": "Easy-report prompt",
        "mechanism": "Effort reduction: 'Not sure? Report it in one click'",
        "click_or": 0.95, "report_or": 2.20, "decay": 0.95, "report_speed": 0.5,
    },
}

# Department-specific scaling of each nudge's log-OR (default 1.0). Reasoning in brief:
# banners are ignored fastest by high-volume inboxes, descriptive norms land in social, target-driven
# teams, loss framing resonates where consequences are concrete (money, accountability), tips help
# most where staff are least trained, and the report prompt adds least where reporting is already habit.
DEPARTMENT_NUDGE_MODIFIER = {
    "warning_banner": {"Customer Support": 0.5, "Sales": 0.6, "Operations": 0.8},
    "social_norm": {"Sales": 1.5, "Marketing": 1.4, "Customer Support": 1.2, "Legal & Compliance": 0.7},
    "loss_framing": {"Finance": 1.5, "Executive Office": 1.4, "HR": 1.2, "Engineering": 0.6},
    "just_in_time_tip": {"HR": 1.3, "Finance": 1.2, "Customer Support": 1.2, "Engineering": 0.7},
    "easy_report_prompt": {"IT & Security": 0.5, "Sales": 1.3, "Customer Support": 1.3},
}

# --- Campaigns --------------------------------------------------------------------------------
# One simulation a month. difficulty is a logit shift on clicking (harder lure, more clicks).
# Employees whose department matches a lure's affinity click more on it (a payroll lure to Finance).
AFFINITY_CLICK_SHIFT = 0.45
CAMPAIGNS = [
    {"id": "C1", "date": "2026-04-14", "lure": "Overdue invoice", "difficulty": 0.15,
     "affinity": ["Finance"]},
    {"id": "C2", "date": "2026-05-12", "lure": "Parcel delivery failed", "difficulty": 0.25,
     "affinity": ["Operations", "Customer Support"]},
    {"id": "C3", "date": "2026-06-09", "lure": "Shared document request", "difficulty": 0.30,
     "affinity": ["Sales", "Marketing"]},
    {"id": "C4", "date": "2026-07-14", "lure": "HR policy update", "difficulty": 0.10,
     "affinity": ["HR", "Executive Office"]},
    {"id": "C5", "date": "2026-08-11", "lure": "MFA reset required", "difficulty": 0.00,
     "affinity": ["Engineering"]},
    {"id": "C6", "date": "2026-09-08", "lure": "Payroll bonus notice", "difficulty": 0.35,
     "affinity": ["Finance", "HR"]},
]

# Programme-wide learning, per campaign (logit). Awareness slowly grows, reporting becomes habit.
CLICK_TREND_PER_CAMPAIGN = -0.08
REPORT_TREND_PER_CAMPAIGN = 0.10

# --- Individual differences -------------------------------------------------------------------
# Each employee has a persistent click propensity and report propensity (logit scale, mean zero).
# People who click readily tend to report less, hence the negative correlation. This creates the
# familiar pattern of a small group accounting for a large share of clicks.
CLICK_PROPENSITY_SD = 0.80
REPORT_PROPENSITY_SD = 0.70
PROPENSITY_CORRELATION = -0.35

# Someone who clicked is less likely to go on to report (they may not realise, or may not want to say).
REPORT_AFTER_CLICK_SHIFT = -0.70

# --- Timing -----------------------------------------------------------------------------------
# Log-normal delays in minutes, capped at the five-day campaign window.
CLICK_MEDIAN_MIN = 6.0
CLICK_SIGMA = 1.3
REPORT_MEDIAN_MIN = 22.0           # report without clicking
REPORT_SIGMA = 1.2
REPORT_AFTER_CLICK_MEDIAN_MIN = 8.0  # extra delay from click to report
REPORT_AFTER_CLICK_SIGMA = 1.0
DEPARTMENT_REPORT_SPEED = {"IT & Security": 0.5, "Legal & Compliance": 0.8}
WINDOW_MINUTES = 5 * 24 * 60
MIN_MINUTES = 0.2
