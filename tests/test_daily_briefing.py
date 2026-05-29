from datetime import UTC, datetime, timedelta

from vut_studis.assistant import (
    briefing_item_id_for_action,
    briefing_item_id_for_change,
    build_daily_briefing,
)
from vut_studis.cache import StoredCourseNote
from vut_studis.models import (
    BriefingItemType,
    ChangeKind,
    ChangeNotification,
    PendingAction,
    PendingActionKind,
    PendingActionSeverity,
    PendingActionType,
)


def test_build_daily_briefing_hides_dismissed_actions_and_keeps_notes() -> None:
    now = datetime(2026, 5, 29, 8, 0, tzinfo=UTC)
    action = _pending_action(now)
    dismissed_action = _pending_action(now, course_code="SUR")
    dismissed_id = briefing_item_id_for_action(dismissed_action)

    briefing = build_daily_briefing(
        pending_actions=[action, dismissed_action],
        change_notifications=[
            ChangeNotification(
                id="grade:abc",
                title="VUT: ABC points changed",
                body="points: 10 -> 12",
                course_code="ABC",
                resource_type="grade",
                resource_id="ABC",
                change_kind=ChangeKind.UPDATED,
                detected_at=now,
            )
        ],
        course_notes=[
            StoredCourseNote(
                note_id="note-1",
                course_code="ABC",
                body="Remember project upload.",
                created_at=now,
                updated_at=now,
            )
        ],
        dismissed_action_ids={dismissed_id},
        horizon_days=7,
        generated_at=now,
    )

    assert briefing.dismissed_count == 1
    assert briefing.warning_count == 1
    assert briefing.info_count == 1
    assert [item.type for item in briefing.items] == [
        BriefingItemType.PENDING_ACTION,
        BriefingItemType.CHANGE,
    ]
    assert briefing.course_notes[0].body == "Remember project upload."


def test_build_daily_briefing_can_hide_dismissed_changes() -> None:
    now = datetime(2026, 5, 29, 8, 0, tzinfo=UTC)
    notification = ChangeNotification(
        id="grade:abc",
        title="VUT: ABC points changed",
        body="points: 10 -> 12",
        course_code="ABC",
        resource_type="grade",
        resource_id="ABC",
        change_kind=ChangeKind.UPDATED,
        detected_at=now,
    )

    briefing = build_daily_briefing(
        pending_actions=[],
        change_notifications=[notification],
        course_notes=[],
        dismissed_action_ids={briefing_item_id_for_change(notification)},
        horizon_days=7,
        generated_at=now,
    )

    assert briefing.items == []
    assert briefing.dismissed_count == 1


def test_briefing_item_id_for_action_is_stable() -> None:
    now = datetime(2026, 5, 29, 8, 0, tzinfo=UTC)

    assert briefing_item_id_for_action(_pending_action(now)) == briefing_item_id_for_action(
        _pending_action(now)
    )


def _pending_action(
    now: datetime,
    *,
    course_code: str = "ABC",
) -> PendingAction:
    return PendingAction(
        type=PendingActionType.UNREGISTERED_TERM,
        severity=PendingActionSeverity.WARNING,
        action_kind=PendingActionKind.REGISTER,
        course_code=course_code,
        title="Exam: 2nd term",
        reason="You are not registered.",
        suggested_next_step="Register or choose another term.",
        due_at=now + timedelta(days=2),
        starts_at=now + timedelta(days=2),
        days_left=2,
        detail_url=f"https://example.test/{course_code}",
    )
