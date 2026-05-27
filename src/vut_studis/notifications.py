import json
import subprocess
from hashlib import sha256
from typing import Literal

from vut_studis.models import ChangeKind, ChangeNotification, RecentChanges, StudisChange

NotificationMode = Literal["fast", "deep"]

IMPORTANT_GRADE_FIELDS = {
    "points",
    "grade",
    "credit_awarded",
    "credit_awarded_on",
    "grade_awarded_on",
    "absolved",
}
IMPORTANT_COURSE_FIELDS = {"absolved", "completion", "credits"}


def include_pending_actions_for_mode(mode: NotificationMode) -> bool:
    return mode == "deep"


def plan_change_notifications(
    changes: RecentChanges,
    *,
    private: bool = False,
) -> list[ChangeNotification]:
    notifications: list[ChangeNotification] = []
    for change in changes.changes:
        if not _is_notifiable(change):
            continue

        notifications.append(
            ChangeNotification(
                id=_notification_id(change),
                title=_title(change),
                body=_private_body(change) if private else _body(change),
                course_code=change.course_code,
                resource_type=change.resource_type,
                resource_id=change.resource_id,
                change_kind=change.kind,
                detected_at=change.detected_at,
            )
        )

    return notifications


def send_macos_notification(notification: ChangeNotification) -> None:
    subprocess.run(
        [
            "osascript",
            "-e",
            (
                "display notification "
                f"{_applescript_string(notification.body)} "
                f"with title {_applescript_string(notification.title)}"
            ),
        ],
        check=True,
    )


def _is_notifiable(change: StudisChange) -> bool:
    if change.resource_type == "grade":
        return (
            change.kind in {ChangeKind.ADDED, ChangeKind.REMOVED}
            or bool(set(change.changed_fields) & IMPORTANT_GRADE_FIELDS)
        )

    if change.resource_type == "course":
        return (
            change.kind in {ChangeKind.ADDED, ChangeKind.REMOVED}
            or bool(set(change.changed_fields) & IMPORTANT_COURSE_FIELDS)
        )

    if change.resource_type == "pending_action":
        return change.kind in {ChangeKind.ADDED, ChangeKind.UPDATED}

    return False


def _notification_id(change: StudisChange) -> str:
    payload = {
        "kind": change.kind,
        "resource_type": change.resource_type,
        "resource_id": change.resource_id,
        "changed_fields": change.changed_fields,
        "before": change.before,
        "after": change.after,
    }
    digest = sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()
    return f"{change.resource_type}:{digest[:20]}"


def _title(change: StudisChange) -> str:
    course = change.course_code or change.title
    if change.resource_type == "grade":
        if change.kind == ChangeKind.ADDED:
            return f"VUT: new grade record in {course}"
        if change.kind == ChangeKind.REMOVED:
            return f"VUT: grade record removed in {course}"
        if "points" in change.changed_fields:
            return f"VUT: {course} points changed"
        if "grade" in change.changed_fields:
            return f"VUT: {course} grade changed"
        return f"VUT: {course} grade updated"

    if change.resource_type == "pending_action":
        return f"VUT: {course} action changed"

    return f"VUT: {course} changed"


def _body(change: StudisChange) -> str:
    if change.kind == ChangeKind.ADDED:
        return _added_body(change)
    if change.kind == ChangeKind.REMOVED:
        return "The item is no longer present in Studis."

    details = [
        _field_change("points", change),
        _field_change("grade", change),
        _field_change("credit_awarded", change),
        _field_change("absolved", change),
        _field_change("completion", change),
    ]
    body = "; ".join(detail for detail in details if detail)
    if body:
        return body

    fields = ", ".join(change.changed_fields)
    return f"Changed fields: {fields}" if fields else "Studis item changed."


def _private_body(change: StudisChange) -> str:
    course = change.course_code or change.resource_type.replace("_", " ")
    return f"{course}: open VUT Changes for details."


def _added_body(change: StudisChange) -> str:
    after = change.after or {}
    details = [
        _value_pair("points", after.get("points")),
        _value_pair("grade", after.get("grade")),
        _value_pair("reason", after.get("reason")),
    ]
    body = "; ".join(detail for detail in details if detail)
    return body or "New item detected in Studis."


def _field_change(field: str, change: StudisChange) -> str | None:
    before = change.before or {}
    after = change.after or {}
    if field not in before and field not in after:
        return None
    if before.get(field) == after.get(field):
        return None
    before_value = _format_value(before.get(field))
    after_value = _format_value(after.get(field))
    return f"{field.replace('_', ' ')}: {before_value} -> {after_value}"


def _value_pair(label: str, value: object) -> str | None:
    if value is None or value == "":
        return None
    return f"{label.replace('_', ' ')}: {_format_value(value)}"


def _format_value(value: object) -> str:
    if value is True:
        return "yes"
    if value is False:
        return "no"
    if value is None:
        return "none"
    return str(value)


def _applescript_string(value: str) -> str:
    return json.dumps(value)
