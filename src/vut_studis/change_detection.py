import json
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime

from pydantic import BaseModel

from vut_studis.cache import CacheStore, StateSnapshot
from vut_studis.models import ChangeKind, RecentChanges, StudisChange


@dataclass(frozen=True)
class ChangeResource:
    resource_type: str
    resource_id: str
    title: str
    payload_json: str
    course_code: str | None = None

    @property
    def payload(self) -> dict[str, object]:
        payload = json.loads(self.payload_json)
        if not isinstance(payload, dict):
            raise ValueError("Change resource payload must be a JSON object.")
        return payload


def model_change_resource(
    *,
    resource_type: str,
    resource_id: str,
    title: str,
    model: BaseModel,
    course_code: str | None = None,
) -> ChangeResource:
    payload = model.model_dump(mode="json", exclude_none=True)
    return ChangeResource(
        resource_type=resource_type,
        resource_id=resource_id,
        title=title,
        course_code=course_code,
        payload_json=json.dumps(payload, ensure_ascii=False, sort_keys=True),
    )


def detect_and_record_changes(
    *,
    cache: CacheStore,
    scope: str,
    resources: Iterable[ChangeResource],
    resource_types: Iterable[str] | None = None,
    captured_at: datetime | None = None,
) -> RecentChanges:
    captured_at = captured_at or datetime.now(UTC)
    by_type = _group_resources(resources)
    types_to_compare = sorted(set(by_type) | set(resource_types or ()))
    baseline_created = True
    changes: list[StudisChange] = []

    for resource_type in types_to_compare:
        current = by_type.get(resource_type, {})
        previous = cache.get_latest_state_snapshots(scope=scope, resource_type=resource_type)
        active_previous = {
            resource_id: snapshot
            for resource_id, snapshot in previous.items()
            if not snapshot.is_deleted
        }
        if previous:
            baseline_created = False

        for resource_id, resource in current.items():
            snapshot = active_previous.get(resource_id)
            if snapshot is None:
                if previous:
                    changes.append(
                        _change(
                            kind=ChangeKind.ADDED,
                            resource=resource,
                            before=None,
                            after=resource.payload,
                            captured_at=captured_at,
                        )
                    )
                cache.record_state_snapshot(
                    scope=scope,
                    resource_type=resource.resource_type,
                    resource_id=resource.resource_id,
                    payload_json=resource.payload_json,
                    captured_at=captured_at,
                )
                continue

            if snapshot.payload_json is not None and snapshot.payload_json != resource.payload_json:
                before = _snapshot_payload(snapshot)
                after = resource.payload
                changes.append(
                    _change(
                        kind=ChangeKind.UPDATED,
                        resource=resource,
                        before=before,
                        after=after,
                        captured_at=captured_at,
                    )
                )
                cache.record_state_snapshot(
                    scope=scope,
                    resource_type=resource.resource_type,
                    resource_id=resource.resource_id,
                    payload_json=resource.payload_json,
                    captured_at=captured_at,
                )

        for resource_id, snapshot in active_previous.items():
            if resource_id in current:
                continue

            before = _snapshot_payload(snapshot)
            changes.append(
                StudisChange(
                    kind=ChangeKind.REMOVED,
                    resource_type=resource_type,
                    resource_id=resource_id,
                    title=str(before.get("title") or before.get("name") or resource_id),
                    course_code=_optional_str(before.get("course_code") or before.get("code")),
                    changed_fields=[],
                    before=before,
                    after=None,
                    detected_at=captured_at,
                )
            )
            cache.record_state_snapshot(
                scope=scope,
                resource_type=resource_type,
                resource_id=resource_id,
                payload_json=None,
                captured_at=captured_at,
                is_deleted=True,
            )

    return RecentChanges(
        baseline_created=baseline_created,
        captured_at=captured_at,
        changes=sorted(changes, key=_change_sort_key),
    )


def _group_resources(
    resources: Iterable[ChangeResource],
) -> dict[str, dict[str, ChangeResource]]:
    grouped: dict[str, dict[str, ChangeResource]] = {}
    for resource in resources:
        grouped.setdefault(resource.resource_type, {})[resource.resource_id] = resource
    return grouped


def _change(
    *,
    kind: ChangeKind,
    resource: ChangeResource,
    before: dict[str, object] | None,
    after: dict[str, object] | None,
    captured_at: datetime,
) -> StudisChange:
    return StudisChange(
        kind=kind,
        resource_type=resource.resource_type,
        resource_id=resource.resource_id,
        title=resource.title,
        course_code=resource.course_code,
        changed_fields=_changed_fields(before, after),
        before=before,
        after=after,
        detected_at=captured_at,
    )


def _changed_fields(
    before: dict[str, object] | None,
    after: dict[str, object] | None,
) -> list[str]:
    if before is None or after is None:
        return []

    keys = set(before) | set(after)
    return sorted(key for key in keys if before.get(key) != after.get(key))


def _snapshot_payload(snapshot: StateSnapshot) -> dict[str, object]:
    if snapshot.payload_json is None:
        return {}
    payload = json.loads(snapshot.payload_json)
    if not isinstance(payload, dict):
        return {}
    return payload


def _optional_str(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _change_sort_key(change: StudisChange) -> tuple[str, str, str]:
    return change.resource_type, change.course_code or "", change.title
