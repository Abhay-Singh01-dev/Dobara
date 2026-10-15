"""Patient-facing text. ALL patient-facing words are fixed templates filled from
clinician-confirmed fields and fixed vocabularies. No AI-generated text reaches a patient.

Privacy rule (audit fix F14): a department is NAMED only if it is on an allow-list after
normalisation; everything else (psychiatry, ICTC/HIV, DVL/skin-VD, OBG/ANC, TB/DOTS, unknown
spellings) is never named in any message or on the slip. Hindi wording is a draft for review.
"""
from __future__ import annotations

import re
from datetime import date

DEPT_ALIASES = {
    "MEDICINE": ["MEDICINE", "GENERAL MEDICINE", "MED", "GM"],
    "SURGERY": ["SURGERY", "GENERAL SURGERY", "SURG"],
    "ORTHOPAEDICS": ["ORTHO", "ORTHOPAEDICS", "ORTHOPEDICS"],
    "ENT": ["ENT"],
    "EYE": ["EYE", "OPHTHAL", "OPHTHALMOLOGY"],
    "PAEDIATRICS": ["PAEDS", "PEDIATRIC", "PEDIATRICS", "PAEDIATRICS", "CHILD"],
    "DENTAL": ["DENTAL", "DENTISTRY"],
    "NCD CLINIC": ["NCD"],
    # never named (not on the allow-list)
    "PSYCHIATRY": ["PSYCHIATRY", "PSYCH", "PSY", "MENTAL HEALTH", "DE-ADDICTION", "DEADDICTION"],
    "OBG": ["OBG", "OBS", "OBSTETRICS", "GYNAE", "GYNAECOLOGY", "GYNECOLOGY", "ANC", "OBS AND GYNAE"],
    "DVL": ["DVL", "SKIN", "SKIN & VD", "SKIN AND VD", "VD", "STD", "STI", "DERMATOLOGY", "DERMA"],
    "ICTC": ["ICTC", "HIV", "ART", "ART CENTRE"],
    "TB": ["TB", "DOTS", "CHEST AND TB", "RNTCP", "NTEP"],
}
NAMEABLE = {"MEDICINE", "SURGERY", "ORTHOPAEDICS", "ENT", "EYE", "PAEDIATRICS", "DENTAL", "NCD CLINIC"}
_ALIAS_TO = {a: canon for canon, aliases in DEPT_ALIASES.items() for a in aliases}

PREREQ_TEXT = {
    "REPORTS": ("Bring all test reports", "सभी जांच रिपोर्ट साथ लाएं"),
    "FASTING": ("Come on an empty stomach", "खाली पेट आएं"),
    "MEDICINES": ("Bring the medicines you are taking", "जो दवाइयां ले रहे हैं, वे साथ लाएं"),
    "OPD_CARD": ("Bring your OPD card", "अपना ओपीडी कार्ड साथ लाएं"),
}
FORBIDDEN_IN_MINIMAL = ["report", "test", "CBC", "LFT", "KFT", "USG", "HbA1c", "fasting", "review", "diagnos",
                        "medicine", "psychiatry", "skin", "hiv", "tb", "obg", "जांच", "दवा"]


def normalize_dept(name: str) -> str:
    s = re.sub(r"[^A-Z& ]", " ", (name or "").upper())
    s = re.sub(r"\b(OPD|CLINIC|DEPT|DEPARTMENT|CENTRE|CENTER|WARD)\b", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    if s in _ALIAS_TO:
        return _ALIAS_TO[s]
    for alias, canon in sorted(_ALIAS_TO.items(), key=lambda kv: -len(kv[0])):
        if re.search(rf"\b{re.escape(alias)}\b", s):
            return canon
    return "OTHER"


def display_dept(name: str):
    canon = normalize_dept(name)
    return canon.title() if canon in NAMEABLE else None


def prereq_text(code: str):
    if code.startswith("TEST:"):
        t = code[5:]
        return (f"Get the {t} test done and bring the result", f"{t} जांच करवाकर रिपोर्ट साथ लाएं")
    return PREREQ_TEXT.get(code)


def _fmt(d: date) -> str:
    return d.strftime("%d-%m-%Y")


def mask_ref(uhid: str) -> str:
    return "XXXX" + uhid[-4:]


def _items(prereq):
    pairs = [prereq_text(c) for c in (prereq or ["OPD_CARD"])]
    pairs = [p for p in pairs if p] or [PREREQ_TEXT["OPD_CARD"]]
    return "; ".join(p[0] for p in pairs), "; ".join(p[1] for p in pairs)


def sms_full(name: str, dept: str, window_end: date, prereq: list, uhid: str, overdue: bool) -> str:
    """For the patient's OWN verified number only. Pre-due wording, or overdue wording that
    never states a deadline that has already passed as if it were still ahead (audit fix M6)."""
    shown = display_dept(dept)
    where = f" {shown} OPD" if shown else " OPD"
    en_items, hi_items = _items(prereq)
    if overdue:
        en = (f"District Hospital: {name}, your follow-up visit at{where} was due by {_fmt(window_end)}. "
              f"Please come as soon as you can. Bring: {en_items}. Ref {mask_ref(uhid)}.")
        hi = (f"जिला अस्पताल: {name}, आपकी दोबारा जांच {_fmt(window_end)} तक होनी थी। कृपया जल्द से जल्द आएं। "
              f"साथ लाएं: {hi_items}। संदर्भ {mask_ref(uhid)}।")
    else:
        en = (f"District Hospital: {name}, please come for your follow-up visit at{where} by {_fmt(window_end)}. "
              f"Bring: {en_items}. Ref {mask_ref(uhid)}.")
        hi = (f"जिला अस्पताल: {name}, कृपया {_fmt(window_end)} तक दोबारा जांच के लिए आएं। "
              f"साथ लाएं: {hi_items}। संदर्भ {mask_ref(uhid)}।")
    return en + "\n" + hi


def sms_minimal(window_end: date, uhid: str, overdue: bool) -> str:
    """SHARED numbers and non-nameable departments: no name, department, reason or tests."""
    if overdue:
        en = f"District Hospital: a visit for ref {mask_ref(uhid)} was due by {_fmt(window_end)}. Please come to OPD registration soon."
        hi = f"जिला अस्पताल: संदर्भ {mask_ref(uhid)} के लिए {_fmt(window_end)} तक आना था। कृपया जल्द ओपीडी पंजीकरण पर आएं।"
    else:
        en = f"District Hospital: please come to OPD registration by {_fmt(window_end)} for ref {mask_ref(uhid)}."
        hi = f"जिला अस्पताल: संदर्भ {mask_ref(uhid)} के लिए {_fmt(window_end)} तक ओपीडी पंजीकरण पर आएं।"
    return en + "\n" + hi


def call_script_shared() -> str:
    return ("Ask to speak to the patient by first name. Do not state the department, reason or tests "
            "to anyone else. If the patient is unavailable, ask only for a good time to call back.")


def call_script_symptoms() -> str:
    """Hospital-authored safety net (placeholder wording, to be written and signed off by the
    clinical team). The software never generates advice."""
    return ("If the patient reports a new or worsening problem: do not advise. Transfer the call to the duty "
            "doctor now. If the duty doctor cannot be reached and the patient describes danger signs, read the "
            "hospital's approved emergency line (come to Emergency / call 108) exactly as written by the clinical "
            "team, and log NEW_OR_WORSE_SYMPTOMS.")


def patient_slip(name: str, dept: str, due_start: date, window_end: date, prereq: list, uhid: str) -> str:
    """Bilingual slip handed to the patient at the end of the visit (fixed vocabulary only)."""
    shown = display_dept(dept)
    where_en = f"{shown} OPD" if shown else "the OPD written on your card"
    where_hi = f"{shown} ओपीडी" if shown else "कार्ड पर लिखी ओपीडी"
    lines = []
    for c in (prereq or ["OPD_CARD"]):
        t = prereq_text(c)
        if t:
            lines.append(f"  - {t[0]} / {t[1]}")
    return (
        f"DOBARA · FOLLOW-UP SLIP / दोबारा दिखाने की पर्ची\n"
        f"Name / नाम: {name}    Ref / संदर्भ: {uhid}\n"
        f"Come back to / कहाँ आएं: {where_en} / {where_hi}\n"
        f"Between / कब: {_fmt(due_start)} – {_fmt(window_end)}\n"
        f"Bring / साथ लाएं:\n" + "\n".join(lines) + "\n"
        f"If you cannot come, tell the hospital when they call. / अगर नहीं आ सकते, तो अस्पताल को बताएं।"
    )
