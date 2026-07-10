from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from vut_mcp.models import Agenda, AgendaItem, AgendaSource
from vut_studis import PendingActionSeverity


def test_agenda_models_are_immutable_and_json_serializable() -> None:
    item = AgendaItem(
        id="stable-id",
        source=AgendaSource.STUDIS,
        title="Register",
        severity=PendingActionSeverity.WARNING,
        status="action_required",
    )
    agenda = Agenda(
        generated_at=datetime(2026, 7, 10, tzinfo=UTC),
        horizon_days=14,
        items=[item],
        studis_count=1,
        moodle_count=0,
        truncated_count=0,
    )

    with pytest.raises(ValidationError):
        item.title = "Changed"  # type: ignore[misc]

    assert agenda.model_dump(mode="json") == {
        "generated_at": "2026-07-10T00:00:00Z",
        "horizon_days": 14,
        "items": [
            {
                "id": "stable-id",
                "source": "studis",
                "title": "Register",
                "course_name": None,
                "due_at": None,
                "starts_at": None,
                "severity": "warning",
                "status": "action_required",
                "url": None,
                "detail": None,
            }
        ],
        "studis_count": 1,
        "moodle_count": 0,
        "truncated_count": 0,
    }
