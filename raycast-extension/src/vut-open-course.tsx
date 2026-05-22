import {
  Action,
  ActionPanel,
  Color,
  Icon,
  List,
  Toast,
  showToast,
} from "@raycast/api";
import { useEffect, useState } from "react";
import { runStudisPython } from "./studis";

type Course = {
  code: string;
  name: string;
  academic_year?: string;
  semester?: string;
  credits?: number;
  completion?: string;
  absolved?: boolean;
  detail_url?: string;
};

const PYTHON = String.raw`
import asyncio
import json
from urllib.parse import urljoin

from vut_studis.aggregates import courses_from_grades
from vut_studis.client import ELECTRONIC_INDEX_PATH, StudisClient, _find_course_detail_path

async def main():
    client = StudisClient()
    grades = await client.get_grades()
    courses = courses_from_grades(grades)
    html = await client._get_html(ELECTRONIC_INDEX_PATH)
    payload = []
    for course in courses:
        detail_url = None
        try:
            detail_url = urljoin(str(client.settings.base_url), _find_course_detail_path(html, course.code))
        except Exception:
            detail_url = None
        data = course.model_dump(mode="json")
        data["detail_url"] = detail_url
        payload.append(data)
    print(json.dumps(payload, ensure_ascii=False))

asyncio.run(main())
`;

export default function Command() {
  const [state, setState] = useState<{
    isLoading: boolean;
    courses: Course[];
    error?: string;
  }>({ isLoading: true, courses: [] });

  async function loadCourses() {
    setState((previous) => ({
      ...previous,
      isLoading: true,
      error: undefined,
    }));

    try {
      const courses = await runStudisPython<Course[]>(PYTHON);
      setState({ isLoading: false, courses: sortCourses(courses) });
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      setState({ isLoading: false, courses: [], error: message });
      await showToast({
        style: Toast.Style.Failure,
        title: "Could not load VUT courses",
        message,
      });
    }
  }

  useEffect(() => {
    void loadCourses();
  }, []);

  if (state.error) {
    return (
      <List isLoading={state.isLoading}>
        <List.EmptyView
          icon={Icon.Warning}
          title="Could not load VUT Courses"
          description={state.error}
          actions={
            <ActionPanel>
              <Action
                title="Retry"
                icon={Icon.ArrowClockwise}
                onAction={loadCourses}
              />
            </ActionPanel>
          }
        />
      </List>
    );
  }

  return (
    <List
      isLoading={state.isLoading}
      searchBarPlaceholder="Search by course code, name, semester, or completion..."
      navigationTitle="VUT Open Course"
    >
      <List.EmptyView
        icon={Icon.Book}
        title="No Courses Found"
        actions={
          <ActionPanel>
            <Action
              title="Refresh"
              icon={Icon.ArrowClockwise}
              onAction={loadCourses}
            />
          </ActionPanel>
        }
      />
      {courseSections(state.courses).map((section) => (
        <List.Section
          key={section.title}
          title={`${section.title} (${section.courses.length})`}
        >
          {section.courses.map((course) => (
            <CourseItem
              key={courseKey(course)}
              course={course}
              onRefresh={loadCourses}
            />
          ))}
        </List.Section>
      ))}
    </List>
  );
}

function CourseItem({
  course,
  onRefresh,
}: {
  course: Course;
  onRefresh: () => void;
}) {
  const subtitle = [
    course.name,
    completionLabel(course.completion),
    course.semester,
  ]
    .filter(Boolean)
    .join(" · ");

  return (
    <List.Item
      icon={{
        source: course.absolved ? Icon.CheckCircle : Icon.Book,
        tintColor: course.absolved ? Color.Green : Color.Blue,
      }}
      title={course.code}
      subtitle={subtitle}
      accessories={[
        { text: course.absolved ? "Completed" : "Active" },
        { text: creditsText(course.credits) },
      ].filter((accessory) => accessory.text !== "")}
      keywords={[
        course.code,
        course.name,
        course.semester ?? "",
        course.academic_year ?? "",
        course.completion ?? "",
      ]}
      actions={
        <ActionPanel>
          <ActionPanel.Section>
            {course.detail_url ? (
              <Action.OpenInBrowser
                title="Open in Studis"
                url={course.detail_url}
              />
            ) : null}
            <Action.CopyToClipboard
              title="Copy Course Code"
              content={course.code}
            />
            <Action.CopyToClipboard
              title="Copy Course Summary"
              content={copySummary(course)}
            />
          </ActionPanel.Section>
          <ActionPanel.Section>
            <Action
              title="Refresh"
              icon={Icon.ArrowClockwise}
              onAction={onRefresh}
            />
          </ActionPanel.Section>
        </ActionPanel>
      }
    />
  );
}

function sortCourses(courses: Course[]): Course[] {
  return [...courses].sort((left, right) => {
    const leftDone = left.absolved ? 1 : 0;
    const rightDone = right.absolved ? 1 : 0;
    if (leftDone !== rightDone) {
      return leftDone - rightDone;
    }
    return left.code.localeCompare(right.code, "cs");
  });
}

function courseSections(courses: Course[]) {
  const active = courses.filter((course) => !course.absolved);
  const completed = courses.filter((course) => course.absolved);
  return [
    { title: "Active", courses: active },
    { title: "Completed", courses: completed },
  ].filter((section) => section.courses.length > 0);
}

function courseKey(course: Course): string {
  return [
    course.academic_year ?? "",
    course.semester ?? "",
    course.code,
    course.name,
  ].join(":");
}

function creditsText(credits: number | undefined): string {
  if (credits === undefined || credits === null) {
    return "";
  }
  return `${new Intl.NumberFormat("cs-CZ", { maximumFractionDigits: 2 }).format(credits)} cr`;
}

function completionLabel(completion: string | undefined): string {
  if (!completion) {
    return "";
  }
  return completion.replaceAll("_", " ");
}

function copySummary(course: Course): string {
  return [
    `${course.code}: ${course.name}`,
    course.semester ? `Semester: ${course.semester}` : undefined,
    course.completion
      ? `Completion: ${completionLabel(course.completion)}`
      : undefined,
    course.credits !== undefined && course.credits !== null
      ? `Credits: ${creditsText(course.credits)}`
      : undefined,
    `Status: ${course.absolved ? "completed" : "active"}`,
    course.detail_url ? `Link: ${course.detail_url}` : undefined,
  ]
    .filter(Boolean)
    .join("\n");
}
