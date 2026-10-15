"""Scores the reader on the independently written held-out set (eval/heldout_notes.json).

Protocol (declared in the Decision Trail):
  * H001-H060 = DEV half: item-level failures may be inspected.
  * H061-H120 = SEALED half: only aggregate numbers are printed, and it is scored once
    before fixes and once after all fixes, never used for tuning.

Outcome classes per note:
  auto      read correctly, no blocking flag
  flagged   a blocking flag sent it to a person (safe; costs seconds)
  SILENT    wrong and unflagged. Split by harm:
              DROP         gold says the patient must return; output says SOS/NONE/UNCLEAR
              MISSCHEDULE  dated, but wrong window
              OVERTRACK    gold SOS/NONE/UNCLEAR; output tracks a dated window (over-contact)
              TYPE         any other type error
Ambiguous gold items are correct only if flagged.
"""
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

VISIT = date(2026, 11, 2)


def load(path=None):
    p = Path(path) if path else ROOT / "eval" / "heldout_notes.json"
    return json.loads(p.read_text())


def classify(item, d):
    gtype = item["fu_type"]
    blocked = bool(d.blocking)
    if item["ambiguous"]:
        return "flagged" if blocked else "SILENT:" + _harm(item, d)
    correct = d.fu_type.value == gtype and (
        gtype != "DATED" or (d.days_min, d.days_max) == (item["days_min"], item["days_max"]))
    if blocked:
        return "flagged"
    return "auto" if correct else "SILENT:" + _harm(item, d)


def _harm(item, d):
    g, o = item["fu_type"], d.fu_type.value
    if g in ("DATED", "CONDITIONAL") and o in ("SOS", "NONE", "UNCLEAR"):
        return "DROP"
    if g == "DATED" and o == "DATED":
        return "MISSCHEDULE"
    if g in ("SOS", "NONE", "UNCLEAR") and o == "DATED":
        return "OVERTRACK"
    return "TYPE"


def run(extractor, label, show_dev=False, items=None):
    items = items or load()
    halves = {"DEV H001-H060": [i for i in items if int(i["id"][1:]) <= 60],
              "SEALED H061-H120": [i for i in items if int(i["id"][1:]) > 60]}
    out = {}
    for name, subset in halves.items():
        counts, esc_fp, esc_fn, fails = {}, 0, 0, []
        for it in subset:
            d = extractor.extract(it["text"], VISIT)
            c = classify(it, d)
            counts[c] = counts.get(c, 0) + 1
            e1 = d.escalation_suggestion is not None
            esc_fp += int(e1 and not it["escalation_explicit"])
            esc_fn += int((not e1) and it["escalation_explicit"])
            if c.startswith("SILENT"):
                fails.append((it["id"], c, it["text"][:90], it["fu_type"], (it["days_min"], it["days_max"]),
                              d.fu_type.value, d.window(), d.flags))
        n = len(subset)
        silent = sum(v for k, v in counts.items() if k.startswith("SILENT"))
        print(f"\n[{label}] {name}  n={n}")
        print(f"  auto-correct {counts.get('auto',0)} ({counts.get('auto',0)/n:.0%}) | "
              f"flagged {counts.get('flagged',0)} ({counts.get('flagged',0)/n:.0%}) | "
              f"SILENT {silent} ({silent/n:.1%})")
        for k in sorted(k for k in counts if k.startswith("SILENT")):
            print(f"     {k}: {counts[k]}")
        print(f"  E1 pre-filled without explicit phrase: {esc_fp} | explicit phrase missed: {esc_fn}")
        if show_dev and name.startswith("DEV"):
            for f in fails:
                print("   ", f)
        out[name] = dict(n=n, counts=counts, silent=silent, esc_fp=esc_fp, esc_fn=esc_fn)
    return out


if __name__ == "__main__":
    from dobara.extractor import RuleExtractor  # noqa: E402
    run(RuleExtractor(), "rules-v2.1, current code (SEALED half contaminated by the post-hoc fix: not counted)", show_dev=True)
