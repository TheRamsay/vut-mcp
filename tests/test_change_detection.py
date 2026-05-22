from datetime import UTC, datetime, timedelta

from vut_studis.cache import CacheStore
from vut_studis.change_detection import ChangeResource, detect_and_record_changes
from vut_studis.models import ChangeKind


def test_detect_and_record_changes_creates_baseline_then_reports_updates(tmp_path) -> None:
    cache = CacheStore(path=tmp_path / "cache.sqlite3")
    first_at = datetime(2026, 5, 22, 10, 0, tzinfo=UTC)
    second_at = first_at + timedelta(hours=1)

    baseline = detect_and_record_changes(
        cache=cache,
        scope="test-scope",
        resources=[
            ChangeResource(
                resource_type="grade",
                resource_id="ABC",
                title="ABC Test Course",
                course_code="ABC",
                payload_json='{"course_code":"ABC","points":10}',
            )
        ],
        captured_at=first_at,
    )

    assert baseline.baseline_created is True
    assert baseline.changes == []

    changes = detect_and_record_changes(
        cache=cache,
        scope="test-scope",
        resources=[
            ChangeResource(
                resource_type="grade",
                resource_id="ABC",
                title="ABC Test Course",
                course_code="ABC",
                payload_json='{"course_code":"ABC","points":12}',
            ),
            ChangeResource(
                resource_type="grade",
                resource_id="DEF",
                title="DEF Other Course",
                course_code="DEF",
                payload_json='{"course_code":"DEF","points":5}',
            ),
        ],
        captured_at=second_at,
    )

    assert changes.baseline_created is False
    assert [(change.kind, change.resource_id) for change in changes.changes] == [
        (ChangeKind.UPDATED, "ABC"),
        (ChangeKind.ADDED, "DEF"),
    ]
    assert changes.changes[0].changed_fields == ["points"]


def test_detect_and_record_changes_reports_removed_once(tmp_path) -> None:
    cache = CacheStore(path=tmp_path / "cache.sqlite3")
    captured_at = datetime(2026, 5, 22, 10, 0, tzinfo=UTC)
    resource = ChangeResource(
        resource_type="pending_action",
        resource_id="ABC:Project",
        title="ABC Project",
        course_code="ABC",
        payload_json='{"course_code":"ABC","title":"Project"}',
    )

    detect_and_record_changes(
        cache=cache,
        scope="test-scope",
        resources=[resource],
        captured_at=captured_at,
    )
    removed = detect_and_record_changes(
        cache=cache,
        scope="test-scope",
        resources=[],
        resource_types=["pending_action"],
        captured_at=captured_at + timedelta(hours=1),
    )
    removed_again = detect_and_record_changes(
        cache=cache,
        scope="test-scope",
        resources=[],
        resource_types=["pending_action"],
        captured_at=captured_at + timedelta(hours=2),
    )

    assert len(removed.changes) == 1
    assert removed.changes[0].kind == ChangeKind.REMOVED
    assert removed_again.changes == []
