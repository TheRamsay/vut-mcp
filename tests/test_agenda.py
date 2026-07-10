from datetime import UTC, datetime, timedelta, timezone

from vut_mcp.agenda import MAX_AGENDA_ITEMS, build_agenda
from vut_mcp.models import AgendaSource
from vut_moodle import MoodleAssignment
from vut_studis import (
    PendingAction,
    PendingActionKind,
    PendingActionSeverity,
    PendingActionType,
)

NOW = datetime(2026, 7, 10, 12, tzinfo=UTC)


def _action(
    *,
    title: str = "Register",
    due_at: datetime | None = None,
    starts_at: datetime | None = None,
    severity: PendingActionSeverity = PendingActionSeverity.WARNING,
    detail_url: str | None = "https://www.vut.cz/studis/action/1",
) -> PendingAction:
    return PendingAction(
        type=PendingActionType.OPEN_TERM_REGISTRATION,
        severity=severity,
        action_kind=PendingActionKind.REGISTER,
        course_code="ABC",
        course_name="Algorithms",
        title=title,
        reason="Registration is open.",
        suggested_next_step="Register.",
        detail="Term registration",
        due_at=due_at,
        starts_at=starts_at,
        detail_url=detail_url,
    )


def _assignment(
    *,
    id: int = 1,
    name: str = "Project",
    due_at: datetime | None = None,
    submission_status: str = "new",
) -> MoodleAssignment:
    return MoodleAssignment(
        id=id,
        course_id=42,
        course_name="Algorithms",
        name=name,
        url=f"https://moodle.vut.cz/mod/assign/view.php?id={id}",
        due_at=due_at,
        submission_status=submission_status,  # type: ignore[arg-type]
    )


def test_build_agenda_converts_sources_and_preserves_statuses() -> None:
    action = _action(due_at=NOW + timedelta(days=1))
    assignment = _assignment(
        due_at=NOW + timedelta(days=2), submission_status="submitted"
    )

    agenda = build_agenda([action], [assignment], horizon_days=14, now=NOW)

    assert agenda.generated_at == NOW
    assert agenda.studis_count == 1
    assert agenda.moodle_count == 1
    assert agenda.truncated_count == 0
    assert [(item.source, item.status, item.severity) for item in agenda.items] == [
        (AgendaSource.STUDIS, "action_required", PendingActionSeverity.WARNING),
        (AgendaSource.MOODLE, "submitted", None),
    ]
    assert agenda.items[0].id == build_agenda([action], [], horizon_days=14, now=NOW).items[0].id


def test_build_agenda_omits_undated_or_out_of_horizon_items() -> None:
    agenda = build_agenda(
        [
            _action(due_at=NOW - timedelta(days=1)),
            _action(due_at=NOW + timedelta(days=15)),
            _action(detail_url=None, due_at=NOW),
        ],
        [
            _assignment(id=1, due_at=NOW - timedelta(days=1)),
            _assignment(id=2),
            _assignment(id=3, due_at=NOW + timedelta(days=15)),
        ],
        horizon_days=14,
        now=NOW,
    )

    assert agenda.items == []
    assert agenda.studis_count == 0
    assert agenda.moodle_count == 0


def test_build_agenda_normalizes_times_and_sorts_by_time_severity_and_source() -> None:
    same_time = NOW + timedelta(days=1)
    agenda = build_agenda(
        [
            _action(title="Info", due_at=same_time, severity=PendingActionSeverity.INFO),
            _action(
                title="Critical",
                due_at=same_time,
                severity=PendingActionSeverity.CRITICAL,
                detail_url="https://www.vut.cz/studis/action/2",
            ),
        ],
        [
            _assignment(
                due_at=(same_time - timedelta(hours=2)).astimezone(timezone(timedelta(hours=2)))
            ),
            _assignment(id=2, due_at=same_time),
        ],
        horizon_days=14,
        now=NOW,
    )

    assert [item.title for item in agenda.items] == ["Project", "Critical", "Info", "Project"]
    assert agenda.items[0].due_at == same_time - timedelta(hours=2)
    assert agenda.items[0].due_at.tzinfo is UTC


def test_build_agenda_deduplicates_by_stable_id_without_mutating_inputs() -> None:
    action = _action(due_at=NOW + timedelta(days=1))
    assignment = _assignment(due_at=NOW + timedelta(days=1))

    agenda = build_agenda([action, action], [assignment, assignment], horizon_days=14, now=NOW)

    assert len(agenda.items) == 2
    assert action.due_at == NOW + timedelta(days=1)
    assert assignment.due_at == NOW + timedelta(days=1)


def test_build_agenda_caps_sorted_items_and_reports_truncation() -> None:
    assignments = [
        _assignment(id=index, due_at=NOW + timedelta(minutes=index))
        for index in range(MAX_AGENDA_ITEMS + 1)
    ]

    agenda = build_agenda([], assignments, horizon_days=14, now=NOW)

    assert len(agenda.items) == MAX_AGENDA_ITEMS
    assert agenda.moodle_count == MAX_AGENDA_ITEMS + 1
    assert agenda.truncated_count == 1
