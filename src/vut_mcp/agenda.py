"""Pure conversion and composition of the read-only cross-source agenda."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from hashlib import sha256

from vut_mcp.models import Agenda, AgendaItem, AgendaSource
from vut_moodle import MoodleAssignment
from vut_studis import PendingAction, PendingActionSeverity

MAX_AGENDA_ITEMS = 250


def build_agenda(
    pending_actions: Sequence[PendingAction],
    moodle_assignments: Sequence[MoodleAssignment],
    *,
    horizon_days: int,
    now: datetime | None = None,
) -> Agenda:
    """Compose a deterministic agenda without mutating either source collection."""
    if isinstance(horizon_days, bool) or not isinstance(horizon_days, int) or horizon_days < 1:
        raise ValueError("horizon_days must be at least 1")

    generated_at = _as_utc(now or datetime.now(UTC))
    horizon_ends_at = generated_at + timedelta(days=horizon_days)
    candidates = [
        *_studis_items(pending_actions),
        *_moodle_items(moodle_assignments),
    ]
    horizon_items = [
        item
        for item in candidates
        if generated_at <= _relevant_at(item) <= horizon_ends_at
    ]
    unique_items = _deduplicate_sorted(horizon_items)
    studis_count = sum(item.source is AgendaSource.STUDIS for item in unique_items)
    moodle_count = sum(item.source is AgendaSource.MOODLE for item in unique_items)
    items = unique_items[:MAX_AGENDA_ITEMS]

    return Agenda(
        generated_at=generated_at,
        horizon_days=horizon_days,
        items=items,
        studis_count=studis_count,
        moodle_count=moodle_count,
        truncated_count=len(unique_items) - len(items),
    )


def _studis_items(actions: Sequence[PendingAction]) -> list[AgendaItem]:
    items: list[AgendaItem] = []
    for action in actions:
        if action.detail_url is None or (action.due_at is None and action.starts_at is None):
            continue
        items.append(
            AgendaItem(
                id=_stable_id(
                    AgendaSource.STUDIS,
                    action.type.value,
                    action.course_code,
                    action.detail_url,
                ),
                source=AgendaSource.STUDIS,
                title=action.title,
                course_name=action.course_name,
                due_at=_as_utc_or_none(action.due_at),
                starts_at=_as_utc_or_none(action.starts_at),
                severity=action.severity,
                status="action_required",
                url=action.detail_url,
                detail=action.detail,
            )
        )
    return items


def _moodle_items(assignments: Sequence[MoodleAssignment]) -> list[AgendaItem]:
    items: list[AgendaItem] = []
    for assignment in assignments:
        if assignment.due_at is None:
            continue
        items.append(
            AgendaItem(
                id=_stable_id(
                    AgendaSource.MOODLE,
                    str(assignment.id),
                    str(assignment.course_id),
                    assignment.url,
                ),
                source=AgendaSource.MOODLE,
                title=assignment.name,
                course_name=assignment.course_name,
                due_at=_as_utc(assignment.due_at),
                status=assignment.submission_status,
                url=assignment.url,
            )
        )
    return items


def _deduplicate_sorted(items: Sequence[AgendaItem]) -> list[AgendaItem]:
    unique_items: list[AgendaItem] = []
    seen_ids: set[str] = set()
    for item in sorted(items, key=_agenda_item_sort_key):
        if item.id not in seen_ids:
            seen_ids.add(item.id)
            unique_items.append(item)
    return unique_items


def _agenda_item_sort_key(item: AgendaItem) -> tuple[datetime, int, str, str, str]:
    severity_priority = {
        PendingActionSeverity.CRITICAL: 0,
        PendingActionSeverity.WARNING: 1,
        PendingActionSeverity.INFO: 2,
        None: 3,
    }[item.severity]
    return (
        _relevant_at(item) or datetime.max.replace(tzinfo=UTC),
        severity_priority,
        item.source,
        item.title,
        item.id,
    )


def _relevant_at(item: AgendaItem) -> datetime | None:
    return item.due_at or item.starts_at


def _stable_id(source: AgendaSource, *identifiers: str) -> str:
    """Hash only source and stable remote metadata; never include fetched content."""
    material = "\x1f".join((source.value, *identifiers))
    return sha256(material.encode()).hexdigest()


def _as_utc_or_none(value: datetime | None) -> datetime | None:
    return _as_utc(value) if value is not None else None


def _as_utc(value: datetime) -> datetime:
    """Treat legacy naive StudIS timestamps as UTC and normalize aware values."""
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
