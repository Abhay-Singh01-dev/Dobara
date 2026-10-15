"""Does ordering by the clinician's 'if missed' level get E1 patients called sooner than
calling in the order patients became overdue (first-come)? A queue MODEL, not real data.
It models the same demand every day (about 42 calls' worth) for 120 calendar days (no weekends),
so any capacity below that is sustained overload. Results depend on run length; E2 calls
deferred by E1-first ordering accumulate. 'Within 2 days' counts from the day an E1 patient
joins the list (the day after the window ends).

CASE inputs (simulated competition data): 900 visits/day, 28% of follow-ups missed.
ASSUMPTIONS (varied, not asserted): 30% of visits marked for follow-up; E1/E2/E3 mix
20/40/40; window mix 7/14/30/90 days at 30/30/30/10%; 93% of patients have some phone
(case: 7% unreachable); E1 called from the day after the window ends, E2 from 7 days
after window + grace; E3 gets SMS only; each call attempt reaches one patient.
"""
import random
from collections import deque

GRACE = lambda w: 3 if w <= 7 else 7 if w <= 30 else 14

def simulate(capacity, policy, days=120, seed=5):
    rnd = random.Random(seed)
    eligible = []           # (eligible_day, level, id)
    waits = {"E1": [], "E2": []}
    pending = []
    uid = 0
    for day in range(days):
        for _ in range(int(900 * 0.30)):
            uid += 1
            if rnd.random() > 0.28 or rnd.random() > 0.93:
                continue                       # returned on time, or no phone at all (CHW/next-contact route)
            w = rnd.choices([7, 14, 30, 90], [30, 30, 30, 10])[0]
            lvl = rnd.choices(["E1", "E2", "E3"], [20, 40, 40])[0]
            if lvl == "E3":
                continue
            start = day + w + 1 if lvl == "E1" else day + w + GRACE(w) + 7
            pending.append((start, lvl, uid))
        queue = [p for p in pending if p[0] <= day]
        if policy == "first-come":
            queue.sort(key=lambda p: (p[0], p[2]))
        else:
            queue.sort(key=lambda p: (p[1] != "E1", p[0], p[2]))
        called = queue[:capacity]
        for p in called:
            if day >= 30:                      # skip warm-up
                waits[p[1]].append(day - p[0])
        called_ids = {p[2] for p in called}
        pending = [p for p in pending if p[2] not in called_ids]
    e1 = waits["E1"]
    on_time = sum(1 for x in e1 if x <= 2) / len(e1) if e1 else float("nan")
    med = sorted(e1)[len(e1) // 2] if e1 else float("nan")
    return on_time, med, len(e1)

print(__doc__)
print("calls/day | policy      | E1 called within 2 days of joining the list | median E1 wait (days) | E1 calls made")
for cap in (10, 20, 30, 45):
    for pol in ("first-come", "E1-first"):
        on, med, n = simulate(cap, pol)
        print(f"   {cap:3d}    | {pol:11s} |            {on:6.0%}               |        {med:5}          |   {n}")
