"""Core data model for Dobara (AI Synergy Hackathon 2026, Round 1 technical proof).

"Dobara" (दोबारा) is Hindi for "again": the word Indian OPD slips use for a follow-up
visit ("dobara dikhayein"). Everything here runs on SYNTHETIC data only.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import List, Optional


class FUType(str, Enum):
    DATED = "DATED"              # return within a time window or on a stated date
    CONDITIONAL = "CONDITIONAL"  # a return is asked for, but no window was written
    SOS = "SOS"                  # return only if needed; not tracked as a due item
    NONE = "NONE"                # clinician wrote that no follow-up is needed
    UNCLEAR = "UNCLEAR"          # no follow-up instruction could be identified


class Escalation(str, Enum):
    """What staff should do IF the patient misses the window. Chosen by a clinician
    (screen tap or a tick on the OPD-slip stamp). Never derived from diagnoses."""
    E1 = "E1"  # personal call within 2 working days of the window ending
    E2 = "E2"  # reminder; call if still not returned 7 days later
    E3 = "E3"  # reminder only


class ContactType(str, Enum):
    OWN = "OWN"        # patient's own number, verified at registration
    SHARED = "SHARED"  # household / shared number
    NONE = "NONE"      # no number, or known unreachable


# RED flags: the value is left blank (or untrusted) and a person must state the type
# (and, for a dated follow-up, the window) before the record can be confirmed.
HARD_FLAGS = {
    "MISSING_WINDOW", "CONFLICTING_WINDOWS", "CONFLICTING_TYPE", "NO_FOLLOWUP_INSTRUCTION",
    "SYMPTOM_CONDITIONAL", "EVENT_AND_TIME", "WINDOW_BOUNDS_UNCLEAR", "UNGROUNDED_FIELD",
    "EXTRACTOR_DISAGREEMENT", "TYPE_DISAGREEMENT", "AI_UNAVAILABLE", "INVALID_DATE",
    "IMPLAUSIBLE_WINDOW", "AMBIGUOUS_SHORTHAND",
}
# AMBER flag: a value is pre-filled but must be explicitly ticked ("I checked this").
ACK_FLAG = "NEEDS_ACK"
BLOCKING_FLAGS = HARD_FLAGS | {ACK_FLAG}


@dataclass
class Evidence:
    """A verbatim span of the clinician's own text that supports an extracted value."""
    field: str
    value: str
    quote: str
    start: int
    end: int


@dataclass
class Draft:
    """Machine-proposed reading of a free-text follow-up instruction. Never authoritative."""
    extractor: str
    fu_type: FUType
    days_min: Optional[int] = None
    days_max: Optional[int] = None
    abs_date: Optional[date] = None
    prerequisites: List[str] = field(default_factory=list)   # codes: REPORTS, FASTING, MEDICINES, TEST:<name>
    purpose: str = "CLINICAL_REVIEW"
    department: Optional[str] = None
    escalation_suggestion: Optional[Escalation] = None
    also_sos: bool = False
    evidence: List[Evidence] = field(default_factory=list)
    flags: List[str] = field(default_factory=list)

    @property
    def blocking(self) -> List[str]:
        return [f for f in self.flags if f in BLOCKING_FLAGS]

    @property
    def hard(self) -> List[str]:
        return [f for f in self.flags if f in HARD_FLAGS]

    def window(self):
        return (self.days_min, self.days_max)

    def flag(self, *names: str) -> None:
        for n in names:
            if n not in self.flags:
                self.flags.append(n)


@dataclass
class Patient:
    uhid: str
    name: str
    age: int
    sex: str
    village: str
    phone: Optional[str]
    contact_type: ContactType
    sms_consent: bool = False
    call_consent: bool = False
    chw_consent: bool = False  # consent to share name/village/date with the community health worker
