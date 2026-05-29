import json
from collections import Counter
from datetime import UTC, datetime
from hashlib import sha256

from vut_studis.cache import StoredCourseNote
from vut_studis.models import (
    BriefingItem,
    BriefingItemType,
    ChangeNotification,
    CourseNote,
    DailyBriefing,
    PendingAction,
    PendingActionSeverity,
)


def build_daily_briefing(
    *,
    pending_actions: list[PendingAction],
    change_notifications: list[ChangeNotification],
    course_notes: list[StoredCourseNote],
    dismissed_action_ids: set[str],
    horizon_days: int,
    generated_at: datetime | None = None,
) -> DailyBriefing:
    generated_at = generated_at or datetime.now(UTC)
    pending_items = [
        _briefing_item_from_pending_action(action)
        for action in pending_actions
        if briefing_item_id_for_action(action) not in dismissed_action_ids
    ]
    change_items = [
        _briefing_item_from_change(notification)
        for notification in change_notifications
        if briefing_item_id_for_change(notification) not in dismissed_action_ids
    ]
    items = sorted([*pending_items, *change_items], key=_briefing_item_sort_key)
    severity_counts = Counter(item.severity for item in items)
    dismissed_count = len(pending_actions) + len(change_notifications) - len(items)

    return DailyBriefing(
        generated_at=generated_at,
        horizon_days=horizon_days,
        items=items,
        course_notes=[_course_note(note) for note in course_notes],
        dismissed_count=dismissed_count,
        critical_count=severity_counts[PendingActionSeverity.CRITICAL],
        warning_count=severity_counts[PendingActionSeverity.WARNING],
        info_count=severity_counts[PendingActionSeverity.INFO],
        summary=_summary(items, dismissed_count),
    )


def briefing_item_id_for_action(action: PendingAction) -> str:
    payload = {
        "type": action.type,
        "course_code": action.course_code,
        "title": action.title,
        "due_at": action.due_at,
        "starts_at": action.starts_at,
        "detail_url": action.detail_url,
    }
    digest = sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()
    return f"pending:{digest[:20]}"


def briefing_item_id_for_change(notification: ChangeNotification) -> str:
    return f"change:{notification.id}"


def _briefing_item_from_pending_action(action: PendingAction) -> BriefingItem:
    return BriefingItem(
        id=briefing_item_id_for_action(action),
        type=BriefingItemType.PENDING_ACTION,
        severity=action.severity,
        title=f"{action.course_code}: {action.title}",
        body=action.reason,
        course_code=action.course_code,
        action_kind=action.action_kind,
        suggested_next_step=action.suggested_next_step,
        due_at=action.due_at,
        starts_at=action.starts_at,
        days_left=action.days_left,
        detail_url=action.detail_url,
    )


def _briefing_item_from_change(notification: ChangeNotification) -> BriefingItem:
    return BriefingItem(
        id=briefing_item_id_for_change(notification),
        type=BriefingItemType.CHANGE,
        severity=PendingActionSeverity.INFO,
        title=notification.title,
        body=notification.body,
        course_code=notification.course_code,
        detail_url=None,
    )


def _course_note(note: StoredCourseNote) -> CourseNote:
    return CourseNote(
        id=note.note_id,
        course_code=note.course_code,
        body=note.body,
        created_at=note.created_at,
        updated_at=note.updated_at,
    )


def _briefing_item_sort_key(item: BriefingItem) -> tuple[int, datetime, str]:
    severity_priority = {
        PendingActionSeverity.CRITICAL: 0,
        PendingActionSeverity.WARNING: 1,
        PendingActionSeverity.INFO: 2,
    }[item.severity]
    relevant_at = item.due_at or item.starts_at or datetime.max
    return severity_priority, relevant_at, item.title


def _summary(items: list[BriefingItem], dismissed_count: int) -> list[str]:
    if not items:
        return ["No active VUT briefing items."]

    counts = Counter(item.severity for item in items)
    summary = [
        (
            f"{len(items)} active item(s): "
            f"{counts[PendingActionSeverity.CRITICAL]} critical, "
            f"{counts[PendingActionSeverity.WARNING]} warning, "
            f"{counts[PendingActionSeverity.INFO]} info."
        )
    ]
    if dismissed_count:
        summary.append(f"{dismissed_count} dismissed item(s) hidden.")
    return summary
