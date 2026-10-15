# Real-LLM reader run: what the model saw

- **Model:** Claude, run as a separate agent. It was not called through an API.
- **Inputs:** `system_prompt.txt` (the production prompt at the time of the run) and `input_notes.json` (120 note texts, no labels).
- **Extra task instructions given to the agent** (both have since been added to `SYSTEM_PROMPT` in `dobara/llm_guard.py`):
  - min_days/max_days are whole days (1 week = 7, 1 month = 30, 1 year = 365; "1-2 weeks" = 7..14).
  - If the instruction gives a calendar date and no visit date is known, return window null.
- **Context:** all 120 notes were processed in one context. Production sends one note per call.
- **Output:** `claude_outputs.json`, frozen and replayed by `eval/evaluate_llm_reader.py`.
- **Protocol:** on the DEV half the three policies gave identical results, so the conservative default (pre-fill off) was kept. SEALED was then reported once and supported that choice.
