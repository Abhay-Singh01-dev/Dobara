"""Daily lists for the records team.

  * pre_due_reminders(): one reminder before the window closes (consented SMS only).
  * build_worklist(): missed follow-ups, ordered ONLY by clinician-confirmed information and
    time - (1) escalation level E1 > E2 > E3, (2) within a level, verified items before
    possible returns, (3) most overdue first. No predicted risk, diagnosis or demographics.
  * Unconfirmed drafts older than a day are surfaced so no record is silently forgotten (F12).

v2 fixes: E1 enters the list as soon as its window ends (F19); a same-ID visit closes a
record only if it is in the right department and not too early (F13); possible returns are
sorted within their level (judge M7); every unassigned call is reported (F22).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import List, Optional

from .audit import AuditLog
from .messages import display_dept, normalize_dept, sms_full, sms_minimal
from .models import ContactType, Escalation
from .workflow import FollowUpRecord

ESC_RANK = {Escalation.E1: 0, Escalation.E2: 1, Escalation.E3: 2}


@dataclass
class Visit:
    uhid: str
    visit_date: date
    department: str
    name: str = ""
    age: int = 0
    village: str = ""


@dataclass
class WorkItem:
    record_id: str
    escalation: Escalation
    days_overdue: int
    actions: List[str]
    message: Optional[str] = None
    possible_return: bool = False
    call_assigned: bool = False


@dataclass
class Worklist:
    day: date
    items: List[WorkItem] = field(default_factory=list)
    unconfirmed: List[str] = field(default_factory=list)
    e1_calls_unassigned: int = 0
    other_calls_unassigned: int = 0
    alerts: List[str] = field(default_factory=list)


def _norm_name(n: str) -> str:
    return " ".join(n.lower().split())


def match_returns(records: List[FollowUpRecord], visits: List[Visit], audit: AuditLog,
                  now: datetime | None = None) -> None:
    for r in records:
        if r.status != "CONFIRMED" or r.closed:
            continue
        same_id = [v for v in visits if v.uhid == r.patient.uhid and v.visit_date > r.visit_date]
        tol = max(2, (r.days_max or 0) // 5)
        good = [v for v in same_id if v.visit_date >= r.due_start - timedelta(days=tol)
                and normalize_dept(v.department) == normalize_dept(r.department)]
        if good:
            v = min(good, key=lambda x: x.visit_date)
            r.closed, r.closed_reason = True, f"RETURNED {v.visit_date.isoformat()}"
            audit.append(r.record_id, "CLOSED_RETURNED", "system", "system", {"visit": v.visit_date.isoformat()}, now)
            continue
        if same_id and "SAME_ID_VISIT_CHECK" not in r.notes:
            r.notes.append("SAME_ID_VISIT_CHECK")   # other department or too early: a person checks, nothing closes
        look_alike = [v for v in visits if v.uhid != r.patient.uhid and v.visit_date > r.visit_date
                      and _norm_name(v.name) == _norm_name(r.patient.name)
                      and abs(v.age - r.patient.age) <= 1 and v.village.lower() == r.patient.village.lower()]
        if look_alike and "POSSIBLE_RETURN_MATCH" not in r.notes:
            r.notes.append("POSSIBLE_RETURN_MATCH")


def _call_due(r: FollowUpRecord, days_since_missed: int) -> bool:
    return r.escalation == Escalation.E1 or (r.escalation == Escalation.E2 and days_since_missed >= 7)


def _actions(r: FollowUpRecord, today: date):
    p = r.patient
    since_missed = (today - r.missed_after).days
    private = display_dept(r.department) is not None
    if p.contact_type == ContactType.NONE or not p.phone:
        return (["CHW_LINE_LIST"] if p.chw_consent else ["FLAG_AT_NEXT_CONTACT"]), None
    actions, msg = [], None
    if p.contact_type == ContactType.SHARED:
        if p.sms_consent:
            actions.append("SMS_MINIMAL")
            msg = sms_minimal(r.window_end, p.uhid, overdue=True)
        if _call_due(r, since_missed) and p.call_consent:
            actions.append("CALL_SHARED_SCRIPT")
    else:
        if p.sms_consent:
            actions.append("SMS")
            msg = (sms_full(p.name, r.department, r.window_end, r.prerequisites, p.uhid, overdue=True)
                   if private else sms_minimal(r.window_end, p.uhid, overdue=True))
        if (_call_due(r, since_missed) or not p.sms_consent) and p.call_consent:
            actions.append("CALL")
    if not actions:
        actions = ["CHW_LINE_LIST"] if p.chw_consent else ["FLAG_AT_NEXT_CONTACT"]
    return actions, msg


def pre_due_reminders(records: List[FollowUpRecord], today: date, days_before: int = 2):
    out = []
    for r in records:
        if r.status != "CONFIRMED" or r.closed or not r.patient.sms_consent or not r.patient.phone \
                or r.patient.contact_type == ContactType.NONE:
            continue
        if (r.window_end - r.visit_date).days > days_before and r.window_end - timedelta(days=days_before) == today:
            p = r.patient
            if p.contact_type == ContactType.SHARED or display_dept(r.department) is None:
                out.append((r.record_id, sms_minimal(r.window_end, p.uhid, overdue=False)))
            else:
                out.append((r.record_id, sms_full(p.name, r.department, r.window_end, r.prerequisites, p.uhid,
                                                  overdue=False)))
    return out


def build_worklist(records: List[FollowUpRecord], today: date, call_capacity: int,
                   unconfirmed_after_days: int = 1) -> Worklist:
    wl = Worklist(day=today)
    for r in records:
        if r.status == "NEEDS_CONFIRMATION" and (today - r.visit_date).days >= unconfirmed_after_days:
            wl.unconfirmed.append(r.record_id)
            continue
        if r.status != "CONFIRMED" or r.closed or r.missed_after is None or today <= r.missed_after:
            continue
        actions, msg = _actions(r, today)
        possible = bool({"POSSIBLE_RETURN_MATCH", "SAME_ID_VISIT_CHECK"} & set(r.notes))
        wl.items.append(WorkItem(r.record_id, r.escalation, (today - r.window_end).days, actions, msg, possible))
    wl.items.sort(key=lambda i: (ESC_RANK[i.escalation], i.possible_return, -i.days_overdue))
    used = 0
    for it in wl.items:
        if any(a.startswith("CALL") for a in it.actions):
            if used < call_capacity:
                it.call_assigned, used = True, used + 1
            elif it.escalation == Escalation.E1:
                wl.e1_calls_unassigned += 1
            else:
                wl.other_calls_unassigned += 1
    if wl.e1_calls_unassigned:
        wl.alerts.append(f"CAPACITY: {wl.e1_calls_unassigned} E1 calls could not be assigned today "
                         f"(capacity {call_capacity}). Escalate to the records supervisor.")
    if wl.other_calls_unassigned:
        wl.alerts.append(f"CAPACITY: {wl.other_calls_unassigned} E2/E3 calls carried to tomorrow.")
    if wl.unconfirmed:
        wl.alerts.append(f"UNCONFIRMED: {len(wl.unconfirmed)} follow-up drafts still unconfirmed after "
                         f"{unconfirmed_after_days} day(s). Send to the OPD in-charge.")
    return wl
