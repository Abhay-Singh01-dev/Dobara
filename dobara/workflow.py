"""Follow-up record lifecycle: capture -> AI/rule draft -> (nurse prepares) -> clinician confirms.

Human/AI boundary enforced here (v2, after the independent code audit):
  * The AI only proposes a Draft.
  * ONLY a clinician can confirm a record or change its type (F11). A nurse may PREPARE
    logistic fields (window, prerequisites, department) and tick AMBER values, which the
    clinician then confirms with one action.
  * Any HARD flag requires the follow-up type to be stated explicitly, and a dated window
    to be entered, whatever type the draft guessed (F7).
  * An AMBER value (NEEDS_ACK) must be ticked ("acknowledge") or re-entered.
  * A confirmed record can only be changed through amend(), with a reason, by a clinician.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Dict, Iterable, List, Optional, Set

from .audit import AuditLog
from .models import ACK_FLAG, Draft, Escalation, FUType, Patient


class ConfirmationError(Exception):
    pass


# Hospital policy (configurable, owned by administration, not learned by AI): days added
# after the written window before an E2/E3 patient counts as missed. E1 has no grace.
GRACE_POLICY = [(7, 3), (30, 7), (10 ** 6, 14)]
LOGISTIC_FIELDS = {"days_min", "days_max", "prerequisites", "department"}


def grace_for(days_max: int) -> int:
    for limit, g in GRACE_POLICY:
        if days_max <= limit:
            return g
    return 14


@dataclass
class FollowUpRecord:
    record_id: str
    patient: Patient
    visit_date: date
    department: str
    clinician_id: str
    source_text: str
    draft: Draft
    status: str = "NEEDS_CONFIRMATION"   # -> CONFIRMED | NOT_TRACKED
    fu_type: Optional[FUType] = None
    days_min: Optional[int] = None
    days_max: Optional[int] = None
    escalation: Optional[Escalation] = None
    prerequisites: List[str] = field(default_factory=list)
    due_start: Optional[date] = None
    window_end: Optional[date] = None
    missed_after: Optional[date] = None     # window_end (E1) or window_end + grace (E2/E3)
    closed: bool = False
    closed_reason: Optional[str] = None
    notes: List[str] = field(default_factory=list)
    pending: Dict = field(default_factory=dict)
    pending_ack: Set[str] = field(default_factory=set)


def create_record(record_id, patient, visit_date, department, clinician_id, text, extractor,
                  audit: AuditLog, now: datetime | None = None) -> FollowUpRecord:
    try:
        draft = extractor.extract(text, visit_date)
    except Exception as exc:  # reader failure must never block care documentation
        draft = Draft(extractor=getattr(extractor, "name", "unknown"), fu_type=FUType.UNCLEAR,
                      flags=["AI_UNAVAILABLE"])
        audit.append(record_id, "EXTRACTOR_FAILED", "system", "system", {"error": type(exc).__name__}, now)
    if draft.department is None:
        draft.department = department
    rec = FollowUpRecord(record_id, patient, visit_date, department, clinician_id, text, draft)
    audit.append(record_id, "DRAFT", draft.extractor, "machine", {
        "source_text": text, "fu_type": draft.fu_type.value, "window": draft.window(),
        "escalation_suggestion": draft.escalation_suggestion.value if draft.escalation_suggestion else None,
        "flags": draft.flags, "evidence": [(e.field, e.quote) for e in draft.evidence]}, now)
    return rec


def prepare(rec: FollowUpRecord, user_id: str, role: str, audit: AuditLog, overrides: Optional[Dict] = None,
            acknowledge: Iterable[str] = (), now: datetime | None = None) -> FollowUpRecord:
    """Nurse (or clinician) stages logistic values before the clinician confirms."""
    overrides = dict(overrides or {})
    if rec.status != "NEEDS_CONFIRMATION":
        raise ConfirmationError("Record already confirmed; a clinician must use amend().")
    if role != "clinician" and set(overrides) - LOGISTIC_FIELDS:
        raise ConfirmationError("Only a clinician can set the follow-up type or escalation.")
    rec.pending.update(overrides)
    rec.pending_ack |= set(acknowledge)
    audit.append(rec.record_id, "PREPARED", user_id, role, {"overrides": overrides, "ack": sorted(acknowledge)}, now)
    return rec


def _apply(rec: FollowUpRecord, ov: Dict, ack: Set[str], escalation: Optional[Escalation]):
    d = rec.draft
    hard = d.hard
    if hard and "fu_type" not in ov:
        raise ConfirmationError(f"{hard}: the follow-up type must be stated explicitly by a clinician.")
    fu_type = FUType(ov.get("fu_type", d.fu_type))
    if fu_type in (FUType.CONDITIONAL, FUType.UNCLEAR):
        raise ConfirmationError("Record must be confirmed as DATED, SOS or NONE.")
    window_entered = "days_min" in ov and "days_max" in ov
    if fu_type == FUType.DATED:
        if hard and not window_entered:
            raise ConfirmationError(f"{hard}: the window must be entered by a person.")
        if ACK_FLAG in d.flags and "window" not in ack and not window_entered:
            raise ConfirmationError("The pre-filled window must be ticked as checked, or re-entered.")
        lo, hi = ov.get("days_min", d.days_min), ov.get("days_max", d.days_max)
        if not (isinstance(lo, int) and isinstance(hi, int)) or not (1 <= lo <= hi <= 365):
            raise ConfirmationError("A dated follow-up needs a valid window of 1-365 days.")
        if escalation is None:
            raise ConfirmationError("Escalation level is required: the clinician must choose E1, E2 or E3.")
        return fu_type, lo, hi, escalation
    return fu_type, None, None, None


def _set(rec: FollowUpRecord, fu_type, lo, hi, escalation, ov):
    rec.fu_type, rec.days_min, rec.days_max, rec.escalation = fu_type, lo, hi, escalation
    rec.prerequisites = ov.get("prerequisites", rec.draft.prerequisites)
    if "department" in ov:
        rec.department = ov["department"]
    if fu_type == FUType.DATED:
        rec.due_start = rec.visit_date + timedelta(days=lo)
        rec.window_end = rec.visit_date + timedelta(days=hi)
        rec.missed_after = rec.window_end if escalation == Escalation.E1 else rec.window_end + timedelta(days=grace_for(hi))
        rec.status = "CONFIRMED"
    else:
        rec.due_start = rec.window_end = rec.missed_after = None
        rec.status = "NOT_TRACKED"


def confirm(rec: FollowUpRecord, user_id: str, role: str, audit: AuditLog,
            escalation: Optional[Escalation] = None, overrides: Optional[Dict] = None,
            acknowledge: Iterable[str] = (), now: datetime | None = None) -> FollowUpRecord:
    if role != "clinician":
        raise ConfirmationError("Only a clinician can confirm a follow-up record.")
    if rec.status != "NEEDS_CONFIRMATION":
        raise ConfirmationError("Record already confirmed; use amend() with a reason.")
    ov = {**rec.pending, **(overrides or {})}
    ack = rec.pending_ack | set(acknowledge)
    fu_type, lo, hi, esc = _apply(rec, ov, ack, escalation)
    _set(rec, fu_type, lo, hi, esc, ov)
    d = rec.draft
    changed = dict(ov)
    if esc and d.escalation_suggestion and esc != d.escalation_suggestion:
        changed["escalation_changed_from_suggestion"] = d.escalation_suggestion.value
    audit.append(rec.record_id, "CONFIRMED", user_id, role, {
        "fu_type": fu_type.value, "window": (lo, hi), "escalation": esc.value if esc else None,
        "human_changes": changed, "acknowledged": sorted(ack), "flags_resolved": d.blocking,
        "accepted_as_drafted": not changed}, now)
    return rec


def amend(rec: FollowUpRecord, user_id: str, role: str, audit: AuditLog, reason: str,
          escalation: Optional[Escalation] = None, overrides: Optional[Dict] = None,
          now: datetime | None = None) -> FollowUpRecord:
    """Change a confirmed record. Clinician only, reason required, before/after logged."""
    if role != "clinician":
        raise ConfirmationError("Only a clinician can amend a confirmed record.")
    if rec.status == "NEEDS_CONFIRMATION":
        raise ConfirmationError("Record is not confirmed yet; use confirm().")
    if not reason or not reason.strip():
        raise ConfirmationError("A reason is required to amend a confirmed record.")
    before = {"fu_type": rec.fu_type.value, "window": (rec.days_min, rec.days_max),
              "escalation": rec.escalation.value if rec.escalation else None}
    ov = dict(overrides or {})
    ov.setdefault("fu_type", rec.fu_type.value)
    if FUType(ov["fu_type"]) == FUType.DATED:
        ov.setdefault("days_min", rec.days_min)
        ov.setdefault("days_max", rec.days_max)
    esc = escalation if escalation is not None else rec.escalation
    fu_type, lo, hi, esc = _apply(rec, ov, {"window"}, esc)
    _set(rec, fu_type, lo, hi, esc, ov)
    audit.append(rec.record_id, "AMENDED", user_id, role, {"before": before, "after": {
        "fu_type": fu_type.value, "window": (lo, hi), "escalation": esc.value if esc else None}, "reason": reason}, now)
    return rec
