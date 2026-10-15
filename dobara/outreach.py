"""Outreach outcome logging. Every contact attempt ends with a coded outcome, so the hospital
learns WHY patients do not return (transport, cost, felt better, went elsewhere), not only
that they did not. Staff never give clinical advice.

v2 fixes: WRONG_NUMBER stops all messages to that number until registration updates it (F15);
OPTED_OUT stops messages and calls but does NOT close the clinical follow-up (F20).
"""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from .audit import AuditLog
from .messages import call_script_symptoms
from .models import ContactType
from .workflow import FollowUpRecord

OUTCOMES = {
    "WILL_COME", "NOT_REACHED", "WRONG_NUMBER", "OPTED_OUT",
    "CANNOT_COME_TRANSPORT", "CANNOT_COME_COST", "CANNOT_COME_WORK_OR_CARE", "FELT_BETTER",
    "TREATED_ELSEWHERE", "ADMITTED", "DECEASED", "MOVED_AWAY", "NEW_OR_WORSE_SYMPTOMS",
}
CLOSING = {"TREATED_ELSEWHERE", "ADMITTED", "DECEASED", "MOVED_AWAY"}
CLINICIAN_TASKS: List[dict] = []


def log_outcome(rec: FollowUpRecord, code: str, staff_id: str, audit: AuditLog,
                note: Optional[str] = None, now: datetime | None = None) -> dict:
    if code not in OUTCOMES:
        raise ValueError(f"Unknown outcome code {code}")
    result = {"record_id": rec.record_id, "code": code}
    if code == "NEW_OR_WORSE_SYMPTOMS":
        task = {"record_id": rec.record_id, "type": "TRANSFER_TO_DUTY_DOCTOR_NOW", "for": "DUTY_DOCTOR", "treating_clinician": rec.clinician_id,
                "script_followed": call_script_symptoms()}
        CLINICIAN_TASKS.append(task)
        result["clinician_task"] = task
    if code == "WRONG_NUMBER":
        rec.patient.contact_type, rec.patient.phone = ContactType.NONE, None
        rec.notes.append("CONTACT_INVALID: registration to update; CHW route if consented")
    if code == "OPTED_OUT":
        rec.patient.sms_consent = rec.patient.call_consent = False
        rec.notes.append("OPTED_OUT_OF_MESSAGES: follow-up stays open; flag at next contact")
    if code in CLOSING:
        rec.closed, rec.closed_reason = True, code
    audit.append(rec.record_id, "OUTREACH_OUTCOME", staff_id, "records_staff", {"code": code, "note": note}, now)
    return result
