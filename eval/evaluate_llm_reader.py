"""Does the AI reader help? A real-LLM run on the independent held-out notes.

How the outputs were produced (declared):
  * Model: Claude, run as a separate agent that saw ONLY the production system prompt
    (eval/llm_run/system_prompt.txt) and the 120 note texts (eval/llm_run/input_notes.json).
    It saw no labels and no code. Its raw JSON is frozen in eval/llm_run/claude_outputs.json
    and replayed here, so this script is deterministic.
  * It was not called through an API, and all 120 notes were in one context window
    (production sends one note per call). It also received two task instructions (whole-day
    units; leave calendar dates blank) that were then added to SYSTEM_PROMPT. See
    eval/llm_run/README.md. All are declared limitations.

Policies compared (same rule reader, same grounding guard):
  RULES      rule reader only (the outage fallback)
  P1-SECOND  AI as a second reader: agreement confirms, disagreement goes RED (current default)
  P2-PREFILL P1, plus: when the rule reader found NOTHING (only an absence flag) and the AI's
             window is grounded in a verbatim quote, the AI value is pre-filled as AMBER
             (a tick), instead of RED (a person types it)

Outcome per note:
  GREEN        correct and no blocking flag (one-action confirm)
  AMBER-ok     pre-filled correctly, needs a tick
  AMBER-WRONG  pre-filled WRONGLY, needs a tick (the automation-bias risk: a tired tick confirms it)
  RED          a person states type/window
  SILENT       wrong and unflagged

The policy is chosen on the DEV half only; the SEALED half is reported once, after the choice.
On DEV the three policies tied, so the conservative default (pre-fill off) was kept.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dobara.extractor import RuleExtractor  # noqa: E402
from dobara.llm_guard import ground, reconcile  # noqa: E402
from dobara.models import ACK_FLAG, FUType  # noqa: E402
from evaluate_heldout import VISIT, load  # noqa: E402

OUT = json.loads((ROOT / "eval" / "llm_run" / "claude_outputs.json").read_text())
R = RuleExtractor()


def correct(item, d):
    if item["ambiguous"]:
        return False
    g = item["fu_type"]
    return d.fu_type.value == g and (g != "DATED" or d.window() == (item["days_min"], item["days_max"]))


def outcome(item, d):
    ok = correct(item, d)
    if d.hard:
        return "RED"
    if ACK_FLAG in d.flags:
        return "AMBER-ok" if ok else "AMBER-WRONG"
    return "GREEN" if ok else "SILENT"


def pipeline(item, policy):
    rules = R.extract(item["text"], VISIT)
    if policy == "RULES":
        return rules
    llm = ground(json.dumps(OUT[item["id"]]), item["text"])
    if "AI_UNAVAILABLE" in llm.flags:
        return rules
    return reconcile(llm, rules, ai_may_prefill=(policy == "P2-PREFILL"))


def ai_alone(item):
    """The AI's grounded reading on its own (no rule reader), for the accuracy comparison."""
    return ground(json.dumps(OUT[item["id"]]), item["text"])


KEYS = ["GREEN", "AMBER-ok", "AMBER-WRONG", "RED", "SILENT"]


def table(items, title, show=False):
    print(f"\n{title}  (n={len(items)})")
    print(f"  {'policy':<11}" + "".join(f"{k:>13}" for k in KEYS))
    res = {}
    for pol in ("RULES", "P1-SECOND", "P2-PREFILL"):
        c = {k: 0 for k in KEYS}
        for it in items:
            c[outcome(it, pipeline(it, pol))] += 1
        res[pol] = c
        print(f"  {pol:<11}" + "".join(f"{c[k]:>8} ({c[k] / len(items):>3.0%})" for k in KEYS))
    rule_ok = sum(correct(it, R.extract(it["text"], VISIT)) for it in items)
    ai_ok = sum(correct(it, ai_alone(it)) for it in items)
    print(f"  Reading correct before any flag logic: rules {rule_ok}/{len(items)}, AI (grounded) {ai_ok}/{len(items)}")
    if show:
        for it in items:
            a, b = outcome(it, pipeline(it, "RULES")), outcome(it, pipeline(it, "P2-PREFILL"))
            p1 = outcome(it, pipeline(it, "P1-SECOND"))
            if len({a, b, p1}) > 1 or "WRONG" in b or "SILENT" in b:
                d = pipeline(it, "P2-PREFILL")
                print(f"   {it['id']} rules={a:<11} P1={p1:<11} P2={b:<11} gold={it['fu_type']}"
                      f"{(it['days_min'], it['days_max']) if it['fu_type'] == 'DATED' else ''}"
                      f" got={d.fu_type.value}{d.window()} | {it['text'][:70]}")
    return res


def second_reader_test(items, title, show=False):
    """Would the AI, as a second reader, have caught the v1 rule reader's silent errors?
    v1 = the frozen pre-audit rule reader (eval/history/rules_v1). A silent v1 error counts as caught
    when the AI's grounded reading differs in type or window, or the AI raised its own RED flag,
    because the reconciler then sends the note to a person."""
    sys.path.insert(0, str(ROOT / "eval" / "history" / "rules_v1"))
    from followthrough.extractor import RuleExtractor as V1  # noqa: E402
    from evaluate_heldout import classify  # noqa: E402
    v1 = V1()
    silent = caught = 0
    for it in items:
        d1 = v1.extract(it["text"], VISIT)
        if not classify(it, d1).startswith("SILENT"):
            continue
        silent += 1
        ai = ai_alone(it)
        differs = ai.fu_type.value != d1.fu_type.value or ai.window() != (d1.days_min, d1.days_max) or bool(ai.hard)
        caught += differs
        if show:
            print(f"   {it['id']} v1={d1.fu_type.value}{(d1.days_min, d1.days_max)} AI={ai.fu_type.value}{ai.window()}"
                  f" {'CAUGHT' if differs else 'missed'} | {it['text'][:60]}")
    print(f"  {title}: v1 silent errors {silent}; AI second reader would have sent {caught} of them to a person")
    return silent, caught


if __name__ == "__main__":
    items = load()
    dev = [i for i in items if int(i["id"][1:]) <= 60]
    sealed = [i for i in items if int(i["id"][1:]) > 60]
    which = sys.argv[1] if len(sys.argv) > 1 else "dev"
    if which in ("dev", "all"):
        table(dev, "DEV H001-H060 (inspectable; used to choose the policy)", show=True)
        print("\nSecond-reader test against the pre-audit rule reader (v1):")
        second_reader_test(dev, "DEV", show=True)
    if which in ("sealed", "all"):
        table(sealed, "SEALED H061-H120 (aggregates only; reported once after the policy was chosen)")
        print("\nSecond-reader test against the pre-audit rule reader (v1):")
        second_reader_test(sealed, "SEALED")
