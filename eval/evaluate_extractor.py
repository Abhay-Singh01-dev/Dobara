"""Measures the rule-based baseline on synthetic data.

Metrics (defined in the SRS):
  auto_correct   : read correctly with no blocking flag (no human edit needed beyond escalation)
  flagged        : a blocking flag sent it to the clinician (safe, costs seconds)
  silent_error   : WRONG and NOT flagged — the dangerous case; target 0
  esc_false_pre  : E1 suggested where the clinician wrote no escalation phrase — target 0
"""
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dobara.extractor import RuleExtractor  # noqa: E402
from datasets import ADVERSARIAL, templated  # noqa: E402

VISIT = date(2026, 11, 2)


def score(cases, label, show_failures=False):
    ex = RuleExtractor()
    n = len(cases); auto = flag = silent = esc_fp = esc_fn = 0
    fails = []
    for text, gold in cases:
        d = ex.extract(text, VISIT)
        gtype = gold[0]
        if gtype == "ABS":
            gtype, gmin = "DATED", (date(2026, gold[2], gold[1]) - VISIT).days
            gmax = gmin
        else:
            gmin, gmax = gold[1], gold[2]
        esc_gold = gold[3]
        if gtype == "CONFLICT":
            correct = False  # any reading is wrong; only a flag is acceptable
        else:
            correct = d.fu_type.value == gtype and (gtype != "DATED" or (d.days_min, d.days_max) == (gmin, gmax))
        blocked = bool(d.blocking)
        if correct and not blocked:
            auto += 1
        elif blocked:
            flag += 1
        else:
            silent += 1
            fails.append((text, gold, d.fu_type.value, d.window(), d.flags))
        got_e1 = d.escalation_suggestion is not None
        esc_fp += int(got_e1 and esc_gold is None)
        esc_fn += int((not got_e1) and esc_gold == "E1")
    print(f"\n[{label}] n={n}")
    print(f"  auto-correct (no human fix needed): {auto} ({auto/n:.0%})")
    print(f"  flagged to clinician (safe):        {flag} ({flag/n:.0%})")
    print(f"  SILENT ERRORS (wrong, unflagged):   {silent} ({silent/n:.1%})")
    print(f"  E1 pre-filled without explicit phrase: {esc_fp}   explicit phrase missed: {esc_fn}")
    if show_failures:
        for f in fails:
            print("   SILENT:", f)
    return dict(n=n, auto=auto, flag=flag, silent=silent, esc_fp=esc_fp, esc_fn=esc_fn)


if __name__ == "__main__":
    score(templated(), "templated synthetic set")
    score(ADVERSARIAL, "hand-written adversarial set", show_failures=True)
