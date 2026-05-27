from datetime import UTC, datetime

from vut_studis.models import ChangeKind, RecentChanges, StudisChange
from vut_studis.notifications import plan_change_notifications


def test_plan_change_notifications_formats_grade_points_change() -> None:
    captured_at = datetime(2026, 5, 27, 12, 0, tzinfo=UTC)
    changes = RecentChanges(
        baseline_created=False,
        captured_at=captured_at,
        changes=[
            StudisChange(
                kind=ChangeKind.UPDATED,
                resource_type="grade",
                resource_id="2025/26:L:ABC",
                title="ABC Test Course",
                course_code="ABC",
                changed_fields=["points"],
                before={"points": 10},
                after={"points": 12},
                detected_at=captured_at,
            )
        ],
    )

    notifications = plan_change_notifications(changes)

    assert len(notifications) == 1
    assert notifications[0].title == "VUT: ABC points changed"
    assert notifications[0].body == "points: 10 -> 12"
    assert notifications[0].id.startswith("grade:")


def test_plan_change_notifications_ignores_unimportant_grade_field() -> None:
    captured_at = datetime(2026, 5, 27, 12, 0, tzinfo=UTC)
    changes = RecentChanges(
        baseline_created=False,
        captured_at=captured_at,
        changes=[
            StudisChange(
                kind=ChangeKind.UPDATED,
                resource_type="grade",
                resource_id="2025/26:L:ABC",
                title="ABC Test Course",
                course_code="ABC",
                changed_fields=["course_name"],
                before={"course_name": "Old"},
                after={"course_name": "New"},
                detected_at=captured_at,
            )
        ],
    )

    assert plan_change_notifications(changes) == []
