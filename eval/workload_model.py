"""Illustrative workload model. Inputs marked CASE come from the case file (simulated competition data);
inputs marked ASSUMPTION are ours and are varied, not asserted."""
VISITS_PER_DAY = 900          # CASE (p.6, simulated)
NON_RETURN = 0.28             # CASE (p.6, 3-month sample, simulated)
SHARED, UNREACHABLE = 0.19, 0.07   # CASE (p.6); ASSUMPTION: categories are disjoint
OPD_DAYS_PER_MONTH = 25       # ASSUMPTION (6-day OPD week)
MIN_PER_CALL_ATTEMPT = 6      # ASSUMPTION incl. dialling, retries, logging
print("Own, reachable number: "
      f"{1-SHARED-UNREACHABLE:.0%} if shared and unreachable numbers never overlap (lower bound); "
      f"up to {1-max(SHARED, UNREACHABLE):.0%} if they fully overlap")
print("\nfraction_marked | marked/day | missed/day | missed/month | staff-hours/day to call every miss")
for f in (0.10, 0.20, 0.30, 0.40):        # UNKNOWN in case -> swept
    marked = VISITS_PER_DAY * f
    missed = marked * NON_RETURN
    hours = missed * MIN_PER_CALL_ATTEMPT / 60
    print(f"     {f:.0%}        |   {marked:5.0f}    |   {missed:5.1f}    |   {missed*OPD_DAYS_PER_MONTH:6.0f}     |   {hours:4.1f}")
