import pytest

from vut_studis.aggregates import find_assessment_message_target
from vut_studis.errors import StudisParseError
from vut_studis.models import AssessmentEntry, AssessmentItem, CourseAssessment


def test_find_assessment_message_target_uses_requested_entry() -> None:
    item, entry, url = find_assessment_message_target(
        CourseAssessment(
            course_code="ABC",
            items=[
                AssessmentItem(
                    order=2,
                    name="Project",
                    entries=[
                        AssessmentEntry(order=1, name="First", message_url="https://first.test"),
                        AssessmentEntry(order=2, name="Second", message_url="https://second.test"),
                    ],
                )
            ],
        ),
        item_order=2,
        entry_order=2,
    )

    assert item.name == "Project"
    assert entry is not None
    assert entry.name == "Second"
    assert url == "https://second.test"


def test_find_assessment_message_target_requires_entry_when_ambiguous() -> None:
    with pytest.raises(StudisParseError, match="multiple entry messages"):
        find_assessment_message_target(
            CourseAssessment(
                course_code="ABC",
                items=[
                    AssessmentItem(
                        order=2,
                        name="Project",
                        entries=[
                            AssessmentEntry(
                                order=1,
                                name="First",
                                message_url="https://first.test",
                            ),
                            AssessmentEntry(
                                order=2,
                                name="Second",
                                message_url="https://second.test",
                            ),
                        ],
                    )
                ],
            ),
            item_order=2,
            entry_order=None,
        )
