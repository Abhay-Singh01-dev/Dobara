"""Precision-first rule reader (v2).

v1 ACCEPTED any number near a follow-up word; an independent code audit found 15 ways
that produced silent errors, and an independently written held-out set showed a 5-8%
silent-error rate. v2 inverts the rule:

  GREEN  a window is accepted only from a narrow, unambiguous template
         ("review after 2 weeks", "RV 2/52", "2 hafte baad dikhayein", "15 दिन बाद आएं").
  AMBER  a plausible reading that is not unambiguous is PRE-FILLED but flagged NEEDS_ACK:
         the clinician must tick it.
  RED    anything risky (conflicts, bounds, conditions, implausible or ambiguous dates,
         NONE/SOS next to a return request) leaves the value blank with a HARD flag.

Roles: baseline that any AI reader must beat; independent second reader; outage fallback.
"""
from __future__ import annotations

import re
import unicodedata
from datetime import date, timedelta
from typing import List, Optional, Tuple

from .models import Draft, Escalation, Evidence, FUType

# ---------------------------------------------------------------- vocabulary
_re_compile = re.compile


def _C(pattern, flags=0):
    """Compile with NFC normalisation (Hindi nukta letters have two Unicode spellings)."""
    return _re_compile(unicodedata.normalize("NFC", pattern), flags)

NUM_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "ten": 10, "fifteen": 15,
    "ek": 1, "do": 2, "teen": 3, "char": 4, "chaar": 4, "paanch": 5, "panch": 5, "chhe": 6, "saat": 7,
    "das": 10, "pandrah": 15,
    "एक": 1, "दो": 2, "तीन": 3, "चार": 4, "पांच": 5, "पाँच": 5, "छह": 6, "सात": 7, "दस": 10, "पंद्रह": 15,
}
_NUMW = "|".join(sorted(map(re.escape, NUM_WORDS), key=len, reverse=True))
# Boundaries that also work for Devanagari (whose vowel signs are not \w).
S = r"(?:^|(?<=[\s.,;:!?।|(\[\-–/]))"
E = r"(?=$|[\s.,;:!?।|)\]\-–])"
UNITS = [
    (r"days?|din|dino|dinon|दिन|दिनों", 1),
    (r"weeks?|wks?|wk|hafte|hafton|hafta|saptah|हफ्ते|हफ़्ते|हफ्ता|हफ़्ता|सप्ताह", 7),
    (r"months?|mths?|mth|mahine|mahina|mahino|महीने|महीना|माह", 30),
    (r"years?|yrs?|saal|साल", 365),
]
_UNIT_ALT = "|".join(u for u, _ in UNITS)
DUR_RE = _C(
    rf"{S}(?P<n>\d{{1,3}}(?:\.5)?|{_NUMW})\s*(?:(?:-|–|to|se)\s*(?P<n2>\d{{1,3}}|{_NUMW})\s*)?(?P<u>{_UNIT_ALT}){E}",
    re.I)
SHORT_RE = _C(rf"{S}(?P<n>\d{{1,3}})\s*(?P<u>d|w){E}", re.I)        # digits only: "5d", "2w"
FORTNIGHT_RE = _C(rf"{S}(?:(?:a|one|1|ek)\s+)?fortnight{E}", re.I)
SLASH_RE = _C(rf"{S}(?P<a>\d{{1,2}})\s*/\s*(?P<b>\d{{1,2}})(?:\s*/\s*(?P<y>\d{{2,4}}))?{E}")

TRIGGER = (r"r\s*/\s*v|rv|review|f\s*/\s*u|fu|follow[\s-]?up|followup|revisit|re-?visit|"
           r"next\s+(?:visit|review|follow[\s-]?up|opd|appointment|anc|checkup|check-up|check\s+up|dressing)|come\s+(?:back|again)|come|report\s+back|"
           r"dikhayein|dikhayen|dikhaye|dikhana|dikhane|dikhaiye|dikhao|aana|aaiye|aaye|aayein|aaiyega|"
           r"दिखाएं|दिखाएँ|दिखाना|दिखाने|दिखाइए|दिखाएं|आएं|आएँ|आना|आइए|आयें")
TRIG_RE = _C(rf"{S}(?:{TRIGGER}){E}", re.I)
# What may sit between a trigger and the duration for a GREEN reading.
TW_GAP_RE = _C(r"^[\s:,\-–]*(?:(?:again|back|after|in|on|at|here|me|mein|without\s+fail|zaroor|zarur|jaroor|"
                r"(?:[a-z]+\s+)?(?:opd|op|clinic))[\s:,\-–]+)*$", re.I)
# What may sit between a duration and a trigger ("2 hafte baad dikhayein").
WT_GAP_RE = _C(r"^\s*(?:ke\s+)?(?:baad|bad|later|के\s+बाद|बाद)\s*(?:(?:phir|फिर)\s+)?(?:se\s+)?"
               r"(?:(?:[a-z]+\s+)?(?:opd|clinic)\s+(?:me\s+|mein\s+)?)?"
               r"(?:(?:reports?|jaanch)\s+(?:leke|lekar|ke\s+saath)\s+|(?:जांच\s+)?रिपोर्ट\s+(?:लेकर|के\s+साथ)\s+)?"
               r"(?:(?:zaroor|zarur|jaroor|ज़रूर|जरूर|अवश्य)\s+)?$", re.I)

MED_BEFORE_RE = _C(r"(?:(?:^|\s)x|×|\bfor|\btill|\bsince|\bfrom|\bc/o|\bh/o)\s*$", re.I)
MED_AFTER_RE = _C(r"^\s*(?:tak|course|ka\s+course|se\b|से|तक|of\s+(?:tab|treatment|medicine))", re.I)
DRUG_RE = _C(r"\b(?:tab|tabs|tablet|cap|caps|capsule|syp|syrup|inj|injection|drops?|oint|ointment|"
                     r"cream|gel|inhaler|insulin|mg|ml|od|bd|tds|hs|qid|rx)\b", re.I)
BOUND_RE = _C(r"(?:\b(?:before|within|by|upto|up\s+to|less\s+than|not\s+later|not\s+before|max|maximum|"
                      r"at\s+the\s+latest|latest|se\s+pehle|ke\s+andar)\b|पहले|के\s+अंदर)", re.I)
COND_RE = _C(r"(?:\b(?:if|agar|in\s+case|incase|unless|jab|yadi|when)\b|अगर|यदि|\bजब\b)", re.I)
OR_EARLIER_RE = _C(r"\bor\s+(?:sos|prn|earlier\s+if\s+(?:needed|required)|if\s+(?:needed|required))\b", re.I)
ALT_RE = _C(r"\b(?:or|ya|athwa|athva)\b|\sया\s", re.I)
EVENT_RE = _C(r"\b(?:after|once|when|jab)\s+(?:the\s+)?(?:reports?|results?|usg|ultrasound|x-?ray|ct|mri|"
                      r"cbc|lft|kft|rft|tft|tsh|hba1c|biopsy|fnac|tests?|investigations?|echo|ecg|endoscopy|"
                      r"surgery|delivery|operation)\b", re.I)
NONE_RE = _C(
    r"\bno\s+(?:need\s+(?:for|of|to)\s+)?(?:follow[\s-]?up|f\s*/?\s*u|review|r\s*/?\s*v|revisit|further\s+visits?|"
    r"need\s+to\s+come)\b|\b(?:follow[\s-]?up|f\s*/?\s*u|review|r\s*/?\s*v|revisit)\s+(?:is\s+)?not\s+"
    r"(?:required|needed|necessary)\b|\bdischarged\s+from\s+opd\b|\bdobara\s+aane\s+ki\s+(?:zarurat|zaroorat|jarurat)"
    r"\s+nahi|\bavashyakta\s+nahi|(?:आने|दिखाने)\s+की\s+(?:ज़रूरत|जरूरत|आवश्यकता)\s+नहीं", re.I)
SOS_FU_RE = _C(
    rf"(?:{S}(?:{TRIGGER})\s+(?:only\s+)?(?:sos|prn){E}|{S}sos\s+(?:review|f\s*/\s*u|follow[\s-]?up|visit|come){E}|"
    r"^\s*sos\s*\.?\s*$|\b(?:as|if|when)\s+(?:needed|required)\b|\bzar(?:u|oo)rat\s+(?:padne|pade|ho)|ज़रूरत\s+पड़ने)",
    re.I)
DX_LINE_RE = _C(r"^\s*(?:imp|dx|diagnosis|d/d|k/?c/?o|c/o|h/o|p/h)\b", re.I)
NEG_RE = _C(r"(?:\bnot|\bnon|\bno|\bnothing|\bna|\bnahi|\bnahin)[\s\-]*(?:very\s+|so\s+|that\s+)?$", re.I)
ESC_RE = _C(
    r"must\s+(?:come|review|visit|follow\s*up)|zar(?:u|oo)r\s+(?:aana|aaye|aayen|aaiye|aaiyega|dikhayein|dikhaye|"
    r"dikhana)|jaroor\s+aana|(?:ज़रूर|जरूर|अवश्य)\s+(?:आएं|आएँ|आना|आइए|दिखाएं)|without\s+fail|"
    r"(?:do\s+not|don'?t|dont)\s+miss\s+(?:the\s+|this\s+)?(?:visit|review|follow[\s-]?up|appointment|date)|"
    r"call\s+(?:if|the\s+patient\s+if|pt\s+if)\s+(?:not|doesn'?t|does\s+not)|"
    r"(?:urgent(?:ly)?|important)\s+(?:review|follow[\s-]?up|f\s*/\s*u|r\s*/\s*v|visit)|"
    r"(?:review|follow[\s-]?up|f\s*/\s*u|r\s*/\s*v|visit)\s+(?:is\s+)?(?:urgent(?:ly)?|important)|#E1\b|\bE1\b",
    re.I)
BARE_MISS_RE = _C(r"^\s*(?:do\s+not|don'?t|dont)\s+miss\s*[.!]*\s*$", re.I)

TESTS = ["HbA1c", "CBC", "Hb", "LFT", "KFT", "RFT", "TFT", "TSH", "FBS", "PPBS", "RBS", "lipid profile",
         "USG", "X-ray", "xray", "ECG", "ECHO", "urine R/M", "urine routine", "sputum", "CT", "MRI"]
TEST_RE = _C(r"(?<![\w])(" + "|".join(re.escape(t) for t in TESTS) + r")(?![\w])", re.I)
REPORTS_RE = _C(r"\b(?:with|c|c̄|bring)\s+(?:all\s+|the\s+|old\s+)?reports?\b|\breports?\s+(?:leke|lekar|ke\s+saath)"
                        r"|रिपोर्ट\s+(?:लेकर|के\s+साथ)", re.I)
FASTING_RE = _C(r"\b(?:fasting|khali\s+pet|empty\s+stomach)\b|खाली\s+पेट", re.I)
MEDS_RE = _C(r"\bbring\s+(?:all\s+)?(?:medicines|meds|dawai|dawaiyan)\b|\bdawai(?:yan)?\s+leke\b", re.I)
PROC_RE = _C(r"\b(?:suture|stitch(?:es)?|dressing|plaster|pop|cast|drain\s+removal)\b", re.I)
MONITOR_RE = _C(r"\b(?:bp|sugar)\s+(?:check|monitoring|chart)\b", re.I)
DEPT_RE = _C(r"\b(medicine|ortho|surgery|ent|eye|ophthal|gynae|obg|paeds|pediatric|psychiatry|psych|dvl|skin|"
                     r"dental|ncd|dots|art)\s*(?:opd|clinic|centre|center)\b", re.I)
SPLIT_RE = _C(r"\.(?=\s|$)|(?<=\D)\.(?=\D)|[;\n।|]")
FRAC_UNIT = {52: 7, 12: 30, 7: 1}


def _num(tok: str) -> float:
    t = tok.lower()
    return float(t) if re.fullmatch(r"\d+(?:\.5)?", t) else float(NUM_WORDS.get(t, NUM_WORDS.get(tok, 0)))


def _unit_days(u: str) -> int:
    for pat, d in UNITS:
        if re.fullmatch(pat, u, re.I):
            return d
    return {"d": 1, "w": 7}[u.lower()]


def sentences(text: str) -> List[Tuple[int, str]]:
    out, start = [], 0
    for m in SPLIT_RE.finditer(text):
        out.append((start, text[start:m.start()]))
        start = m.end()
    out.append((start, text[start:]))
    return [(s, c) for s, c in out if c.strip()]


def clauses(sentence: str, offset: int) -> List[Tuple[int, str]]:
    out, start = [], 0
    for m in re.finditer(r",", sentence):
        out.append((offset + start, sentence[start:m.start()]))
        start = m.end()
    out.append((offset + start, sentence[start:]))
    return [(s, c) for s, c in out if c.strip()]


def parse_durations(fragment: str) -> List[Tuple[int, int, int, int, str]]:
    """(min_days, max_days, start, end, quote) for every duration phrase. Used by the reader
    and by the AI grounding guard to re-check quoted evidence."""
    found = []
    for m in DUR_RE.finditer(fragment):
        d = _unit_days(m.group("u"))
        n1 = _num(m.group("n"))
        n2 = _num(m.group("n2")) if m.group("n2") else n1
        if n1 <= 0 or n2 < n1:
            continue
        found.append((int(round(n1 * d)), int(round(n2 * d)), m.start(), m.end(), m.group(0)))
    for m in SHORT_RE.finditer(fragment):
        n = int(m.group("n")) * _unit_days(m.group("u"))
        found.append((n, n, m.start(), m.end(), m.group(0)))
    for m in FORTNIGHT_RE.finditer(fragment):
        found.append((14, 14, m.start(), m.end(), m.group(0)))
    for m in SLASH_RE.finditer(fragment):
        a, b = int(m.group("a")), int(m.group("b"))
        if m.group("y") is None and b in FRAC_UNIT and a >= 1:
            n = a * FRAC_UNIT[b]
            found.append((n, n, m.start(), m.end(), m.group(0)))
    return sorted(found, key=lambda t: t[2])


class RuleExtractor:
    name = "rules-v2"

    def extract(self, text: str, visit_date: date) -> Draft:
        text = unicodedata.normalize("NFC", text or "")
        d = Draft(extractor=self.name, fu_type=FUType.UNCLEAR)
        cands = []          # (lo, hi, strict, quote, abs_pos, reasons, kind)
        trigger_anywhere, sos_fu, cond_sentence_without_window = False, False, False
        none_m = NONE_RE.search(text)

        for s_off, sent in sentences(text):
            sent_has_trigger = bool(TRIG_RE.search(sent))
            trigger_anywhere |= sent_has_trigger
            sent_cands_before = len(cands)
            for c_off, clause in clauses(sent, s_off):
                if not TRIG_RE.search(clause):
                    continue
                self._durations(clause, c_off, cands, visit_date, d)
                self._slashes(clause, c_off, cands, visit_date, d)
            sent_cands = cands[sent_cands_before:]
            for _, clause in clauses(sent, s_off):
                direct_sos = re.search(rf"(?:{TRIGGER})(?:\s+(?:to\s+)?(?:[a-z]+\s+)?(?:opd|clinic))?\s+(?:only\s+)?(?:sos|prn){E}",
                                       clause, re.I)
                lone_sos = re.fullmatch(r"\s*sos\s*\.?\s*", clause, re.I)
                other_sos = SOS_FU_RE.search(clause) and TRIG_RE.search(clause) and not DRUG_RE.search(clause)
                if direct_sos or lone_sos or other_sos:
                    sos_fu = True
            cond = [m for m in COND_RE.finditer(sent)
                    if not OR_EARLIER_RE.search(sent[max(0, m.start() - 4):m.end() + 14])]
            if cond:
                if sent_cands:
                    d.flag("SYMPTOM_CONDITIONAL")
                elif sent_has_trigger:
                    cond_sentence_without_window = True
            if OR_EARLIER_RE.search(sent) and sent_cands:
                d.also_sos = True
            if sent_cands and [m for m in ALT_RE.finditer(sent) if not OR_EARLIER_RE.search(sent[m.start():m.end() + 20])]:
                d.flag("CONFLICTING_WINDOWS")    # "RV 1 wk ya wapas aane ke baad": two alternatives, a person picks

        distinct = sorted({(c[0], c[1]) for c in cands})
        if EVENT_RE.search(text) and trigger_anywhere:
            d.flag("EVENT_AND_TIME" if distinct else "MISSING_WINDOW")

        if none_m:
            # A "no follow-up" phrase next to a return request is a conflict, never a silent choice.
            other_trigger = any(m.start() < none_m.start() or m.start() > none_m.end() for m in TRIG_RE.finditer(text))
            if distinct or other_trigger:
                d.fu_type = FUType.DATED if distinct else FUType.CONDITIONAL
                d.flag("CONFLICTING_TYPE")
            else:
                d.fu_type = FUType.NONE
                d.evidence.append(Evidence("fu_type", "NONE", none_m.group(0), none_m.start(), none_m.end()))
        elif len(distinct) > 1:
            d.fu_type = FUType.DATED
            d.flag("CONFLICTING_WINDOWS")
        elif len(distinct) == 1:
            d.fu_type = FUType.DATED
            lo, hi = distinct[0]
            mine = [c for c in cands if (c[0], c[1]) == (lo, hi)]
            d.days_min, d.days_max = lo, hi
            if hi > 365:
                d.flag("IMPLAUSIBLE_WINDOW")
                d.days_min = d.days_max = None
            elif not any(c[2] for c in mine):
                d.flag("NEEDS_ACK")
                for c in mine:
                    for r in c[5]:
                        d.flag("ACK:" + r)
            for c in mine:
                d.evidence.append(Evidence("window", f"{lo}-{hi}", c[3], c[4], c[4] + len(c[3])))
                if c[6] == "date":
                    d.abs_date = visit_date + timedelta(days=lo)
        elif sos_fu or cond_sentence_without_window:
            d.fu_type = FUType.SOS
            if cond_sentence_without_window and not sos_fu:
                d.flag("SYMPTOM_CONDITIONAL")
        elif trigger_anywhere:
            d.fu_type = FUType.CONDITIONAL
            d.flag("MISSING_WINDOW")
        else:
            d.fu_type = FUType.UNCLEAR
            d.flag("NO_FOLLOWUP_INSTRUCTION")

        if d.fu_type == FUType.DATED and sos_fu and not d.also_sos:
            d.flag("SYMPTOM_CONDITIONAL")       # "review after 2 days ... SOS" in one instruction: let a person decide

        self._prerequisites(text, d)
        self._purpose_dept(text, d)
        self._escalation(text, d)
        if d.fu_type == FUType.DATED and d.escalation_suggestion is None:
            d.flag("ESCALATION_NOT_SPECIFIED")   # informational: the clinician must choose E1-E3
        return d

    # ------------------------------------------------------------ windows
    @staticmethod
    def _durations(clause, c_off, cands, visit_date, d):
        trig = list(TRIG_RE.finditer(clause))
        risky = []
        if DRUG_RE.search(clause):
            risky.append("MED_CONTEXT")
        n_before = len(cands)
        for lo, hi, s, e, q in parse_durations(clause):
            if re.fullmatch(r"\s*\d{1,2}\s*/\s*\d{1,2}\s*", q):
                continue  # slash forms are handled by _slashes (date ambiguity)
            before, after = clause[:s], clause[e:]
            if MED_BEFORE_RE.search(before[-14:]) or MED_AFTER_RE.search(after):
                continue  # medicine course or complaint duration: never a follow-up window
            strict = any(t.end() <= s and TW_GAP_RE.match(clause[t.end():s]) and len(clause[t.end():s]) <= 24
                         for t in trig) or \
                any(t.start() >= e and WT_GAP_RE.match(clause[e:t.start()]) and len(clause[e:t.start()]) <= 40
                    for t in trig)
            reasons = list(risky) + ([] if strict else ["NON_ADJACENT"])
            cands.append((lo, hi, strict and not risky, q, c_off + s, reasons, "duration"))
        if len(cands) > n_before and BOUND_RE.search(clause):
            d.flag("WINDOW_BOUNDS_UNCLEAR")   # "within / before / by / upto / max ..." changes what the number means

    @staticmethod
    def _slashes(clause, c_off, cands, visit_date, d):
        trig = list(TRIG_RE.finditer(clause))
        for m in SLASH_RE.finditer(clause):
            a, b, y = int(m.group("a")), int(m.group("b")), m.group("y")
            near = any(t.end() <= m.start() and len(clause[t.end():m.start()]) <= 24
                       and re.match(r"^[\s:,\-–]*(?:(?:after|in|on|at|again|here|dated?|dt\.?|without\s+fail|zaroor|zarur|"
                                    r"(?:[a-z]+\s+)?(?:opd|op|clinic))[\s:,\-–]+)*$",
                                    clause[t.end():m.start()], re.I) for t in trig)
            if not near:
                continue
            explicit_date = bool(re.search(r"(?:\bon|\bdated?|\bdt\.?)\s*$", clause[:m.start()], re.I)) or y is not None
            frac_ok = (b == 52 and 1 <= a <= 12) or (b == 12 and 1 <= a <= 12) or (b == 7 and 1 <= a <= 6)
            date_reading = None if b > 12 else RuleExtractor._as_date(a, b, y, visit_date)
            q = m.group(0)
            if explicit_date or (not frac_ok):
                if b > 12 and not explicit_date:
                    d.flag("IMPLAUSIBLE_WINDOW")
                    continue
                if date_reading is None:
                    d.flag("INVALID_DATE")
                    continue
                delta, inferred_year = date_reading
                reasons = ["YEAR_INFERRED"] if inferred_year else []
                if not explicit_date:
                    reasons.append("SHORTHAND_OR_DATE")
                cands.append((delta, delta, not reasons, q, c_off + m.start(), reasons, "date"))
            else:
                n = a * FRAC_UNIT[b]
                reasons = []
                if b in (12, 7) and date_reading is not None and date_reading[0] <= 120 and not date_reading[1]:
                    if abs(n - date_reading[0]) > 7:
                        d.flag("AMBIGUOUS_SHORTHAND")      # "2/12": 2 months (60 d) or 2 December (30 d)?
                        continue
                    reasons.append("SHORTHAND_OR_DATE")    # both readings within a week: pre-fill, ask for a tick
                cands.append((n, n, not reasons, q, c_off + m.start(), reasons, "duration"))

    @staticmethod
    def _as_date(dd, mm, yy, visit):
        try:
            year = visit.year if yy is None else (int(yy) + 2000 if int(yy) < 100 else int(yy))
            dt = date(year, mm, dd)
        except ValueError:
            return None
        inferred = False
        if dt <= visit and yy is None and (visit.month - mm) >= 6:
            try:
                dt, inferred = date(year + 1, mm, dd), True
            except ValueError:
                return None
        delta = (dt - visit).days
        if delta <= 0 or delta > 365:
            return None
        return delta, inferred

    # ------------------------------------------------------------ other fields
    @staticmethod
    def _prerequisites(text: str, d: Draft) -> None:
        items = []
        if REPORTS_RE.search(text):
            items.append("REPORTS")
        for _, sent in sentences(text):
            for _, clause in clauses(sent, 0):
                if DX_LINE_RE.match(clause):
                    continue
                if TRIG_RE.search(clause) or re.search(r"\b(?:repeat|get|karwa|karwake|karwakar|with|c)\b", clause, re.I):
                    for m in TEST_RE.finditer(clause):
                        code = "TEST:" + next(t for t in TESTS if t.lower() == m.group(1).lower())
                        if code not in items:
                            items.append(code)
        if FASTING_RE.search(text):
            items.append("FASTING")
        if MEDS_RE.search(text):
            items.append("MEDICINES")
        d.prerequisites = items

    @staticmethod
    def _purpose_dept(text: str, d: Draft) -> None:
        if PROC_RE.search(text):
            d.purpose = "PROCEDURE"
        elif MONITOR_RE.search(text):
            d.purpose = "MONITORING"
        elif any(p == "REPORTS" or p.startswith("TEST:") for p in d.prerequisites):
            d.purpose = "REVIEW_WITH_RESULTS"
        m = DEPT_RE.search(text)
        if m:
            d.department = m.group(1).upper()

    @staticmethod
    def _escalation(text: str, d: Draft) -> None:
        """Pre-fill E1 ONLY from an explicit, non-negated phrase about coming back, written by
        the clinician. Never from diagnoses, 'Imp:' lines, tests ("urgent USG") or medicines."""
        has_trigger = bool(TRIG_RE.search(text))
        for s_off, sent in sentences(text):
            for c_off, clause in clauses(sent, s_off):
                if DX_LINE_RE.match(clause):
                    continue
                if BARE_MISS_RE.match(clause) and has_trigger:
                    d.escalation_suggestion = Escalation.E1
                    d.evidence.append(Evidence("escalation", "E1", clause.strip(), c_off, c_off + len(clause)))
                    return
                for m in ESC_RE.finditer(clause):
                    if NEG_RE.search(clause[max(0, m.start() - 16):m.start()]):
                        continue
                    d.escalation_suggestion = Escalation.E1
                    d.evidence.append(Evidence("escalation", "E1", m.group(0), c_off + m.start(), c_off + m.end()))
                    return
