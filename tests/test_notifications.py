from datetime import UTC, datetime
from pathlib import Path

from vut_studis.models import ChangeKind, ChangeNotification, RecentChanges, StudisChange
from vut_studis.notifications import plan_change_notifications, send_macos_notification


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


def test_send_macos_notification_prefers_native_helper(monkeypatch) -> None:
    commands: list[list[str]] = []
    notification = _notification()

    monkeypatch.setenv("VUT_ENABLE_DESKTOP_NOTIFICATIONS", "1")
    monkeypatch.setattr(
        "vut_studis.notifications._native_notifier_app_path",
        lambda: Path("/Applications/VUT Studis Notifier.app"),
    )
    monkeypatch.setattr(
        "vut_studis.notifications.subprocess.run",
        lambda command, check: commands.append(command),
    )

    send_macos_notification(notification)

    assert commands[0] == [
        "open",
        "-W",
        "-n",
        "/Applications/VUT Studis Notifier.app",
        "--args",
        "--title",
        "VUT Studis",
        "--subtitle",
        "FLP points changed",
        "--message",
        "points: 15.9 -> 16.75",
        "--id",
        "grade:test",
    ]


def test_send_macos_notification_falls_back_to_terminal_notifier(monkeypatch) -> None:
    commands: list[list[str]] = []
    notification = _notification()

    monkeypatch.setenv("VUT_ENABLE_DESKTOP_NOTIFICATIONS", "1")
    monkeypatch.setattr("vut_studis.notifications._native_notifier_app_path", lambda: None)
    monkeypatch.setattr("vut_studis.notifications.shutil.which", lambda name: "/bin/notifier")
    monkeypatch.setattr(
        "vut_studis.notifications.subprocess.run",
        lambda command, check: commands.append(command),
    )

    send_macos_notification(notification)

    assert commands
    assert commands[0][:7] == [
        "/bin/notifier",
        "-title",
        "VUT Studis",
        "-subtitle",
        "FLP points changed",
        "-message",
        "points: 15.9 -> 16.75",
    ]


def test_send_macos_notification_falls_back_to_osascript(monkeypatch) -> None:
    commands: list[list[str]] = []
    notification = _notification()

    monkeypatch.setenv("VUT_ENABLE_DESKTOP_NOTIFICATIONS", "1")
    monkeypatch.setattr("vut_studis.notifications._native_notifier_app_path", lambda: None)
    monkeypatch.setattr("vut_studis.notifications.shutil.which", lambda name: None)
    monkeypatch.setattr(
        "vut_studis.notifications.subprocess.run",
        lambda command, check: commands.append(command),
    )

    send_macos_notification(notification)

    assert commands[0][0] == "osascript"
    assert 'with title "VUT Studis" subtitle "FLP points changed"' in commands[0][2]


def test_send_macos_notification_is_disabled_by_default(monkeypatch) -> None:
    commands: list[list[str]] = []

    monkeypatch.delenv("VUT_ENABLE_DESKTOP_NOTIFICATIONS", raising=False)
    monkeypatch.setattr(
        "vut_studis.notifications.subprocess.run",
        lambda command, check: commands.append(command),
    )

    send_macos_notification(_notification())

    assert commands == []


def _notification() -> ChangeNotification:
    return ChangeNotification(
        id="grade:test",
        title="VUT: FLP points changed",
        body="points: 15.9 -> 16.75",
        course_code="FLP",
        resource_type="grade",
        resource_id="2025/26:L:FLP",
        change_kind=ChangeKind.UPDATED,
        detected_at=datetime(2026, 5, 27, 12, 0, tzinfo=UTC),
    )
