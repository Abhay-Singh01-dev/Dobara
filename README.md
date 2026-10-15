# Dobara — Round 1 technical proof

**Case 03 (Healthcare): The Follow-Up Blind Spot** · AI Synergy Hackathon 2026 · ABV-IIITM Gwalior

*Dobara* (दोबारा) is Hindi for "again". It is the word Indian OPD slips use for a follow-up ("dobara dikhayein"). Dobara makes sure the clinician's "come back" survives the end of the visit:

1. The clinician's free-text instruction is captured in a form the hospital can act on.
2. A clinician confirms it.
3. The patient leaves with a bilingual slip.
4. Each day the records team gets a list of missed follow-ups, with the patients the clinician marked important at the top.

> **Status (declared):** a Round 1 proof of the workflow logic and its safeguards.
> - **Synthetic data only.** No hospital system is connected.
> - **No real SMS** is sent.
> - **No live LLM API** is called. Tests use a fake model. One real-LLM run (Claude, acting as the reader) is frozen and replayed in `eval/llm_run/`.
> - **Not a medical device.** It makes no diagnostic, triage or treatment decisions.

## How a note is read: green, amber, red

| State | When | What the clinician does |
|---|---|---|
| **Green** | Unambiguous wording, e.g. "review after 2 weeks", "RV 2/52", "2 hafte baad dikhayein", "15 दिन बाद दिखाएं" | Confirms it with one action |
| **Amber** (`NEEDS_ACK`) | A plausible reading that isn't unambiguous: "f/u 1/12" (1 month, or 1 December?), "review on 5/1" (next year), a window found by only one reader | Ticks the pre-filled value, or re-enters it |
| **Red** (hard flags) | Conflicts, bound words ("within", "before"), symptom conditions ("if fever persists"), "no follow-up" next to a return request, impossible dates, the two readers disagreeing on the type | Must state the type and window. Nothing is defaulted |

## What is in the repository

| Path | What it is |
|---|---|
| `dobara/extractor.py` | Precision-first rule reader (v2). It is the baseline, the second reader and the outage fallback. Handles English, Hinglish and Hindi in Devanagari script |
| `dobara/llm_guard.py` | LLM prompt and grounding guard: every value must quote the note verbatim, and medicine durations are rejected. Two-reader reconciliation: any disagreement on type or window is red; a single-source value is amber; calendar dates are computed by the rules, never by the AI. An AI pre-fill switch exists but is **off** (see results) |
| `dobara/workflow.py` | `prepare` (nurse: logistic fields only), `confirm` (clinician only), `amend` (clinician, reason required) |
| `dobara/worklist.py` | Return matching (same ID **and** same department **and** not too early), pre-due reminders, E1-first worklist, routing by reachability, alerts for capacity and unconfirmed drafts |
| `dobara/messages.py` | Fixed bilingual templates. Departments are named only from an allow-list; everything else is unnamed |
| `dobara/outreach.py` | Coded outcomes. "Wrong number" stops messages; "opted out" stops messages but keeps the follow-up open |
| `dobara/audit.py` | Hash-chained log with an external head anchor (detects truncation) and deep-copied payloads |
| `tests/test_acceptance.py` | 23 acceptance tests (AT-01 to AT-23) |
| `tests/test_audit_regressions.py` | 13 regression tests that replay the code auditor's own inputs (F1–F10, F16, F17, F22). The other findings are covered by acceptance tests, e.g. F11 by AT-05, F13 by AT-09, F19 by AT-21 and F21 by AT-13 |
| `eval/` | Evaluations and their recorded outputs (below) |

## Run

```bash
python3 -B -m unittest discover -s tests -v   # 36 tests
python3 -B eval/evaluate_heldout.py           # independent held-out notes (dev + sealed halves)
python3 -B eval/evaluate_llm_reader.py all    # real-LLM reader run, replayed from frozen outputs
python3 -B eval/evaluate_extractor.py         # our own synthetic sets
python3 -B eval/ordering_comparison.py        # E1-first vs first-come calling (queue model)
python3 -B eval/workload_model.py             # illustrative workload from case figures
```

This uses only the Python 3.10+ standard library.

## Results, in the order they happened (all synthetic)

**Our own test sets**, written in the same session as the code. These are not independent.

| Set | n | Reader | Auto | Flagged | Silent errors |
|---|---|---|---|---|---|
| Templated | 500 | v1 | 82% | 18% | 0 |
| Hand-written | 30 | v1, first run | 63% | 33% | **1** |
| Hand-written | 30 | v1, after fix | 63% | 37% | 0 |

**Independent held-out notes.** 120 notes were written by a separate AI agent that had not seen the code. Items H001–H060 are the "dev" half, which we may inspect. Items H061–H120 are "sealed": meant to be scored only before and after the fixes and never used for tuning. One post-hoc fix broke that rule; it is disclosed below and not counted.

| Run | Half | Auto | Flagged | Silent errors |
|---|---|---|---|---|
| v1, before fixes | Dev | 47% | 48% | **3 (5.0%)** |
| v1, before fixes | Sealed | 33% | 58% | **5 (8.3%)** |
| v2, after fixes | Dev | 57% | 43% | 0 |
| **v2, after fixes** | **Sealed** | **30%** | **67%** | **2 (3.3%), both wrong windows, no patient dropped** |
| v2.1 post-hoc fix | Sealed | 30% | 70% | 0. **Contaminated:** this fix was made after seeing the two sealed errors, so it is not counted |

**Real-LLM reader run** (`eval/evaluate_llm_reader.py`). A separate Claude agent acted as the production reader. It saw the system prompt in `eval/llm_run/system_prompt.txt` and the 120 note texts, but no labels and no code. It also got two task instructions: convert to whole days, and leave calendar dates blank. Both were then added to the shipped prompt. All 120 notes were processed in one context, whereas production sends one note per call. Its JSON is frozen in `eval/llm_run/` and replayed. On DEV the three policies tied, so we kept the conservative default (pre-fill off) and then reported SEALED once.

| SEALED (n=60) | Green | Amber, correct | Amber, wrong pre-fill | Red | Silent |
|---|---|---|---|---|---|
| Rules only | 30% | 8% | 2% | 60% | 0 |
| **AI as second reader (default)** | **37%** | 2% | **0%** | 62% | 0 |
| AI may also pre-fill (switch on) | 37% | 5% | 3% | 55% | 0 |

- **Contamination:** "rules only" here is the current code (v2.1), so its SEALED row inherits the contamination of the post-hoc fix. The AI outputs themselves were produced blind.
- **Accuracy on its own:** across all 120 notes the AI read 81 correctly and the rules 86 (DEV 41 vs 47; SEALED 40 vs 39, where the rules benefit from the post-hoc fix). The AI is not a better reader than the rules on these notes.
- **As a second reader:** where both readers agreed, 4 notes moved from a tick to green. Where they disagreed, the rules' one wrong pre-fill went to red.
- **Against the pre-audit rule reader (v1, frozen in `eval/history/rules_v1`):** the AI disagreed on 6 of v1's 8 silent errors (DEV 2 of 3, SEALED 4 of 5), so those notes would have gone to a person.
- **Pre-fill switch:** it added 2 wrong pre-fills in 60 notes, so it stays off until the Build Round test BR-01 shows otherwise.

**Ordering model** (`eval/ordering_comparison.py`). This models the same daily demand (about 42 calls' worth) for 120 days. With 20–30 calls a day, E1-first ordering calls **100%** of E1 patients within 2 days of joining the list (the day after the window ends), against **9–33%** with first-come calling. With 45 calls a day the two policies tie, so ordering matters only when capacity is short. Results depend on run length, and the E2 calls that E1-first defers accumulate.

## Designed but not built (Round 1)

- **Paper mode.** A three-line stamp on the OPD slip: *When?* · *If missed: call / remind then call / remind only* · *Bring?*. The clinician ticks it and the records desk transcribes it. Specified in the Brief and SRS; no code yet.
- **Exclusion of programme-tracked follow-ups** (TB via Ni-kshay, HIV via ART centres, antenatal care). V1 uses "No follow-up" plus a reason; there is no dedicated code path yet.
- **Confirmation screen UI.** Only the logic exists; the wireframe is in the Brief.

## Integrity declarations

- All data is synthetic.
- The held-out notes were written by an independent **AI** agent, not by clinicians. The Build Round test BR-01 requires notes written and labelled by people.
- The case figures (900 visits a day, 28%, 19%, 7%) are competition materials, not real statistics.
- The code was written with AI assistance (Claude) in the team's logged session. The team must review it and be able to explain it.
- The Hindi template wording is a draft and needs native-speaker and hospital review.
