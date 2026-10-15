"""Deterministic rule-based extractor.

Role in the design:
  * It is the BASELINE that any AI (LLM) extractor must beat in the Build Round.
  * It is the INDEPENDENT SECOND READER: when the LLM and the rules disagree on the
    follow-up window, the record is flagged for the clinician instead of picking one.
  * It is the FALLBACK when the AI service is unavailable.

Design rule: when unsure, FLAG — never guess. A wrong window that nobody notices
(a "silent error") is the failure this component is measured against.
"""
from __future__ import annotations

import re
from datetime import date, timedelta
from typing import List, Optional, Tuple

from .models import Draft, Escalation, Evidence, FUType

NUM_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "ten": 10,
    "ek": 1, "do": 2, "teen": 3, "char": 4, "chaar": 4, "paanch": 5, "panch": 5,
    "chhe": 6, "saat": 7, "das": 10, "pandrah": 15,
}
_NUM = r"\d{1,3}|" + "|".join(sorted(NUM_WORDS, key=len, reverse=True))
_UNIT = (r"days?|din|d|weeks?|wks?|wk|w|hafte|hafton|hafta|saptah|"
         r"months?|mths?|mth|mo|mahine|mahina|mahino")
DUR_RE = re.compile(
    rf"(?<![\w/])(?P<n>{_NUM})\s*(?:(?:-|–|to)\s*(?P<n2>{_NUM})\s*)?(?P<u>{_UNIT})\b", re.I)
# Clinical shorthand: 2/52 = 2 weeks, 1/12 = 1 month, 5/7 = 5 days
FRAC_RE = re.compile(r"(?<![\d/])(?P<n>\d{1,2})\s*/\s*(?P<d>52|12|7)(?![\d/])")
DATE_RE = re.compile(
    r"\b(?:on|dated|date)\s*(?P<d>\d{1,2})[/.\-](?P<m>\d{1,2})(?:[/.\-](?P<y>\d{2,4}))?", re.I)

STRONG_TRIGGER_RE = re.compile(
    r"(?<![\w])(r/?v|review|f/?u|follow[\s-]?up|followup|revisit|re-visit|come back|come again|"
    r"next visit|dikhayein|dikhaye|dikhana|dikhane|dikhaiye|aana|aaiye|aaye|aayein)(?![\w])", re.I)
AFTER_RE = re.compile(r"(after|in)\s*$", re.I)          # "... after 2 weeks", "... in 10 days"
BAAD_RE = re.compile(r"^\s*(baad|ke baad)\b", re.I)       # "2 hafte baad"
# Durations of medication courses or complaints are not follow-up windows.
MED_BEFORE_RE = re.compile(r"(\bx|×|\bfor|\btill|\bsince|\bfrom|\bc/o\b[^.]*?)\s*$", re.I)
MED_AFTER_RE = re.compile(r"^\s*(tak|course|ka course)\b", re.I)

SOS_RE = re.compile(r"\b(sos|prn|as needed|if needed|if required|zarurat|zaroorat padne)\b", re.I)
SYMPTOM_COND_RE = re.compile(
    r"\bif\b[^.;]{0,35}\b(persist|persists|worsen|worsens|recur|recurs|continues|not better|"
    r"no improvement|no relief)\b", re.I)
NONE_RE = re.compile(
    r"\b(no (?:follow[\s-]?up|f/?u|review)( needed| required)?|not required|discharged from opd|no need to come)\b",
    re.I)
ESC_RE = re.compile(
    r"\b(must come|must review|do not miss|don'?t miss|dont miss|without fail|zaroor aana|"
    r"zaroor aaye|jaroor aana|important|urgent(?:ly)?|call (?:if|the patient|pt))\b", re.I)
# NB: "imp" is deliberately excluded — in Indian OPD notes "Imp:" means "Impression" (a diagnosis line).
NEGATION_RE = re.compile(r"\b(not|no|non)\s*$", re.I)
# Added after first evaluation run (silent error on "Do not come before 1 week; review within 2 weeks"):
# bound words change what a number means, so the window goes to the clinician instead of being read.
BOUND_RE = re.compile(r"\b(before|within|not earlier than|not later than|latest by|se pehle|ke andar)\s*$", re.I)

TESTS = ["HbA1c", "CBC", "Hb", "LFT", "KFT", "RFT", "FBS", "PPBS", "RBS", "TSH", "lipid profile",
         "USG", "X-ray", "xray", "ECG", "ECHO", "urine R/M", "urine routine", "sputum", "CT", "MRI"]
TEST_RE = re.compile(r"(?<![\w])(" + "|".join(re.escape(t) for t in TESTS) + r")(?![\w])", re.I)
REPORTS_RE = re.compile(r"\b(with reports?|c reports?|reports? leke|reports? lekar|reports? ke saath|"
                        r"with (?:the )?report|bring reports?)\b", re.I)
FASTING_RE = re.compile(r"\b(fasting|khali pet|empty stomach)\b", re.I)
MEDS_RE = re.compile(r"\b(bring (?:all )?(?:medicines|meds|dawai|dawaiyan)|dawai(?:yan)? leke)\b", re.I)
PROC_RE = re.compile(r"\b(suture|stitch(?:es)?|dressing|plaster|pop|cast|drain removal)\b", re.I)
MONITOR_RE = re.compile(r"\b(bp check|sugar check|bp monitoring|bp chart|sugar chart)\b", re.I)
DEPT_RE = re.compile(r"\b(medicine|ortho|surgery|ent|eye|ophthal|gynae|obg|paeds|pediatric|psychiatry|"
                     r"dvl|skin|dental|ncd)\s*(opd|clinic)\b", re.I)

UNIT_DAYS = [
    (re.compile(r"^(days?|din|d)$", re.I), 1),
    (re.compile(r"^(weeks?|wks?|wk|w|hafte|hafton|hafta|saptah)$", re.I), 7),
    (re.compile(r"^(months?|mths?|mth|mo|mahine|mahina|mahino)$", re.I), 30),
]
FRAC_DAYS = {"52": 7, "12": 30, "7": 1}


def _num(tok: str) -> int:
    tok = tok.lower()
    return int(tok) if tok.isdigit() else NUM_WORDS[tok]


def _unit_days(u: str) -> int:
    for rx, d in UNIT_DAYS:
        if rx.match(u):
            return d
    raise ValueError(u)


def _clauses(text: str) -> List[Tuple[int, str]]:
    """Split into clauses on . ; , newline — keeping absolute offsets."""
    out, start = [], 0
    for m in re.finditer(r"[.;,\n]", text):
        out.append((start, text[start:m.start()]))
        start = m.end()
    out.append((start, text[start:]))
    return [(s, c) for s, c in out if c.strip()]


def parse_durations(fragment: str) -> List[Tuple[int, int, int, int, str]]:
    """Return (min_days, max_days, start, end, quote) for every duration in a fragment.
    Used by the extractor AND by the LLM grounding guard to re-check quoted evidence."""
    found = []
    for m in DUR_RE.finditer(fragment):
        n1 = _num(m.group("n"))
        n2 = _num(m.group("n2")) if m.group("n2") else n1
        d = _unit_days(m.group("u"))
        found.append((n1 * d, n2 * d, m.start(), m.end(), m.group(0)))
    for m in FRAC_RE.finditer(fragment):
        before = fragment[max(0, m.start() - 4):m.start()].lower()
        if "on" in before:
            continue  # "on 1/12" is a date, not shorthand
        n = int(m.group("n")) * FRAC_DAYS[m.group("d")]
        found.append((n, n, m.start(), m.end(), m.group(0)))
    return found


class RuleExtractor:
    name = "rules-v1"

    def extract(self, text: str, visit_date: date) -> Draft:
        d = Draft(extractor=self.name, fu_type=FUType.UNCLEAR)
        windows: List[Tuple[int, int]] = []
        abs_dates: List[date] = []
        has_trigger = False

        for off, clause in _clauses(text):
            strong = STRONG_TRIGGER_RE.search(clause)
            has_trigger = has_trigger or bool(strong)
            for lo, hi, s, e, quote in parse_durations(clause):
                before, after = clause[:s], clause[e:]
                if MED_BEFORE_RE.search(before[-12:]) or MED_AFTER_RE.search(after):
                    continue  # medication course / complaint duration
                adjacent = AFTER_RE.search(before[-8:]) or BAAD_RE.search(after)
                if BOUND_RE.search(before[-20:]) and "WINDOW_BOUNDS_UNCLEAR" not in d.flags:
                    d.flags.append("WINDOW_BOUNDS_UNCLEAR")
                if not (strong or adjacent):
                    continue
                has_trigger = True
                if (lo, hi) not in windows:
                    windows.append((lo, hi))
                d.evidence.append(Evidence("window", f"{lo}-{hi}", quote, off + s, off + e))
            for m in DATE_RE.finditer(clause):
                has_trigger = True
                try:
                    y = int(m.group("y")) if m.group("y") else visit_date.year
                    y = y + 2000 if y < 100 else y
                    dt = date(y, int(m.group("m")), int(m.group("d")))
                except ValueError:
                    d.flags.append("INVALID_DATE")
                    continue
                if dt <= visit_date:
                    d.flags.append("INVALID_DATE")
                    continue
                abs_dates.append(dt)
                d.evidence.append(Evidence("abs_date", dt.isoformat(), m.group(0), off + m.start(), off + m.end()))

        sos = SOS_RE.search(text)
        none = NONE_RE.search(text)
        symptom_cond = SYMPTOM_COND_RE.search(text)

        n_distinct = len(windows) + len(abs_dates)
        if n_distinct > 1:
            d.fu_type = FUType.DATED
            d.flags.append("CONFLICTING_WINDOWS")
        elif windows:
            d.fu_type = FUType.DATED
            d.days_min, d.days_max = windows[0]
        elif abs_dates:
            d.fu_type = FUType.DATED
            d.abs_date = abs_dates[0]
            delta = (abs_dates[0] - visit_date).days
            d.days_min = d.days_max = delta
        elif none:
            d.fu_type = FUType.NONE
            d.evidence.append(Evidence("fu_type", "NONE", none.group(0), none.start(), none.end()))
        elif sos:
            d.fu_type = FUType.SOS
            d.evidence.append(Evidence("fu_type", "SOS", sos.group(0), sos.start(), sos.end()))
        elif symptom_cond:
            d.fu_type = FUType.SOS  # "come back if fever persists" = return only if needed
        elif has_trigger:
            d.fu_type = FUType.CONDITIONAL
            d.flags.append("MISSING_WINDOW")
        else:
            d.fu_type = FUType.UNCLEAR
            d.flags.append("NO_FOLLOWUP_INSTRUCTION")

        if d.fu_type == FUType.DATED and sos:
            d.also_sos = True
        if symptom_cond:
            d.flags.append("SYMPTOM_CONDITIONAL")  # "come back in 2 days IF fever persists": clinician decides

        self._prerequisites(text, d)
        self._purpose_dept(text, d)
        self._escalation(text, d)
        if d.fu_type == FUType.DATED and d.escalation_suggestion is None:
            d.flags.append("ESCALATION_NOT_SPECIFIED")  # informational: clinician must choose
        return d

    @staticmethod
    def _prerequisites(text: str, d: Draft) -> None:
        items = []
        if REPORTS_RE.search(text):
            items.append("Bring all test reports")
        tests = []
        for off, clause in _clauses(text):
            if STRONG_TRIGGER_RE.search(clause) or re.search(r"\b(repeat|get|karwa|karwake|with|c)\b", clause, re.I):
                for m in TEST_RE.finditer(clause):
                    t = m.group(1)
                    if t.upper() not in {x.upper() for x in tests}:
                        tests.append(t)
        if tests:
            items.append("Tests to complete/bring: " + ", ".join(tests))
        if FASTING_RE.search(text):
            items.append("Come fasting")
        if MEDS_RE.search(text):
            items.append("Bring current medicines")
        d.prerequisites = items

    @staticmethod
    def _purpose_dept(text: str, d: Draft) -> None:
        if PROC_RE.search(text):
            d.purpose = "PROCEDURE"
        elif MONITOR_RE.search(text):
            d.purpose = "MONITORING"
        elif any("Tests" in p or "reports" in p for p in d.prerequisites):
            d.purpose = "REVIEW_WITH_RESULTS"
        m = DEPT_RE.search(text)
        if m:
            d.department = m.group(1).upper()

    @staticmethod
    def _escalation(text: str, d: Draft) -> None:
        """Pre-fill E1 ONLY when the clinician explicitly wrote an escalation phrase.
        Never inferred from diagnoses, symptoms, age or history."""
        for m in ESC_RE.finditer(text):
            if NEGATION_RE.search(text[max(0, m.start() - 5):m.start()]):
                continue  # "not urgent"
            d.escalation_suggestion = Escalation.E1
            d.evidence.append(Evidence("escalation", "E1", m.group(0), m.start(), m.end()))
            return
